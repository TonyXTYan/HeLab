"""Runs analyses off the GUI thread, one at a time, in submission order.

A local, in-process first step towards the shared job runner
(``roadmaps/analysis-job-runner.md``): each job gets an immutable ``AnalysisContext`` when
it is submitted, so nothing that happens in the browser afterwards changes its input. One
daemon thread computes (NumPy releases the GIL for the heavy parts); results come back on
the GUI thread through ``finished`` and are kept in RAM (``RamResults``). The queue, worker
and cancellation are Qt-free (``helab.analysis.runner_core.AnalysisQueue``); ``AnalysisRunner``
adds the signals.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from helab.analysis.dataset_view import DatasetView
from helab.analysis.results import AnalysisContext, AnalysisResult, RamResults
from helab.analysis.runner_core import AnalysisQueue
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.utils import app_log


class AnalysisRunner(QObject):
    """The app's analysis runner: an ``AnalysisQueue`` (``core``) whose job ends are a Qt
    signal. They are emitted on the worker thread, as the core calls them, and Qt delivers
    them to receivers on the GUI thread."""
    # (AnalysisResult) when a job ends, however it ends.
    finished = pyqtSignal(object)

    def __init__(self, results: Optional[RamResults] = None, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.core = AnalysisQueue(results, None, self._finished)
        self.results = self.core.results

    def _finished(self, result: AnalysisResult) -> None:
        app_log.milestone("plot_done", script=result.analysis.analysis_id, version=result.analysis.version,
                          action=result.action, plot=result.owner, job=result.job_id,
                          seconds=result.finished_at - result.started_at,
                          state={"completed": "ok"}.get(result.state, result.state))
        self.finished.emit(result)

    def submit(self, script: DatasetAnalysis, metadata: ScriptMetadata, action: str,
               view: DatasetView, values: Optional[Mapping[str, Any]] = None,
               constants: Optional[Mapping[str, Mapping[str, float]]] = None, owner: str = "",
               live: bool = False) -> AnalysisContext:
        """Queue ``action`` on ``view`` (GUI thread; ``AnalysisQueue.submit``). Raises
        ``RuntimeError`` while the runner is stopping (until its worker has exited)."""
        return self.core.submit(script, metadata, action, view, values, constants, owner=owner, live=live)

    def prepare(self, script: DatasetAnalysis, metadata: ScriptMetadata, action: str,
                view: DatasetView, values: Optional[Mapping[str, Any]] = None,
                constants: Optional[Mapping[str, Mapping[str, float]]] = None, owner: str = "",
                live: bool = False, to_cache: bool = False) -> AnalysisContext:
        """A run's context without queuing it (``AnalysisQueue.prepare``): ``enqueue`` runs it."""
        return self.core.prepare(script, metadata, action, view, values, constants, owner=owner, live=live,
                                 to_cache=to_cache)

    def enqueue(self, script: DatasetAnalysis, context: AnalysisContext) -> None:
        """Queue a prepared run (``AnalysisQueue.enqueue``); ``RuntimeError`` while stopping."""
        self.core.enqueue(script, context)

    def cancel(self, job_id: str) -> None:
        """Ask a queued or running job to stop; it ends as ``cancelled`` (cooperatively)."""
        self.core.cancel(job_id)

    def running(self) -> int:
        return self.core.running()

    def stop(self, timeout: float = 5.0) -> bool:
        """Cancel every job and end the worker; True once it has exited (``AnalysisQueue.stop``)."""
        return self.core.stop(timeout)


_runner: AnalysisRunner | None = None


def get_analysis_runner() -> AnalysisRunner:
    """The app's runner (created on first use, on the GUI thread)."""
    global _runner
    if _runner is None:
        _runner = AnalysisRunner()
    return _runner
