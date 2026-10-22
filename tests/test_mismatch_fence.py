"""A folder found mismatched (its cached shots gone, ``FolderCache._mismatch``) fences every piece
of its work started before: a load, a memory check, a Live check, a held save, a cached read or a
RAM answer still queued never brings the old data back or clears the mismatch, whatever completes
before it. Only a load started after the mismatch, and accepted, clears it. Through the helpers'
real events (FolderCache's producer-event handler; helpers held, no source I/O)."""
from __future__ import annotations

import time
from typing import Any, Iterator, List

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from helab.utils.folder_cache import Dataset, FolderCache, get_folder_cache
from helab.utils.io_service import IORequest, IOService

PATH = FolderCache.key("/data/root/fenced")
MISMATCH = {"kind": "cache_mismatch", "missing": [1], "missing_count": 1, "known_count": 2, "listed_count": 1}


@pytest.fixture
def cache() -> Iterator[FolderCache]:
    """A cache whose helpers never run: their requests wait in ``service.pending`` for the test."""
    service = IOService()
    service.timer.stop()
    service._dispatch = lambda: None  # type: ignore[method-assign]
    made = get_folder_cache(service)
    made.max_data_bytes = 1 << 40
    yield made
    service.shutdown()


def start(cache: FolderCache, owner: str, operation: str, payload: dict[str, Any]) -> IORequest:
    """Submit ``operation`` and return its helper's request (the producer the events come from)."""
    assert cache.submit(owner, 0, PATH, operation, payload, priority=True, force=operation == "details")
    key = ("live" if payload.get("live") else operation, PATH)
    job = cache.jobs[key]
    return next(r for r in cache.service.pending if r.owner == job.owner)


def send(cache: FolderCache, request: IORequest, *events: dict[str, Any]) -> None:
    for event in events:
        cache.service.resultReady.emit(request, event)
    if request in cache.service.pending:
        cache.service.pending.remove(request)


def shot(number: int) -> dict[str, Any]:
    return {"kind": "shot", "shot": number, "array": np.full((2, 3), float(number)), "fingerprint": [number, 6, 100 + number]}


def loaded(signature: str, shots: List[int], **more: Any) -> dict[str, Any]:
    return {"kind": "loaded", "signature": signature, "files": len(shots), "rows": 2 * len(shots),
            "bytes": 48 * len(shots), "problematic": [], "fingerprint": [[n, 6, 100 + n] for n in shots], **more}


def old_data(cache: FolderCache) -> Dataset:
    """The folder's data as first loaded (shots 1, 2), checked and listed: a later load's base."""
    request = start(cache, "tab", "load", {})
    send(cache, request, shot(1), shot(2),
         loaded("old", [1, 2], listed_at=time.time(), identity={"location": "here"}, verified=True), {"kind": "done"})
    found = cache.latest_dataset(PATH)
    assert found is not None and found.signature == "old"
    return found


def find_mismatch(cache: FolderCache) -> None:
    """Another folder status check (a details scan) finds shot 1 gone."""
    details = start(cache, "status-check", "details", {})
    send(cache, details, MISMATCH, {"kind": "error", "message": "stopped"})
    assert PATH in cache.mismatched


def events_for(cache: FolderCache, owner: str) -> List[str]:
    kinds: List[str] = []
    cache.resultReady.connect(lambda request, event: kinds.append(event["kind"]) if request.owner == owner else None)
    return kinds


def assert_fenced(cache: FolderCache) -> None:
    assert PATH in cache.mismatched  # Still waiting for Review / Retry.
    assert cache.latest_dataset(PATH) is None
    assert all(entry.signature not in ("old", "late") for entry in cache.datasets.values())


# The families of work started before the mismatch


def test_an_ordinary_load_from_before_the_mismatch_is_fenced(cache: FolderCache) -> None:
    """(Fails on c3d4b50 too: the load's ``loaded`` cleared the mismatch and stored the old data.)"""
    kinds = events_for(cache, "tab")
    request = start(cache, "tab", "load", {})
    find_mismatch(cache)
    send(cache, request, shot(1), loaded("late", [1]), {"kind": "done"})
    assert_fenced(cache)
    assert "cancelled" in kinds and "loaded" not in kinds


def test_a_memory_check_from_before_the_mismatch_is_fenced(cache: FolderCache) -> None:
    old_data(cache)
    request = start(cache, "tab", "load", {})
    assert "memory_check" in request.payload and request.payload["base_signature"] == "old"
    find_mismatch(cache)
    send(cache, request, loaded("old", [1, 2], memory_shots=[1, 2], unchanged=True, base_signature="old"),
         {"kind": "done"})
    assert_fenced(cache)


