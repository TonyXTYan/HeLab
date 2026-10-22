"""The life of a saved analysis result against everything that removes results (Gauge's round 3), all
through real helpers and FolderCache's events: a lookup, a save, a waiting result (its Make room or
Discard question) and an adoption (Make room asked) in flight, against Make room evicting the same
result or another of the folder, Clear cached analysis (all, the root's), a purge by age and Discard.
An eviction is no clear: it affects only the saved rows it removed (by result id), never the
folder's other saves or waiting results, nor a newer copy of the same result being saved or waiting
(Tony, Follow-up 2: Make room removes old saved results only). Each cell that can happen has a test (``CELL_*``); the
table is in the session handoff."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterator, List, cast

import numpy as np
import pytest
from PyQt6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from helab.analysis.parameters import ParameterSpec
from helab.analysis.results import DISK_CACHED, FROM_DISK, AnalysisContext, AnalysisResult
from helab.io_ops import stores
from helab.utils import folder_cache
from helab.utils.cache_store import CacheStore, store_root
from helab.utils.constants import cache_dir
from helab.utils.folder_cache import FolderCache
from helab.utils.io_service import IORequest
from helab.views.plots.instance import AnalysisInstance
from test_result_cache_plots import (WAIT, Costly, Window, cache, close, folder_view, make_window,  # noqa: F401
                                     open_plot, results_saved, saved, settled, stop_runners)


class Noisy(Costly):
    """About 160 kB of random values per Scale (incompressible), Scale ``scale`` by default."""

    def __init__(self, scale: int = 1) -> None:
        super().__init__()
        self.scale = scale
        self.entered = threading.Event()

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [ParameterSpec("scale", "Scale", "int", self.scale, (1, 10))]

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        self.entered.set()  # (Its lookup is answered: the run computes.)
        data = super().compute(action_name, context)
        return type(data)(np.random.default_rng(int(context.parameters["scale"])).random(20_000), data.scale)


class Lab:
    """A window and the steps the cells are made of."""

    def __init__(self, qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.qtbot, self.cache, self.tmp_path, self.monkeypatch = qtbot, cache, tmp_path, monkeypatch
        self.window: Window = make_window(qtbot, cache, tmp_path, monkeypatch)
        self.view = folder_view(tmp_path)
        self.answers: list[tuple[str, bool]] = []
        self.held: list[tuple[IORequest, dict[str, Any]]] = []
        cache.resultPendingAnswered.connect(lambda pending_id, done, _: self.answers.append((pending_id, done)))

    def plot(self, scale: int, *, wait: bool = True) -> tuple[AnalysisInstance, Noisy]:
        script = Noisy(scale)
        instance = open_plot(self.window, self.qtbot, self.view, script)
        if wait:
            self.qtbot.waitUntil(lambda: settled(instance), timeout=WAIT)
        return instance, script

    def saved_plot(self, scale: int) -> AnalysisInstance:
        instance, _ = self.plot(scale, wait=False)
        self.qtbot.waitUntil(lambda: saved(instance), timeout=WAIT)
        instance.close()  # (Its kept state, and its owner id, go with it.)
        return instance

    def budget(self, size: int) -> None:
        self.monkeypatch.setattr(folder_cache, "_disk_budget", size)
        self.monkeypatch.setattr(folder_cache, "_disk_budget_set_at", time.time())

    def tight(self) -> None:
        """A budget with room for what is saved now and about 50 kB more: one more result waits."""
        with CacheStore(store_root(cache_dir())) as store:
            usage = store.usage()
        self.budget(usage + 50_000)

    def waiting(self, scale: int) -> tuple[AnalysisInstance, str]:
        """A plot whose result waits for Make room or Discard, and its pending id."""
        before = set(self.cache.pending_results)
        instance, _ = self.plot(scale, wait=False)
        self.qtbot.waitUntil(lambda: bool(set(self.cache.pending_results) - before), timeout=WAIT)
        [pending_id] = set(self.cache.pending_results) - before
        return instance, pending_id

    def admin(self, action: str, **params: Any) -> list[dict[str, Any]]:
        """A cache_admin job run to its end; its events."""
        events: list[dict[str, Any]] = []
        owner = self.cache.cache_admin(action, **params)
        assert owner
        done: list[bool] = []

        def seen(name: str, event: dict[str, Any]) -> None:
            events.append(event)
        self.cache.cacheAdminResult.connect(seen)
        self.cache.cacheAdminDone.connect(lambda finished, *_: done.append(finished == owner))
        self.qtbot.waitUntil(lambda: any(done), timeout=WAIT)
        self.cache.cacheAdminResult.disconnect(seen)
        return events

    def make_room(self, pending_id: str, room_ids: list[str] | None = None) -> dict[str, Any]:
        entry = self.cache.pending_results[pending_id]
        ids = list(entry["room"]["result_ids"]) if room_ids is None else room_ids
        return next(event for event in self.admin("adopt_result", pending_id=pending_id, make_room=True,
                                                  room_ids=ids) if event.get("kind") == "admin_result")

    def root(self) -> str:
        with stores._cache_store(store_root(cache_dir()), [self.view.identity.source_path]) as store:
            return store._path_key(self.view.identity.source_path)[len("root://"):].partition("/")[0]

    def removal(self, what: str) -> None:
        """Clear cached analysis (all, the root's) or purge by age (every result: a cutoff ahead)."""
        if what == "all":
            self.admin("clear_results")
        elif what == "root":
            self.admin("clear_root_results", uuid=self.root())
        else:
            self.admin("purge", what="results", cutoff=time.time() + 3600)

    def hold(self, kind: str) -> Callable[[], None]:
        """Hold FolderCache's result events of ``kind`` from now; the returned call delivers them."""
        held: list[tuple[IORequest, dict[str, Any]]] = []
        self.held = held
        real = self.cache._on_result_event
        released = [False]

        def hold(producer: IORequest, event: dict[str, Any]) -> None:
            if event["kind"] == kind and not released[0]:
                held.append((producer, event))
                return
            real(producer, event)
        self.monkeypatch.setattr(self.cache, "_on_result_event", hold)

        def release() -> None:
            self.qtbot.waitUntil(lambda: bool(held), timeout=WAIT)
            released[0] = True
            for producer, event in held:
                real(producer, event)
        return release

    def arrived(self) -> None:
        """Wait until the held event has arrived (the read or save is done in the store)."""
        self.qtbot.waitUntil(lambda: bool(self.held), timeout=WAIT)

    def store_rows(self) -> tuple[int, int]:
        """(saved results, waiting results) in the store."""
        with CacheStore(store_root(cache_dir())) as store:
            return (int(store._conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]),
                    int(store._conn.execute("SELECT COUNT(*) FROM pending_results").fetchone()[0]))

    def close(self) -> None:
        close(self.window)


