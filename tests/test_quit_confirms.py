"""Quit that confirms (roadmaps/smoke-automation.md): quitting with nothing to save closes at once and
the process ends within a second of its event loop (``helab/views/quit_watch.py``), even with a thread
left running; with something still being saved, the quit window lists every operation by kind, folder,
state and how long it has run (``FolderCache.quit_entries``), and closes by itself when they end."""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from PyQt6 import QtWebEngineWidgets  # noqa: F401  (before any QApplication: the main window)
from PyQt6.QtWidgets import QDialog
from pytestqt.qtbot import QtBot

from helab.utils import folder_cache
from helab.utils.folder_cache import (
    PRESETS_SAVING, QUIT_CONSTANTS, QUIT_CONVERT, QUIT_FLAGS, QUIT_LAST_USED, QUIT_LIVE, QUIT_MAKE_ROOM, QUIT_PRESETS,
    QUIT_RESULT, QUIT_SAVE, TXY_LAST_USED, FolderCache, HeldWrite, QuitSave, SharedJob)
from helab.utils.io_service import IOService
from helab.views import quit_watch
from helab.views.QuitSaveDialog import QuitSaveDialog

CHECKOUT = Path(__file__).resolve().parent.parent
RUN = "/helab-test-nowhere/day/run"  # Never read: the entries are set in memory.


def test_the_watch_ends_a_process_left_running_with_its_exit_code(caplog: pytest.LogCaptureFixture) -> None:
    ended: list[int] = []
    with caplog.at_level(logging.WARNING):
        quit_watch.exit_soon(3, grace=0.05, exit=ended.append).join(5)
    assert ended == [3]
    assert "still running 0.1 s after its windows closed" in caplog.text and "MainThread" in caplog.text


def test_a_process_with_a_thread_still_running_ends_within_the_grace() -> None:
    """A real process whose teardown would wait a minute on a thread (not a daemon) ends at once."""
    script = ("import threading, time\n"
              "threading.Thread(target=time.sleep, args=(60,), name='lingering').start()\n"
              "from helab.views import quit_watch\n"
              "quit_watch.exit_soon(3, grace=0.3)\n")
    started = time.monotonic()
    done = subprocess.run([sys.executable, "-c", script], cwd=CHECKOUT, capture_output=True, text=True, timeout=60,
                          env={**os.environ, "PYTHONPATH": str(CHECKOUT)})
    assert done.returncode == 3, done.stderr
    assert time.monotonic() - started < 20  # (The interpreter's start included.)
    assert "lingering (daemon=False)" in done.stderr


def test_quitting_with_nothing_to_save_closes_within_a_second(qtbot: QtBot) -> None:
    from helab.views.HelabMainWindow import HelabMainWindow
    window = HelabMainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(200)
    started = time.monotonic()
    window.close()
    assert window._closing and window._quit_dialog is None
    assert time.monotonic() - started < 1.0


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch) -> Any:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    made = FolderCache(service)
    yield made
    service.shutdown()


def with_every_kind(cache: FolderCache) -> float:
    """One operation of each kind quitting waits for, started 65 s ago (as the cache keeps them)."""
    since = time.monotonic() - 65
    for owner, live in (("writer-live", True), ("writer", False)):
        cache._finishing[owner] = f"{RUN}-{owner}"
        cache._finishing_created[owner] = since
        cache._finishing_live[owner] = live
        cache._disk_cache_writers.add(owner)
    load = SharedJob("load-live", RUN, "load", 0, {"save": True, "save_memory": True}, created=since)
    cache.jobs[("load", RUN)] = load
    cache._deferred_saves[f"{RUN}-next"] = ("owner", {"save": True})
    cache._deferred_since[f"{RUN}-next"] = since
    cache._pref_writes["flags"] = (f"{RUN}-flags", 1.0, "owner")
    cache._constant_writes["constants"] = (f"{RUN}-constants", 1.0, "owner")
    cache._result_writes["result"] = f"{RUN}-result"
    cache._result_ops["result"] = (f"{RUN}-result", since, "")
    cache._result_writes["room"] = f"{RUN}-room"
    cache._admin["room"] = "adopt_result"
    cache._probe_held.append(HeldWrite("room", RUN, "cache_admin", {}))  # Held for the store's check.
    for owner in ("flags", "constants", "room", "presets"):
        cache._started[owner] = since
    cache._preset_jobs["presets"] = {("script", "id", "name"): 1.0}
    cache.presets_unsaved[("script", "id", "name")] = ""
    cache._mark_flush, cache._mark_flush_started = "marks", since
    cache.jobs[("convert", f"{RUN}-raw")] = SharedJob("convert", f"{RUN}-raw", "convert", 0, {}, created=since)
    return since


