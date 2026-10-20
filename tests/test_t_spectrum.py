"""T spectrum (D6): the summed T profile's spectrum finds a known pulse-rate modulation within
one frequency bin, with the right resolution and Nyquist frequency, for every window; units,
power, padding, peaks above a frequency, empty and short cases, and drawing in place."""
from __future__ import annotations

from typing import Any, cast

import numpy as np
import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtWidgets import QLabel

from helab.analysis import spectrum as spectrum_module
from helab.analysis.dataset_view import DatasetView, build_view
from helab.analysis.display_units import frequency_text, si_text, time_text
from helab.analysis.parameters import effective
from helab.analysis.plot_axes import GroupedAxis
from helab.analysis.results import AnalysisContext, AnalysisResult, Cancelled, RamResults
from helab.analysis.spectrum import (FLAT_TOP, MAX_PADDED, WINDOWS, SpectrumPeak, amplitude_spectrum, find_spectrum_peaks,
                                     padding_for, refine)
from helab.scripts.dld import t_spectrum
from helab.utils.folder_cache import Dataset

PATH = "/data/root/run_D6"
SCRIPT = t_spectrum.TProfileSpectrum()
T0, SPAN = 0.40, 0.05
F0, DEPTH = 2000.0, 0.2  # the pulse rate's modulation: 1 + 0.2 cos(2π·2 kHz·(T − T0))
FULL = {"keep_percent": 100.0}


def view_of_shots(shots: dict[int, np.ndarray[Any, Any]]) -> DatasetView:
    for array in shots.values():
        array.setflags(write=False)
    prints = [[shot, 100 + shot, 1_000 + shot] for shot in sorted(shots)]
    return build_view(Dataset(PATH, "sig-d6", shots, {"fingerprint": prints, "source": "merged"}, 0))


def modulated(shots: int = 10, per_shot: int = 20_000, frequency: float = F0, seed: int = 3,
              envelope: float = 0.0) -> DatasetView:
    """Events in T over SPAN at a rate modulated at ``frequency`` (rejection sampling), under a
    Gaussian cloud of SD ``envelope`` (0: flat)."""
    rng = np.random.default_rng(seed)
    data = {}
    for shot in range(1, shots + 1):
        times = np.empty(0)
        while len(times) < per_shot:
            t = (T0 + SPAN / 2 + rng.normal(0, envelope, per_shot) if envelope
                 else T0 + rng.uniform(0, SPAN, per_shot))
            t = t[(t >= T0) & (t < T0 + SPAN)]
            keep = rng.uniform(0, 1 + DEPTH, len(t)) < 1 + DEPTH * np.cos(2 * np.pi * frequency * (t - T0))
            times = np.concatenate([times, t[keep]])
        times = times[:per_shot]
        times[0], times[-1] = T0, T0 + SPAN  # the full span exactly: whole bins from T0
        data[shot] = np.column_stack([times, rng.normal(0, 1e-3, per_shot), rng.normal(0, 1e-3, per_shot)])
    return view_of_shots(data)


def run(view: DatasetView, values: dict[str, Any] | None = None) -> AnalysisResult:
    context = AnalysisContext("a1", "Plot", view, effective(SCRIPT.parameters("Plot"), values),
                              SCRIPT.get_metadata().identity())
    data = SCRIPT.compute("Plot", context)
    return AnalysisResult.of(context, "completed", data, found=SCRIPT.result_found("Plot", data))




