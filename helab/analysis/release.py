"""The release time (D8): when the atoms left the trap, in DLD time (seconds after the DLD
trigger), from one cloud's arrival, or set by hand; and where the trap is on the detector.

Detection (roadmaps/dld-front-panel-port.md, Decided: "Release-time detection"): one cloud
of atoms released at rest (a BEC, order 0) arrives a fall time t_f = √(2h/g) after its
release, so t_r = t_arrival − t_f. ``detect_release_time``:

1. finds the peaks of the T histogram of the events (summed over the chosen shots) with
   ``peaks.find_time_peaks``, and takes the tallest as the cloud;
2. fits the arrival-time profile + offset (``fits.arrival_time_model`` with the run's h and
   g, h from ``velocity.effective_fall_distance``; Poisson likelihood) to the events within
   ``FIT_FWHMS`` full widths of it (and short of halfway to any other peak). Its centre is
   the arrival of v = 0 by construction, so a wide cloud's skew (below) doesn't move it.
   When that fit fails, a Gaussian + offset is fitted instead (noted, with the skew note
   when the cloud is wide); when that fails too, the mean time of the events near the peak
   ± s/√n is used, noted;
3. subtracts the run's fall time (``ResolvedConstants.fall_time``).

The SE (``error`` "within run") is the fit's: the statistical error of the summed events'
centre, within run (events independent). It leaves out the shot-to-shot jitter of the
release (and of the trap), which is usually larger: on 20 shots of 1000 events with 50 µs
jitter, the fit's SE was 2.1 µs and the shot bootstrap's 9.8 µs. The honest error over shots
is ``bootstrap_release_time`` (``error`` "shot bootstrap"), which reruns the detection on
resampled shots. Either way the fall time is taken as exact: its error is systematic, the
same for every shot, δt_r = −δt_f = −δh / (g t_f) (≈ −1.2 ms for the 5 mm between the
fall-distance candidates 0.848 and 0.8529 m).

The XY origin: given the events' X and Y (``positions``, or TXY shots for the bootstrap),
the same cloud, at rest, also marks the point below the trap: the mean X and Y of its events
within ``ORIGIN_SIGMAS`` σ_t of its arrival and within an XY window about their median
(``ORIGIN_WINDOW`` robust σ, found twice), ± s/√n (within run), recorded as ``origin`` with
the background's estimated share (noted above 5 %; nan, noted, when it can't be measured:
a clean cloud, or a frame around the window reaching past the slice's events). The window keeps a uniform background and
a horizontal Bragg order in the same T slice out; one inside the window (a cloud less than
~3σ away, or a background as dense as the cloud) still pulls the mean towards itself.
``velocity_origin`` picks what ``velocity.txy_to_velocity`` uses: an origin set by hand,
else the detected one, else (0, 0), the trap assumed above X = Y = 0.

Results say what to trust, never raise: ``failure`` (no events, too few, no peak, no fall
time) or ``notes`` on a result that worked (comparable peaks: "unsure"; the fit fell back to
a Gaussian or a mean; the cloud's skew then). Skew: an atom's arrival time is not linear in
its v_z, τ ≈ t_f + u + u²/(2t_f) with u = v_z/g, so a cloud of T width σ_t has its mean
σ_t²/(2t_f) late and its mode about σ_t²/t_f early; a Gaussian's centre lies between. That
is 0.1 µs for a BEC (σ_t ≈ 0.3 ms), but ~30 µs for a 1.5 µK thermal cloud (σ_t ≈ 5.7 ms:
+33 µs measured with the Gaussian, SE 13 µs); the arrival-time fit has no such bias, and the
fallbacks note it when larger than the SE.

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
from helab.analysis.fits import FitModel, FitResult, arrival_time_model, bin_centres, fit_histogram
from helab.analysis.peaks import PROMINENCE_COUNTS, Peak, find_time_peaks
from helab.analysis.physics import ResolvedConstants
from helab.analysis.velocity import effective_fall_distance

Source = Literal["detected", "manual"]
# What the SE covers: the fit of the summed events, within run (events independent, no shot
# jitter), or the spread over resampled shots (bootstrap_release_time).
ErrorKind = Literal["within run", "shot bootstrap", "none"]
OriginSource = Literal["manual", "detected", "detected (unsure)", "assumed"]
RELEASE_N_BOOT = 200  # each resample is a detection; 200 is plenty for an SE (≈ 5 % its own error)
MIN_EVENTS = 50  # fewer events in the search range: too few to find a cloud
STANDS_OUT = 3.0  # the cloud's peak below this many times the histogram's median bin: "unsure"
COMPARABLE_SHARE = 0.5  # another peak at least this share of the tallest's height: "unsure"
FIT_FWHMS = 1.5  # the fit window's half-width, in the peak's full widths (≈ ±3.5 σ)
FIT_BINS_PER_FWHM = 8
MIN_FIT_BINS = 15
ORIGIN_SIGMAS = 2.0  # the XY origin: events within this many σ_t of the cloud's arrival
ORIGIN_WINDOW = 3.0  # … and within this many robust σ (1.4826 MAD) of their median in X and Y
ORIGIN_BACKGROUND_NOTE = 0.05  # a background share of the origin's events above this: noted
ORIGIN_MOST = 0.5  # the window covering more than this share of the slice's XY extent: share unknown
NO_ORIGIN = (Estimate(math.nan), Estimate(math.nan))
XYWindow = tuple[tuple[float, float], tuple[float, float]]  # ((X low, X high), (Y low, Y high))


@dataclass(frozen=True)
class ReleaseTime:
    """A release time in DLD time (s) ± SE, with what it came from. ``failure`` is "" when
    it worked; otherwise ``value`` is nan and the failure says why. ``origin`` is the rest
    cloud's (X, Y) centre (m) ± SE, the point below the trap, when positions were given (nan
    otherwise); its SE covers what ``error`` says, like ``value``'s."""
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
    error: ErrorKind = "within run"  # what ``value.se`` covers: "within run" leaves out shot jitter
    within_run_se: float = math.nan  # the fit's SE, kept when ``error`` is "shot bootstrap"
    bootstrap: BootstrapResult | None = field(default=None, repr=False, compare=False)
    origin: tuple[Estimate, Estimate] = NO_ORIGIN  # the rest cloud's (X, Y) centre (m)
    origin_events: int = 0  # events the origin came from
    origin_background: float = math.nan  # the background's estimated share of them
    # What a plot draws: the fit's T window, the origin's T slice (arrival ± this half-width) and
    # its XY window ((X low, X high), (Y low, Y high)), all nan when not found.
    fit_window: tuple[float, float] = (math.nan, math.nan)
    origin_half: float = math.nan
    origin_window: XYWindow = ((math.nan, math.nan), (math.nan, math.nan))

    @property
    def ok(self) -> bool:
        return not self.failure

    @property
    def unsure(self) -> bool:
        """Another peak was comparable with the cloud's: the tallest may not be the one
        released at rest."""
        return any(note.startswith("unsure") for note in self.notes)

    @property
    def origin_found(self) -> bool:
        return all(math.isfinite(axis.value) for axis in self.origin)

    def as_record(self) -> dict[str, Any]:
        """Strict JSON for a result's record."""
        return {"value": self.value.as_record(), "source": self.source, "fall_time": finite_or_none(self.fall_time),
                "arrival": self.arrival.as_record(), "width": self.width.as_record(), "failure": self.failure,
                "notes": list(self.notes), "events": self.events,
                "peaks": [{"position": peak.position, "height": peak.height, "fwhm": peak.fwhm,
                           "events": peak.events} for peak in self.peaks],
                "fit": self.fit.as_record() if self.fit is not None else None, "error": self.error,
                "within_run_se": finite_or_none(self.within_run_se),
                "bootstrap": self.bootstrap.as_record() if self.bootstrap is not None else None,
                "origin": {"x": self.origin[0].as_record(), "y": self.origin[1].as_record(),
                           "events": self.origin_events, "background": finite_or_none(self.origin_background),
                           "half": finite_or_none(self.origin_half),
                           "window": [[finite_or_none(end) for end in axis] for axis in self.origin_window]},
                "fit_window": [finite_or_none(end) for end in self.fit_window]}


