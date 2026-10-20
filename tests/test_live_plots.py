"""Plots following Live (L3): revisions of the watched folder reach the plots of that folder,
which rerun on the newest one as their Live settings allow, never cancelled for new data and
never queueing obsolete reruns. Live itself is simulated here by publishing datasets, as the
main window does for each dataset a Live tab shows; the last tests drive a real tab."""
from __future__ import annotations

import json
import os
import gc
import threading
import time
import weakref
from pathlib import Path
from typing import Any, Iterator, List, Optional, cast

import numpy as np
import pyqtgraph as pg
import pytest
from PyQt6 import sip
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication, QDockWidget, QLabel, QMainWindow, QTabWidget, QWidget
from pytestqt.qtbot import QtBot

from helab.analysis.dataset_view import DatasetView, build_view, revise, view_of
from helab.analysis.follow import (DELAY, EVERY, FOLLOW, Follow, LiveFeed, LivePolicy, live_specs, newer,
                                   policy_of)
from helab.analysis.parameter_tree import parameter_of
from helab.analysis.panes import PlotlyPane
from helab.analysis.parameters import ParameterSpec, effective
from helab.analysis.results import AnalysisContext, AnalysisResult, Coverage
from helab.analysis.runner import AnalysisRunner
from helab.io_helper import list_folder, live_check, load
from helab.models.ScriptTreeSelector import AnalysisDock, AnalysisInstance, PlotSettingsPanel, TreePanelWidget
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.standard import basic_plots, scatter_3d, shot_times, transfer_fractions
from helab.utils.dash_server import dash_server
from helab.utils.folder_cache import Dataset, FolderCache
from helab.utils.io_service import IORequest, IOService
from helab.views.CentralHint import CentralHint
from helab.views.FolderExplorer import FolderExplorer
from helab.views.HelabMainWindow import HelabMainWindow

PATH = "/data/root/run_L"


def revision(shots: range | list[int], path: str = PATH) -> Dataset:
    """The data a Live tab shows once it holds ``shots`` (two events each, fixed fingerprints)."""
    numbers = list(shots)
    data = {shot: np.full((2, 3), float(shot)) for shot in numbers}
    return Dataset(path, f"sig-{numbers[-1] if numbers else 0}", data, {
        "fingerprint": [[shot, 100 + shot, 1_000 + shot] for shot in numbers], "source": "updated",
        "loaded_at": time.time()}, 0)


class Gated(DatasetAnalysis):
    """Each run waits until ``go`` is set; it fails on the revisions in ``fail``."""

    def __init__(self, policy: LivePolicy = LivePolicy(), name: str = "Gated") -> None:
        self.policy, self.name = policy, name
        self.go = threading.Event()
        self.go.set()
        self.fail: set[int] = set()
        self.started: list[int] = []  # Revisions, as runs start (worker thread).
        self.started_at: list[float] = []

    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(self.name, "test", "Tests", __file__, "tests.gated", "1")

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [ParameterSpec("scale", "Scale", "int", 1, (1, 10))]

    def live_policy(self, action_name: str) -> LivePolicy:
        return self.policy

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        self.started.append(context.view.revision)
        self.started_at.append(time.monotonic())
        assert self.go.wait(10)
        if context.view.revision in self.fail:
            raise RuntimeError(f"bad rev {context.view.revision}")
        return context.view.revision, len(context.view.shots)

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        revision_, shots = result.data
        label = QLabel(f"rev {revision_} · {shots} shots", parent)
        label.setObjectName("gated_plot")
        return label


class Window(HelabMainWindow):
    """The main window's plot-dock parts and the Live feed, around an optional tab."""

    def __init__(self, explorer: Optional[FolderExplorer] = None) -> None:
        QMainWindow.__init__(self)
        self.middle_mainwindow = QMainWindow()
        self.central_placeholder = CentralHint("Select a data folder to begin")
        self.middle_mainwindow.setCentralWidget(self.central_placeholder)
        self.dock_widgets: List[QDockWidget] = []
        self.tab_widget = QTabWidget()  # type: ignore[assignment]
        self.panel_right_top_plot_settings = PlotSettingsPanel(self)
        self.live_feed = LiveFeed(self)
        self.view: Optional[DatasetView] = None  # The data a new plot runs on (else the tab's).
        if explorer is not None:
            self.tab_widget.addTab(explorer, "tab")
            explorer.liveChanged.connect(lambda: self.follow_live(explorer))
            explorer.dataLoaded.connect(lambda _: self.follow_live(explorer))

    def current_dataset_view(self) -> DatasetView | None:
        return self.view if self.view is not None else HelabMainWindow.current_dataset_view(self)

    def show_status_notice(self, text: str, seconds: float = 10.0) -> None:
        pass

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        QMainWindow.closeEvent(self, a0)


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> Iterator[AnalysisRunner]:
    """A runner of the test's own, so its job counts are this test's."""
    made = AnalysisRunner()
    monkeypatch.setattr("helab.models.ScriptTreeSelector.get_analysis_runner", lambda: made)
    yield made
    made.stop()


@pytest.fixture
def window(qtbot: QtBot, runner: AnalysisRunner) -> Iterator[Window]:
    made = Window()
    qtbot.addWidget(made)
    yield made
    made.close_plots()
    if not sip.isdeleted(made.middle_mainwindow):
        made.middle_mainwindow.close()
        made.middle_mainwindow.deleteLater()


def plot(window: Window, qtbot: QtBot, script: DatasetAnalysis) -> AnalysisInstance:
    panel = TreePanelWidget(window)
    qtbot.addWidget(panel)
    instance = panel.run_analysis(script.get_metadata(), script, "Plot")
    assert isinstance(instance, AnalysisInstance)
    return instance


def shown_revision(instance: AnalysisInstance) -> int:
    return instance.shown.input.revision if instance.shown is not None else 0


def source(instance: AnalysisInstance) -> QLabel:
    label = cast(QDockWidget, instance.dock_widget).findChild(QLabel, "plot_data_source")
    assert label is not None
    return label


def error_line(instance: AnalysisInstance) -> QLabel:
    label = cast(QDockWidget, instance.dock_widget).findChild(QLabel, "plot_error")
    assert label is not None
    return label


def results_of(runner: AnalysisRunner) -> list[AnalysisResult]:
    ended: list[AnalysisResult] = []
    runner.finished.connect(ended.append)
    return ended


def set_live(instance: AnalysisInstance, name: str, value: Any) -> None:
    assert instance.parameter_root is not None
    spec = next(spec for spec in live_specs(instance.policy) if spec.name == name)
    parameter_of(instance.parameter_root, spec).setValue(value)


# The view's revisions


def test_a_newer_dataset_of_the_folder_is_the_next_revision() -> None:
    first = view_of(revision(range(1, 3)))
    second_data = revision(range(1, 5))
    second = revise(first, second_data)
    assert second.identity == first.identity and second.revision == 2 and second.added_shots == (3, 4)
    assert second.signature == "sig-4" and first.signature == "sig-2" and second.shot_numbers == (1, 2, 3, 4)
    assert view_of(second_data) is second  # A new run on the data shown starts from this revision.
    assert second.fingerprints[4] == (4, 104, 1004)
    # The same shots again (e.g. a save's reload): no new revision.
    again = revision(range(1, 5))
    assert revise(second, again) is second
    # Shots gone: not a revision of it, but its own view.
    fewer = revision([1, 2, 3])
    other = revise(second, fewer)
    assert other.revision == 1 and other.identity != second.identity


def test_an_empty_view_has_no_events_and_gains_shots_as_revisions() -> None:
    empty = build_view(Dataset(PATH, "", {}, {"fingerprint": []}, 0))
    assert empty.shots == {} and empty.event_count == 0 and empty.events().shape == (0, 3)
    first = revise(empty, revision([1]))
    assert first.revision == 2 and first.added_shots == (1,) and first.event_count == 2


