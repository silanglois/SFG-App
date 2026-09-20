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
    code = "".join("".join(c["source"]) for c in nb["cells"]
                   if c["cell_type"] == "code")
    assert "pip install" not in code


# ── The export handlers ───────────────────────────────────────────────────
# Driving the real slots, not just the builders: the first version of
# this feature used show_loading() as a context manager (it isn't one,
# it returns a dialog the caller must close), which crashed on the very
# first click while every builder-level test still passed.

@pytest.fixture
def silent_dialogs(monkeypatch, tmp_path):
    """Stub the file picker and the confirmation popup."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    target = tmp_path / "exported.ipynb"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(target), "Jupyter Notebook (*.ipynb)")),
    )
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    return target


def test_plotting_export_handler_writes_a_notebook(load_entries, make_homodyne_entry,
                                                   silent_dialogs):
    tab = load_entries(make_homodyne_entry())
    tab._on_export_notebook()

    assert silent_dialogs.exists(), "handler ran but wrote nothing"
    assert json.loads(silent_dialogs.read_text(encoding="utf-8"))["nbformat"] == 4


def test_plotting_export_handler_refuses_an_empty_selection(load_entries,
                                                            make_homodyne_entry,
                                                            silent_dialogs):
    tab = load_entries(make_homodyne_entry(checked=False))
    tab._on_export_notebook()
    assert not silent_dialogs.exists()


def test_processing_export_handler_writes_a_notebook(qtbot, raw_matched_files,
                                                     silent_dialogs):
    from sfg_app2.app.tabs.process_review import ProcessReviewTab
    from sfg_app2.processing.data_file import DataFile
    from sfg_app2.processing.matcher import MatchedSet

    folder, roles = raw_matched_files()
    matched = MatchedSet(
        signal=DataFile(folder / roles["signal"]),
        background=DataFile(folder / roles["background"]),
        reference=DataFile(folder / roles["reference"]),
        reference_background=DataFile(folder / roles["reference_background"]),
        spectrum_type="homodyne",
    )
    tab = ProcessReviewTab()
    qtbot.addWidget(tab)
    tab.set_matched_sets([matched])

    tab._on_export_processing_notebook(matched, 0)

    assert silent_dialogs.exists(), "handler ran but wrote nothing"
    nb = json.loads(silent_dialogs.read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4
    assert any("step_despike" in "".join(c["source"]) or "remove_cosmic_rays" in "".join(c["source"])
               for c in nb["cells"])


# ── Hidden plumbing cells ─────────────────────────────────────────────────

def _is_hidden(cell: dict) -> bool:
    meta = cell["metadata"]
    return (meta.get("cellView") == "form"
            and meta.get("jupyter", {}).get("source_hidden") is True
            and cell["source"][0].startswith("#@title "))


def test_hidden_cell_carries_both_front_ends_and_titles_the_bar():
    """Colab collapses on cellView + a #@title that must be the *first*
    line; JupyterLab reads jupyter.source_hidden instead."""
    cell = notebook_export.code_cell("x = 1", hidden_title="Plumbing")
    assert cell["metadata"]["cellView"] == "form"
    assert cell["metadata"]["jupyter"] == {"source_hidden": True}
    assert cell["source"][0] == '#@title Plumbing { display-mode: "form" }\n'
    assert "x = 1" in "".join(cell["source"])


def test_plain_code_cell_is_not_hidden():
    assert notebook_export.code_cell("x = 1")["metadata"] == {}


def test_processing_setup_splits_into_three_hideable_cells(process_tab):
    """The package blob gets its own cell so it collapses independently
    of the data and the setup logic."""
    tab, matched = process_tab("homodyne")
    from sfg_app2.app.utils import notebook_processing
    cells = notebook_processing.build(tab._notebook_payload(matched, 0))["cells"]

    hidden = {c["source"][0]: "".join(c["source"])
              for c in cells if c["cell_type"] == "code" and _is_hidden(c)}
    titles = sorted(line.split("#@title ")[1].split(" {")[0] for line in hidden)
    assert titles == ["Embedded processing package (source zip)",
                      "Embedded raw data (4 files)",
                      "Unpack everything and import"]

    package = next(src for line, src in hidden.items() if "package" in line)
    assert "_PACKAGE = " in package
    assert "_RAW_FILES" not in package, "blob must hide on its own"


def test_plotting_hides_blobs_and_helpers_but_not_the_editable_cells(
        load_entries, make_homodyne_entry):
    tab = load_entries(make_homodyne_entry())
    nb = notebook_plotting.build(tab._notebook_payload(tab._checked_entries()))
    code = [c for c in nb["cells"] if c["cell_type"] == "code"]

    hidden = ["".join(c["source"]) for c in code if _is_hidden(c)]
    assert any("_EMBEDDED" in s for s in hidden)
    assert any("wrap_phase_for_plot" in s for s in hidden)
    assert any("import matplotlib" in s for s in hidden)

    # The cells the notebook exists for stay open.
    shown = ["".join(c["source"]) for c in code if not _is_hidden(c)]
    assert any("#@param" in s for s in shown), "parameter form must stay readable"
    assert any("# TRACE" in s for s in shown)
    assert any("# DECORATE" in s for s in shown)


def test_processing_stage_cells_stay_visible(process_tab):
    tab, matched = process_tab("homodyne")
    from sfg_app2.app.utils import notebook_processing
    cells = notebook_processing.build(tab._notebook_payload(matched, 0))["cells"]

    shown = ["".join(c["source"]) for c in cells
             if c["cell_type"] == "code" and not _is_hidden(c)]
    assert any("# COMPUTE" in s for s in shown)
    assert any("# PLOT" in s for s in shown)
    assert any("#@param" in s for s in shown)


# ── Fidelity: the notebook must not silently disagree with the app ────────
# Each parameter below was once dropped on the way to the notebook, which
# then fell back to a library default. The notebook still ran and still
# produced a plausible figure -- it just wasn't the app's result. Only a
# test that reads the value back out of the generated notebook catches
# that class of bug.

@pytest.fixture
def process_tab(qtbot, raw_matched_files):
    """A Process & Review tab holding one matched set of the given kind."""
    from sfg_app2.app.tabs.process_review import ProcessReviewTab
    from sfg_app2.processing.data_file import DataFile
    from sfg_app2.processing.matcher import MatchedSet

    def _make(kind="homodyne"):
        folder, roles = raw_matched_files(fringes=(kind == "heterodyne"))
        matched = MatchedSet(
            signal=DataFile(folder / roles["signal"]),
            background=DataFile(folder / roles["background"]),
            reference=DataFile(folder / roles["reference"]),
            reference_background=DataFile(folder / roles["reference_background"]),
            spectrum_type=kind,
        )
        tab = ProcessReviewTab()
        qtbot.addWidget(tab)
        tab.set_matched_sets([matched])
        if kind == "heterodyne":
            tab._hd_sfg_panel.set_matched_set(matched, 0)
        return tab, matched

    return _make


def _processing_source(tab, matched, idx=0) -> str:
    from sfg_app2.app.utils import notebook_processing
    nb = notebook_processing.build(tab._notebook_payload(matched, idx))
    return "".join("".join(c["source"]) for c in nb["cells"])


def test_exposure_times_reach_the_notebook(process_tab):
    """chi is multiplied by (reference / sample) exposure, so dropping
    these rescales the entire result -- 10x at the stock defaults."""
    tab, matched = process_tab("heterodyne")
    tab._hd_sfg_panel._sample_exp.setValue(42.0)
    tab._hd_sfg_panel._ref_exp.setValue(7.0)

    config = tab._notebook_payload(matched, 0)["config"]
    assert config["sample_exposure"] == 42.0
    assert config["reference_exposure"] == 7.0

    source = _processing_source(tab, matched)
    assert "SAMPLE_EXPOSURE_S = 42.0" in source
    assert "REFERENCE_EXPOSURE_S = 7.0" in source


def test_heterodyne_excluded_frames_reach_the_notebook(process_tab):
    """The panel keys the reference background 'ref_background' but
    step_average() reads 'reference_background' -- the translation has to
    survive into the notebook or those exclusions quietly do nothing."""
    tab, matched = process_tab("heterodyne")
    tab._hd_sfg_panel._set_exclude_frames(0, "signal", {2})
    tab._hd_sfg_panel._set_exclude_frames(0, "ref_background", {1})

    excluded = tab._notebook_payload(matched, 0)["config"]["exclude_frames"]
    assert excluded["signal"] == [2]
    assert excluded["reference_background"] == [1], "pipeline's key, not the panel's"

    source = _processing_source(tab, matched).replace('"', "'")
    assert "'signal': [2]" in source
    assert "'reference_background': [1]" in source


def test_homodyne_excluded_frames_reach_the_notebook(process_tab):
    tab, matched = process_tab("homodyne")
    tab._homodyne_panel._set_exclude_frames(0, "signal", {2})

    payload = tab._notebook_payload(matched, 0)
    assert payload["config"]["exclude_frames"] == {"signal": [2]}
    source = _processing_source(tab, matched)
    assert "EXCLUDE_FRAMES = {'signal': [2]}" in source
    # ...and is actually applied, not just defined.
    assert "average_spectrum(exclude_frames=EXCLUDE_FRAMES.get(name))" in source


def test_type_4_mask_geometry_reaches_the_notebook(process_tab):
    """WINDOW_TYPE 4 is selectable in the notebook, so the mask geometry
    behind it has to travel too."""
    tab, matched = process_tab("heterodyne")
    tab._hd_sfg_panel._mask_start.setValue(123)
    source = _processing_source(tab, matched)
    assert "mask_start=123" in source


def test_markers_mode_reaches_the_plotting_payload(load_entries, make_homodyne_entry):
    """'Show data as markers' is applied when drawing, so a notebook that
    ignores it draws lines where the screen shows points."""
    tab = load_entries(make_homodyne_entry())
    tab._markers_checkbox.setChecked(True)

    trace = tab._notebook_payload(tab._checked_entries())["traces"][0]
    assert trace["marker"] == "o"
    assert trace["linestyle"] == "None"


def test_markers_mode_does_not_touch_fits(load_entries, make_fitted_entry):
    """Only data traces become markers -- fits stay as lines, matching
    _draw_specs."""
    tab = load_entries(make_fitted_entry())
    tab._fit_checkboxes["Fit total"].setChecked(True)
    tab._markers_checkbox.setChecked(True)

    fits = [t for t in tab._notebook_payload(tab._checked_entries())["traces"]
            if t["is_fit"]]
    assert fits and all(t["marker"] != "o" for t in fits)


def test_heterodyne_notebook_plots_amplitude_and_error_bands(process_tab):
    """The app's HD-SFG panel offers |chi|^2 and 95% CI bands; the
    notebook should not quietly drop them."""
    tab, matched = process_tab("heterodyne")
    source = _processing_source(tab, matched)
    assert "result.homodyne" in source
    assert "result.imag_err" in source and "result.real_err" in source


def test_notebook_records_where_it_came_from(process_tab):
    tab, matched = process_tab("homodyne")
    source = _processing_source(tab, matched)
    assert f"SFG-App {notebook_export.app_version()}" in source
    assert "sample_ssp_sfg.csv" in source


# ── Processing source bundle ──────────────────────────────────────────────

def test_bundle_is_deterministic():
    """Re-exporting unchanged inputs must produce an unchanged notebook,
    so zip entry order and timestamps have to be pinned."""
    assert notebook_export.build_source_bundle() == notebook_export.build_source_bundle()


def test_bundle_carries_the_pipeline_but_not_the_fitting_code():
    import base64
    import io
    import zipfile

    names = zipfile.ZipFile(
        io.BytesIO(base64.b64decode(notebook_export.build_source_bundle()))
    ).namelist()

    assert "sfg_app2/__init__.py" in names, "namespace root needed for the import to work"
    assert any(n.endswith("processing/data_file.py") for n in names)
    assert any(n.endswith("hd_sfg/steps.py") for n in names)
    # lmfit isn't on Colab and no processing notebook fits.
    assert not any("fitting.py" in n for n in names)


def test_missing_sources_raise_rather_than_shipping_an_empty_bundle(monkeypatch, tmp_path):
    """The frozen build is the case that bites: PyInstaller compiles
    modules into its archive, so the .py sources are unreadable unless
    the spec ships them. That must fail loudly here, not later inside
    the user's notebook.
    """
    monkeypatch.setattr(notebook_export, "processing_source_dir", lambda: tmp_path / "gone")
    with pytest.raises(notebook_export.ProcessingSourceUnavailable):
        notebook_export.build_source_bundle()


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


def _run_notebook(path, workdir):
    """Execute a notebook in `workdir`, returning it with outputs."""
    nbformat = pytest.importorskip("nbformat")
    nbclient = pytest.importorskip("nbclient")

    nb = nbformat.read(path, as_version=4)
    nbclient.NotebookClient(
        nb, timeout=300, kernel_name="python3",
        resources={"metadata": {"path": str(workdir)}},
    ).execute()
    errors = [o for cell in nb.cells for o in cell.get("outputs", [])
              if o.get("output_type") == "error"]
    assert not errors, f"{errors[0].get('ename')}: {errors[0].get('evalue')}"
    return nb


def _processing_payload(kind, folder, roles, **config):
    base = {"label": "sample_ssp", "upconversion_wavelength": 1030.7}
    return {
        "kind": kind,
        "label": "sample_ssp",
        "roles": roles,
        "raw_files": {name: (folder / name).read_text(encoding="utf-8")
                      for name in roles.values()},
        "config": {**base, **config},
        "style_rcparams": notebook_export.capture_rcparams("science"),
    }


@pytest.mark.slow
def test_homodyne_processing_notebook_runs_end_to_end(raw_matched_files, tmp_path):
    """Generate a homodyne processing notebook and execute it.

    This is what proves the embedded package actually imports and the
    pipeline calls are spelled correctly -- a generated notebook that
    only parses would hide both.
    """
    from sfg_app2.app.utils import notebook_processing

    folder, roles = raw_matched_files(fringes=False)
    payload = _processing_payload(
        "homodyne", folder, roles, despike_window=5, despike_threshold=3.0, bg_offset=None,
    )
    path = tmp_path / "homodyne.ipynb"
    notebook_export.write_notebook(notebook_processing.build(payload), path)

    nb = _run_notebook(path, tmp_path)

    figures = [o for cell in nb.cells for o in cell.get("outputs", [])
               if "image/png" in o.get("data", {})]
    assert len(figures) >= 4, "every pipeline stage should plot its own result"

    out = tmp_path / "sample_ssp.csv"
    assert out.exists(), "export cell wrote nothing"

    # The export must be loadable by the app, which is the whole point of
    # writing a provenance header rather than a plain CSV.
    from sfg_app2.processing import provenance
    df = provenance.load_csv_skip_comments(out)
    _, prov, _ = provenance.parse_export_header(out)
    assert "Wavenumber" in df.columns and len(df) > 0
    assert "normalize" in prov["history_list"]
    assert "upconvert" in " ".join(prov["history_list"])


@pytest.mark.slow
def test_heterodyne_processing_notebook_runs_end_to_end(raw_matched_files, tmp_path):
    from sfg_app2.app.utils import notebook_processing

    folder, roles = raw_matched_files(fringes=True)
    payload = _processing_payload(
        "heterodyne", folder, roles,
        despike_window=50, despike_threshold=10.0,
        bg_smoothing_window=0, bg_smoothing_order=3, bg_offset=None,
        edge_left=15, edge_right=15, window_type=3,
        fft_start=30, fft_end=110, hg_left=10, hg_right=10,
        phase_correction_deg=0.0,
    )
    path = tmp_path / "heterodyne.ipynb"
    notebook_export.write_notebook(notebook_processing.build(payload), path)

    nb = _run_notebook(path, tmp_path)

    figures = [o for cell in nb.cells for o in cell.get("outputs", [])
               if "image/png" in o.get("data", {})]
    assert len(figures) >= 3
    assert (tmp_path / "sample_ssp.csv").exists()


@pytest.mark.slow
def test_processing_notebook_needs_no_network_or_install(raw_matched_files, tmp_path):
    """The embedded package is the whole reason this works on Colab:
    the project requires Python >= 3.14 and pulls in PySide6, so
    `pip install git+...` would fail there."""
    from sfg_app2.app.utils import notebook_processing

    folder, roles = raw_matched_files()
    payload = _processing_payload("homodyne", folder, roles,
                                  despike_window=5, despike_threshold=3.0)
    nb = notebook_processing.build(payload)
    # Code only -- the prose says "no pip install", which would match.
    code = "".join("".join(c["source"]) for c in nb["cells"]
                   if c["cell_type"] == "code")
    assert "pip install" not in code
    assert "git+" not in code
