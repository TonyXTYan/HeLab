"""Plot titles that fit their plot and say warnings the same way: every bundled plot stays inside
a 560 px dock (titles wrap; no axis pushed out), warnings and notes are amber with the app's one
``AMBER``, titles are escaped, the T spectrum's no-peak line names the amplitude unit it is
thresholded in, and Counts per shot and Shot times mark the newest shot."""
from __future__ import annotations

from typing import Any, cast

import numpy as np
import pyqtgraph as pg
import pytest
from PyQt6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from helab.analysis import plot_text
from helab.analysis.dataset_view import DatasetView, build_view
from helab.analysis.parameters import effective
from helab.analysis.plot_text import AMBER, WrapLabel, line_html, notes_html, short_note
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.scripts.base import DatasetAnalysis
from helab.scripts.dld import (basic_plots, correlations_plot, density_images, mean_position, release_time,
                                    shot_times, t_spectrum, transfer_fractions, velocity_distributions)
from helab.utils import colours
from helab.utils.folder_cache import Dataset

WIDTH = 560
PATH = "/Volumes/data/2026/20261020_halo_scan_with_a_long_folder_name/run_042_<b>&"
REVERSED_X = {"range_mode": "manual", "x_min": 0.01, "x_max": -0.01}  # A warning: min > max.


def halo_view() -> DatasetView:
    """40 shots of a cloud on a broad background (fits that leave notes), with raw times but
    for three shots (TXY times: an amber warning in Shot times)."""
    rng = np.random.default_rng(1)
    shots, raw = {}, []
    for shot in range(1, 41):
        n = 1500
        core = n // 3
        t = np.concatenate([rng.normal(0.4165, 0.0006, core), rng.normal(0.4165, 0.004, n - core)])
        x = np.concatenate([rng.normal(0.0005, 0.0004, core), rng.normal(0.0005, 0.004, n - core)])
        y = np.concatenate([rng.normal(-0.001, 0.0004, core), rng.normal(-0.001, 0.004, n - core)])
        events = np.column_stack([t, x, y])
        events.setflags(write=False)
        shots[shot] = events
        if shot not in (7, 8, 9):
            raw.append([shot, int((1_700_000_000 + 12 * shot) * 1e9)])
    prints = [[shot, 100 + shot, int(1_700_003_600 * 1e9)] for shot in sorted(shots)]
    return build_view(Dataset(PATH, "sig-text", shots, {"fingerprint": prints, "source": "merged",
                                                       "raw_times": raw}, 0))


def run(script: DatasetAnalysis, view: DatasetView, values: dict[str, Any] | None = None) -> AnalysisResult:
    context = AnalysisContext("a1", "Plot", view, effective(script.parameters("Plot"), values or {}),
                              script.get_metadata().identity())
    data = script.compute("Plot", context)
    return AnalysisResult.of(context, "completed", data, found=script.result_found("Plot", data))


def shown(qtbot: QtBot, widget: QWidget, width: int = WIDTH, height: int = 900) -> Any:
    qtbot.addWidget(widget)
    widget.resize(width, height)
    widget.show()
    qtbot.wait(50)  # Wrapping asks the layout again; its refit runs on a zero timer.
    return widget


def graphics(widget: QWidget) -> Any:
    """The pyqtgraph view of a plot widget (itself, or the one inside it)."""
    return widget if isinstance(widget, pg.GraphicsView) else widget.findChild(pg.GraphicsView)


PLOTS: list[tuple[str, DatasetAnalysis, dict[str, Any]]] = [
    ("counts", basic_plots.CountsPerShot(), {"highlight_newest": True}),
    ("histograms", basic_plots.TxyHistograms(),
     {"fit_t": True, "fit_x": True, "fit_y": True, "units": "rate per shot", "smooth": True,
      "highlight_newest": True}),
    ("histograms log", basic_plots.TxyHistograms(), {"log_y": True, "highlight_newest": True, "fit_t": True}),
    ("histograms BEC", basic_plots.TxyHistograms(),
     {"fit_t": True, "fit_x": True, "fit_x_model": "Bimodal TF² + Bose g_5/2", "fit_y": True,
      "fit_y_model": "Bimodal TF^3/2 + Gaussian", "bec_properties": True}),
    ("density", density_images.DensityImages(), {**REVERSED_X, "projection": "XT", "colour_scale": "log",
                                                 "highlight_newest": True}),
    ("mean position", mean_position.MeanPositionVsT(), {"spectrum": True}),
    ("T spectrum", t_spectrum.TProfileSpectrum(), {"spectrum_scale": "power", "padding": 4}),
    ("shot times", shot_times.ShotTimesPlot(), {"highlight_newest": True}),
    ("transfer fractions", transfer_fractions.TransferFractions(), {}),
    ("release time", release_time.ReleaseTimePlot(), {"n_boot": 20}),
    ("velocity distributions", velocity_distributions.VelocityDistributions(),
     {"fit": True, "density": "v_x–v_z", "velocity_unit": "2ħk/m"}),
    ("correlations", correlations_plot.Correlations(), {"n_boot": 20}),
]


