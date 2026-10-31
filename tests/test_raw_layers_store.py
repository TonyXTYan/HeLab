"""store-v4's raw layers (caching v2 stage 1, step 5's store side): saves in batches under their own
guard (``gen_raw``, a folder's ``raw:`` epoch, its root's, ``job_seq``), within the budget and never
waiting for an answer (T~1); kept, replaced and overwritten files; the only-copy mark; Make room's
order (datasets, raw layers seen, only copies: D8); Clear; the sweep's orphan rule over ``raw/``; the
admin's ``clear_raw``; store-v3's bytes counted while kept (D9). Temp stores only."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any

import pytest

from helab.convert import raw_layer
from helab.io_ops.admin import cache_admin
from helab.utils import cache_move, cache_store
from helab.utils.cache_store import (CacheStore, DatasetRecord, RawEntry, SaveRejected, StoreError, older_stores,
                                     room_items)

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
RUN, X, Y, Z = (f"root://{A}/{name}" for name in ("run", "x", "y", "z"))
RECORD: DatasetRecord = {"ram_bytes": 1, "rows": 1, "shots": 1, "fingerprint": [], "problematic": [], "info": {}}
pytestmark = pytest.mark.no_auto_data_root


def raw_text(shot: int, rows: int = 200) -> bytes:
    return "".join(f"{5 if i == 0 else 1 + i % 8},{1000 * shot + 37 * i}\r\n" for i in range(rows)).encode()


def entry(store: CacheStore, shot: int, *, size: int | None = None, mtime_ns: int = 1_700_000_000_000_000_000,
          parser: int = raw_layer.RAW_PARSER_VERSION, rows: int = 200) -> RawEntry:
    data = raw_text(shot, rows)
    layer = raw_layer.encode(data)
    file = store.write_raw_file(raw_layer.to_hlb(layer, meta={"name": f"d{shot}.txt"}))
    return RawEntry(shot, f"d{shot}.txt", len(data) if size is None else size, mtime_ns,
                    hashlib.sha256(data).hexdigest(), parser, layer.encoding, layer.facts.to_json(), layer.pulses, file)


def retired(store: CacheStore) -> set[str]:
    return {str(file) for (file,) in store._conn.execute("SELECT file FROM retired_files")}


def v4(tmp_path: Path) -> CacheStore:
    return CacheStore(str(tmp_path / "caches" / "store-v4"))


def test_a_batch_saves_its_layers_and_they_read_back(tmp_path: Path) -> None:
    with v4(tmp_path) as store:
        before = store.usage()
        guard = store.start_raw_job(RUN)
        entries = [entry(store, shot) for shot in (1, 2)]
        saved = store.save_raw_batch(RUN, entries, guard, budget=8 << 30, budget_set_at=1.0)
        assert (saved.saved, saved.kept, saved.refused, saved.overwritten, saved.reason) == ((1, 2), (), (), (), "")
        assert saved.usage == store.usage() > before + saved.bytes - 1 and saved.bytes > 0
        found = store.read_raw(RUN, 2).value
        assert found is not None
        row, data = found
        assert (row.shot, row.name, row.parser, row.encoding, row.gone_at, row.job_seq) == (
            2, "d2.txt", raw_layer.RAW_PARSER_VERSION, raw_layer.COMPACT, None, guard.job_seq)
        assert row.maker and row.maker == store._maker_id()
        layer, header = raw_layer.from_hlb(data)
        assert raw_layer.decode(layer).times[0] == 2000.0 and header["meta"]["name"] == "d2.txt"
        rows = store.raw_rows(RUN).value
        assert rows is not None and set(rows) == {1, 2} and store.raw_rows(X).value == {}
        assert store.read_raw(RUN, 9).missing
        raw = store.inventory()["raw"]
        assert (raw["count"], raw["folders"], raw["only_copy"]) == (2, 1, 0) and raw["bytes"] == saved.bytes


def test_the_same_file_is_kept_a_newer_version_replaces_and_an_overwrite_is_named(tmp_path: Path) -> None:
    with v4(tmp_path) as store:
        first = entry(store, 1)
        store.save_raw_batch(RUN, [first], store.start_raw_job(RUN))
        again = entry(store, 1)
        kept = store.save_raw_batch(RUN, [again], store.start_raw_job(RUN))
        assert kept.kept == (1,) and kept.saved == () and again.file in retired(store)
        assert store.read_raw(RUN, 1).value[0].file == first.file  # type: ignore[index]
        older = store.start_raw_job(RUN)
        newer = store.start_raw_job(RUN)
        changed = entry(store, 1, size=9999, mtime_ns=1_800_000_000_000_000_000)
        replaced = store.save_raw_batch(RUN, [changed], newer)
        assert replaced.saved == (1,) and first.file in retired(store)
        [overwrite] = replaced.overwritten
        assert overwrite.shot == 1 and overwrite.old[:2] == (first.size, first.mtime_ns)
        assert overwrite.new == (9999, 1_800_000_000_000_000_000, changed.sha256)
        stale = entry(store, 1, size=1234)
        refused = store.save_raw_batch(RUN, [stale], older)  # (Its listing was older: the newer version stands.)
        assert refused.refused == (1,) and stale.file in retired(store)
        assert store.read_raw(RUN, 1).value[0].size == 9999  # type: ignore[index]
        parsed_again = entry(store, 1, size=9999, mtime_ns=1_800_000_000_000_000_000, parser=99)
        upgrade = store.save_raw_batch(RUN, [parsed_again], store.start_raw_job(RUN))
        assert upgrade.saved == (1,) and upgrade.overwritten == ()  # (Another parser, the same file.)


@pytest.mark.parametrize("clear", ["all", "folder", "root"])
def test_a_clear_after_a_job_started_rejects_its_batch_and_retires_its_files(tmp_path: Path, clear: str) -> None:
    with v4(tmp_path) as store:
        store.save_raw_batch(RUN, [entry(store, 1)], store.start_raw_job(RUN))
        guard = store.start_raw_job(RUN)
        if clear == "all":
            removal = store.remove_raw()
            assert removal.paths is None and removal.rows == 1
        elif clear == "folder":
            assert store.remove_raw([RUN]).paths == (RUN,)
        else:
            assert store.clear_root(A).raw_rows == 1
        late = entry(store, 2)
        with pytest.raises(SaveRejected, match="cleared"):
            store.save_raw_batch(RUN, [late], guard)
        assert late.file in retired(store) and store.raw_rows(RUN).value == {}
        assert store.save_raw_batch(RUN, [entry(store, 2)], store.start_raw_job(RUN)).saved == (2,)


def test_other_clears_dont_fence_a_folders_raw_saves(tmp_path: Path) -> None:
    with v4(tmp_path) as store:
        guard = store.start_raw_job(RUN)
        store.remove_raw([X])  # (Another folder's raw layers.)
        store.remove(cache_store.KINDS, [RUN])  # (Its datasets and records: kinds of their own, cache-2.)
        store.clear_root(B)  # (Another root.)
        assert store.save_raw_batch(RUN, [entry(store, 1)], guard).saved == (1,)


def test_dont_cache_refuses_a_batch(tmp_path: Path) -> None:
    with v4(tmp_path) as store:
        guard = store.start_raw_job(RUN)
        store.set_prefs(RUN, True, False, time.time())
        with pytest.raises(SaveRejected) as refused:
            store.save_raw_batch(RUN, [entry(store, 1)], guard)
        assert refused.value.reason == "no_cache"


def test_a_batch_that_doesnt_fit_saves_nothing_and_never_waits(tmp_path: Path) -> None:
    """T~1 (proposed): a raw batch over the budget isn't saved, asks nothing and leaves no pending save."""
    with v4(tmp_path) as store:
        budget = store.usage() + 10
        entries = [entry(store, shot) for shot in (1, 2)]
        result = store.save_raw_batch(RUN, entries, store.start_raw_job(RUN), budget=budget, budget_set_at=1.0)
        assert (result.saved, result.reason) == ((), "over_budget") and result.bytes > 10
        assert store.raw_rows(RUN).value == {} and {item.file for item in entries} <= retired(store)
        assert store.inventory()["pending"] == []