def manual_release_time(release_time: float, constants: ResolvedConstants) -> ReleaseTime:
    """A release time set by hand, passed through (its SE unknown); a non-finite one fails."""
    value = float(release_time)
    if not math.isfinite(value):
        return ReleaseTime(Estimate(math.nan), "manual", constants.fall_time,
                           failure="the release time set by hand isn't a number", error="none")
    return ReleaseTime(Estimate(value), "manual", constants.fall_time, error="none")


def layer_release_time(constants: ResolvedConstants) -> ReleaseTime | None:
    """The release time the layers give, as a manual ``ReleaseTime`` (its SE unknown); None when
    none does (both "detected"): the run detects it then (``bootstrap_release_time``).

    A t_r set by hand (``release_time``) is used as it is. A saved arrival of the cloud at rest
    (``arrival_time``, what the Release time plot's "Use for this folder" saves) gives
    t_r = t_a − t_f with *these* constants' fall time, so a plot with its own h, g or t_f still
    puts that cloud at v_z = 0 (``arrival`` holds t_a, and a note says so). When both are set, the
    more specific layer wins (plot, then folder, then lab), and t_r by hand on a tie."""
    rank = {"lab": 1, "folder": 2, "plot": 3}
    by_hand, saved = constants.is_set("release_time"), constants.is_set("arrival_time")
    if saved and (not by_hand or rank.get(constants.origins["arrival_time"], 0)
                  > rank.get(constants.origins["release_time"], 0)):
        arrival = constants.arrival_time
        found = manual_release_time(arrival - constants.fall_time, constants)
        if not found.ok:
            return found
        return replace(found, arrival=Estimate(arrival),
                       notes=(f"t_r from the saved arrival ({constants.origins['arrival_time']}) − this run's t_f",))
    if not by_hand:
        return None
    return manual_release_time(constants.release_time, constants)


