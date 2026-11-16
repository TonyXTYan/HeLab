"""Plane projections (Basic plots v2): the chosen shots' events as velocities at release, drawn in 3D with up to
four planes in it, and beside it each plane's histogram of the events flattened onto it (``helab.analysis.planes``).

Velocities, not T, X and Y, so that a plane may lean at any angle: T (s) and X, Y (m) share no unit, the velocities
(v_z up, v_x, v_y, in m/s) do (Tony, 2026-11-10). They follow the Velocity distributions plot's rule
(``release.run_velocity_source``): t_r and the trap's XY origin from the folder or lab (the Release time plot's Use
for this folder…) or this plot's Constants, else detected from the chosen events. Each plane is a preset, XY
(v_x across, v_y up), XT (v_x, v_z) or YT (v_y, v_z), the XY, XT and YT histograms' planes in velocity, or custom:
any orientation, set by three angles (across-axis direction α, tilt θ, in-plane rotation ψ; Tony allowed rotating
XY for this plot, 2026-11-10). Each has a centre and a thickness, 0 keeping every event (the normal axis summed).

Drawn with Plotly by default (the 3D view turns, and keeps its camera as Live adds shots) or Matplotlib (for a PC
whose Qt can't draw web pages); updated in place. Every axis is a velocity in the chosen unit at equal scales."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, Sequence

import numpy as np
import numpy.typing as npt
import plotly.graph_objs as go
from PyQt6.QtWidgets import QWidget

from helab.analysis.backends import MATPLOTLIB, PLOTLY, MatplotlibPane, mpl_colour, mpl_figure
from helab.analysis.budget_core import ESTIMATE_PREFIX, estimate_over, estimate_text
from helab.analysis.dataset_view import DatasetView
from helab.analysis.display_units import LENGTH_SCALE, WIDTH_DIGITS, number_text, time_text
from helab.analysis.empty import empty_pane, empty_text
from helab.analysis.follow import LivePolicy
from helab.analysis.histogram2d import (DISPLAY_BYTES_PER_CELL, MAX_AUTO_BINS, MOMENT_BYTES_PER_BIN, PLOTLY_SIDE,
                                        display_shape, scale_text)
from helab.analysis.panes import PlotlyPane
from helab.analysis.parameters import ParameterSpec
from helab.analysis.planes import CUSTOM, XT, XY, YT, Plane, PlaneImage, as_xyz, plane_image
from helab.analysis.release import ReleaseTime, RunVelocitySource, detect_release_time, run_velocity_source
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.selection import (SHOT_SPECS, keep_fraction, manual, manual_box, range_brief, range_specs,
                                      range_warnings, select_shots, selection_text, shots_brief, shots_text)
from helab.analysis.stats import DISPLAY_CAP, crop_box, display_sample
from helab.analysis.velocity import valid_velocities
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.dld.velocity_distributions import (ASSUMED_NOTE, CONSTANT_KEYS, CONSTANTS, DETECTED_NOTE, MM_S,
                                                      SEARCH_MAX, SEARCH_MIN, UNIT, layer_text, search_range,
                                                      unit_factor)
from helab.analysis.constant_layers import resolve_for_run
from helab.scripts.standard.basic_plots import matplotlib_update, plotly_update
from helab.scripts.standard_v2 import group
from helab.scripts.standard_v2.histograms_2d import (DECADES, GAMMA, SCALE, Colours, Display, cell_bins, display_of,
                                                    matplotlib_norm, plotly_scale)

Array = npt.NDArray[np.float64]

RANGE = range_specs(
    "The events converted to velocities are those inside a box over T, X and Y holding at least this share of them "
    "(as the Velocity distributions plot finds it). Set T by hand to pick one cloud or Bragg order. 100 % converts "
    "every event.", fixed=True)

# The planes: four slots, each a preset or custom, with a centre and a thickness.
SLOTS = 4
PRESETS = (XY, XT, YT, CUSTOM)
PRESET_TITLES = {XY: "XY: v_x across, v_y up", XT: "XT: v_x across, v_z up", YT: "YT: v_y across, v_z up"}
DEFAULT_PRESETS = (XY, XT, YT, CUSTOM)
COLOURS = ((31, 119, 180), (255, 127, 14), (44, 160, 44), (214, 39, 40))  # each plane's, in 3D and its title
POINT_COLOUR = (90, 90, 90)


def _on(name: str) -> Any:
    return lambda values: bool(values.get(name))


@dataclass(frozen=True)
class Slot:
    """One plane slot's parameters."""
    index: int
    on: ParameterSpec
    preset: ParameterSpec
    across: ParameterSpec
    tilt: ParameterSpec
    spin: ParameterSpec
    centre: tuple[ParameterSpec, ParameterSpec, ParameterSpec]
    thickness: ParameterSpec

    def specs(self) -> tuple[ParameterSpec, ...]:
        return (self.on, self.preset, self.across, self.tilt, self.spin, *self.centre, self.thickness)

    def plane(self, values: Mapping[str, Any]) -> Plane:
        preset = str(values.get(self.preset.name, self.preset.default))
        return Plane(f"Plane {self.index}", preset if preset in PRESETS else XY,
                     float(values.get(self.across.name, 0.0)), float(values.get(self.tilt.name, 0.0)),
                     float(values.get(self.spin.name, 0.0)),
                     (float(values.get(self.centre[0].name, 0.0)), float(values.get(self.centre[1].name, 0.0)),
                      float(values.get(self.centre[2].name, 0.0))),
                     max(0.0, float(values.get(self.thickness.name, 0.0))))


