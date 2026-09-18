"""Per-trace styling and annotation value types.

These live apart from the Spectra Library tab that owns the UI so the
dialogs which edit them (trace_style_dialog, plot_annotations_dialog)
don't have to import a tab module -- that direction is a cycle, since
the tab imports the dialogs in turn.
"""
from __future__ import annotations
from dataclasses import dataclass


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
