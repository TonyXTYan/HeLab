"""Roadmap S6: disk cache maintenance (cache_admin), the budget and pending saves, and removals."""
from __future__ import annotations

import builtins
from pathlib import Path
import os
import time
from typing import Any, Callable

import pytest
from pytestqt.qtbot import QtBot

from helab.io_ops import stores
from helab.io_ops.admin import cache_admin
from helab.io_ops.browse import list_folder
from helab.io_ops.loading import load
from helab.io_ops.scanning import scan
from helab.models.SnapshotFileSystemModel import SnapshotFileSystemModel
from helab.utils.cache_store import (
    APPROVAL_SHARE, ORPHAN_MIN_AGE, PENDING_MAX_AGE, RETIRE_GRACE, CacheStore, DatasetRecord, SaveRejected,
    purge_estimate,
)
from helab.utils.folder_cache import FolderCache, get_folder_cache, store_options
from helab.utils.io_service import IORequest, IOService


def record(size: int = 0) -> DatasetRecord:
    return {"ram_bytes": size, "rows": 1, "shots": 1, "fingerprint": [[1, 2, 3]], "problematic": [],
            "info": {"saved_at": time.time(), "signature": "s"}}


def save(store: CacheStore, path: str, size: int, *, budget: int | None = None, last_used: float | None = None) -> Any:
    guard = store.start_dataset_job(path)
    result = store.save_dataset(path, store.write_dataset_file(b"x" * size), record(size), guard, budget=budget)
    if last_used is not None:
        store.touch_dataset(path, last_used)
    return result


def dataset_paths(store: CacheStore) -> set[str]:
    with store.transaction(write=False):
        return {path for (path,) in store._conn.execute("SELECT path FROM datasets")}


def pending_rows(store: CacheStore) -> list[tuple[str, str, str]]:
    with store.transaction(write=False):
        return list(store._conn.execute("SELECT pending_id, path, reason FROM pending_saves"))


@pytest.fixture
def store(tmp_path: Path) -> Any:
    with CacheStore(str(tmp_path / "store-v2")) as opened:
        yield opened


def test_save_over_budget_becomes_pending_and_nothing_is_trimmed(store: CacheStore) -> None:
    save(store, "old", 4000, last_used=100)
    save(store, "recent", 4000, last_used=200)
    budget = store.usage() + 1000
    result = save(store, "new", 3000, budget=budget)
    assert not result.saved and result.reason == "over_budget" and 3000 < result.bytes < 3500  # File and records.
    # Never trimmed automatically; pending bytes don't count.
    assert dataset_paths(store) == {"old", "recent"} and store.usage() < budget
    assert pending_rows(store) == [(result.pending_id, "new", "over_budget")]
    plan = store.room_plan(result.pending_id, budget)
    assert plan.paths == ("old",) and plan.bytes == 4000 and plan.oldest_last_used == 100 and plan.possible
    # A save that fits is saved, with its usage.
    fits = save(store, "small", 500, budget=budget)
    assert fits.saved and fits.usage <= budget


def test_make_room_removes_least_recently_used_others_never_its_own(store: CacheStore) -> None:
    save(store, "target", 1000, last_used=50)  # Oldest of all, but it is being replaced.
    save(store, "a", 3000, last_used=100)
    save(store, "b", 3000, last_used=200)
    save(store, "c", 3000, last_used=300)
    budget = store.usage() + 2000
    pending = save(store, "target", 7000, budget=budget)
    assert pending.reason == "over_budget"
    # The fit rule: live - target's current 1000 + 7000 <= budget needs 4000 freed: a and b.
    adopted = store.adopt_pending(pending.pending_id, budget=budget)
    assert not adopted.adopted and adopted.room is not None and adopted.room.paths == ("a", "b")
    assert dataset_paths(store) == {"target", "a", "b", "c"}
    adopted = store.adopt_pending(pending.pending_id, budget=budget, make_room=True)
    assert adopted.adopted and adopted.removal is not None and adopted.removal.paths == ("a", "b")
    assert dataset_paths(store) == {"target", "c"} and store.usage() <= budget
    assert store.read_dataset_row("target").value is not None
    assert store.read_dataset_row("target").value["bytes"] == 7000  # type: ignore[index]
    assert pending_rows(store) == []


def test_folder_bigger_than_the_budget_can_only_be_discarded(store: CacheStore) -> None:
    save(store, "a", 1000)
    budget = store.usage() + 500
    pending = save(store, "huge", budget + 1, budget=budget)
    adopted = store.adopt_pending(pending.pending_id, budget=budget, make_room=True)
    assert not adopted.adopted and adopted.room is not None and not adopted.room.possible
    assert dataset_paths(store) == {"a"}
    assert store.discard_pending(pending.pending_id) and pending_rows(store) == []


@pytest.mark.parametrize("change", ["cleared", "data cleared", "newer", "superseded", "discarded", "expired"])
def test_make_room_with_a_stale_pending_save_removes_nothing(store: CacheStore, change: str) -> None:
    save(store, "other", 4000, last_used=1)
    save(store, "target", 1000)
    budget = store.usage() + 500
    guard = store.start_dataset_job("target")
    stale = store.save_dataset("target", store.write_dataset_file(b"x" * 5000), record(), guard, budget=budget)
    assert stale.reason == "over_budget"
    if change == "cleared":
        store.remove(("summaries",), ["target"])  # Any removal of the folder bumps its epoch.
    elif change == "data cleared":
        store.remove(("datasets",), ["target"])  # Takes its pending save with it.
    elif change == "newer":
        save(store, "target", 100)
    elif change == "superseded":
        assert not save(store, "target", 5000, budget=budget).saved
    elif change == "discarded":
        store.discard_pending(stale.pending_id)
    else:
        store.sweep(time.time() + PENDING_MAX_AGE + 1)
    with pytest.raises(SaveRejected) as rejected:
        store.adopt_pending(stale.pending_id, budget=budget, make_room=True)
    # A newer direct save drops older pending saves, so they are gone too.
    assert rejected.value.reason == ("cleared" if change == "cleared" else "gone")
    assert "other" in dataset_paths(store)


