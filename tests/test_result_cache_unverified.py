"""Saved analysis results on a volume this session hasn't verified yet (codebase review 2, C-1): the
local lane refuses a lookup or save there (``VolumeUnverified``: ``error`` with ``unverified``). Not
a miss nor a failed read: asked again once volume verification has run (once, as a cached read
is), the run waiting meanwhile. Tony (2026-10-26): after ``VERIFY_WAIT`` the plot computes and
says its result isn't saved yet; the save waits on, up to ``SAVE_VERIFY_WAIT``, then the plot's
amber line says the drive couldn't be checked. And C-3: a run that ends failed drops its lookup's
helper if it hasn't answered."""
from __future__ import annotations

from pathlib import Path
from typing import Any, List

import logging

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDockWidget
from pytestqt.qtbot import QtBot

from helab.analysis.results import DISK_CACHED, AnalysisContext, AnalysisResult
from helab.utils.folder_cache import FolderCache
from helab.utils.io_service import IORequest
from helab.views.plots import cached_results
from helab.views.plots.cached_results import UNCHECKED_NOTE, VERIFY_NOTE
from helab.views.plots.instance import AnalysisInstance
from test_result_cache_plots import (WAIT, Costly, cache, close, folder_view, make_window,  # noqa: F401
                                     open_plot, results_saved, reuse_on, saved, settled, stop_runners)

REFUSED = {"kind": "error", "message": "its drive isn't verified yet this session", "unverified": True}


def refuse_first(cache: FolderCache, monkeypatch: pytest.MonkeyPatch, operation: str, *,
                 verify_meanwhile: bool = False, answer: bool = True, times: int = 1) -> List[str]:
    """The first ``times`` ``operation`` requests aren't sent: their volume refuses them (or,
    ``answer`` False, they never answer). ``verify_meanwhile``: a verification runs after one was
    asked, before the answer."""
    refused: List[str] = []
    submit = cache.service.submit

    def refusing(owner: str, generation: int, path: str, op: str, payload: Any = None, **options: Any) -> bool:
        if op != operation or len(refused) >= times:
            return submit(owner, generation, path, op, payload, **options)
        refused.append(owner)
        request = IORequest(owner, generation, path, op, dict(payload or {}), 60.0)
        if verify_meanwhile:
            QTimer.singleShot(0, cache.volumesVerified.emit)
        if answer:
            QTimer.singleShot(10, lambda: cache.service.resultReady.emit(request, dict(REFUSED)))
        return True
    monkeypatch.setattr(cache.service, "submit", refusing)
    return refused


