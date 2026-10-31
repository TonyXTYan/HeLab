"""A39.3 (Q39.1): one HeLab app running per computer. A second start says one is running and stops
before opening anything; the lock is in the app folder (an override's folder has its own), and a lock
whose HeLab ended, crashed included, doesn't block."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType
from typing import Any, Iterator

import pytest
from PyQt6 import QtWebEngineWidgets  # noqa: F401  (before any QApplication: helab.main)
from PyQt6.QtWidgets import QApplication, QMessageBox
from pytestqt.qtbot import QtBot

from helab.utils.cache_locks import FileLock, take_running
from test_cache_mover import free_soon, hold_in_another_process


@pytest.fixture
def entry() -> Iterator[ModuleType]:
    """``helab.main``, its import's ``coloredlogs.install`` (a DEBUG handler on the root logger) undone."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    try:
        import helab.main
        yield helab.main
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)


def test_the_running_lock_is_held_by_one_process_and_freed_when_it_ends(tmp_path: Path) -> None:
    app = str(tmp_path / "app")
    other = hold_in_another_process(os.path.join(app, "running.lock"))
    try:
        assert take_running(app) == (None, "")  # (The holder here writes no pid.)
    finally:
        other.kill()
        other.wait()
    # Waited for the lock itself: Windows frees a killed process's locks a little later (``free_soon``).
    lock = free_soon(lambda: take_running(app)[0])
    assert lock is not None
    try:
        assert Path(app, "running.lock").read_text() == str(os.getpid())
        assert take_running(app) == (None, str(os.getpid()))  # (Another lock, even in this process.)
        override, _ = take_running(str(tmp_path / "override"))  # Another app folder: its own.
        assert override is not None
        override.unlock()
    finally:
        lock.unlock()


def test_a_lock_naming_a_process_that_ended_doesnt_block(tmp_path: Path) -> None:
    ended = subprocess.Popen([sys.executable, "-c", "pass"])
    ended.wait()
    (tmp_path / "running.lock").write_text(str(ended.pid))
    lock, pid = take_running(str(tmp_path))
    try:
        assert lock is not None and pid == "" and (tmp_path / "running.lock").read_text() == str(os.getpid())
    finally:
        assert lock is not None
        lock.unlock()


class WentOn:
    """The app ``main()`` makes: anything after the check fails the test."""

    def __init__(self, argv: list[str]) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"HeLab went on after the check: app.{name}")


def test_a_second_start_says_one_is_running_and_stops_before_opening_anything(
        entry: ModuleType, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """As a second HeLab while another holds the lock (with its pid): ``main()`` shows one message naming
    it and exits 1, before the app's style, the cache, helpers or settings."""
    app = tmp_path / "app"
    holder = FileLock(str(app / "running.lock"))
    holder.try_lock("4242")
    shown: list[tuple[str, str]] = []

    def opened(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("HeLab went on after the check")
    monkeypatch.setattr(entry, "app_folder", lambda: str(app))
    monkeypatch.setattr(entry.app_log, "start_log_file", lambda folder: None)
    monkeypatch.setattr(entry.app_log, "catch_unhandled", lambda notice=None: None)
    monkeypatch.setattr(entry, "QApplication", WentOn)
    monkeypatch.setattr(entry, "_start_cache", opened)
    monkeypatch.setattr(entry, "app_settings", opened)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda parent, title, text: shown.append((title, text))))
    try:
        with pytest.raises(SystemExit) as stopped:
            entry.main()
        assert stopped.value.code == 1
        assert shown == [("HeLab is running", "HeLab is already running on this computer (process 4242). Use its "
                          "window, or quit it before starting HeLab again.")]
        assert os.listdir(app) == ["running.lock"] and not entry._RUNNING_LOCK
    finally:
        holder.unlock()
    assert QApplication.instance() is not None


def test_the_first_start_holds_the_lock_for_its_life(entry: ModuleType, tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(entry, "app_folder", lambda: str(tmp_path))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda parent, title, text: None))
    try:
        assert entry._another_running() is False and len(entry._RUNNING_LOCK) == 1
        assert entry._another_running() is True  # (Its lock is taken: as another HeLab finds it.)
    finally:
        for lock in entry._RUNNING_LOCK:
            lock.unlock()
        entry._RUNNING_LOCK.clear()


def test_an_app_folder_that_cant_be_checked_doesnt_stop_helab(entry: ModuleType, tmp_path: Path,
                                                              monkeypatch: pytest.MonkeyPatch,
                                                              caplog: pytest.LogCaptureFixture) -> None:
    def refused(app_dir: str) -> Any:
        raise PermissionError(13, "Permission denied", app_dir)
    monkeypatch.setattr("helab.utils.cache_locks.take_running", refused)
    with caplog.at_level(logging.WARNING):
        assert entry._another_running() is False
    assert "Couldn't check for another running HeLab" in caplog.text and not entry._RUNNING_LOCK
