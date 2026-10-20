"""BEC properties beside the bimodal fits (D14): Tc, μ, the Thomas–Fermi radii and the peak density
from the atom numbers, the temperature and the trap, with ± SE; the Castin–Dum expansion that links
a radius measured after the fall to the one in the trap; and the per-axis cap on a bimodal fit's
R/σ_th (D4).

Formulas, from the physics (Dalfovo, Giorgini, Pitaevskii & Stringari, RMP 71, 463 (1999), §II–III;
Pitaevskii & Stringari, *Bose–Einstein Condensation* (2003), ch. 10–11), not from the legacy MATLAB:

- Trap: ω̄ = (ω_x ω_y ω_z)^{1/3} (cylindrical: (ω_⊥² ω_z)^{1/3}), ω_arith = (ω_x + ω_y + ω_z)/3,
  a_ho = √(ħ / m ω̄). Frequencies are the table's f_r, f_r, f_a (2π f).
- Ideal-gas Tc: k_B Tc0 = ħ ω̄ (N / ζ(3))^{1/3} = 0.9405 ħ ω̄ N^{1/3}.
- Finite size (Grossmann & Holthaus 1995): δTc/Tc0 = −ζ(2)/(2 ζ(3)^{2/3}) (ω_arith/ω̄) N^{−1/3}
  = −0.7275 (ω_arith/ω̄) N^{−1/3}.
- Interactions, first order (Giorgini, Pitaevskii & Stringari 1996): δTc/Tc0 = −1.326 (a/a_ho) N^{1/6}.
  Tc = Tc0 (1 + both). ``TC_SHIFT_NOTE``: the expansion is noted when the shift is large.
- Below Tc, ideal gas: N0/N = 1 − (T/Tc0)³, so T/Tc0 = (1 − N0/N)^{1/3} (``t_over_tc_ideal``).
- Thomas–Fermi: μ = ½ ħ ω̄ (15 N0 a / a_ho)^{2/5}; R_i = √(2μ / m ω_i²); peak density
  n0 = μ / g with g = 4π ħ² a / m. Valid for N0 a/a_ho ≫ 1 (noted below ``TF_REGIME``).
- Expansion (Castin & Dum, PRL 77, 5315 (1996)): R_i(t) = λ_i(t) R_i(0) with
  λ̈_i = ω_i² / (λ_i λ_x λ_y λ_z), λ_i(0) = 1, λ̇_i(0) = 0 (``scaling_factors``, solved; for a cigar
  ε = ω_z/ω_⊥ ≪ 1, to first order, λ_⊥ = √(1 + τ²) and λ_z = 1 + ε² (τ arctan τ − ln √(1 + τ²)),
  τ = ω_⊥ t: ``cigar_scaling``). A bimodal fit's R is R(t_f), at the detector; ``release_radius`` gives R(0),
  and from it μ and N0 without the detector's QE (``RadiusCheck``: the QE that N0 implies).
- The R/σ_th cap: a thermal cloud's width after t is σ_i(t) = √(k_B T/m) √(t² + 1/ω_i²), so
  R_i(t)/σ_i(t) = √(2μ/k_B T) λ_i(t)/√(1 + ω_i² t²): at long t, √(2μ/k_B T) along a cigar's radial
  axes, √(4μ/3k_B T) in an isotropic trap and ≈ (π/2) ε √(2μ/k_B T) along a cigar's axis
  (``radius_ratio_cap``). A detector axis between the trap's axes (the default mapping for X and Y)
  sees a projected R no larger than the radial one, so it takes the radial cap.

Atom numbers are counts / QE (``physics`` row ``detector_qe``, unconfirmed). Every result carries
its notes (unconfirmed constants, saturation, regimes). SEs are first order (``estimates.propagate``)
from the covariance of (N, N0, T) — which ``from_fit`` builds from the fit's own covariance, so the
correlation of N and N0 counts — and leave out the constants' own uncertainty. A shot bootstrap
(D10) of a whole fit is the fuller error: ``FIT_N_BOOT`` resamples are enough for an SE to ~5 %.

Pure NumPy/SciPy, no Qt, no I/O.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Literal, Mapping, Sequence

import numpy as np
import numpy.typing as npt
from scipy.integrate import solve_ivp
from scipy.special import zeta

from helab.analysis.estimates import Estimate, propagate
from helab.analysis.fits import CONDENSATE_AREA, SLICE_NOTE, FitResult
from helab.analysis.physics import ResolvedConstants

Array = npt.NDArray[np.float64]
Axis = Literal["T", "X", "Y"]
AXES: tuple[Axis, ...] = ("T", "X", "Y")
# How a detector axis lies against the trap: along a radial axis, along the axial one, or between
# them (in the XY plane, at an unknown angle).
Role = Literal["radial", "axial", "between"]

ZETA3 = float(zeta(3.0))
TC_IDEAL = ZETA3 ** (-1 / 3)  # 0.9405
FINITE_SIZE = float(zeta(2.0)) / (2 * float(zeta(3.0)) ** (2 / 3))  # 0.7275
INTERACTION = 1.326  # Giorgini, Pitaevskii & Stringari, PRA 54, R4633 (1996)
TC_SHIFT_NOTE = 0.1  # a Tc shift beyond this share of Tc0 is noted: the first-order expansions are rough
TF_REGIME = 10.0  # N0 a/a_ho below this: the Thomas–Fermi formulas are rough
# The default μ/k_B T the cap allows: √(2·2) = 2 on a radial axis, fits.MAX_RADIUS_RATIO.
DEFAULT_MU_OVER_KT = 2.0
# Shot-bootstrap resamples recommended for a fit's SE (each resample refits): 1/√(2·200) ≈ 5 %.
FIT_N_BOOT = 200
SCALING_RTOL = 1e-10

AXIAL_AXIS_CODES: Mapping[float, Axis | None] = {1.0: "T", 2.0: "X", 3.0: "Y", 4.0: None}


@dataclass(frozen=True)
class Trap:
    """A harmonic trap's angular frequencies along its own axes: (radial, radial, axial) for the
    table's cylindrical trap."""
    omegas: tuple[float, float, float]

    @classmethod
    def from_constants(cls, constants: ResolvedConstants) -> Trap:
        radial, axial = 2 * math.pi * constants.trap_radial, 2 * math.pi * constants.trap_axial
        return cls((radial, radial, axial))

    @property
    def mean(self) -> float:
        """ω̄, the geometric mean."""
        return math.pow(float(np.prod(self.omegas)), 1 / 3)

    @property
    def arithmetic(self) -> float:
        return sum(self.omegas) / 3

    @property
    def radial(self) -> float:
        return self.omegas[0]

    @property
    def axial(self) -> float:
        return self.omegas[2]

    def omega(self, role: Role) -> float:
        """The frequency along a role's axis (between: the radial one, as the cap takes it)."""
        return self.axial if role == "axial" else self.radial

    def oscillator_length(self, constants: ResolvedConstants) -> float:
        """a_ho = √(ħ / m ω̄)."""
        return math.sqrt(constants.hbar / (constants.mass * self.mean))


