from __future__ import annotations

import os
from pathlib import Path
import time
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QTabWidget

from helab.utils.constants import DEFAULT_LOAD_MODE, LOAD_MODE_LABELS, LOAD_MODE_SETTING, read_load_mode
from helab.utils.folder_cache import FolderCache, get_folder_cache
from helab.utils.io_service import IORequest, IOService
from helab.views.FolderExplorer import FolderExplorer
from helab.views.HelabMainWindow import HelabMainWindow


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
    request = producer(cache, "scan", path)
    cache.service.resultReady.emit(request, {"kind": "entries", "entries": [
        {"path": p, "modified": None} for p in (children or [])]})
    cache.service.resultReady.emit(request, {"kind": "status", "status": "ok", "count": 1, "raw": [1],
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
    qtbot.waitUntil(lambda: ("scan", root) in cache.jobs)
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
    assert "Waiting" in explorer.scan_label.text()
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
    explorer.on_stop_button_clicked()
    assert not explorer._bg_paths and not explorer.load_waiting
    assert not explorer.model.load_states
    assert not any(operation == "load" for operation, _ in cache.jobs)
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


def test_finishing_load_keeps_writing_and_does_not_block_next_load(
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
    assert [r.path for r in service.active] == ["/first", "/second", "/browse"]
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