def test_a_listing_marks_raw_files_gone_and_seen_again(tmp_path: Path) -> None:
    with v4(tmp_path) as store:
        entries = [entry(store, shot) for shot in (1, 2, 3)]
        store.save_raw_batch(RUN, entries, store.start_raw_job(RUN), now=10.0)
        present = {item.shot: (item.size, item.mtime_ns) for item in entries if item.shot != 2}
        present[3] = (1, 1)  # (Shot 3 changed since: neither seen as cached nor gone.)
        assert store.mark_raw_seen(RUN, present, 20.0) == (1, 1)
        rows = store.raw_rows(RUN).value or {}
        assert (rows[1].seen_at, rows[1].gone_at, rows[2].gone_at, rows[3].gone_at) == (20.0, None, 20.0, None)
        assert store.inventory()["raw"]["only_copy"] == 1
        store.mark_raw_seen(RUN, {item.shot: (item.size, item.mtime_ns) for item in entries}, 30.0)
        assert (store.raw_rows(RUN).value or {})[2].gone_at is None  # (Back: seen again.)


def test_make_room_takes_datasets_then_raw_layers_seen_then_only_copies(tmp_path: Path) -> None:
    """D8: other folders' datasets least recently used first, then raw layers whose files were there at
    the last look, a folder at a time, then raw layers that are the only copy, last. Never the folder
    being saved."""
    with v4(tmp_path) as store:
        store.save_dataset(X, store.write_dataset_file(os.urandom(4000)), RECORD, store.start_dataset_job(X))
        y = [entry(store, shot, rows=3000) for shot in (1, 2)]
        store.save_raw_batch(Y, y, store.start_raw_job(Y), now=5.0)
        z = [entry(store, shot, rows=9000) for shot in (1, 2)]  # (Larger than Y's: enough alone.)
        store.save_raw_batch(Z, z, store.start_raw_job(Z), now=1.0)  # (Used longer ago than Y: still after it.)
        store.mark_raw_seen(Z, {}, 6.0)  # (Z's raw files are gone from the share: the only copy.)
        store.save_raw_batch(RUN, [entry(store, 1, rows=3000)], store.start_raw_job(RUN))
        guard = store.start_dataset_job(RUN)
        file = store.write_dataset_file(os.urandom(6000))
        everything = store.usage()
        pending = store.add_pending(RUN, file, RECORD, guard, "over_budget")
        y_bytes = sum(store._size(item.file) for item in y)
        z_bytes = sum(store._size(item.file) for item in z)
        assert z_bytes > y_bytes > 600
        # A budget that needs X's dataset and Y's raw layers: Z's only copy stays, though it would be enough.
        enough = store.room_plan(pending, everything - 4000 - y_bytes + 6000 + 600)
        assert (enough.paths, enough.raw_paths, enough.only_copy_paths) == ((X,), (Y,), ())
        # A budget that needs X's dataset, Y's raw layers and part of Z's.
        budget = everything - 4000 - y_bytes - z_bytes // 2 + 6000 + 600
        plan = store.room_plan(pending, budget)
        assert plan.possible and plan.paths == (X,) and plan.raw_paths == (Y,) and plan.only_copy_paths == (Z,)
        assert plan.raw_bytes == y_bytes + z_bytes and plan.items == (X, f"raw:{Y}", f"raw-only:{Z}")
        assert not store.adopt_pending(pending, budget=budget, budget_set_at=2.0, make_room=True,
                                       expected_room=[X]).adopted  # (Not what the user was told: nothing goes.)
        adopted = store.adopt_pending(pending, budget=budget, budget_set_at=2.0, make_room=True,
                                      expected_room=list(plan.items))
        assert adopted.adopted and adopted.removal is not None
        assert (adopted.removal.raw_paths, adopted.removal.only_copy_paths) == ((Y,), (Z,))
        assert store.raw_rows(Y).value == {} == store.raw_rows(Z).value and store.raw_rows(RUN).value
        assert store.read_dataset_row(X).missing and store.read_dataset_row(RUN).found


