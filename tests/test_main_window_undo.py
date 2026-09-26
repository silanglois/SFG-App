"""The Edit menu's QUndoGroup tracks whichever tab is active."""
import pytest

from sfg_app2.app.main_window import MainWindow


@pytest.fixture
def main_window(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    return window


def test_initial_active_stack_matches_current_tab(main_window):
    index = main_window.ui.mainTabWidget.currentIndex()
    expected = main_window._tab_undo_stacks.get(index)
    assert main_window._undo_group.activeStack() is expected


def test_switching_to_spectra_library_activates_its_stack(main_window):
    main_window.ui.mainTabWidget.setCurrentIndex(2)
    assert main_window._undo_group.activeStack() is main_window.processed_results_tab.undo_stack


def test_switching_to_fitting_activates_its_stack(main_window):
    main_window.ui.mainTabWidget.setCurrentIndex(3)
    assert main_window._undo_group.activeStack() is main_window.fitting_tab.undo_stack


def test_switching_to_load_match_activates_its_stack(main_window):
    main_window.ui.mainTabWidget.setCurrentIndex(2)
    main_window.ui.mainTabWidget.setCurrentIndex(0)
    assert main_window._undo_group.activeStack() is main_window.load_match_tab.undo_stack


def test_process_review_tab_has_no_undo_stack(main_window):
    main_window.ui.mainTabWidget.setCurrentIndex(1)
    assert main_window._undo_group.activeStack() is None


def test_undo_redo_actions_exist_in_edit_menu(main_window):
    actions = main_window._edit_menu.actions()
    assert len(actions) == 2
    assert actions[0].text().startswith("Undo")
    assert actions[1].text().startswith("Redo")


def test_edit_menu_is_right_after_file_menu(main_window):
    menu_actions = main_window.menuBar().actions()
    titles = [a.text() for a in menu_actions]
    file_index = titles.index(main_window.ui.menuFile.title())
    assert titles[file_index + 1] == main_window._edit_menu.title()
