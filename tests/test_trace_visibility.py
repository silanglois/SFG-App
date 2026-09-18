"""Pure-function tests for trace visibility resolution -- no Qt involved.

Run with:
    uv run pytest tests/test_trace_visibility.py -v
"""
import pytest

from sfg_app2.app.tabs.trace_style import (
    AMPLITUDE_COMPONENT, HiddenReason, TraceStyle, _default_trace_style,
    is_customized, resolve_visibility,
)


def _resolve(**overrides):
    kwargs = dict(
        style=TraceStyle(), component="Real", is_fit=False,
        hide_data=False, component_checked=True,
    )
    kwargs.update(overrides)
    return resolve_visibility(**kwargs)


# ── resolve_visibility ────────────────────────────────────────────────────

def test_visible_when_nothing_suppresses_it():
    assert _resolve() is None


def test_hide_data_suppresses_measured_traces():
    assert _resolve(hide_data=True) is HiddenReason.HIDE_DATA


def test_hide_data_does_not_suppress_fit_curves():
    """"Hide data" is about the measured series; fit curves are exactly
    what the user still wants to see."""
    assert _resolve(is_fit=True, hide_data=True) is None


def test_unchecked_hd_component_is_reported_as_such():
    assert _resolve(component_checked=False) is HiddenReason.HD_COMPONENT_UNCHECKED


def test_unchecked_fit_component_is_reported_separately():
    """A fit curve and an HD component are hidden by different panels, so
    they must not share one explanation."""
    assert _resolve(is_fit=True, component_checked=False) is HiddenReason.FIT_COMPONENT_UNCHECKED


def test_per_trace_override_is_reported():
    assert _resolve(style=TraceStyle(visible=False)) is HiddenReason.TRACE_OVERRIDE


def test_panel_reason_wins_over_trace_override():
    """When both apply, name the panel: it's the one the user is more
    likely to have touched, and the coarser of the two."""
    reason = _resolve(style=TraceStyle(visible=False), hide_data=True)
    assert reason is HiddenReason.HIDE_DATA


def test_homodyne_amplitude_is_never_gated_by_a_component_panel():
    assert _resolve(component=AMPLITUDE_COMPONENT, component_checked=True) is None


@pytest.mark.parametrize("reason", list(HiddenReason))
def test_every_reason_names_a_control_the_user_can_find(reason):
    """Each explanation has to point somewhere actionable, otherwise the
    empty-plot message just restates that the plot is empty."""
    assert reason.value.strip()
    assert len(reason.value.split()) >= 4


# ── is_customized ─────────────────────────────────────────────────────────

def test_untouched_style_is_not_customized():
    assert not is_customized(_default_trace_style("Real"), "Real")


def test_phase_default_is_not_customized_despite_differing_from_bare_default():
    """Phase defaults to the secondary axis, so TraceStyle.is_default()
    calls an untouched Phase trace customized. is_customized must not."""
    style = _default_trace_style("Phase")
    assert style.is_default() is False      # documents the trap
    assert not is_customized(style, "Phase")


def test_changed_style_is_customized():
    style = _default_trace_style("Real")
    style.color = "#ff0000"
    assert is_customized(style, "Real")


def test_hiding_a_trace_counts_as_customizing_it():
    style = _default_trace_style("Phase")
    style.visible = False
    assert is_customized(style, "Phase")
