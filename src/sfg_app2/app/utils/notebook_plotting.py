"""Build a self-contained plotting notebook from a plain matplotlib Axes.

The point of this notebook is full control over the figure, so it
reproduces exactly what's currently plotted and then gets out of the
way: each line becomes an explicit, editable `ax.plot()` call with its
color/style/label already resolved. It works from any plot in the app
-- it reads real trace data straight off the Axes (`Line2D.get_xdata()`/
`get_ydata()`), not from any tab-specific data model, so it carries no
processing history/provenance and no per-tab concepts (fits, metadata,
normalization modes) -- just lines.

It installs nothing -- numpy/pandas/matplotlib are preinstalled on
Colab, and the data is embedded, not referenced by path.

`build_payload()` is the only function that touches matplotlib objects;
`build()` takes the plain dict it returns, so this module is easy to
exercise without ever creating a Qt widget.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib as mpl

from .notebook_export import (
    app_version, as_literal, code_cell, encode_text, markdown_cell, notebook,
    timestamp as _timestamp,
)


def is_overlay_line(xd, yd) -> bool:
    """True for a 2-point axhline/axvline artist, which store one of their
    two coordinate arrays as [0, 1] in axes-fraction space rather than real
    data -- axhline puts that placeholder in xdata, axvline in ydata, so
    both must be checked or the un-checked one leaks into range/autoscale
    computations (or, here, into the exported notebook) as if it were real
    plotted data."""
    return ((len(xd) == 2 and np.allclose(xd, [0.0, 1.0])) or
            (len(yd) == 2 and np.allclose(yd, [0.0, 1.0])))


def _line_style(line) -> dict:
    marker = line.get_marker()
    label = line.get_label() or ""
    return {
        "label": "" if label.startswith("_") else label,
        "color": mpl.colors.to_hex(line.get_color(), keep_alpha=False),
        "linestyle": line.get_linestyle(),
        "marker": None if marker in (None, "None", "") else marker,
        "markersize": line.get_markersize(),
        "linewidth": line.get_linewidth(),
        "alpha": line.get_alpha(),
    }


def build_payload(ax, ax2=None, *, output_name: str = "figure",
                   output_format: str = "png") -> dict:
    """Flatten one Axes (plus its optional twin) into the plain dict
    `build()` consumes.

    Only real `Line2D` data survives -- fill_between error bands and
    errorbar caps aren't Line2D children and are silently omitted, and
    axhline/axvline placeholders are excluded via is_overlay_line(). A
    proxy legend handle (e.g. homodyne_panel's "minimized legend" mode,
    built as an mlines.Line2D never added to the axes) is likewise
    invisible here since it's never in ax.get_lines() -- the real data
    line it stands in for is plotted separately and is picked up as
    usual.
    """
    traces = []
    for axis, secondary in ((ax, False), (ax2, True)):
        if axis is None:
            continue
        for line in axis.get_lines():
            xd = np.asarray(line.get_xdata(), dtype=float)
            yd = np.asarray(line.get_ydata(), dtype=float)
            if not len(xd) or is_overlay_line(xd, yd):
                continue
            trace = _line_style(line)
            trace["id"] = f"t{len(traces)}"
            trace["secondary"] = secondary
            trace["csv"] = pd.DataFrame({"x": xd, "y": yd}).to_csv(index=False)
            traces.append(trace)

    width, height = ax.figure.get_size_inches()
    return {
        "title": ax.get_title(),
        "x_label": ax.get_xlabel(),
        "y_label": ax.get_ylabel(),
        "y_label2": ax2.get_ylabel() if ax2 is not None else None,
        "x_range": tuple(ax.get_xlim()),
        "figsize": (float(width), float(height)),
        "dpi": 150,
        "output_name": output_name,
        "output_format": output_format,
        "traces": traces,
    }


def _params_cell(payload: dict) -> str:
    x_range = payload.get("x_range") or (0.0, 0.0)
    figsize = payload.get("figsize", (6.4, 4.8))
    return f"""
#@title Figure settings {{ run: "auto" }}
#@markdown Re-run the trace and decorate cells after changing anything here.

OFFSET_STEP = {as_literal(float(payload.get("offset_step", 0.0)))}  #@param {{type:"number"}}
X_MIN = {as_literal(float(x_range[0]))}  #@param {{type:"number"}}
X_MAX = {as_literal(float(x_range[1]))}  #@param {{type:"number"}}
INVERT_X = {as_literal(bool(payload.get("invert_x", False)))}  #@param {{type:"boolean"}}

FIG_WIDTH = {as_literal(float(figsize[0]))}  #@param {{type:"number"}}
FIG_HEIGHT = {as_literal(float(figsize[1]))}  #@param {{type:"number"}}
DPI = {as_literal(int(payload.get("dpi", 150)))}  #@param {{type:"integer"}}

