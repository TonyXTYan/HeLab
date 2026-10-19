# tests/test_helabMainWindow.py
import signal
from typing import Generator, Any
from unittest.mock import patch

import pytest
from PyQt6.QtGui import QIcon, QCloseEvent
from pytestqt.qtbot import QtBot
from PyQt6.QtWidgets import QApplication, QMessageBox, QListWidget, QMenu, QWidget, QMainWindow
from PyQt6.QtCore import Qt

from helab.resources.icons import StatusIcons, ToolIcons, PercentageIcon
from helab.views.DebugIconsWindow import DebugIconsWindow
from helab.views.FolderExplorer import FolderExplorer
from helab.views.HelabMainWindow import HelabMainWindow
from helab.views.SettingsDialog import SettingsDialog


def test_qtbot_add_widget(qtbot: QtBot) -> None:
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.show()
    assert widget.isVisible()


def test_about_displays_build_provenance(qtbot: QtBot) -> None:
    from helab.utils.constants import APP_BUILD_INFO
    class AboutWindow(HelabMainWindow):
        def __init__(self) -> None:
            QMainWindow.__init__(self)
        def closeEvent(self, a0: QCloseEvent | None) -> None:
            QMainWindow.closeEvent(self, a0)
    window = AboutWindow()
    qtbot.addWidget(window)
    with patch.object(QMessageBox, "about") as about:
        window.show_about_dialog()
    about.assert_called_once_with(window, "About HeLab", APP_BUILD_INFO.description())


@pytest.fixture
def main_window(qtbot: QtBot) -> Any:
    window = HelabMainWindow()
    assert (isinstance(window, QWidget))
    qtbot.addWidget(window)
    window.show()
    # return window
    yield window
    try:
        window.close()
    except Exception:
        pass

@pytest.fixture(autouse=True)
def disable_warnings() -> Any:
    with patch.object(QMessageBox, 'warning'):
        yield


def test_initial_state_main_window(main_window: HelabMainWindow) -> None:
    assert main_window.width() == main_window.DEFAULT_WIDTH
    assert main_window.height() == main_window.DEFAULT_HEIGHT
    assert main_window.status_bar is not None


def test_toggle_left_panel(main_window: HelabMainWindow) -> None:
    initial_sizes = main_window.splitter.sizes()
    main_window.toggle_left_panel(False)
    collapsed_sizes = main_window.splitter.sizes()
    assert collapsed_sizes[0] == 0
    main_window.toggle_left_panel(True)
    expanded_sizes = main_window.splitter.sizes()
    assert expanded_sizes[0] != 0
    assert expanded_sizes[0] == main_window.left_panel_width or expanded_sizes[0] > 0


def test_toggle_right_panel(main_window: HelabMainWindow) -> None:
    initial_sizes = main_window.splitter.sizes()
    main_window.toggle_right_panel(False)
    collapsed_sizes = main_window.splitter.sizes()
    assert collapsed_sizes[2] == 0
    main_window.toggle_right_panel(True)
    expanded_sizes = main_window.splitter.sizes()
    assert expanded_sizes[2] != 0
    assert expanded_sizes[2] == main_window.right_panel_width or expanded_sizes[2] > 0


def test_add_new_folder_explorer_tab(main_window: HelabMainWindow) -> None:
    initial_count = main_window.tab_widget.count()
    main_window.add_new_folder_explorer_tab()
    assert main_window.tab_widget.count() == initial_count + 1


def test_on_back_button_clicked(main_window: HelabMainWindow) -> None:
    main_window.on_back_button_clicked()
    assert True


def test_close_event_main_window(main_window: HelabMainWindow, qtbot: QtBot) -> None:
    QApplication.processEvents()
    qtbot.wait(1000)
    main_window.close()
    qtbot.wait(1000)
    assert not main_window.isVisible()

