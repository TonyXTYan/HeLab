"""T/X/Y profiles for the histogram plot (D1): display units, rates per shot, Gaussian
smoothing, and the fits with their temperatures.

roadmaps/dld-front-panel-port.md (Decided) sets the units and the rate method, after the
front panel's ``dld_plot_tof.m`` with its bug fixed:
- **Axes:** X and Y in mm, T in ms (``display_units``: Tony, 2026-10-20).
- **Rates:** counts / bin width / number of shots, after the view range (and, when chosen,
  the whole box) has picked the events: T in kHz per shot (per ms), X and Y per mm per shot
  (the front panel divided X and Y by the bin width only).
- **Smoothing** (optional): a Gaussian of σ over bins of σ/5 (the front panel's
  ``bin_factor``). Fits use the unsmoothed counts unless the smoothed curve is chosen.

Fits are in the data's own units (s, m) on counts per bin; drawing scales the fitted curve by
the same factor as the bars. No Qt and no I/O: runs in the analysis worker and in tests.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, cast

import numpy as np
import numpy.typing as npt
from scipy.sparse import csr_matrix

from helab.analysis.bec import Axis, axis_caps
from helab.analysis.display_units import WIDTH_DIGITS, axis_text, estimate_text
from helab.analysis.estimates import Estimate
from helab.analysis.fits import (FUGACITY, MAX_RADIUS_RATIO, MODELS, VARIANCE_FLOOR, FitModel, FitResult,
                                 arrival_time_model, bin_bounds, bin_centres, bin_means, condensate_fraction,
                                 fit_histogram)
from helab.analysis.physics import (ResolvedConstants, sigma_v_from_arrival_width, sigma_v_from_transverse_width,
                                    temperature_estimate)
from helab.analysis.velocity import effective_fall_distance

Array = npt.NDArray[np.float64]

# Units

COUNTS, RATE = "counts", "rate per shot"
# Bin widths, in the data's s and m, to the rate's ms and mm: T per ms is kHz.
RATE_UNITS = {"T": "kHz per shot", "X": "per mm per shot", "Y": "per mm per shot"}
RATE_SCALE = 1e3


def rate_factor(bin_width: float, shots: int) -> float:
    """What turns counts per bin into a rate per shot: 1 / (bin width in ms or mm × shots).
    nan without shots or a positive width."""
    if shots <= 0 or not bin_width > 0:
        return math.nan
    return 1.0 / (bin_width * RATE_SCALE * shots)


def value_label(axis: str, units: str, every: bool = False) -> str:
    """The y axis's title: ``Events`` (per bin) or ``Rate (kHz per shot)``; ``every`` (beside
    one highlighted shot's axis): ``Events (all)``, ``Rate, all (kHz per shot)``."""
    if units == RATE:
        return f"Rate{', all' if every else ''} ({RATE_UNITS[axis]})"
    return "Events (all)" if every else "Events"


# Smoothing

SMOOTH_BIN_FACTOR = 5  # bins of σ/5
SMOOTH_MAX_BINS = 5000  # more would be needed: the bins are widened to fit, and the plot says so
KERNEL_HALF_WIDTH = 4.0  # the kernel is cut at ±4 σ (and normalised)


def smoothing_bins(low: float, high: float, sigma: float, axis: str = "T") -> tuple[int, str]:
    """The bin count giving bins of σ/5 over [low, high], at most ``SMOOTH_MAX_BINS``, and a
    note when that cap widened them (``axis``: whose unit the note uses)."""
    if not (high > low and sigma > 0):
        return 1, ""
    wanted = math.ceil((high - low) / (sigma / SMOOTH_BIN_FACTOR))
    if wanted <= SMOOTH_MAX_BINS:
        return max(wanted, 1), ""
    return SMOOTH_MAX_BINS, (f"bins widened to {axis_text(axis, (high - low) / SMOOTH_MAX_BINS, WIDTH_DIGITS)} (σ/5 would "
                             f"need {wanted:,} bins; at most {SMOOTH_MAX_BINS:,})")


