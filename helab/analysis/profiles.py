"""T/X/Y profiles for the histogram plot (D1): display units, rates per shot, Gaussian
smoothing, and the fits with their temperatures.

roadmaps/dld-front-panel-port.md (Decided) sets the units and the rate method, after the
front panel's ``dld_plot_tof.m`` with its bug fixed:
- **Axes:** X and Y in mm; T in ms or s, chosen from its range (``display_unit``).
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
from types import MappingProxyType
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.sparse import csr_matrix

from helab.analysis.estimates import Estimate, propagate, si_prefix
from helab.analysis.fits import (MODELS, VARIANCE_FLOOR, FitModel, FitResult, arrival_time_model, bin_centres,
                                 fit_histogram)
from helab.analysis.physics import (TABLE, ResolvedConstants, sigma_v_from_arrival_width,
                                    sigma_v_from_transverse_width, temperature_estimate)

Array = npt.NDArray[np.float64]

# Units

COUNTS, RATE = "counts", "rate per shot"
# Bin widths, in the data's s and m, to the rate's ms and mm: T per ms is kHz.
RATE_UNITS = {"T": "kHz per shot", "X": "per mm per shot", "Y": "per mm per shot"}
RATE_SCALE = 1e3
# T below this span (s) is shown in ms, else in s.
T_SECONDS_FROM = 1.0


def display_unit(axis: str, low: float, high: float) -> tuple[float, str]:
    """(factor, unit) to show an axis's values (data in s and m): X and Y in mm, T in ms when
    its range spans under ``T_SECONDS_FROM`` (1 s), else in s."""
    if axis != "T":
        return 1e3, "mm"
    span = high - low
    return (1e3, "ms") if math.isfinite(span) and span < T_SECONDS_FROM else (1.0, "s")


def unit_of(axis: str) -> str:
    """The data's unit of an axis: s for T, m for X and Y (``Estimate.text`` adds the prefix)."""
    return "s" if axis == "T" else "m"


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


def si_text(value: float, unit: str) -> str:
    """``0.1 ms``, ``200 µm``: a value with an SI prefix, 3 significant digits."""
    exponent, prefix = si_prefix(value)
    return f"{value / 10 ** exponent:.3g} {prefix}{unit}"


def smoothing_bins(low: float, high: float, sigma: float, unit: str = "") -> tuple[int, str]:
    """The bin count giving bins of σ/5 over [low, high], at most ``SMOOTH_MAX_BINS``, and a
    note when that cap widened them (``unit``: the data's, for the note)."""
    if not (high > low and sigma > 0):
        return 1, ""
    wanted = math.ceil((high - low) / (sigma / SMOOTH_BIN_FACTOR))
    if wanted <= SMOOTH_MAX_BINS:
        return max(wanted, 1), ""
    return SMOOTH_MAX_BINS, (f"bins widened to {si_text((high - low) / SMOOTH_MAX_BINS, unit)} (σ/5 would "
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

GAUSSIAN, ARRIVAL, BIMODAL = "Gaussian", "Arrival-time thermal", "Bimodal TF² + Gaussian"
T_MODELS = (GAUSSIAN, ARRIVAL, BIMODAL)
XY_MODELS = (GAUSSIAN, BIMODAL)
MODEL_KEYS = {GAUSSIAN: "gaussian", ARRIVAL: "arrival_time", BIMODAL: "bimodal_tf2_gaussian"}
UNSMOOTHED, SMOOTHED = "unsmoothed counts", "smoothed curve (model smoothed too)"
CURVE_POINTS = 600  # the drawn fit's samples across the range


def model_for(choice: str, constants: ResolvedConstants) -> FitModel:
    """The fit model a choice names; the arrival-time profile with the run's fall distance and g."""
    if choice == ARRIVAL:
        return arrival_time_model(constants.fall_distance, constants.g)
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
        """``Gaussian: centre (416.12 ± 0.12) ms · σ (4.65 ± 0.05) ms · T (1.00 ± 0.02) µK``, or
        why there is no fit."""
        if not self.ok:
            return f"{self.choice} fit failed: {self.failure}"
        unit = unit_of(self.axis)
        width = "σ thermal" if self.choice == BIMODAL else ("σ_v/g" if self.choice == ARRIVAL else "σ")
        parts = [f"centre {self.centre.text(unit=unit)}", f"{width} {self.width.text(unit=unit)}",
                 f"T {self.temperature.text(unit='K')}"]
        if self.choice == BIMODAL and "radius" in self.fit.estimates:
            parts.insert(2, f"R {self.fit['radius'].text(unit=unit)}")
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
             smoothing: float | None = None) -> AxisFit:
    """Fit one histogram (``edges`` in s or m, raw ``counts``) with the model ``choice`` names.

    By default the raw counts, Poisson weighted (``fit_histogram``). ``smoothing`` (σ in the
    data's units) fits the smoothed curve instead, with the smoothing in the model
    (``fit_smoothed``): the parameters are the unsmoothed profile's, so the width (and a
    bimodal fit's R) needs no correction, and the SEs count the smoothed bins' correlation.
    Temperatures are the ideal-gas, pure-expansion ones (``physics``): along T σ_v = g σ, along
    X and Y σ_v = σ / t_f, each with the run's constants."""
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
            f"the smoothing (σ {si_text(smoothing, unit_of(axis))}) is too wide for this range to fit the "
            f"smoothed curve (at most {MAX_SMOOTHING_SHARE:g} of it): fit the unsmoothed counts"))
        nan = Estimate(math.nan, math.nan)
        return AxisFit(axis, choice, fit, nan, nan, nan, nan, np.empty(0), np.empty(0), (), True)
    curve = np.empty(0)
    if on_smoothed:
        assert smoothing is not None
        fit, curve = fit_smoothed(centres, raw, model, smoothing / width_bins)
        if fit.ok:
            notes.append("fitted to the smoothed curve with the smoothing in the model; SEs include the "
                         "smoothed bins' correlation")
    else:
        fit = fit_histogram(centres, raw, model)
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
SMOOTHED_ROUNDS = 8  # reweighting rounds of a smoothed-curve fit
SMOOTHED_SETTLED = 0.01  # stop once no parameter moves more than this many SEs


