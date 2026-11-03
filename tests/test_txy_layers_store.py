"""Caching v2 stage 2's store side (design addendum §2–§9, inert while the switch is off): TXY layers in
append-only segments, views, per-shot job order, guards, the policy (Q45.1) and source override (Q45.2),
one pending unit per folder with parts (Q45.8), compaction only when it fits (Q45.7), Make room's and
``trim``'s order (Q45.6, A42.2), Clear of TXY layers, the sweep over ``txy/``, a nested root's re-key
(S2-0: raw layers too), stage 1's stores migrated, and a cache move verifying segments. Temp stores only."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
import time
from typing import Any

import numpy as np
import pytest

from helab.convert import raw_layer, txy_layer
from helab.io_ops.admin import cache_admin
from helab.utils import cache_move, cache_store, hlb, store_v4
from helab.utils.cache_move import COPY
from helab.utils.cache_store import (CacheStore, RawEntry, SaveRejected, TxyPart, TxyShot, ViewRecord, room_items,
                                     txy_item)

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
RUN, X, Y, Z, W = (f"root://{A}/{name}" for name in ("run", "x", "y", "z", "w"))
HELAB = txy_layer.helab_layer("abc123")
MATLAB = txy_layer.MATLAB
MTIME = 1_700_000_000_000_000_000
pytestmark = pytest.mark.no_auto_data_root


def later(seconds: float = 60.0) -> float:
    """A listing taken after the saves so far (a new layer was seen when its job saved it)."""
    return time.time() + seconds


def hits(shot: int, rows: int = 300) -> np.ndarray:
    rng = np.random.default_rng(shot * 7919 + rows)
    return rng.random((rows, 3))


def v4(tmp_path: Path) -> CacheStore:
    return CacheStore(str(tmp_path / "caches" / "store-v4"))


def part(store: CacheStore, layer: str, shots: dict[int, int], *, kind: str = "txy", mtime: int = MTIME,
         tags: tuple[str, ...] = ()) -> TxyPart:
    """A published segment of ``shots`` (shot → rows) and its part."""
    data = {shot: hits(shot, rows) for shot, rows in shots.items()}
    file = store.write_txy_file(txy_layer.pack_segment(data, layer=layer, tags=tags))
    return TxyPart(layer, file, tuple(TxyShot(shot, 1000 + shot, mtime, kind, rows) for shot, rows in shots.items()),
                   tags)


def view(shots: dict[int, int], layer: str = MATLAB, signature: str = "sig") -> ViewRecord:
    return {"fingerprint": [[shot, 1000 + shot, MTIME, "txy", layer] for shot in shots], "problematic": [],
            "info": {"signature": signature, "snapshot_at": 1.0}}


def save(store: CacheStore, path: str, *parts: TxyPart, shots: dict[int, int] | None = None,
         **kwargs: Any) -> cache_store.TxySave:
    return store.save_txy(path, "", "", list(parts), view(shots or {}) if shots is not None else None,
                          store.start_txy_job(path), **kwargs)


def retired(store: CacheStore) -> set[str]:
    return {str(file) for (file,) in store._conn.execute("SELECT file FROM retired_files")}


def segments(store: CacheStore, path: str, layer: str) -> list[tuple[int, int, int]]:
    return [(int(seq), int(live), int(count)) for seq, live, count in store._conn.execute(
        "SELECT seq, live_shots, all_shots FROM txy_segments WHERE path = ? AND layer = ? ORDER BY seq", (path, layer))]


# The segment

def test_a_segment_round_trips_and_damage_is_refused() -> None:
    data = {3: hits(3, 10), 1: hits(1, 0), 2: hits(2, 5)}
    packed = txy_layer.pack_segment(data, layer=HELAB, problematic=[2], tags=("m19v1",), precision="f64")
    shots, problematic, header = txy_layer.unpack_segment(packed)
    assert sorted(shots) == [1, 2, 3] and problematic == {2} and header["kind"] == "txy"
    assert header["meta"] == {"layer": HELAB, "profile_hash": "abc123", "tags": ["m19v1"], "precision": "f64"}
    assert all(np.array_equal(shots[shot], data[shot]) for shot in data) and not shots[3].flags.writeable
    assert header["arrays"][2]["codec"]["shuffle"] == "none"
    with pytest.raises(hlb.HlbError):
        txy_layer.unpack_segment(packed[:-3])
    with pytest.raises(hlb.HlbError):
        txy_layer.unpack_segment(raw_layer.to_hlb(raw_layer.encode(b"5,1\r\n")))


# Saving and reading

def test_a_unit_saves_its_layers_and_view_and_they_read_back(tmp_path: Path) -> None:
    with v4(tmp_path) as store:
        before = store.usage()
        done = save(store, RUN, part(store, MATLAB, {1: 300, 2: 200}), shots={1: 300, 2: 200}, budget=8 << 30,
                    budget_set_at=1.0)
        assert (done.saved, done.refused, done.reason, done.pending_id) == ((MATLAB,), (), "", "")
        assert done.usage == store.usage() >= before + done.bytes
        layers = store.txy_layers(RUN).value or {}
        assert set(layers) == {MATLAB} and layers[MATLAB].rows == 500 and layers[MATLAB].ram_bytes == 500 * 24
        assert {shot: (entry.kind, entry.seq) for shot, entry in layers[MATLAB].entries.items()} == {
            1: ("txy", 1), 2: ("txy", 1)}
        read = store.read_txy_shots(RUN, MATLAB).value or {}
        assert np.array_equal(read[2], hits(2, 200)) and set(read) == {1, 2}
        assert set(store.read_txy_shots(RUN, MATLAB, [2]).value or {}) == {2}
        shown = store.read_view(RUN, "", "").value
        assert shown is not None and shown.info["signature"] == "sig" and len(shown.fingerprint) == 2
        assert store.read_view(RUN, "helab-only", "m19v1").missing and store.read_txy_shots(RUN, HELAB).missing
        assert store.inventory()["txy"]["layers"] == 1


def test_saves_append_only_new_and_changed_shots_and_retire_what_nothing_holds(tmp_path: Path) -> None:
    with v4(tmp_path) as store:
        first = part(store, MATLAB, {1: 100, 2: 100})
        save(store, RUN, first)
        second = part(store, MATLAB, {2: 120, 3: 80}, mtime=MTIME + 1)  # (2 changed, 3 new; 1 untouched.)
        save(store, RUN, second)
        assert segments(store, RUN, MATLAB) == [(1, 1, 2), (2, 2, 2)]
        third = part(store, MATLAB, {1: 90}, mtime=MTIME + 2)  # (Segment 1 has no live shot left.)
        save(store, RUN, third)
        assert segments(store, RUN, MATLAB) == [(2, 2, 2), (3, 1, 1)] and first.file in retired(store)
        read = store.read_txy_shots(RUN, MATLAB).value or {}
        assert {shot: len(array) for shot, array in read.items()} == {1: 90, 2: 120, 3: 80}


def test_a_shot_a_later_job_saved_is_kept(tmp_path: Path) -> None:
    with v4(tmp_path) as store:
        earlier, later = store.start_txy_job(RUN), store.start_txy_job(RUN)
        store.save_txy(RUN, "", "", [part(store, MATLAB, {1: 50, 2: 50})], None, later)
        done = store.save_txy(RUN, "", "", [part(store, MATLAB, {1: 70, 3: 70})], None, earlier)
        assert done.refused == ((MATLAB, 1),)
        read = store.read_txy_shots(RUN, MATLAB).value or {}
        assert {shot: len(array) for shot, array in read.items()} == {1: 50, 2: 50, 3: 70}


def test_a_clear_since_the_job_started_rejects_its_unit_and_retires_its_files(tmp_path: Path) -> None:
    with v4(tmp_path) as store:
        guard = store.start_txy_job(RUN)
        late = part(store, MATLAB, {1: 10})
        store.remove_txy([RUN])
        with pytest.raises(SaveRejected):
            store.save_txy(RUN, "", "", [late], view({1: 10}), guard)
        assert late.file in retired(store) and store.txy_layers(RUN).value == {}
        store.set_prefs(RUN, True, False, 5.0)  # (Don't cache.)
        refused = part(store, MATLAB, {1: 10})
        with pytest.raises(SaveRejected, match="your choice"):
            save(store, RUN, refused)
        assert refused.file in retired(store)


def test_policy_raw_writes_no_helab_layer_and_the_choices_follow_convert_prefs(tmp_path: Path) -> None:
    with v4(tmp_path) as store:
        assert store.set_cache_policy(RUN, "raw", 10.0) == {"policy": "raw", "set_at": 10.0}
        assert store.set_cache_policy(RUN, "txy", 9.0)["policy"] == "raw"  # (An earlier choice doesn't win.)
        helab, matlab = part(store, HELAB, {1: 10}, kind="raw"), part(store, MATLAB, {2: 10})
        done = save(store, RUN, helab, matlab)
        assert done.saved == (MATLAB,) and done.dropped == (HELAB,) and helab.file in retired(store)
        other = part(store, HELAB, {1: 10}, kind="raw")  # (Another folder: the global policy the app sends.)
        assert save(store, X, other, default_policy="raw").dropped == (HELAB,)
        assert save(store, X, part(store, HELAB, {1: 10}, kind="raw")).saved == (HELAB,)
        store.set_txy_source_pref(RUN, "helab-priority", "p22v1", 11.0)
        assert store.read_folder_choices([RUN, Y])[RUN].value == {
            "policy": "raw", "policy_set_at": 10.0, "source": "helab-priority", "tag": "p22v1", "source_set_at": 11.0}
        assert store.read_folder_choices([Y])[Y].missing
        with pytest.raises(ValueError):
            store.set_cache_policy(RUN, "everything", 12.0)
        assert RUN in store.clear_prefs(20.0)
        assert store.read_folder_choices([RUN])[RUN].value == {
            "policy": "", "policy_set_at": 20.0, "source": "", "tag": "", "source_set_at": 20.0}
        assert store.set_cache_policy(RUN, "raw", 15.0)["policy"] == ""  # (Chosen before the Clear.)
        options = {"directory": store.root}
    events: list[Any] = []
    cache_admin(options, "folder_choice", events.append, path=RUN, policy="txy", source="matlab-only", set_at=30.0)
    assert events[-1]["choices"]["policy"] == "txy" and events[-1]["choices"]["source"] == "matlab-only"


def test_confirm_writes_only_the_views_info(tmp_path: Path) -> None:
    """A40.3: every shot unchanged, a new signature and listing: no segment, no layer row rewritten."""
    with v4(tmp_path) as store:
        save(store, RUN, part(store, MATLAB, {1: 20}), shots={1: 20})
        layer_before = store._conn.execute("SELECT * FROM txy_layers").fetchall()
        record = view({1: 20})
        guard = store.start_txy_job(RUN)
        info = {"signature": "new", "snapshot_at": 2.0, "txy": {"folders": [["/h", 5]]}}
        assert store.confirm_view(RUN, "", "", record["fingerprint"], info, guard)
        assert (store.read_view(RUN, "", "").value or pytest.fail()).info == info
        assert store._conn.execute("SELECT * FROM txy_layers").fetchall() == layer_before
        assert not store.confirm_view(RUN, "", "", [[1, 1, 1, "txy", MATLAB]], info, guard)  # (Not that view.)
        stale = store.start_txy_job(RUN)
        save(store, RUN, part(store, MATLAB, {2: 5}), shots={1: 20, 2: 5})
        assert not store.confirm_view(RUN, "", "", view({1: 20, 2: 5})["fingerprint"], info, stale)


# Waiting units (Q45.8)

def test_one_waiting_unit_per_folder_merges_layers_and_adopts_each_part_under_its_guard(tmp_path: Path) -> None:
    with v4(tmp_path) as store:
        usage = store.usage()
        matlab = part(store, MATLAB, {1: 300})
        first = save(store, RUN, matlab, shots={1: 300}, budget=usage + 10, budget_set_at=1.0)
        assert first.reason == "over_budget" and first.pending_id and not store.txy_layers(RUN).value
        helab = part(store, HELAB, {1: 300}, kind="raw")
        second = save(store, RUN, helab, budget=usage + 10, budget_set_at=1.0)
        rows = store._conn.execute("SELECT pending_id, parts FROM pending_saves").fetchall()
        assert len(rows) == 1 and rows[0][0] == second.pending_id != first.pending_id
        assert {part_["layer"] for part_ in __import__("json").loads(rows[0][1])} == {MATLAB, HELAB}
        assert {helab.file, matlab.file} <= store._known_files()  # (Every waiting part's file is named.)
        old = time.time() - cache_store.ORPHAN_MIN_AGE - 10
        for file in (helab.file, matlab.file):
            os.utime(store._store_file(file), (old, old))
        store.sweep()  # (Over an hour old, but named by a waiting part: kept.)
        assert all(os.path.exists(store._store_file(file)) for file in (helab.file, matlab.file))
        # The HeLab part's job is fenced since (its txy epoch moved under it): it is dropped, MATLAB's stays.
        import json
        parts = json.loads(rows[0][1])
        for part_ in parts:
            if part_["layer"] == HELAB:
                part_["guard"]["epochs"] = {key: value - 1 for key, value in part_["guard"]["epochs"].items()}
        with store.transaction():
            store._conn.execute("UPDATE pending_saves SET parts = ?", (json.dumps(parts),))
        adopted = store.adopt_pending(second.pending_id, budget=8 << 30, budget_set_at=2.0)
        assert adopted.adopted and set(store.txy_layers(RUN).value or {}) == {MATLAB}
        assert helab.file in retired(store) and store.read_view(RUN, "", "").found


def test_a_later_jobs_part_replaces_a_waiting_one_and_an_earlier_ones_is_dropped(tmp_path: Path) -> None:
    with v4(tmp_path) as store:
        usage = store.usage()
        early = store.start_txy_job(RUN)
        late = store.start_txy_job(RUN)
        newer = part(store, MATLAB, {1: 200})
        store.save_txy(RUN, "", "", [newer], None, late, budget=usage + 10, budget_set_at=1.0)
        older = part(store, MATLAB, {1: 210})
        store.save_txy(RUN, "", "", [older], None, early, budget=usage + 10, budget_set_at=1.0)
        (parts,) = store._conn.execute("SELECT parts FROM pending_saves").fetchone()
        assert newer.file in parts and older.file in retired(store)


# Compaction (Q45.7)

def test_compaction_runs_when_due_and_only_if_it_fits(tmp_path: Path) -> None:
    with v4(tmp_path) as store:
        for shot in range(1, 11):  # (Ten saves: ten segments.)
            save(store, RUN, part(store, MATLAB, {shot: 50}))
        row = (store.txy_layers(RUN).value or {})[MATLAB]
        assert len(row.segments) == 10 and store.compaction_due(row)
        before = store.read_txy_shots(RUN, MATLAB).value or {}
        guard = store.start_txy_job(RUN)
        assert not store.compact_txy(RUN, MATLAB, guard, budget=store.usage() + 100, budget_set_at=1.0)
        assert len(segments(store, RUN, MATLAB)) == 10  # (It doesn't fit beside them: it waits, never asks.)
        assert store.compact_txy(RUN, MATLAB, guard, budget=8 << 30, budget_set_at=2.0)
        assert segments(store, RUN, MATLAB) == [(11, 10, 10)]
        after = store.read_txy_shots(RUN, MATLAB).value or {}
        assert all(np.array_equal(before[shot], after[shot]) for shot in before) and len(after) == 10
        assert not store.compaction_due((store.txy_layers(RUN).value or {})[MATLAB])


# Make room and trim (Q45.6, A42.2)

def raw_entry(store: CacheStore, shot: int, rows: int) -> RawEntry:
    rng = np.random.default_rng(shot * rows)
    data = "".join(f"{5 if i == 0 else int(rng.integers(1, 9))},{1000 * shot + 37 * i}\r\n"
                   for i in range(rows)).encode()
    layer = raw_layer.encode(data)
    file = store.write_raw_file(raw_layer.to_hlb(layer))
    return RawEntry(shot, f"d{shot}.txt", 1000 + shot, MTIME, hashlib.sha256(data).hexdigest(),
                    raw_layer.RAW_PARSER_VERSION, layer.encoding, layer.facts.to_json(), layer.pulses, file)


def five_groups(store: CacheStore) -> None:
    """X: a HeLab layer rebuildable from its raw rows; Y: a MATLAB layer seen; W: raw rows seen;
    Z: a MATLAB layer whose files are gone (an only copy). Used longest ago first: X, Y, W, Z."""
    store.save_raw_batch(X, [raw_entry(store, 1, 400)], store.start_raw_job(X), now=1.0)
    save(store, X, part(store, HELAB, {1: 400}, kind="raw"))
    save(store, Y, part(store, MATLAB, {1: 400}))
    store.save_raw_batch(W, [raw_entry(store, 1, 400)], store.start_raw_job(W), now=1.0)
    save(store, Z, part(store, MATLAB, {1: 400}))
    store.mark_txy_seen(Z, {"matlab": {}}, later())
    with store.transaction():
        for path, used in ((X, 1.0), (Y, 2.0), (Z, 3.0)):
            store._conn.execute("UPDATE txy_layers SET last_used = ? WHERE path = ?", (used, path))


def test_make_room_takes_rebuildable_layers_then_seen_then_raw_then_only_copies(tmp_path: Path) -> None:
    with v4(tmp_path) as store:
        five_groups(store)
        usage = store.usage()
        unit = save(store, RUN, part(store, MATLAB, {1: 400}), shots={1: 400}, budget=usage, budget_set_at=1.0)
        assert unit.pending_id
        layer_bytes = {path: (store.txy_layers(path).value or {}) for path in (X, Y, Z)}
        sizes = {path: sum(row.bytes for row in rows.values()) for path, rows in layer_bytes.items()}
        low, high = 1, usage + unit.bytes  # (The least budget it can fit: everything else must go, in order.)
        while low < high:
            middle = (low + high) // 2
            low, high = (low, middle) if store.room_plan(unit.pending_id, middle).possible else (middle + 1, high)
        assert store.room_plan(unit.pending_id, low).items == room_items(
            (), (W, X), (), [(X, HELAB)], [(Y, MATLAB)], [(Z, MATLAB)])
        assert not store.room_plan(unit.pending_id, low - 1).possible
        margin = sizes[Y] // 4  # (Records change by far less; Y's layer by far more.)
        only_x, x_and_y = usage + unit.bytes - sizes[X] + margin, usage + unit.bytes - sizes[X] - sizes[Y] + margin
        plan = store.room_plan(unit.pending_id, only_x)
        assert plan.items == (txy_item("txy:", X, HELAB),)  # (Only what is needed, first group first.)
        deeper = store.room_plan(unit.pending_id, x_and_y)
        assert deeper.items == (txy_item("txy:", X, HELAB), txy_item("txy-seen:", Y, MATLAB))
        assert not store.adopt_pending(unit.pending_id, budget=x_and_y, budget_set_at=2.0, make_room=True,
                                       expected_room=list(plan.items)).adopted  # (Not what it was told: nothing.)
        adopted = store.adopt_pending(unit.pending_id, budget=x_and_y, budget_set_at=2.0, make_room=True,
                                      expected_room=list(deeper.items))
        assert adopted.adopted and adopted.removal is not None
        assert adopted.removal.txy_layers == ((X, HELAB),) and adopted.removal.txy_seen == ((Y, MATLAB),)
        assert set(store.txy_layers(Z).value or {}) == {MATLAB} and store.raw_rows(W).value  # (Later groups stay.)
        assert set(store.txy_layers(RUN).value or {}) == {MATLAB}


def test_trim_follows_make_rooms_order_and_says_what_it_removed(tmp_path: Path) -> None:
    with v4(tmp_path) as store:
        five_groups(store)
        options = {"directory": store.root}
        x_bytes = sum(row.bytes for row in (store.txy_layers(X).value or {}).values())
        budget = store.usage() - x_bytes + 10
    events: list[Any] = []
    cache_admin(options, "trim", events.append, budget=budget)
    removed = [event for event in events if event["kind"] == "removed" and "txy" in event["kinds"]]
    assert removed and removed[0]["layers"] == [[X, HELAB]]
    with CacheStore(options["directory"]) as store:
        assert store.txy_layers(X).value == {} and store.txy_layers(Y).value and store.raw_rows(W).value


def test_trim_keeps_only_copies_unless_its_plan_names_them(tmp_path: Path) -> None:
    """S2-1 (Assay): lowering the budget takes datasets and layers in Make room's order, but an only copy (here
    Z's MATLAB layer, its files gone) only when the plan the user was shown names it; a plan that changed
    since removes nothing."""
    with v4(tmp_path) as store:
        five_groups(store)
        options = {"directory": store.root}
    events: list[Any] = []
    cache_admin(options, "trim", events.append, budget=1, plan_only=True)
    items = events[-1]["items"]
    assert items[-1] == txy_item("txy-only:", Z, MATLAB) and txy_item("txy:", X, HELAB) in items
    with CacheStore(options["directory"]) as store:
        assert store.txy_layers(Z).value  # (Only a plan: nothing removed.)
    events.clear()
    cache_admin(options, "trim", events.append, budget=1)  # (No plan: everything but only copies.)
    with CacheStore(options["directory"]) as store:
        assert store.txy_layers(Z).value and not store.txy_layers(X).value and not store.raw_rows(W).value
        plan = store.trim_plan(1)
        assert plan.items == (txy_item("txy-only:", Z, MATLAB),)
        assert store.trim(1, expected=["something else"]).txy_only == ()  # (Not what was shown.)
        assert store.txy_layers(Z).value
        assert store.trim(1, expected=list(plan.items)).txy_only == ((Z, MATLAB),)
        assert store.txy_layers(Z).value == {}


# Clear

def test_clear_takes_txy_layers_everywhere_it_joins(tmp_path: Path) -> None:
    with v4(tmp_path) as store:
        for path in (RUN, X):
            save(store, path, part(store, MATLAB, {1: 10}), shots={1: 10})
        options = {"directory": store.root}
    events: list[Any] = []
    cache_admin(options, "clear_txy", events.append, paths=[RUN])
    assert events[0]["kinds"] == ["txy"] and events[0]["paths"] == [RUN]
    with CacheStore(options["directory"]) as store:
        assert store.txy_layers(RUN).value == {} and store.read_view(RUN, "", "").missing and store.txy_layers(X).value
    events.clear()
    cache_admin(options, "clear", events.append)  # (Clear all: every kind, raw and TXY too.)
    assert any(event["kind"] == "removed" and event["kinds"] == ["txy"] for event in events)
    with CacheStore(options["directory"]) as store:
        assert store.txy_layers(X).value == {} and store.inventory()["txy"]["layers"] == 0
        save(store, RUN, part(store, MATLAB, {1: 10}))
        save(store, X, part(store, MATLAB, {1: 10}))
        store.mark_txy_seen(X, {"matlab": {}}, later())  # (X's files are gone: its layer is the only copy.)
        removal = store.clear_root(A)
        assert {pair for pair in removal.txy_seen} == {(RUN, MATLAB), (X, MATLAB)}
        save(store, RUN, part(store, MATLAB, {1: 10}))
        save(store, X, part(store, MATLAB, {1: 10}))
        store.mark_txy_seen(X, {"matlab": {}}, later())
        _, flagged = store.set_prefs_removing(X, True, False, 6.0, remove_cached=True)
        assert flagged is not None and flagged.txy_seen == () and store.txy_layers(X).value  # (Only copy stays.)
        _, flagged = store.set_prefs_removing(RUN, True, False, 6.0, remove_cached=True)
        assert flagged is not None and flagged.txy_seen == ((RUN, MATLAB),)


# The sweep, the re-key, the migration, a cache move

def test_the_sweep_keeps_named_segments_and_deletes_old_unnamed_ones(tmp_path: Path) -> None:
    with v4(tmp_path) as store:
        kept = part(store, MATLAB, {1: 10})
        save(store, RUN, kept)
        orphan = store.write_txy_file(txy_layer.pack_segment({1: hits(1, 3)}, layer=MATLAB))
        young = store.write_txy_file(txy_layer.pack_segment({1: hits(1, 3)}, layer=MATLAB))
        old = time.time() - cache_store.ORPHAN_MIN_AGE - 10
        os.utime(store._store_file(orphan), (old, old))
        store.sweep()
        assert not os.path.exists(store._store_file(orphan)) and os.path.exists(store._store_file(young))
        assert os.path.exists(store._store_file(kept.file)) and store.inventory()["orphans"]["count"] == 1


def test_a_nested_roots_rekey_moves_raw_and_txy_layers(tmp_path: Path) -> None:
    """S2-0: stage 1's ``rekey_subtree`` left raw layers under the old key (unused, counted)."""
    old, new = f"root://{A}/top", "root://bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    with v4(tmp_path) as store:
        store.save_raw_batch(f"{old}/run", [raw_entry(store, 1, 50)], store.start_raw_job(f"{old}/run"))
        save(store, f"{old}/run", part(store, MATLAB, {1: 10}), shots={1: 10})
        store.set_cache_policy(f"{old}/run", "txy", 3.0)
        moved = store.rekey_subtree(old, new)
        assert f"{old}/run" in moved
        assert store.raw_rows(f"{new}/run").value and store.raw_rows(f"{old}/run").value == {}
        assert store.txy_layers(f"{new}/run").value and store.read_view(f"{new}/run", "", "").found
        assert len(store.read_txy_shots(f"{new}/run", MATLAB).value or {}) == 1
        assert store.read_folder_choices([f"{new}/run"])[f"{new}/run"].value["policy"] == "txy"  # type: ignore[index]


