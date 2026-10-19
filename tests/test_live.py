"""Live (L1, L2): a tab watches its selected folder for new shots, saves them every N, and on stop.

Helpers run in-process: each queued request gets the real helper's events (``replay``).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import uuid
import time
from types import SimpleNamespace
from typing import Any, Iterator

import numpy as np
import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QDialog
from pytestqt.qtbot import QtBot

from helab import io_helper
from helab.io_helper import list_folder, live_check, load, read_cached, save_held, scan
from helab.utils.constants import (
    DEFAULT_LIVE_AUTOSAVE, DEFAULT_LIVE_INTERVAL, LIVE_AUTOSAVE_SETTING, LIVE_INTERVAL_SETTING, read_live_autosave,
    read_live_interval,
)
from helab.utils.folder_cache import FolderCache, SharedJob, store_options
from helab.utils.io_service import FOREGROUND, IORequest, IOService
from helab.views.FolderExplorer import FolderExplorer, LiveSession
from helab.views.HelabMainWindow import HelabMainWindow
from helab.views.QuitSaveDialog import QuitSaveDialog


def write_shot(folder: Path, shot: int, *, age: float = 60.0) -> None:
    file = folder / f"d_txy_forc{shot}.txt"
    file.write_text(f"{shot},2,3\n{shot},4,5\n")
    when = time.time() - age
    os.utime(file, (when, when))


def age_folder(folder: Path, seconds: float) -> None:
    """A folder mtime this old is safe for the next check to compare (not within RACY_SECONDS)."""
    when = time.time() - seconds
    os.utime(folder, (when, when))


def job_of(cache: FolderCache, path: str, operation: str = "load") -> SharedJob | None:
    """The folder's queued job: for "load", a Live check (keyed "live") or an ordinary load."""
    keys = [("live", path), ("load", path)] if operation == "load" else [(operation, path)]
    return next((cache.jobs[key] for key in keys if key in cache.jobs), None)


def producer(cache: FolderCache, path: str, operation: str = "load") -> IORequest:
    job = job_of(cache, path, operation)
    assert job is not None
    return next(request for request in cache.service.pending if request.owner == job.owner)


def replay(cache: FolderCache, path: str, tmp_path: Path, operation: str = "load") -> list[dict[str, Any]]:
    """Run the real helper for the queued request in-process and deliver its events, as the
    service's reader thread would (shots' artifacts become arrays; a Live save's data in RAM is
    handed over as ``IOService._run`` writes it, for ``save_held``)."""
    return deliver(cache, *run_helper(cache, path, tmp_path, operation))


def run_helper(cache: FolderCache, path: str, tmp_path: Path,
               operation: str = "load") -> tuple[IORequest, list[dict[str, Any]]]:
    """``replay``'s first half: the queued request taken off the queue and run; its events, not delivered."""
    request = producer(cache, path, operation)
    payload = request.payload
    output = tmp_path / f"artifacts-{time.monotonic_ns()}"
    output.mkdir()
    events: list[dict[str, Any]] = []
    try:
        if operation == "list":
            list_folder(path, events.append, payload.get("cache"))
        elif operation in ("scan", "details"):
            scan(path, events.append, payload.get("cache"), manual=payload.get("scan_manual", False),
                 operation_id=payload.get("scan_operation_id", ""), revision=payload.get("scan_revision", 0))
        elif payload.get("save_memory") and request.arrays is not None:
            held = output / "held"
            held.mkdir()
            for shot, array in request.arrays.items():
                np.save(held / f"{shot}.npy", array, allow_pickle=False)
            save_held(path, events.append, payload.get("cache"), payload.get("held") or [],
                      payload.get("held_problematic") or [], str(held), identity=payload.get("identity", ""),
                      identity_root=payload.get("identity_root"), no_cache=bool(payload.get("no_cache")),
                      recent=payload.get("recent"), output=str(output))
        elif payload.get("live"):
            live_check(path, str(output), events.append, payload.get("memory"), payload.get("known"),
                       payload.get("live_since"), identity=payload.get("identity", ""), seen=payload.get("seen"),
                       check_level=payload.get("check_level", "medium"), recent=payload.get("recent"))
        else:
            load(path, str(output), events.append, payload.get("cache"), payload.get("memory"),
                 payload.get("base_signature", ""), payload.get("signature", ""), limits=payload.get("limits"),
                 no_cache=bool(payload.get("no_cache")), check_level=str(payload.get("check_level") or "medium"))
        events.append({"kind": "done"})
    except Exception as exc:
        events.append({"kind": "error", "message": str(exc)})
    cache.service.pending.remove(request)
    return request, events


def deliver(cache: FolderCache, request: IORequest, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``replay``'s second half: the events, as the service's reader thread delivers them."""
    for event in events:
        if event["kind"] == "shot":
            event = {**event, "array": np.load(event.pop("artifact"))}
        cache.service.resultReady.emit(request, event)
    return events


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> Iterator[IOService]:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    yield service
    service.shutdown()


@pytest.fixture
def run(tmp_path: Path) -> Path:
    folder = tmp_path / "run"
    folder.mkdir()
    for shot in (1, 2):
        write_shot(folder, shot)
    age_folder(folder, 120)
    return folder


def open_loaded(qtbot: QtBot, service: IOService, run: Path, tmp_path: Path) -> FolderExplorer:
    """A tab showing ``run``'s data (loaded from its files, then saved to the disk cache)."""
    path = str(run)
    explorer = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(explorer)
    cache = explorer.model.cache
    cache.live_interval, cache.live_autosave_shots = 0.02, 2
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    replay(cache, path, tmp_path, "list")
    explorer.load_to_ram_cache(path, dwell=False, explicit=True)
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs)
    replay(cache, path, tmp_path)
    qtbot.waitUntil(lambda: explorer.folder_opened_path == path and not cache.disk_cache_saving(path))
    assert sorted(explorer.folder_opened_data or {}) == [1, 2] and cache.disk_cached(path)
    for request in [r for r in service.pending if r.operation == "details"]:
        service.pending.remove(request)
    return explorer


