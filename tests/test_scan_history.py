from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from diskcache import FanoutCache
import numpy as np
import pytest
from PyQt6.QtCore import Qt
from pytestqt.qtbot import QtBot

from helab.io_helper import list_folder, load, scan
from helab.resources.icons import IconsInitUtil, StatusIcons
from helab.utils.folder_cache import FolderCache, get_folder_cache
from helab.utils.io_service import IORequest, IOService
from helab.utils.scan_history import (
    HISTORY_KEY, apply_outcome, begin_scan, empty_history, for_identity,
    history_tooltip, read_history, write_outcome,
)
from helab.views.FolderExplorer import FolderExplorer


def options_for(tmp_path: Path) -> dict[str, Any]:
    return {"directory": str(tmp_path / "cache"), "params": {"shards": 2}}


def failure(operation: str, revision: int, *, identity: list[int] | None = None) -> dict[str, Any]:
    return {"operation_id": operation, "revision": revision, "kind": "timeout",
            "at": time.time() - 7200, "attempts": 3, "reason": "I/O timeout (3 attempts)",
            "identity": identity}


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

    def send(event: dict[str, Any]) -> None:
        cache.service.resultReady.emit(request, event)
    if operation == "list":
        list_folder(path, send, payload.get("cache"), identity=payload.get("identity"))
    else:
        scan(path, send, payload.get("cache"), manual=payload.get("scan_manual", False),
             automatic=payload.get("automatic", False), operation_id=payload["scan_operation_id"],
             revision=payload["scan_revision"], identity=payload.get("identity"))
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
    with FanoutCache(options["directory"], **options["params"]) as cache:
        _, revision = begin_scan(cache, path, "one-job", 100)
        _, retry_revision = begin_scan(cache, path, "one-job", 1)
        assert retry_revision == revision
        first = write_outcome(cache, path, failure("one-job", revision))
        duplicate = write_outcome(cache, path, failure("one-job", revision))
        assert len(first["failures"]) == len(duplicate["failures"]) == 1
        assert duplicate["failures"][0]["attempts"] == 3
        # A backwards wall clock cannot place a newer scan before a saved one.
        for i in range(12):
            _, revision = begin_scan(cache, path, f"job-{i}", 1)
            duplicate = write_outcome(cache, path, failure(f"job-{i}", revision))
        assert len(duplicate["failures"]) == 10
        assert duplicate["failures"][0]["operation_id"] == "job-2"
        _, success_revision = begin_scan(cache, path, "manual-recovery", 1)
        recovered = write_outcome(cache, path, {"operation_id": "manual-recovery",
            "revision": success_revision, "kind": "success", "at": time.time()})
        late = write_outcome(cache, path, failure("job-11", revision))
        assert not recovered["blocked"] and not late["blocked"]
        assert late["last_success_at"] == recovered["last_success_at"]
        assert len(late["failures"]) == 10
    with FanoutCache(options["directory"], **options["params"]) as restarted:
        restored = read_history(restarted, path)
        assert restored is not None and not restored["blocked"]
        assert "later scan succeeded" in history_tooltip(restored, time.time())


def test_folder_replacement_rejects_old_outcomes(tmp_path: Path) -> None:
    old = apply_outcome(empty_history(), failure("old", 10, identity=[1, 2]))
    replaced = for_identity(old, [1, 3])
    assert not replaced["blocked"] and not replaced["failures"]
    assert apply_outcome(replaced, failure("late-old", 10, identity=[1, 2])) == replaced
    options = options_for(tmp_path)
    with FanoutCache(options["directory"], **options["params"]) as cache:
        cache.set((HISTORY_KEY, "folder"), old)
        started, new_revision = begin_scan(cache, "folder", "replacement", 12, [1, 3])
        late = write_outcome(cache, "folder", failure("retired-old", 11, identity=[1, 2]))
        assert late == started and new_revision == 12


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
    with FanoutCache(options["directory"], **options["params"]) as cache:
        write_outcome(cache, path, failure("failed", 11))
        previous = cache.get(("folder-scan-v1", path))
    events: list[dict[str, Any]] = []
    with monkeypatch.context() as blocked:
        blocked.setattr("helab.io_helper._scan", lambda *a, **k: pytest.fail("Automatic check touched source"))
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
    with FanoutCache(options["directory"], **options["params"]) as cache:
        history = read_history(cache, path)
        assert history is not None and history["blocked"]
        assert cache.get(("folder-scan-v1", path)) == previous
    events.clear()
    scan(path, events.append, options, manual=True, revision=12)
    assert any(e["kind"] == "status" for e in events)
    with FanoutCache(options["directory"], **options["params"]) as cache:
        history = read_history(cache, path)
        assert history is not None and not history["blocked"] and len(history["failures"]) == 1


def test_unknown_metadata_does_not_auto_check_and_manual_scan_repairs_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    path, options = str(source), options_for(tmp_path)
    with FanoutCache(options["directory"], **options["params"]) as cache:
        cache.set((HISTORY_KEY, path), {"version": "corrupt"})
    with monkeypatch.context() as blocked:
        blocked.setattr("helab.io_helper._scan", lambda *a, **k: pytest.fail("Unknown metadata touched source"))
        scan(path, lambda e: None, options, manual=False, automatic=True)
    scan(path, lambda e: None, options, manual=True)
    with FanoutCache(options["directory"], **options["params"]) as cache:
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
    with FanoutCache(options["directory"], **options["params"]) as disk:
        saved = write_outcome(disk, path, writer.payload["outcome"])
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
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.DIR_CACHES", str(tmp_path / "caches"))
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.load_cache_param", lambda _: {"shards": 2})
    explorer = FolderExplorer(str(root), str(root), str(root), [0, 4, 5])
    qtbot.addWidget(explorer)
    cache, path = explorer.model.cache, str(child)
    options = explorer.model._cache_options
    monkeypatch.setattr(explorer, "_load_payload", lambda p: {"cache": options, "signature": explorer.model.nodes[p].signature})
    if had_counts:
        scan(path, lambda e: None, options, revision=10)
    stat = child.stat()
    with FanoutCache(options["directory"], **options["params"]) as disk:
        write_outcome(disk, path, failure("saved-failure", 11, identity=[stat.st_dev, stat.st_ino]))
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

    def send_load(event: dict[str, Any]) -> None:
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


def test_identity_observations_and_late_writer_cannot_restore_old_folder_failure(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = frozen_service(monkeypatch)
    cache, path = get_folder_cache(service), str(tmp_path)
    old = apply_outcome(empty_history(), failure("old", 10, identity=[1, 2]))
    cache.remember_history(path, old, identity=[1, 2], observed_at=100)
    cache.remember_history(path, old, identity=[1, 3], observed_at=200)
    assert not cache.scan_history(path)["blocked"]
    cache.remember_history(path, old, identity=[1, 2], observed_at=150)
    cache.remember_history(path, apply_outcome(old, failure("old-writer", 11, identity=[1, 2])))
    assert not cache.scan_history(path)["blocked"] and cache.scan_history(path)["identity"] == [1, 3]
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
    assert isinstance(tooltip, str) and node.error in tooltip and "Automatic folder status checks are skipped" in tooltip
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