def test_save_update_over_80_percent_asks_and_rechecks_the_budget(store: CacheStore) -> None:
    save(store, "cached", 1000)
    save(store, "other", 2000, last_used=1)
    # An update that doesn't grow the cache never asks.
    assert save(store, "cached", 900, budget=int(store.usage() / APPROVAL_SHARE)).saved
    budget = int(store.usage() / APPROVAL_SHARE)  # Usage is at 80%.
    assert store.usage() >= APPROVAL_SHARE * budget
    grow = save(store, "cached", 1500, budget=budget)
    assert not grow.saved and grow.reason == "needs_approval"
    # Save update re-checks the current budget: lowered meanwhile, it needs Make room.
    lower = store.usage() + 100
    answer = store.adopt_pending(grow.pending_id, budget=lower)
    assert not answer.adopted and answer.room is not None and answer.room.paths == ("other",)
    assert pending_rows(store) == [(grow.pending_id, "cached", "over_budget")]
    assert store.adopt_pending(grow.pending_id, budget=lower, make_room=True).adopted
    assert dataset_paths(store) == {"cached"}


def test_retired_and_pending_bytes_do_not_count_toward_the_budget(store: CacheStore) -> None:
    save(store, "a", 5000)
    save(store, "a", 1000)  # The 5000-byte file is retired, not deleted.
    pending = save(store, "b", 9000, budget=store.usage() + 100)
    assert not pending.saved
    inventory = store.inventory(budget=10_000_000)
    assert inventory["datasets"]["bytes"] == 1000
    assert inventory["retired"] == {"count": 1, "bytes": 5000}
    assert [entry["path"] for entry in inventory["pending"]] == ["b"]
    assert inventory["usage"] == 1000 + inventory["records_bytes"]


def test_crash_before_or_after_the_pending_row_leaves_no_dangling_reference(store: CacheStore) -> None:
    datasets = Path(store.datasets_dir)
    # Killed after publishing the file, before the pending row committed: an orphan.
    orphan = store.write_dataset_file(b"x" * 100)
    # Killed after the row committed: the pending save waits, then expires.
    pending = save(store, "b", 100, budget=0)
    pending_file = store.inventory()["pending"][0]
    assert not pending.saved and pending_file["path"] == "b"
    now = time.time()
    store.sweep(now)
    assert (datasets / orphan).exists()  # Too young: a writer may still commit it.
    old = now - ORPHAN_MIN_AGE - 1
    os.utime(datasets / orphan, (old, old))
    swept = store.sweep(now + PENDING_MAX_AGE + 1)
    assert not (datasets / orphan).exists() and swept.expired_pending == 1 and pending_rows(store) == []
    # The expired save's file is retired, then deleted after the grace period.
    assert store.inventory()["retired"]["count"] == 1
    store.sweep(now + PENDING_MAX_AGE + RETIRE_GRACE + 2)
    inventory = store.inventory()
    assert inventory["retired"]["count"] == 0 and inventory["orphans"]["count"] == 0
    assert sorted(os.listdir(datasets)) == []


def test_purge_estimates_equal_what_is_freed(store: CacheStore) -> None:
    now = time.time()
    for index, age_days in enumerate((1, 10, 100, 200)):
        save(store, f"d{index}", 1000 * (index + 1), last_used=now - age_days * 86400)
    guard = store.guard(["s-old", "s-new", "t-old", "h-ok", "h-failed"], ("summaries", "subtrees", "histories"))
    store.save_record("summaries", "s-old", {"v": 1}, guard, saved_at=now - 100 * 86400)
    store.save_record("summaries", "s-new", {"v": 1}, guard, saved_at=now)
    store.save_record("subtrees", "t-old", {"v": 1}, guard, saved_at=now - 100 * 86400)
    store.save_record("histories", "h-ok", {"failures": []}, guard, saved_at=now - 100 * 86400)
    store.save_record("histories", "h-failed", {"failures": [{"x": 1}]}, guard, saved_at=now - 100 * 86400)
    cutoff = now - 90 * 86400
    inventory = store.inventory()
    estimate = purge_estimate(inventory, cutoff, datasets=True)
    assert estimate == {"datasets": 2, "bytes": 3000 + 4000}
    removal = store.purge_datasets(cutoff)
    assert (removal.datasets, removal.dataset_bytes) == (estimate["datasets"], estimate["bytes"])
    assert dataset_paths(store) == {"d0", "d1"}
    for include_failures in (False, True):
        inventory = store.inventory()
        estimate = purge_estimate(inventory, cutoff, datasets=False, include_failures=include_failures)
        removed = {kind: len(removal.paths or ()) for removal in store.purge_records(cutoff, include_failures)
                   for kind in removal.kinds}
        assert {kind: count for kind, count in estimate.items() if count} == removed
    assert store.read_record("summaries", "s-new").found
    assert store.read_record("histories", "h-failed").missing


def test_trim_removes_least_recently_used_datasets_and_keeps_records(store: CacheStore) -> None:
    for name, last_used in (("a", 1), ("b", 2), ("c", 3)):
        save(store, name, 3000, last_used=last_used)
    guard = store.guard(["a"], ("summaries", "histories"))
    store.save_record("summaries", "a", {"v": 1}, guard)
    store.save_record("histories", "a", {"failures": [{"x": 1}]}, guard)
    removal = store.trim(store.usage() - 4000)
    assert removal.paths == ("a", "b") and dataset_paths(store) == {"c"}
    assert store.read_record("summaries", "a").found and store.read_record("histories", "a").found


