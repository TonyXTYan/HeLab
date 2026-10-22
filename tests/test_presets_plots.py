"""Presets and plots reopening (helab/views/plots/presets.py, arrangement.py): script presets in a
plot's settings page, arrangement presets of one folder (its plots, their places, Live once the
data shows), and the plots that reopen at start, each running on its folder's data from RAM or a
local cached read only, never the folder."""
from __future__ import annotations

import json
import math
import sys
import time
from typing import Any, Iterator, List, Optional, cast

import numpy as np
import pytest
from PyQt6 import sip
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QDockWidget, QLabel, QMainWindow, QMenu, QWidget
from pytestqt.qtbot import QtBot

from helab.analysis.backends import backend_specs
from helab.analysis.dataset_view import DatasetView
from helab.analysis.follow import DELAY, EVERY, FOLLOW, live_specs
from helab.analysis.parameter_tree import parameter_of
from helab.analysis.parameters import ParameterSpec
from helab.analysis.presets import FORMAT, Arrangement, SavedPlot, ScriptPreset, ScriptPresets, ScriptRef, parse
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.runner import AnalysisRunner
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.utils.folder_cache import Dataset, FolderCache, get_folder_cache
from helab.utils.io_service import IOService
from helab.utils.settings_defaults import OPEN_PLOTS_SETTING, REOPEN_PLOTS_SETTING, read_setting
from helab.utils.settings_store import app_settings
from helab.views.plots.arrangement import FolderWait, PlotReopen, capture, open_arrangement
from helab.views.plots.dock import AnalysisDock
from helab.views.plots.instance import AnalysisInstance
from helab.views.plots.presets import (ArrangementPresets, PresetBar, arrangement_key,
                                       arrangement_names, read_arrangement, read_script_presets, script_key,
                                       write_arrangement, write_script_presets)
from helab.views.plots.script_tree import TreePanelWidget
from helab.views.plots.workspace import PlotWorkspace

ROWS = 10


def folder(name: str) -> str:
    return FolderCache.key(f"/data/root/{name}")


def dataset(name: str, shots: range) -> Dataset:
    data = {shot: np.full((ROWS, 3), float(shot)) for shot in shots}
    return Dataset(folder(name), f"sig-{name}", data,
                   {"fingerprint": [[shot, 100 + shot, 1_000 + shot] for shot in shots],
                    "bytes": sum(array.nbytes for array in data.values()), "loaded_at": time.time()}, 0)


class Counted(DatasetAnalysis):
    """A test script: its result is the shots it ran on and its settings."""

    runs: List[tuple[int, ...]] = []

    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata("Counted", "test", "Tests", __file__, "tests.counted", "1")

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def execute_action(self, action_name: str, **kwargs: Any) -> None:
        pass

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [ParameterSpec("bins", "Bins", "int", 10, (1, 100)),
                ParameterSpec("mode", "Mode", "choice", "counts", choices=("counts", "rate"))]

    def backends(self, action_name: str) -> tuple[str, ...]:
        return ("PyQtGraph", "Matplotlib")

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        Counted.runs.append(tuple(context.view.shots))
        return tuple(context.view.shots)

    def draw(self, result: AnalysisResult, backend: str, parent: Optional[QWidget] = None) -> QWidget:
        return self.render(result, parent)

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        label = QLabel(f"shots {list(result.data)}", parent)
        label.setObjectName("counted_plot")
        return label


class Plots(PlotWorkspace):
    def __init__(self, window: Window) -> None:
        super().__init__(window, notice=window.notices.append, closing=lambda: window.closing)
        self.window = window

    def current_dataset_view(self) -> DatasetView | None:
        return self.window.view


class Window(QMainWindow):
    """A plot area, Settings panel, RAM budget and Scripts panel (the bundled scripts and ``Counted``)."""

    def __init__(self, cache: FolderCache) -> None:
        super().__init__()
        self.closing = False
        self.view: Optional[DatasetView] = None
        self.notices: List[str] = []
        self.plots = Plots(self)
        self.plots.middle_mainwindow.resize(900, 600)
        self.plots.setup_ram_budget(cache, app_settings())
        self.scripts = TreePanelWidget(self.plots)
        self.scripts.script_manager.load_module(sys.modules[__name__])


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> Iterator[AnalysisRunner]:
    made = AnalysisRunner()
    monkeypatch.setattr("helab.views.plots.instance.get_analysis_runner", lambda: made)
    yield made
    made.stop()


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch) -> Iterator[FolderCache]:
    """A cache whose helpers never run: requests stay in ``service.pending``."""
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    made = get_folder_cache(service)
    made.max_data_bytes = 1 << 40
    yield made
    service.shutdown()


