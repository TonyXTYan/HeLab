"""Dataset view, auto-crop, sampling, counts, histograms and the analysis runner, on known arrays."""
from __future__ import annotations

import hashlib
import math
import threading
import time
from pathlib import Path
from typing import Any, List, Optional

import numpy as np
import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QTabWidget, QWidget
from pyqtgraph.parametertree import ParameterTree

from helab.analysis.dataset_view import DatasetView, ViewKey, build_view, root_key, view_of
from helab.analysis import display_units, selection
from helab.analysis.parameter_tree import UnitSpinBox, build_tree, parameter_of, settings_widget, tree_values
from helab.analysis.parameters import ParameterSpec, describe, effective, tree_children
from helab.analysis.results import AnalysisContext, AnalysisResult, Cancelled, RamResults
from helab.analysis.runner import AnalysisRunner
from helab.analysis.stats import (
    MAX_BINS, counts_per_shot, shortest_range, crop_box, display_sample, freedman_diaconis_bins, histogram)
from helab.scripts import standard
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.scripts_manager import ScriptsManager
from helab.scripts.standard import basic_plots, group, scatter_3d, shot_trends, transfer_fractions
from helab.utils.folder_cache import Dataset


def dataset(path: str = "/data/root/sub/run_1", shots: dict[int, Any] | None = None, **metadata: Any) -> Dataset:
    data = shots if shots is not None else {2: np.ones((4, 3)), 1: np.zeros((2, 3))}
    for array in data.values():
        array.setflags(write=False)
    fingerprint = [[shot, 100 + shot, 1_000 + shot] for shot in sorted(data)]
    return Dataset(path, "sig-1", data, {"fingerprint": fingerprint, "source": "merged",
                                         "loaded_at": 1_700_000_000.0, **metadata}, 0)


# Dataset view

def test_view_snapshot_shares_read_only_arrays_and_copies_records() -> None:
    shown = dataset(checked_at=time.monotonic() - 10, unsettled_files=2, problematic=[2], failed_files=1,
                    data_root={"path": "/data/root", "uuid": "u-1", "label": "Lab"}, verified=False)
    view = build_view(shown)
    assert view.identity.source_path == "/data/root/sub/run_1"
    assert view.identity.root_key == "root://u-1/sub/run_1"
    assert view.identity.signature == "sig-1" and view.revision == 1
    assert view.key == ViewKey(view.identity, 1) and view.key.short() == "run_1 · rev 1"
    assert view.data_root is not None and view.data_root.label == "Lab"
    assert view.shot_numbers == (1, 2) and view.event_count == 6
    assert view.fingerprints[2] == (2, 102, 1002)
    provenance = view.provenance
    assert (provenance.source, provenance.unsettled_files, provenance.failed_files, provenance.problematic,
            provenance.verified) == ("merged", 2, 1, (2,), False)
    assert provenance.loaded_at == 1_700_000_000.0
    assert provenance.checked_at is not None and abs(time.time() - 10 - provenance.checked_at) < 1
    # The arrays are shared, never copied, and can't be written or made writable.
    assert view.shots[2] is not shown.data[2] and np.shares_memory(view.shots[2], shown.data[2])
    with pytest.raises(ValueError):
        view.shots[2][0, 0] = 5
    with pytest.raises(ValueError):
        view.shots[2].setflags(write=True)
    with pytest.raises(TypeError):
        view.shots[3] = np.ones((1, 3))  # type: ignore[index]
    # Later changes to what the browser holds don't reach the view.
    shown.data[3] = np.ones((9, 3))
    shown.metadata["checked_at"] = float("-inf")
    shown.metadata["verified"] = True
    assert view.shot_numbers == (1, 2) and view.provenance.verified is False
    assert view.provenance.checked_at is not None


def test_view_makes_writable_arrays_read_only_without_copying() -> None:
    array = np.arange(6, dtype=np.float64).reshape(2, 3)
    shown = Dataset("/x", "", {1: array}, {}, 0)
    view = build_view(shown)
    assert np.shares_memory(view.shots[1], array) and not view.shots[1].flags.writeable
    # Shared shot data is read-only by convention: the source array is made read-only too.
    assert not array.flags.writeable
    with pytest.raises(ValueError):
        view.shots[1].setflags(write=True)
    assert view.provenance.checked_at is None and view.identity.root_key == ""


def loaded_shot(folder: Path, name: str, rows: int, value: float) -> Any:
    """A shot as IOService delivers it: np.load of a saved artifact (a non-owning array whose
    base owns writable memory), then made read-only as FolderCache does."""
    path = folder / f"{name}.npy"
    np.save(path, np.full((rows, 3), value))
    array = np.load(path)
    assert not array.flags.owndata and isinstance(array.base, np.ndarray) and array.base.flags.writeable
    array.setflags(write=False)
    return array


def test_view_guards_the_loaded_shot_path(tmp_path: Path) -> None:
    source = loaded_shot(tmp_path, "s1", 2, 1.0)
    shown = Dataset("/x", "sig", {1: source}, {}, 0)
    view = build_view(shown)
    for array in (view.shots[1], source):  # neither the view nor the tab's array can be re-enabled
        with pytest.raises(ValueError):
            array.setflags(write=True)
        with pytest.raises(ValueError):
            array[0, 0] = 99
    added = loaded_shot(tmp_path, "s2", 3, 2.0)
    added.setflags(write=True)  # e.g. Live hands over a fresh, writable shot
    later = view.with_shots({2: added})
    for array in (later.shots[1], later.shots[2], added):
        with pytest.raises(ValueError):
            array.setflags(write=True)
        with pytest.raises(ValueError):
            array[0, 0] = 99
    assert float(shown.data[1][0, 0]) == 1.0 and float(later.shots[2][0, 0]) == 2.0


