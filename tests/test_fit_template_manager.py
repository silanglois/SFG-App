"""Tests for src/sfg_app2/app/utils/fit_template_manager.py -- Qt-free,
just JSON persistence + FitModelSpec (de)serialization.

Run with:
    uv run pytest tests/test_fit_template_manager.py -v
"""
import json

import pytest

from sfg_app2.app.utils import fit_template_manager as ftm_module
from sfg_app2.app.utils.fit_template_manager import FitTemplateManager
from sfg_app2.processing.fitting import FitModelSpec, FitParam, PeakInstance


@pytest.fixture
def manager(tmp_path, monkeypatch):
    """A FitTemplateManager backed by a throwaway config dir -- never
    touches the real user's ~/.../SFG-App/fit_templates.json."""
    config_dir = tmp_path / "SFG-App"
    monkeypatch.setattr(ftm_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(ftm_module, "TEMPLATES_FILE", config_dir / "fit_templates.json")
    return FitTemplateManager()


def _make_spec(amplitude: float = 3.0) -> FitModelSpec:
    return FitModelSpec(
        nonresonant={"amplitude": FitParam(1.0), "phase": FitParam(0.0)},
        peaks=[PeakInstance("lorentzian", {
            "amplitude": FitParam(amplitude, shared=True), "center": FitParam(3300.0), "width": FitParam(10.0),
        })],
    )


def test_set_and_get_round_trips_spec_and_fit_range_and_weighting(manager):
    spec = _make_spec()
    assert manager.set("my template", spec, fit_range=(3200.0, 3400.0), weighting="statistical")

    got = manager.get("my template")
    assert got.peaks[0].params["amplitude"].value == 3.0
    assert got.peaks[0].params["amplitude"].shared is True   # shared flag round-trips too

    full = manager.get_full("my template")
    assert full["fit_range"] == (3200.0, 3400.0)
    assert full["weighting"] == "statistical"


def test_set_without_fit_range_or_weighting_stores_none(manager):
    manager.set("bare", _make_spec())
    full = manager.get_full("bare")
    assert full["fit_range"] is None
    assert full["weighting"] is None


def test_legacy_bare_spec_dict_format_still_loads(manager, tmp_path):
    """A template file saved by the pre-fit_range/weighting version of
    this app is just {"templates": {"name": <FitModelSpec.to_dict()>}}
    -- no "model" key. get()/get_full() must still read it correctly."""
    ftm_module.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    legacy = {"templates": {"old one": _make_spec(7.0).to_dict()}}
    ftm_module.TEMPLATES_FILE.write_text(json.dumps(legacy))

    manager.load()
    spec = manager.get("old one")
    assert spec is not None
    assert spec.peaks[0].params["amplitude"].value == 7.0

    full = manager.get_full("old one")
    assert full["fit_range"] is None
    assert full["weighting"] is None


def test_names_lists_sorted(manager):
    manager.set("zebra", _make_spec())
    manager.set("apple", _make_spec())
    assert manager.names() == ["apple", "zebra"]


def test_delete_removes_template(manager):
    manager.set("temp", _make_spec())
    assert "temp" in manager.names()
    assert manager.delete("temp")
    assert "temp" not in manager.names()


def test_rename_moves_value_and_rejects_missing_or_noop(manager):
    manager.set("old", _make_spec(5.0))
    assert manager.rename("old", "new")
    assert manager.names() == ["new"]
    assert manager.get("new").peaks[0].params["amplitude"].value == 5.0

    assert manager.rename("does not exist", "whatever") is False
    manager.set("x", _make_spec())
    assert manager.rename("x", "x") is False   # no-op rename rejected


def test_export_then_import_round_trips_into_a_fresh_manager(manager, tmp_path):
    manager.set("a", _make_spec(1.0), fit_range=(100.0, 200.0), weighting="none")
    manager.set("b", _make_spec(2.0))

    out_file = tmp_path / "exported.json"
    assert manager.export_to_file(["a", "b"], out_file)

    imported = manager.import_from_file(out_file)   # import back into the SAME manager -> collisions
    assert set(imported) == {"a (2)", "b (2)"}   # collision-safe renaming, originals untouched
    assert manager.get("a").peaks[0].params["amplitude"].value == 1.0
    assert manager.get("a (2)").peaks[0].params["amplitude"].value == 1.0
    assert manager.get_full("a (2)")["fit_range"] == (100.0, 200.0)


def test_import_from_missing_file_returns_empty_list(manager, tmp_path):
    assert manager.import_from_file(tmp_path / "does_not_exist.json") == []


def test_export_to_file_only_includes_requested_names(manager, tmp_path):
    manager.set("keep", _make_spec())
    manager.set("also keep", _make_spec())
    manager.set("leave out", _make_spec())
    out_file = tmp_path / "subset.json"
    manager.export_to_file(["keep"], out_file)
    data = json.loads(out_file.read_text())
    assert list(data["templates"].keys()) == ["keep"]
