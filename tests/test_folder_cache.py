from __future__ import annotations

from pathlib import Path
import json
import os
import subprocess
import time
import sys
from typing import Any

import numpy as np
import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtCore import Qt

from helab.models.SnapshotFileSystemModel import SnapshotFileSystemModel
from helab.utils.folder_cache import Dataset, FolderCache, get_folder_cache
from helab.utils.io_service import IORequest, IOService
from helab.views.FolderExplorer import FolderExplorer
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
    request = producer(cache, path, "scan")
    cache.service.resultReady.emit(request, {"kind": "entries", "entries": [
        {"path": p, "modified": None} for p in (children or [])]})
    cache.service.resultReady.emit(request, {"kind": "status", "status": "ok", "count": 1,
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
    qtbot.waitUntil(lambda: ("scan", path) in cache.jobs)
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
    qtbot.waitUntil(lambda: bool(second.root and second.root.loaded) and ("scan", path) in cache.jobs)
    assert child in second.nodes
    assert len(service.pending) == 1
    request = producer(cache, path, "scan")
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
    qtbot.waitUntil(lambda: ("scan", path) in cache.jobs)
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


def test_invalidation_rejects_late_load_results_and_rechecks(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = service_for_test(monkeypatch)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    cache, path = get_folder_cache(service), str(tmp_path)
    first = explorer_for_test(qtbot, path)
    qtbot.waitUntil(lambda: ("scan", path) in cache.jobs)
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
    qtbot.waitUntil(lambda: ("scan", path) in cache.jobs)
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
    assert operations == ["scan", "load"]
    second = explorer_for_test(qtbot, str(tmp_path))
    qtbot.waitUntil(lambda: second.folder_opened_data is not None)
    assert second.load_source == "memory"
    assert operations == ["scan", "load"]  # No helper for warm memory reuse.
    assert first.folder_opened_data is not None and second.folder_opened_data is not None
    assert first.folder_opened_data[1] is second.folder_opened_data[1]
    source.write_text("10,20,30\n")
    first.refresh()
    qtbot.waitUntil(lambda: second.folder_opened_data is not None and second.folder_opened_data[1][0, 0] == 10,
                   timeout=15000)
    assert operations == ["scan", "load", "scan", "load"]
    assert first.folder_opened_data[1] is second.folder_opened_data[1]
    first.close_cleanup()
    second.close_cleanup()
    service.shutdown()

    # A new service has no session snapshots or arrays, like a restarted app.
    restarted_service = IOService()
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: restarted_service)
    reopened = explorer_for_test(qtbot, str(tmp_path))
    qtbot.waitUntil(lambda: reopened.folder_opened_data is not None, timeout=15000)
    assert reopened.load_source == "disk"
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
        assert events[0]["kind"] == "load_source"
        assert events[0]["source"] == expected
        assert events[0]["cache_reason"] == ("" if require_cache else "No saved cache fingerprint")
        assert events[-1]["source"] == expected
        assert events[-1]["cached"] is require_cache
        assert not any(event["kind"] == "cache_warning" for event in events)
        np.testing.assert_array_equal(np.load(tmp_path / name / "1.npy"), [[1, 2, 3]])

    converted.write_text("100,200,300\n")
    events = run("changed", False)
    assert events[-1]["source"] == "files"
    assert events[-1]["cache_reason"] == "TXY files changed since caching"
    assert events[-1]["cached"] is False
    np.testing.assert_array_equal(np.load(tmp_path / "changed" / "1.npy"), [[100, 200, 300]])


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
    assert events[0]["entries"][0]["disk_cached"] is True
    assert events[-1]["disk_cached"] is False
    events.clear()
    scan(str(source), events.append, options)
    assert events[-1]["disk_cached"] is True


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

    assert badges() == [StatusIcons.ICON_CACHED]
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
    assert events[-1]["cache_reason"] == warning["message"]
    assert events[-1]["source"] == "files"
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
