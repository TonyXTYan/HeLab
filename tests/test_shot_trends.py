"""Shot trends (D2): per-shot counts in the View range, centres and widths (Gaussian fits and
threshold edges), moving mean ± SD, low-count flags, the opt-in low-count notification during
Live through ``helab.utils.events``, and per-shot reuse across Live's revisions."""
from __future__ import annotations

import math
import time
from types import SimpleNamespace
from typing import Any, Iterator, List, Optional, cast

import numpy as np
import pyqtgraph as pg
import pytest
from PyQt6 import sip
from PyQt6.QtCore import QObject
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QDockWidget, QLabel, QMainWindow, QTabWidget
from pytestqt.qtbot import QtBot

from helab.analysis import trends
from helab.analysis.dataset_view import DatasetView, build_view, revise
from helab.analysis.follow import LiveFeed, LivePolicy
from helab.analysis.parameter_tree import parameter_of
from helab.analysis.parameters import effective
from helab.analysis.plot_axes import GroupedAxis
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.runner import AnalysisRunner
from helab.models.ScriptTreeSelector import AnalysisInstance, PlotSettingsPanel, TreePanelWidget
from helab.scripts.standard import shot_trends
from helab.scripts.standard.shot_trends import ShotTrends, Trends
from helab.utils import events
from helab.utils.folder_cache import Dataset
from helab.views.CentralHint import CentralHint
from helab.views.FolderExplorer import FolderExplorer
from helab.views.HelabMainWindow import HelabMainWindow

PATH = "/data/root/run_T"
SCRIPT = ShotTrends()
NS = 1_000_000_000
T0, SIGMA_T = 0.4, 2e-3  # s
X0, SIGMA_X = 1e-3, 3e-3  # m


def shot_events(shot: int, count: int = 4000, drift: float = 0.0, seed: int = 0) -> np.ndarray:
    """A Gaussian cloud whose T centre moves by ``drift`` s per shot and whose X width grows by 1 %
    per shot."""
    rng = np.random.default_rng(seed + shot)
    t = rng.normal(T0 + drift * shot, SIGMA_T, count)
    x = rng.normal(X0, SIGMA_X * (1 + 0.01 * shot), count)
    y = rng.normal(-X0, SIGMA_X, count)
    return np.column_stack([np.sort(t), x, y])


def dataset(data: dict[int, np.ndarray], path: str = PATH, raw: Optional[dict[int, float]] = None,
            prints: Optional[dict[int, int]] = None) -> Dataset:
    """Fingerprints (shot, size, mtime) from the shot's event count; ``prints`` overrides a size
    (a rewritten file). ``raw``: shot times of raw files, s."""
    metadata: dict[str, Any] = {
        "fingerprint": [[shot, (prints or {}).get(shot, 100 + len(array)), (1_000 + shot) * NS]
                        for shot, array in data.items()],
        "source": "updated", "loaded_at": time.time()}
    if raw:
        metadata["raw_times"] = [[shot, int(when * NS)] for shot, when in raw.items()]
    return Dataset(path, f"sig-{max(data) if data else 0}", dict(data), metadata, 0)


def context(view: DatasetView, values: Optional[dict[str, Any]] = None, owner: str = "") -> AnalysisContext:
    """A run's input; ``owner``: the plot asking ("" for none)."""
    return AnalysisContext("j1", "Plot", view, effective(SCRIPT.parameters("Plot"), values),
                           SCRIPT.get_metadata().identity(), owner=owner)


def run(view: DatasetView, values: Optional[dict[str, Any]] = None,
        cache: Optional[trends.ShotCache] = None, owner: str = "") -> Trends:
    return shot_trends.compute_trends(context(view, values, owner),
                                      cache if cache is not None else trends.ShotCache())


def result_of(view: DatasetView, values: Optional[dict[str, Any]] = None,
              cache: Optional[trends.ShotCache] = None, owner: str = "") -> AnalysisResult:
    made = context(view, values, owner)
    data = shot_trends.compute_trends(made, cache if cache is not None else trends.ShotCache())
    return AnalysisResult.of(made, "completed", data, found=SCRIPT.result_found("Plot", data))