@pytest.fixture
def lab(qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Lab]:
    made = Lab(qtbot, cache, tmp_path, monkeypatch)
    made.budget(8 << 30)
    # (No CacheDialogs: each cell answers through FolderCache's admin jobs, as the dialog does.)
    yield made
    made.close()


def evict_scale_1(lab: Lab) -> None:
    """Make room for a waiting Scale 2, evicting saved Scale 1 (the least recently shown)."""
    lab.tight()
    _, pending_id = lab.waiting(2)
    assert lab.make_room(pending_id)["adopted"] is True


def shown(instance: AnalysisInstance) -> AnalysisResult:
    return cast(AnalysisResult, instance.shown)


# A lookup in flight

def test_lookup_x_eviction_of_the_same_result_computes_and_saves_the_newer_copy(lab: Lab) -> None:
    lab.saved_plot(1)
    release = lab.hold("result_found")
    instance, script = lab.plot(1, wait=False)
    lab.arrived()
    evict_scale_1(lab)
    lab.budget(8 << 30)
    release()
    lab.qtbot.waitUntil(lambda: settled(instance), timeout=WAIT)
    assert script.computed == 1 and shown(instance).source != FROM_DISK
    # Its guard predates the eviction and still holds (an eviction fences nothing): saved again.
    lab.qtbot.waitUntil(lambda: saved(instance), timeout=WAIT)
    assert lab.store_rows() == (2, 0)