# def test_create_menus_main_window(main_window: HelabMainWindow) -> None:
#     menubar = main_window.menu_bar
#     assert menubar is not None
#
#     file_menu = menubar.findChild(QMenu, 'File')
#     assert file_menu is not None
#     assert file_menu.title() == 'File'
#     assert file_menu.actions()[0].text().strip() == 'Open'
#     assert any(action.text().strip().startswith('Open Drives') for action in file_menu.actions())
#
#     view_menu = menubar.findChild(QMenu, 'View')
#     assert view_menu is not None
#     assert view_menu.title() == 'View'
#     view_actions = view_menu.actions()
#     expected_view_actions = [
#         'Toggle Left Toolbar',
#         'Toggle Right Toolbar',
#         'Toggle Status Bar',
#         'Toggle Thread Status Auto Pop-up',
#         'Toggle Auto Load to RAM',
#         'Toggle Left Panel',
#         'Toggle Right Panel'
#     ]
#     for expected_action in expected_view_actions:
#         assert any(action.text().strip() == expected_action for action in view_actions)
#
#     debug_menu = menubar.findChild(QMenu, 'Debug')
#     assert debug_menu is not None
#     assert debug_menu.title() == 'Debug'
#     debug_actions = debug_menu.actions()
#     expected_debug_actions = [
#         'Draw a line in debug console',
#         'Show all Icons',
#         'Show Memory Usage',
#         'Debug 3',
#         'Debug 4',
#         'gc.collect()'
#     ]
#     for expected_action in expected_debug_actions:
#         assert any(action.text().strip() == expected_action for action in debug_actions)


# def test_show_settings_dialog(main_window: HelabMainWindow, qtbot: QtBot) -> None:
#     with patch.object(main_window, 'show_settings_dialog') as mock_show_settings:
#         settings_action = main_window.menu_bar.findChild(QMenu, 'File').actions()[-2]
#         qtbot.mouseClick(settings_action, Qt.MouseButton.LeftButton)
#         mock_show_settings.assert_called_once()


# def test_toggle_auto_load_ram(main_window: HelabMainWindow, qtbot: QtBot) -> None:
#     current_folder_explorer = main_window.tab_widget.currentWidget()
#     if isinstance(current_folder_explorer, FolderExplorer):
#         original_state = current_folder_explorer.auto_load_ram
#         main_window.toggle_auto_load_ram()
#         assert current_folder_explorer.auto_load_ram == (not original_state)
#     else:
#         pytest.skip("Current widget is not FolderExplorer")


# def test_on_live_button_clicked_start(main_window: HelabMainWindow, qtbot: QtBot) -> None:
#     main_window.action_tab_live_checked = False
#     with patch.object(main_window, 'toggle_left_panel') as mock_toggle:
#         qtbot.mouseClick(main_window.action_tab_live, Qt.MouseButton.LeftButton)
#         assert main_window.action_tab_live_checked is True
#         mock_toggle.assert_called_once_with(False)
#         assert main_window.tab_widget.isEnabled() is False
#         assert not main_window.action_tab_refresh.isEnabled()
#         assert not main_window.action_tab_new.isEnabled()
#         assert not main_window.action_tab_rescan.isEnabled()
#         assert not main_window.action_tab_folder_up.isEnabled()


# def test_on_live_button_clicked_stop(main_window: HelabMainWindow, qtbot: QtBot) -> None:
#     main_window.action_tab_live_checked = True
#     with patch.object(main_window, 'toggle_left_panel') as mock_toggle:
#         qtbot.mouseClick(main_window.action_tab_live, Qt.MouseButton.LeftButton)
#         assert main_window.action_tab_live_checked is False
#         mock_toggle.assert_called_once_with(main_window.action_tab_live_was_left_panel_open_before_clicking_live)
#         assert main_window.tab_widget.isEnabled() is True
#         assert main_window.action_tab_refresh.isEnabled()
#         assert main_window.action_tab_new.isEnabled()
#         assert main_window.action_tab_rescan.isEnabled()
#         assert main_window.action_tab_folder_up.isEnabled()


def test_handle_exit_main_window(main_window: HelabMainWindow, qtbot: QtBot) -> None:
    with patch.object(main_window, 'close') as mock_close:
        main_window.handle_exit(signal.SIGINT, None)
        mock_close.assert_called_once()



