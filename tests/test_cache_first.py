"""Cached data shows at once from the local disk cache; the folder check follows."""
from __future__ import annotations

import math
import os
from pathlib import Path
import time
from typing import Any, Iterator

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from helab.io_helper import load, read_cached
from helab.utils.folder_cache import FolderCache
from helab.utils.io_service import FOREGROUND, LOCAL, IORequest, IOService
from helab.views.FolderExplorer import FolderExplorer


def cache_options(tmp_path: Path) -> dict[str, Any]:
    return {"directory": str(tmp_path / "disk-cache")}


def source_folder(tmp_path: Path, shots: int = 2) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    for shot in range(1, shots + 1):
        (source / f"d_txy_forc{shot}.txt").write_text(f"{shot},2,3\n")
    return source


def run_load(source: Path, tmp_path: Path, **kwargs: Any) -> list[dict[str, Any]]:
    output = tmp_path / f"artifacts-{time.monotonic_ns()}"
    output.mkdir()
    events: list[dict[str, Any]] = []
    load(str(source), str(output), events.append, cache_options(tmp_path), **kwargs)
    return events


def loaded(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next(event for event in events if event["kind"] == "loaded")


def guard_source(monkeypatch: pytest.MonkeyPatch, source: Path, *, folder_stat: bool,
                 files: tuple[str, ...] = ()) -> list[str]:
    """Record source access (``files``: the names that may be stat'ed); the cache folder is
    elsewhere and stays usable."""
    calls: list[str] = []
    real_scandir, real_stat = os.scandir, os.stat

    def scandir(path: Any = ".") -> Any:
        if str(path).startswith(str(source)):
            calls.append(f"scandir {path}")
            raise AssertionError("listed the source folder")
        return real_scandir(path)

    def stat(path: Any, *args: Any, **kwargs: Any) -> Any:
        if str(path).startswith(str(source)) and not (folder_stat and str(path) == str(source)) and not (
                os.path.dirname(str(path)) == str(source) and os.path.basename(str(path)) in files):
            calls.append(f"stat {path}")
            raise AssertionError("checked a source file")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr("os.scandir", scandir)
    monkeypatch.setattr("os.stat", stat)
    return calls


def test_cached_read_never_touches_the_source_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = source_folder(tmp_path)
    first = loaded(run_load(source, tmp_path))
    output = tmp_path / "cached"
    output.mkdir()
    events: list[dict[str, Any]] = []
    with monkeypatch.context() as patched:
        guard_source(patched, source, folder_stat=False)
        read_cached(str(source), str(output), events.append, cache_options(tmp_path))
    shots = {event["shot"]: np.load(event["artifact"]) for event in events if event["kind"] == "shot"}
    assert sorted(shots) == [1, 2]
    np.testing.assert_array_equal(shots[2], [[2, 2, 3]])
    result = loaded(events)
    assert result["verified"] is False and result["source"] == "disk"
    assert result["signature"] == first["signature"]
    assert result["files"] == result["total_files"] == 2


def test_cached_partial_load_progress_counts_unreadable_files(tmp_path: Path) -> None:
    source = source_folder(tmp_path)
    (source / "d_txy_forc2.txt").write_text("not,numeric,data\n")
    first = loaded(run_load(source, tmp_path))
    assert first["files"] == 1 and first["failed_files"] == 1
    output = tmp_path / "cached"
    output.mkdir()
    events: list[dict[str, Any]] = []
    read_cached(str(source), str(output), events.append, cache_options(tmp_path))
    progress = [event for event in events if event["kind"] == "progress"]
    assert progress[-1] == {"kind": "progress", "progress": 1.0, "checked_files": 2,
                               "loaded_files": 1, "total_files": 2, "failed_files": 1,
                               "unsettled_files": 0}


def test_check_of_cached_data_is_one_folder_stat_until_the_folder_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    source = source_folder(tmp_path)
    first = loaded(run_load(source, tmp_path))
    memory = [list(entry) for entry in first["fingerprint"]]
    with monkeypatch.context() as patched:
        # The folder, and its first and last cached files (another folder moved here differs).
        calls = guard_source(patched, source, folder_stat=True, files=("d_txy_forc1.txt", "d_txy_forc2.txt"))
        events = run_load(source, tmp_path, memory=memory, base_signature=first["signature"])
    assert not calls
    result = loaded(events)
    assert result["unchanged"] and result["memory_shots"] == [1, 2]
    assert result["signature"] == first["signature"]
    # Adding a file modifies the folder: the next check lists and reads only the new file.
    (source / "d_txy_forc3.txt").write_text("3,2,3\n")
    later = time.time() + 10
    os.utime(source, (later, later))
    events = run_load(source, tmp_path, memory=memory, base_signature=first["signature"])
    result = loaded(events)
    assert not result.get("unchanged")
    assert result["load_counts"]["new_loaded"] == 1 and result["load_counts"]["reused_memory"] == 2
    # Time left is estimated from the bytes actually read: shots held in memory are not counted.
    progress = [event for event in events if event["kind"] == "progress"]
    new_size = (source / "d_txy_forc3.txt").stat().st_size
    assert progress[0]["read_bytes"] == 0 and progress[0]["total_read_bytes"] == new_size
    assert progress[-1]["read_bytes"] == new_size
    # A different expected signature (the folder changed this session) never takes the shortcut.
    result = loaded(run_load(source, tmp_path, memory=memory, base_signature=first["signature"],
                             expected="changed"))
    assert not result.get("unchanged")


def test_older_folder_moved_into_a_cached_path_is_not_taken_for_it(tmp_path: Path) -> None:
    """A moved folder keeps its older mtime, so the folder stat alone would pass."""
    source = source_folder(tmp_path)
    first = loaded(run_load(source, tmp_path))
    memory = [list(entry) for entry in first["fingerprint"]]
    older = tmp_path / "older"
    older.mkdir()
    (older / "d_txy_forc9.txt").write_text("9,2,3\n")
    past = time.time() - 3600
    os.utime(older / "d_txy_forc9.txt", (past, past))
    os.utime(older, (past, past))
    source.rename(tmp_path / "moved-away")
    older.rename(source)
    events = run_load(source, tmp_path, memory=memory, base_signature=first["signature"])
    # Its shots 1 and 2 are missing: nothing is read until the user says to load it as it is.
    missing = next(event for event in events if event["kind"] == "shots_missing")
    assert missing["missing"] == [1, 2] and missing["listed_count"] == 1
    assert not any(event["kind"] in ("loaded", "shot") for event in events)
    result = loaded(run_load(source, tmp_path, memory=memory, base_signature=first["signature"],
                             allow_missing=True))
    assert not result.get("unchanged") and result["memory_shots"] == []
    assert [entry[0] for entry in result["fingerprint"]] == [9]


def test_full_check_finds_a_file_rewritten_in_place(tmp_path: Path) -> None:
    """Rewriting a file doesn't modify its folder: unless the quick check samples that file,
    only a full check (Retry / Refresh) sees it."""
    source = source_folder(tmp_path, shots=3)
    first = loaded(run_load(source, tmp_path))
    memory = [list(entry) for entry in first["fingerprint"]]
    folder = source.stat()
    (source / "d_txy_forc2.txt").write_text("2,2,3\n2,5,6\n")
    later = time.time() + 10
    os.utime(source / "d_txy_forc2.txt", (later, later))
    os.utime(source, ns=(folder.st_atime_ns, folder.st_mtime_ns))
    # Fast checks only the first and last files: it misses this one (Medium would sample it here).
    assert loaded(run_load(source, tmp_path, memory=memory, base_signature=first["signature"],
                           check_level="fast"))["unchanged"]
    result = loaded(run_load(source, tmp_path, memory=memory, base_signature=first["signature"],
                             full_check=True))
    assert not result.get("unchanged") and result["signature"] != first["signature"]
    assert result["load_counts"]["modified_loaded"] == 1 and result["load_counts"]["reused_memory"] == 2


@pytest.mark.parametrize("newline", [None, "\n", "\r\n"], ids=["native", "lf", "crlf"])
def test_files_still_being_written_are_left_for_the_next_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, newline: str | None,
) -> None:
    monkeypatch.setattr("helab.io_helper.SETTLE_SECONDS", 60.0)
    source = source_folder(tmp_path)
    settled_file = source / "d_txy_forc1.txt"
    settled_file.write_text("1,2,3\n", newline=newline)
    settled_bytes = settled_file.stat().st_size
    old = time.time() - 120
    os.utime(settled_file, (old, old))  # Shot 2 was just written.
    events = run_load(source, tmp_path)
    result = loaded(events)
    assert [event["shot"] for event in events if event["kind"] == "shot"] == [1]
    assert result["files"] == 1 and result["total_files"] == 2 and result["unsettled_files"] == 1
    assert result["failed_files"] == 0
    progress = [event for event in events if event["kind"] == "progress"]
    assert progress[0]["checked_files"] == 1 and progress[0]["unsettled_files"] == 1
    assert progress[-1] == {"kind": "progress", "progress": 1.0, "checked_files": 2,
                           "loaded_files": 1, "total_files": 2, "failed_files": 0, "unsettled_files": 1,
                           # Only the settled file is read, so only its bytes count towards the estimate.
                           "read_bytes": settled_bytes, "read_files": 1, "total_read_bytes": settled_bytes}
    summary = next(event for event in events if event["kind"] == "scan_summary")["status"]
    assert summary["txy"] == [1, 2] and summary["unsettled"] == 1
    saved = next(event for event in events if event["kind"] == "cache_saved")["cache_info"]
    assert saved["unsettled"] == 1
    output = tmp_path / "cached-unsettled"
    output.mkdir()
    cached_events: list[dict[str, Any]] = []
    read_cached(str(source), str(output), cached_events.append, cache_options(tmp_path))
    cached_progress = [event for event in cached_events if event["kind"] == "progress"][-1]
    # Cached reads give the same counts; they read no TXY files, so they have no read counters.
    assert cached_progress == {key: value for key, value in progress[-1].items()
                               if "bytes" not in key and key != "read_files"}
    # A cache with unsettled files is always checked fully, even if the folder is unmodified.
    memory = [list(entry) for entry in result["fingerprint"]]
    os.utime(source, (old, old))
    os.utime(source / "d_txy_forc2.txt", (old, old))
    result = loaded(run_load(source, tmp_path, memory=memory, base_signature=result["signature"]))
    assert not result.get("unchanged")
    assert result["load_counts"]["new_loaded"] == 1 and result["unsettled_files"] == 0