def test_lookup_x_eviction_of_another_result_shows_it_from_disk(lab: Lab) -> None:
    lab.saved_plot(1)
    lab.saved_plot(3)  # Saved after Scale 1: Scale 1 is the one Make room evicts.
    release = lab.hold("result_found")
    instance, script = lab.plot(3, wait=False)
    lab.arrived()
    evict_scale_1(lab)
    release()
    lab.qtbot.waitUntil(lambda: settled(instance), timeout=WAIT)
    assert script.computed == 0 and shown(instance).source == FROM_DISK and shown(instance).policy == DISK_CACHED


@pytest.mark.parametrize("what", ["all", "root", "purge"])
def test_lookup_x_clear_or_purge_computes(lab: Lab, what: str) -> None:
    lab.saved_plot(1)
    release = lab.hold("result_found")
    instance, script = lab.plot(1, wait=False)
    lab.arrived()
    lab.removal(what)
    release()
    lab.qtbot.waitUntil(lambda: settled(instance), timeout=WAIT)
    assert script.computed == 1 and shown(instance).source != FROM_DISK
    # Its guard was taken before the removal: it isn't saved (RAM only).
    lab.qtbot.wait(200)
    assert shown(instance).policy != DISK_CACHED and lab.store_rows()[0] == 0


# A save in flight

def test_save_x_eviction_of_the_same_result_is_ram_only(lab: Lab) -> None:
    lab.saved_plot(1)
    lab.admin("clear_results")  # (So the next run computes and saves Scale 1 again.)
    release = lab.hold("result_saved")
    instance, _ = lab.plot(1)
    lab.arrived()  # Saved in the store; its answer held.
    evict_scale_1(lab)  # Make room for Scale 2 evicts this very result.
    release()
    lab.qtbot.wait(100)
    assert shown(instance).policy != DISK_CACHED


def test_save_x_eviction_of_another_result_is_saved(lab: Lab) -> None:
    lab.saved_plot(1)
    release = lab.hold("result_saved")
    instance, _ = lab.plot(3)
    lab.arrived()
    evict_scale_1(lab)
    release()
    lab.qtbot.waitUntil(lambda: shown(instance).policy == DISK_CACHED, timeout=WAIT)


@pytest.mark.parametrize("what", ["all", "root", "purge"])
def test_save_x_clear_or_purge_is_ram_only(lab: Lab, what: str) -> None:
    lab.budget(8 << 30)
    release = lab.hold("result_saved")
    instance, _ = lab.plot(1)
    lab.arrived()
    lab.removal(what)
    release()
    lab.qtbot.wait(100)
    assert shown(instance).policy != DISK_CACHED and lab.store_rows()[0] == 0


# A result waiting for its answer

def test_waiting_x_another_waiting_ones_eviction_keeps_its_question_and_saves(lab: Lab) -> None:
    lab.saved_plot(1)
    lab.tight()
    _, first = lab.waiting(2)
    second_plot, second = lab.waiting(3)
    assert lab.make_room(first)["adopted"] is True  # Evicts Scale 1.
    assert second in lab.cache.pending_results and lab.store_rows() == (1, 1)
    lab.budget(8 << 30)
    assert lab.make_room(second, room_ids=[])["adopted"] is True  # Its guard still holds.
    lab.qtbot.waitUntil(lambda: saved(second_plot), timeout=WAIT)
    assert lab.store_rows() == (2, 0) and (second, True) in lab.answers


@pytest.mark.parametrize("what", ["all", "root"])
def test_waiting_x_clear_drops_the_question(lab: Lab, what: str) -> None:
    lab.budget(1)
    instance, pending_id = lab.waiting(1)
    lab.removal(what)
    assert pending_id not in lab.cache.pending_results and lab.store_rows() == (0, 0)
    assert (pending_id, False) in lab.answers and "discarded" in instance.status_label.text()


def test_waiting_x_purge_of_its_folder_drops_the_question(lab: Lab) -> None:
    lab.saved_plot(1)
    lab.tight()
    instance, pending_id = lab.waiting(2)
    lab.removal("purge")  # Takes Scale 1 and moves the folder's epoch: the waiting one's guard breaks.
    assert pending_id not in lab.cache.pending_results and lab.store_rows() == (0, 0)
    assert (pending_id, False) in lab.answers
    lab.qtbot.waitUntil(lambda: "discarded" in instance.status_label.text(), timeout=WAIT)


