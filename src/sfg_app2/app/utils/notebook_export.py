"""Generate self-contained, Colab-ready notebooks from app state.

Two kinds are produced (see the builders in `notebook_plotting` and
`notebook_processing`): one that re-plots a set of Spectra Library
spectra so the figure can be tuned freely, and one that reproduces a
matched set's processing pipeline.

Everything here is Qt-free so it can be tested without a GUI, and
every notebook is standalone: data is embedded, not referenced by path,
so it still runs on a fresh Colab runtime with no local files.
"""
from __future__ import annotations

import base64
import gzip
import io
import json
import sys
import warnings
import zipfile
from pathlib import Path

import matplotlib as mpl

# Colab preinstalls numpy/pandas/matplotlib/scipy, which is everything the
# plotting notebook needs -- it installs nothing. Kept here so the
# processing notebook (which needs more) can state the difference.
COLAB_PREINSTALLED = ("numpy", "pandas", "matplotlib", "scipy")


# ── Notebook document ─────────────────────────────────────────────────────

def markdown_cell(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": _as_source(text)}


def code_cell(text: str, *, collapsed: bool = False) -> dict:
    metadata: dict = {}
    if collapsed:
        # Colab's own key for a cell that starts folded -- used for the
        # setup blobs nobody wants to scroll past.
        metadata["cellView"] = "form"
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": metadata,
        "outputs": [],
        "source": _as_source(text),
    }


def _as_source(text: str) -> list[str]:
    """nbformat stores source as a list of lines, each keeping its own
    newline except the last."""
    lines = text.strip("\n").splitlines()
    return [line + "\n" for line in lines[:-1]] + lines[-1:] if lines else []


def notebook(cells: list[dict], *, title: str) -> dict:
    """An nbformat-v4 document with the metadata Colab expects.

    Built as a plain dict rather than via nbformat, which is a dev-only
    dependency -- the app must not gain a runtime dependency just to
    write a JSON file.
    """
    return {
        "nbformat": 4,
        "nbformat_minor": 0,
        "metadata": {
            "colab": {"provenance": [], "name": title},
            "kernelspec": {"name": "python3", "display_name": "Python 3"},
            "language_info": {"name": "python"},
        },
        "cells": cells,
    }


def write_notebook(nb: dict, path: Path):
    path = Path(path)
    path.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")


# ── Embedding ─────────────────────────────────────────────────────────────

def encode_text(text: str) -> str:
    """gzip + base64 a text payload for embedding in a source cell.

    mtime=0 keeps the output byte-identical for identical input, so
    re-exporting an unchanged figure produces an unchanged notebook.
    """
    packed = gzip.compress(text.encode("utf-8"), mtime=0)
    return base64.b64encode(packed).decode("ascii")


def decode_snippet(variable: str = "FILES") -> str:
    """The notebook-side counterpart of encode_text()."""
    return (
        f"{variable} = {{name: gzip.decompress(base64.b64decode(blob)).decode('utf-8')\n"
        f"{' ' * (len(variable) + 3)}for name, blob in _EMBEDDED.items()}}"
    )


def as_literal(value) -> str:
    """Render a value as Python source.

    repr() is right for the scalars, strings, lists and dicts that make
    up the emitted parameters and trace descriptors, but numpy scalars
    repr as `np.float64(1.0)`, which would need numpy imported at the
    point of use and reads badly in a form field.
    """
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (AttributeError, ValueError):
            pass
    if isinstance(value, dict):
        inner = ", ".join(f"{as_literal(k)}: {as_literal(v)}" for k, v in value.items())
        return "{" + inner + "}"
    if isinstance(value, (list, tuple)):
        inner = ", ".join(as_literal(v) for v in value)
        return "[" + inner + "]"
    return repr(value)


# ── Processing source bundle ──────────────────────────────────────────────

# Excluded from the bundle: fitting.py is the only lmfit user and no
# processing notebook fits; the image/SPE readers feed the image viewer,
# not the MatchedSet pipeline.
_BUNDLE_EXCLUDE = {"fitting.py", "spe_file.py", "image_file.py"}


