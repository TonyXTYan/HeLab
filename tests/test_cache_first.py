"""Cached data shows at once from the local disk cache; the folder check follows."""
from __future__ import annotations

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
    return {"directory": str(tmp_path / "disk-cache"), "params": {"shards": 2}}


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


def guard_source(monkeypatch: pytest.MonkeyPatch, source: Path, *, folder_stat: bool) -> list[str]:
    """Record source access; the cache folder is elsewhere and stays usable."""
    calls: list[str] = []
    real_scandir, real_stat = os.scandir, os.stat

    def scandir(path: Any = ".") -> Any:
        if str(path).startswith(str(source)):
            calls.append(f"scandir {path}")
            raise AssertionError("listed the source folder")
        return real_scandir(path)

    def stat(path: Any, *args: Any, **kwargs: Any) -> Any:
        if str(path).startswith(str(source)) and not (folder_stat and str(path) == str(source)):
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


def test_check_of_cached_data_is_one_folder_stat_until_the_folder_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    source = source_folder(tmp_path)
    first = loaded(run_load(source, tmp_path))
    memory = [list(entry) for entry in first["fingerprint"]]
    with monkeypatch.context() as patched:
        calls = guard_source(patched, source, folder_stat=True)
        events = run_load(source, tmp_path, memory=memory, base_signature=first["signature"])
    assert not calls
    result = loaded(events)
    assert result["unchanged"] and result["memory_shots"] == [1, 2]
    assert result["signature"] == first["signature"]
    # Adding a file modifies the folder: the next check lists and reads only the new file.
    (source / "d_txy_forc3.txt").write_text("3,2,3\n")
    later = time.time() + 10
    os.utime(source, (later, later))
    result = loaded(run_load(source, tmp_path, memory=memory, base_signature=first["signature"]))
    assert not result.get("unchanged")
    assert result["load_counts"]["new_loaded"] == 1 and result["load_counts"]["reused_memory"] == 2
    # A different expected signature (the folder changed this session) never takes the shortcut.
    result = loaded(run_load(source, tmp_path, memory=memory, base_signature=first["signature"],
                             expected="changed"))
    assert not result.get("unchanged")


def test_files_still_being_written_are_left_for_the_next_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr("helab.io_helper.SETTLE_SECONDS", 60.0)
    source = source_folder(tmp_path)
    old = time.time() - 120
    os.utime(source / "d_txy_forc1.txt", (old, old))  # Shot 2 was just written.
    events = run_load(source, tmp_path)
    result = loaded(events)
    assert [event["shot"] for event in events if event["kind"] == "shot"] == [1]
    assert result["files"] == 1 and result["total_files"] == 2 and result["unsettled_files"] == 1
    assert result["failed_files"] == 0
    summary = next(event for event in events if event["kind"] == "scan_summary")["status"]
    assert summary["txy"] == [1, 2] and summary["unsettled"] == 1
    saved = next(event for event in events if event["kind"] == "cache_saved")["cache_info"]
    assert saved["unsettled"] == 1
    # A cache with unsettled files is always checked fully, even if the folder is unmodified.
    memory = [list(entry) for entry in result["fingerprint"]]
    os.utime(source, (old, old))
    os.utime(source / "d_txy_forc2.txt", (old, old))
    result = loaded(run_load(source, tmp_path, memory=memory, base_signature=result["signature"]))
    assert not result.get("unchanged")
    assert result["load_counts"]["new_loaded"] == 1 and result["unsettled_files"] == 0


def test_file_growing_while_read_is_not_kept(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import pandas as pd
    source = source_folder(tmp_path)
    growing = source / "d_txy_forc2.txt"
    read_csv = pd.read_csv

    def append_after_read(filename: Any, *args: Any, **kwargs: Any) -> Any:
        frame = read_csv(filename, *args, **kwargs)
        if str(filename) == str(growing):
            with open(growing, "a") as file:
                file.write("4,5,6\n")
        return frame

    monkeypatch.setattr("pandas.read_csv", append_after_read)
    events = run_load(source, tmp_path)
    result = loaded(events)
    assert [event["shot"] for event in events if event["kind"] == "shot"] == [1]
    assert result["files"] == 1 and result["unsettled_files"] == 1 and result["failed_files"] == 0
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
    assert ("load", path) not in cache.jobs  # The check waits for the cached shots.
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
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs)
    check = producer(cache, path, "load")
    assert check.payload["base_signature"] == signature and check.payload["memory"] == fingerprint
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