def layer_origin(constants: ResolvedConstants) -> tuple[float, float] | None:
    """The trap's XY origin the layers set (``trap_x``, ``trap_y``), for ``velocity_origin``'s
    ``manual``; None unless both are set (one alone isn't an origin)."""
    if not (constants.is_set("trap_x") and constants.is_set("trap_y")):
        return None
    return constants.trap_x, constants.trap_y


@dataclass(frozen=True)
class RunVelocitySource:
    """What a plot's run converts TXY to velocities with (``run_velocity_source``): ``release``
    (t_r; check ``release.ok``), where it came from (``release_source``: the layer, "lab",
    "folder" or "plot", or "detected"; ``release_from``: "release_time" by hand,
    "arrival_time" a saved t_a − this run's t_f, or "data"), the run's ``detection`` (None
    when the layers set both t_r and the origin), and the XY ``origin`` with ``origin_how``
    and, for "manual", the layer that set it (``origin_source``)."""
    release: ReleaseTime
    release_source: str
    release_from: str
    detection: ReleaseTime | None
    origin: tuple[float, float]
    origin_how: OriginSource
    origin_source: str = ""

    @property
    def detected(self) -> bool:
        return self.release_source == "detected"


def run_velocity_source(constants: ResolvedConstants, detect: Callable[[], ReleaseTime]) -> RunVelocitySource:
    """t_r and the XY origin for one run, the one rule every velocity plot follows: t_r from the
    layers (``layer_release_time``), else ``detect()``'s; the origin from the layers
    (``layer_origin``), else the same detection's, else assumed (0, 0) (``velocity_origin``).
    ``detect`` (the plot's own detection of its chosen events, which may reuse one it kept) is
    called once, only when the layers leave t_r or the origin unset. Never another plot's t_r:
    a saved arrival gives t_r with *this* run's t_f."""
    given = layer_release_time(constants)
    manual_origin = layer_origin(constants)
    detection = detect() if given is None or manual_origin is None else None
    if given is not None:
        how = "arrival_time" if math.isfinite(given.arrival.value) else "release_time"
        release, source = given, constants.origins[how]
    else:
        assert detection is not None
        release, source, how = detection, "detected", "data"
    origin, origin_how = velocity_origin(detection, manual_origin)
    return RunVelocitySource(release, source, how, detection, origin, origin_how,
                             constants.origins["trap_x"] if origin_how == "manual" else "")


def velocity_origin(release: ReleaseTime | None, manual: tuple[float, float] | None = None
                    ) -> tuple[tuple[float, float], OriginSource]:
    """The XY origin for ``velocity.txy_to_velocity`` and where it came from: ``manual`` when
    set (finite), else the release's detected ``origin`` ("detected (unsure)" when the release
    is ``unsure``: another cloud may be the one at rest), else (0, 0), "assumed": the trap
    taken to be above X = Y = 0 on the detector (say so beside the velocities)."""
    if manual is not None and all(math.isfinite(float(axis)) for axis in manual):
        return (float(manual[0]), float(manual[1])), "manual"
    if release is not None and release.ok and release.origin_found:
        return ((release.origin[0].value, release.origin[1].value),
                "detected (unsure)" if release.unsure else "detected")
    return (0.0, 0.0), "assumed"