def test_view_root_from_session_and_one_view_per_dataset() -> None:
    shown = dataset(path="/Volumes/share/exp/run")
    view = view_of(shown, ("/Volumes/share", "u-2", "Share"))
    assert view.identity.root_key == "root://u-2/exp/run"
    assert view_of(shown) is view
    assert view_of(dataset(path="/Volumes/share/exp/run")) is not view
    assert root_key("/a", "u", "/a") == "root://u"


def test_with_shots_is_the_next_revision() -> None:
    view = build_view(dataset())
    later = view.with_shots({3: np.full((5, 3), 2.0)}, {3: (3, 10, 20)})
    assert later.identity == view.identity and later.revision == 2 and later.added_shots == (3,)
    assert later.shot_numbers == (1, 2, 3) and later.fingerprints[3] == (3, 10, 20)
    assert view.shot_numbers == (1, 2) and view.revision == 1
    assert later.key != view.key


def test_events_skips_malformed_arrays() -> None:
    view = build_view(dataset(shots={1: np.ones((2, 3)), 2: np.ones(0), 3: np.ones((1, 4))}))
    assert view.events().shape == (3, 3)
    assert build_view(dataset(shots={})).events().shape == (0, 3)


# Auto-crop and sampling

def test_crop_trims_outliers_to_hold_the_requested_share() -> None:
    line = np.repeat(np.arange(1000, dtype=np.float64)[:, None], 3, axis=1)  # T = X = Y
    box = crop_box(line, 0.99)
    assert (box.kept, box.total, box.left_out) == (990, 1000, 10)
    # Equally spaced: every end is as good, and ties are cut evenly.
    assert box.lower == (5.0, 5.0, 5.0) and box.upper == (994.0, 994.0, 994.0)
    assert box.fraction == pytest.approx(0.99)


def test_crop_leaves_out_one_sided_tails() -> None:
    core = np.repeat(np.linspace(0, 1, 980)[:, None], 3, axis=1)
    late = np.array([[50.0 + i, 0.5, 0.5] for i in range(20)])  # 2 % late T events
    box = crop_box(np.concatenate([core, late]), 0.98)
    assert box.upper[0] == 1.0 and box.kept == 980


def test_crop_holds_the_share_on_independent_axes() -> None:
    rng = np.random.default_rng(1)
    events = rng.normal(size=(20_000, 3))
    events[:50] *= 1_000  # far outliers
    box = crop_box(events, 0.99)
    needed = math.ceil(0.99 * len(events))
    assert box.kept >= needed and box.left_out == len(events) - box.kept
    assert np.count_nonzero(box.contains(events)) == box.kept
    assert max(abs(v) for v in box.lower + box.upper) < 10  # outliers are outside


def test_crop_finds_the_gap_behind_a_clustered_tail() -> None:
    values = [0.0, 1, 2, 3, 100, 101]
    events = np.array([[value, 0.5, 0.5] for value in values])
    box = crop_box(events, 4 / 6)
    assert box.lower[0] == 0.0 and box.upper[0] == 3.0 and box.kept == 4
    assert shortest_range(np.array(values), 4 / 6) == (0.0, 3.0)


def test_shortest_range_is_exact() -> None:
    rng = np.random.default_rng(3)
    for _ in range(50):
        values = np.concatenate([rng.normal(size=40), rng.exponential(10, size=rng.integers(0, 10))])
        keep = float(rng.uniform(0.5, 1.0))
        m = math.ceil(keep * len(values))
        ordered = np.sort(values)
        best = min(ordered[i + m - 1] - ordered[i] for i in range(len(values) - m + 1))
        lower, upper = shortest_range(values, keep)
        assert upper - lower == pytest.approx(best)
        assert np.count_nonzero((values >= lower) & (values <= upper)) >= m


def test_crop_and_scatter_stop_when_cancelled() -> None:
    events = np.random.default_rng(4).normal(size=(5_000, 3))
    with pytest.raises(Cancelled):
        crop_box(events, 0.99, lambda: True)
    script = scatter_3d.Scatter3D()
    run = context(build_view(dataset(shots={1: events})), script)
    run.cancel_event.set()
    with pytest.raises(Cancelled):
        script.compute("Plot", run)


def test_crop_with_ties_full_keep_and_no_events() -> None:
    grid = np.stack(np.meshgrid(*[np.arange(10.0)] * 3), axis=-1).reshape(-1, 3)
    box = crop_box(grid, 0.99)
    assert box.kept == 1000 and box.lower == (0.0,) * 3 and box.upper == (9.0,) * 3
    full = crop_box(np.array([[0.0, 1, 2], [10, 11, 12]]), 1.0)
    assert full.lower == (0.0, 1.0, 2.0) and full.upper == (10.0, 11.0, 12.0) and full.kept == 2
    empty = crop_box(np.empty((0, 3)))
    assert empty.kept == 0 and empty.fraction == 1.0 and all(math.isnan(v) for v in empty.lower)


def test_display_sample_is_capped_fixed_and_never_repeats() -> None:
    assert np.array_equal(display_sample(5, cap=10), np.arange(5))
    sample = display_sample(1_000, cap=100)
    assert len(sample) == 100 and len(set(sample.tolist())) == 100 and np.all(np.diff(sample) > 0)
    assert np.array_equal(sample, display_sample(1_000, cap=100))


# Counts and histograms

def test_counts_per_shot() -> None:
    view = build_view(dataset(shots={5: np.ones((7, 3)), 1: np.ones((3, 3)), 2: np.empty((0, 3))}))
    shots, counts = counts_per_shot(view)
    assert shots.tolist() == [1, 2, 5] and counts.tolist() == [3, 0, 7]