def smoothed_model(model: FitModel, smoothing: Smoothing) -> FitModel:
    """``model`` with the smoothing applied to its prediction on the bins: S·f(x, θ). Off that
    grid (another number of points, as ``FitResult.evaluate`` on a finer one) it is the
    unsmoothed model."""
    def function(x: Array, *values: float) -> Array:
        profile = model.function(x, *values)
        return smoothing.apply(profile) if len(x) == smoothing.bins else profile

    return replace(model, key=f"{model.key}+smoothing", title=f"{model.title} ⊗ smoothing", function=function)


def fit_smoothed(centres: Array, raw: Array, model: FitModel, sigma_bins: float) -> tuple[FitResult, Array]:
    """Fit the smoothed counts s = S n with the smoothed model S f(θ) (``smoothed_model``), and
    the smoothed fit's curve on the bins.

    - Weights: each smoothed bin's variance from the model, Σⱼ Sᵢⱼ² μⱼ with μ = f(θ) (floored as
      ``fits.VARIANCE_FLOOR`` per raw bin), refitted until θ settles. The first round uses the
      observed counts' (S² n); weights from observed counts alone would bias low-count fits.
    - SEs: the smoothed bins share raw counts, so their covariance is S diag(μ) Sᵀ, not
      diagonal. The covariance is the sandwich (JᵀWJ)⁻¹ JᵀW S diag(μ) Sᵀ WJ (JᵀWJ)⁻¹, with J the
      smoothed model's derivatives and W the weights: what the estimator's spread really is.
      Parameters a fit leaves without an SE (gated) keep none."""
    smoothing = Smoothing(len(raw), sigma_bins)
    forward = smoothed_model(model, smoothing)
    data = smoothing.apply(raw)
    floor = VARIANCE_FLOOR * smoothing.variance(np.ones_like(raw))
    variance = np.maximum(smoothing.variance(raw), floor)
    fit = fit_histogram(centres, data, forward, sigma=np.sqrt(variance))
    for _ in range(SMOOTHED_ROUNDS):
        if not fit.ok:
            break
        mean = np.clip(model.function(centres, *fit.values), 0, None)
        variance = np.maximum(smoothing.variance(mean), floor)
        refit = fit_histogram(centres, data, forward, sigma=np.sqrt(variance))
        if not refit.ok:
            break
        spread = np.array([fit[name].se for name in model.names])
        moved = np.abs(refit.values - fit.values) / np.where(np.isfinite(spread) & (spread > 0), spread, np.inf)
        fit = refit
        if float(np.max(moved)) <= SMOOTHED_SETTLED:
            break
    if not fit.ok:
        return fit, np.empty(0)
    values = fit.values
    mean = np.clip(model.function(centres, *values), 0, None)
    jacobian = np.empty((len(centres), len(values)))
    for index, value in enumerate(values):
        se = fit[model.names[index]].se
        step = 1e-3 * se if math.isfinite(se) and se > 0 else 1e-6 * max(abs(value), 1e-12)
        above, below = values.copy(), values.copy()
        above[index] += step
        below[index] -= step
        jacobian[:, index] = (forward.function(centres, *above) - forward.function(centres, *below)) / (2 * step)
    weighted = jacobian / variance[:, None]
    inverse = np.linalg.pinv(jacobian.T @ weighted)
    covariance = inverse @ (weighted.T @ smoothing.covariance_times(mean, weighted)) @ inverse
    estimates = {}
    for index, name in enumerate(model.names):
        variance_k = float(covariance[index, index])
        se = math.sqrt(variance_k) if math.isfinite(fit[name].se) and variance_k > 0 else math.nan
        estimates[name] = Estimate(float(values[index]), se)
    for extra in model.extras:
        derived = propagate(extra.function, values, covariance)
        estimates[extra.name] = Estimate(derived.value, derived.se if math.isfinite(fit[extra.name].se) else math.nan)
    honest = replace(fit, estimates=MappingProxyType(estimates), covariance=covariance)
    return honest, forward.function(centres, *values)


CONSTANT_NAMES = {"fall_distance": "fall distance", "fall_time": "fall time", "g": "g", "mass": "mass"}
ORIGIN_TEXT = {"default": "default", "lab": "lab", "folder": "folder", "plot": "this plot", "derived": "derived"}


def constants_text(constants: ResolvedConstants, keys: tuple[str, ...] = ("fall_distance", "fall_time", "g")) -> str:
    """``fall distance 0.848 m (default, unconfirmed) · fall time 0.416101 s (derived,
    unconfirmed) · g 9.79602 m/s² (default)``: each value used, where it came from, and the
    borrowed legacy values not yet confirmed on the current setup."""
    unconfirmed = set(constants.unconfirmed)
    parts = []
    for key in keys:
        flag = ", unconfirmed" if key in unconfirmed else ""
        parts.append(f"{CONSTANT_NAMES.get(key, key)} {constants.value(key):.6g} {TABLE[key].unit} "
                     f"({ORIGIN_TEXT[constants.origins[key]]}{flag})")
    return " · ".join(parts)