MANUAL = {"range_mode": "manual", "t_min": 0.37, "t_max": 0.45, "x_min": -0.03, "x_max": 0.03,
          "y_min": -0.03, "y_max": 0.03}


# One shot's centre and width

def test_threshold_edges_find_the_full_width_at_the_fraction() -> None:
    edges = np.linspace(-10, 10, 2001)
    centres = (edges[:-1] + edges[1:]) / 2
    counts = 1000 * np.exp(-0.5 * ((centres - 1.5) / 2.0) ** 2)
    centre, width, failure = trends.threshold_edges(edges, counts, 0.5)
    assert failure == "" and centre == pytest.approx(1.5, abs=1e-3)
    assert width == pytest.approx(2 * math.sqrt(2 * math.log(2)) * 2.0, rel=1e-3)
    assert trends.gaussian_equivalent(width, 0.5) == pytest.approx(2.0, rel=1e-3)
    _, width_10, _ = trends.threshold_edges(edges, counts, 0.1)
    assert trends.gaussian_equivalent(width_10, 0.1) == pytest.approx(2.0, rel=1e-3)
    # A flat top reaching the range's edge: that edge is the histogram's own.
    assert trends.threshold_edges([0, 1, 2, 3], [5, 5, 0], 0.5) == pytest.approx((1.0, 2.0, ""))
    assert trends.threshold_edges([0, 1], [0], 0.5)[2] == "no counts"


def test_estimate_shot_counts_the_box_and_says_why_an_axis_has_no_estimate() -> None:
    events_ = shot_events(1, 2000)
    box = ((0.39, 0.41), (-0.02, 0.02), (-0.02, 0.02))
    found = trends.estimate_shot(events_, box, trends.FIT)
    inside = ((events_[:, 0] >= 0.39) & (events_[:, 0] <= 0.41) & (np.abs(events_[:, 1]) <= 0.02)
              & (np.abs(events_[:, 2]) <= 0.02))
    assert found.count == int(inside.sum())
    t = found.axes[0]
    assert t.ok and abs(t.centre.value - T0) < 4 * t.centre.se and t.width.se > 0
    few = trends.estimate_shot(events_[:5], box, trends.EDGES, min_events=20)
    assert few.count == 5 and all(axis.failure == "fewer than 20 events" for axis in few.axes)


# Over the shots

def test_fitted_centres_and_widths_follow_known_drifts() -> None:
    shots = {shot: shot_events(shot, drift=1e-4) for shot in range(1, 13)}
    data = run(build_view(dataset(shots)), {**MANUAL, "method": trends.FIT})
    t_centre, x_width = data.centres[0], data.widths[1]
    expected = T0 + 1e-4 * data.shots
    assert np.all(np.abs(t_centre.values - expected) < 4 * t_centre.se)
    slope = np.polyfit(data.shots, t_centre.values, 1)[0]
    assert slope == pytest.approx(1e-4, rel=0.05)
    assert np.all(np.abs(x_width.values - SIGMA_X * (1 + 0.01 * data.shots)) < 4 * x_width.se)
    assert data.failures == (0, 0, 0) and data.method == trends.FIT
    assert np.all(data.counts > 3900)  # Nearly all events lie inside the manual box.


def test_threshold_edges_follow_the_same_drifts_without_an_se() -> None:
    shots = {shot: shot_events(shot, 20_000, drift=2e-4) for shot in range(1, 9)}
    data = run(build_view(dataset(shots)), {**MANUAL, "bins": 200})
    t_centre, t_width = data.centres[0], data.widths[0]
    assert np.allclose(t_centre.values, T0 + 2e-4 * data.shots, atol=4e-4)
    fwhm = 2 * math.sqrt(2 * math.log(2)) * SIGMA_T
    assert np.allclose(t_width.values, fwhm, rtol=0.15)
    assert np.all(np.isnan(t_centre.se))
    lines = data.record_lines()
    assert lines[0].startswith("Counts in the View range: ") and any(line.startswith("Centre T: ") for line in lines)


