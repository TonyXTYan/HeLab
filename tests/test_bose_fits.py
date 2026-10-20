"""D4: polylogarithms, the Bose-enhanced thermal fits (g_5/2, g_2), the bimodal TF + Bose fits and
the condensate fraction with its SE, on synthetic clouds whose expected counts are computed
independently of the fit code (a Bose profile as its sum of Gaussians, a TF² projection from its CDF)."""
from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt
import pytest
from scipy.special import ndtr, zeta

from helab.analysis import fits, profiles
from helab.analysis.fits import (MODELS, bin_centres, bose_area, component_areas, condensate_fraction, fit_histogram,
                                 polylog)
from helab.analysis.physics import DEFAULTS
from helab.analysis.profiles import fit_axis

Array = npt.NDArray[np.float64]
TERMS = 4000  # Gaussians in a Bose profile's sum: the left-out weight at z = 1 is ~1/(2·TERMS²)


def bose_counts(edges: Array, events: float, sigma: float, fugacity: float, order: float = 2.5,
                centre: float = 0.0) -> Array:
    """Expected counts per bin of a 1D Bose profile g_ν(z e^{−x²/2σ²}) holding ``events``: the
    sum over k of Gaussians of σ/√k weighted z^k/k^{ν+1/2} (each term's area), by their CDFs."""
    k = np.arange(1, TERMS + 1, dtype=np.float64)
    weights = fugacity ** k / k ** (order + 0.5)
    weights /= weights.sum()
    cdf = ndtr((edges[:, None] - centre) / (sigma / np.sqrt(k))[None, :]) @ weights
    return np.asarray(events * np.diff(cdf), dtype=np.float64)


def tf_counts(edges: Array, events: float, radius: float, centre: float = 0.0) -> Array:
    """Expected counts per bin of a TF² projection (1 − u²)² holding ``events``, by its CDF."""
    u = np.clip((edges - centre) / radius, -1, 1)
    cdf = (u - 2 * u ** 3 / 3 + u ** 5 / 5) * 15 / 16
    return np.asarray(events * np.diff(cdf), dtype=np.float64)


# Polylogarithms

def test_polylog_known_values() -> None:
    ln2 = math.log(2)
    assert polylog(2.0, 1.0) == pytest.approx(math.pi ** 2 / 6, rel=1e-13)
    assert polylog(2.0, 0.5) == pytest.approx(math.pi ** 2 / 12 - ln2 ** 2 / 2, rel=1e-13)
    assert polylog(3.0, 0.5) == pytest.approx(7 / 8 * zeta(3) - math.pi ** 2 * ln2 / 12 + ln2 ** 3 / 6, rel=1e-13)
    assert polylog(3.0, 1.0) == pytest.approx(1.2020569031595942, rel=1e-13)
    assert polylog(2.5, 1.0) == pytest.approx(1.3414872572509172, rel=1e-13)
    assert polylog(2.5, 0.0) == 0.0
    assert polylog(2.5, 1e-9) == pytest.approx(1e-9, rel=1e-9)
    with pytest.raises(ValueError):
        polylog(1.0, 0.5)


@pytest.mark.parametrize("order", [2.0, 2.5, 3.0])
def test_polylog_matches_its_series_on_both_sides_of_the_split(order: float) -> None:
    x = np.array([0.05, 0.3, math.exp(-1) * (1 - 1e-12), math.exp(-1) * (1 + 1e-12), 0.5, 0.8, 0.95, 0.99, 0.999])
    k = np.arange(1, 200_001, dtype=np.float64)
    series = np.array([np.sum(value ** k / k ** order) for value in x])
    assert np.allclose(polylog(order, x), series, rtol=2e-13, atol=0)
    assert polylog(order, np.array([[0.2, 1.0]])).shape == (1, 2)


def test_bose_area_is_the_profiles_integral() -> None:
    x = np.linspace(-12, 12, 20_001)
    for order, z in ((2.5, 1.0), (2.5, 0.4), (2.0, 0.9), (2.0, 1e-14)):
        profile = MODELS["bose_g2_5" if order == 2.5 else "bose_g2"](x, [3.0, 0.0, 1.5, z, 0.0])
        assert float(np.trapezoid(profile, x)) == pytest.approx(bose_area(3.0, 1.5, z, order), rel=1e-6)
    # z → 0 is the Gaussian.
    assert bose_area(2.0, 1.0, 0.0) == pytest.approx(2.0 * math.sqrt(2 * math.pi))


# Thermal fits

