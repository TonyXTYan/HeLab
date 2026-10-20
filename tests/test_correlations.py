"""g² pair correlations (D12, D13): counts against brute force, a simulated thermal source's
bunching, an uncorrelated source, back-to-back pairs, Live updates, the cache, cancellation,
the time budget and the speed."""
from __future__ import annotations

import itertools
import json
import math
import time
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from helab.analysis.correlations import (CacheKey, CorrelationResult, CorrelationSpec, InShot, PairCounts,
                                         ShotEvents, correlate, g2_from_counts, in_shot_counts, linear_edges,
                                         radial_edges)
from helab.analysis.results import Cancelled

Array = npt.NDArray[np.float64]
SIGMA_C = 0.1  # the thermal source's g² − 1 = exp(−Δ²/2σ_c²)
CLOUD = 0.4  # its envelope's σ on each axis
MODES = 512  # plane waves per shot in the simulated field


def thermal_shots(seed: int, shots: int = 40, events: int = 400) -> list[ShotEvents]:
    """A chaotic (thermal) source: per shot, a complex Gaussian random field ψ (a sum of
    ``MODES`` plane waves with k ~ N(0, 1/(2σ_c²)) per axis and circular Gaussian
    amplitudes), and events drawn as a Cox process with density ∝ envelope × |ψ|² (rejection
    sampling of Gaussian-envelope candidates). Then ⟨|ψ(x)|²|ψ(y)|²⟩ = 1 + |g¹|² (Isserlis)
    with |g¹(Δ)|² = exp(−Δ²/2σ_c²): g²(0) = 2. A finite number of plane waves adds
    (1 − |g¹|²)/MODES to g² (the field has MODES degrees of freedom): ``expected_peak``."""
    rng = np.random.default_rng(seed)
    k_sigma = 1 / (math.sqrt(2) * SIGMA_C)
    bound = 12.0  # |ψ|² is exponential with mean 1: P(> 12) = 6·10⁻⁶
    result = []
    for shot in range(shots):
        k = rng.normal(0, k_sigma, (MODES, 3)).astype(np.float32)
        real, imag = (rng.normal(size=(2, MODES)) / math.sqrt(2 * MODES)).astype(np.float32)
        candidates = rng.normal(0, CLOUD, (rng.poisson(events * bound), 3))
        phase = candidates.astype(np.float32) @ k.T
        cos, sin = np.cos(phase), np.sin(phase)
        re, im = cos @ real - sin @ imag, cos @ imag + sin @ real
        keep = rng.random(len(candidates)) * bound < (re * re + im * im)
        result.append(ShotEvents(shot, (shot, 0, 0), candidates[keep]))
    return result


def expected_peak() -> float:
    """g²(0) the estimator should give on ``thermal_shots``: 2 over the mean of g² over all
    pairs, 1 + β + (1 − β)/MODES, with β = ∫(g² − 1)A / ∫A = (σ_c²/(σ_c² + 2σ²))^{3/2} the
    peak's share of pairs (A the envelope's autocorrelation; module docstring)."""
    beta = (SIGMA_C ** 2 / (SIGMA_C ** 2 + 2 * CLOUD ** 2)) ** 1.5
    return float(2 / (1 + beta + (1 - beta) / MODES))


def poisson_shots(seed: int, shots: int, events: int, sigma: float = CLOUD) -> list[ShotEvents]:
    rng = np.random.default_rng(seed)
    return [ShotEvents(shot, (shot, 0, 0), rng.normal(0, sigma, (int(rng.poisson(events)), 3)))
            for shot in range(shots)]


