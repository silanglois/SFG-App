"""Per-trace styling and annotation value types.

These live apart from the Spectra Library tab that owns the UI so the
dialogs which edit them (trace_style_dialog, plot_annotations_dialog)
don't have to import a tab module -- that direction is a cycle, since
the tab imports the dialogs in turn.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


# key used for the (sole) plotted line of a homodyne entry in
# SpectrumEntry.styles — heterodyne entries use the _HD_COMPONENT_COLUMN
# display names ("Imaginary"/"Real"/"Phase"/"|χ⁽²⁾|² (Homodyne)") instead
AMPLITUDE_COMPONENT = "__amplitude__"

_LINESTYLE_CHOICES = [
    ("Solid", "-"), ("Dashed", "--"), ("Dotted", ":"), ("Dash-dot", "-."),
    ("No line", "None"),
]

# marker display name -> matplotlib marker code (None = no marker, matplotlib's
# own default)
_MARKER_CHOICES = [
    ("None", None), ("Circle", "o"), ("Square", "s"), ("Triangle up", "^"),
    ("Triangle down", "v"), ("Diamond", "D"), ("X", "x"), ("Plus", "+"), ("Star", "*"),
]


@dataclass
class TraceStyle:
    """User-configurable overrides for a single plotted line. `None`/default
    values mean "use the automatic behavior _refresh_plot already has"."""
    color: str | None = None       # None = auto-assigned positional color
    linestyle: str = "-"
    axis: str = "primary"          # "primary" | "secondary"
    label: str | None = None       # None = use the computed legend label
    visible: bool = True
    marker: str | None = None      # None = no marker (today's behavior)
    markersize: float | None = None   # None = matplotlib default
    linewidth: float | None = None    # None = matplotlib default
    alpha: float | None = None        # None = fully opaque (1.0)

    def is_default(self) -> bool:
        return self == TraceStyle()


# components whose auto (un-overridden) axis isn't "primary" — Phase is in
# degrees, a very different scale from the other chi(2) components, so it
# defaults to the secondary axis rather than sharing the primary one
_DEFAULT_AXIS_BY_COMPONENT = {"Phase": "secondary"}


def _default_trace_style(component: str) -> TraceStyle:
    # Every component (including a reloaded fit's derived curves) now
    # defaults to visible=True, matching the fixed HD/amplitude
    # components -- the global "Fit components" checkbox panel (default
    # unchecked) is what prevents clutter on load, not per-entry hiding.
    # Trace Properties is still available as a per-entry override.
    return TraceStyle(
        axis=_DEFAULT_AXIS_BY_COMPONENT.get(component, "primary"),
        visible=True,
    )


def is_customized(style: TraceStyle, component: str) -> bool:
    """Whether the user actually changed this trace's style.

    Not the same as `style.is_default()`, which compares against the bare
    dataclass default: a component whose automatic default differs from
    it (Phase, which starts on the secondary axis) would read as
    customized when untouched. Nor is it `component in entry.styles` --
    style_for() materializes an entry on first read, and the trace
    properties dialog writes every row it displayed whether or not it
    changed.
    """
    return style != _default_trace_style(component)


class HiddenReason(Enum):
    """Why a candidate trace isn't on the plot.

    Ordered by which explanation is most useful to show first when
    several apply at once.
    """
    HIDE_DATA = "the \"Hide data\" option, in the Data display panel"
    HD_COMPONENT_UNCHECKED = "no HD-SFG components being selected, in the HD-SFG components panel"
    FIT_COMPONENT_UNCHECKED = "no fit components being selected, in the Fit components panel"
    TRACE_OVERRIDE = "per-trace visibility overrides (right-click a spectrum to reset them)"


def resolve_visibility(
    *, style: TraceStyle, component: str | None, is_fit: bool,
    hide_data: bool, component_checked: bool,
) -> HiddenReason | None:
    """None when the trace should be drawn, else why it was suppressed.

    `component_checked` is the relevant global panel's answer for this
    trace -- the HD component panel for a heterodyne component, the fit
    component panel for a fit curve, and always True for a homodyne
    amplitude line, which no panel gates.
    """
    if is_fit:
        if not component_checked:
            return HiddenReason.FIT_COMPONENT_UNCHECKED
    else:
        if hide_data:
            return HiddenReason.HIDE_DATA
        if not component_checked:
            return HiddenReason.HD_COMPONENT_UNCHECKED
    if not style.visible:
        return HiddenReason.TRACE_OVERRIDE
    return None


@dataclass
class PlotAnnotation:
    """A free-form element drawn on top of the plotted traces."""
    kind: str               # "vline" | "hline" | "region" | "text"
    x: float | None = None        # vline, text
    y: float | None = None        # hline, text
    x0: float | None = None       # region
    x1: float | None = None       # region
    text: str = ""
    color: str = "#000000"
    linestyle: str = "--"
