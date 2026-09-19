"""Build a self-contained plotting notebook from Spectra Library state.

The point of this notebook is full control over the figure, so it
reproduces what the app currently draws and then gets out of the way:
the traces are written as explicit per-trace `ax.plot()` calls with
their colours and labels already resolved, so any line can be edited
directly instead of through a helper.

It installs nothing -- numpy/pandas/matplotlib are preinstalled on
Colab, the spectra are embedded, and the figure uses matplotlib's
default style rather than the app's -- only the resolved trace
colours/styles travel across, as literal values per `ax.plot()` call.

The input is a plain dict (see `PlotPayload` in the docstring of
`build`), not app objects, so this module stays Qt-free.
"""
from __future__ import annotations

from .notebook_export import (
    as_literal, code_cell, encode_text, markdown_cell, notebook,
)

# wrap_phase_for_plot is ~40 lines of pure numpy; the notebook needs the
# identical algorithm or phase traces break at different places than they
# do in the app. Inlined verbatim rather than approximated.
_PHASE_HELPER = '''
def wrap_phase_for_plot(y, wrap):
    """Fold phase into the chosen display window, breaking the line only
    where the continuous phase crosses that window's own seam.

    Copied verbatim from the app so phase traces break in the same
    places. A plain np.mod() fold would heal one seam and open an
    artificial one at the other boundary.
    """
    y = np.asarray(y, dtype=float)
    finite = np.isfinite(y)
    if finite.all():
        filled = y
    else:
        filled = y.copy()
        idx = np.arange(len(y))
        if finite.any():
            filled[~finite] = np.interp(idx[~finite], idx[finite], y[finite])
        else:
            filled[:] = 0.0

    continuous = np.unwrap(filled, period=360.0)
    folded = np.mod(continuous, 360.0) if wrap else np.mod(continuous + 180.0, 360.0) - 180.0

    turns = np.round((continuous - folded) / 360.0)
    breaks = np.diff(turns) != 0
    folded = folded.copy()
    folded[1:][breaks] = np.nan
    folded[~finite] = np.nan
    return folded
'''

_NORM_HELPER = '''
def norm_factor(x, y):
    """Scale factor for one trace, matching the app's Data display modes.

    Kept as a function because the mode is a live form field above --
    inlining three branches into every trace would make the plot cell
    unreadable and unedittable, which is the opposite of the point.
    """
    if NORMALIZATION == "none":
        return 1.0
    if NORMALIZATION == "at wavenumber":
        ref = y[np.argmin(np.abs(x - NORMALIZE_AT))]
        # magnitude, not signed value: a negative reference point must
        # not flip the whole trace
        return 1.0 / abs(ref) if ref != 0 else 1.0
    if NORMALIZATION == "to peak":
        visible = y
        if X_MIN != X_MAX:
            mask = (x >= min(X_MIN, X_MAX)) & (x <= max(X_MIN, X_MAX))
            if mask.any():
                visible = y[mask]
        peak = np.nanmax(np.abs(visible))
        return 1.0 / peak if peak != 0 else 1.0
    return 1.0
'''

_NORM_CHOICES = ["none", "at wavenumber", "to peak"]


def _params_cell(payload: dict) -> str:
    norm = payload["normalization"]
    mode = _NORM_CHOICES[norm.get("mode", 0)]
    x_range = payload.get("x_range") or (0.0, 0.0)
    figsize = payload.get("figsize", (6.4, 4.8))
    return f"""
#@title Figure settings {{ run: "auto" }}
#@markdown Re-run the plot cell after changing anything here.

NORMALIZATION = {as_literal(mode)}  #@param ["none", "at wavenumber", "to peak"]
NORMALIZE_AT = {as_literal(float(norm.get("target", 0.0)))}  #@param {{type:"number"}}
OFFSET_STEP = {as_literal(float(payload.get("offset_step", 0.0)))}  #@param {{type:"number"}}
X_MIN = {as_literal(float(x_range[0]))}  #@param {{type:"number"}}
X_MAX = {as_literal(float(x_range[1]))}  #@param {{type:"number"}}
INVERT_X = {as_literal(bool(payload.get("invert_x", False)))}  #@param {{type:"boolean"}}
PHASE_0_360 = {as_literal(bool(payload.get("phase_wrap_0_360", False)))}  #@param {{type:"boolean"}}
SHOW_ERROR_BANDS = {as_literal(bool(payload.get("show_error", False)))}  #@param {{type:"boolean"}}

FIG_WIDTH = {as_literal(float(figsize[0]))}  #@param {{type:"number"}}
FIG_HEIGHT = {as_literal(float(figsize[1]))}  #@param {{type:"number"}}
DPI = {as_literal(int(payload.get("dpi", 150)))}  #@param {{type:"integer"}}

OUTPUT_NAME = {as_literal(payload.get("output_name", "figure"))}  #@param {{type:"string"}}
OUTPUT_FORMAT = {as_literal(payload.get("output_format", "png"))}  #@param ["png", "pdf", "svg", "eps"]
"""


