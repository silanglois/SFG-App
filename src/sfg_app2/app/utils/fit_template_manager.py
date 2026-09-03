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
    bounds, constraints, and optionally the fit range/weighting they were
    saved with) so a model can be saved once and re-applied to other
    spectra — this is also the mechanism for "copy parameters between
    spectra": save the current fit as a template, apply it elsewhere.

    Each stored template is `{"model": FitModelSpec.to_dict(), "fit_range":
    [lo, hi] | None, "weighting": str | None}`. Older files saved before
    fit_range/weighting existed are just a bare FitModelSpec.to_dict()
    (no "model" key) -- get()/get_full() detect and handle that legacy
    shape transparently, so old templates keep loading unchanged.
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

    @staticmethod
    def _unpack(raw: dict) -> dict:
        """raw -> {"spec": FitModelSpec, "fit_range": tuple|None,
        "weighting": str|None}, transparently handling the legacy
        bare-spec-dict shape (no "model" key)."""
        if "model" in raw:
            fit_range = raw.get("fit_range")
            return {
                "spec": FitModelSpec.from_dict(raw["model"]),
                "fit_range": tuple(fit_range) if fit_range else None,
                "weighting": raw.get("weighting"),
            }
        return {"spec": FitModelSpec.from_dict(raw), "fit_range": None, "weighting": None}

    def get(self, name: str) -> FitModelSpec | None:
        raw = self._templates.get(name)
        if raw is None:
            return None
        return self._unpack(raw)["spec"]

    def get_full(self, name: str) -> dict | None:
        """Like get(), but also returns the saved fit_range/weighting
        (None for either if the template predates them, or was never
        given them)."""
        raw = self._templates.get(name)
        if raw is None:
            return None
        return self._unpack(raw)

    def set(self, name: str, spec: FitModelSpec,
            fit_range: tuple[float, float] | None = None, weighting: str | None = None) -> bool:
        self._templates[name] = {
            "model": spec.to_dict(),
            "fit_range": list(fit_range) if fit_range else None,
            "weighting": weighting,
        }
        return self.save()

    def delete(self, name: str) -> bool:
        self._templates.pop(name, None)
        return self.save()

    def rename(self, old: str, new: str) -> bool:
        if old not in self._templates or old == new:
            return False
        self._templates[new] = self._templates.pop(old)
        return self.save()

    def _unique_name(self, name: str) -> str:
        if name not in self._templates:
            return name
        n = 2
        candidate = f"{name} ({n})"
        while candidate in self._templates:
            n += 1
            candidate = f"{name} ({n})"
        return candidate

    def export_to_file(self, names: list[str], path: str | Path) -> bool:
        """Writes the given templates (by name) to a standalone .json
        file, in the exact same {"templates": {...}} shape as the main
        store -- so the same file can later be handed to
        import_from_file() (on this machine or another)."""
        try:
            subset = {name: self._templates[name] for name in names if name in self._templates}
            Path(path).write_text(json.dumps({"templates": subset}, indent=2))
            return True
        except Exception as e:
            logger.error("Failed to export fit templates to %s: %s", path, e)
            return False

    def import_from_file(self, path: str | Path) -> list[str]:
        """Merges every template found in `path` into the store, renaming
        on collision (mirrors ProcessedResultsTab._unique_label's " (2)",
        " (3)", ... convention) rather than silently overwriting an
        existing template of the same name. Returns the names actually
        used (which may differ from the file's own names, on collision);
        an empty list means nothing was imported (bad/empty file)."""
        try:
            raw = json.loads(Path(path).read_text())
            incoming = raw.get("templates", {})
        except Exception as e:
            logger.error("Failed to import fit templates from %s: %s", path, e)
            return []

        imported = []
        for name, template in incoming.items():
            final_name = self._unique_name(name)
            self._templates[final_name] = template
            imported.append(final_name)
        if imported:
            self.save()
        return imported