def slot(index: int) -> Slot:
    key, where = f"plane{index}", f"Planes/Plane {index}"
    on_name = f"{key}_on"
    shown = _on(on_name)
    on = ParameterSpec(on_name, "Show", "bool", index <= 3, group=where,
                       tip=f"Draw plane {index} in the 3D view and its histogram beside it.")
    preset = ParameterSpec(f"{key}_preset", "Orientation", "choice", DEFAULT_PRESETS[index - 1], choices=PRESETS,
                           group=where, shown_with=shown,
                           tip="XY: v_x across, v_y up (horizontal); XT: v_x across, v_z up; YT: v_y across, v_z up "
                               "(both vertical): the XY, XT and YT histograms' planes in velocity. Custom: set by the "
                               "angles below.")
    custom = (preset.name, CUSTOM)
    across = ParameterSpec(f"{key}_across", "Across axis direction α", "float", 45.0, (-180.0, 180.0), "°",
                           group=where, when=custom, shown_with=shown,
                           tip="The direction of the plane's across axis in the horizontal v_x–v_y plane, from +v_x "
                               "towards +v_y (0: along v_x; 90: along v_y).")
    tilt = ParameterSpec(f"{key}_tilt", "Tilt θ", "float", 45.0 if index == 4 else 0.0, (-180.0, 180.0), "°",
                         group=where, when=custom, shown_with=shown,
                         tip="How far the plane leans up from horizontal about its across axis: 0 is horizontal "
                             "(like XY), 90 vertical (like XT or YT).")
    spin = ParameterSpec(f"{key}_spin", "In-plane rotation ψ", "float", 0.0, (-180.0, 180.0), "°", group=where,
                         shown_with=shown,
                         tip="Turns the plane's two axes about its normal (anticlockwise as drawn); the histogram's "
                             "axes are then called u and v.")
    centre = tuple(ParameterSpec(f"{key}_centre_{axis}", f"Centre v_{axis}", "float", 0.0, (-100.0, 100.0), " m/s",
                                 group=where, si=True, unit_prefix="m", shown_with=shown,
                                 tip=f"The plane passes through this point; v_{axis} of it, in mm/s. The histogram's "
                                     "axes are measured from it.") for axis in ("x", "y", "z"))
    thickness = ParameterSpec(f"{key}_thickness", "Thickness (0 = all)", "float", 0.0, (0.0, 100.0), " m/s",
                              group=where, si=True, unit_prefix="m", shown_with=shown,
                              tip="Only the events within half this of the plane, along its normal, are flattened "
                                  "onto it (a slice); 0 flattens every event (the normal axis summed).")
    return Slot(index, on, preset, across, tilt, spin, (centre[0], centre[1], centre[2]), thickness)