def test_file_growing_while_read_is_not_kept(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from helab import io_helper
    source = source_folder(tmp_path)
    growing = source / "d_txy_forc2.txt"
    read_file = io_helper._read_txy_file

    def append_after_read(filename: str, reason: str) -> Any:
        frame = read_file(filename, reason)
        if str(filename) == str(growing):
            with open(growing, "a") as file:
                file.write("4,5,6\n")
        return frame

    monkeypatch.setattr(io_helper, "_read_txy_file", append_after_read)
    events = run_load(source, tmp_path)
    result = loaded(events)
    assert [event["shot"] for event in events if event["kind"] == "shot"] == [1]
    assert result["files"] == 1 and result["unsettled_files"] == 1 and result["failed_files"] == 0
    progress = [event for event in events if event["kind"] == "progress"][-1]
    assert progress["checked_files"] == 2 and progress["unsettled_files"] == 1
    assert progress["failed_files"] == 0
    # Its earlier fingerprint is kept, so the finished file reads as modified next time.
    assert [entry[0] for entry in result["fingerprint"]] == [1, 2]
    monkeypatch.undo()
    memory = [list(entry) for entry in result["fingerprint"] if entry[0] == 1]
    result = loaded(run_load(source, tmp_path, memory=memory, base_signature=result["signature"]))
    assert result["load_counts"]["modified_loaded"] == 1 and result["unsettled_files"] == 0


def test_cached_reads_run_beside_busy_foreground_and_background_lanes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_run", lambda request: None)
    service.is_foreground = lambda request: request.owner == "tab"
    service.submit("tab", 0, "/browse", "list")
    service.submit("tab", 0, "/data", "load")
    service.submit("other-tab", 0, "/other", "load")
    service.submit("bulk", 0, "/bulk", "scan")
    lanes = {r.path: r.lane for r in service.active}
    # Background work waits while the foreground works.
    assert lanes == {"/browse": FOREGROUND, "/data": FOREGROUND}
    assert {r.path for r in service.pending} == {"/other", "/bulk"}
    service.submit("tab", 0, "/cached", "cached")
    reads = [r for r in service.active if r.operation == "cached"]
    assert [r.lane for r in reads] == [LOCAL]
    service._apply_pauses(time.monotonic())
    assert not reads[0].pause_requested  # Never paused by foreground work.
    assert "Reading cached data" in service.activity_summary()
    service.shutdown()


@pytest.fixture
def browser(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FolderExplorer]:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    (tmp_path / "d_txy_forc1.txt").write_text("1,2,3\n")
    explorer = FolderExplorer(str(tmp_path), str(tmp_path), str(tmp_path), [0, 4, 5])
    qtbot.addWidget(explorer)
    explorer.selectionPathChanged.connect(lambda p: explorer.load_to_ram_cache(p))
    yield explorer
    explorer.close_cleanup()
    service.shutdown()


def producer(cache: FolderCache, path: str, operation: str) -> IORequest:
    job = cache.jobs[(operation, path)]
    return next(r for r in cache.service.pending if r.owner == job.owner)


def show_cached(browser: FolderExplorer, qtbot: QtBot, path: str) -> tuple[str, IORequest]:
    """List the folder, then let the cached read deliver; returns the signature and the check."""
    cache = browser.model.cache
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    listing = producer(cache, path, "list")
    signature = "cached-signature"
    # A names-only listing: no signature or dates, so nothing confirms the cache yet.
    cache.service.resultReady.emit(listing, {
        "kind": "status", "status": "warning", "count": 1, "details": False, "raw": [], "txy": [1],
        "disk_cached": True,
        "cache_info": {"saved_at": time.time() - 60, "snapshot_at": time.time() - 60, "signature": signature}})
    cache.service.resultReady.emit(listing, {"kind": "done"})
    cache.service.pending.remove(listing)
    qtbot.waitUntil(lambda: ("cached", path) in cache.jobs)
    # The check runs beside the cached read, counting the cached shots as held.
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs)
    check = producer(cache, path, "load")
    assert check.payload["cache_base"] is True and "memory" not in check.payload
    read = producer(cache, path, "cached")
    fingerprint = [[1, 6, 123]]
    cache.service.resultReady.emit(read, {"kind": "shot", "shot": 1, "array": np.ones((1, 3)),
                                          "fingerprint": fingerprint[0]})
    cache.service.resultReady.emit(read, {
        "kind": "loaded", "signature": signature, "files": 1, "total_files": 1, "failed_files": 0,
        "rows": 1, "bytes": 24, "problematic": [], "source": "disk", "cached": True, "disk_cached": True,
        "disk_cache_pending": False, "cache_info": cache.cache_status(path).info, "verified": False,
        "fingerprint": fingerprint, "memory_shots": [], "load_counts": {"reused_disk": 1, "read": 0}})
    cache.service.pending.remove(read)
    assert producer(cache, path, "load") is check  # Still the one check.
    return signature, check