def test_a_store_v4_from_stage_1_gets_stage_2s_tables(tmp_path: Path) -> None:
    root = tmp_path / "caches" / "store-v4"
    with CacheStore(str(root)):
        pass
    conn = sqlite3.connect(root / "records.sqlite")
    for table in ("txy_layers", "txy_segments", "txy_views", "cache_policy", "txy_source_prefs"):
        conn.execute(f"DROP TABLE {table}")
    conn.execute("ALTER TABLE pending_saves DROP COLUMN parts")
    conn.execute("DELETE FROM meta WHERE key = 'gen_txy'")
    conn.commit()
    conn.close()
    with CacheStore(str(root)) as store:
        assert store._meta()["gen_txy"] == 0 and store._pending_parts
        assert save(store, RUN, part(store, MATLAB, {1: 10})).saved == (MATLAB,)
    conn = sqlite3.connect(root / "records.sqlite")  # (One migrated before a layer's last sighting, S2-2.)
    conn.execute("ALTER TABLE txy_layers DROP COLUMN seen_at")
    conn.commit()
    conn.close()
    with CacheStore(str(root)) as store:
        assert "seen_at" in {row[1] for row in store._conn.execute("PRAGMA table_info(txy_layers)")}
        assert store.mark_txy_seen(RUN, {"matlab": {}}, later()) == 1


