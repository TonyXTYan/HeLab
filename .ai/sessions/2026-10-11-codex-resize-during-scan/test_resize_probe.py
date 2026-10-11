from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import pytest
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
for name in ('HELAB_DIR_CACHES_OVERRIDE', 'HELAB_DIR_TEMPS_OVERRIDE', 'HELAB_APP_DIR_OVERRIDE'):
    os.environ[name] = tempfile.mkdtemp(prefix='helab_resize_probe_')
os.environ['HELAB_SETTLE_SECONDS'] = '0'
from PyQt6.QtCore import QEvent, QObject, QTimer
from PyQt6.QtGui import QCloseEvent, QResizeEvent
from PyQt6.QtWidgets import QLabel, QMainWindow
from pytestqt.qtbot import QtBot

from helab.resources.icons import IconsInitUtil
from helab.utils.io_service import IOService
from helab.views.FolderExplorer import FolderExplorer
from helab.views.HelabMainWindow import HelabMainWindow


class ProbeWindow(HelabMainWindow):
    def __init__(self, native_handler: bool) -> None:
        QMainWindow.__init__(self)
        self.native_handler = native_handler
        self.resizes: list[float] = []
        self.restores: list[float] = []

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        self.resizes.append(time.monotonic())
        if self.native_handler:
            QMainWindow.resizeEvent(self, event)
        else:
            # Freeze the original handler so this historical comparison survives its removal.
            self.setUpdatesEnabled(False)
            QMainWindow.resizeEvent(self, event)
            QTimer.singleShot(100, self._reenable_updates_after_resize)

    def _reenable_updates_after_resize(self) -> None:
        self.restores.append(time.monotonic())
        self.setUpdatesEnabled(True)

    def closeEvent(self, event: QCloseEvent | None) -> None:
        QMainWindow.closeEvent(self, event)


class PaintProbe(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.paints: list[float] = []

    def eventFilter(self, obj: QObject | None, event: QEvent | None) -> bool:
        if event and event.type() == QEvent.Type.Paint:
            self.paints.append(time.monotonic())
        return False


@pytest.mark.parametrize('native_handler', [False, True])
def test_real_recursive_scan_resize(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
                                    tmp_path: Path, native_handler: bool) -> None:
    IconsInitUtil.initialise_icons()
    service = IOService()
    monkeypatch.setattr('helab.models.SnapshotFileSystemModel.get_io_service', lambda: service)
    root = tmp_path / 'source'
    root.mkdir()
    for i in range(100):
        child = root / f'run_{i:03}'
        child.mkdir()
        (child / 'd_txy_forc1.txt').write_text('1,2,3\n')
    browser = FolderExplorer(str(root), str(root), str(root), [0, 4, 5])
    browser.auto_load_ram = False
    browser.auto_scan_visible = False
    browser.icon_timer.stop()
    monkeypatch.setattr(browser, '_load_visible_icons', lambda: None)
    monkeypatch.setattr(browser.model, 'request_folder_icons', lambda paths: True)
    window = ProbeWindow(native_handler)
    qtbot.addWidget(window)
    window.setCentralWidget(browser)
    window.resize(700, 500)
    probe = PaintProbe()
    browser.tree.viewport().installEventFilter(probe)
    window.show()
    qtbot.waitUntil(lambda: bool(browser.model.nodes.get(str(root)) and browser.model.nodes[str(root)].loaded), timeout=10000)
    qtbot.wait(200)
    browser.start_basic_scan('recursive', 32768)
    start = time.monotonic()
    beats: list[tuple[float, bool, bool, int, int]] = []
    timer = QTimer(window)
    timer.timeout.connect(lambda: beats.append((time.monotonic(), window.updatesEnabled(),
        browser.tree.viewport().updatesEnabled(), browser._basic_completed, len(probe.paints))))
    timer.start(20)
    resize_timers = []
    for offset in (100, 160, 220, 600, 900, 1200, 1600):
        resize_timer = QTimer(window)
        resize_timer.setSingleShot(True)
        resize_timer.timeout.connect(lambda o=offset: window.resize(700 + o // 20, 500 + o // 40))
        resize_timer.start(offset)
        resize_timers.append(resize_timer)
    try:
        qtbot.waitUntil(lambda: not browser._basic_active, timeout=30000)
        timer.stop()
        gaps = [b[0] - a[0] for a, b in zip(beats, beats[1:])]
        disabled = [b for b in beats if not b[1] or not b[2]]
        output = {'native_handler': native_handler, 'duration': time.monotonic() - start,
            'completed': browser._basic_completed, 'max_heartbeat_gap': max(gaps, default=0),
            'resizes': len(window.resizes), 'restores': len(window.restores),
            'disabled_samples': len(disabled), 'samples': len(beats),
            'last_disabled_at': disabled[-1][0] - start if disabled else None,
            'paint_count': len(probe.paints), 'updates_at_end': window.updatesEnabled()}
        print(json.dumps(output))
        (tmp_path / 'probe.json').write_text(json.dumps({'summary': output, 'beats': beats,
            'resizes': window.resizes, 'restores': window.restores, 'paints': probe.paints}))
        assert browser._basic_completed == 101
    finally:
        timer.stop()
        for resize_timer in resize_timers:
            resize_timer.stop()
        browser.close_cleanup()
        service.shutdown()


@pytest.mark.parametrize('native_handler', [False, True])
@pytest.mark.parametrize('burst', [False, True])
def test_idle_resize(qtbot: QtBot, native_handler: bool, burst: bool) -> None:
    window = ProbeWindow(native_handler)
    qtbot.addWidget(window)
    label = QLabel('start', window)
    window.setCentralWidget(label)
    window.resize(700, 500)
    probe = PaintProbe()
    label.installEventFilter(probe)
    window.show()
    qtbot.wait(200)
    start = time.monotonic()
    timer = QTimer(window)
    timer.timeout.connect(lambda: label.setText(str(time.monotonic())))
    timer.start(20)
    resize_timers = []
    for offset in ((100, 160, 220, 600) if burst else (100,)):
        resize_timer = QTimer(window)
        resize_timer.setSingleShot(True)
        resize_timer.timeout.connect(lambda o=offset: window.resize(700 + o // 20, 500 + o // 40))
        resize_timer.start(offset)
        resize_timers.append(resize_timer)
    qtbot.wait(1200)
    timer.stop()
    print(json.dumps({'idle': True, 'native_handler': native_handler, 'burst': burst,
        'paints': len(probe.paints), 'paints_after_800ms': sum(t > start + .8 for t in probe.paints),
        'updates_enabled': window.updatesEnabled(), 'restores': len(window.restores)}))
