"""Exporting and importing the whole configuration as one file.

The round trip is the point: write a bundle, wipe the config, import,
and get the same settings back. Everything here runs against the
isolated config directory from conftest, so it never touches the real
one.

Run with:
    uv run pytest tests/test_settings_bundle.py -v
"""
import json
import zipfile

import pytest

from sfg_app2.app.utils import settings_bundle
from sfg_app2.app.utils.calibration_settings import (
    LINES, CalibrationConfig, CalibrationSettings,
)
from sfg_app2.app.utils.file_format_settings import FileFormatSettings
from sfg_app2.app.utils.pattern_manager import PatternManager
from sfg_app2.processing.readers import ReadOptions


@pytest.fixture
def configured():
    """A config directory with a few parts actually saved."""
    patterns = PatternManager()
    patterns.save()

    formats = FileFormatSettings()
    formats.set_options(ReadOptions(delimiter=";", decimal=","))

    calibration = CalibrationSettings()
    calibration.set_config(CalibrationConfig(kind=LINES, lines=[2850.0, 2920.0]))
    return {"patterns": patterns, "formats": formats, "calibration": calibration}


def test_only_settings_that_exist_are_offered(configured):
    keys = {part.key for part in settings_bundle.available_parts()}
    assert {"patterns", "file_formats", "calibration"} <= keys
    # Never saved in this test, so there is nothing to offer.
    assert "fit_templates" not in keys


def test_a_bundle_round_trips_every_saved_part(tmp_path, configured):
    bundle = tmp_path / "settings.zip"
    written = settings_bundle.export_bundle(bundle)
    assert {"patterns", "file_formats", "calibration"} <= set(written)

    # Wipe the lot, then restore.
    for part in settings_bundle.available_parts():
        if not part.is_directory:
            part.path().unlink()

    assert FileFormatSettings().is_default(), "precondition: settings really gone"
    restored = settings_bundle.import_bundle(bundle)
    assert set(restored) == set(written)

    assert FileFormatSettings().options.delimiter == ";"
    assert CalibrationSettings().config.lines == [2850.0, 2920.0]


def test_exporting_a_subset_writes_only_that(tmp_path, configured):
    bundle = tmp_path / "settings.zip"
    settings_bundle.export_bundle(bundle, ["calibration"])

    with zipfile.ZipFile(bundle) as archive:
        manifest = json.loads(archive.read(settings_bundle.MANIFEST_NAME))
    assert manifest["parts"] == ["calibration"]


def test_importing_a_subset_leaves_the_rest_alone(tmp_path, configured):
    bundle = tmp_path / "settings.zip"
    settings_bundle.export_bundle(bundle)

    FileFormatSettings().set_options(ReadOptions(delimiter="\t"))
    settings_bundle.import_bundle(bundle, ["calibration"])
    assert FileFormatSettings().options.delimiter == "\t", "unrelated part was touched"


def test_custom_plot_styles_travel_as_a_directory(tmp_path, configured):
    """Styles are a folder of files, which is why the bundle is a zip
    rather than one JSON."""
    from sfg_app2.app.utils import plotting_settings

    plotting_settings.CUSTOM_STYLES_DIR.mkdir(parents=True, exist_ok=True)
    (plotting_settings.CUSTOM_STYLES_DIR / "lab.json").write_text('{"axes.grid": true}')

    bundle = tmp_path / "settings.zip"
    assert "custom_styles" in settings_bundle.export_bundle(bundle)

    (plotting_settings.CUSTOM_STYLES_DIR / "lab.json").unlink()
    settings_bundle.import_bundle(bundle, ["custom_styles"])
    assert (plotting_settings.CUSTOM_STYLES_DIR / "lab.json").exists()


def test_dock_layouts_are_not_exported():
    """They're window geometry for one machine's screen."""
    assert "dock_layout" not in {part.key for part in settings_bundle.PARTS}


# ── Refusing what it can't read ───────────────────────────────────────────

def test_a_file_that_is_not_a_bundle_is_refused_clearly(tmp_path):
    path = tmp_path / "notes.zip"
    path.write_text("this is not a zip")
    with pytest.raises(ValueError, match="isn't a settings bundle"):
        settings_bundle.read_manifest(path)


def test_a_zip_without_a_manifest_is_refused(tmp_path):
    path = tmp_path / "empty.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("patterns/patterns.json", "{}")
    with pytest.raises(ValueError, match="isn't a settings bundle"):
        settings_bundle.read_manifest(path)


def test_a_bundle_from_another_schema_version_is_refused(tmp_path):
    """The reason the version is recorded at all: a layout change has to
    fail loudly rather than half-import."""
    path = tmp_path / "future.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(settings_bundle.MANIFEST_NAME,
                         json.dumps({"schema": 99, "parts": ["patterns"]}))
    with pytest.raises(ValueError, match="different version"):
        settings_bundle.read_manifest(path)


def test_an_unknown_part_in_a_bundle_is_skipped_not_fatal(tmp_path, configured):
    """Forwards compatibility: a bundle naming a part this build doesn't
    have should still restore the parts it does."""
    path = tmp_path / "mixed.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("calibration/calibration_settings.json",
                         json.dumps(CalibrationConfig(kind=LINES, lines=[1.0]).to_dict()))
        archive.writestr("from_the_future/x.json", "{}")
        archive.writestr(settings_bundle.MANIFEST_NAME, json.dumps(
            {"schema": settings_bundle.SCHEMA_VERSION,
             "parts": ["calibration", "from_the_future"]}))

    assert settings_bundle.import_bundle(path) == ["calibration"]
    assert CalibrationSettings().config.lines == [1.0]


# ── The dialog ────────────────────────────────────────────────────────────

def test_the_chooser_lists_and_returns_parts(qtbot, configured):
    from sfg_app2.app.dialogs.settings_bundle_dialog import SettingsBundleDialog

    dialog = SettingsBundleDialog("export")
    qtbot.addWidget(dialog)
    assert "calibration" in dialog.selected_keys()

    importer = SettingsBundleDialog("import", ["patterns"])
    qtbot.addWidget(importer)
    assert importer.selected_keys() == ["patterns"]
