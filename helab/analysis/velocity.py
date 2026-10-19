"""TXY events as velocities (D8): z up, as on Earth, with no XY rotation.

Frame (roadmaps/dld-front-panel-port.md, Decided: "Velocities: z up"): the trap is at the
origin, z points up, gravity is −g ẑ (g = |g| > 0), and the detector is the plane z = −h,
h the fall distance. An atom released at DLD time t_r with velocity (v_x, v_y, v_z) is at

    z(τ) = v_z τ − ½ g τ²,   x(τ) = v_x τ,   y(τ) = v_y τ,   τ = t − t_r,

so arriving at DLD time t at (x, y) on the detector (z = −h) means, exactly:

    v_z = (½ g τ² − h) / τ = ½ g τ − h / τ,   v_x = x / τ,   v_y = y / τ.

Checks: released at rest, it arrives at τ = t_f = √(2h/g) and v_z = ½ g t_f − h/t_f = 0. An
atom thrown up (v_z > 0) arrives later than t_f, one thrown down earlier: v_z grows with τ
(dv_z/dτ = ½ g + h/τ² > 0), so v_z is a monotonic relabelling of the T axis. These are the
velocities at release, not at the detector. Near t_f, v_z ≈ g (τ − t_f) (physics.py's
σ_v = g σ_t). The legacy Core copies used both signs; this is the surviving top-level
``txy_to_vel.m`` one, −h/t_f + ½|g| t_f (review notes, D8).

X and Y are taken as measured from the point below the trap; the detector's own axes are
used as they are (no rotation: Tony, 2026-10-20). An event with τ ≤ 0 (arriving before the
release) or a non-finite time has no velocity: nan, counted in ``Velocities.invalid``.

Columns keep the TXY order: (v_z, v_x, v_y) beside (T, X, Y), so a plot's axis index means
the same thing in both. Pure NumPy, no Qt, no I/O; inputs are never written to.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt
import scipy.constants as codata

from helab.analysis.physics import ResolvedConstants

Array = npt.NDArray[np.float64]
VELOCITY_AXES = ("v_z", "v_x", "v_y")  # beside stats.AXES = ("T", "X", "Y")
VELOCITY_UNITS = ("m/s", "m/s", "m/s")
# He* 2³S₁ → 2³P₂ (the cooling and Bragg line), vacuum wavelength from its frequency,
# 276.732 186 5 THz (NIST ASD; Pastor et al. 2004). Not in physics.CONSTANTS yet: proposed
# for Tony as a lab-level row there, marked unconfirmed until he says which beams set the
# recoil unit (a Bragg transfer of order n is 2nħk for counter-propagating beams).
RECOIL_WAVELENGTH = codata.c / 276.7321865e12
RECOIL_WAVELENGTH_UNCONFIRMED = True


@dataclass(frozen=True)
class Velocities:
    """Per-event velocities at release, in m/s, columns (v_z, v_x, v_y), read-only; nan for
    events with no velocity (``invalid`` of them)."""
    values: Array = field(repr=False)
    invalid: int
    release_time: float
    fall_distance: float
    g: float

    def __post_init__(self) -> None:
        self.values.flags.writeable = False

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


def recoil_velocity(constants: ResolvedConstants, wavelength: float = RECOIL_WAVELENGTH) -> float:
    """v_rec = ħk/m = h/(λ m): one photon's recoil at ``wavelength`` (≈ 9.2 cm/s for He* at
    1083 nm). nan unless the wavelength is finite and positive."""
    if not (math.isfinite(wavelength) and wavelength > 0):
        return math.nan
    return 2 * math.pi * constants.hbar / (wavelength * constants.mass)


def vertical_velocity(times: npt.ArrayLike, release_time: float, constants: ResolvedConstants) -> Array:
    """v_z = ½ g τ − h/τ, τ = t − t_r, for DLD times ``times`` (any shape); nan where τ ≤ 0 or
    t isn't finite. A T axis in velocity: monotonic in t for t > t_r."""
    tau = np.asarray(times, dtype=np.float64) - release_time
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(tau > 0, 0.5 * constants.g * tau - constants.fall_distance / tau, math.nan)
    return np.asarray(result, dtype=np.float64)


def arrival_time(vz: npt.ArrayLike, release_time: float, constants: ResolvedConstants) -> Array:
    """The inverse of ``vertical_velocity``: the DLD time at which an atom released at
    ``release_time`` with vertical velocity v_z reaches the detector, the positive root of
    ½ g τ² − v_z τ − h = 0: τ = (v_z + √(v_z² + 2gh)) / g. For a velocity window's T bounds."""
    v = np.asarray(vz, dtype=np.float64)
    g, h = constants.g, constants.fall_distance
    tau = (v + np.sqrt(v * v + 2 * g * h)) / g
    return np.asarray(release_time + tau, dtype=np.float64)


def txy_to_velocity(events: npt.ArrayLike, release_time: float, constants: ResolvedConstants) -> Velocities:
    """Each TXY event's velocity at release (see the module docstring for the frame and
    signs): ``events`` is (n, 3), columns T (s, DLD time), X, Y (m); ``release_time`` is in
    DLD time (``release.detect_release_time``, or set by hand). The input isn't modified
    (read-only arrays are fine)."""
    data = np.asarray(events, dtype=np.float64)
    if data.ndim != 2 or data.shape[1] < 3:
        raise ValueError("events must be an (n, 3) array of T, X, Y")
    tau = data[:, 0] - release_time
    good = np.isfinite(tau) & (tau > 0)
    values = np.full((len(data), 3), math.nan)
    if good.any():
        kept = tau[good]
        values[good, 0] = 0.5 * constants.g * kept - constants.fall_distance / kept
        values[good, 1] = data[good, 1] / kept
        values[good, 2] = data[good, 2] / kept
    return Velocities(values, int((~good).sum()), float(release_time), constants.fall_distance, constants.g)
