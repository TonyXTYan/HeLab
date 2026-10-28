"""Old log files (Tony, 2026-10-22): rotation within a session, the oldest beyond Settings → General →
Log files to keep deleted at startup, and past 50 MB the question that deletes down to under 20 MB.
Every test uses its own temporary app folder, never the real log folder."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import threading
import time
from typing import Iterator

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from helab.utils import app_log
from helab.utils.cache_locks import FileLock, instances_dir
from helab.utils.constants import read_log_keep
from helab.utils.settings_defaults import LOG_KEEP_SETTING, SETTINGS, setting_default
from helab.views.OldLogs import OldLogs

MB = app_log.MB
HOUR = 3600.0


def log(folder: Path, name: str, age: float, size: int = 10) -> Path:
    """A log file ``name`` of ``size`` bytes (sparse), last modified ``age`` seconds ago."""
    path = folder / "logs" / name
    path.parent.mkdir(exist_ok=True)
    with open(path, "wb") as file:
        file.truncate(size)
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))
    return path


def names(folder: Path) -> set[str]:
    return {path.name for path in (folder / "logs").iterdir()}


@pytest.fixture
def running(tmp_path: Path) -> Iterator[int]:
    """Another HeLab, pid 202, running: it holds its instance lock in the app folder."""
    os.makedirs(instances_dir(str(tmp_path)), exist_ok=True)
    lock = FileLock(os.path.join(instances_dir(str(tmp_path)), "202.lock"))
    assert lock.try_lock()
    yield 202
    lock.unlock()


def test_rotation_within_a_session_is_fixed_at_1_mb_and_10_older_files(tmp_path: Path) -> None:
    assert (app_log.LOG_BYTES, app_log.LOG_BACKUPS) == (1000 * 1000, 10)
    handler = app_log.start_log_file(str(tmp_path))
    assert handler is not None
    try:
        assert (handler.maxBytes, handler.backupCount) == (app_log.LOG_BYTES, app_log.LOG_BACKUPS)
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()


def test_the_count_rule_deletes_the_oldest_by_mtime_never_a_running_helabs(tmp_path: Path, running: int) -> None:
    """Every session's files count, rotated copies too; the oldest go first by mtime, whatever their
    names (process IDs come round again); a running HeLab's (another's, this one's) and one just
    written stay."""
    own = os.getpid()
    log(tmp_path, "helab-101.log.2", age=50 * HOUR)  # Oldest of all.
    log(tmp_path, "helab-101.log.1", age=40 * HOUR)
    log(tmp_path, "helab-101.log", age=39 * HOUR)
    log(tmp_path, "helab-7.log", age=45 * HOUR)  # A lower pid, yet newer than helab-101.log.2.
    log(tmp_path, "helab-9.log", age=1 * HOUR)
    log(tmp_path, f"helab-{running}.log.1", age=60 * HOUR)  # Older than all, but running.
    log(tmp_path, f"helab-{own}.log.3", age=70 * HOUR)  # This HeLab's.
    log(tmp_path, "helab-5.log", age=10.0)  # Just written: a HeLab starting up.
    log(tmp_path, "notes.txt", age=90 * HOUR)  # Not a log file: neither counted nor deleted.
    log(tmp_path, "helab-x.log", age=90 * HOUR)

    left = app_log.tidy_logs(str(tmp_path), keep=5)

    assert names(tmp_path) == {"helab-101.log", "helab-9.log", f"helab-{running}.log.1", f"helab-{own}.log.3",
                               "helab-5.log", "notes.txt", "helab-x.log"}
    assert left == 5 * 10
    # Fewer deletable files than the excess: all of them go, the running and new ones stay.
    assert app_log.tidy_logs(str(tmp_path), keep=1) == 3 * 10
    assert names(tmp_path) == {f"helab-{running}.log.1", f"helab-{own}.log.3", "helab-5.log", "notes.txt",
                               "helab-x.log"}


def test_within_the_count_nothing_is_deleted(tmp_path: Path) -> None:
    for pid in range(10, 20):
        log(tmp_path, f"helab-{pid}.log", age=pid * HOUR)
    assert app_log.tidy_logs(str(tmp_path), keep=10) == 100
    assert len(names(tmp_path)) == 10
    assert app_log.tidy_logs(str(tmp_path / "none"), keep=1) == 0  # (No log folder yet.)


def test_a_file_that_cant_be_deleted_is_skipped_and_logged(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    held = log(tmp_path, "helab-11.log", age=3 * HOUR)
    log(tmp_path, "helab-12.log", age=2 * HOUR)
    log(tmp_path, "helab-13.log", age=1 * HOUR)
    remove = os.remove

    def open_elsewhere(path: str) -> None:
        if path == str(held):
            raise PermissionError(13, "The process cannot access the file", path)
        remove(path)
    monkeypatch.setattr(os, "remove", open_elsewhere)
    with caplog.at_level(logging.INFO):
        assert app_log.tidy_logs(str(tmp_path), keep=1) == 20
    assert names(tmp_path) == {"helab-11.log", "helab-13.log"}
    assert f"Old log file {held} not deleted" in caplog.text
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


def test_log_files_to_keep_is_a_setting_default_300(tmp_path: Path) -> None:
    row = next(setting for setting in SETTINGS if setting.key == LOG_KEEP_SETTING)
    assert (row.type, row.default, setting_default(LOG_KEEP_SETTING)) == (int, 300, 300)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    assert read_log_keep(settings) == 300
    for saved, read in (("40", 40), (0, 1), (10 ** 9, 100_000), ("many", 300)):
        settings.setValue(LOG_KEEP_SETTING, saved)
        assert read_log_keep(settings) == read


def test_settings_general_saves_log_files_to_keep(qtbot: QtBot, tmp_path: Path) -> None:
    from helab.views.SettingsDialog import SettingsDialog
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    dialog = SettingsDialog(settings=settings)
    qtbot.addWidget(dialog)
    assert dialog.log_keep_spin.value() == 300
    assert dialog.log_keep_spin.parentWidget() is dialog.general_tab
    dialog.log_keep_spin.setValue(25)
    dialog.save_settings()
    assert read_log_keep(settings) == 25


@pytest.fixture
def parent(qtbot: QtBot) -> QWidget:
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def gui_thread_watch(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The threads the log folder was scanned and deleted from."""
    threads: list[str] = []
    scan, remove = app_log.scan_logs, os.remove

    def scan_logs(folder: str) -> list[app_log.LogFile]:
        threads.append(threading.current_thread().name)
        return scan(folder)

    def watched_remove(path: str) -> None:
        threads.append(threading.current_thread().name)
        remove(path)
    monkeypatch.setattr(app_log, "scan_logs", scan_logs)
    monkeypatch.setattr(os, "remove", watched_remove)
    return threads