def test_the_feed_announces_each_new_revision_once_and_its_end() -> None:
    feed = LiveFeed()
    revised: list[DatasetView] = []
    ended: list[str] = []
    feed.revised.connect(revised.append)
    feed.ended.connect(ended.append)
    first = feed.publish(revision([1]))
    assert revised == [first] and feed.latest(PATH) is first
    second = feed.publish(revision([1, 2]))
    assert revised == [first, second] and second.revision == first.revision + 1
    feed.publish(revision([1, 2]))  # Same shots: nothing new.
    assert len(revised) == 2
    feed.stop(PATH)
    feed.stop(PATH)
    assert ended == [PATH] and feed.latest(PATH) is None


# Hold and coalesce, and the policy (no Qt)


def test_follow_holds_one_newest_revision_while_a_run_is_in_flight() -> None:
    views = [view_of(revision(range(1, n + 1))) for n in (1,)]
    for n in (2, 3, 4):
        views.append(revise(views[-1], revision(range(1, n + 1))))
    follow = Follow(views[0])
    follow.start(views[0])
    for view in views[1:]:
        assert follow.offer(view)
        assert follow.due(0.0) == (None, 0.0)  # Never while running.
    assert follow.pending is views[3] and follow.waiting() == 3
    assert not follow.offer(views[2])  # Older than what waits.
    follow.end(1.0)
    assert follow.due(1.0) == (views[3], 0.0)
    follow.start(views[3])
    assert follow.pending is None and follow.ran is views[3]


def test_follow_policy_every_n_shots_and_a_delay() -> None:
    base = view_of(revision([1]))
    follow = Follow(base, LivePolicy(every_shots=3, min_delay=2.0))
    follow.start(base)
    follow.end(10.0)
    two = revise(base, revision([1, 2, 3]))
    follow.offer(two)
    assert follow.waiting() == 2 and follow.due(10.0) == (None, 0.0)
    four = revise(two, revision([1, 2, 3, 4]))
    follow.offer(four)
    assert follow.due(11.0) == (None, 1.0)  # 3 new shots, but 2 s after the run hadn't passed.
    assert follow.due(12.0) == (four, 0.0)
    follow.pin()
    assert follow.pending is None and not follow.offer(revise(four, revision([1, 2, 3, 4, 5, 6, 7])))
    follow.unpin()
    assert follow.offer(revise(four, revision(range(1, 9))))


def changed(dataset: Dataset, shot: int, signature: str) -> Dataset:
    """``dataset`` loaded again with ``shot``'s file changed in place (same shot numbers)."""
    prints = [[entry[0], entry[1] + (7 if entry[0] == shot else 0), entry[2]] for entry in dataset.metadata["fingerprint"]]
    return Dataset(dataset.path, signature, dict(dataset.data), {**dataset.metadata, "fingerprint": prints}, 0)


def test_follow_counts_changed_fingerprints_and_runs_another_input_once() -> None:
    """Data loaded again before Live, with the same shot numbers but a shot changed, is another
    input: the plot runs on it once, whatever "every N" says; the same data again isn't."""
    before = revision([1, 2])
    old = view_of(before)
    follow = Follow(old, LivePolicy(every_shots=3))
    follow.start(old)
    follow.end(0.0)
    same = view_of(Dataset(PATH, "sig-again", dict(before.data), dict(before.metadata), 0))
    assert follow.offer(same) and follow.changes() == (0, 0) and follow.due(1.0) == (None, 0.0)
    loaded_again = view_of(changed(before, 2, "sig-changed"))
    assert follow.offer(loaded_again) and follow.changes() == (0, 1)
    assert follow.due(1.0) == (loaded_again, 0.0)
    # Live's next revisions of one input still wait for N new or changed shots.
    follow.start(loaded_again)
    follow.end(2.0)
    follow.offer(revise(loaded_again, changed(revision([1, 2, 3]), 2, "sig-3")))
    assert follow.changes() == (1, 0) and follow.due(3.0) == (None, 0.0)


def test_newer_compares_revisions_of_one_input_and_any_other_input() -> None:
    first = view_of(revision([1]))
    second = revise(first, revision([1, 2]))
    assert newer(second, first) and not newer(first, second) and not newer(first, first)
    assert newer(view_of(revision([1, 2], "/elsewhere")), first)


def test_live_settings_read_back_as_a_policy() -> None:
    default = LivePolicy(4, 1.5)
    specs = live_specs(default)
    assert [spec.default for spec in specs] == [True, 4, 1.5]
    assert policy_of(effective(specs, {EVERY: 2, DELAY: 0.0}), default) == LivePolicy(2, 0.0)
    assert policy_of({EVERY: 0}, default) == default
    with pytest.raises(ValueError):
        LivePolicy(every_shots=0)
    assert LivePolicy(5, 10).text() == "every 5 shots, 10 s apart" and LivePolicy().text() == "every shot"


# Coverage and the reuse key


def test_coverage_records_the_shots_used_and_diffs_a_later_revision() -> None:
    view = view_of(revision(range(1, 11)))
    coverage = Coverage.of(view, [8, 9, 10, 99])
    assert coverage.shots == (8, 9, 10) and coverage.fingerprints[9] == (9, 109, 1009)
    later = revise(view, revision(range(1, 13)))
    diff = coverage.diff(later, [9, 10, 11, 12])
    assert diff.new == (11, 12) and diff.changed == () and diff.gone == (8,)
    assert Coverage.of(later).diff(later).current
    assert coverage.text() == "3 shots (8–10)" and Coverage().text() == "no shots"


@pytest.mark.parametrize("script", [basic_plots.CountsPerShot(), basic_plots.TxyHistograms(),
                                    scatter_3d.Scatter3D(), transfer_fractions.TransferFractions(),
                                    shot_times.ShotTimesPlot()],
                         ids=lambda script: type(script).__name__)
def test_every_result_records_coverage_and_a_json_reuse_key(qtbot: QtBot, script: DatasetAnalysis) -> None:
    """Completed, failed and cancelled runs alike; the Shots settings decide the coverage."""
    runner = AnalysisRunner()
    ended = results_of(runner)
    view = view_of(revision(range(1, 21)))
    metadata = script.get_metadata()
    runner.submit(script, metadata, "Plot", view, {"shots": "last N", "last_shots": 5})
    qtbot.waitUntil(lambda: len(ended) == 1, timeout=10_000)
    result = ended[0]
    assert result.coverage.shots == (16, 17, 18, 19, 20)
    assert result.coverage.fingerprints[20] == (20, 120, 1020) and result.input_signature == "sig-20"
    key = result.reuse_key()
    assert json.loads(json.dumps(key)) == key  # Parameters and all: JSON values only.
    assert key["analysis_id"] == metadata.analysis_id and key["version"] == metadata.version
    assert key["coverage"]["shots"] == [16, 17, 18, 19, 20] and key["parameters"]["last_shots"] == 5
    assert "Covers: 5 shots (16–20)" in result.describe()
    runner.stop()


def test_failed_and_cancelled_results_record_coverage_too(qtbot: QtBot) -> None:
    runner = AnalysisRunner()
    ended = results_of(runner)
    script = Gated()
    view = view_of(revision([1, 2]))
    script.fail = {1}
    runner.submit(script, script.get_metadata(), "Plot", view)
    script.go.clear()
    second = runner.submit(script, script.get_metadata(), "Plot", view)
    runner.cancel(second.job_id)
    script.go.set()
    qtbot.waitUntil(lambda: len(ended) == 2, timeout=10_000)
    assert [result.state for result in ended] == ["failed", "cancelled"]
    assert all(result.coverage.shots == (1, 2) for result in ended)
    runner.stop()


