from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from platformdirs import user_config_dir

from sfg_app2.processing.calibration import DEFAULT_WINDOW, POLYSTYRENE

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(user_config_dir("SFG-App"))
SETTINGS_FILE = CONFIG_DIR / "calibration_settings.json"

# How the reference is supplied.
MATERIAL, CURVE, LINES = "material", "curve", "lines"


@dataclass
class CalibrationConfig:
    """Which reference to calibrate against, and over what window.

    Defaults are polystyrene over the C-H stretch region — what this
    app did before any of this was configurable — so someone who never
    touches the reference selector sees the calibration they always had.
    """

    kind: str = MATERIAL
    shelf: str = POLYSTYRENE[0]
    book: str = POLYSTYRENE[1]
    page: str = POLYSTYRENE[2]
    curve_path: str = ""
    lines: list[float] = field(default_factory=list)
    wn_min: float = DEFAULT_WINDOW[0]
    wn_max: float = DEFAULT_WINDOW[1]

    @classmethod
    def from_dict(cls, data: dict | None) -> "CalibrationConfig":
        data = data or {}
        blank = cls()
        lines = []
        for value in data.get("lines") or []:
            try:
                lines.append(float(value))
            except (TypeError, ValueError):
                continue
        return cls(
            kind=data.get("kind") or blank.kind,
            shelf=data.get("shelf") or blank.shelf,
            book=data.get("book") or blank.book,
            page=data.get("page") or blank.page,
            curve_path=data.get("curve_path") or "",
            lines=lines,
            wn_min=float(data.get("wn_min", blank.wn_min)),
            wn_max=float(data.get("wn_max", blank.wn_max)),
        )

    def to_dict(self) -> dict:
        return {"kind": self.kind, "shelf": self.shelf, "book": self.book,
                "page": self.page, "curve_path": self.curve_path,
                "lines": list(self.lines),
                "wn_min": self.wn_min, "wn_max": self.wn_max}

    def display_name(self) -> str:
        if self.kind == CURVE:
            return Path(self.curve_path).stem or "reference curve"
        if self.kind == LINES:
            return f"{len(self.lines)} known line(s)"
        return f"{self.book} ({self.page})"

    def build_reference(self):
        """The reference object the scan samples, or None for line mode
        (which needs no curve -- that's its point)."""
        from sfg_app2.processing.calibration import (
            CurveReference, MaterialReference, load_reference_csv,
        )
        if self.kind == LINES:
            return None
        if self.kind == CURVE:
            if not self.curve_path:
                raise ValueError("No reference curve file chosen.")
            return load_reference_csv(self.curve_path)
        return MaterialReference(self.shelf, self.book, self.page,
                                 name=self.display_name())


class CalibrationSettings:
    """Remembers the last calibration reference used.

    Not a preset tree: the useful thing is not having to re-enter a list
    of literature line positions or re-locate a reference file every
    session, and a single remembered configuration does that without
    another manager UI.
    """

    def __init__(self):
        self._config = CalibrationConfig()
        self.load()

    def load(self):
        try:
            if SETTINGS_FILE.exists():
                self._config = CalibrationConfig.from_dict(
                    json.loads(SETTINGS_FILE.read_text()))
                logger.info("Loaded calibration settings from %s.", SETTINGS_FILE)
            else:
                self._config = CalibrationConfig()
        except Exception as e:
            logger.warning("Failed to load calibration settings: %s — using defaults.", e)
            self._config = CalibrationConfig()

    def save(self) -> bool:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(self._config.to_dict(), indent=2))
            return True
        except Exception as e:
            logger.error("Failed to save calibration settings: %s", e)
            return False

    @property
    def config(self) -> CalibrationConfig:
        return self._config

    def set_config(self, config: CalibrationConfig) -> bool:
        self._config = config
        return self.save()