def detect_release_time(times: npt.ArrayLike, constants: ResolvedConstants, lower: float | None = None,
                        upper: float | None = None, min_events: int = MIN_EVENTS,
                        positions: npt.ArrayLike | None = None) -> ReleaseTime:
    """The release time from the arrival of one cloud released at rest: ``times`` are the
    events' DLD times (s), summed over the chosen shots; [lower, upper] limits the search
    (either end None: open). ``positions``, when given, are the same events' (X, Y), shape
    (n, 2), for the XY ``origin``. See the module docstring for the method and its notes; the
    SE is within run (events independent): ``bootstrap_release_time`` gives the one over
    shots."""
    t_f = constants.fall_time

    def failed(reason: str, events: int = 0, peaks: tuple[Peak, ...] = ()) -> ReleaseTime:
        return ReleaseTime(Estimate(math.nan), "detected", t_f, failure=reason, events=events, peaks=peaks)

    values = np.asarray(times, dtype=np.float64).ravel()
    xy: npt.NDArray[np.float64] | None = None
    if positions is not None:
        xy = np.asarray(positions, dtype=np.float64).reshape(-1, 2)
        if len(xy) != len(values):
            raise ValueError("positions must be (n, 2), one row per time")
    kept = np.isfinite(values)
    if lower is not None:
        kept &= values >= lower
    if upper is not None:
        kept &= values <= upper
    values = values[kept]
    if xy is not None:
        xy = xy[kept]
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
    arrival, width, fit, reach = _arrival(values, cloud, others, constants, notes)
    if not math.isfinite(arrival.value):
        reason = "; ".join(note for note in notes if note.startswith("unsure")) or "too few events near the peak"
        return failed(f"the cloud's arrival couldn't be found ({reason})", len(values), search.peaks)
    skew = width.value ** 2 / t_f if math.isfinite(width.value) else math.nan
    exact = fit is not None and fit.ok and fit.model.key == "arrival_time"
    if not exact and math.isfinite(skew) and not skew <= arrival.se:
        notes.append(f"the cloud is wide (σ_t {width.value * 1e3:.3g} ms): its arrival is skewed, so the "
                     f"centre may be off by up to {skew * 1e6:.3g} µs")
    origin, origin_events, background = NO_ORIGIN, 0, math.nan
    half, window = math.nan, ((math.nan, math.nan), (math.nan, math.nan))
    if xy is not None:
        origin, origin_events, background, half, window = _origin_drawn(values, xy, arrival.value, width.value,
                                                                        reach, notes)
    return ReleaseTime(Estimate(arrival.value - t_f, arrival.se), "detected", t_f, arrival, width, "",
                       tuple(notes), len(values), search.peaks, fit, within_run_se=arrival.se, origin=origin,
                       origin_events=origin_events, origin_background=background,
                       fit_window=(cloud.position - reach, cloud.position + reach), origin_half=half,
                       origin_window=window)


def _split(shot: npt.ArrayLike) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64] | None]:
    """A shot's times, and its (X, Y) when it is (n, ≥ 3) TXY events."""
    array = np.asarray(shot, dtype=np.float64)
    if array.ndim == 2 and array.shape[1] >= 3:
        return array[:, 0], array[:, 1:3]
    return array.ravel(), None


