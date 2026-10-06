"""Background smoothing: the method registry, the conventional/phase-resolved
pipeline hooks, and the provenance round trip."""
import json

import numpy as np
import pandas as pd
import pytest

from sfg_app2.processing import provenance
from sfg_app2.processing.baseline import apply_offset, subtract_background
from sfg_app2.processing.pr_sfg.config import PRSFGConfig
from sfg_app2.processing.pr_sfg.steps import AveragedData, step_bg_smooth
from sfg_app2.processing.processed_spectrum import ProcessedSpectrum
from sfg_app2.processing.smoothing import SmoothingSpec, smooth, smoothing_methods

_X = np.linspace(0, 4 * np.pi, 400)
_CLEAN = np.sin(_X)


def _noisy(seed=0):
    return _CLEAN + np.random.default_rng(seed).normal(0, 0.2, _X.size)


@pytest.mark.parametrize("method", [m.key for m in smoothing_methods() if m.key != "none"])
def test_every_method_reduces_noise(method):
    y = _noisy()
    out = smooth(y, SmoothingSpec(method))
    assert out.shape == y.shape
    assert np.std(out - _CLEAN) < 0.6 * np.std(y - _CLEAN)


def test_none_is_identity():
    y = _noisy()
    np.testing.assert_array_equal(smooth(y, SmoothingSpec()), y)
    np.testing.assert_array_equal(smooth(y, None), y)


def test_windows_are_clamped_and_forced_odd():
    y = _noisy()[:10]
    # A window far longer than the data, and an even one, both still work.
    assert smooth(y, SmoothingSpec("savgol", {"window": 501, "order": 3})).shape == y.shape
    assert smooth(y, SmoothingSpec("moving_average", {"window": 4})).shape == y.shape
    # savgol order >= window would raise inside scipy; it's kept below.
    assert smooth(y, SmoothingSpec("savgol", {"window": 5, "order": 9})).shape == y.shape


def test_spec_round_trips_and_fills_defaults():
    spec = SmoothingSpec("gaussian", {"sigma": 2.5})
    assert SmoothingSpec.from_dict(spec.to_dict()) == spec
    assert SmoothingSpec("savgol").params == {"window": 11, "order": 3}
    assert SmoothingSpec.from_dict({"method": "savgol", "window": "7"}).params["window"] == 7
    assert "window 11" in SmoothingSpec("savgol").describe()


def test_unknown_method_falls_back_to_none():
    spec = SmoothingSpec.from_dict({"method": "wavelet", "level": 3})
    assert spec.method == "none" and not spec.is_active


def _spectrum(intensity):
    wl = np.linspace(780.0, 800.0, intensity.size)
    df = pd.DataFrame({"Frame": 1, "Wavelength": wl, "Intensity": intensity})
    return ProcessedSpectrum(df, metadata={}, history=[], provenance={})


def test_conventional_background_is_smoothed_before_offset():
    bg = _spectrum(_noisy() + 10)
    plain = apply_offset(bg, 1.0).data["Intensity"].to_numpy()
    smoothed = apply_offset(bg, 1.0, SmoothingSpec("savgol", {"window": 31, "order": 2}))
    smoothed = smoothed.data["Intensity"].to_numpy()
    assert np.std(smoothed - (_CLEAN + 11)) < np.std(plain - (_CLEAN + 11))

    signal = _spectrum(np.full(_X.size, 20.0))
    out = subtract_background(signal, bg, smoothing={"method": "median", "window": 9})
    np.testing.assert_allclose(
        out.data["Intensity"].to_numpy(),
        20.0 - smooth(bg.data["Intensity"].to_numpy(), {"method": "median", "window": 9}),
    )


def _averaged():
    n = _X.size
    return AveragedData(
        wavenumber=np.linspace(3000, 2800, n), sig_frames=[np.ones(n)], sig_avg=np.ones(n),
        bg_avg=_noisy(1), ref_avg=np.ones(n), ref_bg_avg=_noisy(2), n_sig_frames=1,
    )


def test_phase_resolved_backgrounds_use_their_own_specs():
    averaged = _averaged()
    cfg = PRSFGConfig(bg_smoothing={"method": "gaussian", "sigma": 4},
                      ref_bg_smoothing=SmoothingSpec("none"))
    out = step_bg_smooth(averaged, cfg)
    np.testing.assert_allclose(out.bg_sm, smooth(averaged.bg_avg, {"method": "gaussian", "sigma": 4}))
    np.testing.assert_array_equal(out.ref_bg_sm, averaged.ref_bg_avg)


def test_phase_resolved_legacy_savgol_fields_still_apply():
    averaged = _averaged()
    out = step_bg_smooth(averaged, PRSFGConfig(bg_smoothing_window=11, bg_smoothing_order=3))
    expected = smooth(averaged.bg_avg, {"method": "savgol", "window": 11, "order": 3})
    np.testing.assert_allclose(out.bg_sm, expected)
    np.testing.assert_allclose(out.ref_bg_sm, smooth(averaged.ref_bg_avg,
                                                      {"method": "savgol", "window": 11, "order": 3}))


@pytest.mark.parametrize("formatter", [provenance.format_conventional_provenance,
                                       provenance.format_phase_resolved_provenance])
def test_smoothing_round_trips_through_the_header(formatter, tmp_path):
    smoothing = {"sample": SmoothingSpec("savgol", {"window": 15, "order": 2}).to_dict(),
                 "reference": SmoothingSpec("gaussian", {"sigma": 1.5}).to_dict()}
    kind = "phase_resolved" if "phase_resolved" in formatter.__name__ else "conventional"
    lines = ([f"# Type: {kind}"] + formatter({"bg_smoothing": smoothing}))
    path = tmp_path / "x.csv"
    path.write_text("\n".join(lines) + "\nWavenumber,Intensity\n1,2\n", encoding="utf-8")

    _, prov, _ = provenance.parse_export_header(path)
    assert prov["bg_smoothing"] == smoothing


def test_old_phase_resolved_header_reads_as_savgol(tmp_path):
    path = tmp_path / "old.csv"
    path.write_text("# Type: phase-resolved\n# BG smoothing window:  11\n# BG smoothing order:  3\n"
                    "Wavenumber,Intensity\n1,2\n", encoding="utf-8")
    _, prov, _ = provenance.parse_export_header(path)
    assert prov["bg_smoothing"]["sample"] == {"method": "savgol", "window": 11, "order": 3}
    assert prov["bg_smoothing"]["reference"] == prov["bg_smoothing"]["sample"]


def test_header_without_smoothing_reads_as_none(tmp_path):
    path = tmp_path / "plain.csv"
    path.write_text("# Type: conventional\nWavenumber,Intensity\n1,2\n", encoding="utf-8")
    _, prov, _ = provenance.parse_export_header(path)
    assert prov["bg_smoothing"] == {"sample": {"method": "none"}, "reference": {"method": "none"}}
    json.dumps(prov["bg_smoothing"])