def axis_roles(constants: ResolvedConstants) -> dict[Axis, Role]:
    """Each detector axis's role from ``trap_axial_axis``: the axial axis named is "axial" and the
    other two "radial"; with the axial axis between X and Y (code 4, the default), T is radial and X
    and Y are "between"."""
    axial = AXIAL_AXIS_CODES.get(constants.trap_axial_axis)
    if axial is None:
        return {"T": "radial", "X": "between", "Y": "between"}
    return {axis: ("axial" if axis == axial else "radial") for axis in AXES}


# Expansion

def scaling_factors(omegas: Sequence[float], t: float) -> tuple[float, ...]:
    """Castin–Dum λ_i(t) for a Thomas–Fermi condensate released at t = 0 from a trap with these
    angular frequencies: λ̈_i = ω_i² / (λ_i Π λ_j), λ_i(0) = 1, λ̇_i(0) = 0, solved numerically
    (in τ = ω_max t). (1, …) at t ≤ 0."""
    rates = np.asarray(omegas, dtype=np.float64)
    if not (np.all(rates > 0) and np.all(np.isfinite(rates))):
        raise ValueError("trap frequencies must be positive and finite")
    if not t > 0:
        return tuple(1.0 for _ in rates)
    scale = float(rates.max())
    squared = (rates / scale) ** 2
    count = len(rates)

    def derivative(_: float, state: Array) -> Array:
        lambdas, speeds = state[:count], state[count:]
        return np.concatenate([speeds, squared / (lambdas * float(np.prod(lambdas)))])
    solution = solve_ivp(derivative, (0.0, scale * t), np.concatenate([np.ones(count), np.zeros(count)]),
                         method="DOP853", rtol=SCALING_RTOL, atol=1e-12)
    if not solution.success:
        raise RuntimeError(f"Castin–Dum scaling equations failed: {solution.message}")
    return tuple(float(value) for value in solution.y[:count, -1])


