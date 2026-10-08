"""Browsing in two steps: names first (``list``), file details in the background (``details``)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterator, cast
import os
import time

import numpy as np
import pytest
from diskcache import FanoutCache
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from pytestqt.qtbot import QtBot

from helab.io_helper import list_folder, load, save_subtrees, scan
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
    entries = [entry for event in events if event["kind"] == "entries" for entry in event["entries"]]
    assert [(entry["path"], entry["name"]) for entry in entries] == [(str(source / "run"), "run")]
    # Saved cache metadata comes along; dates and identities need a stat (step 2).
    assert {"scan_history", "scan_status", "disk_cached", "cache_info"} <= set(entries[0])
    assert not {"modified", "identity"} & set(entries[0])
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
    check_events: list[dict[str, Any]] = []
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
    # The details Refresh cancelled run again once it finishes.
    assert cache.has_request(explorer.model.owner, "details", child)
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


# Near-term fix (roadmaps/_readme.md): while a tab refreshes, it ignores
# results other tabs finish. `_shared_snapshot_changed` applies them through
# `request_scan(automatic=True)`, which Refresh blocks so it starts no new
# checks; that also blocks results already in memory, which need no I/O. The
# planned fix is a separate no-I/O path for in-memory results, also useful for
# cache-only browsing (roadmaps/cache-only-browsing.md). Remove these markers then;
# strict xfail fails as soon as the behaviour is fixed.
SHARED_RESULTS_DURING_REFRESH = pytest.mark.xfail(
    strict=True, reason="Refresh blocks other tabs' in-memory results; needs no-I/O replay (roadmaps/_readme.md)")


def check_in_other_tab(qtbot: QtBot, cache: FolderCache, path: str, options: dict[str, Any]) -> None:
    assert cache.submit("other-tab", 0, path, "scan", {"metadata_only": True}, force=True)
    replay(qtbot, cache, path, "scan", lambda send: scan(path, send, options))


@SHARED_RESULTS_DURING_REFRESH
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


@SHARED_RESULTS_DURING_REFRESH
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
    assert all(node.modified is not None and node.identity is not None for node in nodes)
    assert all(node.report is not None for node in nodes)
    explorer.close_cleanup()
    service.shutdown()


def test_saved_summary_of_a_replaced_folder_is_dropped_by_details(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
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
    os.rename(child, tmp_path / "old-run")
    data_folder(child, subfolder=False)
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    replay(qtbot, cache, path, "list", lambda send: list_folder(path, send, options))
    node = explorer.model.nodes[str(child)]
    assert node.report is not None  # Saved summary shown provisionally.
    replay(qtbot, cache, path, "details", lambda send: scan(path, send, options))
    stat = child.stat()
    assert node.identity == [stat.st_dev, stat.st_ino] and node.report is None
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
    assert saved[4].startswith("Status cache: ") and saved[4].endswith(") · folder not modified since")
    assert saved[5:] == ["Select the folder to check it again."]
    # Busy: a start time (an open tooltip is not rebuilt while the mouse rests), no outdated hint or action.
    model.request_scan(str(leaf), priority=True)
    qtbot.waitUntil(lambda: ("list", str(leaf)) in model.cache.jobs)
    model.cache.service.resultReady.emit(producer(model.cache, str(leaf), "list"), {"kind": "started"})
    busy = tooltip().splitlines()
    assert busy[1].startswith("Listing folder… since ") and busy[1].endswith("· showing last results")
    assert busy[2:4] == ["Here: 2 shots, all converted", "Subfolders: none"] and "Select the folder" not in busy[-1]
    replay(qtbot, model.cache, str(leaf), "list", lambda send: list_folder(str(leaf), send, model._cache_options))
    lines = tooltip().splitlines()
    assert lines[1:3] == ["Here: 2 shots, all converted", "Subfolders: none"] and len(lines) == 5
    assert lines[4].startswith("Status checked: ") and lines[4].endswith(")")  # No freshness note.
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
