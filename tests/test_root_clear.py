"""Settings › Data roots › Clear cached data…: one data root's cache (``clear_root``), nothing else."""
from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Iterator

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from helab.utils.cache_store import CacheStore, DatasetRecord, SaveGuard, SaveRejected, pack_dataset
from helab.utils.folder_cache import FolderCache
from helab.utils.io_service import IOService
from helab.views import DataRootsTab as tab_module
from helab.views.DataRootsTab import CLEAR, DataRootsTab

pytestmark = pytest.mark.no_auto_data_root

A, B = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def record(value: float) -> DatasetRecord:
    return {"ram_bytes": 144, "rows": 6, "shots": 2, "fingerprint": [[1, 10, int(value)], [2, 10, int(value)]],
            "problematic": [], "info": {"saved_at": time.time(), "signature": f"sig-{value}", "kind": "txy"}}


def save(store: CacheStore, path: str, guard: SaveGuard, value: float) -> None:
    file = store.write_dataset_file(pack_dataset({1: np.full((3, 3), value)}))
    store.save_dataset(path, file, record(value), guard)


def summary(store: CacheStore, path: str, guard: SaveGuard | None = None) -> None:
    store.save_record("summaries", path, {"version": 1, "status": "ok"},
                      guard or store.guard([path], ("summaries",)))


def count(store: CacheStore, table: str, prefix: str) -> int:
    return int(store._conn.execute(f"SELECT count(*) FROM {table} WHERE substr(path, 1, ?) = ?",
                                   (len(prefix), prefix)).fetchone()[0])


@pytest.fixture
def store(tmp_path: Path) -> Iterator[CacheStore]:
    with CacheStore(str(tmp_path / "store")) as opened:
        yield opened


def test_clearing_a_root_removes_only_its_rows_and_keeps_folder_flags(store: CacheStore) -> None:
    for root in (A, B):
        for folder in ("", "/run_1", "/run_1/a"):
            path = f"root://{root}{folder}"
            save(store, path, store.start_dataset_job(path), 1.0)
            summary(store, path)
            store.save_record("subtrees", path, {"version": 1, "status": "something"},
                              store.guard([path], ("subtrees",)))
    store.set_prefs(f"root://{A}/run_1", True, True, time.time())
    for root in (A, B):  # A save waiting for Make room.
        path = f"root://{root}/run_2"
        file = store.write_dataset_file(pack_dataset({1: np.zeros((3, 3))}))
        store.add_pending(path, file, record(2.0), store.start_dataset_job(path), "over_budget")
    # A look-alike UUID prefix of A's is another root.
    save(store, f"root://{A}0", store.start_dataset_job(f"root://{A}0"), 2.0)
    before = store.root_usage()
    assert before[A]["folders"] == 4 and before[A]["bytes"] > 0 and before[B]["folders"] == 4
    removal = store.clear_root(A)
    assert sorted(removal.paths or ()) == [f"root://{A}", f"root://{A}/run_1", f"root://{A}/run_1/a",
                                           f"root://{A}/run_2"]
    assert removal.datasets == 3 and set(removal.kinds) == {"datasets", "summaries", "histories", "subtrees"}
    for table, left in (("datasets", 2), ("folder_summaries", 2), ("subtrees", 2), ("pending_saves", 1)):
        assert count(store, table, f"root://{A}/") == 0 and count(store, table, f"root://{B}/") == left
    assert store.read_dataset(f"root://{A}0").found
    assert store.read_prefs([f"root://{A}/run_1"])[f"root://{A}/run_1"].value == {
        "no_cache": True, "no_auto_load": True, "set_at": pytest.approx(time.time(), abs=60)}
    assert A not in store.root_usage() and store.root_usage()[B] == before[B]


def test_a_save_already_running_below_the_root_cannot_bring_data_back(store: CacheStore) -> None:
    cached, new = f"root://{A}/run_1", f"root://{A}/run_2"  # One cached before, one never.
    save(store, cached, store.start_dataset_job(cached), 1.0)
    running = {path: store.start_dataset_job(path) for path in (cached, new)}
    records = store.guard([new], ("summaries",))
    other = store.start_dataset_job(f"root://{B}/run")
    store.clear_root(A)
    for path, guard in running.items():
        with pytest.raises(SaveRejected):
            save(store, path, guard, 3.0)
    with pytest.raises(SaveRejected):
        summary(store, new, records)
    save(store, f"root://{B}/run", other, 4.0)  # Another root's running save is untouched.
    assert count(store, "datasets", f"root://{A}/") == 0
    # A job started after the clear saves as usual.
    save(store, new, store.start_dataset_job(new), 5.0)
    assert store.read_dataset(new).found