def cigar_scaling(omega_radial: float, omega_axial: float, t: float) -> tuple[float, float]:
    """(λ_⊥, λ_z) for a cigar trap to first order in ε = ω_z/ω_⊥ (Castin & Dum 1996):
    λ_⊥ = √(1 + τ²), λ_z = 1 + ε² (τ arctan τ − ln √(1 + τ²)), τ = ω_⊥ t. For orientation only:
    at the table's ε = 0.1, λ_z is 5 % off after the fall. Everything else here uses the solved
    ``scaling_factors``."""
    tau, epsilon = omega_radial * t, omega_axial / omega_radial
    return (math.sqrt(1 + tau ** 2),
            1 + epsilon ** 2 * (tau * math.atan(tau) - 0.5 * math.log1p(tau ** 2)))


def _trap_scaling(trap: Trap, t: float) -> dict[Role, float]:
    lambdas = scaling_factors(trap.omegas, t)
    return {"radial": lambdas[0], "between": lambdas[0], "axial": lambdas[2]}


def radius_ratio_cap(role: Role, constants: ResolvedConstants, mu_over_kt: float = DEFAULT_MU_OVER_KT,
                     t: float | None = None) -> float:
    """The largest R/σ_th a condensate with μ/k_B T up to ``mu_over_kt`` shows along an axis of
    this role after ``t`` (the fall time by default): √(2μ/k_B T) λ_i(t)/√(1 + ω_i² t²), with the
    trap's frequencies (``Trap.from_constants``). An axis between the trap's axes takes the radial
    cap, the largest. For ``fit_histogram(max_radius_ratio=…)``."""
    if not mu_over_kt > 0:
        raise ValueError("μ/k_B T must be positive")
    trap = Trap.from_constants(constants)
    time = constants.fall_time if t is None else t
    omega = trap.omega(role)
    return math.sqrt(2 * mu_over_kt) * _trap_scaling(trap, time)[role] / math.sqrt(1 + (omega * time) ** 2)


def axis_caps(constants: ResolvedConstants, mu_over_kt: float = DEFAULT_MU_OVER_KT) -> dict[Axis, float]:
    """``radius_ratio_cap`` for T, X and Y by their roles (``axis_roles``)."""
    trap = Trap.from_constants(constants)
    scaling = _trap_scaling(trap, constants.fall_time)
    roles = axis_roles(constants)
    return {axis: math.sqrt(2 * mu_over_kt) * scaling[roles[axis]]
            / math.sqrt(1 + (trap.omega(roles[axis]) * constants.fall_time) ** 2) for axis in AXES}


def detector_length(width: Estimate, axis: Axis, constants: ResolvedConstants) -> Estimate:
    """A width or radius fitted on ``axis`` as a length at the detector: X and Y are lengths; a
    T width δt is g t_f δt (the atoms arrive moving at g t_f)."""
    factor = constants.g * constants.fall_time if axis == "T" else 1.0
    return Estimate(width.value * factor, abs(width.se * factor))


def release_radius(radius_at_detector: Estimate, role: Role, constants: ResolvedConstants) -> Estimate:
    """R(0) = R(t_f) / λ(t_f) along a trap axis (Castin–Dum); nan for an axis between the trap's
    axes, whose projected R mixes them."""
    if role == "between":
        return Estimate(math.nan, math.nan)
    scale = _trap_scaling(Trap.from_constants(constants), constants.fall_time)[role]
    return Estimate(radius_at_detector.value / scale, abs(radius_at_detector.se / scale))


# Properties

