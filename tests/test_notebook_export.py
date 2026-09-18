"""Tests for the notebook export.

The one that matters is `test_generated_notebook_runs_end_to_end`: a
notebook that merely parses proves nothing, so it gets executed.

Run with:
    uv run pytest tests/test_notebook_export.py -v
"""
import json

import matplotlib as mpl
import numpy as np
import pytest

from sfg_app2.app.utils import notebook_export, notebook_plotting


# ── Document shape ────────────────────────────────────────────────────────

def test_notebook_is_valid_json_with_colab_metadata(tmp_path):
    nb = notebook_export.notebook(
        [notebook_export.markdown_cell("# hi"), notebook_export.code_cell("x = 1")],
        title="demo",
    )
    path = tmp_path / "demo.ipynb"
    notebook_export.write_notebook(nb, path)

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["nbformat"] == 4
    assert loaded["metadata"]["colab"]["name"] == "demo"
    assert loaded["metadata"]["kernelspec"]["name"] == "python3"
    assert [c["cell_type"] for c in loaded["cells"]] == ["markdown", "code"]


def test_source_lines_keep_their_newlines_except_the_last():
    """nbformat stores source as lines; a trailing newline on the final
    line renders as a stray blank line in every viewer."""
    cell = notebook_export.code_cell("a = 1\nb = 2")
    assert cell["source"] == ["a = 1\n", "b = 2"]


# ── Embedding ─────────────────────────────────────────────────────────────

def test_encoding_is_deterministic():
    """Re-exporting an unchanged figure must produce an unchanged file,
    so gzip's mtime has to be pinned."""
    assert notebook_export.encode_text("payload") == notebook_export.encode_text("payload")


def test_encoded_text_round_trips():
    import base64
    import gzip

    blob = notebook_export.encode_text("wavenumber,intensity\n1,2\n")
    assert gzip.decompress(base64.b64decode(blob)).decode() == "wavenumber,intensity\n1,2\n"


def test_numpy_scalars_render_as_plain_literals():
    """repr(np.float64(1.5)) is 'np.float64(1.5)', which needs numpy in
    scope and reads badly in a Colab form field."""
    assert notebook_export.as_literal(np.float64(1.5)) == "1.5"
    assert notebook_export.as_literal(np.int64(3)) == "3"
    assert notebook_export.as_literal("text") == "'text'"


# ── Style capture ─────────────────────────────────────────────────────────

def test_capture_rcparams_restores_the_global_state():
    """apply_rcparams mutates the process's rcParams; capturing a style
    for export must not restyle the running app."""
    before = dict(mpl.rcParams)
    notebook_export.capture_rcparams("science")
    assert dict(mpl.rcParams) == before


def test_capture_rcparams_emits_the_colour_cycle_as_a_list():
    """axes.prop_cycle is a Cycler object, which has no literal form."""
    captured = notebook_export.capture_rcparams("science")
    colors = captured.get("axes.prop_cycle")
    assert isinstance(colors, list) and colors
    assert all(isinstance(c, str) for c in colors)


def test_capture_rcparams_omits_host_gui_colours():
    """figure/axes facecolor get substituted with the Qt palette colour,
    which means nothing in a notebook."""
    captured = notebook_export.capture_rcparams("science")
    assert "figure.facecolor" not in captured
    assert "axes.facecolor" not in captured


def test_rcparams_snippet_is_executable_python():
    captured = notebook_export.capture_rcparams("science")
    snippet = notebook_export.rcparams_snippet(captured)

    import matplotlib.pyplot as plt
    from cycler import cycler

    before = dict(mpl.rcParams)
    try:
        exec(snippet, {"plt": plt, "cycler": cycler})
    finally:
        mpl.rcParams.update(before)


# ── Payload -> notebook ───────────────────────────────────────────────────

def _payload(tab, entries):
    return tab._notebook_payload(entries)