def source_folder(tmp_path: Path, name: str = "source", rows: int = 1) -> Path:
    import numpy as np
    source = tmp_path / name
    source.mkdir()
    generator = np.random.default_rng(len(name))
    for shot in (1, 2):
        values = generator.random((rows, 3)) if rows > 1 else np.array([[shot, 2, 3]])
        (source / f"d_txy_forc{shot}.txt").write_text("".join(f"{t},{x},{y}\n" for t, x, y in values.tolist()))
    return source


def options_for(tmp_path: Path, budget: int | None = None) -> dict[str, Any]:
    options: dict[str, Any] = {"directory": str(tmp_path / "caches" / "store-v3")}
    if budget is not None:
        options["budget"] = budget
    return options


def run_load(source: Path, tmp_path: Path, options: dict[str, Any],
             send: Callable[[dict[str, Any]], None] | None = None) -> list[dict[str, Any]]:
    output = tmp_path / f"artifacts-{time.monotonic_ns()}"
    output.mkdir()
    events: list[dict[str, Any]] = []

    def collect(event: dict[str, Any]) -> None:
        events.append(event)
        if send is not None:
            send(event)
    load(str(source), str(output), collect, options)
    return events


def admin(options: dict[str, Any], action: str, **params: Any) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    cache_admin(options, action, events.append, **params)
    return events


def test_load_that_does_not_fit_is_held_and_make_room_adopts_it(tmp_path: Path) -> None:
    # Like real data, the datasets are far bigger than their records.
    first, second = source_folder(tmp_path, "first", 20_000), source_folder(tmp_path, "second", 20_000)
    options = options_for(tmp_path)
    run_load(first, tmp_path, options)
    with CacheStore(options["directory"]) as store:
        budget = store.usage() + 5000
    events = run_load(second, tmp_path, {**options, "budget": budget})
    # The data is loaded; only its cache save waits.
    assert next(event for event in events if event["kind"] == "loaded")["files"] == 2
    full = next(event for event in events if event["kind"] == "cache_full")
    assert full["path"] == str(second) and list(full["room"]["paths"]) == [str(first)] and full["room"]["possible"]
    assert not any(event["kind"] in ("cache_saved", "cache_save_failed") for event in events)
    result = admin(options, "adopt", pending_id=full["pending_id"], budget=budget, make_room=True)
    removed = next(event for event in result if event["kind"] == "removed")
    assert removed["paths"] == [str(first)] and removed["kinds"] == ["datasets"]
    final = result[-1]
    assert final["kind"] == "admin_result" and final["adopted"] and final["path"] == str(second)
    assert final["cache_info"]["signature"] and final["next_deadline"] is not None
    with stores._cache_store(options["directory"], [str(second)]) as store:
        assert dataset_paths(store) == {store._path_key(str(second))}


def test_inventory_lists_pending_saves_with_their_job_order(store: CacheStore) -> None:
    held = save(store, "a", 100, budget=0)
    assert store.inventory()["pending"][0]["job_seq"] == held.job_seq > 0


def test_inventory_clear_purge_trim_and_discard_through_the_helper(tmp_path: Path) -> None:
    source = source_folder(tmp_path)
    options = options_for(tmp_path)
    run_load(source, tmp_path, options)
    scan(str(source), lambda event: None, options)
    inventory = admin(options, "inventory")[0]["inventory"]
    assert inventory["datasets"]["count"] == 1 and inventory["summaries"]["count"] == 1
    assert inventory["histories"] == {"count": 1, "blocked": 0}
    estimate = purge_estimate(inventory, time.time() + 1, datasets=True)
    events = admin(options, "purge", what="datasets", cutoff=time.time() + 1)
    assert events[-1]["removed"] == {"datasets": estimate["datasets"]} and events[-1]["bytes"] == estimate["bytes"]
    events = admin(options, "clear", kinds=["summaries"])
    assert events[0] == {"kind": "removed", "kinds": ["summaries"], "paths": None, "datasets": 0, "bytes": 0}
    run_load(source, tmp_path, options)
    assert admin(options, "trim", budget=0)[0]["paths"] == [str(source)]
    assert admin(options, "discard", pending_id="gone")[-1]["discarded"] is False
    rejected = admin(options, "adopt", pending_id="gone")[-1]
    assert rejected["adopted"] is False and rejected["rejected"] == "gone"


def removal_during(kind: str, options: dict[str, Any], path: str) -> None:
    if kind == "invalidate":
        with stores._cache_store(options["directory"], [path]) as store:
            store.remove(("datasets",), [path])
    elif kind == "clear":
        admin(options, "clear", kinds=["datasets", "summaries"])
    elif kind == "purge":
        admin(options, "purge", what="datasets", cutoff=time.time() + 60)
        admin(options, "purge", what="records", cutoff=time.time() + 60, include_failures=True)
    elif kind == "trim":
        admin(options, "trim", budget=0)
    elif kind == "make room":
        # Make room for another folder takes this one's dataset.
        with stores._cache_store(options["directory"], [path]) as store:
            other = str(Path(path).parent / f"elsewhere-{time.monotonic_ns()}")
            guard = store.start_dataset_job(other)
            budget = store.usage()
            # As big as this folder's dataset: only removing it makes room.
            size = store.read_dataset_row(path).value["bytes"]  # type: ignore[index]
            pending = store.save_dataset(other, store.write_dataset_file(b"x" * size), record(), guard,
                                         budget=budget)
            assert store.adopt_pending(pending.pending_id, budget=budget, make_room=True).adopted


REMOVALS = ["invalidate", "clear", "purge", "trim", "make room"]