SLOT_SPECS = tuple(slot(index) for index in range(1, SLOTS + 1))
IMAGE_GROUP = "Images"
KEEP = ParameterSpec("panel_keep", "Range: keep", "float", 99.0, (50.0, 100.0), " %", group=IMAGE_GROUP,
                     tip="Each histogram's two axes span the shortest range holding this share of the plane's events "
                         "(unless a half-width is set).")
HALF_WIDTH = ParameterSpec("panel_half_width", "Half-width (0 = auto)", "float", 0.0, (0.0, 100.0), " m/s",
                           group=IMAGE_GROUP, si=True, unit_prefix="m",
                           tip="Above 0: every histogram spans this either side of its plane's centre on both axes, "
                               "so the planes compare at one scale.")
BINS = ParameterSpec("panel_bins", "Bins per axis (0 = auto)", "int", 0, (0, 10_000), group=IMAGE_GROUP,
                     tip="Bins along each histogram axis; 0 = automatic (Freedman–Diaconis, at most 1,000). A "
                         f"histogram of more than {PLOTLY_SIDE:,} bins a side is drawn from the mean of blocks of "
                         f"bins, at most {PLOTLY_SIDE:,} a side; its counts keep every bin.")
# Memory (``estimated_bytes``). Held while the plot is open: each plane's int64 counts, and its drawn image when
# that is smaller. For a moment: NumPy's float64 histogram the counts are made from, one plane at a time; and
# what drawing takes a drawn cell, every plane in one figure (as the XY, XT, YT histograms count it).
HELD_BYTES_PER_BIN = 8
MAKING_BYTES_PER_BIN = 8


def drawn_cells(shape: tuple[int, int]) -> int:
    """The cells a histogram of ``shape`` bins is drawn with (``PLOTLY_SIDE`` a side at most)."""
    rows, columns = display_shape(shape, PLOTLY_SIDE)
    return rows * columns


def planes_bytes(shapes: Sequence[tuple[int, int]]) -> int:
    """The most memory the planes' histograms of ``shapes`` bins take at once (bytes), drawing included."""
    if not shapes:
        return 0
    bins = [rows * columns for rows, columns in shapes]
    drawn = [drawn_cells(shape) for shape in shapes]
    shown = sum(DISPLAY_BYTES_PER_CELL * cells for size, cells in zip(bins, drawn) if cells < size)
    return (HELD_BYTES_PER_BIN * sum(bins) + shown
            + max(MAKING_BYTES_PER_BIN * max(bins), MOMENT_BYTES_PER_BIN * sum(drawn)))
POINTS_GROUP = "3D view"
POINT_SIZE = ParameterSpec("point_size", "Point size", "float", 1.5, (0.5, 10.0), " px", group=POINTS_GROUP,
                           tip="Marker size in pixels.")
OPACITY = ParameterSpec("opacity", "Opacity", "float", 0.4, (0.05, 1.0), group=POINTS_GROUP,
                        tip="Marker opacity: lower shows density in dense regions.")
CAP = ParameterSpec("display_cap", "Display cap", "int", DISPLAY_CAP, (1_000, 2_000_000), group=POINTS_GROUP,
                    tip="At most this many events are drawn in 3D (a fixed random sample); the histograms count "
                        "every event.")
PLANE_OPACITY = ParameterSpec("plane_opacity", "Plane opacity", "float", 0.2, (0.0, 1.0), group=POINTS_GROUP,
                              tip="How solid the planes are drawn in 3D (their edges are always drawn).")