# The bundled plots with nothing to draw


@pytest.mark.parametrize("script", [basic_plots.CountsPerShot(), basic_plots.TxyHistograms(),
                                    scatter_3d.Scatter3D(), transfer_fractions.TransferFractions()],
                         ids=lambda script: type(script).__name__)
@pytest.mark.parametrize("case", ["no shots yet", "none chosen", "no events"])
def test_bundled_plots_say_why_they_are_empty(qtbot: QtBot, script: DatasetAnalysis, case: str) -> None:
    if case == "no shots yet":
        dataset = revision([])
    elif case == "none chosen":
        dataset = revision([1, 2])
    else:  # Shots loaded, but their TXY files held no events.
        dataset = Dataset(PATH, "sig-empty-shots", {1: np.empty((0, 3)), 2: np.empty((0, 3))},
                          {"fingerprint": [[1, 0, 1_001], [2, 0, 1_002]]}, 0)
    view = view_of(dataset)
    values = effective(script.parameters("Plot"), {"first_shot": 10} if case == "none chosen" else {})
    context = AnalysisContext("a1", "Plot", view, values, script.get_metadata().identity())
    result = AnalysisResult.of(context, "completed", script.compute("Plot", context))
    widget = script.render(result)
    qtbot.addWidget(widget)
    assert isinstance(widget, QLabel) and widget.objectName() == "plot_empty"
    expected = {"no shots yet": "No shots yet", "none chosen": "None of the 2 shots is chosen (Shots settings)",
                "no events": "No events in the chosen shots"}[case]
    assert widget.text() == expected
    assert script.detected_parameters("Plot", result) == {}


def test_a_following_scatter_updates_its_page_in_place(
        window: Window, runner: AnalysisRunner, qtbot: QtBot) -> None:
    """Live's next revision updates the scatter's Plotly page in place (same pane and page, the
    figure swapped by the page's poll), so the camera stays; its figure keeps uirevision."""
    window.view = window.live_feed.publish(revision([1, 2]))
    instance = plot(window, qtbot, scatter_3d.Scatter3D())
    qtbot.waitUntil(lambda: shown_revision(instance) == 1, timeout=10_000)
    set_live(instance, DELAY, 0.0)
    dock = cast(QDockWidget, instance.dock_widget)
    pane = dock.findChild(PlotlyPane)
    assert pane is not None
    before = dash_server.snapshot(pane.plot_id)
    assert before is not None and before.figure.to_dict()["layout"]["uirevision"] == scatter_3d.UI_REVISION
    window.live_feed.publish(revision([1, 2, 3]))
    qtbot.waitUntil(lambda: shown_revision(instance) == 2, timeout=10_000)
    assert dock.findChild(PlotlyPane) is pane  # Not drawn anew: no page reload.
    after = dash_server.snapshot(pane.plot_id)
    assert after is not None and after.revision == before.revision + 1
    updated = cast(Any, after.figure)  # Plotly's attributes are untyped.
    figure = updated.to_dict()
    assert figure["layout"]["uirevision"] == scatter_3d.UI_REVISION and len(updated.data[0].x) == 6
    assert "rev 2" in figure["layout"]["title"]["text"] and pane.note.text().endswith("3 shots")
    plot_id = pane.plot_id
    window.close_plots()
    qtbot.waitUntil(lambda: dash_server.snapshot(plot_id) is None, timeout=10_000)  # Freed with the pane.


def test_a_following_shot_times_plot_updates_in_place(
        window: Window, runner: AnalysisRunner, qtbot: QtBot) -> None:
    """Live's next shot joins the shot-times plots already drawn (zoom and pan stay), with its time."""
    first = revision([1, 2])
    first.metadata["raw_times"] = [[1, 1_000 * 10**9], [2, 1_060 * 10**9]]
    window.view = window.live_feed.publish(first)
    instance = plot(window, qtbot, shot_times.ShotTimesPlot())
    qtbot.waitUntil(lambda: shown_revision(instance) == 1, timeout=10_000)
    set_live(instance, DELAY, 0.0)
    dock = cast(QDockWidget, instance.dock_widget)
    widget = dock.findChild(shot_times.ShotTimesWidget)
    assert widget is not None
    later = revision([1, 2, 3])
    later.metadata["raw_times"] = [*first.metadata["raw_times"], [3, 1_180 * 10**9]]
    window.live_feed.publish(later)
    qtbot.waitUntil(lambda: shown_revision(instance) == 2, timeout=10_000)
    assert dock.findChild(shot_times.ShotTimesWidget) is widget  # Updated, not drawn anew.
    result = cast(AnalysisResult, instance.shown)
    assert result.data.times.tolist() == [1_000.0, 1_060.0, 1_180.0] and not result.data.fallbacks
    assert "longest gap 2.0 min before shot 3" in widget.title.text


def run_now(script: DatasetAnalysis, view: DatasetView, values: dict[str, Any]) -> AnalysisResult:
    context = AnalysisContext("a1", "Plot", view, effective(script.parameters("Plot"), values),
                              script.get_metadata().identity())
    return AnalysisResult.of(context, "completed", script.compute("Plot", context))


def test_the_scatter_highlights_the_newest_shot(qtbot: QtBot) -> None:
    """Off by default; on, the newest shot's events are a second trace in the chosen colour."""
    view = view_of(revision([1, 2, 3]))
    script = scatter_3d.Scatter3D()
    plain = run_now(script, view, {})
    assert plain.data.newest_shot is None and len(plain.data.newest) == 0
    assert len(cast(Any, scatter_3d.figure(plain, plain.data)).data) == 1
    lit = run_now(script, view, {"highlight_newest": True, "newest_colour": "magenta"})
    data = lit.data
    assert data.newest_shot == 3 and (data.newest[:, 0] == 3.0).all() and len(data.newest) == 2
    assert not (data.points[:, 0] == 3.0).any() and data.shown == 6 == data.analysed
    traces = cast(Any, scatter_3d.figure(lit, data)).data
    assert len(traces) == 2 and traces[1].marker.color == "rgb(200, 30, 180)" and traces[1].name == "shot 3 (newest)"
    assert "shot 3 highlighted (2 events)" in scatter_3d.note_text(data)
    assert script.describe_run("Plot", lit.parameters, view)[1].endswith("newest shot in magenta")
    assert script.get_metadata().version == "3" and basic_plots.TxyHistograms().get_metadata().version == "4"


def test_the_display_cap_keeps_the_newest_shot_whole() -> None:
    rng = np.random.default_rng(1)
    data = {1: rng.normal(size=(1500, 3)), 2: rng.normal(size=(1500, 3)), 3: rng.normal(size=(300, 3)) + 5}
    view = view_of(Dataset(PATH, "sig-cap", data, {"fingerprint": [[s, 1, 1] for s in data]}, 0))
    result = run_now(scatter_3d.Scatter3D(), view, {"highlight_newest": True, "display_cap": 1000,
                                                    "keep_percent": 100.0})
    assert len(result.data.newest) == 300 and len(result.data.points) == 700 and result.data.shown == 1000


def test_the_histograms_overlay_the_newest_shot(qtbot: QtBot) -> None:
    rng = np.random.default_rng(2)
    data = {1: rng.normal(size=(400, 3)), 2: rng.normal(size=(400, 3)), 3: rng.normal(size=(50, 3)) * 0.1}
    view = view_of(Dataset(PATH, "sig-hist", data, {"fingerprint": [[s, 1, 1] for s in data]}, 0))
    script = basic_plots.TxyHistograms()
    plain = run_now(script, view, {})
    assert plain.data.newest_shot is None and plain.data.newest == ()
    lit = run_now(script, view, {"highlight_newest": True, "keep_percent": 100.0})
    histograms = lit.data
    assert histograms.newest_shot == 3 and len(histograms.newest) == 3
    for item, counts in zip(histograms.items, histograms.newest):
        assert len(counts) == len(item.counts) and counts.sum() == 50  # Every newest event, in the same bins.
        assert (counts <= item.counts).all()
    assert script.describe_run("Plot", lit.parameters, view)[1].endswith("newest shot in red")


