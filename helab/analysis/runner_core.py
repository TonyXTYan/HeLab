"""Runs analyses off the calling thread, one at a time, in submission order, without Qt
(``AnalysisQueue``): the core of ``helab.analysis.runner.AnalysisRunner``, and of a headless
runner later (``roadmaps/analysis-job-runner.md``). Each job gets an immutable
``AnalysisContext`` when it is submitted; one daemon thread computes (NumPy releases the GIL
for the heavy parts), and completed results are kept in RAM (``RamResults``).
"""
from __future__ import annotations

import itertools
import logging
import queue
import threading
import time
import weakref
from dataclasses import replace
from types import MappingProxyType
from typing import Any, Callable, Generic, Mapping, Optional, TypeVar

from helab.analysis import result_codec
from helab.analysis.dataset_view import DatasetView
from helab.analysis.parameters import effective, unused_parameters
from helab.analysis.results import AnalysisContext, AnalysisResult, Cancelled, Coverage, RamResults, State
from helab.scripts.base import DatasetAnalysis, ScriptMetadata

_Job = tuple[DatasetAnalysis, AnalysisContext]
_Call = TypeVar("_Call", bound=Callable[..., None])


class _Held(Generic[_Call]):
    """A callback held while the queue is idle: a bound method weakly (its owner, e.g. the
    ``AnalysisRunner`` that owns this queue, isn't kept alive by it, so no cycle), anything else
    strongly. ``get`` resolves it (None: its owner is gone)."""

    def __init__(self, callback: Optional[_Call]) -> None:
        self._method: Optional[weakref.WeakMethod[_Call]] = None
        self._strong: Optional[_Call] = None
        if callback is not None and hasattr(callback, "__self__") and hasattr(callback, "__func__"):
            self._method = weakref.WeakMethod(callback)
        else:
            self._strong = callback

    def get(self) -> Optional[_Call]:
        return self._method() if self._method is not None else self._strong