def test_temperatures_use_the_runs_constants_and_the_widths() -> None:
    shots = {shot: shot_events(shot, 20_000) for shot in range(1, 4)}
    view = build_view(dataset(shots))
    values = {**MANUAL, "method": trends.FIT, "show_temperatures": True}
    constants = SCRIPT.run_constants("Plot", effective(SCRIPT.parameters("Plot"), values), {})
    assert constants is not None
    made = AnalysisContext("j", "Plot", view, effective(SCRIPT.parameters("Plot"), values),
                           SCRIPT.get_metadata().identity(), resolved_constants=constants)
    data = shot_trends.compute_trends(made, trends.ShotCache())
    sigma_v = constants.g * data.widths[0].values
    assert np.allclose(data.temperatures[0].values, constants.mass * sigma_v ** 2 / constants.k_B)
    assert data.constants is constants and "constants" in data.record()
    assert SCRIPT.run_constants("Plot", effective(SCRIPT.parameters("Plot"), MANUAL), {}) is None
    assert run(view, MANUAL).temperatures == ()


def test_moving_mean_and_sd_trail_the_window_and_skip_missing_values() -> None:
    values = np.array([1.0, 2.0, np.nan, 4.0, 8.0, 16.0])
    mean, sd = trends.moving_stats(values, 3)
    for index in range(len(values)):
        window = values[max(0, index - 2):index + 1]
        window = window[np.isfinite(window)]
        assert mean[index] == pytest.approx(window.mean())
        if len(window) > 1:
            assert sd[index] == pytest.approx(window.std(ddof=1))
        else:
            assert math.isnan(sd[index])
    # Offsets keep a large value's small spread exact.
    big = 20_450.123 + np.array([0.0, 1e-6, 2e-6, 3e-6])
    assert trends.moving_stats(big, 4)[1][-1] == pytest.approx(np.std(big, ddof=1), rel=1e-6)
    assert [len(part) for part in trends.moving_stats([], 5)] == [0, 0]


@pytest.mark.parametrize("absolute, fraction, low", [
    (None, None, []),
    (50, None, [4]),
    (None, 0.5, [2]),
    (50, 0.5, [2, 4]),
])
def test_low_count_rules_flag_shots_by_either_or_both(absolute: Optional[int], fraction: Optional[float],
                                                      low: List[int]) -> None:
    """Shot 2 (80) is below half of the shot before (200) but not below 50; shot 4 (40) is below 50
    but not below half of the shot before (60). Window 1: the reference is the previous shot."""
    counts = np.array([200, 200, 80, 60, 40, 200])
    flags = trends.low_flags(counts, absolute, fraction, window=1)
    assert np.flatnonzero(flags.low).tolist() == low and flags.count == len(low)
    assert flags.below_count.tolist() == ([False, False, False, False, True, False] if absolute else [False] * 6)
    assert flags.below_fraction.tolist() == ([False, False, True, False, False, False] if fraction else [False] * 6)
    assert math.isnan(flags.reference[0]) and flags.reference[3] == 80
    # The reference is the mean of the window's shots before, the shot itself left out.
    assert trends.previous_means(counts, 3).tolist()[1:] == [200, 200, pytest.approx(160), pytest.approx(340 / 3),
                                                             60]
    if low:
        assert flags.why(low[-1])


def test_low_shots_are_flagged_in_the_data_and_record() -> None:
    shots = {shot: shot_events(shot, 30 if shot == 4 else 400) for shot in range(1, 7)}
    data = run(build_view(dataset(shots)), {**MANUAL, "window": 3})
    assert data.shots[data.low.low].tolist() == [4]
    assert data.low.below_count.tolist()[3] and data.low.below_fraction.tolist()[3]
    record = data.record()
    assert record["low"] == {"rules": "fewer than 50 events or below 50 % of the last 3 shots' mean",
                             "count": 1, "shots": [4]}
    off = run(build_view(dataset(shots)), {**MANUAL, "low_absolute": False, "low_relative": False})
    assert off.low.count == 0 and off.low.rules_text() == ""


