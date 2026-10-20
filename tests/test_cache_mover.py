"""Roadmap S9: the cache move as the app runs it: the I/O hold, the locks, the mover and startup."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Iterator

import psutil
import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QWidget

from helab.utils import cache_locks, cache_move
from helab.utils.cache_locks import FileLock, lock_for_move, other_instances, startup
from helab.utils.cache_store import CacheStore, DatasetRecord, store_root
from helab.utils.constants import cache_dir, cache_dir_refused, set_cache_dir
from helab.utils.folder_cache import get_folder_cache, store_options
from helab.utils.io_service import IORequest, IOService
from helab.views.CacheMover import CacheMover

RECORD: DatasetRecord = {"ram_bytes": 1, "rows": 1, "shots": 1, "fingerprint": [], "problematic": [], "info": {}}


@pytest.fixture(autouse=True)
def keep_cache_dir() -> Iterator[None]:
    before = cache_dir()
    yield
    set_cache_dir(before)


def make_cache(folder: Path) -> str:
    with CacheStore(store_root(str(folder))) as store:
        store.save_dataset("/data/a", store.write_dataset_file(os.urandom(4000)), RECORD, store.start_dataset_job("/data/a"))
        return store.store_id


# The I/O hold

def qtbot_wait(condition: Any, timeout: float = 5.0) -> None:
    """Helpers start on their own threads: wait for them."""
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def started_service(monkeypatch: pytest.MonkeyPatch) -> tuple[IOService, list[IORequest]]:
    service = IOService()
    service.timer.stop()
    service.max_operations = 4
    started: list[IORequest] = []
    # The real dispatch and start, without running helpers.
    monkeypatch.setattr(service, "_run", lambda request: started.append(request))
    return service, started


def test_a_hold_stops_and_holds_every_helper_that_opens_the_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    service, started = started_service(monkeypatch)
    events: list[tuple[str, str]] = []
    service.resultReady.connect(lambda request, event: events.append((request.operation, event["kind"])))
    try:
        service.submit("a", 0, "/x", "load", {"cache": {"directory": "/old"}})
        service._dispatch()
        qtbot_wait(lambda: bool(started))
        running = started[-1]
        service.hold_cache()
        # The running one is stopped, and stays "busy" until its exit is confirmed.
        assert ("load", "cancelled") in events and running in service.retired and service.cache_busy()
        service.submit("b", 0, "/y", "list", {"cache": {"directory": "/old"}})
        service.submit("c", 0, "/z", "cache_admin", {"cache": {"directory": "/old"}, "action": "sweep"})
        service.submit("d", 0, "/w", "icons", {"paths": ["/w"]})
        service.submit("e", 0, "/old", "cache_move", {"move": {"action": "move"}})
        service._dispatch()
        qtbot_wait(lambda: len(started) == 3)
        assert {r.operation for r in started[1:]} == {"icons", "cache_move"}
        service._forget(running)
        assert not service.cache_busy() or any(service.uses_cache(r) for r in service.active)
        # Released after the move: queued helpers open the cache where it is now.
        service.cache_options = lambda: {"directory": "/new"}
        service.release_cache()
        service._dispatch()
        qtbot_wait(lambda: len(started) == 5)
        moved = [r for r in started if r.operation in ("list", "cache_admin")]
        assert len(moved) == 2 and all(r.payload["cache"] == {"directory": "/new"} for r in moved)
    finally:
        service.shutdown()


# The locks

HOLD = "import sys, time\nfrom helab.utils.cache_locks import FileLock\nlock = FileLock(sys.argv[1])\n" \
       "assert lock.try_lock()\nprint('held', flush=True)\ntime.sleep(float(sys.argv[2]))\n"


def hold_in_another_process(path: str, seconds: float = 30) -> subprocess.Popen[str]:
    process = subprocess.Popen([sys.executable, "-c", HOLD, path, str(seconds)], stdout=subprocess.PIPE, text=True)
    assert process.stdout is not None and process.stdout.readline().strip() == "held"
    return process


def test_a_lock_is_exclusive_and_released_when_its_process_ends(tmp_path: Path) -> None:
    path = str(tmp_path / "cache.lock")
    first, second = FileLock(path), FileLock(path)
    assert first.try_lock() and not second.try_lock()
    first.unlock()
    assert second.try_lock()
    second.unlock()
    # Another HeLab holds it; once that process ends (even by a crash) it is free.
    other = hold_in_another_process(path)
    try:
        assert not first.try_lock()
    finally:
        other.kill()
        other.wait()
    assert first.try_lock()
    first.unlock()


def test_a_move_is_refused_while_another_helab_or_a_move_helper_runs(tmp_path: Path) -> None:
    app = str(tmp_path / "app")
    other = hold_in_another_process(os.path.join(cache_locks.instances_dir(app), "4242.lock"))
    try:
        assert other_instances(app) == [4242]
        lock, reason = lock_for_move(app, "move")
        assert lock is None and reason.startswith("Another HeLab is running (1 window)")
    finally:
        other.kill()
        other.wait()
    # A move helper still running (e.g. deleting the old folder) blocks the next move.
    helper = hold_in_another_process(cache_locks.move_lock(app).path)
    try:
        lock, reason = lock_for_move(app, "move")
        assert lock is None and reason.startswith("The previous cache move is still finishing")
    finally:
        helper.kill()
        helper.wait()
    lock, reason = lock_for_move(app, "move")
    assert lock is not None and not reason and other_instances(app) == []
    lock.unlock()


def test_startup_waits_out_a_move_then_recovers_and_registers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app, source, target = str(tmp_path / "app"), tmp_path / "caches", tmp_path / "moved"
    store_id = make_cache(source)
    # A crash after the copy was verified: the next start finishes the move.
    monkeypatch.setattr(cache_move, "same_disk", lambda a, b: False)
    record = cache_move.start(str(source), str(target), app, cache_move.COPY)
    cache_move.move(record, app, lambda done, total: None, lambda: False)
    setting = [str(source)]

    def write(path: str) -> bool:
        setting[0] = path
        return True
    # A move helper is still at work though its HeLab has ended: startup waits for it.
    helper = hold_in_another_process(cache_locks.move_lock(app).path)
    waits: list[bool] = []

    def wait() -> None:
        waits.append(True)
        helper.kill()  # ...until it ends.
        helper.wait()
    message, instance = startup(app, lambda token: cache_move.recover(app, lambda: setting[0], write), wait)
    try:
        assert waits == [True] and "finished" in message and setting == [str(target)]
        assert cache_move.valid_at(str(target), store_id) and not source.exists()
        assert instance.held and os.path.exists(os.path.join(cache_locks.instances_dir(app), f"{os.getpid()}.lock"))
        assert cache_locks.cache_lock(app).try_lock()  # Released after startup.
    finally:
        instance.unlock()
        cache_locks.cache_lock(app).unlock()


# The mover, driven by its helper's events

class Run:
    def __init__(self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.service = IOService()
        self.service.timer.stop()
        monkeypatch.setattr(self.service, "_dispatch", lambda: None)
        self.cache = get_folder_cache(self.service)
        self.parent = QWidget()
        qtbot.addWidget(self.parent)
        self.settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
        self.app = str(tmp_path / "app")
        self.source, self.target = str(tmp_path / "caches"), str(tmp_path / "moved")
        set_cache_dir(self.source)
        self.mover = CacheMover(self.cache, self.settings, self.app)
        self.reports: list[tuple[str, str, list[str]]] = []
        self.confirmed: list[str] = []

        def confirm(text: str) -> bool:
            self.confirmed.append(text)
            return True
        self.mover.confirm = confirm
        self.mover.report = lambda title, text, folders: self.reports.append((title, text, folders))
        self.finished: list[bool] = []
        self.mover.finished.connect(self.finished.append)

    def request(self, action: str) -> IORequest:
        return next(r for r in reversed(self.service.pending) if r.operation == "cache_move"
                    and r.payload["move"]["action"] == action)

    def send(self, request: IORequest, *events: dict[str, Any]) -> None:
        for event in (*events, {"kind": "done"}):
            self.service.resultReady.emit(request, event)
        if request in self.service.pending:
            self.service.pending.remove(request)

    def checked(self, method: str = cache_move.COPY) -> IORequest:
        self.mover.change(self.target, self.parent)
        self.send(self.request("check"), {"kind": "move_check", "problem": "", "method": method, "bytes": 706 << 20,
                                          "free": 1 << 40})
        return self.request("move")

    def close(self) -> None:
        self.mover.detach()
        self.service.shutdown()


def test_the_mover_checks_confirms_holds_moves_and_switches_in_place(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    run = Run(qtbot, monkeypatch, tmp_path)
    try:
        # A load stopped by the hold hasn't exited yet: the move waits for it.
        stopping = IORequest("tab", 0, "/data/a", "load", {"cache": store_options()}, 60)
        run.service.retired.append(stopping)
        run.mover.change(run.target, run.parent)
        run.send(run.request("check"), {"kind": "move_check", "problem": "", "method": cache_move.COPY,
                                        "bytes": 706 << 20, "free": 1 << 40})
        assert run.service.cache_hold and not any(r.payload["move"]["action"] == "move" for r in run.service.pending)
        run.service.retired.remove(stopping)
        run.mover._wait.timeout.emit()
        move = run.request("move")
        assert run.confirmed == [f"HeLab pauses loading and folder checks while it moves the cache (706 MB) to "
                                 f"{run.target}."]
        assert run.service.cache_hold and move.payload["move"]["method"] == cache_move.COPY
        assert run.mover.lock is not None and run.mover.lock.held
        assert run.mover.progress is not None
        run.service.resultReady.emit(move, {"kind": "move_progress", "done": 1, "total": 4})
        assert run.mover.progress.value() == 250
        record = {"from": run.source, "to": run.target, "method": cache_move.COPY, "step": "verified",
                  "store_id": "s"}
        cache_move.write_record(run.app, record)
        run.send(move, {"kind": "move_done", "record": record})
        # The cutover: the setting saved first, then recorded; HeLab switches in place and resumes.
        assert run.settings.value("dir_caches", type=str) == run.target
        assert cache_move.read_record(run.app) == {**record, "step": "setting_updated"}
        assert cache_dir() == run.target and store_options()["directory"] == store_root(run.target)
        assert not run.service.cache_hold and run.mover.switched_folder and not run.mover.busy
        # The old folder is deleted last, by a helper; until then no other move can start.
        cleanup = run.request("cleanup")
        assert cleanup.payload["move"]["id"] == run.mover.move_id
        assert run.mover.running and run.mover.lock is not None and run.finished == []
        assert not run.mover.change(run.target, run.parent)
        run.send(cleanup, {"kind": "move_cleaned", "left": [run.source]})
        assert run.reports[-1][0] == "Old cache folder not fully deleted" and run.reports[-1][2] == [run.source]
        assert run.mover.lock is None and not run.mover.running and run.finished == [True]
    finally:
        run.close()


def test_a_failed_or_cancelled_move_keeps_the_source(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    run = Run(qtbot, monkeypatch, tmp_path)
    try:
        # A check that finds a problem: nothing is held, the target can be shown.
        run.mover.change(run.target, run.parent)
        run.send(run.request("check"), {"kind": "move_check", "problem": "Not enough space on 'Backup': needs "
                                        "706 MB, 210 MB free.", "method": "copy", "bytes": 1, "free": 1})
        assert run.reports[-1] == ("Can't move the disk cache here",
                                   "Not enough space on 'Backup': needs 706 MB, 210 MB free.", [run.target])
        assert not run.service.cache_hold and run.finished == [False]
        # The helper's own failure (e.g. verification): the source stays, a partial copy is shown.
        move = run.checked()
        run.send(move, {"kind": "move_failed", "message": "The copy failed verification: a copied data file "
                        "has the wrong size (x).", "left": [run.target]})
        assert run.reports[-1][1].endswith(f"The cache stays in {run.source}.") and run.reports[-1][2] == [run.target]
        assert cache_dir() == run.source and not run.service.cache_hold and run.mover.lock is None
        # Cancel during the copy: the helper is stopped, then the copy discarded.
        move = run.checked()
        run.mover.cancel()
        abort = run.request("abort")
        assert abort.payload["move"]["before_cutover"] is True
        run.send(abort, {"kind": "move_aborted", "left": []})
        assert run.finished[-1] is False and not run.service.cache_hold and cache_dir() == run.source
        # Refused while another HeLab runs.
        monkeypatch.setattr("helab.views.CacheMover.lock_for_move",
                            lambda app, token: (None, "Another HeLab is running (1 window). Close it before moving "
                                                "the cache."))
        run.mover.change(run.target, run.parent)
        run.send(run.request("check"), {"kind": "move_check", "problem": "", "method": "copy", "bytes": 1, "free": 9})
        assert run.reports[-1][0] == "Can't move the disk cache now" and not run.service.cache_hold
    finally:
        run.close()


def test_a_settings_write_that_fails_is_before_the_cutover(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    run = Run(qtbot, monkeypatch, tmp_path)
    monkeypatch.setattr("helab.views.CacheMover.write_cache_setting", lambda settings, path: False)
    try:
        # Copy: the verified copy is discarded; the source stays.
        move = run.checked()
        record = {"from": run.source, "to": run.target, "method": cache_move.COPY, "step": "verified", "store_id": "s"}
        cache_move.write_record(run.app, record)
        run.send(move, {"kind": "move_done", "record": record})
        abort = run.request("abort")
        assert abort.payload["move"]["before_cutover"] is True and cache_dir() == run.source
        run.send(abort, {"kind": "move_aborted", "left": []})
        cache_move.delete_record(run.app)  # (What the abort helper does.)
        assert "couldn't save the new cache folder setting" in run.reports[-1][1]
        assert run.settings.value("dir_caches", type=str) == run.source  # Not the discarded copy.
        # Rename: renamed back, or (when that fails too) the destination is used for now.
        for undone in (True, False):
            monkeypatch.setattr(cache_move, "undo_rename", lambda app, record: undone)
            move = run.checked(cache_move.RENAME)
            record = {**record, "method": cache_move.RENAME, "step": "renamed"}
            cache_move.write_record(run.app, record)
            run.send(move, {"kind": "move_done", "record": record})
            assert cache_dir() == (run.source if undone else run.target) and not run.service.cache_hold
            set_cache_dir(run.source)
            cache_move.delete_record(run.app)
        assert "fixes the setting at the next start" in run.reports[-1][1]
    finally:
        run.close()


def test_a_cutover_that_cant_be_recorded_still_switches_and_the_next_start_finishes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    run = Run(qtbot, monkeypatch, tmp_path)
    set_step = cache_move.set_step

    def full(app_dir: str, record: dict[str, Any], step: str) -> dict[str, Any]:
        if step == "setting_updated":
            raise OSError(28, "No space left on device")
        return set_step(app_dir, record, step)
    monkeypatch.setattr(cache_move, "set_step", full)
    try:
        move = run.checked()
        record = {"from": run.source, "to": run.target, "method": cache_move.COPY, "step": "verified", "store_id": "s"}
        cache_move.write_record(run.app, record)
        run.send(move, {"kind": "move_done", "record": record})
        # The setting names the new folder, so HeLab uses it; the record stays for the next start.
        assert cache_dir() == run.target and run.settings.value("dir_caches", type=str) == run.target
        assert cache_move.read_record(run.app) == record
        assert not run.service.cache_hold and run.mover.lock is None and run.finished == [True]
        assert "finishes the move" in run.reports[-1][1] and "No space left" in run.reports[-1][1]
    finally:
        run.close()


def test_a_rename_renamed_back_resumes_on_the_source_whatever_the_setting_says(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    run = Run(qtbot, monkeypatch, tmp_path)

    def access_error(settings: QSettings, path: str) -> bool:
        settings.setValue("dir_caches", path)  # Kept in memory, though it couldn't be saved.
        return False
    monkeypatch.setattr("helab.views.CacheMover.write_cache_setting", access_error)
    monkeypatch.setattr(cache_move, "undo_rename", lambda app, record: True)
    try:
        move = run.checked(cache_move.RENAME)
        run.mover.cancel()  # A rename has no cancel point.
        assert not run.mover._cancelled
        record = {"from": run.source, "to": run.target, "method": cache_move.RENAME, "step": "renamed",
                  "store_id": "s"}
        cache_move.write_record(run.app, record)
        run.send(move, {"kind": "move_done", "record": record})
        assert cache_dir() == run.source and run.settings.value("dir_caches", type=str) == run.source
        assert run.finished == [False] and not run.service.cache_hold
    finally:
        run.close()


def test_a_failed_rename_back_resumes_where_the_store_is(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    run = Run(qtbot, monkeypatch, tmp_path)
    try:
        move = run.checked(cache_move.RENAME)
        run.send(move, {"kind": "move_failed", "message": "The move failed: no space for the record.",
                        "left": [run.target], "store_at": run.target})
        assert cache_dir() == run.target and run.settings.value("dir_caches", type=str) == run.target
        assert not run.service.cache_hold and run.mover.lock is None
        assert "HeLab uses it and fixes the setting at the next start" in run.reports[-1][1]
    finally:
        run.close()


def test_an_abort_that_cant_rename_back_resumes_where_the_store_is(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    run = Run(qtbot, monkeypatch, tmp_path)
    try:
        move = run.checked(cache_move.RENAME)
        # The move helper ended abruptly after renaming; the abort can't rename it back.
        run.service.resultReady.emit(move, {"kind": "error", "message": "The helper stopped."})
        run.service.pending.remove(move)
        abort = run.request("abort")
        run.send(abort, {"kind": "move_aborted", "left": [run.target], "store_at": run.target})
        assert cache_dir() == run.target and run.settings.value("dir_caches", type=str) == run.target
        assert not run.service.cache_hold and "fixes the setting at the next start" in run.reports[-1][1]
    finally:
        run.close()


def test_the_helper_reports_where_the_store_is_after_a_failed_move(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.io_ops.admin import cache_move_job
    app, source, target = str(tmp_path / "app"), tmp_path / "caches", tmp_path / "moved"
    make_cache(source)
    set_step = cache_move.set_step

    def full(app_dir: str, record: dict[str, Any], step: str) -> dict[str, Any]:
        if step == "renamed":
            raise OSError(28, "No space left on device")
        return set_step(app_dir, record, step)
    monkeypatch.setattr(cache_move, "set_step", full)
    real_rename = os.rename

    def stuck(src: str, dst: str) -> None:
        if src == str(target):
            raise PermissionError("in use")  # Renaming back fails.
        real_rename(src, dst)
    monkeypatch.setattr(os, "rename", stuck)
    held = cache_locks.cache_lock(app)
    assert held.try_lock("m")
    events: list[Any] = []
    try:
        cache_move_job({"action": "move", "app_dir": app, "from": str(source), "to": str(target),
                        "method": cache_move.RENAME, "id": "m", "token": "m"}, events.append)
        # An abort asked for afterwards (e.g. after the move helper ended abruptly) says so too.
        aborted: list[Any] = []
        cache_move_job({"action": "abort", "app_dir": app, "from": str(source), "to": str(target),
                        "method": cache_move.RENAME, "id": "m", "token": "m"}, aborted.append)
        assert aborted[-1]["store_at"] == str(target) and aborted[-1]["left"] == [str(target)]
    finally:
        held.unlock()
    failed = events[-1]
    assert failed["kind"] == "move_failed" and failed["store_at"] == str(target) and failed["left"] == [str(target)]
    assert cache_move.read_record(app) is not None  # Kept for the next start.


def test_an_undo_that_cant_say_where_the_store_is_turns_the_cache_off(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    run = Run(qtbot, monkeypatch, tmp_path)
    reject = [False]
    submit = run.service.submit

    def maybe(*args: Any, **kwargs: Any) -> bool:
        return False if reject[0] else submit(*args, **kwargs)
    monkeypatch.setattr(run.service, "submit", maybe)
    try:
        for failure in ("error", "queue full"):
            set_cache_dir(run.source)
            move = run.checked(cache_move.RENAME)
            reject[0] = failure == "queue full"
            # The move helper ended abruptly (after renaming?), so its record is undone by an abort...
            run.service.resultReady.emit(move, {"kind": "error", "message": "The helper stopped."})
            run.service.pending.remove(move)
            if failure == "error":
                abort = run.request("abort")
                run.service.resultReady.emit(abort, {"kind": "error", "message": "The helper stopped."})
                run.service.pending.remove(abort)
            # ...which never said where the store is: no disk cache this session, nothing held.
            assert store_options() == {} and "off for this session" in cache_dir_refused()
            assert not run.service.cache_hold and run.mover.lock is None and not run.mover.running
            reject[0] = False
    finally:
        set_cache_dir(cache_dir())
        run.close()


def test_queued_requests_open_no_cache_once_it_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    service, started = started_service(monkeypatch)
    try:
        service.cache_options = lambda: {}  # The disk cache was turned off after these were queued.
        service.submit("a", 0, "/x", "cache_admin", {"cache": {"directory": "/gone"}, "action": "inventory"})
        service.submit("b", 0, "/y", "load", {"cache": {"directory": "/gone"}})
        service._dispatch()
        qtbot_wait(lambda: len(started) == 2)
        assert all(request.payload["cache"] == {} for request in started)
    finally:
        service.shutdown()


@pytest.mark.skipif(sys.platform != "win32" and os.geteuid() == 0, reason="root ignores read-only permissions")
def test_recovery_isnt_usable_after_a_failed_settings_write(tmp_path: Path) -> None:
    from helab.io_ops.admin import cache_move_job
    app, source, target = str(tmp_path / "app"), tmp_path / "caches", tmp_path / "moved"
    make_cache(source)
    record = cache_move.start(str(source), str(target), app, cache_move.RENAME)
    cache_move.move(record, app, lambda done, total: None, lambda: False)  # Renamed; setting still the source.
    folder = tmp_path / "settings"
    folder.mkdir()
    settings = QSettings(str(folder / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("dir_caches", str(source))
    settings.sync()
    os.chmod(folder / "settings.ini", 0o444)
    os.chmod(folder, 0o555)  # Saving the setting fails.
    events: list[Any] = []
    held = cache_locks.cache_lock(app)
    assert held.try_lock("startup-2")
    try:
        cache_move_job({"action": "recover", "app_dir": app, "settings": {"file": settings.fileName()},
                        "token": "startup-2"}, events.append)
    finally:
        held.unlock()
        os.chmod(folder, 0o755)
        os.chmod(folder / "settings.ini", 0o644)
    assert "couldn't save" in events[-1]["message"] and events[-1]["usable"] is False
    assert cache_move.read_record(app) is not None


def test_startup_turns_the_cache_off_rather_than_open_a_new_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.utils import constants
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("dir_caches", str(tmp_path / "renamed-away"))
    monkeypatch.setattr(constants, "_dir_caches_override", None)
    monkeypatch.setattr(constants, "DIR_CACHES_CANDIDATES", [str(tmp_path / "default")])
    constants.start_cache_dir(settings, usable=False, reason="The disk cache is off for this session: …")
    assert store_options() == {} and cache_dir_refused().startswith("The disk cache is off")
    assert settings.value("dir_caches", type=str) == str(tmp_path / "renamed-away")  # Not replaced.
    assert not (tmp_path / "default").exists()


def test_a_move_is_refused_while_an_earlier_one_is_unfinished(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    run = Run(qtbot, monkeypatch, tmp_path)
    try:
        cache_move.write_record(run.app, {"from": "/old", "to": run.source, "method": cache_move.COPY,
                                          "step": "setting_updated", "store_id": "s", "id": "earlier"})
        run.mover.change(run.target, run.parent)
        run.send(run.request("check"), {"kind": "move_check", "problem": "", "method": "copy", "bytes": 1, "free": 9})
        assert run.reports[-1][0] == "Can't move the disk cache now" and "Restart HeLab" in run.reports[-1][1]
        assert not run.service.cache_hold and run.mover.lock is None
    finally:
        run.close()


def test_the_cache_path_is_saved_only_at_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.utils import constants
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("dir_caches", str(tmp_path / "gone"))  # e.g. being renamed by a move right now.
    monkeypatch.setattr(constants, "_dir_caches_override", None)
    monkeypatch.setattr(constants, "DIR_CACHES_CANDIDATES", [str(tmp_path / "default")])
    path, _, _ = constants.resolve_cache_dir(settings)
    assert path == str(tmp_path / "default") and settings.value("dir_caches", type=str) == str(tmp_path / "gone")
    constants.start_cache_dir(settings)  # At startup, holding cache.lock: saved.
    assert settings.value("dir_caches", type=str) == str(tmp_path / "default") == cache_dir()


def test_cleanup_and_abort_touch_only_their_own_move(tmp_path: Path) -> None:
    from helab.io_ops.admin import cache_move_job
    app = str(tmp_path / "app")
    newer = {"from": str(tmp_path / "b"), "to": str(tmp_path / "c"), "method": cache_move.RENAME,
             "step": "renamed", "store_id": "s", "id": "newer"}
    cache_move.write_record(app, newer)
    held = cache_locks.cache_lock(app)
    assert held.try_lock("older")  # The HeLab that asked holds the cache.
    try:
        for action in ("cleanup", "abort"):
            events: list[Any] = []
            cache_move_job({"action": action, "app_dir": app, "from": str(tmp_path / "a"), "to": str(tmp_path / "b"),
                            "id": "older", "token": "older"}, events.append)
            assert events[-1]["left"] == [] and cache_move.read_record(app) == newer
    finally:
        held.unlock()
    # A helper whose HeLab no longer holds the cache (it ended, or another HeLab took over) does nothing.
    with pytest.raises(ValueError, match="no longer moving the cache"):
        cache_move_job({"action": "abort", "app_dir": app, "from": "", "to": "", "id": "newer", "token": "newer"},
                       lambda event: None)
    assert held.try_lock("startup-123")
    try:
        with pytest.raises(ValueError, match="no longer moving the cache"):
            cache_move_job({"action": "abort", "app_dir": app, "from": "", "to": "", "id": "newer", "token": "newer"},
                           lambda event: None)
    finally:
        held.unlock()
    assert cache_move.read_record(app) == newer


def test_startup_recovery_runs_in_a_helper_and_saves_the_setting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.io_ops.admin import cache_move_job
    app, source, target = str(tmp_path / "app"), tmp_path / "caches", tmp_path / "moved"
    store_id = make_cache(source)
    monkeypatch.setattr(cache_move, "same_disk", lambda a, b: False)
    cache_move.move(cache_move.start(str(source), str(target), app, cache_move.COPY), app,
                    lambda done, total: None, lambda: False)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("dir_caches", str(source))
    settings.sync()
    events: list[Any] = []
    held = cache_locks.cache_lock(app)
    assert held.try_lock("startup-1")
    try:
        cache_move_job({"action": "recover", "app_dir": app, "settings": {"file": settings.fileName()},
                        "token": "startup-1"}, events.append)
    finally:
        held.unlock()
    assert "finished" in events[-1]["message"] and events[-1]["usable"] is True
    settings.sync()
    assert settings.value("dir_caches", type=str) == str(target) and cache_move.valid_at(str(target), store_id)
    assert not source.exists() and cache_move.read_record(app) is None


def test_a_real_move_with_real_helpers(qtbot: QtBot, tmp_path: Path) -> None:
    """End to end: the helper renames the cache (same disk); HeLab then uses it there."""
    source, target, app = tmp_path / "caches", tmp_path / "elsewhere" / "caches", str(tmp_path / "app")
    store_id = make_cache(source)
    set_cache_dir(str(source))
    service = IOService()
    cache = get_folder_cache(service)
    parent = QWidget()
    qtbot.addWidget(parent)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    mover = CacheMover(cache, settings, app)
    mover.confirm = lambda text: True
    reports: list[str] = []
    mover.report = lambda title, text, folders: reports.append(text)
    finished: list[bool] = []
    mover.finished.connect(finished.append)
    try:
        mover.change(str(target), parent)
        qtbot.waitUntil(lambda: bool(finished), timeout=30_000)
        assert finished == [True] and not reports
        assert cache_dir() == str(target) and settings.value("dir_caches", type=str) == str(target)
        assert cache_move.valid_at(str(target), store_id) and not source.exists()
        assert cache_move.read_record(app) is None
        with CacheStore(store_root(str(target))) as store:
            assert store.read_dataset("/data/a").value is not None
    finally:
        mover.detach()
        service.shutdown()
        time.sleep(0.1)