class AnalysisQueue:
    """The runner without Qt: a FIFO queue of jobs, one daemon worker thread that computes them,
    job ids, cooperative cancellation and the completed results kept in RAM (``results``).
    ``on_started(job_id)`` when a job starts computing and ``on_finished(result)`` when it ends,
    however it ends, are called on the worker thread (``AnalysisRunner`` turns them into Qt
    signals delivered on the GUI thread). Bound methods are held weakly while no worker runs;
    a running worker holds them strongly, so their owner lives as long as its worker."""

    def __init__(self, results: Optional[RamResults] = None,
                 on_started: Optional[Callable[[str], None]] = None,
                 on_finished: Optional[Callable[[AnalysisResult], None]] = None) -> None:
        self._on_started = _Held(on_started)
        self._on_finished = _Held(on_finished)
        self.results = results if results is not None else RamResults()
        self._queue: queue.Queue[_Job | None] = queue.Queue()
        self._contexts: dict[str, AnalysisContext] = {}
        self._lock = threading.Lock()
        # The worker stays registered until it has exited, so there is never a second one.
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._ids = itertools.count(1)

    def submit(self, script: DatasetAnalysis, metadata: ScriptMetadata, action: str,
               view: DatasetView, values: Optional[Mapping[str, Any]] = None,
               constants: Optional[Mapping[str, Mapping[str, float]]] = None, owner: str = "",
               live: bool = False) -> AnalysisContext:
        """``prepare`` the run and ``enqueue`` it (GUI thread)."""
        context = self.prepare(script, metadata, action, view, values, constants, owner=owner, live=live)
        self.enqueue(script, context)
        return context

    def prepare(self, script: DatasetAnalysis, metadata: ScriptMetadata, action: str,
                view: DatasetView, values: Optional[Mapping[str, Any]] = None,
                constants: Optional[Mapping[str, Mapping[str, float]]] = None, owner: str = "",
                live: bool = False, to_cache: bool = False) -> AnalysisContext:
        """Queue ``action`` on ``view`` with ``values`` validated against its declared parameters,
        and the lab and folder layers of the constants taken now (``constants``: {"lab": …,
        "folder": …}; GUI thread). An analysis that uses constants gets them resolved with its own
        values now too (``DatasetAnalysis.run_constants``), in its context and its result.
        The run's coverage is the shots the script says it uses (all of them if it can't say).
        ``owner``: the plot asking (``AnalysisContext.owner``); ``live``: a rerun following Live
        (``AnalysisContext.live``); ``to_cache``: pack its completed result for the disk cache
        (``AnalysisContext.to_cache``). Queues nothing: ``enqueue`` runs it (a plot may first find
        its result in the disk cache, result caching R2)."""
        parameters = effective(script.parameters(action), values)
        try:
            coverage = Coverage.of(view, script.covered_shots(action, parameters, view))
        except Exception:
            logging.exception("Coverage of %s: all shots", metadata.name)
            coverage = Coverage.of(view)
        layers = MappingProxyType({name: MappingProxyType(dict(values))
                                  for name, values in (constants or {}).items()})
        keys: tuple[str, ...] = ()
        try:
            keys = tuple(script.constant_keys(action))
            resolved = script.run_constants(action, parameters, layers) if keys else None
        except Exception:
            logging.exception("Constants of %s: none resolved", metadata.name)
            resolved = None
        if resolved is not None:
            try:  # The keys this run uses; all the analysis declares if it can't say.
                keys = tuple(script.run_constant_keys(action, parameters))
            except Exception:
                logging.exception("Constant keys of %s: all of them", metadata.name)
        context = AnalysisContext(f"a{next(self._ids)}", action, view, parameters, metadata.identity(),
                                  unused=unused_parameters(script.parameters(action), parameters),
                                  coverage=coverage, constants=layers, resolved_constants=resolved,
                                  constant_keys=keys if resolved is not None else (), owner=owner, live=live,
                                  to_cache=to_cache)
        return context

    def enqueue(self, script: DatasetAnalysis, context: AnalysisContext) -> None:
        """Queue a prepared run. Raises ``RuntimeError`` while the runner is stopping (until its
        worker has exited)."""
        with self._lock:
            if self._stopping:
                raise RuntimeError("The analysis runner is stopping")
            self._contexts[context.job_id] = context
            if self._thread is None:
                # The worker holds the callbacks (and so their owner) while it runs.
                callbacks = (self._on_started.get(), self._on_finished.get())
                self._thread = threading.Thread(target=self._work, args=callbacks, name="AnalysisWorker",
                                                daemon=True)
                self._thread.start()
        self._queue.put((script, context))

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

    def _work(self, on_started: Optional[Callable[[str], None]],
              on_finished: Optional[Callable[[AnalysisResult], None]]) -> None:
        try:
            self._run_jobs(on_started, on_finished)
        finally:
            with self._lock:
                self._thread, self._stopping = None, False

    def _run_jobs(self, on_started: Optional[Callable[[str], None]],
                  on_finished: Optional[Callable[[AnalysisResult], None]]) -> None:
        while (job := self._queue.get()) is not None:
            self._run(*job, on_started, on_finished)
            # Nothing of the job stays referenced while the worker waits for the next one: a plot
            # released to free RAM must free its input (``helab.analysis.budget``).
            del job

    @staticmethod
    def _found(script: DatasetAnalysis, context: AnalysisContext, data: Any) -> dict[str, Any]:
        """The run's ``found`` record; a script whose record fails still has its result (the
        plot draws, without those record lines), and the error is logged."""
        try:
            return script.result_found(context.action, data)
        except Exception:
            logging.exception("Analysis %s: its record of what the run found failed", context.analysis.short())
            return {}

    @staticmethod
    def _packed(script: DatasetAnalysis, result: AnalysisResult) -> AnalysisResult:
        """``result`` with its data packed for the disk cache, if the script says it may be saved
        (``cache_result``: what a plot keeping nothing would give); a script that fails to pack it
        leaves it in RAM only, saying why."""
        try:
            if not script.cache_result(result.action, result):
                return result
            tree, arrays = script.cache_pack(result.action, result.data)
            return replace(result, packed=result_codec.pack(tree, arrays))
        except Exception as error:
            logging.exception("Analysis %s: its result couldn't be packed for the disk cache", result.analysis.short())
            return replace(result, packing_error=str(error) or type(error).__name__)

    def _run(self, script: DatasetAnalysis, context: AnalysisContext,
             on_started: Optional[Callable[[str], None]],
             on_finished: Optional[Callable[[AnalysisResult], None]]) -> None:
        started = time.time()
        if context.cancelled():
            result = AnalysisResult.of(context, "cancelled", started_at=started)
        else:
            if on_started is not None:
                on_started(context.job_id)
            try:
                data = script.compute(context.action, context)
                state: State = "cancelled" if context.cancelled() else "completed"
                found = self._found(script, context, data) if state == "completed" else {}
                result = AnalysisResult.of(context, state, data if state == "completed" else None,
                                           started_at=started, found=found)
            except Cancelled:
                result = AnalysisResult.of(context, "cancelled", started_at=started)
            except Exception as error:
                logging.exception("Analysis %s failed", context.analysis.short())
                result = AnalysisResult.of(context, "failed", error=str(error) or type(error).__name__,
                                           started_at=started)
        if result.state == "completed" and context.to_cache:
            result = self._packed(script, result)
        with self._lock:
            self._contexts.pop(context.job_id, None)
        if result.state == "completed":
            self.results.add(replace(result, packed=None) if result.packed is not None else result)
        if on_finished is not None:
            on_finished(result)
