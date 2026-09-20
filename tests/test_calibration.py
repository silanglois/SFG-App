"""Upconversion-wavelength calibration against a known reference.

Every test here works by hiding a known lambda_upconversion inside
synthetic data and checking the scan finds it: that is the only claim
the feature actually makes.

Run with:
    uv run pytest tests/test_calibration.py -v
"""
import numpy as np
import pytest

from sfg_app2.processing.calibration import (
    CurveReference, DEFAULT_WINDOW, detect_peaks,
    find_best_upconversion_wavelength, find_upconversion_from_lines,
    load_reference_csv, to_wavenumber,
)

TRUE_WAVELENGTH = 1030.7
LINES = [2850.0, 2880.0, 2920.0, 3060.0]
SCAN_STEP = 0.25        # the scan can't do better than its own grid


def _bands(wavenumber, centers, width=8.0):
    return sum(np.exp(-0.5 * ((wavenumber - c) / width) ** 2) for c in centers)


@pytest.fixture
def measured():
    """A ratio curve whose peaks sit at LINES, given TRUE_WAVELENGTH."""
    wavelength = np.linspace(780.0, 815.0, 1200)
    wavenumber = to_wavenumber(wavelength, TRUE_WAVELENGTH)
    rng = np.random.default_rng(0)
    intensity = _bands(wavenumber, LINES) + rng.normal(0.0, 0.01, wavenumber.size)
    return wavelength, intensity


@pytest.fixture
def reference_curve():
    grid = np.linspace(2600.0, 3300.0, 3000)
    return CurveReference(grid, _bands(grid, LINES), name="synthetic")


# ── Correlating against a reference curve ─────────────────────────────────

def test_the_curve_scan_recovers_the_true_wavelength(measured, reference_curve):
    wavelength, intensity = measured
    best, score = find_best_upconversion_wavelength(
        wavelength, intensity, reference_curve)
    assert best == pytest.approx(TRUE_WAVELENGTH, abs=SCAN_STEP)
    assert score > 0.9


def test_any_object_with_sample_works_as_a_reference(measured):
    """The scan is not tied to refractiveindex, or to polystyrene --
    that's the whole point of this phase."""
    wavelength, intensity = measured

    class Stub:
        name = "stub"

        def sample(self, wavenumber):
            return _bands(np.asarray(wavenumber), LINES)

    best, _ = find_best_upconversion_wavelength(wavelength, intensity, Stub())
    assert best == pytest.approx(TRUE_WAVELENGTH, abs=SCAN_STEP)


def test_a_reference_that_cannot_be_sampled_scores_nothing(measured):
    wavelength, intensity = measured

    class Broken:
        def sample(self, wavenumber):
            raise RuntimeError("no data")

    assert find_best_upconversion_wavelength(wavelength, intensity, Broken()) == (None, -np.inf)


def test_a_curve_reference_does_not_extrapolate(reference_curve):
    """Clamping outside the tabulated range would invent a flat
    shoulder for the correlation to score against."""
    sampled = reference_curve.sample(np.array([1000.0, 2900.0, 9000.0]))
    assert np.isnan(sampled[0]) and np.isnan(sampled[2])
    assert np.isfinite(sampled[1])


def test_the_analysis_window_can_be_narrowed(measured, reference_curve):
    wavelength, intensity = measured
    best, _ = find_best_upconversion_wavelength(
        wavelength, intensity, reference_curve, wn_min=2800.0, wn_max=2950.0)
    assert best == pytest.approx(TRUE_WAVELENGTH, abs=1.0)


# ── Matching known line positions ─────────────────────────────────────────

def test_the_line_scan_recovers_the_true_wavelength(measured):
    """No tabulated curve needed -- just published peak positions."""
    wavelength, intensity = measured
    best, rms = find_upconversion_from_lines(wavelength, intensity, LINES)
    assert best == pytest.approx(TRUE_WAVELENGTH, abs=SCAN_STEP)
    assert rms < 5.0


def test_line_matching_tolerates_peaks_the_list_does_not_mention(measured):
    """Real measurements show extra peaks. Scoring line-to-nearest-peak
    (rather than the reverse) means those don't fight the fit."""
    wavelength, intensity = measured
    best, _ = find_upconversion_from_lines(wavelength, intensity, LINES[:2])
    assert best == pytest.approx(TRUE_WAVELENGTH, abs=1.0)


def test_line_matching_reports_error_not_correlation(measured):
    """Its score is an RMS distance, so lower is better and the
    empty answer is +inf -- the opposite of the curve scan, which is
    exactly the kind of thing a caller gets backwards."""
    wavelength, intensity = measured
    assert find_upconversion_from_lines(wavelength, intensity, []) == (None, np.inf)


def test_detect_peaks_finds_the_bands_that_are_there():
    wavenumber = np.linspace(2700.0, 3200.0, 4000)
    found = np.sort(detect_peaks(wavenumber, _bands(wavenumber, LINES)))
    assert len(found) == len(LINES)
    assert found == pytest.approx(LINES, abs=1.0)


def test_detect_peaks_survives_a_flat_or_empty_curve():
    wavenumber = np.linspace(2700.0, 3200.0, 100)
    assert detect_peaks(wavenumber, np.zeros(100)).size == 0
    assert detect_peaks(np.array([1.0]), np.array([np.nan])).size == 0


# ── Reference curves from file ────────────────────────────────────────────

def test_a_two_column_csv_loads_as_a_reference(tmp_path):
    path = tmp_path / "ref.csv"
    path.write_text("wavenumber,k\n2800,0.1\n2900,0.9\n3000,0.2\n")
    reference = load_reference_csv(path)
    assert reference.name == "ref"
    assert reference.sample(np.array([2900.0]))[0] == pytest.approx(0.9)


def test_a_reference_csv_header_may_be_anything(tmp_path):
    """These come from published data and spreadsheets, not from this
    app, so the column names are whatever they are."""
    path = tmp_path / "ref.csv"
    path.write_text("nu (cm-1),absorbance\n2800,0.1\n3000,0.4\n")
    assert load_reference_csv(path).sample(np.array([2800.0]))[0] == pytest.approx(0.1)


def test_a_semicolon_separated_reference_csv_loads(tmp_path):
    """Reference curves get the same separator tolerance as data files,
    by going through the same reader -- they come from elsewhere too."""
    path = tmp_path / "ref.csv"
    path.write_text("nu;k\n2800;0.1\n3000;0.4\n")
    assert load_reference_csv(path).sample(np.array([3000.0]))[0] == pytest.approx(0.4)


def test_a_one_column_file_is_refused_clearly(tmp_path):
    path = tmp_path / "ref.csv"
    path.write_text("wavenumber\n2800\n2900\n")
    with pytest.raises(ValueError, match="two numeric columns"):
        load_reference_csv(path)


def test_the_default_window_is_the_ch_stretch_region():
    assert DEFAULT_WINDOW == (2750.0, 3150.0)
