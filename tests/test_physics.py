"""The constants table, how the layers resolve, and the temperature conversions."""
from __future__ import annotations

import json
import math

import numpy as np
import pytest
import scipy.constants as codata

from helab.analysis import physics
from helab.analysis.estimates import Estimate
from helab.analysis.physics import DEFAULTS, TABLE, ResolvedConstants, fall_time, resolve


def test_table_values_and_metadata() -> None:
    assert TABLE["hbar"].value == codata.hbar
    assert TABLE["k_B"].value == codata.k
    assert TABLE["mass"].value == pytest.approx(6.6465e-27, rel=1e-4)
    assert TABLE["mass"].value == 4.002602 * codata.atomic_mass
    assert TABLE["g"].value == 9.79602
    assert TABLE["scattering_length"].value == 7.512e-9
    assert TABLE["fall_distance"].value == 0.848
    assert TABLE["fall_time"].derived
    assert (TABLE["dld_trigger"].value, TABLE["dld_acquisition"].value) == (20.5, 2.0)
    assert TABLE["dld_trigger"].shown_only and TABLE["dld_acquisition"].shown_only
    for constant in physics.CONSTANTS:
        assert constant.title and constant.unit and constant.source
        assert constant.level in ("lab", "folder")
    assert {key for key, constant in TABLE.items() if constant.unconfirmed} == {
        "fall_distance", "fall_time", "trap_radial", "trap_axial", "dld_trigger", "dld_acquisition"}
    assert {key for key, constant in TABLE.items() if constant.level == "folder"} == {
        "fall_distance", "fall_time", "trap_radial", "trap_axial"}


def test_fall_time_is_derived_from_the_distance() -> None:
    assert fall_time(0.848, 9.79602) == pytest.approx(0.4161, abs=5e-5)
    assert DEFAULTS.fall_time == pytest.approx(math.sqrt(2 * 0.848 / 9.79602))
    assert DEFAULTS.origins["fall_time"] == "derived"
    assert math.isnan(fall_time(0, 9.8)) and math.isnan(fall_time(1, -9.8)) and math.isnan(fall_time(math.inf, 1))


def test_layers_override_in_order() -> None:
    resolved = resolve(lab={"g": 9.8}, folder={"g": 9.81, "trap_radial": 400}, plot={"trap_radial": 420})
    assert (resolved.g, resolved.origins["g"]) == (9.81, "folder")
    assert (resolved.trap_radial, resolved.origins["trap_radial"]) == (420, "plot")
    assert resolved.origins["mass"] == "default"
    assert resolved.fall_time == pytest.approx(fall_time(0.848, 9.81))


def test_a_fall_time_set_by_hand_wins_only_at_the_distance_s_level_or_above() -> None:
    by_hand = resolve(folder={"fall_time": 0.417})
    assert (by_hand.fall_time, by_hand.origins["fall_time"]) == (0.417, "folder")
    # A folder's new distance isn't paired with a lab-wide fall time: the time is derived again.
    newer_distance = resolve(lab={"fall_time": 0.417}, folder={"fall_distance": 0.852925545})
    assert newer_distance.origins["fall_time"] == "derived"
    assert newer_distance.fall_time == pytest.approx(0.4173, abs=1e-4)
    same_level = resolve(folder={"fall_time": 0.417, "fall_distance": 0.8529})
    assert same_level.origins["fall_time"] == "folder"
    plot_time = resolve(folder={"fall_distance": 0.86}, plot={"fall_time": 0.42})
    assert (plot_time.fall_time, plot_time.origins["fall_time"]) == (0.42, "plot")


@pytest.mark.parametrize("layers", [{"lab": {"nope": 1.0}}, {"folder": {"g": 0.0}}, {"plot": {"mass": math.nan}},
                                    {"lab": {"fall_distance": -1.0}}, {"lab": {"g": math.inf}}])
def test_bad_values_are_refused(layers: dict[str, dict[str, float]]) -> None:
    with pytest.raises(ValueError):
        resolve(**layers)


def test_unconfirmed_follows_what_was_set() -> None:
    assert set(DEFAULTS.unconfirmed) == {"fall_distance", "fall_time", "trap_radial", "trap_axial",
                                         "dld_trigger", "dld_acquisition"}
    measured = resolve(folder={"fall_distance": 0.85})
    assert "fall_distance" not in measured.unconfirmed and "fall_time" not in measured.unconfirmed


def test_record_is_json_and_round_trips() -> None:
    resolved = resolve(lab={"g": 9.8}, plot={"fall_time": 0.42})
    record = json.loads(json.dumps(resolved.as_record()))
    assert set(record["values"]) == set(TABLE)
    assert record["origins"]["fall_time"] == "plot"
    assert ResolvedConstants.from_record(record) == resolved
    assert resolved.value("g") == 9.8
    with pytest.raises(KeyError):
        resolved.value("origins")


def test_arrival_width_gives_the_velocity_spread() -> None:
    # Exact arrival times of atoms leaving with Gaussian v_z (z up): h + v t − ½ g t² = 0.
    g, h, sigma_v = DEFAULTS.g, DEFAULTS.fall_distance, 0.01
    v = np.random.default_rng(1).normal(0, sigma_v, 200_000)
    t = (v + np.sqrt(v ** 2 + 2 * g * h)) / g
    assert float(np.mean(t)) == pytest.approx(DEFAULTS.fall_time, abs=1e-5)
    assert physics.sigma_v_from_arrival_width(float(np.std(t)), g) == pytest.approx(sigma_v, rel=0.01)
    # Faster upward atoms arrive later.
    assert np.corrcoef(v, t)[0, 1] > 0.99


def test_transverse_width_and_temperature() -> None:
    temperature = 1e-6
    sigma_v = math.sqrt(codata.k * temperature / DEFAULTS.mass)
    assert sigma_v == pytest.approx(0.0456, rel=1e-3)  # He* at 1 µK
    sigma_x = sigma_v * DEFAULTS.fall_time
    assert physics.sigma_v_from_transverse_width(sigma_x) == pytest.approx(sigma_v)
    assert math.isnan(physics.sigma_v_from_transverse_width(1e-3, 0.0))
    assert physics.thermal_temperature(sigma_v) == pytest.approx(temperature)
    estimate = physics.temperature_estimate(Estimate(sigma_v, sigma_v * 0.01))
    assert estimate.value == pytest.approx(temperature)
    assert estimate.se == pytest.approx(0.02 * temperature)
