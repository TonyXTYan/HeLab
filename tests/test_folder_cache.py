from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import math
import os
import subprocess
import time
import sys
from typing import Any

import numpy as np
import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QTabWidget

from helab.models.SnapshotFileSystemModel import SnapshotFileSystemModel
from helab.utils.folder_cache import Dataset, FolderCache, get_folder_cache
from helab.utils.io_service import IORequest, IOService
from helab.views.FolderExplorer import FolderExplorer
from helab.views.HelabMainWindow import HelabMainWindow
from helab.io_helper import load, scan
from helab.resources.icons import IconsInitUtil, StatusIcons


def service_for_test(monkeypatch: pytest.MonkeyPatch) -> IOService:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    return service


def producer(cache: FolderCache, path: str, operation: str) -> IORequest:
    job = cache.jobs[(operation, path)]
    return next(r for r in cache.service.pending if r.owner == job.owner)


def finish_scan(cache: FolderCache, path: str, signature: str = "v1",
                children: list[str] | None = None) -> None:
    request = producer(cache, path, "list" if ("list", path) in cache.jobs else "scan")
    cache.service.resultReady.emit(request, {"kind": "entries", "entries": [
        {"path": p, "modified": None} for p in (children or [])]})
    # A complete status, as a details scan or load supplies it: no step 2 follows.
    cache.service.resultReady.emit(request, {"kind": "status", "status": "ok", "count": 1, "details": True,
                                           "raw": [1], "txy": [1], "modified": 0, "signature": signature})
    cache.service.resultReady.emit(request, {"kind": "done"})
    if request in cache.service.pending:
        cache.service.pending.remove(request)


def finish_load(cache: FolderCache, path: str, signature: str = "v1", value: float = 1) -> None:
    request = producer(cache, path, "load")
    cache.service.resultReady.emit(request, {"kind": "shot", "shot": 1,
                                           "array": np.array([[value, 2, 3]], dtype=np.float64)})
    cache.service.resultReady.emit(request, {"kind": "loaded", "signature": signature,
                                           "bytes": 24, "rows": 1, "files": 1, "problematic": []})
    cache.service.resultReady.emit(request, {"kind": "done"})
    if request in cache.service.pending:
        cache.service.pending.remove(request)