@pytest.mark.parametrize("log_y", [False, True], ids=["linear", "log Y"])
def test_the_newest_shot_has_its_own_axis_on_the_right(qtbot: QtBot, log_y: bool) -> None:
    """The newest shot's real counts, in a view of their own linked on x, read on a right axis in
    its colour; that view's y range follows the plot's divided by the histogram's total over the
    shot's (log Y: shifted by its log10), so the line sits at the histogram's scale. The left axis
    keeps all the counts, in the plot's colour. The overlay leaves the mouse to the plot."""
    rng = np.random.default_rng(2)
    data = {1: rng.normal(size=(400, 3)), 2: rng.normal(size=(400, 3)), 3: rng.normal(size=(50, 3)) * 0.1}
    view = view_of(Dataset(PATH, "sig-axis", data, {"fingerprint": [[s, 1, 1] for s in data]}, 0))
    script = basic_plots.TxyHistograms()
    lit = run_now(script, view, {"highlight_newest": True, "keep_percent": 100.0, "log_y": log_y})
    widget = cast(Any, script.render(lit))
    qtbot.addWidget(widget)
    widget.resize(900, 700)
    widget.show()
    qtbot.wait(50)
    histograms = lit.data
    assert len(widget.newest_views) == 3
    for row, (item, counts, overlay) in enumerate(zip(histograms.items, histograms.newest, widget.newest_views),
                                                    start=1):
        plot = widget.ci.getItem(row, 0)
        right, left = plot.getAxis("right"), plot.getAxis("left")
        assert right.isVisible() and right.linkedView() is overlay and right.labelText == "shot 3 events"
        assert right.pen().color().getRgb()[:3] == histograms.colour == right.textPen().color().getRgb()[:3]
        assert left.labelText == "Events (all)" and left.pen().color().getRgb()[:3] == basic_plots.COLOUR
        assert isinstance(right, basic_plots.DecadeLogAxis) == log_y
        curves = [child for child in overlay.addedItems if isinstance(child, pg.PlotDataItem)]
        assert len(curves) == 1 and curves[0].name() == "shot 3"
        values = curves[0].yData
        assert values is not None and np.allclose(np.nan_to_num(values, nan=0.0), counts)  # Real counts, unscaled.
        assert curves[0].opts["logMode"] == [False, log_y]
        scale = item.counts.sum() / counts.sum()
        # Linked on x (the link follows the plot's own range as the window settles).
        qtbot.waitUntil(lambda: np.allclose(overlay.viewRange()[0], plot.vb.viewRange()[0]), timeout=5_000)
        (low, high), (overlay_low, overlay_high) = plot.vb.viewRange()[1], overlay.viewRange()[1]
        if log_y:
            assert np.isclose(overlay_low, low - np.log10(scale)) and np.isclose(overlay_high, high - np.log10(scale))
        else:
            assert np.isclose(overlay_low, low / scale) and np.isclose(overlay_high, high / scale)
        # Zooming the plot moves the overlay with it.
        plot.vb.setYRange(low, low + (high - low) / 2, padding=0)
        assert np.isclose(overlay.viewRange()[1][1], (low + (high - low) / 2 - np.log10(scale)) if log_y
                          else (low + (high - low) / 2) / scale)

    class Event:
        ignored = False

        def ignore(self) -> None:
            self.ignored = True

        def delta(self) -> int:
            return 120

    for handler in ("mouseDragEvent", "mouseClickEvent", "wheelEvent"):
        event = Event()
        getattr(widget.newest_views[0], handler)(event)
        assert event.ignored, handler  # Left to the plot below (its zoom, pan and menu).


def histogram_refs(widget: Any) -> list[weakref.ref[Any]]:
    """Weak references to what one highlighted histogram keeps in Python: the plot, its overlay
    view, the overlay's curve and that curve's counts."""
    plot, overlay = widget.ci.getItem(1, 0), widget.newest_views[0]
    curve = next(child for child in overlay.addedItems if isinstance(child, pg.PlotDataItem))
    return [weakref.ref(item) for item in (plot, overlay, curve, curve.yData)]


def freed(refs: list[weakref.ref[Any]]) -> bool:
    """One pass of deferred deletes, then one collection: all gone (nothing held them by a
    connection that outlives the widget)."""
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    gc.collect()
    return all(ref() is None for ref in refs)


@pytest.mark.parametrize("log_y", [False, True], ids=["linear", "log Y"])
def test_without_the_highlight_there_is_no_right_axis(qtbot: QtBot, log_y: bool) -> None:
    """The right axis belongs to the newest shot: with the highlight off, none shows (with log Y
    either: a right decade axis would repeat the left one, unlabelled)."""
    rng = np.random.default_rng(4)
    data = {shot: rng.normal(size=(300, 3)) for shot in (1, 2, 3)}
    view = view_of(Dataset(PATH, "sig-plain", data, {"fingerprint": [[s, 1, 1] for s in data]}, 0))
    script = basic_plots.TxyHistograms()
    widget = cast(Any, script.render(run_now(script, view, {"log_y": log_y})))
    qtbot.addWidget(widget)
    widget.resize(800, 600)
    widget.show()
    qtbot.wait(20)
    assert widget.newest_views == []
    for row in (1, 2, 3):
        plot = widget.ci.getItem(row, 0)
        assert not plot.getAxis("right").isVisible()
        assert isinstance(plot.getAxis("left"), basic_plots.DecadeLogAxis) == log_y


@pytest.mark.parametrize("log_y", [False, True], ids=["linear", "log Y"])
def test_a_highlighted_histogram_is_freed_with_its_widget(qtbot: QtBot, log_y: bool) -> None:
    """The overlay keeps step with its plot through Qt connections that end with either: once
    the widget is deleted, its plot, overlay, curve and counts are freed."""
    rng = np.random.default_rng(3)
    data = {shot: rng.normal(size=(300, 3)) for shot in (1, 2, 3)}
    view = view_of(Dataset(PATH, "sig-free", data, {"fingerprint": [[s, 1, 1] for s in data]}, 0))
    script = basic_plots.TxyHistograms()
    widget = cast(Any, script.render(run_now(script, view, {"highlight_newest": True, "log_y": log_y})))
    widget.resize(800, 600)
    widget.show()
    qtbot.wait(20)
    refs = histogram_refs(widget)
    widget.deleteLater()
    del widget
    assert freed(refs)


def test_a_following_histograms_old_drawing_is_freed_when_redrawn(
        window: Window, runner: AnalysisRunner, qtbot: QtBot) -> None:
    """Live's next revision draws the histograms anew; the old drawing's plot, overlay and
    counts go with the widget it replaced."""
    window.view = window.live_feed.publish(revision([1, 2]))
    instance = plot(window, qtbot, basic_plots.TxyHistograms())
    qtbot.waitUntil(lambda: shown_revision(instance) == 1, timeout=10_000)
    assert instance.parameter_root is not None
    parameter_of(instance.parameter_root, basic_plots.HIGHLIGHT).setValue(True)
    instance.run()
    qtbot.waitUntil(lambda: instance.shown is not None and instance.shown.data.newest_shot == 2, timeout=10_000)
    refs = histogram_refs(instance._content)
    window.live_feed.publish(revision([1, 2, 3]))
    qtbot.waitUntil(lambda: shown_revision(instance) == 2 and instance.shown is not None
                    and instance.shown.data.newest_shot == 3, timeout=10_000)
    assert freed(refs)


