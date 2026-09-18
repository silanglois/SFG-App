"""Shared test fixtures.

The Qt-layer tests run offscreen with matplotlib on Agg, and every
on-disk settings store is redirected into a tmp_path -- see
`isolate_user_config` below for why that isolation is mandatory.
"""
import os

# Must be set before anything imports Qt, so the offscreen platform
# plugin is the one that gets loaded.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import matplotlib
matplotlib.use("Agg")

import numpy as np
import pandas as pd
import pytest

from sfg_app2.processing.processed_spectrum import ProcessedSpectrum

# Every settings module binds its paths at import time
# (CONFIG_DIR = Path(user_config_dir("SFG-App")) at module scope), so
# patching platformdirs itself is too late -- the module attributes have
# to be replaced directly. (module, [attribute names]) pairs:
_SETTINGS_PATH_ATTRS = [
    ("appearance_settings", ["CONFIG_DIR", "SETTINGS_FILE"]),
    ("color_coding_settings", ["CONFIG_DIR", "SETTINGS_FILE"]),
    ("dock_layout_settings", ["CONFIG_DIR", "SETTINGS_FILE"]),
    ("fitting_display_settings", ["CONFIG_DIR", "SETTINGS_FILE"]),
    ("fit_template_manager", ["CONFIG_DIR", "TEMPLATES_FILE"]),
    ("matching_settings", ["CONFIG_DIR", "SETTINGS_FILE"]),
    ("pattern_manager", ["CONFIG_DIR", "PATTERNS_FILE"]),
    ("plotting_settings", ["CONFIG_DIR", "SETTINGS_FILE", "CUSTOM_STYLES_DIR"]),
]


@pytest.fixture(autouse=True)
def isolate_user_config(tmp_path, monkeypatch):
    """Point every settings store at a throwaway directory.

    Without this, merely constructing a tab is destructive: e.g.
    ProcessedResultsTab.__init__ builds a real PlottingSettings() that
    reads the user's own plotting_settings.json, and anything that calls
    save() writes it back. A stray test has already clobbered a real
    user config once -- keep this autouse.
    """
    import importlib

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    for module_name, attrs in _SETTINGS_PATH_ATTRS:
        module = importlib.import_module(f"sfg_app2.app.utils.{module_name}")
        for attr in attrs:
            current = getattr(module, attr)
            # Preserve each constant's own basename under the tmp dir, so
            # the stores stay distinct from one another.
            replacement = config_dir if attr == "CONFIG_DIR" else config_dir / current.name
            monkeypatch.setattr(module, attr, replacement)
    return config_dir


# ── Spectrum factories ────────────────────────────────────────────────────

_WAVENUMBERS = np.linspace(2800.0, 3000.0, 64)


def _frame(**columns) -> pd.DataFrame:
    return pd.DataFrame({"Wavenumber": _WAVENUMBERS, **columns})


@pytest.fixture
def make_homodyne_entry():
    """Builds a checked homodyne SpectrumEntry (Frame/Wavenumber/Intensity).

    The Frame column is required: _refresh_plot routes homodyne entries
    through ProcessedSpectrum.frame(1).
    """
    from sfg_app2.app.tabs.processed_results import SpectrumEntry

    def _make(label="homodyne-1", amplitude=1.0, metadata=None, checked=True):
        df = _frame(Frame=1, Intensity=amplitude * np.sin(_WAVENUMBERS / 40.0))
        spectrum = ProcessedSpectrum(df=df, metadata=dict(metadata or {}), history=[])
        entry = SpectrumEntry(spectrum, label, kind="homodyne")
        entry.checked = checked
        return entry

    return _make


@pytest.fixture
def make_heterodyne_entry():
    """Builds a checked heterodyne SpectrumEntry with all four plottable
    components plus their 95%-CI error columns."""
    from sfg_app2.app.tabs.processed_results import SpectrumEntry

    def _make(label="heterodyne-1", metadata=None, checked=True):
        real = np.sin(_WAVENUMBERS / 40.0)
        imag = np.cos(_WAVENUMBERS / 40.0)
        df = _frame(
            Real=real, Imaginary=imag,
            Phase=np.degrees(np.arctan2(imag, real)),
            Homodyne=real**2 + imag**2,
            Real_err=np.full_like(real, 0.05),
            Imag_err=np.full_like(imag, 0.05),
            Phase_err=np.full_like(real, 1.0),
            Homodyne_err=np.full_like(real, 0.05),
        )
        spectrum = ProcessedSpectrum(df=df, metadata=dict(metadata or {}), history=[])
        entry = SpectrumEntry(spectrum, label, kind="heterodyne")
        entry.checked = checked
        return entry

    return _make


@pytest.fixture
def make_fitted_entry(make_homodyne_entry):
    """A homodyne entry carrying a reloaded fit's derived curves, as
    _add_fit_component_columns would have produced them."""
    def _make(label="fitted-1", components=("Fit (total)",), checked=True):
        entry = make_homodyne_entry(label=label, checked=checked)
        df = entry.spectrum.data
        for column in components:
            df[column] = np.cos(_WAVENUMBERS / 40.0)
        entry.fit_components = [(column, column) for column in components]
        return entry

    return _make


@pytest.fixture
def results_tab(qtbot):
    """A constructed Spectra Library tab, registered with qtbot so Qt
    tears it down deterministically."""
    from sfg_app2.app.tabs.processed_results import ProcessedResultsTab

    tab = ProcessedResultsTab()
    qtbot.addWidget(tab)
    return tab


@pytest.fixture
def load_entries(results_tab):
    """Puts entries into the tab the way the UI would, so list-order and
    checkbox state are consistent with _ordered_entries()."""
    def _load(*entries):
        results_tab._entries = list(entries)
        results_tab._rebuild_list()
        results_tab._refresh_plot()
        return results_tab

    return _load