def test_every_kind_is_an_entry_with_its_state_and_start(cache: FolderCache) -> None:
    since = with_every_kind(cache)
    assert cache.quit_entries() == [
        QuitSave(QUIT_LIVE, f"{RUN}-writer-live", "writing", since),
        QuitSave(QUIT_SAVE, f"{RUN}-writer", "writing", since),
        QuitSave(QUIT_LIVE, RUN, "reading", since),
        QuitSave(QUIT_SAVE, f"{RUN}-next", "waiting", since),
        QuitSave(QUIT_FLAGS, f"{RUN}-flags", "writing", since),
        QuitSave(QUIT_CONSTANTS, f"{RUN}-constants", "writing", since),
        QuitSave(QUIT_RESULT, f"{RUN}-result", "writing", since),
        QuitSave(QUIT_MAKE_ROOM, f"{RUN}-room", "held", since),
        QuitSave(QUIT_PRESETS, PRESETS_SAVING, "writing", since),
        QuitSave(QUIT_LAST_USED, TXY_LAST_USED, "writing", since),
        QuitSave(QUIT_CONVERT, f"{RUN}-raw", "converting", since)]
    # ``quit_saves`` still names each folder once; ``quit_save_started`` gives the earliest start.
    assert cache.quit_saves() == list(dict.fromkeys(entry.path for entry in cache.quit_entries()))
    assert cache.quit_save_started(TXY_LAST_USED) == since and cache.quit_save_started("/nowhere") is None


def lines(dialog: QuitSaveDialog) -> list[str]:
    rows = (dialog.folders.item(row) for row in range(dialog.folders.count()))
    return [item.text() for item in rows if item is not None]


def test_the_quit_window_lists_each_operation_and_closes_when_they_end(qtbot: QtBot, cache: FolderCache) -> None:
    with_every_kind(cache)
    dialog = QuitSaveDialog(cache)
    qtbot.addWidget(dialog)
    results: list[int] = []
    dialog.finished.connect(results.append)
    dialog.open()
    assert [re.sub(r" · 1:0\d$", " · 1:0x", line) for line in lines(dialog)] == [
        "run-writer-live — Live's new shots, writing · 1:0x",
        "run-writer — its data, writing · 1:0x",
        "run — Live's new shots, reading them again · 1:0x",
        "run-next — its data, waiting for its previous save · 1:0x",
        "run-flags — its flags, writing · 1:0x",
        "run-constants — its constants, writing · 1:0x",
        "run-result — a plot's result, writing · 1:0x",
        "run-room — making room for a plot's result, waiting for the disk cache's identity check · 1:0x",
        "Presets — writing · 1:0x",
        "Converted TXY last used — recording when HeLab's converted TXY were last used · 1:0x",
        "run-raw — converting raw files · 1:0x"]
    assert dialog.label.text() == ("Saving 9 folders and presets to the disk cache and recording when converted "
                                   "TXY were last used before HeLab quits:")
    # One ends: its line goes, the others stay (updated in place); all end: the window closes by itself.
    cache.jobs.pop(("convert", f"{RUN}-raw"))
    dialog.refresh()
    assert len(lines(dialog)) == 10 and not results
    for name in ("_finishing", "_disk_cache_writers", "jobs", "_deferred_saves", "_pref_writes", "_constant_writes",
                 "_result_writes", "_preset_jobs"):
        getattr(cache, name).clear()
    cache._mark_flush = ""
    cache.quitSavesChanged.emit()
    qtbot.waitUntil(lambda: bool(results))
    assert results == [QDialog.DialogCode.Accepted] and not dialog.skipped and not dialog.isVisible()


def test_quit_now_skips_them(qtbot: QtBot, cache: FolderCache) -> None:
    with_every_kind(cache)
    dialog = QuitSaveDialog(cache)
    qtbot.addWidget(dialog)
    results: list[int] = []
    dialog.finished.connect(results.append)
    dialog.open()
    dialog.quit_now_button.click()
    assert results == [QDialog.DialogCode.Rejected] and dialog.skipped
    assert folder_cache.QUIT_CONVERT in {entry.kind for entry in cache.quit_entries()}  # (Left to the exit.)
