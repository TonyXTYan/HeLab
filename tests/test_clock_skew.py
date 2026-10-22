"""A folder's files dated ahead of this computer's clock (R-22, Tony 2026-10-22): they stay "still
being written", and the helpers say the computers' clocks are out of sync (``clock_skew``, more than
``FUTURE_SECONDS`` = 2 s ahead), which the app shows once per share or volume per session. Live's
stop on them: tests/test_live.py."""
from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any, Iterator

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox, QWidget
from pytestqt.qtbot import QtBot

from helab.io_ops import fingerprints
from helab.io_ops.loading import load
from helab.io_ops.scanning import scan
from helab.utils import events as hub_events
from helab.utils.folder_cache import FolderCache
from helab.utils.io_service import IORequest, IOService
from helab.utils.time_format import span
from helab.views.ClockSkewWarning import TEXT, ClockSkewWarning


def write_shot(folder: Path, shot: int, ahead: float) -> None:
    """A TXY file dated ``ahead`` seconds in the future (negative: in the past)."""
    folder.mkdir(exist_ok=True)
    file = folder / f"d_txy_forc{shot}.txt"
    file.write_text(f"{shot},2,3\n")
    when = time.time() + ahead
    os.utime(file, (when, when))


def skews(sent: list[Any]) -> list[dict[str, Any]]:
    return [event for event in sent if event["kind"] == "clock_skew"]


@pytest.mark.parametrize("ahead, said", [(-60.0, False), (1.5, False), (3.0, True), (3600.0, True)])
def test_only_files_more_than_2_s_ahead_say_the_clocks_differ(tmp_path: Path, ahead: float, said: bool) -> None:
    """FAT and some shares round mtimes to 2 s: up to 2 s ahead is our clock's rounding, not a skew."""
    sent: list[Any] = []
    now = time.time_ns()
    fingerprint = [(1, 10, now - 10**10), (2, 10, now + int(ahead * 1e9))]
    found = fingerprints._clock_ahead(str(tmp_path), fingerprint, sent.append)
    assert bool(found) is said and len(skews(sent)) == int(said)
    if said:
        event = skews(sent)[0]
        assert event["path"] == str(tmp_path) and event["seconds"] == pytest.approx(ahead, abs=1.0)
        assert event["location"]  # (Its volume, from the mount table, else the folder.)
    assert fingerprints.FUTURE_SECONDS == 2.0


def test_loads_and_scans_say_so(tmp_path: Path) -> None:
    run = tmp_path / "run"
    write_shot(run, 1, -60)
    write_shot(run, 2, 120)
    output = tmp_path / "out"
    output.mkdir()
    sent: list[Any] = []
    load(str(run), str(output), sent.append)
    assert [event["path"] for event in skews(sent)] == [str(run)] and 115 < skews(sent)[0]["seconds"] < 121
    sent.clear()
    scan(str(run), sent.append)
    assert len(skews(sent)) == 1


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch) -> Iterator[FolderCache]:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    yield FolderCache(service)
    service.shutdown()


def skew(cache: FolderCache, path: str, location: str, seconds: float = 90.0) -> None:
    request = IORequest("helper", 0, path, "load", {}, 60.0)
    cache.service.resultReady.emit(request, {"kind": "clock_skew", "path": path, "seconds": seconds,
                                             "location": location})


def test_the_warning_comes_once_per_share_or_volume_per_session(qtbot: QtBot, cache: FolderCache) -> None:
    warned: list[tuple[str, float]] = []
    cache.clockSkew.connect(lambda path, seconds: warned.append((path, seconds)))
    skew(cache, "/Volumes/dld/run_1", "smb://server/dld")
    skew(cache, "/Volumes/dld/run_2", "smb://server/dld")  # Another folder, same share: not again.
    skew(cache, "/Volumes/dld/run_1", "smb://server/dld", 120.0)  # The same again: not again.
    skew(cache, "/Volumes/usb/run_9", "msdos:/dev/disk4s1")  # Another volume: once for it.
    assert warned == [("/Volumes/dld/run_1", 90.0), ("/Volumes/usb/run_9", 90.0)]


def test_the_window_names_the_folder_and_the_skew_and_tells_hooks(qtbot: QtBot, cache: FolderCache) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)
    warning = ClockSkewWarning(cache, parent)
    heard: list[hub_events.Event] = []
    hub_events.hub().add_hook(heard.append)
    skew(cache, "/Volumes/dld/run_1", "smb://server/dld", 3725.0)
    box = warning.dialog
    assert isinstance(box, QMessageBox) and box.isVisible() and box.windowModality() == Qt.WindowModality.NonModal
    assert box.text() == TEXT.format(folder=os.path.normpath("/Volumes/dld/run_1"), skew="1 h 2 min")
    assert span(3725.0) == "1 h 2 min" and span(125.0) == "2 min 5 s" and span(3.0) == "3 s"
    assert [event.kind for event in heard if event.kind == hub_events.CLOCK_SKEW] == [hub_events.CLOCK_SKEW]
    box.close()
    warning.detach()
    warning.detach()  # (Twice is fine: the window may close twice.)
    skew(cache, "/Volumes/usb/run_9", "msdos:/dev/disk4s1")
    assert warning.dialog is None