def test_finds_the_pulse_rate_modulation_within_one_bin() -> None:
    result = run(modulated(), {**FULL, "t_bin": 10e-6})
    data: t_spectrum.ProfileSpectrum = result.data
    spectrum = data.spectrum
    assert spectrum is not None and len(data.counts) == 5000 and not data.automatic and spectrum.binned
    assert spectrum.nyquist == pytest.approx(50_000.0) and spectrum.bin_spacing == pytest.approx(20.0, rel=1e-6)
    assert spectrum.enbw == pytest.approx(1.5) and spectrum.resolution == pytest.approx(30.0, rel=1e-6)
    top = spectrum.peaks[0]
    assert abs(top.frequency - F0) <= 0.05 * spectrum.bin_spacing
    # Rate per shot: 20,000 events in 50 ms is 400 kHz per shot, modulated by 20 %: 80 kHz per shot.
    assert data.profile.mean() == pytest.approx(400.0, rel=1e-3) and data.unit == "kHz per shot"
    assert top.value == pytest.approx(80.0, rel=0.05) and top.prominence > 0.5 * top.value
    assert spectrum.peaks == (top,)  # the noise lists nothing else
    text = SCRIPT.describe_result("Plot", result)
    assert text == "bin spacing Δf 20 Hz, resolution ≈ 30 Hz (ENBW 1.5), Nyquist 50 kHz"
    assert t_spectrum.peak_lines(data)[0].startswith("1. 2 kHz · 8")
    record = SCRIPT.result_record("Plot", result)
    assert record[0] == "T profile: 5,000 bins of 0.01 ms (set), 200,000 events"
    assert record[1].startswith("Spectrum: Hann window, bin spacing Δf 20 Hz") and "÷ sinc" in record[1]
    assert record[2].startswith("Peaks (prominence ≥ ") and record[3].startswith("  1. 2 kHz · 8")
    # The settings line's addition and the record are the result's ``found``: a released plot
    # (its data dropped) keeps both.
    released = RamResults().released(result)
    assert released.data is None and SCRIPT.describe_result("Plot", released) == text
    assert SCRIPT.result_record("Plot", released) == record


@pytest.mark.parametrize("window", list(WINDOWS))
def test_every_window_finds_it_and_nothing_else(window: str) -> None:
    data = run(modulated(shots=4), {**FULL, "t_bin": 10e-6, "window": window}).data
    peaks = data.spectrum.peaks
    assert data.spectrum.window == window and abs(peaks[0].frequency - F0) <= data.spectrum.bin_spacing
    # No sidelobe of it is listed; a rare noise peak just over the threshold may be (well below it).
    assert all(abs(peak.frequency - F0) > 10 * data.spectrum.bin_spacing and peak.value < 0.3 * peaks[0].value
               for peak in peaks[1:])


def test_off_bin_frequency_padding_and_flat_top_amplitude() -> None:
    # Half a bin off: the parabola (and zero padding) place it within a small part of a bin;
    # flat top reads the amplitude truest.
    off = F0 + 10.0
    view = modulated(shots=40, frequency=off)
    plain = run(view, {**FULL, "t_bin": 10e-6}).data.spectrum
    assert abs(plain.peaks[0].frequency - off) < 0.05 * plain.bin_spacing
    padded = run(view, {**FULL, "t_bin": 10e-6, "padding": 4}).data.spectrum
    assert padded.padding == 4 and padded.grid_spacing == pytest.approx(5.0)
    assert len(padded.values) == 4 * 5000 // 2 + 1 and abs(padded.peaks[0].frequency - off) < 0.05 * padded.bin_spacing
    assert padded.bin_spacing == pytest.approx(20.0)  # padding improves neither spacing nor resolution
    flat = run(view, {**FULL, "t_bin": 10e-6, "window": FLAT_TOP}).data.spectrum
    assert flat.peaks[0].value == pytest.approx(80.0, rel=0.05)
    assert abs(flat.peaks[0].frequency - off) <= 0.5 * flat.bin_spacing  # its flat top places it less well


def test_binning_attenuation_is_corrected() -> None:
    # 40 kHz in 10 µs bins (0.4 of the bin rate): the bins hold sinc(0.4) = 0.76 of it.
    data = run(modulated(shots=20, frequency=40_000.0), {**FULL, "t_bin": 10e-6}).data
    peak = data.spectrum.peaks[0]
    assert peak.frequency == pytest.approx(40_000, abs=5) and peak.value == pytest.approx(80.0, rel=0.06)
    correction = data.spectrum.correction()
    assert correction[0] == 1.0 and correction[-1] == pytest.approx(2 / np.pi)


