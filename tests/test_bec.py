"""D14: BEC properties against hand-computed values and limits, the Castin–Dum expansion against
its cigar-trap approximation, the per-axis R/σ_th cap, the new constants rows, and an end-to-end
fit → properties check on a synthetic condensate whose atom number, QE and temperature are known."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest
import scipy.constants as codata

from helab.analysis import bec, constant_layers, fits, physics, profiles
from helab.analysis.estimates import Estimate
from helab.analysis.fits import MODELS, bin_centres, fit_histogram
from helab.analysis.physics import DEFAULTS, resolve

sys.path.insert(0, str(Path(__file__).parent))
from test_bose_fits import bose_counts, tf_counts  # noqa: E402

TWO_PI = 2 * math.pi


def mean_omega(radial: float, axial: float) -> float:
    return TWO_PI * math.pow(radial ** 2 * axial, 1 / 3)


def test_coefficients() -> None:
    assert bec.TC_IDEAL == pytest.approx(0.9405, abs=1e-4)  # the "0.94"
    assert bec.FINITE_SIZE == pytest.approx(0.7275, abs=1e-4)  # the "0.73"
    assert bec.INTERACTION == pytest.approx(1.33, abs=0.01)


def test_properties_match_hand_computed_values() -> None:
    n, n0, t = 1e6, 3e5, 0.5e-6
    hbar, k_b, m, a = codata.hbar, codata.k, DEFAULTS.mass, DEFAULTS.scattering_length
    omega = mean_omega(500, 50)
    a_ho = math.sqrt(hbar / (m * omega))
    tc0 = 0.94047 * hbar * omega * n ** (1 / 3) / k_b
    assert tc0 == pytest.approx(1.0475e-6, rel=1e-3)  # 0.94 ħω̄N^{1/3}/k_B for 10⁶ atoms at (500, 500, 50) Hz
    finite = -0.72747 * (TWO_PI * 350 / omega) * n ** (-1 / 3)
    interaction = -1.326 * a / a_ho * n ** (1 / 6)
    mu = 0.5 * hbar * omega * (15 * n0 * a / a_ho) ** 0.4
    found = bec.bec_properties(n, n0, t, DEFAULTS)
    assert found.mean_frequency == pytest.approx(omega)
    assert found.oscillator_length == pytest.approx(a_ho)
    assert found.tc_ideal.value == pytest.approx(tc0, rel=1e-4)
    assert found.finite_size_shift == pytest.approx(finite, rel=1e-4)
    assert found.interaction_shift == pytest.approx(interaction, rel=1e-6)
    assert found.tc.value == pytest.approx(tc0 * (1 + finite + interaction), rel=1e-4)
    assert found.tc_finite_size.value == pytest.approx(tc0 * (1 + finite), rel=1e-4)
    assert found.t_over_tc.value == pytest.approx(t / found.tc.value)
    assert found.chemical_potential.value == pytest.approx(mu)
    radial, axial = (math.sqrt(2 * mu / (m * (TWO_PI * f) ** 2)) for f in (500, 50))
    assert [r.value for r in found.radii] == pytest.approx([radial, radial, axial])
    assert found.peak_density.value == pytest.approx(mu * m / (4 * math.pi * hbar ** 2 * a))
    assert found.mu_over_kt.value == pytest.approx(mu / (k_b * t))
    assert found.fraction.value == pytest.approx(0.3)
    assert found.t_over_tc_ideal.value == pytest.approx(0.7 ** (1 / 3))
    # Rough magnitudes for He* at these numbers: Tc ≈ 1 µK, μ ≈ 0.22 µK·k_B, R_⊥ ≈ 10 µm,
    # n0 ≈ 2·10¹⁹ m⁻³.
    assert 0.9e-6 < found.tc.value < 1.05e-6
    assert found.chemical_potential.value / k_b == pytest.approx(2.24e-7, rel=0.02)
    assert found.radii[0].value == pytest.approx(9.7e-6, rel=0.02)
    assert found.peak_density.value == pytest.approx(1.96e19, rel=0.02)
    json.dumps(found.as_record(), allow_nan=False)


def test_limits() -> None:
    isotropic = resolve(folder={"trap_radial": 200.0, "trap_axial": 200.0})
    found = bec.bec_properties(1e6, 1e5, 1e-7, isotropic)
    assert found.radii[0].value == pytest.approx(found.radii[2].value)
    assert found.finite_size_shift == pytest.approx(-bec.FINITE_SIZE * 1e-2)
    # Without interactions Tc is the ideal gas's with the finite-size shift alone.
    ideal = bec.bec_properties(1e6, 1e5, 1e-7, resolve(lab={"scattering_length": 1e-20}))
    assert ideal.tc.value == pytest.approx(ideal.tc_finite_size.value, rel=1e-9)
    # Tc ∝ N^{1/3}, μ ∝ N0^{2/5}.
    double = bec.bec_properties(8e6, 32 * 1e5, 1e-7, DEFAULTS)
    single = bec.bec_properties(1e6, 1e5, 1e-7, DEFAULTS)
    assert double.tc_ideal.value / single.tc_ideal.value == pytest.approx(2.0)
    assert double.chemical_potential.value / single.chemical_potential.value == pytest.approx(4.0)
    # (1 − N0/N)^{1/3}: 7/8 condensed is T/Tc0 = 1/2.
    assert bec.bec_properties(8e5, 7e5, math.nan, DEFAULTS).t_over_tc_ideal.value == pytest.approx(0.5)


def test_standard_errors_propagate() -> None:
    covariance = np.diag([1e4 ** 2, 3e3 ** 2, (0.02e-6) ** 2])  # N, N0, T
    found = bec.bec_properties(1e6, 3e5, 0.5e-6, DEFAULTS, covariance)
    assert found.atoms.se == pytest.approx(1e4) and found.temperature.se == pytest.approx(0.02e-6)
    assert found.tc_ideal.se / found.tc_ideal.value == pytest.approx(1e4 / 1e6 / 3, rel=1e-3)
    assert found.chemical_potential.se / found.chemical_potential.value == pytest.approx(0.4 * 0.01, rel=1e-3)
    assert found.peak_density.se / found.peak_density.value == pytest.approx(0.4 * 0.01, rel=1e-3)
    assert math.isnan(bec.bec_properties(1e6, 3e5, 0.5e-6, DEFAULTS).tc.se)  # no covariance: no SEs


def test_edge_cases_give_notes() -> None:
    def notes(atoms: float, condensed: float, temperature: float,
              constants: physics.ResolvedConstants = DEFAULTS) -> str:
        return " | ".join(bec.bec_properties(atoms, condensed, temperature, constants).notes)
    assert "trap frequencies unconfirmed" in notes(1e6, 1e5, 1e-7)
    measured = resolve(folder={"trap_radial": 480.0, "trap_axial": 45.0})
    assert "trap frequencies" not in notes(1e6, 1e5, 1e-7, constants=measured)
    no_condensate = bec.bec_properties(1e6, 0.0, 2e-6, DEFAULTS)
    assert math.isnan(no_condensate.chemical_potential.value) and math.isfinite(no_condensate.tc.value)
    assert "no condensate" in " ".join(no_condensate.notes)
    assert no_condensate.t_over_tc.value > 1
    assert "no atoms" in notes(0.0, 0.0, 1e-7)
    assert math.isnan(bec.bec_properties(-1.0, 0.0, 1e-7, DEFAULTS).tc.value)
    assert "N0 above N" in notes(1e5, 2e5, 1e-7)
    assert "no temperature" in notes(1e6, 1e5, math.nan)
    assert "Thomas–Fermi regime" in notes(1e6, 100.0, 1e-7)
    assert "first-order" in notes(1e12, 1e11, 1e-7)  # a huge cloud: the shifts are large
    assert "above the computed Tc" in notes(1e4, 1e3, 1e-5)


# Castin–Dum

def test_scaling_matches_the_cigar_approximation() -> None:
    radial, axial = TWO_PI * 1000.0, TWO_PI * 10.0  # ε = 0.01
    for t in (1e-4, 1e-3, 1e-2, 0.416):
        lambdas = bec.scaling_factors((radial, radial, axial), t)
        approx = bec.cigar_scaling(radial, axial, t)
        assert lambdas[0] == pytest.approx(lambdas[1])
        assert lambdas[0] == pytest.approx(approx[0], rel=1e-3)
        assert lambdas[2] == pytest.approx(approx[1], rel=3e-3)
    # The table's ε = 0.1: λ_z's first-order form is ~5 % off after the fall; the solved one is used.
    lambdas = bec.scaling_factors((TWO_PI * 500, TWO_PI * 500, TWO_PI * 50), 0.416)
    approx = bec.cigar_scaling(TWO_PI * 500, TWO_PI * 50, 0.416)
    assert lambdas[0] == pytest.approx(approx[0], rel=0.01) and lambdas[2] == pytest.approx(approx[1], rel=0.06)


def test_isotropic_expansion_and_edges() -> None:
    # Energy conservation in an isotropic trap: λ̇ → √(2/3) ω.
    assert bec.scaling_factors((1.0, 1.0, 1.0), 2000.0)[0] / 2000.0 == pytest.approx(math.sqrt(2 / 3), rel=2e-3)
    assert bec.scaling_factors((1.0, 2.0, 3.0), 0.0) == (1.0, 1.0, 1.0)
    with pytest.raises(ValueError):
        bec.scaling_factors((1.0, -1.0, 1.0), 1.0)


def test_release_radius_inverts_the_expansion() -> None:
    lambdas = bec.scaling_factors(bec.Trap.from_constants(DEFAULTS).omegas, DEFAULTS.fall_time)
    r0 = Estimate(10e-6, 1e-6)
    roles: tuple[tuple[bec.Role, int], ...] = (("radial", 0), ("axial", 2))
    for role, index in roles:
        back = bec.release_radius(Estimate(r0.value * lambdas[index], r0.se * lambdas[index]), role, DEFAULTS)
        assert back.value == pytest.approx(r0.value) and back.se == pytest.approx(r0.se)
    assert math.isnan(bec.release_radius(r0, "between", DEFAULTS).value)
    # A T width is a length at the detector through g t_f.
    assert bec.detector_length(Estimate(1e-4), "T", DEFAULTS).value == pytest.approx(
        DEFAULTS.g * DEFAULTS.fall_time * 1e-4)


# The cap and the trap-axis mapping

def test_axis_roles_follow_the_constant() -> None:
    assert bec.axis_roles(DEFAULTS) == {"T": "radial", "X": "between", "Y": "between"}
    assert bec.axis_roles(resolve(folder={"trap_axial_axis": 1.0})) == {"T": "axial", "X": "radial", "Y": "radial"}
    assert bec.axis_roles(resolve(folder={"trap_axial_axis": 3.0})) == {"T": "radial", "X": "radial", "Y": "axial"}


def test_caps_by_axis() -> None:
    caps = bec.axis_caps(DEFAULTS)
    # Radial (and between): √(2μ/k_BT) = 2 at μ = 2 k_B T, a hair less at ε = 0.1 after the fall.
    assert caps["T"] == caps["X"] == caps["Y"] == pytest.approx(2.0, rel=0.01)
    along_y = bec.axis_caps(resolve(folder={"trap_axial_axis": 3.0}))
    assert along_y["Y"] == pytest.approx(math.pi / 2 * 0.1 * 2.0, rel=0.01)  # (π/2) ε √(2μ/k_BT)
    assert along_y["Y"] == pytest.approx(bec.radius_ratio_cap("axial", DEFAULTS))
    isotropic = resolve(folder={"trap_radial": 200.0, "trap_axial": 200.0})
    assert bec.radius_ratio_cap("radial", isotropic, mu_over_kt=3.0) == pytest.approx(math.sqrt(4 * 3.0 / 3), rel=3e-3)
    assert bec.radius_ratio_cap("radial", DEFAULTS, mu_over_kt=8.0) == pytest.approx(4.0, rel=0.01)
    with pytest.raises(ValueError):
        bec.radius_ratio_cap("radial", DEFAULTS, mu_over_kt=0.0)


# The new constants rows

def test_the_new_rows_validate() -> None:
    assert DEFAULTS.detector_qe == 0.1 and DEFAULTS.trap_axial_axis == 4.0
    assert physics.TABLE["trap_axial_axis"].label(4.0) == "between X and Y"
    with pytest.raises(ValueError, match="at most 1"):
        resolve(lab={"detector_qe": 1.5})
    with pytest.raises(ValueError, match="one of 1, 2, 3, 4"):
        resolve(folder={"trap_axial_axis": 2.5})
    assert constant_layers.clean_layer({"detector_qe": 2.0, "trap_axial_axis": 2.5}) == {}
    assert constant_layers.clean_layer({"detector_qe": 0.08, "trap_axial_axis": 2}) == {
        "detector_qe": 0.08, "trap_axial_axis": 2.0}
    assert constant_layers.value_text("trap_axial_axis", 2.0) == "X"
    assert constant_layers.value_text("detector_qe", 0.1) == "0.1"
    specs = constant_layers.constants_specs(("detector_qe", "trap_axial_axis"))
    assert specs[1].limits is not None and specs[1].limits[1] == 1.0
    assert specs[3].kind == "int" and specs[3].limits == (1.0, 4.0) and "2 = X" in specs[3].tip
    overrides = constant_layers.plot_overrides({specs[2].name: constant_layers.SET_HERE, specs[3].name: 3})
    assert resolve(plot=overrides).trap_axial_axis == 3.0
    record = json.loads(json.dumps(DEFAULTS.as_record()))
    record["values"]["trap_axial_axis"] = 2.5
    with pytest.raises(ValueError):
        physics.ResolvedConstants.from_record(record)


# End to end

def physical_condensate(constants: physics.ResolvedConstants, qe: float, shots: int, condensed: float,
                        temperature: float) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], float, float]:
    """(edges, counts, thermal atoms, R(0)) of a TF condensate of ``condensed`` atoms on a saturated
    ideal thermal cloud at ``temperature``, along X (radial), detected at ``qe`` over ``shots``."""
    trap = bec.Trap.from_constants(constants)
    thermal = bec.ZETA3 * (constants.k_B * temperature / (constants.hbar * trap.mean)) ** 3
    a_ho = trap.oscillator_length(constants)
    mu = 0.5 * constants.hbar * trap.mean * (15 * condensed * constants.scattering_length / a_ho) ** 0.4
    r0 = math.sqrt(2 * mu / (constants.mass * trap.radial ** 2))
    r_detector = r0 * bec.scaling_factors(trap.omegas, constants.fall_time)[0]
    sigma = math.sqrt(constants.k_B * temperature / constants.mass) * constants.fall_time
    edges = np.linspace(-0.06, 0.06, 241)
    expected = (tf_counts(edges, condensed * qe * shots, r_detector)
                + bose_counts(edges, thermal * qe * shots, sigma, 1.0))
    return edges, np.random.default_rng(12).poisson(expected).astype(np.float64), thermal, r0


def test_the_condensate_check_compares_mu_both_ways() -> None:
    """fit_axis with the shot count checks μ/k_BT from R/σ_th against μ/k_BT from N0 and T: with the
    true QE they agree and the condensate stands; with a QE 10× too low N0 is 10× too high, μ from
    it 2.5× too high, and the condensate is only "possible"."""
    constants = resolve(folder={"trap_axial_axis": 3.0})
    edges, counts, _, _ = physical_condensate(constants, 0.1, 20, 3e5, 0.6e-6)
    right = profiles.fit_axis("X", edges, counts, profiles.BIMODAL_BOSE, constants, shots=20)
    assert right.fit.model.key == "bimodal_tf2_g2_5" and any(n.startswith("condensate: ") for n in right.notes)
    check = profiles.mu_consistency("X", constants, float(edges[1] - edges[0]), 20)
    assert check(right.fit)[0] is True
    wrong_qe = resolve(lab={"detector_qe": 0.01}, folder={"trap_axial_axis": 3.0})
    wrong = profiles.fit_axis("X", edges, counts, profiles.BIMODAL_BOSE, wrong_qe, shots=20)
    assert wrong.fit.model.key == "bose_g2_5"
    assert any(n.startswith("possible condensate") and "disagree" in n for n in wrong.notes)
    # Unknown shots, or an axis between the trap's axes: not checked, and said so.
    assert profiles.mu_consistency("X", constants, 1e-3, None)(right.fit)[0] is None
    assert profiles.mu_consistency("X", resolve(), 1e-3, 20)(right.fit)[0] is None
    unchecked = profiles.fit_axis("X", edges, counts, profiles.BIMODAL_BOSE, constants)
    assert any("check skipped: no shot count" in n for n in unchecked.notes)


def test_a_thermal_qe_far_from_the_set_one_is_noted() -> None:
    constants = resolve(folder={"trap_axial_axis": 3.0})
    edges, counts, _, _ = physical_condensate(constants, 0.1, 20, 3e5, 0.6e-6)
    fit = fit_histogram(bin_centres(edges), counts, "bimodal_tf2_g2_5")
    width = float(edges[1] - edges[0])
    assert not any("disagree" in n for n in bec.from_fit(fit, "X", constants, width, 20).notes)
    off = bec.from_fit(fit, "X", resolve(lab={"detector_qe": 0.5}, folder={"trap_axial_axis": 3.0}), width, 20)
    assert any("the trap frequencies, T or the QE disagree" in n for n in off.notes)


def test_from_fit_recovers_the_condensate_and_the_qe() -> None:
    """A condensate of 3·10⁵ atoms on a thermal cloud at 0.6 µK, detected at QE 0.1 along X (a radial
    axis: Y is the trap's long one), 20 shots: N, N0, T and the QE its TF radius implies come back
    within their SEs."""
    constants = resolve(folder={"trap_axial_axis": 3.0, "trap_radial": 500.0, "trap_axial": 50.0})
    qe, shots, condensed, temperature = 0.1, 20, 3e5, 0.6e-6
    trap = bec.Trap.from_constants(constants)
    # A saturated ideal thermal cloud: ζ(3)(k_B T/ħω̄)³ atoms (1.9·10⁵ here).
    thermal = bec.ZETA3 * (constants.k_B * temperature / (constants.hbar * trap.mean)) ** 3
    a_ho = trap.oscillator_length(constants)
    mu = 0.5 * constants.hbar * trap.mean * (15 * condensed * constants.scattering_length / a_ho) ** 0.4
    r0 = math.sqrt(2 * mu / (constants.mass * trap.radial ** 2))
    r_detector = r0 * bec.scaling_factors(trap.omegas, constants.fall_time)[0]
    sigma = math.sqrt(constants.k_B * temperature / constants.mass) * constants.fall_time
    edges = np.linspace(-0.06, 0.06, 241)
    expected = (tf_counts(edges, condensed * qe * shots, r_detector)
                + bose_counts(edges, thermal * qe * shots, sigma, 1.0))
    counts = np.random.default_rng(12).poisson(expected).astype(np.float64)
    fit = fit_histogram(bin_centres(edges), counts, "bimodal_tf2_g2_5", max_radius_ratio=bec.axis_caps(constants)["X"])
    assert fit.ok, fit.failure
    found = bec.from_fit(fit, "X", constants, float(edges[1] - edges[0]), shots)
    assert abs(found.atoms.value - (condensed + thermal)) < 3 * found.atoms.se
    assert abs(found.condensed.value - condensed) < 3 * found.condensed.se
    assert abs(found.temperature.value - temperature) < 3 * found.temperature.se
    assert abs(found.fraction.value - condensed / (condensed + thermal)) < 3 * found.fraction.se
    check = found.from_radius
    assert check is not None and check.role == "radial"
    assert abs(check.in_trap.value - r0) < 3 * check.in_trap.se
    assert abs(check.implied_qe.value - qe) < 3 * check.implied_qe.se
    assert abs(check.condensed.value - condensed) < 3 * check.condensed.se
    assert abs(found.saturated_thermal.value - thermal) < 3 * found.saturated_thermal.se
    assert abs(found.implied_qe_thermal.value - qe) < 3 * found.implied_qe_thermal.se
    text = " | ".join(found.notes)
    for words in ("detector QE unconfirmed", "saturate", "per shot", "QE^−1/3", "QE^−2/5", "QE from the thermal",
                  "jitter"):
        assert words in text
    assert "trap frequencies" not in text
    json.dumps(found.as_record(), allow_nan=False)
    # Along the axis between the trap's axes there is no R(0).
    between = bec.from_fit(fit, "X", resolve(), float(edges[1] - edges[0]), shots)
    assert between.from_radius is not None and math.isnan(between.from_radius.in_trap.value)
    assert any("between the trap's axes" in note for note in between.notes)


def test_from_fit_without_a_fit_says_why() -> None:
    failed = fit_histogram([], [], "bimodal_tf2_g2_5")
    found = bec.from_fit(failed, "T", DEFAULTS, 1e-5, 10)
    assert math.isnan(found.tc.value) and found.notes == ("no BEC properties: no data to fit",)
    assert found.from_radius is None
    thermal = fit_histogram(bin_centres(np.linspace(-5e-3, 5e-3, 101)),
                            np.random.default_rng(1).poisson(bose_counts(np.linspace(-5e-3, 5e-3, 101), 1e5, 1e-3, 0.5)
                                                             ).astype(np.float64), "bose_g2_5")
    above = bec.from_fit(thermal, "Y", DEFAULTS, 1e-4, 10)
    assert above.condensed.value == 0 and math.isfinite(above.tc.value) and math.isnan(above.chemical_potential.value)


def test_a_slice_fit_gives_t_and_r0_only() -> None:
    """A thin slice (TF^3/2 + g_2) holds part of the cloud: no N, N0/N, Tc, μ, n0 or implied QE,
    only T and R(0), with the slice note."""
    constants = resolve(folder={"trap_axial_axis": 3.0})  # X radial
    model = MODELS["bimodal_tf1_5_g2"]
    edges = np.linspace(-0.04, 0.04, 161)
    truth = model.function(bin_centres(edges), 300.0, 0.0, 0.8, 150.0, 0.0147, 1.0)
    counts = np.random.default_rng(3).poisson(truth).astype(np.float64)
    fit = fit_histogram(bin_centres(edges), counts, model)
    assert fit.ok and fits.SLICE_NOTE in fit.notes
    found = bec.from_fit(fit, "X", constants, float(edges[1] - edges[0]), 1)
    for name in ("atoms", "condensed", "fraction", "tc", "t_over_tc", "chemical_potential", "peak_density",
                 "implied_qe_thermal"):
        assert math.isnan(getattr(found, name).value), name
    assert math.isfinite(found.temperature.value) and found.temperature.se > 0
    assert found.from_radius is not None and math.isfinite(found.from_radius.in_trap.value)
    for value in (found.from_radius.implied_qe, found.from_radius.condensed, found.from_radius.chemical_potential):
        assert math.isnan(value.value)
    assert fits.SLICE_NOTE in found.notes and not any("no atoms" in note for note in found.notes)
    json.dumps(found.as_record(), allow_nan=False)
