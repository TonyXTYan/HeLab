"""TXY → velocity (z up), the release-time detection and its peak finding, on synthetic
events from exact trajectories."""
from __future__ import annotations

import dataclasses
import json
import math

import numpy as np
import numpy.typing as npt
import pytest
import scipy.constants as codata

from helab.analysis import fits, release
from helab.analysis.peaks import find_time_peaks
from helab.analysis.physics import DEFAULTS, ResolvedConstants, resolve
from helab.analysis.release import (bootstrap_release_time, detect_release_time, manual_release_time,
                                    velocity_origin)
from helab.analysis.velocity import (RECOIL_WAVELENGTH, arrival_time, effective_fall_distance, recoil_velocity,
                                     txy_to_velocity, unit_velocity, vertical_velocity)

Array = npt.NDArray[np.float64]
RELEASE = 1.7  # s after the DLD trigger, about the lab's now (lab-parameters.md)


def trajectories(velocities: Array, release: float, constants: ResolvedConstants) -> Array:
    """TXY events of atoms released at ``release`` with (v_z, v_x, v_y), z up: the positive
    root of −h = v_z τ − ½ g τ², then x = v_x τ."""
    vz, vx, vy = velocities[:, 0], velocities[:, 1], velocities[:, 2]
    g, h = constants.g, constants.fall_distance
    tau = (vz + np.sqrt(vz * vz + 2 * g * h)) / g
    return np.column_stack([release + tau, vx * tau, vy * tau])


def cloud(rng: np.random.Generator, count: int, sigma_v: float, release: float = RELEASE,
          constants: ResolvedConstants = DEFAULTS, drift: tuple[float, float, float] = (0, 0, 0)) -> Array:
    velocities = rng.normal(0, sigma_v, (count, 3)) + np.asarray(drift)
    return trajectories(velocities, release, constants)


def test_velocities_are_recovered_exactly_with_z_up() -> None:
    known = np.array([[0.0, 0.0, 0.0], [0.05, 0.01, -0.02], [-0.05, -0.03, 0.04], [0.5, 0.0, 0.0]])
    events = trajectories(known, RELEASE, DEFAULTS)
    result = txy_to_velocity(events, RELEASE, DEFAULTS)
    np.testing.assert_allclose(result.values, known, atol=1e-12)
    assert result.invalid == 0
    # z up: at rest it arrives a fall time after release; thrown up it arrives later.
    assert events[0, 0] == pytest.approx(RELEASE + DEFAULTS.fall_time)
    assert events[1, 0] > events[0, 0] > events[2, 0]
    assert result.values[1, 0] > 0 > result.values[2, 0]
    # The closed form, v_z = ½ g τ − h/τ, and its inverse.
    tau = events[:, 0] - RELEASE
    np.testing.assert_allclose(vertical_velocity(events[:, 0], RELEASE, DEFAULTS),
                               0.5 * DEFAULTS.g * tau - DEFAULTS.fall_distance / tau)
    np.testing.assert_allclose(arrival_time(known[:, 0], RELEASE, DEFAULTS), events[:, 0])
    # Near the fall time v_z ≈ g (τ − t_f): physics.py's σ_v = g σ_t.
    late = vertical_velocity(RELEASE + DEFAULTS.fall_time + 1e-4, RELEASE, DEFAULTS)
    assert float(late) == pytest.approx(DEFAULTS.g * 1e-4, rel=1e-3)


def test_velocities_follow_the_run_s_constants() -> None:
    constants = resolve(folder={"fall_distance": 0.852925545}, lab={"g": 9.81})
    known = np.array([[0.02, 0.003, -0.001]])
    np.testing.assert_allclose(txy_to_velocity(trajectories(known, 2.0, constants), 2.0, constants).values,
                               known, atol=1e-12)
    # With the default constants, the same events give other velocities.
    assert not np.allclose(txy_to_velocity(trajectories(known, 2.0, constants), 2.0, DEFAULTS).values, known)