@pytest.fixture(autouse=True)
def no_disk_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """By default the disk cache is off (a test turns it on with ``disk_cache``)."""
    monkeypatch.setattr("helab.views.plots.arrangement.store_options", lambda: {})
    Counted.runs = []


def disk_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("helab.views.plots.arrangement.store_options", lambda: {"directory": "store"})


Windows = List[Window]


@pytest.fixture
def windows(qtbot: QtBot, runner: AnalysisRunner, cache: FolderCache) -> Iterator[Windows]:
    made: Windows = []
    yield made
    for window in made:
        window.closing = True
        window.plots.close_plots()
        if window.plots.ram_budget is not None:
            window.plots.ram_budget.detach()
        window.plots.detach()
        if not sip.isdeleted(window.plots.middle_mainwindow):
            window.plots.middle_mainwindow.close()
            window.plots.middle_mainwindow.deleteLater()


def new_window(qtbot: QtBot, cache: FolderCache, windows: Windows) -> Window:
    window = Window(cache)
    qtbot.addWidget(window)
    qtbot.addWidget(window.scripts)
    window.plots.middle_mainwindow.show()
    windows.append(window)
    return window


def bundled(window: Window) -> List[tuple[ScriptMetadata, DatasetAnalysis, str]]:
    """Every bundled script's actions (not the test's)."""
    manager = window.scripts.script_manager
    found = []
    for group in manager.get_groups():
        if group == "Tests":
            continue
        for metadata in manager.get_scripts_in_group(group):
            script_class = manager.get_script(metadata.script_id)
            assert script_class is not None
            script = script_class()
            assert isinstance(script, DatasetAnalysis)
            found += [(metadata, script, action) for action in script.get_actions()]
    assert len(found) >= 17
    return found


def waiting_plot(window: Window, cache: FolderCache, ref: ScriptRef, path: str = folder("run")) -> AnalysisInstance:
    """A plot of ``ref`` at its defaults, waiting for its folder's data (none anywhere): no run."""
    made = window.scripts.reopen_plot(full(window, ref, path), FolderWait(cache, path))
    assert isinstance(made, AnalysisInstance), made
    return made


def full(window: Window, ref: ScriptRef, path: str, **values: Any) -> SavedPlot:
    """A record of a plot of ``ref`` with every setting at its default but ``values``."""
    found = window.scripts.find_script(ref)
    assert not isinstance(found, str)
    script = found[1]
    backends = script.backends(ref.action)
    return SavedPlot(ref, path, values={spec.name: spec.default for spec in script.parameters(ref.action)} | values,
                     backend=backends[0] if len(backends) >= 2 else "",
                     live={spec.name: spec.default for spec in live_specs(script.live_policy(ref.action))})


def other_value(spec: ParameterSpec) -> Any:
    """A valid value of ``spec`` other than its default."""
    if spec.kind == "bool":
        return not spec.default
    if spec.kind == "choice":
        return next((choice for choice in spec.choices if choice != spec.default), spec.default)
    if spec.kind == "text":
        return "0, 0, 0.001"
    low, high = spec.limits if spec.limits is not None else (-math.inf, math.inf)
    default = float(spec.default)
    if spec.kind == "int":
        return int(default) + 1 if default + 1 <= high else int(default) - 1
    target = default + (0.5 if default + 0.5 <= high else -0.5) if math.isinf(high) or high - default > 1 else (
        (default + high) / 2 if high > default else (default + low) / 2)
    return float(f"{target:.4g}")


def set_values(instance: AnalysisInstance, values: dict[str, Any]) -> None:
    root = instance.parameter_root
    assert root is not None
    for spec in instance.script.parameters(instance.action):
        if spec.name in values:
            parameter_of(root, spec).setValue(values[spec.name])


def bar(instance: AnalysisInstance) -> PresetBar:
    assert instance.presets is not None
    return instance.presets


def changed_values(instance: AnalysisInstance) -> dict[str, Any]:
    values = {spec.name: other_value(spec) for spec in instance.script.parameters(instance.action)}
    set_values(instance, values)
    assert instance.values() == values  # (The tree holds them as given.)
    return values


# Script presets


