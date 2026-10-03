"""Phase-resolved (PR-SFG) panel: one Pair selector (sample / reference /
both) drives every step that has a sample and a reference side."""
import pytest


@pytest.fixture
def panel(process_tab):
    tab, _matched = process_tab("phase_resolved")
    panel = tab._pr_sfg_panel
    panel._run_from_step("despiked")
    # qtbot only holds the tab weakly; the panel's C++ children die with it
    yield panel
    del tab


def _labels(panel):
    return [line.get_label() for line in panel.plot_widget.ax.get_lines()
            if not line.get_label().startswith("_")]


def _show(panel, step, pair, view=None):
    panel._step_radios[step].setChecked(True)
    panel._pair_combo.setCurrentText(pair)
    if view is not None:
        panel._view_combo.setCurrentText(view)
    panel._refresh_plot()


def test_pair_selector_is_offered_at_background_subtraction(panel):
    panel._step_radios["bg_smooth"].setChecked(True)
    assert not panel._pair_combo.isHidden()
    assert not panel._view_combo.isHidden()
    assert panel._source_combo.isHidden()
    assert not hasattr(panel, "_comp_combo"), "one Pair combo, not a second Show combo"


@pytest.mark.parametrize("view", ["Signal + Background", "Subtracted result"])
def test_reference_pair_hides_the_sample_curves(panel, view):
    _show(panel, "bg_smooth", "Reference pair", view)
    labels = _labels(panel)
    assert labels and all("Ref" in l or "Reference" in l for l in labels)

    _show(panel, "bg_smooth", "Sample pair", view)
    labels = _labels(panel)
    assert labels and not any("Ref" in l or "Reference" in l for l in labels)


def test_fft_and_ifft_follow_the_same_pair_choice(panel):
    _show(panel, "fft_filter", "Reference pair")
    assert all("Reference" in l for l in _labels(panel))

    _show(panel, "ifft", "Reference pair")
    labels = _labels(panel)
    assert "Reference iFFT (real)" in labels and "Reference iFFT (imag)" in labels
    assert not any(l.startswith("Signal") for l in labels)

    _show(panel, "ifft", "Both pairs")
    assert any(l.startswith("Signal") for l in _labels(panel))
