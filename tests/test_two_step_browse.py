"""Browsing in two steps: names first (``list``), file details in the background (``details``)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterator, cast
import os
import time

import numpy as np
import pytest
from diskcache import FanoutCache
from pytestqt.qtbot import QtBot

from helab.io_helper import list_folder, load, scan
from helab.utils.folder_cache import FolderCache, get_folder_cache
from helab.utils.io_service import IORequest, IOService
from helab.utils.scan_history import apply_outcome, empty_history
from helab.views.FolderExplorer import FolderExplorer


def frozen_service(monkeypatch: pytest.MonkeyPatch) -> IOService:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    return service


def producer(cache: FolderCache, path: str, operation: str) -> IORequest:
    owner = cache.jobs[(operation, path)].owner
    return next(r for r in cache.service.pending if r.owner == owner)


def replay(qtbot: QtBot, cache: FolderCache, path: str, operation: str,
           helper: Callable[[Callable[[dict[str, Any]], None]], None]) -> None:
    """Send a real helper's events for the queued request, then wait for tab delivery."""
    request = producer(cache, path, operation)

    def send(event: dict[str, Any]) -> None:
        if event["kind"] == "shot":
            event = {**event, "array": np.load(event["artifact"])}
        cache.service.resultReady.emit(request, event)
    helper(send)
    cache.service.resultReady.emit(request, {"kind": "done"})
    cache.service.pending.remove(request)
    qtbot.waitUntil(lambda: not any(r.path == path for r in cache._deliveries))


def data_folder(path: Path, *, subfolder: bool = True) -> None:
    path.mkdir(exist_ok=True)
    if subfolder:
        (path / "run").mkdir()
    for shot in (1, 2):
        (path / f"d{shot}.txt").write_text("")
        (path / f"d_txy_forc{shot}.txt").write_text(f"{shot},2,3\n")


class _NoStatEntry:
    def __init__(self, entry: os.DirEntry[str]) -> None:
        self.entry, self.name, self.path = entry, entry.name, entry.path

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        assert not follow_symlinks
        return self.entry.is_dir(follow_symlinks=False)

    def stat(self, **kwargs: Any) -> os.stat_result:
        raise AssertionError("Listing called stat")


class _NoStatListing:
    def __init__(self, path: str, scandir: Callable[[str], Any]) -> None:
        self.listing = scandir(path)

    def __enter__(self) -> Iterator[_NoStatEntry]:
        return (_NoStatEntry(entry) for entry in self.listing.__enter__())

    def __exit__(self, *args: Any) -> None:
        self.listing.__exit__(*args)


def test_listing_reads_names_only_and_never_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    data_folder(source)
    path = str(source)
    options: dict[str, Any] = {"directory": str(tmp_path / "cache"), "params": {"shards": 2}}
    scan(path, lambda event: None, options)
    with FanoutCache(options["directory"], **options["params"]) as disk:
        saved = cast(dict[str, Any], disk.get(("folder-scan-v1", path)))
    assert saved["signature"]
    scandir = os.scandir
    with monkeypatch.context() as no_stat:
        # Without the optional cache, which stats its own files when it opens.
        no_stat.setattr("os.scandir", lambda p: _NoStatListing(p, scandir))
        no_stat.setattr("os.stat", lambda *a, **k: pytest.fail("Listing called os.stat"))
        list_folder(path, lambda event: None)
    events: list[dict[str, Any]] = []
    list_folder(path, events.append, options)
    status = next(event for event in events if event["kind"] == "status")
    assert (status["status"], status["count"], status["raw"], status["txy"]) == ("ok", 2, [1, 2], [1, 2])
    assert not status["details"] and not status["empty"] and status["has_dirs"]
    assert not {"signature", "modified", "identity"} & set(status)
    assert [entry for event in events if event["kind"] == "entries" for entry in event["entries"]] == [
        {"path": str(source / "run"), "name": "run"}]
    # The folder's own saved summary is restored; nothing is written.
    assert next(event for event in events if event["kind"] == "scan_cached")["status"] == saved
    with FanoutCache(options["directory"], **options["params"]) as disk:
        assert disk.get(("folder-scan-v1", path)) == saved