def gaussian_kernel(sigma_bins: float) -> Array:
    """A normalised Gaussian of ``sigma_bins`` bins, cut at ±4 σ (odd length, centred)."""
    half = max(int(math.ceil(KERNEL_HALF_WIDTH * sigma_bins)), 1)
    offsets = np.arange(-half, half + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (offsets / max(sigma_bins, 1e-12)) ** 2)
    return np.asarray(kernel / kernel.sum(), dtype=np.float64)


class Smoothing:
    """The smoothing of ``bins`` bins with a Gaussian of ``sigma_bins`` bins, as the linear map
    s = S n (a sparse matrix): each bin's counts spread by the kernel, the edges reflected (the
    bins beyond an edge mirror those inside, ``np.pad``'s "symmetric"), so what spreads past an
    edge folds back in and every column sums to 1: the total is kept. The same S smooths what
    is drawn and, in a fit of the smoothed curve, the model (``fit_axis``)."""

    def __init__(self, bins: int, sigma_bins: float) -> None:
        kernel = gaussian_kernel(sigma_bins)
        half = len(kernel) // 2
        source = np.pad(np.arange(bins), half, mode="symmetric")  # padded position → bin
        rows = np.repeat(np.arange(bins), len(kernel))
        columns = source[np.arange(bins)[:, None] + np.arange(len(kernel))[None, :]].ravel()
        weights = np.tile(kernel, bins)
        self.bins = bins
        self.matrix = csr_matrix((weights, (rows, columns)), shape=(bins, bins))  # duplicates summed
        self.squared = self.matrix.multiply(self.matrix).tocsr()

    def apply(self, values: npt.ArrayLike) -> Array:
        return np.asarray(self.matrix @ np.asarray(values, dtype=np.float64), dtype=np.float64)

    def variance(self, mean_counts: npt.ArrayLike) -> Array:
        """Each smoothed bin's variance when the raw bins are Poisson with these means: Σⱼ Sᵢⱼ² μⱼ."""
        return np.asarray(self.squared @ np.asarray(mean_counts, dtype=np.float64), dtype=np.float64)

    def covariance_times(self, mean_counts: Array, block: Array) -> Array:
        """S diag(μ) Sᵀ · block: the smoothed bins' covariance (they share raw counts) times a
        matrix, without forming the (bins × bins) covariance."""
        return np.asarray(self.matrix @ (mean_counts[:, None] * (self.matrix.T @ block)), dtype=np.float64)


def smooth(counts: npt.ArrayLike, sigma_bins: float) -> Array:
    """Counts smoothed with a Gaussian of ``sigma_bins`` bins; their sum is kept."""
    values = np.asarray(counts, dtype=np.float64)
    return Smoothing(len(values), sigma_bins).apply(values)


# Fits

GAUSSIAN, ARRIVAL = "Gaussian", "Arrival-time thermal"
# The bimodal fits' Thomas–Fermi exponent follows how the histogram integrates the condensate
# (fits.py, above ``thomas_fermi``): p = 2 for a full projection, p = 3/2 for a thin slice.
BIMODAL, BIMODAL_SLICE = "Bimodal TF² + Gaussian", "Bimodal TF^3/2 + Gaussian"
# D4: the Bose-enhanced thermal profile (fits.py, above ``bose_thermal``): g_5/2 for a full
# projection, g_2 for a thin slice, alone (fugacity fitted) or under a condensate (z = 1).
BOSE, BOSE_SLICE = "Bose g_5/2 thermal", "Bose g_2 thermal (slice)"
BIMODAL_BOSE, BIMODAL_BOSE_SLICE = "Bimodal TF² + Bose g_5/2", "Bimodal TF^3/2 + Bose g_2"
BIMODALS = (BIMODAL, BIMODAL_SLICE, BIMODAL_BOSE, BIMODAL_BOSE_SLICE)
BOSES = (BOSE, BOSE_SLICE)
T_MODELS = (GAUSSIAN, ARRIVAL, BOSE, BOSE_SLICE, BIMODAL, BIMODAL_SLICE, BIMODAL_BOSE, BIMODAL_BOSE_SLICE)
XY_MODELS = (GAUSSIAN, BOSE, BOSE_SLICE, BIMODAL, BIMODAL_SLICE, BIMODAL_BOSE, BIMODAL_BOSE_SLICE)
MODEL_KEYS = {GAUSSIAN: "gaussian", ARRIVAL: "arrival_time", BIMODAL: "bimodal_tf2_gaussian",
              BIMODAL_SLICE: "bimodal_tf1_5_gaussian", BOSE: "bose_g2_5", BOSE_SLICE: "bose_g2",
              BIMODAL_BOSE: "bimodal_tf2_g2_5", BIMODAL_BOSE_SLICE: "bimodal_tf1_5_g2"}
