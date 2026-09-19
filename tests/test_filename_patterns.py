"""Filename -> metadata parsing: positional patterns, regex patterns,
and how a pattern gets chosen for a given file.

The regression guards here matter more than the new features: stored
patterns are a bare {"fields": [...]} written by older versions, and
those have to keep meaning exactly what they always meant.

Run with:
    uv run pytest tests/test_filename_patterns.py -v
"""
import numpy as np
import pandas as pd
import pytest

from sfg_app2.processing.data_file import DataFile, FilenamePattern
from sfg_app2.processing.utils import load_datafiles, select_pattern


@pytest.fixture
def make_csv(tmp_path):
    """A minimal readable spectrum file with the given name."""
    def _make(name: str):
        path = tmp_path / name
        pd.DataFrame({
            "Frame": 1,
            "Wavelength": np.linspace(780.0, 800.0, 8),
            "Intensity": 1.0,
        }).to_csv(path, index=False)
        return path
    return _make


# ── Backward compatibility ────────────────────────────────────────────────

def test_a_bare_field_list_still_means_positional_on_underscores():
    """The historical call shape, used by stored patterns and by tests."""
    pattern = FilenamePattern.coerce(["sample", "polarization", "date"])
    assert pattern.mode == "positional"
    assert pattern.delimiter == "_"
    assert pattern.match("water_ssp_2024") == {
        "sample": "water", "polarization": "ssp", "date": "2024"}


def test_a_stored_fields_only_leaf_coerces_the_same_way():
    """patterns.json leaves written before this change."""
    assert (FilenamePattern.coerce({"fields": ["a", "b"]})
            == FilenamePattern.coerce(["a", "b"]))


def test_extract_keeps_leftovers_rather_than_dropping_them(make_csv):
    path = make_csv("water_ssp_2024_extra.csv")
    metadata = DataFile(path, filename_fields=["sample", "polarization"]).metadata
    assert metadata["sample"] == "water"
    assert metadata["extra_filename_parts"] == ["2024", "extra"]


def test_no_pattern_keeps_the_raw_parts(make_csv):
    metadata = DataFile(make_csv("water_ssp_2024.csv")).metadata
    assert metadata["filename_parts"] == ["water", "ssp", "2024"]


# ── New: delimiters and regex ─────────────────────────────────────────────

def test_a_custom_delimiter_is_honoured():
    pattern = FilenamePattern(fields=["sample", "polarization"], delimiter="-")
    assert pattern.match("water-ssp") == {"sample": "water", "polarization": "ssp"}
    assert pattern.match("water_ssp") is None


def test_regex_named_groups_become_the_fields():
    pattern = FilenamePattern(
        mode="regex", regex=r"^(?P<sample>[^-]+)-(?P<polarization>[a-z]{3})$")
    assert pattern.match("water-ssp") == {"sample": "water", "polarization": "ssp"}
    assert pattern.field_names() == ["sample", "polarization"]


def test_a_regex_that_does_not_match_declines_rather_than_guessing():
    pattern = FilenamePattern(mode="regex", regex=r"^(?P<sample>\d+)$")
    assert pattern.match("water") is None


def test_an_invalid_regex_is_inert_instead_of_raising():
    """It's typed into a text box, so it will be invalid mid-keystroke."""
    pattern = FilenamePattern(mode="regex", regex=r"(?P<unclosed>")
    assert pattern.match("anything") is None
    assert pattern.field_names() == []


# ── Choosing between patterns ─────────────────────────────────────────────

def test_positional_patterns_are_chosen_by_token_count():
    three = FilenamePattern(fields=["a", "b", "c"])
    two = FilenamePattern(fields=["a", "b"])
    assert select_pattern("x_y", [three, two]) is two
    assert select_pattern("x_y_z", [three, two]) is three


def test_regex_patterns_are_tried_before_positional_ones():
    """A regex can actually inspect the text, so it gets to claim the
    file first -- that's what makes it the escape hatch for layouts
    positional parsing can't tell apart."""
    positional = FilenamePattern(fields=["a", "b"])
    regex = FilenamePattern(mode="regex", regex=r"^(?P<sample>\w+)_(?P<pol>ssp)$")
    assert select_pattern("water_ssp", [positional, regex]) is regex


def test_equal_length_positional_patterns_resolve_to_the_first_deterministically():
    """They can't be told apart by content -- but the old token-count map
    silently kept whichever was built last, which made the choice depend
    on tree order in a way nothing documented."""
    first = FilenamePattern(fields=["a", "b"], name="first")
    second = FilenamePattern(fields=["c", "d"], name="second")
    assert select_pattern("x_y", [first, second]) is first


def test_no_applicable_pattern_returns_none():
    assert select_pattern("x_y_z", [FilenamePattern(fields=["a", "b"])]) is None


# ── The role suffix must not break pattern matching ───────────────────────

def test_an_anchored_regex_still_matches_a_background_file(make_csv, tmp_path):
    """Selection and extraction have to see the same text. They didn't:
    selection used the role-stripped stem while extraction re-split the
    full one, so "..._bg" failed any regex anchored with $."""
    make_csv("SAMPLE-ssp-2024.csv")
    make_csv("SAMPLE-ssp-2024_bg.csv")
    pattern = FilenamePattern(
        mode="regex", regex=r"^(?P<sample>[^-]+)-(?P<polarization>[a-z]{3})-(?P<date>\d+)$")

    loaded = {f.path.name: f.metadata for f in load_datafiles(tmp_path, patterns=[pattern])}
    assert loaded["SAMPLE-ssp-2024.csv"]["sample"] == "SAMPLE"

    background = loaded["SAMPLE-ssp-2024_bg.csv"]
    assert background["sample"] == "SAMPLE", "role suffix broke the match"
    assert background["date"] == "2024"
    assert background["role"] == "background"


# ── Re-parsing under a different pattern ──────────────────────────────────

def test_reparsing_swaps_the_parsed_fields(make_csv):
    """Toggling "Use metadata patterns" calls this on every loaded file;
    it used to raise AttributeError because the method didn't exist."""
    data_file = DataFile(make_csv("water_ssp_2024.csv"),
                         filename_fields=["sample", "polarization", "date"])
    assert data_file.metadata["sample"] == "water"

    data_file.reparse_filename_metadata(["solvent", "pol", "year"])
    assert data_file.metadata["solvent"] == "water"
    assert data_file.metadata["year"] == "2024"


def test_manual_metadata_survives_reparsing(make_csv):
    data_file = DataFile(make_csv("water_ssp_2024.csv"),
                         filename_fields=["sample", "polarization", "date"])
    data_file.set_manual_metadata("sample", "corrected by hand")

    data_file.reparse_filename_metadata(["sample", "polarization", "date"])
    assert data_file.metadata["sample"] == "corrected by hand"


def test_the_detected_role_survives_reparsing(make_csv):
    """Role comes from role-stripping, not from the pattern, so changing
    the pattern must not drop it -- auto-matching depends on it."""
    data_file = DataFile(make_csv("water_ssp_bg.csv"),
                         filename_fields=["sample", "polarization"],
                         metadata={"role": "background"})
    data_file.reparse_filename_metadata(["a", "b", "c"])
    assert data_file.metadata["role"] == "background"