@pytest.mark.parametrize(("name", "script", "values"), PLOTS, ids=[name for name, _, _ in PLOTS])
def test_every_plot_fits_a_560_px_dock(qtbot: QtBot, name: str, script: DatasetAnalysis,
                                       values: dict[str, Any]) -> None:
    """Every title and every plot (its axes included) lies within the widget's width: long titles
    wrap instead of widening the layout past the dock and cutting the axes off."""
    widget = shown(qtbot, script.render(run(script, halo_view(), values)))
    view = graphics(widget)
    assert view is not None, name
    width = cast(QWidget, view.viewport()).width()
    labels = [item for item in view.scene().items() if isinstance(item, pg.LabelItem) and item.isVisible()]
    titles = [label for label in labels if isinstance(label, WrapLabel) and label.text.strip()]
    assert titles, name  # Every bundled plot titles itself with wrapping labels.
    for label in labels:
        rect = label.mapRectToScene(label.itemRect())
        assert rect.left() >= -1 and rect.right() <= width + 1, (name, label.text[:80], rect)
    plots = [item for item in view.scene().items() if isinstance(item, pg.PlotItem) and item.isVisible()]
    assert plots, name
    for item in plots:
        rect = item.sceneBoundingRect()
        assert rect.left() >= -1 and rect.right() <= width + 1, (name, rect)
        if not isinstance(item, pg.ColorBarItem):
            assert cast(Any, item).vb.width() > 100, name  # Room left for the data.
    # A title wider than the dock wraps onto more lines; at its natural width it is one line a <br>.
    long = [label for label in titles if label.natural_width() > width]
    assert all(label.itemRect().width() <= width + 1 for label in long), name


def test_a_wrapped_title_shrinks_back_when_the_dock_widens(qtbot: QtBot) -> None:
    """Narrow, the histograms' titles take more lines; widened again they take fewer, and the
    plots fill the view again (the view's top item isn't left at the taller height)."""
    script = basic_plots.TxyHistograms()
    widget = shown(qtbot, script.render(run(script, halo_view(), {"fit_t": True})), 400, 900)
    title = widget.plots[0].titleLabel
    narrow = title.itemRect().height()
    widget.resize(1400, 900)
    qtbot.waitUntil(lambda: title.itemRect().height() < narrow, timeout=5_000)
    qtbot.waitUntil(lambda: widget.ci.geometry().height() <= widget.viewport().height() + 1, timeout=5_000)


def test_one_amber_everywhere() -> None:
    from helab.views import FolderConstantsDialog, FolderExplorer, LabParametersTab
    assert plot_text.AMBER is colours.AMBER and basic_plots.NOTE_COLOUR == AMBER
    assert LabParametersTab.AMBER == AMBER and FolderExplorer.AMBER == AMBER
    assert FolderConstantsDialog.AMBER == AMBER


def test_lines_put_warnings_in_amber_and_notes_one_per_line() -> None:
    assert line_html("3 shots · <b> · ⚠ X: min > max") == (
        f'3 shots · &lt;b&gt; · <span style="color: {AMBER}">⚠ X: min &gt; max</span>')
    assert line_html("plain") == "plain"
    assert notes_html(["one", "", "two"]) == (f'<br><span style="color: {AMBER}">one</span>'
                                              f'<br><span style="color: {AMBER}">two</span>')
    assert notes_html([]) == ""
    assert short_note("did not settle in 10 rounds (moved up to 0.8 SE)") == "did not settle in 10 rounds"
    assert short_note("(only a detail)") == "(only a detail)"


@pytest.mark.parametrize("script", [density_images.DensityImages(), mean_position.MeanPositionVsT(),
                                    t_spectrum.TProfileSpectrum()], ids=lambda script: type(script).__name__)
def test_warnings_in_titles_are_amber(qtbot: QtBot, script: DatasetAnalysis) -> None:
    widget = shown(qtbot, script.render(run(script, halo_view(), REVERSED_X)))
    text = cast(Any, widget).title.text
    assert f'<span style="color: {AMBER}">⚠ X: min &gt; max' in text


def test_shot_times_title_is_escaped_with_its_warning_in_amber(qtbot: QtBot) -> None:
    script = shot_times.ShotTimesPlot()
    widget = shown(qtbot, script.render(run(script, halo_view())))
    text = widget.title.text
    assert "run_042_&lt;b&gt;&amp;" in text and "<b>&" not in text
    assert f'<span style="color: {AMBER}">⚠ 3 TXY times (no raw file)' in text


