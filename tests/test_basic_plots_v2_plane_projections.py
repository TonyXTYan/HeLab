"""Basic plots v2's Plane projections: velocities in 3D with up to four planes at any angle, and each plane's
histogram of the events flattened onto it (``helab.analysis.planes``); XY, XT and YT are the presets."""
from __future__ import annotations

import dataclasses
import math
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest
from pytestqt.qtbot import QtBot

from helab.analysis.backends import MATPLOTLIB, PLOTLY, MatplotlibPane
from helab.analysis.dataset_view import DatasetView, build_view
from helab.analysis.panes import PlotlyPane
from helab.analysis.parameters import effective
from helab.analysis.physics import DEFAULTS
from helab.analysis.planes import CUSTOM, XT, XY, YT, Plane, as_xyz, plane_image, project
from helab.analysis.result_codec import decode, encode
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.velocity import arrival_time
from helab.scripts import standard_v2
from helab.scripts.standard_v2 import plane_projections
from helab.scripts.standard_v2.plane_projections import PlaneProjections, Projections, planes_of
from helab.utils.folder_cache import Dataset

Array = npt.NDArray[np.float64]
SCRIPT = PlaneProjections()
RELEASE = 20.0312  # s, DLD time
ORIGIN = (3e-3, -2e-3)  # m
SAVED = {"arrival_time": RELEASE + DEFAULTS.fall_time, "trap_x": ORIGIN[0], "trap_y": ORIGIN[1]}


def txy_of(velocities: Array) -> Array:
    """TXY events of atoms released at ``RELEASE`` from above ``ORIGIN`` with ``velocities`` (v_z, v_x, v_y)."""
    t = arrival_time(velocities[:, 0], RELEASE, DEFAULTS)
    tau = t - RELEASE
    return np.column_stack([t, ORIGIN[0] + velocities[:, 1] * tau, ORIGIN[1] + velocities[:, 2] * tau])


def view_of(velocities: Array, shots: int = 2) -> DatasetView:
    data = {}
    for shot, part in enumerate(np.array_split(velocities, shots), start=1):
        events = txy_of(part)
        data[shot] = events[np.argsort(events[:, 0])]
    prints = [[shot, 100 + shot, 1_700_000_000_000_000_000 + shot] for shot in data]
    return build_view(Dataset("/data/root/run_planes", "sig-planes", data, {"fingerprint": prints}, 0))


def run(view: DatasetView, values: dict[str, Any] | None = None, ram_budget: int = 0) -> AnalysisResult:
    params = effective(SCRIPT.parameters("Plot"), {"keep_percent": 100.0, **(values or {})})
    layers: dict[str, dict[str, float]] = {"lab": {}, "folder": dict(SAVED)}
    context = AnalysisContext("p1", "Plot", view, params, SCRIPT.get_metadata().identity(), constants=layers,
                              resolved_constants=SCRIPT.run_constants("Plot", params, layers),
                              constant_keys=SCRIPT.constant_keys("Plot"), ram_budget=ram_budget)
    return AnalysisResult.of(context, "completed", SCRIPT.compute("Plot", context))


def shell(rng: np.random.Generator, count: int, radius: float) -> Array:
    """Velocities (v_z, v_x, v_y) on a thin sphere of ``radius`` m/s about 0: a halo."""
    direction = rng.normal(size=(count, 3))
    direction /= np.linalg.norm(direction, axis=1, keepdims=True)
    return direction * rng.normal(radius, radius * 0.01, (count, 1))


# helab.analysis.planes


@pytest.mark.parametrize("preset", [XY, XT, YT])
def test_a_custom_plane_at_a_preset_s_angles_is_that_preset(preset: str) -> None:
    angles = {XY: (0.0, 0.0), XT: (0.0, 90.0), YT: (90.0, 90.0)}[preset]
    exact = Plane("a", preset).axes()
    custom = Plane("b", CUSTOM, *angles).axes()
    for left, right in zip(exact, custom):
        np.testing.assert_allclose(left, right, atol=1e-15)
    u, v, n = exact
    np.testing.assert_array_equal(np.cross(u, v), n)  # Right-handed, the normal u × v.


@pytest.mark.parametrize("angles", [(30.0, 45.0, 0.0), (-120.0, 10.0, 25.0), (75.0, 170.0, -60.0)])
def test_every_basis_is_orthonormal_and_unspun_planes_climb(angles: tuple[float, float, float]) -> None:
    u, v, n = Plane("p", CUSTOM, *angles).axes()
    basis = np.array([u, v, n])
    np.testing.assert_allclose(basis @ basis.T, np.eye(3), atol=1e-12)
    np.testing.assert_allclose(np.cross(u, v), n, atol=1e-12)
    up = Plane("p", CUSTOM, angles[0], angles[1]).axes()[1]
    assert up[2] >= -1e-12 and abs(up[2]) == pytest.approx(abs(math.sin(math.radians(angles[1]))))


