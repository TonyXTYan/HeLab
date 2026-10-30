"""Q30.3 (Tony): a load moves a converted folder's ``last_used`` on at most hourly, and what that limit
(or a busy index) left unwritten is written as HeLab quits, by one helper (``cache_admin``
``mark_used``, the index only) that is a save like the others: the quit window shows it
(``TXY_LAST_USED``), it stops after ``MARK_FLUSH_TIMEOUT`` without progress, and Quit now skips it.
A30.4: and in the background about every ``MARK_FLUSH_INTERVAL`` while any are owed, except while the
disk cache is off, working offline or the foreground works; quitting takes over.
Synthetic folders under ``tmp_path`` only."""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterator

import pytest
from pytestqt.qtbot import QtBot

from helab.convert import provenance
from helab.io_ops import helab_txy, infra
from helab.io_ops.admin import cache_admin
from helab.utils import folder_cache
from helab.utils.folder_cache import MARK_FLUSH_TIMEOUT, TXY_LAST_USED, FolderCache, get_folder_cache, store_options
from helab.utils.io_service import IOService, get_io_service
from helab.views.HelabMainWindow import HelabMainWindow
from test_txy_sources import _key, loaded, make_run, options, run_load
from helab.utils import txy_sources

FOLDER = "0123456789abcdef01234567"


def index_with(root: Path, last_used: float, folder: str = FOLDER) -> None:
    with contextlib.closing(provenance.open_index(str(root), write=True)) as index:
        index.conn.execute("INSERT INTO folders (folder, key, source, bytes, last_used) VALUES (?, ?, ?, ?, ?)",
                           (folder, "path:/data/run", "/data/run", 0, last_used))


def reader(root: Path | str) -> provenance.TxyIndex:
    index = provenance.open_index(str(root), write=False)
    assert index is not None
    return index


def last_used(root: Path | str, folder: str = FOLDER) -> float:
    with reader(root) as index:
        return {row[0]: row[4] for row in index.folders()}[folder]


