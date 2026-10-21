"""F0b plot overrides and resolution at run start: a plot's Constants group (``constants_specs``)
uses the lab and folder values unless set for that plot; each run resolves plot > folder > lab >
default on the GUI thread when it is submitted, and its result records them. A lab or folder
value changed afterwards marks the plot ("constants changed: Rerun to use them"); Rerun and the
next Live update use it. The demo analysis here is how D1's histograms plug in."""
from __future__ import annotations

import json
import os
import time
from typing import Any, Iterator, List, Mapping, Optional, cast

import numpy as np
import pytest
from pytestqt.qtbot import QtBot
from PyQt6 import sip
from PyQt6.QtWidgets import QDockWidget, QLabel, QMainWindow, QWidget

from helab.analysis import constant_layers as layers
from helab.analysis import release
from helab.analysis.dataset_view import DatasetView, build_view, view_of
from helab.analysis.parameter_tree import build_tree, parameter_of, tree_values
from helab.analysis.parameters import ParameterSpec, effective
from helab.analysis.physics import DEFAULTS, ResolvedConstants, fall_time, resolve
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.runner import AnalysisRunner
from helab.views.plots.instance import AnalysisInstance
from helab.views.plots.script_tree import TreePanelWidget
from helab.views.plots.workspace import PlotWorkspace
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.utils.folder_cache import Dataset, FolderCache
from helab.utils.io_service import IOService

ROOT = os.path.join(os.sep, "data", "root")
PATH = os.path.join(ROOT, "run_L")  # test_live_plots' folder
KEYS = ("g", "fall_distance", "fall_time")


def revision(shots: list[int]) -> Dataset:
    """The data a Live tab shows once it holds ``shots`` (as in test_live_plots)."""
    data = {shot: np.full((2, 3), float(shot)) for shot in shots}
    return Dataset(PATH, f"sig-{shots[-1]}", data, {
        "fingerprint": [[shot, 100 + shot, 1_000 + shot] for shot in shots], "source": "updated",
        "loaded_at": time.time()}, 0)


class Plots(PlotWorkspace):
    """The plot area; a new plot runs on the window's ``view``."""

    def __init__(self, window: Window) -> None:
        super().__init__(window)
        self.window = window

    def current_dataset_view(self) -> DatasetView | None:
        return self.window.view


class Window(QMainWindow):
    """A window with the plot area (``plots``: docks, Settings panel, Live feed), as in
    tests/test_live_plots.py."""

    def __init__(self) -> None:
        super().__init__()
        self.view: Optional[DatasetView] = None
        self.plots = Plots(self)


class FallTime(DatasetAnalysis):
    """A demo of an analysis using constants: the fall time and g its run resolved."""

    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata("Fall time", "test", "Tests", __file__, "tests.fall_time", "1")

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [ParameterSpec("bins", "Bins", "int", 10, (1, 100)), *layers.constants_specs(KEYS)]

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        constants = context.resolved_constants
        assert constants is not None
        return constants.fall_time, constants.g

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        return QLabel(f"t_f {result.data[0]:.4f} s", parent)


# The helpers

def test_constants_specs_offer_each_value_with_its_source_choice() -> None:
    specs = layers.constants_specs(KEYS)
    assert [spec.name for spec in specs] == ["const.g.from", "const.g", "const.fall_distance.from",
                                             "const.fall_distance", "const.fall_time.from", "const.fall_time"]
    choice, value = specs[2], specs[3]
    assert choice.kind == "choice" and choice.default == layers.USE_LAYERS and choice.choices == layers.CHOICES
    assert choice.title == "Fall distance h" and "Unconfirmed" in choice.tip and choice.group == "Constants"
    assert value.when == ("const.fall_distance.from", layers.SET_HERE) and value.si and value.suffix == "m"
    assert value.default == 0.848 and specs[5].default == pytest.approx(DEFAULTS.fall_time)
    assert not specs[1].si and specs[1].suffix == "m/s²"
    assert layers.constant_keys([ParameterSpec("bins", "Bins", "int", 1), *specs]) == KEYS
    assert layers.without_constants([ParameterSpec("bins", "Bins", "int", 1), *specs])[0].name == "bins"
    with pytest.raises(ValueError):
        layers.constants_specs(("g", "g"))


