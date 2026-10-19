"""Error bars by resampling shots (D10): the shot bootstrap.

Shots are the independent units of a run (atom number, alignment and noise vary from shot to
shot; events within a shot are not independent of each other's shot), so the bootstrap
resamples whole shots: ``bootstrap_shots(shots, statistic)`` draws ``len(shots)`` shots with
replacement ``n_boot`` times, recomputes ``statistic`` on each draw, and gives the spread of
those replicates as the statistic's standard error, with a percentile interval (Efron &
Tibshirani 1993, ch. 6 and 13).

- ``statistic`` takes a list of per-shot arrays (any shapes: events, per-shot numbers) and
  returns a number or a 1D array of numbers (transfer fractions per order). It should return
  nan for a draw where it's undefined (a fit that failed): such replicates are counted, left
  out and noted, never raised.
- Seeded: the same seed, shots and statistic give the same result (``numpy.random.default_rng``),
  so Live reruns on unchanged data keep their error bars, and the seed goes in the record.
- ``cancelled`` is polled between resamples (an ``AnalysisContext``'s ``cancelled``); it
  raises ``results.Cancelled``, as ``stats.auto_crop`` does.
- Fewer than ``MIN_SHOTS`` shots: the resamples can't show the spread well (with n shots
  there are only C(2n−1, n) distinct draws, and the bootstrap SE is √((n−1)/n) of the usual
  one); noted. Fewer than 2: no error at all, a failure.

For a weighted mean over shots, ``estimates.sewm`` gives the SE directly, with no resampling.
Pure NumPy, no Qt.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np
import numpy.typing as npt

from helab.analysis.estimates import Estimate, finite_or_none
from helab.analysis.results import Cancelled

Array = npt.NDArray[np.float64]
Statistic = Callable[[list[Any]], npt.ArrayLike]
# 1000 resamples: the SE's own relative error is about 1/√(2·n_boot) ≈ 2 %, and a 68 %
# percentile interval's ends are stable to a few %; 200 would do for the SE alone.
DEFAULT_N_BOOT = 1000
DEFAULT_SEED = 0
# The percentile interval's coverage: ±1σ of a normal, to match an SE error bar.
DEFAULT_CONFIDENCE = 0.6827
MIN_SHOTS = 5
FAILED_SHARE_NOTE = 0.05  # replicates that were undefined, as a share, before a note


@dataclass(frozen=True)
class BootstrapResult:
    """The statistic on all shots and its bootstrap spread. Arrays have the statistic's shape
    (0-d for a number), read-only; ``replicates`` is (done, *shape), undefined ones nan.
    ``failure`` is "" when the SE can be used."""
    value: Array
    se: Array
    low: Array
    high: Array
    replicates: Array = field(repr=False)
    shots: int
    n_boot: int
    seed: int | None
    confidence: float
    undefined: npt.NDArray[np.int64] = field(repr=False)  # per element: replicates that were nan or infinite
    failure: str = ""
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for array in (self.value, self.se, self.low, self.high, self.replicates, self.undefined):
            array.flags.writeable = False

    @property
    def ok(self) -> bool:
        return not self.failure

    def estimate(self, index: int | None = None) -> Estimate:
        """One element as an ``Estimate`` (the value on all shots ± the bootstrap SE): the
        statistic for a number, ``index`` for an array."""
        if index is None:
            if self.value.ndim:
                raise ValueError("the statistic is an array: pass an index")
            return Estimate(float(self.value), float(self.se))
        return Estimate(float(self.value.ravel()[index]), float(self.se.ravel()[index]))

    @property
    def estimates(self) -> tuple[Estimate, ...]:
        return tuple(Estimate(float(v), float(s)) for v, s in zip(self.value.ravel(), self.se.ravel()))

    def as_record(self) -> dict[str, Any]:
        """Strict JSON for a result's record (the replicates left out)."""
        def listed(array: Array) -> Any:
            if array.ndim == 0:
                return finite_or_none(float(array))
            return [finite_or_none(float(x)) for x in array.ravel()]
        return {"value": listed(self.value), "se": listed(self.se), "low": listed(self.low), "high": listed(self.high),
                "shots": self.shots, "n_boot": self.n_boot, "seed": self.seed, "confidence": self.confidence,
                "undefined": [int(x) for x in self.undefined.ravel()], "failure": self.failure,
                "notes": list(self.notes), "method": "shot bootstrap, percentile interval"}


