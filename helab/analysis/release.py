"""The release time (D8): when the atoms left the trap, in DLD time (seconds after the DLD
trigger), from one cloud's arrival, or set by hand.

Detection (roadmaps/dld-front-panel-port.md, Decided: "Release-time detection"): one cloud
of atoms released at rest (a BEC, order 0) arrives a fall time t_f = √(2h/g) after its
release, so t_r = t_arrival − t_f. ``detect_release_time``:

1. finds the peaks of the T histogram of the events (summed over the chosen shots) with
   ``peaks.find_time_peaks``, and takes the tallest as the cloud;
2. fits a Gaussian + offset (``fits.fit_histogram``, Poisson likelihood) to the events within
   ``FIT_FWHMS`` full widths of it (and short of halfway to any other peak), for the centre ±
   SE; when that fit fails, the mean time of the events near the peak ± s/√n is used, noted;
3. subtracts the run's fall time (``ResolvedConstants.fall_time``).

The SE (``error`` "within run") is the fit's: the statistical error of the summed events'
centre, as if every event were independent. It leaves out the shot-to-shot jitter of the
release (and of the trap), which is usually larger: on 20 shots of 1000 events with 50 µs
jitter, the fit's SE was 2.1 µs and the shot bootstrap's 9.8 µs. The honest error over shots
is ``bootstrap_release_time`` (``error`` "shot bootstrap"), which reruns the detection on
resampled shots. Either way the fall time is taken as exact: its error is systematic, the
same for every shot, δt_r = −δt_f = −δh / (g t_f) (≈ −1.2 ms for the 5 mm between the
fall-distance candidates 0.848 and 0.8529 m).

Results say what to trust, never raise: ``failure`` (no events, too few, no peak, no fall
time) or ``notes`` on a result that worked (comparable peaks: "unsure"; the fit fell back to
a mean; the cloud's skew). Skew: an atom's arrival time is not linear in its v_z, τ ≈ t_f + u
+ u²/(2t_f) with u = v_z/g, so a cloud of T width σ_t has its mean σ_t²/(2t_f) late and its
mode about σ_t²/t_f early; a Gaussian's centre lies between. That is 0.1 µs for a BEC
(σ_t ≈ 0.3 ms), but ~30 µs for a 1 µK thermal cloud (σ_t ≈ 5 ms); noted when larger than
the SE.

Pure NumPy/SciPy, no Qt, no I/O.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Literal, Sequence

import numpy as np
import numpy.typing as npt

from helab.analysis.bootstrap import BootstrapResult, bootstrap_shots
from helab.analysis.estimates import Estimate, finite_or_none
from helab.analysis.fits import FitResult, bin_centres, fit_histogram
from helab.analysis.peaks import PROMINENCE_COUNTS, Peak, find_time_peaks
from helab.analysis.physics import ResolvedConstants

Source = Literal["detected", "manual"]
# What the SE covers: the fit of the summed events, or the spread over resampled shots.
ErrorKind = Literal["within run", "shot bootstrap", "none"]
RELEASE_N_BOOT = 200  # each resample is a detection; 200 is plenty for an SE (≈ 5 % its own error)
MIN_EVENTS = 50  # fewer events in the search range: too few to find a cloud
STANDS_OUT = 3.0  # the cloud's peak below this many times the histogram's median bin: "unsure"
COMPARABLE_SHARE = 0.5  # another peak at least this share of the tallest's height: "unsure"
FIT_FWHMS = 1.5  # the fit window's half-width, in the peak's full widths (≈ ±3.5 σ)
FIT_BINS_PER_FWHM = 8
MIN_FIT_BINS = 15


@dataclass(frozen=True)
class ReleaseTime:
    """A release time in DLD time (s) ± SE, with what it came from. ``failure`` is "" when
    it worked; otherwise ``value`` is nan and the failure says why."""
    value: Estimate
    source: Source
    fall_time: float  # the run's t_f (s)
    arrival: Estimate = Estimate(math.nan)  # the cloud's arrival (DLD time, s); nan for manual
    width: Estimate = Estimate(math.nan)  # the cloud's σ_t (s), from the fit
    failure: str = ""
    notes: tuple[str, ...] = ()
    events: int = 0  # events searched
    peaks: tuple[Peak, ...] = ()  # tallest first
    fit: FitResult | None = field(default=None, repr=False, compare=False)
    error: ErrorKind = "within run"  # what ``value.se`` covers (module docstring)
    within_run_se: float = math.nan  # the fit's SE, kept when ``error`` is "shot bootstrap"
    bootstrap: BootstrapResult | None = field(default=None, repr=False, compare=False)

    @property
    def ok(self) -> bool:
        return not self.failure

    @property
    def unsure(self) -> bool:
        """Another peak was comparable with the cloud's: the tallest may not be the one
        released at rest."""
        return any(note.startswith("unsure") for note in self.notes)

    def as_record(self) -> dict[str, Any]:
        """Strict JSON for a result's record."""
        return {"value": self.value.as_record(), "source": self.source, "fall_time": finite_or_none(self.fall_time),
                "arrival": self.arrival.as_record(), "width": self.width.as_record(), "failure": self.failure,
                "notes": list(self.notes), "events": self.events,
                "peaks": [{"position": peak.position, "height": peak.height, "fwhm": peak.fwhm,
                           "events": peak.events} for peak in self.peaks],
                "fit": self.fit.as_record() if self.fit is not None else None, "error": self.error,
                "within_run_se": finite_or_none(self.within_run_se),
                "bootstrap": self.bootstrap.as_record() if self.bootstrap is not None else None}