def test_a_following_plot_highlights_lives_newest_shot(
        window: Window, runner: AnalysisRunner, qtbot: QtBot) -> None:
    window.view = window.live_feed.publish(revision([1, 2]))
    instance = plot(window, qtbot, basic_plots.TxyHistograms())
    qtbot.waitUntil(lambda: shown_revision(instance) == 1, timeout=10_000)
    assert instance.parameter_root is not None
    parameter_of(instance.parameter_root, basic_plots.HIGHLIGHT).setValue(True)
    instance.run()
    qtbot.waitUntil(lambda: instance.shown is not None and instance.shown.data.newest_shot == 2, timeout=10_000)
    window.live_feed.publish(revision([1, 2, 3]))
    qtbot.waitUntil(lambda: instance.shown is not None and instance.shown.data.newest_shot == 3, timeout=10_000)


def test_scatter_declares_a_live_policy_others_rerun_on_every_shot() -> None:
    assert scatter_3d.Scatter3D().live_policy("Plot") == LivePolicy(min_delay=5.0)
    for script in (basic_plots.CountsPerShot(), basic_plots.TxyHistograms(), transfer_fractions.TransferFractions(),
                   shot_times.ShotTimesPlot()):
        assert script.live_policy("Plot") == LivePolicy()


# Plots following the feed


def test_shots_arriving_faster_than_a_run_give_one_rerun_on_the_newest(
        window: Window, runner: AnalysisRunner, qtbot: QtBot) -> None:
    ended = results_of(runner)
    window.view = window.live_feed.publish(revision([1]))
    script = Gated()
    instance = plot(window, qtbot, script)
    qtbot.waitUntil(lambda: shown_revision(instance) == 1, timeout=10_000)
    assert "rev 1 · following Live · tests.gated v1" in source(instance).text()
    script.go.clear()
    window.live_feed.publish(revision([1, 2]))
    qtbot.waitUntil(lambda: script.started == [1, 2], timeout=10_000)
    for n in (3, 4, 5):
        window.live_feed.publish(revision(range(1, n + 1)))
        assert runner.running() == 1  # The run in flight only: nothing queued behind it.
    pending = instance.follow.pending
    assert pending is not None and pending.revision == 5 and instance.follow.waiting() == 3
    assert source(instance).text().startswith(
        "Data source: run_L · rev 1 · following Live · updating to rev 2 · 3 new shots waiting · tests.gated v1")
    script.go.set()
    qtbot.waitUntil(lambda: shown_revision(instance) == 5, timeout=10_000)
    assert script.started == [1, 2, 5]  # One coalesced rerun, on the newest revision.
    assert [result.state for result in ended] == ["completed"] * 3  # Nothing cancelled.
    assert instance.follow.pending is None and runner.running() == 0
    assert source(instance).text().startswith("Data source: run_L · rev 5 · following Live · tests.gated v1")
    assert instance.input_label.text() == "Input: run_L · rev 5 · following Live"
    assert window.panel_right_top_plot_settings.chooser.itemText(0) == "Gated (1) · run_L · rev 5"
    assert cast(AnalysisResult, instance.shown).coverage.shots == (1, 2, 3, 4, 5)


def test_a_plot_made_before_live_catches_up_with_changed_data(
        window: Window, runner: AnalysisRunner, qtbot: QtBot) -> None:
    """A plot of data loaded before Live; when Live starts, the folder's data has the same shot
    numbers but one shot changed (another signature): the plot runs once on it."""
    before = revision([1, 2])
    window.view = view_of(before)
    script = Gated(LivePolicy(every_shots=3))
    instance = plot(window, qtbot, script)
    qtbot.waitUntil(lambda: shown_revision(instance) == 1, timeout=10_000)
    old = instance.view
    live = window.live_feed.publish(changed(before, 2, "sig-changed"))  # Live starts on it.
    assert live.identity != old.identity and live.shot_numbers == old.shot_numbers == (1, 2)
    qtbot.waitUntil(lambda: instance.shown is not None and instance.shown.input == live.key, timeout=10_000)
    assert script.started == [1, 1] and instance.follow.pending is None
    shown = cast(AnalysisResult, instance.shown)
    assert shown.input_signature == "sig-changed" and shown.coverage.fingerprints[2] == (2, 109, 1002)
    assert instance.follow_text() == "following Live"


def test_a_plot_reruns_every_n_shots_as_its_script_declares(
        window: Window, runner: AnalysisRunner, qtbot: QtBot) -> None:
    window.view = window.live_feed.publish(revision([1]))
    script = Gated(LivePolicy(every_shots=3))
    instance = plot(window, qtbot, script)
    qtbot.waitUntil(lambda: shown_revision(instance) == 1, timeout=10_000)
    assert instance.live_values() == {FOLLOW: True, EVERY: 3, DELAY: 0.0}  # The script's defaults.
    window.live_feed.publish(revision([1, 2]))
    window.live_feed.publish(revision([1, 2, 3]))
    assert script.started == [1] and instance.follow_text() == "following Live · 2 new shots waiting (runs every 3)"
    window.live_feed.publish(revision([1, 2, 3, 4]))
    qtbot.waitUntil(lambda: shown_revision(instance) == 4, timeout=10_000)
    assert script.started == [1, 4]
    # Changed in the plot's settings: from now on every new shot.
    set_live(instance, EVERY, 1)
    window.live_feed.publish(revision(range(1, 6)))
    qtbot.waitUntil(lambda: shown_revision(instance) == 5, timeout=10_000)


def test_a_plot_waits_its_delay_after_a_run(window: Window, runner: AnalysisRunner, qtbot: QtBot) -> None:
    window.view = window.live_feed.publish(revision([1]))
    script = Gated(LivePolicy(min_delay=0.4))
    instance = plot(window, qtbot, script)
    qtbot.waitUntil(lambda: shown_revision(instance) == 1, timeout=10_000)
    ended_at = instance.follow.finished_at
    window.live_feed.publish(revision([1, 2]))
    assert script.started == [1] and instance.follow_text() == "following Live · 1 new shot waiting (runs 0.4 s after the last run)"
    qtbot.waitUntil(lambda: shown_revision(instance) == 2, timeout=10_000)
    assert script.started_at[1] - ended_at >= 0.39


def test_two_plots_of_one_folder_follow_with_their_own_policies(
        window: Window, runner: AnalysisRunner, qtbot: QtBot) -> None:
    window.view = window.live_feed.publish(revision([1]))
    every, third = Gated(name="Every"), Gated(LivePolicy(every_shots=3), name="Third")
    first, second = plot(window, qtbot, every), plot(window, qtbot, third)
    other = Gated(name="Other")
    window.view = view_of(revision([1], "/data/root/run_M"))
    elsewhere = plot(window, qtbot, other)
    qtbot.waitUntil(lambda: all(shown_revision(i) == 1 for i in (first, second, elsewhere)), timeout=10_000)
    for n in (2, 3, 4):
        window.live_feed.publish(revision(range(1, n + 1)))
        qtbot.waitUntil(lambda: shown_revision(first) == n, timeout=10_000)
    qtbot.waitUntil(lambda: shown_revision(second) == 4, timeout=10_000)
    assert every.started == [1, 2, 3, 4] and third.started == [1, 4]
    assert other.started == [1] and elsewhere.follow_text() == ""  # Plots of other folders stay put.