PARAMETERS = (*SHOT_SPECS, *RANGE, UNIT, *(spec for item in SLOT_SPECS for spec in item.specs()), KEEP, HALF_WIDTH,
              BINS, SCALE, GAMMA, DECADES, POINT_SIZE, OPACITY, CAP, PLANE_OPACITY, SEARCH_MIN, SEARCH_MAX,
              *CONSTANTS)
UI_REVISION = "helab.v2.plane_projections"


def planes_of(values: Mapping[str, Any]) -> tuple[Plane, ...]:
    """The planes turned on, in slot order."""
    return tuple(item.plane(values) for item in SLOT_SPECS if values.get(item.on.name, item.on.default))


@dataclass(frozen=True)
class Projections:
    """A run's data: the events chosen and converted, the unit, each plane's image, the 3D sample (v_x, v_y, v_z;
    m/s), where t_r and the origin came from (``release``), or why there are no velocities (``failure``)."""
    shots: tuple[int, ...]
    total_shots: int
    events: int  # of the chosen shots
    converted: int = 0  # inside the T, X, Y box
    valid: int = 0  # with a velocity
    unit: str = MM_S
    factor: float = 1e-3  # one ``unit`` in m/s
    images: tuple[PlaneImage, ...] = ()
    points: Array = field(default_factory=lambda: np.empty((0, 3)))
    release: str = ""
    failure: str = ""
    notes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    planes: int = 0  # planes turned on
    # Each image as drawn (``drawn``), made on the worker: None where every bin is drawn. (Empty in a result saved
    # before these were kept.)
    displays: tuple[Optional[Display], ...] = ()

    def drawn(self, index: int) -> Optional[Display]:
        """Plane ``index``'s image as drawn, at most ``PLOTLY_SIDE`` cells a side, or None when its bins are that
        few: 10,000 bins a side are 100 million cells, which no library draws (or sends to a web page) at once."""
        if index < len(self.displays):
            return self.displays[index]
        image = self.images[index]  # (A result from before: reduced here.)
        return display_of(image.counts, image.h_edges, image.v_edges, PLOTLY_SIDE)


def release_text(source: RunVelocitySource) -> str:
    """``t_r 20,031.2 ms (folder: saved arrival) · origin (3, −2) mm (folder)``."""
    found = source.release
    if source.detected:
        where = "detected in this run"
    else:
        where = layer_text(source.release_source) + (": saved arrival" if source.release_from == "arrival_time"
                                                     else ", by hand")
    text = f"t_r {time_text(found.value.value)} ({where})"
    if source.origin_how != "assumed":
        x, y = (number_text(axis * LENGTH_SCALE, WIDTH_DIGITS) for axis in source.origin)
        how = layer_text(source.origin_source) if source.origin_how == "manual" else source.origin_how
        text += f" · origin ({x}, {y}) mm ({how})"
    return text


def nothing_text(data: Projections) -> str:
    """Why there is nothing to draw ("" when there is)."""
    if not data.planes:
        return "No plane is on: turn one on under Planes"
    return (empty_text(data.total_shots, len(data.shots), data.events)
            or (f"No release time, so no velocities: {data.failure}" if data.failure else "")
            or ("" if data.valid else "No event in the view range has a velocity (all arrive before t_r)"))


def plane_title(image: PlaneImage, data: Projections) -> str:
    """``Plane 2 · XT · 12,345 events`` (and the slice, and how many fall outside the range)."""
    plane = image.plane
    parts = [plane.label, plane.orientation_text()]
    if plane.thickness > 0:
        parts.append(f"±{number_text(plane.thickness / 2 / data.factor, 4)} {data.unit} slice")
    parts.append(f"{image.inside:,} events")
    if image.kept > image.inside:
        parts.append(f"{image.kept - image.inside:,} outside")
    display = data.drawn(next(index for index, item in enumerate(data.images) if item is image))
    if display is not None:
        rows, columns = display.image.shape
        parts.append(f"{image.counts.shape[0]:,} × {image.counts.shape[1]:,} bins drawn at {rows:,} × {columns:,}")
    return " · ".join(parts)


