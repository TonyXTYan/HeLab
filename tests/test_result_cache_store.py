"""Saved analysis results in the store and the local-lane helper (result caching R2): saves under
a guard taken when the run started, within the one disk budget, found by their exact key or as an
outdated one of their family; Clear cached analysis (all, a root's) beside Clear cached data
(Clear all, a root's), each leaving the other's; files retired, then swept; a nested root's re-key
moves them; a folder without a disk cache saves nothing."""
from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any

import numpy as np
import pytest

from helab.analysis import result_codec
from helab.io_ops import stores
from helab.io_ops.admin import cache_admin
from helab.io_ops.results import result_find, result_save
from helab.utils import cache_store
from helab.utils.cache_store import KINDS, CacheStore, DatasetRecord, SaveGuard, SaveRejected

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
RUN = f"root://{A}/run"


def packed(size: int = 10) -> bytes:
    return result_codec.pack(*result_codec.encode({"x": np.arange(size, dtype=np.float64), "note": "ok"}))


def save(store: CacheStore, path: str = RUN, lookup: str = "k1", family: str = "f1", *,
         guard: SaveGuard | None = None, data: bytes | None = None, **kwargs: Any) -> cache_store.ResultSave:
    guard = guard or store.start_result_job(path)
    file = store.write_result_file(data or packed())
    return store.save_result(path, lookup, family, {"record": lookup}, file, guard, analysis_id="a", action="Plot",
                             computed_at=kwargs.pop("computed_at", time.time()), **kwargs)


def dataset(store: CacheStore, path: str = RUN) -> None:
    record: DatasetRecord = {"ram_bytes": 1, "rows": 1, "shots": 1, "fingerprint": [], "problematic": [], "info": {}}
    store.save_dataset(path, store.write_dataset_file(b"data"), record, store.start_dataset_job(path))


@pytest.mark.no_auto_data_root
def test_a_result_is_found_by_its_exact_key_or_as_outdated(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "store")) as store:
        assert save(store, computed_at=100.0).saved
        exact = store.find_result(RUN, "k1", "f1").value
        assert exact is not None and exact.exact and exact.row["record"] == {"record": "k1"}
        assert result_codec.unpack(exact.data)[0] == result_codec.encode({"x": np.arange(10.0), "note": "ok"})[0]
        assert save(store, lookup="k2", computed_at=200.0).saved
        outdated = store.find_result(RUN, "k3", "f1").value
        assert outdated is not None and not outdated.exact and outdated.row["lookup"] == "k2"  # The newest.
        assert store.find_result(RUN, "k3", "other").missing
        assert store.find_result(RUN, "k3").missing  # (No family: exact only.)
        assert store.find_result(f"root://{A}/elsewhere", "k1", "f1").missing


@pytest.mark.no_auto_data_root
def test_saving_the_same_key_again_retires_the_old_file(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "store")) as store:
        save(store)
        first = store.find_result(RUN, "k1").value
        save(store)
        second = store.find_result(RUN, "k1").value
        assert first is not None and second is not None and first.row["file"] != second.row["file"]
        assert store._conn.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 1
        assert store._conn.execute("SELECT 1 FROM retired_files WHERE file = ?", (first.row["file"],)).fetchone()
        assert os.path.exists(store._store_file(first.row["file"]))  # Retired, not deleted at once.
        store.sweep(time.time() + cache_store.RETIRE_GRACE + 1)
        assert not os.path.exists(store._store_file(first.row["file"]))
        assert os.path.exists(store._store_file(second.row["file"]))


@pytest.mark.no_auto_data_root
def test_the_sweep_deletes_old_orphan_result_files_only(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "store")) as store:
        save(store)
        orphan = store.write_result_file(packed())  # (A writer killed before its row.)
        young = store.write_result_file(packed())
        old = time.time() - cache_store.ORPHAN_MIN_AGE - 10
        os.utime(store._store_file(orphan), (old, old))
        assert store.inventory()["orphans"]["count"] == 2
        store.sweep()
        assert not os.path.exists(store._store_file(orphan)) and os.path.exists(store._store_file(young))
        row = store.find_result(RUN, "k1").value
        assert row is not None


