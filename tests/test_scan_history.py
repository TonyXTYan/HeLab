from __future__ import annotations

from pathlib import Path
import time
from typing import Any

import numpy as np
import pytest
from PyQt6.QtCore import Qt
from pytestqt.qtbot import QtBot

from helab.io_ops import stores
from helab.io_ops.browse import list_folder
from helab.io_ops.loading import load
from helab.io_ops.scanning import scan
from helab.resources.icons import IconsInitUtil, StatusIcons
from helab.utils.folder_cache import FolderCache, get_folder_cache
from helab.utils.io_service import IORequest, IOService
from helab.utils.cache_store import CacheStore
from helab.utils.scan_history import (
    ScanHistory, apply_outcome, begin_scan, empty_history,
    history_tooltip, read_history, write_outcome,
)
from helab.views.FolderExplorer import FolderExplorer


def options_for(tmp_path: Path) -> dict[str, Any]:
    return {"directory": str(tmp_path / "cache")}


def failure(operation: str, revision: int) -> dict[str, Any]:
    return {"operation_id": operation, "revision": revision, "kind": "timeout",
            "at": time.time() - 7200, "attempts": 3, "reason": "I/O timeout (3 attempts)"}


def begin(store: CacheStore, path: str, operation_id: str, revision: int) -> tuple[ScanHistory, int]:
    return begin_scan(store, path, operation_id, revision, store.guard([path], ("histories",)))


def outcome(store: CacheStore, path: str, value: dict[str, Any]) -> ScanHistory:
    return write_outcome(store, path, value, store.guard([path], ("histories",)))


def save_history(store: CacheStore, path: str, record: dict[str, Any]) -> None:
    store.save_record("histories", path, record, store.guard([path], ("histories",)))


def frozen_service(monkeypatch: pytest.MonkeyPatch) -> IOService:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    return service


def producer(cache: FolderCache, path: str, operation: str = "scan") -> IORequest:
    owner = cache.jobs[(operation, path)].owner
    return next(r for r in cache.service.pending if r.owner == owner)


def run_scan(cache: FolderCache, path: str, operation: str = "scan") -> None:
    request = producer(cache, path, operation)
    payload = request.payload

    def send(event: Any) -> None:
        cache.service.resultReady.emit(request, event)
    if operation == "list":
        list_folder(path, send, payload.get("cache"))
    else:
        scan(path, send, payload.get("cache"), manual=payload.get("scan_manual", False),
             automatic=payload.get("automatic", False), operation_id=payload["scan_operation_id"],
             revision=payload["scan_revision"])
    cache.service.resultReady.emit(request, {"kind": "done"})
    cache.service.pending.remove(request)


def browse(qtbot: QtBot, cache: FolderCache, path: str) -> None:
    """List a folder, then run the background details scan that follows."""
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    run_scan(cache, path, "list")
    qtbot.waitUntil(lambda: ("details", path) in cache.jobs)
    run_scan(cache, path, "details")
    # Completed scans reach each tab as a replay of the new snapshot.
    qtbot.waitUntil(lambda: not any(r.path == path for r in cache._deliveries))


def test_retry_history_is_deduplicated_bounded_and_ordered(tmp_path: Path) -> None:
    options = options_for(tmp_path)
    path = str(tmp_path / "unavailable-network-folder")
    with CacheStore(options["directory"]) as cache:
        _, revision = begin(cache, path, "one-job", 100)
        _, retry_revision = begin(cache, path, "one-job", 1)
        assert retry_revision == revision
        first = outcome(cache, path, failure("one-job", revision))
        duplicate = outcome(cache, path, failure("one-job", revision))
        assert len(first["failures"]) == len(duplicate["failures"]) == 1
        assert duplicate["failures"][0]["attempts"] == 3
        # A backwards wall clock cannot place a newer scan before a saved one.
        for i in range(12):
            _, revision = begin(cache, path, f"job-{i}", 1)
            duplicate = outcome(cache, path, failure(f"job-{i}", revision))
        assert len(duplicate["failures"]) == 10
        assert duplicate["failures"][0]["operation_id"] == "job-2"
        _, success_revision = begin(cache, path, "manual-recovery", 1)
        recovered = outcome(cache, path, {"operation_id": "manual-recovery",
            "revision": success_revision, "kind": "success", "at": time.time()})
        late = outcome(cache, path, failure("job-11", revision))
        assert not recovered["blocked"] and not late["blocked"]
        assert late["last_success_at"] == recovered["last_success_at"]
        assert len(late["failures"]) == 10
    with CacheStore(options["directory"]) as restarted:
        restored = read_history(restarted, path)
        assert restored is not None and not restored["blocked"]
        assert "later scan succeeded" in history_tooltip(restored, time.time())