def test_histogram_fit_notes_are_short_in_the_title_and_whole_in_the_record(qtbot: QtBot) -> None:
    script = basic_plots.TxyHistograms()
    result = run(script, halo_view(), {"fit_t": True})
    fit = result.data.fits[0]
    assert fit is not None and fit.notes, "the broad background leaves a fit note"
    widget = shown(qtbot, script.render(result))
    title = widget.plots[0].titleLabel.text
    record = "\n".join(script.result_record("Plot", result))
    for note in fit.notes:
        assert note in record
        assert short_note(note) in title.replace("&#x27;", "'")


def test_t_spectrum_no_peak_line_names_the_amplitude_unit_in_power_mode(qtbot: QtBot) -> None:
    """The prominence threshold is in amplitude (Peak prominence's tip), also for power."""
    script = t_spectrum.TProfileSpectrum()
    result = run(script, halo_view(), {"spectrum_scale": "power", "peak_threshold": 1e5})
    assert result.data.spectrum is not None and not result.data.spectrum.peaks
    widget = shown(qtbot, script.render(result))
    text = widget.peaks_label.text
    assert "No peak with a prominence of" in text and "kHz per shot or more" in text and "²" not in text
    assert widget.spectrum_plot.getAxis("left").labelText == "Power (kHz² per shot²)"
    counts = run(script, halo_view(), {"spectrum_scale": "power", "peak_threshold": 1e5, "profile_units": "counts"})
    assert "events or more" in cast(Any, shown(qtbot, script.render(counts))).peaks_label.text


def test_counts_per_shot_marks_the_newest_shot(qtbot: QtBot) -> None:
    script = basic_plots.CountsPerShot()
    view = halo_view()
    plain = shown(qtbot, script.render(run(script, view)))
    assert plain.newest.xData is None or len(plain.newest.xData) == 0
    result = run(script, view, {"highlight_newest": True, "newest_colour": "magenta"})
    assert result.data.newest_shot == 40 and result.data.colour == (200, 30, 180)
    lit = shown(qtbot, script.render(result))
    assert list(lit.newest.xData) == [40] and list(lit.newest.yData) == [1500]
    assert lit.newest.opts["symbolBrush"].color().getRgb()[:3] == (200, 30, 180)
    assert lit.newest.opts["symbolSize"] == basic_plots.NEWEST_SIZE
    assert script.describe_run("Plot", result.parameters, view)[1].endswith("newest shot in magenta")
    assert script.get_metadata().version == "1"


def test_shot_times_marks_the_newest_shot_in_both_plots(qtbot: QtBot) -> None:
    script = shot_times.ShotTimesPlot()
    view = halo_view()
    plain = shown(qtbot, script.render(run(script, view)))
    assert all(item.xData is None or len(item.xData) == 0 for item in plain.newest)
    assert "newest" not in plain.key_label.text
    result = run(script, view, {"highlight_newest": True})
    assert result.data.newest_shot == 40
    lit = shown(qtbot, script.render(result))
    when = 1_700_000_000 + 12 * 40
    counts, gaps = lit.newest
    assert list(counts.xData) == [when] and list(counts.yData) == [1500]
    assert list(gaps.xData) == [when] and list(gaps.yData) == [12.0]
    assert counts.opts["symbolBrush"].color().getRgb()[:3] == (214, 39, 40)
    assert "shot 40 (newest)" in lit.key_label.text and "TXY file time" in lit.key_label.text
    assert script.get_metadata().version == "3"


def test_mean_position_record_says_the_bins_left_out_once() -> None:
    script = mean_position.MeanPositionVsT()
    result = run(script, halo_view(), {"min_events": 200})
    assert result.data.left_out
    record = script.result_record("Plot", result)
    assert sum("left out" in line and "fewer than 200 events" in line for line in record) == 1
    assert mean_position.left_out_note(result.data.left_out, len(result.data.counts), 200) in result.data.notes


@pytest.mark.parametrize(("values", "label"), [
    ({}, "Events per bin"),
    ({"colour_scale": "log", "log_decades": 4}, "Events per bin · colours log, 4 decades, values linear"),
    ({"colour_scale": "power γ", "gamma": 0.3}, "Events per bin · colours power γ 0.3, values linear"),
])
def test_the_colour_bar_says_when_only_its_colours_are_compressed(
        qtbot: QtBot, values: dict[str, Any], label: str) -> None:
    script = density_images.DensityImages()
    widget = shown(qtbot, script.render(run(script, halo_view(), values)))
    assert widget.bar.getAxis("left").labelText == label