def test_histogram_totals_ranges_and_bins() -> None:
    values = np.concatenate([np.linspace(0, 1, 990), [100.0] * 10])
    item = histogram(values, "T", keep=0.99)
    assert item.total == 1000 and int(item.counts.sum()) + item.outside == 1000
    assert item.outside == 10 and item.edges[-1] == 1.0 and item.automatic_bins
    q1, q3 = np.percentile(np.linspace(0, 1, 990), [25, 75])
    width = 2 * (q3 - q1) * 990 ** (-1 / 3)
    assert len(item.counts) == math.ceil((item.edges[-1] - item.edges[0]) / width)
    full = histogram(values, "T", keep=1.0, bins=7)
    assert len(full.counts) == 7 and full.outside == 0 and int(full.counts.sum()) == 1000
    assert not full.automatic_bins
    same = histogram(np.full(5, 3.0), "X")
    assert int(same.counts.sum()) == 5 and same.outside == 0
    assert histogram(np.empty(0), "Y").total == 0
    bounded = histogram(values, "T", bins=4, bounds=(0.5, 2.0))
    assert (bounded.edges[0], bounded.edges[-1]) == (0.5, 2.0) and bounded.outside == 1000 - int(bounded.counts.sum())
    assert histogram(np.empty(0), "Y", bounds=(1.0, 2.0)).edges.tolist() == [1.0, 2.0]
    assert shortest_range(np.array([1.0, 2.0, 3.0]), 1.0) == (1.0, 3.0)
    assert freedman_diaconis_bins(np.zeros(10), 0, 0) == 1
    assert freedman_diaconis_bins(np.array([0.0, 1e-12, 1.0]), 0.0, 1.0) <= MAX_BINS


# Parameters

def test_parameters_are_validated_and_described() -> None:
    specs = [ParameterSpec("keep", "Keep", "float", 99.0, (50.0, 100.0), " %"),
             ParameterSpec("bins", "Bins", "int", 0, (0, 10))]
    assert effective(specs, {"keep": "120", "bins": 3.7, "other": 1}) == {"keep": 100.0, "bins": 3}
    assert effective(specs) == {"keep": 99.0, "bins": 0}
    assert describe(specs, {"keep": 99.0, "bins": 0}) == "Keep 99 %, Bins 0"
    assert specs[0].tree_item()["limits"] == (50.0, 100.0) and specs[0].tree_item()["suffix"] == "%"
    bound = ParameterSpec("t_min", "T min", "float", 0.0, None, " s", si=True).tree_item()
    assert (bound["suffix"], bound["siPrefix"], bound["dec"], bound["step"]) == ("s", True, True, 0.1)


def test_choice_parameters_gate_what_applies() -> None:
    mode = ParameterSpec("mode", "Mode", "choice", "auto", choices=("auto", "manual"), group="Range")
    keep = ParameterSpec("keep", "Keep", "float", 99.0, (50.0, 100.0), " %", group="Range", when=("mode", "auto"))
    low = ParameterSpec("low", "Low", "float", 0.0, group="Range", when=("mode", "manual"))
    log = ParameterSpec("log", "Log Y", "bool", False)
    specs = [mode, keep, low, log]
    assert effective(specs, {"mode": "other"})["mode"] == "auto"
    manual = effective(specs, {"mode": "manual", "low": "2", "log": 1})
    assert manual == {"mode": "manual", "keep": 99.0, "low": 2.0, "log": True}
    assert describe(specs, manual) == "Mode manual, Low 2, Log Y on"
    assert describe(specs, manual, every=True) == "Mode manual, Keep 99 %, Low 2, Log Y on"
    assert mode.tree_item() == {"name": "mode", "title": "Mode", "type": "list", "value": "auto", "default": "auto",
                                "limits": ["auto", "manual"]}
    children = tree_children(specs)
    assert [child["name"] for child in children] == ["Range", "log"]
    assert [child["name"] for child in children[0]["children"]] == ["mode", "keep", "low"]


def test_parameter_tree_shows_only_what_applies(qtbot: QtBot) -> None:
    specs = scatter_3d.Scatter3D().parameters("Plot")
    root = build_tree(specs)

    def visible(spec: ParameterSpec) -> bool:
        options: dict[str, Any] = parameter_of(root, spec).opts
        return bool(options.get("visible", True))
    assert visible(selection.SHOTS) and visible(selection.FIRST_SHOT) and not visible(selection.LAST_SHOTS)
    assert not visible(selection.LAST_SHOT)
    assert visible(scatter_3d.KEEP) and not visible(selection.BOUNDS[0][0])
    parameter_of(root, selection.SHOTS).setValue(selection.LAST_N)
    parameter_of(root, selection.RANGE_MODE).setValue(selection.MANUAL)
    assert visible(selection.LAST_SHOTS) and visible(selection.FIRST_SHOT) and not visible(selection.LAST_SHOT)
    assert not visible(scatter_3d.KEEP) and all(visible(spec) for pair in selection.BOUNDS for spec in pair)
    values = tree_values(root, specs)
    assert values["shots"] == "last N" and values["range_mode"] == "manual" and values["display_cap"] == 100_000
    assert set(values) == {spec.name for spec in specs}


def test_numbers_can_be_typed_without_their_unit(qtbot: QtBot) -> None:
    """Select all and type a number: the unit (and an SI prefix shown) is understood."""
    specs = scatter_3d.Scatter3D().parameters("Plot")
    root = build_tree(specs)
    tree = settings_widget(root, specs)
    qtbot.addWidget(tree)
    tree.show()
    parameter_of(root, selection.RANGE_MODE).setValue(selection.MANUAL)
    t_min = selection.BOUNDS[0][0]
    parameter_of(root, t_min).setValue(0.004)

    def type_into(spec: ParameterSpec, text: str) -> str:
        box = next(iter(parameter_of(root, spec).items)).widget
        assert isinstance(box, UnitSpinBox)
        edit = box.lineEdit()
        assert edit is not None
        edit.selectAll()
        qtbot.keyClicks(edit, text)  # type: ignore[no-untyped-call]
        qtbot.keyClick(edit, Qt.Key.Key_Return)  # type: ignore[no-untyped-call]
        return str(edit.text())
    assert type_into(t_min, "5") == "5 ms"
    parameter_of(root, selection.RANGE_MODE).setValue(selection.AUTO)
    assert type_into(scatter_3d.KEEP, "95") == "95 %"
    assert type_into(scatter_3d.CAP, "5000") == "5000"
    assert type_into(scatter_3d.POINT_SIZE, "20") == "10 px"  # Above the limit: set to 10 px.
    values = tree_values(root, specs)
    assert values["t_min"] == pytest.approx(0.005) and values["keep_percent"] == 95.0
    assert values["display_cap"] == 5000 and isinstance(values["display_cap"], int)


