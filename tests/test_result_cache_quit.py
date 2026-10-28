"""Saved analysis results at quit and across a recreated store (result caching R2, Gauge's round 9):
quitting waits for a plot's result being saved, by its run or by Make room, as for presets and
datasets (results waiting for Make room stay for the next session); and an answer from a store
recreated at the cache folder since never says a result is saved in the one in use."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Iterator, cast

import pytest
from pytestqt.qtbot import QtBot

from conftest import store_free
from helab.analysis.results import DISK_CACHED, AnalysisResult
from helab.utils.cache_store import CacheStore
from helab.utils.folder_cache import PRESETS_SAVING, FolderCache, store_options
from helab.utils.io_service import IORequest, IOService
from helab.views.QuitSaveDialog import QuitSaveDialog
from test_result_cache_plots import (WAIT, Costly, cache, close, folder_view, make_window,  # noqa: F401
                                     open_plot, results_saved, saved, settled, stop_runners)

RUN = FolderCache.key("/data/root/run")


@pytest.fixture
def frozen() -> Iterator[FolderCache]:
    """A cache whose helpers never run: the test sends their events, in the order it chooses."""
    service = IOService()
    service.timer.stop()
    service._dispatch = lambda: None  # type: ignore[method-assign]
    yield FolderCache(service)
    service.shutdown()


def job(cache: FolderCache, operation: str, action: str = "") -> IORequest:
    """The newest request for ``operation`` (a ``cache_admin`` one: of ``action``)."""
    return next(request for request in reversed(cache.service.pending) if request.operation == operation
                and (not action or request.payload.get("action") == action))


def answer(cache: FolderCache, request: IORequest, *events: dict[str, Any]) -> None:
    for event in events:
        cache.service.resultReady.emit(request, event)
    if request in cache.service.pending:
        cache.service.pending.remove(request)


def save(cache: FolderCache, owner: str = "result-save:1") -> IORequest:
    assert cache.save_result(owner, RUN, b"packed", lookup="k1", family="f1", record={}, analysis_id="a",
                             action="Plot", computed_at=1.0, guard={"generations": {}, "epochs": {}}, label="Costly")
    return job(cache, "result_save")


def test_quit_waits_for_result_saves_and_make_room_but_not_for_waiting_results(frozen: FolderCache) -> None:
    cache = frozen
    told: list[list[str]] = []
    cache.quitSavesChanged.connect(lambda: told.append(cache.quit_saves()))
    first = save(cache)
    assert cache.quit_saves() == [RUN] and told[-1] == [RUN] and cache.result_saving(RUN)
    cache.set_presets([("arrangement", "", "desk", "{}")])  # (A preset write queued too.)
    assert cache.quit_saves() == [RUN, PRESETS_SAVING]
    presets = job(cache, "cache_admin", "presets")
    answer(cache, presets, {"kind": "presets", "saved": [], "rows": [], "store": "A"}, {"kind": "done"})
    for _ in range(5):  # (Its rows written once the store's names are known.)
        waiting = [r for r in cache.service.pending if r.operation == "cache_admin"]
        if not waiting:
            break
        rows = waiting[0].payload["params"]["rows"]
        answer(cache, waiting[0], {"kind": "presets", "saved": rows, "rows": rows, "store": "A"}, {"kind": "done"})
    assert cache.quit_saves() == [RUN]  # The presets are saved; the result save isn't yet.
    answer(cache, first, {"kind": "result_saved", "bytes": 6, "result_id": "r1", "store": "A"})
    assert cache.quit_saves() == [RUN]  # Until its helper ends.
    answer(cache, first, {"kind": "done"})
    assert cache.quit_saves() == [] and told[-1] == [] and not cache.result_saving(RUN)
    # A result that doesn't fit waits for Make room: it stays for the next session, not waited for.
    second = save(cache, "result-save:2")
    answer(cache, second, {"kind": "result_pending", "pending_id": "p1", "path": RUN, "label": "Costly", "bytes": 6,
                           "budget": 10, "room": None, "store": "A"}, {"kind": "done"})
    assert "p1" in cache.pending_results and cache.quit_saves() == []
    # Make room for it saves it: waited for until its helper ends.
    assert cache.cache_admin("adopt_result", pending_id="p1", make_room=True, room_ids=[])
    adopt = job(cache, "cache_admin", "adopt_result")
    assert cache.quit_saves() == [RUN] and told[-1] == [RUN]
    answer(cache, adopt, {"kind": "admin_result", "action": "adopt_result", "adopted": True, "path": RUN,
                          "bytes": 6, "room": None, "result_id": "r2", "store": "A"})
    assert cache.quit_saves() == [RUN]
    answer(cache, adopt, {"kind": "done"})
    assert cache.quit_saves() == [] and told[-1] == []
    # A failed save ends too.
    third = save(cache, "result-save:3")
    answer(cache, third, {"kind": "error", "message": "disk I/O error"})
    assert cache.quit_saves() == []


def test_the_quit_window_waits_for_a_result_save_after_the_presets_are_saved(qtbot: QtBot,
                                                                            frozen: FolderCache) -> None:
    """Gauge's repro: a result save and a preset write queued; the presets end first. The real quit
    window stays open, naming the result's folder, and closes once its helper ends."""
    cache = frozen
    request = save(cache)
    cache.set_presets([("arrangement", "", "desk", "{}")])
    cache.cancel_for_quit()
    dialog = QuitSaveDialog(cache)
    qtbot.addWidget(dialog)
    results: list[int] = []
    dialog.finished.connect(results.append)
    dialog.open()
    assert dialog.label.text() == "Saving 1 folder and presets to the disk cache before HeLab quits:"
    item = dialog.folders.item(0)
    assert item is not None and item.text() == "run — saving a plot's result" and item.toolTip() == RUN
    presets = job(cache, "cache_admin", "presets")
    answer(cache, presets, {"kind": "presets", "saved": [], "rows": [], "store": "A"}, {"kind": "done"})
    for _ in range(5):
        waiting = [r for r in cache.service.pending if r.operation == "cache_admin"]
        if not waiting:
            break
        rows = waiting[0].payload["params"]["rows"]
        answer(cache, waiting[0], {"kind": "presets", "saved": rows, "rows": rows, "store": "A"}, {"kind": "done"})
    dialog.refresh()
    assert results == [] and dialog.isVisible()
    assert dialog.label.text() == "Saving 1 folder to the disk cache before HeLab quits:"
    answer(cache, request, {"kind": "result_saved", "bytes": 6, "result_id": "r1", "store": "A"}, {"kind": "done"})
    qtbot.waitUntil(lambda: bool(results), timeout=WAIT)  # Saved: it closes by itself.
    assert not dialog.skipped and cache.quit_saves() == []