def _quantities(atoms: float, condensed: float, temperature: float, constants: ResolvedConstants
                ) -> dict[str, float]:
    """Every property from (N, N0, T), floats (nan where undefined)."""
    trap = Trap.from_constants(constants)
    hbar, k_b, mass, a = constants.hbar, constants.k_B, constants.mass, constants.scattering_length
    a_ho = trap.oscillator_length(constants)
    out: dict[str, float] = {}
    if atoms > 0:
        tc0 = TC_IDEAL * hbar * trap.mean * atoms ** (1 / 3) / k_b
        finite = -FINITE_SIZE * trap.arithmetic / trap.mean * atoms ** (-1 / 3)
        interaction = -INTERACTION * a / a_ho * atoms ** (1 / 6)
        out.update(tc_ideal=tc0, tc_finite_size=tc0 * (1 + finite), tc=tc0 * (1 + finite + interaction),
                   finite_size_shift=finite, interaction_shift=interaction)
    else:
        out.update(tc_ideal=math.nan, tc_finite_size=math.nan, tc=math.nan, finite_size_shift=math.nan,
                   interaction_shift=math.nan)
    out["t_over_tc"] = temperature / out["tc"] if out["tc"] > 0 else math.nan
    fraction = condensed / atoms if atoms > 0 else math.nan
    out["fraction"] = fraction
    out["t_over_tc_ideal"] = (1 - fraction) ** (1 / 3) if 0 <= fraction <= 1 else math.nan
    if condensed > 0:
        mu = 0.5 * hbar * trap.mean * (15 * condensed * a / a_ho) ** 0.4
        out["chemical_potential"] = mu
        for index, omega in enumerate(trap.omegas):
            out[f"radius_{index}"] = math.sqrt(2 * mu / (mass * omega ** 2))
        out["peak_density"] = mu * mass / (4 * math.pi * hbar ** 2 * a)
        out["mu_over_kt"] = mu / (k_b * temperature) if temperature > 0 else math.nan
    else:
        out.update(chemical_potential=math.nan, radius_0=math.nan, radius_1=math.nan, radius_2=math.nan,
                   peak_density=math.nan, mu_over_kt=math.nan)
    # A saturated (z = 1) ideal thermal cloud holds N_th = ζ(3)(k_B T/ħω̄)³ atoms, whatever N0 is: the
    # counted thermal atoms over it is the QE's error factor (``implied_qe_thermal``), R-independent.
    saturated = ZETA3 * (k_b * temperature / (hbar * trap.mean)) ** 3 if temperature > 0 else math.nan
    out["saturated_thermal"] = saturated
    out["thermal_ratio"] = (atoms - condensed) / saturated if saturated > 0 and atoms > 0 else math.nan
    return out


@dataclass(frozen=True)
class RadiusCheck:
    """What a bimodal fit's TF radius says on its own: R at the detector and in the trap, the μ and
    N0 that R(0) implies (no QE needed), and the QE that makes the counted N0 match. The implied
    QE's SE treats the counted N0 and R as independent (they come from one fit, so roughly); N0 ∝
    R^5 makes it sensitive to R (10 % in R is 50 % in N0), and a saturated detector lowers it."""
    axis: Axis
    role: Role
    at_detector: Estimate  # m
    in_trap: Estimate  # m; nan for an axis between the trap's axes
    chemical_potential: Estimate  # J
    condensed: Estimate  # atoms
    implied_qe: Estimate  # counted N0 / N0 from R (nan without a counted N0)

    def as_record(self) -> dict[str, Any]:
        return {"axis": self.axis, "role": self.role, "at_detector": self.at_detector.as_record(),
                "in_trap": self.in_trap.as_record(), "chemical_potential": self.chemical_potential.as_record(),
                "condensed": self.condensed.as_record(), "implied_qe": self.implied_qe.as_record()}