def test_events_before_the_release_have_no_velocity() -> None:
    events = np.array([[RELEASE - 0.1, 0.0, 0.0], [RELEASE, 0.0, 0.0], [math.nan, 0.0, 0.0],
                       [RELEASE + 0.4, 0.001, 0.0], [RELEASE + 0.4, math.nan, 0.0]])
    events.flags.writeable = False  # a DatasetView's arrays are read-only
    result = txy_to_velocity(events, RELEASE, DEFAULTS)
    assert result.invalid == 4 == int((~result.valid).sum())  # a nan X counts too
    assert np.all(np.isnan(result.values[:3])) and np.all(np.isfinite(result.values[3]))
    assert result.valid.tolist() == [False, False, False, True, False]
    assert not result.values.flags.writeable
    assert np.all(np.isnan(vertical_velocity([RELEASE - 1, RELEASE], RELEASE, DEFAULTS)))
    assert len(txy_to_velocity(np.empty((0, 3)), RELEASE, DEFAULTS)) == 0
    with pytest.raises(ValueError):
        txy_to_velocity(np.zeros((3, 2)), RELEASE, DEFAULTS)


def test_recoil_units() -> None:
    assert RECOIL_WAVELENGTH == pytest.approx(1083.331e-9, rel=1e-6)
    recoil = recoil_velocity(DEFAULTS)
    assert recoil == pytest.approx(codata.h / (RECOIL_WAVELENGTH * DEFAULTS.mass))
    assert recoil == pytest.approx(0.0920, abs=1e-4)  # ≈ 9.2 cm/s for He* at 1083 nm
    known = np.array([[2 * recoil, -recoil, 0.0]])  # a first-order Bragg kick is 2ħk
    result = txy_to_velocity(trajectories(known, RELEASE, DEFAULTS), RELEASE, DEFAULTS)
    np.testing.assert_allclose(result.in_recoils(recoil), [[2, -1, 0]], atol=1e-9)
    assert math.isnan(recoil_velocity(DEFAULTS, 0.0)) and np.all(np.isnan(result.in_recoils(0.0)))
    # Named units: ħk is one photon's recoil, 2ħk one Bragg order.
    assert unit_velocity("m/s", DEFAULTS) == 1.0
    assert unit_velocity("ħk", DEFAULTS) == recoil and unit_velocity("2ħk", DEFAULTS) == 2 * recoil
    np.testing.assert_allclose(result.in_unit("2ħk", DEFAULTS), [[1, -0.5, 0]], atol=1e-9)


def test_velocities_copy_what_they_are_given() -> None:
    from helab.analysis.velocity import Velocities
    mine = np.zeros((2, 3))
    velocities = Velocities(mine, 0, RELEASE, 0.848, 9.8)
    assert mine.flags.writeable and not velocities.values.flags.writeable
    mine[0, 0] = 1.0
    assert velocities.values[0, 0] == 0.0


def test_arrival_time_is_stable_for_fast_atoms() -> None:
    fast = np.array([-1e4, -50.0, -1e-6, 0.0, 1e-6, 50.0, 1e4])
    times = arrival_time(fast, RELEASE, DEFAULTS)
    assert np.all(np.diff(times) > 0)
    np.testing.assert_allclose(vertical_velocity(times, RELEASE, DEFAULTS), fast, rtol=1e-9, atol=1e-12)
    # Thrown down very fast it arrives after about h/|v| (the form without cancellation).
    assert float(times[0]) - RELEASE == pytest.approx(DEFAULTS.fall_distance / 1e4, rel=1e-3)


def test_a_fall_time_set_by_hand_keeps_the_reference_cloud_at_rest() -> None:
    by_hand = resolve(folder={"fall_distance": 0.848, "fall_time": 0.417})
    assert by_hand.notes  # they disagree: √(2h/g) is 0.4161 s
    assert effective_fall_distance(by_hand) == pytest.approx(0.5 * by_hand.g * 0.417 ** 2)
    assert effective_fall_distance(DEFAULTS) == DEFAULTS.fall_distance
    # The atoms really fall 0.848 m; the detection subtracts the hand-set 0.417 s.
    events = cloud(np.random.default_rng(2), 20_000, 0.003)
    release = detect_release_time(events[:, 0], by_hand)
    velocities = txy_to_velocity(events, release.value.value, by_hand)
    assert velocities.fall_distance_from_time and velocities.fall_distance == effective_fall_distance(by_hand)
    assert abs(float(np.mean(velocities.values[:, 0]))) < 1e-4  # with h itself: +8.9 mm/s
    assert float(vertical_velocity(release.arrival.value, release.value.value, by_hand)) == pytest.approx(0, abs=1e-12)
    assert not txy_to_velocity(events, release.value.value, DEFAULTS).fall_distance_from_time