def axis_title(name: str, data: Projections) -> str:
    return f"{name} ({data.unit})"


def heading(result: AnalysisResult, data: Projections) -> list[str]:
    """The figure's title lines: the events, then t_r and the origin, then each warning and note."""
    first = (f"{result.input.short()} · {shots_text(data.shots, data.total_shots)} · "
             f"{data.valid:,} velocities of {data.events:,} events")
    if len(data.points) < data.valid:
        first += f" · {len(data.points):,} drawn in 3D"
    return [first, data.release, *(f"⚠ {text}" for text in (*data.warnings, *data.notes))]


class PlaneProjections(DatasetAnalysis):
    """The events' velocities in 3D with up to four planes, and each plane's histogram of them flattened onto it."""

    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="Plane projections",
            description="The events' velocities at release in 3D with up to four planes at any angle, and each "
                        "plane's histogram of the events flattened onto it",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.v2.plane_projections",
            version="1",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [*PARAMETERS]

    def constant_keys(self, action_name: str) -> tuple[str, ...]:
        return CONSTANT_KEYS

    def cache_types(self, action_name: str) -> Sequence[Any]:
        return (Projections, PlaneImage, Plane, Display)

    def estimated_bytes(self, action_name: str, values: Mapping[str, Any]) -> int:
        """Every plane on, at the bins set (automatic: counted at its most, ``MAX_AUTO_BINS``), and drawing them."""
        bins = int(values.get(BINS.name, 0)) or MAX_AUTO_BINS
        return planes_bytes([(bins, bins)] * len(planes_of(values)))

    def describe_result(self, action_name: str, result: AnalysisResult) -> str:
        """The memory warning, for the dock's settings line and Plot info."""
        data = result.data
        warnings = data.warnings if isinstance(data, Projections) else ()
        return " · ".join(f"⚠ {note}" for note in warnings if note.startswith(ESTIMATE_PREFIX))

    def live_policy(self, action_name: str) -> LivePolicy:
        # As the Velocity distributions plot: a run converts every event and may detect t_r (seconds on a large folder).
        return LivePolicy(min_delay=5.0)

    def minimum_size(self, action_name: str) -> tuple[int, int]:
        return 480, 480  # The 3D view over a row of up to four histograms.

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        planes = ", ".join(plane.orientation_text() + (" slice" if plane.thickness > 0 else "")
                           for plane in planes_of(values))
        bins = int(values.get(BINS.name, 0))
        half = float(values.get(HALF_WIDTH.name, 0.0))
        colours = Colours.of(values)
        settings = (planes or "no plane", shots_brief(values), range_brief(values, fixed=True),
                    str(values.get(UNIT.name, MM_S)), f"bins {bins:,}" if bins else "bins auto",
                    f"±{number_text(half * 1e3, 4)} mm/s" if half > 0 else "",
                    f"colours {scale_text(colours.scale, colours.gamma, colours.decades)}"
                    if scale_text(colours.scale, colours.gamma, colours.decades) else "")
        return selection_text(view, values), " · ".join(part for part in settings if part)

    def parameter_warnings(self, action_name: str, values: Mapping[str, Any]) -> List[str]:
        planes = [] if planes_of(values) else ["No plane is on: turn one on under Planes"]
        return [*planes, *range_warnings(values), *search_range(values)[2]]

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        values, view = context.parameters, context.view
        shots = select_shots(view, values)
        events = view.events(shots)
        planes = planes_of(values)
        constants = context.resolved_constants
        if constants is None:  # Run without the runner: resolved here, the same way.
            constants = resolve_for_run(values, context.constants.get("lab"), context.constants.get("folder"))
        lower, upper, search_warnings = search_range(values)
        warnings = (*range_warnings(values), *search_warnings)
        unit = str(values.get(UNIT.name, MM_S))
        factor = unit_factor(unit, constants)
        if not (math.isfinite(factor) and factor > 0):
            warnings += (f"the recoil wavelength gives no {unit}: using mm/s",)
            unit, factor = MM_S, 1e-3
        data = Projections(tuple(shots), len(view.shots), len(events), unit=unit, factor=factor,
                           warnings=warnings, planes=len(planes))
        if not planes or not len(events):
            return data
        context.check()

        def detect() -> ReleaseTime:
            found = detect_release_time(events[:, 0], constants, lower, upper, positions=events[:, 1:3])
            context.check()
            return found
        source = run_velocity_source(constants, detect)
        if not source.release.ok:
            return Projections(data.shots, data.total_shots, data.events, unit=unit, factor=factor,
                               failure=source.release.failure, warnings=warnings, planes=len(planes))
        notes = [*((DETECTED_NOTE,) if source.detected else ()),
                 *((ASSUMED_NOTE,) if source.origin_how == "assumed" else ()), *constants.notes]
        box = (crop_box(events, keep_fraction(values), context.cancelled) if not manual(values)
               else manual_box(events, values))
        context.check()
        inside = events[box.contains(events)] if box.kept else np.empty((0, 3))
        good, _ = valid_velocities(inside, source.release.value.value, constants, source.origin)
        xyz = as_xyz(good)
        keep = float(values.get(KEEP.name, KEEP.default)) / 100
        bins = int(values.get(BINS.name, 0))
        half = float(values.get(HALF_WIDTH.name, 0.0))
        images, displays = [], []
        for plane in planes:
            context.check()
            image = plane_image(xyz, plane, keep, bins, half, context.check)
            images.append(image)
            # Drawn from the mean of blocks of bins, made here on the worker: the GUI thread never handles more
            # than PLOTLY_SIDE cells a side (review R4; as the XY, XT, YT histograms' screen resolution, GT-4).
            context.check()
            displays.append(display_of(image.counts, image.h_edges, image.v_edges, PLOTLY_SIDE))
        # The memory its bins take (as they came out: automatic ones known now), against the RAM budget.
        estimate = planes_bytes([(int(image.counts.shape[0]), int(image.counts.shape[1])) for image in images])
        if estimate_over(estimate, context.ram_budget):
            warnings += (estimate_text(estimate, context.ram_budget),)
        points = xyz[display_sample(len(xyz), int(values.get(CAP.name, CAP.default)))]
        return Projections(data.shots, data.total_shots, data.events, len(inside), len(xyz), unit, factor,
                           tuple(images), points, release_text(source), "", tuple(notes), warnings, len(planes),
                           tuple(displays))

    def backends(self, action_name: str) -> Sequence[str]:
        return (PLOTLY, MATPLOTLIB)

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        return self.draw(result, PLOTLY, parent)

    def draw(self, result: AnalysisResult, backend: str, parent: Optional[QWidget] = None) -> QWidget:
        why = nothing_text(result.data)
        if why:
            return empty_pane(why, parent)
        if backend == MATPLOTLIB:
            return MatplotlibPane(projections_matplotlib(result), parent)
        return PlotlyPane(projections_plotly(result), parent=parent)

    def update(self, widget: QWidget, result: AnalysisResult) -> bool:
        """A rerun (e.g. Live's next shots) is drawn in place: the 3D camera stays (Plotly)."""
        if nothing_text(result.data):
            return False
        return (plotly_update(widget, projections_plotly(result))
                or matplotlib_update(widget, lambda figure: projections_matplotlib(result, figure)))