def test_settings_pages_become_tabs(qtbot: QtBot) -> None:
    """Parameters on more than one page get a tab each, a group on its first parameter's page;
    one page (as every plot has today) is a plain tree."""
    plain = settings_widget(build_tree(scatter_3d.Scatter3D().parameters("Plot")), [])
    assert isinstance(plain, ParameterTree)
    qtbot.addWidget(plain)
    specs = [ParameterSpec("bins", "Bins", "int", 10, (1, 100)),
             ParameterSpec("model", "Model", "choice", "gauss", choices=("gauss", "lorentz"), group="Fit", page="Fit"),
             ParameterSpec("width", "Width", "float", 1.0, group="Fit"),
             ParameterSpec("log_y", "Log Y", "bool", False, page="Display")]
    root = build_tree(specs)
    tabs = settings_widget(root, specs)
    assert isinstance(tabs, QTabWidget)
    qtbot.addWidget(tabs)
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["Settings", "Fit", "Display"]
    fit = tabs.widget(1)
    assert isinstance(fit, ParameterTree)
    assert [item.param.name() for item in fit.listAllItems()] == ["Fit", "model", "width"]
    parameter_of(root, specs[3]).setValue(True)
    assert tree_values(root, specs) == {"bins": 10, "model": "gauss", "width": 1.0, "log_y": True}


# Shots and view range

def test_select_shots() -> None:
    view = build_view(dataset(shots={shot: np.ones((1, 3)) for shot in (1, 2, 5, 8, 9)}))
    assert selection.select_shots(view, {}) == (1, 2, 5, 8, 9)
    assert selection.select_shots(view, {"shots": "last N", "last_shots": 2}) == (8, 9)
    assert selection.select_shots(view, {"shots": "last N", "last_shots": 50}) == (1, 2, 5, 8, 9)
    assert selection.select_shots(view, {"shots": "range", "first_shot": 2, "last_shot": 8}) == (2, 5, 8)
    assert selection.select_shots(view, {"shots": "range", "first_shot": 6, "last_shot": 0}) == (8, 9)
    assert selection.select_shots(view, {"shots": "range", "first_shot": 10, "last_shot": 0}) == ()
    # From shot applies whichever Shots is chosen.
    assert selection.select_shots(view, {"first_shot": 3}) == (5, 8, 9)
    assert selection.select_shots(view, {"shots": "last N", "last_shots": 50, "first_shot": 3}) == (5, 8, 9)
    assert selection.select_shots(view, {"shots": "last N", "last_shots": 1, "first_shot": 3}) == (9,)
    assert selection.select_shots(view, {"shots": "range", "last_shot": 5}) == (1, 2, 5)
    assert selection.shots_text((1, 2, 5, 8, 9), 5) == "5 shots"
    assert selection.shots_text((8, 9), 5) == "shots 8–9 (2 of 5)"
    assert selection.shots_text((), 5) == "none of 5 shots"
    assert selection.shots_text((8,), 5) == "shot 8 (1 of 5)"


def test_short_settings_for_the_dock() -> None:
    assert selection.shots_brief({}) == ""
    assert selection.shots_brief({"shots": "last N", "last_shots": 1}) == "last 1 shot"
    assert selection.shots_brief({"shots": "range", "first_shot": 20, "last_shot": 45}) == "shots 20–45"
    assert selection.shots_brief({"shots": "range", "first_shot": 20, "last_shot": 0}) == "shots 20–last"
    assert selection.shots_brief({"shots": "range", "last_shot": 45}) == "shots up to 45"
    assert selection.shots_brief({"first_shot": 20}) == "shots 20–last"
    assert selection.shots_brief({"shots": "last N", "last_shots": 10, "first_shot": 20}) == "last 10 shots from shot 20"
    assert selection.range_brief({"range_mode": "auto-crop", "keep_percent": 99.5}) == "auto-crop 99.5 %"
    manual = {"range_mode": "manual", "t_min": 3.84, "t_max": 3.87, "x_min": -0.002, "x_max": 0.0035,
              "y_min": 1.0, "y_max": 1.0}
    # Only the axes actually set: Y (min = max) is its full extent and left out.
    assert selection.range_brief(manual) == "T 3,840–3,870 ms, X −2–3.5 mm"  # T in ms, X/Y in mm
    assert selection.range_brief({**manual, "x_min": 0.01, "x_max": 0.0, "t_max": 0.0}) == "manual range: full extent"
    assert display_units.range_text(1, -4e-6, 2e-6) == "X −0.004–0.002 mm" and display_units.range_text(0, 0.0, 0.0) == "T 0–0 ms"
    assert display_units.range_text(0, 20.4501234, 20.55) == "T 20,450.1234–20,550 ms"
    view = build_view(dataset(shots={shot: np.ones((1, 3)) for shot in range(1, 61)}))
    scatter, histograms, counts = scatter_3d.Scatter3D(), basic_plots.TxyHistograms(), basic_plots.CountsPerShot()

    def run_text(script: DatasetAnalysis, values: dict[str, Any]) -> tuple[str, str]:
        return script.describe_run("Plot", effective(script.parameters("Plot"), values), view)
    assert run_text(histograms, {"shots": "last N", "last_shots": 10, "log_y": True}) == (
        "shots 51–60 (10 of 60)", "last 10 shots · auto-crop 99 % · bins auto · log Y")
    assert run_text(histograms, {**manual, "bins": 80}) == ("60 shots", "T 3,840–3,870 ms, X −2–3.5 mm · bins 80")
    assert run_text(scatter, {"display_cap": 20_000, "point_size": 2}) == (
        "60 shots", "auto-crop 99 % · points 2 px, opacity 0.5, cap 20,000")
    assert run_text(counts, {}) == ("60 shots", "")
    assert run_text(counts, {"shots": "range", "first_shot": 20, "last_shot": 45}) == (
        "shots 20–45 (26 of 60)", "shots 20–45")


