"""homodyne/heterodyne -> conventional/phase-resolved rename: new names
are written, and everything saved under the old names still loads."""
import json

import pytest

from sfg_app2.processing import fitting, provenance
from sfg_app2.processing.kinds import (
    CONVENTIONAL, PHASE_RESOLVED, header_token, kind_label, normalize_kind,
)
from sfg_app2.processing.processed_spectrum import ProcessedSpectrum


@pytest.mark.parametrize("name", ["heterodyne", "Heterodyne", " HD-SFG ", "phase-resolved",
                                  "phase_resolved", "PR-SFG", "Phase-resolved"])
def test_every_phase_resolved_spelling_normalizes(name):
    assert normalize_kind(name) == PHASE_RESOLVED


@pytest.mark.parametrize("name", ["conventional", "Conventional", "homodyne", "Homodyne",
                                  "", None, "anything"])
def test_everything_else_is_conventional(name):
    assert normalize_kind(name) == CONVENTIONAL


def test_labels_and_header_token():
    assert kind_label("heterodyne") == "Phase-resolved"
    assert kind_label(CONVENTIONAL) == "Conventional"
    assert header_token(PHASE_RESOLVED) == "phase-resolved"
    assert kind_label("homodyne") == "Conventional"
    assert header_token("homodyne") == "conventional"


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


@pytest.mark.parametrize("legacy_key, panel_attr", [("hd_sfg", "_pr_sfg_panel"),
                                                    ("homodyne", "_conventional_panel")])
def test_dock_layout_restores_from_legacy_key(qtbot, legacy_key, panel_attr):
    from sfg_app2.app.tabs.process_review import ProcessReviewTab
    tab = ProcessReviewTab()
    qtbot.addWidget(tab)
    panel = getattr(tab, panel_attr)
    saved = panel.save_dock_state()

    class Legacy:
        def get(self, key):
            return {legacy_key: saved}.get(key)

    restored = []
    panel.restore_dock_state = restored.append
    tab.restore_dock_layouts(Legacy())
    assert restored == [saved]


def test_conventional_export_writes_its_type_and_round_trips(tmp_path):
    import pandas as pd
    spectrum = ProcessedSpectrum(
        pd.DataFrame({"Frame": [1], "Wavenumber": [2900.0], "Intensity": [1.0]}),
        metadata={}, history=["x"], provenance={})
    text = provenance.csv_with_provenance_text(spectrum, CONVENTIONAL, "lbl", None)
    assert "# Type:        conventional" in text
    assert "homodyne" not in text.lower()
    path = tmp_path / "conv.csv"
    path.write_text(text, encoding="utf-8")
    _, prov, _ = provenance.parse_export_header(path)
    assert prov["kind"] == CONVENTIONAL


def test_legacy_homodyne_column_loads_as_abs2(tmp_path, results_tab, monkeypatch):
    path = tmp_path / "old_pr.csv"
    path.write_text(
        "# SFG-App export\n# Type:        heterodyne\n# Label:       old\n"
        "Wavenumber,Real,Imaginary,Phase,Homodyne,Real_err,Imag_err,Phase_err,Homodyne_err\n"
        "2900,1,2,63,5,0.1,0.1,1,0.2\n2910,1,1,45,2,0.1,0.1,1,0.2\n",
        encoding="utf-8")
    df = provenance.load_csv_skip_comments(path)
    assert {"Chi2_abs2", "Chi2_abs2_err"} <= set(df.columns)
    assert "Homodyne" not in df.columns

    # ...and the Spectra Library plots it as the |chi|^2 component.
    monkeypatch.setattr("sfg_app2.app.tabs.processed_results.QFileDialog.getOpenFileNames",
                        lambda *a, **k: ([str(path)], ""))
    results_tab._on_add_from_file()
    entry = results_tab._entries[-1]
    assert entry.kind == PHASE_RESOLVED
    entry.checked = True   # loaded entries start unticked
    for name, box in results_tab._pr_checkboxes.items():
        box.setChecked(name == "|χ⁽²⁾|²")
    results_tab._refresh_plot()
    ys = [list(line.get_ydata()) for line in results_tab.plot_widget.ax.get_lines()]
    assert [5.0, 2.0] in ys or [2.0, 5.0] in ys

