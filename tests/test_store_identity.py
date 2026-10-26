"""One store identity for presets and saved results (``FolderCache.store_answer``, Gauge's rounds
10-11): the cache folder decides. An answer from a store other than the one in use waits, with
every answer naming a store, for an identity probe of the folder; the store it finds is the one in
use, the answers of that store then count and the others are stale. Whatever order helpers answer
in, and whichever store the folder holds, nothing of the other store stays: no preset row, waiting
question, folder count, disk usage or "saved in disk cache". Writes name their store; a cache move
keeps it."""
from __future__ import annotations

import itertools
import shutil
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest
from pytestqt.qtbot import QtBot

from conftest import store_free
from helab.utils.cache_store import CacheStore
from helab.utils.folder_cache import FolderCache, get_folder_cache, store_options
from helab.utils.io_service import IORequest, IOService
from test_result_cache_store import find, options, save_through_helper

RUN = FolderCache.key("/data/root/run")
A, B = "a-store", "b-store"
FULL = 8 << 30  # A's usage: the whole disk budget (finding 3: it must never make B look full).
GUARD = {"generations": {"results": 0}, "epochs": {}}


@pytest.fixture
def cache() -> Iterator[FolderCache]:
    """A cache whose helpers never run: the test sends their events, in the order it chooses."""
    service = IOService()
    service.timer.stop()
    service._dispatch = lambda: None  # type: ignore[method-assign]
    yield FolderCache(service)
    service.shutdown()


def newest(cache: FolderCache, operation: str, action: str = "") -> IORequest:
    return next(request for request in reversed(cache.service.pending) if request.operation == operation
                and (not action or request.payload.get("action") == action))


def send(cache: FolderCache, request: IORequest, *events: dict[str, Any]) -> None:
    for event in events:
        cache.service.resultReady.emit(request, event)
    if request in cache.service.pending:
        cache.service.pending.remove(request)


def probes(cache: FolderCache) -> list[IORequest]:
    return [r for r in cache.service.pending if r.operation == "cache_admin" and r.payload["action"] == "identity"]


def folder(cache: FolderCache, store: str) -> None:
    """The cache folder holds ``store``: every identity probe out (and those they start) says so."""
    for _ in range(10):
        out = probes(cache)
        if not out:
            return
        send(cache, out[0], {"kind": "admin_result", "action": "identity", "store": store}, {"kind": "done"})
    raise AssertionError("probes keep starting")


def folder_fails(cache: FolderCache, times: int = 1) -> None:
    """Identity probes out fail (the store couldn't be opened, say), ``times`` in a row at most."""
    for _ in range(times):
        out = probes(cache)
        if not out:
            return
        send(cache, out[0], {"kind": "error", "message": "disk I/O error"})


def presets_job(cache: FolderCache) -> IORequest:
    """A presets read in flight (as ``read_presets`` starts one)."""
    owner = cache.cache_admin("presets", rows=[], store="")
    cache._preset_jobs[owner] = {}
    return newest(cache, "cache_admin", "presets")


def inventory_job(cache: FolderCache) -> IORequest:
    assert cache.cache_admin("inventory")
    return newest(cache, "cache_admin", "inventory")


def usage(store: str) -> dict[str, Any]:
    return {"usage": FULL if store == A else 1, "usage_seq": [store, 5], "store": store}


Answer = Callable[[], None]