def test_peaks_of_two_clouds_tallest_first() -> None:
    rng = np.random.default_rng(1)
    times = np.concatenate([rng.normal(2.10, 0.001, 3000), rng.normal(2.13, 0.001, 6000),
                            rng.uniform(1.9, 2.3, 300)])
    search = find_time_peaks(times)
    assert len(search.peaks) == 2
    assert search.peaks[0].position == pytest.approx(2.13, abs=1e-4)
    assert search.peaks[1].position == pytest.approx(2.10, abs=1e-4)
    assert search.peaks[0].fwhm == pytest.approx(2.3548e-3, rel=0.2)
    assert not search.counts.flags.writeable
    assert find_time_peaks(np.empty(0)).peaks == ()


@pytest.mark.parametrize("seed", range(4))
def test_release_time_is_recovered_within_its_se(seed: int) -> None:
    rng = np.random.default_rng(seed)
    events = cloud(rng, 20_000, 0.003)  # a cold cloud: σ_t = σ_v / g ≈ 0.3 ms
    background = rng.uniform(1.9, 2.4, 500)
    found = detect_release_time(np.concatenate([events[:, 0], background]), DEFAULTS)
    assert found.ok, found.failure
    assert found.source == "detected" and not found.unsure
    assert found.value.se == pytest.approx(0.003 / DEFAULTS.g / math.sqrt(20_000), rel=0.3)
    assert abs(found.value.value - RELEASE) < 3 * found.value.se
    assert found.arrival.value - found.value.value == pytest.approx(DEFAULTS.fall_time)
    assert found.width.value == pytest.approx(0.003 / DEFAULTS.g, rel=0.05)
    assert found.fit is not None and found.fit.ok
    json.dumps(found.as_record(), allow_nan=False)


def test_release_time_uses_the_run_s_fall_time() -> None:
    constants = resolve(folder={"fall_distance": 0.852925545})
    events = cloud(np.random.default_rng(7), 10_000, 0.003, constants=constants)
    found = detect_release_time(events[:, 0], constants)
    assert abs(found.value.value - RELEASE) < 3 * found.value.se
    assert found.fall_time == constants.fall_time
    # The default fall distance moves it by the fall times' difference, a systematic error.
    other = detect_release_time(events[:, 0], DEFAULTS)
    assert other.value.value - found.value.value == pytest.approx(constants.fall_time - DEFAULTS.fall_time)


def test_a_wide_cloud_is_fitted_with_the_arrival_time_profile() -> None:
    """A 1.5 µK cloud (σ_t ≈ 5.7 ms) is skewed in T: a Gaussian's centre came out 33 µs late
    (SE 13 µs) on average. The arrival-time profile's centre is the v = 0 arrival."""
    sigma_v = math.sqrt(DEFAULTS.k_B * 1.5e-6 / DEFAULTS.mass)
    errors, ses = [], []
    for seed in range(20):
        found = detect_release_time(cloud(np.random.default_rng(seed), 200_000, sigma_v)[:, 0], DEFAULTS)
        assert found.ok, found.failure
        assert found.fit is not None and found.fit.model.key == "arrival_time"
        assert not any("skewed" in note for note in found.notes)
        errors.append(found.value.value - RELEASE)
        ses.append(found.value.se)
    se = float(np.mean(ses))
    assert abs(float(np.mean(errors))) < se  # within ~1 SE of 0 (the Gaussian's was 2.6 SE)
    assert abs(float(np.mean(errors))) < 3 * se / math.sqrt(20)
    assert float(np.std(errors)) == pytest.approx(se, rel=0.4)


