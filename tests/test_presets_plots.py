"""Presets and plots reopening (helab/views/plots/presets.py, arrangement.py): script presets in a
plot's settings page, arrangement presets of one folder (its plots, their places, Live once the
data shows), and the plots that reopen at start, each running on its folder's data from RAM or a
local cached read only, never the folder."""
from __future__ import annotations

import json
import math
from dataclasses import replace as dataclass_replace
import sys
import time
from typing import Any, Callable, Iterator, List, Optional, cast

import numpy as np
import pytest
from PyQt6 import sip
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QDockWidget, QLabel, QMainWindow, QMenu, QMessageBox, QWidget
from pytestqt.qtbot import QtBot

from helab.analysis.backends import BACKEND, backend_specs
from helab.analysis.dataset_view import DatasetView
from helab.analysis.follow import DELAY, EVERY, FOLLOW, live_specs
from helab.analysis.parameter_tree import parameter_of
from helab.analysis.parameters import ParameterSpec
from helab.analysis.presets import FORMAT, Arrangement, SavedPlot, ScriptPreset, ScriptPresets, ScriptRef, dumps, parse
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.runner import AnalysisRunner
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.utils.folder_cache import PRESET_FOUND, Dataset, FolderCache, get_folder_cache
from helab.utils.io_service import IOService
from helab.utils.settings_defaults import OPEN_PLOTS_SETTING, REOPEN_PLOTS_SETTING, read_setting
from helab.utils.settings_store import app_settings
from helab.views.plots.arrangement import FolderWait, PlotReopen, capture, open_arrangement
from helab.views.plots.dock import AnalysisDock
from helab.views.plots.instance import AnalysisInstance
from helab.views.plots.presets import (ARRANGEMENT, SCRIPT, ArrangementPresets, PresetBar, arrangement_names, preset_store,
                                       read_arrangement, read_script_presets, script_scope, write_arrangement,
                                       write_script_preset)
from helab.views.plots.script_tree import TreePanelWidget
from helab.views.plots.workspace import PlotWorkspace

ROWS = 10


@pytest.fixture(autouse=True)
def fresh_presets(qtbot: QtBot) -> Iterator[None]:
    """The app's FolderCache lasts the worker's run: each test starts with no presets known, and
    its preset helpers end with it (their store is the test's own)."""
    store = preset_store()
    store.presets.clear()
    store.presets_unsaved.clear()
    store.presets_conflicts.clear()
    store._presets_unknown.clear()
    store.presets_read, store.presets_error, store._store = False, "", (0.0, "")
    # As after startup: the store's presets read (a test of the time before says so).
    store.read_presets()
    qtbot.waitUntil(lambda: store.presets_read and not store._preset_jobs, timeout=30_000)
    yield
    qtbot.waitUntil(lambda: store.service.closed or not store._preset_jobs, timeout=30_000)


def stored(qtbot: QtBot) -> None:
    """Wait for the store to have the presets saved so far, and to have answered."""
    store = preset_store()
    qtbot.waitUntil(lambda: store.presets_read and not store._preset_jobs, timeout=30_000)


def restart_presets(qtbot: QtBot) -> FolderCache:
    """HeLab quits once the presets are saved, and starts again: a new app FolderCache, which
    knows only what it reads from the store."""
    from helab.utils.io_service import get_io_service
    stored(qtbot)
    get_io_service().shutdown()
    store = preset_store()
    assert not store.presets and store.presets_note() == "Reading saved presets…"
    store.read_presets()
    stored(qtbot)
    return store


def folder(name: str) -> str:
    return FolderCache.key(f"/data/root/{name}")


def dataset(name: str, shots: range) -> Dataset:
    data = {shot: np.full((ROWS, 3), float(shot)) for shot in shots}
    return Dataset(folder(name), f"sig-{name}", data,
                   {"fingerprint": [[shot, 100 + shot, 1_000 + shot] for shot in shots],
                    "bytes": sum(array.nbytes for array in data.values()), "loaded_at": time.time()}, 0)


def helper_request(cache: FolderCache, operation: str, path: str) -> Any:
    """The request of the helper running ``path``'s ``operation`` job."""
    job = cache.jobs[(operation, path)]
    return next(r for r in cache.service.pending if r.owner == job.owner)


def helper_says(cache: FolderCache, operation: str, path: str, *events: dict[str, Any]) -> None:
    """The helper of ``path``'s ``operation`` job sends ``events``, as FolderCache gets them."""
    send(cache, helper_request(cache, operation, path), *events)


def send(cache: FolderCache, request: Any, *events: dict[str, Any]) -> None:
    """``request``'s helper sends ``events`` (also after FolderCache has let its job go)."""
    for event in events:
        cache.service.resultReady.emit(request, event)
    if events and events[-1]["kind"] in ("done", "error") and request in cache.service.pending:
        cache.service.pending.remove(request)  # Its helper has ended (as IOService's dispatch would see).


def read_events(shots: range, signature: str) -> List[dict[str, Any]]:
    """A load's or cached read's events for ``shots``, ending ``loaded`` then ``done``."""
    return [*({"kind": "shot", "shot": shot, "array": np.full((ROWS, 3), float(shot))} for shot in shots),
            {"kind": "loaded", "signature": signature, "bytes": ROWS * 3 * 8 * len(shots), "rows": ROWS * len(shots),
             "files": len(shots), "problematic": [], "fingerprint": [[shot, 200 + shot, 2_000 + shot] for shot in shots]},
            {"kind": "done"}]


def load_through_the_cache(cache: FolderCache, path: str, shots: range, signature: str,
                           allow_missing: bool = True, owner: str = "tab-owner") -> Dataset:
    """A tab's load of ``path`` as FolderCache handles it (its helper's events, in their order); with
    ``allow_missing``, reading the folder as it is now (Load as it is now). The dataset it kept."""
    assert cache.submit(owner, 0, path, "load", {"allow_missing": allow_missing}, priority=True)
    helper_says(cache, "load", path, *read_events(shots, signature))
    found = cache.latest_dataset(path)
    assert found is not None and found.signature == signature
    return found


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