@dataclass(frozen=True)
class BecProperties:
    """D14's numbers, each ± SE (nan where undefined or unknown), SI units: atoms, K, J, m, m⁻³.
    ``radii`` are the in-trap TF radii along the trap's axes (radial, radial, axial). ``notes`` say
    what to keep in mind (unconfirmed constants, saturation, regimes, edge cases)."""
    atoms: Estimate
    condensed: Estimate
    fraction: Estimate
    temperature: Estimate
    tc_ideal: Estimate
    tc_finite_size: Estimate
    tc: Estimate
    t_over_tc: Estimate
    t_over_tc_ideal: Estimate  # (1 − N0/N)^{1/3}: T/Tc0 for an ideal gas, from the fraction alone
    chemical_potential: Estimate
    mu_over_kt: Estimate
    radii: tuple[Estimate, Estimate, Estimate]
    peak_density: Estimate
    # ζ(3)(k_B T/ħω̄)³: the thermal atoms a saturated (z = 1) ideal cloud holds at T, and the QE
    # that makes the counted thermal atoms match it (with a condensate only; nan otherwise).
    saturated_thermal: Estimate
    implied_qe_thermal: Estimate
    mean_frequency: float  # ω̄, rad/s
    oscillator_length: float  # a_ho, m
    finite_size_shift: float  # δTc/Tc0
    interaction_shift: float
    notes: tuple[str, ...] = ()
    from_radius: RadiusCheck | None = None
    record: Mapping[str, Any] = field(default_factory=dict, repr=False)  # inputs: what from_fit was given

    def as_record(self) -> dict[str, Any]:
        """Strict JSON (nan as None)."""
        estimates = {name: getattr(self, name).as_record() for name in (
            "atoms", "condensed", "fraction", "temperature", "tc_ideal", "tc_finite_size", "tc", "t_over_tc",
            "t_over_tc_ideal", "chemical_potential", "mu_over_kt", "peak_density", "saturated_thermal",
            "implied_qe_thermal")}
        return {**estimates, "radii": [radius.as_record() for radius in self.radii],
                "mean_frequency": self.mean_frequency, "oscillator_length": self.oscillator_length,
                "finite_size_shift": _finite(self.finite_size_shift),
                "interaction_shift": _finite(self.interaction_shift), "notes": list(self.notes),
                "from_radius": None if self.from_radius is None else self.from_radius.as_record(),
                "inputs": dict(self.record)}


def _finite(value: float) -> float | None:
    return value if math.isfinite(value) else None


def constant_notes(constants: ResolvedConstants, counted: bool) -> list[str]:
    """Notes on the borrowed constants the properties use (``counted``: atoms came from counts / QE)."""
    notes: list[str] = []
    stale = [key for key in ("trap_radial", "trap_axial") if key in constants.unconfirmed]
    if stale:
        notes.append("trap frequencies unconfirmed (stale 2017 values): Tc, μ, the radii and n0 scale with them")
    if counted and "detector_qe" in constants.unconfirmed:
        notes.append(f"detector QE unconfirmed (proposed {constants.detector_qe:g}): N and N0 scale as 1/QE, "
                     "Tc as QE^−1/3, μ and n0 as QE^−2/5, the radii as QE^−1/5; its uncertainty isn't in the SEs")
    return notes


def bec_properties(atoms: float, condensed: float, temperature: float, constants: ResolvedConstants,
                   covariance: npt.ArrayLike | None = None, *, counted: bool = False) -> BecProperties:
    """The properties from N, N0 (atoms, e.g. per shot) and T (K), with SEs from ``covariance``
    (3 × 3, of (N, N0, T); None: no SEs). ``temperature`` nan leaves out T/Tc and μ/k_B T.
    ``counted``: the numbers came from counts / QE (adds the QE and saturation notes)."""
    point = np.array([atoms, condensed, temperature], dtype=np.float64)
    matrix = np.full((3, 3), math.nan) if covariance is None else np.asarray(covariance, dtype=np.float64)
    values = _quantities(atoms, condensed, temperature, constants)

    def estimate(name: str) -> Estimate:
        if not math.isfinite(values[name]):
            return Estimate(math.nan, math.nan)
        return propagate(lambda p: _quantities(float(p[0]), float(p[1]), float(p[2]), constants)[name], point,
                         matrix)
    notes = constant_notes(constants, counted)
    if not atoms > 0:
        notes.append("no atoms: N must be positive for Tc and the rest")
    if condensed > 0 and counted:
        notes.append("N0 is counted: a dense condensate can saturate the detector (dead time, local MCP gain "
                     "depletion) and be undercounted; compare the QE its TF radius implies")
    if not condensed > 0:
        notes.append("no condensate (N0 = 0): no μ, TF radii or peak density")
    elif atoms > 0 and condensed > atoms:
        notes.append("N0 above N: check the fit")
    if not math.isfinite(temperature):
        notes.append("no temperature: no T/Tc or μ/k_B T")
    trap = Trap.from_constants(constants)
    a_ho = trap.oscillator_length(constants)
    shift = values["finite_size_shift"] + values["interaction_shift"]
    if math.isfinite(shift) and abs(shift) > TC_SHIFT_NOTE:
        notes.append(f"Tc's shifts total {shift:+.0%} of Tc0: beyond the first-order expansions' range, Tc is rough")
    if condensed > 0 and condensed * constants.scattering_length / a_ho < TF_REGIME:
        notes.append(f"N0 a/a_ho = {condensed * constants.scattering_length / a_ho:.3g}: not deep in the "
                     "Thomas–Fermi regime (≫ 1), so μ, the radii and n0 are rough")
    if condensed > 0 and values["t_over_tc"] > 1:
        notes.append("a condensate above the computed Tc: check N (the QE) and the trap frequencies")
    implied_thermal = Estimate(math.nan, math.nan)
    if counted and condensed > 0 and math.isfinite(values["thermal_ratio"]):
        ratio = estimate("thermal_ratio")
        implied_thermal = Estimate(ratio.value * constants.detector_qe, ratio.se * constants.detector_qe)
        notes.append("QE from the thermal cloud: counted thermal atoms over ζ(3)(k_B T/ħω̄)³, the saturated "
                     "ideal gas's (interactions deplete it a little; T ∝ σ² and N_th ∝ T³ make it σ⁶-sensitive)")
    return BecProperties(
        atoms=Estimate(atoms, _se(matrix, 0)), condensed=Estimate(condensed, _se(matrix, 1)),
        fraction=estimate("fraction"), temperature=Estimate(temperature, _se(matrix, 2)),
        tc_ideal=estimate("tc_ideal"), tc_finite_size=estimate("tc_finite_size"), tc=estimate("tc"),
        t_over_tc=estimate("t_over_tc"), t_over_tc_ideal=estimate("t_over_tc_ideal"),
        chemical_potential=estimate("chemical_potential"), mu_over_kt=estimate("mu_over_kt"),
        radii=(estimate("radius_0"), estimate("radius_1"), estimate("radius_2")),
        peak_density=estimate("peak_density"), saturated_thermal=estimate("saturated_thermal"),
        implied_qe_thermal=implied_thermal, mean_frequency=trap.mean, oscillator_length=a_ho,
        finite_size_shift=values["finite_size_shift"], interaction_shift=values["interaction_shift"],
        notes=tuple(notes))