@pytest.fixture
def unmarked(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The ``txy_unmarked`` events a load sends (to the helper's stdout, in a helper)."""
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(infra, "emit", sent.append)
    return sent


def test_a_load_says_which_last_uses_it_didnt_write(tmp_path: Path, private_store: str,
                                                    unmarked: list[dict[str, Any]]) -> None:
    source = make_run(tmp_path, private_store)
    [folder] = [path for path in helab_txy.folders(str(source), options(tmp_path, private_store),
                                                   _key(source, private_store)) if os.path.isdir(path)]
    root, name = os.path.split(folder)
    load_helab = options(tmp_path, private_store, txy_sources.HELAB)
    with reader(root) as index:
        index.conn.execute("UPDATE folders SET last_used = 1.0")
    loaded(run_load(source, tmp_path, private_store, load_helab))
    assert unmarked == [] and last_used(root, name) > time.time() - 60  # Written: nothing owed.
    before = time.time()
    loaded(run_load(source, tmp_path, private_store, load_helab))  # Within the hour: skipped, and said.
    [event] = unmarked
    assert (event["kind"], event["root"], event["folder"]) == ("txy_unmarked", root, name)
    assert before <= event["at"] <= time.time()
    # A busy index (a conversion's write held past the 200 ms): skipped too, and said.
    unmarked.clear()
    with reader(root) as index:
        index.conn.execute("UPDATE folders SET last_used = 1.0")
    with contextlib.closing(sqlite3.connect(os.path.join(root, provenance.INDEX_NAME), isolation_level=None)) as holder:
        holder.execute("BEGIN IMMEDIATE")
        loaded(run_load(source, tmp_path, private_store, load_helab))
        holder.execute("ROLLBACK")
    assert [event["folder"] for event in unmarked] == [name] and last_used(root, name) == 1.0


def test_the_flush_writes_only_newer_last_uses_and_never_the_store(tmp_path: Path, private_store: str) -> None:
    root = tmp_path / "converted-txy"
    root.mkdir()
    index_with(root, 100.0)
    index_with(root, 500.0, folder="f" * 24)
    marks = [[str(root), FOLDER, 200.0], [str(root), "f" * 24, 300.0], [str(root), "e" * 24, 400.0],
             [str(tmp_path / "missing"), FOLDER, 900.0]]
    assert helab_txy.mark_used(marks) == []  # Older, unknown and missing: nothing to try again.
    assert (last_used(root), last_used(root, "f" * 24)) == (200.0, 500.0)
    events: list[dict[str, Any]] = []
    cache_admin({"directory": str(tmp_path / "no-store-here")}, "mark_used", events.append,  # type: ignore[arg-type]
                marks=[[str(root), FOLDER, 250.0]])
    assert [(event["kind"], event["unwritten"]) for event in events] == [("admin_result", [])]
    assert last_used(root) == 250.0
    assert not (tmp_path / "no-store-here").exists()  # The index only: the store isn't opened.
    # A busy index (a conversion's write held past 500 ms): those marks are said, to try again.
    with contextlib.closing(sqlite3.connect(root / provenance.INDEX_NAME, isolation_level=None)) as holder:
        holder.execute("BEGIN IMMEDIATE")
        assert helab_txy.mark_used([[str(root), FOLDER, 260.0]]) == [[str(root), FOLDER, 260.0]]
        holder.execute("ROLLBACK")
    assert last_used(root) == 250.0


@pytest.fixture
def frozen() -> Iterator[FolderCache]:
    service = IOService()
    service.timer.stop()
    service._dispatch = lambda: None  # type: ignore[method-assign]
    yield FolderCache(service)
    service.shutdown()


def test_the_cache_remembers_unwritten_last_uses_and_flushes_them_once_as_a_quit_save(frozen: FolderCache) -> None:
    cache = frozen
    changed: list[bool] = []
    cache.quitSavesChanged.connect(lambda: changed.append(True))
    assert not cache.flush_txy_marks() and not cache.service.pending  # Nothing skipped: nothing submitted.
    assert not changed and cache.quit_saves() == []
    load = cache.service.pending
    from helab.utils.io_service import IORequest
    producer = IORequest("tab", 0, "/data/run", "load", {}, 60.0)
    for at in (5.0, 9.0, 7.0):
        cache.service.resultReady.emit(producer, {"kind": "txy_unmarked", "root": "/c", "folder": FOLDER, "at": at})
    cache.service.resultReady.emit(producer, {"kind": "txy_unmarked", "root": "/t", "folder": FOLDER, "at": 3.0})
    assert cache.txy_unmarked == {("/c", FOLDER): 9.0, ("/t", FOLDER): 3.0} and cache.quit_saves() == []
    before = time.monotonic()
    assert cache.flush_txy_marks() and cache.txy_marks_flushing() and not cache.txy_unmarked and changed
    [request] = load
    assert (request.operation, request.payload["action"], request.timeout) == ("cache_admin", "mark_used", 5.0)
    assert MARK_FLUSH_TIMEOUT == 5.0
    assert request.payload["params"]["marks"] == [["/c", FOLDER, 9.0], ["/t", FOLDER, 3.0]]
    assert request.payload["cache"] == store_options()
    # A save like the others: its own entry (its kind), with its start.
    assert cache.quit_saves() == [TXY_LAST_USED]
    started = cache.quit_save_started(TXY_LAST_USED)
    assert started is not None and before <= started <= time.monotonic()
    assert cache.quit_save_started("/data/run") is None
    assert not cache.flush_txy_marks()  # (Once.)
    cache.service.resultReady.emit(request, {"kind": "admin_result", "action": "mark_used", "next_deadline": None})
    assert cache.quit_saves() == [TXY_LAST_USED]
    changed.clear()
    cache.service.resultReady.emit(request, {"kind": "error", "message": "failed"})
    assert not cache.txy_marks_flushing() and cache.quit_saves() == [] and changed
    assert cache.quit_save_started(TXY_LAST_USED) is None


def window_cache(qtbot: QtBot) -> tuple[HelabMainWindow, FolderCache]:
    window = HelabMainWindow()
    qtbot.addWidget(window)
    return window, get_folder_cache(get_io_service())


def test_quit_writes_the_skipped_last_uses_in_the_quit_window(qtbot: QtBot, tmp_path: Path) -> None:
    root = tmp_path / "converted-txy"
    root.mkdir()
    index_with(root, 100.0)
    window, cache = window_cache(qtbot)
    cache.txy_unmarked[(str(root), FOLDER)] = 200.0
    window.close()
    dialog = window._quit_dialog
    assert not window._closing and dialog is not None
    assert [dialog.folders.item(row).text() for row in range(dialog.folders.count())] == [  # type: ignore[union-attr]
        f"{TXY_LAST_USED} — recording when HeLab's converted TXY were last used"]
    assert dialog.label.text() == "Recording when converted TXY were last used before HeLab quits:"
    qtbot.waitUntil(lambda: window._closing, timeout=30000)
    assert last_used(root) == 200.0


def test_a_flush_without_progress_stops_by_itself_and_ends_the_quit_window(
        qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Its no-progress limit (5 s; 0.2 s here) ends it: with the index's write lock held, its write waits
    500 ms without a word, so the limit comes first; an error, so the entry goes and the window closes
    by itself, as for any save that stops. The use stays unwritten."""
    monkeypatch.setattr(folder_cache, "MARK_FLUSH_TIMEOUT", 0.2)
    root = tmp_path / "converted-txy"
    root.mkdir()
    index_with(root, 100.0)
    window, cache = window_cache(qtbot)
    cache.txy_unmarked[(str(root), FOLDER)] = 200.0
    with contextlib.closing(sqlite3.connect(root / provenance.INDEX_NAME, isolation_level=None)) as holder:
        holder.execute("BEGIN IMMEDIATE")  # (A conversion's write, held.)
        window.close()
        assert window._quit_dialog is not None and cache.quit_saves() == [TXY_LAST_USED]
        qtbot.waitUntil(lambda: window._closing, timeout=10000)
        holder.execute("ROLLBACK")
    assert any(record.getMessage().startswith("Converted TXY last used: Timed out") for record in caplog.records)
    assert last_used(root) == 100.0


def test_quit_now_skips_the_flush(qtbot: QtBot, tmp_path: Path) -> None:
    window, cache = window_cache(qtbot)
    cache.txy_unmarked[(str(tmp_path / "converted-txy"), FOLDER)] = 1.0
    window.close()
    dialog = window._quit_dialog
    assert dialog is not None and TXY_LAST_USED in cache.quit_saves()
    dialog.quit_now_button.click()
    qtbot.waitUntil(lambda: window._closing, timeout=3000)


def test_nothing_skipped_quits_at_once_and_submits_nothing(qtbot: QtBot) -> None:
    window, cache = window_cache(qtbot)
    submitted: list[str] = []
    original = cache.service.submit

    def watching(owner: str, generation: int, path: str, operation: str, *args: Any, **kwargs: Any) -> bool:
        submitted.append(operation if operation != "cache_admin" else (args[0] if args else kwargs["payload"])["action"])
        return original(owner, generation, path, operation, *args, **kwargs)
    cache.service.submit = watching  # type: ignore[method-assign]
    window.close()
    assert window._closing and window._quit_dialog is None and "mark_used" not in submitted


def test_beside_other_saves_the_flush_is_one_more_entry(qtbot: QtBot, tmp_path: Path) -> None:
    window, cache = window_cache(qtbot)
    cache.txy_unmarked[(str(tmp_path / "converted-txy"), FOLDER)] = 1.0
    path = str(tmp_path / "run")
    cache._deferred_saves[path] = ("owner", {})
    window.close()
    dialog = window._quit_dialog
    assert dialog is not None and cache.quit_saves()[0] == path
    assert dialog.label.text() == ("Saving 1 folder to the disk cache and recording when converted TXY were last "
                                   "used before HeLab quits:")
    del cache._deferred_saves[path]
    qtbot.waitUntil(lambda: window._closing, timeout=30000)


def owed(cache: FolderCache, root: str, at: float, folder: str = FOLDER) -> None:
    """A load's ``txy_unmarked``, as ``resultReady`` brings it."""
    from helab.utils.io_service import IORequest
    cache.service.resultReady.emit(IORequest("tab", 0, "/data/run", "load", {}, 60.0),
                                   {"kind": "txy_unmarked", "root": root, "folder": folder, "at": at})


def test_owed_last_uses_are_written_in_the_background_about_every_ten_minutes(frozen: FolderCache,
                                                                                caplog: pytest.LogCaptureFixture) -> None:
    cache = frozen
    assert not cache._marks_timer.isActive()  # Nothing owed: no timer.
    owed(cache, "/c", 5.0)
    assert cache._marks_timer.isActive() and cache._marks_timer.interval() == 600_000
    assert folder_cache.MARK_FLUSH_INTERVAL == 600.0
    owed(cache, "/c", 6.0, folder="f" * 24)
    assert cache._marks_timer.remainingTime() > 590_000  # A second skip doesn't put it off or bring it on.
    cache._marks_timer.stop()
    cache._marks_due()
    [request] = cache.service.pending
    assert (request.operation, request.payload["action"], request.timeout, request.priority) == (
        "cache_admin", "mark_used", MARK_FLUSH_TIMEOUT, False)
    assert request.payload["params"]["marks"] == [["/c", FOLDER, 5.0], ["/c", "f" * 24, 6.0]]
    assert cache.quit_saves() == []  # In the background: not a quit save, no window.
    # Owed until written: one at a time, and a newer skip meanwhile waits for it.
    owed(cache, "/c", 7.0)
    assert not cache._marks_timer.isActive()
    cache._marks_due()
    assert list(cache.service.pending) == [request]
    cache.service.resultReady.emit(request, {"kind": "admin_result", "action": "mark_used", "next_deadline": None,
                                             "unwritten": [["/c", "f" * 24, 6.0]]})  # (Its index was busy.)
    cache.service.resultReady.emit(request, {"kind": "done"})
    assert cache.txy_unmarked == {("/c", FOLDER): 7.0, ("/c", "f" * 24): 6.0}
    assert cache._marks_timer.isActive() and cache._marks_timer.interval() == 600_000
    # A failed helper's marks stay owed too, and are tried again in ten minutes.
    cache._marks_timer.stop()
    cache._marks_due()
    request = cache.service.pending[-1]
    cache.service.resultReady.emit(request, {"kind": "error", "message": "Timed out"})
    assert len(cache.txy_unmarked) == 2 and cache._marks_timer.interval() == 600_000
    assert any(record.getMessage() == "Converted TXY last used: Timed out" for record in caplog.records)
    cache._marks_timer.stop()
    cache._marks_due()
    request = cache.service.pending[-1]
    cache.service.resultReady.emit(request, {"kind": "admin_result", "action": "mark_used", "next_deadline": None,
                                             "unwritten": []})
    cache.service.resultReady.emit(request, {"kind": "done"})
    assert cache.txy_unmarked == {} and not cache._marks_timer.isActive()  # All written: no timer.


def test_the_background_write_waits_while_offline_cache_off_or_the_foreground_works(
        frozen: FolderCache, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = frozen
    owed(cache, "/c", 5.0)
    for why, again in (("offline", 600_000), ("cache off", 600_000), ("foreground", 5_000)):
        with monkeypatch.context() as patch:
            if why == "offline":
                patch.setattr(cache.service, "offline", True)
            elif why == "cache off":
                patch.setattr(folder_cache, "store_options", lambda: {})
            else:
                patch.setattr(cache.service, "hold_background", lambda now=None: True)
            cache._marks_timer.stop()
            cache._marks_due()
            assert not cache.service.pending, why
            assert cache._marks_timer.isActive() and cache._marks_timer.interval() == again, why
    cache._marks_timer.stop()
    cache._marks_due()  # None of them now: it goes.
    assert [request.payload["action"] for request in cache.service.pending] == ["mark_used"]


def test_quitting_takes_over_from_the_background_write(frozen: FolderCache) -> None:
    cache = frozen
    owed(cache, "/c", 5.0)
    cache._marks_timer.stop()
    cache._marks_due()
    [background] = cache.service.pending
    owed(cache, "/c", 6.0, folder="f" * 24)
    passed_on: list[str] = []
    cache.resultReady.connect(lambda request, event: passed_on.append(request.owner))
    assert cache.flush_txy_marks()  # The background one is stopped; quitting writes all that is owed.
    assert background.owner not in passed_on  # (Its ``cancelled`` ends it here: Nit-11.)
    [flush] = cache.service.pending
    assert background.cancelled.is_set() and flush is not background and flush.priority
    assert flush.payload["params"]["marks"] == [["/c", FOLDER, 5.0], ["/c", "f" * 24, 6.0]]
    assert cache.quit_saves() == [TXY_LAST_USED] and not cache._marks_timer.isActive()
    owed(cache, "/c", 7.0)  # (A save's load still ending.) No more background writes this session.
    cache._marks_due()
    assert list(cache.service.pending) == [flush] and not cache._marks_timer.isActive()
    cache.shutdown()


def test_nothing_owed_at_quit_still_stops_the_background_timer(frozen: FolderCache) -> None:
    cache = frozen
    assert not cache.flush_txy_marks() and not cache.service.pending
    owed(cache, "/c", 5.0)
    assert not cache._marks_timer.isActive()


def test_the_background_write_reaches_the_index_and_retries_a_busy_one(
        qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """End to end, with a real helper (the interval 0.2 s here): a busy index's mark stays owed and
    the next round writes it; then nothing is owed and no timer runs."""
    monkeypatch.setattr(folder_cache, "MARK_FLUSH_INTERVAL", 0.2)
    root = tmp_path / "converted-txy"
    root.mkdir()
    index_with(root, 100.0)
    cache = get_folder_cache(get_io_service())
    submitted: list[str] = []
    original = cache.service.submit

    def watching(owner: str, generation: int, path: str, operation: str, *args: Any, **kwargs: Any) -> bool:
        if operation == "cache_admin":
            submitted.append(owner)
        return original(owner, generation, path, operation, *args, **kwargs)
    monkeypatch.setattr(cache.service, "submit", watching)
    with contextlib.closing(sqlite3.connect(root / provenance.INDEX_NAME, isolation_level=None)) as holder:
        holder.execute("BEGIN IMMEDIATE")  # (A conversion's write, held.)
        owed(cache, str(root), 200.0)
        qtbot.waitUntil(lambda: len(submitted) >= 1 and not cache._mark_background, timeout=20000)
        assert cache.txy_unmarked == {(str(root), FOLDER): 200.0}
        holder.execute("ROLLBACK")
    qtbot.waitUntil(lambda: not cache.txy_unmarked, timeout=20000)
    assert last_used(root) == 200.0 and len(submitted) >= 2 and not cache._marks_timer.isActive()