def _data_cell(payload: dict) -> str:
    blobs = {e["label"]: encode_text(e["csv"]) for e in payload["entries"]}
    lines = ["_EMBEDDED = {"]
    for label, blob in blobs.items():
        lines.append(f"    {as_literal(label)}: {as_literal(blob)},")
    lines.append("}")
    lines.append("")
    lines.append('''
# Each blob is the app's own CSV export, provenance header and all, so
# these spectra are byte-identical to "Export plotted" -- and can be
# loaded straight back into the Spectra Library.
spectra = {}
for _label, _blob in _EMBEDDED.items():
    _text = gzip.decompress(base64.b64decode(_blob)).decode("utf-8")
    _df = pd.read_csv(io.StringIO(_text), comment="#")
    if "Frame" in _df.columns:
        # Homodyne exports keep every frame; the app plots the averaged one.
        _df = _df[_df["Frame"] == _df["Frame"].iloc[0]]
    spectra[_label] = _df.reset_index(drop=True)

print(f"{len(spectra)} spectra:", ", ".join(spectra))
'''.strip())
    lines.append("")
    lines.append("# Uncomment to swap in your own exported CSVs instead:")
    lines.append("# from google.colab import files")
    lines.append("# for name, raw in files.upload().items():")
    lines.append('#     spectra[name] = pd.read_csv(io.BytesIO(raw), comment="#")')
    return "\n".join(lines)


def _trace_block(trace: dict, payload: dict) -> str:
    """Explicit, editable source for one plotted trace."""
    entry = as_literal(trace["entry"])
    column = as_literal(trace["column"])
    axis = "ax2" if trace["secondary"] else "ax"

    kwargs = [f"color={as_literal(trace['color'])}",
              f"linestyle={as_literal(trace['linestyle'])}"]
    for key in ("marker", "markersize", "linewidth", "alpha"):
        if trace.get(key) is not None:
            kwargs.append(f"{key}={as_literal(trace[key])}")
    if trace.get("legend"):
        kwargs.append(f"label={as_literal(trace['legend'])}")

    lines = [f"# {trace['entry']} — {trace['column']}"]
    lines.append(f"df = spectra[{entry}]")
    lines.append(f"x = df['Wavenumber'].to_numpy()")
    lines.append(f"y = df[{column}].to_numpy()")
    if trace.get("is_phase"):
        lines.append("y = wrap_phase_for_plot(y, PHASE_0_360)")
    if trace["secondary"]:
        # The app leaves a secondary axis in its own native units.
        lines.append(f"y = y + {trace['offset_slot']} * OFFSET_STEP")
    else:
        lines.append(f"y = y * norm_factor(x, y) + {trace['offset_slot']} * OFFSET_STEP")
    lines.append(f"{axis}.plot(x, y, {', '.join(kwargs)})")

    err = trace.get("err_column")
    if err and payload.get("show_error"):
        band_alpha = 0.25 * (trace.get("alpha") if trace.get("alpha") is not None else 1.0)
        lines.append("if SHOW_ERROR_BANDS and " + as_literal(err) + " in df.columns:")
        lines.append(f"    e = df[{as_literal(err)}].to_numpy() * norm_factor(x, df[{column}].to_numpy())")
        lines.append(f"    {axis}.fill_between(x, y - e, y + e, color={as_literal(trace['color'])}, "
                     f"alpha={as_literal(band_alpha)}, linewidth=0)")
    return "\n".join(lines)


def _setup_cell(payload: dict) -> str:
    """The axes every trace cell below draws onto — runs once."""
    traces = payload["traces"]
    lines = [
        "# SETUP — the axes every trace cell below draws onto.",
        "fig, ax = plt.subplots(figsize=(FIG_WIDTH, FIG_HEIGHT), dpi=DPI)",
    ]
    if any(t["secondary"] for t in traces):
        lines.append("ax2 = ax.twinx()   # Phase is on its own scale (degrees)")
    lines += [
        "# Closed right away so Colab doesn't render an empty figure here --",
        "# ax/ax2 stay fully usable, this only stops the auto-display that",
        "# would otherwise fire again after every cell below. The finished",
        "# figure is shown once, explicitly, by the DECORATE cell at the end.",
        "plt.close(fig)",
    ]
    return "\n".join(lines)


def _trace_cell(trace: dict, payload: dict) -> str:
    """One editable cell per plotted spectrum — restyle, or delete, freely."""
    return "# TRACE — edit color/style/label here, or drop this cell to remove the line.\n" + \
        _trace_block(trace, payload)


