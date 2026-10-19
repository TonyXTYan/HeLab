"""Amplitude spectra of evenly sampled traces, and their peaks: pure NumPy and SciPy, no Qt,
so they run in the analysis worker and in tests (the T profile's spectrum, the mean position's
against T).

The normalisation is Core's ``fft_tx``: the trace's mean is subtracted (no DC), it is
multiplied by the window, and the one-sided amplitude is ``2·|rfft|/sum(window)`` (the DC
and Nyquist bins are not doubled), so a sine of amplitude A whose frequency falls on a bin
peaks at A, whatever the window. Zero padding samples the same spectrum more finely without
improving its resolution, ``1/(samples·step)``. Power is the amplitude squared (not a density
per Hz).

Peaks: ``scipy.signal.find_peaks`` above the lowest frequency asked, with a prominence of at
least ``threshold`` times the spectrum's median there (a noise floor estimate), the most
prominent first; each refined by a parabola through its bin and its neighbours.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

import numpy as np
import numpy.typing as npt
from scipy.signal import find_peaks, get_window

from helab.analysis.parameters import ParameterSpec

Array = npt.NDArray[np.float64]

HANN, HAMMING, BLACKMAN, FLAT_TOP, NO_WINDOW = "Hann", "Hamming", "Blackman", "flat top", "none"
WINDOWS = {HANN: "hann", HAMMING: "hamming", BLACKMAN: "blackman", FLAT_TOP: "flattop", NO_WINDOW: "boxcar"}
AMPLITUDE, POWER = "amplitude", "power"
MAX_PADDING = 16
MAX_PADDED = 1 << 22  # samples after zero padding, at most (the padding is lowered to fit)
DEFAULT_THRESHOLD = 4.0  # × the median: noise (Rayleigh-distributed) rarely gets there


@dataclass(frozen=True)
class Peak:
    frequency: float  # Hz, refined between bins
    value: float  # the spectrum's value there (amplitude or power), refined
    prominence: float  # in the spectrum's units (``find_peaks``)


@dataclass(frozen=True)
class Spectrum:
    values: Array  # amplitude (or power) at ``frequencies``, from 0 Hz
    step: float  # the trace's sample spacing (s)
    samples: int  # the trace's samples (before padding)
    padding: int  # the transform's length over ``samples``
    window: str  # a ``WINDOWS`` name
    power: bool = False
    peaks: tuple[Peak, ...] = ()
    threshold: float = 0.0  # the least prominence a listed peak had to have (0: none asked)

    @property
    def frequencies(self) -> Array:
        return cast(Array, np.fft.rfftfreq(self.samples * self.padding, self.step))

    @property
    def resolution(self) -> float:
        """The frequency resolution: 1 over the trace's length (padding doesn't change it)."""
        return 1.0 / (self.samples * self.step)

    @property
    def spacing(self) -> float:
        """The spacing of the frequencies shown (the resolution over the padding)."""
        return self.resolution / self.padding

    @property
    def nyquist(self) -> float:
        return 0.5 / self.step


def window_values(window: str, samples: int) -> Array:
    """The window (periodic, as for spectra) of that name; ``none`` is flat."""
    return cast(Array, np.asarray(get_window(WINDOWS.get(window, "hann"), samples, fftbins=True), dtype=np.float64))


def padding_for(samples: int, padding: int) -> tuple[int, str]:
    """The padding used, lowered so that the transform is at most ``MAX_PADDED`` long; with
    what it says when lowered."""
    padding = min(max(padding, 1), MAX_PADDING)
    fits = max(1, MAX_PADDED // max(samples, 1))
    if padding > fits:
        return fits, f"zero padding ×{padding} is over {MAX_PADDED:,} samples: using ×{fits}"
    return padding, ""


def amplitude_spectrum(trace: Array, step: float, window: str = HANN, padding: int = 1,
                       power: bool = False) -> Spectrum:
    """The one-sided amplitude (or power) spectrum of ``trace``, sampled every ``step`` s.
    ``padding`` must already fit (``padding_for``)."""
    samples = len(trace)
    values = np.asarray(trace, dtype=np.float64)
    weights = window_values(window, samples)
    length = samples * padding
    transform = np.fft.rfft((values - values.mean()) * weights, n=length)
    amplitude = np.abs(transform) / float(weights.sum())
    amplitude[1:] *= 2
    if length % 2 == 0:
        amplitude[-1] /= 2  # The Nyquist bin, like DC, has no mirror image.
    return Spectrum(amplitude ** 2 if power else amplitude, step, samples, padding, window, power)


def refine(values: Array, index: int) -> tuple[float, float]:
    """The vertex of the parabola through the bins at ``index − 1 … index + 1``: (offset in
    bins, value); (0, the bin's value) at an end or on a flat top."""
    if not 0 < index < len(values) - 1:
        return 0.0, float(values[index])
    a, b, c = float(values[index - 1]), float(values[index]), float(values[index + 1])
    curve = a - 2 * b + c
    if curve >= 0:
        return 0.0, b
    offset = 0.5 * (a - c) / curve
    return offset, b - 0.25 * (a - c) * offset


def find_spectrum_peaks(spectrum: Spectrum, count: int, above: float = 0.0,
                        threshold: float = DEFAULT_THRESHOLD) -> Spectrum:
    """``spectrum`` with its ``count`` most prominent peaks above ``above`` Hz (never DC) whose
    prominence is at least ``threshold`` times the median value there."""
    values = spectrum.values
    frequencies = spectrum.frequencies
    start = max(1, int(np.searchsorted(frequencies, above, "right")))
    if count <= 0 or len(values) - start < 3:
        return Spectrum(values, spectrum.step, spectrum.samples, spectrum.padding, spectrum.window,
                        spectrum.power)
    searched = values[start:]
    floor = float(np.median(searched))
    least = threshold * floor if floor > 0 else float(searched.max()) * 1e-9
    least = least if least > 0 else math.ulp(0.0)
    found, properties = find_peaks(searched, prominence=least, distance=max(1, spectrum.padding))
    order = np.argsort(-properties["prominences"], kind="stable")[:count]
    peaks = []
    for position in order:
        index = int(found[position]) + start
        offset, value = refine(values, index)
        peaks.append(Peak(float(frequencies[index]) + offset * spectrum.spacing, value,
                          float(properties["prominences"][position])))
    return Spectrum(values, spectrum.step, spectrum.samples, spectrum.padding, spectrum.window, spectrum.power,
                    tuple(peaks), least)


# Parameters a plot with a spectrum declares (in its own group, optionally only ``when``).

def window_spec(group: str, when: tuple[str, str] | None = None, default: str = HANN) -> ParameterSpec:
    return ParameterSpec("window", "Window", "choice", default, choices=tuple(WINDOWS), group=group, when=when,
                         tip="Taper applied before the transform (after the mean is subtracted). Hann: low leakage "
                             "far from a peak; flat top: the truest amplitude; none: the narrowest peaks, the most "
                             "leakage. Amplitudes are normalised by the window's sum, so a sine reads its amplitude.")


def peak_specs(group: str, count: int, when: tuple[str, str] | None = None) -> tuple[ParameterSpec, ...]:
    return (ParameterSpec("peaks", "Peaks listed", "int", count, (0, 50), group=group, when=when,
                          tip="The most prominent peaks are marked and listed with their frequency, value and "
                              "prominence (0 = none)."),
            ParameterSpec("peak_threshold", "Peak prominence ≥ (× median)", "float", DEFAULT_THRESHOLD,
                          (0.0, 1e6), group=group, when=when,
                          tip="A listed peak stands out at least this many times the spectrum's median (a noise "
                              "floor estimate) above its surroundings."),
            ParameterSpec("peaks_above", "Peaks above (0 = all)", "float", 0.0, (0.0, 1e12), " Hz", group=group,
                          when=when, si=True,
                          tip="Peaks at or below this frequency are not listed (e.g. the cloud's own shape, at "
                              "low frequencies)."))
