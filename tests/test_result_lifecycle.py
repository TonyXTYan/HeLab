"""The life of a saved analysis result against everything that removes results (Gauge's round 3), all
through real helpers and FolderCache's events: a lookup, a save, a waiting result (its Make room or
Discard question) and an adoption (Make room asked) in flight, against Make room evicting the same
result or another of the folder, Clear cached analysis (all, the root's), a purge by age and Discard.
An eviction is no clear: it affects only the results it removed (by folder and lookup key), never
the folder's other saves or waiting results. Each cell that can happen has a test (``CELL_*``); the
table is in the session handoff."""
from __future__ import annotations

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

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [ParameterSpec("scale", "Scale", "int", self.scale, (1, 10))]

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
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
        cache.resultPendingAnswered.connect(lambda pending_id, done: self.answers.append((pending_id, done)))

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

def test_lookup_x_eviction_of_the_same_result_computes(lab: Lab) -> None:
    lab.saved_plot(1)
    release = lab.hold("result_found")
    instance, script = lab.plot(1, wait=False)
    lab.arrived()
    evict_scale_1(lab)
    release()
    lab.qtbot.waitUntil(lambda: settled(instance), timeout=WAIT)
    assert script.computed == 1 and shown(instance).source != FROM_DISK


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
