"""One store identity for presets and saved results (``FolderCache.store_answer``, Gauge's round 10):
a store recreated at the cache folder while HeLab runs sorts after the one it replaced by its
(``created_at``, ``store_id``), so whatever order helpers answer in, the newest store is the one in
use, and nothing an older one said stays: no preset row, waiting question, folder count or "saved
in disk cache". Writes name their store; a cache move keeps it."""
from __future__ import annotations

import itertools
import shutil
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

from helab.utils.cache_store import CacheStore
from helab.utils.folder_cache import FolderCache
from helab.utils.io_service import IORequest, IOService
from test_result_cache_store import find, options, save_through_helper

RUN = FolderCache.key("/data/root/run")
# Their ids sort the other way round from when they were made: the time decides.
A: dict[str, Any] = {"store": "zz-old", "store_created": 1_000.0}
B: dict[str, Any] = {"store": "aa-new", "store_created": 2_000.0}
GUARD = {"generations": {"results": 0}, "epochs": {}}


@pytest.fixture
def cache() -> Iterator[FolderCache]:
    """A cache whose helpers never run: the test sends their events, in the order it chooses."""
    service = IOService()
    service.timer.stop()
    service._dispatch = lambda: None  # type: ignore[method-assign]
    yield FolderCache(service)
    service.shutdown()


def newest(cache: FolderCache, operation: str) -> IORequest:
    return cache.service.pending[-1] if cache.service.pending[-1].operation == operation else next(
        request for request in reversed(cache.service.pending) if request.operation == operation)


def send(cache: FolderCache, request: IORequest, *events: dict[str, Any]) -> None:
    for event in events:
        cache.service.resultReady.emit(request, event)
    if request in cache.service.pending:
        cache.service.pending.remove(request)


def presets_job(cache: FolderCache) -> IORequest:
    """A presets read in flight (as ``read_presets`` starts one)."""
    owner = cache.cache_admin("presets", rows=[], store="")
    cache._preset_jobs[owner] = {}
    return newest(cache, "cache_admin")


def inventory_job(cache: FolderCache) -> IORequest:
    assert cache.cache_admin("inventory")
    return newest(cache, "cache_admin")


def find_job(cache: FolderCache, owner: str) -> IORequest:
    assert cache.find_result(owner, RUN, "k1", "f1")
    return newest(cache, "result_find")


def save_job(cache: FolderCache, owner: str) -> IORequest:
    assert cache.save_result(owner, RUN, b"x", lookup="k1", family="f1", record={}, analysis_id="a", action="Plot",
                             computed_at=1.0, guard=GUARD)
    return newest(cache, "result_save")


Answer = Callable[[], None]


def a_answer(cache: FolderCache, kind: str) -> Answer:
    """A's answer of ``kind``: its request made now, the answer sent when the returned call runs."""
    if kind == "found":
        request = find_job(cache, "result-find:a")
        return lambda: send(cache, request, {"kind": "result_found", "artifact": "", "exact": True, "record": {},
                                             "computed_at": 1.0, "bytes": 1, "result_id": "ra", "guard": GUARD, **A},
                            {"kind": "done"})
    if kind == "missing":
        request = find_job(cache, "result-find:a")
        return lambda: send(cache, request, {"kind": "result_missing", "guard": GUARD, **A}, {"kind": "done"})
    if kind == "saved":
        request = save_job(cache, "result-save:a")
        return lambda: send(cache, request, {"kind": "result_saved", "bytes": 1, "result_id": "ra", **A},
                            {"kind": "done"})
    if kind == "pending":
        request = save_job(cache, "result-save:a")
        return lambda: send(cache, request, {"kind": "result_pending", "pending_id": "pa", "path": RUN, "label": "x",
                                             "bytes": 1, "budget": 1, "room": None, **A}, {"kind": "done"})
    if kind == "adopted":
        cache.pending_results["pa"] = {"pending_id": "pa", "path": RUN, "result": True, "store": A["store"]}
        assert cache.cache_admin("adopt_result", pending_id="pa", make_room=True, room_ids=[])
        request = newest(cache, "cache_admin")
        assert request.payload["params"]["store"] == A["store"]  # Make room in the store it waits in.
        return lambda: send(cache, request, {"kind": "admin_result", "action": "adopt_result", "adopted": True,
                                             "path": RUN, "bytes": 1, "room": None, "result_id": "ra", **A},
                            {"kind": "done"})
    if kind == "presets":
        request = presets_job(cache)
        row = {"kind": "arrangement", "scope": "", "name": "from-a", "record": "{}", "set_at": 1.0}
        return lambda: send(cache, request, {"kind": "presets", "saved": [], "rows": [row], **A}, {"kind": "done"})
    if kind == "inventory":
        request = inventory_job(cache)
        waiting = {"pending_id": "pa", "path": RUN, "label": "x", "analysis_id": "a", "bytes": 1, "created_at": 1.0}
        return lambda: send(cache, request, {"kind": "inventory", "inventory": {
            "pending": [], "pending_results": [waiting], "store_id": A["store"], "store_created": A["store_created"]}},
            {"kind": "done"})
    assert kind == "counts"
    return lambda: cache._note_result_counts({RUN: {"count": 1, "bytes": 1, "seq": [A["store"], 9],
                                                    "store_created": A["store_created"]}})


