"""Folders with no disk cache by design (no .helab-root above them, or an unsupported mount) get
their status from browsing like any other folder; their scan history stays in session RAM."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterator, cast

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from pytestqt.qtbot import QtBot

from helab import io_helper
from helab.io_helper import list_folder, save_scan_history, scan
from helab.resources.icons import IconsInitUtil, StatusIcons
from helab.utils import cache_paths
from helab.utils.cache_paths import Mount
from helab.utils.cache_store import CacheStore, StoreError
from helab.utils.folder_cache import FolderCache
from helab.utils.io_service import IORequest, IOService
from helab.views.FolderExplorer import FolderExplorer

pytestmark = pytest.mark.no_auto_data_root

Events = list[dict[str, Any]]


def data_folder(path: Path) -> Path:
    path.mkdir(parents=True)
    for shot in (1, 2):
        (path / f"d{shot}.txt").write_text("")
        (path / f"d_txy_forc{shot}.txt").write_text(f"{shot},2,3\n")
    return path


@pytest.fixture(params=["no root", "nfs"])
def ram_only(request: pytest.FixtureRequest, tmp_path: Path,
             monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, Any]]:
    """A data folder with no disk cache by design: no .helab-root above it, or on an NFS mount."""
    data = tmp_path / "data"
    mounts = [Mount("/dev/fake", str(tmp_path), "apfs")]
    if request.param == "nfs":
        mounts.append(Mount("server:/export", str(data), "nfs", True))
    monkeypatch.setattr(cache_paths, "current_mounts", lambda: mounts)
    return data_folder(data / "run"), {"directory": str(tmp_path / "store")}


def assert_no_cached_rows(options: dict[str, Any]) -> None:
    with CacheStore(options["directory"], root_mode=True) as store:
        for table in ("datasets", "folder_summaries", "scan_histories", "subtrees"):
            assert store._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("automatic", [False, True], ids=["details", "automatic"])
def test_scan_of_a_folder_without_disk_cache_runs_and_saves_nothing(
    ram_only: tuple[Path, dict[str, Any]], automatic: bool,
) -> None:
    folder, options = ram_only
    events: Events = []
    scan(str(folder), events.append, options, manual=False, automatic=automatic)
    assert any(event["kind"] == "cache_skipped" for event in events)
    assert [event["mode"] for event in events if event["kind"] == "scan_mode"] == ["metadata", "scan"]
    assert next(event for event in events if event["kind"] == "status")["status"] == "ok"
    assert not any(event["kind"] in ("scan_history_warning", "cache_warning") for event in events)
    assert_no_cached_rows(options)


def test_history_write_of_a_folder_without_disk_cache_is_skipped(
    ram_only: tuple[Path, dict[str, Any]],
) -> None:
    folder, options = ram_only
    events: Events = []
    save_scan_history(options, str(folder), {"operation_id": "x", "revision": 1, "kind": "timeout",
                                             "at": 1.0, "attempts": 1, "reason": "Timed out"},
                      None, events.append)
    assert [event["kind"] for event in events] == ["cache_skipped"]
    assert_no_cached_rows(options)


def test_automatic_scan_with_the_cache_off_runs(tmp_path: Path) -> None:
    # No saved history exists with the cache off: the app's session history is the only one.
    folder = data_folder(tmp_path / "run")
    events: Events = []
    scan(str(folder), events.append, {}, manual=False, automatic=True)
    assert any(event["kind"] == "status" for event in events)
    assert not any(event["kind"] == "scan_history_warning" for event in events)


@pytest.mark.parametrize("automatic", [False, True], ids=["details", "automatic"])
def test_a_cache_that_cannot_open_still_skips_scans_that_are_not_manual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, automatic: bool,
) -> None:
    # A saved failure may exist but can't be read: unknown, never empty.
    folder = data_folder(tmp_path / "run")

    def cannot_open(*args: Any, **kwargs: Any) -> Any:
        raise StoreError("Disk cache could not be opened: unable to open database file")
    monkeypatch.setattr(io_helper, "_cache_store", cannot_open)
    events: Events = []
    scan(str(folder), events.append, {"directory": str(tmp_path / "store")}, manual=False, automatic=automatic)
    assert events[-1] == {"kind": "scan_mode", "mode": "skipped"}
    assert not any(event["kind"] == "status" for event in events)


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
           helper: Callable[[IORequest, Callable[[dict[str, Any]], None]], None],
           end: dict[str, Any] | None = None) -> None:
    """Send a real helper's events for the queued request (it gets the request's payload)."""
    request = producer(cache, path, operation)

    def send(event: dict[str, Any]) -> None:
        cache.service.resultReady.emit(request, event)
    helper(request, send)
    cache.service.resultReady.emit(request, end or {"kind": "done"})
    cache.service.pending.remove(request)
    qtbot.waitUntil(lambda: not any(r.path == path for r in cache._deliveries))


def run_scan(path: str) -> Callable[[IORequest, Callable[[dict[str, Any]], None]], None]:
    return lambda request, send: scan(path, send, request.payload["cache"],
                                      manual=request.payload["scan_manual"],
                                      automatic=request.payload.get("automatic", False))


@pytest.fixture
def tab(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
        ram_only: tuple[Path, dict[str, Any]]) -> Iterator[FolderExplorer]:
    """A tab on the RAM-only folder's parent, whose store is the test's own."""
    IconsInitUtil.initialise_icons()
    folder, options = ram_only
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.store_options", lambda: options)
    service = frozen_service(monkeypatch)
    data_folder(folder.parent / "other")
    root = str(folder.parent)
    explorer = FolderExplorer(root, root, root, [0, 4, 5])
    qtbot.addWidget(explorer)
    cache = explorer.model.cache
    qtbot.waitUntil(lambda: ("list", root) in cache.jobs)
    replay(qtbot, cache, root, "list", lambda _, send: list_folder(root, send, options))
    yield explorer
    explorer.close_cleanup()
    service.shutdown()


def status_icon(explorer: FolderExplorer, path: str) -> int | None:
    icon = explorer.model.path_index(path, explorer.model.COLUMN_STATUS_ICON).data(Qt.ItemDataRole.DecorationRole)
    return None if icon is None else cast(QIcon, icon).cacheKey()


def test_browsing_and_automatic_scans_show_the_status_of_a_folder_without_disk_cache(
    qtbot: QtBot, tab: FolderExplorer, ram_only: tuple[Path, dict[str, Any]],
) -> None:
    folder, options = ram_only
    model, cache = tab.model, tab.model.cache
    run, other = str(folder), str(folder.parent / "other")
    ok = StatusIcons.ICONS_STATUS["ok"].cacheKey()
    # Browse step 1 gives counts and status; step 2 (details) the signature and dates.
    model.request_scan(run, priority=True)
    qtbot.waitUntil(lambda: ("list", run) in cache.jobs)
    replay(qtbot, cache, run, "list", lambda _, send: list_folder(run, send, options))
    node = model.nodes[run]
    assert not node.signature and node.modified is None
    replay(qtbot, cache, run, "details", run_scan(run))
    assert node.signature and node.modified is not None and not node.scan_skipped
    assert status_icon(tab, run) == ok
    # An automatic basic scan.
    model.request_scan(other, metadata_only=True)
    qtbot.waitUntil(lambda: ("scan", other) in cache.jobs)
    assert producer(cache, other, "scan").payload["automatic"]
    replay(qtbot, cache, other, "scan", run_scan(other))
    assert status_icon(tab, other) == ok
    assert not cache.scan_history_errors and not cache.cache_read_errors
    assert not any(request.operation == "scan_history" for request in cache.service.pending)
    assert_no_cached_rows(options)


def test_a_failure_without_disk_cache_stays_in_ram_and_blocks_the_next_automatic_scan(
    qtbot: QtBot, tab: FolderExplorer, ram_only: tuple[Path, dict[str, Any]],
) -> None:
    folder, options = ram_only
    model, cache = tab.model, tab.model.cache
    other = str(folder.parent / "other")
    model.request_scan(other, metadata_only=True)
    qtbot.waitUntil(lambda: ("scan", other) in cache.jobs)

    def timed_out(request: IORequest, send: Callable[[dict[str, Any]], None]) -> None:
        events: Events = []
        scan(other, events.append, options, manual=False, automatic=True)
        for event in events[:events.index({"kind": "scan_mode", "mode": "scan"}) + 1]:
            send(event)  # The helper starts, then stops answering.
    replay(qtbot, cache, other, "scan", timed_out,
           {"kind": "error", "timeout": True, "message": "Timed out after 60 s without progress"})
    assert cache.scan_history(other)["blocked"]
    # Recorded in RAM only: no store write, and no "could not be saved" error (RAM only says so).
    assert not any(request.operation == "scan_history" for request in cache.service.pending)
    assert other not in cache.scan_history_errors
    model.request_scan(other, metadata_only=True)
    assert ("scan", other) not in cache.jobs
    assert not any(request.operation == "scan" for request in cache.service.pending)
    assert_no_cached_rows(options)
