"""How a helper is started and read (``IOService._run``, ``_file_lines``): what happens on the
daemon thread before and after the helper process runs."""
from __future__ import annotations

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
