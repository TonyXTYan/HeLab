"""Histogram fits on synthetic events with known parameters, and the failures they report."""
from __future__ import annotations

import json
import math
import warnings
from typing import Callable

import numpy as np
import numpy.typing as npt
import pytest
from scipy.integrate import quad

from helab.analysis import fits
from helab.analysis.estimates import Estimate
from helab.analysis.fits import MODELS, FitModel, FitResult, ModelParameter, bin_centres, fit_histogram

Array = npt.NDArray[np.float64]


def fit_events(events: Array, bins: int, bounds: tuple[float, float], model: str = "gaussian",
               weights: fits.Weights = "poisson") -> FitResult:
    counts, edges = np.histogram(events, bins=bins, range=bounds)
    return fit_histogram(bin_centres(edges), counts, model, weights=weights)


def thomas_fermi_events(rng: np.random.Generator, count: int, radius: float, power: float = 2.0) -> Array:
    """Samples of (1 − u²)^p on [−R, R], by rejection."""
    chosen: list[Array] = []
    while sum(len(part) for part in chosen) < count:
        u = rng.uniform(-1, 1, 4 * count)
        chosen.append(u[rng.uniform(0, 1, len(u)) < (1 - u * u) ** power])
    return np.concatenate(chosen)[:count] * radius


def coverage(seeds: int, fit: Callable[[np.random.Generator], FitResult], truth: dict[str, float]
             ) -> dict[str, tuple[float, float]]:
    """Per parameter: (share of fits within 2 SE of the truth, mean pull)."""
    pulls: dict[str, list[float]] = {name: [] for name in truth}
    for seed in range(seeds):
        result = fit(np.random.default_rng(seed))
        assert result.ok, result.failure
        for name, value in truth.items():
            pulls[name].append((result[name].value - value) / result[name].se)
    return {name: (float(np.mean(np.abs(values) < 2)), float(np.mean(values))) for name, values in pulls.items()}


@pytest.mark.parametrize("count", [500, 5000])
def test_gaussian_recovers_centre_and_width_within_their_errors(count: int) -> None:
    centre, sigma = 0.416, 1e-4  # a T profile: seconds

    def fit(rng: np.random.Generator) -> FitResult:
        return fit_events(rng.normal(centre, sigma, count), 40, (centre - 4 * sigma, centre + 4 * sigma))
    found = coverage(150, fit, {"centre": centre, "sigma": sigma})
    for name, (within, bias) in found.items():
        assert 0.88 <= within <= 1.0, (name, within)  # about 95 % expected
        assert abs(bias) < 0.3, (name, bias)


def test_count_weights_alone_bias_the_width_low() -> None:
    """Why "poisson" refits with the model's variance: errors of √n favour low bins."""
    def fit(rng: np.random.Generator) -> FitResult:
        return fit_events(rng.normal(0, 1, 500), 40, (-4, 4), weights="counts")
    _, bias = coverage(100, fit, {"sigma": 1.0})["sigma"]
    assert bias < -0.6


def test_gaussian_with_a_background() -> None:
    rng = np.random.default_rng(7)
    events = np.concatenate([rng.normal(2e-3, 5e-4, 20_000), rng.uniform(-5e-3, 1e-2, 15_000)])
    result = fit_events(events, 150, (-5e-3, 1e-2))
    assert result.ok, result.failure
    assert result.notes == ()
    assert abs(result["centre"].value - 2e-3) < 3 * result["centre"].se
    assert abs(result["sigma"].value - 5e-4) < 3 * result["sigma"].se
    assert abs(result["offset"].value - 100) < 3 * result["offset"].se  # 15,000 over 150 bins
    assert result.dof == 150 - 4 and 0.6 < result.reduced_chi2 < 1.5
    assert result.curve.shape == (150,)
    areas = MODELS["gaussian"].areas
    assert areas is not None
    area = areas(result.values)["gaussian"]
    bin_width = 1.5e-2 / 150
    assert area / bin_width == pytest.approx(20_000, rel=0.03)