def test_cached_data_shows_before_the_folder_check_and_keeps_its_source(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    path = str(tmp_path)
    signature, check = show_cached(browser, qtbot, path)
    browser._update_activity()
    assert browser.folder_opened_data is not None and browser.folder_opened_path == path
    assert browser.folder_summary_label.text() == "1 TXY found · 1 loaded (cached)"
    assert browser.folder_cache_label.text().startswith("Cached data loaded · Cached 1m ago")
    assert browser.folder_cache_label.text().endswith("Checking for changes…")
    service = browser.model.cache.service
    service.resultReady.emit(check, {"kind": "started"})
    service.resultReady.emit(check, {"kind": "load_source", "source": "memory", "cache_reason": ""})
    service.resultReady.emit(check, {
        "kind": "loaded", "unchanged": True, "signature": signature, "memory_shots": [1],
        "base_signature": signature,
        "modified": time.time() - 90,
        "fingerprint": [[1, 6, 123]], "files": 1, "total_files": 1, "failed_files": 0, "rows": 0,
        "bytes": 0, "problematic": [], "source": "memory", "cached": True, "disk_cached": True,
        "disk_cache_pending": False, "cache_info": browser.model.cache.cache_status(path).info,
        "load_counts": {"reused_memory": 1, "read": 0}})
    service.pending.remove(check)
    browser._update_activity()
    assert not browser.loading
    assert browser.folder_summary_label.text() == "1 TXY found · 1 loaded"
    assert browser.folder_cache_label.text() == "Cached data loaded · Cached 1m ago"
    assert browser.load_source == "disk"  # Checked, still from the disk cache.


def test_failed_check_keeps_cached_data_with_retry(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    path = str(tmp_path)
    _, check = show_cached(browser, qtbot, path)
    cached = browser.displayed_dataset
    service = browser.model.cache.service
    service.resultReady.emit(check, {"kind": "error", "message": "Timed out after 60 s without progress — Retry"})
    service.pending.remove(check)
    browser._update_activity()
    assert browser.displayed_dataset is cached and browser.folder_opened_path == path
    assert browser.folder_summary_label.text().startswith("1 TXY found · 1 loaded (cached) · Timed out")
    assert browser.folder_cache_label.text().endswith("Check failed")
    assert "Timed out" in browser.folder_cache_label.toolTip()
    assert not browser.retry_button.isHidden()


def test_selecting_a_cached_folder_with_saved_counts_does_not_list_it(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    child = tmp_path / "run"
    child.mkdir()
    (child / "d_txy_forc1.txt").write_text("1,2,3\n")
    cache = browser.model.cache
    path = str(tmp_path)
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    listing = producer(cache, path, "list")
    cache.service.resultReady.emit(listing, {"kind": "entries", "entries": [{
        "path": str(child), "name": "run", "disk_cached": True,
        "cache_info": {"saved_at": time.time() - 60, "signature": "s"},
        "scan_status": {"status": "ok", "count": 1, "raw": [1], "txy": [1], "scanned_at": time.time() - 60,
                        "signature": "s"}}]})
    cache.service.resultReady.emit(listing, {"kind": "status", "status": "unknown", "count": -1, "raw": [],
                                             "txy": [], "has_dirs": True})
    cache.service.resultReady.emit(listing, {"kind": "done"})
    cache.service.pending.remove(listing)
    qtbot.waitUntil(lambda: str(child) in browser.model.nodes)
    browser.tree.setCurrentIndex(browser.model.path_index(str(child)))
    qtbot.waitUntil(lambda: ("cached", str(child)) in cache.jobs)
    assert ("list", str(child)) not in cache.jobs


def test_scan_and_load_agree_while_a_file_is_still_being_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from helab.io_helper import scan
    monkeypatch.setattr("helab.io_helper.SETTLE_SECONDS", 60.0)
    source = source_folder(tmp_path)
    old = time.time() - 120
    os.utime(source / "d_txy_forc1.txt", (old, old))
    statuses: list[dict[str, Any]] = []
    scan(str(source), lambda event: statuses.append(event) if event["kind"] == "status" else None)
    # Otherwise the scan would report a change and drop the data just loaded.
    assert statuses[0]["txy"] == [1, 2] and statuses[0]["unsettled"] == 1
    assert statuses[0]["signature"] == loaded(run_load(source, tmp_path))["signature"]


def test_refresh_checks_shown_data_file_by_file(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    path = str(tmp_path)
    signature, check = show_cached(browser, qtbot, path)
    assert not check.payload["full_check"]  # Selecting: one folder stat may be the whole check.
    service = browser.model.cache.service
    service.resultReady.emit(check, {
        "kind": "loaded", "unchanged": True, "signature": signature, "memory_shots": [1],
        "base_signature": signature,
        "fingerprint": [[1, 6, 123]], "files": 1, "total_files": 1, "failed_files": 0, "rows": 0,
        "bytes": 0, "problematic": [], "source": "memory", "cached": True, "disk_cached": True,
        "disk_cache_pending": False, "cache_info": browser.model.cache.cache_status(path).info,
        "load_counts": {"reused_memory": 1, "read": 0}})
    service.pending.remove(check)
    assert not browser.shows_unchecked(path)
    browser.refresh_folder(path)
    qtbot.waitUntil(lambda: ("load", path) in browser.model.cache.jobs)
    assert producer(browser.model.cache, path, "load").payload["full_check"] is True
    assert browser.shows_unchecked(path)  # "Checking for changes…" until it completes.
    assert not browser._full_check_paths  # Only this check, not later ones.


def test_cached_read_finishing_after_a_removal_is_not_marked_cached(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    """Settings → Cache cleared the folder while its cached read ran (they share the local lane)."""
    path = str(tmp_path)
    cache = browser.model.cache
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    listing = producer(cache, path, "list")
    cache.service.resultReady.emit(listing, {
        "kind": "status", "status": "warning", "count": 1, "details": False, "raw": [], "txy": [1],
        "disk_cached": True, "cache_info": {"saved_at": time.time() - 60, "snapshot_at": time.time() - 60,
                                            "signature": "cached-signature"}})
    cache.service.resultReady.emit(listing, {"kind": "done"})
    cache.service.pending.remove(listing)
    qtbot.waitUntil(lambda: ("cached", path) in cache.jobs)
    read = producer(cache, path, "cached")
    info = cache.cache_status(path).info
    cache.removed([path], ["datasets"])
    cache.service.resultReady.emit(read, {"kind": "shot", "shot": 1, "array": np.ones((1, 3)),
                                          "fingerprint": [1, 6, 123]})
    cache.service.resultReady.emit(read, {
        "kind": "loaded", "signature": "cached-signature", "files": 1, "total_files": 1, "failed_files": 0,
        "rows": 1, "bytes": 24, "problematic": [], "source": "disk", "cached": True, "disk_cached": True,
        "disk_cache_pending": False, "cache_info": info, "verified": False,
        "fingerprint": [[1, 6, 123]], "memory_shots": [], "load_counts": {"reused_disk": 1, "read": 0}})
    cache.service.pending.remove(read)
    dataset = browser.displayed_dataset
    assert dataset is not None and dataset.metadata["disk_cached"] is False and dataset.metadata["cache_info"] == {}
    assert not cache.disk_cached(path)


def test_check_finishing_before_the_cached_read_waits_for_its_shots(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    """The check (one folder stat) often beats unpacking the cache: it completes with the read."""
    path = str(tmp_path)
    cache = browser.model.cache
    service = cache.service
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    listing = producer(cache, path, "list")
    info = {"saved_at": time.time() - 60, "snapshot_at": time.time() - 60, "signature": "sig"}
    service.resultReady.emit(listing, {"kind": "status", "status": "warning", "count": 1, "details": False,
                                       "raw": [], "txy": [1], "disk_cached": True, "cache_info": info})
    service.resultReady.emit(listing, {"kind": "done"})
    service.pending.remove(listing)
    qtbot.waitUntil(lambda: ("cached", path) in cache.jobs and ("load", path) in cache.jobs)
    read, check = producer(cache, path, "cached"), producer(cache, path, "load")
    unchanged = {"kind": "loaded", "unchanged": True, "signature": "sig", "base_signature": "sig",
                 "memory_shots": [1], "fingerprint": [[1, 6, 123]], "files": 1, "total_files": 1,
                 "failed_files": 0, "rows": 0, "bytes": 0, "problematic": [], "source": "memory", "cached": True,
                 "disk_cached": True, "disk_cache_pending": False, "cache_info": info,
                 "load_counts": {"reused_memory": 1, "read": 0}}
    service.resultReady.emit(check, unchanged)
    service.resultReady.emit(check, {"kind": "done"})
    assert browser.folder_opened_data is None  # Waiting for the cached shots.
    service.resultReady.emit(read, {"kind": "shot", "shot": 1, "array": np.ones((1, 3)), "fingerprint": [1, 6, 123]})
    service.resultReady.emit(read, {
        "kind": "loaded", "signature": "sig", "files": 1, "total_files": 1, "failed_files": 0, "rows": 1,
        "bytes": 24, "problematic": [], "source": "disk", "cached": True, "disk_cached": True,
        "disk_cache_pending": False, "cache_info": info, "verified": False, "fingerprint": [[1, 6, 123]],
        "memory_shots": [], "load_counts": {"reused_disk": 1, "read": 0}})
    qtbot.waitUntil(lambda: not browser.loading)
    assert browser.folder_opened_data is not None and sorted(browser.folder_opened_data) == [1]
    assert not browser.shows_unchecked(path) and not browser.load_error
    assert ("load", path) not in cache.jobs and ("cached", path) not in cache.jobs


def test_check_waiting_for_a_failed_cached_read_loads_the_files_instead(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    path = str(tmp_path)
    cache = browser.model.cache
    service = cache.service
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    listing = producer(cache, path, "list")
    info = {"saved_at": time.time() - 60, "snapshot_at": time.time() - 60, "signature": "sig"}
    service.resultReady.emit(listing, {"kind": "status", "status": "warning", "count": 1, "details": False,
                                       "raw": [], "txy": [1], "disk_cached": True, "cache_info": info})
    service.resultReady.emit(listing, {"kind": "done"})
    service.pending.remove(listing)
    qtbot.waitUntil(lambda: ("cached", path) in cache.jobs and ("load", path) in cache.jobs)
    read, check = producer(cache, path, "cached"), producer(cache, path, "load")
    service.resultReady.emit(check, {"kind": "loaded", "unchanged": True, "signature": "sig",
                                     "base_signature": "sig", "memory_shots": [1], "fingerprint": [[1, 6, 123]],
                                     "files": 1, "rows": 0, "bytes": 0, "problematic": []})
    service.resultReady.emit(read, {"kind": "error", "message": "Cached dataset invalid"})
    # Its shots never came: that check can't complete, and a load of the files follows.
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs and producer(cache, path, "load") is not check)
    assert producer(cache, path, "load").payload["cache_base"] is False
    assert browser.loading and not browser.load_error


@pytest.mark.parametrize(("level", "count", "checked"), [
    ("swift", 1000, 1), ("fast", 1000, 2), ("medium", 50, 5), ("medium", 1000, 12), ("medium", 2, 2),
    ("high", 50, 12), ("high", 1000, 32), ("high", 5, 5),
])
def test_check_levels_sample_the_ends_and_random_files(level: str, count: int, checked: int) -> None:
    from helab.io_helper import _sample_indices
    first = _sample_indices(count, level)
    assert first is not None and len(first) == checked and len(set(first)) == checked
    assert count - 1 in first and (level == "swift" or 0 in first)
    assert _sample_indices(count, "full") is None


def test_helper_default_check_level_matches_the_settings_default() -> None:
    from helab import io_helper
    from helab.utils import constants
    assert io_helper.DEFAULT_CHECK_LEVEL == constants.DEFAULT_CHECK_LEVEL


def test_full_check_level_always_lists_the_folder(tmp_path: Path) -> None:
    source = source_folder(tmp_path)
    first = loaded(run_load(source, tmp_path))
    memory = [list(entry) for entry in first["fingerprint"]]
    result = loaded(run_load(source, tmp_path, memory=memory, base_signature=first["signature"], check_level="full"))
    assert not result.get("unchanged") and result["memory_shots"] == [1, 2]


MISSING = {"kind": "shots_missing", "missing": [1], "missing_count": 1, "known_count": 1, "listed_count": 1}


@pytest.mark.parametrize("answer", ["load", "dont_load"])
def test_missing_cached_shots_hide_the_cached_data_and_list_the_folder(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path, answer: str,
) -> None:
    path = str(tmp_path)
    _, check = show_cached(browser, qtbot, path)
    service = browser.model.cache.service
    shown = browser.displayed_dataset
    assert shown is not None
    browser.model.cache.retain("another-tab", shown)  # Another tab still shows that data.
    service.resultReady.emit(check, MISSING)
    service.resultReady.emit(check, {"kind": "done"})
    service.pending.remove(check)
    # Not this folder's data, perhaps: no longer shown, and nothing was read.
    assert browser.folder_opened_data is None and browser.displayed_dataset is None and not browser.loading
    assert browser.load_error == "1 cached shot missing — Retry after checking the drive, or Review…"
    cache = browser.model.cache
    assert path in cache.mismatched and cache.latest_dataset(path) is None  # Gone from RAM too.
    entry = cache.mismatched[path]
    assert (entry["missing"], entry["missing_count"], entry["source"], entry["answer"]) == ([1], 1, "load", "")
    # Listed for an answer in the app's one window; one folder holds nothing.
    assert cache.mismatch_count == 1 and not service.mismatch_hold
    qtbot.wait(20)
    assert ("load", path) not in cache.jobs
    if answer == "load":
        browser.load_as_it_is_now(path)
        qtbot.waitUntil(lambda: ("load", path) in cache.jobs)
        load = producer(cache, path, "load")
        # It reads the folder as it is: the dropped shots are neither shown nor sent as held.
        assert load.payload["allow_missing"] is True and "memory" not in load.payload
        assert cache.mismatched[path]["answer"] == "load" and path not in cache.allow_missing  # Used once.
        assert browser.folder_opened_data is None and ("cached", path) not in cache.jobs
        service.resultReady.emit(load, {"kind": "shot", "shot": 9, "array": np.ones((1, 3)),
                                        "fingerprint": [9, 6, 123]})
        service.resultReady.emit(load, {"kind": "loaded", "signature": "now", "files": 1, "rows": 1, "bytes": 24,
                                        "problematic": [], "fingerprint": [[9, 6, 123]]})
        assert browser.folder_opened_data is not None and sorted(browser.folder_opened_data) == [9]
        assert path not in cache.mismatched
    else:
        cache.answer_mismatches([path], "dont_load")
        assert cache.mismatched[path]["answer"] == "dont_load" and browser.load_error
        # Selecting it again shows no cached data; its check finds the shots missing again.
        browser._cache_read_path = None  # As a new selection of the folder does.
        browser.load_to_ram_cache(path, dwell=False, explicit=True)
        assert ("cached", path) not in cache.jobs and browser.folder_opened_data is None
        again = producer(cache, path, "load")
        assert "memory" not in again.payload and again.payload["allow_missing"] is False
        service.resultReady.emit(again, MISSING)
        # The same folder: not counted again, and its answer stands.
        assert cache.mismatch_count == 1 and cache.mismatched[path]["answer"] == "dont_load"


def test_mismatched_folders_are_remembered_up_to_8192_oldest_dropped_first(
    browser: FolderExplorer, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = browser.model.cache
    assert FolderCache.MAX_MISMATCHED == 8192
    monkeypatch.setattr(cache, "MAX_MISMATCHED", 3)
    cache.skip_mismatched = True  # Not about the hold.
    for path in ("/a", "/b", "/c", "/d"):
        cache._mismatch(path)
    cache._mismatch("/b")  # Seen again: now the newest.
    cache._mismatch("/e")
    assert list(cache.mismatched) == ["/d", "/b", "/e"]
    assert cache.mismatch_count == 5  # /b once.


def test_a_cache_saved_without_file_names_gains_them_and_then_takes_the_quick_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import json
    import sqlite3
    source = source_folder(tmp_path)
    first = loaded(run_load(source, tmp_path))
    database = next((tmp_path / "disk-cache").rglob("records.sqlite"))
    with sqlite3.connect(database) as connection:  # As saved before names were kept.
        connection.execute("UPDATE datasets SET info = json_remove(info, '$.names')")
    memory = [list(entry) for entry in first["fingerprint"]]
    check = loaded(run_load(source, tmp_path, memory=memory, base_signature=first["signature"]))
    assert not check.get("unchanged")  # One full check: it lists the folder...
    with sqlite3.connect(database) as connection:
        info = json.loads(connection.execute("SELECT info FROM datasets").fetchone()[0])
    assert info["names"] == ["d_txy_forc1.txt", "d_txy_forc2.txt"]  # ...and records the names.
    with monkeypatch.context() as patched:
        calls = guard_source(patched, source, folder_stat=True, files=("d_txy_forc1.txt", "d_txy_forc2.txt"))
        again = loaded(run_load(source, tmp_path, memory=memory, base_signature=first["signature"]))
    assert not calls and again["unchanged"]



def test_a_full_check_finding_the_cache_complete_brings_the_quick_check_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A folder modified after caching without any TXY change (Finder's .DS_Store, an analysis
    output) gets one full check, which dates the cache's file list from then: the quick check
    is back the next time."""
    import json
    import sqlite3
    source = source_folder(tmp_path)
    first = loaded(run_load(source, tmp_path))
    database = next((tmp_path / "disk-cache").rglob("records.sqlite"))
    now = time.time()
    with sqlite3.connect(database) as connection:  # Cached a while ago...
        connection.execute("UPDATE datasets SET info = json_set(info, '$.snapshot_at', ?, '$.unsettled', 1)",
                           (now - 100,))
    (source / ".DS_Store").write_text("")  # ...and the folder modified since, with no TXY change.
    os.utime(source, (now - 50, now - 50))
    memory = [list(entry) for entry in first["fingerprint"]]
    check = loaded(run_load(source, tmp_path, memory=memory, base_signature=first["signature"]))
    assert not check.get("unchanged") and check["load_counts"]["read"] == 0
    with sqlite3.connect(database) as connection:
        info = json.loads(connection.execute("SELECT info FROM datasets").fetchone()[0])
    assert now - 50 < info["snapshot_at"] <= time.time() and info["unsettled"] == 0
    with monkeypatch.context() as patched:
        calls = guard_source(patched, source, folder_stat=True, files=("d_txy_forc1.txt", "d_txy_forc2.txt"))
        again = loaded(run_load(source, tmp_path, memory=memory, base_signature=first["signature"]))
    assert not calls and again["unchanged"]

def test_a_moved_in_folder_stops_before_the_cache_is_unpacked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    source = source_folder(tmp_path)
    loaded(run_load(source, tmp_path))
    for shot in (1, 2):
        (source / f"d_txy_forc{shot}.txt").unlink()
    (source / "d_txy_forc9.txt").write_text("9,2,3\n")

    def unpack(packed: bytes) -> Any:
        raise AssertionError("the cached dataset was unpacked")
    monkeypatch.setattr("helab.utils.cache_store.unpack_dataset", unpack)
    events = run_load(source, tmp_path)
    missing = next(event for event in events if event["kind"] == "shots_missing")
    assert missing["missing"] == [1, 2] and not any(event["kind"] == "cache_warning" for event in events)


def test_a_cached_read_failing_before_its_check_finishes_loads_the_files(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    path = str(tmp_path)
    cache = browser.model.cache
    service = cache.service
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    listing = producer(cache, path, "list")
    info = {"saved_at": time.time() - 60, "snapshot_at": time.time() - 60, "signature": "sig"}
    service.resultReady.emit(listing, {"kind": "status", "status": "warning", "count": 1, "details": False,
                                       "raw": [], "txy": [1], "disk_cached": True, "cache_info": info})
    service.resultReady.emit(listing, {"kind": "done"})
    service.pending.remove(listing)
    qtbot.waitUntil(lambda: ("cached", path) in cache.jobs and ("load", path) in cache.jobs)
    read, check = producer(cache, path, "cached"), producer(cache, path, "load")
    service.resultReady.emit(read, {"kind": "error", "message": "Cached dataset invalid"})
    service.pending.remove(read)
    qtbot.wait(20)  # The follow-up load runs while the check would still be going.
    # The check counted the cached shots as held: it went, and a load of the files followed.
    assert check.cancelled.is_set() or check not in service.pending
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs and producer(cache, path, "load") is not check)
    assert producer(cache, path, "load").payload["cache_base"] is False
    assert not browser.load_error


def test_a_cached_read_waiting_for_its_volume_runs_once_verification_checks_it(
    browser: FolderExplorer, qtbot: QtBot, tmp_path: Path,
) -> None:
    """A disk swapped in at the same mount must not show the previous disk's cached data: the
    read waits for the volume's verification (the load reads the files meanwhile), then runs."""
    path = str(tmp_path)
    cache = browser.model.cache
    service = cache.service
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    listing = producer(cache, path, "list")
    info = {"saved_at": time.time() - 60, "snapshot_at": time.time() - 60, "signature": "sig"}
    service.resultReady.emit(listing, {"kind": "status", "status": "warning", "count": 1, "details": False,
                                       "raw": [], "txy": [1], "disk_cached": True, "cache_info": info})
    service.resultReady.emit(listing, {"kind": "done"})
    service.pending.remove(listing)
    qtbot.waitUntil(lambda: ("cached", path) in cache.jobs and ("load", path) in cache.jobs)
    read, check = producer(cache, path, "cached"), producer(cache, path, "load")
    assert read.payload["verified_volumes"] == []  # Nothing verified yet this session.
    service.resultReady.emit(read, {"kind": "error", "message": "The volume is not yet verified",
                                    "unverified": True})
    service.pending.remove(read)
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs and producer(cache, path, "load") is not check)
    files_load = producer(cache, path, "load")
    assert files_load.payload["cache_base"] is False
    assert ("cached", path) not in cache.jobs

    volumes = [["/Volumes/USB", "/dev/disk4s1"]]
    # The quick local-lane check of saved volume IDs (``volumes_verify``).
    verify = IORequest("verify", 0, "", "volumes_verify", {}, math.inf)
    cache._volume_verify_owner = verify.owner
    service.resultReady.emit(verify, {"kind": "volumes_verified", "volumes": volumes})
    qtbot.waitUntil(lambda: ("cached", path) in cache.jobs)
    again = producer(cache, path, "cached")
    assert again.payload["verified_volumes"] == volumes
    service.resultReady.emit(again, {"kind": "shot", "shot": 1, "array": np.ones((1, 3)),
                                     "fingerprint": [1, 6, 123]})
    service.resultReady.emit(again, {
        "kind": "loaded", "signature": "sig", "files": 1, "total_files": 1, "failed_files": 0,
        "rows": 1, "bytes": 24, "problematic": [], "source": "disk", "cached": True, "disk_cached": True,
        "disk_cache_pending": False, "cache_info": info, "verified": False,
        "fingerprint": [[1, 6, 123]], "memory_shots": [], "load_counts": {"reused_disk": 1, "read": 0}})
    service.pending.remove(again)
    qtbot.waitUntil(lambda: browser.folder_opened_path == path and browser.folder_opened_data is not None)
    assert browser.shows_unchecked(path)  # Shown at once, as unchecked; the files' load goes on.
    assert producer(cache, path, "load") is files_load

    # Read once per verification: a later one (here the marker check's) doesn't read again.
    markers = IORequest("markers", 0, "", "roots_verify", {}, math.inf)
    cache._root_verify_owner = markers.owner
    service.resultReady.emit(markers, {"kind": "volumes_verified", "volumes": volumes})
    qtbot.wait(20)
    assert ("cached", path) not in cache.jobs