def test_a_live_check_from_before_the_mismatch_is_fenced(cache: FolderCache) -> None:
    old_data(cache)
    request = start(cache, "tab:live", "load", {"live": {"interval": 3}})
    assert ("live", PATH) in cache.jobs and request.payload["base_signature"] == "old"
    find_mismatch(cache)
    send(cache, request, shot(3), loaded("late", [1, 2, 3], memory_shots=[1, 2], base_signature="old"),
         {"kind": "done"})
    assert_fenced(cache)


def test_a_held_save_from_before_the_mismatch_is_fenced(cache: FolderCache) -> None:
    old_data(cache)
    request = start(cache, "tab:save", "load", {"save": True, "save_memory": True})
    assert "held" in request.payload
    find_mismatch(cache)
    send(cache, request, loaded("late", [1, 2], memory_shots=[1, 2], base_signature="old"), {"kind": "done"})
    assert_fenced(cache)


def test_a_check_beside_a_cached_read_from_before_the_mismatch_leaves_it(cache: FolderCache) -> None:
    """The cached read is fenced, and its check's older ``loaded`` neither stores data nor clears the
    mismatch (it used to clear it, then fail for want of the cached shots)."""
    read = start(cache, "tab", "cached", {"cache": {"directory": "store"}})
    check = start(cache, "tab", "load", {"cache_base": True})
    find_mismatch(cache)
    send(cache, read, shot(1), loaded("old", [1], verified=False), {"kind": "done"})
    send(cache, check, loaded("old", [1], memory_shots=[1], base_signature="old"), {"kind": "done"})
    assert_fenced(cache)


def test_a_queued_answer_from_ram_is_cancelled_by_the_mismatch(cache: FolderCache, qtbot: QtBot) -> None:
    """A load answered from RAM waits for the event loop (``_deliver``): recorded first, the mismatch
    cancels it, and the tab hears so instead of getting the old data back."""
    old_data(cache)
    kinds = events_for(cache, "fast-tab")
    assert cache.submit("fast-tab", 0, PATH, "load", {"signature": "old"}, priority=True)
    assert ("load", PATH) not in cache.jobs  # Answered from RAM, queued.
    find_mismatch(cache)
    qtbot.wait(20)
    assert kinds == ["cancelled"]
    assert_fenced(cache)


# Recovery


def test_load_as_it_is_now_after_the_mismatch_clears_it(cache: FolderCache) -> None:
    old_data(cache)
    find_mismatch(cache)
    request = start(cache, "tab", "load", {"allow_missing": True})
    assert "memory" not in request.payload  # Nothing from before is its base.
    send(cache, request, shot(2), shot(9), loaded("now", [2, 9]), {"kind": "done"})
    assert PATH not in cache.mismatched
    current = cache.latest_dataset(PATH)
    assert current is not None and current.signature == "now" and sorted(current.data) == [2, 9]


def test_a_failed_load_after_the_mismatch_leaves_it(cache: FolderCache) -> None:
    find_mismatch(cache)
    request = start(cache, "tab", "load", {"allow_missing": True})
    send(cache, request, {"kind": "error", "message": "Drive gone — Retry"})
    assert PATH in cache.mismatched


def test_after_resolution_the_tabs_loads_live_and_cached_reads_work(cache: FolderCache) -> None:
    old_data(cache)
    find_mismatch(cache)
    send(cache, start(cache, "tab", "load", {"allow_missing": True}), shot(9), loaded("now", [9]), {"kind": "done"})
    assert PATH not in cache.mismatched
    # The tab's next load takes the new data as its base (never the old).
    again = start(cache, "tab", "load", {})
    assert again.payload.get("base_signature") == "now"
    send(cache, again, shot(10), loaded("now2", [9, 10], memory_shots=[9], base_signature="now"), {"kind": "done"})
    current = cache.latest_dataset(PATH)
    assert current is not None and current.signature == "now2" and sorted(current.data) == [9, 10]
    # Live on it, then a cached read asked now: both accepted.
    live = start(cache, "tab:live", "load", {"live": {"interval": 3}})
    send(cache, live, shot(11), loaded("now3", [9, 10, 11], memory_shots=[9, 10], base_signature="now2"),
         {"kind": "done"})
    current = cache.latest_dataset(PATH)
    assert current is not None and current.signature == "now3"
    read = start(cache, "plot-reopen", "cached", {"cache": {"directory": "store"}})
    send(cache, read, shot(9), loaded("cached-now", [9], verified=False), {"kind": "done"})
    assert any(entry.signature == "cached-now" for entry in cache.datasets.values())