def test_browse_shows_counts_first_and_details_fill_dates_and_signature(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = frozen_service(monkeypatch)
    data_folder(tmp_path)
    path, child = str(tmp_path), str(tmp_path / "run")
    explorer = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(explorer)
    cache = explorer.model.cache
    options = explorer.model._cache_options
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    request = producer(cache, path, "list")
    assert service.label(request) == "Browse folder" and request.priority
    service.resultReady.emit(request, {"kind": "started"})
    service.resultReady.emit(request, {"kind": "heartbeat", "phase": "listing", "entries": 3200})
    explorer._update_activity()
    assert explorer.folder_summary_label.text() == "Listing… 3,200 entries"
    replay(qtbot, cache, path, "list", lambda send: list_folder(path, send, options))
    root = explorer.model.nodes[path]
    explorer._update_activity()
    # Counts and status are available at once; dates and signature are not yet.
    assert explorer.folder_summary_label.text() == "2 TXY found · Not loaded"
    assert root.state == "idle" and root.signature == "" and root.modified is None
    assert explorer.model.nodes[child].modified is None
    details = producer(cache, path, "details")
    assert service.label(details) == "Folder details" and not details.priority
    assert not explorer.retrying_scan and root.state == "idle"
    replay(qtbot, cache, path, "details", lambda send: scan(path, send, options))
    assert root.signature and root.modified is not None and root.state == "idle"
    assert explorer.model.nodes[child].modified is not None
    assert not cache.jobs
    explorer.close_cleanup()
    service.shutdown()


def test_load_of_the_selected_folder_replaces_details_and_saves_its_summary(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = frozen_service(monkeypatch)
    data_folder(tmp_path, subfolder=False)
    (tmp_path / "artifacts").mkdir()
    path = str(tmp_path)
    explorer = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(explorer)
    explorer.selectionPathChanged.connect(lambda p: explorer.load_to_ram_cache(p, dwell=False))
    cache = explorer.model.cache
    options = explorer.model._cache_options
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    replay(qtbot, cache, path, "list", lambda send: list_folder(path, send, options))
    # The listing's counts start the load; the load lists and fingerprints the folder itself.
    assert ("load", path) in cache.jobs and ("details", path) not in cache.jobs
    replay(qtbot, cache, path, "load", lambda send: load(path, str(tmp_path / "artifacts"), send, options))
    dataset = explorer.displayed_dataset
    root = explorer.model.nodes[path]
    assert dataset is not None and root.signature == dataset.signature
    snapshot = cache.snapshot(path)
    assert snapshot is not None and snapshot.status["signature"] == dataset.signature
    explorer._update_activity()
    assert explorer.folder_summary_label.text() == "2 TXY found · 2 loaded"
    with FanoutCache(options["directory"], **options["params"]) as disk:
        saved = cast(dict[str, Any], disk.get(("folder-scan-v1", path)))
    assert (saved["signature"], saved["txy_count"], saved["raw_count"]) == (dataset.signature, 2, 2)
    explorer.close_cleanup()
    service.shutdown()


def test_blocked_folder_lists_but_skips_automatic_details(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = frozen_service(monkeypatch)
    cache = get_folder_cache(service)
    path = str(tmp_path)
    cache.remember_history(path, apply_outcome(empty_history(), {
        "operation_id": "failed", "revision": 5, "kind": "timeout", "at": time.time(), "attempts": 1,
        "reason": "Timed out after 60 s without progress"}))
    events: list[dict[str, Any]] = []
    cache.resultReady.connect(lambda request, event: events.append(event))
    assert cache.submit("tab", 0, path, "details", {})
    assert not service.pending
    qtbot.waitUntil(lambda: {"kind": "scan_mode", "mode": "skipped"} in events)
    assert cache.submit("tab", 0, path, "list", {})
    assert [r.operation for r in service.pending] == ["list"]
    assert cache.submit("tab", 0, path, "details", {"scan_manual": True})
    assert [r.operation for r in service.pending] == ["list", "details"]
    service.shutdown()


def test_scan_started_before_a_cache_clear_cannot_restore_the_cached_flag(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = frozen_service(monkeypatch)
    cache = get_folder_cache(service)
    path = str(tmp_path)
    cache.submit("tab", 0, path, "scan", {})
    old = producer(cache, path, "scan")
    cache.submit("tab", 0, path, "invalidate", {})
    status = {"kind": "status", "status": "ok", "count": 1, "raw": [1], "txy": [1], "details": True,
              "signature": "v1", "disk_cached": True}
    service.resultReady.emit(old, status)
    assert not cache.disk_cached(path)
    service.resultReady.emit(old, {"kind": "done"})
    service.resultReady.emit(producer(cache, path, "invalidate"), {"kind": "done"})
    cache.submit("other", 0, path, "scan", {}, force=True)
    service.resultReady.emit(producer(cache, path, "scan"), status)
    assert cache.disk_cached(path)
    service.shutdown()