def test_from_shot_past_the_end_with_gaps_and_with_each_mode() -> None:
    # Shot numbers with gaps: From shot, last N and To shot go by shot number, not position.
    view = build_view(dataset(shots={shot: np.ones((1, 3)) for shot in (3, 4, 10, 11, 12, 30)}))

    def chosen(**values: Any) -> tuple[int, ...]:
        return selection.select_shots(view, values)
    assert chosen(first_shot=5) == (10, 11, 12, 30) and chosen(first_shot=10) == (10, 11, 12, 30)
    assert chosen(shots="last N", last_shots=2, first_shot=5) == (12, 30)
    assert chosen(shots="last N", last_shots=9, first_shot=11) == (11, 12, 30)
    assert chosen(shots="range", first_shot=5, last_shot=20) == (10, 11, 12)
    assert chosen(shots="range", first_shot=5, last_shot=9) == ()  # in a gap
    assert chosen(shots="range", first_shot=12, last_shot=12) == (12,)
    assert chosen(shots="range", first_shot=20, last_shot=10) == ()
    # Past the last shot: none, whichever mode, and the dock's first line says why.
    for mode in ("all", "last N", "range"):
        assert chosen(shots=mode, first_shot=31) == ()
    assert selection.selection_text(view, {"first_shot": 31}) == "none of 6 shots (From shot 31 is past the last, 30)"
    assert selection.selection_text(view, {"shots": "range", "first_shot": 5, "last_shot": 9}) == "none of 6 shots"
    assert selection.selection_text(view, {"first_shot": 5}) == "shots 10–30 (4 of 6)"
    assert selection.selection_text(build_view(dataset(shots={})), {"first_shot": 5}) == "0 shots"


def test_from_shot_while_live_adds_shots() -> None:
    first = build_view(dataset(shots={shot: np.ones((1, 3)) for shot in range(1, 6)}))
    later = first.with_shots({shot: np.ones((1, 3)) for shot in (6, 7, 9)})
    settings: list[tuple[dict[str, Any], tuple[int, ...], tuple[int, ...]]] = [
        ({"first_shot": 3}, (3, 4, 5), (3, 4, 5, 6, 7, 9)),  # all from shot 3 grows
        ({"shots": "last N", "last_shots": 2, "first_shot": 3}, (4, 5), (7, 9)),  # last N slides
        ({"shots": "range", "first_shot": 3, "last_shot": 6}, (3, 4, 5), (3, 4, 5, 6)),  # up to 6, then fixed
        ({"first_shot": 8}, (), (9,))]  # none until a shot from 8 arrives
    for values, before, after in settings:
        assert selection.select_shots(first, values) == before and selection.select_shots(later, values) == after
    assert selection.selection_text(first, {"first_shot": 8}) == "none of 5 shots (From shot 8 is past the last, 5)"
    assert selection.selection_text(later, {"first_shot": 8}) == "shot 9 (1 of 8)"


@pytest.mark.parametrize(("values", "brief"), [
    ({}, ""),
    ({"first_shot": 20}, "shots 20–last"),
    ({"shots": "last N", "last_shots": 10}, "last 10 shots"),
    ({"shots": "last N", "last_shots": 1, "first_shot": 20}, "last 1 shot from shot 20"),
    ({"shots": "range"}, ""),
    ({"shots": "range", "first_shot": 20}, "shots 20–last"),
    ({"shots": "range", "last_shot": 45}, "shots up to 45"),
    ({"shots": "range", "first_shot": 20, "last_shot": 45}, "shots 20–45"),
    ({"shots": "range", "first_shot": 20, "last_shot": 20}, "shot 20"),
    ({"shots": "range", "first_shot": 20, "last_shot": 10}, "no shots: To shot 10 is below From shot 20"),
    ({"last_shot": 45}, ""),  # To shot applies only to a range
    ({"shots": "last N", "last_shots": 10, "last_shot": 45}, "last 10 shots"),
])
def test_shots_brief_for_every_combination(values: dict[str, Any], brief: str) -> None:
    assert selection.shots_brief(values) == brief
    # Every plot's settings line starts with it (Transfer fractions' too).
    view = build_view(dataset(shots={shot: np.ones((1, 3)) for shot in range(1, 61)}))
    for script in (basic_plots.CountsPerShot(), transfer_fractions.TransferFractions(), shot_trends.ShotTrends()):
        _, settings = script.describe_run("Plot", effective(script.parameters("Plot"), values), view)
        assert settings.startswith(brief)


def test_manual_box_uses_set_bounds_and_the_data_extent() -> None:
    events = np.array([[0.0, 0.0, 0.0], [1.0, 10.0, -1.0], [2.0, 20.0, 5.0], [3.0, 30.0, 2.0]])
    values = {"range_mode": "manual", "t_min": 0.5, "t_max": 2.5, "x_min": 1.0, "x_max": 1.0}
    assert selection.manual(values) and selection.manual_bounds(values) == ((0.5, 2.5), None, None)
    box = selection.manual_box(events, values)
    assert box.manual and (box.lower, box.upper) == ((0.5, 0.0, -1.0), (2.5, 30.0, 5.0))
    assert (box.kept, box.total, box.left_out) == (2, 4, 2) and math.isnan(box.keep)
    assert box.contains(events).tolist() == [False, True, True, False]
    empty = selection.manual_box(np.empty((0, 3)), values)
    assert empty.total == 0 and empty.lower[0] == 0.5 and math.isnan(empty.lower[1])