def test_a_lookup_its_volume_refused_waits_and_is_asked_again_after_verification(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    refused = refuse_first(cache, monkeypatch, "result_find")
    script = Costly()
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    plot = open_plot(window, qtbot, folder_view(tmp_path), script)
    qtbot.waitUntil(lambda: bool(refused), timeout=WAIT)
    qtbot.wait(300)  # (The refusal is answered meanwhile.)
    # Not a failed read: the run waits for the drive's check, saying nothing more.
    assert script.computed == 0 and plot.status_label.text().startswith("Looking in the disk cache")
    cache.volumesVerified.emit()
    qtbot.waitUntil(lambda: saved(plot), timeout=WAIT)
    assert script.computed == 1 and results_saved() == 1
    assert "couldn't be read" not in plot.status_label.text()
    close(window)


def test_a_lookup_refused_after_a_verification_ran_since_it_was_asked_is_asked_again_at_once(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    refuse_first(cache, monkeypatch, "result_find", verify_meanwhile=True)
    script = Costly()
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    plot = open_plot(window, qtbot, folder_view(tmp_path), script)
    qtbot.waitUntil(lambda: saved(plot), timeout=WAIT)  # (No other verification comes.)
    assert script.computed == 1 and results_saved() == 1
    close(window)


def amber(plot: AnalysisInstance) -> str:
    dock = plot.dock_widget
    assert isinstance(dock, QDockWidget)
    return str(dock.property("plotError") or "")


def waits(monkeypatch: pytest.MonkeyPatch, compute: float, save: float) -> None:
    monkeypatch.setattr(cached_results, "VERIFY_WAIT", compute)
    monkeypatch.setattr(cached_results, "SAVE_VERIFY_WAIT", save)


def test_after_the_first_wait_the_plot_computes_and_its_save_waits_for_the_drive(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """At VERIFY_WAIT the plot computes; the status bar and its status line say the result isn't
    saved yet. Verification then asks for the guard alone (the run isn't repeated), the result is
    saved and the note clears."""
    waits(monkeypatch, 0.2, 30.0)
    refuse_first(cache, monkeypatch, "result_find")
    script = Costly()
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    plot = open_plot(window, qtbot, folder_view(tmp_path), script)
    qtbot.waitUntil(lambda: settled(plot) and script.computed == 1, timeout=WAIT)
    assert window.notices.count(VERIFY_NOTE) == 1 and VERIFY_NOTE in plot.status_label.text()
    assert isinstance(plot.shown, AnalysisResult) and plot.shown.policy != DISK_CACHED and results_saved() == 0
    cache.volumesVerified.emit()
    qtbot.waitUntil(lambda: saved(plot), timeout=WAIT)
    assert script.computed == 1 and results_saved() == 1
    assert VERIFY_NOTE not in plot.status_label.text() and amber(plot) == ""
    close(window)


def test_without_verification_the_result_is_left_unsaved_and_the_plot_says_so(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    waits(monkeypatch, 0.2, 0.6)
    refuse_first(cache, monkeypatch, "result_find")
    script = Costly()
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    with caplog.at_level(logging.WARNING):
        plot = open_plot(window, qtbot, folder_view(tmp_path), script)
        qtbot.waitUntil(lambda: UNCHECKED_NOTE in amber(plot), timeout=WAIT)
    assert script.computed == 1 and results_saved() == 0 and VERIFY_NOTE not in plot.status_label.text()
    logged = [record for record in caplog.records if "drive couldn't be checked" in record.getMessage()]
    assert len(logged) == 1  # One log line; no window.
    cache.volumesVerified.emit()  # Too late: nothing waits any more.
    qtbot.wait(300)
    assert results_saved() == 0
    close(window)


def test_a_lookup_refused_again_after_verification_computes_and_isnt_saved(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    waits(monkeypatch, 30.0, 60.0)
    refused = refuse_first(cache, monkeypatch, "result_find", times=2)
    script = Costly()
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    plot = open_plot(window, qtbot, folder_view(tmp_path), script)
    qtbot.waitUntil(lambda: len(refused) == 1, timeout=WAIT)
    qtbot.wait(100)
    cache.volumesVerified.emit()  # Its check still refuses the drive.
    qtbot.waitUntil(lambda: settled(plot) and UNCHECKED_NOTE in amber(plot), timeout=WAIT)
    assert script.computed == 1 and results_saved() == 0
    close(window)


def test_a_clear_after_the_run_started_voids_its_late_save(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard verification brings is taken after the run started: a Clear cached analysis of
    the folder in between saves nothing, as the guard taken at the start would have."""
    waits(monkeypatch, 0.2, 30.0)
    refuse_first(cache, monkeypatch, "result_find")
    script = Costly()
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    plot = open_plot(window, qtbot, folder_view(tmp_path), script)
    qtbot.waitUntil(lambda: settled(plot) and script.computed == 1, timeout=WAIT)
    cache.cacheRemoved.emit(None, ["results"])
    cache.volumesVerified.emit()
    qtbot.wait(1500)
    assert results_saved() == 0 and not saved(plot)
    close(window)


class Holding(Costly):
    """A script that keeps state for its plot: its run starts with the lookup, before the guard."""

    def cache_holds_state(self, action_name: str, owner: str) -> bool:
        return True

    def cache_result(self, action_name: str, result: AnalysisResult) -> bool:
        return True


def test_a_clear_voids_the_late_save_of_a_script_holding_state(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sextant's review of item 9: a holds-state run starts before its guard whether or not the
    lookup was refused, so a Clear after it started fences its late guard too."""
    waits(monkeypatch, 30.0, 60.0)
    refuse_first(cache, monkeypatch, "result_find")
    script = Holding()
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    plot = open_plot(window, qtbot, folder_view(tmp_path), script)
    qtbot.waitUntil(lambda: settled(plot) and script.computed == 1, timeout=WAIT)
    cache.cacheRemoved.emit(None, ["results"])
    cache.volumesVerified.emit()
    qtbot.wait(1500)
    assert results_saved() == 0 and not saved(plot)
    close(window)


def test_a_refused_save_left_unsaved_says_so_in_the_amber_line(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    waits(monkeypatch, 0.2, 0.6)
    refuse_first(cache, monkeypatch, "result_save")
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    plot = open_plot(window, qtbot, folder_view(tmp_path), Costly())
    qtbot.waitUntil(lambda: UNCHECKED_NOTE in amber(plot), timeout=WAIT)
    assert VERIFY_NOTE in window.notices and results_saved() == 0
    close(window)


def test_a_save_its_volume_refused_is_asked_again_with_its_guard_after_verification(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    refused = refuse_first(cache, monkeypatch, "result_save")
    script = Costly()
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    plot = open_plot(window, qtbot, folder_view(tmp_path), script)
    qtbot.waitUntil(lambda: settled(plot) and bool(refused), timeout=WAIT)
    qtbot.wait(300)
    assert isinstance(plot.shown, AnalysisResult) and plot.shown.policy != DISK_CACHED and results_saved() == 0
    assert "not saved" not in plot.status_label.text()
    cache.volumesVerified.emit()
    qtbot.waitUntil(lambda: saved(plot), timeout=WAIT)
    assert script.computed == 1 and results_saved() == 1
    close(window)


class Failing(Costly):
    """A script that keeps state for its plot (its run starts at once, beside the lookup) and fails."""

    def cache_holds_state(self, action_name: str, owner: str) -> bool:
        return True

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        raise RuntimeError("no luck")


def test_a_failed_run_cancels_its_lookup_still_out(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    refused = refuse_first(cache, monkeypatch, "result_find", answer=False)
    cancelled: List[str] = []
    cancel = cache.service.cancel

    def recording(owner: str) -> None:
        cancelled.append(owner)
        cancel(owner)
    monkeypatch.setattr(cache.service, "cancel", recording)
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    plot = open_plot(window, qtbot, folder_view(tmp_path), Failing())
    qtbot.waitUntil(lambda: settled(plot) or (not plot.job_id and bool(refused)), timeout=WAIT)
    assert refused and refused[0] in cancelled
    close(window)
