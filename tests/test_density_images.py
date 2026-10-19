"""2D density images (XY, XT, YT): binning, rate per shot, blur, colour compression, empty
views and ranges, rendering offscreen and drawing in place."""
from __future__ import annotations

import math
from typing import Any, cast

import numpy as np
import pyqtgraph as pg
import pytest
from PyQt6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from helab.analysis.dataset_view import DatasetView, build_view
from helab.analysis.parameters import effective
from helab.analysis.results import AnalysisContext, AnalysisResult, Cancelled
from helab.scripts.scripts_manager import ScriptsManager
from helab.scripts.standard import density_images, group
from helab.scripts.standard.density_images import DensityImage, DensityImages, DensityPlot
from helab.utils.folder_cache import Dataset
from helab.utils.ram_buffers import arrays_in, buffers

SCRIPT = DensityImages()


def view_of(shots: dict[int, Any]) -> DatasetView:
    for array in shots.values():
        array.setflags(write=False)
    fingerprint = [[shot, 100 + shot, 1_000 + shot] for shot in sorted(shots)]
    return build_view(Dataset("/data/root/run_D", "sig-1", shots, {"fingerprint": fingerprint, "source": "merged",
                                                                   "loaded_at": 1_700_000_000.0}, 0))


def cloud(seed: int = 0, shots: int = 4, events: int = 2000) -> DatasetView:
    """Events around T 0.42 s, X 0 and Y 1 mm, in s and m like the TXY files."""
    rng = np.random.default_rng(seed)
    return view_of({shot: np.column_stack([rng.normal(0.42, 0.002, events), rng.normal(0.0, 0.004, events),
                                           rng.normal(0.001, 0.003, events)]) for shot in range(1, shots + 1)})


def context(view: DatasetView, values: dict[str, Any] | None = None) -> AnalysisContext:
    return AnalysisContext("a1", "Plot", view, effective(SCRIPT.parameters("Plot"), values),
                           SCRIPT.get_metadata().identity())


def run(view: DatasetView, values: dict[str, Any] | None = None) -> AnalysisResult:
    made = context(view, values)
    return AnalysisResult.of(made, "completed", SCRIPT.compute("Plot", made))


MANUAL = {"range_mode": "manual", "t_min": 0.41, "t_max": 0.43, "x_min": -0.01, "x_max": 0.01,
          "y_min": -0.01, "y_max": 0.012}


@pytest.mark.parametrize("projection", ["XY", "XT", "YT"])
def test_counts_match_numpys_histogram2d(projection: str) -> None:
    view = cloud()
    data: DensityImage = run(view, {**MANUAL, "projection": projection, "bins": 40}).data
    events = view.events(view.shot_numbers)
    box = np.array([[0.41, -0.01, -0.01], [0.43, 0.01, 0.012]])
    inside = events[np.all((events >= box[0]) & (events <= box[1]), axis=1)]
    h, v = density_images.PROJECTIONS[projection]
    expected, edges_h, edges_v = np.histogram2d(inside[:, h], inside[:, v], bins=40,
                                                range=((box[0, h], box[1, h]), (box[0, v], box[1, v])))
    assert data.image.shape == (40, 40) and np.array_equal(data.image, expected)
    assert np.array_equal(data.edges_h, edges_h) and np.array_equal(data.edges_v, edges_v)
    assert data.events == len(inside) == int(data.image.sum()) and data.total == len(events)
    assert data.axes == (h, v) and not data.automatic_bins and not data.per_shot