def test_unweighted_fit_scales_its_errors_by_the_residuals() -> None:
    rng = np.random.default_rng(3)
    result = fit_events(rng.normal(0, 1, 5000), 40, (-4, 4), weights="none")
    weighted = fit_events(np.random.default_rng(3).normal(0, 1, 5000), 40, (-4, 4))
    assert result.ok and abs(result["sigma"].value - 1) < 3 * result["sigma"].se
    # Less efficient than the Poisson fit, but the same order.
    assert 0.5 < result["sigma"].se / weighted["sigma"].se < 2.5


def test_given_errors_replace_the_weights() -> None:
    x = np.linspace(-3, 3, 31)
    y = 50 * np.exp(-x ** 2 / 2) + 2
    result = fit_histogram(x, y, sigma=0.01)
    assert result.ok
    assert result.values == pytest.approx([50, 0, 1, 2], abs=1e-6)
    assert result.chi2 == pytest.approx(0, abs=1e-6)


def test_thomas_fermi_recovers_its_radius() -> None:
    radius = 2e-3

    def fit(rng: np.random.Generator) -> FitResult:
        return fit_events(thomas_fermi_events(rng, 5000, radius), 120, (-3e-3, 3e-3), "thomas_fermi_2")
    found = coverage(60, fit, {"radius": radius, "centre": 0.0})
    for name, (within, bias) in found.items():
        assert within >= 0.85, (name, within)
        assert abs(bias) < 0.4, (name, bias)


def test_thomas_fermi_three_halves() -> None:
    rng = np.random.default_rng(2)
    result = fit_events(thomas_fermi_events(rng, 20_000, 1.0, 1.5) + 0.3, 100, (-1.5, 2.0), "thomas_fermi_1_5")
    assert result.ok, result.failure
    assert abs(result["radius"].value - 1) < 3 * result["radius"].se
    assert abs(result["centre"].value - 0.3) < 3 * result["centre"].se


def condensate_fraction(result: FitResult) -> Estimate:
    areas = result.model.areas
    assert areas is not None

    def fraction(values: Array) -> float:
        parts = areas(values)
        return parts["thomas_fermi"] / (parts["thomas_fermi"] + parts["gaussian"])
    return result.derived(fraction)


def fit_bimodal(events: Array) -> FitResult:
    return fit_events(events, 200, (-1e-2, 1e-2), "bimodal_tf2_gaussian")


def test_bimodal_recovers_the_condensate_fraction() -> None:
    hits = 0
    seeds = 12
    for seed in range(seeds):
        rng = np.random.default_rng(seed)
        result = fit_bimodal(np.concatenate([thomas_fermi_events(rng, 8000, 1e-3),
                                             rng.normal(0, 2.5e-3, 12_000)]) + 5e-4)
        assert result.ok, result.failure
        assert not any("consistent with 0" in note for note in result.notes)
        shares = condensate_fraction(result)
        assert 0 < shares.se < 0.05
        assert abs(result["centre"].value - 5e-4) < 4 * result["centre"].se
        assert abs(result["radius"].value - 1e-3) < 4 * result["radius"].se
        assert result["radius"].value == pytest.approx(result["ratio"].value * result["sigma"].value)
        assert abs(result["sigma"].value - 2.5e-3) < 4 * result["sigma"].se
        hits += abs(shares.value - 0.4) < 2 * shares.se
    assert hits >= seeds - 3


def test_bimodal_on_a_thermal_cloud_finds_no_condensate() -> None:
    """Unconstrained, the fit invented a condensate here (N0/N up to 0.15, R/σ 2–4)."""
    clear = 0
    seeds = 8
    for seed in range(seeds):
        result = fit_bimodal(np.random.default_rng(seed).normal(0, 2e-3, 20_000))
        assert result.ok, result.failure
        shares = condensate_fraction(result)
        assert shares.value < 0.2
        assert result["ratio"].value <= fits.MAX_RADIUS_RATIO
        assert abs(result["sigma"].value - 2e-3) < 4 * result["sigma"].se
        noted = any(note.startswith("Condensate amplitude consistent with 0") for note in result.notes)
        if noted:
            assert math.isnan(result["ratio"].se) and math.isnan(result["radius"].se)
        clear += noted or shares.value < 2 * shares.se
    assert clear >= seeds - 2