def test_counts_power_and_peaks_above() -> None:
    view = modulated(shots=4)
    counts = run(view, {**FULL, "t_bin": 10e-6, "profile_units": "counts"}).data
    assert counts.unit == "events" and counts.profile.sum() == 80_000
    # 4 shots × 20,000 events over 5,000 bins: 16 per bin, modulated by 20 %.
    assert counts.spectrum.peaks[0].value == pytest.approx(16 * DEPTH, rel=0.15)
    power = run(view, {**FULL, "t_bin": 10e-6, "profile_units": "counts", "spectrum_scale": "power"}).data
    assert power.spectrum.power and t_spectrum.value_unit(power) == "events²"
    assert power.spectrum.peaks[0].value == pytest.approx(counts.spectrum.peaks[0].value ** 2, rel=1e-9)
    assert power.spectrum.peaks[0].frequency == counts.spectrum.peaks[0].frequency
    above = run(view, {**FULL, "t_bin": 10e-6, "peaks_above": 2500.0}).data.spectrum
    assert all(peak.frequency > 2500 for peak in above.peaks)
    none = run(view, {**FULL, "t_bin": 10e-6, "peaks": 0}).data.spectrum
    assert none.peaks == () and none.threshold == 0


def test_pure_noise_lists_no_peak_in_amplitude_or_power() -> None:
    rng = np.random.default_rng(8)
    for scale in ("amplitude", "power"):
        listed = 0
        for _ in range(20):
            times = np.sort(T0 + rng.uniform(0, SPAN, 50_000))
            times[0], times[-1] = T0, T0 + SPAN
            view = view_of_shots({1: np.column_stack([times, np.zeros((len(times), 2))])})
            listed += len(run(view, {**FULL, "peaks": 50, "spectrum_scale": scale}).data.spectrum.peaks)
        assert listed <= 2, scale


def test_a_cloud_envelope_doesnt_hide_the_modulation() -> None:
    data = run(modulated(shots=10, envelope=0.01), {**FULL, "t_bin": 10e-6, "peaks_above": 500.0}).data
    assert abs(data.spectrum.peaks[0].frequency - F0) <= data.spectrum.bin_spacing


def test_automatic_bins_follow_the_data_rate_within_their_limits() -> None:
    few = run(modulated(shots=1), FULL)
    assert few.data.automatic and len(few.data.counts) == 2_000 and few.data.clamp == ""  # 10 events per bin
    assert few.data.spectrum.nyquist == pytest.approx(20_000 / SPAN / 20, rel=1e-3)
    assert SCRIPT.describe_result("Plot", few).startswith("T bins 0.025 ms (auto: ~10 events per bin) · bin spacing")
    assert len(run(modulated(shots=5), FULL).data.counts) == 10_000
    many = run(modulated(shots=10), FULL)
    assert many.data.clamp == "at most" and len(many.data.counts) == 16_384
    assert "(auto: at most 16,384 bins, ~12.2 events per bin)" in SCRIPT.describe_result("Plot", many)
    assert abs(many.data.spectrum.peaks[0].frequency - F0) <= many.data.spectrum.bin_spacing
    sparse = run(modulated(shots=1, per_shot=100), FULL)
    assert len(sparse.data.counts) == 256 and sparse.data.clamp == "at least"
    assert "(auto: at least 256 bins, ~0.391 events per bin)" in SCRIPT.describe_result("Plot", sparse)
    tiny = run(modulated(shots=1, per_shot=100), {**FULL, "t_bin": 1e-12}).data
    assert len(tiny.counts) == t_spectrum.MAX_BINS and any("over 1,048,576 bins" in w for w in tiny.warnings)


def test_a_set_width_wider_than_the_range_is_the_range() -> None:
    data = run(modulated(shots=1, per_shot=5_000), {**FULL, "t_bin": 0.08}).data
    assert data.width == pytest.approx(SPAN) and len(data.counts) == 1 and data.counts.sum() == 5_000
    assert data.profile[0] == pytest.approx(5_000 / SPAN / 1e3)  # the true rate, not 62.5 % of it
    assert "T bin width 80 ms is wider than the range (50 ms): using one bin of the range" in data.warnings


