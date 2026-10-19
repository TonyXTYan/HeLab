"""T spectrum (D6): the summed T profile's spectrum finds a known pulse-rate modulation within
one frequency bin, with the right resolution and Nyquist frequency, for every window; units,
power, padding, peaks above a frequency, empty and short cases, and drawing in place."""
from __future__ import annotations

from typing import Any, cast

import numpy as np
import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtWidgets import QLabel

from helab.analysis.dataset_view import DatasetView, build_view
from helab.analysis.display_units import frequency_text, si_text, time_text, time_unit
from helab.analysis.parameters import effective
from helab.analysis.results import AnalysisContext, AnalysisResult, Cancelled
from helab.analysis.spectrum import (FLAT_TOP, MAX_PADDED, WINDOWS, amplitude_spectrum, find_spectrum_peaks,
                                     padding_for, refine)
from helab.scripts.standard import t_spectrum
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
        times[0], times[-1] = T0, T0 + SPAN - 1e-9  # the full span exactly, so the bins start at T0
        data[shot] = np.column_stack([times, rng.normal(0, 1e-3, per_shot), rng.normal(0, 1e-3, per_shot)])
    return view_of_shots(data)


def run(view: DatasetView, values: dict[str, Any] | None = None) -> AnalysisResult:
    context = AnalysisContext("a1", "Plot", view, effective(SCRIPT.parameters("Plot"), values),
                              SCRIPT.get_metadata().identity())
    return AnalysisResult.of(context, "completed", SCRIPT.compute("Plot", context))


def test_finds_the_pulse_rate_modulation_within_one_bin() -> None:
    result = run(modulated(), {**FULL, "t_bin": 10e-6})
    data: t_spectrum.ProfileSpectrum = result.data
    spectrum = data.spectrum
    assert spectrum is not None and len(data.counts) == 5000 and not data.automatic
    assert spectrum.nyquist == pytest.approx(50_000.0) and spectrum.resolution == pytest.approx(20.0, rel=1e-6)
    top = spectrum.peaks[0]
    assert abs(top.frequency - F0) <= spectrum.resolution
    # Rate per shot: 20,000 events in 50 ms is 400 kHz per shot, modulated by 20 %: 80 kHz/shot.
    assert data.profile.mean() == pytest.approx(400.0, rel=1e-3) and data.unit == "kHz/shot"
    assert top.value == pytest.approx(80.0, rel=0.1) and top.prominence > 0.5 * top.value
    assert len(spectrum.peaks) <= 5  # the top 5 by prominence, the strongest first
    assert all(a.prominence >= b.prominence for a, b in zip(spectrum.peaks, spectrum.peaks[1:]))
    line = SCRIPT.describe_result("Plot", result)
    assert line == "Δf 20 Hz · Nyquist 50 kHz"
    assert t_spectrum.peak_lines(data)[0].startswith("1. 2 kHz · 8")


@pytest.mark.parametrize("window", list(WINDOWS))
def test_every_window_finds_it(window: str) -> None:
    data = run(modulated(shots=4), {**FULL, "t_bin": 10e-6, "window": window}).data
    assert data.spectrum.window == window
    assert abs(data.spectrum.peaks[0].frequency - F0) <= data.spectrum.resolution


def test_off_bin_frequency_padding_and_flat_top_amplitude() -> None:
    # Half a bin off: zero padding and the parabola place it closer than a bin; flat top reads
    # the amplitude truest.
    off = F0 + 10.0
    view = modulated(shots=40, frequency=off)
    padded = run(view, {**FULL, "t_bin": 10e-6, "padding": 4}).data.spectrum
    assert padded.padding == 4 and padded.spacing == pytest.approx(5.0) and len(padded.values) == 4 * 5000 // 2 + 1
    assert abs(padded.peaks[0].frequency - off) < 0.25 * padded.resolution
    assert padded.resolution == pytest.approx(20.0)  # padding doesn't improve the resolution
    flat = run(view, {**FULL, "t_bin": 10e-6, "window": FLAT_TOP}).data.spectrum
    assert flat.peaks[0].value == pytest.approx(80.0, rel=0.05)
    assert abs(flat.peaks[0].frequency - off) <= flat.resolution  # its flat top places it less well


def test_counts_power_and_peaks_above() -> None:
    view = modulated(shots=4)
    counts = run(view, {**FULL, "t_bin": 10e-6, "profile_units": "counts"}).data
    assert counts.unit == "events" and counts.profile.sum() == 80_000
    # 4 shots × 20,000 events over 5,000 bins: 16 per bin, modulated by 20 %.
    assert counts.spectrum.peaks[0].value == pytest.approx(16 * DEPTH, rel=0.15)
    power = run(view, {**FULL, "t_bin": 10e-6, "profile_units": "counts", "spectrum_scale": "power"}).data
    assert power.spectrum.power and t_spectrum.value_unit(power) == "(events)²"
    assert power.spectrum.peaks[0].value == pytest.approx(counts.spectrum.peaks[0].value ** 2, rel=0.05)
    above = run(view, {**FULL, "t_bin": 10e-6, "peaks_above": 2500.0}).data.spectrum
    assert all(peak.frequency > 2500 for peak in above.peaks)
    none = run(view, {**FULL, "t_bin": 10e-6, "peaks": 0}).data.spectrum
    assert none.peaks == () and none.threshold == 0