def test_follow_live_off_pins_the_plot_and_on_again_catches_up(
        window: Window, runner: AnalysisRunner, qtbot: QtBot) -> None:
    window.view = window.live_feed.publish(revision([1]))
    script = Gated()
    instance = plot(window, qtbot, script)
    qtbot.waitUntil(lambda: shown_revision(instance) == 1, timeout=10_000)
    set_live(instance, FOLLOW, False)
    window.live_feed.publish(revision([1, 2]))
    window.live_feed.publish(revision([1, 2, 3]))
    assert script.started == [1] and instance.follow_text() == "pinned (Follow Live off) · 2 newer shots"
    assert "rev 1 · pinned (Follow Live off) · 2 newer shots" in source(instance).text()
    assert instance.input_label.text() == "Input: run_L · rev 1 (stays with this plot)"
    # Rerun with other settings stays on the pinned revision.
    instance.run()
    qtbot.waitUntil(lambda: len(script.started) == 2 and instance.job_id == "", timeout=10_000)
    assert script.started == [1, 1] and shown_revision(instance) == 1
    set_live(instance, FOLLOW, True)
    qtbot.waitUntil(lambda: shown_revision(instance) == 3, timeout=10_000)
    assert script.started == [1, 1, 3]


def test_pinning_during_a_live_rerun_keeps_the_pinned_revision(
        window: Window, runner: AnalysisRunner, qtbot: QtBot) -> None:
    """Follow Live off while a rerun on newer data runs: that run ends, but its result isn't the
    pinned plot's (dropped, not drawn), and Rerun stays on the pinned revision."""
    window.view = window.live_feed.publish(revision([1]))
    script = Gated()
    instance = plot(window, qtbot, script)
    qtbot.waitUntil(lambda: shown_revision(instance) == 1, timeout=10_000)
    script.go.clear()
    window.live_feed.publish(revision([1, 2]))
    qtbot.waitUntil(lambda: script.started == [1, 2], timeout=10_000)
    set_live(instance, FOLLOW, False)
    assert instance.follow.ran.revision == 1 and instance.job_id  # Pinned at rev 1; rev 2 still runs.
    script.go.set()
    qtbot.waitUntil(lambda: instance.job_id == "", timeout=10_000)
    dock = cast(QDockWidget, instance.dock_widget)
    plotted = dock.findChild(QLabel, "gated_plot")
    assert plotted is not None and plotted.text() == "rev 1 · 1 shots" and shown_revision(instance) == 1
    assert instance.status_label.text() == "Pinned at rev 1: the run on rev 2 isn't shown"
    assert source(instance).text().startswith(
        "Showing previously loaded data: run_L · rev 1 · pinned (Follow Live off) · 1 newer shot")
    assert instance.input_label.text() == "Input: run_L · rev 1 (stays with this plot)"
    instance.run()  # Rerun with these settings: the pinned revision.
    qtbot.waitUntil(lambda: len(script.started) == 3 and instance.job_id == "", timeout=10_000)
    assert script.started == [1, 2, 1] and shown_revision(instance) == 1
    set_live(instance, FOLLOW, True)  # On again: catches up.
    qtbot.waitUntil(lambda: shown_revision(instance) == 2, timeout=10_000)


def test_a_failed_rerun_keeps_the_last_plot_and_following_goes_on(
        window: Window, runner: AnalysisRunner, qtbot: QtBot) -> None:
    window.view = window.live_feed.publish(revision([1]))
    script = Gated()
    script.fail = {2}
    instance = plot(window, qtbot, script)
    qtbot.waitUntil(lambda: shown_revision(instance) == 1, timeout=10_000)
    dock = cast(QDockWidget, instance.dock_widget)
    assert not error_line(instance).isVisibleTo(dock)
    window.live_feed.publish(revision([1, 2]))
    qtbot.waitUntil(lambda: instance.result is not None and instance.result.state == "failed", timeout=10_000)
    plotted = dock.findChild(QLabel, "gated_plot")
    assert plotted is not None and plotted.text() == "rev 1 · 1 shots"  # The last good plot stays.
    assert shown_revision(instance) == 1 and error_line(instance).isVisibleTo(dock)
    assert error_line(instance).text() == "⚠ rev 2 failed: bad rev 2 · showing rev 1"
    # The settings name what the plot shows, not the failed run's data.
    assert instance.input_label.text() == "Input: run_L · rev 1 · following Live"
    assert window.panel_right_top_plot_settings.chooser.itemText(0) == "Gated (1) · run_L · rev 1"
    assert "#b26a00" in error_line(instance).styleSheet()
    assert source(instance).text().startswith("Data source: run_L · rev 1 · following Live")
    window.live_feed.publish(revision([1, 2, 3]))
    qtbot.waitUntil(lambda: shown_revision(instance) == 3, timeout=10_000)
    assert not error_line(instance).isVisibleTo(dock) and instance.error == ""


def test_a_floating_plot_runs_and_follows_with_its_settings_in_its_window(
        window: Window, runner: AnalysisRunner, qtbot: QtBot) -> None:
    """Float, dock again and close a plot while it runs and follows Live: its page (Follow
    Live, Rerun and unapplied edits) moves with it, its header names its settings, and closing
    it while floating and running cancels the run and leaves nothing behind."""
    ended = results_of(runner)
    window.middle_mainwindow.show()
    window.view = window.live_feed.publish(revision([1]))
    script = Gated()
    instance = plot(window, qtbot, script)
    qtbot.waitUntil(lambda: shown_revision(instance) == 1, timeout=10_000)
    dock = cast(AnalysisDock, instance.dock_widget)
    page = cast(QWidget, instance.param_tab)
    settings = window.panel_right_top_plot_settings
    script.go.clear()
    window.live_feed.publish(revision([1, 2]))
    qtbot.waitUntil(lambda: script.started == [1, 2], timeout=10_000)
    dock.setFloating(True)  # While the Live rerun runs.
    dock.show()
    qtbot.waitUntil(dock.settings.isVisible)
    assert dock.settings.page is page and settings.stack.currentWidget() is settings.away
    toggle = dock.settings.toggle
    assert toggle.name == "Gated (1) · run_L · rev 1" and toggle.summary == dock.property("plotSourceSettings")
    window.live_feed.publish(revision([1, 2, 3]))  # Waits for the run in flight.
    script.go.set()
    qtbot.waitUntil(lambda: shown_revision(instance) == 3, timeout=10_000)
    assert script.started == [1, 2, 3] and toggle.name == "Gated (1) · run_L · rev 3"
    assert source(instance).text().startswith("Data source: run_L · rev 3 · following Live")
    # Its Live settings, in its window: Follow Live off pins it.
    set_live(instance, FOLLOW, False)
    window.live_feed.publish(revision(range(1, 5)))
    assert instance.follow_text() == "pinned (Follow Live off) · 1 newer shot"
    # Unapplied edits and Rerun stay with the page, floating and docked again.
    root = cast(Any, instance.parameter_root)
    root.child("scale").setValue(4)
    dock.setFloating(False)
    qtbot.waitUntil(dock.settings.isHidden)
    assert page.parentWidget() is settings.stack and instance.values() == {"scale": 4}
    dock.setFloating(True)
    dock.show()
    qtbot.waitUntil(dock.settings.isVisible)
    instance.rerun_button.click()
    qtbot.waitUntil(lambda: len(script.started) == 4 and instance.job_id == "", timeout=10_000)
    assert script.started[-1] == 3 and cast(AnalysisResult, instance.shown).parameters["scale"] == 4
    # Closed while floating and running: the run is cancelled and nothing is left.
    script.go.clear()
    instance.rerun_button.click()
    qtbot.waitUntil(lambda: len(script.started) == 5, timeout=10_000)
    window.close_plots()  # As closing the main window does.
    assert instance.is_closed and settings.plots() == [] and not window.dock_widgets
    script.go.set()
    qtbot.waitUntil(lambda: runner.running() == 0, timeout=10_000)
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    assert sip.isdeleted(page) and sip.isdeleted(dock) and not runner.results._pinned
    assert ended[-1].state == "cancelled"