def test_legacy_identity_does_not_reset_blocked_history(tmp_path: Path) -> None:
    old = apply_outcome(empty_history(), failure("old", 10))
    old_record = {**old, "identity": [1, 2]}
    options = options_for(tmp_path)
    with CacheStore(options["directory"]) as cache:
        save_history(cache, "folder", old_record)
        restored = read_history(cache, "folder")
        assert restored is not None and restored["blocked"] and "identity" not in restored
        started, new_revision = begin(cache, "folder", "manual-check", 12)
        assert started["blocked"] and new_revision == 12
        late = outcome(cache, "folder", failure("retired-old", 11))
        assert late["blocked"]


@pytest.mark.parametrize("had_counts", [False, True])
def test_blocked_helper_skips_automatic_check_but_allows_browsing_and_manual_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, had_counts: bool,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "subfolder").mkdir()
    (source / "d_txy_forc1.txt").write_text("1,2,3\n")
    path, options = str(source), options_for(tmp_path)
    if had_counts:
        scan(path, lambda e: None, options, revision=10)
    with stores._cache_store(options["directory"], [path]) as cache:
        outcome(cache, path, failure("failed", 11))
        previous = cache.read_record("summaries", path).value
    events: list[Any] = []
    with monkeypatch.context() as blocked:
        blocked.setattr("helab.io_ops.scanning._scan", lambda *a, **k: pytest.fail("Automatic check touched source"))
        scan(path, events.append, options, manual=False, automatic=True)
        assert {"kind": "scan_mode", "mode": "skipped"} in events
        events.clear()
        # Browse step 2 (details) is skipped too; step 1 still lists the folder.
        scan(path, events.append, options, manual=False)
        assert {"kind": "scan_mode", "mode": "skipped"} in events
    events.clear()
    list_folder(path, events.append, options)
    assert any(e["kind"] == "entries" for e in events)
    status = next(e for e in events if e["kind"] == "status")
    assert not status["details"] and "signature" not in status
    with stores._cache_store(options["directory"], [path]) as cache:
        history = read_history(cache, path)
        assert history is not None and history["blocked"]
        assert cache.read_record("summaries", path).value == previous
    events.clear()
    scan(path, events.append, options, manual=True, revision=12)
    assert any(e["kind"] == "status" for e in events)
    with stores._cache_store(options["directory"], [path]) as cache:
        history = read_history(cache, path)
        assert history is not None and not history["blocked"] and len(history["failures"]) == 1


def test_unknown_metadata_does_not_auto_check_and_manual_scan_repairs_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    path, options = str(source), options_for(tmp_path)
    with stores._cache_store(options["directory"], [path]) as cache:
        save_history(cache, path, {"version": "corrupt"})
    with monkeypatch.context() as blocked:
        blocked.setattr("helab.io_ops.scanning._scan", lambda *a, **k: pytest.fail("Unknown metadata touched source"))
        scan(path, lambda e: None, options, manual=False, automatic=True)
    scan(path, lambda e: None, options, manual=True)
    with stores._cache_store(options["directory"], [path]) as cache:
        history = read_history(cache, path)
        assert history is not None and not history["blocked"] and history["last_success_at"] is not None