TF_EXPONENT_TIP = (
    "The bimodal fits' Thomas–Fermi exponent p follows how the histogram integrates the condensate, not "
    "the expansion: a Thomas–Fermi cloud keeps its inverted-parabola shape through time of flight (only "
    "its radii grow), and integrating (1 − r²) over k other axes gives (1 − u²)^(1 + k/2). "
    "p = 2: a full projection, the other two axes' ranges enclosing the condensate (any T, X or Y "
    "histogram of all events; a crop to about 0.7 R still fits p = 2). "
    "p = 3/2: a thin slice, one other axis windowed well inside R (an X histogram of a thin T window, or a "
    "cut through a 2D image): the column density integrated over one axis only. p = 1 (both other axes "
    "windowed) isn't offered. The wrong exponent biases R by about 8–9 % and the condensate fraction by "
    "1–2 points. Windowing the other axes windows the thermal cloud too, so a fraction from a cropped box "
    "isn't the whole cloud's. The Gaussian is the thermal part's Boltzmann limit (its Bose-enhanced form "
    "is g_5/2 for p = 2, g_2 for p = 3/2). "
    "Bose g_5/2 / g_2 thermal: an ideal Bose gas's profile, A g_ν(z e^(−u²/2)) / g_ν(z), its fugacity z "
    "fitted in [0, 1]; σ gives T as the Gaussian's does. Near Tc (z → 1) its centre is sharper than a "
    "Gaussian's, and a Gaussian fitted to it biases T low (by 5–10 % for z from 0.6 to 1); as a bimodal "
    "fit's thermal part a Gaussian overstates N0/N. Far above Tc (z → 0) the Bose profile is the Gaussian. "
    "Pair the order with the integration as the TF exponent: g_5/2 for a full projection, g_2 for a thin "
    "slice. z at 1 means a saturated cloud, at or below Tc: try a bimodal fit. "
    "Bimodal TF + Bose: the condensate on a saturated thermal cloud (z fixed at 1), TF² with g_5/2 and "
    "TF^3/2 with g_2; their N0/N comes from the parts' areas. "
    "R/σ_th is capped: after the fall it is about √(2μ/k_B T) along the trap's radial axes but only "
    "≈ (π/2)(ω_z/ω_⊥)√(2μ/k_B T) along its long axis, so the cap depends on the axis (which detector axis "
    "is the trap's long one: the Trap axial axis constant). A fit that ends at the cap says so: its T and "
    "N0/N are then bounds.")
UNSMOOTHED, SMOOTHED = "unsmoothed counts", "smoothed curve (model smoothed too)"
CURVE_POINTS = 600  # the drawn fit's samples across the range


def model_for(choice: str, constants: ResolvedConstants) -> FitModel:
    """The fit model a choice names; the arrival-time profile with the run's g and its effective
    fall distance (``velocity.effective_fall_distance``: h, or ½ g t_f² when the fall time was set
    by hand, so that a v = 0 atom arrives t_f after release, as D8's velocities have it)."""
    if choice == ARRIVAL:
        return arrival_time_model(effective_fall_distance(constants), constants.g)
    return MODELS[MODEL_KEYS.get(choice, "gaussian")]


