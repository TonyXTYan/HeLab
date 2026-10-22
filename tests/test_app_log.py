"""The log file and the catch for unhandled exceptions (``helab.utils.app_log``, R-11). Each test
writes only its own temporary folder, never the app folder."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
import threading
from typing import Iterator

import pytest
from PyQt6.QtCore import QTimer
from pytestqt.qtbot import QtBot

from helab.utils import app_log


@pytest.fixture
def hooks(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """The hooks as they were before the test, put back after it; the notices shown."""
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(app_log, "_seen", {})
    monkeypatch.setattr(app_log, "_notice", None)
    notices: list[str] = []
    app_log.catch_unhandled(notices.append)
    yield notices


def boom() -> None:
    raise ValueError("no such shot")


@pytest.mark.qt_no_exception_capture
def test_an_exception_in_a_slot_is_logged_and_shown_and_helab_carries_on(
        qtbot: QtBot, hooks: list[str], caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR):
        QTimer.singleShot(0, boom)
        qtbot.waitUntil(lambda: bool(hooks))
    assert hooks == ["Unexpected error, logged: ValueError: no such shot"]
    record = next(record for record in caplog.records if record.levelno == logging.ERROR)
    assert record.exc_info is not None and "in boom" in caplog.text and "Traceback" in caplog.text
    # Still running: a timer fires after it.
    fired: list[bool] = []
    QTimer.singleShot(0, lambda: fired.append(True))
    qtbot.waitUntil(lambda: bool(fired))


@pytest.mark.qt_no_exception_capture
def test_the_same_exception_again_is_counted_not_logged(
        qtbot: QtBot, hooks: list[str], caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    with caplog.at_level(logging.ERROR):
        for _ in range(3):
            QTimer.singleShot(0, boom)
        qtbot.wait(50)
        assert len(caplog.records) == 1 and len(hooks) == 1
        monkeypatch.setattr(app_log, "REPEAT_SECONDS", 0.0)
        QTimer.singleShot(0, boom)
        qtbot.waitUntil(lambda: len(caplog.records) == 2)
    assert "(2 more like it not logged)" in caplog.records[1].getMessage()


def test_an_exception_in_another_thread_is_logged_without_a_notice(
        hooks: list[str], caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR):
        thread = threading.Thread(target=boom, name="reader")
        thread.start()
        thread.join()
    assert "Unhandled exception in thread reader: ValueError: no such shot" in caplog.text
    assert not hooks


def test_a_broken_notice_is_logged_too(hooks: list[str], caplog: pytest.LogCaptureFixture) -> None:
    def gone(text: str) -> None:
        raise RuntimeError("wrapped C/C++ object has been deleted")
    app_log.catch_unhandled(gone)
    with caplog.at_level(logging.ERROR):
        try:
            boom()
        except ValueError as error:
            sys.excepthook(ValueError, error, error.__traceback__)
    assert "no such shot" in caplog.text and "couldn't be shown in the status bar" in caplog.text


def test_the_log_file_keeps_tracebacks_and_rotates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_log, "LOG_BYTES", 4096)
    root = logging.getLogger()
    monkeypatch.setattr(root, "level", logging.INFO)
    handler = app_log.start_log_file(str(tmp_path))
    assert handler is not None
    try:
        try:
            boom()
        except ValueError:
            logging.exception("Unhandled exception")
        handler.flush()
        log = tmp_path / "logs" / f"helab-{os.getpid()}.log"
        assert "Traceback" in log.read_text(encoding="utf-8") and "ValueError: no such shot" in log.read_text(
            encoding="utf-8")
        for index in range(200):
            logging.info(f"line {index} " + "x" * 40)
        names = sorted(path.name for path in (tmp_path / "logs").iterdir())
        own = f"helab-{os.getpid()}.log"
        assert names == [own, *(f"{own}.{index}" for index in range(1, 5))]
    finally:
        root.removeHandler(handler)
        handler.close()


def test_no_log_file_where_it_cant_be_written(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    (tmp_path / "logs").write_text("a file, not a folder")
    with caplog.at_level(logging.WARNING):
        assert app_log.start_log_file(str(tmp_path)) is None
    assert "No log file" in caplog.text


def test_each_helab_writes_its_own_log_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two HeLabs at once never share a file (a Windows rollover in one would lose the other's lines):
    each writes helab-<its process ID>.log, rotated on its own."""
    root = logging.getLogger()
    monkeypatch.setattr(root, "level", logging.INFO)
    handlers = []
    try:
        for pid in (101, 202):
            monkeypatch.setattr(os, "getpid", lambda pid=pid: pid)
            handler = app_log.start_log_file(str(tmp_path))
            assert handler is not None
            handlers.append(handler)
            logging.info(f"from {pid}")
            root.removeHandler(handler)  # (One instance's handler at a time, as in two processes.)
            handler.flush()
        assert sorted(path.name for path in (tmp_path / "logs").iterdir()) == ["helab-101.log", "helab-202.log"]
        assert "from 101" in (tmp_path / "logs" / "helab-101.log").read_text(encoding="utf-8")
        assert "from 202" not in (tmp_path / "logs" / "helab-101.log").read_text(encoding="utf-8")
    finally:
        for handler in handlers:
            root.removeHandler(handler)
            handler.close()
