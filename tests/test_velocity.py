"""TXY → velocity (z up), the release-time detection and its peak finding, on synthetic
events from exact trajectories."""
from __future__ import annotations

import json
import math

import numpy as np
import numpy.typing as npt
import pytest
import scipy.constants as codata

from helab.analysis.peaks import find_time_peaks
from helab.analysis.physics import DEFAULTS, ResolvedConstants, resolve
from helab.analysis.release import detect_release_time, manual_release_time
from helab.analysis.velocity import (RECOIL_WAVELENGTH, arrival_time, recoil_velocity, txy_to_velocity,
                                     vertical_velocity)

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
                       [RELEASE + 0.4, 0.001, 0.0]])
    events.flags.writeable = False  # a DatasetView's arrays are read-only
    result = txy_to_velocity(events, RELEASE, DEFAULTS)
    assert result.invalid == 3
    assert np.all(np.isnan(result.values[:3])) and np.all(np.isfinite(result.values[3]))
    assert result.valid.tolist() == [False, False, False, True]
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


def test_a_wide_cloud_gets_a_skew_note() -> None:
    events = cloud(np.random.default_rng(3), 200_000, 0.05)  # ~1.5 µK thermal: σ_t ≈ 5 ms
    found = detect_release_time(events[:, 0], DEFAULTS)
    assert found.ok
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


def test_identical_times_have_no_peak() -> None:
    found = detect_release_time(np.full(500, 2.1), DEFAULTS)
    assert not found.ok and "no peak" in found.failure


def test_manual_release_time_passes_through() -> None:
    manual = manual_release_time(1.69, DEFAULTS)
    assert manual.ok and manual.source == "manual" and manual.value.value == 1.69 and math.isnan(manual.value.se)
    assert not manual_release_time(math.nan, DEFAULTS).ok
    json.dumps(manual.as_record(), allow_nan=False)