def test_rate_per_shot_divides_by_shots_and_bin_area_in_display_units() -> None:
    view = cloud(shots=5)
    counts = run(view, {**MANUAL, "projection": "XT", "bins": 20}).data
    rate = run(view, {**MANUAL, "projection": "XT", "bins": 20, "quantity": density_images.PER_SHOT}).data
    # T in ms (its range is under 10 s), X in mm.
    assert rate.time_unit == "ms" and rate.unit(0) == "ms" and rate.unit(1) == "mm"
    area = (0.02 / 20 * 1e3) * (0.02 / 20 * 1e3)
    assert np.allclose(rate.image, counts.image / (5 * area))
    assert rate.quantity_text() == "Events / (mm·ms) / shot"
    xy = run(view, {**MANUAL, "bins": 10, "quantity": density_images.PER_SHOT}).data
    assert xy.quantity_text() == "Events / mm² / shot"
    assert np.isclose(xy.image.sum() * (20 / 10) * (22 / 10), xy.events / 5)
    assert counts.quantity_text() == "Events per bin"


def test_time_unit_is_chosen_from_the_range() -> None:
    assert density_images.time_unit(0.41, 0.43) == ("ms", 1e3)
    assert density_images.time_unit(3.84, 3.87) == ("ms", 1e3)
    assert density_images.time_unit(0.0, 12.0) == ("s", 1.0)
    assert density_images.time_unit(math.nan, math.nan) == ("s", 1.0)


@pytest.mark.parametrize("sigma", [0.5, 2.0, 30.0])
def test_blur_keeps_the_total(sigma: float) -> None:
    view = cloud()
    plain = run(view, {**MANUAL, "bins": 25}).data
    smooth = run(view, {**MANUAL, "bins": 25, "blur": sigma}).data
    assert np.isclose(smooth.image.sum(), plain.image.sum()) and not np.array_equal(smooth.image, plain.image)
    assert smooth.image.max() < plain.image.max() and smooth.quantity_text() == "Events per bin (blurred)"
    assert density_images.blurred(plain.image, 0.0) is plain.image


def test_colour_compression_changes_the_colours_only() -> None:
    view = cloud()
    linear = run(view, {**MANUAL, "bins": 30}).data
    for scale in (density_images.SQRT, density_images.LOG, density_images.POWER):
        compressed = run(view, {**MANUAL, "bins": 30, "colour_scale": scale, "gamma": 0.3}).data
        assert np.array_equal(compressed.image, linear.image)
    x = np.linspace(0.0, 1.0, 11)
    assert np.allclose(density_images.compress(x, density_images.SQRT), np.sqrt(x))
    assert np.allclose(density_images.compress(x, density_images.POWER, gamma=2.0), x ** 2)
    assert np.array_equal(density_images.compress(x, density_images.LINEAR), x)
    log = density_images.compress(np.array([0.0, 1e-3, 1e-2, 0.1, 1.0]), density_images.LOG, decades=3)
    assert np.allclose(log, [0.0, 0.0, 1 / 3, 2 / 3, 1.0])
    for scale in (density_images.LINEAR, density_images.SQRT, density_images.LOG, density_images.POWER):
        assert np.all(np.diff(density_images.compress(np.linspace(0, 1, 101), scale)) >= 0)
    # The colour map is resampled, linear in value: half-way in value is sqrt(½) of viridis for sqrt.
    cmap: Any = density_images.colour_map(density_images.SQRT)
    viridis: Any = pg.colormap.get("viridis")
    assert np.allclose(cmap.map(np.array([0.5]), mode="float"), viridis.map(np.array([math.sqrt(0.5)]), mode="float"),
                       atol=5e-3)  # colours as bytes: within 1/255


def test_auto_crop_and_automatic_bins() -> None:
    view = cloud()
    data = run(view).data
    assert data.automatic_bins and not data.box.manual and data.box.fraction >= 0.99
    assert 1 < data.image.shape[0] <= density_images.AUTO_BINS_CAP
    assert data.events == int(data.image.sum())
    assert SCRIPT.describe_run("Plot", effective(SCRIPT.parameters("Plot")), view) == (
        "4 shots", "XY · auto-crop 99 % · bins auto")
    values = effective(SCRIPT.parameters("Plot"), {"projection": "YT", "bins": 50, "blur": 1.5, "colour_scale": "log",
                                                   "quantity": density_images.PER_SHOT, "shots": "last N",
                                                   "last_shots": 2})
    assert SCRIPT.describe_run("Plot", values, view) == (
        "shots 3–4 (2 of 4)", "YT · last 2 shots · auto-crop 99 % · bins 50 · blur 1.5 · per shot · "
                              "colour log 3 decades")