class ProcessingSourceUnavailable(RuntimeError):
    """The processing sources needed for a notebook bundle are missing.

    Most likely a frozen build whose spec didn't ship them as data --
    PyInstaller compiles modules into its archive, so `processing/*.py`
    isn't readable from disk unless it's bundled explicitly. Raised
    rather than silently emitting an empty zip, which would only fail
    later, inside the user's notebook.
    """


def processing_source_dir() -> Path:
    """Where `sfg_app2/processing`'s .py sources can be read from.

    Mirrors the frozen/source split user_guide_dialog.py uses for the
    bundled docs.
    """
    if getattr(sys, "frozen", False):
        bundled = Path(getattr(sys, "_MEIPASS", "")) / "sfg_app2" / "processing_src"
        if bundled.is_dir():
            return bundled
    return Path(__file__).parents[2] / "processing"


def build_source_bundle() -> str:
    """The processing package as one base64 zip, for the notebook to
    unpack onto sys.path.

    Deterministic -- sorted entries, fixed timestamps -- so re-exporting
    unchanged inputs produces an unchanged notebook. This is what makes
    the processing notebook work on Colab at all: the project requires
    Python >= 3.14 and depends on PySide6, so `pip install git+...`
    would fail there, while `processing/` itself needs nothing beyond
    numpy/pandas/scipy.
    """
    source_dir = processing_source_dir()
    files = sorted(
        p for p in source_dir.rglob("*.py")
        if p.name not in _BUNDLE_EXCLUDE and "__pycache__" not in p.parts
    )
    if not files:
        raise ProcessingSourceUnavailable(
            f"No processing sources under {source_dir}. In a frozen build the "
            "spec must ship src/sfg_app2/processing as data at "
            "sfg_app2/processing_src."
        )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        # Namespace root: processing/ has no __init__.py, and sfg_app2's is
        # empty, so an empty file is enough to make the import work.
        archive.writestr(_fixed_info("sfg_app2/__init__.py"), "")
        for path in files:
            arcname = "sfg_app2/processing/" + path.relative_to(source_dir).as_posix()
            archive.writestr(_fixed_info(arcname), path.read_bytes())
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _fixed_info(arcname: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


# ── Style capture ─────────────────────────────────────────────────────────

# rcParams that describe the host GUI rather than the figure, or that
# would pin the notebook to this machine.
_RCPARAM_SKIP = {
    "backend", "interactive", "figure.facecolor", "axes.facecolor",
    "savefig.facecolor", "savefig.edgecolor", "figure.edgecolor",
    "webagg.address", "webagg.port", "docstring.hardcopy",
}


def capture_rcparams(style_name: str) -> dict:
    """The active plotting style, resolved to a literal rcParams dict.

    The app styles figures through aquarel, which isn't available on
    Colab -- but aquarel only mutates rcParams, so the resolved state
    transfers as a plain dict. Applying the style mutates the process's
    global rcParams, so this saves and restores them the way the
    settings dialog's preview does.
    """
    from sfg_app2.app.utils.plotting_settings import apply_rcparams

    original = dict(mpl.rcParams)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", mpl.MatplotlibDeprecationWarning)
            apply_rcparams(style_name)
            resolved = dict(mpl.rcParams)
    finally:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", mpl.MatplotlibDeprecationWarning)
            mpl.rcParams.update(original)

    defaults = mpl.rcParamsDefault
    out = {}
    for key, value in resolved.items():
        if key in _RCPARAM_SKIP or value == defaults.get(key):
            continue
        if key == "axes.prop_cycle":
            # A Cycler object; only its colour list survives as a literal.
            colors = value.by_key().get("color")
            if colors:
                out[key] = list(colors)
            continue
        if isinstance(value, Path):
            continue
        out[key] = value
    return out


def rcparams_snippet(rcparams: dict) -> str:
    """Source that restores a captured style, prop_cycle included."""
    colors = rcparams.get("axes.prop_cycle")
    plain = {k: v for k, v in rcparams.items() if k != "axes.prop_cycle"}

    lines = ["plt.rcParams.update({"]
    for key in sorted(plain):
        lines.append(f"    {as_literal(key)}: {as_literal(plain[key])},")
    lines.append("})")
    if colors:
        lines.append(f"plt.rcParams['axes.prop_cycle'] = cycler(color={as_literal(list(colors))})")
    return "\n".join(lines)
