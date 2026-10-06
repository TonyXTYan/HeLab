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