def test_reversed_manual_bounds_use_the_full_extent_and_say_so() -> None:
    """min = max is the full extent, silently; min > max is the full extent too, but reported."""
    events = np.array([[0.0, 0.0, 0.0], [1.0, 10.0, -1.0], [2.0, 20.0, 5.0], [3.0, 30.0, 2.0]])
    values = {"range_mode": "manual", "t_min": 0.5, "t_max": 2.5, "x_min": 25.0, "x_max": 5.0}
    assert selection.manual_bounds(values) == ((0.5, 2.5), None, None)
    assert selection.reversed_axes(values) == ("X",)
    assert selection.range_warnings(values) == ("X: min > max, using full extent",)
    assert selection.range_warnings({**values, "range_mode": "auto-crop"}) == ()
    assert selection.range_warnings({"range_mode": "manual", "y_min": 1.0, "y_max": 1.0}) == ()
    box = selection.manual_box(events, values)
    assert (box.lower[1], box.upper[1]) == (0.0, 30.0)
    view = build_view(dataset(shots={1: events}))
    scatter = scatter_3d.Scatter3D()
    data = scatter.compute("Plot", context(view, scatter, values))
    assert data.warnings == ("X: min > max, using full extent",)
    assert scatter.parameter_warnings("Plot", effective(scatter.parameters("Plot"), values)) == list(data.warnings)
    assert scatter_3d.crop_text(data.crop, data.warnings).endswith("· ⚠ X: min > max, using full extent")
    assert scatter_3d.note_text(data).endswith("· ⚠ X: min > max, using full extent")
    result = AnalysisResult.of(context(view, scatter, values), "completed", data)
    drawn_figure: Any = scatter_3d.figure(result, data)  # plotly's layout attributes are untyped
    assert "⚠ X: min > max, using full extent" in drawn_figure.layout.title.text
    histograms = basic_plots.TxyHistograms()
    drawn = histograms.compute("Plot", context(view, histograms, {**values, "bins": 3}))
    assert drawn.reversed == ("X",) and (drawn.items[1].edges[0], drawn.items[1].edges[-1]) == (0.0, 30.0)
    assert basic_plots.histogram_title(drawn.items[1], True).endswith("· ⚠ min > max, using full extent")
    assert not basic_plots.histogram_title(drawn.items[0], False).endswith("full extent")
    assert histograms.parameter_warnings("Plot", values) == ["X: min > max, using full extent"]
    assert basic_plots.CountsPerShot().parameter_warnings("Plot", values) == []


def test_scatter_and_histograms_take_shots_and_manual_ranges() -> None:
    rng = np.random.default_rng(3)
    view = build_view(dataset(shots={shot: rng.normal(size=(1000, 3)) for shot in range(1, 11)}))
    scatter = scatter_3d.Scatter3D()
    values = {"shots": "last N", "last_shots": 2, "range_mode": "manual", "t_min": -1.0, "t_max": 1.0,
              "display_cap": 1000, "point_size": 3, "opacity": 0.2}
    data = scatter.compute("Plot", context(view, scatter, values))
    assert data.shots == (9, 10) and data.total_shots == 10 and data.crop.total == 2000
    assert data.crop.manual and (data.crop.lower[0], data.crop.upper[0]) == (-1.0, 1.0)
    assert data.crop.kept == int(np.count_nonzero(np.abs(view.events((9, 10))[:, 0]) <= 1))
    assert len(data.points) == 1000 and data.cap == 1000
    assert scatter_3d.crop_text(data.crop).startswith(f"Manual range keeps {data.crop.fraction:.1%}")
    assert scatter_3d.note_text(data).endswith("· shots 9–10 (2 of 10)")
    result = AnalysisResult.of(context(view, scatter, values), "completed", data)
    fig: Any = scatter_3d.figure(result, data)
    trace: Any = fig.data[0]
    assert (trace.marker.size, trace.marker.opacity) == (3.0, 0.2) and len(trace.x) == 1000
    assert tuple(fig.layout.scene.zaxis.range) == (-1000.0, 1000.0)  # T in ms
    assert fig.layout.scene.zaxis.title.text == "T (ms)" and fig.layout.scene.xaxis.title.text == "X (mm)"
    assert fig.layout.scene.zaxis.tickformat == ",~f" and "%{z:,.4f} ms" in trace.hovertemplate
    assert list(trace.z) == pytest.approx(list(data.points[:, 0] * 1e3))
    assert "shots 9–10 (2 of 10)" in fig.layout.title.text
    histograms = basic_plots.TxyHistograms()
    items = histograms.compute("Plot", context(view, histograms, {**values, "bins": 5})).items
    t, x, _ = items
    assert (t.edges[0], t.edges[-1]) == (-1.0, 1.0) and t.total == 2000 and t.outside == data.crop.left_out
    assert x.edges[0] == view.events((9, 10))[:, 1].min() and x.outside == 0
    assert all(len(item.counts) == 5 for item in items)
    counts = basic_plots.CountsPerShot()
    shots = counts.compute("Plot", context(view, counts, {"shots": "range", "first_shot": 3, "last_shot": 4}))
    assert shots.shots.tolist() == [3, 4] and shots.total == 2000 and shots.total_shots == 10
    assert basic_plots.counts_title(shots) == "shots 3–4 (2 of 10) · 2,000 events"