def big_logs(folder: Path) -> list[Path]:
    """64 MB of logs from eight ended sessions, oldest first."""
    return [log(folder, f"helab-{pid}.log", age=(20 - pid) * HOUR, size=8 * MB) for pid in range(1, 9)]


def done(old_logs: OldLogs) -> bool:
    return not any(thread.is_alive() for thread in old_logs.threads)


def test_past_50_mb_delete_goes_under_20_mb_oldest_first_off_the_gui_thread(
        qtbot: QtBot, parent: QWidget, tmp_path: Path, gui_thread_watch: list[str]) -> None:
    files = big_logs(tmp_path)
    old_logs = OldLogs(str(tmp_path), parent)
    old_logs.start(keep=300)
    qtbot.waitUntil(lambda: old_logs.box is not None)
    box = old_logs.box
    assert box is not None and box.text() == "Log files use 64 MB. Delete old ones?"
    assert box.defaultButton() is old_logs.keep_button and box.escapeButton() is old_logs.keep_button
    assert old_logs.delete_button is not None
    old_logs.delete_button.click()
    qtbot.waitUntil(lambda: len(names(tmp_path)) == 2 and done(old_logs))
    assert names(tmp_path) == {files[-2].name, files[-1].name}  # 16 MB: under 20, the newest kept.
    assert gui_thread_watch and threading.main_thread().name not in gui_thread_watch


def test_keep_deletes_nothing_and_isnt_asked_again_this_session(
        qtbot: QtBot, parent: QWidget, tmp_path: Path, gui_thread_watch: list[str]) -> None:
    big_logs(tmp_path)
    old_logs = OldLogs(str(tmp_path), parent)
    old_logs.start(keep=300)
    qtbot.waitUntil(lambda: old_logs.box is not None)
    assert old_logs.box is not None and old_logs.keep_button is not None
    old_logs.keep_button.click()
    assert old_logs.box is None
    old_logs.start(keep=300)
    qtbot.waitUntil(lambda: done(old_logs) and len(gui_thread_watch) == 2)  # The second scan ended…
    qtbot.wait(50)
    assert old_logs.box is None and len(names(tmp_path)) == 8  # …and asked nothing.
    assert threading.main_thread().name not in gui_thread_watch


def test_under_50_mb_nothing_is_asked(qtbot: QtBot, parent: QWidget, tmp_path: Path) -> None:
    for pid in range(1, 7):
        log(tmp_path, f"helab-{pid}.log", age=(10 - pid) * HOUR, size=8 * MB)  # 48 MB.
    old_logs = OldLogs(str(tmp_path), parent)
    old_logs.start(keep=300)
    qtbot.waitUntil(lambda: done(old_logs))
    qtbot.wait(50)
    assert old_logs.box is None and not old_logs.asked and len(names(tmp_path)) == 6


def test_the_count_rule_runs_before_the_question(qtbot: QtBot, parent: QWidget, tmp_path: Path) -> None:
    big_logs(tmp_path)
    old_logs = OldLogs(str(tmp_path), parent)
    old_logs.start(keep=6)  # 48 MB left: no question.
    qtbot.waitUntil(lambda: done(old_logs) and len(names(tmp_path)) == 6)
    qtbot.wait(50)
    assert old_logs.box is None