def _se(matrix: Array, index: int) -> float:
    variance = float(matrix[index, index])
    return math.sqrt(variance) if math.isfinite(variance) and variance >= 0 else math.nan


def _jacobian(function: Callable[[Array], Array], point: Array, covariance: Array) -> Array:
    """∂function/∂point by central differences, steps 10⁻³ SE (as ``estimates.propagate``)."""
    base = function(point.copy())
    jacobian = np.zeros((len(base), len(point)))
    for index in range(len(point)):
        spread = math.sqrt(max(float(covariance[index, index]), 0.0)) if math.isfinite(covariance[index, index]) \
            else 0.0
        step = 1e-3 * spread if spread > 0 else 1e-8 * max(abs(float(point[index])), 1.0)
        above, below = point.copy(), point.copy()
        above[index] += step
        below[index] -= step
        jacobian[:, index] = (function(above) - function(below)) / (2 * step)
    return jacobian


def from_fit(fit: FitResult, axis: Axis, constants: ResolvedConstants, bin_width: float, shots: int
             ) -> BecProperties:
    """The properties from one histogram fit (in s or m, raw counts per bin of ``bin_width`` over
    ``shots`` shots): N and N0 per shot from its components' areas / bin width / shots / QE (N0 = 0
    for a model without a condensate part), T from its (thermal) σ as ``profiles.fit_axis`` takes it
    (σ_v = g σ on T, σ / t_f on X and Y; T = m σ_v²/k_B), and their covariance from the fit's. With a
    TF radius, ``from_radius`` checks it against N0 (``RadiusCheck``). A failed fit gives nan with its
    failure as a note.

    A slice model (``FitModel.slice``: TF^{3/2}, g_2) holds only part of the cloud, so only T and
    R(0) are given; N, N0, N0/N, Tc, μ, n0 and the implied QEs are nan, with ``fits.SLICE_NOTE``."""
    areas = fit.model.areas
    record = {"model": fit.model.key, "axis": axis, "bin_width": bin_width, "shots": shots,
              "detector_qe": constants.detector_qe}
    if not fit.ok or areas is None or not (bin_width > 0 and shots > 0) or "sigma" not in fit.model.names:
        why = fit.failure or ("the model has no areas or σ" if areas is None or "sigma" not in fit.model.names
                              else "no bins or shots")
        empty = bec_properties(math.nan, math.nan, math.nan, constants)
        return _replace_notes(empty, (f"no BEC properties: {why}",), record)
    model_areas: Callable[[Array], dict[str, float]] = areas
    sigma_index = fit.model.names.index("sigma")
    per_atom = 1.0 / (bin_width * shots * constants.detector_qe)
    velocity = constants.g if axis == "T" else 1.0 / constants.fall_time

    def numbers(p: Array) -> Array:
        parts = model_areas(p)
        condensed = parts.get(CONDENSATE_AREA, 0.0)
        return np.array([sum(parts.values()) * per_atom, condensed * per_atom,
                         constants.mass * (velocity * float(p[sigma_index])) ** 2 / constants.k_B])
    covariance = fit.covariance if fit.covariance is not None else np.full((len(fit.values),) * 2, math.nan)
    point = numbers(fit.values)
    if np.all(np.isfinite(covariance)):
        jacobian = _jacobian(numbers, fit.values, covariance)
        combined: Array | None = jacobian @ covariance @ jacobian.T
    else:
        combined = None
    if fit.model.slice:
        temperature_only = None if combined is None else np.diag([math.nan, math.nan, float(combined[2, 2])])
        properties = bec_properties(math.nan, math.nan, float(point[2]), constants, temperature_only)
        notes = [*constant_notes(constants, False), SLICE_NOTE]
    else:
        properties = bec_properties(float(point[0]), float(point[1]), float(point[2]), constants, combined,
                                    counted=True)
        notes = list(properties.notes)
        notes.append("N and N0 per shot (the histogram's events over its shots), counting only the events in "
                     "its range and box")
    notes.append(f"T from {'the histogram of all shots' if shots > 1 else 'one shot'}"
                 + (": shot-to-shot jitter of the cloud's centre widens it, so T reads high (per-shot fits "
                    "avoid it)" if shots > 1 else ""))
    check = None
    condensate_part = fit.model.areas is not None and CONDENSATE_AREA in model_areas(fit.values)
    if "radius" in fit.estimates and condensate_part and math.isfinite(fit["radius"].value) and (
            fit.model.slice or point[1] > 0):
        check = radius_check(fit["radius"], axis, constants, Estimate(math.nan, math.nan) if fit.model.slice
                             else properties.condensed)
        if fit.model.slice:  # R(0) only: μ and N0 from it stay with the full projection, as the rest
            nan = Estimate(math.nan, math.nan)
            check = replace(check, chemical_potential=nan, condensed=nan)
        if check.role == "between":
            notes.append(f"R on {axis} lies between the trap's axes (Trap axial axis along): no R(0) from it")
    return _replace_notes(properties, tuple(notes), record, check)