def _as_values(result: npt.ArrayLike) -> Array:
    values = np.asarray(result, dtype=np.float64)
    if values.ndim > 1:
        raise ValueError("the statistic must return a number or a 1D array")
    return values


def bootstrap_shots(shots: Sequence[Any], statistic: Statistic, n_boot: int = DEFAULT_N_BOOT,
                    seed: int | None = DEFAULT_SEED, confidence: float = DEFAULT_CONFIDENCE,
                    cancelled: Callable[[], bool] | None = None) -> BootstrapResult:
    """The shot bootstrap of ``statistic`` over ``shots`` (see the module docstring). The
    SE is the replicates' standard deviation (ddof 1) and the interval their
    (1 ∓ confidence)/2 percentiles, both over the defined replicates; nan when fewer than 2
    are defined. ``seed`` None draws fresh entropy (recorded as None: not reproducible)."""
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    if n_boot < 2:
        raise ValueError("n_boot must be at least 2")
    pool = list(shots)
    count = len(pool)
    if cancelled is not None and cancelled():
        raise Cancelled()
    value = _as_values(statistic(pool)) if count else np.asarray(math.nan)
    shape = value.shape
    nan = np.full(shape, math.nan)

    def result(replicates: Array, failure: str = "", notes: tuple[str, ...] = ()) -> BootstrapResult:
        defined = np.isfinite(replicates)
        undefined = np.asarray((~defined).sum(axis=0), dtype=np.int64) if len(replicates) else np.zeros(shape, np.int64)
        if len(replicates) and not failure:
            se, low, high = (np.full(shape, math.nan) for _ in range(3))
            for index in np.ndindex(shape):
                column = replicates[(slice(None), *index)]
                column = column[np.isfinite(column)]
                if len(column) >= 2:
                    se[index] = float(np.std(column, ddof=1))
                    low[index], high[index] = np.quantile(column, [(1 - confidence) / 2, (1 + confidence) / 2])
        else:
            se, low, high = nan.copy(), nan.copy(), nan.copy()
        return BootstrapResult(value.copy(), se, low, high, replicates, count, int(n_boot), seed, float(confidence),
                               undefined, failure, notes)

    if count < 2:
        return result(np.empty((0, *shape)), f"needs at least 2 shots for an error, has {count}")
    rng = np.random.default_rng(seed)
    replicates = np.empty((n_boot, *shape))
    for round_index in range(n_boot):
        if cancelled is not None and cancelled():
            raise Cancelled()
        draw = rng.integers(0, count, count)
        replicate = _as_values(statistic([pool[i] for i in draw]))
        if replicate.shape != shape:
            raise ValueError(f"the statistic returned shape {replicate.shape} on a resample, {shape} on all shots")
        replicates[round_index] = replicate
    notes: list[str] = []
    if count < MIN_SHOTS:
        notes.append(f"only {count} shots: the bootstrap error is rough below {MIN_SHOTS}")
    undefined = int((~np.isfinite(replicates)).any(axis=tuple(range(1, replicates.ndim))).sum()) \
        if replicates.ndim > 1 else int((~np.isfinite(replicates)).sum())
    if undefined > FAILED_SHARE_NOTE * n_boot:
        notes.append(f"the statistic was undefined on {undefined:,} of {n_boot:,} resamples, left out")
    return result(replicates, notes=tuple(notes))