@pytest.mark.no_auto_data_root
@pytest.mark.parametrize("clear", ["all", "root", "folder"])
def test_clearing_cached_analysis_rejects_a_save_already_running(tmp_path: Path, clear: str) -> None:
    with CacheStore(str(tmp_path / "store")) as store:
        save(store, lookup="old")
        guard = store.start_result_job(RUN)  # The run starts...
        removal = (store.remove_results() if clear == "all" else store.remove_results(root=A) if clear == "root"
                   else store.remove_results([RUN]))  # ...the user clears...
        assert removal.results == 1 and removal.paths == (None if clear == "all" else (RUN,))
        with pytest.raises(SaveRejected) as rejected:
            save(store, guard=guard)  # ...and its save can't bring results back.
        assert rejected.value.reason == "cleared"
        assert store.find_result(RUN, "k1").missing and store.find_result(RUN, "old").missing
        assert store._conn.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 0
        assert save(store).saved  # A run started after the clear saves.


@pytest.mark.no_auto_data_root
def test_clear_cached_data_leaves_results_and_their_saves(tmp_path: Path) -> None:
    """Tony, 2026-10-22: Clear cached data (Clear all, a root's) and Clear cached analysis are
    separate; neither touches the other's."""
    with CacheStore(str(tmp_path / "store")) as store:
        dataset(store)
        save(store, lookup="kept")
        guard = store.start_result_job(RUN)
        store.remove(KINDS)  # Clear all of the dataset cache.
        store.clear_root(A)  # The root's Clear cached data.
        store.remove(("datasets",), [RUN], _stored_keys=True)  # The folder's cached data.
        assert store.find_result(RUN, "kept").found
        assert save(store, guard=guard).saved  # Its epoch isn't the results'.
        dataset(store)
        store.remove_results(root=A)  # Clear cached analysis leaves the dataset.
        assert store.read_dataset_row(RUN).found and store.find_result(RUN, "kept").missing


@pytest.mark.no_auto_data_root
def test_another_roots_clear_leaves_these_results(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "store")) as store:
        guard = store.start_result_job(RUN)
        save(store, f"root://{B}/run")
        store.remove_results(root=B)
        assert save(store, guard=guard).saved
        assert store.find_result(RUN, "k1").found and store.find_result(f"root://{B}/run", "k1").missing


@pytest.mark.no_auto_data_root
def big_result(seed: int = 0) -> bytes:
    noise = np.random.default_rng(seed).random(20_000)  # (Incompressible: ~160 kB.)
    return result_codec.pack(*result_codec.encode({"x": noise}))


def test_results_count_toward_the_budget_and_one_that_doesnt_fit_waits(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "store")) as store:
        dataset(store)
        before = store.usage()
        budget = before + 250_000
        saved = save(store, data=big_result(), budget=budget, budget_set_at=1.0)
        assert saved.saved and store.usage() >= before + 150_000
        held = save(store, lookup="k2", data=big_result(1), budget=budget, budget_set_at=1.0, label="Correlations")
        assert not held.saved and held.reason == "over_budget" and held.pending_id
        assert store.find_result(RUN, "k2").missing
        # It waits for the user's answer and doesn't count toward the budget.
        assert store.usage() < budget
        inventory = store.inventory(budget)
        assert inventory["results"]["count"] == 1
        assert [(entry["pending_id"], entry["label"], entry["path"]) for entry in inventory["pending_results"]] == [
            (held.pending_id, "Correlations", RUN)]
        assert store._conn.execute("SELECT COUNT(*) FROM retired_files").fetchone()[0] == 0
        # Without holding it, its file is retired at once.
        assert not save(store, lookup="k9", data=big_result(9), budget=budget, budget_set_at=1.0, hold=False).saved
        assert store._conn.execute("SELECT COUNT(*) FROM retired_files").fetchone()[0] == 1
        # A budget set later (recorded by the store) wins over an older job's.
        assert not save(store, lookup="k3", data=big_result(3), budget=10 ** 12, budget_set_at=0.5).saved