@pytest.mark.parametrize("fugacity", [0.6, 0.97])
def test_the_bose_fit_recovers_t_where_a_gaussian_is_biased(fugacity: float) -> None:
    """A Bose cloud near Tc: the g_5/2 fit's σ (so T) is within its SE; a Gaussian's is many SEs low."""
    rng = np.random.default_rng(5)
    edges = np.linspace(-5e-3, 5e-3, 121)
    sigma = 1e-3
    counts = rng.poisson(bose_counts(edges, 2e5, sigma, fugacity)).astype(np.float64)
    bose = fit_axis("X", edges, counts, profiles.BOSE, DEFAULTS)
    gauss = fit_axis("X", edges, counts, profiles.GAUSSIAN, DEFAULTS)
    assert bose.ok and gauss.ok
    true_t = DEFAULTS.mass * (sigma / DEFAULTS.fall_time) ** 2 / DEFAULTS.k_B
    assert abs(bose.temperature.value - true_t) < 3 * bose.temperature.se
    assert abs(bose.fit["fugacity"].value - fugacity) < 3 * bose.fit["fugacity"].se
    assert (true_t - gauss.temperature.value) > 8 * gauss.temperature.se  # biased low
    assert "z (" in bose.text() or "z 0" in bose.text()


def test_the_g2_profile_fits_a_slice() -> None:
    rng = np.random.default_rng(6)
    edges = np.linspace(-5e-3, 5e-3, 101)
    counts = rng.poisson(bose_counts(edges, 1e5, 1.2e-3, 0.9, order=2.0, centre=3e-4)).astype(np.float64)
    fit = fit_histogram(bin_centres(edges), counts, "bose_g2")
    assert fit.ok and not fit.notes
    assert abs(fit["sigma"].value - 1.2e-3) < 3 * fit["sigma"].se
    assert abs(fit["centre"].value - 3e-4) < 3 * fit["centre"].se


def test_fugacity_at_its_ends_is_noted_not_called_a_bound() -> None:
    edges = np.linspace(-5e-3, 5e-3, 121)
    centres = bin_centres(edges)
    rng = np.random.default_rng(7)
    saturated = fit_histogram(centres, rng.poisson(bose_counts(edges, 5e5, 1e-3, 1.0)).astype(np.float64),
                              "bose_g2_5")
    gaussian = fit_histogram(centres, rng.poisson(bose_counts(edges, 5e5, 1e-3, 1e-6)).astype(np.float64),
                             "bose_g2_5")
    for fit, words in ((saturated, "saturated"), (gaussian, "Boltzmann")):
        if fit["fugacity"].value >= fits.FUGACITY_SATURATED or fit["fugacity"].value <= 1 - fits.FUGACITY_SATURATED:
            assert any(words in note for note in fit.notes)
        assert not any("at its bound" in note and "Fugacity" in note for note in fit.notes)
    assert saturated["fugacity"].value > 0.95


# Bimodal fits and the condensate fraction

@pytest.mark.parametrize("fraction", [0.15, 0.5])
def test_the_bimodal_bose_fit_recovers_n0_over_n_and_r(fraction: float) -> None:
    rng = np.random.default_rng(int(fraction * 100))
    edges = np.linspace(-6e-3, 6e-3, 161)
    events, sigma, radius = 2e5, 1e-3, 1.5e-3
    expected = tf_counts(edges, fraction * events, radius) + bose_counts(edges, (1 - fraction) * events, sigma, 1.0)
    counts = rng.poisson(expected).astype(np.float64)
    fit = fit_histogram(bin_centres(edges), counts, "bimodal_tf2_g2_5", max_radius_ratio=3.0)
    assert fit.ok, fit.failure
    found = condensate_fraction(fit)
    assert abs(found.value - fraction) < 3 * found.se
    assert abs(fit["radius"].value - radius) < 3 * fit["radius"].se
    assert abs(fit["sigma"].value - sigma) < 3 * fit["sigma"].se
    areas = component_areas(fit)
    assert set(areas) == {"thomas_fermi", "bose"}
    width = float(edges[1] - edges[0])
    assert (areas["thomas_fermi"].value + areas["bose"].value) / width == pytest.approx(counts.sum(), rel=0.01)
    assert MODELS["bimodal_tf2_g2_5"].fixed == {"fugacity": 1.0}
    # The Gaussian thermal part, on the same Bose cloud, overstates the condensate.
    biased = condensate_fraction(fit_histogram(bin_centres(edges), counts, "bimodal_tf2_gaussian",
                                               max_radius_ratio=3.0))
    assert biased.value - fraction > 3 * biased.se


