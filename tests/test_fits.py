"""Histogram fits on synthetic events with known parameters, and the failures they report."""
from __future__ import annotations

import math
from typing import Callable

import numpy as np
import numpy.typing as npt
import pytest
from scipy.integrate import quad

from helab.analysis import fits
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


def test_bimodal_recovers_the_condensate_fraction() -> None:
    model = MODELS["bimodal_tf2_gaussian"]
    assert model.areas is not None
    areas = model.areas

    def fraction(values: Array) -> float:
        parts = areas(values)
        return parts["thomas_fermi"] / (parts["thomas_fermi"] + parts["gaussian"])

    hits = 0
    seeds = 12
    for seed in range(seeds):
        rng = np.random.default_rng(seed)
        events = np.concatenate([thomas_fermi_events(rng, 8000, 1e-3), rng.normal(0, 2.5e-3, 12_000)]) + 5e-4
        result = fit_events(events, 200, (-1e-2, 1e-2), "bimodal_tf2_gaussian")
        assert result.ok, result.failure
        shares = result.derived(fraction)
        assert 0 < shares.se < 0.05
        assert abs(result["centre"].value - 5e-4) < 4 * result["centre"].se
        assert abs(result["radius"].value - 1e-3) < 4 * result["radius"].se
        assert abs(result["sigma"].value - 2.5e-3) < 4 * result["sigma"].se
        hits += abs(shares.value - 0.4) < 2 * shares.se
    assert hits >= seeds - 3


def test_areas_match_the_integrals() -> None:
    for power in (2.0, 1.5, 1.0):
        integral, _ = quad(lambda x: float(fits.thomas_fermi(np.array([x]), 3.0, 0.5, 2.0, 0.0, power)[0]), -1.5, 2.5)
        assert fits.thomas_fermi_area(3.0, 2.0, power) == pytest.approx(integral, rel=1e-6)
    assert fits.thomas_fermi_area(1.0, 1.0, 2.0) == pytest.approx(16 / 15)
    assert fits.thomas_fermi_area(1.0, 1.0, 1.5) == pytest.approx(3 * math.pi / 8)
    integral, _ = quad(lambda x: float(fits.gaussian(np.array([x]), 2.0, 1.0, 0.3, 0.0)[0]), -5, 5)
    assert fits.gaussian_area(2.0, 0.3) == pytest.approx(integral, rel=1e-8)


def failure_of(centres: npt.ArrayLike, counts: npt.ArrayLike, max_evaluations: int = fits.MAX_EVALUATIONS
               ) -> FitResult:
    result = fit_histogram(centres, counts, max_evaluations=max_evaluations)
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
    assert failure_of(x, 100 * np.exp(-((x - 0.5) / 0.1) ** 2 / 2), max_evaluations=1).failure == \
        "the fit did not converge"
    nothing = failure_of(x, np.full(20, np.nan))
    assert nothing.failure == "no data to fit" and nothing.notes == ("20 bins with non-finite values left out",)
    assert np.all(np.isnan(nothing.evaluate([0.1, 0.2])))
    with pytest.raises(ValueError):
        fit_histogram([1, 2], [1])


def test_an_undetermined_parameter_is_a_failure() -> None:
    # "b" has no effect: SciPy gives it a variance of 0, which must not read as an exact value.
    flat = FitModel("flat", "Flat", (ModelParameter("a", "a", "height"), ModelParameter("b", "b", "shape")),
                    lambda x, a, b: a + 0 * x, lambda x, y: [np.array([1.0, 1.0])],
                    lambda x, y: (np.array([0.0, 0.0]), np.array([np.inf, 10.0])))
    result = fit_histogram(np.linspace(0, 1, 20), np.full(20, 10.0), flat)
    assert result.failure == "not determined by the data: b (no usable SE)"
    assert result["a"].value == pytest.approx(10)
    assert math.isnan(result["b"].se)


def test_non_finite_bins_are_left_out_and_noted() -> None:
    x = np.linspace(0, 1, 22)
    y = 100 * np.exp(-((x - 0.5) / 0.1) ** 2 / 2)
    y[[0, 1]] = [np.nan, np.inf]
    result = fit_histogram(x, y)
    assert result.ok and result.points == 20
    assert result.notes[0] == "2 bins with non-finite values left out"
    assert result["centre"].value == pytest.approx(0.5, abs=1e-3)


def test_bounds_and_poor_models_are_noted() -> None:
    x = np.linspace(0, 1, 20)
    flat = fit_histogram(x, np.full(20, 100.0))
    assert any(note.startswith("at its bound: σ") for note in flat.notes)
    rng = np.random.default_rng(0)
    square = fit_events(rng.uniform(-1, 1, 50_000), 60, (-1.5, 1.5))
    assert any("reduced χ²" in note for note in square.notes)


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