OUTPUT_NAME = {as_literal(payload.get("output_name", "figure"))}  #@param {{type:"string"}}
OUTPUT_FORMAT = {as_literal(payload.get("output_format", "png"))}  #@param ["png", "pdf", "svg", "eps"]
"""


def _data_cell(payload: dict) -> str:
    blobs = {t["id"]: encode_text(t["csv"]) for t in payload["traces"]}
    lines = ["_ENCODED = {"]
    for tid, blob in blobs.items():
        lines.append(f"    {as_literal(tid)}: {as_literal(blob)},")
    lines.append("}")
    lines.append("")
    lines.append('''
_TRACES = {}
for _id, _blob in _ENCODED.items():
    _text = gzip.decompress(base64.b64decode(_blob)).decode("utf-8")
    _TRACES[_id] = pd.read_csv(io.StringIO(_text))

print(f"{len(_TRACES)} traces:", ", ".join(_TRACES))
'''.strip())
    return "\n".join(lines)


def _trace_block(index: int, trace: dict) -> str:
    """Explicit, editable source for one plotted line."""
    tid = as_literal(trace["id"])
    axis = "ax2" if trace["secondary"] else "ax"

    kwargs = [f"color={as_literal(trace['color'])}",
              f"linestyle={as_literal(trace['linestyle'])}"]
    for key in ("marker", "markersize", "linewidth", "alpha"):
        if trace.get(key) is not None:
            kwargs.append(f"{key}={as_literal(trace[key])}")
    if trace.get("label"):
        kwargs.append(f"label={as_literal(trace['label'])}")

    lines = [f"# {trace.get('label') or trace['id']}"]
    lines.append(f"_df = _TRACES[{tid}]")
    lines.append("x = _df['x'].to_numpy()")
    lines.append(f"y = _df['y'].to_numpy() + {index} * OFFSET_STEP")
    lines.append(f"{axis}.plot(x, y, {', '.join(kwargs)})")
    return "\n".join(lines)


def _setup_cell(payload: dict) -> str:
    """The axes every trace cell below draws onto -- runs once."""
    traces = payload["traces"]
    lines = [
        "# SETUP — the axes every trace cell below draws onto.",
        "fig, ax = plt.subplots(figsize=(FIG_WIDTH, FIG_HEIGHT), dpi=DPI)",
    ]
    if any(t["secondary"] for t in traces):
        lines.append("ax2 = ax.twinx()")
    lines += [
        "# Closed right away so Colab doesn't render an empty figure here --",
        "# ax/ax2 stay fully usable, this only stops the auto-display that",
        "# would otherwise fire again after every cell below. The finished",
        "# figure is shown once, explicitly, by the DECORATE cell at the end.",
        "plt.close(fig)",
    ]
    return "\n".join(lines)


def _trace_cell(index: int, trace: dict) -> str:
    """One editable cell per plotted line -- restyle, or drop it, freely."""
    return ("# TRACE — edit color/style/label here, or drop this cell to "
            "remove the line.\n" + _trace_block(index, trace))


def _decorate_cell(payload: dict) -> str:
    """Axis labels, limits and legend -- runs after every trace cell above."""
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


def build(payload: dict) -> dict:
    """Assemble the notebook.

    `payload` keys: title, x_label, y_label, y_label2, x_range,
    offset_step, invert_x, figsize, dpi, output_name, output_format,
    traces [{id, label, color, linestyle, marker, markersize,
    linewidth, alpha, secondary, csv}].
    """
    n = len(payload["traces"])

    cells = [
        markdown_cell(f"""
# {payload.get('title') or 'Figure'}

Exported from SFG-App {app_version()} on {_timestamp()}.

Everything needed is embedded — this runs on a fresh Colab runtime with
no local files and installs nothing.

The figure is built as one **setup** cell, one **trace** cell per
plotted line (colours and labels already resolved — edit, duplicate,
or delete any of them), and one **decorate** cell for axis labels/
limits/legend. The form fields control offsets, x-range and output;
re-run the trace and decorate cells after changing them.
""".strip()),

        code_cell("""
import base64, gzip, io
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display
""".strip(), hidden_title="Imports"),

        code_cell(_params_cell(payload)),

        markdown_cell(f"## Data\n\n{n} line(s), embedded as plain x/y CSV "
                      f"data. Expand the cell below to read them, or to "
                      f"swap in your own instead."),
        code_cell(_data_cell(payload), hidden_title=f"Embedded traces ({n})"),

        markdown_cell("## The figure\n\nOne cell per line below — edit, "
                      "duplicate, or delete any of them freely."),
        code_cell(_setup_cell(payload)),
        *[code_cell(_trace_cell(i, t)) for i, t in enumerate(payload["traces"])],
        code_cell(_decorate_cell(payload)),

        markdown_cell("## Save"),
        code_cell("""
out = f"{OUTPUT_NAME}.{OUTPUT_FORMAT}"
fig.savefig(out, dpi=DPI, bbox_inches="tight")
print("wrote", out)
# In Colab: from google.colab import files; files.download(out)
""".strip()),
    ]

    return notebook(cells, title=(payload.get("title") or "Figure"))
