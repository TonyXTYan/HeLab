"""How a helper is started and read (``IOService._run``, ``_file_lines``): what happens on the
daemon thread before and after the helper process runs."""
from __future__ import annotations

import logging
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from helab.utils.io_service import IORequest, IOService


def test_writing_held_data_out_counts_as_progress(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    """A Live save writes the data held in RAM to the helper's folder before the helper starts; a
    dump slower than the no-progress time must not retire the save before its helper runs."""
    service = IOService()
    service.timer.stop()
    request = IORequest("tab", 0, "/data", "load", {"save_memory": True}, service.NO_PROGRESS_TIMEOUT,
                        arrays={1: np.zeros(3), 2: np.zeros(3)})
    request.last_activity = time.monotonic()

    def slow_save(*args: Any, **kwargs: Any) -> None:
        request.last_activity -= service.NO_PROGRESS_TIMEOUT  # As if each array took that long.

    idle_at_start: list[float] = []

    def popen(*args: Any, **kwargs: Any) -> None:
        idle_at_start.append(time.monotonic() - request.last_activity)
        raise OSError("not started in this test")

    monkeypatch.setattr(np, "save", slow_save)
    monkeypatch.setattr("helab.utils.io_service.subprocess.Popen", popen)
    service._run(request)
    assert len(idle_at_start) == 1 and idle_at_start[0] < request.timeout
    service.shutdown()


def test_the_frozen_reader_reads_lines_written_just_before_the_helper_exited(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The packaged app reads the helper's response file: a ``done`` written between the reader's
    last read and its check that the helper exited must still be read."""
    response = tmp_path / "response.jsonl"
    response.write_text('{"kind": "status"}\n', encoding="utf-8")

    class Exiting:
        def poll(self) -> int:
            with response.open("a", encoding="utf-8") as stream:
                stream.write('{"kind": "done"}\n')
            return 0

    request = IORequest("tab", 0, "/data", "list", {}, 60.0)
    monkeypatch.setattr(request, "process", Exiting())
    assert list(IOService._file_lines(request, str(response))) == ['{"kind": "status"}\n', '{"kind": "done"}\n']


@pytest.mark.parametrize("exited", [False, True], ids=["dies", "died before its request was written"])
def test_a_helper_that_dies_leaves_what_it_said_in_the_log(
        qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, exited: bool) -> None:
    """Whether it exits before or after its request is written to it (then the write finds its
    pipe closed: "Broken pipe" on macOS CI), it exited unexpectedly, and what it said is logged."""
    service = IOService()
    service.timer.stop()
    started = subprocess.Popen

    def dying(command: list[str], **kwargs: Any) -> subprocess.Popen[str]:
        process = started([sys.executable, "-c", "import sys; sys.stderr.write('ImportError: no blosc\\n'); "
                           "sys.exit(1)"], **kwargs)
        if exited:
            process.wait()
        return process

    monkeypatch.setattr("helab.utils.io_service.subprocess.Popen", dying)
    request = IORequest("tab", 0, "/data", "list", {}, 60.0)
    with caplog.at_level(logging.WARNING):
        service._run(request)
    events = []
    while not service.messages.empty():
        events.append(service.messages.get_nowait()[1])
    assert {"kind": "error", "message": "I/O helper exited unexpectedly"} in events
    assert "ImportError: no blosc" in caplog.text
    service.shutdown()