def b_confirmation(cache: FolderCache, kind: str) -> Answer:
    """B's first answer of ``kind`` (finding 4: results may learn of B first)."""
    if kind == "presets":
        request = presets_job(cache)
        return lambda: send(cache, request, {"kind": "presets", "saved": [], "rows": [], **B}, {"kind": "done"})
    if kind == "missing":
        request = find_job(cache, "result-find:b")
        return lambda: send(cache, request, {"kind": "result_missing", **B}, {"kind": "done"})
    if kind == "inventory":
        request = inventory_job(cache)
        return lambda: send(cache, request, {"kind": "inventory", "inventory": {
            "pending": [], "pending_results": [], "store_id": B["store"], "store_created": B["store_created"]}},
            {"kind": "done"})
    assert kind == "counts"
    return lambda: cache._note_result_counts({"/data/root/other": {"count": 0, "bytes": 0, "seq": [B["store"], 1],
                                                                   "store_created": B["store_created"]}})


A_KINDS = ("found", "missing", "saved", "pending", "adopted", "presets", "inventory", "counts")
B_KINDS = ("presets", "missing", "inventory", "counts")


@pytest.mark.parametrize("start", ["fresh", "A in use"])
@pytest.mark.parametrize("a_kind,b_kind", list(itertools.product(A_KINDS, B_KINDS)))
@pytest.mark.parametrize("order", ["A then B", "B then A"])
def test_every_order_of_an_old_stores_answer_and_the_new_ones_ends_on_the_new_one(
        cache: FolderCache, start: str, a_kind: str, b_kind: str, order: str) -> None:
    """The store is recreated (A → B) while HeLab runs: an answer of A's (each kind) and B's first
    answer (each kind) arrive in either order, after a fresh start (finding 3: A's delayed first
    answer) or with A in use. Always: B is in use, A retired; no preset row, waiting question or
    count of A's stays; and whatever said "saved in disk cache" or handed a guard from A is
    followed by the drop of A's saved results (plots say RAM only), never left standing."""
    if start == "A in use":
        confirm = presets_job(cache)
        send(cache, confirm, {"kind": "presets", "saved": [], "rows": [], **A}, {"kind": "done"})
        assert cache._store == (A["store_created"], A["store"])
    timeline: list[str] = []
    cache.resultReady.connect(lambda request, event: timeline.append(
        "claim" if event.get("kind") in ("result_found", "result_saved")
        or (event.get("kind") == "result_missing" and event.get("guard")) else ""))
    cache.resultPendingAnswered.connect(lambda pending_id, saved, result_id: timeline.append("claim" if saved else ""))
    cache.cacheRemoved.connect(lambda paths, kinds: timeline.append(
        "dropped" if paths is None and "results" in kinds else ""))
    old, new = a_answer(cache, a_kind), b_confirmation(cache, b_kind)
    for answer in ((old, new) if order == "A then B" else (new, old)):
        answer()
    assert cache._store == (B["store_created"], B["store"]) and A["store"] in cache._stores_retired
    assert ("arrangement", "", "from-a") not in cache.presets
    assert all(entry.get("store") == B["store"] for entry in cache.pending_results.values())
    assert all(entry[2] is not None and entry[2][0] == B["store"] for entry in cache.result_counts.values())
    claims = [index for index, mark in enumerate(timeline) if mark == "claim"]
    assert all("dropped" in timeline[index:] for index in claims), timeline
    if order == "B then A":
        assert not claims  # Taken as stale: nothing found, not saved, not asked.