def answer_of(cache: FolderCache, store: str, kind: str, tag: str) -> Answer:
    """``store``'s answer of ``kind``: its request made now, the answer sent when the returned call
    runs. ``tag`` names what it holds (a preset row, a waiting result) to find it again."""
    found = {"kind": "result_found", "artifact": "", "exact": True, "record": {}, "computed_at": 1.0, "bytes": 1,
             "result_id": f"r{tag}", "guard": {**GUARD, "store": store}, "store": store}
    if kind in ("found", "missing"):
        request = (cache.find_result(f"result-find:{tag}", RUN, "k1", "f1"), newest(cache, "result_find"))[1]
        event = found if kind == "found" else {"kind": "result_missing", "guard": {**GUARD, "store": store},
                                               "store": store}
        return lambda: send(cache, request, event, {"kind": "done"})
    if kind in ("saved", "not_saved", "pending"):
        assert cache.save_result(f"result-save:{tag}", RUN, b"x", lookup="k1", family="f1", record={},
                                 analysis_id="a", action="Plot", computed_at=1.0, guard=GUARD)
        request = newest(cache, "result_save")
        events = {"saved": {"kind": "result_saved", "bytes": 1, "result_id": f"r{tag}", **usage(store)},
                  "not_saved": {"kind": "result_not_saved", "reason": "store_replaced", "message": "", "bytes": 1,
                                "budget": None, **usage(store)},
                  "pending": {"kind": "result_pending", "pending_id": f"p{tag}", "path": RUN, "label": "x",
                              "bytes": 1, "budget": 1, "room": None, **usage(store)}}
        return lambda: send(cache, request, events[kind], {"kind": "done"})
    if kind.startswith("adopt"):
        pending = f"p{tag}"
        cache.pending_results[pending] = {"pending_id": pending, "path": RUN, "result": True, "store": store,
                                          "room": {"ids": ["old"]}}
        assert cache.cache_admin("adopt_result", pending_id=pending, make_room=True, room_ids=[])
        request = newest(cache, "cache_admin", "adopt_result")
        assert request.payload["params"]["store"] == store  # Make room in the store it waits in.
        result = {"adopted": True, "path": RUN, "bytes": 1, "room": None, "result_id": f"r{tag}"} if kind == "adopted" \
            else {"adopted": False, "rejected": "gone", "message": "gone"} if kind == "adopt_failed" \
            else {"adopted": False, "path": RUN, "bytes": 1, "room": {"ids": [f"new{tag}"]}}
        return lambda: send(cache, request, {"kind": "admin_result", "action": "adopt_result", **result,
                                             **usage(store)}, {"kind": "done"})
    if kind == "presets_ack":
        # The user's change, written to the store whose names are known: its answer acknowledges it.
        # (At a fresh start, as if they were known: a write of its own, not behind a read.)
        cache.presets_read = True
        cache.set_presets([("arrangement", "", f"owed-{tag}", "{}")])
        request = newest(cache, "cache_admin", "presets")

        def acknowledge() -> None:
            rows = [dict(row) for row in request.payload["params"]["rows"]]
            send(cache, request, {"kind": "presets", "saved": rows, "rows": rows, "store": store}, {"kind": "done"})
        return acknowledge
    if kind == "presets":
        request = presets_job(cache)
        row = {"kind": "arrangement", "scope": "", "name": f"from-{tag}", "record": "{}", "set_at": 1.0}
        return lambda: send(cache, request, {"kind": "presets", "saved": [], "rows": [row], "store": store},
                            {"kind": "done"})
    if kind == "inventory":
        request = inventory_job(cache)
        waiting = {"pending_id": f"p{tag}", "path": RUN, "label": "x", "analysis_id": "a", "bytes": 1,
                   "created_at": 1.0}
        return lambda: send(cache, request, {"kind": "inventory", "inventory": {
            "pending": [], "pending_results": [waiting], "store_id": store, "usage": usage(store)["usage"],
            "usage_seq": [store, 5]}}, {"kind": "done"})
    if kind == "counts":
        return lambda: cache._note_result_counts({RUN: {"count": 1, "bytes": 1, "seq": [store, 9]}})
    assert kind == "usage"  # A load's measurement of the store (any helper's).
    return lambda: cache._note_usage(usage(store)["usage"], [store, 5])


A_KINDS = ("found", "missing", "saved", "not_saved", "pending", "adopted", "adopt_failed", "adopt_replanned",
           "presets", "presets_ack", "inventory", "counts", "usage")
OWED = ("arrangement", "", "owed-a")
B_KINDS = ("presets", "missing", "not_saved", "inventory", "counts")