def manual_release_time(release_time: float, constants: ResolvedConstants) -> ReleaseTime:
    """A release time set by hand, passed through (its SE unknown); a non-finite one fails."""
    value = float(release_time)
    if not math.isfinite(value):
        return ReleaseTime(Estimate(math.nan), "manual", constants.fall_time,
                           failure="the release time set by hand isn't a number", error="none")
    return ReleaseTime(Estimate(value), "manual", constants.fall_time, error="none")


def detect_release_time(times: npt.ArrayLike, constants: ResolvedConstants, lower: float | None = None,
                        upper: float | None = None, min_events: int = MIN_EVENTS) -> ReleaseTime:
    """The release time from the arrival of one cloud released at rest: ``times`` are the
    events' DLD times (s), summed over the chosen shots; [lower, upper] limits the search
    (either end None: open). See the module docstring for the method and its notes."""
    t_f = constants.fall_time

    def failed(reason: str, events: int = 0, peaks: tuple[Peak, ...] = ()) -> ReleaseTime:
        return ReleaseTime(Estimate(math.nan), "detected", t_f, failure=reason, events=events, peaks=peaks)

    values = np.asarray(times, dtype=np.float64).ravel()
    values = values[np.isfinite(values)]
    if lower is not None:
        values = values[values >= lower]
    if upper is not None:
        values = values[values <= upper]
    if not (math.isfinite(t_f) and t_f > 0):
        return failed("no fall time: set the fall distance and g", len(values))
    if len(values) == 0:
        return failed("no events in the search range")
    if len(values) < min_events:
        return failed(f"too few events to find a cloud: {len(values):,} (needs {min_events:,})", len(values))
    search = find_time_peaks(values, lower, upper)
    if len(values) and float(values.min()) == float(values.max()):
        return failed(f"no peak found in T: all {len(values):,} times are equal", len(values))
    if not search.peaks:
        tallest = float(search.smoothed.max())
        if tallest < PROMINENCE_COUNTS:
            return failed(f"too few events to find a cloud: {len(values):,}, and the T histogram's tallest bin "
                          f"holds {tallest:.2g} (smoothed; a peak needs {PROMINENCE_COUNTS:g})", len(values))
        return failed("no peak found in T", len(values))
    cloud, others = search.peaks[0], search.peaks[1:]
    notes: list[str] = []
    comparable = [peak for peak in others if peak.height >= COMPARABLE_SHARE * cloud.height]
    if comparable:
        where = ", ".join(f"{peak.position:.6g} s" for peak in comparable)
        notes.append(f"unsure: {len(comparable)} other peak{'s' if len(comparable) > 1 else ''} at least "
                     f"{COMPARABLE_SHARE:.0%} as tall ({where}); the tallest, {cloud.position:.6g} s, is "
                     "taken as the cloud released at rest (narrow Search T to choose)")
    typical = float(np.median(search.smoothed))
    if typical > 0 and cloud.height < STANDS_OUT * typical:
        notes.append(f"unsure: the tallest peak is only {cloud.height / typical:.2g}× the T histogram's median "
                     "bin, so no cloud stands out: check that the search range holds one")
    arrival, width, fit = _arrival(values, cloud, others, notes)
    if not math.isfinite(arrival.value):
        reason = "; ".join(note for note in notes if note.startswith("unsure")) or "too few events near the peak"
        return failed(f"the cloud's arrival couldn't be found ({reason})", len(values), search.peaks)
    skew = width.value ** 2 / t_f if math.isfinite(width.value) else math.nan
    if math.isfinite(skew) and not skew <= arrival.se:
        notes.append(f"the cloud is wide (σ_t {width.value * 1e3:.3g} ms): its arrival is skewed, so the "
                     f"centre may be off by up to {skew * 1e6:.3g} µs")
    return ReleaseTime(Estimate(arrival.value - t_f, arrival.se), "detected", t_f, arrival, width, "",
                       tuple(notes), len(values), search.peaks, fit, within_run_se=arrival.se)


