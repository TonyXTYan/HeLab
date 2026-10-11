"""Folder details' All I/O row: the folder of a single running load, a tooltip with each load's
tab, progress, file and time, and a click that shows the folder in its tab."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from helab.utils.folder_cache import get_folder_cache
from helab.utils.io_service import IORequest, IOService
from helab.views.FolderDetailsPanel import FolderDetailsPanel


def frozen(monkeypatch: pytest.MonkeyPatch) -> IOService:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    return service


def running(service: IOService, owner: str, path: str, operation: str = "load") -> IORequest:
    request = IORequest(owner, 0, path, operation, {}, 60)
    service.active.append(request)
    return request


def test_all_io_names_a_single_load_and_its_tooltip_says_more(monkeypatch: pytest.MonkeyPatch) -> None:
    service = frozen(monkeypatch)
    try:
        first = running(service, "job-1", "/Volumes/dld_output/2026/run_042")
        assert service.activity_summary() == "Loading run_042"
        service.request_note = lambda request: 'tab "Today" · 12 of 50 files (24%) · d_txy_forc13.txt · 0:42'
        assert ('Load data: /Volumes/dld_output/2026/run_042\n'
                '  tab "Today" · 12 of 50 files (24%) · d_txy_forc13.txt · 0:42') in service.queue_tooltip()
        running(service, "job-2", "/Volumes/dld_output/2026/run_043")
        assert service.activity_summary() == "Loading 2 datasets"
        first.paused = True  # A paused load isn't "loading".
        assert service.activity_summary().startswith("Loading run_043")
    finally:
        service.shutdown()


def test_a_running_loads_note_has_its_progress_and_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service = frozen(monkeypatch)
    cache = get_folder_cache(service)
    try:
        path = str(tmp_path / "run_042")
        cache.submit("tab-a", 0, path, "load", {})
        producer = next(r for r in service.pending if r.operation == "load")
        assert cache.load_note(producer) == (["tab-a"], "")
        service.resultReady.emit(producer, {"kind": "progress", "progress": 0.24, "checked_files": 12,
                                            "total_files": 50, "loaded_files": 12})
        service.resultReady.emit(producer, {"kind": "file_started", "filename": os.path.join(path, "d_txy_forc13.txt")})
        owners, note = cache.load_note(producer)
        assert owners == ["tab-a"] and note.startswith("12 of 50 files (24%) · d_txy_forc13.txt")
        service.resultReady.emit(producer, {"kind": "file_finished"})
        assert "d_txy_forc13" not in cache.load_note(producer)[1]
    finally:
        service.shutdown()


def test_clicking_all_io_asks_to_show_the_single_load(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    service = frozen(monkeypatch)
    panel = FolderDetailsPanel()
    qtbot.addWidget(panel)
    revealed: list[tuple[str, str]] = []
    panel.revealRequested.connect(lambda owner, path: revealed.append((owner, path)))

    def click(button: Qt.MouseButton = Qt.MouseButton.LeftButton) -> None:
        label = panel.values["io"]
        for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            QApplication.sendEvent(label, QMouseEvent(kind, QPointF(2, 2), QPointF(2, 2), button,
                                                     button, Qt.KeyboardModifier.NoModifier))
    try:
        running(service, "job-1", "/data/run_042")
        panel.show_explorer(None, service)
        assert panel.text("io") == "Loading run_042"
        assert panel.values["io"].toolTip().startswith("Click to show this folder in its tab.")
        for button in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            click(button)
        assert not revealed
        click()
        assert revealed == [("job-1", "/data/run_042")]
        running(service, "job-2", "/data/run_043")  # Two loads: nothing to pick.
        panel.show_explorer(None, service)
        click()
        assert len(revealed) == 1 and not panel.values["io"].toolTip().startswith("Click")
    finally:
        service.shutdown()


def test_the_main_window_names_the_loads_tab_and_shows_its_folder(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import time as clock
    from PyQt6.QtWidgets import QTabWidget
    from helab.views.FolderExplorer import FolderExplorer
    from helab.views.HelabMainWindow import HelabMainWindow
    service = frozen(monkeypatch)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    monkeypatch.setattr("helab.views.HelabMainWindow.get_io_service", lambda: service)
    cache = get_folder_cache(service)
    root = str(tmp_path)
    run = os.path.join(root, "run_042")
    other = FolderExplorer(root, root, root, [0, 4, 5])
    explorer = FolderExplorer(root, root, root, [0, 4, 5])
    tabs = QTabWidget()
    for widget in (tabs, other, explorer):
        qtbot.addWidget(widget)
    tabs.addTab(other, "Other")
    tabs.addTab(explorer, "Today")

    class Window:
        tab_widget = tabs
        _explorers = HelabMainWindow._explorers
        _load_tabs = HelabMainWindow._load_tabs
    window: Any = Window()  # Just what these methods use of the main window.
    try:
        # The root's listing (no data there), with run_042 in it.
        qtbot.waitUntil(lambda: ("list", root) in cache.jobs)
        listing = next(r for r in service.pending if r.operation == "list" and r.path == root)
        for event in ({"kind": "entries", "entries": [{"path": run, "modified": None}]},
                      {"kind": "status", "status": "nothing", "count": 0, "raw": [], "txy": [], "details": True,
                       "modified": 0, "signature": "v1", "scanned_at": clock.time()}, {"kind": "done"}):
            service.resultReady.emit(listing, event)
        service.pending.remove(listing)
        qtbot.waitUntil(lambda: run in explorer.model.nodes)
        explorer.queue_load(run)  # A background load in the "Today" tab.
        producer = next(r for r in service.pending if r.operation == "load")
        service.pending.remove(producer)
        service.active.append(producer)
        assert HelabMainWindow._request_note(window, producer) == 'tab "Today"'
        HelabMainWindow.reveal_load(window, producer.owner, run)
        assert tabs.currentWidget() is explorer and explorer.selected_path_globally == run
    finally:
        for widget in (other, explorer):
            widget.close_cleanup()
        service.shutdown()