def test_a_failed_arrival_fit_falls_back_to_a_gaussian_with_the_skew_note(monkeypatch: pytest.MonkeyPatch) -> None:
    real = fits.fit_histogram

    def no_arrival(centres: npt.ArrayLike, counts: npt.ArrayLike, model: str | fits.FitModel = "gaussian"
                   ) -> fits.FitResult:
        result = real(centres, counts, model)
        if result.model.key == "arrival_time":
            return dataclasses.replace(result, failure="made to fail")
        return result
    monkeypatch.setattr(release, "fit_histogram", no_arrival)
    events = cloud(np.random.default_rng(3), 200_000, 0.05)  # ~1.5 µK thermal: σ_t ≈ 5 ms
    found = detect_release_time(events[:, 0], DEFAULTS)
    assert found.ok and found.fit is not None and found.fit.model.key == "gaussian"
    assert any("arrival-time fit failed (made to fail)" in note for note in found.notes)
    assert any("skewed" in note for note in found.notes)
    assert abs(found.value.value - RELEASE) < 1e-4  # off by tens of µs at most


def test_two_comparable_clouds_are_unsure() -> None:
    rng = np.random.default_rng(5)
    first, second = cloud(rng, 8000, 0.003), cloud(rng, 6000, 0.003, drift=(0.1, 0, 0))
    found = detect_release_time(np.concatenate([first[:, 0], second[:, 0]]), DEFAULTS)
    assert found.ok and found.unsure and len(found.peaks) == 2
    assert abs(found.value.value - RELEASE) < 3 * found.value.se  # the taller one
    # A Search T around the other one chooses it, without the note.
    arrival = float(arrival_time(0.1, RELEASE, DEFAULTS))
    chosen = detect_release_time(np.concatenate([first[:, 0], second[:, 0]]), DEFAULTS,
                                 lower=arrival - 0.004, upper=arrival + 0.004)
    assert chosen.ok and not chosen.unsure
    assert chosen.arrival.value == pytest.approx(arrival, abs=3 * chosen.arrival.se)
    # A small side cloud isn't comparable.
    small = cloud(rng, 1000, 0.003, drift=(0.1, 0, 0))
    assert not detect_release_time(np.concatenate([first[:, 0], small[:, 0]]), DEFAULTS).unsure


def test_failures_are_results() -> None:
    empty = detect_release_time(np.empty(0), DEFAULTS)
    assert not empty.ok and "no events" in empty.failure and math.isnan(empty.value.value)
    few = detect_release_time(np.full(10, 2.1), DEFAULTS)
    assert "too few" in few.failure and few.events == 10
    outside = detect_release_time(cloud(np.random.default_rng(0), 1000, 0.003)[:, 0], DEFAULTS, lower=3.0)
    assert "no events" in outside.failure
    json.dumps(few.as_record(), allow_nan=False)


@pytest.mark.parametrize("count", [50, 80, 150])
def test_small_clouds_near_the_limit_are_found(count: int) -> None:
    for seed in range(10):
        found = detect_release_time(cloud(np.random.default_rng(seed), count, 0.003)[:, 0], DEFAULTS)
        assert found.ok, (seed, found.failure)
        assert abs(found.value.value - RELEASE) < 4 * found.value.se


def test_sparse_events_are_too_few_not_no_peak() -> None:
    below = detect_release_time(cloud(np.random.default_rng(0), 40, 0.003)[:, 0], DEFAULTS)
    assert "too few" in below.failure
    # With the event floor lowered, a few stray events are no cloud.
    sparse = detect_release_time(np.random.default_rng(1).uniform(1.9, 2.4, 20), DEFAULTS, min_events=10)
    assert not sparse.ok or sparse.unsure


def test_background_alone_is_unsure() -> None:
    found = detect_release_time(np.random.default_rng(0).uniform(1.9, 2.4, 3000), DEFAULTS)
    assert found.unsure and any("stands out" in note for note in found.notes)
    clear = detect_release_time(np.concatenate([cloud(np.random.default_rng(1), 300, 0.003)[:, 0],
                                                np.random.default_rng(2).uniform(1.9, 2.4, 3000)]), DEFAULTS)
    assert clear.ok and not clear.unsure and abs(clear.value.value - RELEASE) < 4 * clear.value.se


