"""Build a self-contained processing notebook for one matched set.

Walks the homodyne or heterodyne pipeline a stage at a time, with a
short note and an intermediate plot at each, mirroring the hand-written
walkthroughs in tests/. The parameters are pre-filled with whatever the
app was using, exposed as Colab form fields so they can be re-tuned.

Self-contained in the strong sense: the four raw CSVs are embedded, and
so is the processing package itself, as a zip the setup cell unpacks
onto sys.path. `pip install git+...` is not an option -- the project
requires Python >= 3.14 while Colab runs 3.11/3.12, and its dependencies
pull in PySide6 -- but `processing/` alone needs nothing beyond
numpy/pandas/scipy, all preinstalled there.

Qt-free: the caller passes a plain dict (see `build`).
"""
from __future__ import annotations

from .notebook_export import (
    as_literal, build_source_bundle, code_cell, encode_text, markdown_cell,
    notebook,
)

_ROLES = ("signal", "background", "reference", "reference_background")

_SETUP = '''
import base64, gzip, io, json, os, sys, zipfile

# The SFG processing package, embedded. Unpacked here rather than pip
# installed: the project requires Python >= 3.14 (Colab runs 3.11/3.12)
# and depends on PySide6, but processing/ needs only numpy/pandas/scipy,
# which Colab already has.
zipfile.ZipFile(io.BytesIO(base64.b64decode(_PACKAGE))).extractall("sfg_pkg")
sys.path.insert(0, os.path.abspath("sfg_pkg"))

# The four raw files, embedded, written back out so DataFile can read
# them by path exactly as the app does.
os.makedirs("data", exist_ok=True)
for _name, _blob in _RAW_FILES.items():
    with open(os.path.join("data", _name), "w", encoding="utf-8", newline="") as _f:
        _f.write(gzip.decompress(base64.b64decode(_blob)).decode("utf-8"))

import numpy as np
import matplotlib.pyplot as plt

print("ready:", ", ".join(sorted(os.listdir("data"))))
'''

_UPLOAD_FALLBACK = '''
# Swap in your own files instead of the embedded ones: run this cell,
# pick four raw CSVs, then re-run the loading cell below.
# from google.colab import files
# for _name, _raw in files.upload().items():
#     with open(os.path.join("data", _name), "wb") as _f:
#         _f.write(_raw)
# RAW["signal"] = "your_signal.csv"   # ...and the other three roles
'''


def _package_cell(payload: dict) -> str:
    lines = [f"_PACKAGE = {as_literal(build_source_bundle())}", ""]
    lines.append("_RAW_FILES = {")
    for name, text in payload["raw_files"].items():
        lines.append(f"    {as_literal(name)}: {as_literal(encode_text(text))},")
    lines.append("}")
    lines.append("")
    lines.append(_SETUP.strip())
    return "\n".join(lines)


def _roles_cell(payload: dict) -> str:
    lines = ["RAW = {"]
    for role in _ROLES:
        name = payload["roles"].get(role)
        if name:
            lines.append(f"    {as_literal(role)}: {as_literal(name)},")
    lines.append("}")
    return "\n".join(lines)


def _homodyne_params(cfg: dict) -> str:
    return f"""
#@title Processing parameters {{ run: "auto" }}
#@markdown Pre-filled with the values the app was using.

DESPIKE_WINDOW = {as_literal(int(cfg.get("despike_window", 5)))}  #@param {{type:"integer"}}
DESPIKE_THRESHOLD = {as_literal(float(cfg.get("despike_threshold", 3.0)))}  #@param {{type:"number"}}
BACKGROUND_OFFSET = {as_literal(float(cfg.get("bg_offset") or 0.0))}  #@param {{type:"number"}}
UPCONVERSION_NM = {as_literal(float(cfg.get("upconversion_wavelength") or 1030.7))}  #@param {{type:"number"}}

OUTPUT_NAME = {as_literal(cfg.get("label", "processed"))}  #@param {{type:"string"}}
"""