def test_an_old_stores_answer_never_says_saved_in_the_recreated_one(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Through real helpers: a result saved in store A; a plot's lookup finds it there, its answer
    held; the store is recreated at the cache folder (B, empty), which a presets read answers from;
    A's answer, released, is old: the plot computes and keeps its result in RAM only (no guard of
    A's checked against B). The plot that showed A's saved result says RAM only too."""
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    first = open_plot(window, qtbot, folder_view(tmp_path), Costly())
    qtbot.waitUntil(lambda: saved(first), timeout=WAIT)
    held: list[tuple[IORequest, dict[str, Any]]] = []
    handle = cache._on_result_event

    def holding(producer: IORequest, event: dict[str, Any]) -> None:
        if event["kind"] == "result_found":
            held.append((producer, event))
        else:
            handle(producer, event)
    monkeypatch.setattr(cache, "_on_result_event", holding)
    script = Costly()
    second = open_plot(window, qtbot, folder_view(tmp_path), script)
    # The lookup sends result_found with the store still open: delete it only once no helper has it
    # open, every exit confirmed, as a cache move does (Windows refuses to delete an open file), the
    # app-wide service's too: the plots' Presets rows read through it (``store_free``).
    qtbot.waitUntil(lambda: bool(held) and store_free(cache.service), timeout=WAIT)
    assert held[0][1]["exact"] and held[0][1]["store"]
    directory = store_options()["directory"]
    shutil.rmtree(directory)
    with CacheStore(directory) as store:  # (Recreated by hand: another store_id.)
        assert store.store_id != held[0][1]["store"]
    cache.read_presets()
    qtbot.waitUntil(lambda: not cache._preset_jobs, timeout=WAIT)
    # The plot showing A's saved result: RAM only now.
    assert cast(AnalysisResult, first.shown).policy != DISK_CACHED
    monkeypatch.setattr(cache, "_on_result_event", handle)
    for producer, event in held:
        handle(producer, event)
    qtbot.waitUntil(lambda: settled(second) and script.computed == 1, timeout=WAIT)
    assert cast(AnalysisResult, second.shown).policy != DISK_CACHED
    assert results_saved() == 0  # Nothing saved in B under A's guard.
    close(window)


def test_a_store_is_free_only_once_the_app_wide_services_helpers_have_exited(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The Windows rerun above (WinError 32 deleting records.sqlite): a plot's Presets row reads
    presets through the app-wide service, which the test's own ``cache.service.cache_busy()`` never
    counted. Its helper kept as not exited, the test's service is idle but the store isn't free."""
    from helab.utils.io_service import get_io_service
    app = get_io_service()
    held: list[IORequest] = []
    reap = app._reap

    def keep(request: IORequest) -> None:  # (Its exit not confirmed: the reaper hasn't seen it.)
        if app.uses_cache(request):
            held.append(request)
        else:
            reap(request)
    monkeypatch.setattr(app, "_reap", keep)
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    first = open_plot(window, qtbot, folder_view(tmp_path), Costly())
    qtbot.waitUntil(lambda: saved(first) and bool(held) and not cache.service.cache_busy(), timeout=WAIT)
    assert app.cache_busy() and not store_free(cache.service)  # (The old wait would delete it now.)
    monkeypatch.setattr(app, "_reap", reap)
    for request in held:
        reap(request)
    qtbot.waitUntil(lambda: store_free(cache.service), timeout=WAIT)
    close(window)


def test_a_waiting_result_that_goes_says_why(frozen: FolderCache) -> None:
    """C-2 (Tony, 2026-10-26): a waiting result that expired, or whose store was recreated, isn't
    said to be discarded: resultPendingAnswered carries why."""
    from helab.utils.folder_cache import PENDING_DISCARDED, PENDING_EXPIRED, PENDING_STORE
    cache = frozen
    reasons: list[tuple[str, bool, str]] = []
    cache.resultPendingAnswered.connect(lambda pending_id, saved, _, why: reasons.append((pending_id, saved, why)))

    def waiting(pending_id: str) -> None:
        request = save(cache, f"result-save:{pending_id}")
        answer(cache, request, {"kind": "result_pending", "pending_id": pending_id, "path": RUN, "label": "Costly",
                                "bytes": 6, "budget": 10, "room": None, "store": "A"}, {"kind": "done"})
        assert pending_id in cache.pending_results
    waiting("p1")
    assert cache.cache_admin("sweep")
    answer(cache, job(cache, "cache_admin", "sweep"),
           {"kind": "swept", "expired_ids": ["p1"], "next_deadline": None, "store": "A"}, {"kind": "done"})
    waiting("p2")
    assert cache.cache_admin("discard_result", pending_id="p2")
    answer(cache, job(cache, "cache_admin", "discard_result"),
           {"kind": "admin_result", "action": "discard_result", "adopted": False, "path": RUN, "store": "A"},
           {"kind": "done"})
    waiting("p3")
    cache._results_store_replaced("B")
    assert reasons == [("p1", False, PENDING_EXPIRED), ("p2", False, PENDING_DISCARDED), ("p3", False, PENDING_STORE)]


def test_the_plot_words_each_reason(qtbot: QtBot, cache: FolderCache, tmp_path: Path,
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.utils.folder_cache import PENDING_CLEARED, PENDING_DISCARDED, PENDING_EXPIRED, PENDING_STORE
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    plot = open_plot(window, qtbot, folder_view(tmp_path), Costly())
    qtbot.waitUntil(lambda: settled(plot), timeout=WAIT)
    link = plot._cached_runs()
    shown = cast(AnalysisResult, plot.shown)
    for why, text in ((PENDING_EXPIRED, "not saved (expired): it waited over an hour for Make room"),
                      (PENDING_STORE, "not saved: the disk cache was recreated"),
                      (PENDING_CLEARED, "not saved: its cached analysis was cleared"),
                      (PENDING_DISCARDED, "not saved in the disk cache (discarded)")):
        link._waiting[why] = (shown, 6)
        cache.resultPendingAnswered.emit(why, False, "", why)
        assert plot.status_label.text().endswith(f"⚠ {text}"), (why, plot.status_label.text())
    close(window)