def test_times_on_a_coarse_grid_get_whole_grid_bins() -> None:
    times = np.round(cloud(np.random.default_rng(4), 5000, 0.003)[:, 0], 4)  # 0.1 ms steps
    search = find_time_peaks(times)
    assert len(search.counts) < 100
    np.testing.assert_allclose(np.diff(search.edges), 1e-4, rtol=1e-6)
    assert len(search.peaks) == 1
    found = detect_release_time(times, DEFAULTS)
    assert found.ok and abs(found.value.value - RELEASE) < 4 * found.value.se + 5e-5
    # One stray grid point far away doesn't explode the bins either.
    assert len(find_time_peaks(np.concatenate([times, [3.0]])).counts) <= 20_000


def test_shot_jitter_needs_the_shot_bootstrap() -> None:
    rng = np.random.default_rng(0)
    shots = [cloud(rng, 1000, 0.003, release=RELEASE + rng.normal(0, 50e-6))[:, 0] for _ in range(20)]
    within = detect_release_time(np.concatenate(shots), DEFAULTS)
    over_shots = bootstrap_release_time(shots, DEFAULTS, n_boot=100)
    assert within.error == "within run" and over_shots.error == "shot bootstrap"
    assert over_shots.value.value == within.value.value
    assert over_shots.within_run_se == within.value.se
    assert over_shots.value.se > 2 * within.value.se
    assert over_shots.value.se == pytest.approx(50e-6 / math.sqrt(20), rel=0.5)
    record = over_shots.as_record()
    assert record["error"] == "shot bootstrap" and record["bootstrap"]["n_boot"] == 100
    json.dumps(record, allow_nan=False)
    # One shot: no bootstrap error, the fit's kept and noted.
    single = bootstrap_release_time(shots[:1], DEFAULTS, n_boot=10)
    assert single.ok and single.error == "within run" and any("no shot bootstrap" in n for n in single.notes)


def test_identical_times_have_no_peak() -> None:
    found = detect_release_time(np.full(500, 2.1), DEFAULTS)
    assert not found.ok and "no peak" in found.failure


def test_manual_release_time_passes_through() -> None:
    manual = manual_release_time(1.69, DEFAULTS)
    assert manual.ok and manual.source == "manual" and manual.value.value == 1.69 and math.isnan(manual.value.se)
    assert manual.error == "none"
    assert not manual_release_time(math.nan, DEFAULTS).ok
    json.dumps(manual.as_record(), allow_nan=False)


ORIGIN = (1.2e-3, -0.7e-3)  # m: the trap above this point of the detector, off X = Y = 0


def test_back_to_back_pairs_need_the_xy_origin() -> None:
    """Pairs with v₁ = −v₂ released from a trap above (x₀, y₀): measured from the origin they
    sum to 0; measured from (0, 0) each atom gets x₀/τ more, so the sum is x₀(1/τ₁ + 1/τ₂)
    ≈ 2x₀/t_f."""
    rng = np.random.default_rng(0)
    first = rng.normal(0, 0.02, (500, 3))
    velocities = np.concatenate([first, -first])
    events = trajectories(velocities, RELEASE, DEFAULTS)
    events[:, 1] += ORIGIN[0]
    events[:, 2] += ORIGIN[1]
    centred = txy_to_velocity(events, RELEASE, DEFAULTS, origin=ORIGIN)
    assert centred.origin == ORIGIN
    np.testing.assert_allclose(centred.values, velocities, atol=1e-12)
    sums = centred.values[:500] + centred.values[500:]
    np.testing.assert_allclose(sums, 0.0, atol=1e-12)
    assumed = txy_to_velocity(events, RELEASE, DEFAULTS)
    assert assumed.origin == (0.0, 0.0)
    tau = events[:, 0] - RELEASE
    shift = 1 / tau[:500] + 1 / tau[500:]
    plain = assumed.values[:500] + assumed.values[500:]
    np.testing.assert_allclose(plain[:, 1], ORIGIN[0] * shift, rtol=1e-9)
    np.testing.assert_allclose(plain[:, 2], ORIGIN[1] * shift, rtol=1e-9)
    assert float(np.mean(plain[:, 1])) == pytest.approx(2 * ORIGIN[0] / DEFAULTS.fall_time, rel=1e-3)
    np.testing.assert_allclose(plain[:, 0], 0.0, atol=1e-12)  # v_z doesn't depend on it
    with pytest.raises(ValueError):
        txy_to_velocity(events, RELEASE, DEFAULTS, origin=(math.nan, 0.0))