def radius_check(radius: Estimate, axis: Axis, constants: ResolvedConstants, counted: Estimate) -> RadiusCheck:
    """``RadiusCheck`` for a TF radius fitted on ``axis`` (s or m) and the counted N0 (atoms)."""
    role = axis_roles(constants)[axis]
    at_detector = detector_length(radius, axis, constants)
    in_trap = release_radius(at_detector, role, constants)
    trap = Trap.from_constants(constants)
    omega = trap.omega(role)
    a_ho = trap.oscillator_length(constants)

    def mu(r: float) -> float:
        return 0.5 * constants.mass * omega ** 2 * r ** 2

    def condensed(r: float) -> float:
        scaled = max(2 * mu(r) / (constants.hbar * trap.mean), 0.0)
        return a_ho / (15 * constants.scattering_length) * math.pow(scaled, 2.5)
    variance = np.array([[in_trap.se ** 2]])
    chemical = propagate(lambda p: mu(float(p[0])), [in_trap.value], variance)
    from_r = propagate(lambda p: condensed(float(p[0])), [in_trap.value], variance)
    if math.isfinite(from_r.value) and from_r.value > 0 and math.isfinite(counted.value):
        implied = propagate(lambda p: float(p[0]) / condensed(float(p[1])) * constants.detector_qe,
                            [counted.value, in_trap.value], np.diag([counted.se ** 2, in_trap.se ** 2]))
    else:
        implied = Estimate(math.nan, math.nan)
    return RadiusCheck(axis, role, at_detector, in_trap, chemical, from_r, implied)


def _replace_notes(properties: BecProperties, notes: tuple[str, ...], record: Mapping[str, Any],
                   check: RadiusCheck | None = None) -> BecProperties:
    return replace(properties, notes=notes, record=dict(record), from_radius=check)