@dataclass(frozen=True)
class AxisFit:
    """One axis's fit: the ``FitResult`` (in s or m, counts per bin), the centre and width
    (σ; a bimodal fit's thermal σ) with the velocity spread and temperature they give, and
    the curve to draw (``x``, ``y`` in counts per bin)."""
    axis: str
    choice: str
    fit: FitResult
    centre: Estimate
    width: Estimate
    sigma_v: Estimate
    temperature: Estimate
    x: Array
    y: Array
    notes: tuple[str, ...] = ()
    on_smoothed: bool = False

    def __post_init__(self) -> None:
        for array in (self.x, self.y):
            array.flags.writeable = False

    @property
    def ok(self) -> bool:
        return self.fit.ok

    @property
    def failure(self) -> str:
        return self.fit.failure

    def text(self) -> str:
        """``Gaussian: centre (20,416.12 ± 0.12) ms · σ (4.65 ± 0.05) ms · T (1.00 ± 0.02) µK``:
        positions and widths in ms (T) or mm (X, Y), grouped by thousands; or why there is no fit."""
        if not self.ok:
            return f"{self.choice} fit failed: {self.failure}"
        bimodal = self.choice in BIMODALS
        width = "σ thermal" if bimodal else ("σ_v/g" if self.choice == ARRIVAL else "σ")
        parts = [f"centre {estimate_text(self.axis, self.centre)}", f"{width} {estimate_text(self.axis, self.width)}",
                 f"T {self.temperature.text(unit='K')}"]
        if bimodal and "radius" in self.fit.estimates:
            parts.insert(2, f"R {estimate_text(self.axis, self.fit['radius'])}")
        if bimodal:
            parts.append(f"N0/N {condensate_fraction(self.fit).text()}")
        if FUGACITY in self.fit.estimates:
            parts.append(f"z {self.fit[FUGACITY].text()}")
        return f"{self.choice}{' ⊗ smoothing' if self.on_smoothed else ''}: " + " · ".join(parts)

    def as_record(self) -> dict[str, Any]:
        """Strict JSON: the fit's record and the numbers derived from it."""
        return {"axis": self.axis, "model": self.choice, "fit": self.fit.as_record(),
                "centre": self.centre.as_record(), "width": self.width.as_record(),
                "sigma_v": self.sigma_v.as_record(), "temperature": self.temperature.as_record(),
                "on_smoothed": self.on_smoothed, "notes": list(self.notes)}


def _scaled(estimate: Estimate, factor: float) -> Estimate:
    return Estimate(estimate.value * factor, abs(estimate.se * factor))