def test_the_xy_origin_is_detected_from_the_rest_cloud() -> None:
    rng = np.random.default_rng(1)
    rest = cloud(rng, 20_000, 0.003)
    rest[:, 1] += ORIGIN[0]
    rest[:, 2] += ORIGIN[1]
    # A Bragg order 0.1 m/s up, released from the same trap: separate in T, ignored.
    moving = cloud(rng, 4000, 0.003, drift=(0.1, 0.0, 0.0))
    moving[:, 1:] += ORIGIN
    events = np.concatenate([rest, moving])
    found = detect_release_time(events[:, 0], DEFAULTS, positions=events[:, 1:3])
    assert found.ok and found.origin_found and found.origin_events > 10_000
    spread = 0.003 * DEFAULTS.fall_time  # the cloud's XY width
    for axis, truth in zip(found.origin, ORIGIN):
        assert axis.se == pytest.approx(spread / math.sqrt(found.origin_events), rel=0.2)
        assert abs(axis.value - truth) < 3 * axis.se
    record = found.as_record()["origin"]
    assert record["x"]["value"] == found.origin[0].value and record["events"] == found.origin_events
    json.dumps(found.as_record(), allow_nan=False)
    # Without positions there is no origin, and velocities assume (0, 0).
    times_only = detect_release_time(events[:, 0], DEFAULTS)
    assert not times_only.origin_found and math.isnan(times_only.origin[0].value)
    assert velocity_origin(times_only) == ((0.0, 0.0), "assumed")
    assert velocity_origin(found) == ((found.origin[0].value, found.origin[1].value), "detected")
    assert velocity_origin(found, manual=(1e-3, 2e-3)) == ((1e-3, 2e-3), "manual")
    assert velocity_origin(found, manual=(math.nan, 0.0))[1] == "detected"
    assert velocity_origin(None) == ((0.0, 0.0), "assumed")
    with pytest.raises(ValueError):
        detect_release_time(events[:, 0], DEFAULTS, positions=events[:10, 1:3])
    # The detected origin centres the rest cloud's velocities.
    origin, _ = velocity_origin(found)
    at_rest = txy_to_velocity(rest, found.value.value, DEFAULTS, origin=origin)
    assert abs(float(np.mean(at_rest.values[:, 1]))) < 3 * 0.003 / math.sqrt(len(rest))


def test_the_shot_bootstrap_covers_the_trap_s_shot_to_shot_drift() -> None:
    rng = np.random.default_rng(2)
    shots = []
    for _ in range(20):
        events = cloud(rng, 1000, 0.003)
        events[:, 1:] += np.asarray(ORIGIN) + rng.normal(0, 200e-6, 2)  # the trap moves 0.2 mm per shot
        shots.append(events)
    found = bootstrap_release_time(shots, DEFAULTS, n_boot=100)
    assert found.ok and found.error == "shot bootstrap" and found.origin_found
    within = detect_release_time(np.concatenate(shots)[:, 0], DEFAULTS, positions=np.concatenate(shots)[:, 1:3])
    for axis, still, truth in zip(found.origin, within.origin, ORIGIN):
        assert axis.value == still.value
        assert axis.se > 2 * still.se
        assert axis.se == pytest.approx(200e-6 / math.sqrt(20), rel=0.5)
        assert abs(axis.value - truth) < 4 * axis.se
    # Times alone: no origin, as before.
    times = bootstrap_release_time([shot[:, 0] for shot in shots], DEFAULTS, n_boot=20)
    assert times.ok and not times.origin_found
