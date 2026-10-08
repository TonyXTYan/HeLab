from __future__ import annotations

import os
from pathlib import Path
import time
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtCore import QSettings, QTimer, Qt
from PyQt6.QtGui import QAction, QCloseEvent
from PyQt6.QtWidgets import QDialog, QMainWindow, QPushButton, QTabWidget, QToolButton

from helab.resources.icons import IconsInitUtil
from helab.utils.constants import DEFAULT_LOAD_MODE, LOAD_MODE_LABELS, LOAD_MODE_SETTING, read_load_mode
from helab.utils.constants import AUTO_SCAN_VISIBLE_SETTING, SIMULTANEOUS_IO_SETTING
from helab.utils.folder_cache import FolderCache, get_folder_cache
from helab.utils.io_service import IORequest, IOService
from helab.views.FolderExplorer import FolderExplorer
from helab.views.FolderTabWidget import FolderTabWidget
from helab.views.HelabMainWindow import HelabMainWindow
from helab.views.SettingsDialog import SettingsDialog


def service_for_test(monkeypatch: pytest.MonkeyPatch) -> IOService:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    return service


def explorer_for_test(qtbot: QtBot, path: str) -> FolderExplorer:
    explorer = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(explorer)
    explorer.selectionPathChanged.connect(lambda p: explorer.load_to_ram_cache(p))
    return explorer


def producer(cache: FolderCache, operation: str, path: str) -> IORequest:
    job = cache.jobs[(operation, path)]
    return next(r for r in (*cache.service.pending, *cache.service.active) if r.owner == job.owner)


def retire(cache: FolderCache, request: IORequest) -> None:
    for requests in (cache.service.pending, cache.service.active):
        if request in requests:
            requests.remove(request)


def scan_folder(cache: FolderCache, path: str, children: list[str] | None = None, data: bool = True) -> None:
    request = producer(cache, "list" if ("list", path) in cache.jobs else "scan", path)
    cache.service.resultReady.emit(request, {"kind": "entries", "entries": [
        {"path": p, "modified": None} for p in (children or [])]})
    # A complete status, as a details scan or load supplies it: no step 2 follows.
    cache.service.resultReady.emit(request, {"kind": "status", "status": "ok", "count": 1, "raw": [1], "details": True,
                                           "txy": [1] if data else [], "modified": 0, "signature": "v1"})
    cache.service.resultReady.emit(request, {"kind": "done"})
    retire(cache, request)


def start_load(cache: FolderCache, path: str) -> IORequest:
    request = producer(cache, "load", path)
    cache.service.pending.remove(request)
    cache.service.active.append(request)
    cache.service.resultReady.emit(request, {"kind": "started"})
    return request


def send_shot(cache: FolderCache, path: str, shot: int) -> None:
    cache.service.resultReady.emit(producer(cache, "load", path), {
        "kind": "shot", "shot": shot, "array": np.array([[shot, 2, 3]], dtype=np.float64)})


def complete_load(cache: FolderCache, path: str) -> None:
    request = producer(cache, "load", path)
    send_shot(cache, path, 1)
    cache.service.resultReady.emit(request, {"kind": "loaded", "signature": "v1", "bytes": 24,
                                           "rows": 1, "files": 1, "problematic": []})
    cache.service.resultReady.emit(request, {"kind": "done"})
    retire(cache, request)


def make_explorer(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                  mode: str) -> tuple[IOService, FolderCache, FolderExplorer, list[str]]:
    service = service_for_test(monkeypatch)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    cache = get_folder_cache(service)
    root = str(tmp_path)
    explorer = explorer_for_test(qtbot, root)
    explorer.load_mode = mode
    qtbot.waitUntil(lambda: ("list", root) in cache.jobs)
    paths = [os.path.join(root, name) for name in "abcde"]
    # The root holds no data, so opening it does not start a load.
    scan_folder(cache, root, paths, data=False)
    qtbot.waitUntil(lambda: all(p in explorer.model.nodes for p in paths))
    for path in paths:
        explorer.model.request_scan(path)
        scan_folder(cache, path)
    qtbot.waitUntil(lambda: all(explorer.model.nodes[p].report for p in paths))
    return service, cache, explorer, paths


def select(explorer: FolderExplorer, path: str) -> None:
    explorer.tree.setCurrentIndex(explorer.model.path_index(path))


def finish(explorer: FolderExplorer, service: IOService) -> None:
    explorer.close_cleanup()
    service.shutdown()


