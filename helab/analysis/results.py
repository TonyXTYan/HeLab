"""An analysis run's input (``AnalysisContext``) and its record (``AnalysisResult``), kept in
RAM only for now (result caching stage R1).

Each record keeps what a later reuse needs (result caching rules 5 and 8), though nothing
reuses it yet: the analysis's ID, version and file hash, the input's root key and
signatures, the effective parameters (JSON values only) and the coverage: the TXY shots the
run used, with their fingerprints (``Coverage``), so HeLab can tell what a later revision
adds (``Coverage.diff``)."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import MappingProxyType
from typing import Any, Iterable, Literal, Mapping

from helab.analysis.dataset_view import DatasetView, Fingerprint, ViewKey
from helab.analysis.identity import AnalysisIdentity
from helab.analysis.physics import ResolvedConstants

State = Literal["completed", "failed", "cancelled"]
# Where a result is kept (result caching rule 2). R1 has only RAM.
RAM_ONLY = "ram"


class Cancelled(Exception):
    """Raised inside a computation that noticed ``AnalysisContext.cancelled()``."""


@dataclass(frozen=True)
class CoverageDiff:
    """How a view differs from a result's coverage: shots it has that the run didn't use
    (``new``), used shots whose fingerprints differ now (``changed``), used shots it lacks
    (``gone``)."""
    new: tuple[int, ...] = ()
    changed: tuple[int, ...] = ()
    gone: tuple[int, ...] = ()

    @property
    def current(self) -> bool:
        return not (self.new or self.changed or self.gone)


@dataclass(frozen=True)
class Coverage:
    """The TXY shots a run used, ascending, with their fingerprints (those the view knew)."""
    shots: tuple[int, ...] = ()
    fingerprints: Mapping[int, Fingerprint] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def of(cls, view: DatasetView, shots: Iterable[int] | None = None) -> Coverage:
        """The view's ``shots`` (default: all of them); numbers the view lacks are left out."""
        chosen = tuple(sorted({int(shot) for shot in (view.shots if shots is None else shots)} & set(view.shots)))
        return cls(chosen, MappingProxyType({shot: view.fingerprints[shot] for shot in chosen
                                             if shot in view.fingerprints}))

    def diff(self, view: DatasetView, shots: Iterable[int] | None = None) -> CoverageDiff:
        """``view``'s shots (or those of them chosen) against this coverage."""
        wanted = set(view.shots if shots is None else shots) & set(view.shots)
        covered = set(self.shots)
        changed = [shot for shot in sorted(wanted & covered)
                   if view.fingerprints.get(shot) != self.fingerprints.get(shot)]
        return CoverageDiff(tuple(sorted(wanted - covered)), tuple(changed), tuple(sorted(covered - wanted)))

    def text(self) -> str:
        if not self.shots:
            return "no shots"
        count = len(self.shots)
        return f"{count:,} shot{'' if count == 1 else 's'} ({self.shots[0]}–{self.shots[-1]})"

    def to_json(self) -> dict[str, Any]:
        return {"shots": list(self.shots), "fingerprints": [list(self.fingerprints[shot])
                                                           for shot in self.shots if shot in self.fingerprints]}


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
    # The shots the run uses (``DatasetAnalysis.covered_shots``); all of the view's by default.
    coverage: Coverage | None = None
    # The lab and folder layers of the constants (``physics.resolve``), as {"lab": {key: value},
    # "folder": {…}}, taken when the run starts (compute does no I/O); a plot adds its own
    # overrides from its parameters. Empty until the Lab parameters and folder settings (F0b)
    # exist: the table's defaults apply.
    constants: Mapping[str, Mapping[str, float]] = field(default_factory=lambda: MappingProxyType({}))
    # Those layers with the plot's own values, resolved when the run was submitted
    # (``DatasetAnalysis.run_constants``), for an analysis that uses constants
    # (``DatasetAnalysis.constant_keys``); None otherwise. ``compute`` may read them here.
    resolved_constants: ResolvedConstants | None = None

    @property
    def covered(self) -> Coverage:
        return self.coverage if self.coverage is not None else Coverage.of(self.view)

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
    coverage: Coverage = field(default_factory=Coverage)
    input_signature: str = ""  # the input revision's own dataset signature (``DatasetView.signature``)
    # The run's constant layers and what it resolved from them (``AnalysisContext``'s).
    constant_layers: Mapping[str, Mapping[str, float]] = field(default_factory=lambda: MappingProxyType({}))
    resolved_constants: ResolvedConstants | None = None

    @classmethod
    def of(cls, context: AnalysisContext, state: State, data: Any = None, error: str = "",
           started_at: float = 0.0) -> AnalysisResult:
        return cls(context.job_id, context.action, context.analysis, context.view.key,
                   MappingProxyType(dict(context.parameters)), state, data, error,
                   started_at, time.time(), coverage=context.covered, input_signature=context.view.signature,
                   constant_layers=context.constants, resolved_constants=context.resolved_constants)

    @property
    def constants_record(self) -> dict[str, Any] | None:
        """The constants the run used, as JSON values: its lab and folder layers and, for an
        analysis that uses constants, what it resolved (``ResolvedConstants.as_record``)."""
        layers = {name: dict(values) for name, values in self.constant_layers.items()}
        if self.resolved_constants is None:
            return {"layers": layers} if layers else None
        return {"layers": layers, **self.resolved_constants.as_record()}

    def reuse_key(self) -> dict[str, Any]:
        """What a later reuse of this result must match (result caching rule 5), as JSON values:
        not used yet (R2 and R3 will)."""
        identity = self.input.identity
        return {"analysis_id": self.analysis.analysis_id, "version": self.analysis.version,
                "file_hash": self.analysis.file_hash, "action": self.action, "root_key": identity.root_key,
                "signature": identity.signature, "input_signature": self.input_signature,
                "parameters": dict(self.parameters), "coverage": self.coverage.to_json(),
                **({"constants": record} if (record := self.constants_record) is not None else {})}

    def describe(self, parameters_text: str = "") -> str:
        """The record, one item per line, for a plot dock's tooltip."""
        identity = self.input.identity
        lines = [f"{self.analysis.text()} · {self.action}",
                 f"Input: {identity.source_path} · revision {self.input.revision}",
                 f"Data root: {identity.root_key or 'none known'}",
                 f"Signature: {identity.signature[:16] or 'none'}"
                 + (f" (this revision: {self.input_signature[:16]})"
                    if self.input_signature and self.input_signature != identity.signature else ""),
                 f"Covers: {self.coverage.text()}",
                 f"Parameters: {parameters_text or _plain(self.parameters) or 'none'}"]
        if self.resolved_constants is not None:
            from helab.analysis.constant_layers import record_text
            lines.append(f"Constants: {record_text(self.resolved_constants)}")
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

    def peek(self, job_id: str) -> AnalysisResult | None:
        """The result, if kept, without making it recently used (for counting RAM)."""
        with self._lock:
            return self._results.get(job_id)

    def discard(self, job_id: str) -> None:
        """Forget a result (its plot was released or closed: nothing reads it again)."""
        with self._lock:
            self._pinned.discard(job_id)
            self._results.pop(job_id, None)

    def for_input(self, key: ViewKey) -> list[AnalysisResult]:
        with self._lock:
            return [result for result in self._results.values() if result.input == key]

    def pin(self, job_id: str) -> None:
        with self._lock:
            self._pinned.add(job_id)

    def unpin(self, job_id: str) -> None:
        with self._lock:
            self._pinned.discard(job_id)

    def released(self, result: AnalysisResult) -> AnalysisResult:
        """``result`` without its data, forgotten here: its plot was released to free RAM. The
        record (input, parameters, coverage) stays with the plot, so it can say what it showed
        and reload exactly that."""
        self.discard(result.job_id)
        return replace(result, data=None)

    def __len__(self) -> int:
        return len(self._results)