@pytest.mark.parametrize("removal", REMOVALS)
def test_removal_while_a_load_runs_or_saves_does_not_come_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, removal: str,
) -> None:
    source = source_folder(tmp_path)
    path, options = str(source), options_for(tmp_path)
    run_load(source, tmp_path, options)
    (source / "d_txy_forc3.txt").write_text("3,2,3\n")
    for moment in ("starting", "saving"):
        done: list[bool] = []
        original_import = builtins.__import__

        def hook(name: str, *args: Any, **kwargs: Any) -> Any:
            if not done and (moment == "starting" and name == "pandas" or moment == "saving" and name == "blosc"):
                done.append(True)
                removal_during(removal, options, path)
            return original_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", hook)
        events = run_load(source, tmp_path, options)
        monkeypatch.undo()
        assert done, moment
        assert not any(event["kind"] == "cache_saved" for event in events), moment
        with stores._cache_store(options["directory"], [path]) as store:
            assert store.read_dataset_row(path).missing, moment
        run_load(source, tmp_path, options)  # Cached again for the next moment.


@pytest.mark.parametrize("removal", ["clear", "purge"])
def test_removal_while_a_scan_runs_does_not_come_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, removal: str,
) -> None:
    from helab.io_ops import scanning
    source = source_folder(tmp_path)
    path, options = str(source), options_for(tmp_path)
    scan(path, lambda event: None, options)
    original = scanning._scan

    def remove_then_scan(*args: Any) -> dict[str, Any]:
        removal_during(removal, options, path)
        return original(*args)
    monkeypatch.setattr(scanning, "_scan", remove_then_scan)
    events: list[dict[str, Any]] = []
    scan(path, events.append, options, manual=True)
    assert any(event["kind"] == "status" for event in events)
    with CacheStore(options["directory"]) as store:
        assert store.read_record("summaries", path).missing


def frozen_cache(monkeypatch: pytest.MonkeyPatch) -> tuple[IOService, FolderCache]:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    return service, FolderCache(service)


def emit_all(service: IOService, request: IORequest, *events: dict[str, Any]) -> None:
    for event in events:
        service.resultReady.emit(request, event)