def test_shots_choose_the_events_and_coverage() -> None:
    view = cloud(shots=6)
    data = run(view, {**MANUAL, "shots": "range", "first_shot": 2, "last_shot": 3, "bins": 10}).data
    assert data.shots == (2, 3) and data.total == 4000 and data.total_shots == 6
    values = effective(SCRIPT.parameters("Plot"), {"shots": "last N", "last_shots": 2})
    assert tuple(SCRIPT.covered_shots("Plot", values, view)) == (5, 6)


def test_empty_selections_and_an_empty_range_say_why(qtbot: QtBot) -> None:
    cases: dict[str, tuple[DatasetView, dict[str, Any]]] = {
        "No shots yet": (view_of({}), {}),
        "None of the 4 shots is chosen (Shots settings)": (cloud(), {"first_shot": 10}),
        "No events in the chosen shots": (view_of({1: np.empty((0, 3)), 2: np.empty((0, 3))}), {}),
        "None of the 8,000 events in the chosen shots is inside the view range (View range settings)":
            (cloud(), {"range_mode": "manual", "t_min": 5.0, "t_max": 6.0})}
    for text, (view, values) in cases.items():
        result = run(view, values)
        widget = SCRIPT.render(result)
        qtbot.addWidget(widget)
        assert isinstance(widget, QLabel) and widget.objectName() == "plot_empty" and widget.text() == text
        assert density_images.empty_reason(result.data) == text


def test_a_reversed_manual_range_uses_the_full_extent_and_warns(qtbot: QtBot) -> None:
    view = cloud()
    values = {"range_mode": "manual", "x_min": 0.01, "x_max": -0.01, "bins": 12}
    data = run(view, values).data
    events = view.events(view.shot_numbers)
    assert data.warnings == ("X: min > max, using full extent",)
    assert (data.edges_h[0], data.edges_h[-1]) == (events[:, 1].min(), events[:, 1].max())
    assert data.events == data.total == len(events)
    assert SCRIPT.parameter_warnings("Plot", effective(SCRIPT.parameters("Plot"), values)) == list(data.warnings)
    assert density_images.image_title(data)[1].endswith("· ⚠ X: min > max, using full extent")
    # Nothing in a reversed range's box: the empty note keeps the warning.
    empty = run(view, {**values, "t_min": 5.0, "t_max": 6.0}).data
    assert density_images.empty_reason(empty).endswith("· ⚠ X: min > max, using full extent")


def test_all_events_at_one_value_get_a_small_range() -> None:
    view = view_of({1: np.tile([0.42, 0.001, 0.002], (5, 1))})
    data = run(view, {"bins": 3}).data
    assert data.events == 5 and int(data.image.sum()) == 5
    assert np.isclose(data.edges_h[-1] - data.edges_h[0], 1e-3)


@pytest.mark.parametrize("projection", ["XY", "XT", "YT"])
def test_rendering_draws_an_image_of_the_right_shape(qtbot: QtBot, projection: str) -> None:
    view = cloud()
    result = run(view, {**MANUAL, "projection": projection, "bins": 30, "colour_scale": "sqrt"})
    widget = SCRIPT.render(result)
    qtbot.addWidget(widget)
    assert isinstance(widget, DensityPlot)
    (image,) = [cast(Any, item) for item in widget.plot.items if isinstance(item, pg.ImageItem)]
    assert image is widget.image and image.image.shape == (30, 30)
    rect = image.mapRectToParent(image.boundingRect())
    h, v = density_images.PROJECTIONS[projection]
    low = np.array([0.41 * 1e3, -10.0, -10.0])
    high = np.array([0.43 * 1e3, 10.0, 12.0])
    assert np.allclose([rect.left(), rect.right()], [low[h], high[h]])
    assert np.allclose([rect.top(), rect.bottom()], [low[v], high[v]])
    axis_names = {"XY": ("X (mm)", "Y (mm)"), "XT": ("T (ms)", "X (mm)"), "YT": ("T (ms)", "Y (mm)")}[projection]
    assert (widget.plot.getAxis("bottom").labelText, widget.plot.getAxis("left").labelText) == axis_names
    assert widget.bar is not None and widget.bar.levels() == (0.0, float(result.data.image.max()))
    assert widget.bar.getAxis("left").labelText == "Events per bin"
    assert widget.contour.data is None  # No highlight by default.
    assert widget.plot.getViewBox().state["aspectLocked"] == (1 if projection == "XY" else False)