def test_mark_seen_makes_a_layer_an_only_copy_and_back(tmp_path: Path) -> None:
    with v4(tmp_path) as store:
        save(store, RUN, part(store, MATLAB, {1: 10, 2: 10}))
        gone_at = later()
        assert store.mark_txy_seen(RUN, {"matlab": {1: (1001, MTIME)}}, gone_at) == 1
        assert (store.txy_layers(RUN).value or {})[MATLAB].gone_at == gone_at
        assert store.inventory()["txy"]["only_copy"] == 1
        assert store.mark_txy_seen(RUN, {"matlab": {1: (1001, MTIME), 2: (1002, MTIME)}}, gone_at + 1) == 0
        assert (store.txy_layers(RUN).value or {})[MATLAB].gone_at is None


def test_an_older_listing_landing_late_undoes_no_mark(tmp_path: Path) -> None:
    """S2-2 (Assay): C2-10's rule for layers. A listing that found a source gone, then a slower one that
    started earlier and saw it: the layer stays an only copy (else Make room would name it "seen"); and the
    other way, an older listing that missed a file doesn't mark gone a layer a newer one saw."""
    with v4(tmp_path) as store:
        save(store, RUN, part(store, MATLAB, {1: 10}))
        newer = later()
        assert store.mark_txy_seen(RUN, {"matlab": {}}, newer) == 1
        store.mark_txy_seen(RUN, {"matlab": {1: (1001, MTIME)}}, newer - 50)  # (Older, lands late.)
        assert (store.txy_layers(RUN).value or {})[MATLAB].gone_at == newer
        save(store, X, part(store, MATLAB, {1: 10}))
        store.mark_txy_seen(X, {"matlab": {1: (1001, MTIME)}}, newer)
        assert store.mark_txy_seen(X, {"matlab": {}}, newer - 50) == 0  # (Older than the last sighting.)
        assert (store.txy_layers(X).value or {})[MATLAB].gone_at is None