def frozen_service(monkeypatch: pytest.MonkeyPatch) -> IOService:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    return service


def test_the_removal_reaches_folder_cache(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service = frozen_service(monkeypatch)
    monkeypatch.setattr("helab.utils.folder_cache.store_options", lambda: {"directory": str(tmp_path)})
    cache = FolderCache(service)
    path = str(tmp_path / "run_1")
    cache.remember_scan(path, {"status": "ok", "scanned_at": time.time()})
    owner = cache.cache_admin("clear_root", uuid=A)
    request = next(r for r in service.pending if r.owner == owner)
    assert request.operation == "cache_admin" and request.payload["action"] == "clear_root"
    assert request.payload["params"] == {"uuid": A}
    service.resultReady.emit(request, {"kind": "removed", "paths": [path],
                                       "kinds": ["datasets", "summaries", "histories", "subtrees"]})
    qtbot.waitUntil(lambda: path not in cache.scan_summaries)
    service.shutdown()


@pytest.fixture
def jobs() -> list[tuple[str, dict[str, Any]]]:
    return []


@pytest.fixture
def page(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
         jobs: list[tuple[str, dict[str, Any]]]) -> Iterator[DataRootsTab]:
    service = frozen_service(monkeypatch)
    cache = FolderCache(service)

    def admin(action: str, **params: Any) -> str:
        jobs.append((action, params))
        return f"job-{len(jobs)}"
    monkeypatch.setattr(cache, "cache_admin", admin)
    monkeypatch.setattr(tab_module, "store_options", lambda: {"directory": str(tmp_path)})
    settings = DataRootsTab(cache)
    qtbot.addWidget(settings)
    rows = [{"location": "smb://server/dld_output", "uuid": A, "kind": "smb", "label": "dld_output",
             "first_seen": 1.0e9, "last_seen": 1.7e9, "decision": "confirmed", "path": "",
             "cached": {"folders": 12, "bytes": 3 * 1024 ** 3}},
            {"location": "vol://abc/data", "uuid": B, "kind": "vol", "label": "data",
             "first_seen": 1.0e9, "last_seen": 1.6e9, "decision": "confirmed", "path": "/data"}]
    cache.cacheAdminResult.emit("inventory", {"kind": "inventory", "inventory": {"roots": rows}})
    cache.cacheAdminDone.emit("job-1", "inventory", "")
    yield settings
    settings.detach()
    service.shutdown()


def test_clear_names_the_root_and_its_size_then_asks_a_helper(
    page: DataRootsTab, jobs: list[tuple[str, dict[str, Any]]],
) -> None:
    first, second = page.list.topLevelItem(0), page.list.topLevelItem(1)
    assert first is not None and second is not None
    assert first.text(4) == "3.0 GB" and second.text(4) == "—"
    page.list.setCurrentItem(first)  # Not mounted: its cache can still be cleared.
    assert page.clear_button.isEnabled()
    assert next(a for a in page.context_menu().actions() if a.text() == CLEAR).isEnabled()
    asked: list[str] = []

    def answer(title: str, text: str, verb: str) -> bool:
        asked.append(text)
        return len(asked) > 1
    page.confirm = answer
    page.clear_selected()
    assert asked == ["Clears 12 cached folders (3.0 GB) for data root “dld_output” on this computer. "
                     "The .helab-root and folder flags stay."] and len(jobs) == 1
    page.clear_selected()
    assert jobs[-1] == ("clear_root", {"uuid": A}) and not page.clear_button.isEnabled()
    assert page.cache is not None
    page.cache.cacheAdminDone.emit(f"job-{len(jobs)}", "clear_root", "")
    assert jobs[-1] == ("inventory", {})  # The sizes are read again.
    page.list.setCurrentItem(second)
    page.clear_selected()
    assert asked[-1].startswith("Clears the cached data for data root “data”")
