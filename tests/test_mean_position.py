"""Mean X, Y against T (D5): per-bin means and SDs with standard errors on synthetic events
with a known slosh and width, the slosh frequency and amplitude from the spectrum, bins left
out, gaps filled or not, whole bins, the automatic width's limits, empty and short cases, the
dock's lines and record, and drawing in place."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pyqtgraph as pg
import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtWidgets import QLabel

from helab.analysis.dataset_view import DatasetView, build_view
from helab.analysis.parameters import effective
from helab.analysis.results import AnalysisContext, AnalysisResult, Cancelled, RamResults
from helab.analysis.spectrum import FLAT_TOP, NO_WINDOW
from helab.scripts.standard import mean_position
from helab.utils.folder_cache import Dataset

PATH = "/data/root/run_D5"
SCRIPT = mean_position.MeanPositionVsT()
T0, SPAN = 0.40, 0.05  # T from 400 ms over 50 ms
AMPLITUDE, FREQUENCY, SIGMA = 2e-3, 100.0, 1e-3  # X(T) = A sin(2π f (T − T0)), SD of X and Y: 1 mm


def view_of_shots(shots: dict[int, np.ndarray[Any, Any]], signature: str = "sig-d5") -> DatasetView:
    for array in shots.values():
        array.setflags(write=False)
    prints = [[shot, 100 + shot, 1_000 + shot] for shot in sorted(shots)]
    return build_view(Dataset(PATH, signature, shots, {"fingerprint": prints, "source": "merged"}, 0))


def sloshing(shots: int = 10, per_shot: int = 20_000, seed: int = 5) -> DatasetView:
    """Events uniform in T over exactly SPAN (one at each end), X centred on the slosh, Y on
    0.5 mm, both SD SIGMA."""
    rng = np.random.default_rng(seed)
    data = {}
    for shot in range(1, shots + 1):
        t = T0 + rng.uniform(0, SPAN, per_shot)
        t[0], t[-1] = T0, T0 + SPAN
        x = AMPLITUDE * np.sin(2 * np.pi * FREQUENCY * (t - T0)) + rng.normal(0, SIGMA, per_shot)
        y = 5e-4 + rng.normal(0, SIGMA, per_shot)
        data[shot] = np.column_stack([t, x, y])
    return view_of_shots(data)


def run(view: DatasetView, values: dict[str, Any] | None = None) -> AnalysisResult:
    context = AnalysisContext("a1", "Plot", view, effective(SCRIPT.parameters("Plot"), values),
                              SCRIPT.get_metadata().identity())
    data = SCRIPT.compute("Plot", context)
    return AnalysisResult.of(context, "completed", data, found=SCRIPT.result_found("Plot", data))


FULL = {"keep_percent": 100.0}  # the whole T span, so the bins start at the first event


def test_means_and_widths_match_the_truth_within_their_standard_errors() -> None:
    data: mean_position.PositionProfile = run(sloshing(), {**FULL, "t_bin": 1e-3}).data
    assert len(data.counts) == 50 and data.width == 1e-3 and not data.automatic and data.counts.sum() == 200_000
    assert np.allclose(np.diff(data.edges), 1e-3)  # exactly the width set (the old GUI's were ~2×)
    assert data.box is not None and data.edges[0] == data.box.lower[0]
    x, y = data.traces
    centres = data.centres
    truth = AMPLITUDE * np.sin(2 * np.pi * FREQUENCY * (centres - T0)) * 1e3  # mm
    # Within a bin the slosh moves the mean a little: compare with the bin's average of it.
    within = [AMPLITUDE * 1e3 * np.sin(2 * np.pi * FREQUENCY * (np.linspace(lo, lo + 1e-3, 1001) - T0))
              for lo in data.edges[:-1]]
    averaged = np.array([np.mean(slosh) for slosh in within])
    pulls = (x.mean - averaged) / x.mean_se
    assert np.mean(np.abs(pulls) < 3) > 0.95 and abs(float(np.mean(pulls))) < 0.5
    assert np.max(np.abs(x.mean - truth)) < 0.2  # mm
    # Y's mean and both SDs: 0.5 mm and 1 mm, X's widened by the slosh within its bin.
    assert np.mean(np.abs((y.mean - 0.5) / y.mean_se) < 3) > 0.95
    assert np.mean(np.abs((y.sd - 1.0) / y.sd_se) < 3) > 0.95
    widened = np.sqrt(1.0 + np.array([np.var(slosh) for slosh in within]))
    assert np.mean(np.abs((x.sd - widened) / x.sd_se) < 3) > 0.95


def test_standard_errors_match_the_scatter_of_the_estimates() -> None:
    """Not circular: across many bins (and seeds) of known truth, the estimates scatter by
    their quoted standard errors (pulls of SD 1)."""
    mean_pulls, sd_pulls = [], []
    for seed in (1, 2, 3):
        data = run(sloshing(shots=4, per_shot=10_000, seed=seed), {**FULL, "t_bin": 0.5e-3}).data
        y = data.traces[1]
        mean_pulls.append((y.mean - 0.5) / y.mean_se)
        sd_pulls.append((y.sd - 1.0) / y.sd_se)
    for pulls in (np.concatenate(mean_pulls), np.concatenate(sd_pulls)):
        assert len(pulls) == 300 and 0.85 < float(np.std(pulls)) < 1.15 and abs(float(np.mean(pulls))) < 0.2


def test_the_spectrum_recovers_the_slosh_frequency_and_amplitude() -> None:
    result = run(sloshing(), {**FULL, "t_bin": 0.5e-3, "spectrum": True})
    data: mean_position.PositionProfile = result.data
    x, y = data.spectra
    assert x.bin_spacing == pytest.approx(1 / SPAN) and x.nyquist == pytest.approx(1000.0) and x.binned
    top = x.peaks[0]
    assert abs(top.frequency - FREQUENCY) <= 0.05 * x.bin_spacing
    assert top.value == pytest.approx(2.0, rel=0.03)  # the slosh's amplitude, 2 mm
    assert not y.peaks or y.peaks[0].value < 0.1 * top.value
    text = SCRIPT.describe_result("Plot", result)
    assert "bin spacing Δf 20 Hz, resolution ≈ 30 Hz (ENBW 1.5), Nyquist 1 kHz" in text
    record = SCRIPT.result_record("Plot", result)
    assert record[0].startswith("T bins: 100 of 0.5 ms (set), 200,000 events; 0 with fewer than 10")
    assert any(line.startswith("Peaks, mean X: 100 Hz (2") for line in record)
    # The settings line's addition and the record are the result's ``found``: a released plot
    # (its data dropped) keeps both.
    released = RamResults().released(result)
    assert released.data is None and SCRIPT.describe_result("Plot", released) == text
    assert SCRIPT.result_record("Plot", released) == record
    for window in (NO_WINDOW, FLAT_TOP, "Hamming", "Blackman"):
        found = run(sloshing(), {**FULL, "t_bin": 0.5e-3, "spectrum": True, "window": window}).data.spectra[0]
        assert found.window == window and abs(found.peaks[0].frequency - FREQUENCY) <= found.bin_spacing
        assert len(found.peaks) == 1  # no sidelobe listed as a peak


def test_the_bins_averaging_is_corrected_for() -> None:
    # A fast slosh, 400 Hz in 1 ms bins (0.4 of the bin rate): the bin means hold sinc(0.4) of it.
    rng = np.random.default_rng(4)
    t = T0 + rng.uniform(0, SPAN, 400_000)
    t[0], t[-1] = T0, T0 + SPAN
    x = AMPLITUDE * np.sin(2 * np.pi * 400 * (t - T0)) + rng.normal(0, SIGMA, len(t))
    data = run(view_of_shots({1: np.column_stack([t, x, rng.normal(0, SIGMA, len(t))])}),
               {**FULL, "t_bin": 1e-3, "spectrum": True}).data
    peak = data.spectra[0].peaks[0]
    assert peak.frequency == pytest.approx(400, abs=2) and peak.value == pytest.approx(2.0, rel=0.05)
    assert np.sinc(0.4) * 2.0 < 0.8 * peak.value  # uncorrected it would read 1.51 mm


def test_bins_with_too_few_events_are_left_out_and_gaps_filled_up_to_a_fifth() -> None:
    rng = np.random.default_rng(1)
    # Dense but for a sparse 4 ms in the middle (4 of 40 bins, 10 %): filled.
    t = np.concatenate([rng.uniform(0.40, 0.418, 20_000), rng.uniform(0.418, 0.422, 20),
                        rng.uniform(0.422, 0.44, 20_000), [0.40, 0.44]])
    events = np.column_stack([t, rng.normal(0, 1e-3, len(t)), rng.normal(0, 1e-3, len(t))])
    result = run(view_of_shots({1: events}), {**FULL, "t_bin": 1e-3, "min_events": 20, "spectrum": True})
    data: mean_position.PositionProfile = result.data
    gaps = int(np.count_nonzero(~data.kept))
    assert gaps == 4 and data.left_out == 4 and len(data.counts) == 40
    assert np.isnan(data.traces[0].mean[~data.kept]).all() and np.isfinite(data.traces[0].mean[data.kept]).all()
    assert "4 of 40 bins with fewer than 20 events left out" in data.notes
    assert "4 gap bins filled by straight lines for the spectrum" in data.notes
    assert all(np.isfinite(spectrum.values).all() for spectrum in data.spectra)  # no NaN spectrum (legacy bug 5)
    assert data.spectra[0].samples == 40
    assert "4 of 40 bins left out" in SCRIPT.describe_result("Plot", result)


def test_wide_gaps_use_the_longest_stretch_or_no_spectrum() -> None:
    rng = np.random.default_rng(2)

    def clouds(first: float, second: float) -> DatasetView:
        """Two clouds, 10 ms and ``second − first`` apart, nothing between."""
        t = np.concatenate([rng.uniform(0.40, 0.40 + first, 20_000), rng.uniform(0.43, 0.43 + second, 20_000),
                            [0.40, 0.43 + second]])
        return view_of_shots({1: np.column_stack([t, rng.normal(0, 1e-3, len(t)), rng.normal(0, 1e-3, len(t))])})
    values = {**FULL, "t_bin": 1e-3, "spectrum": True}
    # Two 15 ms clouds 15 ms apart: a third of the 45 bins would be filled.
    long = run(clouds(0.015, 0.015), values).data
    assert len(long.spectra) == 2 and long.spectra[0].samples == 15
    assert any("gaps are 33 % of the traces (over 20 %): spectrum of the longest stretch without gaps, T 400.5–414.5 ms (15 bins)" in note
               for note in long.notes)
    short = run(clouds(0.005, 0.005), values).data
    assert short.spectra == ()
    assert any(note.startswith("no spectrum: gaps are") and "has 5 bins, under 8" in note for note in short.notes)


def test_whole_bins_only_and_the_automatic_widths_limits() -> None:
    data = run(sloshing(shots=1, per_shot=5_000), FULL)
    assert data.data.automatic and len(data.data.counts) == 50 and data.data.width == pytest.approx(SPAN / 50)
    assert "T bins 1 ms (auto: ~100 events per bin)" in SCRIPT.describe_result("Plot", data)
    few = run(sloshing(shots=1, per_shot=500), FULL)
    assert len(few.data.counts) == 10 and few.data.clamp == "at least"
    assert "(auto: at least 10 bins, ~50 events per bin)" in SCRIPT.describe_result("Plot", few)
    many = run(sloshing(shots=1, per_shot=200_000), FULL)
    assert len(many.data.counts) == 1000 and "(auto: at most 1,000 bins, ~200 events per bin)" in \
        SCRIPT.describe_result("Plot", many)
    # A set width that doesn't divide the range: a last, partial bin, centred on its own extent,
    # keeps its events in the traces; the spectrum's even samples leave it out.
    partial = run(sloshing(shots=1, per_shot=5_000), {**FULL, "t_bin": 3e-3, "spectrum": True}).data
    assert len(partial.counts) == 17 and partial.counts.sum() == partial.events == 5_000
    assert partial.edges[-2] == pytest.approx(T0 + 0.048) and partial.edges[-1] == pytest.approx(T0 + SPAN)
    assert partial.centres[-1] == pytest.approx(T0 + 0.049) and np.isfinite(partial.traces[0].mean[-1])
    assert "the last bin is 2 ms wide (partial): in the traces, not in the spectrum" in partial.notes
    assert partial.spectra[0].samples == 16
    wide = run(sloshing(shots=1, per_shot=5_000), {**FULL, "t_bin": 30e-3}).data
    assert wide.counts.sum() == 5_000 and len(wide.counts) == 2  # 30 ms + 20 ms: no event dropped
    wider = run(sloshing(shots=1, per_shot=5_000), {**FULL, "t_bin": 0.08}).data
    assert len(wider.counts) == 1 and wider.width == pytest.approx(SPAN)
    assert "T bin width 80 ms is wider than the range (50 ms): using one bin of the range" in wider.warnings
    odd = run(sloshing(shots=1, per_shot=5_000), {**FULL, "t_bin": SPAN / 37, "spectrum": True}).data
    assert len(odd.counts) == 37 and len(odd.spectra) == 2  # odd lengths work (the old GUI's FFT crashed)
    tiny = run(sloshing(shots=1, per_shot=5_000), {**FULL, "t_bin": 1e-9}).data
    assert len(tiny.counts) == mean_position.MAX_BINS and any("over 100,000 bins" in w for w in tiny.warnings)


@pytest.mark.parametrize("case", ["no events in range", "no bin full", "too short for a spectrum"])
def test_empty_and_short_cases_say_why(qtbot: QtBot, case: str) -> None:
    view = sloshing(shots=1, per_shot=200)
    values: dict[str, Any] = {"range_mode": "manual", "t_min": 1.0, "t_max": 2.0}
    if case == "no bin full":
        values = {**FULL, "min_events": 1000}
    elif case == "too short for a spectrum":
        values = {**FULL, "t_bin": SPAN / 5, "spectrum": True}
    result = run(view, values)
    widget = SCRIPT.render(result)
    qtbot.addWidget(widget)
    if case == "too short for a spectrum":
        assert isinstance(widget, mean_position.PositionPlot) and not result.data.spectra
        assert "no spectrum: the traces have 5 bins" in widget.peaks_label.text
        return
    assert isinstance(widget, QLabel) and widget.objectName() == "plot_empty"
    expected = {"no events in range": "None of the 200 events in the chosen shots is inside the view range",
                "no bin full": "No T bin holds 1,000 events or more: 200 events in 10 bins of 5 ms"}[case]
    assert widget.text().startswith(expected)


def test_a_single_event_and_cancellation() -> None:
    one = run(view_of_shots({1: np.array([[0.4, 0.0, 0.0]])}), {"min_events": 2}).data
    assert one.events == 1 and not one.kept.any() and mean_position.empty_reason(one).startswith("No T bin holds")
    context = AnalysisContext("a1", "Plot", sloshing(shots=1), effective(SCRIPT.parameters("Plot"), FULL),
                              SCRIPT.get_metadata().identity())
    context.cancel_event.set()
    with pytest.raises(Cancelled):
        SCRIPT.compute("Plot", context)


def test_drawn_in_mm_and_ms_and_updated_in_place(qtbot: QtBot) -> None:
    values = {**FULL, "t_bin": 1e-3, "spectrum": True}
    first = run(sloshing(shots=2), values)
    widget = SCRIPT.render(first)
    qtbot.addWidget(widget)
    assert isinstance(widget, mean_position.PositionPlot)
    assert widget.means.getAxis("bottom").labelText == "T (ms)" and widget.means.getAxis("left").labelText == "Mean (mm)"
    xs, _ = widget.curves["X", "mean"].getData()
    assert xs[0] == pytest.approx(400.5, abs=0.1)  # ms
    assert "Peaks: mean X: 100" in widget.peaks_label.text
    widget.means.vb.setXRange(410, 420, padding=0)
    later = run(sloshing(shots=4, seed=6), values)
    assert SCRIPT.update(widget, later)
    assert widget.means.vb.viewRange()[0] == pytest.approx([410, 420])  # the zoom stays
    assert "4 shots" in widget.title.text
    # Another layout (no spectrum) or an empty result: drawn anew.
    assert not SCRIPT.update(widget, run(sloshing(shots=2), FULL))
    assert not SCRIPT.update(widget, run(sloshing(shots=2), {"range_mode": "manual", "t_min": 1.0, "t_max": 2.0}))
    assert isinstance(widget.spectrum.getAxis("bottom"), pg.AxisItem)


def test_settings_line_and_record_only_for_completed_runs() -> None:
    view = sloshing(shots=3, per_shot=10)
    values = effective(SCRIPT.parameters("Plot"), {"shots": "last N", "last_shots": 2, "t_bin": 2e-4,
                                                   "spectrum": True})
    assert SCRIPT.describe_run("Plot", values, view) == (
        "shots 2–3 (2 of 3)", "last 2 shots · auto-crop 99 % · T bins 0.2 ms · ≥ 10 events per bin · "
        "spectrum Hann, log")
    failed = AnalysisResult.of(AnalysisContext("a1", "Plot", view, values, SCRIPT.get_metadata().identity()), "failed")
    assert SCRIPT.describe_result("Plot", failed) == "" and SCRIPT.result_record("Plot", failed) == []
    assert math.isclose(mean_position.bin_width(10_000, 1.0, 0.0)[0], 0.01)
