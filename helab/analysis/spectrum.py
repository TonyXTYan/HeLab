"""Amplitude spectra of evenly sampled traces, and their peaks: pure NumPy and SciPy, no Qt,
so they run in the analysis worker and in tests (the T profile's spectrum, the mean position's
against T).

The normalisation is Core's ``fft_tx``: the trace's mean is subtracted (no DC), it is
multiplied by the window, and the one-sided amplitude is ``2·|rfft|/sum(window)`` (the DC
and Nyquist bins are not doubled), so a sine of amplitude A whose frequency falls on a bin
peaks at A, whatever the window. Power is the amplitude squared (not a density per Hz).

Frequencies: the bin spacing is ``Δf = 1/(samples·step)``; two sines are told apart about
``ENBW·Δf`` apart (the window's equivalent noise bandwidth, in bins: none 1, Hann 1.5,
Hamming 1.36, Blackman 1.73, flat top 3.77), the resolution quoted. Zero padding draws the
same spectrum more finely (``grid_spacing``) without improving either.

Binned traces (``binned``): a trace whose samples are averages over their bin (a histogram's
counts, a bin's mean position) has each frequency's amplitude reduced by ``sinc(f·step)``
(−36 % at Nyquist), which ``binned`` divides out. That is right for a real modulation; shot
noise, being white in the bins, is raised by the same factor towards Nyquist (up to ×1.57), so
peaks are found on the uncorrected spectrum, whose noise floor is flat, and only their values
corrected.

Peaks are found on the amplitude (the square root in power mode, so the threshold means the
same in both) of the unpadded bins, where a window's sidelobes don't show as separate maxima:
``scipy.signal.find_peaks`` above the lowest frequency asked, at least the window's main-lobe
half-width apart, with a prominence of at least ``threshold`` times the median amplitude there
(a noise-floor estimate), the most prominent first; a peak no more than twice as tall as a
stronger one's leakage at its exact (fractional) distance from it is taken for that line's
sidelobe and left out; a real line between sidelobes, where the leakage is low, stays. Each is then placed on the padded
spectrum's highest sample near it and refined by a parabola through the logarithms of it and
its neighbours (a Gaussian fit to the peak's top: little bias for the tapered windows; a
straight parabola where a value is 0).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

import numpy as np
import numpy.typing as npt
from scipy.signal import find_peaks, get_window

from helab.analysis.display_units import WIDTH_DIGITS, frequency_text, time_text
from helab.analysis.parameters import ParameterSpec

Array = npt.NDArray[np.float64]

HANN, HAMMING, BLACKMAN, FLAT_TOP, NO_WINDOW = "Hann", "Hamming", "Blackman", "flat top", "none"
WINDOWS = {HANN: "hann", HAMMING: "hamming", BLACKMAN: "blackman", FLAT_TOP: "flattop", NO_WINDOW: "boxcar"}
# Half the main lobe's width, in bins: peaks closer than this are one peak.
MAIN_LOBE = {NO_WINDOW: 1, HANN: 2, HAMMING: 2, BLACKMAN: 3, FLAT_TOP: 5}
AMPLITUDE, POWER = "amplitude", "power"
MAX_PADDING = 16
MAX_PADDED = 1 << 22  # samples after zero padding, at most (the padding is lowered to fit)
DEFAULT_THRESHOLD = 4.0  # × the median amplitude: noise (Rayleigh-distributed) rarely gets there


@dataclass(frozen=True)
class SpectrumPeak:
    frequency: float  # Hz, refined between bins
    value: float  # the spectrum's value there (amplitude or power), refined and binning-corrected
    prominence: float  # in amplitude (also in power mode), before the binning correction


@dataclass(frozen=True)
class Spectrum:
    values: Array  # amplitude (or power) at ``frequencies``, from 0 Hz
    step: float  # the trace's sample spacing (s)
    samples: int  # the trace's samples (before padding)
    padding: int  # the transform's length over ``samples``
    window: str  # a ``WINDOWS`` name
    power: bool = False
    peaks: tuple[SpectrumPeak, ...] = ()
    threshold: float = 0.0  # the least prominence (amplitude) a listed peak had to have (0: none asked)
    binned: bool = False  # values divided by sinc(f·step)
    enbw: float = 1.0  # the window's equivalent noise bandwidth, in bins

    @property
    def frequencies(self) -> Array:
        return cast(Array, np.fft.rfftfreq(self.samples * self.padding, self.step))

    @property
    def bin_spacing(self) -> float:
        """Δf: 1 over the trace's length (padding doesn't change it)."""
        return 1.0 / (self.samples * self.step)

    @property
    def resolution(self) -> float:
        """About how far apart two sines can be told apart: ENBW · Δf."""
        return self.enbw * self.bin_spacing

    @property
    def grid_spacing(self) -> float:
        """The spacing of the frequencies drawn (Δf over the padding)."""
        return self.bin_spacing / self.padding

    @property
    def nyquist(self) -> float:
        return 0.5 / self.step

    def correction(self) -> Array:
        """What each value was divided by: sinc(f·step) (squared for power), or 1."""
        if not self.binned:
            return np.ones(len(self.values))
        factor = np.sinc(self.frequencies * self.step)
        return factor ** 2 if self.power else factor


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
                       power: bool = False, binned: bool = False) -> Spectrum:
    """The one-sided amplitude (or power) spectrum of ``trace``, sampled every ``step`` s;
    ``binned``: its samples are bin averages, corrected for (module docstring). ``padding``
    must already fit (``padding_for``)."""
    samples = len(trace)
    values = np.asarray(trace, dtype=np.float64)
    weights = window_values(window, samples)
    length = samples * padding
    transform = np.fft.rfft((values - values.mean()) * weights, n=length)
    amplitude = np.abs(transform) / float(weights.sum())
    amplitude[1:] *= 2
    if length % 2 == 0:
        amplitude[-1] /= 2  # The Nyquist bin, like DC, has no mirror image.
    if binned:
        amplitude /= np.sinc(np.fft.rfftfreq(length, step) * step)
    enbw = samples * float(np.sum(weights ** 2)) / float(weights.sum()) ** 2
    return Spectrum(amplitude ** 2 if power else amplitude, step, samples, padding, window, power,
                    binned=binned, enbw=enbw)


def refine(values: Array, index: int) -> tuple[float, float]:
    """The vertex of the parabola through the logarithms of the values at ``index − 1 …
    index + 1`` (a straight parabola where one is 0): (offset in bins, value); (0, the bin's
    value) at an end or on a flat top."""
    if not 0 < index < len(values) - 1:
        return 0.0, float(values[index])
    a, b, c = float(values[index - 1]), float(values[index]), float(values[index + 1])
    logarithmic = a > 0 and b > 0 and c > 0
    if logarithmic:
        a, b, c = math.log(a), math.log(b), math.log(c)
    curve = a - 2 * b + c
    if curve >= 0:
        return 0.0, float(values[index])
    offset = 0.5 * (a - c) / curve
    top = b - 0.25 * (a - c) * offset
    return offset, math.exp(top) if logarithmic else top


SIDELOBE_MARGIN = 1.25  # a peak's bin must hold this many times a stronger line's leakage into it
_LEAKAGE: dict[str, Array] = {}
LEAKAGE_PADDING = 64


def leakage(window: str, distance: float) -> float:
    """How much of a line the window leaks ``distance`` bins (fractional) from it: its
    transform's magnitude there over its peak (1 within the main lobe). Measured once per
    window, on 256 samples padded ×64 (the shape in bins hardly depends on the length)."""
    response = _LEAKAGE.get(window)
    if response is None:
        samples = 256
        weights = window_values(window, samples)
        response = np.abs(np.fft.rfft(weights, n=samples * LEAKAGE_PADDING))
        response /= response[0]
        response[:MAIN_LOBE.get(window, 2) * LEAKAGE_PADDING] = 1.0
        _LEAKAGE[window] = response
    position = int(round(distance * LEAKAGE_PADDING))
    return float(response[min(position, len(response) - 1)])


def find_spectrum_peaks(spectrum: Spectrum, count: int, above: float = 0.0,
                        threshold: float = DEFAULT_THRESHOLD) -> Spectrum:
    """``spectrum`` with its ``count`` most prominent peaks above ``above`` Hz (never DC) whose
    prominence in amplitude is at least ``threshold`` times the median amplitude there (module
    docstring)."""
    def without() -> Spectrum:
        return Spectrum(spectrum.values, spectrum.step, spectrum.samples, spectrum.padding, spectrum.window,
                        spectrum.power, binned=spectrum.binned, enbw=spectrum.enbw)

    padding = spectrum.padding
    correction = spectrum.correction()
    raw = spectrum.values * correction  # before the binning correction: a flat noise floor
    amplitude = np.sqrt(raw) if spectrum.power else raw
    coarse = amplitude[::padding]  # the unpadded bins: no sidelobe maxima between them
    frequencies = spectrum.frequencies
    start = max(1, int(np.searchsorted(frequencies[::padding], above, "right")))
    if count <= 0 or len(coarse) - start < 3:
        return without()
    searched = coarse[start:]
    floor = float(np.median(searched))
    least = threshold * floor if floor > 0 else float(searched.max()) * 1e-9
    least = least if least > 0 else math.ulp(0.0)
    found, properties = find_peaks(searched, prominence=least, distance=MAIN_LOBE.get(spectrum.window, 2))
    # (frequency, amplitude before correction, prominence, the unpadded bin's frequency and amplitude)
    candidates: list[tuple[float, float, float, float, float]] = []
    for position in range(len(found)):
        bin_index = int(found[position]) + start
        if spectrum.window == FLAT_TOP:
            # Its top is flat: the padded samples on it only add noise to where the top is.
            offset, top = refine(coarse, bin_index)
            frequency = float(frequencies[bin_index * padding]) + offset * spectrum.bin_spacing
        else:
            centre = bin_index * padding
            low, high = max(1, centre - padding + 1), min(len(amplitude), centre + padding)
            index = low + int(np.argmax(amplitude[low:high]))  # the padded spectrum's top near it
            offset, top = refine(amplitude, index)
            frequency = float(frequencies[index]) + offset * spectrum.grid_spacing
        candidates.append((frequency, top, float(properties["prominences"][position]),
                           float(frequencies[bin_index * padding]), float(coarse[bin_index])))
    # A peak whose bin holds no more than a stronger line's leakage into that bin (from the
    # line's refined frequency; with a margin for noise) is that line's sidelobe.
    real: list[tuple[float, float, float, float, float]] = []
    for candidate in sorted(candidates, key=lambda item: -item[1]):
        if all(candidate[4] > SIDELOBE_MARGIN * other[1] * leakage(spectrum.window, abs(candidate[3] - other[0])
                                                                   / spectrum.bin_spacing) for other in real):
            real.append(candidate)
    peaks = []
    for frequency, top, prominence, _, _ in sorted(real, key=lambda item: -item[2])[:count]:
        value = top / float(np.sinc(frequency * spectrum.step)) if spectrum.binned else top
        peaks.append(SpectrumPeak(frequency, value ** 2 if spectrum.power else value, prominence))
    return Spectrum(spectrum.values, spectrum.step, spectrum.samples, padding, spectrum.window, spectrum.power,
                    tuple(peaks), least, spectrum.binned, spectrum.enbw)


@dataclass(frozen=True)
class WholeBins:
    """Values put in whole bins of one width from ``lower``: a bin past ``upper`` would be
    partial (its rate low, its sample off the even spacing), so the remainder past the last
    whole bin is left out (``dropped`` of the values; ``remainder`` s of the range)."""
    index: npt.NDArray[np.intp]  # each kept value's bin
    kept: npt.NDArray[np.bool_]  # which values are in a whole bin
    bins: int
    dropped: int
    remainder: float


def whole_bins(values: Array, lower: float, upper: float, width: float) -> WholeBins:
    span = upper - lower
    bins = max(1, int(math.floor(span / width + 1e-6)))  # a millionth of a bin short is whole
    remainder = max(span - bins * width, 0.0)
    raw = np.floor((values - lower) / width).astype(np.intp)
    if remainder <= 1e-6 * width:  # no partial bin: a value at the very end goes in the last
        raw = np.minimum(raw, bins - 1)
        remainder = 0.0
    kept = (raw >= 0) & (raw < bins)
    return WholeBins(raw[kept], kept, bins, int(len(values) - np.count_nonzero(kept)), remainder)


def dropped_text(binned: WholeBins) -> str:
    """The note when the remainder past the last whole bin held values ("" when it held none)."""
    if not binned.dropped:
        return ""
    return (f"{binned.dropped:,} event{'' if binned.dropped == 1 else 's'} in the last "
            f"{time_text(binned.remainder, WIDTH_DIGITS)}, past the last whole bin, left out")


def spectrum_text(spectrum: Spectrum) -> str:
    """``bin spacing Δf 20 Hz, resolution ≈ 30 Hz (ENBW 1.5), Nyquist 50 kHz`` for a dock line."""
    text = (f"bin spacing Δf {frequency_text(spectrum.bin_spacing)}, resolution ≈ "
            f"{frequency_text(spectrum.resolution)} (ENBW {spectrum.enbw:.3g}), Nyquist "
            f"{frequency_text(spectrum.nyquist)}")
    return text


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
                          tip="A listed peak stands out above its surroundings, in amplitude (also for power), at "
                              "least this many times the median amplitude (a noise floor estimate)."),
            ParameterSpec("peaks_above", "Peaks above (0 = all)", "float", 0.0, (0.0, 1e12), " Hz", group=group,
                          when=when, si=True,
                          tip="Peaks at or below this frequency are not listed (e.g. the cloud's own shape, at "
                              "low frequencies)."))
