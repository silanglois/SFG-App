"""Exporting and importing the app's configuration as one file.

Everything configurable here — filename patterns, matching profiles,
fit templates, plotting styles, import options, the calibration
reference — lives in its own JSON under one config directory. That's
fine for one machine and useless for handing a working setup to
somebody else in the lab, which is what this is for.

A zip rather than a single JSON, because plotting styles are a
*directory* of files, not one. Every bundle records a schema version:
a future layout change has to be able to refuse an old bundle clearly
rather than half-importing it.
"""
from __future__ import annotations

import json
import logging
import zipfile
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
MANIFEST_NAME = "bundle.json"


@dataclass(frozen=True)
class SettingsPart:
    """One exportable piece of configuration.

    `module`/`attribute` are resolved at call time rather than import
    time: the test suite redirects every store by monkeypatching those
    module attributes, and caching the paths here would read straight
    past that and touch the real user config.
    """

    key: str
    label: str
    module: str
    attribute: str
    is_directory: bool = False

    def path(self) -> Path:
        module = import_module(f"sfg_app2.app.utils.{self.module}")
        return Path(getattr(module, self.attribute))


PARTS: tuple[SettingsPart, ...] = (
    SettingsPart("patterns", "Filename metadata patterns",
                 "pattern_manager", "PATTERNS_FILE"),
    SettingsPart("matching", "Auto-matching profiles",
                 "matching_settings", "SETTINGS_FILE"),
    SettingsPart("fit_templates", "Fit templates",
                 "fit_template_manager", "TEMPLATES_FILE"),
    SettingsPart("plotting", "Plotting settings",
                 "plotting_settings", "SETTINGS_FILE"),
    SettingsPart("custom_styles", "Custom plot styles",
                 "plotting_settings", "CUSTOM_STYLES_DIR", is_directory=True),
    SettingsPart("color_coding", "Filename colour coding",
                 "color_coding_settings", "SETTINGS_FILE"),
    SettingsPart("file_formats", "File import options",
                 "file_format_settings", "SETTINGS_FILE"),
    SettingsPart("calibration", "Calibration reference",
                 "calibration_settings", "SETTINGS_FILE"),
    SettingsPart("fitting_display", "Fitting display settings",
                 "fitting_display_settings", "SETTINGS_FILE"),
    SettingsPart("appearance", "Appearance",
                 "appearance_settings", "SETTINGS_FILE"),
)

# Dock layouts are deliberately absent: they're window geometry for one
# machine's screen, so carrying them to another is at best noise.


def available_parts() -> list[SettingsPart]:
    """The parts that currently exist on disk — nothing to offer for a
    setting the user has never touched."""
    return [part for part in PARTS
            if part.path().exists()
            and (not part.is_directory or any(part.path().glob("*.json")))]


def export_bundle(path: str | Path, keys: list[str] | None = None) -> list[str]:
    """Write the chosen parts to a zip. Returns the keys written."""
    path = Path(path)
    parts = [p for p in available_parts() if keys is None or p.key in keys]

    written = []
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for part in parts:
            source = part.path()
            if part.is_directory:
                for child in sorted(source.glob("*.json")):
                    archive.write(child, f"{part.key}/{child.name}")
            else:
                archive.write(source, f"{part.key}/{source.name}")
            written.append(part.key)
        archive.writestr(MANIFEST_NAME, json.dumps({
            "schema": SCHEMA_VERSION,
            "parts": written,
        }, indent=2))
    logger.info("Exported %d settings part(s) to %s.", len(written), path)
    return written


def read_manifest(path: str | Path) -> dict:
    """The bundle's manifest, or a clear error if it isn't one."""
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read(MANIFEST_NAME))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as e:
        raise ValueError(f"{Path(path).name} isn't a settings bundle ({e}).") from e

    schema = manifest.get("schema")
    if schema != SCHEMA_VERSION:
        raise ValueError(
            f"{Path(path).name} was written by a different version of the app "
            f"(bundle format {schema}, this build reads {SCHEMA_VERSION})."
        )
    return manifest


def import_bundle(path: str | Path, keys: list[str] | None = None) -> list[str]:
    """Restore the chosen parts. Returns the keys actually restored.

    Replaces a part wholesale rather than merging into it: these files
    are trees and profile lists whose entries have generated ids, so a
    key-by-key merge would produce combinations neither side ever had.
    The caller is expected to say which parts it is about to overwrite.
    """
    manifest = read_manifest(path)
    wanted = set(manifest.get("parts", []) if keys is None else keys)
    by_key = {part.key: part for part in PARTS}

    restored = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        for key in manifest.get("parts", []):
            if key not in wanted:
                continue
            part = by_key.get(key)
            if part is None:
                logger.warning("Bundle contains unknown settings part %r.", key)
                continue
            members = [n for n in names if n.startswith(f"{key}/")]
            if not members:
                continue
            target = part.path()
            directory = target if part.is_directory else target.parent
            directory.mkdir(parents=True, exist_ok=True)
            for member in members:
                data = archive.read(member)
                out = (target / Path(member).name if part.is_directory else target)
                out.write_bytes(data)
            restored.append(key)

    logger.info("Imported %d settings part(s) from %s.", len(restored), path)
    return restored