def test_a_script_preset_saved_is_there_after_a_restart(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    ref = ScriptRef("tests.counted", "Plot", "1", "", "Counted")
    first = waiting_plot(window, cache, ref)
    set_values(first, {"bins": 42, "mode": "rate"})
    bar(first).ask_name = lambda *_: "42 bins"
    bar(first).save()
    assert bar(first).note.text() == "Saved preset “42 bins”"
    first.close()
    restart_presets(qtbot)
    again = new_window(qtbot, cache, windows)
    second = waiting_plot(again, cache, ref)
    assert bar(second).combo.currentText() == "42 bins"
    bar(second).apply()
    assert second.values() == {"bins": 42, "mode": "rate"}


def marked(instance: AnalysisInstance) -> dict[str, str]:
    """The settings marked as changed from the preset applied, with their tooltips."""
    root = cast(Any, instance.parameter_root)
    specs = [*instance.script.parameters(instance.action), *backend_specs(instance.script.backends(instance.action))]
    found = {}
    for spec in specs:
        items = list(parameter_of(root, spec).items.keys())
        assert items  # (The settings page's tree shows it.)
        if not items[0].icon(0).isNull():
            found[spec.name] = items[0].toolTip(0)
    return found


def test_settings_changed_from_the_applied_preset_are_marked(qtbot: QtBot, cache: FolderCache,
                                                             windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    ref = ScriptRef("tests.counted", "Plot", "1", "", "Counted")
    instance = waiting_plot(window, cache, ref)
    presets = bar(instance)
    set_values(instance, {"bins": 20})
    qtbot.wait(10)
    assert marked(instance) == {} and presets.changes_button.isHidden()  # No preset applied: nothing to say.
    presets.ask_name = lambda *_: "p"
    presets.save()
    assert marked(instance) == {} and presets.changes_button.isHidden()
    set_values(instance, {"bins": 30})
    qtbot.waitUntil(lambda: not presets.changes_button.isHidden(), timeout=2_000)
    assert marked(instance) == {"bins": "Changed from preset “p”, which has 20"}
    assert presets.changes_button.text() == "Save 1 change" and presets.save_to_action.text() == "Save to preset “p”"
    parameter_of(cast(Any, instance.parameter_root), backend_specs(("PyQtGraph", "Matplotlib"))[0]).setValue("Matplotlib")
    qtbot.waitUntil(lambda: presets.changes_button.text() == "Save 2 changes", timeout=2_000)
    assert set(marked(instance)) == {"bins", BACKEND}
    # Save to preset "p" asks first.
    presets.confirm = lambda *_: False
    presets.save_to_action.trigger()
    assert read_script_presets(ref).presets["p"].values["bins"] == 20
    presets.confirm = lambda *_: True
    presets.save_to_action.trigger()
    saved = read_script_presets(ref).presets["p"]
    assert saved.values["bins"] == 30 and saved.backend == "Matplotlib"
    assert marked(instance) == {} and presets.changes_button.isHidden()
    # Save as new preset…: the new one is what changes are marked against.
    set_values(instance, {"mode": "rate"})
    qtbot.waitUntil(lambda: not presets.changes_button.isHidden(), timeout=2_000)
    presets.ask_name = lambda *_: "q"
    presets.save_new_action.trigger()
    assert presets.applied is not None and presets.applied.name == "q" and marked(instance) == {}
    # Back to the preset's value: unmarked; the preset deleted: nothing to compare with.
    set_values(instance, {"bins": 31})
    qtbot.waitUntil(lambda: bool(marked(instance)), timeout=2_000)
    set_values(instance, {"bins": 30})
    qtbot.waitUntil(lambda: not marked(instance), timeout=2_000)
    set_values(instance, {"bins": 32})
    qtbot.waitUntil(lambda: bool(marked(instance)), timeout=2_000)
    presets.combo.setCurrentText("q")
    presets.delete()
    assert presets.applied is None and marked(instance) == {} and presets.changes_button.isHidden()


def test_values_a_preset_holds_that_dont_fit_are_named_not_marked(qtbot: QtBot, cache: FolderCache,
                                                                   windows: Windows) -> None:
    """A preset with values the script doesn't accept (wrong types, nothing, a list) applies the
    rest, names those, and marks only accepted values that were changed afterwards."""
    window = new_window(qtbot, cache, windows)
    ref = ScriptRef("tests.counted", "Plot", "1", "", "Counted")
    instance = waiting_plot(window, cache, ref)
    data: dict[str, Any] = {"format": FORMAT, "presets": {"odd": {"format": FORMAT, "script": ref.to_json(), "saved_at": 1.0,
                                                  "values": {"bins": "many", "mode": "rate"}, "backend": None},
                                          "odder": {"format": FORMAT, "script": ref.to_json(), "saved_at": 1.0,
                                                    "values": {"bins": None, "mode": ["a"]}, "backend": [1]}}}
    preset_store().set_presets([(SCRIPT, script_scope(ref), name, json.dumps(entry))
                                for name, entry in data["presets"].items()])
    presets = bar(instance)
    presets.refresh()
    for name in ("odd", "odder"):
        presets.combo.setCurrentText(name)
        presets.apply()
        qtbot.wait(10)
        assert "Bins" in presets.note.text() and marked(instance) == {}
    presets.combo.setCurrentText("odd")
    presets.apply()
    assert instance.values() == {"bins": 10, "mode": "rate"}
    set_values(instance, {"bins": 11})  # Bins: never compared (the preset's value isn't one).
    qtbot.wait(20)
    assert marked(instance) == {}
    set_values(instance, {"mode": "counts"})
    qtbot.waitUntil(lambda: set(marked(instance)) == {"mode"}, timeout=2_000)


def test_another_plot_deleting_the_preset_clears_the_marks(qtbot: QtBot, cache: FolderCache,
                                                          windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    ref = ScriptRef("tests.counted", "Plot", "1", "", "Counted")
    first, second = waiting_plot(window, cache, ref), waiting_plot(window, cache, ref)
    bar(first).ask_name = lambda *_: "p"
    bar(first).save()
    set_values(first, {"bins": 50})
    qtbot.waitUntil(lambda: bool(marked(first)), timeout=2_000)
    bar(second).confirm = lambda *_: True
    bar(second).delete()
    assert marked(first) == {} and bar(first).applied is None


def test_applying_a_preset_is_an_edit_and_names_what_doesnt_fit(qtbot: QtBot, cache: FolderCache,
                                                                 windows: Windows) -> None:
    """Incompatible values are named and leave the open plot's settings as they were; nothing reruns."""
    window = new_window(qtbot, cache, windows)
    ref = ScriptRef("tests.counted", "Plot", "1", "", "Counted")
    instance = waiting_plot(window, cache, ref)
    set_values(instance, {"bins": 7, "mode": "rate"})
    preset = ScriptPreset("old", ScriptRef("tests.counted", "Plot", "0", "", "Counted"),
                          {"bins": 500, "mode": "radial", "gone": 1}, "Bokeh", 1.0)
    write_script_preset(preset)
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


def test_an_unreadable_script_preset_is_named_and_replaced_only_when_asked(qtbot: QtBot, cache: FolderCache,
                                                                           windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    ref = ScriptRef("tests.counted", "Plot", "1", "", "Counted")
    preset_store().set_presets([(SCRIPT, script_scope(ref), "broken", "{broken")])
    instance = waiting_plot(window, cache, ref)
    presets = bar(instance)
    assert presets.note.text().startswith("⚠ Preset “broken” can't be read (not valid JSON")
    assert not presets.combo.isEnabled()
    presets.ask_name = lambda *_: "new"
    presets.save()  # Another name: nothing to ask, and the unreadable one stays as it was.
    records = preset_store().preset_records(SCRIPT, script_scope(ref))
    assert records[(script_scope(ref), "broken")] == "{broken" and read_script_presets(ref).names() == ["new"]
    presets.ask_name = lambda *_: "broken"
    presets.confirm = lambda *_: False
    presets.save()
    assert preset_store().preset_records(SCRIPT, script_scope(ref))[(script_scope(ref), "broken")] == "{broken"
    presets.confirm = lambda *_: True
    presets.save()
    assert read_script_presets(ref).names() == ["broken", "new"]


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
    entry = load_through_the_cache(cache, folder("ram"), range(1, 4), "v1", allow_missing=False)
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
    helper_says(cache, "cached", path, *read_events(range(1, 3), "disk"))
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
    helper_says(cache, "cached", path, {"kind": "error", "message": "No cached data for this folder"})
    message = cast(QLabel, cast(QDockWidget, instance.dock_widget).widget())
    assert message.text() == "Waiting for later's data: select it to load"
    assert "waiting for its data" in instance._title() and instance.waiting()
    assert Counted.runs == []
    # A tab's normal load stores the folder's data: the plot runs.
    load_through_the_cache(cache, path, range(5, 7), "v1", allow_missing=False)
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


def recorded() -> List[str]:
    """The plots the reopen record holds (by script); none when it's empty."""
    text = read_setting(app_settings(), OPEN_PLOTS_SETTING)
    return [plot.script.analysis_id for plot in parse(text).plots] if text else []


def test_plots_that_cant_reopen_are_asked_about_once_and_kept_until_dropped(
        qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    """One question for every plot that can't reopen; until it's answered, and after Keep, they stay
    in the record (each on its own, after the open plots); Drop forgets them. A record that can't
    be read at all is only named."""
    window = new_window(qtbot, cache, windows)
    gone = SavedPlot(ScriptRef("user.gone", "Plot", "1", "", "Gone"), folder("x"), values={"a": 1}, group=0)
    other = SavedPlot(ScriptRef("tests.counted", "Other", "1", "", "Counted"), folder("x"), group=0)
    record = Arrangement((gone, other, SavedPlot(ScriptRef("tests.counted", "Plot", "1"), folder("x"))))
    text = json.loads(record.dumps())
    text["plots"].append({"script": {"analysis_id": "broken"}})
    app_settings().setValue(OPEN_PLOTS_SETTING, json.dumps(text))
    reopen = PlotReopen(window.plots, window.scripts)
    asked: List[List[str]] = []
    reopen.ask = asked.append
    opened = reopen.restore()
    assert len(opened) == 1
    assert asked == [["Gone (its script isn't loaded (Load Scripts… its folder, then open it again))",
                      "Counted › Other (its script has no “Other” now)"]]
    assert window.notices == ["Not reopened (their records can't be read): no script action"]
    # Not answered yet: kept, after the open plot, each in a tab group of its own.
    saved = parse(read_setting(app_settings(), OPEN_PLOTS_SETTING)).plots
    assert [plot.script.analysis_id for plot in saved] == ["tests.counted", "user.gone", "tests.counted"]
    assert [plot.group for plot in saved] == [0, 1, 2] and saved[1].values == {"a": 1} and saved[1].dock_name == ""
    reopen.answer(True)  # Keep: still there as plots open and close.
    opened[0].close()
    assert recorded() == ["user.gone", "tests.counted"]
    reopen.answer(False)  # Drop.
    assert recorded() == []


def test_the_keep_or_drop_question_doesnt_block_the_window(qtbot: QtBot, cache: FolderCache,
                                                            windows: Windows) -> None:
    """The real question (not a test stand-in): shown, not modal, and its Drop answers."""
    window = new_window(qtbot, cache, windows)
    window.show()
    app_settings().setValue(OPEN_PLOTS_SETTING, Arrangement(
        (SavedPlot(ScriptRef("user.gone", "Plot", "1", "", "Gone"), folder("x")),)).dumps())
    reopen = PlotReopen(window.plots, window.scripts)
    assert reopen.restore() == []
    box = reopen._question
    assert isinstance(box, QMessageBox)
    qtbot.waitUntil(box.isVisible, timeout=2_000)
    assert box.windowModality() == Qt.WindowModality.NonModal and not box.isModal()
    assert QApplication.activeModalWidget() is None
    assert "Gone (its script isn't loaded" in box.text() and recorded() == ["user.gone"]
    [drop] = [button for button in box.buttons() if button.text() == "Drop"]
    drop.click()
    assert recorded() == [] and reopen._question is None


def test_a_kept_plot_reopens_once_its_script_is_loaded(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    app_settings().setValue(OPEN_PLOTS_SETTING, Arrangement(
        (SavedPlot(ScriptRef("tests.counted", "Plot", "1"), folder("x")),)).dumps())
    # A start without the script: kept.
    first = PlotReopen(window.plots, window.scripts)
    first.scripts.script_manager._remove_script(next(
        meta.script_id for meta in window.scripts.script_manager.get_scripts_in_group("Tests")))
    first.ask = lambda names: None
    assert first.restore() == [] and recorded() == ["tests.counted"]
    first.quit()
    # The next start has it loaded again (as a Load Scripts… folder would).
    again = new_window(qtbot, cache, windows)
    asked: List[List[str]] = []
    reopen = PlotReopen(again.plots, again.scripts)
    reopen.ask = asked.append
    [instance] = reopen.restore()
    assert asked == [] and instance.waiting() and recorded() == ["tests.counted"]


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

    def stop_live(self, save: bool = True) -> None:
        self.calls.append(("stop_live", self.selected_path_globally))
        self.live = None

    def show_data(self, data: Any = "data") -> None:
        """The tab's load ended and its data shows."""
        self.loading = False
        self.folder_opened_path, self.folder_opened_data = self.selected_path_globally, data
        self.unavailable = ""
        self.dataLoaded.emit(self.selected_path_globally)


def presets_for(window: Window, explorer: Explorer, cache: FolderCache) -> ArrangementPresets:
    presets = ArrangementPresets(window.plots, window.scripts, lambda: cast(Any, explorer), window, cache)
    presets.confirm = lambda *_: True
    presets.replace_or_add = lambda *_: "replace"
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
    # Restart (the presets read from the store again): another window, a tab elsewhere.
    restart_presets(qtbot)
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
    questions: List[str] = []

    def answer(reply: Optional[str]) -> Callable[..., Optional[str]]:
        def ask(parent: Optional[QWidget], title: str, text: str) -> Optional[str]:
            questions.append(text)
            return reply
        return ask

    presets.replace_or_add = answer(None)  # Cancel
    assert presets.apply("one") == [] and not kept.is_closed and explorer.calls == []
    assert questions == ["“one” opens a with its 1 plot. Replace the 1 open plot, or Add the preset's beside it?"]
    presets.replace_or_add = answer("replace")
    [opened] = presets.apply("one")
    assert kept.is_closed and opened.values()["bins"] == 2 and opened.path == folder("a")


def test_applying_can_add_beside_the_open_plots(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    """Add: the open plots stay where they are; the preset's open beside them, numbered after them."""
    window = new_window(qtbot, cache, windows)
    ref = ScriptRef("tests.counted", "Plot", "1")
    first, second = waiting_plot(window, cache, ref, folder("a")), waiting_plot(window, cache, ref, folder("a"))
    area = window.plots.middle_mainwindow
    tabbed = area.tabifiedDockWidgets(cast(QDockWidget, first.dock_widget))
    arrangement = capture(window.plots, [first, second], folder=folder("a"))
    write_arrangement("pair", arrangement)
    presets = presets_for(window, Explorer(folder("b")), cache)
    presets.replace_or_add = lambda *_: "add"
    added = presets.apply("pair")
    assert not first.is_closed and not second.is_closed
    assert [instance.instance_id for instance in added] == ["3", "4"]
    assert area.tabifiedDockWidgets(cast(QDockWidget, first.dock_widget)) == tabbed  # Not moved.
    assert area.tabifiedDockWidgets(cast(QDockWidget, added[0].dock_widget)) == [added[1].dock_widget]
    assert len(window.scripts.instances()) == 4


def test_a_replaced_plots_dock_isnt_taken_for_a_new_one(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    """The plots an arrangement replaces are deleted later, with the names a recorded layout uses:
    the layout places the new plots, never those."""
    window = new_window(qtbot, cache, windows)
    ref = ScriptRef("tests.counted", "Plot", "1")
    first = waiting_plot(window, cache, ref, folder("a"))
    first_dock = first.dock_widget
    arrangement = capture(window.plots, [first], folder=folder("a"))
    write_arrangement("same", arrangement)
    assert first_dock is not None and first_dock.objectName() == "helab-plot-0"
    [opened] = presets_for(window, Explorer(folder("b")), cache).apply("same")
    new_dock = cast(QDockWidget, opened.dock_widget)
    assert new_dock.objectName() == "helab-plot-0" and first_dock.objectName() == ""
    assert window.plots.middle_mainwindow.dockWidgetArea(new_dock) != Qt.DockWidgetArea.NoDockWidgetArea


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
    write_script_preset(ScriptPreset("p", ref, {"bins": 3}, "", 5.0))
    saved = full(window, ref, folder("a"), bins=4)
    write_arrangement("mixed", Arrangement((
        SavedPlot(ScriptRef("user.gone", "Plot", "1", "", "Gone"), folder("a")),
        SavedPlot(saved.script, saved.path, values=saved.values, backend=saved.backend, live=saved.live,
                  preset="p", preset_saved_at=1.0)), folder("a")))
    stored(qtbot)
    [plot] = presets_for(window, Explorer(folder("a")), cache).apply("mixed")
    assert plot.values()["bins"] == 4  # The arrangement's own values.
    assert bar(plot).note.text() == "Preset “mixed” · preset “p” changed since: this arrangement's values are used"
    assert window.notices[0].startswith("Preset “mixed”: not opened: Gone (its script isn't loaded")


def test_a_corrupt_arrangement_preset_is_named_and_kept(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    preset_store().set_presets([(ARRANGEMENT, "", "bad/one", "{nope")])
    write_arrangement("good", Arrangement((), folder("a")))
    presets = presets_for(window, Explorer(folder("a")), cache)
    stored(qtbot)
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
    assert preset_store().preset_records(ARRANGEMENT)[("", "bad/one")] == "{nope"
    # Delete asks first.
    presets.confirm = lambda *_: False
    assert not presets.delete("good") and arrangement_names() == ["bad/one", "good"]
    presets.confirm = lambda *_: True
    assert presets.delete("good") and arrangement_names() == ["bad/one"]
    with pytest.raises(Exception):
        read_arrangement("good")


# Review findings (Flint, a74fd07)


def test_a_mismatched_folders_pinned_data_is_never_used(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    """A tab still pins data the folder no longer matches: a reopened plot doesn't run on it, nor on
    the disk cache; when a load matches the folder again (FolderCache lifts the mismatch before it
    publishes the new dataset), the plot runs on the new data, never the old pin."""
    window = new_window(qtbot, cache, windows)
    old = dataset("moved", range(1, 4))
    cache.retain("existing-tab", old)
    cache._mismatch(old.path, {"missing": [1]})
    assert old.path in cache.mismatched and cache.pins["existing-tab"] is old
    app_settings().setValue(OPEN_PLOTS_SETTING, Arrangement(
        (SavedPlot(ScriptRef("tests.counted", "Plot", "1"), old.path),)).dumps())
    before = list(cache.service.pending)
    [instance] = PlotReopen(window.plots, window.scripts).restore()
    instance.run()  # Deliberately too.
    qtbot.wait(20)
    assert Counted.runs == [] and instance.waiting() and list(cache.service.pending) == before
    assert instance.status_label.text() == ("moved's cached data doesn't match the folder: Review… it, or select it "
                                            "to load it as it is now")
    load_through_the_cache(cache, old.path, range(2, 4), "fresh")
    assert old.path not in cache.mismatched and cache.pins["existing-tab"] is old  # The old pin is still there.
    qtbot.waitUntil(lambda: instance.shown is not None, timeout=10_000)
    assert Counted.runs == [(2, 3)]


def test_a_cached_read_that_lands_while_the_folder_is_mismatched_is_refused(
        qtbot: QtBot, cache: FolderCache, windows: Windows, monkeypatch: pytest.MonkeyPatch) -> None:
    disk_cache(monkeypatch)
    window = new_window(qtbot, cache, windows)
    path = folder("raced")
    app_settings().setValue(OPEN_PLOTS_SETTING, Arrangement(
        (SavedPlot(ScriptRef("tests.counted", "Plot", "1"), path),)).dumps())
    [instance] = PlotReopen(window.plots, window.scripts).restore()
    read = helper_request(cache, "cached", path)
    mismatch_through_the_cache(cache, path, [1])  # Found by another check while the read was in flight.
    send(cache, read, *read_events(range(1, 4), "old"))
    qtbot.wait(20)
    assert Counted.runs == [] and instance.waiting()
    assert instance.status_label.text().startswith("raced's cached data doesn't match the folder")
    load_through_the_cache(cache, path, range(1, 3), "fresh")
    qtbot.waitUntil(lambda: instance.shown is not None, timeout=10_000)
    assert Counted.runs == [(1, 2)]


def test_a_cached_read_waiting_for_its_volume_is_asked_again(qtbot: QtBot, cache: FolderCache, windows: Windows,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    disk_cache(monkeypatch)
    window = new_window(qtbot, cache, windows)
    path = folder("external")
    app_settings().setValue(OPEN_PLOTS_SETTING, Arrangement(
        (SavedPlot(ScriptRef("tests.counted", "Plot", "1"), path),)).dumps())
    [instance] = PlotReopen(window.plots, window.scripts).restore()
    helper_says(cache, "cached", path, {"kind": "error", "message": "Volume not verified yet", "unverified": True})
    assert ("cached", path) not in cache.jobs and instance.waiting()
    cache.volumesVerified.emit()
    assert ("cached", path) in cache.jobs  # Asked again, through the local lane.
    helper_says(cache, "cached", path, *read_events(range(1, 3), "external"))
    qtbot.waitUntil(lambda: instance.shown is not None, timeout=10_000)
    assert Counted.runs == [(1, 2)]
    cache.volumesVerified.emit()  # Done waiting: nothing more is asked.
    assert ("cached", path) not in cache.jobs


def test_a_plain_cache_miss_isnt_asked_again_when_volumes_are_verified(
        qtbot: QtBot, cache: FolderCache, windows: Windows, monkeypatch: pytest.MonkeyPatch) -> None:
    disk_cache(monkeypatch)
    window = new_window(qtbot, cache, windows)
    path = folder("none")
    app_settings().setValue(OPEN_PLOTS_SETTING, Arrangement(
        (SavedPlot(ScriptRef("tests.counted", "Plot", "1"), path),)).dumps())
    PlotReopen(window.plots, window.scripts).restore()
    helper_says(cache, "cached", path, {"kind": "error", "message": "No cached data for this folder"})
    cache.volumesVerified.emit()
    assert ("cached", path) not in cache.jobs


def test_a_live_off_preset_turns_live_off_in_its_folder(qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    """Already at the preset's folder with Live on: the preset's Live off is applied, not skipped."""
    window = new_window(qtbot, cache, windows)
    path = folder("watched")
    write_arrangement("quiet", Arrangement((), path, live=False))
    explorer = Explorer(path)
    explorer.live = type("Session", (), {"path": path})()
    presets_for(window, explorer, cache).apply("quiet")
    assert ("open_to_path", path) not in explorer.calls and ("stop_live", path) in explorer.calls
    assert explorer.live is None and "Preset “quiet”: Live off for watched" in window.notices


def test_a_layout_that_cant_be_read_is_named_and_the_plots_still_open(
        qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    ref = ScriptRef("tests.counted", "Plot", "1")
    record = json.loads(Arrangement((SavedPlot(ref, folder("a"), group=0), SavedPlot(ref, folder("a"), group=0),
                                     SavedPlot(ref, folder("a"), group=1)), folder("a")).dumps())
    record["dock_state"] = "\u2603 not base64"
    arrangement = parse(json.dumps(record))
    assert arrangement.dock_state == "" and arrangement.layout_error == "its saved layout can't be read"
    assert parse(json.dumps({**record, "dock_state": 5})).layout_error == "its saved layout isn't text"
    # Reopen: the plots open in their tab groups, and it is said.
    app_settings().setValue(OPEN_PLOTS_SETTING, json.dumps(record))
    opened = PlotReopen(window.plots, window.scripts).restore()
    area = window.plots.middle_mainwindow
    assert len(opened) == 3 and area.tabifiedDockWidgets(cast(QDockWidget, opened[0].dock_widget)) == [
        opened[1].dock_widget]
    assert window.notices == ["The plots open last time reopened in their tab groups: its saved layout can't be read"]
    # An arrangement preset: applied all the same (folder, plots), and said.
    preset_store().set_presets([(ARRANGEMENT, "", "bad layout", json.dumps(record))])
    explorer = Explorer(folder("b"))
    applied = presets_for(window, explorer, cache).apply("bad layout")
    assert len(applied) == 3 and explorer.calls[:2] == [("open_to_path", folder("a")), ("load", (folder("a"), False, True))]
    assert window.notices[-1] == "Preset “bad layout”: its plots are in their tab groups: its saved layout can't be read"
    # Even a layout that slipped past the parser (base64 in name only) doesn't stop a restore.
    broken = dataclass_replace(arrangement, dock_state="\u2603")
    again = new_window(qtbot, cache, windows)
    assert len(open_arrangement(again.scripts, cache, broken)[0]) == 3


# Round 3: one rule, the folder's data is what FolderCache itself keeps (never a tab's pin alone)


def mismatch_through_the_cache(cache: FolderCache, path: str, missing: List[int]) -> None:
    """A check finds shots of ``path`` gone (its helper's ``shots_missing``): FolderCache lists the
    folder as mismatched and drops its data (a tab may still pin it)."""
    assert cache.submit("checker", 0, path, "load", {}, priority=True)
    helper_says(cache, "load", path, {"kind": "shots_missing", "missing": missing, "missing_count": len(missing)},
                {"kind": "error", "message": "Shots missing — Retry"})
    assert path in cache.mismatched


def list_through_the_cache(cache: FolderCache, path: str, signature: str) -> None:
    """A listing of ``path`` (its helper's entries, status, done): one with another signature than
    the last tells FolderCache the folder changed."""
    assert cache.submit(f"lister-{signature}", 0, path, "list", {}, priority=True, force=True)
    helper_says(cache, "list", path, {"kind": "entries", "entries": []},
                {"kind": "status", "status": "ok", "count": 1, "details": True, "raw": [1], "txy": [1],
                 "modified": 0, "signature": signature},
                {"kind": "done"})


def new_waiter(cache: FolderCache, path: str) -> tuple[FolderWait, List[DatasetView], List[str]]:
    wait = FolderWait(cache, path)
    found: List[DatasetView] = []
    noted: List[str] = []
    wait.found.connect(found.append)
    wait.noted.connect(noted.append)
    return wait, found, noted


@pytest.mark.parametrize("drop", ["mismatch, then a load, then evicted", "folder changed", "cleared"])
def test_a_waiter_made_after_the_cache_dropped_a_folders_data_never_takes_a_tabs_old_pin(
        qtbot: QtBot, cache: FolderCache, windows: Windows, monkeypatch: pytest.MonkeyPatch, drop: str) -> None:
    """A tab still pins the folder's old data; FolderCache has dropped it (and maybe more since): a
    waiter made afterwards, with no history, reads the disk cache (or waits), never the old pin."""
    disk_cache(monkeypatch)
    path = folder("dropped")
    old = load_through_the_cache(cache, path, range(1, 4), "v1", allow_missing=False)
    cache.retain("existing-tab", old)
    if drop == "mismatch, then a load, then evicted":
        mismatch_through_the_cache(cache, path, [1])
        fresh = load_through_the_cache(cache, path, range(2, 4), "fresh")  # Load as it is now
        assert path not in cache.mismatched and cache.latest_dataset(path) is fresh
        cache.evict_to(0)  # The fresh data, shown in no tab, leaves RAM.
        assert not cache.holds(fresh)
    elif drop == "folder changed":
        list_through_the_cache(cache, path, "v1")
        list_through_the_cache(cache, path, "v2")
    else:
        assert cache.submit("tab-owner", 0, path, "invalidate", {})
        helper_says(cache, "invalidate", path, {"kind": "done"})
    assert cache.pins["existing-tab"] is old and not cache.holds(old)
    wait, found, noted = new_waiter(cache, path)
    wait.look()
    wait.look(deliberate=True)  # A deliberate Rerun takes no pin either.
    assert found == [] and ("cached", path) in cache.jobs  # Asks the local disk cache instead.
    helper_says(cache, "cached", path, *read_events(range(2, 4), "fresh"))
    assert [view.shot_numbers for view in found] == [(2, 3)]


def test_a_cached_read_racing_a_mismatch_isnt_kept_by_the_cache(qtbot: QtBot, cache: FolderCache,
                                                                windows: Windows, monkeypatch: pytest.MonkeyPatch) -> None:
    """A cached read in flight when a check finds shots gone: FolderCache doesn't keep what it read,
    so no waiter, then or later, can take it."""
    disk_cache(monkeypatch)
    path = folder("raced2")
    wait, found, noted = new_waiter(cache, path)
    wait.look()
    read = helper_request(cache, "cached", path)
    mismatch_through_the_cache(cache, path, [1])  # Fences the read in flight: refused when it reports.
    send(cache, read, *read_events(range(1, 4), "old"))
    assert ("cached", path) not in cache.jobs
    assert found == [] and cache.latest_dataset(path) is None
    assert noted[-1].startswith("raced2's cached data doesn't match the folder")
    fresh = load_through_the_cache(cache, path, range(2, 4), "fresh")
    assert [view.shot_numbers for view in found] == [(2, 3)]
    later, found_later, _ = new_waiter(cache, path)
    later.look()
    assert [view.shot_numbers for view in found_later] == [(2, 3)] and cache.holds(fresh)


def test_an_arrangement_applied_while_a_tab_pins_old_data_waits(qtbot: QtBot, cache: FolderCache,
                                                                windows: Windows) -> None:
    """The same rule when an arrangement preset opens plots: the folder's old data, pinned by a
    tab after a mismatch, isn't run on; a load as it is now is."""
    window = new_window(qtbot, cache, windows)
    path = folder("preset")
    old = load_through_the_cache(cache, path, range(1, 4), "v1", allow_missing=False)
    cache.retain("existing-tab", old)
    mismatch_through_the_cache(cache, path, [1])
    write_arrangement("p", Arrangement((SavedPlot(ScriptRef("tests.counted", "Plot", "1"), path),), path))
    [plot] = presets_for(window, Explorer(folder("b")), cache).apply("p")
    qtbot.wait(20)
    assert plot.waiting() and Counted.runs == []
    load_through_the_cache(cache, path, range(2, 4), "fresh")
    qtbot.waitUntil(lambda: plot.shown is not None, timeout=10_000)
    assert Counted.runs == [(2, 3)]


def test_a_cached_read_from_before_a_mismatch_never_lands_after_it_is_resolved(
        qtbot: QtBot, cache: FolderCache, windows: Windows, monkeypatch: pytest.MonkeyPatch) -> None:
    """Flint's round-4 order, end to end: a tab's cached read of the old data and its check start;
    the check finds shot 1 gone; Load as it is now replaces the data and clears the mismatch; only
    then does the old read's helper answer. FolderCache never keeps it (its job was fenced at the
    mismatch), so once the fresh data leaves RAM a new waiter reads the disk cache again, and that
    read, asked after the folder matched again, is taken."""
    disk_cache(monkeypatch)
    path = folder("late")
    assert cache.submit("tab-owner", 0, path, "cached", {"cache": {"directory": "store"}}, priority=True)
    old_read = helper_request(cache, "cached", path)
    mismatch_through_the_cache(cache, path, [1])  # The tab's check
    fresh = load_through_the_cache(cache, path, range(9, 10), "fresh")  # Load as it is now
    assert path not in cache.mismatched and cache.latest_dataset(path) is fresh
    send(cache, old_read, *read_events(range(1, 2), "old"))  # The old read answers at last.
    assert cache.latest_dataset(path) is fresh and all(entry.signature != "old" for entry in cache.datasets.values())
    cache.evict_to(0)
    assert cache.latest_dataset(path) is None
    wait, found, _ = new_waiter(cache, path)
    wait.look()
    assert found == [] and ("cached", path) in cache.jobs  # A read asked after the folder matched again…
    helper_says(cache, "cached", path, *read_events(range(9, 10), "fresh"))
    assert [view.shot_numbers for view in found] == [(9,)]  # … is taken.


# Settings → Cache › Presets… (helab/views/PresetsInspector.py)


def inspector_rows(inspector: Any) -> dict[str, list[str]]:
    """Each preset's row (by name): its columns."""
    from helab.views.PresetsInspector import PresetsInspector
    assert isinstance(inspector, PresetsInspector)
    return {entry.name: [inspector._items[key].text(column) for column in range(4)]
            for key, entry in inspector.entries.items()}


def choose(inspector: Any, name: str) -> None:
    item = next(inspector._items[key] for key, entry in inspector.entries.items() if entry.name == name)
    inspector.tree.setCurrentItem(item)


def test_the_inspector_lists_presets_with_whether_they_fit_the_installed_scripts(
        qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    from helab.views.PresetsInspector import PresetsInspector, set_script_finder
    window = new_window(qtbot, cache, windows)
    set_script_finder(window.scripts.find_script)
    ref = ScriptRef("tests.counted", "Plot", "1", "", "Counted")
    write_script_preset(ScriptPreset("fits", ref, {"bins": 20, "mode": "rate"}, "PyQtGraph", 1.0))
    write_script_preset(ScriptPreset("old", dataclass_replace(ref, version="0"), {"bins": 500, "mode": "rate"},
                                     "PyQtGraph", 1.0))
    preset_store().set_presets([(SCRIPT, script_scope(ref), "broken", "{broken")])
    write_arrangement("run", Arrangement((full(window, ref, folder("a"), bins=3),
                                          SavedPlot(ScriptRef("user.gone", "Plot", "1", "", "Gone"), folder("a"))),
                                         folder("a"), root_key="root://u/a", live=True))
    stored(qtbot)
    inspector = PresetsInspector(preset_store())
    qtbot.addWidget(inspector)
    rows = inspector_rows(inspector)
    assert rows["fits"][1:3] == ["v1", "✓ fits the installed script"]
    assert rows["old"][1:3] == ["v0", "⚠ 1 setting wouldn't apply · saved with v0, now v1"]
    assert rows["broken"][2].startswith("⚠ can't be read: not valid JSON")
    assert rows["run"][1:3] == ["a, 2 plots", "⚠ 1 plot wouldn't open as saved"]
    choose(inspector, "old")
    details = inspector.details.toPlainText()
    assert "saved with v0" in details and "Mode rate" in details
    assert "⚠ Bins: saved 500 is outside 1 to 100" in details
    choose(inspector, "run")
    details = inspector.details.toPlainText()
    assert f"{folder('a')} (root://u/a), Live on" in details and "Bins 3" in details
    assert "• Gone: ⚠ its script isn't loaded (Load Scripts… its folder, then open it again)" in details
    # Without the installed scripts (a Settings dialog of its own): listed, not checked.
    set_script_finder(None)
    inspector.refresh()
    assert inspector_rows(inspector)["fits"][2] == "not checked: the installed scripts aren't known here"


def test_the_inspector_renames_duplicates_and_deletes_after_asking(qtbot: QtBot, cache: FolderCache,
                                                                   windows: Windows) -> None:
    from helab.views.PresetsInspector import PresetsInspector
    ref = ScriptRef("tests.counted", "Plot", "1", "", "Counted")
    write_script_preset(ScriptPreset("fast", ref, {"bins": 5}, "", 1.0))
    write_script_preset(ScriptPreset("slow", ref, {"bins": 50}, "", 1.0))
    write_arrangement("run", Arrangement((), folder("a")))
    inspector = PresetsInspector(preset_store())
    qtbot.addWidget(inspector)
    questions: List[str] = []

    def answer(reply: bool) -> Callable[..., bool]:
        def ask(parent: Any, title: str, text: str, action: str) -> bool:
            questions.append(text)
            return reply
        return ask
    scope = script_scope(ref)
    # Rename: onto another preset's name asks; No leaves both.
    choose(inspector, "fast")
    inspector.ask_name = lambda *_: "slow"
    inspector.confirm = answer(False)
    inspector.rename()
    assert questions == ["A preset “slow” exists. Replace it?"]
    assert set(preset_store().preset_records(SCRIPT, scope)) == {(scope, "fast"), (scope, "slow")}
    inspector.ask_name = lambda *_: "quick"
    inspector.rename()
    assert read_script_presets(ref).names() == ["quick", "slow"]
    assert read_script_presets(ref).presets["quick"].values == {"bins": 5}
    # Duplicate.
    choose(inspector, "quick")
    inspector.ask_name = lambda *_: "quick copy"
    inspector.duplicate()
    assert read_script_presets(ref).names() == ["quick", "quick copy", "slow"]
    # Delete asks first.
    choose(inspector, "run")
    inspector.delete()
    assert questions[-1] == "Delete the preset “run”? Open plots keep their settings." and arrangement_names() == ["run"]
    inspector.confirm = answer(True)
    inspector.delete()
    assert arrangement_names() == [] and not inspector.delete_button.isEnabled()
    # Saved: a restart reads the same.
    restart_presets(qtbot)
    assert read_script_presets(ref).names() == ["quick", "quick copy", "slow"] and arrangement_names() == []


def test_settings_cache_tab_counts_presets_and_opens_the_inspector(qtbot: QtBot, tmp_path: Any) -> None:
    from PyQt6.QtCore import QSettings
    from helab.views.CacheTab import CacheTab
    from helab.views.PresetsInspector import PresetsInspector
    store = preset_store()
    tab = CacheTab(store, QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(tab)
    assert tab.presets_label.text() == "0 script presets, 0 arrangements"
    write_arrangement("run", Arrangement((), folder("a")))
    stored(qtbot)
    assert tab.presets_label.text() == "0 script presets, 1 arrangement"
    tab.presets_button.click()
    first = tab.presets_window
    assert isinstance(first, PresetsInspector) and first.isVisible()
    tab.presets_button.click()
    assert tab.presets_window is first  # One at a time.
    first.close()


# Review round 7 (Flint, 5923fe7..9a338fd): names not yet known never authorize replacing


def before_the_first_read(qtbot: QtBot, *rows: tuple[str, str, str, str]) -> FolderCache:
    """Another session saved ``rows``; this one starts, its first read not answered yet."""
    from helab.utils.cache_store import CacheStore
    from helab.utils.folder_cache import store_options
    stored(qtbot)
    with CacheStore(store_options()["directory"]) as saved:
        saved.write_presets([{"kind": kind, "scope": scope, "name": name, "record": record, "set_at": 1.0}
                             for kind, scope, name, record in rows])
    store = preset_store()
    store.presets.clear()
    store.presets_read = False
    return store


def test_a_plots_save_before_the_first_read_keeps_the_stored_preset_and_says_so(
        qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    ref = ScriptRef("tests.counted", "Plot", "1", "", "Counted")
    theirs = ScriptPreset("p", ref, {"bins": 77, "mode": "rate"}, "", 1.0)
    store = before_the_first_read(qtbot, (SCRIPT, script_scope(ref), "p", dumps(theirs)))
    instance = waiting_plot(window, cache, ref)  # Its settings page asks for a read.
    presets = bar(instance)
    set_values(instance, {"bins": 5})
    presets.ask_name = lambda *_: "p"
    asked: List[str] = []

    def confirm(parent: Optional[QWidget], title: str, text: str, action: str) -> bool:
        asked.append(text)
        return True
    presets.confirm = confirm
    presets.save()  # Not a known name yet: nothing to ask.
    assert asked == [] and presets.note.text() == "Saved preset “p” (saved once the saved presets are read)"
    stored(qtbot)
    assert read_script_presets(ref).presets["p"].values["bins"] == 77  # The stored one stays.
    assert presets.note.text() == f"⚠ Preset “p” not saved: {PRESET_FOUND}" and presets.applied is None
    # Now the name is known: saving again asks first.
    presets.save()
    assert asked == ["A preset “p” of Counted exists. Replace it?"]
    stored(qtbot)
    assert read_script_presets(ref).presets["p"].values["bins"] == 5 and not store.presets_conflicts


def test_a_folder_preset_saved_before_the_first_read_keeps_the_stored_one(
        qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    before_the_first_read(qtbot, (ARRANGEMENT, "", "run", Arrangement((), folder("theirs")).dumps()))
    explorer = Explorer(folder("mine"))
    presets = presets_for(window, explorer, cache)  # Asks for the read at startup.
    presets.ask_name = lambda *_: "run"
    presets.save()
    stored(qtbot)
    assert read_arrangement("run").folder == folder("theirs")
    assert window.notices[-1] == f"Preset “run” not saved: {PRESET_FOUND}"


def test_the_menu_says_no_presets_saved_only_after_a_successful_read(
        qtbot: QtBot, cache: FolderCache, windows: Windows) -> None:
    window = new_window(qtbot, cache, windows)
    presets = presets_for(window, Explorer(folder("a")), cache)
    stored(qtbot)
    store = preset_store()
    menu = QMenu()

    def texts() -> List[str]:
        presets.fill_menu(menu, read=False)
        return [action.text() for action in menu.actions() if not action.isSeparator()]
    assert texts() == ["Save Folder and Plots as Preset…", "No presets saved"]
    store.presets_read = False
    assert texts() == ["Save Folder and Plots as Preset…", "Reading saved presets…"]
    store.presets_error = "disk I/O error"
    assert texts() == ["Save Folder and Plots as Preset…", "⚠ Saved presets can't be read: disk I/O error"]
