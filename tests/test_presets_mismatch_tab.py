"""A real tab's cached read and check (helab/views/FolderExplorer.py) against a reopened plot's wait
for data (helab/views/plots/arrangement.py, ``FolderWait``): a cached read from before a mismatch
never lands after it, whatever completes in between (Flint's round-4 order)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterator, List

import numpy as np
import pytest
from PyQt6 import QtWebEngineWidgets  # noqa: F401  (before any QApplication)
from pytestqt.qtbot import QtBot

from helab.analysis.dataset_view import DatasetView
from helab.utils.folder_cache import FolderCache
from helab.utils.io_service import IORequest, IOService
from helab.views.FolderExplorer import FolderExplorer
from helab.views.plots.arrangement import FolderWait

MISSING = {"kind": "shots_missing", "missing": [1], "missing_count": 1, "known_count": 1, "listed_count": 1}


@pytest.fixture
def browser(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FolderExplorer]:
    """A tab on a folder with one TXY file, its helpers held (their events are the test's)."""
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    monkeypatch.setattr("helab.views.plots.arrangement.store_options", lambda: {"directory": "store"})
    (tmp_path / "d_txy_forc1.txt").write_text("1,2,3\n")
    explorer = FolderExplorer(str(tmp_path), str(tmp_path), str(tmp_path), [0, 4, 5])
    qtbot.addWidget(explorer)
    explorer.selectionPathChanged.connect(lambda p: explorer.load_to_ram_cache(p))
    yield explorer
    explorer.close_cleanup()
    service.shutdown()


def producer(cache: FolderCache, path: str, operation: str) -> IORequest:
    job = cache.jobs[(operation, path)]
    return next(r for r in cache.service.pending if r.owner == job.owner)


def send(cache: FolderCache, request: IORequest, *events: dict[str, Any]) -> None:
    for event in events:
        cache.service.resultReady.emit(request, event)
    if request in cache.service.pending:
        cache.service.pending.remove(request)


def test_a_tabs_cached_read_from_before_a_mismatch_never_lands_after_load_as_it_is_now(
        browser: FolderExplorer, qtbot: QtBot, tmp_path: Path) -> None:
    path = str(tmp_path)
    cache = browser.model.cache
    # (1) The tab lists the folder: its cached read of the old shot 1 and its check start.
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    send(cache, producer(cache, path, "list"), {
        "kind": "status", "status": "warning", "count": 1, "details": False, "raw": [], "txy": [1],
        "disk_cached": True,
        "cache_info": {"saved_at": time.time() - 60, "snapshot_at": time.time() - 60, "signature": "old"}},
        {"kind": "done"})
    qtbot.waitUntil(lambda: ("cached", path) in cache.jobs and ("load", path) in cache.jobs)
    read, check = producer(cache, path, "cached"), producer(cache, path, "load")
    # (2) A folder status check (not the tab's) finds shot 1 gone, and the tab's check errors: the
    # folder is mismatched, and the read still in flight is fenced.
    assert cache.submit("status-check", 0, path, "details", {}, priority=True, force=True)
    send(cache, producer(cache, path, "details"), {**MISSING, "kind": "cache_mismatch"},
         {"kind": "error", "message": "Folder details failed"})
    send(cache, check, {"kind": "error", "message": "Load failed — Retry"})
    assert path in cache.mismatched and ("cached", path) not in cache.jobs
    # (3) Load as it is now: shot 9 shows, the mismatch clears.
    browser.load_as_it_is_now(path)
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs)
    load = producer(cache, path, "load")
    assert load.payload["allow_missing"] is True
    send(cache, load, {"kind": "shot", "shot": 9, "array": np.ones((1, 3)), "fingerprint": [9, 6, 123]},
         {"kind": "loaded", "signature": "fresh", "files": 1, "rows": 1, "bytes": 24, "problematic": [],
          "fingerprint": [[9, 6, 123]]}, {"kind": "done"})
    assert path not in cache.mismatched and sorted(browser.folder_opened_data or {}) == [9]
    # (4) Only now does the old read answer: never kept, never shown.
    send(cache, read, {"kind": "shot", "shot": 1, "array": np.ones((1, 3)), "fingerprint": [1, 6, 123]},
         {"kind": "loaded", "signature": "old", "files": 1, "total_files": 1, "failed_files": 0, "rows": 1,
          "bytes": 24, "problematic": [], "source": "disk", "cached": True, "disk_cached": True,
          "disk_cache_pending": False, "verified": False, "fingerprint": [[1, 6, 123]], "memory_shots": [],
          "load_counts": {"reused_disk": 1, "read": 0}}, {"kind": "done"})
    assert all(entry.signature != "old" for entry in cache.datasets.values())
    assert sorted(browser.folder_opened_data or {}) == [9]
    # (5) The tab lets go of the fresh data and RAM pressure evicts it.
    for owner in [owner for owner, entry in cache.pins.items() if entry.path == path]:
        cache.release(owner)
    cache.evict_to(0)
    assert cache.latest_dataset(path) is None
    # (6) A reopened plot's wait made now has nothing old to take: it asks the disk cache again, and
    # that read, asked after the folder matched again, is taken.
    wait = FolderWait(cache, path)
    found: List[DatasetView] = []
    wait.found.connect(found.append)
    wait.look()
    assert found == [] and ("cached", path) in cache.jobs
    send(cache, producer(cache, path, "cached"),
         {"kind": "shot", "shot": 9, "array": np.ones((1, 3)), "fingerprint": [9, 6, 123]},
         {"kind": "loaded", "signature": "fresh", "files": 1, "rows": 1, "bytes": 24, "problematic": [],
          "fingerprint": [[9, 6, 123]], "verified": False}, {"kind": "done"})
    assert [view.shot_numbers for view in found] == [(9,)]