class Timeline:
    """What the cache told plots and views, in order: "claim A" (a result said found or saved, a
    guard handed out, an adoption said saved), "dropped" (every saved result's mark dropped)."""

    def __init__(self, cache: FolderCache) -> None:
        self.marks: list[str] = []
        self.owner_store: dict[str, str] = {}
        cache.resultReady.connect(self._result)
        cache.resultPendingAnswered.connect(lambda pending_id, saved, result_id: self.marks.append(
            f"claim {result_id[1]}" if saved and result_id else ""))
        cache.cacheRemoved.connect(lambda paths, kinds: self.marks.append(
            "dropped" if paths is None and "results" in kinds else ""))

    def _result(self, request: IORequest, event: dict[str, Any]) -> None:
        kind = event.get("kind")
        tag = request.owner.rsplit(":", 1)[-1]
        if kind in ("result_found", "result_saved") or (kind == "result_missing" and event.get("guard")):
            self.marks.append(f"claim {tag}")

    def claims_left(self, loser: str) -> list[int]:
        """Claims of ``loser``'s answers not followed by a drop of the saved results' marks."""
        return [index for index, mark in enumerate(self.marks)
                if mark == f"claim {loser}" and "dropped" not in self.marks[index:]]


def nothing_of(cache: FolderCache, timeline: Timeline, store: str) -> None:
    """Nothing ``store`` (one the folder doesn't hold) said stays: its answers are tagged by its
    first letter ("a", "b")."""
    tag = store[0]
    assert ("arrangement", "", f"from-{tag}") not in cache.presets
    assert f"p{tag}" not in cache.pending_results
    assert all(entry.get("store") != store for entry in cache.pending_results.values())
    assert all(entry[2] is not None and entry[2][0] != store for entry in cache.result_counts.values())
    assert store != A or cache.disk_usage != FULL
    assert all(entry.get("room") != {"ids": [f"new{tag}"]} for entry in cache.pending_results.values())
    assert not timeline.claims_left(tag), timeline.marks


@pytest.mark.parametrize("start", ["fresh", "A in use"])
@pytest.mark.parametrize("a_kind,b_kind", list(itertools.product(A_KINDS, B_KINDS)))
@pytest.mark.parametrize("arrive", ["A then B", "B then A"])
@pytest.mark.parametrize("asked", ["A asked first", "B asked first"])
@pytest.mark.parametrize("first_probe", ["finds A", "fails", "fails, then recovers"])
def test_every_order_of_two_stores_answers_ends_on_the_store_the_folder_holds(
        cache: FolderCache, start: str, a_kind: str, b_kind: str, arrive: str, asked: str, first_probe: str) -> None:
    """The store is recreated (A → B) while HeLab runs. An answer of A's (each kind) and B's
    first answer (each kind), asked in either order and arriving in either order, after a fresh
    start or with A in use. The folder's first probe finds A still there (B's answer is from a
    helper that opened it later, say), or fails, and then a deliberate read answered by the store
    in use asks again and finds it (a recovery); then a later answer of B's starts another probe,
    which finds B. After each: the store in use is the folder's (a failed probe changes none),
    nothing of another store stays, nothing waits and quitting waits for nothing. After a failure
    nothing claims anything, the store in use's answers included, and a change owed then stays
    owed (in RAM) until a store takes it: it is never lost."""
    if start == "A in use":
        send(cache, presets_job(cache), {"kind": "presets", "saved": [], "rows": [], "store": A}, {"kind": "done"})
        assert cache._store == A
    timeline = Timeline(cache)
    if asked == "A asked first":
        old = answer_of(cache, A, a_kind, "a")
        new = answer_of(cache, B, b_kind, "b")
    else:
        new = answer_of(cache, B, b_kind, "b")
        old = answer_of(cache, A, a_kind, "a")
    for answer in ((old, new) if arrive == "A then B" else (new, old)):
        answer()
    if first_probe.startswith("fails"):
        in_use = cache._store
        owed = OWED in cache.presets_unsaved
        before = len(timeline.marks)
        folder_fails(cache)
        assert not probes(cache) and not cache._probe_waiting and not cache._probe_held
        assert cache._store == in_use and RUN not in cache.quit_saves()
        assert "Presets" not in cache.quit_saves() or cache._preset_jobs  # (Only a job still in flight.)
        assert not [mark for mark in timeline.marks[before:] if mark.startswith("claim")], timeline.marks
        assert not owed or (OWED in cache.presets_unsaved and OWED in cache.presets)  # Still owed, in RAM.
        if first_probe == "fails, then recovers":
            # A deliberate read (the Presets menu), answered by the store in use: asked again, found.
            send(cache, presets_job(cache), {"kind": "presets", "saved": [], "rows": [], "store": in_use},
                 {"kind": "done"})
            assert probes(cache)
            folder(cache, in_use)
            assert cache._store == in_use and not cache._store_unknown and not cache.presets_error
            if owed:  # Written now, to the store in use.
                write = newest(cache, "cache_admin", "presets")
                assert write.payload["params"]["store"] == in_use
                assert "owed-a" in [row["name"] for row in write.payload["params"]["rows"]]
        if in_use == B:
            return  # (B came first and is in use: B's next answer counts.)
        nothing_of(cache, timeline, B)
    else:
        folder(cache, A)
        assert cache._store == A and not probes(cache) and not cache._probe_waiting
        nothing_of(cache, timeline, B)
    # B's next answer: the folder is asked again, and holds B now.
    owed = OWED in cache.presets_unsaved
    send(cache, presets_job(cache), {"kind": "presets", "saved": [], "rows": [], "store": B}, {"kind": "done"})
    folder(cache, B)
    assert cache._store == B and not probes(cache) and not cache._probe_waiting
    nothing_of(cache, timeline, A)
    assert not owed or OWED in cache.presets  # A change still owed is kept for B, never lost.


