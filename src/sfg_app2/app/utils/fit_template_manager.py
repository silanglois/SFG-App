from __future__ import annotations
import json
import logging
from pathlib import Path
from platformdirs import user_config_dir

from sfg_app2.processing.fitting import FitModelSpec

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(user_config_dir("SFG-App"))
TEMPLATES_FILE = CONFIG_DIR / "fit_templates.json"


class FitTemplateManager:
    """Persists named fit-model definitions (peak count, initial values,
    bounds, constraints) so a model can be saved once and re-applied to
    other spectra — this is also the mechanism for "copy parameters
    between spectra": save the current fit as a template, apply it
    elsewhere.
    """

    def __init__(self):
        self._templates: dict[str, dict] = {}
        self.load()

    def load(self):
        try:
            if TEMPLATES_FILE.exists():
                raw = json.loads(TEMPLATES_FILE.read_text())
                self._templates = raw.get("templates", {})
                logger.info("Loaded %d fit template(s) from %s.", len(self._templates), TEMPLATES_FILE)
            else:
                self._templates = {}
                logger.info("No fit templates file found — starting empty.")
        except Exception as e:
            logger.warning("Failed to load fit templates: %s — starting empty.", e)
            self._templates = {}

    def save(self) -> bool:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            TEMPLATES_FILE.write_text(json.dumps({"templates": self._templates}, indent=2))
            logger.info("Fit templates saved to %s.", TEMPLATES_FILE)
            return True
        except Exception as e:
            logger.error("Failed to save fit templates: %s", e)
            return False

    def names(self) -> list[str]:
        return sorted(self._templates.keys())

    def get(self, name: str) -> FitModelSpec | None:
        raw = self._templates.get(name)
        if raw is None:
            return None
        return FitModelSpec.from_dict(raw)

    def set(self, name: str, spec: FitModelSpec) -> bool:
        self._templates[name] = spec.to_dict()
        return self.save()

    def delete(self, name: str) -> bool:
        self._templates.pop(name, None)
        return self.save()
