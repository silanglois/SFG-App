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


# ── Empty-plot explanation ────────────────────────────────────────────────

def _explanation(tab):
    texts = [t.get_text() for t in tab.plot_widget.ax.texts]
    return texts[0] if texts else None


def test_empty_plot_names_hide_data_as_the_cause(load_entries, make_homodyne_entry):
    tab = load_entries(make_homodyne_entry())
    tab._hide_data_checkbox.setChecked(True)

    assert _lines(tab) == []
    assert "Hide data" in _explanation(tab)
    assert "Data display" in _explanation(tab)


def test_empty_plot_names_trace_overrides_as_the_cause(load_entries, make_homodyne_entry):
    entry = make_homodyne_entry()
    tab = load_entries(entry)
    entry.style_for(AMPLITUDE_COMPONENT).visible = False
    tab._refresh_plot()

    assert _lines(tab) == []
    assert "per-trace" in _explanation(tab)


def test_empty_plot_message_is_pluralized(load_entries, make_homodyne_entry):
    """"1 trace(s)" reads as placeholder text in a message whose whole
    purpose is to be plain."""
    tab = load_entries(make_homodyne_entry())
    tab._hide_data_checkbox.setChecked(True)
    assert "1 trace hidden" in _explanation(tab)

    tab._entries.append(make_homodyne_entry(label="second"))
    tab._rebuild_list()
    tab._refresh_plot()
    assert "2 traces hidden" in _explanation(tab)


def test_explanation_does_not_accumulate_across_redraws(load_entries, make_homodyne_entry):
    """soft_clear() must drop text artists.

    It removed lines, collections and the legend but not texts, so every
    redraw stacked another copy of the explanation -- and, since
    _draw_annotations re-adds them too, of every text annotation.
    """
    tab = load_entries(make_homodyne_entry())
    tab._hide_data_checkbox.setChecked(True)
    assert len(tab.plot_widget.ax.texts) == 1

    for _ in range(3):
        tab._refresh_plot()
    assert len(tab.plot_widget.ax.texts) == 1


def test_no_explanation_while_something_is_plotted(load_entries, make_homodyne_entry):
    tab = load_entries(make_homodyne_entry())
    assert len(_lines(tab)) == 1
    assert _explanation(tab) is None


# ── Per-trace override badge and reset ────────────────────────────────────

def _row_text(tab, row=0):
    return tab.ui.spectraList.item(row).text()


def test_untouched_entry_carries_no_override_badge(load_entries, make_heterodyne_entry):
    """Reading a style must not look like customizing it.

    style_for() materializes a TraceStyle on first read, and Phase's
    automatic default differs from the bare dataclass default -- both
    would fool a naive "has overrides" check.
    """
    tab = load_entries(make_heterodyne_entry(label="het"))
    for component in ("Real", "Imaginary", "Phase"):
        tab._entries[0].style_for(component)
    tab._rebuild_list()

    assert "◆" not in _row_text(tab)


def test_override_badge_appears_and_resets(load_entries, make_homodyne_entry):
    entry = make_homodyne_entry(label="sample")
    tab = load_entries(entry)
    assert "◆" not in _row_text(tab)

    entry.style_for(AMPLITUDE_COMPONENT).color = "#ff0000"
    tab._rebuild_list()
    assert "◆" in _row_text(tab)

    tab._on_reset_trace_styles([entry])
    assert "◆" not in _row_text(tab)
    assert len(_lines(tab)) == 1


def test_reset_restores_a_trace_hidden_by_an_override(load_entries, make_homodyne_entry):
    entry = make_homodyne_entry()
    tab = load_entries(entry)
    entry.style_for(AMPLITUDE_COMPONENT).visible = False
    tab._refresh_plot()
    assert _lines(tab) == []

    tab._on_reset_trace_styles([entry])
    assert len(_lines(tab)) == 1
