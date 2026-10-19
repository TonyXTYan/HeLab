"""Live checks through the real IOService and helper processes: when they pause background work,
and how a stuck read is retried (never beside the helper it replaces).

Reads are ordered with the helper's read gate (``HELAB_TEST_READ_GATE``): a TXY read waits until
its ``<name>.go`` file exists, so the tests decide when each read may finish, on every platform.
A gate never opened stands in for a read that never returns."""
from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any, Iterator

import pytest
from PyQt6 import QtWebEngineWidgets  # noqa: F401  (before any QApplication: conftest loads the views)
from pytestqt.qtbot import QtBot

from helab.utils.io_service import FOREGROUND, IORequest, IOService


def write_files(folder: Path, shots: range, rows: int = 1) -> None:
    line = "".join(f"{row},2,3\n" for row in range(rows))
    old = time.time() - 60
    for shot in shots:
        file = folder / f"d_txy_forc{shot}.txt"
        file.write_text(line)
        os.utime(file, (old, old))


def fingerprints(folder: Path, shots: range) -> list[list[int]]:
    return [[shot, (info := (folder / f"d_txy_forc{shot}.txt").stat()).st_size, info.st_mtime_ns] for shot in shots]


@pytest.fixture
def service() -> Iterator[IOService]:
    service = IOService()
    # Live checks are the current tab's: the foreground lane.
    service.is_foreground = lambda request: bool(request.payload.get("live"))
    yield service
    service.shutdown()


def events_of(service: IOService) -> list[tuple[IORequest, dict[str, Any], float]]:
    events: list[tuple[IORequest, dict[str, Any], float]] = []
    service.resultReady.connect(lambda request, event: events.append((request, event, time.monotonic())))
    return events


