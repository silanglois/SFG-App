import numpy as np
import pytest

pytest.importorskip("refractiveindex")

from sfg_app2.app.dialogs.polystyrene_calibration_dialog import (
    find_best_upconversion_wavelength, _get_polystyrene_material,
)


@pytest.fixture(scope="module")
def ps_material():
    return _get_polystyrene_material()


def _synthetic_ratio(true_wl: float, ps_material, noise: float = 0.0005, n: int = 1340):
    """Builds a synthetic SFG ratio curve that mimics the real
    polystyrene extinction spectrum as it would appear on a
    spectrometer's own wavelength axis for a given true upconversion
    wavelength -- Wavelength = 1e7 / (1e7/true_wl + wavenumber)."""
    wavenumber_true = np.linspace(2750.0, 3150.0, n)
    wavelength = 1e7 / (1e7 / true_wl + wavenumber_true)
    ratio = ps_material.get_extinction_coefficient(wavenumber_true, unit="cm-1")
    ratio = ratio + noise * np.random.default_rng(0).normal(size=n)
    return wavelength, ratio


@pytest.mark.parametrize("true_wl", [515.0, 532.0, 800.0, 1030.7])
def test_find_best_upconversion_wavelength_recovers_common_sources(ps_material, true_wl):
    wavelength, ratio = _synthetic_ratio(true_wl, ps_material)
    best_wl, best_score = find_best_upconversion_wavelength(wavelength, ratio, ps_material)
    assert best_wl is not None
    assert best_score > 0.95
    assert abs(best_wl - true_wl) < 1.0   # within one scan step of the coarse grid


def test_find_best_upconversion_wavelength_handles_no_data():
    best_wl, best_score = find_best_upconversion_wavelength(
        np.array([]), np.array([]), object(),
    )
    assert best_wl is None
    assert best_score == -np.inf