def test_histogram_log_y_renders_without_empty_bins(qtbot: QtBot) -> None:
    view = build_view(dataset(shots={1: np.array([[0.0, 0, 0], [0.0, 0, 0], [10.0, 0, 0]])}))
    script = basic_plots.TxyHistograms()
    values = {"bins": 10, "log_y": True, "range_mode": "auto-crop", "keep_percent": 100}
    result = AnalysisResult.of(context(view, script, values), "completed",
                               script.compute("Plot", context(view, script, values)))
    widget: Any = script.render(result)
    qtbot.addWidget(widget)
    plot = widget.getItem(1, 0)
    assert plot.ctrl.logYCheck.isChecked()
    axis = plot.getAxis("left")
    assert isinstance(axis, basic_plots.DecadeLogAxis)
    # Decades labelled, the 2…9 ticks between them not; no decade in view: pyqtgraph's ticks.
    levels = axis.logTickValues(1.7, 3.1, 300, [])
    assert levels[0] == (1.0, [2.0, 3.0]) and levels[1][0] is None
    assert len(levels[1][1]) == 4 + 8  # 6…9 · 10¹ and 2…9 · 10² (2 · 10³ is out of view)
    assert getattr(axis, "style")["maxTextLevel"] == 0  # pyqtgraph's style dict, not QWidget.style()
    assert axis.logTickValues(1.2, 1.8, 300, [])[0][1]
    (item,) = plot.listDataItems()
    _, ys = item.getOriginalDataset()
    assert np.isnan(ys).sum() == 8 and np.nansum(ys) == 3


# Analyses

def scripts_manager() -> ScriptsManager:
    manager = ScriptsManager()
    for module in standard.MODULES:
        manager.load_module(module)
    return manager


def test_bundled_analyses_declare_identity_and_file_hash() -> None:
    manager = scripts_manager()
    names = {metadata.name: metadata for metadata in manager.get_scripts_in_group(group.NAME)}
    assert set(names) == {"3D scatter", "Counts per shot", "Density images", "Shot times", "Shot trends",
                          "T, X, Y histograms", "Mean X, Y against T", "T spectrum", "Transfer fractions",
                          "Release time", "Correlations"}
    scatter = names["3D scatter"]
    expected = hashlib.sha256(open(scatter_3d.__file__, "rb").read()).hexdigest()
    assert (scatter.analysis_id, scatter.version, scatter.file_hash) == ("helab.scatter_3d", "4", expected)
    identity = scatter.identity()
    assert identity.file_name == "scatter_3d.py" and identity.text().startswith("helab.scatter_3d v4 · scatter_3d.py")
    assert all(metadata.analysis_id and metadata.version for metadata in names.values())
    assert group.NAME == f"Basic plots v{group.VERSION}" and group.VERSION == 1


def context(view: DatasetView, script: DatasetAnalysis, values: dict[str, Any] | None = None) -> AnalysisContext:
    return AnalysisContext("a1", "Plot", view, effective(script.parameters("Plot"), values),
                           script.get_metadata().identity())


def test_scatter_samples_for_display_only() -> None:
    rng = np.random.default_rng(2)
    view = build_view(dataset(shots={shot: rng.normal(size=(50_000, 3)) for shot in range(1, 6)}))
    script = scatter_3d.Scatter3D()
    data = script.compute("Plot", context(view, script))
    assert data.crop.total == 250_000 and data.analysed == data.crop.kept >= 247_500
    assert len(data.points) == 100_000 and data.shots == (1, 2, 3, 4, 5) and data.total_shots == 5
    assert np.all(data.crop.contains(data.points))
    text = scatter_3d.sample_text(data)
    assert f"100,000 of {data.analysed:,}" in text and "analysis uses all" in text
    assert scatter_3d.note_text(data).startswith(f"Display sample: 100,000 of {data.analysed:,} events in range")
    result = AnalysisResult.of(context(view, script), "completed", data)
    fig: Any = scatter_3d.figure(result, data)
    trace: Any = fig.data[0]
    assert len(trace.x) == 100_000
    assert "run_1 · rev 1" in fig.layout.title.text and text in fig.layout.title.text
    assert "Auto-crop (heuristic box) keeps 99.0%" in fig.layout.title.text
    assert tuple(fig.layout.scene.zaxis.range) == (data.crop.lower[0] * 1e3, data.crop.upper[0] * 1e3)


def test_scatter_without_crop_shows_every_event() -> None:
    view = build_view(dataset(shots={1: np.arange(30.0).reshape(10, 3)}))
    script = scatter_3d.Scatter3D()
    data = script.compute("Plot", context(view, script, {"keep_percent": 100}))
    assert data.analysed == 10 and len(data.points) == 10
    assert scatter_3d.sample_text(data) == "Showing all 10 events in the range"
    empty = script.compute("Plot", context(build_view(dataset(shots={})), script))
    assert empty.analysed == 0 and scatter_3d.crop_text(empty.crop) == "No events"


def test_basic_plots_compute() -> None:
    view = build_view(dataset(shots={1: np.ones((3, 3)), 4: np.ones((5, 3))}, unsettled_files=1))
    counts = basic_plots.CountsPerShot()
    data = counts.compute("Plot", context(view, counts))
    assert data.shots.tolist() == [1, 4] and data.total == 8
    assert basic_plots.counts_title(data) == "2 shots · 8 events · 1 files still being written left out"
    assert data.total_shots == 2
    histograms = basic_plots.TxyHistograms()
    items = histograms.compute("Plot", context(view, histograms, {"bins": 4})).items
    assert [item.axis for item in items] == ["T", "X", "Y"]
    assert all(len(item.counts) == 4 and int(item.counts.sum()) == 8 for item in items)
    assert basic_plots.histogram_title(items[0]) == "T · 4 bins (set) · 8 of 8 events"


def test_basic_plots_render(qtbot: QtBot) -> None:
    view = build_view(dataset())
    for script in (basic_plots.CountsPerShot(), basic_plots.TxyHistograms()):
        result = AnalysisResult.of(context(view, script), "completed", script.compute("Plot", context(view, script)))
        widget = script.render(result)
        qtbot.addWidget(widget)
        assert isinstance(widget, QWidget)


