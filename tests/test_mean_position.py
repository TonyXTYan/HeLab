"""Mean X, Y against T (D5): per-bin means and SDs with standard errors on synthetic events
with a known slosh and width, the slosh frequency from the spectrum, bins left out, empty
and short cases, and drawing in place."""
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
from helab.analysis.results import AnalysisContext, AnalysisResult, Cancelled
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
    """Events uniform in T over SPAN, X centred on the slosh, Y on 0.5 mm, both SD SIGMA."""
    rng = np.random.default_rng(seed)
    data = {}
    for shot in range(1, shots + 1):
        t = T0 + rng.uniform(0, SPAN, per_shot)
        x = AMPLITUDE * np.sin(2 * np.pi * FREQUENCY * (t - T0)) + rng.normal(0, SIGMA, per_shot)
        y = 5e-4 + rng.normal(0, SIGMA, per_shot)
        data[shot] = np.column_stack([t, x, y])
    return view_of_shots(data)


def run(view: DatasetView, values: dict[str, Any] | None = None) -> AnalysisResult:
    context = AnalysisContext("a1", "Plot", view, effective(SCRIPT.parameters("Plot"), values),
                              SCRIPT.get_metadata().identity())
    return AnalysisResult.of(context, "completed", SCRIPT.compute("Plot", context))


FULL = {"keep_percent": 100.0}  # the whole T span, so the bins start at the first event


def test_means_and_widths_match_the_truth_within_their_standard_errors() -> None:
    data: mean_position.PositionProfile = run(sloshing(), {**FULL, "t_bin": 1e-3}).data
    assert len(data.counts) == 50 and data.width == 1e-3 and not data.automatic
    assert np.allclose(np.diff(data.edges), 1e-3)  # exactly the width set (the old GUI's were ~2×)
    assert data.edges[0] == data.box.lower[0] if data.box else False
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
    # The standard errors: SD/√n and SD/√(2(n−1)).
    assert np.allclose(y.mean_se, y.sd / np.sqrt(data.counts))
    assert np.allclose(y.sd_se, y.sd / np.sqrt(2 * (data.counts - 1)))


def test_the_spectrum_recovers_the_slosh_frequency() -> None:
    result = run(sloshing(), {**FULL, "t_bin": 0.5e-3, "spectrum": True})
    data: mean_position.PositionProfile = result.data
    x, y = data.spectra
    assert x.resolution == pytest.approx(1 / SPAN, rel=0.02) and x.nyquist == pytest.approx(1000.0)
    top = x.peaks[0]
    assert abs(top.frequency - FREQUENCY) <= x.resolution
    assert top.value == pytest.approx(2.0, rel=0.25)  # the slosh's amplitude, 2 mm (Hann's normalisation)
    assert not y.peaks or y.peaks[0].value < 0.2 * top.value
    text = SCRIPT.describe_result("Plot", result)
    assert "Δf 20 Hz" in text and "Nyquist 1 kHz" in text
    # Other windows find it too.
    for window in (NO_WINDOW, FLAT_TOP, "Hamming", "Blackman"):
        found = run(sloshing(), {**FULL, "t_bin": 0.5e-3, "spectrum": True, "window": window}).data.spectra[0]
        assert found.window == window and abs(found.peaks[0].frequency - FREQUENCY) <= found.resolution


def test_bins_with_too_few_events_are_left_out_and_counted() -> None:
    rng = np.random.default_rng(1)
    # Dense at both ends, a sparse middle: its bins are gaps.
    t = np.concatenate([rng.uniform(0.40, 0.41, 5000), rng.uniform(0.41, 0.43, 30), rng.uniform(0.43, 0.44, 5000)])
    events = np.column_stack([t, rng.normal(0, 1e-3, len(t)), rng.normal(0, 1e-3, len(t))])
    result = run(view_of_shots({1: events}), {**FULL, "t_bin": 1e-3, "min_events": 20, "spectrum": True})
    data: mean_position.PositionProfile = result.data
    gaps = int(np.count_nonzero(~data.kept))
    assert 15 <= gaps <= 20 and data.left_out == gaps
    assert np.isnan(data.traces[0].mean[~data.kept]).all() and np.isfinite(data.traces[0].mean[data.kept]).all()
    assert f"{gaps} of {len(data.counts)} bins with fewer than 20 events left out" in data.notes
    assert any("filled by straight lines for the spectrum" in note for note in data.notes)
    assert all(np.isfinite(spectrum.values).all() for spectrum in data.spectra)  # no NaN spectrum (legacy bug 5)
    assert f"{gaps} of {len(data.counts)} bins left out" in SCRIPT.describe_result("Plot", result)


def test_automatic_bins_and_odd_lengths() -> None:
    data = run(sloshing(shots=1, per_shot=5_000), FULL).data
    assert data.automatic and len(data.counts) == 50 and data.width == pytest.approx(SPAN / 50, rel=1e-3)
    assert "T bins 1 ms (auto)" in SCRIPT.describe_result("Plot", run(sloshing(shots=1, per_shot=5_000), FULL))
    odd = run(sloshing(shots=1, per_shot=5_000), {**FULL, "t_bin": SPAN / 37, "spectrum": True}).data
    assert len(odd.counts) in (37, 38) and len(odd.spectra) == 2  # odd lengths work (the old GUI's FFT crashed)
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
                "no bin full": "No T bin holds 1,000 events or more: 200 events in 10 bins of 4.9"}[case]
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
    assert "Peaks: mean X: 100 Hz" in widget.peaks_label.text
    widget.means.vb.setXRange(410, 420, padding=0)
    later = run(sloshing(shots=4, seed=6), values)
    assert SCRIPT.update(widget, later)
    assert widget.means.vb.viewRange()[0] == pytest.approx([410, 420])  # the zoom stays
    assert "4 shots" in widget.title.text
    # Another layout (no spectrum) or an empty result: drawn anew.
    assert not SCRIPT.update(widget, run(sloshing(shots=2), FULL))
    assert not SCRIPT.update(widget, run(sloshing(shots=2), {"range_mode": "manual", "t_min": 1.0, "t_max": 2.0}))
    assert isinstance(widget.spectrum.getAxis("bottom"), pg.AxisItem)


def test_settings_line() -> None:
    view = sloshing(shots=3, per_shot=10)
    values = effective(SCRIPT.parameters("Plot"), {"shots": "last N", "last_shots": 2, "t_bin": 2e-4,
                                                   "spectrum": True})
    assert SCRIPT.describe_run("Plot", values, view) == (
        "shots 2–3 (2 of 3)", "last 2 shots · auto-crop 99 % · T bins 200 µs · ≥ 10 events per bin · "
        "spectrum Hann, log")
    assert SCRIPT.describe_result("Plot", AnalysisResult.of(
        AnalysisContext("a1", "Plot", view, values, SCRIPT.get_metadata().identity()), "failed")) == ""
    assert math.isclose(mean_position.bin_width(10_000, 1.0, 0.0)[0], 0.01)
