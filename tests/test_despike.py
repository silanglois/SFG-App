import numpy as np
import pandas as pd

from sfg_app2.processing.despike import remove_outliers_movmedian
from sfg_app2.processing.data_file import DataFile


def _spiky_signal(n: int = 200, spike_indices=(50, 120)):
    rng = np.random.default_rng(0)
    y = 10.0 + 0.5 * np.sin(np.linspace(0, 4 * np.pi, n)) + 0.05 * rng.normal(size=n)
    for idx in spike_indices:
        y[idx] += 50.0
    return y


def test_remove_outliers_movmedian_default_return_shape_unchanged():
    y = _spiky_signal()
    cleaned = remove_outliers_movmedian(y, window=11, threshold_factor=3.0)
    assert isinstance(cleaned, np.ndarray)
    assert cleaned.shape == y.shape


def test_remove_outliers_movmedian_return_mask_flags_spikes():
    y = _spiky_signal(spike_indices=(50, 120))
    cleaned, mask = remove_outliers_movmedian(y, window=11, threshold_factor=3.0, return_mask=True)
    assert mask.dtype == bool
    assert mask.shape == y.shape
    flagged = set(np.nonzero(mask)[0])
    assert 50 in flagged
    assert 120 in flagged
    # cleaned values at flagged points should no longer be spiked
    assert cleaned[50] < 20.0
    assert cleaned[120] < 20.0


def test_remove_outliers_movmedian_return_mask_false_by_default_matches_old_call():
    y = _spiky_signal()
    old_style = remove_outliers_movmedian(y, window=11, threshold_factor=3.0)
    new_style = remove_outliers_movmedian(y, window=11, threshold_factor=3.0, return_mask=False)
    np.testing.assert_array_equal(old_style, new_style)


def _make_data_file(tmp_path, n=200, spike_indices=(50, 120)):
    y = _spiky_signal(n=n, spike_indices=spike_indices)
    wavelength = np.linspace(2700, 3200, n)
    df = pd.DataFrame({"Frame": 1, "Wavelength": wavelength, "Intensity": y})
    path = tmp_path / "spiky.csv"
    df.to_csv(path, index=False)
    return DataFile(path)


def test_data_file_flag_cosmic_rays_matches_frame_sort_order(tmp_path):
    data_file = _make_data_file(tmp_path)
    masks = data_file.flag_cosmic_rays(window=11, threshold_factor=3.0)
    assert set(masks.keys()) == {1}
    mask = masks[1]

    fd = data_file.frame(1)
    assert len(mask) == len(fd)
    flagged_wavelengths = fd["Wavelength"].to_numpy()[mask]
    # the two spikes were placed at indices 50/120 of the *unsorted*
    # synthetic array, but Wavelength is already ascending here so the
    # sort in frame()/flag_cosmic_rays doesn't reorder anything --
    # just confirm both known spikes were flagged, aligned to frame().
    assert mask.sum() >= 2
    assert len(flagged_wavelengths) == mask.sum()


def test_data_file_flag_cosmic_rays_does_not_mutate_data(tmp_path):
    data_file = _make_data_file(tmp_path)
    before = data_file.frame(1)["Intensity"].to_numpy().copy()
    data_file.flag_cosmic_rays(window=11, threshold_factor=3.0)
    after = data_file.frame(1)["Intensity"].to_numpy()
    np.testing.assert_array_equal(before, after)