def test_the_presets_flatten_as_the_xy_xt_and_yt_histograms_sum_their_third_axis() -> None:
    rng = np.random.default_rng(1)
    xyz = rng.normal(size=(500, 3))
    for preset, (across, up) in {XY: (0, 1), XT: (0, 2), YT: (1, 2)}.items():
        h, w, kept = project(xyz, Plane("p", preset))
        assert kept == len(xyz)
        np.testing.assert_array_equal(h, xyz[:, across])
        np.testing.assert_array_equal(w, xyz[:, up])
    as_velocity = xyz[:, [2, 0, 1]]  # (v_z, v_x, v_y), as ``velocity`` gives them
    np.testing.assert_array_equal(as_xyz(as_velocity), xyz)


def test_a_thickness_keeps_a_slice_and_a_centre_moves_the_plane() -> None:
    xyz = np.array([[0.0, 0.0, z] for z in (-0.3, -0.1, 0.0, 0.1, 0.25, 0.6)])
    assert project(xyz, Plane("p", XY, thickness=0.4))[2] == 3  # |v_z| ≤ 0.2: −0.1, 0 and 0.1
    h, w, kept = project(xyz, Plane("p", XY, centre=(0.1, -0.2, 0.5), thickness=0.4))
    assert kept == 1  # Only v_z 0.6 is within 0.2 of 0.5.
    np.testing.assert_allclose(h, -0.1)
    np.testing.assert_allclose(w, 0.2)


def test_a_tilted_plane_images_a_tilted_ring_as_a_circle() -> None:
    """A ring in a plane tilted 30° about v_y's direction is a circle on that plane and nearly a line edge-on."""
    rng = np.random.default_rng(4)
    plane = Plane("p", CUSTOM, 90.0, 30.0)
    u, v, n = plane.axes()
    phase = rng.uniform(0, 2 * np.pi, 4_000)
    ring = 0.05 * (np.cos(phase)[:, None] * u + np.sin(phase)[:, None] * v)
    h, w, _ = project(ring, plane)
    np.testing.assert_allclose(np.hypot(h, w), 0.05, rtol=1e-12)
    image = plane_image(ring, plane, keep=1.0, half_width=0.06, bins=60)
    assert image.inside == len(ring) and image.counts.shape == (60, 60)
    np.testing.assert_allclose(image.corners()[0], -0.06 * u - 0.06 * v)
    edge_on = project(ring, Plane("q", CUSTOM, 90.0, 30.0 + 90.0))
    assert np.ptp(edge_on[1]) < 1e-12  # Seen edge-on, the ring has no height.


# The plot


def test_registered_with_velocity_constants() -> None:
    assert plane_projections in standard_v2.MODULES
    metadata = SCRIPT.get_metadata()
    assert (metadata.name, metadata.analysis_id, metadata.version) == (
        "Plane projections", "helab.v2.plane_projections", "1")
    assert "release_time" in SCRIPT.constant_keys("Plot") and SCRIPT.live_policy("Plot").min_delay == 5.0
    defaults = effective(SCRIPT.parameters("Plot"), {})
    assert [plane.preset for plane in planes_of(defaults)] == [XY, XT, YT]  # The fourth (custom) is off.
    assert SCRIPT.parameter_warnings("Plot", {**defaults, **{f"plane{i}_on": False for i in range(1, 5)}}) == [
        "No plane is on: turn one on under Planes"]


def test_a_halo_slice_through_its_centre_is_a_ring_of_its_radius() -> None:
    rng = np.random.default_rng(7)
    radius = 0.06
    result = run(view_of(shell(rng, 20_000, radius)), {
        "plane4_on": True, "plane4_across": 30.0, "plane4_tilt": 50.0, "plane4_thickness": 0.01,
        "panel_half_width": 0.08, "panel_bins": 80})
    data: Projections = result.data
    assert data.valid == data.events == 20_000 and len(data.images) == 4 and not data.failure
    assert "folder" in data.release and "origin (3, -2) mm" in data.release.replace("−", "-")
    slice_ = data.images[3]
    assert slice_.plane.preset == CUSTOM and slice_.kept < data.valid / 5
    # Every event of a thin slice through the centre of a shell lies near the shell's radius on the plane.
    h, w = np.meshgrid((slice_.h_edges[:-1] + slice_.h_edges[1:]) / 2, (slice_.v_edges[:-1] + slice_.v_edges[1:]) / 2,
                       indexing="ij")
    weighted = float(np.average(np.hypot(h, w), weights=slice_.counts))
    assert weighted == pytest.approx(radius, rel=0.03)
    # The flattened (whole) XY is a filled disc: its events reach the centre.
    whole = data.images[0]
    centre = whole.counts[35:45, 35:45].sum()
    assert whole.kept == data.valid and centre > 0