def next_request(qtbot: QtBot, explorer: FolderExplorer, path: str) -> IORequest:
    cache = explorer.model.cache
    qtbot.waitUntil(lambda: job_of(cache, path) is not None)
    return producer(cache, path)


def checks(qtbot: QtBot, explorer: FolderExplorer, path: str, tmp_path: Path, count: int = 2) -> None:
    """Run Live's next checks: a new file is seen by one and read by the next (same size and mtime)."""
    for _ in range(count):
        next_request(qtbot, explorer, path)
        replay(explorer.model.cache, path, tmp_path)


def cached_shots(path: str, tmp_path: Path) -> list[int]:
    output = tmp_path / f"cached-{time.monotonic_ns()}"
    output.mkdir()
    events: list[dict[str, Any]] = []
    read_cached(path, str(output), events.append, store_options())
    return sorted(event["shot"] for event in events if event["kind"] == "shot")


def test_live_adds_new_shots_saves_every_n_and_when_it_stops(
    qtbot: QtBot, service: IOService, run: Path, tmp_path: Path,
) -> None:
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    assert explorer.live_state()[0] and not explorer.watching(path)
    assert explorer.folder_freshness_label.text().endswith("Live updates off")
    assert explorer.start_live()
    assert not explorer.tree.isEnabled() and not explorer.path_edit.isEnabled()
    assert explorer.live_state() == (True, explorer.live_state()[1]) and "Click to stop" in explorer.live_state()[1]

    # First check: lists the folder, nothing new; it is a foreground load with the shots held.
    check = next_request(qtbot, explorer, path)
    job = job_of(cache, path)
    assert job is not None and job.live and check.owner == job.owner and check.payload["live"]
    assert sorted(entry[0] for entry in check.payload["memory"]) == [1, 2] and check.payload["live_since"] is None
    assert service.is_foreground(check)
    events = replay(cache, path, tmp_path)
    assert events[0]["kind"] == "live_unchanged" and events[0]["live_listed"]
    session = explorer.live
    assert session is not None and session.since == run.stat().st_mtime_ns and session.checks == 1
    explorer._update_activity()
    assert explorer.folder_freshness_label.text().startswith("Live · ")
    assert "0 new shots" in explorer.folder_freshness_label.text()

    # Nothing changed: the next check is one stat (it compares the folder's mtime).
    check = next_request(qtbot, explorer, path)
    assert check.payload["live_since"] == session.since
    events = replay(cache, path, tmp_path)
    assert events[0]["kind"] == "live_unchanged" and not events[0]["live_listed"]
    # At least once a minute it lists the folder anyway (a network drive may report its mtime late).
    session.listed_at -= explorer.LIVE_LIST_SECONDS
    check = next_request(qtbot, explorer, path)
    assert check.payload["live_since"] is None
    assert replay(cache, path, tmp_path)[0]["live_listed"]

    # A new shot arrives: read and shown at once, kept in RAM (not yet saved).
    write_shot(run, 3)
    age_folder(run, 60)
    checks(qtbot, explorer, path, tmp_path)
    assert sorted(explorer.folder_opened_data or {}) == [1, 2, 3]
    assert session.new == 1 and session.unsaved == {3}
    assert explorer.displayed_dataset is not None and explorer.displayed_dataset.metadata["source"] == "updated"
    assert cached_shots(path, tmp_path) == [1, 2]
    # The superseded dataset isn't kept beside the new one (its arrays would count twice).
    assert [key for key in cache.datasets if key[0] == path] == [(path, explorer.displayed_dataset.signature, 0)]
    explorer._update_activity()
    assert "1 new shot" in explorer.folder_freshness_label.text()
    assert "1 not cached yet" in explorer.folder_freshness_label.text()

    # The second unsaved shot: the next step saves the folder (N = 2) with an ordinary load, in the background.
    write_shot(run, 4)
    age_folder(run, 50)
    checks(qtbot, explorer, path, tmp_path)
    assert session.unsaved == {3, 4}
    save = next_request(qtbot, explorer, path)
    assert save.payload.get("save") and not save.payload.get("live") and not service.is_foreground(save)
    assert session.request == "save" and session.saving == {3, 4} and not session.unsaved
    assert path in cache.quit_saves()
    replay(cache, path, tmp_path)
    qtbot.waitUntil(lambda: not session.saving)
    assert session.saved_at is not None and cached_shots(path, tmp_path) == [1, 2, 3, 4]
    assert not cache.quit_saves()

    # Live off with one unsaved shot: saved in the background, then the session is done.
    write_shot(run, 5)
    age_folder(run, 40)
    checks(qtbot, explorer, path, tmp_path)
    assert session.unsaved == {5}
    explorer.stop_live()
    assert explorer.live is None and explorer.tree.isEnabled() and explorer.path_edit.isEnabled()
    save = next_request(qtbot, explorer, path)
    job = job_of(cache, path)
    assert save.payload.get("save") and job is not None and not job.live and save.owner == job.owner
    explorer._update_activity()
    assert explorer.folder_freshness_label.text() == "Live updates off · saving 1 shot"
    replay(cache, path, tmp_path)
    qtbot.waitUntil(lambda: not explorer._live_sessions)
    assert cached_shots(path, tmp_path) == [1, 2, 3, 4, 5]
    assert sorted(explorer.folder_opened_data or {}) == [1, 2, 3, 4, 5]
    explorer._update_activity()
    assert explorer.folder_freshness_label.text().endswith("Live updates off")
    explorer.close_cleanup()