def _heterodyne_params(cfg: dict) -> str:
    return f"""
#@title Processing parameters {{ run: "auto" }}
#@markdown Pre-filled with the values the app was using.

DESPIKE_WINDOW = {as_literal(int(cfg.get("despike_window", 50)))}  #@param {{type:"integer"}}
DESPIKE_THRESHOLD = {as_literal(float(cfg.get("despike_threshold", 10.0)))}  #@param {{type:"number"}}
UPCONVERSION_NM = {as_literal(float(cfg.get("upconversion_wavelength", 1030.7)))}  #@param {{type:"number"}}

BG_SMOOTHING_WINDOW = {as_literal(int(cfg.get("bg_smoothing_window", 0)))}  #@param {{type:"integer"}}
BG_SMOOTHING_ORDER = {as_literal(int(cfg.get("bg_smoothing_order", 3)))}  #@param {{type:"integer"}}
BACKGROUND_OFFSET = {as_literal(float(cfg.get("bg_offset") or 0.0))}  #@param {{type:"number"}}

EDGE_LEFT = {as_literal(int(cfg.get("edge_left", 15)))}  #@param {{type:"integer"}}
EDGE_RIGHT = {as_literal(int(cfg.get("edge_right", 15)))}  #@param {{type:"integer"}}
WINDOW_TYPE = {as_literal(int(cfg.get("window_type", 3)))}  #@param [1, 2, 3, 4] {{type:"raw"}}
FFT_START = {as_literal(int(cfg.get("fft_start", 30)))}  #@param {{type:"integer"}}
FFT_END = {as_literal(int(cfg.get("fft_end", 110)))}  #@param {{type:"integer"}}
HG_LEFT = {as_literal(int(cfg.get("hg_left", 10)))}  #@param {{type:"integer"}}
HG_RIGHT = {as_literal(int(cfg.get("hg_right", 10)))}  #@param {{type:"integer"}}
PHASE_CORRECTION_DEG = {as_literal(float(cfg.get("phase_correction_deg", 0.0)))}  #@param {{type:"number"}}

OUTPUT_NAME = {as_literal(cfg.get("label", "processed"))}  #@param {{type:"string"}}
"""