def drawn_peak(display: Display) -> float:
    """The colour range's top for a drawn image: its largest mean, so the colours read what is drawn (at least a
    hundredth of an event a bin, for an image with nothing in it)."""
    return max(float(display.image.max()) if display.image.size else 0.0, 0.01)


def rgb(colour: tuple[int, int, int]) -> str:
    return f"rgb({colour[0]},{colour[1]},{colour[2]})"


def centres(edges: Array) -> Array:
    return (edges[:-1] + edges[1:]) / 2


def projections_plotly(result: AnalysisResult) -> go.Figure:
    """The 3D view (v_x, v_y, v_z, equal scales) with each plane drawn in it, over a row of the planes' histograms."""
    from plotly.subplots import make_subplots

    data: Projections = result.data
    values = result.parameters
    count = len(data.images)
    factor = data.factor
    titles = ["", *(plane_title(image, data) for image in data.images)]
    figure = make_subplots(rows=2, cols=count, row_heights=(0.58, 0.42), vertical_spacing=0.1,
                           horizontal_spacing=0.08 if count > 1 else 0.02, subplot_titles=titles,
                           specs=[[{"type": "scene", "colspan": count}, *([None] * (count - 1))],
                                  [{"type": "xy"} for _ in range(count)]])
    layout: Any = figure.layout  # (Plotly is loosely typed.)
    points = data.points / factor
    figure.add_trace(go.Scatter3d(
        x=points[:, 0], y=points[:, 1], z=points[:, 2], mode="markers", name="events", showlegend=False,
        marker=dict(size=float(values.get(POINT_SIZE.name, POINT_SIZE.default)), color=rgb(POINT_COLOUR),
                    opacity=float(values.get(OPACITY.name, OPACITY.default))),
        hovertemplate="v_x %{x:.4g}<br>v_y %{y:.4g}<br>v_z %{z:.4g}<extra></extra>"), row=1, col=1)
    solid = float(values.get(PLANE_OPACITY.name, PLANE_OPACITY.default))
    colours = Colours.of(values)
    scale = plotly_scale(colours)
    for column, image in enumerate(data.images, start=1):
        colour = COLOURS[(int(image.plane.label.split()[-1]) - 1) % len(COLOURS)]
        corners = image.corners() / factor
        figure.add_trace(go.Mesh3d(x=corners[:, 0], y=corners[:, 1], z=corners[:, 2], i=[0, 0], j=[1, 2], k=[2, 3],
                                   color=rgb(colour), opacity=solid, name=image.plane.label, hoverinfo="name",
                                   showlegend=False), row=1, col=1)
        loop = np.vstack((corners, corners[:1]))
        figure.add_trace(go.Scatter3d(x=loop[:, 0], y=loop[:, 1], z=loop[:, 2], mode="lines",
                                      line=dict(color=rgb(colour), width=4), name=image.plane.label,
                                      hoverinfo="name", showlegend=False), row=1, col=1)
        across, up = image.plane.axis_names()
        display = data.drawn(column - 1)
        if display is None:
            figure.add_trace(go.Heatmap(
                x=centres(image.h_edges) / factor, y=centres(image.v_edges) / factor, z=image.counts.T, zmin=0,
                zmax=max(image.peak, 1), colorscale=scale, showscale=False, name=image.plane.label,
                hovertemplate=f"{across} %{{x:.4g}}<br>{up} %{{y:.4g}}<br>%{{z:,}} events<extra></extra>"),
                row=2, col=column)
        else:  # (A block's mean: no one bin's events to show.)
            blocks = f"{cell_bins(display.factors[0])} × {cell_bins(display.factors[1])} bins"
            figure.add_trace(go.Heatmap(
                x=centres(display.h_edges) / factor, y=centres(display.v_edges) / factor, z=display.image.T, zmin=0,
                zmax=drawn_peak(display), colorscale=scale, showscale=False, name=image.plane.label,
                hovertemplate=f"{across} %{{x:.4g}}<br>{up} %{{y:.4g}}<br>%{{z:.4g}} events a bin (the mean of "
                              f"{blocks})<extra></extra>"), row=2, col=column)
        subplot: Any = figure.get_subplot(2, column)  # (Plotly is loosely typed.)
        figure.update_xaxes(title_text=axis_title(across, data), row=2, col=column)
        figure.update_yaxes(title_text=axis_title(up, data), row=2, col=column,
                            scaleanchor=subplot.xaxis.plotly_name.replace("axis", ""), scaleratio=1)
        layout.annotations[column - 1].font.color = rgb(colour)  # (The 3D view's empty title makes none.)
    for annotation in layout.annotations:
        annotation.font.size = 11
    title = heading(result, data)
    figure.update_layout(
        title=dict(text=title[0] + "".join(f"<br><sup>{line}</sup>" for line in title[1:] if line), x=0.01),
        scene=dict(xaxis_title=axis_title("v_x", data), yaxis_title=axis_title("v_y", data),
                   zaxis_title=axis_title("v_z", data), aspectmode="data"),
        margin=dict(l=40, r=20, b=40, t=40 + 16 * len(title)), plot_bgcolor="white",
        # Constant: a newer figure on the same page keeps the user's rotation, zoom and pan.
        uirevision=UI_REVISION)
    return figure