def test_a_first_run_that_fails_shows_why(window: Window, runner: AnalysisRunner, qtbot: QtBot) -> None:
    window.view = window.live_feed.publish(revision([1]))
    script = Gated()
    script.fail = {1}
    instance = plot(window, qtbot, script)
    qtbot.waitUntil(lambda: instance.result is not None, timeout=10_000)
    assert instance.shown is None and instance.status_label.text() == "Failed: bad rev 1"
    texts = [label.text() for label in cast(QDockWidget, instance.dock_widget).findChildren(QLabel)]
    assert "Gated failed: bad rev 1" in texts
    window.live_feed.publish(revision([1, 2]))  # Still following: the next revision is plotted.
    qtbot.waitUntil(lambda: shown_revision(instance) == 2, timeout=10_000)


@pytest.mark.parametrize("held_by", ["every N shots", "the delay"])
def test_live_off_catches_up_at_once_then_stays(
        window: Window, runner: AnalysisRunner, qtbot: QtBot, held_by: str) -> None:
    """Shots the policy held back run once more as soon as Live stops, whatever the policy;
    then the plot stays at that revision."""
    window.view = window.live_feed.publish(revision([1]))
    policy = LivePolicy(every_shots=5) if held_by == "every N shots" else LivePolicy(min_delay=60.0)
    script = Gated(policy)
    instance = plot(window, qtbot, script)
    qtbot.waitUntil(lambda: shown_revision(instance) == 1, timeout=10_000)
    window.live_feed.publish(revision([1, 2]))
    window.live_feed.publish(revision([1, 2, 3]))
    assert script.started == [1] and instance.follow.waiting() == 2  # Held back.
    window.live_feed.stop(PATH)  # Live off (or another tab, or an error).
    qtbot.waitUntil(lambda: shown_revision(instance) == 3, timeout=10_000)
    assert script.started == [1, 3]  # One catch-up, on the last revision, at once.
    assert not instance._follow_timer.isActive() and instance.follow.pending is None
    assert instance.follow_text() == "" and "following Live" not in source(instance).text()
    assert instance.input_label.text() == "Input: run_L · rev 3 (stays with this plot)"
    qtbot.wait(50)
    assert script.started == [1, 3]  # Then it stays.


def test_live_off_during_a_run_catches_up_after_it(
        window: Window, runner: AnalysisRunner, qtbot: QtBot) -> None:
    window.view = window.live_feed.publish(revision([1]))
    script = Gated(LivePolicy(every_shots=5))
    instance = plot(window, qtbot, script)
    qtbot.waitUntil(lambda: shown_revision(instance) == 1, timeout=10_000)
    script.go.clear()
    instance.run()  # A run in flight (Rerun with these settings).
    qtbot.waitUntil(lambda: script.started == [1, 1], timeout=10_000)
    window.live_feed.publish(revision([1, 2]))
    window.live_feed.stop(PATH)
    assert instance.follow_text() == "Live off · 1 new shot waiting"  # Never cancels the run.
    script.go.set()
    qtbot.waitUntil(lambda: shown_revision(instance) == 2, timeout=10_000)
    assert script.started == [1, 1, 2]


def test_a_pinned_plot_doesnt_catch_up_when_live_stops(
        window: Window, runner: AnalysisRunner, qtbot: QtBot) -> None:
    window.view = window.live_feed.publish(revision([1]))
    script = Gated(LivePolicy(every_shots=5))
    instance = plot(window, qtbot, script)
    qtbot.waitUntil(lambda: shown_revision(instance) == 1, timeout=10_000)
    window.live_feed.publish(revision([1, 2]))
    set_live(instance, FOLLOW, False)
    window.live_feed.stop(PATH)
    qtbot.wait(50)
    assert script.started == [1] and shown_revision(instance) == 1


def test_live_on_again_brings_the_policy_back() -> None:
    first = view_of(revision([1]))
    follow = Follow(first, LivePolicy(every_shots=3, min_delay=10.0))
    follow.start(first)
    follow.end(0.0)
    second = revise(first, revision([1, 2]))
    follow.offer(second)
    assert follow.due(1.0) == (None, 0.0)
    follow.live_ended()
    assert follow.due(1.0) == (second, 0.0)  # The catch-up: no N, no delay.
    follow.live_on()
    assert follow.due(1.0) == (None, 0.0)


# A real tab: Live from an empty folder to its first shots


def write_shot(folder: Path, shot: int) -> None:
    file = folder / f"d_txy_forc{shot}.txt"
    file.write_text(f"{shot},2,3\n{shot},4,5\n")
    when = time.time() - 60
    os.utime(file, (when, when))


def age(folder: Path, seconds: float) -> None:
    when = time.time() - seconds
    os.utime(folder, (when, when))


def replay(cache: FolderCache, path: str, tmp_path: Path, operation: str) -> None:
    """Run the real helper for the folder's queued request in-process and deliver its events."""
    job = cache.jobs[(operation, path)]
    request = next(r for r in cache.service.pending if r.owner == job.owner)
    payload = request.payload
    output = tmp_path / f"artifacts-{time.monotonic_ns()}"
    output.mkdir()
    events: list[dict[str, Any]] = []
    if operation == "list":
        list_folder(path, events.append, payload.get("cache"))
    else:
        live_check(path, str(output), events.append, payload.get("memory"), payload.get("known"),
                   payload.get("live_since"), identity=payload.get("identity", ""), seen=payload.get("seen"))
    cache.service.pending.remove(request)
    for event in [*events, {"kind": "done"}]:
        if event["kind"] == "shot":
            event = {**event, "array": np.load(event.pop("artifact"))}
        cache.service.resultReady.emit(request, event)


def live_checks(qtbot: QtBot, explorer: FolderExplorer, path: str, tmp_path: Path, count: int) -> None:
    for _ in range(count):
        qtbot.waitUntil(lambda: ("live", path) in explorer.model.cache.jobs)
        replay(explorer.model.cache, path, tmp_path, "live")


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> Iterator[IOService]:
    made = IOService()
    made.timer.stop()
    monkeypatch.setattr(made, "_dispatch", lambda: None)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: made)
    yield made
    made.shutdown()


def test_a_plot_follows_live_from_an_empty_folder_to_its_first_shots(
        qtbot: QtBot, service: IOService, runner: AnalysisRunner, tmp_path: Path) -> None:
    folder = tmp_path / "run_E"
    folder.mkdir()
    age(folder, 120)
    path = str(folder)
    explorer = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(explorer)
    cache = explorer.model.cache
    cache.live_interval = 0.02
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    replay(cache, path, tmp_path, "list")
    qtbot.waitUntil(lambda: explorer.model.nodes[path].report is not None)
    window = Window(explorer)
    qtbot.addWidget(window)
    assert explorer.start_live()
    start = window.live_feed.latest(path)
    assert start is not None and start.shots == {} and window.current_dataset_view() is start
    instance = plot(window, qtbot, basic_plots.CountsPerShot())
    qtbot.waitUntil(lambda: shown_revision(instance) == 1, timeout=10_000)
    dock = cast(QDockWidget, instance.dock_widget)
    empty = dock.findChild(QLabel, "plot_empty")
    assert empty is not None and empty.text() == "No shots yet"
    assert source(instance).text().startswith("Data source: run_E · rev 1 · following Live · 0 shots")
    live_checks(qtbot, explorer, path, tmp_path, 1)  # Nothing yet.
    write_shot(folder, 1)
    age(folder, 60)
    live_checks(qtbot, explorer, path, tmp_path, 2)  # Seen, then read: the first shot.
    qtbot.waitUntil(lambda: shown_revision(instance) == 2, timeout=10_000)
    result = cast(AnalysisResult, instance.shown)
    assert result.data.shots.tolist() == [1] and result.data.counts.tolist() == [2]
    assert result.coverage.shots == (1,) and result.input_signature == cast(Dataset, explorer.displayed_dataset).signature
    assert dock.findChild(QLabel, "plot_empty") is None
    assert source(instance).text().startswith("Data source: run_E · rev 2 · following Live · 1 shot")
    write_shot(folder, 2)
    age(folder, 50)
    live_checks(qtbot, explorer, path, tmp_path, 2)
    qtbot.waitUntil(lambda: shown_revision(instance) == 3, timeout=10_000)
    # Checks stopped by an error: the plot stops following (it caught up already); Retry resumes.
    session = explorer.live
    assert session is not None
    explorer._live_halt(session, "Folder not found — is its drive connected?")
    assert window.live_feed.latest(path) is None and "following Live" not in source(instance).text()
    explorer.resume_live()
    assert window.live_feed.latest(path) is not None and instance.follow_text() == "following Live"
    # Live off (as switching tabs does): the plot keeps its revision and stops following.
    explorer.stop_live(save=False)
    assert window.live_feed.latest(path) is None and shown_revision(instance) == 3
    assert "following Live" not in source(instance).text() and instance.follow_text() == ""
    window.close_plots()
    explorer.close_cleanup()