def bootstrap_release_time(shots: Sequence[npt.ArrayLike], constants: ResolvedConstants,
                           lower: float | None = None, upper: float | None = None, min_events: int = MIN_EVENTS,
                           n_boot: int = RELEASE_N_BOOT, seed: int | None = 0,
                           cancelled: Callable[[], bool] | None = None) -> ReleaseTime:
    """``detect_release_time`` on all the shots' times together, with its SE from the shot
    bootstrap (``bootstrap.bootstrap_shots``: the detection rerun on ``n_boot`` resamples of
    whole shots), so it includes the shot-to-shot jitter; ``error`` "shot bootstrap", the
    fit's own SE kept as ``within_run_se``. ``shots`` are per-shot arrays of DLD times. When
    the bootstrap has no error (fewer than 2 shots, or the detection failing on resamples),
    the within-run SE stays, noted. ``cancelled`` raises ``results.Cancelled``."""
    arrays = [np.asarray(shot, dtype=np.float64).ravel() for shot in shots]

    def detect(chosen: list[Any]) -> ReleaseTime:
        times = np.concatenate(chosen) if chosen else np.empty(0)
        return detect_release_time(times, constants, lower, upper, min_events)

    whole = detect(arrays)
    if not whole.ok:
        return whole
    result = bootstrap_shots(arrays, lambda chosen: detect(chosen).value.value, n_boot=n_boot, seed=seed,
                             cancelled=cancelled)
    notes = whole.notes + tuple(f"bootstrap: {note}" for note in result.notes)
    if not result.ok:
        return replace(whole, notes=notes + (f"no shot bootstrap error ({result.failure}): the SE is the fit's "
                                             "alone, without the shot-to-shot jitter",), bootstrap=result)
    return replace(whole, value=Estimate(whole.value.value, float(result.se)), notes=notes,
                   error="shot bootstrap", bootstrap=result)


def _arrival(values: npt.NDArray[np.float64], cloud: Peak, others: tuple[Peak, ...], notes: list[str]
             ) -> tuple[Estimate, Estimate, FitResult | None]:
    """(centre ± SE, σ_t ± SE, the fit) of the cloud's arrival: a Gaussian fit near the peak,
    else the mean of the events near it (noted)."""
    reach = FIT_FWHMS * cloud.fwhm
    nearest = min((abs(peak.position - cloud.position) for peak in others), default=math.inf)
    reach = min(reach, nearest / 2)
    low, high = cloud.position - reach, cloud.position + reach
    near = values[(values >= low) & (values <= high)]
    bins = max(MIN_FIT_BINS, math.ceil(2 * reach / cloud.fwhm * FIT_BINS_PER_FWHM)) if cloud.fwhm > 0 else MIN_FIT_BINS
    fit: FitResult | None = None
    reason = ""
    if high > low and len(near) >= 2:
        counts, edges = np.histogram(near, bins=bins, range=(low, high))
        fit = fit_histogram(bin_centres(edges), counts, "gaussian")
        centre, sigma = fit["centre"], fit["sigma"]
        if not fit.ok:
            reason = fit.failure
        elif not (low <= centre.value <= high and math.isfinite(centre.se) and centre.se > 0):
            reason = "its centre is outside the window or has no error"
        else:
            notes.extend(f"fit: {note}" for note in fit.notes)
            return centre, sigma, fit
    else:
        reason = "too few events near the peak"
    if len(near) < 2:
        return Estimate(math.nan), Estimate(math.nan), fit
    spread = float(np.std(near, ddof=1))
    notes.append(f"Gaussian fit failed ({reason}): the mean time of the {len(near):,} events within "
                 f"{reach * 1e3:.3g} ms of the peak is used instead")
    return Estimate(float(near.mean()), spread / math.sqrt(len(near))), Estimate(spread), fit