def test_a_script_preset_round_trips_for_every_bundled_script(qtbot: QtBot, cache: FolderCache,
                                                               windows: Windows) -> None:
    """Save each bundled script's settings (every parameter changed from its default), restart,
    apply in a new plot: the same effective values and library."""
    window = new_window(qtbot, cache, windows)
    saved = {}
    for metadata, script, action in bundled(window):
        ref = ScriptRef.of(metadata.identity(), action, metadata.name)
        instance = waiting_plot(window, cache, ref)
        values = changed_values(instance)
        backends = script.backends(action)
        if len(backends) >= 2:
            parameter_of(cast(Any, instance.parameter_root), backend_specs(backends)[0]).setValue(backends[-1])
        presets = bar(instance)
        presets.ask_name = lambda *_: "mine"
        presets.save()
        assert presets.note.text() == "Saved preset “mine”"
        saved[ref] = (values, instance.backend())
        instance.close()
    # Restart: a new window reads them from the settings store.
    again = new_window(qtbot, cache, windows)
    for ref, (values, backend) in saved.items():
        instance = waiting_plot(again, cache, ref)
        presets = bar(instance)
        assert presets.combo.currentText() == "mine"
        presets.apply()
        assert instance.values() == values, ref.analysis_id
        assert instance.backend() == backend
        assert presets.note.text() == "Preset “mine” applied" and not presets.note.styleSheet()
        assert instance.preset_from[0] == "mine"
        instance.close()


