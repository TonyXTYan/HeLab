"""The shot bootstrap: its SE against the analytic one, reproducibility, cancellation and
its notes."""
from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from helab.analysis.bootstrap import DEFAULT_N_BOOT, bootstrap_shots
from helab.analysis.estimates import sewm
from helab.analysis.results import Cancelled

Array = npt.NDArray[np.float64]


def per_shot_events(seed: int, shots: int) -> list[Array]:
    """Shots of events whose mean varies from shot to shot (the between-shot noise the
    bootstrap is for), with different event counts."""
    rng = np.random.default_rng(seed)
    centres = rng.normal(2.12, 0.002, shots)
    return [rng.normal(centre, 0.001, int(rng.integers(200, 400))) for centre in centres]


def mean_of_shot_means(shots: list[Any]) -> float:
    return float(np.mean([float(np.mean(shot)) for shot in shots]))


def test_se_of_a_mean_over_shots_matches_the_analytic_one() -> None:
    shots = per_shot_events(0, 60)
    means = np.array([np.mean(shot) for shot in shots])
    analytic = sewm(means, np.ones(len(means)))  # s/√n
    result = bootstrap_shots(shots, mean_of_shot_means, n_boot=2000)
    assert result.ok and not result.notes
    assert float(result.value) == pytest.approx(analytic.value)
    # The bootstrap SE is the plug-in one, √((n−1)/n) s/√n.
    assert float(result.se) == pytest.approx(analytic.se, rel=0.1)
    estimate = result.estimate()
    assert (estimate.value, estimate.se) == (float(result.value), float(result.se))
    # The 68 % interval is about ±1 SE.
    assert float(result.high - result.low) == pytest.approx(2 * analytic.se, rel=0.15)
    assert result.replicates.shape == (2000,) and not result.replicates.flags.writeable
    json.dumps(result.as_record(), allow_nan=False)


def test_it_is_reproducible_with_a_seed() -> None:
    shots = per_shot_events(1, 20)
    first = bootstrap_shots(shots, mean_of_shot_means, n_boot=200, seed=42)
    again = bootstrap_shots(shots, mean_of_shot_means, n_boot=200, seed=42)
    other = bootstrap_shots(shots, mean_of_shot_means, n_boot=200, seed=43)
    np.testing.assert_array_equal(first.replicates, again.replicates)
    assert float(first.se) == float(again.se) and float(first.se) != float(other.se)
    assert first.seed == 42 and first.n_boot == 200
    assert bootstrap_shots(shots, mean_of_shot_means, n_boot=10).seed == 0  # seeded by default


def test_an_array_statistic() -> None:
    rng = np.random.default_rng(2)
    shots = [rng.integers(0, 3, 500) for _ in range(30)]  # per event, an order 0, 1 or 2

    def fractions(chosen: list[Any]) -> Array:
        orders = np.concatenate(chosen)
        return np.bincount(orders, minlength=3) / len(orders)

    result = bootstrap_shots(shots, fractions, n_boot=300)
    assert result.value.shape == result.se.shape == (3,)
    assert result.replicates.shape == (300, 3)
    assert len(result.estimates) == 3 and result.estimate(1).value == pytest.approx(float(result.value[1]))
    with pytest.raises(ValueError):
        result.estimate()
    json.dumps(result.as_record(), allow_nan=False)


def test_cancellation_stops_it() -> None:
    calls = 0

    def statistic(chosen: list[Any]) -> float:
        nonlocal calls
        calls += 1
        return float(len(chosen))

    polls = 0

    def cancelled() -> bool:
        nonlocal polls
        polls += 1
        return polls > 5

    with pytest.raises(Cancelled):
        bootstrap_shots([np.zeros(1)] * 10, statistic, n_boot=DEFAULT_N_BOOT, cancelled=cancelled)
    assert calls == 5  # all shots, then 4 resamples before the 6th poll


def test_small_samples_and_undefined_replicates() -> None:
    shots = per_shot_events(3, 3)
    few = bootstrap_shots(shots, mean_of_shot_means, n_boot=100)
    assert few.ok and any("only 3 shots" in note for note in few.notes)
    one = bootstrap_shots(shots[:1], mean_of_shot_means)
    assert not one.ok and "at least 2" in one.failure and math.isnan(float(one.se))
    assert float(one.value) == pytest.approx(mean_of_shot_means(shots[:1]))
    none = bootstrap_shots([], mean_of_shot_means)
    assert not none.ok and math.isnan(float(none.value))
    json.dumps(none.as_record(), allow_nan=False)

    def first_shot_matters(chosen: list[Any]) -> float:  # undefined unless the first shot is drawn
        return mean_of_shot_means(chosen) if any(shot is shots[0] for shot in chosen) else math.nan

    partial = bootstrap_shots(shots, first_shot_matters, n_boot=200)
    assert partial.ok and int(partial.undefined) > 0 and math.isfinite(float(partial.se))
    assert any("undefined" in note for note in partial.notes)


def test_no_error_is_a_failure() -> None:
    shots = list(range(6))
    undefined = bootstrap_shots(shots, lambda chosen: math.nan, n_boot=50)
    assert not undefined.ok and "undefined on all shots" in undefined.failure
    # Defined on all shots but on at most one resample (here: only with every shot drawn).
    rare = bootstrap_shots(shots, lambda chosen: 1.0 if len(set(chosen)) == 6 else math.nan, n_boot=50)
    assert not rare.ok and "resamples: no error" in rare.failure and math.isnan(float(rare.se))
    assert rare.failures == (rare.failure,)
    json.dumps(rare.as_record(), allow_nan=False)


def test_an_array_statistic_may_answer_a_plain_nan() -> None:
    def fractions(chosen: list[Any]) -> Any:
        if 0 not in chosen:
            return math.nan  # no answer, without knowing the shape
        return np.array([len(chosen), math.nan, 1.0])  # element 1 is never defined

    result = bootstrap_shots(list(range(8)), fractions, n_boot=100)
    assert result.value.shape == result.se.shape == (3,) and result.replicates.shape == (100, 3)
    assert result.ok and result.usable.tolist() == [True, False, True]
    assert result.failures[0] == "" and "undefined on all shots" in result.failures[1]
    assert any("no error for element 1" in note for note in result.notes)
    # A plain nan on all shots takes its shape from the resamples, and fails.
    unknown = bootstrap_shots(list(range(8)), lambda chosen: math.nan if len(set(chosen)) == 8 else np.ones(2),
                              n_boot=20)
    assert unknown.value.shape == (2,) and not unknown.ok
    with pytest.raises(ValueError):
        bootstrap_shots(list(range(8)), lambda chosen: np.ones(len(set(chosen)) % 2 + 2), n_boot=20)


def test_bad_arguments_raise() -> None:
    with pytest.raises(ValueError):
        bootstrap_shots([1, 2, 3], lambda chosen: 0.0, confidence=1.5)
    with pytest.raises(ValueError):
        bootstrap_shots([1, 2, 3], lambda chosen: 0.0, n_boot=1)