@pytest.mark.no_auto_data_root
def test_make_room_removes_least_recently_shown_results_never_datasets(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "store")) as store:
        dataset(store)
        dataset(store, f"root://{A}/other")
        budget = store.usage() + 400_000
        for index, lookup in enumerate(("old", "new")):
            assert save(store, lookup=lookup, data=big_result(index), budget=budget, budget_set_at=1.0).saved
        store._conn.execute("UPDATE results SET last_used = 1 WHERE lookup = 'old'")
        held = save(store, lookup="k3", data=big_result(3), budget=budget, budget_set_at=1.0)
        assert held.pending_id
        room = store.result_room_plan(held.pending_id, budget)
        old_id = store._conn.execute("SELECT result_id FROM results WHERE lookup = 'old'").fetchone()[0]
        assert room.possible and room.result_ids == (old_id,) and room.bytes > 100_000
        # Plain adopt doesn't fit: it keeps waiting, with the plan.
        kept = store.adopt_pending_result(held.pending_id, budget=budget, budget_set_at=1.0)
        assert not kept.adopted and kept.room == room
        # Make room with another plan than the user was told removes nothing.
        assert not store.adopt_pending_result(held.pending_id, budget=budget, budget_set_at=1.0, make_room=True,
                                              expected_room=["someone-else"]).adopted
        adopted = store.adopt_pending_result(held.pending_id, budget=budget, budget_set_at=1.0, make_room=True,
                                             expected_room=list(room.result_ids))
        assert adopted.adopted and adopted.removal is not None and adopted.removal.results == 1
        assert store.find_result(RUN, "k3").found and store.find_result(RUN, "old").missing
        assert store.find_result(RUN, "new").found
        assert store.read_dataset_row(RUN).found and store.read_dataset_row(f"root://{A}/other").found
        assert store.inventory(budget)["pending_results"] == []


@pytest.mark.no_auto_data_root
def test_make_room_impossible_when_results_alone_cant_free_enough(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "store")) as store:
        dataset(store)
        budget = store.usage() + 50_000  # Smaller than the result: nothing makes room among results.
        held = save(store, data=big_result(), budget=budget, budget_set_at=1.0)
        assert held.pending_id and not store.result_room_plan(held.pending_id, budget).possible


@pytest.mark.no_auto_data_root
def test_a_waiting_result_is_discarded_expired_or_rejected_by_a_clear(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "store")) as store:
        budget = store.usage() + 1_000
        first = save(store, lookup="a", data=big_result(), budget=budget, budget_set_at=1.0)
        assert store.discard_pending_result(first.pending_id) and not store.discard_pending_result(first.pending_id)
        second = save(store, lookup="b", data=big_result(1), budget=budget, budget_set_at=1.0)
        store.remove_results(root=A)  # Clear cached analysis takes the waiting ones too.
        with pytest.raises(SaveRejected) as gone:
            store.adopt_pending_result(second.pending_id, budget=10 ** 12, budget_set_at=2.0)
        assert gone.value.reason == "gone"
        # A purge removing an older result of the folder moves its epoch: the waiting result's guard no
        # longer holds, so it goes with the purge (Make room would refuse it).
        assert save(store, lookup="old", budget=10 ** 12, budget_set_at=2.0).saved
        store._conn.execute("UPDATE results SET last_used = 1")
        guard = store.start_result_job(RUN)
        third = save(store, lookup="c", data=big_result(2), budget=budget, budget_set_at=3.0, guard=guard)
        removal = store.remove_results(cutoff=time.time() - 60)
        assert removal.results == 1 and removal.paths == (RUN,)
        with pytest.raises(SaveRejected) as cleared:
            store.adopt_pending_result(third.pending_id, budget=10 ** 12, budget_set_at=4.0)
        assert cleared.value.reason == "gone"
        assert store._conn.execute("SELECT COUNT(*) FROM pending_results").fetchone()[0] == 0
        fifth = save(store, lookup="e", data=big_result(4), budget=budget, budget_set_at=5.0)
        swept = store.sweep(time.time() + cache_store.PENDING_MAX_AGE + 1)
        assert fifth.pending_id in swept.expired_ids
        assert store._conn.execute("SELECT COUNT(*) FROM pending_results").fetchone()[0] == 0