# Per-shot reuse

def test_live_revisions_estimate_only_their_new_or_changed_shots() -> None:
    cache = trends.ShotCache()
    shots = {shot: shot_events(shot, 500) for shot in range(1, 11)}
    first = build_view(dataset(shots))
    values = {"method": trends.FIT}  # auto-crop: the plot's rounded-out range stays put
    assert run(first, values, cache, "plot-1").computed == 10
    later = revise(first, dataset({**shots, 11: shot_events(11, 500)}))
    data = run(later, values, cache, "plot-1")
    assert later.revision == 2 and data.computed == 1 and data.reused == 10
    assert data.record()["computed"] == 1
    # A rewritten shot (new fingerprint) is estimated again; other settings are other results.
    changed = revise(later, dataset({**shots, 11: shot_events(11, 500)}, prints={5: 999}))
    assert run(changed, values, cache, "plot-1").computed == 1
    assert run(changed, {**values, "min_events": 30}, cache, "plot-1").computed == 11
    small = trends.ShotCache(limit=3)
    run(first, values, small)
    assert len(small) == 3
    # Closing the folder's last plot drops its estimates; another plot keeps them until it closes.
    run(changed, values, cache, "plot-2")
    cache.plot_closed("plot-1")
    assert len(cache) > 0
    cache.plot_closed("plot-2")
    assert len(cache) == 0


def test_a_kept_box_is_one_plots_and_its_reuse_key_says_so() -> None:
    """Plot B's box doesn't depend on plot A having run; one plot keeps its own box across Live
    revisions, and the reuse key covers the box (it may come from an earlier run)."""
    view = build_view(dataset({shot: shot_events(shot, 400, drift=2e-4) for shot in range(1, 21)}))
    last = {"shots": "last N", "last_shots": 12}
    shared = trends.ShotCache()
    fresh = result_of(view, last, trends.ShotCache(), "B")
    result_of(view, {}, shared, "A")
    after_a = result_of(view, last, shared, "B")
    assert after_a.data.box == fresh.data.box and after_a.reuse_key() == fresh.reuse_key()
    assert fresh.reuse_key()["found"] == {"box": [list(bounds) for bounds in fresh.data.box]}
    # The same plot with other Shots settings finds its box again.
    other = result_of(view, {"shots": "last N", "last_shots": 5}, shared, "B")
    assert "kept" not in " ".join(other.data.notes)
    again = result_of(view, last, shared, "B")
    assert again.data.box == fresh.data.box
    assert "kept from an earlier run of this plot" in " ".join(again.data.notes)
    # A run no plot asked for keeps nothing.
    assert "kept" not in " ".join(result_of(view, last, shared).data.notes)


def test_snapped_ranges_round_out_to_a_nice_step() -> None:
    assert trends.nice_step(0.0042) == pytest.approx(0.002) and trends.nice_step(7.0) == 5.0
    low, high = trends.snapped(0.3912, 0.4088)  # steps of 0.5 ms, one more each side
    assert (low, high) == pytest.approx((0.3905, 0.4095))
    assert trends.snapped(0.39121, 0.40879) == (low, high)
    assert trends.snapped(1.0, 1.0) == (1.0, 1.0)
    cache = trends.ShotCache()
    found, kept = cache.stable_range("k", 0.3912, 0.4088)
    assert found == pytest.approx((0.3905, 0.4095)) and not kept
    assert cache.stable_range("k", 0.3907, 0.4093) == (found, True)
    assert cache.stable_range("k", 0.3915, 0.4100)[1] is False  # Outside: found again.
    assert cache.stable_range("k", 0.399, 0.401)[1] is False  # Far narrower: found again.


def point_data(panel: shot_trends.Panel) -> Any:
    """A panel's drawn points (ScatterPlotItem's record array of x, y, symbol, brush…)."""
    return cast(Any, panel.points).data


# Shot times

