from __future__ import annotations
import json
import logging
from pathlib import Path
from platformdirs import user_config_dir

import matplotlib as mpl
import aquarel
from aquarel import Theme, list_themes

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(user_config_dir("SFG-App"))
SETTINGS_FILE = CONFIG_DIR / "plotting_settings.json"
THEMES_DIR = Path(aquarel.__file__).parent / "themes"
CUSTOM_STYLES_DIR = CONFIG_DIR / "custom_styles"

MATPLOTLIB_DEFAULT = "matplotlib_default"
DEFAULT_STYLE = "ambivalent"


def custom_styles_dir() -> Path:
    return CUSTOM_STYLES_DIR


def list_custom_styles() -> list[str]:
    """Returns the names (file stems) of every user-created custom style."""
    if not CUSTOM_STYLES_DIR.exists():
        return []
    return sorted(p.stem for p in CUSTOM_STYLES_DIR.glob("*.json"))


def is_custom_style(name: str) -> bool:
    return (CUSTOM_STYLES_DIR / f"{name}.json").exists()


def available_styles() -> list[str]:
    """Returns all selectable style names, matplotlib default first, then
    built-in aquarel themes, then user-created custom styles."""
    return [MATPLOTLIB_DEFAULT, *sorted(list_themes()), *list_custom_styles()]


def _load_theme(name: str) -> Theme:
    # aquarel.load_theme() opens theme files without an explicit encoding,
    # which fails on Windows for themes containing non-ASCII descriptions
    # (e.g. ambivalent's emoji) since the default codepage isn't UTF-8.
    directory = CUSTOM_STYLES_DIR if is_custom_style(name) else THEMES_DIR
    text = (directory / f"{name}.json").read_text(encoding="utf-8")
    return Theme.from_dict(json.loads(text))


def delete_custom_style(name: str) -> bool:
    try:
        (CUSTOM_STYLES_DIR / f"{name}.json").unlink()
        logger.info("Deleted custom style '%s'.", name)
        return True
    except Exception as e:
        logger.error("Failed to delete custom style '%s': %s", name, e)
        return False


def _qt_window_color() -> str:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QPalette
    app = QApplication.instance()
    if app is not None:
        return app.palette().color(QPalette.ColorRole.Window).name()
    return "white"


# The figure/axes background the *active* style resolves to. Kept in sync
# by apply_style() and re-asserted on every canvas draw (see style_figure()
# below) so a plot can never end up stuck with a stale color — regardless
# of when its Figure/Axes were constructed relative to the last style
# change, or whether they're a twin axes created outside SpectrumPlotWidget.
_current_figure_bg: str | None = None
_current_axes_bg: str | None = None


def _apply_theme_object(theme: Theme):
    """Applies an in-memory Theme's rcParams, patching transparent
    backgrounds to blend with the app. Shared by apply_rcparams() (which
    loads a style by name first) and the custom style editor's live
    preview (which edits a Theme that has no name/file yet)."""
    theme.apply()
    # Qt's FigureCanvasQTAgg erases each frame to opaque white before
    # compositing, so a "none" (transparent) figure/axes facecolor still
    # renders as a white box instead of blending with the widget behind
    # it. Substitute the app's real window color to actually blend in.
    if mpl.rcParams["figure.facecolor"] == "none":
        bg = _qt_window_color()
        mpl.rcParams.update({"figure.facecolor": bg, "axes.facecolor": bg})


def apply_rcparams(name: str):
    """Applies a style's rcParams only, without touching the persisted
    'currently active' background used by style_figure(). Used both by
    apply_style() below and by the settings dialog's live preview (which
    must not mark an unconfirmed style as the active one).
    """
    if name == MATPLOTLIB_DEFAULT:
        mpl.rcParams.update(mpl.rcParamsDefault)
    else:
        _apply_theme_object(_load_theme(name))


def apply_style(name: str):
    """Applies a style globally via matplotlib rcParams and marks it as
    the active style for style_figure() to enforce on every draw."""
    global _current_figure_bg, _current_axes_bg
    apply_rcparams(name)
    _current_figure_bg = mpl.rcParams["figure.facecolor"]
    _current_axes_bg = mpl.rcParams["axes.facecolor"]
    logger.info("Applied '%s' plotting style.", name)


def style_figure(figure):
    """Force the active style's resolved background onto a figure and all
    of its axes — including twin axes (e.g. from ax.twinx()), whose patch
    matplotlib hides but which still get created with whatever rcParams
    happened to be active at the time. Call this right before every draw
    so plots can't drift out of sync with the chosen style.
    """
    if _current_figure_bg is None:
        return
    figure.patch.set_facecolor(_current_figure_bg)
    for ax in figure.get_axes():
        ax.patch.set_facecolor(_current_axes_bg)


class PlottingSettings:
    """Load, save, and apply the user's chosen matplotlib/aquarel style."""

    def __init__(self):
        self._style: str = DEFAULT_STYLE
        self.load()

    def load(self):
        try:
            if SETTINGS_FILE.exists():
                data = json.loads(SETTINGS_FILE.read_text())
                style = data.get("style", DEFAULT_STYLE)
                self._style = style if style in available_styles() else DEFAULT_STYLE
                logger.info("Loaded plotting style '%s' from %s.", self._style, SETTINGS_FILE)
            else:
                self._style = DEFAULT_STYLE
                logger.info("No plotting settings file found — using default '%s'.", DEFAULT_STYLE)
        except Exception as e:
            logger.warning("Failed to load plotting settings: %s — using default.", e)
            self._style = DEFAULT_STYLE

    def save(self) -> bool:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps({"style": self._style}, indent=2))
            logger.info("Plotting settings saved to %s.", SETTINGS_FILE)
            return True
        except Exception as e:
            logger.error("Failed to save plotting settings: %s", e)
            return False

    @property
    def style(self) -> str:
        return self._style

    def apply_current(self):
        apply_style(self._style)

    def set_style(self, name: str) -> bool:
        self._style = name
        saved = self.save()
        apply_style(name)
        return saved
