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
  one); noted. Fewer than 2: no error at all, a failure. A statistic undefined on all shots,
  or on all but one resample, has no error either: a failure (per element for an array,
  ``BootstrapResult.failures``).

For a weighted mean over shots, ``estimates.sewm`` gives the SE directly, with no resampling;
``shot_means`` does that per element for a per-shot statistic with many elements (D5's mean X
per T bin: each shot's mean per bin, weighted by its events there). Pure NumPy, no Qt.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np
import numpy.typing as npt

from helab.analysis.estimates import Estimate, finite_or_none, sewm
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
    ``failure`` is "" when the SE can be used: it is set when there are fewer than 2 shots,
    or no element has both a value on all shots and an SE. ``failures`` says the same per
    element (flattened; "" where usable), for an array statistic some of whose elements have
    no error (an order with no events)."""
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
    failures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for array in (self.value, self.se, self.low, self.high, self.replicates, self.undefined):
            array.flags.writeable = False

    @property
    def ok(self) -> bool:
        return not self.failure

    @property
    def usable(self) -> npt.NDArray[np.bool_]:
        """Per element (the statistic's shape): a value on all shots with an SE."""
        return np.asarray(np.isfinite(self.value) & np.isfinite(self.se))

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
                "failures": list(self.failures), "notes": list(self.notes),
                "method": "shot bootstrap, percentile interval"}


def _as_values(result: npt.ArrayLike) -> Array:
    values = np.asarray(result, dtype=np.float64)
    if values.ndim > 1:
        raise ValueError("the statistic must return a number or a 1D array")
    return values


def _fit_shape(values: Array, shape: tuple[int, ...], where: str) -> Array:
    """``values`` in ``shape``: a single undefined number (a statistic's ``math.nan`` for "no
    answer") fills an array statistic's every element; any other mismatch is the statistic's
    bug (``ValueError``)."""
    if values.shape == shape:
        return values
    if values.ndim == 0 and not math.isfinite(float(values)):
        return np.full(shape, float(values))
    raise ValueError(f"the statistic returned shape {values.shape} on {where}, {shape} elsewhere")


def bootstrap_shots(shots: Sequence[Any], statistic: Statistic, n_boot: int = DEFAULT_N_BOOT,
                    seed: int | None = DEFAULT_SEED, confidence: float = DEFAULT_CONFIDENCE,
                    cancelled: Callable[[], bool] | None = None) -> BootstrapResult:
    """The shot bootstrap of ``statistic`` over ``shots`` (see the module docstring). The
    SE is the replicates' standard deviation (ddof 1) and the interval their
    (1 ∓ confidence)/2 percentiles, both over the defined replicates; nan when fewer than 2
    are defined (a failure for that element). ``seed`` None draws fresh entropy (recorded as
    None: not reproducible). The statistic may return a plain nan for "undefined" even when
    it otherwise returns an array."""
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    if n_boot < 2:
        raise ValueError("n_boot must be at least 2")
    pool = list(shots)
    count = len(pool)
    if cancelled is not None and cancelled():
        raise Cancelled()
    value = _as_values(statistic(pool)) if count else np.asarray(math.nan)
    outputs: list[Array] = []
    if count >= 2:
        rng = np.random.default_rng(seed)
        for _ in range(n_boot):
            if cancelled is not None and cancelled():
                raise Cancelled()
            draw = rng.integers(0, count, count)
            outputs.append(_as_values(statistic([pool[i] for i in draw])))
    # The shape: the statistic's on all shots, unless that was a plain nan and a resample says.
    shape = value.shape
    if value.ndim == 0 and not math.isfinite(float(value)):
        shape = next((output.shape for output in outputs if output.ndim), shape)
    value = _fit_shape(value, shape, "all shots")
    replicates = np.array([_fit_shape(output, shape, "a resample") for output in outputs]).reshape(-1, *shape)
    se, low, high = (np.full(shape, math.nan) for _ in range(3))
    defined = np.isfinite(replicates)
    undefined = np.asarray((~defined).sum(axis=0), dtype=np.int64)
    element_failures: list[str] = []
    for index in np.ndindex(shape):
        column = replicates[(slice(None), *index)]
        column = column[np.isfinite(column)]
        if count < 2:
            element_failures.append(f"needs at least 2 shots for an error, has {count}")
        elif not math.isfinite(float(value[index])):
            element_failures.append("the statistic is undefined on all shots")
        elif len(column) < 2:
            element_failures.append(f"the statistic was defined on {len(column)} of {n_boot:,} resamples: no error")
        else:
            se[index] = float(np.std(column, ddof=1))
            low[index], high[index] = np.quantile(column, [(1 - confidence) / 2, (1 + confidence) / 2])
            element_failures.append("")
    notes: list[str] = []
    failure = ""
    if element_failures and all(element_failures):
        failure = element_failures[0] if len(set(element_failures)) == 1 else "; ".join(dict.fromkeys(element_failures))
    elif any(element_failures):
        missing = [str(i) for i, text in enumerate(element_failures) if text]
        notes.append(f"no error for element{'s' if len(missing) > 1 else ''} {', '.join(missing)}: "
                     "the statistic was undefined there")
    if 2 <= count < MIN_SHOTS:
        notes.append(f"only {count} shots: the bootstrap error is rough below {MIN_SHOTS}")
    if len(replicates):
        rows = int((~defined.reshape(len(replicates), -1)).any(axis=1).sum())
        if rows > FAILED_SHARE_NOTE * n_boot:
            notes.append(f"the statistic was undefined on {rows:,} of {n_boot:,} resamples, left out")
    return BootstrapResult(value.copy(), se, low, high, replicates, count, int(n_boot), seed, float(confidence),
                           undefined, failure, tuple(notes), tuple(element_failures))


@dataclass(frozen=True)
class ShotMeans:
    """Per element: the weighted mean over shots of a per-shot value ± its SE over shots
    (``estimates.sewm``), and how many shots it used (finite value, finite weight > 0).
    Read-only arrays of the statistic's shape; SE nan with fewer than 2 shots, both nan with
    none."""
    value: Array
    se: Array
    shots: npt.NDArray[np.int64]

    def __post_init__(self) -> None:
        for array in (self.value, self.se, self.shots):
            array.flags.writeable = False

    @property
    def estimates(self) -> tuple[Estimate, ...]:
        return tuple(Estimate(float(v), float(s)) for v, s in zip(self.value.ravel(), self.se.ravel()))


def shot_means(per_shot: npt.ArrayLike, weights: npt.ArrayLike | None = None) -> ShotMeans:
    """The SE over shots of a per-shot mean statistic, without resampling: ``per_shot`` is
    (shots, …), each shot's value per element (nan where it has none: no events in that
    bin), ``weights`` the same shape (each shot's events there; None: equal). Per element,
    ``sewm`` over the shots with a finite value and a finite weight > 0: with weights the
    events, the value is the mean over all the shots' events and the SE includes the shot
    to shot spread (the bootstrap's SE of the same ratio is about √((n−1)/n) of it)."""
    values = np.asarray(per_shot, dtype=np.float64)
    if values.ndim < 1:
        raise ValueError("per_shot must have a shots axis first")
    shares = np.ones_like(values) if weights is None else np.asarray(weights, dtype=np.float64)
    if shares.shape != values.shape:
        raise ValueError("weights must have per_shot's shape")
    shape = values.shape[1:]
    flat_values, flat_weights = values.reshape(len(values), -1), shares.reshape(len(values), -1)
    usable = np.isfinite(flat_values) & np.isfinite(flat_weights) & (flat_weights > 0)
    mean, se = np.full(flat_values.shape[1], math.nan), np.full(flat_values.shape[1], math.nan)
    for index in range(flat_values.shape[1]):
        chosen = usable[:, index]
        estimate = sewm(flat_values[chosen, index], flat_weights[chosen, index])
        mean[index], se[index] = estimate.value, estimate.se
    shots = np.asarray(usable.sum(axis=0), dtype=np.int64).reshape(shape)
    return ShotMeans(mean.reshape(shape), se.reshape(shape), shots)