def test_runs_resolve_plot_over_folder_over_lab_with_origins() -> None:
    values = effective(layers.constants_specs(KEYS))  # Defaults: lab/folder for every key.
    assert layers.plot_overrides(values) == {}
    resolved = layers.resolve_for_run(values, lab={"g": 9.8, "fall_distance": 0.5},
                                      folder={"fall_distance": 0.9, "bogus": 1.0, "trap_axial": float("nan")})
    assert (resolved.g, resolved.origins["g"]) == (9.8, "lab")
    assert (resolved.fall_distance, resolved.origins["fall_distance"]) == (0.9, "folder")
    assert resolved.origins["fall_time"] == "derived" and resolved.fall_time == pytest.approx(fall_time(0.9, 9.8))
    assert resolved.origins["trap_axial"] == "default"
    values.update({"const.fall_distance.from": layers.SET_HERE, "const.fall_distance": 0.7,
                   "const.g": 1.0})  # A plot value of a key not set here is ignored.
    assert layers.plot_overrides(values) == {"fall_distance": 0.7}
    resolved = layers.resolve_for_run(values, lab={"g": 9.8}, folder={"fall_distance": 0.9})
    assert (resolved.fall_distance, resolved.origins["fall_distance"], resolved.g) == (0.7, "plot", 9.8)
    assert layers.describe_constants(resolved, KEYS) == ("g 9.8 m/s² (lab) · h 700 mm (this plot) · "
                                                         "t_f 377.9645 ms (derived)")
    assert layers.describe_constants(DEFAULTS, KEYS) == ""  # All defaults: nothing to say on the line.
    assert "h = 848 mm (default, unconfirmed)" in layers.record_text(DEFAULTS)
    assert layers.record_text(DEFAULTS, ("g",)) == "g = 9.79602 m/s² (default)"
    assert layers.changed_keys(DEFAULTS, resolved, KEYS) == ["g", "fall_distance", "fall_time"]


def test_a_fall_time_set_above_the_distances_folder_is_derived_again() -> None:
    found = {"fall_time": (0.417, "/data/root"), "fall_distance": (0.9, "/data/root/run")}
    assert layers.folder_layer(found) == {"fall_distance": 0.9}
    found["fall_time"] = (0.417, "/data/root/run")  # The same folder sets both: kept.
    assert layers.folder_layer(found) == {"fall_distance": 0.9, "fall_time": 0.417}


def test_the_nearer_folders_release_time_or_saved_arrival_is_kept() -> None:
    # A t_r by hand above, a subfolder's "Use for this folder" arrival below: the arrival wins.
    found = {"release_time": (0.01, "/data/root"), "arrival_time": (0.43, "/data/root/run")}
    assert layers.folder_layer(found) == {"arrival_time": 0.43}
    resolved = resolve(folder=layers.folder_layer(found))
    given = release.layer_release_time(resolved)
    assert given is not None and given.arrival.value == pytest.approx(0.43)
    assert given.value.value == pytest.approx(0.43 - resolved.fall_time)
    # The other way round: a t_r by hand in the subfolder wins over an arrival saved above.
    found = {"release_time": (0.01, "/data/root/run"), "arrival_time": (0.43, "/data/root")}
    assert layers.folder_layer(found) == {"release_time": 0.01}
    # Both in one folder: both kept, and the t_r by hand wins the tie.
    found = {"release_time": (0.01, "/data/root/run"), "arrival_time": (0.43, "/data/root/run")}
    assert layers.folder_layer(found) == {"release_time": 0.01, "arrival_time": 0.43}
    given = release.layer_release_time(resolve(folder=layers.folder_layer(found)))
    assert given is not None and given.value.value == pytest.approx(0.01)