def test_a_cloud_envelope_doesnt_hide_the_modulation() -> None:
    data = run(modulated(shots=10, envelope=0.01), {**FULL, "t_bin": 10e-6, "peaks_above": 500.0}).data
    assert abs(data.spectrum.peaks[0].frequency - F0) <= data.spectrum.resolution


def test_automatic_bins_follow_the_data_rate() -> None:
    few = run(modulated(shots=1), FULL)
    assert few.data.automatic and len(few.data.counts) == 2_000  # 10 events per bin
    assert few.data.spectrum.nyquist == pytest.approx(20_000 / SPAN / 20, rel=1e-3)
    assert SCRIPT.describe_result("Plot", few).startswith("T bins 25 µs (auto: ~10 events per bin) · Δf 20 Hz")
    assert not few.data.capped and len(run(modulated(shots=5), FULL).data.counts) == 10_000
    many = run(modulated(shots=10), FULL)
    assert many.data.capped and len(many.data.counts) == 16_384
    assert "(auto: capped at 16,384 bins)" in SCRIPT.describe_result("Plot", many)
    assert abs(many.data.spectrum.peaks[0].frequency - F0) <= many.data.spectrum.resolution
    sparse = run(modulated(shots=1, per_shot=100), FULL)
    assert len(sparse.data.counts) == 256  # at least 256 bins
    tiny = run(modulated(shots=1, per_shot=100), {**FULL, "t_bin": 1e-12}).data
    assert len(tiny.counts) == t_spectrum.MAX_BINS and any("over 1,048,576 bins" in w for w in tiny.warnings)


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
    assert result.data.spectrum is None and SCRIPT.describe_result("Plot", result).startswith(
        "" if case == "no events in range" else "T bins" if case == "too few events" else "")


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
    assert widget.spectrum_plot.getAxis("left").labelText == "Amplitude (kHz/shot)"
    assert "Peaks: 1. 2 kHz" in widget.peaks_label.text and len(widget.labels) == len(widget.markers.getData()[0])
    assert "Δf 20 Hz, Nyquist 50 kHz" in widget.title.text
    widget.spectrum_plot.vb.setXRange(1000, 3000, padding=0)
    assert SCRIPT.update(widget, run(modulated(shots=3, seed=4), values))
    assert widget.spectrum_plot.vb.viewRange()[0] == pytest.approx([1000, 3000]) and "3 shots" in widget.title.text
    assert not SCRIPT.update(widget, run(modulated(shots=2), {**values, "spectrum_log": False}))
    assert not SCRIPT.update(widget, run(modulated(shots=2), {**values, "profile_units": "counts"}))
    assert not SCRIPT.update(widget, run(modulated(shots=1, per_shot=5), FULL))


def test_settings_line() -> None:
    view = modulated(shots=3, per_shot=20)
    values = effective(SCRIPT.parameters("Plot"), {"shots": "last N", "last_shots": 2, "t_bin": 2e-6,
                                                   "padding": 4, "window": "Hamming"})
    assert SCRIPT.describe_run("Plot", values, view) == (
        "shots 2–3 (2 of 3)", "last 2 shots · auto-crop 99 % · T bins 2 µs · Hamming window, ×4 padding · log · "
        "5 peaks")


def test_spectrum_helpers() -> None:
    # A sine of amplitude 3 on a bin, through each window: read as 3 (fft_tx's normalisation).
    step = 1e-3
    t = np.arange(1000) * step
    for window in WINDOWS:
        spectrum = amplitude_spectrum(5 + 3 * np.sin(2 * np.pi * 50 * t), step, window)
        assert spectrum.values[0] == pytest.approx(0, abs=1e-9)  # the mean is subtracted
        assert spectrum.values[50] == pytest.approx(3.0, rel=1e-6)
    odd = amplitude_spectrum(np.sin(2 * np.pi * 50 * np.arange(999) * step), step)
    assert len(odd.values) == 500 and odd.nyquist == 500
    assert padding_for(1000, 8) == (8, "") and padding_for(MAX_PADDED, 2)[0] == 1
    assert refine(np.array([1.0, 3.0, 1.0]), 1) == (0.0, 3.0) and refine(np.array([1.0, 2.0]), 0) == (0.0, 1.0)
    flat = find_spectrum_peaks(amplitude_spectrum(np.zeros(64), step), 3)
    assert flat.peaks == ()
    assert frequency_text(1250) == "1.25 kHz" and time_text(5e-8) == "50 ns" and si_text(-0.002, "m") == "−2 mm"
    assert time_text(0.00099999) == "1 ms" and si_text(float("nan"), "Hz") == "–" and si_text(0, "Hz") == "0 Hz"
    assert time_unit(0.4, 0.45) == ("ms", 1e3) and time_unit(20.0, 21.0) == ("s", 1.0)
