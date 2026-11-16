"""No HeLab starts while HeLab's updater changes its code and venv (``update.lock`` in the app folder, held by
``helab/updates/updater.py``; its side is in ``tests/test_updates_updater.py``). The app and ``helab convert``
take their own lock first and look at the updater's second, the updater the other way round, so whichever
comes later sees the other; the start the updater makes itself carries the lock's token and goes on."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from types import ModuleType
from typing import Any, Iterator

import pytest
from PyQt6 import QtWebEngineWidgets  # noqa: F401  (before any QApplication: helab.main)
from PyQt6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from helab.utils import cache_locks
from helab.utils.cache_locks import FileLock, take_running, update_in_progress

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "0123abcd4567ef89"

# ``helab <arguments>`` as the entry point runs it, saying how the import of ``helab.main`` ended and what it
# had loaded by then.
START = (
    "import os, sys; sys.path.insert(0, sys.argv[1]); sys.argv = ['helab', *sys.argv[2:]]"
    "\ntry: import helab.main"
    "\nexcept SystemExit as exc: print('exit', exc.code)"
    "\nelse: print('no exit: HeLab would start')"
    "\nprint('loaded', sorted(m for m in ('PyQt6', 'helab.utils.constants', 'helab.convert_cli', 'helab.cache_cli')"
    " if m in sys.modules))"
)


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


@pytest.fixture
def updating(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """An app folder whose ``update.lock`` an updater holds, with ``TOKEN`` in it."""
    monkeypatch.delenv(cache_locks.UPDATE_TOKEN_ENV, raising=False)
    app = tmp_path / "app"
    lock = FileLock(str(app / cache_locks.UPDATE_LOCK))
    assert lock.try_lock(TOKEN)
    try:
        yield app
    finally:
        lock.unlock()


def start(app: Path, *arguments: str, token: str = "") -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, HELAB_APP_DIR_OVERRIDE=str(app), QT_QPA_PLATFORM="offscreen")
    env.pop(cache_locks.UPDATE_TOKEN_ENV, None)
    if token:
        env[cache_locks.UPDATE_TOKEN_ENV] = token
    return subprocess.run([sys.executable, "-c", START, str(ROOT), *arguments], cwd=app.parent, env=env,
                          capture_output=True, text=True, timeout=180)


@pytest.mark.parametrize("arguments", [["convert", "--watch", "nowhere", "--once"], ["cache", "dump", "nothing.hlb"]])
def test_a_command_started_during_an_update_stops_before_importing_its_code(updating: Path,
                                                                           arguments: list[str]) -> None:
    result = start(updating, *arguments)
    assert result.stdout.splitlines() == ["exit 1", "loaded []"], result.stdout + result.stderr[-2000:]
    assert result.stderr.strip() == "HeLab is being updated: run this again when the update has finished."
    assert os.listdir(updating) == ["update.lock"]  # (Nothing registered, logged or written.)


def test_the_app_started_during_an_update_says_so_and_stops_before_importing_helab(updating: Path) -> None:
    """As a double click during an update: one window that closes by itself, exit 1, none of HeLab's own modules
    imported (no settings, log file or lock of its own)."""
    began = time.monotonic()
    result = start(updating)
    assert result.stdout.splitlines() == ["exit 1", "loaded ['PyQt6']"], result.stdout + result.stderr[-2000:]
    assert "HeLab is being updated." in result.stderr
    assert os.listdir(updating) == ["update.lock"]
    assert time.monotonic() - began < 120  # (Its window closed without anyone: it doesn't hold up the update.)


def test_help_and_version_still_answer_during_an_update(updating: Path) -> None:
    result = start(updating, "--help")
    assert result.stdout.startswith("usage: helab") and "exit 0" in result.stdout, result.stdout + result.stderr
    result = start(updating, "--version")
    assert "exit 0" in result.stdout, result.stdout + result.stderr


def test_the_start_the_updater_makes_goes_on(updating: Path) -> None:
    """With the lock's token in ``HELAB_UPDATE_TOKEN``, as the updater starts the new version: the gate lets it by
    (here ``helab cache``, which then gives its own answer; the app's import goes on the same way)."""
    result = start(updating, "cache", "dump", "nothing.hlb", token=TOKEN)
    assert "loaded ['helab.cache_cli']" in result.stdout, result.stdout + result.stderr[-2000:]
    assert "HeLab is being updated" not in result.stderr
    result = start(updating, "cache", "dump", "nothing.hlb", token="another0another0")
    assert result.stdout.splitlines() == ["exit 1", "loaded []"]  # (Another update's start isn't this one's.)


def test_the_gate_at_import_stops_only_during_an_update(entry: ModuleType, updating: Path, tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    said: list[bool] = []
    monkeypatch.setattr(entry, "_say_updating", lambda: said.append(True))
    monkeypatch.setenv("HELAB_APP_DIR_OVERRIDE", str(tmp_path / "quiet"))
    entry._stop_during_update(command=False)  # No update: nothing happens, and no file is made
    assert not said and not (tmp_path / "quiet").exists()
    monkeypatch.setenv("HELAB_APP_DIR_OVERRIDE", str(updating))
    with pytest.raises(SystemExit) as stopped:
        entry._stop_during_update(command=False)
    assert stopped.value.code == 1 and said == [True]
    monkeypatch.setenv(cache_locks.UPDATE_TOKEN_ENV, TOKEN)
    entry._stop_during_update(command=False)  # The updater's own start
    assert said == [True]


def test_the_updating_window_closes_by_itself(entry: ModuleType, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(entry, "UPDATING_SHOWN_MS", 50)
    began = time.monotonic()
    entry._say_updating()  # (Returns: nobody clicked.)
    assert time.monotonic() - began < 30


def test_a_start_that_took_the_running_lock_gives_it_back_when_an_update_holds_its_own(
        entry: ModuleType, updating: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The check that decides: ``running.lock`` first, then ``update.lock``. Held by an updater, HeLab says so,
    lets its own lock go (the updater is waiting for it) and stops; the updater's own start keeps it."""
    said: list[bool] = []
    monkeypatch.setattr(entry, "app_folder", lambda: str(updating))
    monkeypatch.setattr(entry, "_say_updating", lambda: said.append(True))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda parent, title, text: said.append(False)))
    assert entry._another_running() is True and said == [True] and not entry._RUNNING_LOCK
    lock, _ = take_running(str(updating))  # (Given back: free for the updater's wait.)
    assert lock is not None
    # The lock taken by the updater's own look at it (or a HeLab's): during an update that is what is said
    assert entry._another_running() is True and said == [True, True] and not entry._RUNNING_LOCK
    lock.unlock()
    monkeypatch.setenv(cache_locks.UPDATE_TOKEN_ENV, TOKEN)
    try:
        assert entry._another_running() is False and len(entry._RUNNING_LOCK) == 1 and said == [True, True]
    finally:
        for held in entry._RUNNING_LOCK:
            held.unlock()
        entry._RUNNING_LOCK.clear()


def test_the_converter_unregisters_and_stops_when_an_update_holds_its_lock(
        updating: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """``helab convert``'s check that decides: registered (``instances/<pid>.lock``) first, ``update.lock`` second;
    held, it lets its registration go and exits 1 before the cache or a helper starts."""
    from helab import convert_cli
    registered: list[FileLock] = []

    def startup(app_dir: str, recover: Any, wait: Any) -> tuple[str, FileLock]:
        lock = FileLock(str(updating / "instances" / "4242.lock"))
        assert lock.try_lock()
        registered.append(lock)
        return "", lock

    monkeypatch.setattr(cache_locks, "startup", startup)
    monkeypatch.setattr("helab.utils.constants.app_folder", lambda: str(updating))
    with pytest.raises(convert_cli.UpdateRunning):
        convert_cli._start_cache()
    assert len(registered) == 1 and not registered[0].held
    assert not cache_locks.locked_elsewhere(str(updating / "instances" / "4242.lock"))
    source = tmp_path / "source"
    source.mkdir()
    with caplog.at_level(logging.ERROR):
        assert convert_cli.main(["--watch", str(source), "--once"]) == 1
    assert "HeLab is being updated" in caplog.text and not registered[1].held
    monkeypatch.setenv(cache_locks.UPDATE_TOKEN_ENV, TOKEN)
    assert not update_in_progress(str(updating))
