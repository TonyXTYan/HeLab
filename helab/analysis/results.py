"""An analysis run's input (``AnalysisContext``) and its record (``AnalysisResult``), kept in
RAM only for now (result caching stage R1)."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Literal, Mapping

from helab.analysis.dataset_view import DatasetView, ViewKey
from helab.analysis.identity import AnalysisIdentity

State = Literal["completed", "failed", "cancelled"]
# Where a result is kept (result caching rule 2). R1 has only RAM.
RAM_ONLY = "ram"


class Cancelled(Exception):
    """Raised inside a computation that noticed ``AnalysisContext.cancelled()``."""


@dataclass(frozen=True)
class AnalysisContext:
    """Everything a run gets: an immutable dataset view and its effective parameters,
    never the tab. ``cancelled()`` lets a long computation stop early."""
    job_id: str
    action: str
    view: DatasetView
    parameters: Mapping[str, Any]
    analysis: AnalysisIdentity
    cancel_event: threading.Event = field(default_factory=threading.Event, compare=False)

    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def check(self) -> None:
        """Stop here (raise ``Cancelled``) if the run was cancelled: call between phases."""
        if self.cancel_event.is_set():
            raise Cancelled()


@dataclass(frozen=True)
class AnalysisResult:
    job_id: str
    action: str
    analysis: AnalysisIdentity
    input: ViewKey
    parameters: Mapping[str, Any]  # effective: every declared parameter, defaults filled in
    state: State
    data: Any = None  # what the analysis's ``compute`` returned
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    policy: str = RAM_ONLY

    @classmethod
    def of(cls, context: AnalysisContext, state: State, data: Any = None, error: str = "",
           started_at: float = 0.0) -> AnalysisResult:
        return cls(context.job_id, context.action, context.analysis, context.view.key,
                   MappingProxyType(dict(context.parameters)), state, data, error,
                   started_at, time.time())

    def describe(self, parameters_text: str = "") -> str:
        """The record, one item per line, for a plot dock's tooltip."""
        identity = self.input.identity
        lines = [f"{self.analysis.text()} · {self.action}",
                 f"Input: {identity.source_path} · revision {self.input.revision}",
                 f"Data root: {identity.root_key or 'none known'}",
                 f"Signature: {identity.signature[:16] or 'none'}",
                 f"Parameters: {parameters_text or _plain(self.parameters) or 'none'}"]
        when = datetime.fromtimestamp(self.finished_at).strftime("%H:%M:%S") if self.finished_at else ""
        took = f" in {self.finished_at - self.started_at:.1f} s" if self.started_at and self.finished_at else ""
        lines.append(f"Job {self.job_id} · {self.state} {when}{took} · kept in RAM only")
        if self.error:
            lines.append(f"Error: {self.error}")
        return "\n".join(lines)


def _plain(parameters: Mapping[str, Any]) -> str:
    return ", ".join(f"{name} = {value}" for name, value in parameters.items())


class RamResults:
    """Results of this session, least recently used dropped first beyond ``limit``; results
    a plot dock shows are pinned and never dropped."""

    def __init__(self, limit: int = 64) -> None:
        self.limit = limit
        self._results: OrderedDict[str, AnalysisResult] = OrderedDict()
        self._pinned: set[str] = set()
        self._lock = threading.Lock()

    def add(self, result: AnalysisResult) -> None:
        with self._lock:
            self._results[result.job_id] = result
            self._results.move_to_end(result.job_id)
            for job_id in [key for key in self._results if key not in self._pinned]:
                if len(self._results) <= self.limit:
                    break
                del self._results[job_id]

    def get(self, job_id: str) -> AnalysisResult | None:
        with self._lock:
            result = self._results.get(job_id)
            if result is not None:
                self._results.move_to_end(job_id)
            return result

    def for_input(self, key: ViewKey) -> list[AnalysisResult]:
        with self._lock:
            return [result for result in self._results.values() if result.input == key]

    def pin(self, job_id: str) -> None:
        with self._lock:
            self._pinned.add(job_id)

    def unpin(self, job_id: str) -> None:
        with self._lock:
            self._pinned.discard(job_id)

    def __len__(self) -> int:
        return len(self._results)