def test_empty_cases_say_why() -> None:
    nothing = run(view_of(np.empty((0, 3)), shots=1), {})
    assert plane_projections.nothing_text(nothing.data).startswith("No events")
    off = run(view_of(shell(np.random.default_rng(0), 100, 0.05)), {f"plane{i}_on": False for i in range(1, 5)})
    assert plane_projections.nothing_text(off.data) == "No plane is on: turn one on under Planes"


def test_results_survive_the_codec() -> None:
    result = run(view_of(shell(np.random.default_rng(2), 2_000, 0.05)), {"panel_bins": 20})
    tree, arrays = encode(result.data, SCRIPT.cache_types("Plot"))
    back = decode(tree, arrays, SCRIPT.cache_types("Plot"))
    assert isinstance(back, Projections) and back.release == result.data.release
    np.testing.assert_array_equal(back.images[1].counts, result.data.images[1].counts)
    assert back.images[2].plane == result.data.images[2].plane


@pytest.mark.parametrize("backend", [PLOTLY, MATPLOTLIB])
def test_drawn_and_updated_in_place(qtbot: QtBot, backend: str) -> None:
    view = view_of(shell(np.random.default_rng(3), 3_000, 0.05))
    result = run(view, {"plane4_on": True, "velocity_unit": "m/s"})
    widget = SCRIPT.draw(result, backend)
    qtbot.addWidget(widget)
    assert isinstance(widget, PlotlyPane if backend == PLOTLY else MatplotlibPane)
    assert SCRIPT.update(widget, run(view, {"plane4_on": True, "plane4_spin": 20.0}))
    figure = plane_projections.projections_plotly(result)
    traces: Any = figure.data
    assert [trace.type for trace in traces].count("heatmap") == 4
    layout: Any = figure.layout
    assert layout.scene.aspectmode == "data" and layout.xaxis.title.text == "v_x (m/s)"


# Memory and drawing at many bins (review R4, 2026-11-17)


def estimate(values: dict[str, Any]) -> int:
    return SCRIPT.estimated_bytes("Plot", effective(SCRIPT.parameters("Plot"), values))


def heatmap(result: AnalysisResult) -> Any:
    """The first plane's histogram as Plotly is given it."""
    figure: Any = plane_projections.projections_plotly(result)
    return next(trace for trace in figure.data if trace.type == "heatmap")


def test_the_estimate_counts_every_plane_on_and_its_bins() -> None:
    """Up to four planes of 10,000 × 10,000 int64 counts: 3.2 GB held before anything is drawn. The estimate is
    what the settings page's memory warning (Undo, Cancel) reads; it was 0."""
    bins, drawn = 10_000 * 10_000, 1_000 * 1_000
    four = {"panel_bins": 10_000, "plane4_on": True}
    # held: counts (8 B a bin) and the drawn image (4 B a cell); for a moment NumPy's float64 histogram of one plane
    assert estimate(four) == 8 * 4 * bins + 4 * 4 * drawn + 8 * bins
    assert estimate(four) > 3_200_000_000
    assert estimate({"panel_bins": 10_000}) == 8 * 3 * bins + 4 * 3 * drawn + 8 * bins  # three on by default
    assert estimate({"panel_bins": 10_000, "plane2_on": False, "plane3_on": False}) == 8 * bins + 4 * drawn + 8 * bins
    assert estimate({f"plane{index}_on": False for index in range(1, 5)}) == 0
    # automatic bins: counted at their most (1,000 a side), drawn as they are; drawing three planes is the moment
    assert estimate({}) == 8 * 3 * drawn + 32 * 3 * drawn
    sizes = [estimate({"panel_bins": bins_}) for bins_ in (500, 1_000, 2_000, 5_000, 10_000)]
    assert sizes == sorted(sizes) and len(set(sizes)) == 5
    assert plane_projections.planes_bytes([]) == 0
    assert plane_projections.planes_bytes([(1_200, 1_200)]) == 8 * 1_440_000 + 4 * 360_000 + 32 * 360_000