def test_payload_resolves_colours_and_offsets(load_entries, make_homodyne_entry):
    tab = load_entries(
        make_homodyne_entry(label="a"),
        make_homodyne_entry(label="b"),
    )
    payload = _payload(tab, tab._checked_entries())

    assert [t["entry"] for t in payload["traces"]] == ["a", "b"]
    # Offset slots are per entry, matching the figure.
    assert [t["offset_slot"] for t in payload["traces"]] == [0, 1]
    assert all(t["color"].startswith("#") for t in payload["traces"])


def test_phase_trace_is_flagged_for_the_twin_axis(load_entries, make_heterodyne_entry):
    tab = load_entries(make_heterodyne_entry(label="het"))
    tab._hd_checkboxes["Phase"].setChecked(True)
    payload = _payload(tab, tab._checked_entries())

    phase = [t for t in payload["traces"] if t["column"] == "Phase"]
    assert len(phase) == 1
    assert phase[0]["secondary"] is True
    assert phase[0]["is_phase"] is True


def test_embedded_csv_carries_the_provenance_header(load_entries, make_homodyne_entry):
    tab = load_entries(make_homodyne_entry(label="a"))
    payload = _payload(tab, tab._checked_entries())
    assert payload["entries"][0]["csv"].startswith("# SFG-App export")


def test_built_notebook_has_no_fit_section_without_fits(load_entries, make_homodyne_entry):
    tab = load_entries(make_homodyne_entry())
    nb = notebook_plotting.build(_payload(tab, tab._checked_entries()))
    sources = "".join("".join(c["source"]) for c in nb["cells"])
    assert "Fit parameters" not in sources


def test_built_notebook_adds_a_fit_section_when_fits_are_plotted(load_entries, make_fitted_entry):
    tab = load_entries(make_fitted_entry())
    tab._fit_checkboxes["Fit total"].setChecked(True)
    nb = notebook_plotting.build(_payload(tab, tab._checked_entries()))
    sources = "".join("".join(c["source"]) for c in nb["cells"])
    assert "Fit parameters" in sources


def test_notebook_installs_nothing(load_entries, make_homodyne_entry):
    """The plotting notebook must be zero-install: everything it imports
    is preinstalled on Colab."""
    tab = load_entries(make_homodyne_entry())
    nb = notebook_plotting.build(_payload(tab, tab._checked_entries()))
    sources = "".join("".join(c["source"]) for c in nb["cells"])
    assert "pip install" not in sources


# ── The one that matters ──────────────────────────────────────────────────

@pytest.mark.slow
def test_generated_notebook_runs_end_to_end(load_entries, make_homodyne_entry,
                                            make_heterodyne_entry, tmp_path):
    """Generate a notebook from live tab state and execute it.

    Covers both spectrum kinds, a twin-axis Phase trace and error bands,
    since those are where the reproduction is most likely to drift from
    what the app draws.
    """
    nbformat = pytest.importorskip("nbformat")
    nbclient = pytest.importorskip("nbclient")

    tab = load_entries(
        make_homodyne_entry(label="sample_ssp"),
        make_heterodyne_entry(label="gold_ref"),
    )
    tab._hd_checkboxes["Phase"].setChecked(True)
    tab.ui.hdCheckShowError.setChecked(True)
    tab.ui.offsetSpectraSpinner.setValue(0.5)
    tab._refresh_plot()

    payload = tab._notebook_payload(tab._checked_entries())
    payload["output_name"] = str(tmp_path / "figure")
    path = tmp_path / "exported.ipynb"
    notebook_export.write_notebook(notebook_plotting.build(payload), path)

    nb = nbformat.read(path, as_version=4)
    nbclient.NotebookClient(
        nb, timeout=180, kernel_name="python3", resources={"metadata": {"path": str(tmp_path)}},
    ).execute()

    errors = [o for cell in nb.cells for o in cell.get("outputs", [])
              if o.get("output_type") == "error"]
    assert not errors, errors[0].get("evalue")

    figures = [o for cell in nb.cells for o in cell.get("outputs", [])
               if "image/png" in o.get("data", {})]
    assert figures, "notebook ran but rendered no figure"
    assert (tmp_path / "figure.png").exists(), "save cell wrote nothing"