def test_answers_of_the_folders_store_that_waited_count_once_it_has_answered(cache: FolderCache) -> None:
    """Finding 2: B's inventory, asked first and answered while A was in use, waits for the probe
    and is applied once the folder holds B: B's waiting result is asked, A's isn't."""
    send(cache, presets_job(cache), {"kind": "presets", "saved": [], "rows": [], "store": A}, {"kind": "done"})
    b_first, a_second = inventory_job(cache), inventory_job(cache)
    send(cache, a_second, {"kind": "inventory", "inventory": {"pending": [], "pending_results": [
        {"pending_id": "pa", "path": RUN, "label": "x", "analysis_id": "a", "bytes": 1, "created_at": 1.0}],
        "store_id": A}}, {"kind": "done"})
    send(cache, b_first, {"kind": "inventory", "inventory": {"pending": [], "pending_results": [
        {"pending_id": "pb", "path": RUN, "label": "x", "analysis_id": "a", "bytes": 1, "created_at": 1.0}],
        "store_id": B}}, {"kind": "done"})
    assert probes(cache) and "pb" not in cache.pending_results  # Waiting for the folder.
    folder(cache, B)
    assert cache._store == B and set(cache.pending_results) == {"pb"}
    assert cache.pending_results["pb"]["store"] == B


def test_writes_wait_for_the_probe_and_then_go(cache: FolderCache) -> None:
    """While the folder is asked, a result save, Make room and presets reads and writes wait (quit
    waits for them); then they go, to the store the folder holds."""
    send(cache, presets_job(cache), {"kind": "presets", "saved": [], "rows": [], "store": A}, {"kind": "done"})
    cache.presets_read = True
    cache._note_usage(1, [B, 1])  # Another store answers: the folder is asked.
    assert probes(cache)
    before = len(cache.service.pending)
    assert cache.save_result("result-save:w", RUN, b"x", lookup="k1", family="f1", record={}, analysis_id="a",
                             action="Plot", computed_at=1.0, guard=GUARD)
    cache.set_presets([("arrangement", "", "desk", "{}")])
    assert len(cache.service.pending) == before  # Held.
    assert RUN in cache.quit_saves() and "Presets" in cache.quit_saves()
    folder(cache, B)
    operations = [(r.operation, r.payload.get("action")) for r in cache.service.pending]
    assert ("result_save", "Plot") in operations and ("cache_admin", "presets") in operations
    read = newest(cache, "cache_admin", "presets")
    assert read.payload["params"]["store"] == B and read.payload["params"]["rows"] == []  # (B's names: read first.)