def _homodyne_cells(payload: dict) -> list[dict]:
    return [
        markdown_cell("## 1. Load the matched set\n\n"
                      "Four raw files: the sample signal and its background, "
                      "and a reference and its background."),
        code_cell("""
# COMPUTE — replace this cell to change how the raw files are loaded;
# the cells below only need `signal`, `background`, `reference` and
# `reference_bg` to stay DataFile objects.
from sfg_app2.processing.data_file import DataFile
from sfg_app2.processing.matcher import MatchedSet
from sfg_app2.processing.baseline import subtract_background
from sfg_app2.processing.normalization import normalize

signal = DataFile(os.path.join("data", RAW["signal"]))
background = DataFile(os.path.join("data", RAW["background"]))
reference = DataFile(os.path.join("data", RAW["reference"]))
reference_bg = DataFile(os.path.join("data", RAW["reference_background"]))

matched = MatchedSet(signal=signal, background=background,
                     reference=reference, reference_background=reference_bg,
                     spectrum_type="homodyne")
print("complete set:", matched.is_complete(),
      "|", signal.n_frames, "frames")
""".strip()),
        code_cell("""
# PLOT — safe to restyle without touching the cell above.
fig, axes = plt.subplots(1, 2, figsize=(9, 4))
signal.plot(ax=axes[0])
axes[0].set_title("Signal")
background.plot(ax=axes[1])
axes[1].set_title("Background")
fig.suptitle("Sample (raw)")
plt.show()

fig, axes = plt.subplots(1, 2, figsize=(9, 4))
reference.plot(ax=axes[0])
axes[0].set_title("Reference")
reference_bg.plot(ax=axes[1])
axes[1].set_title("Reference background")
fig.suptitle("Reference (raw)")
plt.show()
""".strip()),

        markdown_cell("## 2. Despike\n\nA moving-median filter removes cosmic "
                      "ray hits, which are single-pixel spikes far above the "
                      "local noise."),
        code_cell("""
# COMPUTE — replace this cell to change despiking; the cell below only
# needs `despiked` to stay a dict of DataFile keyed the same way.
despiked = {name: f.remove_cosmic_rays(window=DESPIKE_WINDOW,
                                       threshold_factor=DESPIKE_THRESHOLD)
            for name, f in [("signal", signal), ("background", background),
                            ("reference", reference), ("reference_bg", reference_bg)]}
""".strip()),
        code_cell("""
# PLOT — safe to restyle without touching the cell above.
fig, axes = plt.subplots(1, 2, figsize=(9, 4))
signal.plot(ax=axes[0], frame_id=1, label="raw", alpha=0.6)
despiked["signal"].plot(ax=axes[0], frame_id=1, label="despiked")
axes[0].legend()
axes[0].set_title("Signal")
background.plot(ax=axes[1], frame_id=1, label="raw", alpha=0.6)
despiked["background"].plot(ax=axes[1], frame_id=1, label="despiked")
axes[1].legend()
axes[1].set_title("Background")
fig.suptitle("Sample")
plt.show()

fig, axes = plt.subplots(1, 2, figsize=(9, 4))
reference.plot(ax=axes[0], frame_id=1, label="raw", alpha=0.6)
despiked["reference"].plot(ax=axes[0], frame_id=1, label="despiked")
axes[0].legend()
axes[0].set_title("Reference")
reference_bg.plot(ax=axes[1], frame_id=1, label="raw", alpha=0.6)
despiked["reference_bg"].plot(ax=axes[1], frame_id=1, label="despiked")
axes[1].legend()
axes[1].set_title("Reference background")
fig.suptitle("Reference")
plt.show()
""".strip()),

        markdown_cell("## 3. Average frames"),
        code_cell("""
# COMPUTE — replace this cell to change how frames are combined; the
# cell below only needs `averaged` to stay a dict of DataFile.
averaged = {name: f.average_spectrum() for name, f in despiked.items()}
""".strip()),
        code_cell("""
# PLOT — safe to restyle without touching the cell above.
fig, ax = plt.subplots()
averaged["signal"].plot(ax=ax, label="signal")
averaged["background"].plot(ax=ax, label="background")
ax.legend()
ax.set_title("Sample")
plt.show()

fig, ax = plt.subplots()
averaged["reference"].plot(ax=ax, label="reference")
averaged["reference_bg"].plot(ax=ax, label="reference background")
ax.legend()
ax.set_title("Reference")
plt.show()
""".strip()),

        markdown_cell("## 4. Subtract backgrounds\n\nThe sample keeps its own "
                      "background; the reference keeps its own."),
        code_cell("""
# COMPUTE — replace this cell to change background subtraction; the
# cell below only needs `sample_corrected` and `reference_corrected`.
offset = BACKGROUND_OFFSET or None
sample_corrected = subtract_background(averaged["signal"], averaged["background"], offset=offset)
reference_corrected = subtract_background(averaged["reference"], averaged["reference_bg"])
""".strip()),
        code_cell("""
# PLOT — safe to restyle without touching the cell above.
fig, ax = plt.subplots()
sample_corrected.plot(ax=ax)
ax.set_ylabel("Intensity (bg-subtracted)")
ax.set_title("Sample")
plt.show()

fig, ax = plt.subplots()
reference_corrected.plot(ax=ax)
ax.set_ylabel("Intensity (bg-subtracted)")
ax.set_title("Reference")
plt.show()
""".strip()),

        markdown_cell("## 5. Normalize and upconvert\n\nDividing by the "
                      "reference removes the IR profile; upconversion converts "
                      "the detected wavelength to the IR wavenumber probed."),
        code_cell("""
# COMPUTE — replace this cell to change normalization/upconversion; the
# cell below only needs `result` to keep a `.plot()` method and a
# "Wavenumber" column.
normalized = normalize(sample_corrected, reference_corrected)
result = normalized.upconvert_to_wavenumber(UPCONVERSION_NM)
""".strip()),
        code_cell("""
# PLOT — safe to restyle without touching the cell above.
fig, ax = plt.subplots()
result.plot(ax=ax, x="Wavenumber")
ax.set_ylabel("Normalized Intensity (a.u.)")
plt.show()
""".strip()),
    ]


