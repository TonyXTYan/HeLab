"""FolderCache's shared jobs: how each is keyed, joined and forgotten (area review io-2,
.ai/sessions/2026-10-31-claude-area-review/io.md on ``agent/area-review``)."""
from __future__ import annotations

import os
from typing import Any

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from helab.utils.folder_cache import FolderCache
from helab.utils.io_service import IORequest, IOService
from test_folder_cache import service_for_test

RUN = os.path.abspath("/data/run")
# A plot's own TXY source (``AnalysisInstance._load_source``): its load is keyed by its choice.
OWN_SOURCE = {"txy": {"source": "helab-only"}, "no_cache": True}


def own_producer(cache: FolderCache, service: IOService) -> IORequest:
    job = next(job for key, job in cache.jobs.items() if key[0].startswith("load:"))
    return next(r for r in service.pending if r.owner == job.owner)


def finish(service: IOService, producer: IORequest) -> None:
    service.resultReady.emit(producer, {"kind": "started"})
    service.resultReady.emit(producer, {"kind": "shot", "shot": 1, "array": np.zeros((1, 3)),
                                        "fingerprint": [1, 10, 100]})
    service.resultReady.emit(producer, {"kind": "loaded", "signature": "sig", "fingerprint": [[1, 10, 100]],
                                        "problematic": [], "files": 1, "rows": 1, "bytes": 24})
    service.resultReady.emit(producer, {"kind": "done"})


def events_of(cache: FolderCache, owner: str) -> list[str]:
    events: list[str] = []

    def record(request: IORequest, event: dict[str, Any]) -> None:
        if request.owner == owner:
            events.append(event["kind"])
    cache.resultReady.connect(record)
    return events


def test_a_plot_choice_load_is_forgotten_when_it_ends_so_the_next_one_runs(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = service_for_test(monkeypatch)
    cache = FolderCache(service)
    try:
        assert cache.submit("plot-1", 0, RUN, "load", dict(OWN_SOURCE))
        first = own_producer(cache, service)
        finish(service, first)
        assert not cache.jobs  # Forgotten: its arrays go with the dataset.
        events = events_of(cache, "plot-2")
        assert cache.submit("plot-2", 0, RUN, "load", dict(OWN_SOURCE))
        second = own_producer(cache, service)
        assert second is not first and second.operation == "load"
        assert events == ["queued"]
    finally:
        service.shutdown()


def test_a_cancelled_plot_choice_load_is_forgotten(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    """A choice change while the plot's load runs (``_end_source_load`` → ``cancel``)."""
    service = service_for_test(monkeypatch)
    cache = FolderCache(service)
    try:
        assert cache.submit("plot-1", 0, RUN, "load", dict(OWN_SOURCE))
        cache.cancel("plot-1", "load", RUN)
        assert not cache.jobs
        assert cache.submit("plot-1", 1, RUN, "load", dict(OWN_SOURCE))
        assert len(cache.jobs) == 1
    finally:
        service.shutdown()


def test_clearing_a_folders_cache_cancels_its_plot_choice_loads(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = service_for_test(monkeypatch)
    cache = FolderCache(service)
    try:
        events = events_of(cache, "plot-1")
        assert cache.submit("plot-1", 0, RUN, "load", dict(OWN_SOURCE))
        producer = own_producer(cache, service)
        cache._invalidate_data(RUN)
        assert "cancelled" in events and not cache.jobs and producer.owner not in cache._producers
    finally:
        service.shutdown()
