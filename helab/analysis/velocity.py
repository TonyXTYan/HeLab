"""TXY events as velocities (D8): z up, as on Earth, with no XY rotation.

Frame (roadmaps/dld-front-panel-port.md, Decided: "Velocities: z up"): the trap is at
(x₀, y₀, 0), z points up, gravity is −g ẑ (g = |g| > 0), and the detector is the plane
z = −h, h the fall distance. An atom released at DLD time t_r with velocity (v_x, v_y, v_z)
is at

    z(τ) = v_z τ − ½ g τ²,   x(τ) = x₀ + v_x τ,   y(τ) = y₀ + v_y τ,   τ = t − t_r,

so arriving at DLD time t at (x, y) on the detector (z = −h) means, exactly:

    v_z = (½ g τ² − h) / τ = ½ g τ − h / τ,   v_x = (x − x₀) / τ,   v_y = (y − y₀) / τ.

Checks: released at rest, it arrives at τ = t_f = √(2h/g) and v_z = ½ g t_f − h/t_f = 0. An
atom thrown up (v_z > 0) arrives later than t_f, one thrown down earlier: v_z grows with τ
(dv_z/dτ = ½ g + h/τ² > 0), so v_z is a monotonic relabelling of the T axis. These are the
velocities at release, not at the detector. Near t_f, v_z ≈ g (τ − t_f) (physics.py's
σ_v = g σ_t). The legacy Core copies used both signs; this is the surviving top-level
``txy_to_vel.m`` one, −h/t_f + ½|g| t_f (review notes, D8).

X and Y are measured from (x₀, y₀), the point on the detector below the trap: the
``origin`` argument. By default it is (0, 0), so **the trap is assumed to be above X = Y = 0**
unless an origin is given; a trap off that point gives every atom a spurious v_x of x₀/τ
(back-to-back pairs then sum to about 2x₀/t_f, not 0). ``release.detect_release_time``
detects it from the rest cloud (its XY centre, ``ReleaseTime.origin``) and
``release.velocity_origin`` picks a hand-set origin over the detected one, else (0, 0). The
detector's own axes are used as they are (no rotation: Tony, 2026-10-20). An event with τ ≤ 0 (arriving before the
release) or a non-finite T, X or Y has no velocity: nan, counted in ``Velocities.invalid``.

h is the fall distance, unless the fall time was set by hand: then h = ½ g t_f²
(``effective_fall_distance``), so the cloud the release time came from is at rest.

Columns keep the TXY order: (v_z, v_x, v_y) beside (T, X, Y), so a plot's axis index means
the same thing in both. Pure NumPy, no Qt, no I/O; inputs are never written to.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Mapping

import numpy as np
import numpy.typing as npt

from helab.analysis.physics import TABLE, ResolvedConstants

Array = npt.NDArray[np.float64]
VELOCITY_AXES = ("v_z", "v_x", "v_y")  # beside stats.AXES = ("T", "X", "Y")
# Velocity units and how many single-photon recoils (ħk/m) each is: "ħk" is one photon's
# recoil, "2ħk" one Bragg order (counter-propagating beams). Named so a plot's axis says which.
VelocityUnit = Literal["m/s", "ħk", "2ħk"]
RECOILS_PER_UNIT: Mapping[str, int] = MappingProxyType({"ħk": 1, "2ħk": 2})
# He* 2³S₁ → 2³P₂ (the cooling and Bragg line), vacuum wavelength from its frequency,
# 276.732 186 5 THz (NIST ASD; Pastor et al. 2004): the table's lab-level row
# ``recoil_wavelength`` (unconfirmed until Tony says which beams set the recoil unit: a Bragg
# transfer of order n is 2nħk for counter-propagating beams). A run uses its constants' value.
RECOIL_WAVELENGTH = TABLE["recoil_wavelength"].value
RECOIL_WAVELENGTH_UNCONFIRMED = TABLE["recoil_wavelength"].unconfirmed


@dataclass(frozen=True)
class Velocities:
    """Per-event velocities at release, in m/s, columns (v_z, v_x, v_y), read-only (a copy of
    what it's given); nan for events with no velocity (``invalid`` of them: τ ≤ 0 or any
    non-finite T, X or Y). ``fall_distance`` is the h the conversion used
    (``effective_fall_distance``); ``origin`` the (x₀, y₀) X and Y were measured from."""
    values: Array = field(repr=False)
    invalid: int
    release_time: float
    fall_distance: float
    g: float
    fall_distance_from_time: bool = False  # h was ½ g t_f², from a fall time set by hand
    origin: tuple[float, float] = (0.0, 0.0)  # (x₀, y₀) (m): the point below the trap

    def __post_init__(self) -> None:
        frozen = np.array(self.values, dtype=np.float64, copy=True)
        frozen.flags.writeable = False
        object.__setattr__(self, "values", frozen)

    def __len__(self) -> int:
        return len(self.values)

    @property
    def valid(self) -> npt.NDArray[np.bool_]:
        return np.all(np.isfinite(self.values), axis=1)

    def in_recoils(self, recoil: float) -> Array:
        """The velocities in units of ``recoil`` (``recoil_velocity``), a new read-only array."""
        scaled = self.values / recoil if recoil > 0 else np.full(self.values.shape, math.nan)
        scaled.flags.writeable = False
        return scaled

    def in_unit(self, unit: VelocityUnit, constants: ResolvedConstants,
                wavelength: float | None = None) -> Array:
        """The velocities in ``unit`` (``unit_velocity``), a new read-only array."""
        return self.in_recoils(unit_velocity(unit, constants, wavelength))


def effective_fall_distance(constants: ResolvedConstants) -> float:
    """The fall distance the velocities use: h, or ½ g t_f² when the fall time was set by hand
    (``origins["fall_time"]`` isn't "derived"). Then the cloud whose arrival set the release
    time (``release.detect_release_time``: t_r = t_arrival − t_f) maps to v_z = 0 whatever h
    says; with h itself, a hand-set t_f 0.417 s beside h 0.848 m (√(2h/g) 0.4161 s) would give
    it +8.9 mm/s. ``ResolvedConstants.notes`` says when the two disagree."""
    if constants.origins.get("fall_time", "derived") == "derived":
        return constants.fall_distance
    return 0.5 * constants.g * constants.fall_time ** 2


def recoil_velocity(constants: ResolvedConstants, wavelength: float | None = None) -> float:
    """v_rec = ħk/m = h/(λ m): one photon's recoil at ``wavelength`` (default: the constants'
    ``recoil_wavelength``; ≈ 9.2 cm/s for He* at 1083 nm). nan unless the wavelength is finite
    and positive."""
    if wavelength is None:
        wavelength = constants.recoil_wavelength
    if not (math.isfinite(wavelength) and wavelength > 0):
        return math.nan
    return 2 * math.pi * constants.hbar / (wavelength * constants.mass)


def unit_velocity(unit: VelocityUnit, constants: ResolvedConstants, wavelength: float | None = None) -> float:
    """One ``unit`` in m/s: 1 for "m/s", ħk/m for "ħk", 2ħk/m for "2ħk"."""
    if unit == "m/s":
        return 1.0
    return RECOILS_PER_UNIT[unit] * recoil_velocity(constants, wavelength)


def vertical_velocity(times: npt.ArrayLike, release_time: float, constants: ResolvedConstants) -> Array:
    """v_z = ½ g τ − h/τ, τ = t − t_r, for DLD times ``times`` (any shape), h from
    ``effective_fall_distance``; nan where τ ≤ 0 or t isn't finite. A T axis in velocity:
    monotonic in t for t > t_r."""
    tau = np.asarray(times, dtype=np.float64) - release_time
    h = effective_fall_distance(constants)
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(tau > 0, 0.5 * constants.g * tau - h / tau, math.nan)
    return np.asarray(result, dtype=np.float64)


def arrival_time(vz: npt.ArrayLike, release_time: float, constants: ResolvedConstants) -> Array:
    """The inverse of ``vertical_velocity``: the DLD time at which an atom released at
    ``release_time`` with vertical velocity v_z reaches the detector, the positive root of
    ½ g τ² − v_z τ − h = 0: τ = (v_z + √(v_z² + 2gh)) / g, written 2h / (√(v_z² + 2gh) − v_z)
    for v_z < 0 so neither form subtracts nearly equal numbers. For a velocity window's T
    bounds; h from ``effective_fall_distance``."""
    v = np.asarray(vz, dtype=np.float64)
    g, h = constants.g, effective_fall_distance(constants)
    root = np.sqrt(v * v + 2 * g * h)
    with np.errstate(divide="ignore", invalid="ignore"):
        tau = np.where(v >= 0, (v + root) / g, 2 * h / (root - v))
    return np.asarray(release_time + tau, dtype=np.float64)


def txy_to_velocity(events: npt.ArrayLike, release_time: float, constants: ResolvedConstants,
                    origin: tuple[float, float] = (0.0, 0.0)) -> Velocities:
    """Each TXY event's velocity at release (see the module docstring for the frame and
    signs): ``events`` is (n, 3), columns T (s, DLD time), X, Y (m); ``release_time`` is in
    DLD time (``release.detect_release_time``, or set by hand); h from
    ``effective_fall_distance``. ``origin`` is (x₀, y₀) (m), the point below the trap that X
    and Y are measured from (``release.velocity_origin``); the default (0, 0) assumes the
    trap is above X = Y = 0. The input isn't modified (read-only arrays are fine)."""
    data = np.asarray(events, dtype=np.float64)
    if data.ndim != 2 or data.shape[1] < 3:
        raise ValueError("events must be an (n, 3) array of T, X, Y")
    x0, y0 = (float(axis) for axis in origin)
    if not (math.isfinite(x0) and math.isfinite(y0)):
        raise ValueError("the XY origin must be finite")
    tau = data[:, 0] - release_time
    h = effective_fall_distance(constants)
    good = np.isfinite(tau) & (tau > 0)
    values = np.full((len(data), 3), math.nan)
    if good.any():
        kept = tau[good]
        values[good, 0] = 0.5 * constants.g * kept - h / kept
        values[good, 1] = (data[good, 1] - x0) / kept
        values[good, 2] = (data[good, 2] - y0) / kept
    invalid = int((~np.all(np.isfinite(values), axis=1)).sum())
    return Velocities(values, invalid, float(release_time), h, constants.g,
                      constants.origins.get("fall_time", "derived") != "derived", (x0, y0))
