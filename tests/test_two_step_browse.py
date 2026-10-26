"""Browsing in two steps: names first (``list``), file details in the background (``details``)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterator, cast
import os
import time

import numpy as np
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from pytestqt.qtbot import QtBot

from helab.io_ops import stores
from helab.io_ops.browse import list_folder
from helab.io_ops.loading import load
from helab.io_ops.scanning import save_subtrees, scan
from helab.utils.cache_store import CacheStore, Read
from helab.utils.cache_paths import Mount
from helab.utils import cache_paths
from helab.utils.cache_freshness import CacheFreshness
from helab.models.SnapshotFileSystemModel import SnapshotFileSystemModel
from helab.resources.icons import IconsInitUtil, StatusIcons
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
           helper: Callable[[Callable[[Any], None]], None]) -> None:
    """Send a real helper's events for the queued request, then wait for tab delivery.

    Some requests are submitted from a posted call (Refresh's details, ``QTimer.singleShot(0)``),
    so wait for the request first."""
    qtbot.waitUntil(lambda: (operation, path) in cache.jobs and any(
        r.owner == cache.jobs[(operation, path)].owner for r in cache.service.pending))
    request = producer(cache, path, operation)

    def send(event: Any) -> None:
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


def saved_summary(options: dict[str, Any], path: str) -> dict[str, Any]:
    with stores._cache_store(options["directory"], [path]) as store:
        found = store.read_record("summaries", path)
    assert found.value is not None
    return found.value


def test_listing_reads_names_only_and_never_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    data_folder(source)
    path = str(source)
    options: dict[str, Any] = {"directory": str(tmp_path / "cache")}
    scan(path, lambda event: None, options)
    saved = saved_summary(options, path)
    assert saved["signature"]
    scandir = os.scandir
    with monkeypatch.context() as no_stat:
        # Without the optional cache, which stats its own files when it opens.
        no_stat.setattr("os.scandir", lambda p: _NoStatListing(p, scandir))
        no_stat.setattr("os.stat", lambda *a, **k: pytest.fail("Listing called os.stat"))
        list_folder(path, lambda event: None)
    events: list[Any] = []
    list_folder(path, events.append, options)
    status = next(event for event in events if event["kind"] == "status")
    assert (status["status"], status["count"], status["raw"], status["txy"]) == ("ok", 2, [1, 2], [1, 2])
    assert not status["details"] and not status["empty"] and status["has_dirs"]
    assert not {"signature", "modified", "identity"} & set(status)
    entries = [entry for event in events if event["kind"] == "entries" for entry in event["entries"]]
    assert [(entry["path"], entry["name"]) for entry in entries] == [(str(source / "run"), "run")]
    # Saved cache metadata comes along; dates need a stat (step 2).
    assert {"scan_history", "scan_status", "disk_cached", "cache_info"} <= set(entries[0])
    assert not {"modified", "identity"} & set(entries[0])
    # The folder's own saved summary is restored; nothing is written.
    assert next(event for event in events if event["kind"] == "scan_cached")["status"] == saved
    assert saved_summary(options, path) == saved


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
    assert explorer.folder_summary_label.text() == "Listing folder… 3,200 entries"
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


def test_details_dates_subfolders_from_the_listing_without_another_stat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A share's top folder may hold hundreds of date folders: their dates come from the listing's
    entries (free on Windows, the same single call elsewhere), never a stat by path per subfolder."""
    child = tmp_path / "run"
    child.mkdir()
    stat, modified = os.stat, child.lstat().st_mtime

    def refuse_subfolder(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        if os.fspath(path) == str(child):
            raise PermissionError("a stat by path")
        return stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", refuse_subfolder)
    events: list[Any] = []
    scan(str(tmp_path), events.append)
    dated = [entry for event in events if event["kind"] == "entries" for entry in event["entries"]]
    assert [entry["path"] for entry in dated] == [str(child)] and dated[0]["modified"] == modified


def test_refresh_does_not_complete_a_running_folder_status_check(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = frozen_service(monkeypatch)
    data_folder(tmp_path)
    path = str(tmp_path)
    explorer = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(explorer)
    cache, options = explorer.model.cache, explorer.model._cache_options
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    replay(qtbot, cache, path, "list", lambda send: list_folder(path, send, options))
    replay(qtbot, cache, path, "details", lambda send: scan(path, send, options))
    explorer.start_basic_scan("current")
    explorer._dispatch_deep()
    check = producer(cache, path, "scan")
    explorer.refresh()
    replay(qtbot, cache, path, "list", lambda send: list_folder(path, send, options))
    assert explorer._basic_active and path in explorer._deep_depth
    assert explorer._basic_completed == 0 and not check.cancelled.is_set()
    replay(qtbot, cache, path, "scan", lambda send: scan(path, send, options))
    explorer._dispatch_deep()
    assert not explorer._basic_active and explorer._basic_completed == 1
    explorer.close_cleanup()
    service.shutdown()


def test_refresh_replaces_newer_ram_status_history_and_subtree_with_saved_listing(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = frozen_service(monkeypatch)
    child = tmp_path / "run"
    data_folder(child, subfolder=False)
    root, path = str(tmp_path), str(child)
    explorer = FolderExplorer(root, root, root, [0, 4, 5])
    explorer.auto_load_ram = False
    qtbot.addWidget(explorer)
    cache, options = explorer.model.cache, explorer.model._cache_options
    scan(path, lambda event: None, options)
    with stores._cache_store(options["directory"], [path]) as store:
        saved_status = store.read_record("summaries", path).value
        assert saved_status is not None
        saved_history = apply_outcome(empty_history(), {
            "operation_id": "saved", "revision": 1, "kind": "timeout", "at": time.time() - 60,
            "attempts": 1, "reason": "Saved failure"})
        saved_subtree = {"version": 1, "status": "nothing", "older": False,
                         "derived_at": time.time() - 60, "data": 0, "checked": 0, "total": 0}
        guard = store.guard([path], ("histories", "subtrees"))
        store.save_record("histories", path, saved_history, guard)
        store.save_record("subtrees", path, saved_subtree, guard)
    qtbot.waitUntil(lambda: ("list", root) in cache.jobs)
    replay(qtbot, cache, root, "list", lambda send: list_folder(root, send, options))
    node = explorer.model.nodes[path]
    newer_status = {**saved_status, "status": "warning", "scanned_at": time.time() + 120}
    cache.remember_scan(path, newer_status)
    explorer.model._restore_summary(node, newer_status)
    cache.remember_history(path, apply_outcome(saved_history, {
        "operation_id": "newer", "revision": 2, "kind": "success", "at": time.time(),
        "attempts": 1, "reason": ""}))
    cache.remember_subtree(path, {**saved_subtree, "status": "something", "derived_at": time.time() + 120})
    node.subtree_saved = cache.subtrees[path]
    cache._subtree_pending[path] = {"path": path, **cache.subtrees[path]}
    explorer.refresh()
    replay(qtbot, cache, root, "list", lambda send: list_folder(root, send, options))
    assert cache.scan_summaries[path] == saved_status
    assert cache.scan_history(path) == saved_history
    assert cache.subtrees[path] == saved_subtree
    assert path not in cache._subtree_pending
    assert node.report is not None and node.report.status == saved_status["status"]
    assert node.subtree_saved == saved_subtree
    # Even without new children, Refresh observes dates again so freshness
    # does not stay unknown after clearing the previous share's mtime.
    qtbot.waitUntil(lambda: ("details", root) in cache.jobs)
    replay(qtbot, cache, root, "details", lambda send: scan(root, send, options))
    assert node.modified is not None
    assert explorer.model.status_freshness(node) is not CacheFreshness.UNKNOWN
    explorer.close_cleanup()
    service.shutdown()


@pytest.mark.parametrize("cache_mode", ["off", "unsupported", "read_error"])
def test_refresh_keeps_ram_status_when_saved_records_cannot_be_read(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cache_mode: str,
) -> None:
    service = frozen_service(monkeypatch)
    child = tmp_path / "run"
    child.mkdir()
    root, path = str(tmp_path), str(child)
    explorer = FolderExplorer(root, root, root, [0, 4, 5])
    explorer.auto_load_ram = False
    qtbot.addWidget(explorer)
    cache, options = explorer.model.cache, explorer.model._cache_options
    status = {"status": "ok", "count": 1, "raw": [1], "txy": [1], "scanned_at": time.time()}
    cache.remember_scan(path, status)
    qtbot.waitUntil(lambda: ("list", root) in cache.jobs)
    replay(qtbot, cache, root, "list", lambda send: list_folder(root, send, None))
    node = explorer.model.nodes[path]
    report = node.report
    assert report is not None
    history = apply_outcome(empty_history(), {
        "operation_id": "failed", "revision": 1, "kind": "timeout", "at": time.time(),
        "attempts": 1, "reason": "Unavailable"})
    cache.remember_history(path, history)
    subtree = {"version": 1, "status": "something", "older": False,
               "derived_at": time.time(), "data": 1, "checked": 1, "total": 1}
    cache.remember_subtree(path, subtree)
    explorer.refresh()
    if cache_mode == "unsupported":
        monkeypatch.setattr(cache_paths, "current_mounts",
                            lambda: [Mount("server:/export", root, "nfs", True)])
    if cache_mode == "read_error":
        original = CacheStore.read_records

        def fail_summaries(store: CacheStore, kind: Any, paths: Any) -> Any:
            if kind == "summaries":
                return {item: Read("error", error="Disk read failed") for item in paths}
            return original(store, kind, paths)

        monkeypatch.setattr(CacheStore, "read_records", fail_summaries)
    replay(qtbot, cache, root, "list", lambda send: list_folder(
        root, send, None if cache_mode == "off" else options))
    assert node.report is report
    assert cache.scan_summaries[path] == status
    assert cache.scan_history(path) == history
    assert cache.subtrees[path] == subtree
    explorer.close_cleanup()
    service.shutdown()


@pytest.fixture
def checked_browser(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                    ) -> Iterator[tuple[IOService, FolderExplorer, str]]:
    service = frozen_service(monkeypatch)
    data_folder(tmp_path)
    path = str(tmp_path)
    explorer = FolderExplorer(path, path, path, [0, 4, 5])
    explorer.auto_load_ram = False
    qtbot.addWidget(explorer)
    cache, options = explorer.model.cache, explorer.model._cache_options
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    replay(qtbot, cache, path, "list", lambda send: list_folder(path, send, options))
    replay(qtbot, cache, path, "details", lambda send: scan(path, send, options))
    yield service, explorer, path
    explorer.close_cleanup()
    service.shutdown()


@pytest.mark.parametrize("outcome", ["done", "error", "cancelled"])
def test_refresh_disables_only_its_folder_retry_until_terminal_outcome(
    qtbot: QtBot, checked_browser: tuple[IOService, FolderExplorer, str],
    tmp_path: Path, outcome: str,
) -> None:
    service, explorer, path = checked_browser
    cache, options = explorer.model.cache, explorer.model._cache_options
    (tmp_path / "d_txy_forc3.txt").write_text("3,2,3\n")
    previous_report = explorer.model.nodes[path].report
    explorer.refresh()
    qtbot.waitUntil(lambda: not explorer.model._refresh_submitting)
    assert explorer.model.refresh_pending(path) and not explorer.retry_button.isEnabled()
    refresh = producer(cache, path, "list")
    assert not explorer.model.request_scan(path, priority=True, force=True, no_timeout=True)
    assert refresh.timeout == service.NO_PROGRESS_TIMEOUT
    assert explorer.model.request_scan(str(tmp_path / "run"), force=True, no_timeout=True)
    explorer.load_error = "Load failed"
    explorer._update_activity()
    assert explorer.retry_button.isEnabled()  # Load Retry remains independent.
    explorer.load_error = ""
    if outcome == "done":
        replay(qtbot, cache, path, "list", lambda send: list_folder(path, send, options))
        assert explorer.model.nodes[path].txy_count == 2  # Refresh preserves checked counts.
    elif outcome == "error":
        service.resultReady.emit(refresh, {"kind": "error", "message": "Disconnected"})
        service.pending.remove(refresh)
    else:
        cache.cancel(explorer.model.owner, "list", path)
    if outcome != "done":
        assert explorer.model.nodes[path].report is previous_report
    assert not explorer.model.refreshing and explorer.retry_button.isEnabled()
    explorer._retry()
    assert producer(cache, path, "list").timeout == float("inf")
    replay(qtbot, cache, path, "list", lambda send: list_folder(path, send, options))
    replay(qtbot, cache, path, "details", lambda send: scan(path, send, options))
    assert explorer.model.nodes[path].txy_count == 3


@pytest.mark.parametrize("completion_order", ["check_first", "refresh_first", "during_replay"])
def test_manual_check_cannot_restore_children_removed_by_a_newer_refresh(
    qtbot: QtBot, checked_browser: tuple[IOService, FolderExplorer, str],
    tmp_path: Path, completion_order: str,
) -> None:
    service, explorer, path = checked_browser
    cache, options = explorer.model.cache, explorer.model._cache_options
    explorer.start_basic_scan("current")
    explorer._dispatch_deep()
    check = producer(cache, path, "scan")
    check_events: list[Any] = []
    scan(path, check_events.append, options)
    explorer.refresh()
    assert not check.cancelled.is_set() and explorer._basic_active
    old = tmp_path / "run"
    old.rmdir()

    def finish_check() -> None:
        for event in check_events:
            service.resultReady.emit(check, event)
        service.resultReady.emit(check, {"kind": "done"})
        service.pending.remove(check)
        qtbot.waitUntil(lambda: not cache._deliveries)

    if completion_order == "check_first":
        finish_check()
    if completion_order == "during_replay":
        refresh = producer(cache, path, "list")
        list_folder(path, lambda event: service.resultReady.emit(refresh, event), options)
        service.resultReady.emit(refresh, {"kind": "done"})
        service.pending.remove(refresh)
        finish_check()
    else:
        replay(qtbot, cache, path, "list", lambda send: list_folder(path, send, options))
    assert str(old) not in explorer.model.nodes
    if completion_order == "refresh_first":
        assert explorer._basic_active
        finish_check()
    explorer._dispatch_deep()
    assert str(old) not in explorer.model.nodes and not explorer._basic_active
    assert explorer._basic_completed == 1
    assert not explorer.model.refreshing
    assert str(old) not in {entry["path"] for entry in cache.snapshots[path].entries}
    later = SnapshotFileSystemModel(service=service)
    later.setRootPath(path)
    qtbot.waitUntil(lambda: not cache._deliveries)
    assert str(old) not in later.nodes
    later.close_cleanup()


def test_refresh_cancels_only_automatic_subscriptions_and_suppresses_new_checks(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
    checked_browser: tuple[IOService, FolderExplorer, str], tmp_path: Path,
) -> None:
    service, explorer, path = checked_browser
    cache, options = explorer.model.cache, explorer.model._cache_options
    child = str(tmp_path / "run")
    explorer.show()
    monkeypatch.setattr(explorer, "_viewport_paths", lambda: [child])
    explorer.set_auto_scan_visible(True)
    explorer._check_visible_folders()
    automatic = producer(cache, child, "scan")
    assert cache.submit("other-tab", 0, child, "scan", {"scan_manual": True}, force=True)
    explorer.model._request_details(explorer.model.nodes[child], manual=False)
    details = producer(cache, child, "details")
    explorer.start_basic_scan("current")
    explorer._dispatch_deep()
    manual = producer(cache, path, "scan")
    explorer.refresh()
    assert not cache.has_request(explorer.model.owner, "scan", child)
    assert cache.has_request("other-tab", "scan", child) and not automatic.cancelled.is_set()
    assert details.cancelled.is_set() and not manual.cancelled.is_set()
    assert explorer.model.nodes[child].state == "idle" and not explorer.model.nodes[child].error
    assert not explorer.visible_timer.isActive()
    explorer._check_visible_folders()
    explorer.model._request_details(explorer.model.nodes[child], manual=False)
    assert not cache.has_request(explorer.model.owner, "scan", child)
    assert ("details", child) not in cache.jobs
    replay(qtbot, cache, path, "list", lambda send: list_folder(path, send, options))
    assert not explorer.model.refreshing
    # The details Refresh cancelled run again once it finishes (from a posted call).
    qtbot.waitUntil(lambda: cache.has_request(explorer.model.owner, "details", child))
    cache.cancel(explorer.model.owner, "details", child)
    service.max_operations = 2  # The surviving manual check still occupies one slot.
    explorer._check_visible_folders()
    assert cache.has_request(explorer.model.owner, "scan", child)
    cache.cancel("other-tab")


def test_refresh_requests_details_for_new_subfolders_after_it_finishes(
    qtbot: QtBot, checked_browser: tuple[IOService, FolderExplorer, str], tmp_path: Path,
) -> None:
    service, explorer, path = checked_browser
    cache, options = explorer.model.cache, explorer.model._cache_options
    added = tmp_path / "run2"
    added.mkdir()
    explorer.refresh()
    qtbot.waitUntil(lambda: not explorer.model._refresh_submitting)
    replay(qtbot, cache, path, "list", lambda send: list_folder(path, send, options))
    assert not explorer.model.refreshing
    assert explorer.model.nodes[str(added)].modified is None
    replay(qtbot, cache, path, "details", lambda send: scan(path, send, options))
    assert explorer.model.nodes[str(added)].modified is not None


def test_refresh_cancelling_work_resubmitted_after_a_cache_clear_leaves_the_row_idle(
    qtbot: QtBot, checked_browser: tuple[IOService, FolderExplorer, str], tmp_path: Path,
) -> None:
    service, explorer, _ = checked_browser
    cache, child = explorer.model.cache, str(tmp_path / "run")
    node = explorer.model.nodes[child]
    assert cache.submit("other-tab", 0, child, "invalidate", {})
    # Parked behind the clear: this request is replaced, never finished.
    explorer.model._request_details(node, manual=False)
    parked = next(r for r in explorer.model._scan_seen if r.path == child and r.operation == "details")
    clear = producer(cache, child, "invalidate")
    service.resultReady.emit(clear, {"kind": "done"})
    service.pending.remove(clear)
    qtbot.waitUntil(lambda: ("details", child) in cache.jobs)
    explorer.refresh()
    assert node.state == "idle" and parked not in explorer.model._scan_seen
    assert explorer.model._tree_requests.get(child) is not parked


def test_joining_another_tabs_running_listing_shows_the_row_running(
    qtbot: QtBot, checked_browser: tuple[IOService, FolderExplorer, str],
) -> None:
    service, explorer, path = checked_browser
    cache, options = explorer.model.cache, explorer.model._cache_options
    node = explorer.model.nodes[path]
    assert cache.submit("other-tab", 0, path, "list", {}, force=True)
    service.resultReady.emit(producer(cache, path, "list"), {"kind": "started"})
    # Joining late delivers "started", not "queued".
    assert explorer.model.request_scan(path, force=True)
    assert node.state == "running"
    replay(qtbot, cache, path, "list", lambda send: list_folder(path, send, options))
    assert node.state == "idle" and [child.path for child in node.children] == [str(Path(path) / "run")]


def test_row_returns_to_a_running_status_check_when_refresh_listing_finishes(
    qtbot: QtBot, checked_browser: tuple[IOService, FolderExplorer, str],
) -> None:
    service, explorer, path = checked_browser
    cache, options = explorer.model.cache, explorer.model._cache_options
    node = explorer.model.nodes[path]
    explorer.start_basic_scan("current")
    explorer._dispatch_deep()
    service.resultReady.emit(producer(cache, path, "scan"), {"kind": "started"})
    explorer.refresh()
    replay(qtbot, cache, path, "list", lambda send: list_folder(path, send, options))
    assert not explorer.model.refreshing and node.state == "running"
    replay(qtbot, cache, path, "scan", lambda send: scan(path, send, options))
    assert node.state == "idle" and node.children


def check_in_other_tab(qtbot: QtBot, cache: FolderCache, path: str, options: dict[str, Any]) -> None:
    """Another tab checks the folder; this tab shows the result from memory, submitting nothing."""
    before = list(cache.service.pending)
    assert cache.submit("other-tab", 0, path, "scan", {"metadata_only": True}, force=True)
    replay(qtbot, cache, path, "scan", lambda send: scan(path, send, options))
    assert list(cache.service.pending) == before


def test_other_tabs_finished_check_shows_while_this_tab_refreshes(
    qtbot: QtBot, checked_browser: tuple[IOService, FolderExplorer, str], tmp_path: Path,
) -> None:
    _, explorer, _ = checked_browser
    cache, options = explorer.model.cache, explorer.model._cache_options
    child = str(tmp_path / "run")
    (tmp_path / "run" / "d_txy_forc9.txt").write_text("9,2,3\n")
    explorer.refresh()  # The root listing stays pending.
    assert explorer.model.refreshing
    check_in_other_tab(qtbot, cache, child, options)
    assert explorer.model.nodes[child].txy_count == 1


def test_other_tabs_finished_check_of_an_off_screen_row_shows_after_refresh(
    qtbot: QtBot, checked_browser: tuple[IOService, FolderExplorer, str], tmp_path: Path,
) -> None:
    _, explorer, path = checked_browser
    cache, options = explorer.model.cache, explorer.model._cache_options
    run, inner = tmp_path / "run", tmp_path / "run" / "inner"
    inner.mkdir()
    # "run" is listed but collapsed: Refresh relists only the root, not "inner"'s parent.
    assert explorer.model.request_scan(str(run))
    replay(qtbot, cache, str(run), "list", lambda send: list_folder(str(run), send, options))
    assert str(inner) in explorer.model.nodes
    (inner / "d_txy_forc9.txt").write_text("9,2,3\n")
    explorer.refresh()
    check_in_other_tab(qtbot, cache, str(inner), options)
    replay(qtbot, cache, path, "list", lambda send: list_folder(path, send, options))
    qtbot.waitUntil(lambda: not explorer.model.refreshing)
    assert explorer.model.nodes[str(inner)].txy_count == 1


@pytest.mark.parametrize("refreshing", [False, True])
def test_applying_another_tabs_old_result_submits_no_source_operation(
    qtbot: QtBot, checked_browser: tuple[IOService, FolderExplorer, str], tmp_path: Path, refreshing: bool,
) -> None:
    service, explorer, _ = checked_browser
    cache, child = explorer.model.cache, str(tmp_path / "run")
    check_in_other_tab(qtbot, cache, child, explorer.model._cache_options)
    if refreshing:
        explorer.refresh()
    before = list(service.pending)
    # Older than the freshness window: a replay through ``submit`` would revalidate it in a helper.
    cache.snapshots[child].checked_at -= 10 * cache.FRESH_SECONDS
    cache.snapshotChanged.emit(child)
    qtbot.waitUntil(lambda: not any(r.path == child for r in cache._deliveries))
    node = explorer.model.nodes[child]
    assert list(service.pending) == before
    assert node.state == "idle" and node.report is not None and node.loaded


@pytest.mark.parametrize("row_state", ["queued", "idle"])
def test_manual_check_joining_automatic_work_survives_refresh(
    checked_browser: tuple[IOService, FolderExplorer, str],
    row_state: str,
) -> None:
    _, explorer, path = checked_browser
    cache = explorer.model.cache
    cache.snapshots.pop(path)  # Simulate automatic work that cannot use a saved snapshot.
    explorer.model.request_scan(path, metadata_only=True)
    automatic = producer(cache, path, "scan")
    explorer.model.nodes[path].state = row_state
    explorer.start_basic_scan("current")
    explorer._dispatch_deep()
    explorer.refresh()
    assert not automatic.cancelled.is_set()
    subscriber = next(request for request in cache.requests(explorer.model.owner)
                      if request.operation == "scan")
    assert subscriber.payload["scan_manual"] and not subscriber.payload["automatic"]


def test_refresh_superseding_cached_replay_keeps_retry_disabled(
    qtbot: QtBot, checked_browser: tuple[IOService, FolderExplorer, str],
) -> None:
    _, explorer, path = checked_browser
    cache = explorer.model.cache
    assert explorer.model.request_scan(path)  # Replay has not been delivered yet.
    explorer.refresh()
    qtbot.waitUntil(lambda: not explorer.model._refresh_submitting)
    assert explorer.model.refresh_pending(path) and not explorer.retry_button.isEnabled()
    assert producer(cache, path, "list").payload["listing_only"]


def test_refresh_joins_another_tabs_listing_while_its_manual_check_is_active(
    qtbot: QtBot, checked_browser: tuple[IOService, FolderExplorer, str],
) -> None:
    _, explorer, path = checked_browser
    cache, options = explorer.model.cache, explorer.model._cache_options
    explorer.start_basic_scan("current")
    explorer._dispatch_deep()
    assert cache.submit("other-tab", 0, path, "list", {}, force=True)
    explorer.refresh()
    assert cache.has_request(explorer.model.owner, "list", path)
    replay(qtbot, cache, path, "list", lambda send: list_folder(path, send, options))
    assert not explorer.model.refreshing and explorer._basic_active


def test_refresh_batch_waiting_for_queue_space_is_abandoned_on_navigation(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
    checked_browser: tuple[IOService, FolderExplorer, str], tmp_path: Path,
) -> None:
    service, explorer, path = checked_browser
    cache, options = explorer.model.cache, explorer.model._cache_options
    branches = [str(tmp_path / f"branch-{i}") for i in range(18)]
    for branch in branches:
        Path(branch).mkdir()
    explorer.model.request_scan(path, force=True)
    replay(qtbot, cache, path, "list", lambda send: list_folder(path, send, options))
    replay(qtbot, cache, path, "details", lambda send: scan(path, send, options))
    monkeypatch.setattr(explorer.model, "viewport_paths", lambda: branches)
    monkeypatch.setattr(explorer.tree, "isExpanded", lambda index: True)
    explorer.refresh()
    assert len(service.pending) == 16 and explorer.model._refresh_submitting
    assert all(explorer.model.refresh_pending(branch) for branch in branches)
    explorer.open_to_path(str(tmp_path / "elsewhere"))
    qtbot.wait(80)
    assert not explorer.model.refreshing
    assert not any(request.payload.get("listing_only") for request in service.pending)


def test_load_of_the_selected_folder_replaces_details_and_saves_its_summary(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = frozen_service(monkeypatch)
    source = tmp_path / "source"
    data_folder(source, subfolder=False)
    (tmp_path / "artifacts").mkdir()
    path = str(source)
    explorer = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(explorer)
    explorer.selectionPathChanged.connect(lambda p: explorer.load_to_ram_cache(p, dwell=False))
    cache = explorer.model.cache
    options = explorer.model._cache_options
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    replay(qtbot, cache, path, "list", lambda send: list_folder(path, send, options))
    # The listing's counts start the load. Without subfolders, the load lists and
    # fingerprints everything step 2 would.
    assert ("load", path) in cache.jobs and ("details", path) not in cache.jobs
    replay(qtbot, cache, path, "load", lambda send: load(path, str(tmp_path / "artifacts"), send, options))
    dataset = explorer.displayed_dataset
    root = explorer.model.nodes[path]
    assert dataset is not None and root.signature == dataset.signature
    snapshot = cache.snapshot(path)
    assert snapshot is not None and snapshot.status["signature"] == dataset.signature
    explorer._update_activity()
    assert explorer.folder_summary_label.text() == "2 TXY found · 2 loaded"
    saved = saved_summary(options, path)
    assert saved["files"] == {"raw": {"count": 2}, "txy": {"count": 2, "bytes": sum(
        (source / f"d_txy_forc{shot}.txt").stat().st_size for shot in (1, 2))}}
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


def test_startup_restores_saved_subfolder_status_without_rescanning(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A loading root with saved subfolder summaries: badges appear with the names,
    automatic visible scans have nothing to do, and the root's details still run
    for subfolder dates."""
    service = frozen_service(monkeypatch)
    data_folder(tmp_path, subfolder=False)
    children = [tmp_path / f"run_{i}" for i in range(3)]
    for child in children:
        data_folder(child, subfolder=False)
    path = str(tmp_path)
    explorer = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(explorer)
    explorer.selectionPathChanged.connect(lambda p: explorer.load_to_ram_cache(p, dwell=False))
    cache = explorer.model.cache
    options = explorer.model._cache_options
    for child in children:
        scan(str(child), lambda event: None, options)  # Saved by a previous session.
    # A prior version stored mount-dependent IDs. Their mismatch must not erase statuses.
    with stores._cache_store(options["directory"], [str(child) for child in children]) as store:
        for child in children:
            saved = store.read_record("summaries", str(child)).value
            assert saved is not None
            store.save_record("summaries", str(child), {**saved, "identity": [999, 888]},
                              store.guard([str(child)], ("summaries",)))
    explorer.resize(420, 350)
    explorer.show()
    explorer.set_auto_scan_visible(True)
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    replay(qtbot, cache, path, "list", lambda send: list_folder(path, send, options))
    nodes = [explorer.model.nodes[str(child)] for child in children]
    assert all(node.report is not None and node.txy_count == 2 and node.cached_report for node in nodes)
    explorer._check_visible_folders()
    assert not [r for r in service.pending if r.operation == "scan"]
    # The root loads (it has TXY files) and still gets details for its subfolders.
    assert ("load", path) in cache.jobs and ("details", path) in cache.jobs
    replay(qtbot, cache, path, "details", lambda send: scan(path, send, options))
    assert all(node.modified is not None for node in nodes)
    assert all(node.report is not None and node.cached_report for node in nodes)
    explorer._check_visible_folders()
    assert not [r for r in service.pending if r.operation == "scan"]
    explorer.close_cleanup()
    service.shutdown()


@pytest.mark.parametrize("mtime_shift", [-60, 60])
def test_saved_summary_of_a_replaced_folder_stays_with_clock_until_checked(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mtime_shift: int,
) -> None:
    IconsInitUtil.initialise_icons()
    service = frozen_service(monkeypatch)
    child = tmp_path / "run"
    data_folder(child, subfolder=False)
    path = str(tmp_path)
    explorer = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(explorer)
    cache = explorer.model.cache
    options = explorer.model._cache_options
    scan(str(child), lambda event: None, options)
    # The folder is replaced by another one with the same name.
    saved_mtime = child.stat().st_mtime
    os.rename(child, tmp_path / "old-run")
    data_folder(child, subfolder=False)
    os.utime(child, (saved_mtime + mtime_shift, saved_mtime + mtime_shift))
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    replay(qtbot, cache, path, "list", lambda send: list_folder(path, send, options))
    node = explorer.model.nodes[str(child)]
    assert node.report is not None  # Saved summary shown provisionally.
    replay(qtbot, cache, path, "details", lambda send: scan(path, send, options))
    assert node.report is not None and node.cached_report
    assert explorer.model.status_freshness(node) == CacheFreshness.POSSIBLY_OLD
    assert status_icon(explorer, child) == StatusIcons.ICONS_STATUS_OLDER["ok"].cacheKey()
    explorer.close_cleanup()
    service.shutdown()


# A folder's status derived from its subfolders: "something" when any holds data,
# "nothing" when all were checked and hold nothing, else the folder's own status.
@pytest.fixture
def tree(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FolderExplorer]:
    IconsInitUtil.initialise_icons()
    service = frozen_service(monkeypatch)
    root = str(tmp_path)
    explorer = FolderExplorer(root, root, root, [0, 4, 5])
    qtbot.addWidget(explorer)
    qtbot.waitUntil(lambda: ("list", root) in explorer.model.cache.jobs)
    yield explorer
    explorer.close_cleanup()
    service.shutdown()


def browse(qtbot: QtBot, explorer: FolderExplorer, path: Path, *, force: bool = False) -> None:
    """List one folder (an expand, or a forced recheck) with the real helper."""
    cache, options = explorer.model.cache, explorer.model._cache_options
    if str(path) != explorer.model.rootPath() or force:
        explorer.model.request_scan(str(path), priority=True, force=force)
    qtbot.waitUntil(lambda: ("list", str(path)) in cache.jobs)
    replay(qtbot, cache, str(path), "list", lambda send: list_folder(str(path), send, options))


def shown(explorer: FolderExplorer, path: Path) -> str | None:
    return explorer.model.display_status(explorer.model.nodes[str(path)])


def status_icon(explorer: FolderExplorer, path: Path) -> int:
    index = explorer.model.path_index(str(path), explorer.model.COLUMN_STATUS_ICON)
    return cast(QIcon, index.data(Qt.ItemDataRole.DecorationRole)).cacheKey()


def test_data_in_a_subfolder_marks_its_ancestors_something(qtbot: QtBot, tree: FolderExplorer, tmp_path: Path) -> None:
    a = tmp_path / "A"
    (a / "X").mkdir(parents=True)
    data_folder(a / "X" / "B", subfolder=False)
    browse(qtbot, tree, tmp_path)
    browse(qtbot, tree, a)
    assert shown(tree, a) == "unknown"
    browse(qtbot, tree, a / "X")
    browse(qtbot, tree, a / "X" / "B")
    assert shown(tree, a / "X" / "B") == "ok"
    assert shown(tree, a / "X") == shown(tree, a) == shown(tree, tmp_path) == "something"
    node = tree.model.nodes[str(a)]
    # Only the display is derived: the folder's own check still has no data to load.
    assert node.report is not None and node.report.status == "unknown"
    assert status_icon(tree, a) == StatusIcons.ICONS_STATUS["something"].cacheKey()
    index = tree.model.path_index(str(a), tree.model.COLUMN_STATUS_ICON)
    tooltip = index.data(Qt.ItemDataRole.ToolTipRole)
    assert "\nHere: no TXY files\nSubfolders: 1 · TXY data in 1\nFolder modified: " in tooltip


def test_nothing_only_when_every_subfolder_was_checked_and_has_nothing(
    qtbot: QtBot, tree: FolderExplorer, tmp_path: Path,
) -> None:
    a = tmp_path / "A"
    (a / "B").mkdir(parents=True)
    (a / "C").mkdir()
    browse(qtbot, tree, tmp_path)
    browse(qtbot, tree, a)
    assert shown(tree, a) == "unknown"  # No subfolder checked yet.
    browse(qtbot, tree, a / "B")
    assert shown(tree, a / "B") == "nothing"
    assert shown(tree, a) == "unknown"  # C is still unchecked.
    browse(qtbot, tree, a / "C")
    assert shown(tree, a) == shown(tree, tmp_path) == "nothing"


def test_recheck_follows_the_subfolders_current_status(qtbot: QtBot, tree: FolderExplorer, tmp_path: Path) -> None:
    a = tmp_path / "A"
    a.mkdir()
    data_folder(a / "B", subfolder=False)
    browse(qtbot, tree, tmp_path)
    browse(qtbot, tree, a)
    browse(qtbot, tree, a / "B")
    assert shown(tree, a) == "something"
    for file in (a / "B").iterdir():
        file.unlink()
    browse(qtbot, tree, a / "B", force=True)
    assert shown(tree, a / "B") == shown(tree, a) == "nothing"


def test_own_data_wins_over_subfolders(qtbot: QtBot, tree: FolderExplorer, tmp_path: Path) -> None:
    a = tmp_path / "A"
    data_folder(a)  # Data in A itself, plus an empty subfolder "run".
    browse(qtbot, tree, tmp_path)
    browse(qtbot, tree, a)
    browse(qtbot, tree, a / "run")
    assert shown(tree, a / "run") == "nothing"
    assert shown(tree, a) == "ok"


def test_derived_status_may_be_outdated_when_its_subfolder_is(
    qtbot: QtBot, tree: FolderExplorer, tmp_path: Path,
) -> None:
    a = tmp_path / "A"
    a.mkdir()
    data_folder(a / "B", subfolder=False)
    browse(qtbot, tree, tmp_path)
    browse(qtbot, tree, a)
    browse(qtbot, tree, a / "B")
    node = tree.model.nodes[str(a)]
    assert node.subtree == "something" and not node.subtree_older
    later = time.time() + 60
    tree.model.observe_modified(str(a / "B"), later, later)
    assert node.subtree_older and tree.model.nodes[str(tmp_path)].subtree_older
    assert status_icon(tree, a) == StatusIcons.ICONS_STATUS_OLDER["something"].cacheKey()
    tooltip = str(tree.model.path_index(str(a)).data(Qt.ItemDataRole.ToolTipRole)).splitlines()
    assert "Subfolders: 1 · TXY data in 1 · may be outdated" in tooltip
    assert tooltip[-1] == "Select the outdated subfolder to check it again."


def save_queued_subtrees(qtbot: QtBot, explorer: FolderExplorer) -> list[str]:
    """Run the queued batched save of derived statuses with the real helper."""
    service = explorer.model.cache.service
    qtbot.waitUntil(lambda: any(r.operation == "subtree_save" for r in service.pending))
    request = next(r for r in service.pending if r.operation == "subtree_save")
    save_subtrees(request.payload["cache"], request.payload["records"],
                  lambda event: service.resultReady.emit(request, event))
    service.resultReady.emit(request, {"kind": "done"})
    service.pending.remove(request)
    return [record["path"] for record in request.payload["records"]]


def restart(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, explorer: FolderExplorer, root: Path) -> FolderExplorer:
    """A new session: no memory, only the disk cache (shared through the test's cache folder)."""
    explorer.close_cleanup()
    explorer.model.cache.service.shutdown()
    service = frozen_service(monkeypatch)
    restarted = FolderExplorer(str(root), str(root), str(root), [0, 4, 5])
    qtbot.addWidget(restarted)
    assert restarted.model.cache.service is service and not restarted.model.cache.subtrees
    qtbot.waitUntil(lambda: ("list", str(root)) in restarted.model.cache.jobs)
    return restarted


def test_derived_status_survives_restart_without_listing_the_folder(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tree: FolderExplorer, tmp_path: Path,
) -> None:
    a = tmp_path / "A"
    a.mkdir()
    data_folder(a / "B", subfolder=False)
    browse(qtbot, tree, tmp_path)
    browse(qtbot, tree, a)
    browse(qtbot, tree, a / "B")
    # B's background details scan saves its summary (a names-only listing does not).
    scan(str(a / "B"), lambda event: None, tree.model._cache_options)
    assert set(save_queued_subtrees(qtbot, tree)) == {str(a), str(tmp_path)}
    with stores._cache_store(tree.model._cache_options["directory"],
                             [str(a), str(tmp_path)]) as store:
        for path in (str(a), str(tmp_path)):
            saved = store.read_record("subtrees", path).value
            assert saved is not None
            store.save_record("subtrees", path, {**saved, "identity": [999, 888]},
                              store.guard([path], ("subtrees",)))
    restarted = restart(qtbot, monkeypatch, tree, tmp_path)
    browse(qtbot, restarted, tmp_path)
    node = restarted.model.nodes[str(a)]
    # A is not listed: its saved derivation shows, marked as saved.
    assert not node.children and shown(restarted, a) == "something" and not node.subtree_live
    index = restarted.model.path_index(str(a), restarted.model.COLUMN_STATUS_ICON)
    tooltip = index.data(Qt.ItemDataRole.ToolTipRole)
    assert "\nSubfolders: 1 · TXY data in 1 · saved " in tooltip and "Select the folder to check it again." in tooltip
    # The listed root shows its own saved derivation until a subfolder is checked here.
    assert shown(restarted, tmp_path) == "something"
    # Expanding derives it again from B's saved summary, without listing B.
    browse(qtbot, restarted, a)
    assert shown(restarted, a) == "something" and node.subtree_live
    assert ("list", str(a / "B")) not in restarted.model.cache.jobs
    restarted.close_cleanup()


def test_saved_derivation_follows_a_recheck_and_folder_changes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tree: FolderExplorer, tmp_path: Path,
) -> None:
    a = tmp_path / "A"
    a.mkdir()
    data_folder(a / "B", subfolder=False)
    browse(qtbot, tree, tmp_path)
    browse(qtbot, tree, a)
    browse(qtbot, tree, a / "B")
    save_queued_subtrees(qtbot, tree)
    for file in (a / "B").iterdir():
        file.unlink()
    browse(qtbot, tree, a / "B", force=True)
    assert shown(tree, a) == "nothing"
    assert str(a) in save_queued_subtrees(qtbot, tree)
    restarted = restart(qtbot, monkeypatch, tree, tmp_path)
    browse(qtbot, restarted, tmp_path)
    node = restarted.model.nodes[str(a)]
    assert shown(restarted, a) == "nothing" and not node.subtree_older
    # A changed after the derivation (e.g. a new subfolder): the saved result may be outdated.
    later = time.time() + 60
    restarted.model.observe_modified(str(a), later, later)
    assert node.subtree_older
    assert status_icon(restarted, a) == StatusIcons.ICONS_STATUS_OLDER["nothing"].cacheKey()
    restarted.close_cleanup()


def test_saved_subtree_uses_folder_mtime_in_both_directions(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tree: FolderExplorer, tmp_path: Path,
) -> None:
    a = tmp_path / "A"
    a.mkdir()
    data_folder(a / "B", subfolder=False)
    browse(qtbot, tree, tmp_path)
    browse(qtbot, tree, a)
    browse(qtbot, tree, a / "B")
    # The parent's details pass supplies A's mtime after the first derivation.
    replay(qtbot, tree.model.cache, str(tmp_path), "details",
           lambda send: scan(str(tmp_path), send, tree.model._cache_options))
    save_queued_subtrees(qtbot, tree)
    restarted = restart(qtbot, monkeypatch, tree, tmp_path)
    browse(qtbot, restarted, tmp_path)
    node = restarted.model.nodes[str(a)]
    saved_modified = node.subtree_info["modified"] if node.subtree_info else None
    assert isinstance(saved_modified, float)
    restarted.model.observe_modified(str(a), saved_modified, time.time() + 60)
    assert shown(restarted, a) == "something" and not node.subtree_older
    restarted.model.observe_modified(str(a), saved_modified - 60, time.time() + 120)
    assert node.subtree_older
    assert status_icon(restarted, a) == StatusIcons.ICONS_STATUS_OLDER["something"].cacheKey()
    restarted.close_cleanup()


def test_partial_listing_keeps_saved_derivation_with_clock_after_child_recheck(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tree: FolderExplorer, tmp_path: Path,
) -> None:
    a = tmp_path / "A"
    a.mkdir()
    data_folder(a / "B", subfolder=False)
    (a / "C").mkdir()
    browse(qtbot, tree, tmp_path)
    browse(qtbot, tree, a)
    browse(qtbot, tree, a / "B")
    scan(str(a / "B"), lambda event: None, tree.model._cache_options)
    save_queued_subtrees(qtbot, tree)
    restarted = restart(qtbot, monkeypatch, tree, tmp_path)
    browse(qtbot, restarted, tmp_path)
    browse(qtbot, restarted, a)
    assert shown(restarted, a) == "something"
    for file in (a / "B").iterdir():
        file.unlink()
    browse(qtbot, restarted, a / "B", force=True)
    node = restarted.model.nodes[str(a)]
    assert shown(restarted, a) == "something" and node.subtree_older and not node.subtree_live
    assert not any(record["path"] == str(a) and not record["status"]
                   for record in restarted.model.cache._subtree_pending.values())
    browse(qtbot, restarted, a / "C")
    assert shown(restarted, a) == "nothing" and node.subtree_live
    restarted.close_cleanup()


def test_other_tabs_show_a_newly_derived_status(qtbot: QtBot, tree: FolderExplorer, tmp_path: Path) -> None:
    a = tmp_path / "A"
    a.mkdir()
    data_folder(a / "B", subfolder=False)
    browse(qtbot, tree, tmp_path)
    other = FolderExplorer(str(tmp_path), str(tmp_path), str(tmp_path), [0, 4, 5])
    qtbot.addWidget(other)
    qtbot.waitUntil(lambda: str(a) in other.model.nodes)
    assert shown(other, a) != "something"
    browse(qtbot, tree, a)
    browse(qtbot, tree, a / "B")
    qtbot.waitUntil(lambda: shown(other, a) == "something")
    other.close_cleanup()


def test_saved_summary_decides_whether_an_unlisted_folder_is_expandable(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tree: FolderExplorer, tmp_path: Path,
) -> None:
    leaf, parent, unknown = tmp_path / "leaf", tmp_path / "parent", tmp_path / "unknown"
    data_folder(leaf, subfolder=False)
    data_folder(parent)  # Has the subfolder "run".
    unknown.mkdir()
    browse(qtbot, tree, tmp_path)
    for path in (leaf, parent):
        scan(str(path), lambda event: None, tree.model._cache_options)
    restarted = restart(qtbot, monkeypatch, tree, tmp_path)
    browse(qtbot, restarted, tmp_path)
    model = restarted.model

    def expandable(path: Path) -> bool:
        return model.hasChildren(model.path_index(str(path)))
    assert not expandable(leaf) and not model.canFetchMore(model.path_index(str(leaf)))
    assert expandable(parent) and expandable(unknown)  # Unknown stays expandable until listed.
    # A subfolder appears; selecting the row lists it and the arrow returns.
    (leaf / "new").mkdir()
    restarted.tree.setCurrentIndex(model.path_index(str(leaf)))
    qtbot.waitUntil(lambda: ("list", str(leaf)) in model.cache.jobs)
    replay(qtbot, model.cache, str(leaf), "list",
           lambda send: list_folder(str(leaf), send, model._cache_options))
    assert expandable(leaf) and model.nodes[str(leaf)].has_dirs
    restarted.close_cleanup()


def test_tooltips_share_one_layout_for_leaf_and_busy_folders(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tree: FolderExplorer, tmp_path: Path,
) -> None:
    leaf = tmp_path / "leaf"
    data_folder(leaf, subfolder=False)
    browse(qtbot, tree, tmp_path)
    scan(str(leaf), lambda event: None, tree.model._cache_options)
    restarted = restart(qtbot, monkeypatch, tree, tmp_path)
    browse(qtbot, restarted, tmp_path)
    model = restarted.model

    def tooltip() -> str:
        return str(model.path_index(str(leaf), model.COLUMN_STATUS_ICON).data(Qt.ItemDataRole.ToolTipRole))
    # Unlisted, known from its saved summary to have no subfolders.
    saved = tooltip().splitlines()
    assert saved[1:3] == ["Here: 2 shots, all converted", "Subfolders: none"]
    assert saved[3].startswith("Folder modified: 20")
    # The .helab-root it uses: the tab's folder (the test's data root) holds it.
    assert saved[4] == f"Data root: {tmp_path.name} · {tmp_path / '.helab-root'}"
    assert saved[5].startswith("Status cache: ") and saved[5].endswith(") · folder not modified since")
    assert saved[6:] == ["Select the folder to check it again."]
    # Busy: a start time (an open tooltip is not rebuilt while the mouse rests), no outdated hint or action.
    model.request_scan(str(leaf), priority=True)
    qtbot.waitUntil(lambda: ("list", str(leaf)) in model.cache.jobs)
    model.cache.service.resultReady.emit(producer(model.cache, str(leaf), "list"), {"kind": "started"})
    busy = tooltip().splitlines()
    assert busy[1].startswith("Listing folder… since ") and busy[1].endswith("· showing last results")
    assert busy[2:4] == ["Here: 2 shots, all converted", "Subfolders: none"] and "Select the folder" not in busy[-1]
    replay(qtbot, model.cache, str(leaf), "list", lambda send: list_folder(str(leaf), send, model._cache_options))
    lines = tooltip().splitlines()
    assert lines[1:3] == ["Here: 2 shots, all converted", "Subfolders: none"] and len(lines) == 6
    assert lines[4].startswith("Data root: ")
    assert lines[5].startswith("Status checked: ") and lines[5].endswith(")")  # No freshness note.
    restarted.close_cleanup()


def test_open_tooltip_is_rebuilt_when_its_row_changes(qtbot: QtBot, tree: FolderExplorer, tmp_path: Path) -> None:
    from PyQt6.QtGui import QCursor
    from PyQt6.QtWidgets import QToolTip
    (tmp_path / "a").mkdir()
    browse(qtbot, tree, tmp_path)
    tree.resize(600, 300)
    tree.show()
    qtbot.waitExposed(tree)
    model, view = tree.model, tree.tree
    view.expand(model.path_index(str(tmp_path)))
    index = model.path_index(str(tmp_path / "a"))
    viewport = view.viewport()
    assert viewport is not None
    QCursor.setPos(viewport.mapToGlobal(view.visualRect(index).center()))
    QToolTip.showText(QCursor.pos(), str(index.data(Qt.ItemDataRole.ToolTipRole)), viewport)
    if not QToolTip.isVisible():
        pytest.skip("No tooltip window on this platform")
    assert "Subfolders: not listed yet" in QToolTip.text()
    # Synchronously: the offscreen platform hides tooltips while events run.
    node = model.nodes[str(tmp_path / "a")]
    node.state, node.state_since = "running", time.time()
    model.changed(node)
    assert "Listing folder… since " in QToolTip.text()
    QToolTip.hideText()


def test_entries_sent_again_after_root_discovery_replace_those_streamed_first(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A listing whose folder's key changed (a marker found) sends its names again with the new
    root's records (``replace``): they take the earlier entries' places, not add to them."""
    service = frozen_service(monkeypatch)
    cache = get_folder_cache(service)
    path = str(tmp_path)
    run, other = os.path.join(path, "run"), os.path.join(path, "other")
    assert cache.submit("tab", 0, path, "list", {})
    request = producer(cache, path, "list")
    service.resultReady.emit(request, {"kind": "entries", "entries": [
        {"path": run, "name": "run", "prefs": {}}, {"path": other, "name": "other", "prefs": {}}]})
    service.resultReady.emit(request, {"kind": "entries", "replace": True, "entries": [
        {"path": run, "name": "run", "prefs": {"no_cache": True}}]})
    entries = cache.jobs[("list", path)].entries
    assert [entry["path"] for entry in entries] == [run, other]
    assert entries[0]["prefs"] == {"no_cache": True}
    assert cache.folder_prefs(run)["no_cache"]
    service.shutdown()
