"""Qt-layer tests for the Spectra Library tab.

Split in two: smoke tests that the tab wires up and plots at all, and
*characterization* tests that pin down today's plotting behaviour
(line counts, colour inheritance, offsets) so the upcoming extraction
of _refresh_plot can be shown to be behaviour-preserving.

Run with:
    uv run pytest tests/test_processed_results_tab.py -v
"""
import numpy as np
import pytest

from sfg_app2.app.tabs.processed_results import AMPLITUDE_COMPONENT


def _lines(tab):
    """Primary-axis traces, in draw order."""
    return tab.plot_widget.ax.get_lines()


def _all_lines(tab):
    """Every trace, including the secondary axis -- Phase defaults there
    (_DEFAULT_AXIS_BY_COMPONENT), so a primary-only count misses it."""
    lines = list(tab.plot_widget.ax.get_lines())
    if tab.plot_widget.ax2 is not None:
        lines += list(tab.plot_widget.ax2.get_lines())
    return lines


# ── Smoke ─────────────────────────────────────────────────────────────────

def test_tab_constructs_with_empty_plot(results_tab):
    assert results_tab._entries == []
    assert _lines(results_tab) == []


def test_checked_entry_is_plotted_unchecked_is_not(load_entries, make_homodyne_entry):
    tab = load_entries(make_homodyne_entry(checked=True))
    assert len(_lines(tab)) == 1

    tab._entries[0].checked = False
    tab._rebuild_list()
    tab._refresh_plot()
    assert _lines(tab) == []


def test_heterodyne_components_are_opt_in(load_entries, make_heterodyne_entry):
    """A heterodyne entry plots one line per *checked* HD component.

    Phase lands on the secondary axis, so this counts both axes.
    """
    tab = load_entries(make_heterodyne_entry())
    baseline = len(_all_lines(tab))

    tab._hd_checkboxes["Phase"].setChecked(True)
    assert len(_all_lines(tab)) == baseline + 1

    tab._hd_checkboxes["Phase"].setChecked(False)
    assert len(_all_lines(tab)) == baseline


def test_fit_curves_are_opt_in(load_entries, make_fitted_entry):
    tab = load_entries(make_fitted_entry())
    assert len(_lines(tab)) == 1          # data only; fit panel starts off

    tab._fit_checkboxes["Fit total"].setChecked(True)
    assert len(_lines(tab)) == 2          # data + Fit (total)


def test_hide_data_suppresses_only_measured_series(load_entries, make_fitted_entry):
    tab = load_entries(make_fitted_entry())
    tab._fit_checkboxes["Fit total"].setChecked(True)
    assert len(_lines(tab)) == 2

    tab._hide_data_checkbox.setChecked(True)
    assert len(_lines(tab)) == 1          # fit curve survives


def test_per_trace_visible_override_hides_one_line(load_entries, make_homodyne_entry):
    entry = make_homodyne_entry()
    tab = load_entries(entry)
    assert len(_lines(tab)) == 1

    entry.style_for(AMPLITUDE_COMPONENT).visible = False
    tab._refresh_plot()
    assert _lines(tab) == []


# ── Characterization: colours ─────────────────────────────────────────────

def test_fit_curve_inherits_its_own_entry_data_colour(load_entries, make_fitted_entry):
    tab = load_entries(make_fitted_entry())
    tab._fit_checkboxes["Fit total"].setChecked(True)

    data_line, fit_line = _lines(tab)
    assert data_line.get_color() == fit_line.get_color()


def test_two_entries_get_distinct_colours(load_entries, make_homodyne_entry):
    tab = load_entries(
        make_homodyne_entry(label="a"),
        make_homodyne_entry(label="b"),
    )
    first, second = _lines(tab)
    assert first.get_color() != second.get_color()


# ── Characterization: offset ──────────────────────────────────────────────

def _baseline_of(line):
    """Vertical position of a trace, robust to its shape."""
    return float(np.mean(line.get_ydata()))


def test_offset_separates_two_spectra(load_entries, make_homodyne_entry):
    tab = load_entries(
        make_homodyne_entry(label="a"),
        make_homodyne_entry(label="b"),
    )
    tab.ui.offsetSpectraSpinner.setValue(0.0)
    flat = [_baseline_of(line) for line in _lines(tab)]
    assert flat[1] == pytest.approx(flat[0])

    tab.ui.offsetSpectraSpinner.setValue(10.0)
    offset = [_baseline_of(line) for line in _lines(tab)]
    assert offset[1] - offset[0] == pytest.approx(10.0)


def test_offset_is_per_spectrum_not_per_line(load_entries, make_heterodyne_entry):
    """Two HD components of the SAME spectrum share one offset slot.

    Measured as the shift each trace gains when the offset is switched
    on, which isolates the offset from the components' own differing
    signal shapes. Before the fix the offset was keyed by flat line
    index, giving [0, 10, 20, 30] -- so a spectrum's own components were
    pushed apart from each other and the spacing grew with the number of
    components enabled.
    """
    tab = load_entries(
        make_heterodyne_entry(label="a"),
        make_heterodyne_entry(label="b"),
    )
    tab._hd_checkboxes["Real"].setChecked(True)
    tab._hd_checkboxes["Imaginary"].setChecked(True)

    tab.ui.offsetSpectraSpinner.setValue(0.0)
    flat = [_baseline_of(line) for line in _lines(tab)]
    assert len(flat) == 4, "expect 2 spectra x 2 components"

    tab.ui.offsetSpectraSpinner.setValue(10.0)
    shifted = [_baseline_of(line) for line in _lines(tab)]

    applied = [after - before for before, after in zip(flat, shifted)]
    # Lines are emitted entry-major: a/Imag, a/Real, b/Imag, b/Real.
    assert applied == pytest.approx([0.0, 0.0, 10.0, 10.0])


# ── Characterization: y-axis label ────────────────────────────────────────

def test_homodyne_ylabel_is_arbitrary_units(load_entries, make_homodyne_entry):
    tab = load_entries(make_homodyne_entry())
    assert tab.plot_widget.ax.get_ylabel() == "Normalized Intensity (a.u.)"