def test_auto_orders_are_found_again_on_each_rerun_and_manual_fixes_them(
        window: Window, runner: AnalysisRunner, qtbot: QtBot) -> None:
    """Transfer fractions following Live: in auto mode each rerun detects the orders in its own
    data; in manual mode the centre and spacing stay as set."""
    def orders(centre: float, shots: range) -> Dataset:
        rng = np.random.default_rng(0)
        data = {}
        for shot in shots:
            times = np.concatenate([rng.normal(centre + k * 0.01, 0.0005, 300 if k == 0 else 120) for k in (-1, 0, 1)])
            data[shot] = np.column_stack([times, np.zeros_like(times), np.zeros_like(times)])
        return Dataset(PATH, f"orders-{centre}-{shots.stop}", data, {
            "fingerprint": [[shot, 100 + shot, 1_000 + shot] for shot in shots]}, 0)

    window.view = window.live_feed.publish(orders(2.0, range(1, 3)))
    instance = plot(window, qtbot, transfer_fractions.TransferFractions())
    qtbot.waitUntil(lambda: shown_revision(instance) == 1, timeout=10_000)
    first = cast(AnalysisResult, instance.shown).data
    assert first.detected and first.orders.centre == pytest.approx(2.0, abs=1e-3)
    # The orders move (shots 3–4 arrive later in T): auto finds them again in the new data.
    moved = orders(2.0, range(1, 3))
    later = orders(2.004, range(3, 5))
    window.live_feed.publish(Dataset(PATH, "orders-moved", {**moved.data, **later.data},
                                     {"fingerprint": moved.metadata["fingerprint"] + later.metadata["fingerprint"]}, 0))
    qtbot.waitUntil(lambda: shown_revision(instance) == 2, timeout=10_000)
    second = cast(AnalysisResult, instance.shown).data
    assert second.detected and second.orders.centre != first.orders.centre
    # Manual: the detected values became the settings, and stay as set on later reruns.
    root = instance.parameter_root
    assert root is not None
    parameter_of(root, transfer_fractions.MODE).setValue(transfer_fractions.MANUAL)
    manual_centre = parameter_of(root, transfer_fractions.CENTRE).value()
    window.live_feed.publish(Dataset(PATH, "orders-more", {**moved.data, **later.data, **orders(2.01, range(5, 6)).data},
                                     {"fingerprint": [[shot, 100 + shot, 1_000 + shot] for shot in range(1, 6)]}, 0))
    qtbot.waitUntil(lambda: shown_revision(instance) == 3, timeout=10_000)
    third = cast(AnalysisResult, instance.shown).data
    assert not third.auto and third.orders.centre == manual_centre


def test_the_main_window_feeds_its_live_tab_to_the_plots(qtbot: QtBot, runner: AnalysisRunner) -> None:
    """The real window: each tab's Live changes and shown data reach the feed (wired when the tab
    is made), and Live off ends the folder's feed."""
    from helab.views.FolderExplorer import LiveSession
    window = HelabMainWindow()
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: isinstance(window.tab_widget.currentWidget(), FolderExplorer))
    explorer = window.tab_widget.currentWidget()
    assert isinstance(explorer, FolderExplorer)
    path = explorer.selected_path_globally
    ended: list[str] = []
    window.live_feed.ended.connect(ended.append)
    first = revision([1], path)
    explorer.displayed_dataset = first
    explorer.live = LiveSession(path, time.time(), {1}, first)
    explorer.liveChanged.emit()
    view = window.live_feed.latest(path)
    assert view is not None and view.shot_numbers == (1,)
    explorer.displayed_dataset = revision([1, 2], path)
    explorer.dataLoaded.emit(path)
    newest = window.live_feed.latest(path)
    assert newest is not None and newest.revision == view.revision + 1
    assert window.current_dataset_view() is newest
    explorer.live = None
    explorer.liveChanged.emit()
    assert window.live_feed.latest(path) is None and ended == [path]
    explorer.displayed_dataset = None
    window._quit_now = True


def test_an_error_stopping_live_checks_catches_plots_up(
        qtbot: QtBot, service: IOService, runner: AnalysisRunner, tmp_path: Path) -> None:
    """A real tab: shots held back by "every N" run once when an error stops Live's checks."""
    folder = tmp_path / "run_H"
    folder.mkdir()
    write_shot(folder, 1)
    age(folder, 120)
    path = str(folder)
    explorer = FolderExplorer(path, path, path, [0, 4, 5])
    qtbot.addWidget(explorer)
    cache = explorer.model.cache
    cache.live_interval = 0.02
    qtbot.waitUntil(lambda: ("list", path) in cache.jobs)
    replay(cache, path, tmp_path, "list")
    explorer.load_to_ram_cache(path, dwell=False, explicit=True)
    qtbot.waitUntil(lambda: ("load", path) in cache.jobs)
    job = cache.jobs[("load", path)]
    request = next(r for r in service.pending if r.owner == job.owner)
    output = tmp_path / "load"
    output.mkdir()
    events: list[dict[str, Any]] = []
    load(path, str(output), events.append, None)
    service.pending.remove(request)
    for event in [*events, {"kind": "done"}]:
        if event["kind"] == "shot":
            event = {**event, "array": np.load(event.pop("artifact"))}
        service.resultReady.emit(request, event)
    qtbot.waitUntil(lambda: explorer.folder_opened_path == path)
    window = Window(explorer)
    qtbot.addWidget(window)
    assert explorer.start_live()
    script = Gated(LivePolicy(every_shots=5))
    instance = plot(window, qtbot, script)
    qtbot.waitUntil(lambda: shown_revision(instance) == 1, timeout=10_000)
    write_shot(folder, 2)
    age(folder, 60)
    live_checks(qtbot, explorer, path, tmp_path, 2)
    qtbot.waitUntil(lambda: instance.follow.waiting() == 1, timeout=10_000)
    assert script.started == [1]  # Held back: 1 of 5.
    session = explorer.live
    assert session is not None
    explorer._live_halt(session, "Folder not found — is its drive connected?")
    qtbot.waitUntil(lambda: shown_revision(instance) == 2, timeout=10_000)
    assert script.started == [1, 2] and cast(AnalysisResult, instance.shown).coverage.shots == (1, 2)
    explorer.stop_live(save=False)
    window.close_plots()
    explorer.close_cleanup()