def test_the_result_records_the_constants_it_ran_with(qtbot: QtBot) -> None:
    script = FallTime()
    data = {1: np.zeros((2, 3))}
    view = build_view(Dataset(PATH, "sig", data, {"fingerprint": [[1, 1, 1]], "source": "files",
                                                  "loaded_at": 0.0}, 0))
    runner = AnalysisRunner()
    try:
        resolved = layers.resolve_for_run({}, lab={"g": 9.8})
        ended: list[AnalysisResult] = []
        runner.finished.connect(ended.append)
        given = {"lab": {"g": 9.8}, "folder": {}}
        context = runner.submit(script, script.get_metadata(), "Plot", view, {}, given)
        assert context.constants == given and context.resolved_constants == resolved
        qtbot.waitUntil(lambda: bool(ended), timeout=10_000)
        result = ended[0]
        assert result.state == "completed" and result.data == (resolved.fall_time, 9.8)
        assert result.resolved_constants == resolved and result.constant_layers == given
        # The empty folder layer is left out of the record.
        assert result.constants_record == {"layers": {"lab": {"g": 9.8}}, **resolved.as_record(KEYS)}
        key = json.loads(json.dumps(result.reuse_key()))
        assert key["constants"]["origins"]["g"] == "lab" and key["constants"]["layers"] == {"lab": {"g": 9.8}}
        # Hidden rows (this plot's own values, while the layers are used) aren't in the reuse key.
        assert "bins" in key["parameters"] and "const.g.from" in key["parameters"]
        assert "const.g" not in key["parameters"] and "const.g" in result.parameters
        assert set(key["constants"]["values"]) == set(KEYS)  # The analysis's own constants only.
        # The record names the analysis's own constants only (not all of the table's).
        assert "Constants: g = 9.8 m/s² (lab)" in result.describe() and "ħ =" not in result.describe()
        # An analysis that declares no constants records none: a lab or folder change never makes
        # its results look different (it keeps the layers it was given, unrecorded).
        plain = AnalysisResult.of(AnalysisContext("a9", "Plot", view, {}, script.get_metadata().identity(),
                                                  constants=given), "completed")
        assert plain.resolved_constants is None and plain.constant_layers == given
        assert plain.constants_record is None and "constants" not in plain.reuse_key()
    finally:
        runner.stop()


def test_a_run_whose_keys_cant_be_named_keeps_its_constants(qtbot: QtBot) -> None:
    """``run_constant_keys`` raising: the run keeps what it resolved, with every declared key."""
    class Broken(FallTime):
        def run_constant_keys(self, action_name: str, values: Mapping[str, Any]) -> tuple[str, ...]:
            raise RuntimeError("no keys")

    script = Broken()
    view = build_view(Dataset(PATH, "sig", {1: np.zeros((2, 3))}, {"fingerprint": [[1, 1, 1]], "source": "files",
                                                                 "loaded_at": 0.0}, 0))
    runner = AnalysisRunner()
    try:
        context = runner.submit(script, script.get_metadata(), "Plot", view, {}, {"lab": {"g": 9.8}})
        assert context.resolved_constants is not None and context.constant_keys == script.constant_keys("Plot")
    finally:
        runner.stop()


# A plot: its settings, its runs, and changes to the lab and folder values