def test_mismatched_folders_show_in_the_status_bar_and_load_from_the_current_tab(
    main_window: HelabMainWindow, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from helab.utils.folder_cache import get_folder_cache
    from helab.utils.io_service import get_io_service
    cache = get_folder_cache(get_io_service())
    try:
        cache.skip_mismatched = True  # Neither the hold nor the window: only the button and the routing.
        assert not main_window.mismatch_button.isVisible()
        cache._mismatch("/data/run", {"missing": [1], "missing_count": 1, "known_count": 2, "listed_count": 1})
        assert main_window.mismatch_button.isVisible() and main_window.mismatch_button.text() == "⚠ 1 mismatched"
        qtbot.waitUntil(lambda: isinstance(main_window.tab_widget.currentWidget(), FolderExplorer))
        explorer = main_window.tab_widget.currentWidget()
        assert isinstance(explorer, FolderExplorer)
        loads: list[str] = []
        monkeypatch.setattr(explorer, "load_as_it_is_now", loads.append)
        main_window.missing_shots.loadRequested.emit(["/data/run"])
        assert loads == ["/data/run"]
        main_window.mismatch_button.click()
        assert main_window.missing_shots.isVisible()
        main_window.missing_shots.close()
        explorer.reviewMismatchRequested.emit("/data/run")  # A tab's Review…
        assert main_window.missing_shots.isVisible()
        assert main_window.missing_shots.selected_paths() == ["/data/run"]
    finally:
        main_window.missing_shots.close()
        cache.mismatched.clear()
        cache.allow_missing.clear()
        cache.mismatch_count = 0
        cache.skip_mismatched = False
        cache.resume_after_mismatch()


def test_file_menu_places_a_root_in_the_current_tabs_selected_folder(
    main_window: HelabMainWindow, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
) -> None:
    import os
    import uuid
    from helab.utils.folder_cache import PLACE_ROOT_TOOLTIP
    from helab.views import DataRootDialogs
    from helab.views.HelabMainWindow import PLACE_ROOT_MENU
    qtbot.waitUntil(lambda: isinstance(main_window.tab_widget.currentWidget(), FolderExplorer))
    explorer = main_window.tab_widget.currentWidget()
    assert isinstance(explorer, FolderExplorer)
    menu = next(action.menu() for action in main_window.menu_bar.actions() if action.text() == "File")
    assert isinstance(menu, QMenu)
    texts = [action.text() for action in menu.actions()]
    place = main_window.action_place_root
    assert menu.actions().index(place) < texts.index(main_window.action_tab_cancel.text())
    top = explorer.model_root_path
    name = os.path.basename(top.rstrip("/\\")) or top

    def shown() -> tuple[str, bool, str]:
        menu.aboutToShow.emit()
        return place.text(), place.isEnabled(), place.toolTip()
    # Nothing selected: the tab's top folder, which isn't a tree row.
    assert shown() == (f" Place .helab-root in “{name}”…", True, f"{top}\n{PLACE_ROOT_TOOLTIP}")
    asked: list[str] = []
    submitted: list[tuple[str, str, dict[str, Any]]] = []

    def ask(parent: Any, cache: Any, path: str) -> str:
        asked.append(path)
        return path

    def submit(owner: str, generation: int, path: str, operation: str, payload: dict[str, Any],
               **kwargs: Any) -> bool:
        submitted.append((path, operation, payload))
        return True
    monkeypatch.setattr(DataRootDialogs, "ask_place_root", ask)
    monkeypatch.setattr(explorer.model.cache, "submit", submit)
    place.trigger()
    assert asked == [top] and submitted[0][:2] == (top, "root_create") and submitted[0][2]["clicked"] == top
    # A selected folder, with a long name elided in the middle.
    selected = str(tmp_path / ("run_" + "x" * 60))
    explorer.selected_path_globally = selected
    text, enabled, _ = shown()
    assert enabled and text.startswith(" Place .helab-root in “run_xxx") and "…" in text[:-1] and len(text) < 70
    asked.clear()
    place.trigger()
    assert asked == [selected]
    # Already a root: greyed, with the tree menu's tooltip; triggering does nothing.
    explorer.model.cache._root_seen(selected, str(uuid.uuid4()), "run")
    assert shown()[1:] == (False, f"{selected}\nThis folder already has a .helab-root")
    asked.clear()
    assert not main_window.place_root_in_current_tab() and not asked
    explorer.model.cache._root_gone(selected)
    # The disk cache off for this session.
    monkeypatch.setattr("helab.views.FolderExplorer.store_options", lambda: {})
    assert shown()[1:] == (False, f"{selected}\nThe disk cache is off for this session")
    # No folder tab.
    monkeypatch.setattr(main_window.tab_widget, "currentWidget", lambda: None)
    assert shown() == (PLACE_ROOT_MENU, False, "Open a folder tab first")
    assert not main_window.place_root_in_current_tab()


def test_review_root_opens_the_duplicates_window_at_that_location(
    main_window: HelabMainWindow, qtbot: QtBot,
) -> None:
    from helab.utils.folder_cache import get_folder_cache
    from helab.utils.io_service import get_io_service
    cache = get_folder_cache(get_io_service())
    locations = ("smb://server/a", "smb://server/b")
    try:
        for location in locations:
            cache.root_duplicates[location] = {"path": f"/Volumes/{location[-1]}", "location": location,
                                               "uuid": "u", "label": location[-1], "answer": "later",
                                               "found_at": 0.0, "others": []}
        main_window.review_root("smb://server/b")
        window = main_window.root_duplicates
        assert window.isVisible() and window.selected() == "smb://server/b"
        assert window.windowModality() == Qt.WindowModality.NonModal  # Nothing modal open.
    finally:
        for location in locations:
            cache.root_duplicates.pop(location, None)
        main_window.root_duplicates.hide()


def test_review_from_settings_is_modal_only_while_settings_is_open(
    main_window: HelabMainWindow, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PyQt6.QtWidgets import QDialog
    from helab.utils.folder_cache import get_folder_cache
    from helab.utils.io_service import IORequest, get_io_service
    from helab.views.SettingsDialog import SettingsDialog
    cache = get_folder_cache(get_io_service())
    window = main_window.root_duplicates
    location = "smb://server/review"
    modality: list[Qt.WindowModality] = []

    def settings_open(dialog: SettingsDialog) -> int:
        # Review… in Settings › Data roots while the (modal) dialog is open.
        monkeypatch.setattr(QApplication, "activeModalWidget", staticmethod(lambda: dialog))
        main_window.review_root(location)
        modality.append(window.windowModality())
        monkeypatch.setattr(QApplication, "activeModalWidget", staticmethod(lambda: None))
        return int(QDialog.DialogCode.Rejected)
    monkeypatch.setattr(SettingsDialog, "exec", settings_open)
    try:
        cache.root_duplicates[location] = {"path": "/Volumes/review", "location": location, "uuid": "u",
                                           "label": "review", "answer": "later", "found_at": 0.0, "others": []}
        # Settings opens only with no modal widget up (an earlier test's may still be closing).
        monkeypatch.setattr(QApplication, "activeModalWidget", staticmethod(lambda: None))
        main_window.show_settings_dialog()
        assert modality == [Qt.WindowModality.ApplicationModal], "Review… from Settings is modal"
        # Settings closed: the window stays open, no longer modal.
        qtbot.waitUntil(window.isVisible)
        assert window.windowModality() == Qt.WindowModality.NonModal, "non-modal once Settings closed"
        window.hide()
        # An automatic sighting (not through review_root) opens it without blocking the main window.
        cache.service.resultReady.emit(IORequest("helper", 0, "/Volumes/other", "list", {}, 60.0), {
            "kind": "root_duplicate", "path": "/Volumes/other", "location": "smb://server/other", "uuid": "v",
            "label": "other", "other_locations": [], "marker": None, "others": []})
        qtbot.waitUntil(window.isVisible)
        assert window.windowModality() == Qt.WindowModality.NonModal, "an automatic sighting isn't modal"
    finally:
        for key in (location, "smb://server/other"):
            cache.root_duplicates.pop(key, None)
        window.hide()


def test_help_menu_records_the_io_trace_for_this_session(
    main_window: HelabMainWindow, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
) -> None:
    """Off at every start; turned on, a new recording folder in the temp folder's io-traces folder (one
    file per helper) and a status-bar note. Earlier recordings ask once (Keep, the default, or Delete
    old traces); none, no question. Files that can't be deleted are kept, and the user is told."""
    import os
    from helab.utils import cache_location
    from helab.utils.io_service import get_io_service, io_trace_folder
    service = get_io_service()
    action = main_window.action_io_trace
    help_menu = next(item.menu() for item in main_window.menu_bar.actions() if item.text() == "Help")
    assert isinstance(help_menu, QMenu)
    assert {"Record I/O trace (this session)", "Show I/O trace folder"} <= {a.text() for a in help_menu.actions()}
    assert action.isCheckable() and not action.isChecked() and service.trace_dir is None
    assert main_window.io_trace_label.isHidden()
    monkeypatch.setattr("helab.views.HelabMainWindow.DIR_TEMPS", str(tmp_path))
    folder = io_trace_folder(str(tmp_path))
    asked: list[tuple[list[str], str]] = []
    answer = [False]

    def ask(earlier: list[str], where: str) -> bool:
        asked.append((earlier, where))
        return answer[0]

    def record(recording: str, *pids: int) -> None:
        for pid in pids:  # (As helpers write them.)
            with open(os.path.join(recording, f"{pid}.jsonl"), "w", encoding="utf-8") as stream:
                stream.write("{}\n")
    main_window.ask_delete_old_traces = ask
    try:
        # No earlier recordings: no question.
        action.setChecked(True)
        first = service.trace_dir
        assert first is not None and os.path.dirname(first) == folder and os.path.isdir(first) and not asked
        assert main_window.io_trace_label.isVisible() and first in main_window.io_trace_label.toolTip()
        record(first, 101, 102)
        action.setChecked(False)
        assert service.trace_dir is None and main_window.io_trace_label.isHidden()
        other = os.path.join(folder, "notes.txt")  # Not a trace: never removed.
        with open(other, "w", encoding="utf-8") as stream:
            stream.write("kept")
        # Keep (the default): the earlier recording stays.
        action.setChecked(True)
        second = service.trace_dir
        assert asked == [([first], folder)] and second is not None and second != first
        assert sorted(os.listdir(first)) == ["101.jsonl", "102.jsonl"] and os.path.exists(other)
        record(second, 103)
        action.setChecked(False)
        # Delete old traces: only earlier recordings go, never the one about to start. A file Windows
        # won't delete (a helper still has it open) is kept, and the user is told.
        asked.clear()
        answer[0] = True
        remove = os.remove

        def held_open(path: str) -> None:
            if path.endswith("102.jsonl"):
                raise PermissionError(13, "in use", path)
            remove(path)
        monkeypatch.setattr("helab.utils.io_service.os.remove", held_open)
        with patch.object(QMessageBox, "information") as told:
            action.setChecked(True)
        monkeypatch.setattr("helab.utils.io_service.os.remove", remove)
        third = service.trace_dir
        assert asked == [([first, second], folder)] and third is not None
        assert sorted(os.listdir(folder)) == sorted([os.path.basename(first), os.path.basename(third), "notes.txt"])
        assert os.listdir(first) == ["102.jsonl"] and os.listdir(third) == []
        assert told.call_count == 1 and "1 trace file couldn't be deleted" in told.call_args.args[2]
        action.setChecked(False)
        # A temp folder on a share: refused, unticked, nothing recorded.
        monkeypatch.setattr(cache_location, "cache_location_problem", lambda path: "on a network drive (smbfs)")
        with patch.object(QMessageBox, "warning") as warned:
            action.setChecked(True)
        assert not action.isChecked() and service.trace_dir is None and main_window.io_trace_label.isHidden()
        assert "network drive" in warned.call_args.args[2]
    finally:
        main_window.ask_delete_old_traces = None
        action.setChecked(False)
        service.stop_io_trace()


@pytest.mark.parametrize("choice", ["Keep", "Delete old traces", None])
def test_earlier_io_traces_ask_with_keep_as_the_default(
    main_window: HelabMainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, choice: str | None,
) -> None:
    import os
    from helab.utils.number_format import byte_size
    earlier = [str(tmp_path / "io-trace-1"), str(tmp_path / "io-trace-2.jsonl")]  # (A recording; an older file.)
    os.mkdir(earlier[0])
    for file in (os.path.join(earlier[0], "1.jsonl"), os.path.join(earlier[0], "2.jsonl"), earlier[1]):
        with open(file, "wb") as stream:
            stream.write(b"x" * 1000)
    seen: list[tuple[str, str, list[str]]] = []

    def run(box: QMessageBox) -> int:
        default = box.defaultButton()
        assert default is not None
        seen.append((box.text(), default.text(), [button.text() for button in box.buttons()]))
        if choice is not None:  # (None: closed with Esc or the title bar.)
            next(button for button in box.buttons() if button.text() == choice).click()
        return 0
    monkeypatch.setattr(QMessageBox, "exec", run)
    assert main_window._ask_delete_old_traces(earlier, str(tmp_path)) is (choice == "Delete old traces")
    text, default, buttons = seen[0]
    assert text == f"2 earlier I/O traces ({byte_size(3000)}) in {tmp_path}."
    assert default == "Keep" and sorted(buttons) == ["Delete old traces", "Keep"]
