"""Dataset view, auto-crop, sampling, counts, histograms and the analysis runner, on known arrays."""
from __future__ import annotations

import hashlib
import math
import threading
import time
from typing import Any, List, Optional

import numpy as np
import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtWidgets import QLabel, QWidget

from helab.analysis.dataset_view import DatasetView, ViewKey, build_view, root_key, view_of
from helab.analysis.parameters import ParameterSpec, describe, effective
from helab.analysis.results import AnalysisContext, AnalysisResult, RamResults
from helab.analysis.runner import AnalysisRunner
from helab.analysis.stats import (
    MAX_BINS, central_range, counts_per_shot, crop_box, display_sample, freedman_diaconis_bins, histogram)
from helab.scripts import standard
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.scripts_manager import ScriptsManager
from helab.scripts.standard import basic_plots, scatter_3d
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
    # The arrays are shared, never copied, and can't be written.
    assert view.shots[2] is shown.data[2]
    with pytest.raises(ValueError):
        view.shots[2][0, 0] = 5
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
    assert array.flags.writeable  # the browser's own array is left as it was
    assert view.provenance.checked_at is None and view.identity.root_key == ""


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
    assert central_range(np.array([1.0, 2.0, 3.0]), 1.0) == (1.0, 3.0)
    assert freedman_diaconis_bins(np.zeros(10), 0, 0) == 1
    assert freedman_diaconis_bins(np.array([0.0, 1e-12, 1.0]), 0.0, 1.0) <= MAX_BINS


# Parameters

def test_parameters_are_validated_and_described() -> None:
    specs = [ParameterSpec("keep", "Keep", "float", 99.0, (50.0, 100.0), " %"),
             ParameterSpec("bins", "Bins", "int", 0, (0, 10))]
    assert effective(specs, {"keep": "120", "bins": 3.7, "other": 1}) == {"keep": 100.0, "bins": 3}
    assert effective(specs) == {"keep": 99.0, "bins": 0}
    assert describe(specs, {"keep": 99.0, "bins": 0}) == "Keep 99 %, Bins 0"
    assert specs[0].tree_item()["limits"] == (50.0, 100.0)


# Analyses

def scripts_manager() -> ScriptsManager:
    manager = ScriptsManager()
    for module in standard.MODULES:
        manager.load_module(module)
    return manager


def test_bundled_analyses_declare_identity_and_file_hash() -> None:
    manager = scripts_manager()
    names = {metadata.name: metadata for metadata in manager.get_scripts_in_group("Plots")}
    assert set(names) == {"3D scatter", "Counts per shot", "T, X, Y histograms"}
    scatter = names["3D scatter"]
    expected = hashlib.sha256(open(scatter_3d.__file__, "rb").read()).hexdigest()
    assert (scatter.analysis_id, scatter.version, scatter.file_hash) == ("helab.scatter_3d", "1", expected)
    identity = scatter.identity()
    assert identity.file_name == "scatter_3d.py" and identity.text().startswith("helab.scatter_3d v1 · scatter_3d.py")
    assert all(metadata.analysis_id and metadata.version for metadata in names.values())


def context(view: DatasetView, script: DatasetAnalysis, values: dict[str, Any] | None = None) -> AnalysisContext:
    return AnalysisContext("a1", "Plot", view, effective(script.parameters("Plot"), values),
                           script.get_metadata().identity())


def test_scatter_samples_for_display_only() -> None:
    rng = np.random.default_rng(2)
    view = build_view(dataset(shots={shot: rng.normal(size=(50_000, 3)) for shot in range(1, 6)}))
    script = scatter_3d.Scatter3D()
    data = script.compute("Plot", context(view, script))
    assert data.crop.total == 250_000 and data.analysed == data.crop.kept >= 247_500
    assert len(data.points) == 100_000 and data.shots == 5
    assert np.all(data.crop.contains(data.points))
    text = scatter_3d.sample_text(data)
    assert f"100,000 of {data.analysed:,}" in text and "analysis uses all" in text
    assert scatter_3d.note_text(data).startswith(f"Display sample: 100,000 of {data.analysed:,} cropped events")
    result = AnalysisResult.of(context(view, script), "completed", data)
    fig = scatter_3d.figure(result, data)
    trace: Any = fig.data[0]
    assert len(trace.x) == 100_000
    assert "run_1 · rev 1" in fig.layout.title.text and text in fig.layout.title.text
    assert "Auto-crop keeps 99.0%" in fig.layout.title.text
    assert tuple(fig.layout.scene.zaxis.range) == (data.crop.lower[0], data.crop.upper[0])


def test_scatter_without_crop_shows_every_event() -> None:
    view = build_view(dataset(shots={1: np.arange(30.0).reshape(10, 3)}))
    script = scatter_3d.Scatter3D()
    data = script.compute("Plot", context(view, script, {"keep_percent": 100}))
    assert data.analysed == 10 and len(data.points) == 10
    assert scatter_3d.sample_text(data) == "Showing all 10 events in the crop"
    empty = script.compute("Plot", context(build_view(dataset(shots={})), script))
    assert empty.analysed == 0 and scatter_3d.crop_text(empty.crop) == "No events"


def test_basic_plots_compute() -> None:
    view = build_view(dataset(shots={1: np.ones((3, 3)), 4: np.ones((5, 3))}, unsettled_files=1))
    counts = basic_plots.CountsPerShot()
    data = counts.compute("Plot", context(view, counts))
    assert data.shots.tolist() == [1, 4] and data.total == 8
    assert basic_plots.counts_title(data) == "2 shots · 8 events · 1 files still being written left out"
    histograms = basic_plots.TxyHistograms()
    items = histograms.compute("Plot", context(view, histograms, {"bins": 4}))
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
