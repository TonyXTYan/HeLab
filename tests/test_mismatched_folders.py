"""Folders whose cached data doesn't match them: one list window, a hold of loads and scans at
2, 4, 8… mismatched folders, skipping them from 8, and scans that find them."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import time
from typing import Any

import pytest
from pytestqt.qtbot import QtBot
from PyQt6 import QtWebEngineWidgets  # noqa: F401  Shared worker cleanup imports WebEngine; preload before QApplication.

from helab.io_ops.loading import load
from helab.io_ops.scanning import scan
from helab.utils.folder_cache import FolderCache, get_folder_cache
from helab.utils.io_service import IORequest, IOService
from helab.views.MissingShotsWindow import CANCEL_TIP, LOAD_TIP, SKIP_ALL_TIP, SKIP_TIP, MissingShotsWindow


def held_service(monkeypatch: pytest.MonkeyPatch) -> IOService:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_run", lambda request: None)
    service.is_foreground = lambda request: request.owner == "tab"
    return service


def frozen(monkeypatch: pytest.MonkeyPatch) -> tuple[IOService, FolderCache]:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    return service, get_folder_cache(service)


def found(cache: FolderCache, path: str, missing: int = 1) -> None:
    cache._mismatch(path, {"missing": list(range(1, missing + 1)), "missing_count": missing,
                           "known_count": missing + 1, "listed_count": 1}, "load")


def test_held_loads_and_scans_pause_and_wait_while_browsing_goes_on(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = held_service(monkeypatch)
    service.configure_concurrency(2)
    service.submit("tab", 0, "/data", "load")
    running = service.active[0]
    running.output = str(tmp_path)
    service.set_mismatch_hold(True)
    assert running.pause_requested and (tmp_path / "pause").exists()
    service.submit("bulk", 0, "/bulk", "scan")
    service.submit("other", 0, "/details", "details")
    service.submit("tab", 0, "/browse", "list")
    service.submit("local", 0, "/cached", "cached")
    # Browsing and cached reads go on; the scans wait.
    assert {r.path for r in service.active} == {"/data", "/browse", "/cached"}
    assert {r.path for r in service.pending} == {"/bulk", "/details"}
    service.messages.put((running, {"kind": "paused"}))
    service._tick()
    assert "Paused: cached data doesn't match several folders" in service.queue_tooltip()
    # Released: the load pauses only for the tab's listing now, as usual, and the scans start.
    listing = next(r for r in service.active if r.path == "/browse")
    service.messages.put((listing, {"kind": "exit"}))
    service._tick()
    service._listing_busy_at -= service.RESUME_DELAY
    service._foreground_busy_at -= service.RESUME_DELAY
    service.set_mismatch_hold(False)
    assert not running.pause_requested and not (tmp_path / "pause").exists()
    # The scans now wait only for the foreground load, as before any hold.
    assert not any(service.held_by_mismatch(r) for r in service.pending)
    service.shutdown()


def test_cancel_held_cancels_loads_and_scans_but_not_browsing_or_cache_saves(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = held_service(monkeypatch)
    service.configure_concurrency(3)
    service.submit("a", 0, "/saving", "load")
    saving = next(r for r in service.active if r.path == "/saving")
    saving.completed = True  # Delivered its data; writing the disk cache.
    service.submit("b", 0, "/scan", "scan")
    service.submit("tab", 0, "/browse", "list")
    assert {r.path for r in service.active} == {"/saving", "/scan", "/browse"}
    service.set_mismatch_hold(True)
    service.submit("c", 0, "/queued", "load")
    cancelled: list[str] = []
    service.resultReady.connect(
        lambda request, event: cancelled.append(request.path) if event["kind"] == "cancelled" else None)
    service.cancel_held()
    assert sorted(cancelled) == ["/queued", "/scan"]
    assert {r.path for r in service.active} == {"/browse", "/saving"} and not service.pending
    service.shutdown()


def test_the_hold_spares_saves_and_live_checks(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """io-1 (area review, 2026-10-31): a save (Live's too) and a Live check are neither held nor
    paused nor cancelled by the hold; only ordinary loads and scans are."""
    service = held_service(monkeypatch)
    service.configure_concurrency(4)
    service.submit("tab", 0, "/live", "load", {"live": True})
    check = service.active[0]
    check.output = str(tmp_path)
    service.set_mismatch_hold(True)
    assert not check.pause_requested and not (tmp_path / "pause").exists()
    service.submit("save", 0, "/saved", "load", {"save": True, "save_memory": True})
    service.submit("other", 0, "/plain", "load")
    service.submit("bulk", 0, "/scan", "scan")
    assert {r.path for r in service.active} == {"/live", "/saved"}
    assert {r.path for r in service.pending} == {"/plain", "/scan"}
    service._apply_pauses(time.monotonic() + service.RESUME_DELAY)
    assert not any(r.pause_requested for r in service.active)
    cancelled: list[str] = []
    service.resultReady.connect(
        lambda request, event: cancelled.append(request.path) if event["kind"] == "cancelled" else None)
    service.cancel_held()
    assert sorted(cancelled) == ["/plain", "/scan"]
    assert {r.path for r in service.active} == {"/live", "/saved"}
    service.shutdown()


def test_quitting_lifts_the_hold(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    """io-1: quitting starts nothing but saves, so the hold has nothing left to hold, and a save
    queued behind it would otherwise keep the quit window waiting."""
    service, cache = frozen(monkeypatch)
    found(cache, "/1")
    found(cache, "/2")
    assert service.mismatch_hold
    cache.cancel_for_quit()
    assert not service.mismatch_hold
    service.shutdown()


def test_holds_at_two_four_eight_until_answered_and_skipping_from_eight(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, cache = frozen(monkeypatch)
    warnings: list[int] = []
    cache.mismatchWarning.connect(warnings.append)
    found(cache, "/1")
    assert not service.mismatch_hold and not warnings  # One moved folder: just listed.
    found(cache, "/2")
    assert service.mismatch_hold and warnings == [2]
    found(cache, "/2")  # The same folder again: not counted again.
    cache.resume_after_mismatch()
    assert not service.mismatch_hold and cache.mismatch_count == 2
    found(cache, "/3")
    assert not service.mismatch_hold
    found(cache, "/4")
    assert service.mismatch_hold and warnings == [2, 4]
    cancelled: list[bool] = []
    monkeypatch.setattr(service, "cancel_held", lambda: cancelled.append(True))
    cache.cancel_held_io()
    assert cancelled == [True] and not service.mismatch_hold
    for index in range(5, 9):
        found(cache, f"/{index}")
    assert warnings == [2, 4, 8] and service.mismatch_hold
    cache.skip_mismatches()
    assert not service.mismatch_hold and cache.skip_mismatched
    for index in range(9, 17):
        found(cache, f"/{index}")
    assert warnings == [2, 4, 8] and not service.mismatch_hold and len(cache.mismatched) == 16
    service.shutdown()


def test_a_scan_finding_missing_cached_shots_lists_the_folder(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, cache = frozen(monkeypatch)
    run, quiet_path = cache.key("/run"), cache.key("/quiet")  # As FolderCache keys them (a drive on Windows).
    cache.submit("tab", 0, run, "details", {})
    job = cache.jobs[("details", run)]
    request = next(r for r in service.pending if r.owner == job.owner)
    event = {"kind": "cache_mismatch", "missing": [1, 2], "missing_count": 2, "known_count": 2, "listed_count": 5}
    service.resultReady.emit(request, event)
    assert cache.mismatched[run]["source"] == "scan" and cache.mismatched[run]["listed_count"] == 5
    # A folder not cached by choice never shows its cached data: nothing to answer.
    cache.remember_prefs(quiet_path, {"no_cache": True, "no_auto_load": False, "set_at": time.time()})
    cache.submit("tab", 0, quiet_path, "details", {})
    quiet = next(r for r in service.pending if r.path == quiet_path)
    service.resultReady.emit(quiet, event)
    assert quiet_path not in cache.mismatched
    service.shutdown()


def test_clearing_a_mismatched_folders_cached_data_resolves_it(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, cache = frozen(monkeypatch)
    cache.skip_mismatched = True
    a, b = cache.key("/a"), cache.key("/b")  # As FolderCache keys them (a drive on Windows).
    found(cache, a)
    found(cache, b)
    cache.removed([a], ["datasets"])
    assert list(cache.mismatched) == [b]
    service.shutdown()


def source_folder(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    for shot in (1, 2):
        (source / f"d_txy_forc{shot}.txt").write_text(f"{shot},2,3\n")
    return source


def test_helper_scan_reports_cached_shots_the_folder_no_longer_has(tmp_path: Path) -> None:
    options = {"directory": str(tmp_path / "disk-cache")}
    source = source_folder(tmp_path)
    output = tmp_path / "artifacts"
    output.mkdir()
    load(str(source), str(output), lambda event: None, options)
    events: list[Any] = []
    scan(str(source), events.append, options)
    assert not any(event["kind"] == "cache_mismatch" for event in events)
    # Another folder moved to this path: its shot 1 is gone; shot 3 is new (not a mismatch).
    (source / "d_txy_forc1.txt").unlink()
    (source / "d_txy_forc3.txt").write_text("3,2,3\n")
    events.clear()
    scan(str(source), events.append, options)
    mismatch = next(event for event in events if event["kind"] == "cache_mismatch")
    assert (mismatch["missing"], mismatch["known_count"], mismatch["listed_count"]) == ([1], 2, 2)
    # Only the dataset's record is read, never its data.
    db = next(tmp_path.rglob("records.sqlite"))
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] == 1


def test_window_lists_folders_newest_first_and_answers_them(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, cache = frozen(monkeypatch)
    window = MissingShotsWindow(cache)
    qtbot.addWidget(window)
    assert not window.isVisible()
    found(cache, "/data/run1", missing=3)
    qtbot.waitUntil(window.isVisible)  # The first folder opens it, without taking the focus.
    found(cache, "/data/run2")  # Two: loads and scans are held, and the banner says so.
    window.refresh()
    assert [window.tree.topLevelItem(i).text(0) for i in range(2)] == ["run2", "run1"]  # type: ignore[union-attr]
    first = window.tree.topLevelItem(1)
    assert first is not None and first.text(1) == "3 of 4" and first.text(4) == "Not answered"
    assert "3 of the 4 shots HeLab had" in first.toolTip(0) and "/data/run1" in first.toolTip(0)
    assert window.banner.isVisible() and "loads and scans are paused" in window.banner.text()
    assert window.resume_button.isVisible() and window.cancel_button.isVisible()
    assert not window.skip_all_button.isVisible()  # Only from 8 folders.
    assert not window.load_button.isEnabled()  # Nothing selected.
    first.setSelected(True)
    requested: list[list[str]] = []
    window.loadRequested.connect(requested.append)
    window.load_button.click()
    assert requested == [["/data/run1"]]
    window.skip_button.click()
    window.refresh()
    assert cache.mismatched["/data/run1"]["answer"] == "dont_load"
    window.resume_button.click()
    window.refresh()
    assert not service.mismatch_hold and not window.banner.isVisible()
    assert (window.load_button.toolTip(), window.skip_button.toolTip(), window.cancel_button.toolTip(),
            window.skip_all_button.toolTip()) == (LOAD_TIP, SKIP_TIP, CANCEL_TIP, SKIP_ALL_TIP)
    service.shutdown()


def test_closed_window_stays_closed_until_the_next_warning_and_skip_shows_from_eight(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, cache = frozen(monkeypatch)
    window = MissingShotsWindow(cache)
    qtbot.addWidget(window)
    found(cache, "/1")
    qtbot.waitUntil(window.isVisible)
    window.close()
    found(cache, "/2")  # A warning (2): it comes back.
    qtbot.waitUntil(window.isVisible)
    cache.resume_after_mismatch()
    window.close()
    found(cache, "/3")
    qtbot.wait(20)
    assert not window.isVisible()
    for index in range(4, 9):
        found(cache, f"/{index}")
    qtbot.waitUntil(window.isVisible)
    window.refresh()
    assert window.skip_all_button.isVisible()
    window.skip_all_button.click()
    window.refresh()
    assert cache.skip_mismatched and not service.mismatch_hold
    assert window.banner.isVisible() and "Skipping mismatched folders" in window.banner.text()
    service.shutdown()


def test_a_held_load_waits_for_the_answer(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    """Through FolderCache: a load submitted while held is queued, not started."""
    service = held_service(monkeypatch)
    cache = get_folder_cache(service)
    found(cache, "/1")
    found(cache, "/2")
    assert service.mismatch_hold
    following = cache.key("/next")  # As FolderCache keys it (a drive on Windows).
    cache.submit("tab", 0, following, "load", {})
    request: IORequest = next(r for r in service.pending if r.path == following)
    assert request not in service.active
    cache.resume_after_mismatch()
    assert any(r.path == following for r in service.active)
    service.shutdown()


def test_review_shows_the_window_with_that_folder_selected(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    service, cache = frozen(monkeypatch)
    window = MissingShotsWindow(cache)
    qtbot.addWidget(window)
    found(cache, "/data/run1")
    found(cache, "/data/run2")
    window.close()  # Dismissed: a tab's Review… still shows it.
    window.show_list(activate=True, select="/data/run1")
    assert window.isVisible() and window.selected_paths() == ["/data/run1"]
    assert window.load_button.isEnabled()
    service.shutdown()


def test_working_offline_load_as_it_is_now_is_off(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    """Work Offline (cache-only browsing, D6): Load as it is now reads the folder."""
    from helab.utils import folder_cache
    from helab.utils.folder_cache import OFFLINE_TOOLTIP
    service, cache = frozen(monkeypatch)
    window = MissingShotsWindow(cache)
    qtbot.addWidget(window)
    found(cache, "/data/run1", missing=3)
    window.refresh()
    item = window.tree.topLevelItem(0)
    assert item is not None
    window.tree.setCurrentItem(item)
    requested: list[list[str]] = []
    window.loadRequested.connect(requested.append)
    try:
        cache.set_offline(True)
        assert not window.load_button.isEnabled() and window.load_button.toolTip() == OFFLINE_TOOLTIP
        assert window.skip_button.isEnabled()
        window._load()
        assert not requested
        cache.set_offline(False)
        assert window.load_button.isEnabled()
    finally:
        folder_cache._offline = False