def projections_matplotlib(result: AnalysisResult, drawn: Any = None) -> Any:
    """Matplotlib's 3D axes with the planes, over a row of their histograms (equal scales throughout)."""
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    data: Projections = result.data
    values = result.parameters
    figure = mpl_figure(drawn)
    count = len(data.images)
    grid = figure.add_gridspec(2, count, height_ratios=(1.3, 1.0))
    view = figure.add_subplot(grid[0, :], projection="3d")
    factor = data.factor
    points = data.points / factor
    size = float(values.get(POINT_SIZE.name, POINT_SIZE.default))
    view.scatter(points[:, 0], points[:, 1], points[:, 2], s=size ** 2, linewidths=0, depthshade=False,
                 color=mpl_colour(POINT_COLOUR, float(values.get(OPACITY.name, OPACITY.default))))
    solid = float(values.get(PLANE_OPACITY.name, PLANE_OPACITY.default))
    colours = Colours.of(values)
    spans = [points] if len(points) else []
    for column, image in enumerate(data.images):
        colour = COLOURS[(int(image.plane.label.split()[-1]) - 1) % len(COLOURS)]
        corners = image.corners() / factor
        spans.append(corners)
        view.add_collection3d(Poly3DCollection([corners], facecolors=[mpl_colour(colour, solid)],
                                               edgecolors=[mpl_colour(colour)], linewidths=1.5))
        axes = figure.add_subplot(grid[1, column])
        display = data.drawn(column)
        if display is None:
            axes.pcolormesh(image.h_edges / factor, image.v_edges / factor, image.counts.T, cmap="viridis",
                            norm=matplotlib_norm(colours, max(image.peak, 1)), shading="flat", rasterized=True)
        else:  # One raster of equal cells (a quad a bin is too many to draw).
            axes.imshow(display.image.T, origin="lower", cmap="viridis", interpolation="nearest",
                        norm=matplotlib_norm(colours, drawn_peak(display)),
                        extent=(display.h_edges[0] / factor, display.h_edges[-1] / factor,
                                display.v_edges[0] / factor, display.v_edges[-1] / factor))
        axes.set_aspect("equal")
        across, up = image.plane.axis_names()
        axes.set_xlabel(axis_title(across, data), fontsize=8)
        axes.set_ylabel(axis_title(up, data), fontsize=8)
        axes.tick_params(labelsize=7)
        axes.set_title(plane_title(image, data), fontsize=8, color=mpl_colour(colour), wrap=True)
    every = np.vstack(spans)
    low, high = every.min(axis=0), every.max(axis=0)
    width = np.where(high > low, high - low, 1.0)
    view.set_xlim(low[0], low[0] + width[0])
    view.set_ylim(low[1], low[1] + width[1])
    view.set_zlim(low[2], low[2] + width[2])
    view.set_box_aspect(tuple(float(side) for side in width))  # Equal scales: every axis a velocity.
    for label, name in ((view.set_xlabel, "v_x"), (view.set_ylabel, "v_y"), (view.set_zlabel, "v_z")):
        label(axis_title(name, data), fontsize=8)
    view.tick_params(labelsize=7)
    figure.suptitle("\n".join(line for line in heading(result, data) if line), fontsize=8, wrap=True)
    return figure
