"""heterodyne -> phase-resolved rename: new names are written, and
everything saved under the old name still loads."""
import json

import pytest

from sfg_app2.processing import fitting, provenance
from sfg_app2.processing.kinds import (
    HOMODYNE, PHASE_RESOLVED, header_token, kind_label, normalize_kind,
)
from sfg_app2.processing.processed_spectrum import ProcessedSpectrum


@pytest.mark.parametrize("name", ["heterodyne", "Heterodyne", " HD-SFG ", "phase-resolved",
                                  "phase_resolved", "PR-SFG", "Phase-resolved"])
def test_every_phase_resolved_spelling_normalizes(name):
    assert normalize_kind(name) == PHASE_RESOLVED


@pytest.mark.parametrize("name", ["homodyne", "Homodyne", "", None, "anything"])
def test_everything_else_is_homodyne(name):
    assert normalize_kind(name) == HOMODYNE


def test_labels_and_header_token():
    assert kind_label("heterodyne") == "Phase-resolved"
    assert kind_label(HOMODYNE) == "Homodyne"
    assert header_token(PHASE_RESOLVED) == "phase-resolved"


def _write(tmp_path, header: str):
    path = tmp_path / "x.csv"
    path.write_text(header + "Wavenumber,Real,Imaginary\n2900,1,2\n", encoding="utf-8")
    return path


def test_legacy_heterodyne_csv_reads_as_phase_resolved(tmp_path):
    _, prov, _ = provenance.parse_export_header(
        _write(tmp_path, "# SFG-App export\n# Type:        heterodyne\n"))
    assert prov["kind"] == PHASE_RESOLVED


def test_new_export_writes_phase_resolved_and_round_trips(tmp_path):
    import pandas as pd
    spectrum = ProcessedSpectrum(
        pd.DataFrame({"Wavenumber": [2900.0], "Real": [1.0], "Imaginary": [2.0]}),
        metadata={}, history=["x"], provenance={"kind": PHASE_RESOLVED})
    text = provenance.csv_with_provenance_text(spectrum, PHASE_RESOLVED, "lbl", None)
    assert "# Type:        phase-resolved" in text
    assert "heterodyne" not in text.lower()
    path = tmp_path / "new.csv"
    path.write_text(text, encoding="utf-8")
    _, prov, _ = provenance.parse_export_header(path)
    assert prov["kind"] == PHASE_RESOLVED


def test_legacy_fit_kind_reloads():
    assert fitting.fit_kind_from_provenance_payload({"kind": "heterodyne"}) == PHASE_RESOLVED
    assert fitting.fit_kind_from_provenance_payload({}) is None


def test_legacy_matching_profile_loads():
    from sfg_app2.app.utils.matching_settings import MatchingSettings
    settings = MatchingSettings.from_dict({
        "type_rules": [{"mode": "filename", "key": "x", "type": "heterodyne", "scope": "both"}],
        "background_role_priority": {"heterodyne": ["irbg", "bg"]},
    })
    assert settings.type_rules[0]["type"] == PHASE_RESOLVED
    assert settings.background_role_priority == {PHASE_RESOLVED: ["irbg", "bg"]}
    json.dumps(settings.to_dict())


def test_dock_layout_restores_from_legacy_key(qtbot):
    from sfg_app2.app.tabs.process_review import ProcessReviewTab
    tab = ProcessReviewTab()
    qtbot.addWidget(tab)
    saved = tab._pr_sfg_panel.save_dock_state()

    class Legacy:
        def get(self, key):
            return {"hd_sfg": saved}.get(key)

    restored = []
    tab._pr_sfg_panel.restore_dock_state = restored.append
    tab.restore_dock_layouts(Legacy())
    assert restored == [saved]