def test_a_set_width_uses_whole_bins_only() -> None:
    data = run(modulated(shots=1, per_shot=5_000), {**FULL, "t_bin": 3e-3}).data
    assert len(data.counts) == 16 and data.counts.sum() == data.events < 5_000
    assert data.notes == (f"{5_000 - data.events:,} events in the last 2 ms, past the last whole bin, left out",)
    assert data.profile.mean() == pytest.approx(data.events / 0.048 / 1e3, rel=1e-9)  # every bin whole


@pytest.mark.parametrize("case", ["no events in range", "too few events", "too few bins"])
def test_empty_and_short_cases_say_why(qtbot: QtBot, case: str) -> None:
    values: dict[str, Any] = cast(dict[str, dict[str, Any]], {
        "no events in range": {"range_mode": "manual", "t_min": 1.0, "t_max": 2.0},
        "too few events": FULL, "too few bins": {**FULL, "t_bin": SPAN / 8}})[case]
    view = modulated(shots=1, per_shot=5 if case == "too few events" else 500)
    result = run(view, values)
    widget = SCRIPT.render(result)
    qtbot.addWidget(widget)
    assert isinstance(widget, QLabel) and widget.objectName() == "plot_empty"
    expected = {"no events in range": "None of the 500 events in the chosen shots is inside the view range",
                "too few events": "Only 5 events in the view range: a spectrum needs 10 or more",
                "too few bins": "Only 8 T bins of 6.25 ms in the view range: a spectrum needs 16 or more"}[case]
    assert widget.text().startswith(expected)
    assert result.data.spectrum is None
    line = {"no events in range": "", "too few events": "T bins 0.1953 ms (auto: at least 256 bins, ~0.0195 events "
                                                        "per bin)", "too few bins": ""}[case]
    assert SCRIPT.describe_result("Plot", result) == line


def test_cancellation() -> None:
    context = AnalysisContext("a1", "Plot", modulated(shots=1), effective(SCRIPT.parameters("Plot"), FULL),
                              SCRIPT.get_metadata().identity())
    context.cancel_event.set()
    with pytest.raises(Cancelled):
        SCRIPT.compute("Plot", context)


def test_drawn_with_its_peak_list_and_updated_in_place(qtbot: QtBot) -> None:
    values = {**FULL, "t_bin": 10e-6}
    widget = SCRIPT.render(run(modulated(shots=2), values))
    qtbot.addWidget(widget)
    assert isinstance(widget, t_spectrum.SpectrumPlot)
    assert widget.profile_plot.getAxis("bottom").labelText == "T (ms)"
    assert widget.spectrum_plot.getAxis("bottom").labelUnits == "Hz"
    assert widget.spectrum_plot.getAxis("left").labelText == "Amplitude (kHz per shot)"
    assert isinstance(widget.spectrum_plot.getAxis("left"), GroupedAxis)
    assert "Peaks: 1. 2 kHz" in widget.peaks_label.text and len(widget.labels) == len(widget.markers.getData()[0])
    assert "bin spacing Δf 20 Hz, resolution ≈ 30 Hz (ENBW 1.5), Nyquist 50 kHz" in widget.title.text
    widget.spectrum_plot.vb.setXRange(1000, 3000, padding=0)
    assert SCRIPT.update(widget, run(modulated(shots=3, seed=4), values))
    assert widget.spectrum_plot.vb.viewRange()[0] == pytest.approx([1000, 3000]) and "3 shots" in widget.title.text
    assert not SCRIPT.update(widget, run(modulated(shots=2), {**values, "spectrum_log": False}))
    assert not SCRIPT.update(widget, run(modulated(shots=2), {**values, "profile_units": "counts"}))
    assert not SCRIPT.update(widget, run(modulated(shots=1, per_shot=5), FULL))