@pytest.mark.no_auto_data_root
def test_a_nested_roots_rekey_moves_waiting_results_whose_guard_then_fails(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "store")) as store:
        budget = store.usage() + 1_000
        held = save(store, f"root://{A}/inner/run", data=big_result(), budget=budget, budget_set_at=1.0)
        store.rekey_subtree(f"root://{A}/inner", f"root://{B}")
        assert store.inventory()["pending_results"][0]["path"] == f"root://{B}/run"
        with pytest.raises(SaveRejected) as changed:
            store.adopt_pending_result(held.pending_id, budget=10 ** 12, budget_set_at=2.0)
        assert changed.value.reason == "cleared"


@pytest.mark.no_auto_data_root
def test_dont_cache_this_folder_refuses_result_saves(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "store")) as store:
        guard = store.start_result_job(RUN)
        store.set_prefs(RUN, True, False, time.time())
        with pytest.raises(SaveRejected) as rejected:
            save(store, guard=guard)
        assert rejected.value.reason == "no_cache"


@pytest.mark.no_auto_data_root
def test_a_nested_roots_rekey_moves_results(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "store")) as store:
        save(store, f"root://{A}/inner/run", lookup="k1", computed_at=1.0)
        save(store, f"root://{B}/run", lookup="k1", computed_at=2.0)  # Already at the new key, newer.
        save(store, f"root://{A}/inner/other", lookup="k9")
        time.sleep(0.01)
        moved = store.rekey_subtree(f"root://{A}/inner", f"root://{B}")
        assert f"root://{A}/inner/run" in moved
        assert store.find_result(f"root://{B}/other", "k9").found
        kept = store.find_result(f"root://{B}/run", "k1").value
        assert kept is not None and kept.row["computed_at"] == 2.0  # The one saved later wins.
        assert store._conn.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 2


@pytest.mark.no_auto_data_root
def test_root_usage_and_inventory_show_results_apart(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "store")) as store:
        dataset(store)
        save(store)
        usage = store.root_usage()[A]
        assert usage["results"] == 1 and usage["result_bytes"] > 0 and usage["bytes"] == 4
        inventory = store.inventory()
        assert inventory["results"]["count"] == 1 and inventory["results"]["bytes"] > usage["result_bytes"]
        assert inventory["datasets"]["count"] == 1 and inventory["ages"]["results"]


@pytest.mark.no_auto_data_root
def test_purging_results_by_age(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "store")) as store:
        save(store, lookup="old")
        store._conn.execute("UPDATE results SET last_used = 1")
        save(store, lookup="new")
        guard = store.start_result_job(RUN)
        removal = store.remove_results(cutoff=time.time() - 60)
        assert removal.results == 1 and removal.paths == (RUN,)
        assert store.find_result(RUN, "new").found and store.find_result(RUN, "old").missing
        with pytest.raises(SaveRejected):
            save(store, guard=guard)  # (Its folder's results epoch moved.)


# The helper's operations (local lane)

def options(tmp_path: Path) -> dict[str, Any]:
    return {"directory": str(tmp_path / "caches" / "store-v3"), "budget": 8 << 30, "budget_set_at": 1.0}


def find(tmp_path: Path, folder: Path, cache: dict[str, Any] | None, lookup: str = "k1",
         family: str = "f1") -> list[Any]:
    output = tmp_path / f"out-{time.monotonic_ns()}"
    output.mkdir()
    events: list[Any] = []
    result_find(str(folder), str(output), cache, lookup, family, events.append)
    return events


def save_through_helper(tmp_path: Path, folder: Path, cache: dict[str, Any] | None, guard: Any,
                        data: bytes | None = None, lookup: str = "k1") -> list[Any]:
    blob = tmp_path / f"blob-{time.monotonic_ns()}"
    blob.write_bytes(data or packed())
    events: list[Any] = []
    result_save(str(folder), cache, str(blob), lookup=lookup, family="f1", record={"r": 1}, analysis_id="a",
                action="Plot", computed_at=5.0, guard=guard, send=events.append)
    return events