def test_removed_event_clears_badges_and_saved_results_and_late_results_stay_out(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen_cache(monkeypatch)
    root, child = str(tmp_path), str(tmp_path / "run")
    saved_summary = {"version": 1, "status": "ok", "count": 1, "signature": "s", "scanned_at": time.time(),
                     "raw_count": 1, "txy_count": 1, "raw": [1], "txy": [1]}
    entry = {"path": child, "name": "run", "scan_history": None, "scan_status": saved_summary,
             "subtree": {"version": 1, "status": "something", "derived_at": time.time(), "older": False,
                         "data": 1, "checked": 1, "total": 1}, "disk_cached": True,
             "cache_info": {"saved_at": time.time(), "signature": "s"}}
    status = {"kind": "status", "details": False, "status": "unknown", "count": -1, "empty": False,
              "has_dirs": True, "scanned_at": time.time(), "raw": [], "txy": []}
    try:
        # A listing that started before the removal reports what was then saved.
        assert cache.submit("tab", 0, root, "list", {"cache": store_options()})
        listing = next(r for r in service.pending if r.operation == "list")
        emit_all(service, listing, {"kind": "entries", "entries": [entry]})
        assert cache.disk_cached(child) and child in cache.scan_summaries and cache.subtree(child)
        cache.removed(None, ["datasets", "summaries", "subtrees"])
        assert not cache.disk_cached(child) and child not in cache.scan_summaries and not cache.subtree(child)
        # Its late results, and the snapshot replayed to other tabs, don't bring them back.
        emit_all(service, listing, {"kind": "entries", "entries": [entry]}, status, {"kind": "done"})
        assert not cache.disk_cached(child) and child not in cache.scan_summaries and not cache.subtree(child)
        snapshot = cache.snapshot(root)
        assert snapshot is not None and all(
            not {"disk_cached", "scan_status", "subtree"} & set(saved) for saved in snapshot.entries)
        # A listing that starts after the removal is trusted again.
        cache.snapshots.clear()
        assert cache.submit("tab-2", 0, root, "list", {"cache": store_options()})
        later = next(r for r in service.pending if r.operation == "list" and r.owner != listing.owner)
        emit_all(service, later, {"kind": "entries", "entries": [entry]})
        assert cache.disk_cached(child) and child in cache.scan_summaries
    finally:
        service.shutdown()


def test_model_drops_removed_saved_summaries_but_keeps_its_own_checks(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    model = SnapshotFileSystemModel(service=service)
    cache = get_folder_cache(service)
    try:
        model.setRootPath(str(tmp_path))
        node = model.nodes[cache.key(str(tmp_path))]
        model._restore_summary(node, {"status": "ok", "count": 2, "scanned_at": time.time(), "raw": [1, 2],
                                      "txy": [1, 2], "signature": "s"})
        assert node.cached_report and node.report is not None
        cache.removed([str(tmp_path)], ["summaries"])
        assert node.report is None and not node.cached_report and node.txy_count == 0
    finally:
        model.close_cleanup()
        service.shutdown()


def test_cleanup_deadlines_schedule_one_sweep_without_a_restart(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, cache = frozen_cache(monkeypatch)
    try:
        owner = cache.cache_admin("clear", kinds=["datasets"])
        request = next(r for r in service.pending if r.owner == owner)
        assert request.operation == "cache_admin" and request.lane == "" and request.payload["params"] == {
            "kinds": ["datasets"]}
        soon = time.time() + 0.2
        emit_all(service, request, {"kind": "removed", "kinds": ["datasets"], "paths": None, "datasets": 0,
                                    "bytes": 0},
                 {"kind": "admin_result", "action": "clear", "next_deadline": time.time() + 3600},
                 {"kind": "admin_result", "action": "clear", "next_deadline": soon},
                 {"kind": "done"})
        assert cache._sweep_deadline == soon and cache._sweep_timer.isActive()
        assert cache._sweep_timer.remainingTime() < 3000
        qtbot.waitUntil(lambda: any(r.operation == "cache_admin" and r.payload["action"] == "sweep"
                                    for r in service.pending), timeout=5000)
        sweep = next(r for r in service.pending if r.payload.get("action") == "sweep")
        emit_all(service, sweep, {"kind": "swept", "next_deadline": time.time() + 600}, {"kind": "done"})
        assert cache._sweep_timer.isActive() and 599_000 < cache._sweep_timer.remainingTime() <= 602_000
    finally:
        service.shutdown()


def test_held_load_save_is_tracked_until_answered(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service, cache = frozen_cache(monkeypatch)
    path = str(tmp_path)
    changes: list[bool] = []
    cache.pendingSavesChanged.connect(lambda: changes.append(True))
    try:
        cache._finishing["writer"] = path
        cache._finishing_epochs["writer"] = 0
        cache._disk_cache_writers.add("writer")
        writer = IORequest("writer", 0, path, "load", {}, 60)
        full = {"kind": "cache_full", "pending_id": "p1", "path": path, "reason": "over_budget", "bytes": 10,
                "usage": 1, "budget": 5, "job_seq": 1, "next_deadline": time.time() + 3600}
        emit_all(service, writer, full, {"kind": "done"})
        assert cache.pending_saves[path]["pending_id"] == "p1" and changes
        assert cache.cache_status(path).error == "Not cached — disk cache full"
        assert not cache.writing_disk_cache("writer")
        owner = cache.cache_admin("adopt", pending_id="p1", make_room=True)
        adopt = next(r for r in service.pending if r.owner == owner)
        emit_all(service, adopt, {"kind": "admin_result", "action": "adopt", "adopted": True, "path": path,
                                  "bytes": 10, "room": None, "cache_info": {"saved_at": 1.0, "signature": "s"},
                                  "next_deadline": None}, {"kind": "done"})
        assert path not in cache.pending_saves and cache.disk_cached(path)
        assert cache.cache_status(path).error == ""
    finally:
        service.shutdown()


def test_listing_and_scan_badges_are_cleared_after_a_helper_removal(tmp_path: Path) -> None:
    """End to end in the helpers: after a clear, listings report the folder as not cached."""
    source = source_folder(tmp_path)
    options = options_for(tmp_path)
    run_load(source, tmp_path, options)
    admin(options, "clear", kinds=["datasets"])
    for helper in (list_folder, scan):
        events: list[dict[str, Any]] = []
        helper(str(tmp_path), events.append, options)
        entry = next(e for event in events if event["kind"] == "entries" for e in event["entries"]
                     if e["path"] == str(source))
        assert entry["disk_cached"] is False


def test_budget_counts_the_records_a_save_adds(store: CacheStore) -> None:
    save(store, "a", 1000)
    big: DatasetRecord = {**record(), "fingerprint": [[shot, 1000, 10**18 + shot] for shot in range(20_000)]}
    file = store.write_dataset_file(b"x" * 100)
    budget = store.usage() + 1000  # The file fits; its ~500 KB fingerprint doesn't.
    result = store.save_dataset("b", file, big, store.start_dataset_job("b"), budget=budget)
    assert not result.saved and result.reason == "over_budget" and result.bytes > 400_000
    assert dataset_paths(store) == {"a"} and store.usage() <= budget
    # Make room removes until the save really fits, records included.
    larger = store.usage() + 700_000
    adopted = store.adopt_pending(result.pending_id, budget=larger, make_room=True)
    assert adopted.adopted and store.usage() <= larger
    assert store.read_dataset_row("b").found


def test_late_save_event_after_a_clear_does_not_restore_the_badge(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen_cache(monkeypatch)
    path = str(tmp_path)
    try:
        # A load whose save committed just before a Clear; its events arrive after.
        cache._finishing["writer"] = path
        cache._finishing_epochs["writer"] = 0
        cache._finishing_created["writer"] = time.monotonic()
        cache._disk_cache_writers.add("writer")
        cache.removed(None, ["datasets"])
        writer = IORequest("writer", 0, path, "load", {}, 60)
        emit_all(service, writer, {"kind": "cache_saved", "cache_info": {"saved_at": 1.0, "signature": "s"},
                                   "next_deadline": None},
                 {"kind": "disk_cached", "disk_cached": True}, {"kind": "done"})
        assert not cache.disk_cached(path)
        assert not cache.cache_status(path).info
    finally:
        service.shutdown()


def test_replacing_a_dataset_schedules_its_cleanup(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    source = source_folder(tmp_path)
    options = options_for(tmp_path)
    run_load(source, tmp_path, options)
    (source / "d_txy_forc3.txt").write_text("3,2,3\n")
    saved = next(event for event in run_load(source, tmp_path, options) if event["kind"] == "cache_saved")
    # The replaced file is retired: its deletion is due after the grace period.
    assert saved["next_deadline"] == pytest.approx(time.time() + RETIRE_GRACE, abs=30)
    service, cache = frozen_cache(monkeypatch)
    try:
        cache._finishing["writer"] = str(source)
        cache._finishing_epochs["writer"] = 0
        cache._finishing_created["writer"] = time.monotonic()
        emit_all(service, IORequest("writer", 0, str(source), "load", {}, 60), saved)
        assert cache._sweep_timer.isActive() and cache._sweep_deadline == saved["next_deadline"]
    finally:
        service.shutdown()


def test_pending_saves_are_matched_by_id_and_expire_with_the_sweep(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen_cache(monkeypatch)
    path, other = str(tmp_path / "a"), str(tmp_path / "b")
    try:
        cache.pending_saves = {path: {"pending_id": "new", "path": path},
                               other: {"pending_id": "old-b", "path": other}}
        # A late answer about an older save of the same folder leaves the newer one alone.
        owner = cache.cache_admin("discard", pending_id="older")
        request = next(r for r in service.pending if r.owner == owner)
        emit_all(service, request, {"kind": "admin_result", "action": "discard", "discarded": False,
                                    "next_deadline": None}, {"kind": "done"})
        owner = cache.cache_admin("adopt", pending_id="older")
        request = next(r for r in service.pending if r.owner == owner)
        emit_all(service, request, {"kind": "admin_result", "action": "adopt", "adopted": False,
                                    "rejected": "gone", "next_deadline": None}, {"kind": "done"})
        assert cache.pending_saves[path]["pending_id"] == "new"
        # Expired by the sweep.
        owner = cache.cache_admin("sweep")
        request = next(r for r in service.pending if r.owner == owner)
        emit_all(service, request, {"kind": "swept", "expired_ids": ["old-b"], "next_deadline": None},
                 {"kind": "done"})
        assert other not in cache.pending_saves and path in cache.pending_saves
        # The store's inventory is the truth.
        owner = cache.cache_admin("inventory")
        request = next(r for r in service.pending if r.owner == owner)
        emit_all(service, request, {"kind": "inventory", "inventory": {"pending": [], "next_deadline": None}},
                 {"kind": "done"})
        assert cache.pending_saves == {}
    finally:
        service.shutdown()


def test_failure_of_a_scan_started_before_a_clear_is_not_saved(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from helab.utils.cache_store import SaveGuard
    from helab.utils.scan_history import write_outcome
    service, cache = frozen_cache(monkeypatch)
    path, options = str(tmp_path), options_for(tmp_path)
    try:
        assert cache.submit("tab", 0, path, "scan", {"cache": options}, force=True)
        request = next(r for r in service.pending if r.operation == "scan")
        with CacheStore(options["directory"]) as store:
            guard = store.guard([path], ("summaries", "histories"))
        emit_all(service, request, {"kind": "save_guard", "guard": {"generations": dict(guard.generations),
                                                                    "epochs": dict(guard.epochs)}})
        cache.removed(None, ["histories"])  # Forget scan failures, while the scan runs.
        emit_all(service, request, {"kind": "error", "message": "Timed out", "timeout": True, "attempt": 1})
        assert not cache.scan_history(path)["blocked"]
        assert not any(r.operation == "scan_history" for r in service.pending)
    finally:
        service.shutdown()
    # In the helper, a history write with the scan's guard is rejected after a Clear.
    with CacheStore(options["directory"]) as store:
        store.remove(("histories",))
        with pytest.raises(SaveRejected):
            write_outcome(store, path, {"operation_id": "x", "revision": 1, "kind": "timeout", "at": time.time(),
                                        "attempts": 1, "reason": "late"}, SaveGuard(guard.generations, guard.epochs))
        assert store.read_record("histories", path).missing


def test_scan_history_helper_uses_the_scan_guard(tmp_path: Path) -> None:
    import json
    import subprocess
    import sys
    options = options_for(tmp_path)
    path = str(tmp_path)
    with stores._cache_store(options["directory"], [path]) as store:
        guard = store.guard([path], ("summaries", "histories"))
        store.remove(("histories",))
    request = {"operation": "scan_history", "path": path, "cache": options,
               "guard": {"generations": dict(guard.generations), "epochs": dict(guard.epochs)},
               "outcome": {"operation_id": "x", "revision": 1, "kind": "timeout", "at": time.time(),
                           "attempts": 1, "reason": "late"}}
    completed = subprocess.run([sys.executable, "-m", "helab.io_helper"], input=json.dumps(request) + "\n",
                               capture_output=True, text=True, timeout=60, check=True)
    last = json.loads(completed.stdout.strip().splitlines()[-1])
    assert last == {"kind": "error", "message": "Cache was cleared before saving completed"}
    with CacheStore(options["directory"]) as store:
        assert store.read_record("histories", path).missing


def big_record(entries: int) -> DatasetRecord:
    return {**record(), "fingerprint": [[shot, 1000, 10**18 + shot] for shot in range(entries)]}


def test_trim_measures_after_each_removal(store: CacheStore) -> None:
    # The oldest folder's records (a large fingerprint) are freed with its file.
    guard = store.start_dataset_job("old")
    store.save_dataset("old", store.write_dataset_file(b"x" * 1000), big_record(20_000), guard)
    store.touch_dataset("old", 1)
    save(store, "new", 1000, last_used=2)
    removal = store.trim(store.usage() - 100_000)
    assert removal.paths == ("old",) and dataset_paths(store) == {"new"}


def test_make_room_preview_is_what_make_room_removes(store: CacheStore) -> None:
    from helab.utils.cache_store import _record_bytes
    save(store, "a", 50_000, last_used=1)
    save(store, "b", 50_000, last_used=2)
    file = store.write_dataset_file(b"x" * 1000)
    incoming = big_record(5_000)
    # Fits once "a" is gone, records included; not before.
    budget = store.usage() + 1000 + _record_bytes(incoming) - 25_000
    pending = store.save_dataset("c", file, incoming, store.start_dataset_job("c"), budget=budget)
    assert not pending.saved
    plan = store.room_plan(pending.pending_id, budget)
    assert plan.possible and plan.paths == ("a",) and plan.bytes == 50_000
    # The preview changed nothing.
    assert dataset_paths(store) == {"a", "b"} and pending_rows(store)[0][0] == pending.pending_id
    adopted = store.adopt_pending(pending.pending_id, budget=budget, make_room=True)
    assert adopted.adopted and adopted.removal is not None and adopted.removal.paths == plan.paths


def test_late_history_save_after_forget_scan_failures_stays_out(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from helab.utils.scan_history import apply_outcome, empty_history
    service, cache = frozen_cache(monkeypatch)
    path = str(tmp_path)
    try:
        cache._history_writes["writer"] = path
        cache._started["writer"] = time.monotonic()
        cache.removed(None, ["histories"])
        blocked = apply_outcome(empty_history(), {"operation_id": "x", "revision": 1, "kind": "timeout",
                                                  "at": time.time(), "attempts": 1, "reason": "late"})
        emit_all(service, IORequest("writer", 0, path, "scan_history", {}, 60),
                 {"kind": "scan_history_saved", "history": blocked}, {"kind": "done"})
        assert not cache.scan_history(path)["blocked"]
    finally:
        service.shutdown()


def test_late_adopt_result_after_a_clear_does_not_restore_the_badge(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen_cache(monkeypatch)
    path = str(tmp_path)
    try:
        cache.pending_saves[path] = {"pending_id": "p", "path": path}
        owner = cache.cache_admin("adopt", pending_id="p", make_room=True)
        request = next(r for r in service.pending if r.owner == owner)
        cache.removed(None, ["datasets"])
        emit_all(service, request, {"kind": "admin_result", "action": "adopt", "adopted": True, "path": path,
                                    "bytes": 1, "room": None, "cache_info": {"saved_at": 1.0, "signature": "s"},
                                    "next_deadline": None}, {"kind": "done"})
        assert not cache.disk_cached(path) and path not in cache.pending_saves
    finally:
        service.shutdown()


def test_newer_saves_reconcile_pending_saves(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service, cache = frozen_cache(monkeypatch)
    path = str(tmp_path)

    def writer(owner: str, *events: dict[str, Any]) -> None:
        cache._finishing[owner] = path
        cache._finishing_epochs[owner] = 0
        cache._finishing_created[owner] = time.monotonic()
        emit_all(service, IORequest(owner, 0, path, "load", {}, 60), *events, {"kind": "done"})

    def held(pending_id: str, job_seq: int, superseded: list[str]) -> dict[str, Any]:
        return {"kind": "cache_full", "pending_id": pending_id, "path": path, "reason": "over_budget", "bytes": 1,
                "usage": 1, "budget": 1, "job_seq": job_seq, "superseded": superseded, "next_deadline": None}
    try:
        writer("w2", held("p2", 2, ["p1"]))
        # An older job's pending save arriving later doesn't replace the newer one shown.
        writer("w1", held("p1", 1, []))
        assert cache.pending_saves[path]["pending_id"] == "p2"
        # A newer job's direct save superseded it in the store; the dialog goes too.
        writer("w3", {"kind": "cache_saved", "cache_info": {"saved_at": 1.0, "signature": "s"},
                      "superseded": ["p2"], "next_deadline": None})
        assert path not in cache.pending_saves and cache.disk_cached(path)
    finally:
        service.shutdown()


def test_rejected_save_schedules_cleanup_of_its_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = source_folder(tmp_path)
    path, options = str(source), options_for(tmp_path)
    done: list[bool] = []
    original_import = builtins.__import__

    def clear_before_saving(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "blosc" and not done:
            done.append(True)
            removal_during("clear", options, path)
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", clear_before_saving)
    events = run_load(source, tmp_path, options)  # The folder's first save.
    monkeypatch.undo()
    failed = next(event for event in events if event["kind"] == "cache_save_failed")
    assert failed["next_deadline"] == pytest.approx(time.time() + RETIRE_GRACE, abs=30)


def test_late_pending_event_after_a_newer_save_is_ignored(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen_cache(monkeypatch)
    path = str(tmp_path)

    def writer(owner: str, *events: dict[str, Any]) -> None:
        cache._finishing[owner] = path
        cache._finishing_epochs[owner] = 0
        cache._finishing_created[owner] = time.monotonic()
        emit_all(service, IORequest(owner, 0, path, "load", {}, 60), *events, {"kind": "done"})
    try:
        # The newer job (2) saved and superseded p1 before p1's own event arrived.
        writer("w2", {"kind": "cache_saved", "cache_info": {"saved_at": 1.0, "signature": "s"}, "job_seq": 2,
                      "superseded": ["p1"], "next_deadline": None})
        writer("w1", {"kind": "cache_full", "pending_id": "p1", "path": path, "reason": "over_budget",
                      "bytes": 1, "usage": 1, "budget": 1, "job_seq": 1, "superseded": [], "next_deadline": None})
        assert path not in cache.pending_saves
        assert cache.cache_status(path).error == ""
    finally:
        service.shutdown()


def test_inventory_requested_before_a_new_pending_save_keeps_it(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen_cache(monkeypatch)
    path, other = str(tmp_path / "new"), str(tmp_path / "old")
    try:
        cache.pending_saves[other] = {"pending_id": "gone-meanwhile", "path": other, "job_seq": 1}
        owner = cache.cache_admin("inventory")
        request = next(r for r in service.pending if r.owner == owner)
        cache._finishing["w"] = path
        cache._finishing_epochs["w"] = 0
        cache._finishing_created["w"] = time.monotonic()
        emit_all(service, IORequest("w", 0, path, "load", {}, 60),
                 {"kind": "cache_full", "pending_id": "p-new", "path": path, "reason": "over_budget", "bytes": 1,
                  "usage": 1, "budget": 1, "job_seq": 3, "superseded": [], "next_deadline": None})
        # The inventory was read before that save, and after "old" was answered elsewhere.
        emit_all(service, request, {"kind": "inventory", "inventory": {"pending": [], "next_deadline": None}},
                 {"kind": "done"})
        assert cache.pending_saves[path]["pending_id"] == "p-new" and other not in cache.pending_saves
    finally:
        service.shutdown()


def test_sweep_rejected_by_a_full_queue_is_retried(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    service, cache = frozen_cache(monkeypatch)
    accept = [False]
    original = service.submit

    def submit(*args: Any, **kwargs: Any) -> bool:
        return original(*args, **kwargs) if accept[0] else False
    monkeypatch.setattr(service, "submit", submit)
    monkeypatch.setattr(FolderCache, "SWEEP_RETRY", 0.1)
    try:
        cache._schedule_sweep(time.time())
        qtbot.waitUntil(lambda: cache._sweep_deadline is not None and cache._sweep_timer.isActive()
                        and cache._sweep_deadline > time.time(), timeout=5000)
        accept[0] = True  # A slot frees up.
        qtbot.waitUntil(lambda: any(r.payload.get("action") == "sweep" for r in service.pending), timeout=5000)
    finally:
        service.shutdown()


def test_inventories_keep_pending_order_and_never_go_back(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen_cache(monkeypatch)
    path = str(tmp_path)
    shown: list[str] = []
    cache.cacheAdminResult.connect(lambda action, event: shown.append(event["kind"]))

    def inventory(pending: list[dict[str, Any]]) -> IORequest:
        owner = cache.cache_admin("inventory")
        return next(r for r in service.pending if r.owner == owner)

    def answer(request: IORequest, pending: list[dict[str, Any]]) -> None:
        emit_all(service, request, {"kind": "inventory", "inventory": {"pending": pending, "next_deadline": None}},
                 {"kind": "done"})
    newer = {"pending_id": "p2", "path": path, "reason": "over_budget", "bytes": 1, "created_at": 2.0, "job_seq": 2}
    try:
        # A pending save known only from an inventory still orders late events, even after
        # it was answered.
        answer(inventory([]), [newer])
        owner = cache.cache_admin("discard", pending_id="p2")
        emit_all(service, next(r for r in service.pending if r.owner == owner),
                 {"kind": "admin_result", "action": "discard", "discarded": True, "next_deadline": None},
                 {"kind": "done"})
        assert path not in cache.pending_saves
        cache._finishing["w1"] = path
        cache._finishing_epochs["w1"] = 0
        cache._finishing_created["w1"] = time.monotonic()
        emit_all(service, IORequest("w1", 0, path, "load", {}, 60),
                 {"kind": "cache_full", "pending_id": "p1", "path": path, "reason": "over_budget", "bytes": 1,
                  "usage": 1, "budget": 1, "job_seq": 1, "superseded": [], "next_deadline": None})
        assert path not in cache.pending_saves
        # An older inventory answered after a newer one is ignored.
        older, latest = inventory([]), inventory([])
        answer(latest, [])
        shown.clear()
        answer(older, [newer])
        assert path not in cache.pending_saves and shown == []
    finally:
        service.shutdown()


def test_failed_listing_history_write_keeps_the_listing_guard(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import json
    import subprocess
    import sys
    service, cache = frozen_cache(monkeypatch)
    path, options = str(tmp_path / "unavailable"), options_for(tmp_path)
    try:
        assert cache.submit("tab", 0, path, "list", {"cache": options})
        request = next(r for r in service.pending if r.operation == "list")
        events: list[dict[str, Any]] = []
        with pytest.raises(OSError):
            list_folder(path, events.append, options)
        assert events[0]["kind"] == "save_guard"
        emit_all(service, request, *events, {"kind": "error", "message": "No such folder"})
        writer = next(r for r in service.pending if r.operation == "scan_history")
        assert writer.payload["guard"] == events[0]["guard"]
    finally:
        service.shutdown()
    # The user forgets scan failures before the queued writer runs: it saves nothing.
    with stores._cache_store(options["directory"], [path]) as store:
        store.remove(("histories",))
    completed = subprocess.run([sys.executable, "-m", "helab.io_helper"],
                               input=json.dumps({"operation": "scan_history", "path": path, **writer.payload}) + "\n",
                               capture_output=True, text=True, timeout=60, check=True)
    assert json.loads(completed.stdout.strip().splitlines()[-1])["message"] == \
        "Cache was cleared before saving completed"
    with stores._cache_store(options["directory"], [path]) as store:
        assert store.read_record("histories", path).missing


def test_clearing_subfolder_status_cancels_a_queued_save(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, cache = frozen_cache(monkeypatch)
    path = str(tmp_path)
    try:
        cache.save_subtree(path, {"status": "something", "derived_at": time.time(), "older": False, "data": 1,
                                  "checked": 1, "total": 1, "identity": None}, store_options())
        cache._save_subtrees()
        writer = next(r for r in service.pending if r.operation == "subtree_save")
        cache.removed(None, ["subtrees"])
        assert writer.cancelled.is_set() and writer not in service.pending
        assert not cache.subtree(path)
    finally:
        service.shutdown()


def test_make_room_removes_exactly_the_folders_it_named_or_nothing(store: CacheStore) -> None:
    """The question named a plan; if the budget changed since, nothing goes and it is asked again."""
    save(store, "old", 4000, last_used=1.0)
    save(store, "older", 4000, last_used=0.5)
    base = store.usage()
    budget = base + 2000
    pending = save(store, "new", 5000, budget=budget)
    plan = store.room_plan(pending.pending_id, budget)
    assert plan.paths == ("older",)
    lower = budget - 4000  # Lowered since: it takes both.
    held = store.adopt_pending(pending.pending_id, budget=lower, make_room=True, expected_room=list(plan.paths))
    assert not held.adopted and held.room is not None and set(held.room.paths) == {"older", "old"}
    assert dataset_paths(store) == {"old", "older"} and pending_rows(store)[0][2] == "over_budget"
    adopted = store.adopt_pending(pending.pending_id, budget=lower, make_room=True, expected_room=["old", "older"])
    assert adopted.adopted and dataset_paths(store) == {"new"}
    # Through the helper, as the dialog sends it: a plan that no longer holds removes nothing.
    other = save(store, "other", 4000, last_used=2.0)
    assert other.saved
    later = save(store, "later", 5000, budget=store.usage() + 1000)
    events: list[dict[str, Any]] = []
    cache_admin({"directory": store.root, "budget": store.usage() + 1000}, "adopt", events.append,
                pending_id=later.pending_id, make_room=True, room_paths=["nowhere"])
    assert events[-1]["adopted"] is False and dataset_paths(store) == {"new", "other"}