def test_cancel_mode_cancels_previous_load(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache, explorer, (a, b, *_) = make_explorer(qtbot, monkeypatch, tmp_path, "cancel")
    select(explorer, a)
    start_load(cache, a)
    assert explorer.model.load_states[a] == "loading"
    select(explorer, b)
    assert ("load", a) not in cache.jobs and a not in explorer.model.load_states
    assert explorer._load_path == b and ("load", b) in cache.jobs
    finish(explorer, service)


def test_finish_mode_keeps_started_load_but_drops_unstarted_one(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache, explorer, (a, b, c, *_) = make_explorer(qtbot, monkeypatch, tmp_path, "finish")
    select(explorer, a)
    start_load(cache, a)
    select(explorer, b)
    assert list(explorer._bg_paths) == [a]
    assert list(cache.jobs[("load", a)].subscribers) == [(explorer.bg_owner, 0)]
    assert explorer.model.load_states[a] == "loading"
    assert explorer._load_path == b and explorer.model.load_states[b] == "queued"
    # B never started, so moving on cancels it.
    select(explorer, c)
    assert ("load", b) not in cache.jobs and b not in explorer.model.load_states
    complete_load(cache, a)
    assert not explorer._bg_paths and a not in explorer.model.load_states
    assert cache.current_dataset(a) is not None
    # A background result never replaces what the tab shows.
    assert explorer.folder_opened_path is None and explorer._load_path == c
    finish(explorer, service)


def test_queue_mode_loads_immediately_when_idle_and_waits_when_busy(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(FolderExplorer, "DWELL_MS", 200)
    service, cache, explorer, (a, b, c, d, _) = make_explorer(qtbot, monkeypatch, tmp_path, "queue")
    select(explorer, a)
    assert ("load", a) in cache.jobs and not explorer.load_waiting
    start_load(cache, a)
    explorer.queue_load(d)
    select(explorer, b)
    assert explorer.load_waiting and ("load", b) not in cache.jobs
    assert "Waiting" in explorer.folder_summary_label.text()
    # Browsing past B leaves nothing queued for it.
    select(explorer, c)
    assert ("load", b) not in cache.jobs
    qtbot.waitUntil(lambda: ("load", c) in cache.jobs, timeout=2000)
    assert ("load", b) not in cache.jobs and not explorer.load_waiting
    # The selected folder runs before the earlier queued one.
    assert service.queued_load_paths() == [c, d]
    assert explorer._load_path == c and list(explorer._bg_paths) == [d, a]
    finish(explorer, service)


def test_reselecting_background_folder_adopts_its_load_and_shots(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(FolderExplorer, "DWELL_MS", 60_000)
    service, cache, explorer, (a, b, *_) = make_explorer(qtbot, monkeypatch, tmp_path, "queue")
    select(explorer, a)
    start_load(cache, a)
    job = cache.jobs[("load", a)]
    send_shot(cache, a, 7)
    select(explorer, b)
    assert explorer.load_waiting and list(explorer._bg_paths) == [a]
    select(explorer, a)
    assert cache.jobs[("load", a)] is job and not explorer._bg_paths
    assert list(job.subscribers) == [(explorer.model.owner, explorer.model.generation)]
    assert explorer.loading and not explorer.load_queued and not explorer.load_waiting
    complete_load(cache, a)
    assert explorer.folder_opened_path == a
    assert explorer.folder_opened_data is not None and sorted(explorer.folder_opened_data) == [1, 7]
    finish(explorer, service)


def test_context_menu_load_queues_without_cancelling(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache, explorer, (a, b, c, d, _) = make_explorer(qtbot, monkeypatch, tmp_path, "cancel")
    assert explorer.queue_load(d)
    assert ("load", d) in cache.jobs and explorer.model.load_states[d] == "queued"
    select(explorer, a)
    start_load(cache, a)
    assert explorer.queue_load(b) and explorer.queue_load(c)
    assert service.queued_load_paths() == [d, b, c]
    assert explorer._load_path == a and ("load", a) in cache.jobs
    # The selected folder is loaded for display, not in the background.
    assert explorer.queue_load(a) and a not in explorer._bg_paths
    finish(explorer, service)


def test_background_queue_is_capped_and_cancel_clears_it(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(FolderExplorer, "MAX_BACKGROUND_LOADS", 2)
    monkeypatch.setattr(FolderExplorer, "DWELL_MS", 60_000)
    service, cache, explorer, (a, b, c, d, e) = make_explorer(qtbot, monkeypatch, tmp_path, "queue")
    select(explorer, a)
    start_load(cache, a)
    for path in (b, c, d):
        explorer.queue_load(path)
    assert list(explorer._bg_paths) == [c, d] and ("load", b) not in cache.jobs
    select(explorer, e)
    assert explorer.load_waiting and list(explorer._bg_paths) == [c, d, a]
    explorer.cancel_loading()
    assert not explorer._bg_paths and not explorer.load_waiting
    assert not explorer.model.load_states
    assert not any(operation == "load" for operation, _ in cache.jobs)
    finish(explorer, service)


def test_cancel_loading_preserves_scans_shared_load_and_explicit_retry(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache, first, (a, b, c, *_) = make_explorer(qtbot, monkeypatch, tmp_path, "cancel")
    select(first, a)
    request = start_load(cache, a)
    second = explorer_for_test(qtbot, a)
    second.load_mode = "cancel"
    qtbot.waitUntil(lambda: len(cache.jobs[("load", a)].subscribers) == 2)
    assert first.queue_load(b) and first.queue_load(c)
    first.model.request_scan(a, force=True)
    scan_request = producer(cache, "list", a)

    first.cancel_loading()

    assert not first.can_cancel_loading and first._load_path is None
    assert not first.model.load_states and not first._bg_paths
    assert not scan_request.cancelled.is_set() and scan_request in service.pending
    assert not request.cancelled.is_set() and request in service.active
    assert list(cache.jobs[("load", a)].subscribers) == [(second.model.owner, second.model.generation)]
    assert ("load", b) not in cache.jobs and ("load", c) not in cache.jobs
    # Scan completion and another tab's completed dataset must not undo Cancel.
    scan_folder(cache, a)
    complete_load(cache, a)
    qtbot.wait(50)
    assert not first.can_cancel_loading and first.folder_opened_data is None
    assert second.folder_opened_path == a and second.folder_opened_data is not None
    first._retry()
    qtbot.waitUntil(lambda: first.folder_opened_path == a)
    assert first.folder_opened_data is not None
    second.close_cleanup()
    finish(first, service)


def test_cancel_loading_keeps_previous_dataset_and_allows_new_selection(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache, explorer, (a, b, c, *_) = make_explorer(qtbot, monkeypatch, tmp_path, "cancel")
    select(explorer, a)
    start_load(cache, a)
    complete_load(cache, a)
    data = explorer.folder_opened_data
    select(explorer, b)
    request = start_load(cache, b)
    explorer.cancel_loading()
    assert request.cancelled.is_set() and request not in service.active
    assert explorer.folder_opened_data is data and explorer.folder_opened_path == a
    assert not explorer.can_cancel_loading
    assert not explorer.load_to_ram_cache(b)
    select(explorer, c)
    assert explorer.loading and explorer._load_path == c
    finish(explorer, service)


class CancelTestWindow(HelabMainWindow):
    """Use the real toolbar/menu setup without application startup or shutdown."""

    def __init__(self) -> None:
        QMainWindow.__init__(self)
        self._closing = False
        self._setup_left_toolbar()
        self.tab_widget = FolderTabWidget(self)
        self.setCentralWidget(self.tab_widget)
        menu_bar = self.menuBar()
        assert menu_bar is not None
        self.menu_bar = menu_bar
        self.menu_bar.setNativeMenuBar(False)
        self.create_menus()
        self.tab_widget.currentChanged.connect(self._update_cancel_loading_action)

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        QMainWindow.closeEvent(self, a0)


def test_folder_status_toolbar_keeps_scope_cancel_and_up_out_of_path_row(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    IconsInitUtil.initialise_icons()
    service, cache, first, (a, *_) = make_explorer(qtbot, monkeypatch, tmp_path, "finish")
    first.deep_timer.stop()
    first.auto_load_ram = False
    window = CancelTestWindow()
    qtbot.addWidget(window)
    window.tab_widget.addTab(first, "First")
    second = explorer_for_test(qtbot, a)
    second.deep_timer.stop()
    second.auto_load_ram = False
    window.tab_widget.addTab(second, "Second")
    first_layout = first.layout()
    assert first_layout is not None
    path_row = first_layout.itemAt(0)
    assert path_row is not None and path_row.widget() is first.path_edit
    button = window.folder_status_button
    scope_button = window.folder_status_scope_button
    assert isinstance(button, QToolButton)
    assert button.menu() is None
    assert button.autoRaise() and scope_button.autoRaise()
    assert scope_button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
    assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    menu = scope_button.menu()
    assert menu is not None
    assert [action.text() for action in menu.actions()] == [
        "Folders in view", "Current folder", "Recursive depth…", "All subfolders"]
    window.show()
    qtbot.waitUntil(button.isVisible)
    up_button = window.sidebar_toolbar_left.widgetForAction(window.action_tab_folder_up)
    assert up_button is not None
    assert button.width() <= up_button.width()
    assert scope_button.width() == button.width()
    assert scope_button.geometry().top() > button.geometry().bottom()
    assert scope_button.geometry().center().x() == button.geometry().center().x()
    assert len(button.toolTip().splitlines()) == 4
    opened: list[bool] = []
    menu.aboutToShow.connect(lambda: opened.append(True))
    QTimer.singleShot(0, menu.close)
    qtbot.mouseClick(scope_button, Qt.MouseButton.LeftButton)  # type: ignore[no-untyped-call]
    assert opened and not first._basic_active

    def click_primary() -> None:
        menu_opens = len(opened)
        # Close an unexpected popup so a regression fails instead of hanging.
        QTimer.singleShot(0, menu.close)
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton,  # type: ignore[no-untyped-call]
                         pos=button.rect().center())
        assert len(opened) == menu_opens

    select(first, a)
    menu.actions()[1].trigger()
    assert first._basic_roots == {a} and first._basic_active
    assert window.action_tab_rescan.text() == "Cancel check"
    first._dispatch_deep()
    cache.submit("other-tab", 0, a, "scan", {}, force=True)
    window.tab_widget.setCurrentWidget(second)
    assert window.action_tab_rescan.text() == "Check folder status"
    window.tab_widget.setCurrentWidget(first)
    assert window.action_tab_rescan.text() == "Cancel check"
    click_primary()
    assert not first._basic_active and cache.has_request("other-tab", "scan", a)
    assert window.action_tab_rescan.text() == "Check folder status"
    cache.cancel("other-tab")
    # The primary icon still checks folders in view, and toggles to cancellation.
    click_primary()
    assert first._basic_active and str(tmp_path) in first._basic_roots
    click_primary()
    assert not first._basic_active
    window.action_tab_folder_up.triggered.connect(window.on_back_button_clicked)
    first.open_to_path(a)
    window.update_tool_enabled_state()
    assert window.action_tab_folder_up.isEnabled()
    window.action_tab_folder_up.trigger()
    assert first.view_path == str(tmp_path)
    window.action_tab_rescan.setEnabled(False)
    assert not button.isEnabled() and not scope_button.isEnabled()
    second.close_cleanup()
    finish(first, service)


def test_folder_io_menu_and_settings_apply_to_existing_and_new_tabs(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue(SIMULTANEOUS_IO_SETTING, 2)
    monkeypatch.setattr("helab.views.HelabMainWindow.QSettings", lambda *args: settings)
    service = service_for_test(monkeypatch)
    monkeypatch.setattr("helab.views.HelabMainWindow.get_io_service", lambda: service)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    window = CancelTestWindow()
    qtbot.addWidget(window)
    first = explorer_for_test(qtbot, str(tmp_path))
    second = explorer_for_test(qtbot, str(tmp_path))
    window.tab_widget.addTab(first, "First")
    window.tab_widget.addTab(second, "Second")
    assert service.max_operations == 2
    action = window.view_toggle_auto_scan_visible
    assert not action.isChecked() and not first.auto_scan_visible and not second.auto_scan_visible
    action.trigger()
    assert first.auto_scan_visible and second.auto_scan_visible
    assert settings.value(AUTO_SCAN_VISIBLE_SETTING, type=bool)

    # Exercise the real Save dialog and main-window application after it closes.
    def save_dialog() -> None:
        dialog = window.settings_dialog
        dialog.simultaneous_io_spin.setValue(4)
        dialog.auto_scan_visible_checkbox.setChecked(False)
        dialog.save_button.click()

    monkeypatch.setattr("helab.views.HelabMainWindow.SettingsDialog",
                        lambda parent: SettingsDialog(parent, settings=settings))
    QTimer.singleShot(0, save_dialog)
    window.show_settings_dialog()
    assert service.max_operations == 4
    assert not action.isChecked() and not first.auto_scan_visible and not second.auto_scan_visible
    action.trigger()
    window.add_new_folder_explorer_tab(target_path=str(tmp_path))
    third = window.tab_widget.currentWidget()
    assert isinstance(third, FolderExplorer) and third.auto_scan_visible
    action.trigger()
    assert not first.auto_scan_visible and not second.auto_scan_visible and not third.auto_scan_visible
    for explorer in (first, second, third):
        explorer.close_cleanup()
    service.shutdown()


@pytest.mark.parametrize("control", ["toolbar", "menu", "shortcut"])
def test_cancel_controls_target_current_tab_only(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, control: str,
) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("helab.views.HelabMainWindow.QSettings", lambda *args: settings)
    service, cache, first, (a, b, *_) = make_explorer(qtbot, monkeypatch, tmp_path, "cancel")
    monkeypatch.setattr("helab.views.HelabMainWindow.get_io_service", lambda: service)
    second = explorer_for_test(qtbot, b)
    second.load_mode = "cancel"
    qtbot.waitUntil(lambda: second.loading)
    select(first, a)
    start_load(cache, a)
    window = CancelTestWindow()
    qtbot.addWidget(window)
    window.tab_widget.addTab(first, "First")
    window.tab_widget.addTab(second, "Second")
    for explorer in (first, second):
        explorer.loadStateChanged.connect(window._update_cancel_loading_action)
    window.show()
    window.activateWindow()
    first.path_edit.setFocus()
    qtbot.waitUntil(window.isActiveWindow)
    action = window.action_tab_cancel
    assert action.isEnabled()
    assert all(button.text() != "Cancel" for button in first.findChildren(QPushButton))
    file_menu = window.menu_bar.actions()[0].menu()
    assert file_menu is not None and action in file_menu.actions()
    if control == "toolbar":
        button = window.sidebar_toolbar_left.widgetForAction(action)
        assert button is not None
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)  # type: ignore[no-untyped-call]
    elif control == "menu":
        next(item for item in file_menu.actions() if item.text() == "Cancel Loading").trigger()
    else:
        window.sidebar_toolbar_left.hide()
        qtbot.keyClick(first.path_edit, Qt.Key.Key_Escape)  # type: ignore[no-untyped-call]
    qtbot.waitUntil(lambda: not first.can_cancel_loading)
    assert not action.isEnabled() and second.loading
    assert ("load", a) not in cache.jobs and ("load", b) in cache.jobs
    window.tab_widget.setCurrentIndex(1)
    assert action.isEnabled()
    second.cancel_loading()
    assert not action.isEnabled()
    first.close_cleanup()
    second.close_cleanup()
    service.shutdown()


def test_escape_closes_dialog_without_cancelling_load(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("helab.views.HelabMainWindow.QSettings", lambda *args: settings)
    service, cache, explorer, (a, *_) = make_explorer(qtbot, monkeypatch, tmp_path, "cancel")
    monkeypatch.setattr("helab.views.HelabMainWindow.get_io_service", lambda: service)
    select(explorer, a)
    window = CancelTestWindow()
    qtbot.addWidget(window)
    window.tab_widget.addTab(explorer, "Tab")
    window.show()
    dialog = QDialog(window)
    qtbot.addWidget(dialog)
    dialog.setModal(True)
    dialog.show()
    dialog.activateWindow()
    qtbot.waitUntil(dialog.isActiveWindow)
    qtbot.keyClick(dialog, Qt.Key.Key_Escape)  # type: ignore[no-untyped-call]
    assert not dialog.isVisible()
    assert explorer.loading and ("load", a) in cache.jobs
    finish(explorer, service)


def test_revalidation_scan_is_prioritised_and_runs_once(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = service_for_test(monkeypatch)
    cache = get_folder_cache(service)
    path, other = str(tmp_path / "selected"), str(tmp_path / "other")
    cache.submit("tab", 0, path, "scan")
    scan_folder(cache, path)
    qtbot.waitUntil(lambda: not cache.requests("tab"))
    cache.snapshots[path].checked_at -= 60
    cache.submit("browser", 0, other, "scan")
    cache.submit("tab", 0, path, "scan", priority=True)
    qtbot.waitUntil(lambda: ("scan", path) in cache.jobs)
    assert service.pending[0] is producer(cache, "scan", path)
    scan_folder(cache, path)
    qtbot.wait(50)
    assert ("scan", path) not in cache.jobs
    service.shutdown()


def test_finishing_load_retains_shared_slot_until_cache_writer_exits(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_run", lambda request: None)
    service.submit("tab", 0, "/first", "load")
    first = service.active[0]
    assert service.load_busy()
    service.messages.put((first, {"kind": "loaded"}))
    service._tick()
    assert not service.load_busy()
    first.last_activity = time.monotonic() - 20
    service.submit("tab", 0, "/second", "load")
    service.submit("browser", 0, "/browse", "scan")
    service._tick()
    assert [r.path for r in service.active] == ["/first"]
    assert service.queued_operations() == [("load", "/second"), ("scan", "/browse")]
    assert first.timeout == service.FINISH_TIMEOUT and not first.cancelled.is_set()
    service.messages.put((first, {"kind": "cache_saved"}))
    service._tick()
    assert service.active == [first]
    service.messages.put((first, {"kind": "exit"}))
    service._tick()
    assert [r.path for r in service.active] == ["/second"]
    service.shutdown()


def test_promote_moves_owner_requests_to_front(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    service = service_for_test(monkeypatch)
    for owner, path in (("a", "/a"), ("b", "/b"), ("c", "/c")):
        service.submit(owner, 0, path, "load")
    service.promote("c")
    assert service.queued_load_paths() == ["/c", "/a", "/b"]
    service.shutdown()


def test_load_mode_setting_and_menu_apply_to_tabs(qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    assert read_load_mode(settings) == DEFAULT_LOAD_MODE
    settings.setValue(LOAD_MODE_SETTING, "unknown")
    assert read_load_mode(settings) == DEFAULT_LOAD_MODE
    settings.setValue(LOAD_MODE_SETTING, "queue")
    assert read_load_mode(settings) == "queue"
    service = service_for_test(monkeypatch)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    explorer = explorer_for_test(qtbot, str(tmp_path))
    tabs = QTabWidget()
    qtbot.addWidget(tabs)
    tabs.addTab(explorer, "Tab")
    actions: dict[str, QAction] = {}
    for mode in LOAD_MODE_LABELS:
        actions[mode] = QAction(mode, tabs)
        actions[mode].setCheckable(True)
    window: Any = SimpleNamespace(load_mode_actions=actions, tab_widget=tabs)
    HelabMainWindow.apply_load_mode(window, "queue")
    assert explorer.load_mode == "queue" and actions["queue"].isChecked()
    HelabMainWindow.apply_load_mode(window, "unknown")
    assert explorer.load_mode == DEFAULT_LOAD_MODE
    finish(explorer, service)


def test_paused_selected_load_is_shown_in_summary_and_row(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache, explorer, (a, *_) = make_explorer(qtbot, monkeypatch, tmp_path, "finish")
    assert explorer.is_foreground
    select(explorer, a)
    request = start_load(cache, a)
    service.resultReady.emit(request, {"kind": "progress", "progress": 456 / 1234, "loaded_files": 456,
                                       "total_files": 1234})
    service.resultReady.emit(request, {"kind": "paused"})
    explorer._update_activity()
    assert explorer.loading_message == "456 of 1234 files checked (37%) · 456 loaded · Paused"
    assert "1,234 TXY found · 456 of 1234 files checked (37%) · 456 loaded · Paused" in explorer.folder_summary_label.text()
    index = explorer.model.path_index(a)
    assert explorer.model.data(index, explorer.model.LOAD_QUEUED_ROLE)
    service.resultReady.emit(request, {"kind": "resumed"})
    explorer._update_activity()
    assert "Paused" not in explorer.folder_summary_label.text()
    assert explorer.model.load_states[a] == "loading"
    finish(explorer, service)
    assert not cache.foreground_owners


def test_queue_mode_keeps_queued_loads_in_the_foreground(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache, explorer, _ = make_explorer(qtbot, monkeypatch, tmp_path, "finish")
    assert cache.foreground_owners == {explorer.model.owner}
    explorer.load_mode = "queue"
    assert cache.foreground_owners == {explorer.model.owner, explorer.bg_owner}
    other = FolderExplorer(str(tmp_path), str(tmp_path), str(tmp_path), [0])
    qtbot.addWidget(other)
    assert not other.is_foreground  # The first tab keeps it until another becomes current.
    other.claim_foreground()
    assert other.is_foreground and not explorer.is_foreground
    explorer.load_mode = "finish"
    assert cache.foreground_owners == {other.model.owner}
    other.close_cleanup()
    finish(explorer, service)