def test_waiting_x_discard(lab: Lab) -> None:
    lab.budget(1)
    instance, pending_id = lab.waiting(1)
    lab.admin("discard_result", pending_id=pending_id)
    assert pending_id not in lab.cache.pending_results and lab.store_rows() == (0, 0)
    lab.qtbot.waitUntil(lambda: "discarded" in instance.status_label.text(), timeout=WAIT)


# An adoption in flight (Make room asked)

def test_adoption_x_another_adoptions_eviction_asks_again_with_the_new_plan(lab: Lab) -> None:
    lab.saved_plot(1)
    lab.tight()
    _, first = lab.waiting(2)
    _, second = lab.waiting(3)
    planned = list(lab.cache.pending_results[second]["room"]["result_ids"])  # Scale 1, as told.
    assert lab.make_room(first)["adopted"] is True  # Another adoption evicted it first.
    answer = lab.make_room(second, room_ids=planned)
    assert answer["adopted"] is False and answer["room"] is not None  # Not what the user agreed to: nothing.
    assert second in lab.cache.pending_results and lab.cache.pending_results[second]["room"] == answer["room"]
    assert lab.store_rows() == (1, 1)


@pytest.mark.parametrize("what", ["all", "root"])
def test_adoption_x_clear_before_it_is_gone(lab: Lab, what: str) -> None:
    lab.budget(1)
    instance, pending_id = lab.waiting(1)
    entry = dict(lab.cache.pending_results[pending_id])
    lab.removal(what)
    lab.cache.pending_results[pending_id] = entry  # (As the question was answered before the clear arrived.)
    lab.budget(8 << 30)
    answer = lab.make_room(pending_id, room_ids=[])
    assert answer["adopted"] is False and answer["rejected"] == "gone"
    assert pending_id not in lab.cache.pending_results and lab.store_rows() == (0, 0)
    assert shown(instance).policy != DISK_CACHED


def test_adoption_x_purge_before_it_is_gone(lab: Lab) -> None:
    lab.saved_plot(1)
    lab.tight()
    instance, pending_id = lab.waiting(2)
    entry = dict(lab.cache.pending_results[pending_id])
    lab.removal("purge")
    lab.cache.pending_results[pending_id] = entry  # (Make room was asked before the purge arrived.)
    lab.budget(8 << 30)
    answer = lab.make_room(pending_id, room_ids=[])
    assert answer["adopted"] is False and answer["rejected"] == "gone"
    assert lab.store_rows() == (0, 0) and shown(instance).policy != DISK_CACHED


# Round 4: a save running since before its key's eviction, and a saved row with a waiting replacement

class Deferred:
    """Saves asked for from now are held, their guards taken at their lookups; ``run`` sends one."""

    def __init__(self, lab: Lab) -> None:
        self.lab = lab
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.real = lab.cache.save_result
        lab.monkeypatch.setattr(lab.cache, "save_result", self.hold)

    def hold(self, *args: Any, **kwargs: Any) -> bool:
        self.calls.append((args, kwargs))
        return True  # (Asked: its answer comes once it is sent.)

    def ready(self, count: int) -> None:
        self.lab.qtbot.waitUntil(lambda: len(self.calls) >= count, timeout=WAIT)

    def run(self, index: int) -> None:
        args, kwargs = self.calls[index]
        assert self.real(*args, **kwargs)


def saved_with_waiting_replacement(lab: Lab) -> tuple[AnalysisInstance, str]:
    """Scale 1 saved by one run, and another run's result of the same key waiting (it didn't fit):
    both runs looked up before either saved, as two plots (or two HeLabs) can."""
    deferred = Deferred(lab)
    first, _ = lab.plot(1)
    second, _ = lab.plot(1)
    deferred.ready(2)
    deferred.run(0)
    lab.qtbot.waitUntil(lambda: saved(first), timeout=WAIT)
    first.close()
    with CacheStore(store_root(cache_dir())) as store:
        usage = store.usage()
    lab.budget(usage - 1)  # The replacement doesn't fit: it waits, beside the saved row of its key.
    before = set(lab.cache.pending_results)
    deferred.run(1)
    lab.qtbot.waitUntil(lambda: bool(set(lab.cache.pending_results) - before), timeout=WAIT)
    [pending_id] = set(lab.cache.pending_results) - before
    assert lab.store_rows() == (1, 1)
    lab.monkeypatch.setattr(lab.cache, "save_result", deferred.real)
    return second, pending_id


