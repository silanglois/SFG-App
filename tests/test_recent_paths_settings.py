"""Tests for the per-category last-used-directory memory.

isolate_user_config (conftest.py, autouse) redirects CONFIG_DIR/
SETTINGS_FILE into tmp_path, so these hit a throwaway file, never the
real user's config.
"""
from sfg_app2.app.utils import recent_paths_settings as rps


def test_get_last_dir_is_empty_when_nothing_remembered():
    assert rps.get_last_dir("raw_data") == ""


def test_remember_dir_with_a_file_path_stores_its_parent(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    file_path = folder / "spectrum.csv"
    file_path.write_text("x,y\n1,2\n")

    rps.remember_dir("raw_data", file_path)

    assert rps.get_last_dir("raw_data") == str(folder)


def test_remember_dir_with_a_directory_path_stores_itself(tmp_path):
    folder = tmp_path / "exports"
    folder.mkdir()

    rps.remember_dir("spectra_library", folder)

    assert rps.get_last_dir("spectra_library") == str(folder)


def test_category_without_history_falls_back_to_global(tmp_path):
    folder = tmp_path / "somewhere"
    folder.mkdir()
    rps.remember_dir("calibration", folder)

    # "fitting" has never been visited itself -- falls back to whatever
    # was most recently used anywhere.
    assert rps.get_last_dir("fitting") == str(folder)


def test_categories_stay_independent_once_both_have_history(tmp_path):
    folder_a = tmp_path / "a"
    folder_a.mkdir()
    folder_b = tmp_path / "b"
    folder_b.mkdir()

    rps.remember_dir("raw_data", folder_a)
    rps.remember_dir("figures", folder_b)

    assert rps.get_last_dir("raw_data") == str(folder_a)
    assert rps.get_last_dir("figures") == str(folder_b)


def test_a_remembered_folder_that_no_longer_exists_is_not_returned(tmp_path):
    folder = tmp_path / "temporary"
    folder.mkdir()
    rps.remember_dir("settings", folder)
    folder.rmdir()

    assert rps.get_last_dir("settings") == ""


def test_save_and_load_round_trip(tmp_path):
    folder = tmp_path / "persisted"
    folder.mkdir()
    rps.remember_dir("fitting", folder)

    reloaded = rps.RecentPathsSettings()
    assert reloaded.get("fitting") == str(folder)
