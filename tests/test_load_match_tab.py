"""Qt-layer tests for the Load / Match tab.

Run with:
    uv run pytest tests/test_load_match_tab.py -v
"""
import types

import pytest

from sfg_app2.app.tabs.load_match import LoadMatchTab


@pytest.fixture
def load_match_tab(qtbot):
    tab = LoadMatchTab()
    qtbot.addWidget(tab)
    return tab


def _with_fake_main(tab, monkeypatch, *, use_patterns: bool, active_patterns):
    """Stand in for the MainWindow that _get_active_patterns reaches via
    self.window(), which is None for a parentless tab under test."""
    fake_main = types.SimpleNamespace(
        use_metadata_patterns=use_patterns,
        pattern_manager=types.SimpleNamespace(active_patterns=active_patterns),
    )
    monkeypatch.setattr(tab, "window", lambda: fake_main)
    return fake_main


def test_patterns_are_returned_when_the_toggle_is_on(load_match_tab, monkeypatch):
    patterns = [["sample", "polarization"]]
    _with_fake_main(load_match_tab, monkeypatch, use_patterns=True, active_patterns=patterns)

    assert load_match_tab._get_active_patterns() == patterns


def test_toggle_off_disables_pattern_parsing(load_match_tab, monkeypatch):
    """Preferences > Load / Match > Use metadata patterns must actually
    disable parsing.

    A duplicate definition of _get_active_patterns used to shadow the
    real one and drop this check, so the toggle did nothing while the
    status bar still announced "Metadata patterns disabled". None is the
    documented signal that tells load_datafiles to skip parsing.
    """
    _with_fake_main(
        load_match_tab, monkeypatch,
        use_patterns=False, active_patterns=[["sample", "polarization"]],
    )

    assert load_match_tab._get_active_patterns() is None


def test_only_one_definition_of_get_active_patterns():
    """Guards against the shadowing regression returning: a second `def`
    in the class body silently wins and is invisible at the call sites.
    """
    import inspect

    source = inspect.getsource(LoadMatchTab)
    assert source.count("def _get_active_patterns") == 1
