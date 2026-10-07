from __future__ import annotations

import os
from pathlib import Path
import subprocess
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
    assert events[0]["entries"][0]["path"] == str(tmp_path / "experiment")


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


def test_stalled_process_keeps_heartbeat_and_shutdown_responsive(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = subprocess.Popen

    def stalled(command: Any, **kwargs: Any) -> subprocess.Popen[str]:
        return original([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)

    monkeypatch.setattr(subprocess, "Popen", stalled)
    monkeypatch.setattr(IOService, "TIMEOUTS", (0.15, 0.20, 0.30))
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
    assert [e["attempt"] for e in events if e["kind"] == "started"] == [1, 2, 3]
    assert len([e for e in events if e["kind"] == "error"]) == 1
    assert len(beats) >= 3
    assert max(b - a for a, b in zip(beats, beats[1:])) < 0.2
    qtbot.waitUntil(lambda: not service.retired, timeout=3000)
    timer.stop()
    start = time.monotonic()
    service.shutdown()
    assert time.monotonic() - start < 0.2


def test_pending_queue_is_bounded(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    service = frozen_service(qtbot, monkeypatch)
    for index in range(service.MAX_PENDING):
        assert service.submit("test", 0, f"/folder-{index}", "scan")
    assert not service.submit("test", 0, "/overflow", "scan")
    assert len(service.pending) == service.MAX_PENDING
    service.cancel("test")
    assert not service.pending
    service.shutdown()


@pytest.mark.parametrize("operation", ["scan", "load"])
def test_timeout_retries_use_three_deadlines_and_ignore_old_attempts(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_run", lambda request: None)
    events: list[dict[str, Any]] = []
    service.resultReady.connect(lambda request, event: events.append(event))
    service.submit("tab", 0, "/slow", operation)
    for attempt, timeout in enumerate((15.0, 20.0, 30.0), 1):
        request = service.active[0]
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


def test_loads_are_serial_fifo_while_scans_can_bypass_them(
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
    assert [(r.path, r.operation) for r in service.active] == [("/first", "load"), ("/browse", "scan")]
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
    assert progress[0] == {"kind": "progress", "progress": 0.0, "loaded_files": 0,
                           "total_files": 2, "failed_files": 0}
    assert progress[-1] == {"kind": "progress", "progress": 1.0, "loaded_files": 1,
                            "total_files": 2, "failed_files": 1}
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