def bootstrap_release_time(shots: Sequence[npt.ArrayLike], constants: ResolvedConstants,
                           lower: float | None = None, upper: float | None = None, min_events: int = MIN_EVENTS,
                           n_boot: int = RELEASE_N_BOOT, seed: int | None = 0,
                           cancelled: Callable[[], bool] | None = None) -> ReleaseTime:
    """``detect_release_time`` on all the shots' events together, with its SE from the shot
    bootstrap (``bootstrap.bootstrap_shots``: the detection rerun on ``n_boot`` resamples of
    whole shots), so it includes the shot-to-shot jitter; ``error`` "shot bootstrap", the
    fit's own (within-run) SE kept as ``within_run_se``. ``shots`` are per-shot arrays of DLD
    times, or of TXY events (n, 3): then the XY ``origin`` is detected too, with its SE from
    the same bootstrap. When the bootstrap has no error (fewer than 2 shots, or the
    detection failing on resamples), the within-run SE stays, noted. ``cancelled`` raises
    ``results.Cancelled``."""
    split = [_split(shot) for shot in shots]
    with_xy = bool(split) and all(xy is not None for _, xy in split)
    pieces: list[tuple[npt.NDArray[np.float64], npt.NDArray[np.float64] | None]] = [
        (times, xy if with_xy else None) for times, xy in split]

    def detect(chosen: list[Any]) -> ReleaseTime:
        times = np.concatenate([t for t, _ in chosen]) if chosen else np.empty(0)
        xy = np.concatenate([p for _, p in chosen]) if with_xy and chosen else None
        return detect_release_time(times, constants, lower, upper, min_events, positions=xy)

    def statistic(chosen: list[Any]) -> npt.NDArray[np.float64]:
        found = detect(chosen)
        return np.array([found.value.value, found.origin[0].value, found.origin[1].value] if with_xy
                        else [found.value.value])

    whole = detect(list(pieces))
    if not whole.ok:
        return whole
    result = bootstrap_shots(pieces, statistic, n_boot=n_boot, seed=seed, cancelled=cancelled)
    notes = whole.notes + tuple(f"bootstrap: {note}" for note in result.notes
                                if not note.startswith("no error for element"))
    if result.failures[0]:
        return replace(whole, notes=notes + (f"no shot bootstrap error ({result.failures[0]}): the SE is the fit's "
                                             "alone, within run, without the shot-to-shot jitter",),
                       bootstrap=result)
    origin = whole.origin
    if with_xy and whole.origin_found:
        if all(not text for text in result.failures[1:]):
            origin = (Estimate(whole.origin[0].value, float(result.se[1])),
                      Estimate(whole.origin[1].value, float(result.se[2])))
        else:
            origin = (Estimate(whole.origin[0].value), Estimate(whole.origin[1].value))
            notes += ("no shot bootstrap error for the XY origin: its SE is unknown",)
    return replace(whole, value=Estimate(whole.value.value, float(result.se[0])), notes=notes,
                   error="shot bootstrap", bootstrap=result, origin=origin)


def _arrival(values: npt.NDArray[np.float64], cloud: Peak, others: tuple[Peak, ...], constants: ResolvedConstants,
             notes: list[str]) -> tuple[Estimate, Estimate, FitResult | None, float]:
    """(centre ± SE, σ_t ± SE, the fit, the window's half-width) of the cloud's arrival: the
    arrival-time profile fitted near the peak, else a Gaussian, else the mean of the events
    near it (each fallback noted)."""
    reach = FIT_FWHMS * cloud.fwhm
    nearest = min((abs(peak.position - cloud.position) for peak in others), default=math.inf)
    reach = min(reach, nearest / 2)
    low, high = cloud.position - reach, cloud.position + reach
    near = values[(values >= low) & (values <= high)]
    bins = max(MIN_FIT_BINS, math.ceil(2 * reach / cloud.fwhm * FIT_BINS_PER_FWHM)) if cloud.fwhm > 0 else MIN_FIT_BINS
    fit: FitResult | None = None
    if not (high > low and len(near) >= 2):
        if len(near) < 2:
            return Estimate(math.nan), Estimate(math.nan), None, reach
        return _mean_arrival(near, reach, "too few events near the peak", notes) + (None, reach)
    counts, edges = np.histogram(near, bins=bins, range=(low, high))
    centres = bin_centres(edges)
    models: list[tuple[str, FitModel | str]] = []
    try:
        models.append(("the arrival-time profile", arrival_time_model(effective_fall_distance(constants),
                                                                      constants.g)))
    except ValueError as error:
        notes.append(f"no arrival-time fit ({error})")
    models.append(("a Gaussian", "gaussian"))
    reasons: list[str] = []
    for title, model in models:
        fit = fit_histogram(centres, counts, model)
        centre, sigma = fit["centre"], fit["sigma"]
        if not fit.ok:
            reasons.append(f"{title}: {fit.failure}")
        elif not (low <= centre.value <= high and math.isfinite(centre.se) and centre.se > 0):
            reasons.append(f"{title}: its centre is outside the window or has no error")
        else:
            if reasons:
                notes.append(f"the arrival-time fit failed ({reasons[0].split(': ', 1)[1]}): a Gaussian's "
                             "centre is used instead")
            notes.extend(f"fit: {note}" for note in fit.notes)
            return centre, sigma, fit, reach
    return _mean_arrival(near, reach, "; ".join(reasons), notes) + (fit, reach)


def _mean_arrival(near: npt.NDArray[np.float64], reach: float, reason: str, notes: list[str]
                  ) -> tuple[Estimate, Estimate]:
    spread = float(np.std(near, ddof=1))
    notes.append(f"the fits failed ({reason}): the mean time of the {len(near):,} events within "
                 f"{reach * 1e3:.3g} ms of the peak is used instead")
    return Estimate(float(near.mean()), spread / math.sqrt(len(near))), Estimate(spread)