def test_a_probe_that_fails_changes_nothing_and_ends_the_wait(cache: FolderCache) -> None:
    send(cache, presets_job(cache), {"kind": "presets", "saved": [], "rows": [], "store": A}, {"kind": "done"})
    cache._note_usage(1, [B, 1])
    [probe] = probes(cache)
    send(cache, probe, {"kind": "error", "message": "disk I/O error"})
    assert cache._store == A and not cache._probe_owner and not probes(cache)


def test_a_store_in_the_folder_whatever_its_age_ends_quit(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    """Finding 1, through the helpers: presets read from store A; the store is recreated as B
    (whatever its id or creation time: neither is compared) while a preset change is owed; quit
    waits only until the folder has said B and the change is saved there, then ends."""
    service = IOService()
    try:
        cache = get_folder_cache(service)
        cache.read_presets()
        qtbot.waitUntil(lambda: cache.presets_read and not cache._preset_jobs and store_free(service),
                        timeout=30_000)  # (Windows deletes no open file.)
        first = cache._store
        directory = store_options()["directory"]
        shutil.rmtree(directory)
        with CacheStore(directory) as store:
            replacement = store.store_id
        assert replacement != first
        cache.set_presets([("arrangement", "", "desk", '"mine"')])  # Written to A by name: B refuses it.
        cache.cancel_for_quit()
        qtbot.waitUntil(lambda: cache.quit_saves() == [], timeout=30_000)
        assert cache._store == replacement and not cache.presets_unsaved
        with CacheStore(directory) as store:
            rows = store.read_presets().value or []
        assert [(row["name"], row["record"]) for row in rows] == [("desk", '"mine"')]
    finally:
        service.shutdown()


def test_a_moved_store_keeps_its_identity(tmp_path: Path, cache: FolderCache) -> None:
    """A cache move goes only to an empty or new folder, by a rename or a verified copy: the store
    there is the same (its id), so it stays in use and nothing starts afresh."""
    source, target = tmp_path / "caches" / "store-v3", tmp_path / "moved" / "store-v3"
    with CacheStore(str(source)) as store:
        identity = store.store_id
    shutil.copytree(source, target)
    with CacheStore(str(target)) as store:
        assert store.store_id == identity
    dropped: list[Any] = []
    cache.cacheRemoved.connect(lambda paths, kinds: dropped.append(kinds))
    assert cache.store_answer(identity)
    cache.presets[("arrangement", "", "kept")] = {"record": "{}", "set_at": 1.0}
    assert cache.store_answer(identity)  # The moved store answering.
    assert dropped == [] and not probes(cache) and ("arrangement", "", "kept") in cache.presets


def test_a_guard_taken_in_a_store_saves_nothing_in_the_one_recreated_there(tmp_path: Path) -> None:
    """Round 10's finding 1, through the helpers: a running plot's guard from A (its lookup found
    nothing); the store recreated as B at the same folder; the save with A's guard writes nothing."""
    folder_path = tmp_path / "run"
    folder_path.mkdir()
    cache_options = options(tmp_path)
    missing = find(tmp_path, folder_path, cache_options)[-1]
    assert missing["kind"] == "result_missing" and missing["guard"]["store"] == missing["store"]
    shutil.rmtree(cache_options["directory"])
    with CacheStore(cache_options["directory"]) as store:
        assert store.store_id != missing["store"]
    events = save_through_helper(tmp_path, folder_path, cache_options, missing["guard"])
    assert events[-1]["kind"] == "result_not_saved" and events[-1]["reason"] == "store_replaced"
    with CacheStore(cache_options["directory"]) as store:
        assert store._conn.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 0
    guard = find(tmp_path, folder_path, cache_options)[-1]["guard"]
    assert save_through_helper(tmp_path, folder_path, cache_options, guard)[-1]["kind"] == "result_saved"


def test_views_hear_when_a_store_change_learned_through_results_makes_preset_names_unknown(
        cache: FolderCache) -> None:
    """Finding 5: presets read from A; a result answer from B starts the probe, which finds B: the
    presets views are told (``presetsChanged``), since the names they show are no longer known."""
    row = {"kind": "arrangement", "scope": "", "name": "desk", "record": "{}", "set_at": 1.0}
    send(cache, presets_job(cache), {"kind": "presets", "saved": [], "rows": [row], "store": A}, {"kind": "done"})
    assert cache.presets_read and cache.preset_records("arrangement")
    told: list[bool] = []
    cache.presetsChanged.connect(lambda: told.append(cache.presets_read))
    answer_of(cache, B, "missing", "b")()
    assert not told  # (Waiting for the folder: nothing is said yet.)
    folder(cache, B)
    assert told and told[0] is False and not cache.presets_read and not cache.preset_records("arrangement")


def owed_change_with_a_disagreement(cache: FolderCache) -> None:
    """Presets read from A; the user saves a preset (its write named A, in flight); B answers it
    (the helper opened B): the folder is asked."""
    send(cache, presets_job(cache), {"kind": "presets", "saved": [], "rows": [], "store": A}, {"kind": "done"})
    cache.set_presets([("arrangement", "", "desk", "{}")])
    write = newest(cache, "cache_admin", "presets")
    assert write.payload["params"]["store"] == A
    send(cache, write, {"kind": "presets", "saved": [], "rows": [], "store": B}, {"kind": "done"})
    assert probes(cache)


def test_failed_probes_with_an_owed_change_end_quit_and_a_later_success_writes_it(cache: FolderCache) -> None:
    """Gauge's round-12 repro 1: five probes fail in a row while a preset change is owed. Nothing
    re-reads by itself and quitting waits for nothing: the change is said not saved (kept in RAM).
    A deliberate read (the Presets menu) asks again; this time the folder says B, and the change
    is written there."""
    owed_change_with_a_disagreement(cache)
    for attempt in range(5):
        folder_fails(cache)
        assert not probes(cache) and not [r for r in cache.service.pending if r.operation == "cache_admin"
                                          and r.payload["action"] == "presets"]  # Nothing re-reads.
        assert cache.quit_saves() == [] and not cache.presets_saving()
        why = cache.preset_unsaved("arrangement", "", "desk")
        assert why.startswith("couldn't be saved (the disk cache's store couldn't be confirmed")
        assert cache.presets_note().startswith("⚠ Saved presets can't be read: the disk cache's store")
        if attempt < 4:
            cache.read_presets()  # Opening the Presets menu: tries again…
            read = newest(cache, "cache_admin", "presets")
            send(cache, read, {"kind": "presets", "saved": [], "rows": [], "store": B}, {"kind": "done"})
            assert probes(cache)  # …which asks the folder once more (one probe, never a chain).
    cache.read_presets()
    send(cache, newest(cache, "cache_admin", "presets"), {"kind": "presets", "saved": [], "rows": [], "store": B},
         {"kind": "done"})
    folder(cache, B)
    write = newest(cache, "cache_admin", "presets")
    assert write.payload["params"]["store"] == B and [row["name"] for row in write.payload["params"]["rows"]] == [
        "desk"]
    saved = dict(write.payload["params"]["rows"][0])
    send(cache, write, {"kind": "presets", "saved": [saved], "rows": [saved], "store": B}, {"kind": "done"})
    assert not cache.presets_unsaved and cache.quit_saves() == [] and cache._store == B


def test_a_failed_probe_ends_held_writes_not_saved(cache: FolderCache) -> None:
    """Held result saves and Make room end as not saved (the store unknown); quit waits for none."""
    send(cache, presets_job(cache), {"kind": "presets", "saved": [], "rows": [], "store": A}, {"kind": "done"})
    cache._note_usage(1, [B, 1])
    ended: list[tuple[str, str]] = []
    cache.resultReady.connect(lambda request, event: ended.append((request.owner, event["kind"])))
    assert cache.save_result("result-save:h", RUN, b"x", lookup="k1", family="f1", record={}, analysis_id="a",
                             action="Plot", computed_at=1.0, guard=GUARD)
    assert RUN in cache.quit_saves()
    folder_fails(cache)
    assert ("result-save:h", "error") in ended and cache.quit_saves() == []
    assert not [r for r in cache.service.pending if r.operation == "result_save"]


def test_cancelling_a_held_save_drops_it(cache: FolderCache) -> None:
    """Gauge's repro 2b: ``cancel(owner)`` reaches a write held for the probe: it ends cancelled
    and is never submitted."""
    send(cache, presets_job(cache), {"kind": "presets", "saved": [], "rows": [], "store": A}, {"kind": "done"})
    cache._note_usage(1, [B, 1])
    ended: list[str] = []
    cache.resultReady.connect(lambda request, event: ended.append(event["kind"]))
    assert cache.save_result("result-save:c", RUN, b"x", lookup="k1", family="f1", record={}, analysis_id="a",
                             action="Plot", computed_at=1.0, guard=GUARD)
    cache.cancel("result-save:c")
    assert ended == ["cancelled"] and not cache._probe_held and cache.quit_saves() == []
    folder(cache, B)
    assert not [r for r in cache.service.pending if r.operation == "result_save"]


def test_shutting_down_during_a_hold_launches_nothing() -> None:
    """Gauge's repro 2a: shutdown while writes are held. They end cancelled before the service
    cancels the probe, whose end then submits nothing."""
    service = IOService()
    service.timer.stop()
    service._dispatch = lambda: None  # type: ignore[method-assign]
    cache = FolderCache(service)
    service.folder_cache = cache
    send(cache, presets_job(cache), {"kind": "presets", "saved": [], "rows": [], "store": A}, {"kind": "done"})
    cache._note_usage(1, [B, 1])
    assert cache.save_result("result-save:s", RUN, b"x", lookup="k1", family="f1", record={}, analysis_id="a",
                             action="Plot", computed_at=1.0, guard=GUARD)
    cache.set_presets([("arrangement", "", "desk", "{}")])
    submitted: list[str] = []
    real_submit = service.submit

    def submit(*args: Any, **kwargs: Any) -> bool:
        submitted.append(str(args[3]))
        return real_submit(*args, **kwargs)
    service.submit = submit  # type: ignore[method-assign]
    service.shutdown()
    assert submitted == [] and not cache._probe_held and not cache._probe_owner


def test_after_a_failed_probe_the_old_stores_acknowledgement_never_clears_an_owed_change(cache: FolderCache) -> None:
    """Gauge's round-13 repro 1: A in use; the user's change is written to A; B answers something
    (the folder is asked) and A's acknowledgement waits; the probe fails. A's acknowledgement is
    stale: the change stays owed (said not saved). Later B is confirmed: the change is written to B."""
    send(cache, presets_job(cache), {"kind": "presets", "saved": [], "rows": [], "store": A}, {"kind": "done"})
    cache.set_presets([("arrangement", "", "desk", "{}")])
    to_a = newest(cache, "cache_admin", "presets")
    answer_of(cache, B, "missing", "b")()
    assert probes(cache)
    rows = [dict(row) for row in to_a.payload["params"]["rows"]]
    send(cache, to_a, {"kind": "presets", "saved": rows, "rows": rows, "store": A}, {"kind": "done"})
    folder_fails(cache)
    assert cache.preset_unsaved("arrangement", "", "desk").startswith("couldn't be saved")
    assert cache.quit_saves() == []
    cache.read_presets()  # The Presets menu.
    send(cache, newest(cache, "cache_admin", "presets"), {"kind": "presets", "saved": [], "rows": [], "store": B},
         {"kind": "done"})
    folder(cache, B)
    write = newest(cache, "cache_admin", "presets")
    assert write.payload["params"]["store"] == B and [r["name"] for r in write.payload["params"]["rows"]] == ["desk"]


def test_after_a_failed_probe_the_store_in_uses_saved_result_is_not_saved(cache: FolderCache) -> None:
    """Repro 1b: a result save's answer from A (in use) that waited for a probe that failed: not
    saved, never "saved in disk cache"."""
    send(cache, presets_job(cache), {"kind": "presets", "saved": [], "rows": [], "store": A}, {"kind": "done"})
    seen: list[str] = []
    cache.resultReady.connect(lambda request, event: seen.append(str(event["kind"])))
    saved = answer_of(cache, A, "saved", "a")
    answer_of(cache, B, "missing", "b")()
    saved()
    folder_fails(cache)
    assert "result_saved" not in seen and "result_not_saved" in seen


def test_a_deliberate_read_answered_by_the_store_in_use_while_unknown_recovers(cache: FolderCache) -> None:
    """Repro 1c: with the store unknown, a deliberate read answered by A (in use) asks the folder;
    it holds A: the unknown state ends, the note clears and the owed change is written to A."""
    send(cache, presets_job(cache), {"kind": "presets", "saved": [], "rows": [], "store": A}, {"kind": "done"})
    answer_of(cache, B, "missing", "b")()
    folder_fails(cache)
    cache.set_presets([("arrangement", "", "desk", "{}")])  # Owed (written to A: its answer asks the folder).
    write = newest(cache, "cache_admin", "presets")
    assert cache.presets_note().startswith("⚠ Saved presets can't be read")
    rows = [dict(row) for row in write.payload["params"]["rows"]]
    send(cache, write, {"kind": "presets", "saved": rows, "rows": rows, "store": A}, {"kind": "done"})
    assert probes(cache) and ("arrangement", "", "desk") in cache.presets_unsaved  # (Not taken yet.)
    folder(cache, A)
    assert not cache._store_unknown and cache.presets_note() == "" and not cache.presets_unsaved


def test_a_probe_that_cant_be_asked_fails_the_same_way(cache: FolderCache, monkeypatch: pytest.MonkeyPatch) -> None:
    """Finding 2: the queue is full when the folder must be asked: the same failure state as a
    failed probe ("Saved presets can't be read: …", owed changes said not saved), no retry."""
    send(cache, presets_job(cache), {"kind": "presets", "saved": [], "rows": [], "store": A}, {"kind": "done"})
    cache.set_presets([("arrangement", "", "desk", "{}")])
    to_a = newest(cache, "cache_admin", "presets")
    admin = cache.cache_admin
    monkeypatch.setattr(cache, "cache_admin", lambda action, **params: "" if action == "identity"
                        else admin(action, **params))
    rows = [dict(row) for row in to_a.payload["params"]["rows"]]
    send(cache, to_a, {"kind": "presets", "saved": rows, "rows": rows, "store": B}, {"kind": "done"})
    assert not probes(cache) and cache._store_unknown == "HeLab's work queue is full"
    assert cache.presets_note() == ("⚠ Saved presets can't be read: the disk cache's store couldn't be confirmed "
                                    "(HeLab's work queue is full)")
    assert cache.preset_unsaved("arrangement", "", "desk").startswith("couldn't be saved")
    assert cache.quit_saves() == [] and not [r for r in cache.service.pending if r.operation == "cache_admin"
                                             and r.payload["action"] == "presets"]


def test_a_recovery_started_by_a_result_answer_clears_the_confirmation_note(cache: FolderCache) -> None:
    """Gauge's round-14 P3: the store unknown with no preset change owed; a plot's lookup answered
    by A (in use) asks the folder, which holds A: the "store couldn't be confirmed" note goes at
    once. A real error reading presets is a different note, and stays."""
    send(cache, presets_job(cache), {"kind": "presets", "saved": [], "rows": [], "store": A}, {"kind": "done"})
    answer_of(cache, B, "missing", "b")()
    folder_fails(cache)
    assert cache.presets_note().startswith("⚠ Saved presets can't be read: the disk cache's store")
    assert not cache.presets_unsaved
    answer_of(cache, A, "missing", "a")()
    assert probes(cache)
    folder(cache, A)
    assert not cache._store_unknown and cache.presets_note() == ""
    # Another failure, then a real read error, then a recovery: the read error stays.
    answer_of(cache, B, "missing", "b2")()
    folder_fails(cache)
    send(cache, presets_job(cache), {"kind": "presets", "saved": [], "error": "disk I/O error", "store": A},
         {"kind": "done"})
    folder(cache, A)
    assert cache.presets_note() == "⚠ Saved presets can't be read: disk I/O error"