def test_settings_line_and_record_only_for_completed_runs() -> None:
    view = modulated(shots=3, per_shot=20)
    values = effective(SCRIPT.parameters("Plot"), {"shots": "last N", "last_shots": 2, "t_bin": 2e-6,
                                                   "padding": 4, "window": "Hamming"})
    assert SCRIPT.describe_run("Plot", values, view) == (
        "shots 2–3 (2 of 3)", "last 2 shots · auto-crop 99 % · T bins 0.002 ms · Hamming window, ×4 padding · log · "
        "5 peaks")
    failed = AnalysisResult.of(AnalysisContext("a1", "Plot", view, values, SCRIPT.get_metadata().identity()), "failed")
    assert SCRIPT.describe_result("Plot", failed) == "" and SCRIPT.result_record("Plot", failed) == []


# The spectrum helpers

STEP = 1e-3
TIMES = np.arange(1000) * STEP


def test_normalisation_dc_and_nyquist() -> None:
    # A sine of amplitude 3 on a bin, through each window: read as 3 (fft_tx's normalisation).
    for window in WINDOWS:
        spectrum = amplitude_spectrum(5 + 3 * np.sin(2 * np.pi * 50 * TIMES), STEP, window)
        assert spectrum.values[0] == pytest.approx(0, abs=1e-9)  # the mean is subtracted
        assert spectrum.values[50] == pytest.approx(3.0, rel=1e-6)
    # At Nyquist (alternating ±2): not doubled; binned, divided by sinc(½) = 2/π.
    alternating = np.where(np.arange(1000) % 2 == 0, 2.0, -2.0).astype(np.float64)
    assert amplitude_spectrum(alternating, STEP, "none").values[-1] == pytest.approx(2.0)
    assert amplitude_spectrum(alternating, STEP, "none", binned=True).values[-1] == pytest.approx(np.pi)
    odd = amplitude_spectrum(np.sin(2 * np.pi * 50 * np.arange(999) * STEP), STEP)
    assert len(odd.values) == 500 and odd.nyquist == 500
    assert padding_for(1000, 8) == (8, "") and padding_for(MAX_PADDED, 2)[0] == 1


# Frequency error bounds of the log parabola without padding, in bins, by window (flat top's
# top is flat and the rectangular window's peak is a sinc: placed less well).
BOUNDS = {"Hann": 0.03, "Hamming": 0.03, "Blackman": 0.02, "flat top": 0.15, "none": 0.2}


@pytest.mark.parametrize("window", list(WINDOWS))
def test_peak_frequency_error_bounds(window: str) -> None:
    for offset in np.linspace(0.0, 0.5, 11):
        frequency = 100 + offset
        trace = 3 * np.sin(2 * np.pi * frequency * TIMES)
        found = find_spectrum_peaks(amplitude_spectrum(trace, STEP, window), 1).peaks[0]
        assert abs(found.frequency - frequency) < BOUNDS[window], offset
        power = find_spectrum_peaks(amplitude_spectrum(trace, STEP, window, power=True), 1).peaks[0]
        assert power.frequency == pytest.approx(found.frequency) and power.value == pytest.approx(found.value ** 2)


def test_flat_top_is_placed_on_the_unpadded_bins() -> None:
    """Padding doesn't worsen it (the padded samples on its flat top only add noise)."""
    for padding in (1, 4, 16):
        for offset in np.linspace(0.0, 0.5, 11):
            trace = np.sin(2 * np.pi * (100 + offset) * TIMES)
            found = find_spectrum_peaks(amplitude_spectrum(trace, STEP, FLAT_TOP, padding), 1).peaks[0]
            assert abs(found.frequency - 100 - offset) < BOUNDS[FLAT_TOP], (padding, offset)


# The closest a second line at a tenth of the first is resolved, in bins, by window.
RESOLVED = {"Hann": 4, "Hamming": 4, "Blackman": 4, "flat top": 6, "none": 5}


