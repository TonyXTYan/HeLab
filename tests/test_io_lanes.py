"""Foreground/background I/O lanes and cooperative pausing (io-lanes Phase 3)."""
from __future__ import annotations

import os
from pathlib import Path
import threading
import time
from typing import Any

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from helab.io_helper import Pause, list_folder
from helab.utils.folder_cache import get_folder_cache
from helab.utils.io_service import BACKGROUND, FOREGROUND, REQUEUED, IORequest, IOService


def lanes_service(monkeypatch: pytest.MonkeyPatch, foreground: set[str]) -> IOService:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_run", lambda request: None)
    service.is_foreground = lambda request: request.owner in foreground
    return service


def active(service: IOService, owner: str, operation: str) -> IORequest:
    return next(r for r in service.active if (r.owner, r.operation) == (owner, operation))


def exit_helper(service: IOService, request: IORequest) -> None:
    service.messages.put((request, {"kind": "exit"}))
    service._tick()


def test_foreground_starts_while_background_slots_are_full_or_stopping(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = lanes_service(monkeypatch, {"tab"})
    service.submit("stuck", 0, "/stuck", "details")
    stuck = service.active[0]
    service.cancel("stuck")  # Its helper keeps the only background slot until it exits.
    service.submit("bulk", 0, "/bulk", "scan")
    assert stuck in service.retired and [r.path for r in service.pending] == ["/bulk"]
    service.submit("tab", 0, "/browse", "list")
    service.submit("tab", 0, "/data", "load")
    assert {(r.path, r.lane) for r in service.active} == {("/browse", FOREGROUND), ("/data", FOREGROUND)}
    assert [r.path for r in service.pending] == ["/bulk"]
    exit_helper(service, stuck)
    # The background slot is free, but background work waits while the foreground works.
    assert [r.path for r in service.pending] == ["/bulk"]
    service.shutdown()


def test_background_pauses_while_foreground_works_and_resumes_after_delay(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = lanes_service(monkeypatch, {"tab"})
    service.configure_concurrency(2)
    service.submit("other-tab", 0, "/a", "load")
    background = service.active[0]
    background.output = str(tmp_path)
    flag = tmp_path / "pause"
    assert background.lane == BACKGROUND
    service.submit("tab", 0, "/browse", "list")
    listing = active(service, "tab", "list")
    service.submit("bulk", 0, "/bulk", "scan")
    service._tick()
    assert background.pause_requested and flag.exists()
    assert [r.path for r in service.pending] == ["/bulk"]  # Not dispatched beside the foreground.
    service.messages.put((background, {"kind": "paused"}))
    service._tick()
    assert background.paused and "Paused while the current tab browses or loads:\nLoad data: /a" in service.queue_tooltip()
    # The no-progress timer is frozen while paused.
    background.last_activity = time.monotonic() - service.NO_PROGRESS_TIMEOUT - 1
    service._tick()
    assert background in service.active and not background.cancelled.is_set()
    exit_helper(service, listing)
    # Consecutive expands must not stop and start background work.
    assert background.pause_requested and flag.exists()
    service._foreground_busy_at -= service.RESUME_DELAY
    service._tick()
    assert not background.pause_requested and not flag.exists()
    assert [r.path for r in service.active] == ["/a", "/bulk"]
    service.messages.put((background, {"kind": "resumed"}))
    service._tick()
    assert not background.paused and background in service.active
    assert time.monotonic() - background.last_activity < 5
    service.shutdown()


def test_selected_load_pauses_for_listings_and_stalled_listings_do_not_block(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = lanes_service(monkeypatch, {"tab"})
    service.submit("tab", 0, "/data", "load")
    load = active(service, "tab", "load")
    service.submit("tab", 0, "/first", "list")
    service.submit("tab", 0, "/second", "list")
    first = active(service, "tab", "list")
    assert [r.path for r in service.pending] == ["/second"]  # One listing at a time.
    service._tick()
    assert load.pause_requested
    # A listing without progress for 3 s cannot help a hung volume: the next
    # listing starts and the selected load resumes.
    first.last_activity = time.monotonic() - service.STALLED_LISTING - 1
    service._listing_busy_at -= service.RESUME_DELAY
    service._tick()
    assert [r.path for r in service.active] == ["/data", "/first", "/second"]
    assert load.pause_requested  # The new listing is progressing.
    second = service.active[2]
    second.last_activity = time.monotonic() - service.STALLED_LISTING - 1
    service._listing_busy_at -= service.RESUME_DELAY
    service._tick()
    assert not load.pause_requested
    # A dead mount cannot pile up foreground helpers: three at most, stopping included.
    service.submit("tab", 0, "/third", "list")
    assert [r.path for r in service.pending] == ["/third"]
    service.cancel("tab", "list")
    assert len(service.retired) == 2 and not service.pending
    service.submit("tab", 1, "/fourth", "list")
    assert [r.path for r in service.pending] == ["/fourth"]
    exit_helper(service, first)
    assert [r.path for r in service.active] == ["/data", "/fourth"]
    service.shutdown()


@pytest.mark.parametrize("slot_free", [True, False])
def test_load_leaving_foreground_takes_free_background_slot_or_is_requeued(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, slot_free: bool,
) -> None:
    foreground = {"tab"}
    service = lanes_service(monkeypatch, foreground)
    events: list[tuple[IORequest, dict[str, Any]]] = []
    service.resultReady.connect(lambda request, event: events.append((request, event)))
    if not slot_free:
        service.submit("bulk", 0, "/bulk", "details")
    service.submit("tab", 0, "/a", "load")
    load = active(service, "tab", "load")
    assert load.lane == FOREGROUND
    foreground.clear()  # Another folder is selected; this load continues in the background.
    service.reschedule()
    if slot_free:
        assert load in service.active and load.lane == BACKGROUND and not service.pending
    else:
        assert load in service.retired and load.retirement_reason == REQUEUED
        again = service.pending[0]
        assert (again.owner, again.path, again.operation, again.attempt) == ("tab", "/a", "load", 1)
        assert (again, {"kind": "queued", "retry": True, "requeued": True, "attempt": 1}) in events
        assert service.stopping_summary() == "Waiting for background load to stop (0 s)"
        assert "restarts from the shots already loaded when it exits" in service.queue_tooltip()
        exit_helper(service, load)
        assert service.pending[0] is again  # Still waits for a background slot.
        service._foreground_busy_at -= service.RESUME_DELAY
        exit_helper(service, service.active[0])
        assert service.active == [again] and again.lane == BACKGROUND
    service.shutdown()


def test_tab_switch_moves_work_to_background_and_requeued_load_reuses_ram_shots(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_run", lambda request: None)
    cache = get_folder_cache(service)
    data, browse, bulk = (str(tmp_path / name) for name in ("data", "browse", "bulk"))
    cache.submit("bulk-tab", 0, bulk, "details")
    cache.set_foreground({"tab-a"})
    cache.submit("tab-a", 0, data, "load")
    cache.submit("tab-a", 0, browse, "list")
    load, listing = active(service, cache.jobs[("load", data)].owner, "load"), service.active[-1]
    assert (load.lane, listing.lane) == (FOREGROUND, FOREGROUND)
    shot = os.path.join(data, "d_txy_forc1.txt")
    service.messages.put((load, {"kind": "file_started", "filename": shot}))
    service.messages.put((load, {"kind": "shot", "shot": 1, "array": np.array([[1.0, 2, 3]]),
                                "fingerprint": [1, 10, 100]}))
    service.messages.put((load, {"kind": "file_finished", "filename": shot}))
    service._tick()
    cache.set_foreground({"tab-b"})
    # The listing finishes as background work; the load has no free slot, so it
    # stops and restarts later from the shot already in RAM.
    assert listing in service.active and listing.lane == BACKGROUND
    assert load in service.retired
    again = next(r for r in service.pending if r.operation == "load")
    assert again.payload["memory"] == [[1, 10, 100]]
    cache.set_foreground({"tab-a"})
    exit_helper(service, load)
    assert again in service.active and again.lane == FOREGROUND
    service.shutdown()


def test_helper_waits_at_checkpoints_while_paused(tmp_path: Path) -> None:
    (tmp_path / "folder").mkdir()
    (tmp_path / "folder" / "d_txy_forc1.txt").write_text("")
    control = tmp_path / "control"
    control.mkdir()
    flag = control / "pause"
    flag.touch()
    Pause.configure(str(control))
    events: list[dict[str, Any]] = []
    try:
        worker = threading.Thread(target=list_folder, args=(str(tmp_path / "folder"), events.append))
        worker.start()
        deadline = time.monotonic() + 5
        while not events and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.2)
        assert [event["kind"] for event in events] == ["scan_history", "paused"]
        flag.unlink()
        worker.join(5)
        kinds = [event["kind"] for event in events]
        assert kinds[:3] == ["scan_history", "paused", "resumed"] and kinds[-1] == "status"
    finally:
        Pause.configure(None)