def test_a_cache_move_verifies_txy_segments(tmp_path: Path) -> None:
    caches, app, target = tmp_path / "caches", tmp_path / "app", tmp_path / "moved" / "caches"
    with v4(tmp_path) as store:
        held = part(store, MATLAB, {1: 10})
        save(store, RUN, held)
        store_id = store.store_id
    record = cache_move.start(str(caches), str(target), str(app), COPY)
    record = cache_move.move(record, str(app), lambda done, total: None, lambda: False)
    assert cache_move.verify(str(target), store_id, record["store_ids"]) == ""
    (target / "store-v4" / held.file).write_bytes(b"cut")
    assert cache_move.verify(str(target), store_id, record["store_ids"]) != ""


def test_store_v3_has_no_txy_layers(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "store-v3")) as store:
        assert store.txy_layers(RUN).missing and store.read_view(RUN, "", "").missing
        assert store.remove_txy() == cache_store.TxyRemoval(None, 0, 0)
        assert store.read_folder_choices([RUN])[RUN].missing
        with pytest.raises(cache_store.StoreError):
            store.start_txy_job(RUN)
    assert store_v4.DEFAULT_POLICY == "raw+used"


def test_a_new_layer_is_first_seen_when_its_job_listed(tmp_path: Path) -> None:
    """S2-3 (Assay, C2-11's class): a load lists at t0 and saves later; a listing between them that found the
    TXY gone lands after the save. It still makes the new layer an only copy (its first sighting is t0, not
    the save's time)."""
    with v4(tmp_path) as store:
        listed = time.time() - 100
        store.save_txy(RUN, "", "", [part(store, MATLAB, {1: 10})], None, store.start_txy_job(RUN), seen_at=listed)
        assert store.mark_txy_seen(RUN, {"matlab": {}}, listed + 50) == 1
        assert (store.txy_layers(RUN).value or {})[MATLAB].gone_at == listed + 50


