"""Regressions from Gauge's review of 6906d96 (result caching R2): result events a Clear cached
analysis made stale are never taken as current (a late result_found / result_saved / result_pending);
result saves report the store's cleanup deadline and FolderCache schedules the sweep; a result
reused from disk says where it is kept after a clear; a damaged result file is a CodecError."""
from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Any, Callable, Iterator, cast

import numpy as np
import pytest
from PyQt6.QtWidgets import QDockWidget, QLabel
from pytestqt.qtbot import QtBot

from helab.analysis import result_codec
from helab.analysis.result_codec import CodecError
from helab.analysis.results import DISK_CACHED, FROM_DISK, AnalysisResult
from helab.io_ops.results import result_find, result_save
from helab.utils.folder_cache import FolderCache, get_folder_cache
from helab.utils.io_service import IORequest, IOService
from test_result_cache_plots import (Costly, cache, close, folder_view, make_window, open_plot, results_saved,  # noqa: F401
                                     saved, settled, stop_runners, WAIT)


def held_events(cache: FolderCache, monkeypatch: pytest.MonkeyPatch, kind: str
                ) -> tuple[list[tuple[IORequest, dict[str, Any]]], Callable[[], None]]:
    """Hold the result events of ``kind`` FolderCache gets; the second value delivers them."""
    held: list[tuple[IORequest, dict[str, Any]]] = []
    real = cache._on_result_event

    def hold(producer: IORequest, event: dict[str, Any]) -> None:
        if event["kind"] == kind and not getattr(hold, "released", False):
            held.append((producer, event))
            return
        real(producer, event)

    def release() -> None:
        setattr(hold, "released", True)
        for producer, event in held:
            real(producer, event)
    monkeypatch.setattr(cache, "_on_result_event", hold)
    return held, release