def test_a_preset_is_shared_by_every_plot_of_the_script(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    ref = ScriptRef("tests.counted", "Plot", "1", "", "Counted")
    first, second = waiting_plot(window, cache, ref), waiting_plot(window, cache, ref)
    set_values(first, {"bins": 42})
    bar(first).ask_name = lambda *_: "42 bins"
    bar(first).save()
    assert [bar(second).combo.itemText(i) for i in range(bar(second).combo.count())] == ["42 bins"]
    bar(second).apply()
    assert second.values()["bins"] == 42
    # Delete asks first; No keeps it.
    bar(second).confirm = lambda *_: False
    bar(second).delete()
    assert read_script_presets(ref).names() == ["42 bins"]
    bar(second).confirm = lambda *_: True
    bar(second).delete()
    assert read_script_presets(ref).names() == [] and bar(first).combo.count() == 0
    assert not bar(first).apply_button.isEnabled()


def test_applying_a_preset_is_an_edit_and_names_what_doesnt_fit(qtbot: QtBot, cache: FolderCache,
                                                                 windows: Windows) -> None:
    """Incompatible values are named and leave the open plot's settings as they were; nothing reruns."""
    window = new_window(qtbot, cache, windows)
    ref = ScriptRef("tests.counted", "Plot", "1", "", "Counted")
    instance = waiting_plot(window, cache, ref)
    set_values(instance, {"bins": 7, "mode": "rate"})
    preset = ScriptPreset("old", ScriptRef("tests.counted", "Plot", "0", "", "Counted"),
                          {"bins": 500, "mode": "radial", "gone": 1}, "Bokeh", 1.0)
    write_script_presets(ref, ScriptPresets().with_preset(preset))
    presets = bar(instance)
    presets.combo.setCurrentText("old")
    runs = len(Counted.runs)
    presets.apply()
    assert instance.values() == {"bins": 7, "mode": "rate"}  # Left as they were.
    assert instance.backend() == "PyQtGraph"
    text = presets.note.text()
    assert text.startswith("Preset “old” applied · ⚠ 4 settings left as they were: Bins, Mode, gone, Library")
    assert text.endswith("saved with v0, now v1") and "color" in presets.note.styleSheet()
    tip = presets.note.toolTip()
    assert "Bins: saved 500 is outside 1 to 100" in tip and "Mode: saved “radial” is no longer a choice" in tip
    assert "gone: not a setting of this script now" in tip and "Library: saved “Bokeh” is no longer a choice" in tip
    assert len(Counted.runs) == runs and instance.waiting()


def test_corrupt_script_presets_are_named_and_replaced_only_when_asked(qtbot: QtBot, cache: FolderCache,
                                                                        windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    ref = ScriptRef("tests.counted", "Plot", "1", "", "Counted")
    app_settings().setValue(script_key(ref), "{broken")
    instance = waiting_plot(window, cache, ref)
    presets = bar(instance)
    assert presets.note.text().startswith("⚠ Counted's saved presets can't be read (not valid JSON")
    assert not presets.combo.isEnabled()
    presets.ask_name = lambda *_: "new"
    presets.confirm = lambda *_: False
    presets.save()
    assert read_setting(app_settings(), script_key(ref)) == "{broken"  # Left as it was.
    presets.confirm = lambda *_: True
    presets.save()
    assert read_script_presets(ref).names() == ["new"]


# Arrangements: placement, and reopening at start


def test_placement_round_trips(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    """Two plots tabbed together (the second in front), one on its own and one floating come back
    so, with their numbers, settings section and the area's saved layout."""
    window = new_window(qtbot, cache, windows)
    ref = ScriptRef("tests.counted", "Plot", "1", "", "Counted")
    plots = [waiting_plot(window, cache, ref) for _ in range(4)]
    area = window.plots.middle_mainwindow
    docks = [cast(AnalysisDock, plot.dock_widget) for plot in plots]
    # As opened: all tabbed together. Make two groups and a floating plot.
    area.removeDockWidget(docks[2])
    area.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, docks[2])
    docks[2].show()
    docks[3].setFloating(True)
    docks[3].settings.open_width = 333
    docks[1].raise_()
    qtbot.wait(50)
    arrangement = capture(window.plots, plots)
    assert [(plot.group, plot.floating, plot.instance_id) for plot in arrangement.plots] == [
        (0, False, "1"), (0, False, "2"), (1, False, "3"), (2, True, "4")]
    assert [plot.front for plot in arrangement.plots[:2]] == [False, True]
    assert arrangement.plots[3].settings_width == 333 and arrangement.dock_state
    again = new_window(qtbot, cache, windows)
    opened, failed = open_arrangement(again.scripts, cache, parse(arrangement.dumps()), keep_ids=True)
    assert failed == []
    new = [cast(AnalysisDock, instance.dock_widget) for instance, _ in opened]
    new_area = again.plots.middle_mainwindow
    qtbot.wait(50)
    assert [instance.instance_id for instance, _ in opened] == ["1", "2", "3", "4"]
    assert new_area.tabifiedDockWidgets(new[0]) == [new[1]] and not new_area.tabifiedDockWidgets(new[2])
    assert new[3].isFloating() and not new[2].isFloating()
    assert new_area.dockWidgetArea(new[2]) == Qt.DockWidgetArea.RightDockWidgetArea
    assert new[3].settings.open_width == 333
    assert not new[1].visibleRegion().isEmpty() and new[0].visibleRegion().isEmpty()  # The front tab
    assert again.scripts.reopen_plot(arrangement.plots[0], FolderWait(cache, folder("run"))) is not None
    assert again.scripts.instances()[-1].instance_id == "5"  # Numbering goes on after them.


def test_reopened_plots_keep_every_bundled_scripts_settings_library_and_live_group(
        qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    expected = []
    for metadata, script, action in bundled(window):
        instance = waiting_plot(window, cache, ScriptRef.of(metadata.identity(), action, metadata.name))
        values = changed_values(instance)
        root = cast(Any, instance.parameter_root)
        backends = script.backends(action)
        if len(backends) >= 2:
            parameter_of(root, backend_specs(backends)[0]).setValue(backends[-1])
        live = {FOLLOW: False, EVERY: 7, DELAY: 1.5}
        for spec in live_specs(instance.policy):
            parameter_of(root, spec).setValue(live[spec.name])
        expected.append((values, instance.backend(), instance.live_values()))
    reopen = PlotReopen(window.plots, window.scripts)
    reopen.quit()
    text = read_setting(app_settings(), OPEN_PLOTS_SETTING)
    assert json.loads(text)["format"] == FORMAT and len(json.loads(text)["plots"]) == len(expected)
    # Restart.
    again = new_window(qtbot, cache, windows)
    restored = PlotReopen(again.plots, again.scripts).restore()
    assert len(restored) == len(expected) and again.notices == []
    for instance, (values, backend, live) in zip(restored, expected):
        assert instance.values() == values, instance.metadata.analysis_id
        assert instance.backend() == backend and instance.live_values() == live
        assert instance.waiting() and not instance.follow.on  # Follow Live off: pinned.
        assert bar(instance).note.text() == ""  # Everything restored: nothing to say.


def test_reopen_runs_from_ram_without_any_request(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    entry = dataset("ram", range(1, 4))
    cache.datasets[(entry.path, entry.signature, entry.epoch)] = entry
    before = list(cache.service.pending)
    record = Arrangement((SavedPlot(ScriptRef("tests.counted", "Plot", "1"), entry.path, values={"bins": 3}),))
    app_settings().setValue(OPEN_PLOTS_SETTING, record.dumps())
    [instance] = PlotReopen(window.plots, window.scripts).restore()
    qtbot.waitUntil(lambda: instance.shown is not None, timeout=10_000)
    assert Counted.runs == [(1, 2, 3)] and instance.values()["bins"] == 3
    assert list(cache.service.pending) == before  # Nothing asked of any helper.


def test_reopen_reads_the_disk_cache_only(qtbot: QtBot, cache: FolderCache, windows: Windows,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    disk_cache(monkeypatch)
    window = new_window(qtbot, cache, windows)
    path = folder("disk")
    record = Arrangement((SavedPlot(ScriptRef("tests.counted", "Plot", "1"), path),
                          SavedPlot(ScriptRef("tests.counted", "Plot", "1"), path)))
    app_settings().setValue(OPEN_PLOTS_SETTING, record.dumps())
    before = set(map(id, cache.service.pending))
    first, second = PlotReopen(window.plots, window.scripts).restore()
    asked = [request for request in cache.service.pending if id(request) not in before]
    assert [(request.operation, request.path) for request in asked] == [("cached", path)]  # One read, shared.
    assert asked[0].payload["allow_large"] is False and asked[0].payload["cache"] == {"directory": "store"}
    message = cast(QLabel, cast(QDockWidget, first.dock_widget).widget())
    assert message.text() == "Reading disk's data from the disk cache…"
    job = cache.jobs[("cached", path)]
    for request in list(job.subscribers.values()):
        cache.resultReady.emit(request, {"kind": "loaded", "dataset": dataset("disk", range(1, 3))})
    qtbot.waitUntil(lambda: first.shown is not None and second.shown is not None, timeout=10_000)
    assert Counted.runs == [(1, 2), (1, 2)]
    assert all(request.operation == "cached" for request in cache.service.pending if id(request) not in before)


def test_reopen_without_data_waits_for_a_tabs_load(qtbot: QtBot, cache: FolderCache, windows: Windows,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """No data in RAM and no cached data: the plot waits, saying so, asks nothing, and runs when
    a tab's load brings the folder's data."""
    disk_cache(monkeypatch)
    window = new_window(qtbot, cache, windows)
    path = folder("later")
    app_settings().setValue(OPEN_PLOTS_SETTING, Arrangement(
        (SavedPlot(ScriptRef("tests.counted", "Plot", "1"), path),)).dumps())
    before = set(map(id, cache.service.pending))
    [instance] = PlotReopen(window.plots, window.scripts).restore()
    assert [request.operation for request in cache.service.pending if id(request) not in before] == ["cached"]
    job = cache.jobs[("cached", path)]
    for request in list(job.subscribers.values()):
        cache.resultReady.emit(request, {"kind": "error", "message": "No cached data for this folder"})
    message = cast(QLabel, cast(QDockWidget, instance.dock_widget).widget())
    assert message.text() == "Waiting for later's data: select it to load"
    assert "waiting for its data" in instance._title() and instance.waiting()
    assert Counted.runs == []
    # A tab's normal load stores the folder's data: the plot runs.
    entry = dataset("later", range(5, 7))
    cache.datasets[(entry.path, entry.signature, entry.epoch)] = entry
    cache.datasetChanged.emit(entry.path)
    qtbot.waitUntil(lambda: instance.shown is not None, timeout=10_000)
    assert Counted.runs == [(5, 6)] and not instance.waiting()


def test_reopen_with_the_disk_cache_off_asks_nothing(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    app_settings().setValue(OPEN_PLOTS_SETTING, Arrangement(
        (SavedPlot(ScriptRef("tests.counted", "Plot", "1"), folder("ramonly")),)).dumps())
    before = list(cache.service.pending)
    [instance] = PlotReopen(window.plots, window.scripts).restore()
    assert list(cache.service.pending) == before and instance.waiting()
    assert instance.status_label.text() == "Waiting for ramonly's data: select it to load"
    # Rerun looks again (deliberately): still nothing, still no request of the folder.
    instance.run()
    assert list(cache.service.pending) == before and Counted.runs == []


def test_a_plot_whose_script_isnt_loaded_is_named_once(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    record = Arrangement((SavedPlot(ScriptRef("user.gone", "Plot", "1", "", "Gone"), folder("x")),
                          SavedPlot(ScriptRef("tests.counted", "Other", "1", "", "Counted"), folder("x")),
                          SavedPlot(ScriptRef("tests.counted", "Plot", "1"), folder("x"))))
    text = json.loads(record.dumps())
    text["plots"].append({"script": {"analysis_id": "broken"}})
    app_settings().setValue(OPEN_PLOTS_SETTING, json.dumps(text))
    opened = PlotReopen(window.plots, window.scripts).restore()
    assert len(opened) == 1
    assert window.notices == [
        "Not reopened: Gone (its script isn't loaded (Load Scripts… its folder, then open it again)); "
        "Counted › Other (its script has no “Other” now); a plot (no script action)"]
    # The record now holds the plot that opened only.
    assert len(parse(read_setting(app_settings(), OPEN_PLOTS_SETTING)).plots) == 1


def test_a_reopened_plot_names_settings_that_dont_fit(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    app_settings().setValue(OPEN_PLOTS_SETTING, Arrangement((SavedPlot(
        ScriptRef("tests.counted", "Plot", "0"), folder("x"), values={"bins": 1000, "mode": "rate"},
        backend="Matplotlib"),)).dumps())
    [instance] = PlotReopen(window.plots, window.scripts).restore()
    assert instance.values() == {"bins": 10, "mode": "rate"} and instance.backend() == "Matplotlib"
    note = bar(instance).note
    assert note.text() == ("Reopened · ⚠ 4 settings at the script's defaults: Bins, Follow Live, Rerun every N new "
                           "shots, Wait after a run · saved with v0, now v1")
    assert "Bins: saved 1,000 is outside 1 to 100" in note.toolTip()


def test_an_unreadable_reopen_record_is_named(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    app_settings().setValue(OPEN_PLOTS_SETTING, '{"format": 99, "plots": []}')
    assert PlotReopen(window.plots, window.scripts).restore() == []
    assert window.notices == ["The plots open last time can't be reopened: their record can't be read "
                              "(saved by a newer HeLab (format 99; this HeLab reads 1))"]


def test_reopening_can_be_turned_off(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    settings = app_settings()
    settings.setValue(OPEN_PLOTS_SETTING, Arrangement(
        (SavedPlot(ScriptRef("tests.counted", "Plot", "1"), folder("x")),)).dumps())
    settings.setValue(REOPEN_PLOTS_SETTING, False)
    assert PlotReopen(window.plots, window.scripts).restore() == []
    assert window.scripts.instances() == []


def test_plots_opening_and_closing_are_recorded(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    PlotReopen(window.plots, window.scripts)
    ref = ScriptRef("tests.counted", "Plot", "1")
    first = waiting_plot(window, cache, ref)
    waiting_plot(window, cache, ref, folder("y"))
    assert [plot.path for plot in parse(read_setting(app_settings(), OPEN_PLOTS_SETTING)).plots] == [
        folder("run"), folder("y")]
    first.close()
    assert [plot.path for plot in parse(read_setting(app_settings(), OPEN_PLOTS_SETTING)).plots] == [folder("y")]


# Arrangement presets


class Model(QObject):
    activityChanged = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.nodes: dict[str, Any] = {}
        self.cached = True  # Whether the folder has a disk cache (it loads at once)
        self.cache = self

    def disk_cached(self, path: str) -> bool:
        return self.cached


def node(error: str = "", txy: int = 0) -> Any:
    """A listed folder's row: its error, or how many TXY files it has."""
    return type("Node", (), {"error": error, "report": None if error else "listed", "txy_count": txy})()


class Explorer(QObject):
    """What applying an arrangement uses of a tab (``FolderExplorer``)."""

    dataLoaded = pyqtSignal(str)
    loadStateChanged = pyqtSignal()
    liveChanged = pyqtSignal()

    def __init__(self, path: str) -> None:
        super().__init__()
        self.model = Model()
        self.closed = False
        self.selected_path_globally = self.view_path = path
        self.folder_opened_path: Optional[str] = None
        self.folder_opened_data: Optional[Any] = None
        self.loading = False
        self.load_path: Optional[str] = None
        self.load_waiting = self.settling = False
        self.load_error = ""
        self.live: Optional[Any] = None
        self.calls: List[tuple[str, Any]] = []
        self.unavailable = "Wait for it to finish loading"

    def open_to_path(self, path: str) -> None:
        self.calls.append(("open_to_path", path))
        self.selected_path_globally = self.view_path = path

    def load_to_ram_cache(self, path: str, *, dwell: bool = True, explicit: bool = False) -> bool:
        self.calls.append(("load", (path, dwell, explicit)))
        self.loading, self.load_path = True, path
        return True

    def large_state(self, path: Optional[str]) -> Optional[tuple[int, bool]]:
        return None

    def live_unavailable(self, path: str) -> str:
        return self.unavailable

    def start_live(self) -> bool:
        self.calls.append(("start_live", self.selected_path_globally))
        if self.unavailable:
            return False
        self.live = type("Session", (), {"path": self.selected_path_globally})()
        return True

    def show_data(self, data: Any = "data") -> None:
        """The tab's load ended and its data shows."""
        self.loading = False
        self.folder_opened_path, self.folder_opened_data = self.selected_path_globally, data
        self.unavailable = ""
        self.dataLoaded.emit(self.selected_path_globally)


def presets_for(window: Window, explorer: Explorer, cache: FolderCache) -> ArrangementPresets:
    presets = ArrangementPresets(window.plots, window.scripts, lambda: cast(Any, explorer), window, cache)
    presets.confirm = lambda *_: True
    return presets


def test_an_arrangement_preset_round_trips_every_bundled_script(qtbot: QtBot, cache: FolderCache,
                                                                windows: Windows) -> None:
    """Save the folder, Live and a plot of every bundled script (settings changed); restart;
    apply: the folder is selected and loaded deliberately, the same plots open with the same
    values, and Live starts once the data shows."""
    window = new_window(qtbot, cache, windows)
    path = folder("run")
    explorer = Explorer(path)
    explorer.folder_opened_path, explorer.folder_opened_data = path, "data"
    explorer.live = type("Session", (), {"path": path})()
    expected = []
    for metadata, script, action in bundled(window):
        instance = waiting_plot(window, cache, ScriptRef.of(metadata.identity(), action, metadata.name), path)
        expected.append((metadata.analysis_id, changed_values(instance), instance.backend()))
    other = waiting_plot(window, cache, ScriptRef("tests.counted", "Plot", "1"), folder("elsewhere"))
    presets = presets_for(window, explorer, cache)
    asked: List[str] = []

    def ask(parent: Optional[QWidget], title: str, label: str, text: str) -> str:
        asked.append(label)
        return "all plots"

    presets.ask_name = ask
    saved = presets.save()
    assert saved is not None and saved.folder == path and saved.live
    assert asked == [f"Save run with its {len(expected)} plots (not the 1 of other folders) as:"]
    assert arrangement_names() == ["all plots"]
    other.close()
    # Restart: another window, a tab elsewhere.
    again = new_window(qtbot, cache, windows)
    tab = Explorer(folder("somewhere"))
    opened = presets_for(again, tab, cache).apply("all plots")
    assert tab.calls[:2] == [("open_to_path", path), ("load", (path, False, True))]
    assert [(instance.metadata.analysis_id, instance.values(), instance.backend()) for instance in opened] == expected
    assert all(instance.path == path and instance.waiting() for instance in opened)
    assert ("start_live", path) not in tab.calls  # Not before the data shows.
    tab.loadStateChanged.emit()
    assert ("start_live", path) not in tab.calls
    tab.show_data()
    assert tab.calls[-1] == ("start_live", path) and tab.live is not None
    assert again.notices[-1] == "Preset “all plots”: Live on for run"


def test_applying_replaces_open_plots_after_asking(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    ref = ScriptRef("tests.counted", "Plot", "1")
    write_arrangement("one", Arrangement((SavedPlot(ref, folder("a"), values={"bins": 2}),), folder("a")))
    kept = waiting_plot(window, cache, ref, folder("b"))
    explorer = Explorer(folder("b"))
    presets = presets_for(window, explorer, cache)
    presets.confirm = lambda *_: False
    assert presets.apply("one") == [] and not kept.is_closed and explorer.calls == []
    presets.confirm = lambda *_: True
    [opened] = presets.apply("one")
    assert kept.is_closed and opened.values()["bins"] == 2 and opened.path == folder("a")


def test_live_is_never_forced(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    """Live can't start (the load failed): the preset says why, and stops trying."""
    window = new_window(qtbot, cache, windows)
    write_arrangement("live", Arrangement((), folder("a"), live=True))
    explorer = Explorer(folder("b"))
    presets_for(window, explorer, cache).apply("live")
    explorer.loading, explorer.load_error = False, "Load failed — Retry"
    explorer.unavailable = "Select a folder with loaded data, or with no shots yet, to watch it for new shots"
    explorer.loadStateChanged.emit()
    assert window.notices == ["Preset “live”: Live not started: Load failed"]
    explorer.show_data()
    assert explorer.live is None  # Given up: never started later behind the user's back.


def test_a_folder_with_no_shots_isnt_loaded_and_live_waits_for_its_listing(
        qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    path = folder("empty")
    write_arrangement("first shot", Arrangement((), path, live=True))
    explorer = Explorer(folder("b"))
    explorer.model.cached = False
    presets_for(window, explorer, cache).apply("first shot")
    assert explorer.calls == [("open_to_path", path)]  # Not loaded, Live not tried: not listed yet.
    explorer.model.nodes[path] = node(txy=0)
    explorer.unavailable = ""  # Listed with no TXY files: Live may watch it from no shots.
    explorer.model.activityChanged.emit()
    assert explorer.calls == [("open_to_path", path), ("start_live", path)] and explorer.live is not None


def test_a_listed_folder_with_shots_loads_deliberately(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    path = folder("shots")
    write_arrangement("plain", Arrangement((), path))
    explorer = Explorer(folder("b"))
    explorer.model.cached = False
    presets_for(window, explorer, cache).apply("plain")
    explorer.model.nodes[path] = node(txy=3)
    explorer.model.activityChanged.emit()
    assert explorer.calls == [("open_to_path", path), ("load", (path, False, True))]


def test_another_folder_selected_cancels_live(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    write_arrangement("live", Arrangement((), folder("a"), live=True))
    explorer = Explorer(folder("b"))
    presets_for(window, explorer, cache).apply("live")
    explorer.selected_path_globally = folder("c")
    explorer.show_data()
    assert explorer.live is None and window.notices == ["Preset “live”: Live not started: another folder was selected"]


def test_a_missing_folder_is_named_and_its_plots_wait(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    path = folder("unmounted")
    write_arrangement("gone", Arrangement((SavedPlot(ScriptRef("tests.counted", "Plot", "1"), path),), path))
    explorer = Explorer(folder("b"))
    explorer.model.cached = False
    [plot] = presets_for(window, explorer, cache).apply("gone")
    explorer.model.nodes[path] = node("No such folder — Retry")
    explorer.model.activityChanged.emit()
    assert ("load", (path, False, True)) not in explorer.calls
    assert window.notices == ["Preset “gone”: unmounted can't be opened now (No such folder): its plots wait for "
                              "its data"]
    assert plot.waiting()


def test_a_missing_script_and_a_changed_script_preset_are_named(qtbot: QtBot, cache: FolderCache,
                                                                windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    ref = ScriptRef("tests.counted", "Plot", "1", "", "Counted")
    write_script_presets(ref, ScriptPresets().with_preset(ScriptPreset("p", ref, {"bins": 3}, "", 5.0)))
    saved = full(window, ref, folder("a"), bins=4)
    write_arrangement("mixed", Arrangement((
        SavedPlot(ScriptRef("user.gone", "Plot", "1", "", "Gone"), folder("a")),
        SavedPlot(saved.script, saved.path, values=saved.values, backend=saved.backend, live=saved.live,
                  preset="p", preset_saved_at=1.0)), folder("a")))
    [plot] = presets_for(window, Explorer(folder("a")), cache).apply("mixed")
    assert plot.values()["bins"] == 4  # The arrangement's own values.
    assert bar(plot).note.text() == "Preset “mixed” · preset “p” changed since: this arrangement's values are used"
    assert window.notices[0].startswith("Preset “mixed”: not opened: Gone (its script isn't loaded")


def test_a_corrupt_arrangement_preset_is_named_and_kept(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    app_settings().setValue(arrangement_key("bad/one"), "{nope")
    write_arrangement("good", Arrangement((), folder("a")))
    presets = presets_for(window, Explorer(folder("a")), cache)
    warned: List[str] = []
    presets.warn = lambda title, text: warned.append(text)
    assert presets.apply("bad/one") == []
    assert warned[0].startswith("The preset “bad/one” can't be read (not valid JSON")
    menu = QMenu()
    presets.fill_menu(menu)
    actions = [action for action in menu.actions() if not action.isSeparator()]
    texts = [action.text() for action in actions]
    assert texts[:3] == ["Save Folder and Plots as Preset…", "⚠ bad/one (can't be read)", "good"]
    assert not actions[1].isEnabled() and "not valid JSON" in actions[1].toolTip()
    assert read_setting(app_settings(), arrangement_key("bad/one")) == "{nope"
    # Delete asks first.
    presets.confirm = lambda *_: False
    assert not presets.delete("good") and arrangement_names() == ["bad/one", "good"]
    presets.confirm = lambda *_: True
    assert presets.delete("good") and arrangement_names() == ["bad/one"]
    with pytest.raises(Exception):
        read_arrangement("good")