def test_the_helper_finds_saves_and_finds_again(tmp_path: Path) -> None:
    folder = tmp_path / "data" / "run"
    folder.mkdir(parents=True)
    cache = options(tmp_path)
    missing = find(tmp_path, folder, cache)
    assert missing[-1]["kind"] == "result_missing" and "guard" in missing[-1]
    saved = save_through_helper(tmp_path, folder, cache, missing[-1]["guard"])
    assert saved[-1]["kind"] == "result_saved" and saved[-1]["usage"] > 0
    found = find(tmp_path, folder, cache)[-1]
    assert found["kind"] == "result_found" and found["exact"] and found["record"] == {"r": 1}
    assert found["computed_at"] == 5.0 and os.path.exists(found["artifact"])
    tree, arrays = result_codec.unpack(Path(found["artifact"]).read_bytes())
    assert result_codec.decode(tree, arrays)["note"] == "ok"
    outdated = find(tmp_path, folder, cache, lookup="k2")[-1]
    assert outdated["kind"] == "result_found" and not outdated["exact"]


def test_the_helpers_guard_wins_over_a_clear(tmp_path: Path) -> None:
    folder = tmp_path / "data" / "run"
    folder.mkdir(parents=True)
    cache = options(tmp_path)
    guard = find(tmp_path, folder, cache)[-1]["guard"]
    events: list[Any] = []
    cache_admin(cache, "clear_results", events.append)
    assert any(event["kind"] == "removed" and event["kinds"] == ["results"] and event["paths"] is None
               for event in events)
    refused = save_through_helper(tmp_path, folder, cache, guard)[-1]
    assert refused["kind"] == "result_not_saved" and refused["reason"] == "cleared"
    assert find(tmp_path, folder, cache)[-1]["kind"] == "result_missing"


def test_a_roots_clear_cached_analysis_through_the_admin(tmp_path: Path) -> None:
    folder = tmp_path / "data" / "run"
    folder.mkdir(parents=True)
    cache = options(tmp_path)
    save_through_helper(tmp_path, folder, cache, find(tmp_path, folder, cache)[-1]["guard"])
    with stores._cache_store(cache["directory"], [str(folder)]) as store:
        key = store._path_key(str(folder))
    identifier = key[len("root://"):].partition("/")[0]
    events: list[Any] = []
    cache_admin(cache, "clear_root", events.append, uuid=identifier)  # Clear cached data: results stay.
    assert find(tmp_path, folder, cache)[-1]["kind"] == "result_found"
    cache_admin(cache, "clear_root_results", events.append, uuid=identifier)
    removed = [event for event in events if event["kind"] == "removed" and event["kinds"] == ["results"]]
    assert removed and removed[0]["root"] == identifier and removed[0]["paths"] == [str(folder)]
    assert next(event for event in events if event["kind"] == "admin_result"
                and event["action"] == "clear_root_results")["results"] == 1
    assert find(tmp_path, folder, cache)[-1]["kind"] == "result_missing"


@pytest.mark.no_auto_data_root
def test_a_folder_without_a_data_root_reads_and_writes_nothing(tmp_path: Path) -> None:
    folder = tmp_path / "plain"
    folder.mkdir()
    cache = options(tmp_path)
    missing = find(tmp_path, folder, cache)
    assert missing[-1] == {"kind": "result_missing", "ram_only": True}
    assert any(event["kind"] == "cache_skipped" for event in missing)
    refused = save_through_helper(tmp_path, folder, cache, {"generations": {"results": 0}, "epochs": {}})
    assert refused[-1]["kind"] == "result_not_saved" and refused[-1]["reason"] == "ram_only"
    results = Path(cache["directory"]) / cache_store.RESULTS_DIRNAME
    assert not results.exists() or not os.listdir(results)


# Round 4: a key's own epoch (Make room's eviction), and a saved row with a waiting replacement

