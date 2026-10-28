"""An analysis run's input (``AnalysisContext``) and its record (``AnalysisResult``), kept in
RAM (result caching stage R1) and, for a script that supports it, saved in the disk cache and
reused from it on an exact key match (R2: ``helab.analysis.result_cache``).

Each record keeps what a reuse needs (result caching rules 5 and 8): the analysis's ID,
version and file hash, the input's root key and signatures, the effective parameters (JSON
values only) and the coverage: the TXY shots the run used, with their fingerprints
(``Coverage``), so HeLab can tell what a later revision adds (``Coverage.diff``)."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import MappingProxyType
from typing import Any, Iterable, Literal, Mapping

from helab.analysis.constant_layers import record_text
from helab.analysis.dataset_view import DatasetView, Fingerprint, ViewKey
from helab.analysis.identity import AnalysisIdentity
from helab.analysis.masks import mask_key
from helab.analysis.physics import ResolvedConstants
from helab.utils import txy_sources

State = Literal["completed", "failed", "cancelled"]
# Where a result is kept (result caching rule 2): in RAM only, or also in the disk cache (R2).
RAM_ONLY = "ram"
DISK_CACHED = "disk"
# Where a result shown came from: this session's run, or the disk cache (R2).
COMPUTED = ""
FROM_DISK = "disk"


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
    """The TXY shots a run used, ascending, with their fingerprints (those the view knew) and, for
    those read from HeLab's TXY, their origins (Q6.6: ``helab:<profile hash>``)."""
    shots: tuple[int, ...] = ()
    fingerprints: Mapping[int, Fingerprint] = field(default_factory=lambda: MappingProxyType({}))
    origins: Mapping[int, str] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def of(cls, view: DatasetView, shots: Iterable[int] | None = None) -> Coverage:
        """The view's ``shots`` (default: all of them); numbers the view lacks are left out."""
        chosen = tuple(sorted({int(shot) for shot in (view.shots if shots is None else shots)} & set(view.shots)))
        return cls(chosen, MappingProxyType({shot: view.fingerprints[shot] for shot in chosen
                                             if shot in view.fingerprints}),
                   MappingProxyType({shot: view.origins[shot] for shot in chosen if shot in view.origins}))

    def diff(self, view: DatasetView, shots: Iterable[int] | None = None) -> CoverageDiff:
        """``view``'s shots (or those of them chosen) against this coverage."""
        wanted = set(view.shots if shots is None else shots) & set(view.shots)
        covered = set(self.shots)
        changed = [shot for shot in sorted(wanted & covered)
                   if view.fingerprints.get(shot) != self.fingerprints.get(shot)
                   or view.origins.get(shot, "") != self.origins.get(shot, "")]
        return CoverageDiff(tuple(sorted(wanted - covered)), tuple(changed), tuple(sorted(covered - wanted)))

    def text(self) -> str:
        if not self.shots:
            return "no shots"
        count = len(self.shots)
        return f"{count:,} shot{'' if count == 1 else 's'} ({self.shots[0]}–{self.shots[-1]})"

    def to_json(self) -> dict[str, Any]:
        """Origins only when some shot has one: MATLAB's TXY alone keep the key they had."""
        return {"shots": list(self.shots), "fingerprints": [list(self.fingerprints[shot])
                                                           for shot in self.shots if shot in self.fingerprints],
                **({"origins": [[shot, self.origins[shot]] for shot in self.shots if shot in self.origins]}
                   if self.origins else {})}


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
    # The constants the analysis uses (``DatasetAnalysis.constant_keys``), with ``resolved_constants``:
    # the record names these.
    constant_keys: tuple[str, ...] = ()
    # The plot that asked for the run (``AnalysisInstance.instance_id``); "" for a run no plot asked
    # for (tests, scripts). An analysis may keep per-plot state under it (dropped in
    # ``DatasetAnalysis.plot_closed``); it is not part of the result's reuse key.
    owner: str = ""
    # A rerun following Live (the plot's newest revision while Live watches its folder), not one the
    # user asked for: a costly analysis may do less then and say so (the Release time plot skips its
    # bootstrap). Not part of the result's reuse key unless the script puts what it did in
    # ``found["reuse"]``.
    live: bool = False
    # The parameters not in use under ``parameters`` (``parameters.unused_parameters``: rows the
    # settings hide, e.g. a smoothing width with Smooth off): left out of the result's reuse key.
    unused: frozenset[str] = frozenset()
    # A run whose completed result may be saved in the disk cache (result caching R2): the worker
    # then packs its data (``DatasetAnalysis.cache_pack``) into ``AnalysisResult.packed``.
    to_cache: bool = False

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
    constant_keys: tuple[str, ...] = ()
    # What the run found or used beyond its parameters, as JSON values (``DatasetAnalysis.result_found``:
    # fit results, the constants used). Part of the record, kept when the plot is released.
    # Read-only at the top level only (a MappingProxyType over a copy of the script's dict): the
    # lists and dicts inside are shared, so readers must not change them.
    found: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    owner: str = ""  # the plot that asked for the run (``AnalysisContext.owner``)
    # The parameters the run didn't use (``AnalysisContext.unused``): not in ``reuse_key``.
    unused: frozenset[str] = frozenset()
    # ``FROM_DISK``: read back from the disk cache (computed at ``finished_at``, maybe in an earlier
    # session), not computed now; ``outdated`` then says what no longer matches the run asked for
    # (the script, the data, the constants…; empty: an exact match).
    source: str = COMPUTED
    outdated: tuple[str, ...] = ()
    # The data packed for the disk cache (``result_codec.pack``) by the worker, for a run with
    # ``AnalysisContext.to_cache`` that may be saved (``DatasetAnalysis.cache_result``); None
    # otherwise, or once handed to the save. ``packing_error``: why it couldn't be packed.
    packed: bytes | None = field(default=None, compare=False, repr=False)
    packing_error: str = ""

    @classmethod
    def of(cls, context: AnalysisContext, state: State, data: Any = None, error: str = "",
           started_at: float = 0.0, found: Mapping[str, Any] | None = None) -> AnalysisResult:
        return cls(context.job_id, context.action, context.analysis, context.view.key,
                   MappingProxyType(dict(context.parameters)), state, data, error,
                   started_at, time.time(), coverage=context.covered, input_signature=context.view.signature,
                   constant_layers=context.constants, resolved_constants=context.resolved_constants,
                   constant_keys=context.constant_keys if context.resolved_constants is not None else (),
                   found=MappingProxyType(dict(found or {})), owner=context.owner, unused=context.unused)

    @property
    def constants_record(self) -> dict[str, Any] | None:
        """The constants the run used, as JSON values: for an analysis that declares constants
        (``DatasetAnalysis.constant_keys``), its lab and folder layers and what it resolved
        (``ResolvedConstants.as_record``), of its ``constant_keys`` only (all without); None for one
        that doesn't, so a lab or folder change of a value it doesn't use never makes its results
        look different. A layer with none of those keys is left out."""
        if self.resolved_constants is None:
            return None
        keys = set(self.constant_keys) or None
        layers = {name: kept for name, values in self.constant_layers.items()
                  if (kept := {key: value for key, value in values.items() if keys is None or key in keys})}
        return {"layers": layers, **self.resolved_constants.as_record(self.constant_keys or None)}

    def reuse_key(self) -> dict[str, Any]:
        """What a later reuse of this result must match (result caching rule 5), as JSON values: a
        saved result's lookup key (R2, ``result_cache.lookup_key``). What the run decided beyond its parameters and input, which a
        reuse must match too, comes from ``found["reuse"]`` when the script gives it
        (``DatasetAnalysis.result_found``; e.g. a box kept from an earlier run of the plot). The
        parameters are those in use (not ``unused``: a hidden setting never changes the key)."""
        identity = self.input.identity
        return {"analysis_id": self.analysis.analysis_id, "version": self.analysis.version,
                "file_hash": self.analysis.file_hash, "action": self.action, "root_key": identity.root_key,
                "signature": identity.signature, "input_signature": self.input_signature,
                # Which TXY (Q6.6); the default's key is as it was.
                **({"txy_source": identity.source} if identity.source else {}),
                "parameters": {name: value for name, value in self.parameters.items() if name not in self.unused},
                "coverage": self.coverage.to_json(),
                **({"constants": record} if (record := self.constants_record) is not None else {}),
                **({"found": self.found["reuse"]} if "reuse" in self.found else {}),
                **mask_key(self.parameters)}

    def describe(self, parameters_text: str = "") -> str:
        """The record, one item per line, for a plot dock's tooltip."""
        identity = self.input.identity
        lines = [f"{self.analysis.text()} · {self.action}",
                 f"Input: {identity.source_path} · revision {self.input.revision}",
                 f"Data root: {identity.root_key or 'none known'}",
                 f"TXY source: {txy_sources.SHORT.get(identity.source or txy_sources.DEFAULT_SOURCE, identity.source)}"
                 + (f"; {len(self.coverage.origins):,} shots from HeLab's TXY" if self.coverage.origins else ""),
                 f"Signature: {identity.signature[:16] or 'none'}"
                 + (f" (this revision: {self.input_signature[:16]})"
                    if self.input_signature and self.input_signature != identity.signature else ""),
                 f"Covers: {self.coverage.text()}",
                 f"Parameters: {parameters_text or _plain(self.parameters) or 'none'}"]
        if self.resolved_constants is not None:
            lines.append(f"Constants: {record_text(self.resolved_constants, self.constant_keys or None)}")
        when = datetime.fromtimestamp(self.finished_at).strftime("%H:%M:%S") if self.finished_at else ""
        took = f" in {self.finished_at - self.started_at:.1f} s" if self.started_at and self.finished_at else ""
        if self.source == FROM_DISK:
            computed = datetime.fromtimestamp(self.finished_at).strftime("%Y-%m-%d %H:%M") if self.finished_at else "?"
            # Where it is kept now too: a Clear cached analysis after it was shown leaves it in RAM only.
            kept = "in the disk cache" if self.policy == DISK_CACHED else "kept in RAM only"
            lines.append(f"From disk cache, computed {computed}{took} (job {self.job_id}) · {kept}"
                         + (f" · outdated: {'; '.join(self.outdated)}" if self.outdated else ""))
        else:
            kept = "saved in the disk cache" if self.policy == DISK_CACHED else "kept in RAM only"
            lines.append(f"Job {self.job_id} · {self.state} {when}{took} · {kept}")
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