def loaded_event(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next(event for event in events if event["kind"] == "loaded")


def explorer_for_test(qtbot: QtBot, path: str) -> FolderExplorer:
    explorer = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(explorer)
    explorer.selectionPathChanged.connect(lambda p: explorer.load_to_ram_cache(p))
    return explorer


def test_two_tabs_share_snapshot_arrays_and_default_resolution(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = service_for_test(monkeypatch)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    cache, path = get_folder_cache(service), str(tmp_path)
    first = explorer_for_test(qtbot, path)
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    finish_scan(cache, path, children=[str(tmp_path / "child")])
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs)
    finish_load(cache, path)
    assert first.folder_opened_data is not None
    second = explorer_for_test(qtbot, path)
    qtbot.waitUntil(lambda: second.folder_opened_data is not None)
    assert not service.pending
    assert second.folder_opened_data is not None
    assert first.folder_opened_data is not second.folder_opened_data
    assert first.folder_opened_data[1] is second.folder_opened_data[1]
    with pytest.raises(ValueError):
        second.folder_opened_data[1][0, 0] = 99
    second.folder_opened_data.pop(1)
    assert 1 in first.folder_opened_data
    assert second.model.root and len(second.model.root.children) == 1
    tooltip = str(second.model.data(second.model.path_index(path), int(Qt.ItemDataRole.ToolTipRole)))
    assert "Shared RAM" in tooltip
    second._update_activity()
    assert second.scan_label.text() == "Ready · Loaded from memory"
    assert second.spinner_label.isHidden()
    events: list[dict[str, Any]] = []
    cache.resultReady.connect(lambda r, e: events.append(e) if r.owner == "default" else None)
    assert cache.submit("default", 0, path, "resolve", {"candidates": [path]})
    request = producer(cache, path, "resolve")
    service.resultReady.emit(request, {"kind": "resolved", "path": path})
    service.resultReady.emit(request, {"kind": "done"})
    service.pending.remove(request)
    assert cache.submit("default", 1, path, "resolve", {"candidates": [path]})
    qtbot.waitUntil(lambda: len([e for e in events if e["kind"] == "resolved"]) == 2)
    assert not service.pending
    first.close_cleanup()
    assert cache.current_dataset(path) is not None
    second.close_cleanup()
    service.shutdown()


def test_inflight_scan_and_load_survive_one_tab_cancellation(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = service_for_test(monkeypatch)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    cache, path = get_folder_cache(service), str(tmp_path)
    first, second = explorer_for_test(qtbot, path), explorer_for_test(qtbot, path)
    qtbot.waitUntil(lambda: len(cache.requests(first.model.owner)) == 1 and len(cache.requests(second.model.owner)) == 1)
    assert len(service.pending) == 1
    finish_scan(cache, path)
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs and len(cache.jobs[("load", path)].subscribers) == 2)
    assert len(service.pending) == 1
    first.close_cleanup()
    assert len(service.pending) == 1
    finish_load(cache, path)
    assert second.folder_opened_data is not None
    second.close_cleanup()
    service.shutdown()


def test_loading_counts_and_queue_tooltips_follow_shared_jobs(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = service_for_test(monkeypatch)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    cache, path = get_folder_cache(service), str(tmp_path)
    first = explorer_for_test(qtbot, path)
    tabs = QTabWidget()
    qtbot.addWidget(tabs)
    tabs.addTab(first, "First")
    # Exercise the central message with real widgets, without creating native
    # settings, a watchdog, or a full main window and its startup jobs.
    window: Any = SimpleNamespace(_closing=False, tab_widget=tabs, central_placeholder=QLabel(tabs), dock_widgets=[])
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    finish_scan(cache, path)
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs)
    request = producer(cache, path, "load")
    assert first.loading_message == "Queued"
    assert first.scan_label.text() == "Queued · 1 queued"
    assert first.progress.toolTip() == f"Queued\n\nQueued folders (next first):\nLoad data: {path}"
    HelabMainWindow._central_placeholder_loading_indicator(window)
    assert window.central_placeholder.text() == f"{tmp_path.name}\nQueued"
    assert window.central_placeholder.toolTip() == first.progress.toolTip()
    service.pending.remove(request)
    service.resultReady.emit(request, {"kind": "started"})
    assert first.loading_message == "Preparing…"
    service.resultReady.emit(request, {"kind": "progress", "progress": 123 / 456,
                                       "loaded_files": 123, "total_files": 456, "failed_files": 0})
    message = "123 of 456 files loaded (27%)"
    assert first.loading_message == message
    assert first.folder_summary_label.text() == "456 TXY found · 123 loaded (27%)"
    assert first.progress.toolTip() == message
    assert message not in first.scan_label.text()
    assert first.progress.value() == 27
    HelabMainWindow._central_placeholder_loading_indicator(window)
    assert window.central_placeholder.text().endswith(f"Loading {tmp_path.name}\n{message}")
    assert window.central_placeholder.toolTip() == message
    second = explorer_for_test(qtbot, path)
    qtbot.waitUntil(lambda: second.loading)
    assert second.loading_message == message  # Join an already-running shared load.
    other = str(tmp_path / "other")
    cache.submit("tab-c", 0, other, "load")
    first._update_activity()
    assert first.progress.toolTip() == f"{message}\n\nQueued folders (next first):\nLoad data: {other}"
    cache.cancel("tab-c")
    first._update_activity()
    assert first.progress.toolTip() == message
    service.resultReady.emit(request, {"kind": "queued", "retry": True, "attempt": 2})
    for explorer in (first, second):
        assert explorer.loading and not explorer.load_error
        assert explorer.load_progress is None and explorer.load_total_files is None
        assert explorer.load_files == 0 and explorer.load_attempt == 2
    service.resultReady.emit(request, {"kind": "started", "attempt": 2})
    assert first.loading_message == "Retrying… (attempt 2 of 3)"
    # The listing phase reports entries before the first file starts.
    service.resultReady.emit(request, {"kind": "heartbeat", "phase": "listing", "entries": 3200})
    assert first.loading_message == "Retrying… (attempt 2 of 3) · Listing files… 3,200"
    first.close_cleanup()
    second.close_cleanup()
    service.shutdown()


def test_queue_tooltip_covers_scans_loads_and_navigation_across_tabs_when_idle(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = service_for_test(monkeypatch)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    cache, path = get_folder_cache(service), str(tmp_path)
    first = explorer_for_test(qtbot, path)
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    first.auto_load_ram = False
    finish_scan(cache, path)
    assert not first.loading
    bulk, data, browse = (str(tmp_path / name) for name in ("bulk", "data", "browse"))
    cache.submit("other-tab", 0, bulk, "scan", {"metadata_only": True})
    cache.submit("other-tab", 0, data, "load")
    cache.submit("other-tab", 0, browse, "list", priority=True)
    first._update_activity()
    expected = (f"Queued folders (next first):\nLoad data: {data}\nBrowse folder: {browse}"
                f"\nBasic scan: {bulk}")
    assert first.scan_label.text().endswith("3 queued")
    assert first.scan_label.toolTip() == expected
    assert first.progress.toolTip() == expected
    assert expected in first.folder_summary_label.toolTip()
    # The pending list is global and deduplicated despite multiple subscribers.
    cache.submit("third-tab", 0, data, "load")
    assert len(service.queued_operations()) == 3
    cache.cancel("other-tab")
    first._update_activity()
    assert first.scan_label.text().endswith("1 queued")
    assert first.progress.toolTip() == f"Queued folders (next first):\nLoad data: {data}"
    cache.cancel("third-tab")
    first._update_activity()
    assert "queued" not in first.scan_label.text().lower()
    assert "Queued folders" not in first.folder_summary_label.toolTip()
    first.close_cleanup()
    service.shutdown()


def test_queue_explains_waiting_for_timed_out_operation_to_stop(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = service_for_test(monkeypatch)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    cache, path = get_folder_cache(service), str(tmp_path)
    explorer = explorer_for_test(qtbot, path)
    explorer.auto_load_ram = False
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    old = producer(cache, path, "list")
    service.pending.remove(old)
    old.retirement_reason = "timed out"
    old.retired_at = time.monotonic() - 42
    old.cancelled.set()
    service.retired.append(old)
    # A listing is not retried automatically, so nothing is held behind it.
    rerun = IORequest(old.owner, old.generation, path, "list", old.payload, 60.0)
    service.pending.append(rerun)
    explorer._update_activity()
    # One phrase for the stuck helper and the request it holds; that request is not counted twice.
    assert explorer.scan_label.text() == "Waiting for timed-out folder listing to stop (42 s)"
    tooltip = explorer.scan_label.toolTip()
    assert (f"Browse folder: {path} — timed out after 60 s without progress · stopping for 42 s"
            " · requested again; starts when it exits") in tooltip
    assert "volume is not responding" in tooltip and "Queued folders" not in tooltip
    assert "Other queued I/O" not in tooltip  # Only the held request is waiting.
    assert "Stopping operations" in explorer.folder_summary_label.toolTip()
    # The main status bar must expose the same queue, including basic scans.
    monkeypatch.setattr("helab.views.HelabMainWindow.get_io_service", lambda: service)
    global_label = QLabel(explorer)
    window: Any = SimpleNamespace(
        _closing=False, status_bar_message_left=global_label, action_tab_live_checked=True,
        _update_cancel_loading_action=lambda: None,
        tab_widget=SimpleNamespace(set_tab_switching_enable=lambda: None),
    )
    HelabMainWindow.update_status_bar_left(window)
    assert global_label.text() == ("Scanning 0 folders · Loading 0 datasets · "
                                   "Waiting for timed-out folder listing to stop (42 s) · 0 queued")
    assert global_label.toolTip() == explorer.scan_label.toolTip()
    service.messages.put((old, {"kind": "exit"}))
    service._tick()
    explorer._update_activity()
    assert "waiting for timed-out" not in explorer.scan_label.text()
    writer = IORequest("writer", 0, path, "load", {}, 120.0, completed=True)
    service.active.append(writer)
    HelabMainWindow.update_status_bar_left(window)
    assert "Saving 1 cache" in global_label.text() and "Loading 0 datasets" in global_label.text()
    assert "stopping" not in global_label.text()
    explorer.close_cleanup()
    service.shutdown()


def test_manual_retry_lists_without_timeout_shows_elapsed_and_can_be_cancelled(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = service_for_test(monkeypatch)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    cache, path = get_folder_cache(service), str(tmp_path)
    explorer = explorer_for_test(qtbot, path)
    explorer.auto_load_ram = False
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    first = producer(cache, path, "list")
    assert first.timeout == service.NO_PROGRESS_TIMEOUT
    service.pending.remove(first)
    service.resultReady.emit(first, {"kind": "error", "timeout": True, "attempt": 1,
                                     "message": "Timed out after 60 s without progress — Retry"})
    explorer._update_activity()
    # A listing timeout is a scan failure.
    assert explorer.folder_summary_label.text() == "TXY count not checked · Retry manually"
    assert cache.scan_history(path)["blocked"]
    assert not explorer.retry_button.isHidden() and explorer.cancel_load_button.isHidden()
    # The status-line Retry lists the selected folder with no timeout.
    explorer._retry()
    retry = producer(cache, path, "list")
    assert retry.timeout == math.inf
    node = explorer.model.nodes[path]
    assert node.retry_since is not None
    node.retry_since -= 80
    service.resultReady.emit(retry, {"kind": "heartbeat", "phase": "listing", "entries": 3200})
    explorer._update_activity()
    assert explorer.folder_summary_label.text() == "Retrying… 1 min 20 s · 3,200 entries"
    assert not explorer.cancel_load_button.isHidden() and explorer.can_cancel_loading
    assert explorer.cancel_load_button.toolTip() == "Cancel the folder listing retry (Esc)"
    explorer.cancel_loading()
    assert retry.cancelled.is_set() and ("list", path) not in cache.jobs
    assert node.state == "cancelled" and node.retry_since is None
    assert explorer.cancel_load_button.isHidden() and explorer.retrying_scan is None
    # Right-click Retry / Refresh joins a running listing and lifts its limit.
    assert explorer.model.request_scan(path, force=True)
    bulk = producer(cache, path, "list")
    assert bulk.timeout == service.NO_PROGRESS_TIMEOUT
    assert explorer.model.request_scan(path, priority=True, force=True, no_timeout=True)
    assert producer(cache, path, "list") is bulk and bulk.timeout == math.inf
    assert explorer.retrying_scan is node
    explorer.close_cleanup()
    service.shutdown()


def test_scan_timeout_fails_once_for_shared_subscribers(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_run", lambda request: None)
    cache, path = get_folder_cache(service), str(tmp_path)
    events: list[dict[str, Any]] = []
    cache.resultReady.connect(lambda request, event: events.append(event) if request.owner == "tab-b" else None)
    cache.submit("tab-a", 0, path, "scan")
    cache.submit("tab-b", 0, path, "scan")
    request = service.active[0]
    request.started = request.last_activity = time.monotonic() - request.timeout - 1
    service._tick()
    assert ("scan", path) not in cache.jobs and not service.pending
    errors = [event for event in events if event["kind"] == "error"]
    assert len(errors) == 1 and errors[0]["message"] == "Timed out after 60 s without progress — Retry"
    service.shutdown()


def test_load_timeout_retry_resumes_files_for_shared_subscribers(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_run", lambda request: None)
    cache, path = get_folder_cache(service), str(tmp_path)
    events: list[dict[str, Any]] = []
    cache.resultReady.connect(lambda request, event: events.append(event) if request.owner == "tab-b" else None)
    cache.submit("tab-a", 0, path, "load")
    cache.submit("tab-b", 0, path, "load")
    request = service.active[0]
    job = cache.jobs[("load", path)]
    first, second = (os.path.join(path, f"d_txy_forc{shot}.txt") for shot in (1, 2))
    service.messages.put((request, {"kind": "file_started", "filename": first}))
    service.messages.put((request, {"kind": "shot", "shot": 1, "array": np.array([[1.0, 2, 3]]),
                                   "fingerprint": [1, 10, 100], "problematic": True}))
    service.messages.put((request, {"kind": "file_finished", "filename": first}))
    service.messages.put((request, {"kind": "progress", "progress": 0.5, "loaded_files": 1, "total_files": 2}))
    service.messages.put((request, {"kind": "file_started", "filename": second}))
    service._tick()
    assert job.data
    request.started = request.last_activity = time.monotonic() - request.timeout - 1
    service._tick()
    assert job.state == "queued" and job.attempt == 2
    assert not job.data and job.progress is None
    cache.cancel("tab-a")
    assert len(job.subscribers) == 1 and service.pending  # The other tab still needs this retry.
    service.messages.put((request, {"kind": "done"}))  # Late success from the discarded attempt.
    service.messages.put((request, {"kind": "exit"}))
    service._tick()
    retry = service.active[0]
    assert retry.payload["memory"] == [[1, 10, 100]]
    service.messages.put((retry, {"kind": "shot", "shot": 2, "array": np.array([[4.0, 5, 6]])}))
    service.messages.put((retry, {"kind": "loaded", "signature": "v1", "bytes": 24,
                                 "rows": 1, "files": 1, "problematic": [], "memory_shots": [1]}))
    service._tick()
    dataset = cache.current_dataset(path)
    assert dataset is not None and list(dataset.data) == [1, 2]
    assert loaded_event(events)["files"] == 2 and loaded_event(events)["problematic"] == [1]
    assert not any(event["kind"] == "error" for event in events)


def test_expired_snapshot_is_visible_during_failed_background_check(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = service_for_test(monkeypatch)
    cache, path = get_folder_cache(service), str(tmp_path)
    first = SnapshotFileSystemModel(service=service)
    first.setRootPath(path)
    child = str(tmp_path / "child")
    finish_scan(cache, path, children=[child])
    qtbot.waitUntil(lambda: bool(first.root and first.root.loaded))
    snapshot = cache.snapshot(path)
    assert snapshot is not None
    snapshot.checked_at = time.monotonic() - cache.FRESH_SECONDS - 1
    second = SnapshotFileSystemModel(service=service)
    second.setRootPath(path)
    qtbot.waitUntil(lambda: bool(second.root and second.root.loaded) and ("list", path) in cache.jobs)
    assert child in second.nodes
    assert len(service.pending) == 1
    request = producer(cache, path, "list")
    service.resultReady.emit(request, {"kind": "entries", "entries": [{"path": str(tmp_path / "partial"), "modified": None}]})
    service.resultReady.emit(request, {"kind": "error", "message": "offline"})
    assert cache.snapshot(path) is snapshot
    assert str(tmp_path / "partial") not in second.nodes
    assert second.root and second.root.error == "offline"
    first.close_cleanup()
    second.close_cleanup()
    service.shutdown()


def test_refresh_propagates_changed_data_to_both_tabs(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = service_for_test(monkeypatch)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    cache, path = get_folder_cache(service), str(tmp_path)
    first, second = explorer_for_test(qtbot, path), explorer_for_test(qtbot, path)
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    finish_scan(cache, path)
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs and len(cache.jobs[("load", path)].subscribers) == 2)
    finish_load(cache, path)
    first.refresh()
    assert len(service.pending) == 1
    finish_scan(cache, path, signature="v2")
    assert first.folder_opened_data is not None  # Keep old displayed data.
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs and len(cache.jobs[("load", path)].subscribers) == 2)
    finish_load(cache, path, signature="v2", value=10)
    assert second.folder_opened_data is not None
    assert second.folder_opened_data[1] is first.folder_opened_data[1]
    assert first.folder_opened_data[1][0, 0] == 10
    first.close_cleanup()
    second.close_cleanup()
    service.shutdown()


def test_refresh_reuses_open_dataset_and_receives_only_new_shots(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = service_for_test(monkeypatch)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    cache, path = get_folder_cache(service), str(tmp_path)
    explorer = explorer_for_test(qtbot, path)
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    finish_scan(cache, path)
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs)
    request = producer(cache, path, "load")
    assert "memory" not in request.payload
    service.resultReady.emit(request, {"kind": "shot", "shot": 1, "array": np.array([[1.0, 2, 3]])})
    service.resultReady.emit(request, {"kind": "loaded", "signature": "v1", "bytes": 24, "rows": 1, "files": 1,
                                       "problematic": [1], "fingerprint": [[1, 10, 100], [9, 0, 100]]})
    service.resultReady.emit(request, {"kind": "done"})
    service.pending.remove(request)
    old = explorer.folder_opened_data
    assert old is not None

    explorer.refresh()
    finish_scan(cache, path, signature="v2")
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs)
    request = producer(cache, path, "load")
    # Shot 9 failed to load, so only shot 1 can be reused from RAM.
    assert request.payload["memory"] == [[1, 10, 100]]
    service.resultReady.emit(request, {"kind": "shot", "shot": 2, "array": np.array([[4.0, 5, 6], [7, 8, 9]])})
    service.resultReady.emit(request, {"kind": "loaded", "signature": "v2", "bytes": 48, "rows": 2, "files": 2,
                                       "problematic": [], "memory_shots": [1], "disk_cached": False,
                                       "source": "updated", "fingerprint": [[1, 10, 100], [2, 20, 200]]})
    data = explorer.folder_opened_data
    assert data is not None and list(data) == [1, 2]
    assert data[1] is old[1]
    assert not explorer.loading and explorer.load_source == "updated"
    assert explorer.model.fetch_status(path).problematic_txy_ns == [1]
    assert explorer.load_bytes == 72
    # The helper keeps updating the disk cache without holding the load job.
    assert ("load", path) not in cache.jobs and not cache.disk_cached(path)
    service.resultReady.emit(request, {"kind": "disk_cached", "disk_cached": True})
    service.resultReady.emit(request, {"kind": "done"})
    assert cache.disk_cached(path) and not cache._finishing
    explorer.close_cleanup()
    service.shutdown()


def test_invalidation_rejects_late_load_results_and_rechecks(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = service_for_test(monkeypatch)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    cache, path = get_folder_cache(service), str(tmp_path)
    first = explorer_for_test(qtbot, path)
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    finish_scan(cache, path)
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs)
    old = producer(cache, path, "load")
    first.clear_data_cache(path)
    assert old.cancelled.is_set()
    service.resultReady.emit(old, {"kind": "loaded", "signature": "v1", "bytes": 24})
    assert cache.current_dataset(path) is None
    assert first.folder_opened_data is None
    clear = producer(cache, path, "invalidate")
    service.resultReady.emit(clear, {"kind": "done"})
    service.pending.remove(clear)
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    finish_scan(cache, path)
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs)
    finish_load(cache, path)
    assert first.folder_opened_data is not None
    first.close_cleanup()
    service.shutdown()


def test_memory_budget_evicts_unused_entries_but_pins_open_data(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = service_for_test(monkeypatch)
    cache = get_folder_cache(service)
    cache.MAX_DATA_BYTES = 24
    first = Dataset("/one", "v1", {1: np.zeros((1, 3))}, {"bytes": 24}, 0)
    second = Dataset("/two", "v1", {1: np.zeros((1, 3))}, {"bytes": 24}, 0)
    cache.datasets[(cache.key("/one"), "v1", 0)] = first
    cache.retain("tab", first)
    cache.datasets[(cache.key("/two"), "v1", 0)] = second
    cache._evict()
    assert cache.dataset("/one", "v1") is first
    assert cache.dataset("/two", "v1") is None
    cache.MAX_DATA_BYTES = 0
    cache.release("tab")
    assert not cache.datasets
    service.shutdown()


def test_refresh_supersedes_older_cached_snapshot_replay(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = service_for_test(monkeypatch)
    cache, path = get_folder_cache(service), str(tmp_path)
    first = SnapshotFileSystemModel(service=service)
    first.setRootPath(path)
    finish_scan(cache, path, children=[str(tmp_path / "old")])
    qtbot.waitUntil(lambda: bool(first.root and first.root.loaded))
    second = SnapshotFileSystemModel(service=service)
    second.setRootPath(path)  # Cached delivery has not run yet.
    first.request_scan(path, force=True)
    finish_scan(cache, path, signature="v2", children=[str(tmp_path / "new")])
    qtbot.waitUntil(lambda: bool(second.root and second.root.loaded and second.root.signature == "v2"))
    assert str(tmp_path / "new") in second.nodes
    assert str(tmp_path / "old") not in second.nodes
    first.close_cleanup()
    second.close_cleanup()
    service.shutdown()


def test_cached_child_counts_are_restored_without_scanning_children(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = service_for_test(monkeypatch)
    cache, path, child = get_folder_cache(service), str(tmp_path), str(tmp_path / "child")
    child_model = SnapshotFileSystemModel(service=service)
    child_model.setRootPath(child)
    finish_scan(cache, child)
    qtbot.waitUntil(lambda: bool(child_model.root and child_model.root.loaded))
    parent_model = SnapshotFileSystemModel(service=service)
    parent_model.setRootPath(path)
    finish_scan(cache, path, children=[child])
    qtbot.waitUntil(lambda: child in parent_model.nodes)
    assert parent_model.fetch_status(child).count == 1
    assert parent_model.nodes[child].loaded
    assert not service.pending
    child_report = parent_model.fetch_status(child)
    assert child_report.d_txy_shots is not None
    child_report.d_txy_shots.clear()
    snapshot = cache.snapshot(child)
    assert snapshot and snapshot.status["txy"] == [1]
    child_model.close_cleanup()
    parent_model.close_cleanup()
    service.shutdown()


def test_oversized_scan_is_not_published_and_reports_limit(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = service_for_test(monkeypatch)
    cache, path = get_folder_cache(service), str(tmp_path)
    cache.MAX_ENTRIES = 0
    model = SnapshotFileSystemModel(service=service)
    model.setRootPath(path)
    finish_scan(cache, path, children=[str(tmp_path / "child")])
    assert not cache.snapshots
    assert model.root and model.root.state == "error"
    assert "entry limit" in model.root.error
    model.close_cleanup()
    service.shutdown()


def test_real_helpers_reuse_warm_tab_without_scan_or_decompression(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = IOService()
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    operations: list[str] = []
    original = service.submit

    def record(owner: str, generation: int, path: str, operation: str,
               payload: dict[str, Any] | None = None, *, priority: bool = False,
               timeout: float = 15.0) -> bool:
        operations.append(operation)
        return original(owner, generation, path, operation, payload, priority=priority, timeout=timeout)

    monkeypatch.setattr(service, "submit", record)
    (tmp_path / "d1.txt").write_text("")
    source = tmp_path / "d_txy_forc1.txt"
    source.write_text("1,2,3\n")
    first = explorer_for_test(qtbot, str(tmp_path))
    qtbot.waitUntil(lambda: first.folder_opened_data is not None, timeout=15000)
    assert first.load_source == "files"
    qtbot.waitUntil(lambda: bool(first.model.cache.cache_status(str(tmp_path)).info), timeout=15000)
    first_saved_at = first.model.cache.cache_status(str(tmp_path)).info["saved_at"]
    assert first.folder_cache_label.text().startswith("Cache created ")
    # The load lists and fingerprints the folder, so the details scan is skipped.
    assert operations == ["list", "load"]
    second = explorer_for_test(qtbot, str(tmp_path))
    qtbot.waitUntil(lambda: second.folder_opened_data is not None)
    assert second.load_source == "memory"
    assert second.folder_cache_label.text().startswith("Cached data loaded · Cached ")
    assert second.model.cache.cache_status(str(tmp_path)).info["saved_at"] == first_saved_at
    assert second.load_counts["reused_memory"] == 1 and second.load_counts["read"] == 0
    assert operations == ["list", "load"]  # No helper for warm memory reuse.
    assert first.folder_opened_data is not None and second.folder_opened_data is not None
    assert first.folder_opened_data[1] is second.folder_opened_data[1]
    source.write_text("10,20,30\n")
    first.refresh()
    qtbot.waitUntil(lambda: second.folder_opened_data is not None and second.folder_opened_data[1][0, 0] == 10,
                   timeout=15000)
    # The listing finds the same names; the details scan finds the modified file.
    assert operations == ["list", "load", "list", "details", "load"]
    assert first.folder_opened_data[1] is second.folder_opened_data[1]
    qtbot.waitUntil(lambda: first.model.cache.cache_status(str(tmp_path)).info.get("saved_at", 0)
                   > first_saved_at, timeout=15000)
    updated_at = first.model.cache.cache_status(str(tmp_path)).info["saved_at"]
    assert first.folder_cache_label.text().startswith("Cache updated ")
    assert "1 modified file loaded" in first.folder_cache_label.toolTip()
    first.close_cleanup()
    second.close_cleanup()
    service.shutdown()

    # A new service has no session snapshots or arrays, like a restarted app.
    restarted_service = IOService()
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: restarted_service)
    reopened = explorer_for_test(qtbot, str(tmp_path))
    qtbot.waitUntil(lambda: reopened.folder_opened_data is not None, timeout=15000)
    assert reopened.load_source == "disk"
    assert reopened.model.cache.cache_status(str(tmp_path)).info["saved_at"] == updated_at
    assert reopened.folder_cache_label.text().startswith("Cached data loaded · Cached ")
    qtbot.waitUntil(lambda: not reopened.model.cache.requests(reopened.model.owner))
    reopened._update_activity()
    assert reopened.scan_label.text() == "Ready · Loaded from disk cache"
    reopened.close_cleanup()
    restarted_service.shutdown()


def test_disk_cache_reused_after_process_restart_and_rejects_changed_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    converted = source / "d_txy_forc1.txt"
    converted.write_text("1,2,3\n")
    program = """
import json, sys
import pandas as pd
from helab.io_helper import load
request = json.load(sys.stdin)
if request["require_cache"]:
    def forbid_csv(*args, **kwargs):
        raise AssertionError("Restart read source TXY instead of disk cache")
    pd.read_csv = forbid_csv
events = []
load(request["path"], request["output"], events.append, request["cache"])
print(json.dumps(events))
"""

    def run(name: str, require_cache: bool) -> list[dict[str, Any]]:
        output = tmp_path / name
        output.mkdir()
        request = {"path": str(source), "output": str(output), "require_cache": require_cache,
                   "cache": {"directory": str(tmp_path / "cache"), "params": {"shards": 2}}}
        completed = subprocess.run([sys.executable, "-c", program], input=json.dumps(request),
                                   capture_output=True, text=True, check=True, timeout=30)
        events: list[dict[str, Any]] = json.loads(completed.stdout)
        return events

    for name, require_cache, expected in (("cold", False, "files"), ("restart", True, "disk")):
        events = run(name, require_cache)
        # The folder summary comes first, before any cache or file read.
        assert events[0]["kind"] == "scan_summary" and events[0]["status"]["txy"] == [1]
        source_event = next(event for event in events if event["kind"] == "load_source")
        assert source_event["source"] == expected
        assert source_event["cache_reason"] == ("" if require_cache else "No saved cache fingerprint")
        assert loaded_event(events)["source"] == expected
        assert loaded_event(events)["cached"] is require_cache
        assert not any(event["kind"] == "cache_warning" for event in events)
        np.testing.assert_array_equal(np.load(tmp_path / name / "1.npy"), [[1, 2, 3]])

    converted.write_text("100,200,300\n")
    events = run("changed", False)
    assert loaded_event(events)["source"] == "files"
    assert loaded_event(events)["cache_reason"] == "TXY files changed since caching"
    assert loaded_event(events)["cached"] is False
    np.testing.assert_array_equal(np.load(tmp_path / "changed" / "1.npy"), [[100, 200, 300]])


def test_changed_folder_reads_only_new_or_modified_txy_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import blosc
    import pickle
    import pandas as pd
    from diskcache import FanoutCache

    source = tmp_path / "source"
    source.mkdir()
    for shot in (1, 2, 3):
        (source / f"d_txy_forc{shot}.txt").write_text(f"{shot},{shot},{shot}\n")
    (source / "d_txy_forc4.txt").write_text("4,nan,4\n5,5,5\n")
    options: dict[str, Any] = {"directory": str(tmp_path / "cache"), "params": {"shards": 2}}
    (tmp_path / "first").mkdir()
    load(str(source), str(tmp_path / "first"), lambda event: None, options)

    (source / "d_txy_forc2.txt").write_text("20,20,20\n")
    (source / "d_txy_forc3.txt").unlink()
    (source / "d_txy_forc5.txt").write_text("50,50,50\n")
    original_read_csv = pd.read_csv
    read: list[str] = []

    def record_read_csv(filename: str, *args: Any, **kwargs: Any) -> Any:
        read.append(os.path.basename(filename))
        return original_read_csv(filename, *args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", record_read_csv)
    output = tmp_path / "second"
    output.mkdir()
    events: list[dict[str, Any]] = []
    load(str(source), str(output), events.append, options)
    assert sorted(read) == ["d_txy_forc2.txt", "d_txy_forc5.txt"]
    assert next(event for event in events if event["kind"] == "load_source") == {"kind": "load_source", "source": "merged",
                         "cache_reason": "Reused 2 shots from disk cache; read 2 new or changed TXY files"}
    assert loaded_event(events)["source"] == "merged"
    assert loaded_event(events)["problematic"] == [4]
    assert loaded_event(events)["load_counts"] == {
        "reused_memory": 0, "reused_disk": 2, "new": 1, "modified": 1, "removed": 1,
        "read": 2, "new_loaded": 1, "modified_loaded": 1,
    }
    assert events[-1] == {"kind": "disk_cached", "disk_cached": True}
    for shot, expected in ((1, [[1, 1, 1]]), (2, [[20, 20, 20]]), (4, [[5, 5, 5]]), (5, [[50, 50, 50]])):
        np.testing.assert_array_equal(np.load(output / f"{shot}.npy"), expected)
    assert not (output / "3.npy").exists()
    with FanoutCache(options["directory"], **options["params"]) as cache:
        merged = pickle.loads(blosc.decompress(cache.get(str(source))))
        assert sorted(merged) == [1, 2, 4, 5]
        assert cache.get(("snapshot-problematic", str(source))) == [4]

    events.clear()
    (tmp_path / "third").mkdir()
    load(str(source), str(tmp_path / "third"), events.append, options)
    assert loaded_event(events)["source"] == "disk"
    assert sorted(read) == ["d_txy_forc2.txt", "d_txy_forc5.txt"]


def test_load_skips_shots_already_in_memory_and_completes_disk_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import blosc
    import pickle
    import pandas as pd
    from diskcache import FanoutCache

    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    for shot in (1, 2, 3):
        (source / f"d_txy_forc{shot}.txt").write_text(f"{shot},{shot},{shot}\n")
    memory = [[shot, info.st_size, info.st_mtime_ns] for shot in (1, 2, 3)
              for info in ((source / f"d_txy_forc{shot}.txt").stat(),)]
    (source / "d_txy_forc3.txt").write_text("30,30,30\n")
    original_read_csv = pd.read_csv
    read: list[str] = []
    events: list[dict[str, Any]] = []

    def record_read_csv(filename: str, *args: Any, **kwargs: Any) -> Any:
        # Before ``loaded`` only changed files are read; afterwards the disk
        # cache (empty here) is completed in the background.
        read.append(os.path.basename(filename) + ("" if any(e["kind"] == "loaded" for e in events) else "*"))
        return original_read_csv(filename, *args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", record_read_csv)
    options: dict[str, Any] = {"directory": str(tmp_path / "cache"), "params": {"shards": 2}}
    load(str(source), str(output), events.append, options, memory)
    assert read == ["d_txy_forc3.txt*", "d_txy_forc1.txt", "d_txy_forc2.txt"]
    assert [event["shot"] for event in events if event["kind"] == "shot"] == [3]
    loaded = loaded_event(events)
    assert loaded["source"] == "updated" and loaded["memory_shots"] == [1, 2]
    assert loaded["load_counts"] == {
        "reused_memory": 2, "reused_disk": 0, "new": 0, "modified": 1, "removed": 0,
        "read": 1, "new_loaded": 0, "modified_loaded": 1,
    }
    assert loaded["cache_reason"] == "Reused 2 shots from memory; read 1 new or changed TXY files"
    assert events[-1] == {"kind": "disk_cached", "disk_cached": True}
    with FanoutCache(options["directory"], **options["params"]) as cache:
        assert sorted(pickle.loads(blosc.decompress(cache.get(str(source))))) == [1, 2, 3]


def test_scan_reports_cached_children_without_loading_or_probing_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import blosc

    root, output = tmp_path / "root", tmp_path / "output"
    source = root / "experiment"
    source.mkdir(parents=True)
    output.mkdir()
    (source / "d_txy_forc1.txt").write_text("1,2,3\n")
    options: dict[str, Any] = {"directory": str(tmp_path / "cache"), "params": {"shards": 2}}
    load(str(source), str(output), lambda event: None, options)
    original_scandir = os.scandir
    scanned: list[str] = []

    def record_scandir(path: str) -> Any:
        scanned.append(path)
        return original_scandir(path)

    def forbid_decompression(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Checking cache badges decompressed a dataset")

    monkeypatch.setattr("os.scandir", record_scandir)
    monkeypatch.setattr(blosc, "decompress", forbid_decompression)
    events: list[dict[str, Any]] = []
    scan(str(root), events.append, options)
    assert scanned == [str(root)]
    assert next(e for e in events if e["kind"] == "entries")["entries"][0]["disk_cached"] is True
    assert next(e for e in events if e["kind"] == "status")["disk_cached"] is False
    events.clear()
    scan(str(source), events.append, options)
    assert next(e for e in events if e["kind"] == "status")["disk_cached"] is True


def test_disk_badge_after_restart_ram_load_eviction_and_clear(qtbot: QtBot, tmp_path: Path) -> None:
    IconsInitUtil.initialise_icons()
    root, output = tmp_path / "root", tmp_path / "output"
    source = root / "experiment"
    source.mkdir(parents=True)
    output.mkdir()
    (source / "d1.txt").write_text("")
    (source / "d_txy_forc1.txt").write_text("1,2,3\n")
    service = IOService()
    model = SnapshotFileSystemModel(service=service)
    options = model._cache_options
    load(str(source), str(output), lambda event: None, options)
    model.setRootPath(str(root))
    qtbot.waitUntil(lambda: bool(model.root and model.root.loaded), timeout=15000)
    path = str(source)
    index = model.path_index(path, model.COLUMN_STATUS_ICON)

    def badges() -> object:
        return model.data(index, model.STATUS_EXTRA_ICONS_ROLE)

    # Subfolder cache lookups come with the root's background details scan.
    qtbot.waitUntil(lambda: badges() == [StatusIcons.ICON_CACHED], timeout=15000)
    assert model.cache.current_dataset(path) is None
    assert "Cached on disk; not loaded into RAM" in str(model.data(index, int(Qt.ItemDataRole.ToolTipRole)))
    model.request_scan(path, priority=True)
    qtbot.waitUntil(lambda: model.nodes[path].loaded, timeout=15000)
    assert model.cache.submit(model.owner, model.generation, path, "load",
                              {"cache": options, "signature": model.nodes[path].signature}, timeout=30)
    qtbot.waitUntil(lambda: model.cache.current_dataset(path) is not None, timeout=15000)
    assert badges() == [StatusIcons.ICON_RAM_OPENED]
    assert "not loaded into RAM" not in str(model.data(index, int(Qt.ItemDataRole.ToolTipRole)))
    model.cache.MAX_DATA_BYTES = 0
    model.cache._evict()
    assert badges() == [StatusIcons.ICON_CACHED]
    assert model.cache.submit(model.owner, model.generation, path, "invalidate", {"cache": options})
    qtbot.waitUntil(lambda: not model.cache.requests(model.owner), timeout=15000)
    assert badges() == []
    assert not model.cache.disk_cached(path)
    model.close_cleanup()
    service.shutdown()


def test_disk_clear_epoch_prevents_older_load_from_repopulating_cache(tmp_path: Path) -> None:
    from diskcache import FanoutCache
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    (source / "d_txy_forc1.txt").write_text("1,2,3\n")
    options: dict[str, Any] = {"directory": str(tmp_path / "cache"), "params": {"shards": 2}}

    def clear_during_delivery(event: dict[str, Any]) -> None:
        if event["kind"] == "shot":
            with FanoutCache(options["directory"], **options["params"]) as cache:
                cache.set(("snapshot-epoch", str(source)), "cleared")

    load(str(source), str(output), clear_during_delivery, options)
    with FanoutCache(options["directory"], **options["params"]) as cache:
        assert cache.get(str(source)) is None
        assert cache.get(("snapshot-fingerprint", str(source))) is None


def test_save_date_persists_and_cache_reuse_does_not_rewrite_it(tmp_path: Path) -> None:
    from diskcache import FanoutCache
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    (source / "d_txy_forc1.txt").write_text("1,2,3\n")
    path = str(source)
    options: dict[str, Any] = {"directory": str(tmp_path / "cache"), "params": {"shards": 2}}
    events: list[dict[str, Any]] = []
    load(path, str(output), events.append, options)
    saved = next(event["cache_info"] for event in events if event["kind"] == "cache_saved")
    assert saved["action"] == "created"
    assert saved["saved_at"] > 0
    with FanoutCache(options["directory"], **options["params"]) as cache:
        assert cache.get(("snapshot-cache-info", path)) == saved
    events.clear()
    scan(path, events.append, options)
    assert next(e for e in events if e["kind"] == "status")["cache_info"] == saved
    events.clear()
    load(path, str(output), events.append, options)
    assert loaded_event(events)["cache_info"] == saved
    assert loaded_event(events)["load_counts"]["reused_disk"] == 1
    assert not any(event["kind"] == "cache_saved" for event in events)
    # A legacy cache remains readable without inventing its save date.
    with FanoutCache(options["directory"], **options["params"]) as cache:
        cache.pop(("snapshot-cache-info", path))
    events.clear()
    load(path, str(output), events.append, options)
    assert loaded_event(events)["source"] == "disk"
    assert loaded_event(events)["cache_info"] == {}


@pytest.mark.parametrize("failed_key", ["data", "snapshot-fingerprint", "snapshot-cache-info"])
def test_failed_save_rolls_back_bytes_fingerprint_and_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_key: str,
) -> None:
    from diskcache import FanoutCache
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    path = str(source)
    converted = source / "d_txy_forc1.txt"
    converted.write_text("1,2,3\n")
    options: dict[str, Any] = {"directory": str(tmp_path / "cache"), "params": {"shards": 2}}
    load(path, str(output), lambda event: None, options)
    keys = [path, ("snapshot-fingerprint", path), ("snapshot-cache-info", path)]
    with FanoutCache(options["directory"], **options["params"]) as cache:
        before = [cache.get(key) for key in keys]
    converted.write_text("10,20,30\n")
    original_set = FanoutCache.set

    def fail_set(self: Any, key: Any, value: Any, *args: Any, **kwargs: Any) -> bool:
        if key == (path if failed_key == "data" else (failed_key, path)):
            return False
        return bool(original_set(self, key, value, *args, **kwargs))

    monkeypatch.setattr(FanoutCache, "set", fail_set)
    events: list[dict[str, Any]] = []
    load(path, str(output), events.append, options)
    assert loaded_event(events)["files"] == 1
    assert any(event["kind"] == "cache_save_failed" for event in events)
    assert not any(event["kind"] == "cache_saved" for event in events)
    with FanoutCache(options["directory"], **options["params"]) as cache:
        assert [cache.get(key) for key in keys] == before
    np.testing.assert_array_equal(np.load(output / "1.npy"), [[10, 20, 30]])


def test_new_file_during_background_save_caches_loaded_shots_as_possibly_old(tmp_path: Path) -> None:
    from diskcache import FanoutCache
    from helab.utils.cache_freshness import CacheFreshness, cache_freshness, data_as_of
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    path = str(source)
    (source / "d_txy_forc1.txt").write_text("1,2,3\n")
    options: dict[str, Any] = {"directory": str(tmp_path / "cache"), "params": {"shards": 2}}
    events: list[dict[str, Any]] = []

    def add_after_load(event: dict[str, Any]) -> None:
        events.append(event)
        if event["kind"] == "loaded":
            time.sleep(0.02)  # The new shot's folder mtime must follow the load's file listing.
            (source / "d_txy_forc2.txt").write_text("4,5,6\n")

    load(path, str(output), add_after_load, options)
    saved = next(event for event in events if event["kind"] == "cache_saved")["cache_info"]
    assert not any(event["kind"] == "cache_save_failed" for event in events)
    with FanoutCache(options["directory"], **options["params"]) as cache:
        fingerprint = cache.get(("snapshot-fingerprint", path))
        assert isinstance(fingerprint, list) and [entry[0] for entry in fingerprint] == [1]
    # Saved after the shot arrived, but compared from the file listing, so it is not shown as current.
    modified = source.stat().st_mtime
    assert saved["saved_at"] > modified > saved["snapshot_at"]
    assert data_as_of(saved) == saved["snapshot_at"]
    assert cache_freshness(data_as_of(saved), modified) == CacheFreshness.POSSIBLY_OLD


def test_corrupt_disk_cache_reports_failure_and_loads_source(tmp_path: Path) -> None:
    from diskcache import FanoutCache

    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    converted = source / "d_txy_forc1.txt"
    converted.write_text("1,2,3\n")
    info = converted.stat()
    options: dict[str, Any] = {"directory": str(tmp_path / "cache"), "params": {"shards": 2}}
    with FanoutCache(options["directory"], **options["params"]) as cache:
        cache.set(("snapshot-fingerprint", str(source)), [(1, info.st_size, info.st_mtime_ns)])
        cache.set(str(source), b"invalid compressed dataset")
    events: list[dict[str, Any]] = []
    load(str(source), str(output), events.append, options)
    warning = next(event for event in events if event["kind"] == "cache_warning")
    assert warning["message"].startswith("Cache read failed:")
    assert loaded_event(events)["cache_reason"] == warning["message"]
    assert loaded_event(events)["source"] == "files"
    np.testing.assert_array_equal(np.load(output / "1.npy"), [[1, 2, 3]])


def test_changed_source_during_load_is_not_published_to_disk_cache(tmp_path: Path) -> None:
    from diskcache import FanoutCache
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    file = source / "d_txy_forc1.txt"
    file.write_text("1,2,3\n")
    options: dict[str, Any] = {"directory": str(tmp_path / "cache"), "params": {"shards": 2}}

    def change_during_delivery(event: dict[str, Any]) -> None:
        if event["kind"] == "shot":
            file.write_text("100,200,300\n")

    with pytest.raises(ValueError, match="changed while loading"):
        load(str(source), str(output), change_during_delivery, options)
    with FanoutCache(options["directory"], **options["params"]) as cache:
        assert cache.get(str(source)) is None


def test_shot_added_during_live_load_is_left_for_the_next_load(tmp_path: Path) -> None:
    from diskcache import FanoutCache
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    for shot in (1, 2):
        (source / f"d_txy_forc{shot}.txt").write_text("1,2,3\n")
    options: dict[str, Any] = {"directory": str(tmp_path / "cache"), "params": {"shards": 2}}
    events: list[dict[str, Any]] = []

    def next_shot_arrives(event: dict[str, Any]) -> None:
        events.append(event)
        if event["kind"] == "shot" and not (source / "d_txy_forc3.txt").exists():
            (source / "d_txy_forc3.txt").write_text("4,5,6\n")

    load(str(source), str(output), next_shot_arrives, options)
    assert loaded_event(events)["files"] == 2
    assert any(e["kind"] == "cache_saved" for e in events)
    assert not any(e["kind"] == "cache_save_failed" for e in events)
    with FanoutCache(options["directory"], **options["params"]) as cache:
        saved = cache.get(("snapshot-fingerprint", str(source)))
        assert isinstance(saved, list) and [entry[0] for entry in saved] == [1, 2]
    # The next load reads only the new shot and reuses the cached ones.
    events.clear()
    (output / "next").mkdir()
    load(str(source), str(output / "next"), events.append, options)
    counts = loaded_event(events)["load_counts"]
    assert (loaded_event(events)["files"], counts["new_loaded"], counts["reused_disk"]) == (3, 1, 2)


@pytest.mark.skipif(sys.platform == "win32", reason="Creating symlinks can require Windows privileges")
def test_scan_and_load_use_same_fingerprint_for_symlinked_data(tmp_path: Path) -> None:
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    target = tmp_path / "converted.txt"
    target.write_text("1,2,3\n")
    (source / "d_txy_forc1.txt").symlink_to(target)
    events: list[dict[str, Any]] = []
    scan(str(source), events.append)
    signature = events[-1]["signature"]
    events.clear()
    load(str(source), str(output), events.append)
    assert events[-1]["signature"] == signature


def test_stopping_rows_merge_held_requests_and_cover_cancelled_final_and_cache_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = service_for_test(monkeypatch)
    now = time.monotonic()

    def stopped(path: str, operation: str, reason: str, age: float | None, **kwargs: Any) -> IORequest:
        request = IORequest("tab", 0, path, operation, kwargs.pop("payload", {}), kwargs.pop("timeout", 15.0), **kwargs)
        request.retirement_reason, request.retired_at = reason, None if age is None else now - age
        service.retired.append(request)
        return request

    stopped("/a", "load", "cancelled", 2)
    again = IORequest("tab", 0, "/a", "load", {}, 15.0)  # Same folder requested again after Cancel.
    stopped("/b", "scan", "timed out", 70, payload={"metadata_only": True}, timeout=60.0)
    stopped("/c", "load", "timed out", None, completed=True)  # Cache writer; no recorded stop time.
    other = IORequest("other-tab", 0, "/a", "load", {}, 15.0)  # Same path, different owner: not held.
    service.pending.extend([again, other])
    tooltip = service.queue_tooltip()
    assert "Load data: /a — cancelled · stopping for 2 s · requested again; starts when it exits" in tooltip
    assert "Basic scan: /b — timed out after 60 s without progress · stopping for 1 min 10 s\n" in tooltip
    assert "Save data cache: /c — timed out while saving the data cache · stopping\n" in tooltip
    assert "Other queued I/O also waits" in tooltip  # The unrelated request needs a held slot.
    assert tooltip.endswith("Queued folders (next first):\nLoad data: /a")
    assert service.held_requests() == [again] and service.blocker(other) is None
    assert service.queued_operations(include_held=False) == [("load", "/a")]
    # The longest-stopping helper leads the one-line status.
    assert service.stopping_summary() == "Waiting for timed-out basic scan to stop (1 min 10 s) · 2 more stopping"
    service.pending.remove(other)
    assert "Other queued I/O" not in service.queue_tooltip()
    load = IORequest("tab", 0, "/e", "load", {}, 20.0, attempt=2, current_file="/e/d_txy_forc12.txt")
    load.retirement_reason, load.retired_at = "timed out", now
    assert ("attempt 2 of 3 timed out after 20 s without progress on d_txy_forc12.txt"
            in service._stopping_row(load, now))
    # Only a load's per-file reads are retried; the retry is described with the helper it waits for.
    service.retired[:] = [load]
    service.pending.clear()
    service.pending.append(IORequest("tab", 0, "/e", "load", {}, 60.0, attempt=3))
    assert service.stopping_summary() == "Retry 3 of 3 waiting for timed-out load to stop (0 s)"
    assert "· attempt 3 of 3 starts when it exits" in service._stopping_row(load, now)
    load.attempt = 3
    service.pending.clear()
    assert service._stopping_row(load, now).endswith("· no retries left")
    service.shutdown()
