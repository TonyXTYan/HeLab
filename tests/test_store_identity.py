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
           "presets", "inventory", "counts", "usage")
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
def test_every_order_of_two_stores_answers_ends_on_the_store_the_folder_holds(
        cache: FolderCache, start: str, a_kind: str, b_kind: str, arrive: str, asked: str) -> None:
    """The store is recreated (A → B) while HeLab runs. An answer of A's (each kind) and B's
    first answer (each kind), asked in either order and arriving in either order, after a fresh
    start or with A in use. The folder's first probe finds A still there (B's answer is from a
    helper that opened it later, say), then a later answer of B's starts another probe, which
    finds B. After each: the folder's store is in use, nothing of the other one stays, and B's
    waiting result (its inventory) is kept once B is in use."""
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
    folder(cache, A)
    assert cache._store == A and not probes(cache) and not cache._probe_waiting
    nothing_of(cache, timeline, B)
    # B's next answer: the folder is asked again, and holds B now.
    send(cache, presets_job(cache), {"kind": "presets", "saved": [], "rows": [], "store": B}, {"kind": "done"})
    folder(cache, B)
    assert cache._store == B and not probes(cache) and not cache._probe_waiting
    nothing_of(cache, timeline, A)


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
        qtbot.waitUntil(lambda: cache.presets_read and not cache._preset_jobs, timeout=30_000)
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
