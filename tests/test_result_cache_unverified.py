"""Saved analysis results on a volume this session hasn't verified yet (codebase review 2, C-1): the
local lane refuses a lookup or save there (``VolumeUnverified``: ``error`` with ``unverified``). Not
a miss nor a failed read: asked again once volume verification has run (once, as a cached read
is), the run waiting meanwhile; without verification within ``VERIFY_WAIT``, as for any error.
And C-3: a run that ends failed drops its lookup's helper if it hasn't answered."""
from __future__ import annotations

from pathlib import Path
from typing import Any, List

import pytest
from PyQt6.QtCore import QTimer
from pytestqt.qtbot import QtBot

from helab.analysis.results import DISK_CACHED, AnalysisContext, AnalysisResult
from helab.utils.folder_cache import FolderCache
from helab.utils.io_service import IORequest
from helab.views.plots import cached_results
from test_result_cache_plots import (WAIT, Costly, cache, close, folder_view, make_window,  # noqa: F401
                                     open_plot, results_saved, saved, settled, stop_runners)

REFUSED = {"kind": "error", "message": "its drive isn't verified yet this session", "unverified": True}


def refuse_first(cache: FolderCache, monkeypatch: pytest.MonkeyPatch, operation: str, *,
                 verify_meanwhile: bool = False, answer: bool = True) -> List[str]:
    """The first ``operation`` request isn't sent: its volume refuses it (or, ``answer`` False, it
    never answers). ``verify_meanwhile``: a verification runs after it was asked, before the answer."""
    refused: List[str] = []
    submit = cache.service.submit

    def refusing(owner: str, generation: int, path: str, op: str, payload: Any = None, **options: Any) -> bool:
        if op != operation or refused:
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


def test_without_verification_a_refused_lookup_computes_as_for_any_error(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cached_results, "VERIFY_WAIT", 0.2)
    refuse_first(cache, monkeypatch, "result_find")
    script = Costly()
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    plot = open_plot(window, qtbot, folder_view(tmp_path), script)
    qtbot.waitUntil(lambda: settled(plot) and script.computed == 1, timeout=WAIT)
    assert "the disk cache couldn't be read (its drive isn't verified yet this session)" in plot.status_label.text()
    assert isinstance(plot.shown, AnalysisResult) and plot.shown.policy != DISK_CACHED and results_saved() == 0
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