@pytest.mark.no_auto_data_root
def test_a_save_running_since_before_an_eviction_cant_write_the_key_back(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "store")) as store:
        assert save(store, lookup="old", data=big_result(0), budget=10 ** 12, budget_set_at=1.0).saved
        running = store.start_result_job(RUN, "old")  # A run of "old" starts (its save in flight)...
        other = store.start_result_job(RUN, "other")  # ...and one of another key of the folder.
        budget = store.usage() + 50_000
        held = save(store, lookup="a", data=big_result(1), budget=budget, budget_set_at=2.0)
        evicted = store.adopt_pending_result(held.pending_id, budget=budget, budget_set_at=2.0, make_room=True)
        assert evicted.adopted and evicted.removal is not None and evicted.removal.evicted == ((RUN, "old"),)
        with pytest.raises(SaveRejected) as refused:  # Even with room now, the evicted key stays evicted.
            save(store, lookup="old", data=big_result(0), guard=running, budget=10 ** 12, budget_set_at=3.0)
        assert refused.value.reason == "cleared" and store.find_result(RUN, "old").missing
        # Another key's run keeps its guard; a run started after the eviction saves the key again.
        assert save(store, lookup="other", data=big_result(2), guard=other, budget=10 ** 12, budget_set_at=3.0).saved
        fresh = store.start_result_job(RUN, "old")
        assert save(store, lookup="old", data=big_result(0), guard=fresh, budget=10 ** 12, budget_set_at=3.0).saved


@pytest.mark.no_auto_data_root
def test_a_waiting_replacement_goes_when_its_saved_row_is_evicted(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "store")) as store:
        assert save(store, lookup="k", data=big_result(0), budget=10 ** 12, budget_set_at=1.0).saved
        replacement = save(store, lookup="k", data=big_result(9), budget=1, budget_set_at=2.0)
        assert replacement.pending_id and store.find_result(RUN, "k").found  # Both, under one key.
        budget = store.usage() + 50_000
        held = save(store, lookup="a", data=big_result(1), budget=budget, budget_set_at=3.0)
        adopted = store.adopt_pending_result(held.pending_id, budget=budget, budget_set_at=3.0, make_room=True)
        assert adopted.removal is not None and adopted.removal.dropped == (replacement.pending_id,)
        assert store.find_result(RUN, "k").missing
        with pytest.raises(SaveRejected) as gone:
            store.adopt_pending_result(replacement.pending_id, budget=10 ** 12, budget_set_at=4.0)
        assert gone.value.reason == "gone"


@pytest.mark.no_auto_data_root
def test_two_processes_answering_one_waiting_result_one_wins(tmp_path: Path) -> None:
    """Two HeLabs (processes) asked the same question: one Make room and one Discard at once give one
    success and one "gone"/False, never both."""
    import subprocess
    import sys
    directory = tmp_path / "store"
    code = ("import sys\nfrom helab.utils.cache_store import CacheStore, SaveRejected\n"
            "with CacheStore(sys.argv[1]) as store:\n"
            "    if sys.argv[2] == 'adopt':\n"
            "        try:\n"
            "            print('won' if store.adopt_pending_result(sys.argv[3], budget=10 ** 12, budget_set_at=float(sys.argv[4]))"
            ".adopted else 'waiting')\n"
            "        except SaveRejected as rejected:\n"
            "            print(rejected.reason)\n"
            "    else:\n"
            "        print('won' if store.discard_pending_result(sys.argv[3]) else 'gone')\n")
    for round_ in range(4):
        with CacheStore(str(directory)) as store:
            # (Each round's budget is set after the last round's Make room recorded a larger one.)
            pending_id = save(store, lookup=f"k{round_}", data=big_result(round_), budget=1,
                              budget_set_at=10.0 * (round_ + 1)).pending_id
        assert pending_id
        helpers = [subprocess.Popen([sys.executable, "-c", code, str(directory), answer, pending_id,
                                     str(10.0 * (round_ + 1) + 5)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                   for answer in ("adopt", "discard")]
        outcomes = [helper.communicate(timeout=60)[0].strip() for helper in helpers]
        assert sorted(outcomes) in (["gone", "won"], ["won", "gone"]), outcomes
        with CacheStore(str(directory)) as store:
            assert store._conn.execute("SELECT COUNT(*) FROM pending_results").fetchone()[0] == 0
            assert store.find_result(RUN, f"k{round_}").found is (outcomes[0] == "won")