def test_shot_time_axis_uses_raw_times_and_marks_fallbacks(qtbot: QtBot) -> None:
    shots = {shot: shot_events(shot, 300) for shot in range(1, 5)}
    raw = {1: 1_700_000_010.0, 2: 1_700_000_020.0, 4: 1_700_000_040.0}
    view = build_view(dataset(shots, raw=raw))
    result = result_of(view, {"x_axis": shot_trends.SHOT_TIME})
    data: Trends = result.data
    assert data.times.tolist() == [1_700_000_010.0, 1_700_000_020.0, 1_003.0, 1_700_000_040.0]
    assert data.fallback.tolist() == [False, False, True, False] and data.fallbacks == 1
    widget = SCRIPT.render(result)
    qtbot.addWidget(widget)
    assert isinstance(widget, shot_trends.TrendsWidget)
    assert isinstance(widget.counts_plot.getAxis("bottom"), pg.DateAxisItem)
    assert "1 TXY time (no raw file)" in widget.title.text
    symbols = point_data(widget.panels[0][0])["symbol"].tolist()
    assert symbols == ["o", "o", "t", "o"]
    used, settings = SCRIPT.describe_run("Plot", result.parameters, view)
    assert "⚠ 1 TXY time (no raw file)" in used and "against shot time" in settings


# Empty, one shot, drawing

def test_empty_and_one_shot_views(qtbot: QtBot) -> None:
    empty = SCRIPT.render(result_of(build_view(dataset({}))))
    qtbot.addWidget(empty)
    assert isinstance(empty, QLabel) and empty.text() == "No shots yet"
    no_events = SCRIPT.render(result_of(build_view(dataset({1: np.empty((0, 3))}))))
    qtbot.addWidget(no_events)
    assert isinstance(no_events, QLabel) and no_events.text() == "No events in the chosen shots"
    one = result_of(build_view(dataset({7: shot_events(7, 300)})))
    data: Trends = one.data
    assert data.shots.tolist() == [7] and math.isnan(data.counts_series.sd[0])
    assert data.counts_series.mean[0] == data.counts[0]
    widget = SCRIPT.render(one)
    qtbot.addWidget(widget)
    assert isinstance(widget, shot_trends.TrendsWidget)


def test_axes_are_in_ms_and_mm_with_grouped_ticks_and_updates_keep_the_plots(qtbot: QtBot) -> None:
    shots = {shot: shot_events(shot, 500) for shot in range(1, 6)}
    view = build_view(dataset(shots))
    result = result_of(view, {"show_temperatures": True})
    widget = SCRIPT.render(result)
    qtbot.addWidget(widget)
    assert isinstance(widget, shot_trends.TrendsWidget)
    labels = {(quantity, axis): panel.plot.getAxis("left").labelText for panel, quantity, axis in widget.panels}
    assert labels[("centres", 0)] == "Centre T (ms)" and labels[("centres", 1)] == "Centre X (mm)"
    assert labels[("widths", 2)] == "Width, full width at 50 %, Y (mm)" and labels[("temperatures", 0)].startswith("Temperature from T")
    left = widget.panels[1][0].plot.getAxis("left")
    bottom = widget.counts_plot.getAxis("bottom")
    assert isinstance(left, GroupedAxis) and isinstance(bottom, GroupedAxis)
    assert left.tickStrings([20_400.0, 20_450.5], 1.0, 0.5) == ["20,400.0", "20,450.5"]
    points = point_data(widget.panels[1][0])["y"]
    assert np.allclose(sorted(points), sorted(result.data.centres[0].values * 1e3))  # ms
    temperature_axis = next(panel.plot.getAxis("left") for panel, quantity, _ in widget.panels
                            if quantity == "temperatures")
    assert temperature_axis.labelUnits == "K" and temperature_axis.autoSIPrefix  # µK, nK as the values need
    # Any x change in one plot (zoom, pan, auto range) is every plot's (narrow ones under the wide one).
    widget.counts_plot.setXRange(2.0, 4.0, padding=0)
    for panel, _, _ in widget.panels:
        assert panel.plot.vb.viewRange()[0] == pytest.approx([2.0, 4.0])
    assert "mean ± SD of the last 100 shots" in widget.key_label.text
    later = result_of(revise(view, dataset({**shots, 6: shot_events(6, 500)})), {"show_temperatures": True})
    assert SCRIPT.update(widget, later) and len(point_data(widget.panels[0][0])) == 6
    other = result_of(view, {"method": trends.FIT})
    assert not SCRIPT.update(widget, other)  # Other panels and labels: drawn anew.