def test_files_still_being_written_wait_and_are_counted(
    qtbot: QtBot, service: IOService, run: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    assert explorer.start_live()
    monkeypatch.setattr(io_helper, "SETTLE_SECONDS", 5.0)
    write_shot(run, 3, age=0)
    age_folder(run, 60)
    checks(qtbot, explorer, path, tmp_path)
    session = explorer.live
    assert session is not None and session.unsettled == 1 and session.new == 0 and session.since is None
    explorer._update_activity()
    assert "1 still being written" in explorer.folder_freshness_label.text()
    write_shot(run, 3, age=60)  # Written now; the folder itself didn't change.
    checks(qtbot, explorer, path, tmp_path)  # Seen settled, then read unchanged a check later.
    assert session.unsettled == 0 and session.new == 1 and sorted(explorer.folder_opened_data or {}) == [1, 2, 3]
    explorer.stop_live(save=False)
    explorer.close_cleanup()


def test_an_error_stops_checking_keeps_the_data_and_retry_resumes(
    qtbot: QtBot, service: IOService, run: Path, tmp_path: Path,
) -> None:
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    data = explorer.folder_opened_data
    explorer.load_error = "Timed out after 60 s without progress"  # An earlier check's.
    assert explorer.start_live()
    explorer._update_activity()
    assert explorer.retry_button.isHidden()  # Live's own Retry shows when Live needs it.
    hidden = tmp_path / "unmounted"
    run.rename(hidden)
    next_request(qtbot, explorer, path)
    events = replay(cache, path, tmp_path)
    assert events[-1]["kind"] == "error"
    session = explorer.live
    assert session is not None and session.error.startswith("Folder not found")
    explorer._update_activity()
    assert explorer.folder_freshness_label.text().startswith("Live stopped: Folder not found")
    assert "color" in explorer.folder_freshness_label.styleSheet()
    assert explorer.folder_opened_data is data and not explorer.retry_button.isHidden()
    assert explorer.activity_brief == "Live stopped: run"
    # No retries by itself: nothing more is queued.
    qtbot.wait(100)
    assert job_of(cache, path) is None
    hidden.rename(run)
    explorer.retry_button.click()
    next_request(qtbot, explorer, path)
    assert replay(cache, path, tmp_path)[0]["kind"] == "live_unchanged"
    assert not session.error and explorer.retry_button.isHidden()
    explorer.stop_live(save=False)
    explorer.close_cleanup()


def test_a_shot_live_read_recently_that_changes_is_read_again_and_said(
    qtbot: QtBot, service: IOService, run: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """By Tony's decision: a shot Live itself read in the last LIVE_REREAD_SECONDS that changes (its
    writer paused longer than the settle age) is read again, Live goes on, the Live line and Folder
    details say so for a minute, and one WARNING names the file, its old and new size and mtime and
    how long after Live read it. An older one that changes still stops Live as mismatched."""
    import logging
    from helab.views.FolderDetailsPanel import FolderDetailsPanel
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    cache.live_autosave_shots = 100  # (Checks only, no save between them.)
    assert explorer.start_live()
    session = explorer.live
    assert session is not None
    # The writer pauses mid-row longer than the settle age: Live reads shot 3 unfinished.
    partial = run / "d_txy_forc3.txt"
    partial.write_bytes(b"3,2,3\n3,4")  # (Bytes: text mode writes "\r\n" on Windows.)
    old = time.time() - 60
    os.utime(partial, (old, old))
    age_folder(run, 50)
    checks(qtbot, explorer, path, tmp_path)
    assert 3 in session.shots and 3 in session.read_at and 1 not in session.read_at  # (Shot 1: the load's.)
    request = next_request(qtbot, explorer, path)
    assert request.payload["recent"] == [3]
    # It finishes, and the next shot comes (the folder changes: the check lists it).
    partial.write_bytes(b"3,2,3\n3,4,5\n")
    os.utime(partial, (old + 5, old + 5))
    write_shot(run, 4)
    age_folder(run, 40)
    replay(cache, path, tmp_path)  # Both seen: shot 3 changed, shot 4 new.
    assert not session.error and path not in cache.mismatched
    with caplog.at_level(logging.WARNING):
        checks(qtbot, explorer, path, tmp_path, count=1)
    assert not session.error and path not in cache.mismatched and session.shots == {1, 2, 3, 4}
    np.testing.assert_array_equal((explorer.folder_opened_data or {})[3], [[3, 2, 3], [3, 4, 5]])
    note = "Shot 3 changed after it was read (writer paused > 5 s?): read again"
    text, tooltip, stopped = explorer.live_line(session)
    assert note in text and not stopped and "old and new size and mtime" in tooltip
    panel = FolderDetailsPanel(explorer)
    panel.show_explorer(explorer, service)
    assert note in panel.text("state")
    [warning] = [record for record in caplog.records if record.levelname == "WARNING" and "Live: shot" in record.getMessage()]
    message = warning.getMessage()
    assert f"shot 3 changed" in message and str(partial) in message and "read again" in message
    assert f"size 9 → {partial.stat().st_size:,} bytes" in message
    assert {3, 4} <= session.unsaved  # (Its new data is saved with the next save.)
    # The note lasts a minute.
    text, at = explorer._reread_notes[path]
    explorer._reread_notes[path] = (text, at - explorer.LIVE_REREAD_NOTE_SECONDS)
    assert explorer.live_reread_note(path) == "" and note not in explorer.live_line(session)[0]
    # Shot 4, read by Live but longer ago than the window, changes: Live stops as mismatched.
    session.read_at[4] = time.time() - explorer.LIVE_REREAD_SECONDS - 1
    (run / "d_txy_forc4.txt").write_text("4,9,9\n")
    os.utime(run / "d_txy_forc4.txt", (old, old))
    write_shot(run, 5)
    age_folder(run, 30)
    next_request(qtbot, explorer, path)
    replay(cache, path, tmp_path)
    halted = explorer.live  # (Read again: the asserts above narrowed ``session.error``.)
    assert halted is not None and halted.error == "1 shot changed in the folder" and path in cache.mismatched
    explorer.stop_live(save=False)
    explorer.close_cleanup()


def test_the_save_at_live_off_reads_a_recently_read_shot_again_and_saves_it(
    qtbot: QtBot, service: IOService, run: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """The reviewer's repro (recheck at 660ba9c): Live reads shot 3 mid-row, the writer finishes, and
    Live is turned off before another check. Its save (the real ``save_held``) is the first to read
    shot 3 again: it sends the folder's new summary first, so FolderCache keeps the save (no cancel),
    the tab shows and the disk cache holds the whole shot, and the note and WARNING follow."""
    import logging
    from helab.views.FolderDetailsPanel import FolderDetailsPanel
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    cache.live_autosave_shots = 100  # (No save until Live off.)
    assert explorer.start_live()
    session = explorer.live
    assert session is not None
    partial = run / "d_txy_forc3.txt"
    partial.write_bytes(b"3,2,3\n3,4")
    old = time.time() - 60
    os.utime(partial, (old, old))
    age_folder(run, 50)
    checks(qtbot, explorer, path, tmp_path)
    assert 3 in session.shots and 3 in session.read_at
    np.testing.assert_array_equal((explorer.folder_opened_data or {})[3], [[3, 2, 3]])
    partial.write_bytes(b"3,2,3\n3,4,5\n")  # The writer finishes it; no check sees that.
    os.utime(partial, (old + 5, old + 5))
    age_folder(run, 40)
    explorer.stop_live()
    request = next_request(qtbot, explorer, path)
    assert request.payload.get("save_memory") and request.payload["recent"] == [3] and request.arrays is not None
    with caplog.at_level(logging.WARNING):
        events = replay(cache, path, tmp_path)
    kinds = [event["kind"] for event in events]
    assert kinds.index("shot") < kinds.index("scan_summary") < kinds.index("loaded") < kinds.index("disk_cached")
    assert not any(event["kind"] == "cancelled" for event in events)
    np.testing.assert_array_equal((explorer.folder_opened_data or {})[3], [[3, 2, 3], [3, 4, 5]])
    dataset = cache.current_dataset(path)
    assert dataset is not None and sorted(dataset.data) == [1, 2, 3]
    np.testing.assert_array_equal(dataset.data[3], [[3, 2, 3], [3, 4, 5]])
    snapshot = cache.snapshot(path)
    assert snapshot is not None and snapshot.status["signature"] == dataset.signature
    assert cached_shots(path, tmp_path) == [1, 2, 3]
    output = tmp_path / f"cached-{time.monotonic_ns()}"
    output.mkdir()
    found: list[dict[str, Any]] = []
    read_cached(path, str(output), found.append, store_options())
    shot = next(event for event in found if event["kind"] == "shot" and event["shot"] == 3)
    np.testing.assert_array_equal(np.load(shot["artifact"]), [[3, 2, 3], [3, 4, 5]])
    note = "Shot 3 changed after it was read (writer paused > 5 s?): read again"
    qtbot.waitUntil(lambda: not explorer._live_sessions)  # (Its save ended: the session is done.)
    assert explorer.live_reread_note(path) == note
    panel = FolderDetailsPanel(explorer)
    panel.show_explorer(explorer, service)
    assert note in panel.text("state")
    explorer._update_folder_summary()
    assert note in explorer.folder_freshness_label.text()
    [warning] = [record.getMessage() for record in caplog.records if "Live: shot" in record.getMessage()]
    assert "shot 3 changed" in warning and str(partial) in warning
    assert f"size 9 → {partial.stat().st_size:,} bytes" in warning
    explorer.close_cleanup()


def test_a_save_older_than_the_folders_listing_keeps_the_listing_and_still_saves(
    qtbot: QtBot, service: IOService, run: Path, tmp_path: Path,
) -> None:
    """The reviewer's probe (recheck at 65a15a2): Live off saves (and reads shot 3 again) while a newer
    check of the folder (Refresh, another tab) sees shot 4. The save's older summary isn't adopted:
    the snapshot keeps the newer status, [1, 2, 3, 4]; the save still completes (not cancelled for
    the newer signature) without counting its data as checked."""
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    cache.live_autosave_shots = 100
    assert explorer.start_live()
    partial = run / "d_txy_forc3.txt"
    partial.write_bytes(b"3,2,3\n3,4")
    old = time.time() - 60
    os.utime(partial, (old, old))
    age_folder(run, 50)
    checks(qtbot, explorer, path, tmp_path)
    partial.write_bytes(b"3,2,3\n3,4,5\n")
    os.utime(partial, (old + 5, old + 5))
    age_folder(run, 40)
    explorer.stop_live()
    next_request(qtbot, explorer, path)
    save, save_events = run_helper(cache, path, tmp_path)  # The save lists the folder, reads shot 3 again…
    assert [event["kind"] for event in save_events].count("scan_summary") == 1
    write_shot(run, 4)  # …shot 4 comes, and another tab lists the folder (foreground)…
    age_folder(run, 30)
    assert cache.submit("other-tab", 0, path, "list", {"cache": store_options()}, force=True)
    replay(cache, path, tmp_path, "list")
    snapshot = cache.snapshot(path)
    assert snapshot is not None and snapshot.status["txy"] == [1, 2, 3, 4]
    # …and its load of the folder, also in the foreground, adopts its newer signature (no data
    # dropped, unlike a status check's, which runs in the background lane after the save).
    snapshot.status["signature"] = "another tab's load"
    newer = dict(snapshot.status)
    events = deliver(cache, save, save_events)  # …then the save's events arrive.
    loaded = next(event for event in events if event["kind"] == "loaded")
    assert loaded["signature"] != newer["signature"] and float(newer["scanned_at"]) > float(
        next(event for event in events if event["kind"] == "scan_summary")["status"]["scanned_at"])
    snapshot = cache.snapshot(path)
    assert snapshot is not None and snapshot.status == newer  # Not rolled back to [1, 2, 3].
    # Kept (the folder's newest data, though not its current state: shot 4 is still to load).
    dataset = cache.latest_dataset(path)
    assert dataset is not None and dataset.signature == loaded["signature"] and sorted(dataset.data) == [1, 2, 3]
    np.testing.assert_array_equal(dataset.data[3], [[3, 2, 3], [3, 4, 5]])
    assert "checked_at" not in dataset.metadata and not cache.counts_as_checked(dataset)
    np.testing.assert_array_equal((explorer.folder_opened_data or {})[3], [[3, 2, 3], [3, 4, 5]])
    assert cached_shots(path, tmp_path) == [1, 2, 3]
    qtbot.waitUntil(lambda: not explorer._live_sessions)  # (The save ended: not cancelled.)
    explorer.close_cleanup()


def test_shots_gone_from_the_folder_stop_live(qtbot: QtBot, service: IOService, run: Path, tmp_path: Path) -> None:
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    assert explorer.start_live()
    (run / "d_txy_forc2.txt").unlink()
    next_request(qtbot, explorer, path)
    replay(cache, path, tmp_path)
    assert explorer.live is not None and explorer.live.error == "1 shot missing from the folder"
    assert path in cache.mismatched
    explorer.stop_live()  # Nothing to save, and its cached data may not be this folder's.
    assert job_of(cache, path) is None and not explorer._live_sessions
    explorer.close_cleanup()


@pytest.mark.parametrize("change", ["replaced", "remounted"])
def test_another_folder_at_the_same_path_stops_live_and_is_never_merged(
    qtbot: QtBot, service: IOService, run: Path, tmp_path: Path, change: str,
) -> None:
    """Same shot numbers at the watched path: a replaced folder (its sampled shots differ) or a
    copy under another data root (same files; its .helab-root differs)."""
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    data = explorer.folder_opened_data
    assert explorer.start_live()
    checks(qtbot, explorer, path, tmp_path, 1)
    session = explorer.live
    assert session is not None and session.identity.startswith("root:")
    if change == "replaced":
        run.rename(tmp_path / "old run")
        run.mkdir()
        for shot in (1, 2, 3):
            (run / f"d_txy_forc{shot}.txt").write_text(f"{shot},9,9\n")
    else:
        copy = tmp_path / "copy"
        shutil.copytree(run, copy, copy_function=shutil.copy2)
        (copy / ".helab-root").write_text(json.dumps({"helab": "root", "version": 1, "uuid": str(uuid.uuid4()),
                                                      "label": "copy", "created_at": "2026-10-19T00:00:00Z"}))
        run.rename(tmp_path / "unmounted")
        copy.rename(run)
    age_folder(run, 30)
    checks(qtbot, explorer, path, tmp_path, 1)
    expected = ("2 shots changed in the folder" if change == "replaced"
                else "another folder is at this path now (drive or data root changed)")
    assert session.error == expected and path in cache.mismatched
    assert explorer.folder_opened_data is data and sorted(data or {}) == [1, 2]  # Kept, never merged.
    explorer.stop_live()  # Its cached data may not be this folder's: nothing is saved.
    assert job_of(cache, path) is None and not explorer._live_sessions
    explorer.close_cleanup()


def test_live_needs_shown_data_and_locks_navigation(
    qtbot: QtBot, service: IOService, run: Path, tmp_path: Path,
) -> None:
    path = str(run)
    explorer = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(explorer)
    enabled, tooltip = explorer.live_state()
    assert not enabled and "Select a folder with loaded data" in tooltip and not explorer.start_live()
    explorer.close_cleanup()
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    assert explorer.start_live() and not explorer.start_live()
    # Selecting another folder, opening one, or Deselect turn Live off (the tree is locked: by code only).
    explorer.load_to_ram_cache(path, dwell=False, explicit=True)
    assert ("load", path) not in cache.jobs  # No ordinary load of the watched folder.
    explorer.open_to_path(str(tmp_path))
    assert explorer.live is None and explorer.tree.isEnabled()
    explorer.close_cleanup()


def test_live_starts_on_a_folder_with_no_shots_yet(qtbot: QtBot, service: IOService, tmp_path: Path) -> None:
    """Start Live, then run the experiment: a listed folder without TXY files is watched from no
    data, and its first shot arrives as the next data shown (a revision), then saved on stop."""
    folder = tmp_path / "run"
    folder.mkdir()
    age_folder(folder, 120)
    path = str(folder)
    explorer = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(explorer)
    cache = explorer.model.cache
    cache.live_interval = 0.02
    # Not listed yet: whether it has shots is unknown.
    assert not explorer.live_state()[0] and not explorer.start_live()
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    replay(cache, path, tmp_path, "list")
    qtbot.waitUntil(lambda: explorer.model.nodes[path].report is not None)
    assert explorer.displayed_dataset is None and explorer.live_state()[0]
    loaded: list[str] = []
    explorer.dataLoaded.connect(loaded.append)
    assert explorer.start_live()
    shown = explorer.displayed_dataset
    assert shown is not None and shown.path == path and shown.data == {} and explorer.folder_opened_path == path
    session = explorer.live
    assert session is not None and session.dataset is shown and loaded == [path]

    # The first check holds no shots and lists the folder: nothing yet.
    check = next_request(qtbot, explorer, path)
    assert check.payload["live"] and check.payload["memory"] == [] and check.payload["live_since"] is None
    assert replay(cache, path, tmp_path)[0]["kind"] == "live_unchanged"
    explorer._update_activity()
    assert "waiting for the first shot" in explorer.folder_freshness_label.text()

    # The first shot: seen by one check, read by the next, shown as the folder's data.
    write_shot(folder, 1)
    age_folder(folder, 60)
    checks(qtbot, explorer, path, tmp_path)
    assert sorted(explorer.folder_opened_data or {}) == [1] and session.new == 1 and session.unsaved == {1}
    dataset = explorer.displayed_dataset
    assert dataset is not None and dataset is session.dataset and dataset.metadata["source"] == "updated"
    assert dataset.signature and len(loaded) == 2
    explorer._update_activity()
    assert "1 new shot" in explorer.folder_freshness_label.text()

    # A second shot is a further revision; Live off saves both.
    write_shot(folder, 2)
    age_folder(folder, 50)
    checks(qtbot, explorer, path, tmp_path)
    assert sorted(explorer.folder_opened_data or {}) == [1, 2] and len(loaded) == 3
    explorer.stop_live()
    save = next_request(qtbot, explorer, path)
    assert save.payload.get("save")
    replay(cache, path, tmp_path)
    qtbot.waitUntil(lambda: not explorer._live_sessions)
    assert cached_shots(path, tmp_path) == [1, 2]
    explorer.close_cleanup()


def test_a_folder_with_shots_not_yet_loaded_cant_be_watched(
    qtbot: QtBot, service: IOService, run: Path, tmp_path: Path,
) -> None:
    """Only a folder with no shots yet starts from no data; one with shots is loaded first."""
    path = str(run)
    explorer = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(explorer)
    cache = explorer.model.cache
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    replay(cache, path, tmp_path, "list")
    qtbot.waitUntil(lambda: explorer.model.nodes[path].report is not None)
    assert explorer.model.nodes[path].txy_count == 2 and explorer.displayed_dataset is None
    enabled, tooltip = explorer.live_state()
    assert not enabled and "loaded data, or with no shots yet" in tooltip and not explorer.start_live()
    explorer.close_cleanup()


def test_a_folder_with_subfolders_is_watched_alone(
    qtbot: QtBot, service: IOService, run: Path, tmp_path: Path,
) -> None:
    """A folder with subfolders and no TXY files of its own (a drive's top, a day's folder of runs)
    can be watched from no data too; Live reads only the folder's own TXY files, never those in
    its subfolders (here ``run``, with shots 1 and 2, and a new shot 9 written into it)."""
    path = str(tmp_path)
    explorer = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(explorer)
    cache = explorer.model.cache
    cache.live_interval = 0.02
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    replay(cache, path, tmp_path, "list")
    qtbot.waitUntil(lambda: explorer.model.nodes[path].report is not None)
    node = explorer.model.nodes[path]
    assert node.txy_count == 0 and node.children and explorer.displayed_dataset is None
    assert explorer.live_state()[0] and explorer.start_live()
    age_folder(tmp_path, 60)
    checks(qtbot, explorer, path, tmp_path)
    write_shot(run, 9)  # In the subfolder: never read.
    write_shot(tmp_path, 5)  # The folder's own first shot.
    age_folder(run, 60)
    age_folder(tmp_path, 60)
    checks(qtbot, explorer, path, tmp_path)
    assert sorted(explorer.folder_opened_data or {}) == [5]
    session = explorer.live
    assert session is not None and session.shots == {5} and session.new == 1
    explorer.stop_live(save=False)
    explorer.close_cleanup()


def test_rules_that_stop_saving_show_on_the_line(
    qtbot: QtBot, service: IOService, run: Path, tmp_path: Path,
) -> None:
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    cache.remember_prefs(path, {"no_cache": True, "no_auto_load": False, "set_at": time.time()}, confirmed=False)
    assert explorer.start_live()
    for shot in (3, 4, 5):
        write_shot(run, shot)
        age_folder(run, 100 - shot)
        checks(qtbot, explorer, path, tmp_path)
    session = explorer.live
    assert session is not None and session.unsaved == {3, 4, 5} and not session.saving
    explorer._update_activity()
    assert "3 not cached (Don't cache)" in explorer.folder_freshness_label.text()
    assert "Not saved: you chose Don't cache for this folder" in explorer.folder_freshness_label.toolTip()
    explorer.stop_live()
    assert not explorer._live_sessions and job_of(cache, path) is None
    explorer.close_cleanup()


def test_closing_the_tab_saves_its_new_shots(qtbot: QtBot, service: IOService, run: Path, tmp_path: Path) -> None:
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    assert explorer.start_live()
    write_shot(run, 3)
    age_folder(run, 60)
    checks(qtbot, explorer, path, tmp_path)
    explorer.on_stop_button_clicked()  # As closing a tab does first.
    explorer.close_cleanup()
    assert explorer.closed and cache.quit_saves() == [path]
    replay(cache, path, tmp_path)
    assert not cache.quit_saves() and cached_shots(path, tmp_path) == [1, 2, 3]


def test_switching_tabs_turns_live_off(qtbot: QtBot, service: IOService, run: Path, tmp_path: Path) -> None:
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    other = FolderExplorer(str(tmp_path), str(tmp_path), str(tmp_path), [0])
    qtbot.addWidget(other)
    assert explorer.start_live()
    current = [explorer]
    window = SimpleNamespace(
        update_tool_enabled_state=lambda: None, _update_live_action=lambda: None,
        _explorers=lambda: [(0, explorer), (1, other)],
        tab_widget=SimpleNamespace(currentWidget=lambda: current[0]))
    HelabMainWindow.on_current_tab_changed(window, 0)  # type: ignore[arg-type]
    assert explorer.live is not None
    current[0] = other
    other.claim_foreground()
    HelabMainWindow.on_current_tab_changed(window, 1)  # type: ignore[arg-type]
    assert explorer.live is None and explorer.tree.isEnabled()
    other.close_cleanup()
    explorer.close_cleanup()


def test_a_save_waits_for_the_folders_running_save(
    qtbot: QtBot, service: IOService, run: Path, tmp_path: Path,
) -> None:
    """Saves of one folder never overlap: Live off while its auto-save writes waits for it."""
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    assert explorer.start_live()
    for shot in (3, 4):
        write_shot(run, shot)
        age_folder(run, 100 - shot)
        checks(qtbot, explorer, path, tmp_path)
    save = next_request(qtbot, explorer, path)
    assert save.payload.get("save")
    # Deliver its data, but not its write yet.
    events = run_helper_events(cache, path, tmp_path)
    loaded_at = next(i for i, event in enumerate(events) if event["kind"] == "loaded")
    for event in events[:loaded_at + 1]:
        cache.service.resultReady.emit(save, event)
    assert cache.disk_cache_saving(path)
    write_shot(run, 5)
    age_folder(run, 60)
    checks(qtbot, explorer, path, tmp_path)
    explorer.stop_live()
    assert job_of(cache, path) is None and cache.quit_saves() == [path]  # Waiting.
    for event in events[loaded_at + 1:]:
        cache.service.resultReady.emit(save, event)
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs)
    replay(cache, path, tmp_path)
    qtbot.waitUntil(lambda: not explorer._live_sessions)
    assert cached_shots(path, tmp_path) == [1, 2, 3, 4, 5]
    explorer.close_cleanup()


def run_helper_events(cache: FolderCache, path: str, tmp_path: Path) -> list[dict[str, Any]]:
    """The real helper's events for the queued load, not yet delivered."""
    request = producer(cache, path)
    payload = request.payload
    output = tmp_path / f"artifacts-{time.monotonic_ns()}"
    output.mkdir()
    events: list[dict[str, Any]] = []
    load(path, str(output), events.append, payload.get("cache"), payload.get("memory"),
         payload.get("base_signature", ""), payload.get("signature", ""), limits=payload.get("limits"))
    events.append({"kind": "done"})
    cache.service.pending.remove(request)
    return [{**event, "array": np.load(event.pop("artifact"))} if event["kind"] == "shot" else event
            for event in events]


def test_a_save_never_joins_another_load_and_quit_waits_for_it(
    qtbot: QtBot, service: IOService, run: Path, tmp_path: Path,
) -> None:
    """Another tab's ordinary load of the folder is queued: Live's save waits for it (its own
    choices, its own write) and Quit counts it; quitting cancels the load, so the save starts."""
    path = str(run)
    explorer = open_loaded(qtbot, service, run, tmp_path)
    cache = explorer.model.cache
    assert explorer.start_live()
    write_shot(run, 3)
    age_folder(run, 60)
    checks(qtbot, explorer, path, tmp_path)
    assert cache.submit("other tab", 0, path, "load", {"cache": store_options(), "no_cache": True})
    explorer.stop_live()
    session = explorer._live_sessions[path]
    ordinary = cache.jobs[("load", path)]
    assert session.request == "save" and not ordinary.saves() and not ordinary.payload.get("save")
    assert cache.quit_saves() == [path]  # Waiting for the ordinary load, still a save to quit for.
    cache.cancel_for_quit()
    qtbot.waitUntil(lambda: (job := job_of(cache, path)) is not None and job is not ordinary)
    save = job_of(cache, path)
    assert save is not None and save.payload.get("save") and not save.payload.get("no_cache")
    assert cache.quit_saves() == [path]
    replay(cache, path, tmp_path)
    qtbot.waitUntil(lambda: not cache.quit_saves())
    assert cached_shots(path, tmp_path) == [1, 2, 3]
    explorer.close_cleanup()


def test_every_save_subscriber_counts_for_quit(service: IOService, tmp_path: Path) -> None:
    """Save intent is the subscriber's, not the producer payload's: a save that joined a job
    (or a job another save joined) is waited for, and quitting doesn't cancel it."""
    cache = FolderCache(service)
    path = str(tmp_path)
    assert cache.submit("tab", 0, path, "load", {})
    assert cache.submit("tab:live-save", 0, path, "load", {"save": True})
    job = cache.jobs[("load", path)]
    assert not job.payload.get("save") and job.saves() and cache.quit_saves() == [path]
    cache.cancel_for_quit()
    assert cache.jobs.get(("load", path)) is job


def test_quit_window_waits_for_saves_and_quit_now_skips_them(
    qtbot: QtBot, service: IOService, tmp_path: Path,
) -> None:
    cache = FolderCache(service)
    path = str(tmp_path / "run")
    cache._deferred_saves[path] = ("owner", {})
    dialog = QuitSaveDialog(cache)
    qtbot.addWidget(dialog)
    results: list[int] = []
    dialog.finished.connect(results.append)
    dialog.open()
    item = dialog.folders.item(0)
    assert dialog.folders.count() == 1 and item is not None and item.text() == "run — waiting for its previous save"
    dialog.reject()  # Esc keeps waiting.
    assert dialog.isVisible() and not results
    del cache._deferred_saves[path]
    qtbot.waitUntil(lambda: bool(results))
    assert results == [QDialog.DialogCode.Accepted] and not dialog.skipped
    cache._deferred_saves[path] = ("owner", {})
    dialog = QuitSaveDialog(cache)
    qtbot.addWidget(dialog)
    dialog.finished.connect(results.append)
    dialog.open()
    dialog.quit_now_button.click()
    assert results[-1] == QDialog.DialogCode.Rejected and dialog.skipped


def test_a_finished_loads_background_save_is_a_quit_save(service: IOService, tmp_path: Path) -> None:
    cache = FolderCache(service)
    path = str(tmp_path)
    assert cache.submit("tab", 0, path, "load", {})
    request = producer(cache, path)
    service.resultReady.emit(request, {"kind": "shot", "shot": 1, "array": np.ones((1, 3))})
    service.resultReady.emit(request, {"kind": "loaded", "signature": "s", "files": 1, "rows": 1, "bytes": 24,
                                       "problematic": [], "disk_cache_pending": True})
    assert cache.quit_saves() == [path]
    ended: list[tuple[str, str]] = []
    cache.saveEnded.connect(lambda folder, outcome: ended.append((folder, outcome)))
    service.resultReady.emit(request, {"kind": "cache_saved", "cache_info": {"signature": "s"}})
    assert not cache.quit_saves() and ended == [(path, "saved")]


def test_closing_the_window_waits_in_the_quit_window(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    window = HelabMainWindow()
    qtbot.addWidget(window)
    from helab.utils.folder_cache import get_folder_cache
    from helab.utils.io_service import get_io_service
    cache = get_folder_cache(get_io_service())
    path = str(tmp_path / "run")
    cache._deferred_saves[path] = ("owner", {})
    window.close()
    assert not window._closing and window._quit_dialog is not None and window._quit_dialog.isVisible()
    window.close()  # Again (e.g. Ctrl+C): the window still decides.
    assert not window._closing
    del cache._deferred_saves[path]
    qtbot.waitUntil(lambda: window._closing, timeout=3000)
    assert get_io_service() is not cache.service  # The old service was shut down.


def test_the_live_action_follows_the_current_tab_and_locks_navigation(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The default tab opens a folder with a shot that isn't loaded (auto-load off), so Live can't
    # start there, whatever folders this computer has (any listed folder without TXY files can).
    folder = tmp_path / "run"
    folder.mkdir()
    write_shot(folder, 1)
    monkeypatch.setattr("helab.views.FolderTabWidget.DEFAULT_DATA_PATH", str(folder))
    monkeypatch.setattr("helab.views.FolderTabWidget.DEV_POTENTIAL_DATA_PATHS", [str(folder)])
    window = HelabMainWindow()
    qtbot.addWidget(window)
    window.view_toggle_auto_load_ram.setChecked(False)
    window.toggle_auto_load_ram()
    qtbot.waitUntil(lambda: isinstance(window.tab_widget.currentWidget(), FolderExplorer))
    explorer = window.tab_widget.currentWidget()
    assert isinstance(explorer, FolderExplorer)
    qtbot.waitUntil(lambda: explorer.selected_path_globally == str(folder))
    window._update_live_action()
    assert not window.action_tab_live.isEnabled() and "Select a folder with loaded data" in window.action_tab_live.toolTip()
    window.on_live_button_clicked()  # Says why instead.
    assert window._status_notice is not None and "Select a folder" in window._status_notice[0]
    from helab.utils.folder_cache import Dataset
    explorer.live = LiveSession(explorer.selected_path_globally, time.time(), set(),
                                Dataset(explorer.selected_path_globally, "s", {}, {}, 0))
    window._update_live_action()
    assert window.action_tab_live.isEnabled() and window.action_tab_live.isChecked()
    assert not window.action_tab_refresh.isEnabled() and not window.action_tab_rescan.isEnabled()
    assert not window.action_tab_folder_up.isEnabled() and window.action_tab_new.isEnabled()
    explorer.live = None
    window._update_live_action()
    assert not window.action_tab_live.isChecked() and window.action_tab_refresh.isEnabled()
    window._quit_now = True


def test_quitting_straight_after_a_save_waits_for_another_tabs_load_waits_for_the_save(
    qtbot: QtBot, tmp_path: Path,
) -> None:
    """Real helpers: another tab's ordinary load of the folder is queued, a Live save of it waits
    for that load; quitting at once cancels the load, starts the save and waits for it."""
    window = HelabMainWindow()
    qtbot.addWidget(window)
    from helab.utils.folder_cache import get_folder_cache
    from helab.utils.io_service import get_io_service
    cache = get_folder_cache(get_io_service())
    folder = tmp_path / "run"
    folder.mkdir()
    for shot in (1, 2):
        write_shot(folder, shot)
    path = str(folder)
    cache.service.configure_concurrency(1)
    # Keep the ordinary load queued: the background lane is busy with another tab's load.
    blocker = tmp_path / "blocker"
    blocker.mkdir()
    assert cache.submit("busy tab", 0, str(blocker), "list", {})
    assert cache.submit("other tab", 0, path, "load", {"cache": store_options()})
    assert cache.save("live tab:live-save", path, {"cache": store_options()})
    assert ("load", path) in cache.jobs and cache.quit_saves() == [path]
    window.close()
    assert not window._closing and window._quit_dialog is not None
    qtbot.waitUntil(lambda: window._closing, timeout=20000)
    assert cached_shots(path, tmp_path) == [1, 2]


def test_quit_now_closes_at_once(qtbot: QtBot, tmp_path: Path) -> None:
    window = HelabMainWindow()
    qtbot.addWidget(window)
    from helab.utils.folder_cache import get_folder_cache
    from helab.utils.io_service import get_io_service
    cache = get_folder_cache(get_io_service())
    cache._deferred_saves[str(tmp_path)] = ("owner", {})
    window.close()
    dialog = window._quit_dialog
    assert dialog is not None
    dialog.quit_now_button.click()
    qtbot.waitUntil(lambda: window._closing, timeout=3000)


def test_a_live_check_holds_background_work_only_while_reading(service: IOService) -> None:
    check = IORequest("tab:live", 0, "/data/run", "load", {"live": True}, 60.0)
    check.lane, check.last_activity = FOREGROUND, time.monotonic()
    service.active.append(check)
    assert not service.hold_background()
    check.current_file = "/data/run/d_txy_forc3.txt"
    assert service.hold_background()
    assert service.label(check) == "Live check" and service.running_loads() == []
    check.current_file = None
    assert "Checking for new shots" in service.activity_summary()
    service.active.remove(check)


def test_live_settings_are_read_within_bounds(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    assert read_live_interval(settings) == DEFAULT_LIVE_INTERVAL == 3.0
    assert read_live_autosave(settings) == DEFAULT_LIVE_AUTOSAVE == 10
    for value, expected in ((0.01, 0.5), (1e9, 600.0), ("nan", 3.0), ("x", 3.0), (7.5, 7.5)):
        settings.setValue(LIVE_INTERVAL_SETTING, value)
        assert read_live_interval(settings) == expected
    for count, saved in ((0, 1), ("x", 10), (25, 25)):
        settings.setValue(LIVE_AUTOSAVE_SETTING, count)
        assert read_live_autosave(settings) == saved


def test_settings_dialog_edits_both_live_settings(qtbot: QtBot, tmp_path: Path) -> None:
    from helab.views.SettingsDialog import SettingsDialog
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    dialog = SettingsDialog(settings=settings)
    qtbot.addWidget(dialog)
    assert dialog.live_interval_spin.value() == 3.0 and dialog.cache_tab.live_autosave.value() == 10
    dialog.live_interval_spin.setValue(5.5)
    dialog.cache_tab.live_autosave.setValue(4)
    dialog._write_settings()
    assert read_live_interval(settings) == 5.5 and read_live_autosave(settings) == 4