def test_save_x_eviction_of_the_same_key_before_its_transaction_saves_the_newer_copy(lab: Lab) -> None:
    """The order Gauge found: the save's transaction runs after Make room evicted its key's old row.
    The newer copy is saved, checked against the budget like any save."""
    deferred = Deferred(lab)
    late, _ = lab.plot(1)  # Looked up before anything was saved (its guard is old); its save waits.
    deferred.ready(1)
    lab.monkeypatch.setattr(lab.cache, "save_result", deferred.real)
    lab.saved_plot(1)  # Another run saves Scale 1...
    evict_scale_1(lab)  # ...and Make room for Scale 2 evicts it.
    lab.budget(8 << 30)
    deferred.run(0)  # Only now does the first run's save of Scale 1 reach the store, with its old guard.
    lab.qtbot.waitUntil(lambda: saved(late), timeout=WAIT)
    assert lab.store_rows() == (2, 0)


def test_save_x_eviction_of_the_same_key_then_no_room_is_its_own_question(lab: Lab) -> None:
    deferred = Deferred(lab)
    late, _ = lab.plot(1)
    deferred.ready(1)
    lab.monkeypatch.setattr(lab.cache, "save_result", deferred.real)
    lab.saved_plot(1)
    evict_scale_1(lab)  # (The budget stays tight: the newer copy doesn't fit.)
    before = set(lab.cache.pending_results)
    deferred.run(0)
    lab.qtbot.waitUntil(lambda: bool(set(lab.cache.pending_results) - before), timeout=WAIT)
    assert lab.store_rows() == (1, 1)
    lab.qtbot.waitUntil(lambda: "not saved yet" in late.status_label.text(), timeout=WAIT)


def test_waiting_x_eviction_of_its_keys_saved_row_keeps_the_replacement(lab: Lab) -> None:
    from helab.views.CacheDialogs import result_room_text
    replacement_plot, replacement = saved_with_waiting_replacement(lab)
    lab.tight()
    _, other = lab.waiting(2)
    room = lab.cache.pending_results[other]["room"]
    assert set(room) == {"result_ids", "bytes", "newest_last_used", "possible"}
    assert result_room_text(room).endswith("least recently shown first. Cached data isn't touched.")
    assert lab.make_room(other)["adopted"] is True  # Evicts the old saved Scale 1 only.
    assert replacement in lab.cache.pending_results and (replacement, False) not in lab.answers
    assert lab.store_rows() == (1, 1)
    lab.budget(8 << 30)
    assert lab.make_room(replacement, room_ids=[])["adopted"] is True  # Its own question, its guard intact.
    lab.qtbot.waitUntil(lambda: saved(replacement_plot), timeout=WAIT)
    assert lab.store_rows() == (2, 0)


def test_adoption_x_eviction_of_its_keys_saved_row_still_saves(lab: Lab) -> None:
    replacement_plot, replacement = saved_with_waiting_replacement(lab)
    lab.tight()
    _, other = lab.waiting(2)
    assert lab.make_room(other)["adopted"] is True
    lab.budget(8 << 30)
    answer = lab.make_room(replacement, room_ids=[])
    assert answer["adopted"] is True and answer["result_id"]
    lab.qtbot.waitUntil(lambda: saved(replacement_plot), timeout=WAIT)
    assert lab.store_rows() == (2, 0)