# Notifications

class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def deliver(self, title: str, message: str) -> str:
        self.sent.append((title, message))
        return "fake"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def notifier() -> Iterator[tuple[FakeNotifier, Clock]]:
    """A hub with a fake notifier and clock; Live feeds the test made stop watching at its end."""
    fake, clock = FakeNotifier(), Clock()
    events.reset(fake, clock)
    yield fake, clock
    for feed in list(events.hub()._feeds):
        for path in list(feed.paths()):
            feed.stop(path)
    events.reset()


NOTIFY = {"notify_low": True, "window": 5}


def live_views(low_last: bool = True, path: str = PATH) -> tuple[DatasetView, DatasetView]:
    shots = {shot: shot_events(shot, 400) for shot in range(1, 6)}
    first = build_view(dataset(shots, path))
    newest = shot_events(6, 10 if low_last else 400)
    return first, revise(first, dataset({**shots, 6: newest}, path))


def test_a_low_newest_shot_live_added_notifies_once(qtbot: QtBot, notifier: tuple[FakeNotifier, Clock]) -> None:
    fake, _ = notifier
    feed = LiveFeed()
    first, later = live_views(path=PATH)
    # Live doesn't watch the folder: a newer revision drawn notifies nothing.
    assert shot_trends.notify_low(result_of(first, NOTIFY, owner="p0")) is None
    assert shot_trends.notify_low(result_of(later, NOTIFY, owner="p0")) is None
    feed.publish(dataset({shot: np.asarray(later.shots[shot]) for shot in later.shots}))
    assert events.hub().is_live(PATH)
    # A plot's first drawing (opened during Live) notifies nothing, nor does a run with no plot.
    result = result_of(later, NOTIFY, owner="p1")
    assert shot_trends.notify_low(result) is None
    assert shot_trends.notify_low(result_of(later, NOTIFY)) is None
    assert shot_trends.notify_low(result_of(first, NOTIFY, owner="p2")) is None  # p2 drew revision 1
    result = result_of(later, NOTIFY, owner="p2")
    event = shot_trends.notify_low(result)
    assert event is not None and event.shown and event.kind == events.LOW_COUNTS
    ((title, message),) = fake.sent
    assert title == "HeLab: low counts" and message.startswith(
        "Shot 6 of run_T: 10 events in the View range (below 50; below 50 % of the last 5 shots' mean (39")
    assert shot_trends.notify_low(result) is None and len(fake.sent) == 1  # The same revision again.
    # Once per shot (another plot), notifications off, or a newest shot that isn't low.
    shot_trends.notify_low(result_of(first, NOTIFY, owner="p3"))
    assert shot_trends.notify_low(result_of(later, NOTIFY, owner="p3")) is None and len(fake.sent) == 1
    shot_trends.notify_low(result_of(first, {"window": 5}, owner="p4"))
    assert shot_trends.notify_low(result_of(later, {"window": 5}, owner="p4")) is None
    calm_first, calm = live_views(low_last=False)
    shot_trends.notify_low(result_of(calm_first, NOTIFY, owner="p5"))
    assert shot_trends.notify_low(result_of(calm, NOTIFY, owner="p5")) is None
    SCRIPT.plot_closed("Plot", "p2", PATH)
    assert "p2" not in shot_trends._drawn
    feed.stop(PATH)
    assert not events.hub().is_live(PATH)
    assert len(fake.sent) == 1