def test_a_lookup_answered_after_a_clear_computes(qtbot: QtBot, cache: FolderCache, tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    first = open_plot(window, qtbot, folder_view(tmp_path), Costly())
    qtbot.waitUntil(lambda: saved(first), timeout=WAIT)
    first.close()
    held, release = held_events(cache, monkeypatch, "result_found")
    script = Costly()
    second = open_plot(window, qtbot, folder_view(tmp_path), script)
    qtbot.waitUntil(lambda: bool(held), timeout=WAIT)
    cache.removed(None, ["results"])  # Clear cached analysis: its removed event arrives first.
    release()
    qtbot.waitUntil(lambda: settled(second), timeout=WAIT)
    assert script.computed == 1 and cast(AnalysisResult, second.shown).source != FROM_DISK
    close(window)


@pytest.mark.parametrize("scope", ["all", "folder"])
def test_a_save_acknowledged_after_a_clear_doesnt_mark_the_plot(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scope: str) -> None:
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    held, release = held_events(cache, monkeypatch, "result_saved")
    view = folder_view(tmp_path)
    instance = open_plot(window, qtbot, view, Costly())
    qtbot.waitUntil(lambda: bool(held) and settled(instance), timeout=WAIT)
    # The clear (all, or the folder's: a root's or a purge names its folders) removes the row...
    cache.removed(None if scope == "all" else [view.identity.source_path], ["results"])
    release()  # ...and the save's late acknowledgement doesn't bring the mark back.
    qtbot.wait(50)
    assert cast(AnalysisResult, instance.shown).policy != DISK_CACHED
    close(window)


def test_a_result_pending_after_a_clear_is_dropped_not_asked(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
                                                             tmp_path: Path) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    frozen = get_folder_cache(service)
    monkeypatch.setattr("helab.utils.folder_cache.store_options", lambda: {"directory": str(tmp_path)})
    path = str(tmp_path / "run")
    assert frozen.save_result("plot-save", path, b"x", lookup="k", family="f", record={}, analysis_id="a",
                              action="Plot", computed_at=1.0, guard={})
    request = next(r for r in service.pending if r.owner == "plot-save")
    seen: list[dict[str, Any]] = []
    frozen.resultReady.connect(lambda producer, event: seen.append(event))
    frozen.removed([path], ["results"])
    service.resultReady.emit(request, {"kind": "result_pending", "pending_id": "p1", "path": path, "label": "x",
                                       "bytes": 5, "budget": 1, "room": None})
    assert not frozen.pending_results and seen[-1]["kind"] == "result_not_saved" and seen[-1]["reason"] == "cleared"
    discard = next(r for r in service.pending if r.operation == "cache_admin")
    assert discard.payload["action"] == "discard_result" and discard.payload["params"] == {"pending_id": "p1"}
    service.shutdown()


# The sweep deadline

def test_result_saves_report_the_cleanup_deadline_and_the_sweep_is_scheduled(
        tmp_path: Path, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "data" / "run"
    folder.mkdir(parents=True)
    options: dict[str, Any] = {"directory": str(tmp_path / "caches" / "store-v3"), "budget": 1, "budget_set_at": 1.0}
    output = tmp_path / "out"
    output.mkdir()
    events: list[Any] = []
    result_find(str(folder), str(output), options, "k", "f", events.append)
    guard = events[-1]["guard"]
    blob = tmp_path / "blob"
    blob.write_bytes(result_codec.pack(*result_codec.encode({"x": np.random.default_rng(0).random(5000)})))
    for hold_budget in (1, 8 << 30, 8 << 30):  # Waits (expires), saved, saved again (replaces: retires).
        sent: list[Any] = []
        result_save(str(folder), {**options, "budget": hold_budget, "budget_set_at": time.time()}, str(blob),
                    lookup="k", family="f", record={}, analysis_id="a", action="Plot", computed_at=1.0,
                    guard=guard, send=sent.append)
        assert isinstance(sent[-1].get("next_deadline"), float), sent[-1]
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    frozen = get_folder_cache(service)
    monkeypatch.setattr("helab.utils.folder_cache.store_options", lambda: {"directory": str(tmp_path)})
    frozen.save_result("s", str(folder), b"x", lookup="k", family="f", record={}, analysis_id="a", action="Plot",
                       computed_at=1.0, guard={})
    request = next(r for r in service.pending if r.owner == "s")
    deadline = time.time() + 600
    service.resultReady.emit(request, {"kind": "result_saved", "bytes": 5, "next_deadline": deadline})
    assert frozen._sweep_deadline == deadline and frozen._sweep_timer.isActive()
    service.shutdown()


# The record after a clear

def test_a_result_reused_from_disk_says_ram_only_after_a_clear(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    first = open_plot(window, qtbot, folder_view(tmp_path), Costly())
    qtbot.waitUntil(lambda: saved(first), timeout=WAIT)
    first.close()
    second = open_plot(window, qtbot, folder_view(tmp_path), Costly())
    qtbot.waitUntil(lambda: settled(second), timeout=WAIT)
    shown = cast(AnalysisResult, second.shown)
    assert shown.source == FROM_DISK and "· in the disk cache" in shown.describe()
    assert cache.cache_admin("clear_results")
    qtbot.waitUntil(lambda: cast(AnalysisResult, second.shown).policy != DISK_CACHED, timeout=WAIT)
    record = cast(AnalysisResult, second.shown).describe()
    assert "From disk cache, computed" in record and "kept in RAM only" in record
    close(window)


# A damaged file

@pytest.mark.parametrize("damage", ["truncated zip", "a bare npy", "empty"])
def test_a_damaged_result_file_is_a_codec_error(damage: str) -> None:
    good = result_codec.pack(*result_codec.encode({"x": np.arange(10.0)}))
    if damage == "truncated zip":
        data = good[: len(good) // 2]
    elif damage == "a bare npy":
        buffer = io.BytesIO()
        np.save(buffer, np.arange(3.0))
        data = buffer.getvalue()
    else:
        data = b""
    with pytest.raises(CodecError):
        result_codec.unpack(data)


# Round 2: the Make room flow

class Noisy(Costly):
    """A result of 20,000 random values (about 160 kB, incompressible), one per Scale."""

    def compute(self, action_name: str, context: Any) -> Any:
        data = super().compute(action_name, context)
        return type(data)(np.random.default_rng(int(context.parameters["scale"])).random(20_000), data.scale)


def make_room_button(dialogs: Any) -> Any:
    box = dialogs.dialog
    assert box is not None
    return next(button for button in box.buttons() if button.text() == "Make room")


def test_make_room_evicting_a_result_of_the_same_folder_saves_the_new_one(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.utils import folder_cache
    from helab.views.CacheDialogs import CacheDialogs
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    dialogs = CacheDialogs(cache, window, lambda: None)
    instance = open_plot(window, qtbot, folder_view(tmp_path), Noisy())
    qtbot.waitUntil(lambda: saved(instance), timeout=WAIT)
    assert cache.disk_usage is not None
    monkeypatch.setattr(folder_cache, "_disk_budget", cache.disk_usage + 50_000)
    monkeypatch.setattr(folder_cache, "_disk_budget_set_at", time.time())
    root = instance.parameter_root
    assert root is not None
    root.child("scale").setValue(2)  # Another result of the same folder: it doesn't fit beside the first.
    instance.run()
    qtbot.waitUntil(lambda: dialogs.dialog is not None, timeout=WAIT)
    [entry] = cache.pending_results.values()
    assert entry["room"]["possible"] and len(entry["room"]["result_ids"]) == 1
    answers: list[bool] = []
    cache.resultPendingAnswered.connect(lambda pending_id, done, _: answers.append(done))
    make_room_button(dialogs).click()
    qtbot.waitUntil(lambda: saved(instance), timeout=WAIT)
    assert answers == [True] and results_saved() == 1
    status = instance.status_label.text()
    assert "discarded" not in status and "not saved yet" not in status
    dialogs.detach()
    close(window)


def test_a_delayed_inventory_keeps_a_result_waiting_since(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.utils import folder_cache
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    held: list[tuple[IORequest, dict[str, Any]]] = []
    real = cache._on_admin_event
    owner = cache.cache_admin("inventory")  # Asked before the result waits; its answer is held.

    def hold(producer: IORequest, event: dict[str, Any]) -> None:
        if producer.owner == owner and not getattr(hold, "released", False):
            held.append((producer, event))
            return
        real(producer, event)
    monkeypatch.setattr(cache, "_on_admin_event", hold)
    qtbot.waitUntil(lambda: any(event["kind"] == "done" for _, event in held), timeout=WAIT)
    monkeypatch.setattr(folder_cache, "_disk_budget", 1)
    monkeypatch.setattr(folder_cache, "_disk_budget_set_at", time.time())
    instance = open_plot(window, qtbot, folder_view(tmp_path), Costly())
    qtbot.waitUntil(lambda: bool(cache.pending_results), timeout=WAIT)
    setattr(hold, "released", True)
    for producer, event in held:
        real(producer, event)
    assert len(cache.pending_results) == 1  # The older inventory didn't drop it.
    assert "not saved yet" in instance.status_label.text()
    close(window)


def test_a_result_saved_after_make_room_clears_the_plots_warning(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.utils import folder_cache
    from helab.views.CacheDialogs import CacheDialogs
    monkeypatch.setattr(folder_cache, "_disk_budget", 1)
    monkeypatch.setattr(folder_cache, "_disk_budget_set_at", time.time())
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    dialogs = CacheDialogs(cache, window, lambda: None)
    instance = open_plot(window, qtbot, folder_view(tmp_path), Costly())
    qtbot.waitUntil(lambda: dialogs.dialog is not None, timeout=WAIT)
    assert "not saved yet" in instance.status_label.text()
    monkeypatch.setattr(folder_cache, "_disk_budget", 8 << 30)  # The user raised the budget meanwhile.
    monkeypatch.setattr(folder_cache, "_disk_budget_set_at", time.time())
    box = dialogs.dialog
    assert box is not None
    button = next((b for b in box.buttons() if b.text() == "Make room"), None)
    if button is None:  # (Asked as "results alone can't make room": answered with the new budget.)
        dialogs._answer(next(iter(cache.pending_results)), dialogs._asking[1], "adopt_result")
        dialogs._close()
    else:
        button.click()
    qtbot.waitUntil(lambda: saved(instance), timeout=WAIT)
    assert "not saved yet" not in instance.status_label.text() and results_saved() == 1
    dialogs.detach()
    close(window)
