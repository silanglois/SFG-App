"""Calibration against the *real* polystyrene reference, plus the
dialog that drives it.

tests/test_calibration.py covers the algorithms against synthetic
references; this file is the one that talks to refractiveindex.info, so
it's skipped when that package isn't installed.

Run with:
    uv run pytest tests/test_calibration_dialog.py -v
"""
import numpy as np
import pytest

from sfg_app2.app.utils.calibration_settings import (
    CURVE, LINES, MATERIAL, CalibrationConfig, CalibrationSettings,
)
from sfg_app2.processing.calibration import find_best_upconversion_wavelength


@pytest.fixture(scope="module")
def ps_reference():
    pytest.importorskip("refractiveindex")
    from sfg_app2.processing.calibration import polystyrene_reference
    return polystyrene_reference()


def _synthetic_ratio(true_wl: float, reference, noise: float = 0.0005, n: int = 1340):
    """A synthetic SFG ratio curve that mimics the real polystyrene
    spectrum as a spectrometer would record it for a given true
    upconversion wavelength -- Wavelength = 1e7 / (1e7/true_wl + wavenumber)."""
    wavenumber_true = np.linspace(2750.0, 3150.0, n)
    wavelength = 1e7 / (1e7 / true_wl + wavenumber_true)
    ratio = reference.sample(wavenumber_true)
    ratio = ratio + noise * np.random.default_rng(0).normal(size=n)
    return wavelength, ratio


@pytest.mark.parametrize("true_wl", [515.0, 532.0, 800.0, 1030.7])
def test_real_polystyrene_recovers_common_upconversion_sources(ps_reference, true_wl):
    wavelength, ratio = _synthetic_ratio(true_wl, ps_reference)
    best_wl, best_score = find_best_upconversion_wavelength(
        wavelength, ratio, ps_reference)
    assert best_wl is not None
    assert best_score > 0.95
    assert abs(best_wl - true_wl) < 1.0   # within one step of the coarse grid


def test_the_scan_handles_having_no_data():
    best_wl, best_score = find_best_upconversion_wavelength(
        np.array([]), np.array([]), object(),
    )
    assert best_wl is None
    assert best_score == -np.inf


# ── Remembered reference ──────────────────────────────────────────────────

def test_the_default_reference_is_still_polystyrene():
    """Someone who never touches the reference selector must get the
    calibration this app always did."""
    config = CalibrationSettings().config
    assert config.kind == MATERIAL
    assert config.book == "polystyrene"
    assert config.page == "Myers"
    assert (config.wn_min, config.wn_max) == (2750.0, 3150.0)


def test_a_chosen_reference_is_remembered():
    """Re-entering literature line positions every session is the main
    friction in using anything but the default."""
    settings = CalibrationSettings()
    assert settings.set_config(CalibrationConfig(
        kind=LINES, lines=[2850.0, 2880.0, 2920.0], wn_min=2800.0, wn_max=3000.0))

    reloaded = CalibrationSettings().config
    assert reloaded.kind == LINES
    assert reloaded.lines == [2850.0, 2880.0, 2920.0]
    assert reloaded.wn_min == 2800.0


def test_line_mode_needs_no_reference_object():
    """Its point is working without a reference database at all."""
    assert CalibrationConfig(kind=LINES, lines=[2850.0]).build_reference() is None


def test_a_curve_reference_is_built_from_its_file(tmp_path):
    path = tmp_path / "ref.csv"
    path.write_text("nu,k\n2800,0.1\n3000,0.4\n")
    reference = CalibrationConfig(kind=CURVE, curve_path=str(path)).build_reference()
    assert reference.sample(np.array([3000.0]))[0] == pytest.approx(0.4)


def test_a_curve_reference_with_no_file_says_so():
    with pytest.raises(ValueError, match="No reference curve"):
        CalibrationConfig(kind=CURVE).build_reference()


# ── The dialog ────────────────────────────────────────────────────────────

def test_the_dialog_builds_and_exposes_the_reference_modes(qtbot):
    from sfg_app2.app.dialogs.calibration_dialog import CalibrationDialog

    dialog = CalibrationDialog(matched_sets=[], initial_wavelength=1030.7)
    qtbot.addWidget(dialog)
    modes = [dialog._mode_combo.itemData(i) for i in range(dialog._mode_combo.count())]
    assert modes == [MATERIAL, CURVE, LINES]
    assert dialog.result_wavelength == 1030.7


def test_the_dialog_shows_only_the_fields_for_the_chosen_mode(qtbot):
    from sfg_app2.app.dialogs.calibration_dialog import CalibrationDialog

    dialog = CalibrationDialog(matched_sets=[], initial_wavelength=1030.7)
    qtbot.addWidget(dialog)
    dialog.show()      # visibility is only meaningful once shown

    dialog._mode_combo.setCurrentIndex(dialog._mode_combo.findData(LINES))
    assert dialog._lines_edit.isVisible()
    assert not dialog._book_edit.isVisible()

    dialog._mode_combo.setCurrentIndex(dialog._mode_combo.findData(MATERIAL))
    assert dialog._book_edit.isVisible()
    assert not dialog._lines_edit.isVisible()


def test_the_dialog_parses_typed_line_positions(qtbot):
    from sfg_app2.app.dialogs.calibration_dialog import CalibrationDialog

    dialog = CalibrationDialog(matched_sets=[], initial_wavelength=1030.7)
    qtbot.addWidget(dialog)
    dialog._mode_combo.setCurrentIndex(dialog._mode_combo.findData(LINES))
    dialog._lines_edit.setText("2850, 2880; 2920,  , junk")
    assert dialog._current_config().lines == [2850.0, 2880.0, 2920.0]