def pair_shots(seed: int, shots: int = 30, pairs: int = 150, background: int = 150, width: float = 0.01,
               origin: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> list[ShotEvents]:
    """Back-to-back pairs from a source at ``origin``: u isotropic on a sphere of radius 0.3
    (a halo), the partner at −u, each event blurred by ``width``; plus uncorrelated events
    on the same halo."""
    rng = np.random.default_rng(seed)

    def sphere(n: int) -> Array:
        u = rng.normal(size=(n, 3))
        return 0.3 * u / np.linalg.norm(u, axis=1, keepdims=True)
    result = []
    centre = np.asarray(origin)
    for shot in range(shots):
        u = sphere(pairs)
        events = np.concatenate([centre + u, centre - u]) + rng.normal(0, width, (2 * pairs, 3))
        events = np.concatenate([events, centre + sphere(background)])
        result.append(ShotEvents(shot, (shot, 0, 0), events[rng.permutation(len(events))]))
    return result


@pytest.fixture(scope="module")
def thermal() -> list[ShotEvents]:
    return thermal_shots(1)


def check_peak(result: CorrelationResult, expected: float) -> None:
    assert result.ok, result.failure
    assert result.fit is not None and result.fit.ok, result.fit
    zero = result.g2_zero
    assert math.isfinite(zero.se) and 0 < zero.se < 0.15
    assert abs(zero.value - expected) < 3 * zero.se, (zero, expected)
    assert abs(zero.value - 2) < 0.15


# ---- counts against brute force ----

def brute_values(spec: CorrelationSpec, a: Array, b: Array, same: bool) -> list[float]:
    """Every ordered pair's histogrammed value, by a double loop."""
    origin2 = 2 * np.asarray(spec.origin or (0.0, 0.0, 0.0))
    values = []
    for i, j in itertools.product(range(len(a)), range(len(b))):
        if same and i == j:
            continue
        d = (a[i] + b[j]) - origin2 if spec.mode == "bb" else a[i] - b[j]
        if spec.geometry == "1d":
            others = [x for x in range(3) if x != spec.axis]
            if all(abs(d[x]) <= spec.window for x in others):
                values.append(float(d[spec.axis]))
        else:
            values.append(float(np.sqrt((d * d).sum())))
    return values


def brute_hist(spec: CorrelationSpec, values: list[float]) -> npt.NDArray[np.int64]:
    return np.histogram(np.asarray(values), bins=np.asarray(spec.edges))[0].astype(np.int64)


SPECS = [CorrelationSpec("1d", linear_edges(-0.5, 0.5, 10), window=0.3),
         CorrelationSpec("1d", linear_edges(-0.2, 0.7, 9), axis=2, window=0.25, mode="bb", origin=(0.1, -0.2, 0.05)),
         CorrelationSpec("radial", linear_edges(0, 0.8, 8)),
         CorrelationSpec("radial", radial_edges(0.9, 6), mode="bb"),
         CorrelationSpec("radial", linear_edges(0, 0.8, 8), partners=2)]


@pytest.mark.parametrize("spec", SPECS, ids=lambda spec: f"{spec.geometry}-{spec.mode}-{spec.partners}")
def test_counts_match_brute_force(spec: CorrelationSpec) -> None:
    shots = poisson_shots(3, 7, 25, sigma=0.4)
    shots[2] = ShotEvents(2, (2, 0, 0), np.vstack([shots[2].events, [[math.nan, 0, 0]]]))  # left out
    shots[4] = ShotEvents(4, (4, 0, 0), shots[4].events[:1])  # one event: no in-shot pairs
    state = PairCounts(spec)
    state.update(shots)
    h_in, p_in, cross, q = state.arrays()
    events = [s.events[np.all(np.isfinite(s.events), axis=1)] for s in shots]
    partners = spec.partners or len(shots)
    for index, own in enumerate(events):
        assert np.array_equal(h_in[index], brute_hist(spec, brute_values(spec, own, own, True)))
        assert p_in[index] == len(own) * (len(own) - 1)
        others = [t for t in range(len(shots)) if t != index and abs(t - index) <= partners]
        values = [v for t in others for v in brute_values(spec, own, events[t], False)]
        assert np.array_equal(cross[index], brute_hist(spec, values))
        assert q[index] == sum(len(own) * len(events[t]) for t in others)
    assert np.array_equal(in_shot_counts(spec, shots[0].events).counts, h_in[0])


# ---- the physics ----

def test_thermal_source_bunches_to_two_radially(thermal: list[ShotEvents]) -> None:
    result = correlate(thermal, CorrelationSpec("radial", linear_edges(0, 0.4, 40)))
    check_peak(result, expected_peak())
    assert result.fit is not None
    sigma = result.fit["sigma"]
    assert abs(sigma.value - SIGMA_C) < max(3 * sigma.se, 0.01)
    assert result.se_method == "shot bootstrap" and result.bootstrap is not None
    far = result.centres > 4 * SIGMA_C
    assert np.allclose(result.g2[far], 1, atol=0.05)


def test_thermal_source_bunches_to_two_in_one_dimension(thermal: list[ShotEvents]) -> None:
    window = 0.15 * SIGMA_C
    result = correlate(thermal, CorrelationSpec("1d", linear_edges(-0.4, 0.4, 40), axis=1, window=window))
    # A Gaussian peak averaged over the two transverse windows: 1 − w²/(6σ_c²) on each.
    diluted = 1 + (expected_peak() - 1) * (1 - window ** 2 / (6 * SIGMA_C ** 2)) ** 2
    check_peak(result, diluted)
    assert result.fit is not None
    centre = result.fit["centre"]
    assert abs(centre.value) < 3 * centre.se + 1e-3
    # CL pairs are counted from both events: the histogram is symmetric.
    assert np.array_equal(result.in_counts, result.in_counts[::-1])
    assert np.array_equal(result.between_counts, result.between_counts[::-1])


def test_uncorrelated_source_gives_one() -> None:
    shots = poisson_shots(5, 30, 400)
    for spec in (CorrelationSpec("radial", linear_edges(0, 0.4, 20)),
                 CorrelationSpec("1d", linear_edges(-0.4, 0.4, 20), window=0.05)):
        result = correlate(shots, spec)
        assert result.ok
        pulls = (result.g2 - 1) / result.se
        assert np.mean(np.abs(pulls) < 3) >= 0.9, pulls
        weights = 1 / result.se ** 2
        mean = float(np.sum(weights * result.g2) / np.sum(weights))
        assert abs(mean - 1) < 3 / math.sqrt(float(np.sum(weights))) + 0.01
        assert result.fit is not None
        if result.fit.ok:
            amplitude = result.fit["amplitude"]
            assert abs(amplitude.value) < 3 * amplitude.se + 0.05


def test_back_to_back_pairs_peak_at_zero_and_twice_an_unknown_origin() -> None:
    edges = linear_edges(-0.1, 0.1, 40)
    centred = correlate(pair_shots(7), CorrelationSpec("1d", edges, mode="bb", window=0.01), n_boot=200)
    assert centred.fit is not None and centred.fit.ok
    assert centred.g2_zero.value - 1 > 10 * centred.g2_zero.se  # a clear pair peak
    assert abs(centred.fit["centre"].value) < 0.003
    # The pair width per event is 0.01, so v1 + v2 has σ = 0.01·√2 on each axis.
    assert abs(centred.fit["sigma"].value - 0.01 * math.sqrt(2)) < 0.003
    # Collinear on the same events: no peak at 0.
    collinear = correlate(pair_shots(7), CorrelationSpec("1d", edges, window=0.01), n_boot=0, fit=False)
    assert collinear.g2[len(edges) // 2 - 1] < 1.5

    delta = (0.02, 0.0, 0.0)
    moved = pair_shots(7, origin=delta)
    unknown = correlate(moved, CorrelationSpec("1d", edges, mode="bb", window=0.01), n_boot=200)
    assert unknown.fit is not None and unknown.fit.ok
    assert abs(unknown.fit["centre"].value - 2 * delta[0]) < 0.003
    assert any("centred on the source" in note for note in unknown.notes)
    known = correlate(moved, CorrelationSpec("1d", edges, mode="bb", window=0.01, origin=delta), n_boot=200)
    assert known.fit is not None and abs(known.fit["centre"].value) < 0.003


def test_back_to_back_radial_peaks_at_zero() -> None:
    result = correlate(pair_shots(8), CorrelationSpec("radial", linear_edges(0, 0.08, 16), mode="bb"), n_boot=200)
    assert result.ok and result.fit is not None and result.fit.ok
    assert result.g2_zero.value - 1 > 10 * result.g2_zero.se
    assert result.g2[0] > 1.5 and abs(result.g2[-1] - 1) < 0.2


# ---- Live: incremental updates and the cache ----

def same_counts(a: PairCounts, b: PairCounts) -> bool:
    first, second = a.arrays(), b.arrays()
    order = [a.shots.index(shot) for shot in b.shots]
    return all(np.array_equal(x[order], y) for x, y in zip(first, second))


@pytest.mark.parametrize("partners", [None, 3])
def test_incremental_updates_equal_a_full_recompute(partners: int | None) -> None:
    spec = CorrelationSpec("1d", linear_edges(-0.3, 0.3, 30), window=0.03, partners=partners)
    shots = poisson_shots(11, 25, 300)
    live = PairCounts(spec)
    live.update(shots[:10])
    live.update(shots[:17])
    live.update(shots)
    full = PairCounts(spec)
    full.update(shots)
    assert same_counts(live, full)
    first = g2_from_counts(live, n_boot=50)
    second = g2_from_counts(full, n_boot=50)
    assert np.array_equal(first.g2, second.g2, equal_nan=True)
    # A shot read again (new fingerprint and events) and one gone.
    changed = list(shots)
    changed[5] = ShotEvents(5, (5, 1, 0), np.random.default_rng(99).normal(0, CLOUD, (280, 3)))
    del changed[12]
    live.update(changed)
    fresh = PairCounts(spec)
    fresh.update(changed)
    assert same_counts(live, fresh)
    assert np.array_equal(g2_from_counts(live, n_boot=0).g2, g2_from_counts(fresh, n_boot=0).g2, equal_nan=True)


def test_radial_remove_equals_recompute() -> None:
    spec = CorrelationSpec("radial", linear_edges(0, 0.2, 10), mode="bb", origin=(0.01, 0.0, -0.02))
    shots = poisson_shots(12, 13, 200)
    live = PairCounts(spec)
    live.update(shots)
    for shot in (0, 7, 12):
        live.remove(shot)
    fresh = PairCounts(spec)
    fresh.update([s for s in shots if s.shot not in (0, 7, 12)])
    assert same_counts(live, fresh)
    with pytest.raises(KeyError):
        live.remove(0)
    with pytest.raises(ValueError):
        live.add(shots[1])


def test_in_shot_counts_are_cached_by_fingerprint() -> None:
    spec = CorrelationSpec("1d", linear_edges(-0.3, 0.3, 30), window=0.03)
    shots = poisson_shots(13, 8, 300)
    cache: dict[CacheKey, InShot] = {}
    first = correlate(shots, spec, cache=cache, n_boot=0)
    assert set(cache) == {(s.shot, s.fingerprint, spec.key()) for s in shots}
    state = PairCounts(spec, cache)
    second = correlate(shots, spec, state=state, n_boot=0)
    assert state.cache_hits == len(shots)
    assert np.array_equal(first.in_counts, second.in_counts)
    # Another binning, events key or window is another key; partners aren't part of it.
    assert CorrelationSpec("1d", spec.edges, window=0.04).key() != spec.key()
    assert CorrelationSpec("1d", spec.edges, window=0.03, events_key="t_r=0.4").key() != spec.key()
    assert CorrelationSpec("1d", spec.edges, window=0.03, partners=4).key() == spec.key()
    with pytest.raises(ValueError):
        correlate(shots, CorrelationSpec("1d", spec.edges, window=0.04), state=state)


# ---- cancellation and the time budget ----

def test_cancellation_stops_and_leaves_the_state_as_it_was() -> None:
    spec = CorrelationSpec("radial", linear_edges(0, 0.3, 10))
    shots = poisson_shots(14, 6, 5000)
    polls = 0

    def cancelled() -> bool:
        nonlocal polls
        polls += 1
        return polls > 4
    with pytest.raises(Cancelled):
        correlate(shots, spec, cancelled=cancelled)
    state = PairCounts(spec)
    state.update(shots[:2])
    before = [array.copy() for array in state.arrays()]
    polls = 0

    def inside_the_add() -> bool:
        nonlocal polls
        polls += 1
        return polls > 2  # past the add's own check: inside the pair loop
    with pytest.raises(Cancelled):
        state.add(shots[2], inside_the_add)
    assert state.shots == (0, 1)
    assert all(np.array_equal(a, b) for a, b in zip(before, state.arrays()))
    with pytest.raises(Cancelled):
        g2_from_counts(state, cancelled=lambda: True)


def test_time_budget_reports_partial_coverage_and_continues() -> None:
    spec = CorrelationSpec("1d", linear_edges(-0.3, 0.3, 30), window=0.03)
    shots = poisson_shots(15, 12, 300)
    ticks = itertools.count()

    def clock() -> float:
        return float(next(ticks))  # each add costs one "second"
    state = PairCounts(spec)
    partial = correlate(shots, spec, state=state, budget=5, clock=clock, n_boot=0)
    assert not partial.complete
    # The clock is read at the start and before each add: 4 adds fit in 5 "seconds".
    assert partial.shots_used == tuple(range(4)) and partial.shots_total == 12
    assert any("time budget" in note for note in partial.notes)
    alone = correlate(shots[:4], spec, n_boot=0)
    assert alone.complete
    assert np.array_equal(partial.g2, alone.g2, equal_nan=True)  # those shots' g², not a mix
    finished = correlate(shots, spec, state=state, n_boot=0)
    assert finished.complete
    assert np.array_equal(finished.g2, correlate(shots, spec, n_boot=0).g2, equal_nan=True)
    none = correlate(shots, spec, budget=0, clock=lambda: 0.0, n_boot=0)
    assert not none.ok and none.shots_used == ()


# ---- notes, failures and the record ----

def test_failures_and_notes_never_raise() -> None:
    spec = CorrelationSpec("radial", linear_edges(0, 0.1, 5))
    empty = correlate([], spec)
    assert empty.failure == "no shots"
    one = correlate(poisson_shots(16, 1, 50), spec)
    assert "at least 2 shots" in one.failure
    blank = correlate([ShotEvents(0, 0, np.empty((0, 3))), ShotEvents(1, 1, np.full((3, 3), math.nan))], spec)
    assert not blank.ok and any("fewer than 2 events" in note for note in blank.notes)
    far = correlate(poisson_shots(16, 4, 30, sigma=100.0), CorrelationSpec("radial", linear_edges(0, 1e-3, 5)))
    assert far.failure == "no in-shot pairs in range"
    sparse = correlate(poisson_shots(16, 6, 30, sigma=0.3), CorrelationSpec("radial", linear_edges(0, 0.1, 5)))
    assert any("in-shot pairs in range" in note for note in sparse.notes)
    for result in (empty, one, blank, far, sparse):
        json.dumps(result.as_record(), allow_nan=False)
    with pytest.raises(ValueError):
        PairCounts(spec).update([ShotEvents(0, 0, np.zeros((2, 3))), ShotEvents(0, 1, np.zeros((2, 3)))])
    with pytest.raises(ValueError):
        in_shot_counts(spec, np.zeros((4, 2)))


def test_record_is_strict_json(thermal: list[ShotEvents]) -> None:
    result = correlate(thermal[:10], CorrelationSpec("radial", linear_edges(0, 0.4, 10), partners=3), n_boot=100)
    record: dict[str, Any] = json.loads(json.dumps(result.as_record(), allow_nan=False))
    assert record["spec"]["partners"] == 3 and record["se_method"] == "shot bootstrap"
    assert record["shots_used"] == list(range(10)) and record["fit"]["model"] == "g2_gaussian_centred"
    assert len(record["g2"]) == 10 and record["in_pairs"] == sum(
        len(s.events) * (len(s.events) - 1) for s in thermal[:10])
    with pytest.raises(ValueError):
        result.g2[0] = 0.0


@pytest.mark.parametrize("kwargs", [
    {"geometry": "1d", "edges": (0.0, 1.0)},  # no window
    {"geometry": "1d", "edges": (0.0, 1.0), "window": 0.1, "axis": 3},
    {"geometry": "radial", "edges": (-0.1, 1.0)},
    {"geometry": "radial", "edges": (1.0, 1.0)},
    {"geometry": "radial", "edges": (0.0,)},
    {"geometry": "radial", "edges": (0.0, 1.0), "origin": (0.0, 0.0, 0.0)},  # an origin is for BB
    {"geometry": "radial", "edges": (0.0, 1.0), "mode": "bb", "origin": (0.0, 0.0)},
    {"geometry": "radial", "edges": (0.0, 1.0), "partners": 0},
    {"geometry": "cube", "edges": (0.0, 1.0)},
])
def test_spec_validation(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        CorrelationSpec(**kwargs)


def test_radial_centres_and_edges() -> None:
    spec = CorrelationSpec("radial", radial_edges(1.0, 4))
    edges = np.asarray(spec.edges)
    assert np.allclose(np.diff(edges ** 3), 0.25)  # equal shell volumes
    assert spec.centres[0] == pytest.approx(0.75 * edges[1])  # ¾ r for a full ball
    assert np.all((spec.centres > edges[:-1]) & (spec.centres < edges[1:]))


# ---- speed ----

def test_fifty_shots_of_two_thousand_events_take_seconds() -> None:
    shots = poisson_shots(17, 50, 2000, sigma=1.0)
    for spec in (CorrelationSpec("1d", linear_edges(-0.3, 0.3, 30), window=0.02),
                 CorrelationSpec("radial", linear_edges(0, 0.3, 30))):
        start = time.perf_counter()
        result = correlate(shots, spec)
        elapsed = time.perf_counter() - start
        assert result.ok
        # A few seconds on an idle machine (notes.md); generous for a loaded test run.
        assert elapsed < 20, f"{spec.geometry}: {elapsed:.1f} s"