def test_a_run_over_half_the_ram_budget_says_so() -> None:
    view = view_of(shell(np.random.default_rng(5), 4_000, 0.05))
    values = {"panel_bins": 1_200}
    wanted = plane_projections.planes_bytes([(1_200, 1_200)] * 3)
    assert wanted == estimate(values)  # (Set bins: the settings page's estimate is the run's.)
    over = run(view, values, ram_budget=2 * wanted)  # at half of it
    warned = [text for text in over.data.warnings if text.startswith("Estimated memory")]
    assert len(warned) == 1 and "50 % of the RAM budget" in warned[0]
    assert SCRIPT.describe_result("Plot", over) == f"⚠ {warned[0]}"
    assert warned[0] in " ".join(plane_projections.heading(over, over.data))
    for budget in (2 * wanted + 2, 0):  # under half of it, or unknown
        under = run(view, values, ram_budget=budget)
        assert not any(text.startswith("Estimated memory") for text in under.data.warnings)
        assert SCRIPT.describe_result("Plot", under) == ""


@pytest.mark.parametrize("bins, cells", [(2_500, 834), (1_001, 501), (1_000, 1_000), (300, 300)])
def test_many_bins_are_counted_whole_and_drawn_with_at_most_a_thousand_cells_a_side(bins: int, cells: int) -> None:
    """The counts keep every bin (the analysis, a saved result); what Plotly is sent and Matplotlib draws is made on
    the worker, bounded, each cell the mean of the bins it covers and in their place."""
    view = view_of(shell(np.random.default_rng(6), 6_000, 0.05))
    result = run(view, {"panel_bins": bins, "plane2_on": False, "plane3_on": False, "velocity_unit": "m/s"})
    data = result.data
    image = data.images[0]
    assert image.counts.shape == (bins, bins) and image.counts.dtype == np.int64 and image.inside > 0
    display = data.displays[0]
    reduced = cells < bins
    assert len(data.displays) == 1 and (display is not None) is reduced
    trace = heatmap(result)
    z, x = np.asarray(trace.z), np.asarray(trace.x)
    assert z.shape == (cells, cells) and z.size <= 1_000 * 1_000 and len(x) == cells
    assert np.allclose(np.diff(x), (image.h_edges[-1] - image.h_edges[0]) / cells)  # equal cells over the range
    assert x[0] - np.diff(x)[0] / 2 == pytest.approx(image.h_edges[0])
    assert x[-1] + np.diff(x)[0] / 2 == pytest.approx(image.h_edges[-1])
    title = plane_projections.plane_title(image, data)
    assert (f"{bins:,} × {bins:,} bins drawn at {cells:,} × {cells:,}" in title) is reduced
    axes = plane_projections.projections_matplotlib(result).axes[1]
    if reduced:
        assert display is not None
        assert float(display.image.astype(np.float64).sum()) * (bins / cells) ** 2 == pytest.approx(image.inside, rel=1e-4)
        assert "the mean of" in trace.hovertemplate and trace.zmax == pytest.approx(float(display.image.max()))
        raster = axes.images[0]
        assert raster.get_array().shape == (cells, cells) and not axes.collections
        assert raster.get_extent() == pytest.approx([image.h_edges[0], image.h_edges[-1], image.v_edges[0],
                                                     image.v_edges[-1]])
    else:
        assert np.array_equal(z, image.counts.T) and trace.zmax == max(image.peak, 1)
        assert not axes.images and len(axes.collections) == 1  # (pcolormesh, a quad a bin, as before.)


def test_a_drawn_image_survives_the_codec_and_an_older_result_is_reduced_when_drawn() -> None:
    result = run(view_of(shell(np.random.default_rng(7), 3_000, 0.05)),
                 {"panel_bins": 1_200, "plane2_on": False, "plane3_on": False})
    tree, arrays = encode(result.data, SCRIPT.cache_types("Plot"))
    back = decode(tree, arrays, SCRIPT.cache_types("Plot"))
    assert isinstance(back, Projections) and back.displays[0] is not None and result.data.displays[0] is not None
    np.testing.assert_array_equal(back.displays[0].image, result.data.displays[0].image)
    assert back.displays[0].factors == (2.0, 2.0)
    older = dataclasses.replace(result.data, displays=())  # as saved before the drawn images were kept
    drawn = older.drawn(0)
    assert drawn is not None and drawn.image.shape == (600, 600)
    np.testing.assert_array_equal(drawn.image, result.data.displays[0].image)
    trace = heatmap(dataclasses.replace(result, data=older))
    assert np.asarray(trace.z).shape == (600, 600)