def _heterodyne_cells(payload: dict) -> list[dict]:
    return [
        markdown_cell("## 1. Load the matched set\n\n"
                      "The same four raw files as homodyne, processed very "
                      "differently: the signal interferes with a reference "
                      "field, so both the real and imaginary parts of "
                      "$\\chi^{(2)}$ — and therefore the phase — survive."),
        code_cell("""
# COMPUTE — replace this cell to change how the raw files are loaded;
# the cells below only need `matched` to stay a MatchedSet.
from sfg_app2.processing.data_file import DataFile
from sfg_app2.processing.matcher import MatchedSet
from sfg_app2.processing.hd_sfg import (
    HDSFGConfig, DeSpikeParams,
    step_despike, step_average, step_bg_smooth, step_fft_filter, step_normalize,
)

signal = DataFile(os.path.join("data", RAW["signal"]))
background = DataFile(os.path.join("data", RAW["background"]))
reference = DataFile(os.path.join("data", RAW["reference"]))
reference_bg = DataFile(os.path.join("data", RAW["reference_background"]))

matched = MatchedSet(signal=signal, background=background,
                     reference=reference, reference_background=reference_bg,
                     spectrum_type="heterodyne")
print("complete set:", matched.is_complete())
""".strip()),
        code_cell("""
# PLOT — safe to restyle without touching the cell above.
fig, axes = plt.subplots(1, 2, figsize=(9, 4))
signal.plot(ax=axes[0])
axes[0].set_title("Signal")
background.plot(ax=axes[1])
axes[1].set_title("Background")
fig.suptitle("Sample (raw)")
plt.show()

fig, axes = plt.subplots(1, 2, figsize=(9, 4))
reference.plot(ax=axes[0])
axes[0].set_title("Reference")
reference_bg.plot(ax=axes[1])
axes[1].set_title("Reference background")
fig.suptitle("Reference (raw)")
plt.show()
""".strip()),

        markdown_cell("## 2. Configuration\n\nOne config object drives every "
                      "step below, built from the form fields above."),
        code_cell("""
# COMPUTE — replace this cell to override any pipeline setting directly
# (instead of through the form fields); the cells below only need
# `config` to stay an HDSFGConfig.
config = HDSFGConfig(
    upconversion_wavelength=UPCONVERSION_NM,
    bg_smoothing_window=BG_SMOOTHING_WINDOW,
    bg_smoothing_order=BG_SMOOTHING_ORDER,
    bg_offset=BACKGROUND_OFFSET or None,
    edge_left=EDGE_LEFT,
    edge_right=EDGE_RIGHT,
    window_type=WINDOW_TYPE,
    fft_start=FFT_START,
    fft_end=FFT_END,
    hg_left=HG_LEFT,
    hg_right=HG_RIGHT,
    phase_correction_deg=PHASE_CORRECTION_DEG,
)
config
""".strip()),

        markdown_cell("## 3. Despike\n\nOne `DeSpikeParams` per component — a "
                      "long-exposure sample is noisier than a short reference, "
                      "so they can differ. Here all four share one setting."),
        code_cell("""
# COMPUTE — replace this cell to despike components differently; the
# cell below only needs `despiked`.
params = DeSpikeParams(window=DESPIKE_WINDOW, threshold=DESPIKE_THRESHOLD)
despiked = step_despike(matched, params, params, params, params)
print("despiked:", despiked.signal.n_frames, "signal frames")
""".strip()),
        code_cell("""
# PLOT — safe to restyle without touching the cell above.
fig, axes = plt.subplots(1, 2, figsize=(9, 4))
signal.plot(ax=axes[0], frame_id=1, label="raw", alpha=0.6)
despiked.signal.plot(ax=axes[0], frame_id=1, label="despiked")
axes[0].legend()
axes[0].set_title("Signal")
background.plot(ax=axes[1], frame_id=1, label="raw", alpha=0.6)
despiked.background.plot(ax=axes[1], frame_id=1, label="despiked")
axes[1].legend()
axes[1].set_title("Background")
fig.suptitle("Sample")
plt.show()

fig, axes = plt.subplots(1, 2, figsize=(9, 4))
reference.plot(ax=axes[0], frame_id=1, label="raw", alpha=0.6)
despiked.reference.plot(ax=axes[0], frame_id=1, label="despiked")
axes[0].legend()
axes[0].set_title("Reference")
reference_bg.plot(ax=axes[1], frame_id=1, label="raw", alpha=0.6)
despiked.ref_background.plot(ax=axes[1], frame_id=1, label="despiked")
axes[1].legend()
axes[1].set_title("Reference background")
fig.suptitle("Reference")
plt.show()
""".strip()),

        markdown_cell("## 4. Average and interpolate\n\nConverts to wavenumber, "
                      "averages frames, and puts every component on one uniform grid."),
        code_cell("""
# COMPUTE — replace this cell freely; the cell below only needs
# `averaged` to expose `.wavenumber`, `.sig_avg` and `.bg_avg`.
averaged = step_average(despiked, config)
""".strip()),
        code_cell("""
# PLOT — safe to restyle without touching the cell above.
fig, ax = plt.subplots()
ax.plot(averaged.wavenumber, averaged.sig_avg, label="signal")
ax.plot(averaged.wavenumber, averaged.bg_avg, label="background")
ax.set_xlabel("Wavenumber (cm$^{-1}$)")
ax.set_ylabel("Intensity")
ax.legend()
ax.set_title("Sample")
plt.show()

fig, ax = plt.subplots()
ax.plot(averaged.wavenumber, averaged.ref_avg, label="reference")
ax.plot(averaged.wavenumber, averaged.ref_bg_avg, label="reference background")
ax.set_xlabel("Wavenumber (cm$^{-1}$)")
ax.set_ylabel("Intensity")
ax.legend()
ax.set_title("Reference")
plt.show()
""".strip()),

        markdown_cell("## 5. Background subtraction and edge taper\n\n"
                      "Optionally smooths the background before subtracting it, "
                      "then tapers the edges so the FFT sees no step."),
        code_cell("""
# COMPUTE — replace this cell freely; the cell below only needs
# `bg_sub` to expose `.sig_delta` and `.sig_delta_windowed`.
bg_sub = step_bg_smooth(averaged, config)
""".strip()),
        code_cell("""
# PLOT — safe to restyle without touching the cell above.
fig, ax = plt.subplots()
ax.plot(bg_sub.wavenumber, bg_sub.sig_delta, label="signal − background")
ax.plot(bg_sub.wavenumber, bg_sub.sig_delta_windowed, linestyle="--",
        label="after edge taper")
ax.set_xlabel("Wavenumber (cm$^{-1}$)")
ax.set_ylabel("Signal − background")
ax.legend()
ax.set_title("Sample")
plt.show()

fig, ax = plt.subplots()
ax.plot(bg_sub.wavenumber, bg_sub.ref_delta, label="reference − reference background")
ax.plot(bg_sub.wavenumber, bg_sub.ref_delta_windowed, linestyle="--",
        label="after edge taper")
ax.set_xlabel("Wavenumber (cm$^{-1}$)")
ax.set_ylabel("Reference − reference background")
ax.legend()
ax.set_title("Reference")
plt.show()
""".strip()),

        markdown_cell("## 6. FFT filter\n\nIn the time domain the interferometric "
                      "cross-term sits apart from the DC and autocorrelation "
                      "terms, so a window isolates it before transforming back."),
        code_cell("""
# COMPUTE — replace this cell freely; the cell below only needs
# `fft_data` to expose `.time_axis`, `.sig_fft` and `.fft_mask`. The mask
# plot is what shows whether FFT_START/END/HG_LEFT/HG_RIGHT are cutting
# in the right place.
fft_data = step_fft_filter(bg_sub, config)
""".strip()),
        code_cell("""
# PLOT — safe to restyle without touching the cell above.
fig, ax = plt.subplots()
t = fft_data.time_axis * 1e12
ax.plot(t, fft_data.sig_fft.imag, label="signal FFT (imag)")
ax2 = ax.twinx()
ax2.plot(t, fft_data.fft_mask, color="firebrick", linestyle=":", label="mask")
ax2.set_ylabel("Mask weight", color="firebrick")
ax.set_xlabel("Time (ps)")
ax.set_ylabel("FFT amplitude, imaginary (a.u.)")
ax.legend(loc="upper right")
ax.set_title("Sample")
plt.show()

fig, ax = plt.subplots()
ax.plot(t, fft_data.ref_fft.imag, label="reference FFT (imag)")
ax2 = ax.twinx()
ax2.plot(t, fft_data.fft_mask, color="firebrick", linestyle=":", label="mask")
ax2.set_ylabel("Mask weight", color="firebrick")
ax.set_xlabel("Time (ps)")
ax.set_ylabel("FFT amplitude, imaginary (a.u.)")
ax.legend(loc="upper right")
ax.set_title("Reference")
plt.show()
""".strip()),

        markdown_cell("## 7. Normalize\n\nDividing by the reference yields the "
                      "complex $\\chi^{(2)}$ — real, imaginary and phase."),
        code_cell("""
# COMPUTE — replace this cell freely; the export cell below only needs
# `result` to keep a `.to_dataframe()` method.
result = step_normalize(fft_data, config)
""".strip()),
        code_cell("""
# PLOT — safe to restyle without touching the cell above.
fig, ax = plt.subplots()
ax.plot(result.wavenumber, result.complex_chi.imag, label=r"Im($\\chi^{(2)}$)")
ax.plot(result.wavenumber, result.complex_chi.real, linestyle="--", label=r"Re($\\chi^{(2)}$)")
ax.axhline(0, color="gray", linewidth=0.5)
ax2 = ax.twinx()
ax2.plot(result.wavenumber, result.phase, color="gray", linestyle=":", alpha=0.8)
ax2.set_ylabel("Phase (°)", color="gray")
ax.set_xlabel("Wavenumber (cm$^{-1}$)")
ax.set_ylabel(r"$\\chi^{(2)}$: Re / Im (a.u.)")
ax.legend()
plt.show()
""".strip()),
    ]