def test_bimodal_on_a_pure_condensate_finds_no_thermal_part() -> None:
    """Unconstrained, the thermal part became a narrow spike inside the TF profile."""
    for seed in range(4):
        result = fit_bimodal(thomas_fermi_events(np.random.default_rng(seed), 20_000, 1e-3))
        assert result.ok, result.failure
        assert any(note.startswith("Thermal amplitude consistent with 0") for note in result.notes), result.notes
        assert math.isnan(result["sigma"].se)
        assert condensate_fraction(result).value > 0.95
        assert abs(result["radius"].value - 1e-3) < 4 * result["radius"].se
        assert result["sigma"].value >= result["radius"].value / fits.MAX_RADIUS_RATIO * (1 - 1e-9)


def test_areas_match_the_integrals() -> None:
    for power in (2.0, 1.5, 1.0):
        integral, _ = quad(lambda x: float(fits.thomas_fermi(np.array([x]), 3.0, 0.5, 2.0, 0.0, power)[0]), -1.5, 2.5)
        assert fits.thomas_fermi_area(3.0, 2.0, power) == pytest.approx(integral, rel=1e-6)
    assert fits.thomas_fermi_area(1.0, 1.0, 2.0) == pytest.approx(16 / 15)
    assert fits.thomas_fermi_area(1.0, 1.0, 1.5) == pytest.approx(3 * math.pi / 8)
    integral, _ = quad(lambda x: float(fits.gaussian(np.array([x]), 2.0, 1.0, 0.3, 0.0)[0]), -5, 5)
    assert fits.gaussian_area(2.0, 0.3) == pytest.approx(integral, rel=1e-8)


def failure_of(centres: npt.ArrayLike, counts: npt.ArrayLike, model: str = "gaussian",
               max_evaluations: int = fits.MAX_EVALUATIONS) -> FitResult:
    result = fit_histogram(centres, counts, model, max_evaluations=max_evaluations)
    assert not result.ok
    assert all(math.isnan(estimate.value) for estimate in result.estimates.values())
    return result


def test_failures_are_results_with_a_reason() -> None:
    x = np.linspace(0, 1, 20)
    assert failure_of([], []).failure == "no data to fit"
    assert failure_of(x, np.zeros(20)).failure == "no counts to fit"
    assert failure_of(x[:4], [1, 5, 4, 1]).failure.startswith("too few bins to fit: 4 for 4")
    one = np.zeros(20)
    one[10] = 50
    assert failure_of(x, one).failure.startswith("all counts in one bin")
    two = np.zeros(20)
    two[[9, 10]] = [50, 30]
    assert failure_of(x, two).failure == "counts in only 2 bins: too few to fit this model (it needs 3)"
    three = np.zeros(20)
    three[[9, 10, 11]] = [30, 50, 30]
    assert fit_histogram(x, three).ok
    assert failure_of(x, three, "bimodal_tf2_gaussian").failure == \
        "counts in only 3 bins: too few to fit this model (it needs 4)"
    assert failure_of(x, 100 * np.exp(-((x - 0.5) / 0.1) ** 2 / 2), max_evaluations=1).failure == \
        "the fit did not converge in 1 evaluations"
    nothing = failure_of(x, np.full(20, np.nan))
    assert nothing.failure == "no data to fit"
    assert nothing.notes == ("20 bins with a non-finite centre or count left out",)
    assert np.all(np.isnan(nothing.evaluate([0.1, 0.2])))
    assert set(failure_of(x, one, "bimodal_tf2_gaussian").estimates) == {*MODELS["bimodal_tf2_gaussian"].names,
                                                                         "radius"}
    with pytest.raises(ValueError):
        fit_histogram([1, 2], [1])


def test_an_undetermined_parameter_is_a_failure() -> None:
    # "b" has no effect: SciPy gives it a variance of 0, which must not read as an exact value.
    flat = FitModel("flat", "Flat", (ModelParameter("a", "a", "height"), ModelParameter("b", "b", "shape")),
                    lambda x, a, b: a + 0 * x, lambda x, y, errors: [np.array([1.0, 1.0])],
                    lambda x, y: (np.array([0.0, 0.0]), np.array([np.inf, 10.0])))
    result = fit_histogram(np.linspace(0, 1, 20), np.full(20, 10.0), flat)
    assert result.failure == "not determined by the data: b (no usable SE)"
    assert result["a"].value == pytest.approx(10)
    assert math.isnan(result["b"].se)