def test_the_condensate_fractions_se_matches_its_spread() -> None:
    """The delta-method SE of N0/N (from the fit's covariance, the areas' correlation included)
    agrees with the spread over repeated clouds."""
    edges = np.linspace(-6e-3, 6e-3, 121)
    expected = tf_counts(edges, 6000, 1.5e-3) + bose_counts(edges, 14000, 1e-3, 1.0)
    values, ses = [], []
    for seed in range(24):
        counts = np.random.default_rng(100 + seed).poisson(expected).astype(np.float64)
        fit = fit_histogram(bin_centres(edges), counts, "bimodal_tf2_g2_5", max_radius_ratio=3.0)
        assert fit.ok
        found = condensate_fraction(fit)
        values.append(found.value)
        ses.append(found.se)
    spread, typical = float(np.std(values, ddof=1)), float(np.mean(ses))
    assert 0.6 < spread / typical < 1.5
    assert abs(float(np.mean(values)) - 0.3) < 3 * typical / math.sqrt(len(values)) + 0.005


def test_the_slice_pairing_fits_tf_three_halves_with_g2() -> None:
    model = MODELS["bimodal_tf1_5_g2"]
    edges = np.linspace(-6e-3, 6e-3, 161)
    centres = bin_centres(edges)
    truth = model.function(centres, 300.0, 0.0, 1.4, 150.0, 1.1e-3, 1.0)
    counts = np.random.default_rng(9).poisson(truth).astype(np.float64)
    fitted = fit_axis("Y", edges, counts, profiles.BIMODAL_BOSE_SLICE, DEFAULTS)
    assert fitted.ok, fitted.failure
    assert abs(fitted.fit["radius"].value - 1.4 * 1.1e-3) < 3 * fitted.fit["radius"].se
    assert "N0/N" in fitted.text() and "R (" in fitted.text()


def test_no_condensate_gives_no_fraction() -> None:
    edges = np.linspace(-5e-3, 5e-3, 101)
    counts = np.random.default_rng(3).poisson(bose_counts(edges, 1e5, 1e-3, 0.5)).astype(np.float64)
    thermal_only = fit_histogram(bin_centres(edges), counts, "bose_g2_5")
    assert math.isnan(condensate_fraction(thermal_only).value)
    assert set(component_areas(thermal_only)) == {"bose"}
    failed = fit_histogram([], [], "bimodal_tf2_g2_5")
    assert math.isnan(condensate_fraction(failed).value)
    assert all(math.isnan(area.value) for area in component_areas(failed).values())


def test_the_new_models_are_offered_with_their_caveats() -> None:
    for choice in (profiles.BOSE, profiles.BOSE_SLICE, profiles.BIMODAL_BOSE, profiles.BIMODAL_BOSE_SLICE):
        assert choice in profiles.T_MODELS and choice in profiles.XY_MODELS
        assert profiles.MODEL_KEYS[choice] in MODELS
    for words in ("fugacity", "g_5/2 for a full projection", "biases T low", "(π/2)(ω_z/ω_⊥)", "Trap axial axis",
                  "z fixed at 1"):
        assert words in profiles.TF_EXPONENT_TIP


def test_fit_axis_takes_the_axis_cap_when_asked() -> None:
    from helab.analysis import bec, physics
    constants = physics.resolve(folder={"trap_axial_axis": 2.0})  # X is the trap's long axis
    edges = np.linspace(-6e-3, 6e-3, 161)
    expected = tf_counts(edges, 5e4, 1.5e-3) + bose_counts(edges, 1e5, 1e-3, 1.0)
    counts = np.random.default_rng(4).poisson(expected).astype(np.float64)
    along_x = fit_axis("X", edges, counts, profiles.BIMODAL_BOSE, constants, max_radius_ratio=None)
    along_y = fit_axis("Y", edges, counts, profiles.BIMODAL_BOSE, constants, max_radius_ratio=None)
    caps = bec.axis_caps(constants)
    assert along_x.fit.options["max_radius_ratio"] == caps["X"] < 0.4
    assert along_y.fit.options["max_radius_ratio"] == caps["Y"] == pytest.approx(2.0, rel=0.01)
    # R/σ = 1.5 is beyond an axial cap: the capped fit says it can't describe the cloud.
    assert along_x.fit["ratio"].value <= caps["X"]
    assert any("at its limit" in note or "doesn't describe" in note for note in along_x.notes)
    assert along_y.ok and not any("doesn't describe" in note for note in along_y.notes)
