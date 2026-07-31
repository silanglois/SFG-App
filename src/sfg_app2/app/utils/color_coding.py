from __future__ import annotations
import zlib

from PySide6.QtGui import QColor

from sfg_app2.app.utils.color_coding_settings import ColorCodingSettings

# Housekeeping keys every DataFile.metadata carries that aren't meaningful
# grouping fields — "role" gets its own dedicated mode instead.
NON_GROUPING_KEYS = {"source_filename", "filename_parts", "extra_filename_parts", "role"}

# A fixed, curated categorical palette (matplotlib "tab10" + a few "tab20"
# lighter variants). Each entry is mid-toned/saturated enough that a
# contrasting black-or-white foreground (see contrasting_text_color) always
# reads clearly against it, regardless of the app's own light/dark theme.
_PALETTE = [
    QColor(31, 119, 180), QColor(255, 127, 14), QColor(44, 160, 44),
    QColor(214, 39, 40), QColor(148, 103, 189), QColor(140, 86, 75),
    QColor(227, 119, 194), QColor(127, 127, 127), QColor(188, 189, 34),
    QColor(23, 190, 207), QColor(174, 199, 232), QColor(255, 187, 120),
]


def group_key(metadata: dict, settings: ColorCodingSettings) -> str | None:
    """The group identity a file belongs to under the current settings, or
    None if there's nothing meaningful to group by (coloring should be
    skipped in that case)."""
    if settings.mode == "role":
        return str(metadata.get("role", "signal"))

    if not settings.fields:
        return None
    return " / ".join(str(metadata.get(f, "")) for f in settings.fields)


def color_for_key(key: str) -> QColor:
    """Deterministic color for a group key — stable across sessions (uses
    a fixed-algorithm hash, not Python's randomized hash()), and shared by
    every widget that colors by the same key so they always agree."""
    idx = zlib.crc32(key.encode("utf-8")) % len(_PALETTE)
    return _PALETTE[idx]


def contrasting_text_color(bg: QColor) -> QColor:
    """Black or white, whichever reads more clearly against bg."""
    luminance = 0.299 * bg.red() + 0.587 * bg.green() + 0.114 * bg.blue()
    return QColor(0, 0, 0) if luminance > 140 else QColor(255, 255, 255)


def available_fields(metadata_dicts) -> list[str]:
    """Union of grouping-eligible metadata keys across an iterable of
    metadata dicts, sorted for stable display in the settings dialog."""
    keys: set[str] = set()
    for md in metadata_dicts:
        keys.update(md.keys())
    return sorted(keys - NON_GROUPING_KEYS)