def test_unusable_bins_are_left_out_and_noted() -> None:
    x = np.linspace(0, 1, 22)
    y = np.round(100 * np.exp(-((x - 0.5) / 0.1) ** 2 / 2))
    y[[0, 1]] = [np.nan, np.inf]
    result = fit_histogram(x, y)
    assert result.ok and result.points == 20
    assert result.notes == ("2 bins with a non-finite centre or count left out",)
    assert result["centre"].value == pytest.approx(0.5, abs=1e-3)
    given = fit_histogram(x[2:], y[2:], sigma=np.r_[0.0, -1.0, np.ones(18)])
    assert given.points == 18
    assert given.notes == ("2 bins with an error that isn't finite and > 0 left out",)


def test_count_weights_say_when_the_input_isnt_counts() -> None:
    x = np.linspace(0, 1, 20)
    rate = 100.5 * np.exp(-((x - 0.5) / 0.1) ** 2 / 2)
    assert any(note.startswith("the counts aren't whole numbers") for note in fit_histogram(x, rate).notes)
    assert fit_histogram(x, rate, sigma=1.0).notes == ()
    assert fit_histogram(x, rate, weights="none").notes == ()


def test_bounds_and_poor_models_are_noted() -> None:
    x = np.linspace(0, 1, 20)
    flat = fit_histogram(x, np.full(20, 100.0))
    assert any(note.startswith("at its bound: σ") for note in flat.notes)
    rng = np.random.default_rng(0)
    square = fit_events(rng.uniform(-1, 1, 50_000), 60, (-1.5, 1.5))
    assert any("reduced χ²" in note for note in square.notes)
    # A Gaussian on a flat-topped cloud: the Poisson weights keep moving, and say so.
    assert any(note.startswith("the Poisson weights did not settle") for note in square.notes)
    assert square.ok


def test_registry() -> None:
    assert {"gaussian", "thomas_fermi_2", "thomas_fermi_1_5", "bimodal_tf2_gaussian",
            "bimodal_tf1_5_gaussian"} <= set(MODELS)
    with pytest.raises(ValueError):
        fits.register(MODELS["gaussian"])
    assert MODELS["gaussian"].names == ("amplitude", "centre", "sigma", "offset")
    assert bin_centres([0, 1, 3]) == pytest.approx([0.5, 2.0])


def test_evaluate_draws_the_fitted_model() -> None:
    x = np.linspace(-3, 3, 31)
    result = fit_histogram(x, 50 * np.exp(-x ** 2 / 2) + 2, sigma=0.01)
    assert result.evaluate([0.0]) == pytest.approx([52.0], abs=1e-4)
    assert result.derived(lambda values: float(values[0] + values[3])).value == pytest.approx(52.0, abs=1e-4)


def test_record_is_strict_json_and_arrays_are_read_only() -> None:
    x = np.linspace(-3, 3, 31)
    result = fit_histogram(x, np.round(50 * np.exp(-x ** 2 / 2)))
    record = json.loads(json.dumps(result.as_record(), allow_nan=False))
    assert record["model"] == "gaussian" and record["failure"] == "" and record["dof"] == 27
    assert record["estimates"]["sigma"]["value"] == pytest.approx(result["sigma"].value)
    failed = json.loads(json.dumps(fit_histogram([], []).as_record(), allow_nan=False))
    assert failed["estimates"]["centre"] == {"value": None, "se": None} and failed["chi2"] is None
    for array in (result.x, result.curve, result.covariance):
        assert array is not None
        with pytest.raises(ValueError):
            array[0] = 1.0


def test_fits_leave_the_warning_filters_alone() -> None:
    """Fits run in the analysis worker thread: no per-call changes to the global filters."""
    before = list(warnings.filters)
    fit_events(np.random.default_rng(1).normal(0, 1, 2000), 40, (-4, 4), "bimodal_tf2_gaussian")
    assert warnings.filters == before