def test_an_older_store_never_seen_is_retired_with_one_warning(cache: FolderCache,
                                                              caplog: pytest.LogCaptureFixture) -> None:
    """A store sorting before the one in use (e.g. made after the clock was set back) is kept out:
    one WARNING names both, the one in use is kept; equal times order by id, never both ways."""
    assert cache.store_answer(B["store"], B["store_created"])
    assert not cache.store_answer(A["store"], A["store_created"])
    assert not cache.store_answer(A["store"], A["store_created"])
    warnings = [record for record in caplog.records if record.levelname == "WARNING"]
    assert len(warnings) == 1 and A["store"] in warnings[0].getMessage() and B["store"] in warnings[0].getMessage()
    assert cache._store == (B["store_created"], B["store"])
    assert cache.store_answer("ab-tie", B["store_created"])  # Same time, later id: newer.
    assert not cache.store_answer("a0-tie", B["store_created"])  # Same time, earlier id: older.
    assert cache.store_answer("", None) and cache.store_answer(None)  # No store named: no claim.


def test_a_moved_store_keeps_its_identity(tmp_path: Path, cache: FolderCache) -> None:
    """A cache move goes only to an empty or new folder, by a rename or a verified copy: the store
    there is the same (its id and ``created_at``), so it stays in use and nothing starts afresh."""
    source, target = tmp_path / "caches" / "store-v3", tmp_path / "moved" / "store-v3"
    with CacheStore(str(source)) as store:
        identity = (store.created_at, store.store_id)
    shutil.copytree(source, target)
    with CacheStore(str(target)) as store:
        assert (store.created_at, store.store_id) == identity and store.created_at > 0
    dropped: list[Any] = []
    cache.cacheRemoved.connect(lambda paths, kinds: dropped.append(kinds))
    assert cache.store_answer(identity[1], identity[0])
    cache.presets[("arrangement", "", "kept")] = {"record": "{}", "set_at": 1.0}
    assert cache.store_answer(identity[1], identity[0])  # The moved store answering.
    assert dropped == [] and ("arrangement", "", "kept") in cache.presets


def test_a_guard_taken_in_a_store_saves_nothing_in_the_one_recreated_there(tmp_path: Path) -> None:
    """Finding 1, through the helpers: a running plot's guard from A (its lookup found nothing); the
    store recreated as B at the same folder; the save with A's guard writes nothing in B."""
    folder = tmp_path / "run"
    folder.mkdir()
    cache_options = options(tmp_path)
    missing = find(tmp_path, folder, cache_options)[-1]
    assert missing["kind"] == "result_missing" and missing["guard"]["store"] == missing["store"]
    shutil.rmtree(cache_options["directory"])
    with CacheStore(cache_options["directory"]) as store:
        assert store.store_id != missing["store"] and store.created_at >= missing["store_created"]
    events = save_through_helper(tmp_path, folder, cache_options, missing["guard"])
    assert events[-1]["kind"] == "result_not_saved" and events[-1]["reason"] == "store_replaced"
    with CacheStore(cache_options["directory"]) as store:
        assert store._conn.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 0
    # A guard of the store itself saves.
    guard = find(tmp_path, folder, cache_options)[-1]["guard"]
    assert save_through_helper(tmp_path, folder, cache_options, guard)[-1]["kind"] == "result_saved"