def _origin(values: npt.NDArray[np.float64], xy: npt.NDArray[np.float64], arrival: float, width: float,
            reach: float, notes: list[str]) -> tuple[tuple[Estimate, Estimate], int, float]:
    """``_origin_drawn`` without what a plot draws."""
    origin, events, share, _, _ = _origin_drawn(values, xy, arrival, width, reach, notes)
    return origin, events, share


def _origin_drawn(values: npt.NDArray[np.float64], xy: npt.NDArray[np.float64], arrival: float, width: float,
                  reach: float, notes: list[str]
                  ) -> tuple[tuple[Estimate, Estimate], int, float, float, XYWindow]:
    """(the rest cloud's (X, Y) centre ± s/√n (within run), its events, the background's
    estimated share of them, the T slice's half-width, the XY window), from the events within
    ``ORIGIN_SIGMAS`` σ_t of its arrival (and the fit window) with finite X and Y, kept to an XY
    window: ±``ORIGIN_WINDOW`` robust σ (1.4826 MAD) of the median, then again about the kept events' median and spread. The
    window keeps a uniform background and another cloud in the same T slice (a horizontal
    Bragg order) out of the mean unless they fall inside it. The background's share is its
    density in a frame around the window (out to twice its half-widths) times the window's
    area, over the events kept; nan (noted) when the frame reaches past the slice's events or
    the window covers more than ``ORIGIN_MOST`` of their XY bounding box (a clean cloud:
    nothing outside to measure)."""
    half = min(ORIGIN_SIGMAS * width, reach) if math.isfinite(width) and width > 0 else reach
    near = xy[(np.abs(values - arrival) <= half) & np.all(np.isfinite(xy), axis=1)]

    def window(points: npt.NDArray[np.float64]) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        centre = np.median(points, axis=0)
        spread = 1.4826 * np.median(np.abs(points - centre), axis=0)
        return centre - ORIGIN_WINDOW * spread, centre + ORIGIN_WINDOW * spread

    chosen = near
    low, high = np.full(2, -math.inf), np.full(2, math.inf)
    for _ in range(2):  # the median's window, then once more about what it kept
        if len(chosen) < 2:
            break
        low, high = window(chosen)
        chosen = near[np.all((near >= low) & (near <= high), axis=1)]
    unfound = ((math.nan, math.nan), (math.nan, math.nan))
    if len(chosen) < 2:
        notes.append(f"no XY origin: {len(chosen)} event{'' if len(chosen) == 1 else 's'} with finite X and Y "
                     "near the cloud's arrival")
        return NO_ORIGIN, len(chosen), math.nan, half, unfound
    window_xy = ((float(low[0]), float(high[0])), (float(low[1]), float(high[1])))
    root = math.sqrt(len(chosen))
    x, y = (Estimate(float(chosen[:, axis].mean()), float(np.std(chosen[:, axis], ddof=1)) / root)
            for axis in (0, 1))
    # The background's density from a frame around the window, as wide again on each side
    # (three times its area; the cloud's own tails there are ~0.5 % of it).
    # Unknown (nan, noted) when the window covers most of the slice's XY extent (too little
    # outside it to measure), or the frame reaches past the slice's events, where there may
    # be no detector.
    middle, reach_xy = (low + high) / 2, (high - low) / 2
    extent = near.max(axis=0) - near.min(axis=0)
    most = bool(np.prod(2 * reach_xy) > ORIGIN_MOST * np.prod(extent))
    past = bool(np.any(middle - 2 * reach_xy < near.min(axis=0)) or np.any(middle + 2 * reach_xy > near.max(axis=0)))
    if not np.all(reach_xy > 0) or most or past:
        why = ("its window covers most of the T slice's XY extent: a background that fills the slice "
               "would pull the origin towards its own centre" if most else
               "the frame around its window reaches past the T slice's events")
        notes.append(f"XY origin: background share unknown ({why})")
        return (x, y), len(chosen), math.nan, half, window_xy
    frame = near[np.all(np.abs(near - middle) <= 2 * reach_xy, axis=1)]
    share = min((len(frame) - len(chosen)) / 3 / len(chosen), 1.0)
    if share > ORIGIN_BACKGROUND_NOTE:
        notes.append(f"XY origin: about {share:.0%} of its {len(chosen):,} events are background (the density "
                     "outside its window), pulling it towards the background's centre")
    return (x, y), len(chosen), share, half, window_xy