def test_low_count_notifications_are_rate_limited_per_folder(notifier: tuple[FakeNotifier, Clock]) -> None:
    fake, clock = notifier
    feed = LiveFeed()
    path = "/data/root/run_rate"
    feed._latest[path] = cast(DatasetView, None)  # Live watches the folder (its views aren't needed).
    hooked: list[events.Event] = []
    remove = events.hub().add_hook(hooked.append)
    shots = {shot: shot_events(shot, 400) for shot in range(1, 6)}
    view = build_view(dataset(shots, path))
    shot_trends.notify_low(result_of(view, NOTIFY, owner="rate"))
    for shot in (6, 7, 8):
        shots[shot] = shot_events(shot, 10)
        view = revise(view, dataset(dict(shots), path))
        shot_trends.notify_low(result_of(view, NOTIFY, owner="rate"))
        clock.now += 10
    assert len(fake.sent) == 1 and [event.shown for event in hooked] == [True, False, False]
    clock.now += 60
    shots[9] = shot_events(9, 10)
    shot_trends.notify_low(result_of(revise(view, dataset(dict(shots), path)), NOTIFY, owner="rate"))
    assert len(fake.sent) == 2 and fake.sent[1][1].endswith("(2 more since the last notification)")
    remove()
    assert events.hub().history[-1].data["delivered"] == "fake"
    feed.stop(path)


def test_events_without_a_tray_go_to_the_status_sink_and_the_log(notifier: tuple[FakeNotifier, Clock]) -> None:
    desktop = events.DesktopNotifier()
    shown: list[str] = []

    class Window(QObject):
        def show_status_notice(self, text: str, seconds: float = 10.0) -> None:
            shown.append(text)

    window = Window()
    desktop.set_status_sink(window.show_status_notice)
    assert desktop.deliver("HeLab: low counts", "Shot 6") == "status"  # Offscreen Qt has no tray.
    assert shown == ["HeLab: low counts: Shot 6"]
    del window  # Held weakly: the window can go.
    assert desktop.deliver("HeLab", "again") == "log"
    hub = events.hub()
    failing: list[events.Event] = []

    def broken(event: events.Event) -> None:
        failing.append(event)
        raise RuntimeError("hook")

    hub.add_hook(broken)
    assert hub.notify("custom", "x") is not None and len(failing) == 1  # A broken hook breaks nothing.


def test_live_errors_go_through_the_event_hub(notifier: tuple[FakeNotifier, Clock]) -> None:
    hooked: list[events.Event] = []
    events.hub().add_hook(hooked.append)
    stopped: list[bool] = []
    tab = SimpleNamespace(_live_timer=SimpleNamespace(stop=lambda: stopped.append(True)),
                          _live_changed=lambda: None)
    session = SimpleNamespace(path=PATH, error="")
    FolderExplorer._live_halt(cast(FolderExplorer, tab), cast(Any, session), "the drive went away")
    assert session.error == "the drive went away" and stopped == [True]
    (event,) = hooked
    assert event.kind == events.LIVE_ERROR and event.data["path"] == PATH and not event.desktop
    assert notifier[0].sent == []  # Recorded for hooks only: no desktop notification.


# A plot following Live

class Window(HelabMainWindow):
    """The main window's plot-dock parts and the Live feed (as tests/test_live_plots.py's)."""

    def __init__(self) -> None:
        QMainWindow.__init__(self)
        self.middle_mainwindow = QMainWindow()
        self.central_placeholder = CentralHint("Select a data folder to begin")
        self.middle_mainwindow.setCentralWidget(self.central_placeholder)
        self.dock_widgets: List[QDockWidget] = []
        self.tab_widget = QTabWidget()  # type: ignore[assignment]
        self.panel_right_top_plot_settings = PlotSettingsPanel(self)
        self.live_feed = LiveFeed(self)
        self.view: Optional[DatasetView] = None

    def current_dataset_view(self) -> DatasetView | None:
        return self.view

    def show_status_notice(self, text: str, seconds: float = 10.0) -> None:
        pass

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        QMainWindow.closeEvent(self, a0)