def test_a_clear_of_the_folders_datasets_fences_its_layer_saves(tmp_path: Path) -> None:
    """Assay's note for step 3: a load may seed layers from the folder's store-v4 datasets (Q45.4); a Clear of
    them since the job started (for the folder, or every dataset) must stop its save."""
    with v4(tmp_path) as store:
        for selected in ([RUN], None):  # (The folder's datasets, then every one.)
            guard = store.start_txy_job(RUN)
            late = part(store, MATLAB, {1: 10})
            store.remove(("datasets",), selected)
            with pytest.raises(SaveRejected):
                store.save_txy(RUN, "", "", [late], None, guard)
            assert late.file in retired(store)
        assert save(store, RUN, part(store, MATLAB, {1: 10})).saved == (MATLAB,)  # (A job after the Clear saves.)


def test_a_layers_txy_entries_count_only_their_own_layers_txy(tmp_path: Path) -> None:
    """C-2 (PR #11's review): a shot's TXY of one source is no copy of another layer's entry. HeLab's TXY of
    shot 1 leaves the MATLAB layer, whose TXY is gone, the only copy, and the other way round; raw-keyed
    entries go by the raw files."""
    with v4(tmp_path) as store:
        save(store, RUN, part(store, MATLAB, {1: 10}))
        save(store, RUN, part(store, HELAB, {1: 10}))
        save(store, X, part(store, HELAB, {1: 10}, kind="raw"))
        seen = later()
        assert store.mark_txy_seen(RUN, {"raw": {1: (1, 1)}, HELAB: {1: (1001, MTIME)}}, seen) == 1
        layers = store.txy_layers(RUN).value or {}
        assert layers[MATLAB].gone_at == seen and layers[HELAB].gone_at is None
        assert store.mark_txy_seen(RUN, {MATLAB: {1: (1001, MTIME)}}, seen + 1) == 1
        layers = store.txy_layers(RUN).value or {}
        assert layers[MATLAB].gone_at is None and layers[HELAB].gone_at == seen + 1
        assert store.mark_txy_seen(X, {"raw": {1: (1, 1)}}, seen) == 0  # (Raw-keyed: its raw file is there.)
        assert store.mark_txy_seen(X, {HELAB: {1: (1, 1)}}, seen + 1) == 1  # (Its raw file gone: HeLab's TXY isn't it.)