@pytest.mark.parametrize("window", list(WINDOWS))
def test_a_weaker_line_3_to_10_bins_away_is_listed(window: str) -> None:
    """Two lines, the second a tenth (and 3 %) of the first, 3–10 bins apart, the first on a bin
    or off it: the sidelobe test never drops the weaker line (listed as without the test),
    and a tenth is listed from ``RESOLVED`` bins on (the reviewer's cases)."""
    step, samples = 1e-5, 5000
    times = np.arange(samples) * step
    spacing = 1 / (samples * step)
    margin = spectrum_module.SIDELOBE_MARGIN
    try:
        for ratio in (0.1, 0.03):
            for distance in range(3, 11):
                for offset in (0.0, 0.25, 0.5):
                    rng = np.random.default_rng(distance)
                    trace = (80 * np.cos(2 * np.pi * (300 + offset) * spacing * times)
                             + 80 * ratio * np.cos(2 * np.pi * (300 + offset + distance) * spacing * times + 1.0)
                             + rng.normal(0, 4, samples))
                    spectrum = amplitude_spectrum(trace, step, window)
                    target = 300 + offset + distance

                    def listed(peaks: tuple[SpectrumPeak, ...]) -> bool:
                        return any(abs(peak.frequency / spacing - target) < 1 for peak in peaks)
                    spectrum_module.SIDELOBE_MARGIN = margin
                    peaks = find_spectrum_peaks(spectrum, 5).peaks
                    found = listed(peaks)
                    spectrum_module.SIDELOBE_MARGIN = 0.0
                    # The rule drops only sidelobes (it may drop those): never the weaker line.
                    assert found == listed(find_spectrum_peaks(spectrum, 5).peaks) or (
                        window == FLAT_TOP and distance < RESOLVED[FLAT_TOP]), (ratio, distance, offset)
                    if ratio == 0.1 and distance >= RESOLVED[window]:
                        assert found, (distance, offset)
    finally:
        spectrum_module.SIDELOBE_MARGIN = margin


@pytest.mark.parametrize("window", list(WINDOWS))
def test_sidelobes_are_not_peaks_even_padded(window: str) -> None:
    rng = np.random.default_rng(3)
    trace = 100 * np.sin(2 * np.pi * 100.37 * TIMES) + rng.normal(0, 1, len(TIMES))
    peaks = find_spectrum_peaks(amplitude_spectrum(trace, STEP, window, padding=16), 10).peaks
    assert len(peaks) == 1 and abs(peaks[0].frequency - 100.37) < 0.5


def test_a_weak_peak_beside_a_strong_one_stays() -> None:
    rng = np.random.default_rng(4)
    trace = (100 * np.sin(2 * np.pi * 100.37 * TIMES) + 2 * np.sin(2 * np.pi * 160 * TIMES)
             + rng.normal(0, 0.2, len(TIMES)))
    peaks = find_spectrum_peaks(amplitude_spectrum(trace, STEP, "Hann", padding=4), 10).peaks
    assert [round(peak.frequency) for peak in peaks] == [100, 160]


def test_small_helpers_and_units() -> None:
    assert refine(np.array([1.0, 3.0, 1.0]), 1) == pytest.approx((0.0, 3.0))
    assert refine(np.array([1.0, 2.0]), 0) == (0.0, 1.0)
    assert refine(np.array([0.0, 3.0, 1.0]), 1)[0] == pytest.approx(0.1)  # a zero: the straight parabola
    flat = find_spectrum_peaks(amplitude_spectrum(np.zeros(64), STEP), 3)
    assert flat.peaks == ()
    assert frequency_text(1250) == "1.25 kHz" and si_text(5e-8, "s") == "50 ns" and si_text(-0.002, "m") == "−2 mm"
    assert si_text(0.00099999, "s") == "1 ms" and si_text(float("nan"), "Hz") == "–" and si_text(0, "Hz") == "0 Hz"
    assert time_text(0.4) == "400 ms" and time_text(20.5) == "20,500 ms"  # T always in ms
