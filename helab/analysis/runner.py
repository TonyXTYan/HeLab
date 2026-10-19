"""Runs analyses off the GUI thread, one at a time, in submission order.

A local, in-process first step towards the shared job runner
(``roadmaps/analysis-job-runner.md``): each job gets an immutable ``AnalysisContext`` when
it is submitted, so nothing that happens in the browser afterwards changes its input. One
daemon thread computes (NumPy releases the GIL for the heavy parts); results come back on
the GUI thread through ``finished`` and are kept in RAM (``RamResults``).
"""
from __future__ import annotations

import itertools
import logging
import queue
import threading
import time
from typing import Any, Mapping, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from helab.analysis.dataset_view import DatasetView
from helab.analysis.parameters import effective
from helab.analysis.results import AnalysisContext, AnalysisResult, Cancelled, RamResults, State
from helab.scripts.base import DatasetAnalysis, ScriptMetadata

_Job = tuple[DatasetAnalysis, AnalysisContext]


class AnalysisRunner(QObject):
    # (job_id) when a job starts computing; (AnalysisResult) when it ends, however it ends.
    started = pyqtSignal(str)
    finished = pyqtSignal(object)

    def __init__(self, results: Optional[RamResults] = None, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.results = results if results is not None else RamResults()
        self._queue: queue.Queue[_Job | None] = queue.Queue()
        self._contexts: dict[str, AnalysisContext] = {}
        self._lock = threading.Lock()
        # The worker stays registered until it has exited, so there is never a second one.
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._ids = itertools.count(1)

    def submit(self, script: DatasetAnalysis, metadata: ScriptMetadata, action: str,
               view: DatasetView, values: Optional[Mapping[str, Any]] = None) -> AnalysisContext:
        """Queue ``action`` on ``view`` with ``values`` validated against its declared parameters.
        Raises ``RuntimeError`` while the runner is stopping (until its worker has exited)."""
        parameters = effective(script.parameters(action), values)
        context = AnalysisContext(f"a{next(self._ids)}", action, view, parameters, metadata.identity())
        with self._lock:
            if self._stopping:
                raise RuntimeError("The analysis runner is stopping")
            self._contexts[context.job_id] = context
            if self._thread is None:
                self._thread = threading.Thread(target=self._work, name="AnalysisWorker", daemon=True)
                self._thread.start()
        self._queue.put((script, context))
        return context

    def cancel(self, job_id: str) -> None:
        """Ask a queued or running job to stop; it ends as ``cancelled`` (cooperatively)."""
        with self._lock:
            context = self._contexts.get(job_id)
        if context is not None:
            context.cancel_event.set()

    def running(self) -> int:
        with self._lock:
            return len(self._contexts)

    def stop(self, timeout: float = 5.0) -> bool:
        """Cancel every job and end the worker; True once it has exited. A computation that
        ignores cancellation may outlast ``timeout``: the worker then stays registered and
        submissions are refused until it exits (it then frees the runner for a new worker)."""
        with self._lock:
            contexts, thread = list(self._contexts.values()), self._thread
            if thread is not None and not self._stopping:
                self._stopping = True
                self._queue.put(None)
        for context in contexts:
            context.cancel_event.set()
        if thread is not None:
            thread.join(timeout=timeout)
            return not thread.is_alive()
        return True

    def _work(self) -> None:
        try:
            self._run_jobs()
        finally:
            with self._lock:
                self._thread, self._stopping = None, False

    def _run_jobs(self) -> None:
        while (job := self._queue.get()) is not None:
            script, context = job
            started = time.time()
            if context.cancelled():
                result = AnalysisResult.of(context, "cancelled", started_at=started)
            else:
                self.started.emit(context.job_id)
                try:
                    data = script.compute(context.action, context)
                    state: State = "cancelled" if context.cancelled() else "completed"
                    result = AnalysisResult.of(context, state, data if state == "completed" else None,
                                               started_at=started)
                except Cancelled:
                    result = AnalysisResult.of(context, "cancelled", started_at=started)
                except Exception as error:
                    logging.exception("Analysis %s failed", context.analysis.short())
                    result = AnalysisResult.of(context, "failed", error=str(error) or type(error).__name__,
                                               started_at=started)
            with self._lock:
                self._contexts.pop(context.job_id, None)
            if result.state == "completed":
                self.results.add(result)
            self.finished.emit(result)


_runner: AnalysisRunner | None = None


def get_analysis_runner() -> AnalysisRunner:
    """The app's runner (created on first use, on the GUI thread)."""
    global _runner
    if _runner is None:
        _runner = AnalysisRunner()
    return _runner