def _decorate_cell(payload: dict) -> str:
    """Axis labels, limits and legend — runs after every trace cell above."""
    traces = payload["traces"]
    needs_secondary = any(t["secondary"] for t in traces)

    lines = ["# DECORATE — labels, limits and legend for the figure as a whole.",
              f"ax.set_xlabel({as_literal(payload['x_label'])})",
              f"ax.set_ylabel({as_literal(payload['y_label'])})"]
    if needs_secondary and payload.get("y_label2"):
        lines.append(f"ax2.set_ylabel({as_literal(payload['y_label2'])})")
    if payload.get("title"):
        lines.append(f"ax.set_title({as_literal(payload['title'])})")
    lines += [
        "if X_MIN != X_MAX:",
        "    ax.set_xlim(min(X_MIN, X_MAX), max(X_MIN, X_MAX))",
        "if INVERT_X:",
        "    ax.invert_xaxis()",
    ]
    if needs_secondary:
        lines += [
            "handles, labels = ax.get_legend_handles_labels()",
            "h2, l2 = ax2.get_legend_handles_labels()",
            "handles, labels = handles + h2, labels + l2",
        ]
    else:
        lines.append("handles, labels = ax.get_legend_handles_labels()")
    lines += [
        "if len(handles) > 1:",
        "    ax.legend(handles, labels, fontsize=8)",
        "fig.tight_layout()",
        "display(fig)   # fig was closed in SETUP; this renders it, once.",
    ]
    return "\n".join(lines)


def _fit_cell(payload: dict) -> str:
    return '''
# Fit parameters recovered from each spectrum's "# Fit json:" header --
# the same numbers the Fitting tab reported, uncertainties included.
rows = []
for label, blob in _EMBEDDED.items():
    text = gzip.decompress(base64.b64decode(blob)).decode("utf-8")
    line = next((l for l in text.splitlines() if l.startswith("# Fit json:")), None)
    if line is None:
        continue
    fit = json.loads(line.split("# Fit json:", 1)[1].strip())
    errors = fit.get("param_errors") or {}
    for key, value in (fit.get("model") or {}).get("params", {}).items():
        rows.append({"spectrum": label, "parameter": key,
                     "value": value, "stderr": errors.get(key)})
    rows.append({"spectrum": label, "parameter": "redchi",
                 "value": fit.get("redchi"), "stderr": None})

if rows:
    display(pd.DataFrame(rows))
else:
    print("No fit attached to these spectra.")
'''.strip()


def build(payload: dict) -> dict:
    """Assemble the notebook.

    `payload` keys: title, x_label, y_label, y_label2, normalization
    {mode,target}, offset_step, x_range, invert_x, phase_wrap_0_360,
    show_error, figsize, dpi, output_name, output_format, entries
    [{label, kind, csv}], traces [{entry, column, err_column, legend,
    color, linestyle, marker, markersize, linewidth, alpha, secondary,
    is_fit, is_phase, offset_slot}].
    """
    n = len(payload["entries"])
    has_fits = any(t.get("is_fit") for t in payload["traces"])

    cells = [
        markdown_cell(f"""
# {payload.get('title') or 'SFG figure'}

Exported from SFG-App. Everything needed is embedded — this runs on a
fresh Colab runtime with no local files and installs nothing.

The figure is built as one **setup** cell, one **trace** cell per
plotted spectrum (colours and labels already resolved — edit, duplicate,
or delete any of them), and one **decorate** cell for axis labels/limits/
legend. The form fields control normalization, offsets and output;
re-run the trace and decorate cells after changing them.
""".strip()),

        code_cell("""
import base64, gzip, io, json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display
""".strip()),

        code_cell(_params_cell(payload)),

        markdown_cell(f"## Data\n\n{n} spectra, embedded as the app's own CSV exports."),
        code_cell(_data_cell(payload)),

        markdown_cell("## Helpers\n\nThe two pieces of app behaviour the "
                      "figure depends on, so it reproduces exactly."),
        code_cell(_PHASE_HELPER.strip() + "\n\n\n" + _NORM_HELPER.strip()),

        markdown_cell("## The figure\n\nOne cell per trace below — edit, "
                      "duplicate, or delete any of them freely."),
        code_cell(_setup_cell(payload)),
        *[code_cell(_trace_cell(t, payload)) for t in payload["traces"]],
        code_cell(_decorate_cell(payload)),
    ]

    if has_fits:
        cells += [
            markdown_cell("## Fit parameters"),
            code_cell(_fit_cell(payload)),
        ]

    cells += [
        markdown_cell("## Save"),
        code_cell("""
out = f"{OUTPUT_NAME}.{OUTPUT_FORMAT}"
fig.savefig(out, dpi=DPI, bbox_inches="tight")
print("wrote", out)
# In Colab: from google.colab import files; files.download(out)
""".strip()),
    ]

    return notebook(cells, title=(payload.get("title") or "SFG figure"))