def test_final_timeout_counts_once_across_tabs_and_saves_without_source_io(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = frozen_service(monkeypatch)
    cache = get_folder_cache(service)
    path, options = str(tmp_path / "unavailable-folder"), options_for(tmp_path)
    assert cache.submit("tab-one", 0, path, "scan", {"cache": options}, force=True)
    assert cache.submit("tab-two", 0, path, "scan", {"cache": options}, force=True)
    request = producer(cache, path)
    # A scan makes one attempt: 60 s without progress is one failure.
    error = {"kind": "error", "attempt": 1, "timeout": True,
             "message": "Timed out after 60 s without progress — Retry"}
    service.resultReady.emit(request, error)
    service.resultReady.emit(request, error)  # Stale/duplicate final event.
    history = cache.scan_history(path)
    assert history["blocked"] and len(history["failures"]) == 1
    recorded = history["failures"][0]
    assert recorded["operation_id"] == request.owner and recorded["attempts"] == 1
    assert recorded["reason"] == "Timed out after 60 s without progress"
    tooltip = history_tooltip(history, time.time())
    assert "· Timed out after 60 s without progress" in tooltip and "attempt" not in tooltip
    service.pending.remove(request)
    writes = [r for r in service.pending if r.operation == "scan_history"]
    assert len(writes) == 1
    writer = writes[0]
    # The folder does not exist: persistence must access only the local cache.
    with CacheStore(options["directory"]) as disk:
        saved = outcome(disk, path, writer.payload["outcome"])
    service.resultReady.emit(writer, {"kind": "scan_history_saved", "history": saved})
    service.resultReady.emit(writer, {"kind": "done"})
    assert not cache.scan_history_errors
    assert not cache._history_writes
    service.shutdown()


@pytest.mark.parametrize("event", ["cancelled", "metadata-timeout", "save-timeout"])
def test_cancellation_and_metadata_errors_are_not_scan_failures(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, event: str,
) -> None:
    service = frozen_service(monkeypatch)
    cache = get_folder_cache(service)
    path = str(tmp_path)
    cache.submit("tab", 0, path, "scan", {"cache": options_for(tmp_path)}, force=True)
    request = producer(cache, path)
    if event == "metadata-timeout":
        service.resultReady.emit(request, {"kind": "scan_mode", "mode": "metadata"})
    if event == "save-timeout":
        service.resultReady.emit(request, {"kind": "status", "status": "ok", "count": 1,
            "txy": [1], "raw": [1], "scanned_at": time.time(), "signature": "ok"})
    service.resultReady.emit(request, {"kind": "cancelled" if event == "cancelled" else "error",
        "timeout": True, "attempt": 1, "message": "Timed out after 60 s without progress — Retry"})
    assert not cache.scan_history(path)["blocked"]
    assert not cache.scan_history(path)["failures"]
    if event == "save-timeout":
        snapshot = cache.snapshot(path)
        assert snapshot is not None and snapshot.status["count"] == 1
        assert "metadata failed" in cache.scan_history_errors[path]
    service.shutdown()


def test_save_failure_keeps_session_suppression_and_warns_without_another_failure(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = frozen_service(monkeypatch)
    cache, path = get_folder_cache(service), str(tmp_path)
    cache.submit("tab", 0, path, "scan", {"cache": options_for(tmp_path)}, force=True)
    request = producer(cache, path)
    service.resultReady.emit(request, {"kind": "error", "message": "Permission denied"})
    writer = next(r for r in service.pending if r.operation == "scan_history")
    service.resultReady.emit(writer, {"kind": "error", "message": "Cache unavailable"})
    assert cache.scan_history(path)["blocked"] and len(cache.scan_history(path)["failures"]) == 1
    assert "session-only" in cache.scan_history_errors[path]
    service.shutdown()


@pytest.mark.parametrize("had_counts", [False, True])
def test_visible_folder_restores_failure_before_selection_load_and_manual_recovery(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, had_counts: bool,
) -> None:
    IconsInitUtil.initialise_icons()
    root, child = tmp_path / "source", tmp_path / "source" / "run"
    child.mkdir(parents=True)
    (child / "d_txy_forc1.txt").write_text("1,2,3\n")
    service = frozen_service(monkeypatch)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    monkeypatch.setattr("helab.utils.constants._cache_dir_state", [str(tmp_path / "caches"), "", True])
    explorer = FolderExplorer(str(root), str(root), str(root), [0, 4, 5])
    qtbot.addWidget(explorer)
    cache, path = explorer.model.cache, str(child)
    options = explorer.model._cache_options
    monkeypatch.setattr(explorer, "_load_payload", lambda p, deliberate=False: {
        "cache": options, "signature": explorer.model.nodes[p].signature})
    if had_counts:
        scan(path, lambda e: None, options, revision=10)
    with stores._cache_store(options["directory"], [path]) as disk:
        outcome(disk, path, failure("saved-failure", 11))
    browse(qtbot, cache, str(root))
    qtbot.waitUntil(lambda: path in explorer.model.nodes)
    node = explorer.model.nodes[path]
    # Without a saved summary the count stays unknown (no report), not zero files found.
    assert (node.report is None, node.txy_count) == ((False, 1) if had_counts else (True, 0))
    assert cache.scan_history(path)["blocked"]  # Restored before clicking this row.
    explorer.resize(550, 350)
    explorer.show()
    qtbot.wait(20)
    for _ in range(2):
        explorer.set_auto_scan_visible(False)
        explorer.set_auto_scan_visible(True)
        explorer._check_visible_folders()
        assert ("scan", path) not in cache.jobs
    explorer.model.request_scan(path, metadata_only=True)
    qtbot.waitUntil(lambda: not cache.has_request(explorer.model.owner, "scan", path))
    assert ("scan", path) not in cache.jobs and cache.scan_history(path)["blocked"]
    # Explicit data loading is possible even when the basic count is unknown.
    explorer.selected_path_globally = path
    assert explorer.queue_load(path) and explorer._load_path == path
    request = producer(cache, path, "load")
    output = tmp_path / "artifacts"
    output.mkdir()

    def send_load(event: Any) -> None:
        if event["kind"] == "shot":
            event = {**event, "array": np.load(event["artifact"])}
        service.resultReady.emit(request, event)
    load(path, str(output), send_load, options)
    service.resultReady.emit(request, {"kind": "done"})
    service.pending.remove(request)
    assert cache.current_dataset(path) is not None and cache.scan_history(path)["blocked"]
    explorer._update_activity()
    assert explorer.folder_freshness_label.text() == "Folder status check failed 2h ago · Retry manually"
    assert "3 attempts" in explorer.folder_freshness_label.toolTip()  # Recorded before single attempts.
    assert "1 loaded" in explorer.folder_summary_label.text()
    assert datetime_date(cache.scan_history(path)["failures"][0]["failed_at"]) in explorer.folder_freshness_label.toolTip()
    # Badges/tooltips and relative ages never read the disk cache or source FS.
    with monkeypatch.context() as render:
        render.setattr("os.stat", lambda *a, **k: pytest.fail("Rendering called stat"))
        render.setattr("os.scandir", lambda *a, **k: pytest.fail("Rendering called scandir"))
        render.setattr(service, "submit", lambda *a, **k: pytest.fail("Rendering submitted I/O"))
        index = explorer.model.path_index(path)
        extras = explorer.model.data(index, explorer.model.STATUS_EXTRA_ICONS_ROLE)
        tooltip = explorer.model.data(index, int(Qt.ItemDataRole.ToolTipRole))
        assert isinstance(extras, list) and StatusIcons.ICON_SCAN_FAILED in extras
        assert isinstance(tooltip, str) and "Automatic folder status checks are skipped" in tooltip
        explorer._update_activity()
    explorer.deep_timer.stop()
    explorer.context_menu_action_deep_calc_status(path)
    explorer._dispatch_deep()
    run_scan(cache, path)
    qtbot.waitUntil(lambda: not cache.scan_history(path)["blocked"])
    assert len(cache.scan_history(path)["failures"]) == 1
    extras = explorer.model.data(explorer.model.path_index(path), explorer.model.STATUS_EXTRA_ICONS_ROLE)
    assert isinstance(extras, list) and StatusIcons.ICON_SCAN_FAILED not in extras
    explorer.close_cleanup()
    service.shutdown()


def datetime_date(timestamp: float) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(timestamp).astimezone().strftime("%Y-%m-%d")


def test_late_history_cannot_restore_old_folder_failure(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = frozen_service(monkeypatch)
    cache, path = get_folder_cache(service), str(tmp_path)
    old = apply_outcome(empty_history(), failure("old", 10))
    cache.remember_history(path, {**old, "identity": [1, 2]})
    assert cache.scan_history(path)["blocked"]
    recovered = apply_outcome(old, {"operation_id": "recovered", "revision": 12,
                                   "kind": "success", "at": time.time()})
    cache.remember_history(path, recovered)
    cache.remember_history(path, {**old, "identity": [1, 3]})
    cache.remember_history(path, apply_outcome(old, failure("old-writer", 11)))
    assert not cache.scan_history(path)["blocked"] and cache.scan_history(path)["revision"] == 12
    service.shutdown()


def test_failure_badge_replaces_unavailable_text_and_cancelled_text_follows_badges(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QPainter, QPixmap
    from PyQt6.QtWidgets import QStyleOptionViewItem
    IconsInitUtil.initialise_icons()
    root, child = tmp_path / "source", tmp_path / "source" / "run"
    child.mkdir(parents=True)
    service = frozen_service(monkeypatch)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    explorer = FolderExplorer(str(root), str(root), str(root), [0, 4, 5])
    qtbot.addWidget(explorer)
    cache, model, path = explorer.model.cache, explorer.model, str(child)
    browse(qtbot, cache, str(root))
    qtbot.waitUntil(lambda: path in model.nodes)
    node = model.nodes[path]
    node.state, node.error = "error", "Request timed out after 3 attempts — Retry"
    index = model.path_index(path).siblingAtColumn(model.COLUMN_STATUS_ICON)
    display = int(Qt.ItemDataRole.DisplayRole)
    assert model.data(index, display) == "Unavailable"  # Session error without a saved failure.
    cache.remember_history(path, apply_outcome(empty_history(), failure("timed-out", 5)))
    assert model.data(index, display) == ""
    tooltip = model.data(index, int(Qt.ItemDataRole.ToolTipRole))
    assert isinstance(tooltip, str) and node.error.removesuffix(" — Retry") in tooltip
    assert "Automatic folder status checks are skipped" in tooltip
    node.state = "cancelled"  # A cancelled manual retry keeps its text beside the badge.
    assert model.data(index, display) == "Cancelled"
    pixmap = QPixmap(150, 20)
    painter = QPainter(pixmap)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 150, 20)
    explorer.delegate.paint(painter, option, index)
    painter.end()
    explorer.close_cleanup()
    service.shutdown()