def test_the_newest_shot_is_contoured(qtbot: QtBot) -> None:
    view = cloud(shots=3)
    result = run(view, {**MANUAL, "bins": 20, "highlight_newest": True, "newest_colour": "orange"})
    data: DensityImage = result.data
    assert data.newest_shot == 3 and data.colour == (255, 127, 14) and data.newest.shape == (20, 20)
    assert np.isclose(data.newest.sum(), data.newest_events) and data.newest_events <= 2000
    widget = SCRIPT.render(result)
    qtbot.addWidget(widget)
    assert isinstance(widget, DensityPlot)
    assert widget.contour.data is data.newest and widget.contour.level == data.newest.max() / 2
    assert widget.contour.pen.color().getRgb()[:3] == (255, 127, 14)
    assert "shot 3 contoured" in density_images.image_title(data)[1]


def test_a_rerun_draws_in_place_keeping_the_view(qtbot: QtBot) -> None:
    first = run(cloud(seed=1, shots=2), {"bins": 20})
    widget = SCRIPT.render(first)
    qtbot.addWidget(widget)
    assert isinstance(widget, DensityPlot)
    image, bar = widget.image, widget.bar
    widget.plot.getViewBox().setRange(xRange=(-1, 1), yRange=(-1, 1), padding=0)
    second = run(cloud(seed=2, shots=3), {"bins": 25, "highlight_newest": True})
    assert SCRIPT.update(widget, second)
    assert widget.image is image and widget.bar is bar and image.image.shape == (25, 25)
    assert widget.contour.data is not None
    assert np.allclose(widget.plot.getViewBox().viewRange(), [[-1, 1], [-1, 1]])  # The zoom stays.
    assert "3 shots" in widget.title.text
    # A new colour scale replaces the bar; the highlight off clears the contour.
    third = run(cloud(seed=2, shots=3), {"bins": 25, "colour_scale": "sqrt"})
    assert SCRIPT.update(widget, third) and widget.bar is not bar and widget.contour.data is None
    # Another projection, or nothing to draw: drawn anew.
    assert not SCRIPT.update(widget, run(cloud(), {"projection": "XT"}))
    assert not SCRIPT.update(widget, run(view_of({}), {}))
    assert not SCRIPT.update(QLabel(), second)


def test_the_result_arrays_count_toward_the_ram_budget() -> None:
    data: DensityImage = run(cloud(), {**MANUAL, "bins": 50, "highlight_newest": True}).data
    counted = buffers(arrays_in(data))
    for array in (data.image, data.newest, data.edges_h, data.edges_v):
        assert any(size >= array.nbytes for size in counted.values())
    assert sum(counted.values()) >= data.image.nbytes + data.newest.nbytes


def test_cancelled_runs_stop() -> None:
    made = context(cloud())
    made.cancel_event.set()
    with pytest.raises(Cancelled):
        SCRIPT.compute("Plot", made)


def test_discovered_in_the_bundled_group() -> None:
    manager = ScriptsManager()
    manager.load_module(density_images)
    (metadata,) = manager.get_scripts_in_group(group.NAME)
    assert (metadata.name, metadata.analysis_id, metadata.version) == ("Density images", "helab.density_images", "1")
    assert manager.get_script(metadata.script_id) is DensityImages
    assert SCRIPT.get_actions() == ["Plot"]
    assert SCRIPT.live_policy("Plot").min_delay == 2.0