def _export_cell(kind: str) -> str:
    if kind == "heterodyne":
        # Same shape the app builds when an HDSFGResult enters the
        # Library, so the CSV reloads identically.
        to_spectrum = """
from sfg_app2.processing.processed_spectrum import ProcessedSpectrum

df = result.to_dataframe()
df.insert(0, "Frame", 1)
spectrum = ProcessedSpectrum(df, metadata=getattr(result, "metadata", {}) or {},
                             history=list(getattr(result, "history", []) or []))
""".strip()
    else:
        to_spectrum = "spectrum = result"
    return f"""
from sfg_app2.processing import provenance

{to_spectrum}
out = OUTPUT_NAME + ".csv"
provenance.write_csv_with_provenance(spectrum, {as_literal(kind)}, OUTPUT_NAME, out)
print("wrote", out)

# Same format the app writes, so this loads straight back into the
# Spectra Library via "Add spectra from file".
# In Colab: from google.colab import files; files.download(out)
""".strip()


def build(payload: dict) -> dict:
    """Assemble the notebook.

    `payload` keys: kind ("homodyne"/"heterodyne"), label, roles
    {role: filename}, raw_files {filename: csv text}, config (the
    pipeline parameters the app was using).
    """
    kind = payload["kind"]
    label = payload.get("label", "processed")
    is_het = kind == "heterodyne"

    cells = [
        markdown_cell(f"""
# {label} — {'heterodyne (HD-SFG)' if is_het else 'homodyne'} processing

Exported from SFG-App. Fully self-contained: the four raw files and the
processing package are both embedded, so this runs on a fresh Colab
runtime with no uploads and no `pip install`.

Each stage below is a **compute** cell followed by a **plot** cell: edit
a compute cell to change how that stage works, or a plot cell to change
how it's drawn — each names the variable(s) the next cell needs, so an
edit stays contained to that one cell. The form fields are pre-filled
with the values the app was using.
""".strip()),

        markdown_cell("## Setup"),
        code_cell(_package_cell(payload), collapsed=True),
        code_cell(_roles_cell(payload)),
        code_cell(_UPLOAD_FALLBACK.strip()),

        code_cell(_heterodyne_params(payload["config"]) if is_het
                  else _homodyne_params(payload["config"])),
    ]

    cells += _heterodyne_cells(payload) if is_het else _homodyne_cells(payload)

    cells += [
        markdown_cell("## Export\n\nWrites a CSV the app can read back."),
        code_cell(_export_cell(kind)),
    ]

    return notebook(cells, title=f"{label} ({kind})")