@pytest.fixture
def window(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> Iterator[Window]:
    runner = AnalysisRunner()
    monkeypatch.setattr("helab.models.ScriptTreeSelector.get_analysis_runner", lambda: runner)
    made = Window()
    qtbot.addWidget(made)
    yield made
    made.close_plots()
    if not sip.isdeleted(made.middle_mainwindow):
        made.middle_mainwindow.close()
        made.middle_mainwindow.deleteLater()
    runner.stop()


def test_a_plot_following_live_notifies_once_for_a_low_new_shot(
        window: Window, qtbot: QtBot, notifier: tuple[FakeNotifier, Clock]) -> None:
    fake, _ = notifier
    path = "/data/root/run_window"
    shots = {shot: shot_events(shot, 400) for shot in range(1, 6)}
    window.view = window.live_feed.publish(dataset(dict(shots), path))
    panel = TreePanelWidget(window)
    qtbot.addWidget(panel)
    instance = panel.run_analysis(SCRIPT.get_metadata(), SCRIPT, "Plot")
    assert isinstance(instance, AnalysisInstance)
    qtbot.waitUntil(lambda: instance.shown is not None, timeout=10_000)
    assert instance.parameter_root is not None
    parameter_of(instance.parameter_root, shot_trends.NOTIFY).setValue(True)
    instance.run()
    qtbot.waitUntil(lambda: instance.shown is not None and instance.shown.parameters["notify_low"], timeout=10_000)
    assert fake.sent == []  # The shots shown when it started are never notified.
    shots[6] = shot_events(6, 10)
    window.live_feed.publish(dataset(dict(shots), path))
    qtbot.waitUntil(lambda: instance.shown is not None and instance.shown.input.revision == 2, timeout=10_000)
    assert len(fake.sent) == 1 and fake.sent[0][1].startswith("Shot 6 of run_window: 10 events")
    instance.run()  # Run again on the same shots: no second notification.
    qtbot.wait(300)
    assert len(fake.sent) == 1
    assert instance.shown is not None and instance.shown.owner == instance.instance_id
    assert instance.instance_id in shot_trends._drawn
    instance.close()  # plot_closed: what the plot kept goes.
    assert instance.instance_id not in shot_trends._drawn
    window.live_feed.stop(path)


def test_registration_and_live_policy() -> None:
    from helab.scripts import standard
    assert shot_trends in standard.MODULES
    metadata = SCRIPT.get_metadata()
    assert (metadata.name, metadata.analysis_id, metadata.version) == ("Shot trends", "helab.shot_trends", "1")
    assert SCRIPT.live_policy("Plot") == LivePolicy()
    assert SCRIPT.parameter_warnings("Plot", {"notify_low": True}) == [
        "Notify during Live is on but no low-count rule is: nothing is notified"]


def test_the_tray_icon_goes_when_live_watches_no_folder(notifier: tuple[FakeNotifier, Clock]) -> None:
    hidden: list[bool] = []

    class Tray:
        def hide(self) -> None:
            hidden.append(True)

    desktop = events.hub().desktop
    desktop._tray = Tray()
    first, second = LiveFeed(), LiveFeed()
    first._latest["/a"] = cast(DatasetView, object())
    second._latest["/b"] = cast(DatasetView, object())
    first.stop("/a")
    assert hidden == []  # Live still watches /b.
    second.stop("/b")
    assert hidden == [True]

    class Gone:
        def hide(self) -> None:
            raise RuntimeError("wrapped C/C++ object has been deleted")

    desktop._tray = Gone()
    desktop.hide()
    assert desktop._tray is None


def test_constants_show_only_with_temperatures() -> None:
    sources = [spec for spec in SCRIPT.parameters("Plot") if spec.name.startswith("const.") and
               spec.name.endswith(".from")]
    assert sources and all(spec.when == ("show_temperatures", "True") for spec in sources)
    assert SCRIPT.constant_keys("Plot") == shot_trends.CONSTANT_KEYS


def test_a_reset_hub_skips_feeds_whose_qt_object_is_gone(notifier: tuple[FakeNotifier, Clock]) -> None:
    """A window that closed leaves its LiveFeed's wrapper behind: a fresh hub doesn't watch it."""
    gone = LiveFeed()
    sip.delete(gone)
    hub = events.reset(*notifier)
    assert gone not in set(hub._feeds) and not hub.is_live(PATH)