def fit_axis(axis: str, edges: npt.ArrayLike, counts: npt.ArrayLike, choice: str, constants: ResolvedConstants,
             smoothing: float | None = None, max_radius_ratio: float | None = MAX_RADIUS_RATIO) -> AxisFit:
    """Fit one histogram (``edges`` in s or m, raw ``counts``) with the model ``choice`` names.

    By default the raw counts, Poisson weighted (``fit_histogram``). ``smoothing`` (σ in the
    data's units) fits the smoothed curve instead, with the smoothing in the model
    (``fit_smoothed``): the parameters are the unsmoothed profile's, so the width (and a
    bimodal fit's R) needs no correction, and the SEs count the smoothed bins' correlation.
    Temperatures are the ideal-gas, pure-expansion ones (``physics``): along T σ_v = g σ, along
    X and Y σ_v = σ / t_f, each with the run's constants. ``max_radius_ratio``: the bimodal
    fits' cap on R/σ_thermal (``fit_histogram``); None takes this axis's physical cap at
    μ/k_B T ≤ 2 (``bec.axis_caps``: the trap frequencies, the fall time and which detector axis is
    the trap's long one), which a bimodal plot should pass (D4)."""
    if max_radius_ratio is None:
        max_radius_ratio = axis_caps(constants)[cast(Axis, axis)]
    edges = np.asarray(edges, dtype=np.float64)
    raw = np.asarray(counts, dtype=np.float64)
    centres = bin_centres(edges)
    model = model_for(choice, constants)
    notes: list[str] = []
    width_bins = float(np.mean(np.diff(edges))) if len(edges) > 1 else math.nan
    on_smoothed = smoothing is not None and width_bins > 0
    span = float(edges[-1] - edges[0]) if len(edges) > 1 else math.nan
    if on_smoothed and smoothing is not None and not smoothing <= span * MAX_SMOOTHING_SHARE:
        # Folded back many times at the edges, the smoothed curve keeps little of the profile's
        # shape, and the SEs stop being reliable (checked: right at a fifth of the range, 2× too
        # large at half of it).
        fit = replace(fit_histogram([], [], model), failure=(
            f"the smoothing (σ {axis_text(axis, smoothing, WIDTH_DIGITS)}) is too wide for this range to fit the "
            f"smoothed curve (at most {MAX_SMOOTHING_SHARE:g} of it): fit the unsmoothed counts"))
        nan = Estimate(math.nan, math.nan)
        return AxisFit(axis, choice, fit, nan, nan, nan, nan, np.empty(0), np.empty(0), (), True)
    curve = np.empty(0)
    if on_smoothed:
        assert smoothing is not None
        fit, curve = fit_smoothed(centres, raw, model, smoothing / width_bins, max_radius_ratio)
        if fit.ok:
            notes.append("fitted to the smoothed curve with the smoothing in the model; SEs include the "
                         "smoothed bins' correlation")
    else:
        fit = fit_histogram(centres, raw, model, max_radius_ratio=max_radius_ratio)
    nan = Estimate(math.nan, math.nan)
    if not fit.ok:
        return AxisFit(axis, choice, fit, nan, nan, nan, nan, np.empty(0), np.empty(0), (*fit.notes, *notes),
                       on_smoothed)
    centre, width = fit["centre"], fit["sigma"]
    if axis == "T":
        sigma_v = _scaled(width, sigma_v_from_arrival_width(1.0, constants))
    else:
        sigma_v = _scaled(width, sigma_v_from_transverse_width(1.0, constants))
    temperature = temperature_estimate(sigma_v, constants) if math.isfinite(sigma_v.value) else nan
    if on_smoothed:
        # The smoothed model, on the bins (it compares with the smoothed curve drawn).
        x, y = centres, curve
    else:
        x = np.linspace(float(edges[0]), float(edges[-1]), CURVE_POINTS)
        y = fit.evaluate(x)
    return AxisFit(axis, choice, fit, centre, width, sigma_v, temperature, x, y, (*fit.notes, *notes), on_smoothed)


MAX_SMOOTHING_SHARE = 0.2  # a smoothed-curve fit needs σ_s ≤ this share of the histogram's range
SMOOTHED_ROUNDS = 3  # model-weighted refits of a smoothed-curve fit after the first (cost: one fit each)
SMOOTHED_SETTLED = 0.05  # stop once no parameter moves more than this many SEs


def smoothed_model(model: FitModel, smoothing: Smoothing, centres: Array) -> FitModel:
    """``model`` with the smoothing applied to its prediction on the bins (``centres``), the
    model averaged over each bin (``fits.bin_means``): S·f̄(θ). Anywhere else (a finer grid,
    as ``FitResult.evaluate`` draws) it is the
    unsmoothed model: S belongs to those bins only."""
    step = float(np.min(np.diff(centres))) if len(centres) > 1 else 1.0
    lower, upper = bin_bounds(centres)

    def function(x: Array, *values: float) -> Array:
        on_bins = len(x) == smoothing.bins and bool(np.allclose(x, centres, rtol=0.0, atol=1e-6 * step))
        return smoothing.apply(bin_means(model.function, lower, upper, values)) if on_bins else \
            model.function(x, *values)

    return replace(model, key=f"{model.key}+smoothing", title=f"{model.title} ⊗ smoothing", function=function)


