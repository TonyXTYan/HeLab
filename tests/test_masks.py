"""XY circle masks (D9), their presets, the plots that apply them, and the hot-spot finder's
placeholder (D15): keep/cut logic, parsing, the presets' un-rotation, every wired plot, the
reuse key, the circles drawn on XY, and the finder offering circles without applying them."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from helab.analysis import hotspots, masks
from helab.analysis.dataset_view import DatasetView, build_view
from helab.analysis.masks import CUSTOM, CURRENT, EARLIER, NONE, PRESET, Circle, Mask, MaskError, parse_circles
from helab.analysis.parameter_tree import CommitTextEdit, build_tree, parameter_of, settings_widget, tree_values
from helab.analysis.parameters import ParameterSpec, effective
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.scripts.base import DatasetAnalysis
from helab.scripts.standard import (basic_plots, density_images, mean_position, scatter_3d, shot_times, shot_trends,
                                    t_spectrum, transfer_fractions)
from helab.scripts.standard.density_images import FIND, PLOT, DensityImages, DensityPlot, HotSpots, HotSpotsPlot
from helab.utils.folder_cache import Dataset

MM = 1e-3


def view_of(shots: dict[int, Any]) -> DatasetView:
    for array in shots.values():
        array.setflags(write=False)
    prints = [[shot, 100 + shot, int((1_700_000_000 + 10 * shot) * 1e9)] for shot in sorted(shots)]
    return build_view(Dataset("/data/root/run_M", "sig-mask", shots, {"fingerprint": prints, "source": "merged"}, 0))


def run(script: DatasetAnalysis, view: DatasetView, values: dict[str, Any] | None = None,
        action: str = "Plot") -> AnalysisResult:
    context = AnalysisContext("a1", action, view, effective(script.parameters(action), values or {}),
                              script.get_metadata().identity())
    data = script.compute(action, context)
    return AnalysisResult.of(context, "completed", data, found=script.result_found(action, data))


def xy(*points: tuple[float, float]) -> np.ndarray:
    """Events at these (x, y) in mm, T 0.4 s."""
    return np.array([[0.4, x * MM, y * MM] for x, y in points], dtype=np.float64)


# Keep and cut

def test_cut_removes_inside_and_keep_keeps_inside_with_the_boundary_outside() -> None:
    events = xy((0, 0), (1, 0), (2, 0), (3, 0))
    cut = Mask((Circle(0.0, 0.0, 2 * MM),))
    keep = Mask((Circle(0.0, 0.0, 2 * MM, keep=True),))
    # Inside is strictly closer than r (masktxy_2d_circle's "<"): the event at r = 2 mm is outside.
    assert cut.keeps(events).tolist() == [False, False, True, True]
    assert keep.keeps(events).tolist() == [True, True, False, False]
    kept, removed = cut.apply(events)
    assert removed == 2 and np.array_equal(kept, events[2:])
    assert Mask().apply(events) == (events, 0)  # no circles: the events as they are


def test_several_circles_are_anded() -> None:
    events = xy((0, 0), (5, 0), (10, 0), (-5, 0), (3, 4), (20, 0))
    # Two keep circles keep only their overlap; a cut inside it removes more.
    mask = Mask((Circle(0.0, 0.0, 8 * MM, keep=True), Circle(4 * MM, 0.0, 8 * MM, keep=True),
                 Circle(3 * MM, 4 * MM, 0.5 * MM)))
    assert mask.keeps(events).tolist() == [True, True, False, False, False, False]
    assert mask.counts() == (2, 1)


def test_the_lookup_grid_answers_as_the_exact_test() -> None:
    rng = np.random.default_rng(4)
    preset = masks.mask_from({"mask_mode": PRESET, "mask_preset": EARLIER})
    custom = Mask((Circle(1e-3, 2e-3, 3e-3), Circle(1.02e-3, 2e-3, 0.05e-3, keep=True), Circle(5.0, 5.0, 0.01)))
    for mask in (preset, custom, Mask((Circle(0.0, 0.0, 1e-3, keep=True),))):
        events = np.column_stack([np.zeros(200_000), rng.normal(0, 0.03, (200_000, 2))])
        # Points exactly on each circle (strictly inside is the rule), at its centre, and not a number.
        angles = rng.uniform(0, 2 * np.pi, 50)
        rims = [np.column_stack([np.zeros(50), c.x + c.r * np.cos(angles), c.y + c.r * np.sin(angles)])
                for c in mask.circles]
        odd = np.array([[0, np.nan, 0.0], [0, 0.0, np.inf], [0, 1e9, -1e9]])
        events = np.concatenate([events, *rims, odd])
        assert np.array_equal(mask.keeps(events), mask.keeps_exactly(events))
    grid = masks.raster(preset.circles)
    assert grid.cell == masks.GRID_CELL and (grid.status == masks.EDGE).mean() < 0.02


def test_custom_circles_parse_with_defaults_and_round_trip() -> None:
    circles = parse_circles(" 0, 0, 38, keep; 30.5,5,4.5\n-2.48, −34.8, 2, cut ;; 1,2,3,0\n")
    assert circles == (Circle(0.0, 0.0, 38 * MM, True), Circle(30.5 * MM, 5 * MM, 4.5 * MM),
                       Circle(-2.48 * MM, -34.8 * MM, 2 * MM), Circle(1 * MM, 2 * MM, 3 * MM))
    text = masks.format_circles(circles)
    assert text.splitlines()[0] == "0, 0, 38, keep" and "-2.48, -34.8, 2, cut" in text
    assert all(math.isclose(a.x, b.x) and math.isclose(a.r, b.r) and a.keep == b.keep
               for a, b in zip(parse_circles(text), circles))
    assert parse_circles("") == () and parse_circles(" ; \n") == ()


@pytest.mark.parametrize("text, message", [
    ("1, 2", "needs x, y and r"),
    ("1, 2, 3, 4, 5", "use “.” for decimals"),
    ("1, 2, 3, keep, 5", "needs x, y and r"),
    ("1,5, 2, 3", "use “.” for decimals: “,” separates x, y, r"),
    ("1,5, 2,5, 3", "use “.” for decimals"),
    ("a, 2, 3", "must be numbers in mm"),
    ("1, 2, 0", "radius must be above 0"),
    ("1, 2, -3", "radius must be above 0"),
    ("1, nan, 3", "finite"),
    ("1, 2, 3, maybe", "keep or cut, not “maybe”"),
])
def test_invalid_circles_name_the_circle_and_why(text: str, message: str) -> None:
    with pytest.raises(MaskError) as error:
        parse_circles(f"0, 0, 38, keep; {text}")
    assert message in str(error.value) and f"“{text}”" in str(error.value)


def test_invalid_circles_fail_the_run_and_warn_in_the_settings() -> None:
    values = {"mask_mode": CUSTOM, "mask_circles": "1, 2"}
    script = basic_plots.TxyHistograms()
    view = view_of({1: xy((0, 0), (1, 1))})
    with pytest.raises(MaskError, match="needs x, y and r"):
        run(script, view, values)
    assert any("needs x, y and r" in warning for warning in script.parameter_warnings("Plot", values))
    assert "mask: ⚠ circles can't be read" in script.describe_run("Plot", effective(script.parameters("Plot"), values),
                                                                  view)[1]


def test_briefs_and_empty_masks() -> None:
    assert masks.mask_brief({"mask_mode": NONE}) == ""
    assert masks.mask_brief({"mask_mode": CUSTOM, "mask_circles": "1,1,1; 2,2,1; 3,3,1"}) == "mask: 3 cut circles"
    assert masks.mask_brief({"mask_mode": CUSTOM, "mask_circles": "0,0,38,keep; 2,2,1"}) == \
        "mask: 1 keep and 1 cut circles"
    assert masks.mask_brief({"mask_mode": PRESET, "mask_preset": EARLIER}) == \
        "mask: earlier detector (2020), 1 keep and 13 cut circles"
    assert masks.mask_brief({"mask_mode": PRESET, "mask_preset": CURRENT}) == "mask: current detector, no circles"
    assert masks.mask_warnings({"mask_mode": PRESET, "mask_preset": CURRENT}) == (
        "Mask preset “current detector” has no circles yet: nothing masked",)
    assert masks.mask_warnings({"mask_mode": CUSTOM, "mask_circles": ""}) == ("Mask: no circles typed: nothing masked",)
    assert masks.mask_warnings({"mask_mode": PRESET, "mask_preset": EARLIER}) == ()


# Presets

def test_rotation_round_trip_and_the_labs_matrix() -> None:
    rng = np.random.default_rng(3)
    for x, y in rng.normal(0, 0.02, (20, 2)):
        back = masks.rotate(*masks.unrotate(x, y), masks.LEGACY_ROTATION)
        assert math.isclose(back[0], x, abs_tol=1e-15) and math.isclose(back[1], y, abs_tol=1e-15)
    # The lab's import: txy · [1 0 0; 0 cos α −sin α; 0 sin α cos α], α = −dld_xy_rot (row vectors).
    alpha = -masks.LEGACY_ROTATION
    matrix = np.array([[1, 0, 0], [0, math.cos(alpha), -math.sin(alpha)], [0, math.sin(alpha), math.cos(alpha)]])
    preset = masks.PRESETS[EARLIER]
    for circle, (x0, y0, r0, polarity) in zip(preset, masks.EARLIER_ROTATED):
        rotated = np.array([0.0, circle.x, circle.y]) @ matrix  # HeLab's centre, as the lab would see it
        assert np.allclose(rotated[1:], (x0, y0), atol=1e-15)
        assert circle.r == r0 and circle.keep == bool(polarity)
    assert preset[0] == Circle(0.0, 0.0, 38e-3, True)  # the origin doesn't move
    assert len(preset) == 14 and sum(not circle.keep for circle in preset) == 13
    assert masks.PRESETS[CURRENT] == ()


def test_the_presets_circles_are_in_the_record_and_reuse_key() -> None:
    assert masks.MASK_PRESET.text(EARLIER).startswith("Preset earlier detector (2020) (0, 0, 38, keep; 25.144, ")
    assert masks.MASK_PRESET.text(CURRENT) == "Preset current detector (no circles)"
    view, _ = spotted_view(1)
    result = run(basic_plots.CountsPerShot(), view, {"mask_mode": PRESET})
    circles = result.reuse_key()["mask_preset_circles"]
    assert len(circles) == 14 and circles[0] == [0.0, 0.0, 0.038, True]
    assert "mask_preset_circles" not in run(basic_plots.CountsPerShot(), view, MASK).reuse_key()


def test_the_preset_cuts_an_event_on_a_hot_spot_in_heLabs_frame() -> None:
    # An event at the first cut circle's centre in the lab's rotated frame, taken back to HeLab's.
    x, y = masks.unrotate(5.788e-3, 35.61e-3)
    events = np.array([[0.4, x, y], [0.4, 5.788e-3, 35.61e-3], [0.4, 0.0, 0.0], [0.4, 0.039, 0.0]])
    kept = masks.mask_from({"mask_mode": PRESET, "mask_preset": EARLIER}).keeps(events)
    # The spot's HeLab position is cut; its rotated-frame position isn't a spot here; outside 38 mm is cut.
    assert kept.tolist() == [False, True, True, False]


# Every wired plot

SPOT = (20.0, 5.0)  # mm: a planted cluster the mask cuts
MASK = {"mask_mode": CUSTOM, "mask_circles": f"{SPOT[0]}, {SPOT[1]}, 2, cut"}


def spotted_view(shots: int = 4) -> tuple[DatasetView, int]:
    """Shots of events at T ≈ order 0 of Transfer fractions' defaults over ±25 mm, plus a cluster at
    ``SPOT``; and how many events the cut circle takes."""
    rng = np.random.default_rng(7)
    arrays, inside = {}, 0
    for shot in range(1, shots + 1):
        n, m = 2000, 150
        x = np.concatenate([rng.uniform(-0.025, 0.025, n), rng.normal(SPOT[0] * MM, 0.3 * MM, m)])
        y = np.concatenate([rng.uniform(-0.025, 0.025, n), rng.normal(SPOT[1] * MM, 0.3 * MM, m)])
        t = rng.normal(2.1375, 0.0005, n + m)
        arrays[shot] = np.column_stack([t, x, y])
        inside += int(np.count_nonzero(np.hypot(x - SPOT[0] * MM, y - SPOT[1] * MM) < 2 * MM))
    return view_of(arrays), inside


def total_of(data: Any) -> int:
    if isinstance(data, basic_plots.ShotCounts):
        return data.total
    if isinstance(data, shot_times.ShotTimes):
        return int(data.counts.sum())
    if isinstance(data, basic_plots.Histograms):
        return data.items[0].total
    if isinstance(data, scatter_3d.ScatterData):
        return data.crop.total
    if isinstance(data, (transfer_fractions.Fractions, shot_trends.Trends)):
        return int(data.counts.sum())
    return int(data.total)  # DensityImage, PositionProfile, ProfileSpectrum


WIRED: list[DatasetAnalysis] = [basic_plots.CountsPerShot(), shot_times.ShotTimesPlot(), basic_plots.TxyHistograms(),
                                density_images.DensityImages(), mean_position.MeanPositionVsT(),
                                t_spectrum.TProfileSpectrum(), scatter_3d.Scatter3D(),
                                transfer_fractions.TransferFractions(), shot_trends.ShotTrends()]


@pytest.mark.parametrize("script", WIRED, ids=lambda script: type(script).__name__)
def test_every_wired_plot_leaves_out_the_masked_events(script: DatasetAnalysis) -> None:
    view, inside = spotted_view()
    assert inside > 4 * 150 * 0.9
    values: dict[str, Any] = {}
    if isinstance(script, transfer_fractions.TransferFractions):
        values = {"orders_mode": "manual"}
    if isinstance(script, shot_trends.ShotTrends):
        values = {"keep_percent": 100.0}  # its box then holds every event, masked or not
    plain = run(script, view, values)
    masked = run(script, view, {**values, **MASK})
    assert total_of(plain.data) - total_of(masked.data) == inside
    if not isinstance(script, shot_trends.ShotTrends):  # it counts what it masked only when nothing is left
        assert getattr(masked.data, "masked") == inside and getattr(plain.data, "masked") == 0
    names = {spec.name for spec in script.parameters("Plot")}
    assert {"mask_mode", "mask_preset", "mask_circles"} <= names
    assert "mask: 1 cut circle" in script.describe_run("Plot", masked.parameters, view)[1]
    assert plain.reuse_key() != masked.reuse_key()
    assert masked.reuse_key()["parameters"]["mask_circles"] == MASK["mask_circles"]


@pytest.mark.parametrize("script", WIRED, ids=lambda script: type(script).__name__)
def test_a_plot_with_every_event_masked_says_so(qtbot: QtBot, script: DatasetAnalysis) -> None:
    view, _ = spotted_view(1)
    values = {"mask_mode": CUSTOM, "mask_circles": "0, 0, 1000, cut"}
    if isinstance(script, (transfer_fractions.TransferFractions, shot_times.ShotTimesPlot)):
        # Their own: no shot has enough counts in the XY box; a shot without events is drawn at 0.
        return
    widget = script.render(run(script, view, values))
    qtbot.addWidget(widget)
    assert widget.objectName() == "plot_empty" and "masked out (Mask settings)" in getattr(widget, "text")()


def test_the_newest_shot_is_masked_too() -> None:
    view, _ = spotted_view()
    lit = {**MASK, "highlight_newest": True, "keep_percent": 100.0}
    histograms = run(basic_plots.TxyHistograms(), view, lit).data
    newest = view.shots[4]
    expected = int(np.count_nonzero(np.hypot(newest[:, 1] - SPOT[0] * MM, newest[:, 2] - SPOT[1] * MM) >= 2 * MM))
    assert int(histograms.newest[0].sum()) == expected
    scatter = run(scatter_3d.Scatter3D(), view, lit).data
    assert len(scatter.newest) == expected


# Drawing

def test_density_xy_draws_the_masks_circles_dashed(qtbot: QtBot) -> None:
    view, _ = spotted_view()
    script = DensityImages()
    result = run(script, view, {"mask_mode": PRESET, "mask_preset": EARLIER})
    widget = script.render(result)
    qtbot.addWidget(widget)
    assert isinstance(widget, DensityPlot) and len(widget.circle_items) == 14
    # The circles (out to ±45 mm) don't widen the view: it stays the image's.
    widget.plot.vb.autoRange(padding=0)
    (x_low, x_high), _ = widget.plot.vb.viewRange()
    image = widget.image.mapRectToParent(widget.image.boundingRect())
    assert math.isclose(x_low, image.left(), abs_tol=0.01) and math.isclose(x_high, image.right(), abs_tol=0.01)
    pens = [item.pen() for item in widget.circle_items]
    assert all(pen.style() == Qt.PenStyle.DashLine for pen in pens)
    assert pens[0].color().getRgb()[:3] == density_images.KEEP_COLOUR
    assert pens[1].color().getRgb()[:3] == density_images.CUT_COLOUR
    keep = widget.circle_items[0].rect()
    assert math.isclose(keep.width(), 76.0) and math.isclose(keep.center().x(), 0.0, abs_tol=1e-12)
    # A rerun without a mask clears them; XT never draws them.
    assert script.update(widget, run(script, view)) and widget.circle_items == []
    xt = script.render(run(script, view, {"mask_mode": PRESET, "projection": "XT"}))
    qtbot.addWidget(xt)
    assert isinstance(xt, DensityPlot) and xt.circle_items == []


def test_the_density_title_counts_masked_events() -> None:
    view, inside = spotted_view()
    data = run(DensityImages(), view, MASK).data
    assert f"{inside:,} masked out" in density_images.image_title(data)[0]


# The parameter tree

def test_text_parameters_in_the_tree(qtbot: QtBot) -> None:
    spec = masks.MASK_CIRCLES
    assert spec.coerce(12) == "12" and spec.tree_item()["type"] == "text"
    assert spec.text("1, 2, 3\n4, 5, 6, keep") == "Circles (mm) 1, 2, 3; 4, 5, 6, keep"
    assert ParameterSpec("t", "T", "text", "").text("") == "T (empty)"
    specs = DensityImages().parameters(PLOT)
    root = build_tree(specs)
    parameter_of(root, masks.MASK_MODE).setValue(CUSTOM)
    parameter_of(root, spec).setValue("1, 2, 3")
    values = tree_values(root, specs)
    assert values["mask_mode"] == CUSTOM and values["mask_circles"] == "1, 2, 3"
    assert parameter_of(root, spec).opts["visible"] and not parameter_of(root, masks.MASK_PRESET).opts["visible"]


def test_typed_circles_count_only_when_the_edit_ends(qtbot: QtBot) -> None:
    specs = DensityImages().parameters(PLOT)
    root = build_tree(specs)
    tree = settings_widget(root, specs)
    qtbot.addWidget(tree)
    parameter = parameter_of(root, masks.MASK_CIRCLES)
    parameter.setValue("1, 2, 3")
    edits = tree.findChildren(CommitTextEdit)
    assert len(edits) == 1
    edit = edits[0]
    assert edit.toPlainText() == "1, 2, 3"
    edit.setPlainText("1, 2")  # half typed: a Live rerun still reads the last committed text
    assert parameter.value() == "1, 2, 3"
    edit.setPlainText("1, 2, 4")
    edit.commit()
    assert parameter.value() == "1, 2, 4"
    edit.setPlainText("7, 8, 9")
    qtbot.keyClick(edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)  # type: ignore[no-untyped-call]
    assert parameter.value() == "7, 8, 9" and edit.toPlainText() == "7, 8, 9"


# The hot-spot finder (D15 placeholder)

SPOTS = ((10.0, 10.0), (-15.0, 5.0), (5.0, -20.0))  # mm


def flat_field(seed: int = 11, shots: int = 4, per_shot: int = 50_000, spots: tuple[tuple[float, float], ...] = SPOTS,
               spot_events: int = 500) -> DatasetView:
    """A smooth (flat) background over ±30 mm with bright, compact spots planted at ``spots``."""
    rng = np.random.default_rng(seed)
    arrays = {}
    for shot in range(1, shots + 1):
        parts = [rng.uniform(-0.03, 0.03, (per_shot, 2))]
        parts += [rng.normal((x * MM, y * MM), 0.3 * MM, (spot_events, 2)) for x, y in spots]
        positions = np.concatenate(parts)
        arrays[shot] = np.column_stack([rng.uniform(1.0, 2.0, len(positions)), positions])
    return view_of(arrays)


def test_the_finder_recovers_planted_spots_on_a_smooth_background() -> None:
    result = run(DensityImages(), flat_field(), action=FIND)
    data = result.data
    assert isinstance(data, HotSpots) and data.search is not None
    found = data.search.spots
    assert len(found) == 3
    for x, y in SPOTS:
        near = [spot for spot in found if math.hypot(spot.circle.x - x * MM, spot.circle.y - y * MM) < 0.3 * MM]
        assert len(near) == 1 and 0.3 * MM < near[0].circle.r < 2.5 * MM and not near[0].circle.keep
    assert data.density.found == data.search.circles and data.density.projection == "XY"
    # Offered as mask text that reads back as the same circles, in the record too.
    assert masks.parse_circles(data.text()) == tuple(
        Circle(round(c.x / MM, 3) * MM, round(c.y / MM, 3) * MM, round(c.r / MM, 3) * MM) for c in data.search.circles)
    assert result.found["brief"] == "3 hot spots found"
    assert any(line.startswith("As mask circles") for line in result.found["record_lines"])


@pytest.mark.parametrize("per_shot", [50_000, 500])
def test_the_finder_ignores_noise(per_shot: int) -> None:
    # A dense flat field (~14 events per bin) and a sparse one (most bins empty): Poisson noise only.
    data = run(DensityImages(), flat_field(per_shot=per_shot, spots=()), action=FIND).data
    assert data.search is not None and data.search.spots == () and data.search.flagged == 0
    assert density_images.spots_title(data)[1].startswith("No hot spots")


def disc(rng: np.random.Generator, n: int, radius: float = 0.04) -> np.ndarray:
    r = radius * np.sqrt(rng.uniform(0, 1, n))
    a = rng.uniform(0, 2 * np.pi, n)
    return np.column_stack([r * np.cos(a), r * np.sin(a)])


def detector_view(seed: int, gain: bool = False, cloud: int = 0, spots: tuple[tuple[float, float], ...] = (),
                  shots: int = 40) -> DatasetView:
    """A round detector (r 40 mm): ``gain``, uneven (the centre 2.5 × the edge, and a bright rim);
    ``cloud`` events per shot of an atom cloud (σ 3 mm); a few events per shot on each spot."""
    rng = np.random.default_rng(seed)
    arrays = {}
    for shot in range(1, shots + 1):
        dark = disc(rng, 2000 if gain else 400)
        if gain:
            r = np.hypot(dark[:, 0], dark[:, 1])
            dark = dark[rng.uniform(0, 1, len(dark)) < 0.4 + 0.6 * np.exp(-(r / 0.015) ** 2)]
            angle = rng.uniform(0, 2 * np.pi, 60)
            rim = rng.normal(0.0395, 0.0004, 60)
            dark = np.concatenate([dark, np.column_stack([rim * np.cos(angle), rim * np.sin(angle)])])
        parts = [dark, rng.normal((0.0005, -0.001), 0.003, (cloud, 2))]
        parts += [rng.normal((x * MM, y * MM), 0.4 * MM, (rng.poisson(8), 2)) for x, y in spots]
        positions = np.concatenate(parts)
        arrays[shot] = np.column_stack([rng.uniform(0.38, 0.46, len(positions)), positions])
    return view_of(arrays)


DETECTOR_SPOTS = ((25.14, 25.87), (16.0, -30.35), (-10.0, 5.0))  # mm: two at the edge, one inside


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_the_finder_offers_nothing_on_uneven_gain_or_a_clouds_wings(seed: int) -> None:
    for view in (detector_view(seed, gain=True), detector_view(seed, cloud=3000)):
        search = run(DensityImages(), view, action=FIND).data.search
        assert isinstance(search, hotspots.HotSpotSearch)
        assert search.spots == (), hotspots.search_lines(search)


def test_the_finder_still_finds_spots_on_a_cloud_and_the_edge() -> None:
    for view in (detector_view(5, cloud=3000, spots=DETECTOR_SPOTS), detector_view(6, spots=DETECTOR_SPOTS),
                 detector_view(7, gain=True, spots=DETECTOR_SPOTS)):
        search = run(DensityImages(), view, action=FIND).data.search
        assert isinstance(search, hotspots.HotSpotSearch)
        assert len(search.spots) == 3, hotspots.search_lines(search)
        for x, y in DETECTOR_SPOTS:
            assert any(math.hypot(spot.circle.x - x * MM, spot.circle.y - y * MM) < 0.5 * MM < spot.circle.r
                       for spot in search.spots)


def test_the_finders_rule() -> None:
    """A local background, a Poisson tail under α / bins tested, spots grown over touching
    unlikely bins, and the minimum for one-bin spots."""
    rng = np.random.default_rng(9)
    width = 1e-3
    image = rng.poisson(20.0, (40, 40)).astype(float)
    image[:, 20:] = rng.poisson(60.0, (40, 20))  # a step in gain: not a spot
    image[10, 10] += 80.0  # one bin, 80 over 20: very unlikely
    image[30, 30] += 60.0
    image[30, 31] += 60.0  # two touching bins
    image[5, 35] += 30  # one bin, 30 over 60: within the noise
    centres = (np.arange(40) + 0.5) * width
    grid_x, grid_y = np.meshgrid(centres, centres, indexing="ij")
    reps = image.astype(int).ravel()
    x = np.asarray(grid_x, dtype=np.float64)
    y = np.asarray(grid_y, dtype=np.float64)
    search = hotspots.find_hot_spots(np.repeat(x.ravel(), reps), np.repeat(y.ravel(), reps), (0.0, 0.04),
                                     (0.0, 0.04), width, scale=2e-3)
    # The filled area: all but the corners, where the smoothed occupancy falls under half.
    assert 1550 < search.tested <= 1600 and math.isclose(search.p_limit, 0.01 / search.tested)
    assert sorted(spot.bins for spot in search.spots) == [1, 2]
    assert {(round(spot.circle.x / width - 0.5), round(spot.circle.y / width - 0.5)) for spot in search.spots
            if spot.bins == 1} == {(10, 10)}
    two = next(spot for spot in search.spots if spot.bins == 2)
    # Between the two bins' centres, nearer the one with more excess.
    assert math.isclose(two.circle.x, 30.5e-3, abs_tol=1e-9) and 30.5e-3 < two.circle.y < 31.5e-3
    assert two.circle.r >= 0.5e-3 + math.hypot(width, width) / 2 - 1e-9
    # A higher minimum leaves the one-bin spot out (counted), not the two-bin one.
    strict = hotspots.find_hot_spots(np.repeat(x.ravel(), reps), np.repeat(y.ravel(), reps), (0.0, 0.04),
                                     (0.0, 0.04), width, scale=2e-3, min_excess=1000)
    assert [spot.bins for spot in strict.spots] == [2] and strict.dropped == 1
    assert "1 one-bin spot under the minimum excess left out" in hotspots.search_lines(strict)[0]
    assert "2 bins," in hotspots.search_lines(strict)[1] and "1 bins" not in " ".join(hotspots.search_lines(search))
    empty = hotspots.find_hot_spots(np.empty(0), np.empty(0), (0.0, 0.01), (0.0, 0.01), 0.001)
    assert empty.spots == () and empty.tested == 0


def test_the_finders_notes_are_plain_not_warnings() -> None:
    view = view_of({1: np.array([[0.4, 0.0, 0.0], [0.4, 2.0, 2.0]])})  # 2 m apart: bins widened
    data = run(DensityImages(), view, action=FIND).data
    assert data.search is not None and data.search.notes and not data.density.warnings
    second = density_images.spots_title(data)[1]
    assert "bins widened" in second and "⚠" not in second


def test_the_finder_never_applies_its_circles(qtbot: QtBot) -> None:
    script = DensityImages()
    view = flat_field()
    result = run(script, view, action=FIND)
    assert script.detected_parameters(FIND, result) == {}
    assert result.parameters["mask_mode"] == NONE
    assert not run(script, view).data.masked  # the next image is not masked
    widget = script.render(result)
    qtbot.addWidget(widget)
    assert isinstance(widget, HotSpotsPlot) and widget.copy_button.isEnabled()
    found = [item for item in widget.circle_items
             if item.pen().color().name() == density_images.FOUND_COLOUR.lower()]
    assert len(found) == 3 and len(widget.circle_items) == 3
    clipboard = QApplication.clipboard()
    assert clipboard is not None
    clipboard.clear()
    widget.copy_button.click()
    assert clipboard.text() == result.data.text() and len(parse_circles(clipboard.text())) == 3
    # Pasted into a plot's custom Mask, they cut the spots.
    masked = run(script, view, {"mask_mode": CUSTOM, "mask_circles": clipboard.text()}).data
    assert masked.masked > 0.9 * 4 * 3 * 500
    assert script.update(widget, run(script, flat_field(seed=12), action=FIND))
