"""One representative call site per category, confirming the real
dialog handlers (not just the settings module in isolation) actually
read and write recent_paths_settings.

isolate_user_config (conftest.py, autouse) keeps this off the real
user's config.
"""
from PySide6.QtWidgets import QFileDialog

from sfg_app2.app.utils import recent_paths_settings as rps


def _stub_dialog(monkeypatch, method_name, ret):
    """Stub a QFileDialog static method, capturing the args it's called
    with (index 2 is always the `dir` argument at every call site)."""
    captured = {}

    def fake(*args, **kwargs):
        captured["args"] = args
        return ret

    monkeypatch.setattr(QFileDialog, method_name, staticmethod(fake))
    return captured


# ── Spectra Library ("spectra_library") ────────────────────────────────────

def test_add_from_file_reads_and_remembers_spectra_library_dir(
        results_tab, tmp_path, monkeypatch):
    remembered = tmp_path / "already_remembered"
    remembered.mkdir()
    rps.remember_dir("spectra_library", remembered)

    csv_path = tmp_path / "new_folder" / "sample.csv"
    csv_path.parent.mkdir()
    csv_path.write_text("Wavenumber,Intensity\n2800.0,1.0\n")
    captured = _stub_dialog(monkeypatch, "getOpenFileNames", ([str(csv_path)], ""))

    results_tab._on_add_from_file()

    assert captured["args"][2] == str(remembered)
    assert rps.get_last_dir("spectra_library") == str(csv_path.parent)


# ── Figures (Save Plot / notebook export, "figures") ───────────────────────

def test_save_plot_reads_and_remembers_figures_dir(qtbot, tmp_path, monkeypatch):
    from sfg_app2.app.widgets.spectrum_plot_widget import SpectrumPlotWidget
    from sfg_app2.app.dialogs.save_plot_dialog import SavePlotDialog
    from PySide6.QtWidgets import QDialog

    widget = SpectrumPlotWidget()
    qtbot.addWidget(widget)
    widget.plot([1, 2, 3], [4, 5, 6], label="alpha")

    remembered = tmp_path / "figs_before"
    remembered.mkdir()
    rps.remember_dir("figures", remembered)

    monkeypatch.setattr(SavePlotDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(SavePlotDialog, "selected_format", lambda self: "png")
    monkeypatch.setattr(SavePlotDialog, "export", lambda self, path: None)
    out_path = tmp_path / "new_figs" / "out.png"
    out_path.parent.mkdir()
    captured = _stub_dialog(monkeypatch, "getSaveFileName", (str(out_path), ""))

    widget._on_save_plot()

    assert captured["args"][2] == str(remembered)
    assert rps.get_last_dir("figures") == str(out_path.parent)


# ── Fitting tab ("fitting") ─────────────────────────────────────────────────

def test_load_files_into_reads_and_remembers_fitting_dir(qtbot, tmp_path, monkeypatch):
    from sfg_app2.app.tabs.fitting_tab import FittingTab

    tab = FittingTab()
    qtbot.addWidget(tab)

    remembered = tmp_path / "fitting_before"
    remembered.mkdir()
    rps.remember_dir("fitting", remembered)

    csv_path = tmp_path / "fitting_after" / "spectrum.csv"
    csv_path.parent.mkdir()
    csv_path.write_text("Wavenumber,Intensity\n2800.0,1.0\n2850.0,1.1\n")
    captured = _stub_dialog(monkeypatch, "getOpenFileNames", ([str(csv_path)], ""))

    tab._load_files_into(tab._batch_list, tab._batch_file_entries, checkable=False)

    assert captured["args"][2] == str(remembered)
    assert rps.get_last_dir("fitting") == str(csv_path.parent)


# ── Calibration ("calibration") ─────────────────────────────────────────────

def test_browse_curve_reads_and_remembers_calibration_dir(qtbot, tmp_path, monkeypatch):
    from sfg_app2.app.dialogs.calibration_dialog import CalibrationDialog

    dialog = CalibrationDialog(matched_sets=[], initial_wavelength=1030.7)
    qtbot.addWidget(dialog)

    remembered = tmp_path / "calib_before"
    remembered.mkdir()
    rps.remember_dir("calibration", remembered)

    curve_path = tmp_path / "calib_after" / "reference.csv"
    curve_path.parent.mkdir()
    curve_path.write_text("Wavenumber,Intensity\n2800.0,1.0\n")
    captured = _stub_dialog(monkeypatch, "getOpenFileName", (str(curve_path), ""))

    dialog._on_browse_curve()

    assert captured["args"][2] == str(remembered)
    assert rps.get_last_dir("calibration") == str(curve_path.parent)