@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> Iterator[AnalysisRunner]:
    made = AnalysisRunner()
    monkeypatch.setattr("helab.views.plots.instance.get_analysis_runner", lambda: made)
    yield made
    made.stop()


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch) -> Iterator[FolderCache]:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    made = FolderCache(service)
    made.data_roots[ROOT] = ("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "root")
    monkeypatch.setattr("helab.views.plots.instance.get_folder_cache", lambda _service: made)
    yield made
    service.shutdown()


@pytest.fixture
def window(qtbot: QtBot, runner: AnalysisRunner, cache: FolderCache) -> Iterator[Window]:
    made = Window()
    qtbot.addWidget(made)
    yield made
    made.plots.close_plots()
    if not sip.isdeleted(made.plots.middle_mainwindow):
        made.plots.middle_mainwindow.close()
        made.plots.middle_mainwindow.deleteLater()


def plot(window: Window, qtbot: QtBot) -> AnalysisInstance:
    panel = TreePanelWidget(window.plots)
    qtbot.addWidget(panel)
    instance = panel.run_analysis(FallTime().get_metadata(), FallTime(), "Plot")
    assert isinstance(instance, AnalysisInstance)
    qtbot.waitUntil(lambda: instance.shown is not None, timeout=10_000)
    return instance


def shown(instance: AnalysisInstance) -> ResolvedConstants:
    assert instance.shown is not None and instance.shown.resolved_constants is not None
    return instance.shown.resolved_constants


def label(instance: AnalysisInstance, name: str) -> str:
    found = cast(QDockWidget, instance.dock_widget).findChild(QLabel, name)
    assert found is not None
    return found.text() if found.isVisibleTo(instance.dock_widget) else ""


def title(instance: AnalysisInstance, key: str) -> str:
    assert instance.parameter_root is not None
    spec = next(spec for spec in FallTime().parameters("Plot") if spec.name == layers.source_name(key))
    return str(parameter_of(instance.parameter_root, spec).opts["title"])


def test_a_plot_resolves_when_it_runs_and_marks_changes_until_rerun(
        window: Window, cache: FolderCache, qtbot: QtBot) -> None:
    cache.set_lab_constants({"g": 9.8})
    cache.remember_constants(ROOT, {"values": {"fall_distance": 0.9}, "set_at": 1.0})
    window.view = window.plots.live_feed.publish(revision([1]))
    instance = plot(window, qtbot)
    constants = shown(instance)
    assert (constants.origins["g"], constants.origins["fall_distance"], constants.origins["fall_time"]) == (
        "lab", "folder", "derived")
    assert instance.shown is not None and instance.shown.data[0] == pytest.approx(fall_time(0.9, 9.8))
    # Each value's source in the settings, and the ones not at their defaults on the source line.
    assert title(instance, "fall_distance") == "Fall distance h: 900 mm (folder)"
    assert title(instance, "g") == "Gravitational acceleration g: 9.8 m/s² (lab)"
    line = label(instance, "plot_data_source")
    assert "constants: g 9.8 m/s² (lab) · h 900 mm (folder) · t_f 428.5714 ms (derived)" in line
    assert "Fall distance" not in line.split("\n")[1].split("constants:")[0]  # Not as a parameter.
    assert label(instance, "plot_error") == ""
    # A lab value changes: the plot is marked, and keeps what it drew.
    cache.set_lab_constants({"g": 9.79})
    assert label(instance, "plot_error") == ("⚠ constants changed (Gravitational acceleration g, Fall time t_f): "
                                             "Rerun to use them")
    assert title(instance, "g") == "Gravitational acceleration g: 9.79 m/s² (lab)"
    assert shown(instance).g == 9.8
    # Another folder's change says nothing to this plot.
    cache.set_lab_constants({"g": 9.8})
    assert label(instance, "plot_error") == ""  # Back as drawn.
    # Another folder's change (a sibling, one whose name starts with the plot's) isn't heard.
    checks: list[str] = []
    check = instance._check_constants
    def counted() -> None:
        checks.append("checked")
        check()
    instance._check_constants = counted  # type: ignore[method-assign]
    for other in (os.path.join(ROOT, "other"), PATH + "_2"):
        cache.remember_constants(other, {"values": {"fall_distance": 0.5}, "set_at": 2.0})
    assert checks == [] and label(instance, "plot_error") == ""
    cache.remember_constants(ROOT, {"values": {"fall_distance": 0.9, "trap_axial": 40.0}, "set_at": 2.0})
    assert checks == ["checked"] and label(instance, "plot_error") == ""  # Heard; no key it uses changed.
    instance._check_constants = check  # type: ignore[method-assign]
    cache.set_lab_constants({"g": 9.79})
    instance.run()  # Rerun.
    qtbot.waitUntil(lambda: shown(instance).g == 9.79, timeout=10_000)
    assert label(instance, "plot_error") == ""
    # The plot's own value wins over the folder's.
    assert instance.parameter_root is not None
    root = instance.parameter_root
    root.child("Constants", "const.fall_distance.from").setValue(layers.SET_HERE)
    root.child("Constants", "const.fall_distance").setValue(0.8)
    assert tree_values(root, FallTime().parameters("Plot"))["const.fall_distance"] == 0.8
    instance.run()
    qtbot.waitUntil(lambda: shown(instance).origins["fall_distance"] == "plot", timeout=10_000)
    assert shown(instance).fall_distance == 0.8 and title(instance, "fall_distance") == \
        "Fall distance h: 800 mm (this plot)"
    # A folder value it overrides doesn't mark it.
    cache.remember_constants(ROOT, {"values": {"fall_distance": 0.95}, "set_at": 3.0})
    assert label(instance, "plot_error") == ""
    instance.close()


def test_live_reruns_resolve_again(window: Window, cache: FolderCache, qtbot: QtBot) -> None:
    window.view = window.plots.live_feed.publish(revision([1]))
    instance = plot(window, qtbot)
    assert shown(instance) == DEFAULTS and label(instance, "plot_error") == ""
    cache.remember_constants(PATH, {"values": {"fall_distance": 0.9}, "set_at": 1.0})  # Its own folder.
    assert label(instance, "plot_error").startswith("⚠ constants changed (Fall distance h, Fall time t_f)")
    window.plots.live_feed.publish(revision([1, 2]))  # The next Live update uses them.
    qtbot.waitUntil(lambda: shown(instance).fall_distance == 0.9, timeout=10_000)
    assert shown(instance).origins["fall_distance"] == "folder" and label(instance, "plot_error") == ""
    instance.close()


def test_a_plots_settings_without_a_window_still_resolve(qtbot: QtBot, cache: FolderCache) -> None:
    """``resolve_constants`` is what the plot submits; a plain plot (no constants) resolves none."""
    data = {1: np.zeros((2, 3))}
    view = build_view(Dataset(os.path.join(PATH, "x"), "sig", data, {"fingerprint": [[1, 1, 1]],
                                                                     "source": "files", "loaded_at": 0.0}, 0))
    cache.remember_constants(PATH, {"values": {"fall_distance": 0.9}, "set_at": 1.0})
    instance = AnalysisInstance(FallTime().get_metadata(), FallTime(), "Plot", view, "1", None, cache=cache)
    instance.parameter_root = build_tree(FallTime().parameters("Plot"))
    resolved = instance.resolve_constants(instance.values())
    assert resolved is not None and resolved.origins["fall_distance"] == "folder"  # Inherited from run_L.
    instance.close()


class OwnOverrides(DatasetAnalysis):
    """An analysis with its own override parameters (as D1's histograms on agent/dld-d1: 0 = not
    set), reading the layers from ``context.constants`` itself; it declares the constants it uses
    and how it resolves them, so its plots are marked when a lab or folder value changes."""

    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata("Own overrides", "test", "Tests", __file__, "tests.own", "1")

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [ParameterSpec("fall_distance", "Fall distance (0 = default)", "float", 0.0, (0.0, 100.0))]

    def constant_keys(self, action_name: str) -> tuple[str, ...]:
        return ("g", "fall_distance", "fall_time")

    def run_constants(self, action_name: str, values: Mapping[str, Any],
                      layers: Mapping[str, Mapping[str, float]]) -> ResolvedConstants:
        plot = {"fall_distance": float(values["fall_distance"])} if values.get("fall_distance") else {}
        return resolve(lab=layers.get("lab"), folder=layers.get("folder"), plot=plot)

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        return self.run_constants(action_name, context.parameters, context.constants).fall_time, 0.0

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        return QLabel(f"t_f {result.data[0]:.4f} s", parent)


def test_an_analysis_with_its_own_overrides_gets_the_layers(window: Window, cache: FolderCache, qtbot: QtBot) -> None:
    cache.remember_constants(ROOT, {"values": {"fall_distance": 0.9}, "set_at": 1.0})
    window.view = window.plots.live_feed.publish(revision([1]))
    panel = TreePanelWidget(window.plots)
    qtbot.addWidget(panel)
    instance = panel.run_analysis(OwnOverrides().get_metadata(), OwnOverrides(), "Plot")
    assert isinstance(instance, AnalysisInstance)
    qtbot.waitUntil(lambda: instance.shown is not None, timeout=10_000)
    assert instance.shown is not None
    assert instance.shown.constant_layers == {"lab": {}, "folder": {"fall_distance": 0.9}}
    assert instance.shown.data[0] == pytest.approx(fall_time(0.9, DEFAULTS.g))
    assert shown(instance).origins["fall_distance"] == "folder"
    cache.set_lab_constants({"g": 9.7})
    assert label(instance, "plot_error").startswith("⚠ constants changed (Gravitational acceleration g")
    instance.close()


def test_a_released_plot_reloads_with_the_layers_it_was_drawn_with(
        window: Window, cache: FolderCache, qtbot: QtBot) -> None:
    cache.remember_constants(ROOT, {"values": {"fall_distance": 0.9}, "set_at": 1.0})
    drawn = revision([1])
    window.view = view_of(drawn)  # Loaded, not Live: a plot that follows Live is never released.
    instance = plot(window, qtbot)
    first = cast(AnalysisResult, instance.shown)
    assert instance.release()
    cache.remember_constants(ROOT, {"values": {"fall_distance": 0.95}, "set_at": 2.0})
    instance.reload()  # As it was drawn: from the disk cache (nothing in RAM here).
    request = next(r for r in cache.requests(instance._reload_owner) if r.operation == "cached")
    cache.resultReady.emit(request, {"kind": "loaded", "dataset": drawn})  # As FolderCache passes it on.
    qtbot.waitUntil(lambda: instance.released is None and instance.shown is not first, timeout=10_000)
    again = cast(AnalysisResult, instance.shown)
    assert again.constant_layers == first.constant_layers and shown(instance).fall_distance == 0.9
    # It is drawn with the old value: marked, and Rerun uses the new one.
    assert label(instance, "plot_error").startswith("⚠ constants changed (Fall distance h")
    instance.run()
    qtbot.waitUntil(lambda: shown(instance).fall_distance == 0.95, timeout=10_000)
    instance.close()


def test_the_histograms_fits_are_keyed_on_constants_and_marked_when_one_changes(
        window: Window, qtbot: QtBot, cache: FolderCache) -> None:
    """D1 uses F0b's Constants group: with a fit on, its runs resolve the fall distance and time, g,
    the mass and k_B, its key carries them, the constants appear once in the record, and a lab
    change marks the plot until Rerun; without a fit it uses none (no key, no mark)."""
    from helab.scripts.dld import basic_plots
    window.view = window.plots.live_feed.publish(revision([1, 2]))
    script = basic_plots.TxyHistograms()
    panel = TreePanelWidget(window.plots)
    qtbot.addWidget(panel)
    instance = panel.run_analysis(script.get_metadata(), script, "Plot")
    assert isinstance(instance, AnalysisInstance) and instance.parameter_root is not None
    qtbot.waitUntil(lambda: instance.shown is not None, timeout=10_000)
    assert instance.constant_keys == basic_plots.CONSTANT_KEYS  # Those it can use; a run names its own.
    plain = instance.shown
    assert plain is not None and plain.resolved_constants is None and "constants" not in plain.reuse_key()
    cache.set_lab_constants({"g": 9.79})
    assert label(instance, "plot_error") == ""  # No fit: nothing to mark.
    specs = {spec.name: spec for spec in script.parameters("Plot")}
    parameter_of(instance.parameter_root, specs["fit_x"]).setValue(True)
    instance.run()
    qtbot.waitUntil(lambda: instance.shown is not None and instance.shown.resolved_constants is not None,
                    timeout=10_000)
    fitted = instance.shown
    assert fitted is not None and fitted.resolved_constants is not None
    assert fitted.reuse_key()["constants"]["layers"]["lab"] == {"g": 9.79}
    assert fitted.resolved_constants.origins["g"] == "lab"
    record = cast(QDockWidget, instance.dock_widget).findChild(QLabel, "plot_data_source")
    assert record is not None and record.toolTip().count("Constants: ") == 1
    assert fitted.constant_keys == ("fall_distance", "fall_time", "g", "mass", "k_B")  # No bimodal fit: no trap
    assert "QE = " not in record.toolTip()
    assert "constants: t_f 416.2187 ms (derived, unconfirmed) · g 9.79 m/s² (lab)" in label(instance, "plot_data_source")
    assert label(instance, "plot_error") == ""
    cache.set_lab_constants({"g": 9.79, "detector_qe": 0.2})  # The trap's: a Gaussian fit doesn't use it.
    assert label(instance, "plot_error") == ""
    cache.set_lab_constants({"g": 9.79, "detector_qe": 0.2, "mass": 6.6e-27})  # Only the fits use it: marked.
    assert label(instance, "plot_error").startswith("⚠ constants changed (")


class RaisingHooks(FallTime):
    """A user's script whose dock hooks raise: the dock still shows its plot."""

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        raise RuntimeError("describe_run")

    def describe_result(self, action_name: str, result: AnalysisResult) -> str:
        raise RuntimeError("describe_result")

    def result_record(self, action_name: str, result: AnalysisResult) -> List[str]:
        raise RuntimeError("result_record")

    def parameter_warnings(self, action_name: str, values: Mapping[str, Any]) -> List[str]:
        raise RuntimeError("parameter_warnings")

    def detected_parameters(self, action_name: str, result: AnalysisResult) -> dict[str, Any]:
        raise RuntimeError("detected_parameters")


def test_a_raising_dock_hook_is_logged_not_fatal(window: Window, qtbot: QtBot,
                                                 caplog: pytest.LogCaptureFixture) -> None:
    window.view = window.plots.live_feed.publish(revision([1]))
    panel = TreePanelWidget(window.plots)
    qtbot.addWidget(panel)
    script = RaisingHooks()
    instance = panel.run_analysis(script.get_metadata(), script, "Plot")
    assert isinstance(instance, AnalysisInstance)
    qtbot.waitUntil(lambda: instance.shown is not None, timeout=10_000)
    assert instance.shown is not None and instance.shown.state == "completed"
    for name in ("describe_run", "describe_result", "result_record", "parameter_warnings", "detected_parameters"):
        assert any(record.getMessage().startswith(f"{name} of ") for record in caplog.records), name