def test_the_sweep_deletes_old_unnamed_and_retired_raw_files_only(tmp_path: Path) -> None:
    with v4(tmp_path) as store:
        named = entry(store, 1)
        store.save_raw_batch(RUN, [named], store.start_raw_job(RUN))
        orphan = store.write_raw_file(b"killed writer")
        young = store.write_raw_file(b"being saved")
        old = time.time() - cache_store.ORPHAN_MIN_AGE - 10
        os.utime(store._store_file(orphan), (old, old))
        store.save_raw_batch(RUN, [entry(store, 1, size=5)], store.start_raw_job(RUN))  # (Retires the first.)
        store.sweep(time.time() + cache_store.RETIRE_GRACE + 1)
        assert not os.path.exists(store._store_file(orphan)) and not os.path.exists(store._store_file(named.file))
        assert os.path.exists(store._store_file(young))
        assert os.path.exists(store._store_file((store.raw_rows(RUN).value or {})[1].file))


def test_store_v3_keeps_no_raw_layers(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "store-v3")) as store:
        with pytest.raises(StoreError, match="store-v4"):
            store.write_raw_file(b"x")
        with pytest.raises(StoreError, match="store-v4"):
            store.start_raw_job(RUN)
        assert store.raw_rows(RUN).missing and store.read_raw(RUN, 1).missing
        assert store.remove_raw().rows == 0 and "raw" not in store.inventory()