def test_dataset_analysis_needs_a_context() -> None:
    with pytest.raises(ValueError, match="needs loaded data"):
        scatter_3d.Scatter3D().execute_action("Plot")


# Runner and RAM results

class Blocking(DatasetAnalysis):
    """Counts the view's events once released (tests change things while it waits)."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.entered = threading.Event()
        self.fail = False

    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata("Blocking", "test", "Tests", __file__, "tests.blocking", "3")

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [ParameterSpec("scale", "Scale", "int", 1, (1, 10))]

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        self.entered.set()
        self.release.wait(10)
        if self.fail:
            raise RuntimeError("broken")
        return context.view.event_count * int(context.parameters["scale"])

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        return QLabel(str(result.data), parent)


class Harness:
    def __init__(self) -> None:
        self.runner = AnalysisRunner()
        self.results: list[AnalysisResult] = []
        self.runner.finished.connect(self.results.append)

    def finished(self, qtbot: QtBot, job_id: str) -> AnalysisResult:
        def found() -> list[AnalysisResult]:
            return [result for result in self.results if result.job_id == job_id]
        qtbot.waitUntil(lambda: bool(found()), timeout=10_000)
        return found()[0]


@pytest.fixture
def harness() -> Any:
    made = Harness()
    yield made
    made.runner.stop()


def test_runner_records_identity_input_and_parameters(qtbot: QtBot, harness: Harness) -> None:
    runner = harness.runner
    script = Blocking()
    script.release.set()
    view = build_view(dataset())
    metadata = script.get_metadata()
    metadata.file_hash = "abc"
    job = runner.submit(script, metadata, "Plot", view, {"scale": 30, "junk": 1})
    result = harness.finished(qtbot, job.job_id)
    assert result.state == "completed" and result.data == 60
    assert dict(result.parameters) == {"scale": 10}
    assert result.input == view.key and result.policy == "ram"
    assert (result.analysis.analysis_id, result.analysis.version, result.analysis.file_hash) == \
        ("tests.blocking", "3", "abc")
    record = result.describe("Scale 10")
    assert "tests.blocking v3" in record and "revision 1" in record and "root://" not in record
    assert "Parameters: Scale 10" in record and "kept in RAM only" in record
    assert runner.results.get(job.job_id) is result and runner.results.for_input(view.key) == [result]


class Finding(Blocking):
    """Records what it found; ``broken`` makes that record fail."""

    def __init__(self, broken: bool) -> None:
        super().__init__()
        self.broken = broken
        self.release.set()

    def result_found(self, action_name: str, data: Any) -> dict[str, Any]:
        if self.broken:
            raise ValueError("no record")
        return {"events": data, "record_lines": [f"Found {data} events"]}


def test_runner_keeps_what_a_run_found_and_survives_a_failing_record(
        qtbot: QtBot, harness: Harness, caplog: pytest.LogCaptureFixture) -> None:
    view = build_view(dataset())
    script = Finding(broken=False)
    result = harness.finished(qtbot, harness.runner.submit(script, script.get_metadata(), "Plot", view).job_id)
    assert dict(result.found) == {"events": 6, "record_lines": ["Found 6 events"]}
    assert script.result_record("Plot", result) == ["Found 6 events"]
    assert RamResults().released(result).found == result.found
    broken = Finding(broken=True)
    with caplog.at_level("ERROR"):
        kept = harness.finished(qtbot, harness.runner.submit(broken, broken.get_metadata(), "Plot", view).job_id)
    assert kept.state == "completed" and kept.data == 6 and dict(kept.found) == {}
    assert broken.result_record("Plot", kept) == []
    assert "its record of what the run found failed" in caplog.text


def test_runner_reports_failure_and_cancellation(qtbot: QtBot, harness: Harness) -> None:
    runner = harness.runner
    script = Blocking()
    script.fail = True
    script.release.set()
    view = build_view(dataset())
    failed = harness.finished(qtbot, runner.submit(script, script.get_metadata(), "Plot", view).job_id)
    assert failed.state == "failed" and failed.error == "broken" and runner.results.get(failed.job_id) is None
    slow = Blocking()
    first = runner.submit(slow, slow.get_metadata(), "Plot", view)
    second = runner.submit(slow, slow.get_metadata(), "Plot", view)
    assert slow.entered.wait(5)
    runner.cancel(second.job_id)
    runner.cancel(first.job_id)
    slow.release.set()
    assert harness.finished(qtbot, first.job_id).state == "cancelled"
    assert harness.finished(qtbot, second.job_id).state == "cancelled"


def test_stop_keeps_a_blocked_worker_registered(qtbot: QtBot, harness: Harness) -> None:
    runner = harness.runner
    script = Blocking()  # ignores cancellation
    view = build_view(dataset())
    first = runner.submit(script, script.get_metadata(), "Plot", view)
    assert script.entered.wait(5)
    assert runner.stop(timeout=0.2) is False  # still computing after the join timed out
    with pytest.raises(RuntimeError, match="stopping"):
        runner.submit(script, script.get_metadata(), "Plot", view)
    script.release.set()
    assert harness.finished(qtbot, first.job_id).state == "cancelled"
    qtbot.waitUntil(lambda: runner._thread is None, timeout=5_000)
    # Exited: the runner takes work again, on one new worker.
    again = runner.submit(script, script.get_metadata(), "Plot", view)
    assert harness.finished(qtbot, again.job_id).state == "completed"
    assert runner.stop() is True


def test_ram_results_drop_least_recent_unpinned() -> None:
    store = RamResults(limit=2)
    view = build_view(dataset())
    script = Blocking()

    def made(job_id: str) -> AnalysisResult:
        return AnalysisResult.of(AnalysisContext(job_id, "Plot", view, {}, script.get_metadata().identity()),
                                 "completed")

    store.add(made("a"))
    store.pin("a")
    store.add(made("b"))
    store.add(made("c"))
    assert store.get("a") is not None and store.get("b") is None and len(store) == 2