def test_adopted_then_evicted_says_ram_only(lab: Lab) -> None:
    """A result saved by Make room is named by its row's id: a later eviction of it marks its plot."""
    lab.budget(1)
    instance, pending_id = lab.waiting(1)
    lab.budget(8 << 30)
    assert lab.make_room(pending_id, room_ids=[])["adopted"] is True
    lab.qtbot.waitUntil(lambda: saved(instance), timeout=WAIT)
    evict_scale_1(lab)
    lab.qtbot.waitUntil(lambda: shown(instance).policy != DISK_CACHED, timeout=WAIT)


def test_lookup_x_discard_of_a_waiting_replacement_shows_the_saved_row(lab: Lab) -> None:
    _, replacement = saved_with_waiting_replacement(lab)
    release = lab.hold("result_found")
    instance, script = lab.plot(1, wait=False)
    lab.arrived()
    lab.admin("discard_result", pending_id=replacement)
    release()
    lab.qtbot.waitUntil(lambda: settled(instance), timeout=WAIT)
    assert script.computed == 0 and shown(instance).source == FROM_DISK and lab.store_rows() == (1, 0)


def test_adoption_acknowledged_after_a_clear_is_not_saved(lab: Lab) -> None:
    lab.budget(1)
    instance, pending_id = lab.waiting(1)
    lab.budget(8 << 30)
    held: list[tuple[IORequest, dict[str, Any]]] = []
    real, adopting = lab.cache._on_admin_event, [""]

    def hold(producer: IORequest, event: dict[str, Any]) -> None:
        if producer.owner == adopting[0]:  # (All of the adoption's events, its done too: held in order.)
            held.append((producer, event))
            return
        real(producer, event)
    lab.monkeypatch.setattr(lab.cache, "_on_admin_event", hold)
    adopting[0] = lab.cache.cache_admin("adopt_result", pending_id=pending_id, make_room=True, room_ids=[])
    assert adopting[0]
    lab.qtbot.waitUntil(lambda: any(event["kind"] == "admin_result" for _, event in held), timeout=WAIT)
    acknowledgement = next(event for _, event in held if event["kind"] == "admin_result")
    assert acknowledgement["adopted"] is True and lab.store_rows() == (1, 0)  # Saved in the store...
    lab.removal("all")  # ...then cleared, before its acknowledgement arrives.
    for producer, event in held:
        real(producer, event)
    assert (pending_id, False) in lab.answers and shown(instance).policy != DISK_CACHED
    assert lab.store_rows() == (0, 0)


def test_waiting_in_transit_x_eviction_of_its_key_is_still_asked(lab: Lab) -> None:
    """The replacement's result_pending is still on its way when Make room evicts its key's old row:
    it stays waiting, and is asked."""
    deferred = Deferred(lab)
    first, _ = lab.plot(1)
    second, _ = lab.plot(1)
    deferred.ready(2)
    deferred.run(0)
    lab.qtbot.waitUntil(lambda: saved(first), timeout=WAIT)
    first.close()
    with CacheStore(store_root(cache_dir())) as store:
        usage = store.usage()
    lab.budget(usage - 1)
    replacement_owner = deferred.calls[1][0][0]
    held: list[tuple[IORequest, dict[str, Any]]] = []
    real = lab.cache._on_result_event

    def hold(producer: IORequest, event: dict[str, Any]) -> None:
        if producer.owner == replacement_owner and event["kind"] == "result_pending" and not getattr(hold, "go", False):
            held.append((producer, event))
            return
        real(producer, event)
    lab.monkeypatch.setattr(lab.cache, "_on_result_event", hold)
    deferred.run(1)
    lab.qtbot.waitUntil(lambda: bool(held), timeout=WAIT)  # Waiting in the store; its message held.
    lab.monkeypatch.setattr(lab.cache, "save_result", deferred.real)
    assert lab.store_rows() == (1, 1)
    lab.tight()
    _, other = lab.waiting(2)
    assert lab.make_room(other)["adopted"] is True  # Evicts the old Scale 1; the replacement stays.
    setattr(hold, "go", True)
    for producer, event in held:
        real(producer, event)
    [pending_id] = [str(held_event["pending_id"]) for _, held_event in held]
    assert pending_id in lab.cache.pending_results and lab.store_rows() == (1, 1)
    lab.qtbot.waitUntil(lambda: "not saved yet" in second.status_label.text(), timeout=WAIT)
