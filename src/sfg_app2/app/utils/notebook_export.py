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
import json
import warnings
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