def test_the_admin_clears_raw_layers_and_says_so(tmp_path: Path) -> None:
    directory = str(tmp_path / "caches" / "store-v4")
    with CacheStore(directory) as store:
        for path in (RUN, X):
            store.save_raw_batch(path, [entry(store, 1)], store.start_raw_job(path))
    options: dict[str, Any] = {"directory": directory}
    events: list[Any] = []
    cache_admin(options, "clear_raw", events.append, paths=[RUN])
    [removed] = [event for event in events if event["kind"] == "removed"]
    assert removed["kinds"] == ["raw"] and removed["paths"] == [RUN] and removed["raw"] == 1
    assert events[-1]["kind"] == "admin_result" and events[-1]["raw"] == 1
    events.clear()
    cache_admin(options, "clear", events.append)  # (Clear all: raw layers too.)
    assert {tuple(event["kinds"]) for event in events if event["kind"] == "removed"} >= {("raw",)}
    with CacheStore(directory) as store:
        assert store.inventory()["raw"]["count"] == 0
    with pytest.raises(ValueError, match="Unknown cache kinds"):
        cache_admin(options, "clear", events.append, kinds=["nothing"])


def test_a_roots_clear_takes_its_raw_layers_and_says_so(tmp_path: Path) -> None:
    directory = str(tmp_path / "caches" / "store-v4")
    with CacheStore(directory) as store:
        store.save_raw_batch(RUN, [entry(store, 1)], store.start_raw_job(RUN))
    events: list[Any] = []
    cache_admin({"directory": directory}, "clear_root", events.append, uuid=A)
    raw = [event for event in events if event["kind"] == "removed" and event["kinds"] == ["raw"]]
    assert raw and raw[0]["paths"] == [RUN] and raw[0]["raw"] == 1


def test_a_cache_move_verifies_raw_layer_files(tmp_path: Path) -> None:
    caches = tmp_path / "caches"
    with v4(tmp_path) as store:
        made = entry(store, 1)
        store.save_raw_batch(RUN, [made], store.start_raw_job(RUN))
        store_id = store.store_id
    assert cache_move.verify(str(caches), store_id) == ""
    os.remove(caches / "store-v4" / made.file)
    assert "missing" in cache_move.verify(str(caches), store_id)


def test_store_v3s_bytes_count_while_kept_and_older_stores_are_listed(tmp_path: Path) -> None:
    caches = tmp_path / "caches"
    with CacheStore(str(caches / "store-v3")) as v3:
        v3.save_dataset(X, v3.write_dataset_file(os.urandom(50_000)), RECORD, v3.start_dataset_job(X))
    with v4(tmp_path) as store:
        alone = store.usage()
        store.inventory()  # (Measures store-v3: Keep, not answered yet.)
        counted = store.usage()
        assert counted >= alone + 50_000
        with store.transaction():
            store._conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('legacy_v3', ?)",
                                (json.dumps({"choice": "ignore"}),))
        assert store.usage() == alone
    [older] = older_stores(str(caches), 4)
    assert older["name"] == "store-v3" and older["layout"] == 3 and older["bytes"] >= 50_000
    assert older_stores(str(caches), 3) == [] and room_items(["p"], ["q"], ["r"]) == ("p", "raw:q", "raw-only:r")