class ReadGate:
    """The helpers' read gate for one test: TXY files are read only once opened here."""

    def __init__(self, folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.folder = folder
        folder.mkdir()
        # Read by each helper when it starts (helpers copy the parent's environment).
        monkeypatch.setenv("HELAB_TEST_READ_GATE", str(folder))

    def open(self, *files: Path) -> None:
        for file in files:
            (self.folder / f"{file.name}.go").touch()

    def open_all(self, folder: Path, shots: range) -> None:
        self.open(*(folder / f"d_txy_forc{shot}.txt" for shot in shots))


@pytest.fixture
def gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ReadGate:
    return ReadGate(tmp_path / "read gate", monkeypatch)


def test_a_live_check_pauses_background_work_only_while_it_reads(
    qtbot: QtBot, service: IOService, tmp_path: Path, gate: ReadGate,
) -> None:
    """Two closed gates fix the order of events, whatever the machine's speed: the other tab's
    load is held on one of its TXY files until the Live check is reading, and the check is held
    on its last new file until the load has reported itself paused. (Gates go by file name, so
    the two folders use different shot numbers.)"""
    background = tmp_path / "other folder"
    background.mkdir()
    write_files(background, range(1001, 1052), rows=200)
    hold_load = background / "d_txy_forc1041.txt"
    gate.open_all(background, range(1001, 1041))
    gate.open_all(background, range(1042, 1052))
    watched = tmp_path / "run"
    watched.mkdir()
    write_files(watched, range(1, 11))
    held = fingerprints(watched, range(1, 11))
    hold_check = watched / "d_txy_forc211.txt"
    events = events_of(service)

    def seen(owner: str, kind: str, filename: Path | None = None) -> bool:
        return any(r.owner == owner and e["kind"] == kind and (filename is None or e.get("filename") == str(filename))
                   for r, e, _ in events)

    assert service.submit("other tab", 0, str(background), "load")
    qtbot.waitUntil(lambda: seen("other tab", "file_finished"), timeout=10000)

    def check(owner: str, payload: dict[str, Any]) -> None:
        assert service.submit(owner, 0, str(watched), "load", {"live": True, "memory": held, **payload})

    def finished(owner: str) -> list[dict[str, Any]]:
        qtbot.waitUntil(lambda: seen(owner, "done") or seen(owner, "error"), timeout=10000)
        return [e for r, e, _ in events if r.owner == owner]

    # Nothing new: the check lists the folder and never holds the other tab's load, which reads on.
    check("live 1", {})
    nothing = finished("live 1")
    assert [e["kind"] for e in nothing][-2:] == ["live_unchanged", "done"]
    assert not seen("other tab", "paused")
    # The load is now provably mid-way: held reading one file, with files still to read after it.
    qtbot.waitUntil(lambda: seen("other tab", "file_started", hold_load), timeout=10000)
    assert not seen("other tab", "file_finished", hold_load)
    # New files (seen unchanged by the previous check): background work waits while they are read,
    # then resumes.
    write_files(watched, range(11, 212), rows=2000)
    gate.open_all(watched, range(11, 211))
    check("live 2", {"seen": fingerprints(watched, range(11, 212))})
    qtbot.waitUntil(lambda: seen("live 2", "file_started"), timeout=10000)
    assert not seen("other tab", "paused")
    # The check is reading: the load, let go, pauses at its next file.
    gate.open(hold_load)
    qtbot.waitUntil(lambda: seen("other tab", "paused"), timeout=10000)
    assert not seen("live 2", "done")
    # Only then may the check finish; the load resumes after it.
    gate.open(hold_check)
    found = finished("live 2")
    assert sum(e["kind"] == "shot" for e in found) == 201
    qtbot.waitUntil(lambda: seen("other tab", "resumed"), timeout=10000)
    kinds = [(r.owner, e["kind"], at) for r, e, at in events if e["kind"] in ("paused", "resumed", "file_started")]
    paused = next(at for owner, kind, at in kinds if owner == "other tab" and kind == "paused")
    first_read = next(at for owner, kind, at in kinds if owner == "live 2" and kind == "file_started")
    assert paused >= first_read  # Only once the check reads a file.
    assert not any(r.owner.startswith("live") and e["kind"] == "paused" for r, e, _ in events)
    qtbot.waitUntil(lambda: seen("other tab", "done"), timeout=15000)


def test_a_stuck_read_is_retried_only_after_the_previous_helper_has_exited(
    qtbot: QtBot, service: IOService, tmp_path: Path, gate: ReadGate,
) -> None:
    """A TXY file whose read never returns (its gate is never opened): each attempt times out, is
    stopped, and the next starts only once the stopped helper's exit is confirmed; the third
    failure ends the check with an error (Live then stops with Retry)."""
    watched = tmp_path / "run"
    watched.mkdir()
    write_files(watched, range(1, 4))
    stuck = watched / "d_txy_forc3.txt"
    info = stuck.stat()
    service.TIMEOUTS = (0.4, 0.4, 0.4)
    started: list[tuple[IORequest, bool]] = []
    seen_requests: list[IORequest] = []
    events: list[dict[str, Any]] = []

    def track(request: IORequest, event: dict[str, Any]) -> None:
        if request.owner != "live":
            return
        events.append(event)
        if event["kind"] == "started":
            # Every earlier attempt's helper must have exited before this one starts.
            started.append((request, all(old.exited.is_set() for old in seen_requests)))
            seen_requests.append(request)
    service.resultReady.connect(track)
    assert service.submit("live", 0, str(watched), "load", {
        "live": True, "memory": fingerprints(watched, range(1, 3)),
        "seen": [[3, info.st_size, info.st_mtime_ns]]})
    qtbot.waitUntil(lambda: any(e["kind"] == "error" for e in events), timeout=15000)
    assert [request.attempt for request, _ in started] == [1, 2, 3]
    assert all(exited for _, exited in started)
    error = next(e for e in events if e["kind"] == "error")
    assert error["timeout"] and error["message"] == "File timed out after 3 attempts: d_txy_forc3.txt — Retry"
    assert all(request.lane == FOREGROUND for request, _ in started)
    qtbot.waitUntil(lambda: not service.active and not service.retired, timeout=5000)


def test_live_on_an_empty_folder_through_the_helper_processes(
    qtbot: QtBot, service: IOService, tmp_path: Path, gate: ReadGate,
) -> None:
    """Live started before the first shot: the check holds no shots (``memory=[]``, sent as is to
    the helper process), lists the folder, and reads the first shot once it is seen unchanged a
    check later; the gate shows the read happens in that second check, and only there."""
    watched = tmp_path / "run"
    watched.mkdir()
    old = time.time() - 60
    os.utime(watched, (old, old))
    events = events_of(service)

    def finished(owner: str) -> list[dict[str, Any]]:
        qtbot.waitUntil(lambda: any(r.owner == owner and e["kind"] in ("done", "error") for r, e, _ in events),
                        timeout=10000)
        return [e for r, e, _ in events if r.owner == owner]

    def check(owner: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        assert service.submit(owner, 0, str(watched), "load", {"live": True, "memory": [], **payload})
        return finished(owner)

    nothing = check("live 1", {})
    assert [e["kind"] for e in nothing][-2:] == ["live_unchanged", "done"]
    unchanged = next(e for e in nothing if e["kind"] == "live_unchanged")
    assert unchanged["live_listed"] and unchanged["total_files"] == 0
    write_files(watched, range(1, 2), rows=3)
    first = check("live 2", {})  # Seen, not read: no read waits at the gate.
    seen = next(e for e in first if e["kind"] == "live_unchanged")["live_seen"]
    assert [entry[0] for entry in seen] == [1] and not any(e["kind"] == "file_started" for e in first)
    assert service.submit("live 3", 0, str(watched), "load", {"live": True, "memory": [], "seen": seen})
    qtbot.waitUntil(lambda: any(r.owner == "live 3" and e["kind"] == "file_started" for r, e, _ in events),
                    timeout=10000)
    assert not any(r.owner == "live 3" and e["kind"] == "loaded" for r, e, _ in events)
    gate.open(watched / "d_txy_forc1.txt")
    read = finished("live 3")
    loaded = next(e for e in read if e["kind"] == "loaded")
    assert [e["shot"] for e in read if e["kind"] == "shot"] == [1]
    assert loaded["memory_shots"] == [] and loaded["source"] == "updated" and loaded["files"] == 1
