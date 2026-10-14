"""Resize regressions observe paint delivery, not just updatesEnabled()."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtCore import QEvent, QObject, QTimer, Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QLabel, QMainWindow
from pytestqt.qtbot import QtBot

from helab.resources.icons import IconsInitUtil
from helab.utils.io_service import IORequest, IOService
from helab.views.FolderExplorer import FolderExplorer
from helab.views.FolderTabWidget import FolderTabWidget
from helab.views.HelabMainWindow import HelabMainWindow


class ResizeWindow(HelabMainWindow):
    """Real resize and scan controls, without application startup/shutdown."""

    def __init__(self) -> None:
        QMainWindow.__init__(self)
        self._closing = False
        self._setup_left_toolbar()
        self.tab_widget = FolderTabWidget(self)
        self.setCentralWidget(self.tab_widget)

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        QMainWindow.closeEvent(self, a0)


class PaintCounter(QObject):
    def __init__(self, widget: QObject) -> None:
        super().__init__(widget)
        self.count = 0
        widget.installEventFilter(self)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a1 is not None and a1.type() == QEvent.Type.Paint:
            self.count += 1
        return False


def resize_window(window: QMainWindow, qtbot: QtBot, repeated: bool) -> None:
    for width in ((740, 780, 820) if repeated else (740,)):
        window.resize(width, 520)
        qtbot.wait(10)
    # Wait past the old handler's 100 ms restore, then require *new* painting.
    # A successful restore callback or a single repaint would miss the freeze.
    qtbot.wait(250)


@pytest.mark.parametrize("repeated", [False, True], ids=["single", "repeated"])
def test_label_keeps_painting_after_resize(qtbot: QtBot, repeated: bool) -> None:
    IconsInitUtil.initialise_icons()
    window = ResizeWindow()
    qtbot.addWidget(window)
    label = QLabel("Tick 000000", window)
    window.setCentralWidget(label)
    paints = PaintCounter(label)
    tick = 0

    def update_label() -> None:
        nonlocal tick
        tick += 1
        label.setText(f"Tick {tick:06d}")

    timer = QTimer(window)
    timer.timeout.connect(update_label)
    timer.start(30)
    try:
        window.resize(700, 500)
        window.show()
        qtbot.waitUntil(lambda: paints.count > 0)
        resize_window(window, qtbot, repeated)
        painted, previous_tick = paints.count, tick
        qtbot.waitUntil(lambda: paints.count > painted, timeout=2000)
        assert tick > previous_tick
        painted = paints.count
        qtbot.waitUntil(lambda: paints.count > painted, timeout=2000)
    finally:
        timer.stop()


@pytest.mark.parametrize("repeated", [False, True], ids=["single", "repeated"])
def test_recursive_scan_keeps_painting_and_can_be_cancelled_after_resize(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, repeated: bool,
) -> None:
    IconsInitUtil.initialise_icons()
    service = IOService()
    service.timer.stop()
    # Hold helpers so scan work cannot finish before painting and Cancel are checked.
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    root = str(tmp_path)
    explorer = FolderExplorer(root, root, root, [0, 4, 5])
    explorer.auto_load_ram = False
    explorer.auto_scan_visible = False
    monkeypatch.setattr(explorer.model, "request_folder_icons", lambda paths: True)
    window = ResizeWindow()
    qtbot.addWidget(window)
    window.tab_widget.addTab(explorer, "Scan")
    viewport = explorer.tree.viewport()
    assert viewport is not None
    paints = PaintCounter(viewport)

    def request_for(operation: str, path: str) -> IORequest:
        job = explorer.model.cache.jobs[(operation, path)]
        return next(request for request in service.pending if request.owner == job.owner)

    children = [str(tmp_path / f"run_{index:03}") for index in range(100)]

    def complete_root(operation: str) -> None:
        request = request_for(operation, root)
        events: list[dict[str, Any]] = [
            {"kind": "entries", "entries": [{"path": path, "modified": None} for path in children]},
            {"kind": "status", "status": "nothing", "count": 0, "raw": [], "txy": [],
             "has_dirs": True, "signature": "root", "details": True},
            {"kind": "done"},
        ]
        with qtbot.waitSignal(explorer.model.directoryLoaded, timeout=2000):
            for event in events:
                service.resultReady.emit(request, event)
        service.pending.remove(request)

    beats = 0

    def heartbeat() -> None:
        nonlocal beats
        beats += 1

    timer = QTimer(window)
    timer.timeout.connect(heartbeat)
    timer.start(20)
    try:
        window.resize(700, 500)
        window.show()
        qtbot.waitUntil(lambda: ("list", root) in explorer.model.cache.jobs)
        complete_root("list")
        window._check_folder_status("recursive", 32768)
        explorer._dispatch_deep()
        complete_root("scan")
        explorer._dispatch_deep()
        path = next(iter(explorer._deep_depth))
        request = request_for("scan", path)
        service.pending.remove(request)
        service.active.append(request)
        service.resultReady.emit(request, {"kind": "started"})
        assert explorer._basic_completed == 1 and explorer._basic_active

        resize_window(window, qtbot, repeated)
        painted, previous_beats = paints.count, beats
        qtbot.waitUntil(lambda: paints.count > painted and beats > previous_beats, timeout=2000)
        painted = paints.count
        qtbot.waitUntil(lambda: paints.count > painted, timeout=2000)
        assert explorer._basic_active and request in service.active
        assert explorer._basic_completed == 1  # Paint delivery did not depend on finishing the scan.
        qtbot.mouseClick(window.folder_status_button, Qt.MouseButton.LeftButton)  # type: ignore[no-untyped-call]
        assert not explorer._basic_active
        assert request.cancelled.is_set()
        assert not explorer._deep and not explorer._deep_depth
        assert not any(r.operation == "scan" for r in service.pending)
        assert window.action_tab_rescan.text() == "Check folder status"
    finally:
        timer.stop()
        explorer.close_cleanup()
        service.shutdown()