def fit_smoothed(centres: Array, raw: Array, model: FitModel, sigma_bins: float,
                 max_radius_ratio: float = MAX_RADIUS_RATIO) -> tuple[FitResult, Array]:
    """Fit the smoothed counts s = S n with the smoothed model S f(θ) (``smoothed_model``), and
    the smoothed fit's curve on the bins.

    - Weights: each smoothed bin's variance from the model, Σⱼ Sᵢⱼ² μⱼ with μ = f(θ) (floored as
      ``fits.VARIANCE_FLOOR`` per raw bin), refitted up to ``SMOOTHED_ROUNDS`` times until θ
      settles. The first fit uses the observed counts' (S² n); weights from observed counts
      alone would bias low-count fits.
    - SEs: the smoothed bins share raw counts, so their covariance is S diag(μ) Sᵀ, not
      diagonal. Each fit's covariance is the sandwich (JᵀWJ)⁻¹ JᵀW S diag(μ) Sᵀ WJ (JᵀWJ)⁻¹, with
      J the smoothed model's derivatives and W the weights: what the estimator's spread really
      is. It goes to ``fit_histogram`` (``covariance_of``), so the SEs, the "consistent with 0"
      gating and its notes, the undetermined check and the extras (a bimodal R) all use it."""
    smoothing = Smoothing(len(raw), sigma_bins)
    forward = smoothed_model(model, smoothing, centres)
    data = smoothing.apply(raw)
    floor = VARIANCE_FLOOR * smoothing.variance(np.ones_like(raw))
    lower, upper = bin_bounds(centres)

    def fit_with(variance: Array, start: Array | None = None) -> FitResult:
        def sandwich(x: Array, values: Array, fitted: Array) -> Array:
            if len(x) != len(centres):  # bins left out: S doesn't apply (fit_histogram noted them)
                return np.full_like(fitted, math.nan)
            mean = np.clip(bin_means(model.function, lower, upper, values), 0, None)
            jacobian = np.empty((len(centres), len(values)))
            for index, value in enumerate(values):
                spread = math.sqrt(fitted[index, index]) if fitted[index, index] > 0 else math.nan
                step = 1e-3 * spread if math.isfinite(spread) else 1e-6 * max(abs(float(value)), 1e-12)
                above, below = values.copy(), values.copy()
                above[index] += step
                below[index] -= step
                difference = forward.function(centres, *above) - forward.function(centres, *below)
                jacobian[:, index] = difference / (2 * step)
            weighted = jacobian / variance[:, None]
            inverse = np.linalg.pinv(jacobian.T @ weighted)
            return np.asarray(inverse @ (weighted.T @ smoothing.covariance_times(mean, weighted)) @ inverse,
                              dtype=np.float64)
        # A refit starts from the last fit only (not the model's several guesses: a bimodal
        # fit's four starts and its Gaussian seed fit would cost each round as much as the first).
        fitted = forward if start is None else replace(forward, guesses=lambda x, y, errors: [start])
        return fit_histogram(centres, data, fitted, sigma=np.sqrt(variance), covariance_of=sandwich,
                             max_radius_ratio=max_radius_ratio, nonnegative_offset=True,
                             binned=False)  # counts; the model bins itself

    fit = fit_with(np.maximum(smoothing.variance(raw), floor))
    for _ in range(SMOOTHED_ROUNDS):
        if not fit.ok:
            break
        mean = np.clip(bin_means(model.function, lower, upper, fit.values), 0, None)
        refit = fit_with(np.maximum(smoothing.variance(mean), floor), fit.values)
        if not refit.ok:
            break
        spread = np.array([fit[name].se for name in model.names])
        moved = np.abs(refit.values - fit.values) / np.where(np.isfinite(spread) & (spread > 0), spread, np.inf)
        fit = refit
        if float(np.max(moved)) <= SMOOTHED_SETTLED:
            break
    if not fit.ok:
        return fit, np.empty(0)
    return fit, forward.function(centres, *fit.values)
