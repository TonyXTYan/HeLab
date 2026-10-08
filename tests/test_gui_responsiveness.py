from __future__ import annotations

import math
import os
import io
from pathlib import Path
import subprocess
import threading
import sys
import time
from typing import Any

import numpy as np
import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QTreeView

from helab.io_helper import load, scan
from helab.models.SnapshotFileSystemModel import SnapshotFileSystemModel
from helab.utils.io_service import IORequest, IOService
from helab.views.FolderExplorer import FolderExplorer


def frozen_service(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> IOService:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    return service


def deliver(service: IOService, model: SnapshotFileSystemModel, path: str, event: dict[str, Any]) -> None:
    request = IORequest(model.owner, model.generation, path, "scan", {}, 15.0)
    service.resultReady.emit(request, {"kind": "queued"})
    service.resultReady.emit(request, event)


def test_scan_matches_shots_without_probing_children(tmp_path: Path) -> None:
    (tmp_path / "experiment").mkdir()
    (tmp_path / "d1.txt").write_text("")
    (tmp_path / "d2.txt").write_text("")
    (tmp_path / "d_txy_forc1.txt").write_text("1,2,3\n")
    events: list[dict[str, Any]] = []
    scan(str(tmp_path), events.append)
    assert events[-1]["status"] == "fixable"
    assert events[-1]["count"] == 1
    assert events[-1]["raw"] == [1, 2]
    entries = next(event for event in events if event["kind"] == "entries")
    assert entries["entries"][0]["path"] == str(tmp_path / "experiment")


def test_loader_preserves_shots_and_drops_nan_rows(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    source.mkdir()
    output.mkdir()
    (source / "d_txy_forc7.txt").write_text("1,2,3\n4,,6\n")
    events: list[dict[str, Any]] = []
    load(str(source), str(output), events.append)
    shot = next(event for event in events if event["kind"] == "shot")
    np.testing.assert_array_equal(np.load(shot["artifact"]), [[1, 2, 3]])
    assert events[-1]["problematic"] == [7]
    assert events[-1]["rows"] == 1


def test_compressed_cache_is_reused_and_validated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pandas as pd
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    (source / "d_txy_forc7.txt").write_text("1,2,3\n")
    options = {"directory": str(tmp_path / "cache"), "params": {"shards": 2}}
    events: list[dict[str, Any]] = []
    load(str(source), str(output), events.append, options)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Unchanged source was parsed instead of using cache")

    monkeypatch.setattr(pd, "read_csv", forbidden)
    events.clear()
    load(str(source), str(output), events.append, options)
    assert events[-1]["kind"] == "loaded"
    shot = next(event for event in events if event["kind"] == "shot")
    np.testing.assert_array_equal(np.load(shot["artifact"]), [[1, 2, 3]])


def test_rendering_never_reads_filesystem_or_disk_cache(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = frozen_service(qtbot, monkeypatch)
    model = SnapshotFileSystemModel(service=service)
    index = model.setRootPath(str(tmp_path))
    model.cache._set_disk_cached(str(tmp_path), True)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("GUI rendering performed I/O")

    monkeypatch.setattr(os, "scandir", forbidden)
    monkeypatch.setattr(os, "stat", forbidden)
    from helab.utils.caching_setup import status_cache
    monkeypatch.setattr(status_cache, "get", forbidden)
    from diskcache import FanoutCache
    monkeypatch.setattr(FanoutCache, "get", forbidden)
    monkeypatch.setattr(FanoutCache, "__contains__", forbidden)
    for role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.DecorationRole,
                 Qt.ItemDataRole.ToolTipRole, Qt.ItemDataRole.ForegroundRole,
                 model.STATUS_EXTRA_ICONS_ROLE):
        for column in range(7):
            model.data(model.index(0, column), int(role))
    assert model.hasChildren(index)
    assert model.fetch_status(str(tmp_path)).status == "loading"
    assert len(service.pending) == 1  # Painting did not launch more work.
    model.close_cleanup()
    service.shutdown()


def test_scope_and_stale_results(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service = frozen_service(qtbot, monkeypatch)
    model = SnapshotFileSystemModel(service=service)
    view = QTreeView()
    qtbot.addWidget(view)
    view.setModel(model)
    model.view = view
    root = str(tmp_path)
    child, grandchild = str(tmp_path / "child"), str(tmp_path / "child" / "grandchild")
    view.setRootIndex(model.setRootPath(root))
    deliver(service, model, root, {"kind": "entries", "entries": [{"path": child, "modified": None}]})
    deliver(service, model, child, {"kind": "entries", "entries": [{"path": grandchild, "modified": None}]})
    assert grandchild not in [path for _, path in model.get_visible_rows()]
    view.expand(model.path_index(child))
    assert grandchild in [path for _, path in model.get_visible_rows()]
    old = IORequest(model.owner, model.generation, root, "scan", {}, 15)
    model.setRootPath(str(tmp_path / "other"))
    service.resultReady.emit(old, {"kind": "entries", "entries": [{"path": child, "modified": None}]})
    assert child not in model.nodes
    model.close_cleanup()
    service.shutdown()


def test_helpers_send_heartbeats_while_listing_and_checking_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from helab import io_helper
    monkeypatch.setattr(io_helper.Heartbeat, "INTERVAL", 0.0)
    source = tmp_path / "source"
    source.mkdir()
    for shot in (1, 2, 3):
        (source / f"d_txy_forc{shot}.txt").write_text("1,2,3\n")
    events: list[dict[str, Any]] = []
    scan(str(source), events.append)
    assert [(e["phase"], e["entries"]) for e in events if e["kind"] == "heartbeat"] == [
        ("listing", 1), ("listing", 2), ("listing", 3)]
    events.clear()
    output = tmp_path / "output"
    output.mkdir()
    load(str(source), str(output), events.append)
    beats = [(e["phase"], e["entries"]) for e in events if e["kind"] == "heartbeat"]
    assert beats == [(phase, count) for phase in ("listing", "checking", "verifying") for count in (1, 2, 3)]
    # Listing and stat heartbeats arrive before the first file's read timer starts.
    kinds = [e.get("phase", e["kind"]) for e in events]
    assert kinds.index("file_started") > max(i for i, k in enumerate(kinds) if k == "checking")


def test_stalled_process_keeps_heartbeat_and_shutdown_responsive(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = subprocess.Popen

    def stalled(command: Any, **kwargs: Any) -> subprocess.Popen[str]:
        return original([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)

    monkeypatch.setattr(subprocess, "Popen", stalled)
    service = IOService()
    events: list[dict[str, Any]] = []
    service.resultReady.connect(lambda request, event: events.append(event))
    beats: list[float] = []
    timer = QTimer()
    timer.timeout.connect(lambda: beats.append(time.monotonic()))
    timer.start(20)
    assert service.submit("test", 0, "/unresponsive", "scan", timeout=0.15)
    assert service.submit("test", 0, "/unresponsive", "scan", timeout=0.15)
    assert len(service.active) == 1  # Duplicate requests coalesce.
    qtbot.waitUntil(lambda: any(e.get("timeout") for e in events), timeout=3000)
    # A stalled listing makes one attempt; retries did not help a hung volume.
    assert [e["attempt"] for e in events if e["kind"] == "started"] == [1]
    errors = [e for e in events if e["kind"] == "error"]
    assert len(errors) == 1 and "without progress" in errors[0]["message"]
    assert len(beats) >= 3
    assert max(b - a for a, b in zip(beats, beats[1:])) < 0.2
    qtbot.waitUntil(lambda: not service.retired, timeout=3000)
    timer.stop()
    start = time.monotonic()
    service.shutdown()
    assert time.monotonic() - start < 0.2


@pytest.mark.parametrize("limit", [1, 2])
def test_timeout_retry_releases_dead_helper_slot_while_artifact_reader_is_blocked(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, limit: int,
) -> None:
    import json

    artifact = tmp_path / "shot.npy"
    np.save(artifact, np.array([[1.0, 2.0, 3.0]]))
    reading, release_reader = threading.Event(), threading.Event()
    original_load, original_process = np.load, subprocess.Popen
    processes: list[subprocess.Popen[str]] = []

    def blocked_read(*args: Any, **kwargs: Any) -> Any:
        reading.set()
        if not release_reader.wait(5):
            raise AssertionError("Artifact reader was not released")
        return original_load(*args, **kwargs)

    def helper(command: Any, **kwargs: Any) -> subprocess.Popen[str]:
        script = "import time; time.sleep(60)"
        if not processes:
            started = json.dumps({"kind": "file_started", "filename": "/slow-reader/d_txy_forc1.txt"})
            event = json.dumps({"kind": "shot", "shot": 1, "artifact": str(artifact)})
            script = f"import time; print({started!r}); print({event!r}, flush=True); time.sleep(60)"
        process = original_process([sys.executable, "-c", script], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(np, "load", blocked_read)
    monkeypatch.setattr(subprocess, "Popen", helper)
    service = IOService()
    started: list[IORequest] = []
    service.resultReady.connect(lambda r, e: started.append(r) if e["kind"] == "started" else None)
    try:
        service.submit("tab", 0, "/slow-reader", "load")
        qtbot.waitUntil(reading.is_set, timeout=3000)
        old = service.active[0]
        qtbot.waitUntil(lambda: old.current_file is not None, timeout=3000)
        old.started = old.last_activity = time.monotonic() - old.timeout - 1
        service._tick()
        service.configure_concurrency(limit)
        # The process is killed, but the daemon reader is still in np.load.
        # Waiting for that reader's finally block used to strand this retry.
        qtbot.waitUntil(lambda: len(started) == 2, timeout=1500)
        retry = started[1]
        assert processes[0].poll() is not None
        assert not release_reader.is_set() and old.output is not None
        assert retry.attempt == 2 and service.active == [retry]
        assert not service.pending and not service.retired
        release_reader.set()
        qtbot.waitUntil(lambda: old.output is None, timeout=3000)
        service._tick()
        assert service.active == [retry]  # Late old-reader exit is harmless.
    finally:
        release_reader.set()
        service.shutdown()
        qtbot.waitUntil(lambda: all(p.poll() is not None for p in processes), timeout=3000)


def test_output_close_failure_cannot_leave_dead_helper_in_active_queue(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    class BrokenClose(io.StringIO):
        def close(self) -> None:
            if not self.closed:
                super().close()
                raise OSError("Output cleanup failed")

    original_process = subprocess.Popen
    processes: list[subprocess.Popen[str]] = []

    def helper(command: Any, **kwargs: Any) -> subprocess.Popen[str]:
        process = original_process([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
        assert process.stdout is not None
        process.stdout.close()
        stream = BrokenClose if not processes else io.StringIO
        process.stdout = stream('{"kind":"done"}\n')
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", helper)
    service = IOService()
    done: list[str] = []
    service.resultReady.connect(lambda r, e: done.append(r.path) if e["kind"] == "done" else None)
    try:
        service.submit("first-tab", 0, "/first", "scan")
        service.submit("second-tab", 0, "/second", "scan")
        qtbot.waitUntil(lambda: done == ["/first", "/second"] and not service.active, timeout=3000)
        assert not service.pending and not service.retired
        assert "Could not close I/O helper output" in caplog.text
    finally:
        service.shutdown()
        qtbot.waitUntil(lambda: all(p.poll() is not None for p in processes), timeout=3000)


def test_pending_queue_is_bounded(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    service = frozen_service(qtbot, monkeypatch)
    for index in range(service.MAX_PENDING):
        assert service.submit("test", 0, f"/folder-{index}", "scan")
    assert not service.submit("test", 0, "/overflow", "scan")
    assert len(service.pending) == service.MAX_PENDING
    service.cancel("test")
    assert not service.pending
    service.shutdown()


@pytest.mark.parametrize("operation", ["scan", "resolve", "load"])
def test_stalled_listing_times_out_once_after_no_progress(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_run", lambda request: None)
    events: list[dict[str, Any]] = []
    service.resultReady.connect(lambda request, event: events.append(event))
    service.submit("tab", 0, "/slow", operation)
    request = service.active[0]
    assert request.timeout == service.NO_PROGRESS_TIMEOUT == 60.0
    # A slow listing that keeps reporting entries never times out.
    for entries in (1000, 2000, 3000):
        request.last_activity = time.monotonic() - 59
        service.messages.put((request, {"kind": "heartbeat", "phase": "listing", "entries": entries}))
        service._tick()
        assert service.active == [request] and not request.cancelled.is_set()
    request.started = time.monotonic() - 600
    request.last_activity = time.monotonic() - 61
    service._tick()
    assert request.cancelled.is_set() and request in service.retired
    assert not service.pending  # No retry: retries did not help a hung volume.
    errors = [event for event in events if event["kind"] == "error"]
    assert len(errors) == 1 and errors[0]["timeout"] and errors[0]["attempt"] == 1
    assert errors[0]["message"] == "Timed out after 60 s without progress — Retry"
    service.shutdown()


def test_no_timeout_request_runs_until_cancelled(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_run", lambda request: None)
    events: list[dict[str, Any]] = []
    service.resultReady.connect(lambda request, event: events.append(event))
    service.submit("tab", 0, "/hung", "scan")
    request = service.active[0]
    service.set_timeout("tab", math.inf)
    request.started = request.last_activity = time.monotonic() - 3600
    service._tick()
    assert service.active == [request] and not any(event["kind"] == "error" for event in events)
    service.cancel("tab")
    assert request.cancelled.is_set() and request in service.retired
    assert [event["kind"] for event in events][-1] == "cancelled"
    service.shutdown()


def test_load_file_retries_use_three_deadlines_and_ignore_old_attempts(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_run", lambda request: None)
    events: list[dict[str, Any]] = []
    service.resultReady.connect(lambda request, event: events.append(event))
    service.submit("tab", 0, "/slow", "load")
    for attempt, timeout in enumerate((15.0, 20.0, 30.0), 1):
        request = service.active[0]
        # Each attempt lists the folder under the no-progress limit first.
        assert (request.attempt, request.timeout) == (attempt, service.NO_PROGRESS_TIMEOUT)
        service.messages.put((request, {"kind": "file_started", "filename": "/slow/d_txy_forc1.txt"}))
        service._tick()
        assert (request.attempt, request.timeout) == (attempt, timeout)
        request.started = request.last_activity = time.monotonic() - timeout - 1
        service._tick()
        assert request.cancelled.is_set()
        if attempt < 3:
            assert not any(e["kind"] == "error" for e in events)
            retry = service.pending[0]
            assert retry.started == 0
            service._tick()
            assert not service.active  # Wait for the previous helper to exit.
            service.messages.put((request, {"kind": "done", "stale": True}))
            service.messages.put((request, {"kind": "exit"}))
            service._tick()
            assert service.active == [retry]
        else:
            assert not service.pending
            assert not service.active
    errors = [event for event in events if event["kind"] == "error"]
    assert len(errors) == 1 and errors[0]["attempt"] == 3 and errors[0]["timeout"]
    assert errors[0]["message"] == "File timed out after 3 attempts: d_txy_forc1.txt — Retry"
    assert not any(event.get("stale") for event in events)
    service.shutdown()


@pytest.mark.parametrize("stop", ["cancel", "shutdown"])
def test_stopping_a_timeout_retry_prevents_restart(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, stop: str,
) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_run", lambda request: None)
    service.submit("tab", 0, "/slow", "load")
    request = service.active[0]
    service.messages.put((request, {"kind": "file_started", "filename": "/slow/d_txy_forc1.txt"}))
    service._tick()
    request.started = request.last_activity = time.monotonic() - request.timeout - 1
    service._tick()
    assert len(service.pending) == 1
    if stop == "cancel":
        service.cancel("tab")
    else:
        service.shutdown()
    service.messages.put((request, {"kind": "exit"}))
    service._tick()
    assert not service.pending and not service.active
    service.shutdown()


@pytest.mark.parametrize("kind", ["loaded", "resolved", "done", "error"])
def test_completed_results_are_not_retried_when_helper_cleanup_times_out(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, kind: str,
) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_run", lambda request: None)
    events: list[dict[str, Any]] = []
    service.resultReady.connect(lambda request, event: events.append(event))
    service.submit("tab", 0, "/folder", "load")
    request = service.active[0]
    request.started = request.last_activity = time.monotonic() - request.timeout - 1
    service.messages.put((request, {"kind": kind}))
    service._tick()
    # Writing the disk cache after completion gets the longer finishing deadline.
    assert service.active == [request] and request.timeout == service.FINISH_TIMEOUT
    request.last_activity = time.monotonic() - service.FINISH_TIMEOUT - 1
    service._tick()
    assert not service.pending and not service.active
    assert request in service.retired
    assert not any(event.get("retry") or event.get("timeout") for event in events)
    service.shutdown()


def test_full_queue_reserves_space_for_automatic_retry(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_run", lambda request: None)
    service.submit("tab", 0, "/slow", "load")
    request = service.active[0]
    service.messages.put((request, {"kind": "file_started", "filename": "/slow/d_txy_forc1.txt"}))
    service._tick()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    for index in range(service.MAX_PENDING - 1):
        assert service.submit("other", 0, f"/folder-{index}", "load")
    assert not service.submit("other", 0, "/overflow", "load")
    request.started = request.last_activity = time.monotonic() - request.timeout - 1
    service._tick()
    assert len(service.pending) == service.MAX_PENDING
    assert service.pending[0].attempt == 2
    service.shutdown()


def test_folder_can_load_longer_than_five_minutes_with_file_progress(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_run", lambda request: None)
    service.submit("tab", 0, "/large", "load")
    request = service.active[0]
    request.started = time.monotonic() - 600
    for filename in ("first.txt", "second.txt", "third.txt"):
        service.messages.put((request, {"kind": "file_started", "filename": filename}))
        service._tick()
        assert service.active == [request] and request.attempt == 1
        service.messages.put((request, {"kind": "file_finished", "filename": filename}))
        service._tick()
        assert service.active == [request] and not service.pending
    # A repeated percentage without file progress must not hide a stalled file.
    service.messages.put((request, {"kind": "file_started", "filename": "stalled.txt"}))
    service._tick()
    request.last_activity = time.monotonic() - 16
    service.messages.put((request, {"kind": "progress", "progress": 0.5}))
    service._tick()
    assert service.pending[0].attempt == 2
    service.shutdown()


@pytest.mark.parametrize("succeeds", [False, True])
def test_file_has_three_attempts_and_next_file_gets_a_fresh_budget(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, succeeds: bool,
) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_run", lambda request: None)
    events: list[dict[str, Any]] = []
    service.resultReady.connect(lambda request, event: events.append(event))
    service.submit("tab", 0, "/folder", "load")
    for attempt, timeout in enumerate((15.0, 20.0, 30.0), 1):
        request = service.active[0]
        # Restarted helpers may first skip files already loaded into RAM.
        service.messages.put((request, {"kind": "file_started", "filename": "/folder/earlier.txt"}))
        service.messages.put((request, {"kind": "file_finished", "filename": "/folder/earlier.txt"}))
        service.messages.put((request, {"kind": "file_started", "filename": "/folder/slow.txt"}))
        service._tick()
        assert (request.attempt, request.timeout) == (attempt, timeout)
        if succeeds and attempt == 3:
            service.messages.put((request, {"kind": "file_finished", "filename": "/folder/slow.txt"}))
            service.messages.put((request, {"kind": "file_started", "filename": "/folder/next.txt"}))
            service._tick()
            assert (request.attempt, request.timeout) == (1, 15.0)
            assert not request.file_attempts
            assert not any(event["kind"] == "error" for event in events)
            break
        request.last_activity = time.monotonic() - timeout - 1
        service._tick()
        if attempt < 3:
            assert not any(event["kind"] == "error" for event in events)
            service.messages.put((request, {"kind": "exit"}))
            service._tick()
        else:
            assert not service.pending and not service.active
            error = next(event for event in events if event["kind"] == "error")
            assert "slow.txt" in error["message"] and error["attempt"] == 3
    service.shutdown()


def test_loads_and_scans_share_one_slot_with_fifo_loads(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_run", lambda request: None)
    assert service.submit("tab-a", 0, "/first", "load", priority=True)
    first = service.active[0]
    assert service.submit("tab-b", 0, "/second", "load", priority=True)
    assert service.submit("tab-c", 0, "/third", "load", priority=True)
    assert service.queued_load_paths() == ["/second", "/third"]
    assert all(request.started == 0 for request in service.pending)
    assert service.submit("browser", 0, "/browse", "scan")
    assert [(r.path, r.operation) for r in service.active] == [("/first", "load")]
    assert service.queued_operations() == [("load", "/second"), ("load", "/third"), ("scan", "/browse")]
    service.messages.put((first, {"kind": "exit"}))
    service._tick()
    assert [r.path for r in service.active if r.operation == "load"] == ["/second"]
    assert service.queued_load_paths() == ["/third"]
    service.cancel("tab-c")
    assert service.queued_load_paths() == []
    service.shutdown()


def test_cancelled_load_keeps_slot_until_helper_exits(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_run", lambda request: None)
    service.submit("tab-a", 0, "/first", "load")
    first = service.active[0]
    service.submit("tab-b", 0, "/second", "load")
    service.cancel("tab-a")
    service._tick()
    assert first in service.retired
    assert not service.active
    assert service.queued_load_paths() == ["/second"]
    service.messages.put((first, {"kind": "exit"}))
    service._tick()
    assert [r.path for r in service.active] == ["/second"]
    service.shutdown()


def test_shared_scan_and_load_limits_change_without_interrupting_work(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_run", lambda request: None)
    try:
        for i in range(4):
            service.submit(f"scan-tab-{i}", 0, f"/scan-{i}", "scan")
            service.submit(f"load-tab-{i}", 0, f"/load-{i}", "load")
        assert [(r.path, r.operation) for r in service.active] == [("/scan-0", "scan")]
        service.configure_concurrency(5)
        assert sum(r.operation == "scan" for r in service.active) == 1
        assert sum(r.operation == "load" for r in service.active) == 4
        running = list(service.active)
        service.configure_concurrency(1)
        assert service.active == running
        assert not any(r.cancelled.is_set() for r in running)
        for request in running:
            service.messages.put((request, {"kind": "exit"}))
        service._tick()
        assert [(r.path, r.operation) for r in service.active] == [("/scan-1", "scan")]
        assert not service.queued_load_paths()
    finally:
        service.shutdown()


def test_cancelled_scan_retains_shared_slot_until_exit(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_run", lambda request: None)
    try:
        service.submit("first-tab", 0, "/first", "scan")
        first = service.active[0]
        service.submit("second-tab", 0, "/second", "scan")
        assert len(service.pending) == 1
        service.cancel("first-tab", "scan")
        service.submit("load-tab", 0, "/data", "load")
        assert first in service.retired
        assert not service.active
        assert service.queued_operations() == [("load", "/data"), ("scan", "/second")]
        service.messages.put((first, {"kind": "exit"}))
        service._tick()
        assert [(r.path, r.operation) for r in service.active] == [("/data", "load")]
        service.messages.put((service.active[0], {"kind": "exit"}))
        service._tick()
        assert [(r.path, r.operation) for r in service.active] == [("/second", "scan")]
    finally:
        service.shutdown()


def test_navigation_and_loads_precede_bulk_scans_in_stable_order(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_run", lambda request: None)
    try:
        service.submit("running", 0, "/running", "scan")
        first = service.active[0]
        service.submit("bulk-a", 0, "/bulk-a", "scan", {"metadata_only": True})
        service.submit("bulk-b", 0, "/bulk-b", "scan", {"metadata_only": True})
        service.submit("browser", 0, "/browse", "scan", priority=True)
        service.submit("loader", 0, "/data", "load")
        service.submit("resolver", 0, "/default", "resolve", priority=True)
        expected = [("scan", "/browse"), ("load", "/data"), ("resolve", "/default"),
                    ("scan", "/bulk-a"), ("scan", "/bulk-b")]
        assert service.queued_operations() == expected
        assert service.active == [first] and not first.cancelled.is_set()
        for operation, path in expected:
            service.messages.put((service.active[0], {"kind": "exit"}))
            service._tick()
            assert [(r.operation, r.path) for r in service.active] == [(operation, path)]
    finally:
        service.shutdown()


@pytest.mark.parametrize("reuse", ["files", "disk", "memory"])
def test_load_progress_counts_cached_files_and_reports_unreadable_files(
    tmp_path: Path, reuse: str,
) -> None:
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    good = source / "d_txy_forc1.txt"
    good.write_text("1,2,3\n")
    (source / "d_txy_forc2.txt").write_text("not,numeric,data\n")
    options = {"directory": str(tmp_path / "cache"), "params": {"shards": 2}}
    if reuse == "disk":
        load(str(source), str(output), lambda event: None, options)
    info = good.stat()
    memory = [[1, info.st_size, info.st_mtime_ns]] if reuse == "memory" else None
    events: list[dict[str, Any]] = []
    load(str(source), str(output), events.append, options if reuse == "disk" else None, memory)
    progress = [event for event in events if event["kind"] == "progress"]
    expected_files = [str(source / f"d_txy_forc{shot}.txt") for shot in (1, 2)]
    assert [event["filename"] for event in events if event["kind"] == "file_started"] == expected_files
    assert [event["filename"] for event in events if event["kind"] == "file_finished"] == expected_files
    assert progress[0] == {"kind": "progress", "progress": 0.0, "checked_files": 0, "loaded_files": 0,
                           "total_files": 2, "failed_files": 0, "unsettled_files": 0}
    assert progress[-1] == {"kind": "progress", "progress": 1.0, "checked_files": 2, "loaded_files": 1,
                            "total_files": 2, "failed_files": 1, "unsettled_files": 0}
    loaded = next(event for event in events if event["kind"] == "loaded")
    assert loaded["files"] == 1
    assert loaded["problematic"] == [2]


def test_windowed_helper_protocol_has_no_gui_startup(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    # Exercise the frozen file transport/bootstrap with a small executable
    # wrapper. Building an actual platform bundle is a separate release check.
    if sys.platform == "win32":
        pytest.skip("Executable shebang wrapper requires POSIX")
    wrapper = tmp_path / "windowed-helper"
    wrapper.write_text(f"#!{sys.executable}\nimport runpy\nrunpy.run_module('helab.main', run_name='__main__')\n")
    wrapper.chmod(0o700)
    source = tmp_path / "data"
    source.mkdir()
    (source / "d1.txt").write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(wrapper))
    service = IOService()
    events: list[dict[str, Any]] = []
    service.resultReady.connect(lambda request, event: events.append(event))
    service.submit("test", 0, str(source), "scan")
    qtbot.waitUntil(lambda: any(event["kind"] == "done" for event in events), timeout=5000)
    assert next(event for event in events if event["kind"] == "status")["raw"] == [1]
    service.shutdown()


def test_cancel_does_not_retry_and_navigation_remains_available(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = frozen_service(qtbot, monkeypatch)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    explorer = FolderExplorer(str(tmp_path), str(tmp_path), str(tmp_path), [0, 4, 5])
    qtbot.addWidget(explorer)
    qtbot.waitUntil(lambda: bool(service.pending))
    angle = explorer.delegate.angle
    qtbot.wait(180)
    assert explorer.delegate.angle != angle
    explorer.on_stop_button_clicked()
    qtbot.wait(150)
    assert not service.pending
    assert not service.active
    explorer.open_to_path(str(tmp_path / "different"))
    assert explorer.selected_path_globally.endswith("different")
    assert explorer.path_edit.isEnabled()
    explorer.close_cleanup()
    qtbot.wait(50)
    assert not service.pending
    service.shutdown()


def test_real_helper_loads_data_and_refresh_replaces_changed_data(
    qtbot: QtBot, tmp_path: Path,
) -> None:
    from helab.utils.io_service import get_io_service
    (tmp_path / "d1.txt").write_text("")
    converted = tmp_path / "d_txy_forc1.txt"
    converted.write_text("1,2,3\n")
    explorer = FolderExplorer(str(tmp_path), str(tmp_path), str(tmp_path), [0, 4, 5])
    qtbot.addWidget(explorer)
    explorer.selectionPathChanged.connect(lambda path: explorer.load_to_ram_cache(path))
    qtbot.waitUntil(lambda: explorer.folder_opened_data is not None, timeout=15000)
    assert explorer.folder_opened_data is not None
    np.testing.assert_array_equal(explorer.folder_opened_data[1], [[1, 2, 3]])
    converted.write_text("10,20,30\n")
    explorer.rescan(True)
    qtbot.waitUntil(lambda: explorer.folder_opened_data is not None
                   and explorer.folder_opened_data[1][0, 0] == 10, timeout=15000)
    explorer.close_cleanup()
    get_io_service().shutdown()
