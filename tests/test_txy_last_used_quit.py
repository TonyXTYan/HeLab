"""Q~3 (Tony): a load moves a converted folder's ``last_used`` on at most hourly, and what that limit
(or a busy index) left unwritten is written as HeLab quits: by one best-effort helper (``cache_admin``
``mark_used``, the index only), never delaying quit beyond the quit window. With no quit window
every window hides at once and the process waits at most ``MARK_FLUSH_GRACE`` (the event loop: the
GUI never blocks). Synthetic folders under ``tmp_path`` only."""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterator

import pytest
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from helab.convert import provenance
from helab.io_ops import helab_txy, infra
from helab.io_ops.admin import cache_admin
from helab.utils.folder_cache import FolderCache, get_folder_cache, store_options
from helab.utils.io_service import IOService, get_io_service
from helab.views import HelabMainWindow as main_window
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
    assert helab_txy.mark_used(marks) == 1
    assert (last_used(root), last_used(root, "f" * 24)) == (200.0, 500.0)
    events: list[dict[str, Any]] = []
    cache_admin({"directory": str(tmp_path / "no-store-here")}, "mark_used", events.append,  # type: ignore[arg-type]
                marks=[[str(root), FOLDER, 250.0]])
    assert [event["kind"] for event in events] == ["admin_result"] and last_used(root) == 250.0
    assert not (tmp_path / "no-store-here").exists()  # The index only: the store isn't opened.


@pytest.fixture
def frozen() -> Iterator[FolderCache]:
    service = IOService()
    service.timer.stop()
    service._dispatch = lambda: None  # type: ignore[method-assign]
    yield FolderCache(service)
    service.shutdown()


def test_the_cache_remembers_unwritten_last_uses_and_flushes_them_once(frozen: FolderCache) -> None:
    cache = frozen
    assert not cache.flush_txy_marks() and not cache.service.pending  # Nothing skipped: nothing submitted.
    load = cache.service.pending
    from helab.utils.io_service import IORequest
    producer = IORequest("tab", 0, "/data/run", "load", {}, 60.0)
    for at in (5.0, 9.0, 7.0):
        cache.service.resultReady.emit(producer, {"kind": "txy_unmarked", "root": "/c", "folder": FOLDER, "at": at})
    cache.service.resultReady.emit(producer, {"kind": "txy_unmarked", "root": "/t", "folder": FOLDER, "at": 3.0})
    assert cache.txy_unmarked == {("/c", FOLDER): 9.0, ("/t", FOLDER): 3.0}
    assert cache.flush_txy_marks() and cache.txy_marks_flushing() and not cache.txy_unmarked
    [request] = load
    assert (request.operation, request.payload["action"]) == ("cache_admin", "mark_used")
    assert request.payload["params"]["marks"] == [["/c", FOLDER, 9.0], ["/t", FOLDER, 3.0]]
    assert request.payload["cache"] == store_options()
    assert not cache.flush_txy_marks()  # (Once.)
    cache.service.resultReady.emit(request, {"kind": "admin_result", "action": "mark_used", "next_deadline": None})
    assert cache.txy_marks_flushing()
    cache.service.resultReady.emit(request, {"kind": "error", "message": "failed"})
    assert not cache.txy_marks_flushing()


def window_cache(qtbot: QtBot) -> tuple[HelabMainWindow, FolderCache]:
    window = HelabMainWindow()
    qtbot.addWidget(window)
    window.show()
    return window, get_folder_cache(get_io_service())


def test_quit_writes_the_skipped_last_uses_with_every_window_hidden(qtbot: QtBot, tmp_path: Path) -> None:
    root = tmp_path / "converted-txy"
    root.mkdir()
    index_with(root, 100.0)
    window, cache = window_cache(qtbot)
    cache.txy_unmarked[(str(root), FOLDER)] = 200.0
    started = time.monotonic()
    window.close()
    assert not window._closing and window._quit_dialog is None  # No quit window,
    assert not [widget for widget in QApplication.topLevelWidgets() if widget.isVisible()]  # and nothing seen.
    qtbot.waitUntil(lambda: window._closing, timeout=int(main_window.MARK_FLUSH_GRACE * 1000) + 3000)
    assert time.monotonic() - started < main_window.MARK_FLUSH_GRACE + 2
    assert last_used(root) == 200.0


@pytest.mark.parametrize("outcome", ["hangs", "fails"])
def test_quit_never_waits_past_its_grace_for_the_flush(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
                                                       outcome: str) -> None:
    window, cache = window_cache(qtbot)
    cache.txy_unmarked[("/no/such/converted-txy", FOLDER)] = 1.0
    if outcome == "hangs":
        monkeypatch.setattr(main_window, "MARK_FLUSH_GRACE", 0.5)
        def hanging() -> bool:
            cache._mark_flush = "never ends"
            return True
        monkeypatch.setattr(cache, "flush_txy_marks", hanging)
    else:
        def failing() -> bool:
            assert FolderCache.flush_txy_marks(cache)
            request = next(r for r in (*cache.service.pending, *cache.service.active) if r.owner == cache._mark_flush)
            cache.service.resultReady.emit(request, {"kind": "error", "message": "the helper failed"})
            return True
        monkeypatch.setattr(cache, "flush_txy_marks", failing)
    started = time.monotonic()
    window.close()
    assert not window._closing and not window.isVisible()
    qtbot.waitUntil(lambda: window._closing, timeout=3000)
    took = time.monotonic() - started
    assert took < main_window.MARK_FLUSH_GRACE + 1.5
    if outcome == "hangs":
        assert took >= main_window.MARK_FLUSH_GRACE - 0.05  # It waited, but no longer.


def test_nothing_skipped_quits_at_once_and_submits_nothing(qtbot: QtBot) -> None:
    window, cache = window_cache(qtbot)
    submitted: list[str] = []
    original = cache.service.submit

    def watching(owner: str, generation: int, path: str, operation: str, *args: Any, **kwargs: Any) -> bool:
        submitted.append(operation if operation != "cache_admin" else (args[0] if args else kwargs["payload"])["action"])
        return original(owner, generation, path, operation, *args, **kwargs)
    cache.service.submit = watching  # type: ignore[method-assign]
    window.close()
    assert window._closing and "mark_used" not in submitted


def test_with_a_quit_window_up_the_flush_runs_meanwhile_and_ends_with_it(qtbot: QtBot, tmp_path: Path) -> None:
    window, cache = window_cache(qtbot)
    cache.txy_unmarked[(str(tmp_path / "converted-txy"), FOLDER)] = 1.0
    path = str(tmp_path / "run")
    cache._deferred_saves[path] = ("owner", {})
    window.close()
    assert window._quit_dialog is not None and window._marks_wait is None and window.isVisible()
    assert not cache.txy_unmarked  # (Submitted.)
    del cache._deferred_saves[path]
    qtbot.waitUntil(lambda: window._closing, timeout=3000)
