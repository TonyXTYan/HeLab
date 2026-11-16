"""XY, XT and YT histograms (Basic plots v2, LR-13): one plot of the chosen shots' events binned in up to three
planes, each plane's third axis summed over the selection (``helab.analysis.histogram2d``), side by side under
one set of settings; each plane is turned on or off under Planes. With the DLD port's Density images' options
(Tony's choice): blur filters under Blur (``helab.analysis.image_filters``: Gaussian in bins or in m and s, box,
median, Poisson denoise, adaptive KDE; each on by itself, run in the order set), counts per bin or a rate per shot, and the colour
range compressed (sqrt, log, power γ) in the colour map only, so the colour bar reads real values. Bins are set
per axis (T, X, Y), so an axis shown in two planes has the same bins in both. In s and m with SI prefixes (Basic
plots' units). Drawn with PyQtGraph (``ImageItem``) by default, or Plotly or Matplotlib; updated in place as Live
adds shots. Under Image, Draw › dots draws each event (up to Max dots, a fixed sample beyond) instead of the bins,
coloured by nothing, the summed axis or the local density (its bin's value in the image, filtered, on the image's colour
scale), on a white or black plot area. A space axis runs across every plane and T runs up XT and YT. In PyQtGraph and Plotly every space
axis shown has the same scale (metres per pixel, ``SpaceScale``), XY's at equal scales, and T is the same in XT and
YT. Matplotlib gives the space axes the same span instead."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Mapping, Optional, Sequence, cast

import numpy as np
import numpy.typing as npt
import plotly.graph_objs as go
import pyqtgraph as pg
from PyQt6.QtCore import QObject, QPointF, QRectF, QTimer
from PyQt6.QtGui import QColor, QFontMetricsF
from PyQt6.QtWidgets import QApplication, QWidget

from helab.analysis.budget_core import ESTIMATE_PREFIX, estimate_over, estimate_text
from helab.analysis.backends import MATPLOTLIB, PLOTLY, PYQTGRAPH, MatplotlibPane, WrappingLabel, mpl_figure
from helab.analysis.dataset_view import DatasetView
from helab.analysis.empty import empty_pane, empty_text
from helab.analysis import image_filters
from helab.analysis.display_units import si_text
from helab.analysis.histogram2d import (DISPLAY_SIDE, LINEAR, LOG, MAX_AUTO_BINS, MAX_BINS, PLANES, PLOTLY_SIDE, POWER,
                                        SCALES, Histogram2D, bin_area, cell_edges, cell_mean, compress,
                                        display_shape, estimated_bytes, histogram2d, scale_text)
from helab.analysis.panes import PlotlyPane
from helab.analysis.parameters import Kind, ParameterSpec, Value
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.selection import (MANUAL, RANGE_GROUP, RANGE_MODE, SHOT_SPECS, keep_fraction, manual,
                                      manual_bounds, range_brief, range_specs, range_text, range_warnings,
                                      reversed_axes, select_shots, selection_text, shots_brief, shots_text)
from helab.analysis.stats import AXES, UNITS, display_sample
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.standard.basic_plots import matplotlib_update, plotly_update
from helab.scripts.standard_v2 import group
from helab.scripts.standard_v2.common import notes_html, source_title

RANGE = range_specs(
    "Each shown axis covers the exact shortest range holding this share of its events; the summed axis isn't "
    "cut (every event of the chosen shots counts). 100 % covers every event.")
OUTSIDE = ParameterSpec(
    "include_outside", "Sum the whole summed axis", "bool", False, group=RANGE_GROUP, when=(RANGE_MODE.name, MANUAL),
    tip="On: the bounds set on the summed axis are left out, so every event of the chosen shots along it counts "
        "and the bounds cut only the two shown axes. Off: they limit the events summed (a T window on XY "
        "images one cloud).")
PLANES_GROUP = "Planes"
SHOW = {plane: ParameterSpec(
    f"show_{plane.lower()}", f"{plane} ({PLANES[plane][2]} summed)", "bool", True, group=PLANES_GROUP,
    tip=f"Show the {plane} histogram: {PLANES[plane][0]} across, {PLANES[plane][1]} up, {PLANES[plane][2]} summed "
        f"over the chosen shots.") for plane in PLANES}
IMAGE_GROUP = "Image"
BINS = {axis: ParameterSpec(
    f"bins_{axis.lower()}", f"{axis} bins (0 = auto)", "int", 0, (0, MAX_BINS), group=IMAGE_GROUP,
    tip=f"Bins on {axis} wherever it is shown. 0 = automatic (Freedman–Diaconis on {axis} in each plane, at most "
        f"{MAX_AUTO_BINS:,}; set by hand, at most {MAX_BINS:,}).") for axis in AXES}
SCREEN, EVERY_BIN = "screen resolution", "every bin"
DRAWN_DOTS = 500_000  # At most this many dots a plane drawn at screen resolution (PyQtGraph and Matplotlib).
DRAW_AT = ParameterSpec(
    "draw_at", "Draw at", "choice", SCREEN, choices=(SCREEN, EVERY_BIN), group=IMAGE_GROUP,
    tip=f"Screen resolution: an image of more than {DISPLAY_SIDE:,} bins a side is drawn from the mean of blocks of "
        f"bins, at most {DISPLAY_SIDE:,} a side (Plotly {PLOTLY_SIDE:,}), and at most {DRAWN_DOTS:,} dots a plane "
        "are drawn in PyQtGraph and Matplotlib; the plane's title says so. The bins, counts and filters stay as set. "
        "Every bin: each bin and dot drawn, which at the largest bins can take seconds and gigabytes, the window "
        "waiting.")
HISTOGRAM, DOTS = "histogram", "dots"
DRAW = ParameterSpec(
    "draw", "Draw", "choice", HISTOGRAM, choices=(HISTOGRAM, DOTS), group=IMAGE_GROUP,
    tip="The events binned (histogram), or each event as a dot, no bins drawn. Dots cover the same view range, and "
        "their local density colouring is their bin's value in the image (bins, blur and rate per shot as set).")
NO_COLOUR, SUMMED, DENSITY = "none", "summed axis", "local density"
DOT_COLOUR = ParameterSpec(
    "dot_colour", "Dot colour", "choice", DENSITY, choices=(NO_COLOUR, SUMMED, DENSITY), group=IMAGE_GROUP,
    when=(DRAW.name, DOTS),
    tip="None: one colour. Summed axis: each dot's own third coordinate (T on XY, Y on XT, X on YT), linear over its "
        "range in that plane (in the plane's title). Local density: the value of the dot's bin in the image, on the "
        "colour scale set under Colour, the densest dots drawn on top.")
MAX_DOTS = ParameterSpec(
    "max_dots", "Max dots", "int", 200_000, (1_000, 5_000_000), " per plane", group=IMAGE_GROUP,
    when=(DRAW.name, DOTS),
    tip="At most this many dots in each plane: beyond it, a fixed random sample of the events in the view range "
        "(the plane's title says so). The bins and the local density count every event.")
WHITE, BLACK = "white", "black"
BACKGROUND = ParameterSpec(
    "dot_background", "Background", "choice", WHITE, choices=(WHITE, BLACK), group=IMAGE_GROUP,
    when=(DRAW.name, DOTS),
    tip="The plot area behind the dots (the titles, axes and colour bar stay on white). Black brings out faint "
        "dots; uncoloured dots are then white.")
DOT_SIZE = 2  # px (PyQtGraph and Plotly; Matplotlib's smallest marker)
# Dots without colouring: one translucent tint, so that overlaps read as stronger: blue on white, white on black.
DOT_TINTS = {WHITE: (31, 78, 156, 140), BLACK: (255, 255, 255, 120)}
AREA_COLOURS = {WHITE: "#ffffff", BLACK: "#000000"}
DARK_GRID = "#3a3a3a"  # Plotly's grid and zero lines on black


def background(values: Mapping[str, Any]) -> str:
    """The plot area's colour: black only for dots set so."""
    return BLACK if values.get(DRAW.name) == DOTS and values.get(BACKGROUND.name) == BLACK else WHITE
BLUR_GROUP = "Blur"
ORDER_TIP = ("Where this filter runs in the chain: lower first (an equal number runs in the order listed). Gaussian, "
             "Gaussian in m and s, and box commute with one another, so their order among themselves changes nothing; "
             "median, denoise and adaptive KDE don't, so where they sit matters.")
CAP_TIP = "A σ is at most a quarter of the image's side on each axis (the plot says so)."
FILTER_TITLES = {image_filters.MEDIAN: "Median", image_filters.DENOISE: "Denoise (counts)",
                 image_filters.ADAPTIVE: "Adaptive KDE", image_filters.GAUSSIAN: "Gaussian (σ in bins)",
                 image_filters.UNITS: "Gaussian (σ in m, s)", image_filters.BOX: "Box"}
FILTER_TIPS = {
    image_filters.MEDIAN: "Each bin becomes the median of the square of bins around it: lone hot bins and speckle go, "
                          "edges stay sharp. It doesn't keep the total (counts and rates near it change).",
    image_filters.DENOISE: "For counts: the Anscombe transform (2√(n + 3/8), whose noise is about the same whatever the "
                           "count), a Gaussian blur there, and back, scaled to keep the total. Best first, on the "
                           "counts themselves.",
    image_filters.ADAPTIVE: "An adaptive kernel density estimate on the bins (Abramson's): a pilot Gaussian of σ sets "
                            "each bin's own σ, wider where it is faint and narrower where bright (¼ … 4 times σ), so "
                            "sparse regions are smoothed and dense cores kept. The total is kept.",
    image_filters.GAUSSIAN: "A Gaussian blur, its σ in bins on both axes. The total is kept (edges reflect).",
    image_filters.UNITS: "A Gaussian blur, its σ in metres on X and Y and in seconds on T, so it is the same size in "
                         "every plane whatever their bins. The total is kept.",
    image_filters.BOX: "The mean over the square of bins around each bin (a top-hat). The total is kept.",
}


def filter_group(kind: str) -> str:
    return f"{BLUR_GROUP}/{FILTER_TITLES[kind]}"


def filter_on(kind: str) -> ParameterSpec:
    return ParameterSpec(f"blur_{kind}", "On", "bool", False, group=filter_group(kind), tip=FILTER_TIPS[kind])


def when_on(kind: str) -> tuple[str, str]:
    return f"blur_{kind}", "True"  # (``when`` compares the value's text.)


def filter_order(kind: str) -> ParameterSpec:
    return ParameterSpec(f"blur_{kind}_order", "Order", "int", image_filters.FILTERS.index(kind) + 1,
                         (1, len(image_filters.FILTERS)), group=filter_group(kind), when=when_on(kind), tip=ORDER_TIP)


def filter_spec(kind: str, name: str, title: str, kind_of: Kind, default: Value, limits: tuple[float, float],
                suffix: str = "", tip: str = "", si: bool = False) -> ParameterSpec:
    return ParameterSpec(f"blur_{kind}_{name}", title, kind_of, default, limits, suffix, group=filter_group(kind),
                         when=when_on(kind), tip=tip, si=si)


FILTER_SPECS = {
    image_filters.MEDIAN: (filter_spec(image_filters.MEDIAN, "size", "Size", "int", 3, (2, 51), " bins",
                                       "The square's side, in bins."),),
    image_filters.DENOISE: (filter_spec(image_filters.DENOISE, "sigma", "σ", "float", 1.0, (0.1, 50.0), " bins",
                                        "The blur's σ after the transform, in bins. " + CAP_TIP),),
    image_filters.ADAPTIVE: (filter_spec(image_filters.ADAPTIVE, "sigma", "σ", "float", 2.0, (0.1, 50.0), " bins",
                                         "The pilot's σ, and the middle of the bins' own σ, in bins. " + CAP_TIP),
                             filter_spec(image_filters.ADAPTIVE, "alpha", "α", "float", 0.5, (0.0, 1.0), "",
                                         "How strongly a bin's σ follows its brightness: σ × (pilot / its geometric "
                                         "mean)^-α. 0 is a plain Gaussian; ½ is Abramson's.")),
    image_filters.GAUSSIAN: (filter_spec(image_filters.GAUSSIAN, "sigma", "σ", "float", 1.0, (0.1, 50.0), " bins",
                                         "The blur's σ, in bins. " + CAP_TIP),),
    image_filters.UNITS: (filter_spec(image_filters.UNITS, "space", "σ on X, Y", "float", 1e-4, (1e-7, 1.0), " m",
                                      "The blur's σ on X and Y. " + CAP_TIP, si=True),
                          filter_spec(image_filters.UNITS, "time", "σ on T", "float", 1e-4, (1e-8, 10.0), " s",
                                      "The blur's σ on T. " + CAP_TIP, si=True)),
    image_filters.BOX: (filter_spec(image_filters.BOX, "size", "Size", "int", 3, (2, 51), " bins",
                                    "The square's side, in bins."),),
}
BLUR_SPECS = [spec for kind in image_filters.FILTERS
              for spec in (filter_on(kind), *FILTER_SPECS[kind], filter_order(kind))]


def blur_steps(values: Mapping[str, Any], item: Histogram2D) -> list[image_filters.Step]:
    """The filters turned on, as steps for ``item``'s bins (σ in m and s become bins on each axis)."""
    steps = []
    for kind in image_filters.FILTERS:
        if not values.get(f"blur_{kind}"):
            continue
        order = int(values.get(f"blur_{kind}_order", image_filters.FILTERS.index(kind) + 1))
        if kind in (image_filters.MEDIAN, image_filters.BOX):
            size = int(values.get(f"blur_{kind}_size", 3))
            steps.append(image_filters.Step(kind, order, size=size, text=f"{kind} {size} × {size} bins"))
        elif kind == image_filters.UNITS:
            space, time = float(values.get("blur_units_space", 1e-4)), float(values.get("blur_units_time", 1e-4))
            widths = (float(item.h_edges[1] - item.h_edges[0]), float(item.v_edges[1] - item.v_edges[0]))
            wanted = tuple(time if axis == "T" else space for axis in item.axes[:2])
            sigma = (wanted[0] / widths[0] if widths[0] > 0 else 0.0, wanted[1] / widths[1] if widths[1] > 0 else 0.0)
            sizes = " × ".join(dict.fromkeys(si_text(value, "s" if axis == "T" else "m", 3)
                                             for value, axis in zip(wanted, item.axes[:2])))
            steps.append(image_filters.Step(kind, order, sigma=sigma,
                                            text=f"Gaussian σ {sizes} ({sigma[0]:.3g} × {sigma[1]:.3g} bins)"))
        else:
            sigma_bins = float(values.get(f"blur_{kind}_sigma", 1.0))
            alpha = float(values.get("blur_adaptive_alpha", 0.5))
            name = {image_filters.GAUSSIAN: "Gaussian", image_filters.DENOISE: "denoise",
                    image_filters.ADAPTIVE: "adaptive KDE"}[kind]
            extra = f", α {alpha:g}" if kind == image_filters.ADAPTIVE else ""
            steps.append(image_filters.Step(kind, order, sigma=(sigma_bins, sigma_bins), alpha=alpha,
                                            text=f"{name} σ {sigma_bins:g} bins{extra}"))
    return image_filters.chain(steps)


def blur_brief(values: Mapping[str, Any]) -> str:
    """The filters on, in their order, for the dock's line ("" for none)."""
    on = [kind for kind in image_filters.FILTERS if values.get(f"blur_{kind}")]
    ordered = sorted(on, key=lambda kind: (int(values.get(f"blur_{kind}_order", 0)), image_filters.FILTERS.index(kind)))
    names = {image_filters.MEDIAN: "median", image_filters.DENOISE: "denoise", image_filters.ADAPTIVE: "adaptive KDE",
             image_filters.GAUSSIAN: "Gaussian", image_filters.UNITS: "Gaussian (m, s)", image_filters.BOX: "box"}
    return "blur " + " → ".join(names[kind] for kind in ordered) if ordered else ""
COUNTS, PER_SHOT = "counts per bin", "rate per shot"
QUANTITY = ParameterSpec("quantity", "Show", "choice", COUNTS, choices=(COUNTS, PER_SHOT), group=IMAGE_GROUP,
                         tip="Counts per bin, or a rate per shot: counts / shots chosen / bin area (per mm² for XY; "
                             "per mm per ms for XT and YT).")
COLOUR_GROUP = "Colour"
SCALE = ParameterSpec("colour_scale", "Colour scale", "choice", LINEAR, choices=SCALES, group=COLOUR_GROUP,
                      tip="Compresses the colour range only: the image's values stay linear and the colour bar "
                          "reads them. sqrt and power γ below 1 bring out faint regions; log spans the decades "
                          "below the maximum.")
GAMMA = ParameterSpec("gamma", "γ", "float", 0.5, (0.05, 5.0), group=COLOUR_GROUP, when=(SCALE.name, POWER),
                      tip="Colour position = value^γ (of the colour bar's range): below 1 brings out faint regions, "
                          "above 1 the bright ones.")
DECADES = ParameterSpec("log_decades", "Decades", "int", 3, (1, 8), group=COLOUR_GROUP, when=(SCALE.name, LOG),
                        tip="How many decades below the maximum the colours span; lower values share the darkest "
                            "colour.")
COLOUR_MAP = "viridis"
LUT_SIZE = 1024


@dataclass(frozen=True)
class Dots:
    """A plane's events drawn as dots: those inside the shown ranges (and the summed axis's bounds), or a fixed
    sample of them beyond Max dots (``display_sample``). ``values``: each dot's colour value (its summed-axis
    coordinate, or its bin's value in the image; empty for none); ``span``: the summed axis's range over every
    event inside, for its colouring."""
    h: npt.NDArray[np.float64]
    v: npt.NDArray[np.float64]
    colour: str
    values: npt.NDArray[np.float64]
    inside: int
    span: tuple[float, float] = (0.0, 1.0)

    @property
    def drawn(self) -> int:
        return len(self.h)


def plane_dots(events: npt.NDArray[np.float64], item: Histogram2D, image: npt.NDArray[np.float64], colour: str,
               cap: int) -> Dots:
    """``item``'s events as dots, coloured by ``colour`` (``image``: the plane's image, for the local density)."""
    horizontal, vertical, summed = (AXES.index(name) for name in item.axes)
    if item.flattened is not None and len(events):
        column = events[:, summed]
        events = events[(column >= item.flattened[0]) & (column <= item.flattened[1])]
    h_edges, v_edges = item.h_edges, item.v_edges
    h, v = events[:, horizontal], events[:, vertical]
    inside = events[(h >= h_edges[0]) & (h <= h_edges[-1]) & (v >= v_edges[0]) & (v <= v_edges[-1])]
    span = (float(inside[:, summed].min()), float(inside[:, summed].max())) if len(inside) else (0.0, 1.0)
    picked = inside[display_sample(len(inside), cap)]
    h, v = np.ascontiguousarray(picked[:, horizontal]), np.ascontiguousarray(picked[:, vertical])
    values = np.empty(0)
    if colour == SUMMED:
        values = np.ascontiguousarray(picked[:, summed])
    elif colour == DENSITY:
        across = np.clip(np.searchsorted(h_edges, h, side="right") - 1, 0, image.shape[0] - 1)
        up = np.clip(np.searchsorted(v_edges, v, side="right") - 1, 0, image.shape[1] - 1)
        values = image[across, up]
        order = np.argsort(values, kind="stable")  # The densest last: drawn on top.
        h, v, values = h[order], v[order], values[order]
    return Dots(h, v, colour, np.asarray(values, dtype=np.float64), len(inside), span)


def at_screen(values: Mapping[str, Any]) -> bool:
    """Whether the plot is drawn at screen resolution (Draw at, Q~1)."""
    return bool(values.get(DRAW_AT.name, SCREEN) != EVERY_BIN)


@dataclass(frozen=True)
class Display:
    """A plane's image as drawn at screen resolution (Q~1): equal cells, each the mean of the ``factors`` bins it
    covers (``cell_mean``, float32; whole blocks of bins when they divide, else a bin on a border counts by its
    part inside), and those cells' edges, evenly spaced, so the image drawn over its range has every cell in its
    place. Made on the worker, by ``compute``."""
    image: npt.NDArray[np.float32]
    h_edges: npt.NDArray[np.float64]
    v_edges: npt.NDArray[np.float64]
    factors: tuple[float, float]


def display_of(image: npt.NDArray[np.floating[Any]], h_edges: npt.NDArray[np.float64],
               v_edges: npt.NDArray[np.float64], side: int) -> Optional[Display]:
    """``image`` drawn at most ``side`` a side, or None when it is that small already."""
    shape = (int(image.shape[0]), int(image.shape[1]))
    drawn = display_shape(shape, side)
    if drawn == shape:
        return None
    return Display(cell_mean(image, drawn), cell_edges(h_edges, drawn[0]), cell_edges(v_edges, drawn[1]),
                   (shape[0] / drawn[0], shape[1] / drawn[1]))


def cell_bins(bins: float) -> str:
    """The bins one drawn cell covers along an axis: a whole number when the bins divide, else to 4 figures."""
    return f"{round(bins):,}" if abs(bins - round(bins)) < 1e-9 else f"{bins:.4g}"


def display_note(display: Display) -> str:
    rows, columns = display.image.shape
    return (f"drawn at {rows:,} × {columns:,}, each the mean of {cell_bins(display.factors[0])} × "
            f"{cell_bins(display.factors[1])} bins")


@dataclass(frozen=True)
class PlaneCounts:
    """A plane's counts (``histogram``) and the image shown (``image``: filtered, per shot if chosen)."""
    histogram: Histogram2D
    image: npt.NDArray[np.float64]
    per_shot: bool = False
    filters: tuple[str, ...] = ()  # the filters run, in their order (``image_filters.Step.text``)
    notes: tuple[str, ...] = ()  # settings not followed as given
    dots: Optional[Dots] = None  # drawn as dots (Draw › dots) instead of the image
    display: Optional[Display] = None  # the image as drawn at screen resolution, when smaller than ``image``

    @property
    def shown(self) -> npt.NDArray[np.floating[Any]]:
        """The image drawn: ``display``'s, else ``image``."""
        return self.display.image if self.display is not None else self.image

    @property
    def peak(self) -> float:
        """The highest value drawn (the colour bar's top)."""
        shown = self.shown
        return float(shown.max()) if shown.size else 0.0


@dataclass(frozen=True)
class Planes:
    """The plot's result: the planes shown (in ``PLANES``' order), the chosen shots, and notes on the shared
    settings."""
    items: tuple[PlaneCounts, ...]
    shots: tuple[int, ...]
    total_shots: int
    notes: tuple[str, ...] = ()  # settings not followed as given (each plane's own are on it)

    @property
    def peak(self) -> float:
        """The highest bin in this group of planes."""
        return max((item.peak for item in self.items), default=0.0)

    @property
    def top(self) -> float:
        """This group's colour bar top (1 when every bin is empty)."""
        return self.peak if self.peak > 0 else 1.0

    @property
    def dot_colour(self) -> str:
        """How the dots are coloured ("" when the planes are drawn as images)."""
        dots = self.items[0].dots if self.items else None
        return dots.colour if dots is not None else ""

    @property
    def real_summed(self) -> bool:
        """Dots coloured by the summed axis in its own units: one plane shown (with more, each plane's summed
        axis differs, and each is coloured over its own range, low to high)."""
        return self.dot_colour == SUMMED and len(self.items) == 1

    @property
    def bar_range(self) -> tuple[float, float]:
        """The colour bar's range: 0 … the highest bin, or with dots coloured by the summed axis its range in
        the one plane shown (0 … 1, low to high, with more)."""
        dots = self.items[0].dots if self.items else None
        if self.dot_colour == SUMMED and dots is not None:
            if not self.real_summed:
                return 0.0, 1.0
            low, high = dots.span
            return (low, high) if high > low else (low - 0.5, low + 0.5)
        return 0.0, self.top


def colour_groups(data: Planes) -> tuple[Planes, ...]:
    """Planes that can share numerical colour ticks: counts together, rates by physical unit."""
    if data.dot_colour in (SUMMED, NO_COLOUR) or not any(item.per_shot for item in data.items):
        return (data,)
    groups = []
    for spatial in (True, False):
        items = tuple(item for item in data.items if (item.histogram.plane == "XY") == spatial)
        if items:
            groups.append(Planes(items, data.shots, data.total_shots, data.notes))
    return tuple(groups)


def left_colour_bar(data: Planes) -> bool:
    """Whether this is XY's rate legend, placed beside the leftmost plane."""
    return (bool(data.items) and data.items[0].per_shot and data.dot_colour not in (SUMMED, NO_COLOUR)
            and all(item.histogram.plane == "XY" for item in data.items))


def colour_group(data: Planes, item: PlaneCounts) -> Planes:
    """The numerical colour range used by this plane, including local-density dots."""
    return next(group for group in colour_groups(data)
                if any(candidate is item for candidate in group.items))


def group_label(data: Planes, colours: Optional[Colours] = None) -> str:
    """The planes and units belonging to one numerical colour axis."""
    label = ", ".join(item.histogram.plane for item in data.items) + ": " + planes_quantity(data)
    return label + (f" · colours {colours.text()}" if colours is not None and colours.text() else "")


@dataclass(frozen=True)
class Colours:
    """The colour scale chosen: compression, γ, decades."""
    scale: str = LINEAR
    gamma: float = 0.5
    decades: int = 3

    @classmethod
    def of(cls, values: Mapping[str, Any]) -> "Colours":
        return cls(str(values.get(SCALE.name, LINEAR)), float(values.get(GAMMA.name, GAMMA.default)),
                   int(values.get(DECADES.name, DECADES.default)))

    def text(self) -> str:
        return scale_text(self.scale, self.gamma, self.decades)


def bins_text(item: Histogram2D) -> str:
    across, up = item.counts.shape
    how = ("automatic" if all(item.automatic) else "set" if not any(item.automatic)
           else "automatic across" if item.automatic[0] else "automatic up")
    return f"{across:,} × {up:,} bins ({how})"


def plane_title(data: PlaneCounts, drawn: Optional[str] = None) -> str:
    """What a plane's image shows, for its own title (the shots are in the plot's). ``drawn``: how it is drawn when
    not every bin or dot is (default: ``display``'s note)."""
    item = data.histogram
    summed = item.axes[2]
    flattened = (f"{summed} summed over {range_text(AXES.index(summed), *item.flattened)}" if item.flattened
                 else f"{summed} summed")
    dots = data.dots
    if dots is None:
        parts = [bins_text(item)]
    else:
        parts = [f"{dots.drawn:,} dots" + (f" (a sample of {dots.inside:,})" if dots.drawn < dots.inside else "")]
        if dots.colour == DENSITY:
            parts.append(f"density in {bins_text(item)}")
        elif dots.colour == SUMMED:
            parts.append(f"colour {range_text(AXES.index(summed), *dots.span)}")
    parts += [f"{item.inside:,} of {item.total:,} events", flattened]
    if not item.summed:
        parts.append("no events inside the summed axis's bounds")
    if item.outside:
        parts.append(f"{item.outside:,} outside the range")
    if data.filters:
        parts.append("blur " + " → ".join(data.filters))
    if drawn is None and data.display is not None:
        drawn = display_note(data.display)
    if drawn:
        parts.append(drawn)
    return " · ".join(parts)


def dot_pick(item: PlaneCounts, screen: bool) -> npt.NDArray[np.intp]:
    """The dots drawn in PyQtGraph and Matplotlib: at most ``DRAWN_DOTS`` at screen resolution (a fixed sample, in
    their order: the densest stay on top), else all."""
    count = item.dots.drawn if item.dots is not None else 0
    return display_sample(count, DRAWN_DOTS) if screen else np.arange(count)


def dots_note(item: PlaneCounts, screen: bool) -> Optional[str]:
    """The title's note when PyQtGraph or Matplotlib draws fewer dots than the plane has (None: all drawn)."""
    if item.dots is None or not screen or item.dots.drawn <= DRAWN_DOTS:
        return None
    return f"{DRAWN_DOTS:,} of them drawn (screen resolution)"


def notes(data: PlaneCounts) -> list[str]:
    return [f"⚠ {note}" for note in data.notes]


def planes_title(data: Planes) -> str:
    """The plot's title: the shots chosen (the input is on the dock's line and in Plot info)."""
    return shots_text(data.shots, data.total_shots)


def plain_title(result: AnalysisResult) -> str:
    data: Planes = result.data
    return " · ".join([source_title(result, planes_title(data)), *(f"⚠ {note}" for note in data.notes)])


def axis_label(name: str) -> str:
    return f"{name} ({UNITS[AXES.index(name)]})"


def quantity_text(data: PlaneCounts) -> str:
    """The colour bar's quantity: events per bin, or per area per shot in ms and mm."""
    blur = " (filtered)" if data.filters else ""
    if not data.per_shot:
        return f"Events per bin{blur}"
    across, up, _ = data.histogram.axes
    area = "mm²" if "T" not in (across, up) else "(mm·ms)"
    return f"Events / {area} / shot{blur}"


def planes_quantity(data: Planes) -> str:
    """The one colour bar's quantity: each plane's, or with a rate per shot over planes of different units (XY's
    per mm², XT's and YT's per mm·ms), which unit is whose."""
    texts = list(dict.fromkeys(quantity_text(item) for item in data.items))
    if len(texts) == 1:
        return texts[0]
    blur = " (filtered)" if any(item.filters for item in data.items) else ""
    return f"Events / bin area / shot (XY per mm², XT and YT per mm·ms){blur}"


def bar_label(data: Planes, colours: Colours) -> str:
    """The quantity, and with a compressed colour scale, that only the colours are (the numbers are real); for
    dots coloured by the summed axis, that axis (or with several planes, that each runs over its own range)."""
    if data.dot_colour == SUMMED:
        if data.real_summed:
            return f"Dot colour: {axis_label(data.items[0].histogram.axes[2])}"
        return "Dot colour: the summed axis, low → high over its range in each plane's title"
    how = colours.text()
    prefix = "Dot colour: local density, " if data.dot_colour == DENSITY else ""
    return prefix + planes_quantity(data) + (f" · colours {how}, values linear" if how else "")


def bar_colours(data: Planes, colours: Colours) -> Colours:
    """The colour scale the bar and dots use: the one set, but linear for the summed axis."""
    return Colours() if data.dot_colour == SUMMED else colours


def dot_values(item: PlaneCounts, data: Planes) -> npt.NDArray[np.float64]:
    """The dots' values on the colour bar (``Planes.bar_range``): the local density, or the summed axis in its
    units (one plane) or over this plane's range, 0 … 1."""
    dots = item.dots
    if dots is None:
        return np.empty(0)
    if dots.colour != SUMMED or data.real_summed:
        return dots.values
    low, high = dots.span
    return (dots.values - low) / (high - low) if high > low else np.full(len(dots.values), 0.5)


def dot_positions(item: PlaneCounts, data: Planes, colours: Colours) -> npt.NDArray[np.float64]:
    """Each dot's place in the colour map (0…1), as the image's bins (compressed) for the local density."""
    low, high = colour_group(data, item).bar_range
    linear = (dot_values(item, data) - low) / (high - low) if high > low else np.zeros(len(dot_values(item, data)))
    shown = bar_colours(data, colours)
    return compress(linear, shown.scale, shown.gamma, shown.decades)


def colour_positions(item: PlaneCounts, colours: Colours, peak: float) -> npt.NDArray[np.float64]:
    """Each drawn cell's place in the colour map (0…1): its value over the planes' peak (``Planes.peak``),
    compressed."""
    shown = np.asarray(item.shown, dtype=np.float64)
    return compress(shown / peak if peak > 0 else np.zeros_like(shown), colours.scale, colours.gamma,
                    colours.decades)


def viridis() -> Any:
    return pg.colormap.get(COLOUR_MAP)


def bar_map(colours: Colours) -> pg.ColorMap:
    """Viridis resampled so that a linear value shows the colour of its compressed position: the colour bar's
    gradient over its linear axis in real values (the image itself is drawn from ``colour_positions``)."""
    positions = colour_stops(colours, LUT_SIZE)
    picked = viridis().map(compress(positions, colours.scale, colours.gamma, colours.decades), mode="byte")
    return pg.ColorMap(positions, picked, name=f"{COLOUR_MAP} ({colours.scale})")


def shown_planes(values: Mapping[str, Any]) -> tuple[str, ...]:
    """The planes turned on, in ``PLANES``' order."""
    return tuple(plane for plane in PLANES if values.get(SHOW[plane].name, True))


def plane_counts(events: npt.NDArray[np.float64], plane: str, values: Mapping[str, Any], chosen: int,
                 check: Callable[[], None]) -> PlaneCounts:
    """One plane's counts and image under the plot's settings, from the chosen shots' ``events``."""
    across, up, summed = PLANES[plane]
    bounds = list(manual_bounds(values)) if manual(values) else [None, None, None]
    if values.get(OUTSIDE.name):
        bounds[AXES.index(summed)] = None  # The bounds cut only the shown axes.
    # Manual: a shown axis without bounds (unset or reversed) covers its full extent, as v1's and the note say.
    item = histogram2d(events, plane, 1.0 if manual(values) else keep_fraction(values),
                       (int(values[BINS[across].name]), int(values[BINS[up].name])),
                       (bounds[0], bounds[1], bounds[2]), check)
    check()
    image, filters, capped = image_filters.apply(item.counts, blur_steps(values, item), check)
    per_shot = values.get(QUANTITY.name) == PER_SHOT
    if per_shot and chosen and item.summed:
        # Bin edges stay in SI units; rates use mm² for XY and mm·ms for XT/YT.
        area = bin_area(item) * 1e6
        image = image / chosen / area
    dots = None
    if values.get(DRAW.name) == DOTS:
        check()
        dots = plane_dots(events, item, image, str(values.get(DOT_COLOUR.name, DENSITY)),
                          int(values.get(MAX_DOTS.name, MAX_DOTS.default)))
    display = None
    if dots is None and at_screen(values):
        # Drawn at screen resolution: the mean of blocks of bins, here on the worker (Q~1; GT-4: colouring every bin
        # of a 20,000² image on the GUI thread took seconds and gigabytes).
        check()
        display = display_of(image, item.h_edges, item.v_edges, DISPLAY_SIDE)
    return PlaneCounts(item, image, per_shot, filters, tuple(f"{plane}: {note}" for note in capped), dots, display)


BAR_WIDTH = 32


class InsideColourAxis(pg.AxisItem):  # type: ignore[misc]  # PyQtGraph is untyped.
    """A colour bar's numerical axis, with legible labels inside the gradient."""

    def __init__(self, orientation: str) -> None:
        super().__init__(orientation=orientation)
        self.label_rects: list[QRectF] = []
        self.gradient_width = BAR_WIDTH
        # The negative length includes the gradient in AxisItem's painting bounds. drawPicture
        # shortens the actual marks; text starts three pixels inside that same bounded area.
        self.setStyle(tickLength=-BAR_WIDTH, tickTextOffset=-BAR_WIDTH + 3, tickAlpha=255,
                      autoExpandTextSpace=False)
        self.setWidth(0)
        self.setPen("k")
        self.setTickPen("k")
        self.setTextPen("k")
        self.unlinkFromView()

    def fit_labels(self, low: float, high: float) -> int:
        """Keep full tick precision inside the bar, widening only when the values need it."""
        metrics = QFontMetricsF(QApplication.font())
        levels = self.tickValues(low, high, max(300.0, self.height()))
        texts = [text for spacing, values in levels for text in self.tickStrings(values, 1.0, spacing)]
        width = max(BAR_WIDTH, int(max((metrics.horizontalAdvance(text) for text in texts), default=0.0)) + 8)
        if width != self.gradient_width:
            self.gradient_width = width
            self.setStyle(tickLength=-width, tickTextOffset=-width + 3)
        return width

    def drawPicture(self, p: Any, axisSpec: Any, tickSpecs: Any, textSpecs: Any) -> None:
        ticks = []
        for pen, start, end in tickSpecs:
            direction = 1 if end.x() > start.x() else -1
            ticks.append((pen, start, QPointF(start.x() + 2 * direction, end.y())))
        super().drawPicture(p, axisSpec, ticks, [])
        bounds = self.mapRectFromParent(self.geometry())
        self.label_rects = []
        for rect, flags, text in textSpecs:
            inside = QRectF(rect)
            inside.moveTop(max(bounds.top() + 2, min(inside.top(), bounds.bottom() - inside.height() - 2)))
            self.label_rects.append(inside)
            p.fillRect(inside.adjusted(-2, 0, 2, 0), QColor(255, 255, 255, 220))
            p.drawText(inside, int(flags), text)


@dataclass
class PlanePanel:
    """A PyQtGraph drawing's items for one plane: its title, plot and image, and the plane's axes and extent
    (horizontal, vertical; set by ``fill``). Colour bars are shared only by planes with the same physical units."""
    label: Any
    plot: Any
    image: Any
    dots: Any = None  # a ScatterPlotItem (Draw › dots)
    axes: tuple[str, str] = ("X", "Y")
    extent: tuple[tuple[float, float], tuple[float, float]] = ((0.0, 1.0), (0.0, 1.0))


FIT_MARGIN = 1.04  # The fitted view's margin around the images.


def middle(span: Sequence[float]) -> float:
    return (float(span[0]) + float(span[1])) / 2


class SpaceScale(QObject):
    """Keeps one scale (metres per pixel) on every space axis of a PyQtGraph drawing, each plane's horizontal axis
    and XY's vertical one, with X shared by XY and XT and Y by XY and YT; and T alike in XT and YT. Until the user
    zooms or pans, the views fit the images at that scale (again as Live adds shots or the plot is resized); after,
    the other views follow the one changed. Settled after the event (a zoom's range change comes before PyQtGraph
    says it was the user's), so a child of the drawing whose timer goes with it."""

    def __init__(self, widget: QWidget, panels: Sequence[PlanePanel]) -> None:
        super().__init__(widget)
        self.panels = list(panels)
        self.zoomed = False
        self.busy = False
        self.last: Optional[PlanePanel] = None  # the view the user last zoomed or panned
        self.changing: Optional[PlanePanel] = None  # the view whose range changed last, for ``manual``
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.settle)
        for panel in self.panels:
            box = panel.plot.getViewBox()
            box.disableAutoRange()
            box.sigRangeChanged.connect(self.changed)
            box.sigResized.connect(self.changed)
            box.sigRangeChangedManually.connect(self.manual)

    def panel_of(self, box: Any) -> Optional[PlanePanel]:
        return next((panel for panel in self.panels if panel.plot.getViewBox() is box), None)

    def changed(self, box: Any, *args: Any) -> None:
        if self.busy:
            return
        self.changing = self.panel_of(box) or self.changing
        self.schedule()

    def manual(self, *args: Any) -> None:
        """The user's zoom or pan, said by PyQtGraph right after that view's range changed: it leads from now on
        (a later change of another view's, e.g. on a resize, doesn't)."""
        self.zoomed = True
        self.last = self.changing or self.last
        self.schedule()

    def schedule(self) -> None:
        if not self.timer.isActive():
            self.timer.start(0)

    def settle(self) -> None:
        if self.zoomed and self.last is not None:
            self.follow(self.last)
        else:
            self.fit()

    def sizes(self) -> Optional[list[tuple[float, float]]]:
        sizes = [(float(panel.plot.getViewBox().width()), float(panel.plot.getViewBox().height()))
                 for panel in self.panels]
        return sizes if all(width > 1 and height > 1 for width, height in sizes) else None  # Laid out yet?

    def apply(self, ranges: Sequence[tuple[tuple[float, float], tuple[float, float]]]) -> None:
        self.busy = True
        try:
            for panel, (across, up) in zip(self.panels, ranges):
                panel.plot.getViewBox().setRange(xRange=across, yRange=up, padding=0)
        finally:
            self.busy = False

    def fit(self) -> None:
        """Every image in view at the one scale that fits the most cramped of them."""
        sizes = self.sizes()
        if sizes is None:
            return
        needed = []
        times: list[float] = []
        for panel, (width, height) in zip(self.panels, sizes):
            (h0, h1), (v0, v1) = panel.extent
            needed.append((h1 - h0) / width)
            if panel.axes[1] == "T":
                times += [v0, v1]
            else:
                needed.append((v1 - v0) / height)
        scale = max(max(needed), 1e-12) * FIT_MARGIN
        time = (0.0, 1.0)
        if times:
            pad = (max(times) - min(times)) * (FIT_MARGIN - 1) / 2 or 1e-6
            time = (min(times) - pad, max(times) + pad)
        ranges = []
        for panel, (width, height) in zip(self.panels, sizes):
            across, up = panel.extent
            centre = middle(across)
            vertical = (time if panel.axes[1] == "T" else
                        (middle(up) - scale * height / 2, middle(up) + scale * height / 2))
            ranges.append(((centre - scale * width / 2, centre + scale * width / 2), vertical))
        self.apply(ranges)

    def follow(self, source: PlanePanel) -> None:
        """The other views at ``source``'s scale, centred where it shows a shared axis, T as it shows T."""
        sizes = self.sizes()
        if sizes is None:
            return
        box = source.plot.getViewBox()
        (x0, x1), (y0, y1) = box.viewRange()
        scale = (x1 - x0) / float(box.width())
        centres = {source.axes[0]: middle((x0, x1))}
        time: Optional[tuple[float, float]] = None
        if source.axes[1] == "T":
            time = (y0, y1)
        else:
            centres[source.axes[1]] = middle((y0, y1))
        ranges = []
        for panel, (width, height) in zip(self.panels, sizes):
            if panel is source:
                ranges.append(((x0, x1), (y0, y1)))
                continue
            across, up = panel.plot.getViewBox().viewRange()
            centre = centres.get(panel.axes[0], middle(across))
            if panel.axes[1] == "T":
                vertical = time or (float(up[0]), float(up[1]))
            else:
                mid = centres.get(panel.axes[1], middle(up))
                vertical = (mid - scale * height / 2, mid + scale * height / 2)
            ranges.append(((centre - scale * width / 2, centre + scale * width / 2), vertical))
        self.apply(ranges)


class PlaneHistograms(DatasetAnalysis):
    """The XY, XT and YT histograms in one plot, each plane turned on or off under Planes."""

    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="XY, XT, YT histograms",
            description="The loaded events binned in the XY, XT and YT planes, the third axis summed over the "
                        "chosen shots",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.v2.plane_histograms",
            version="1",
        )

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [*SHOT_SPECS, *SHOW.values(), *RANGE, OUTSIDE, DRAW, DOT_COLOUR, MAX_DOTS, BACKGROUND,
                *BINS.values(), DRAW_AT, QUANTITY,
                *BLUR_SPECS, SCALE, GAMMA, DECADES]

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        planes = shown_planes(values)
        used = [axis for axis in AXES if any(axis in PLANES[plane][:2] for plane in planes)]
        bins = {axis: int(values[BINS[axis].name]) for axis in used}
        bins_part = ("bins auto" if not any(bins.values())
                     else "bins " + ", ".join(f"{axis} {count or 'auto'}" for axis, count in bins.items()))
        colours = Colours.of(values)
        summed = "/".join(PLANES[plane][2] for plane in planes)
        dots = (f"dots, {values.get(DOT_COLOUR.name, DENSITY)}" if values.get(DOT_COLOUR.name) != NO_COLOUR
                else "dots") if values.get(DRAW.name) == DOTS else ""
        dots += " on black" if dots and background(values) == BLACK else ""
        settings = (", ".join(planes) if len(planes) < len(PLANES) else "", shots_brief(values),
                    range_brief(values), f"whole {summed}" if manual(values) and values.get(OUTSIDE.name) else "",
                    dots, bins_part, "" if at_screen(values) else "every bin drawn", blur_brief(values),
                    "per shot" if values.get(QUANTITY.name) == PER_SHOT else "",
                    f"colours {colours.text()}" if colours.text() else "")
        return selection_text(view, values), " · ".join(part for part in settings if part)

    def parameter_warnings(self, action_name: str, values: Mapping[str, Any]) -> List[str]:
        planes = [] if shown_planes(values) else ["No plane is on: turn on XY, XT or YT under Planes"]
        return [*planes, *range_warnings(values)]

    def minimum_size(self, action_name: str) -> tuple[int, int]:
        return 480, 280  # Up to three images side by side, one colour bar, under a title.

    def estimated_bytes(self, action_name: str, values: Mapping[str, Any]) -> int:
        """The planes on, at their set bins, an automatic axis counted at its most (``MAX_AUTO_BINS``); drawn at
        screen resolution or every bin (Draw at, Q~1)."""
        bins = {axis: min(int(values.get(BINS[axis].name, 0)), MAX_BINS) or MAX_AUTO_BINS for axis in AXES}
        shapes = [(bins[PLANES[plane][0]], bins[PLANES[plane][1]]) for plane in shown_planes(values)]
        return estimated_bytes([across * up for across, up in shapes], bool(values.get(f"blur_{image_filters.ADAPTIVE}")),
                               drawn_cells(values, shapes), any(values.get(f"blur_{kind}") for kind in image_filters.FILTERS))

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        values = context.parameters
        shots = select_shots(context.view, values)
        events = context.view.events(shots)
        items = []
        for plane in shown_planes(values):
            context.check()
            items.append(plane_counts(events, plane, values, len(shots), context.check))
        warnings = tuple(f"{axis}: min > max, using full extent" for axis in reversed_axes(values))
        # The memory its bins take (as they came out: automatic ones known now), against the RAM budget.
        shapes = [(int(item.histogram.counts.shape[0]), int(item.histogram.counts.shape[1])) for item in items]
        estimate = estimated_bytes([item.histogram.counts.size for item in items],
                                   bool(values.get(f"blur_{image_filters.ADAPTIVE}")), drawn_cells(values, shapes),
                                   any(values.get(f"blur_{kind}") for kind in image_filters.FILTERS))
        if estimate_over(estimate, context.ram_budget):
            warnings += (estimate_text(estimate, context.ram_budget),)
        return Planes(tuple(items), shots, len(context.view.shots), warnings)

    def describe_result(self, action_name: str, result: AnalysisResult) -> str:
        """The memory warning, for the dock's settings line and Plot info."""
        data = result.data
        notes = data.notes if isinstance(data, Planes) else ()
        return " · ".join(f"⚠ {note}" for note in notes if note.startswith(ESTIMATE_PREFIX))

    def backends(self, action_name: str) -> Sequence[str]:
        return (PYQTGRAPH, PLOTLY, MATPLOTLIB)

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        return self.draw(result, PYQTGRAPH, parent)

    def draw(self, result: AnalysisResult, backend: str, parent: Optional[QWidget] = None) -> QWidget:
        why = nothing_text(result.data)
        if why:
            return empty_pane(why, parent)
        if backend == PLOTLY:
            return PlotlyPane(planes_plotly(result), parent=parent)
        if backend == MATPLOTLIB:
            return MatplotlibPane(planes_matplotlib(result), parent)
        data: Planes = result.data
        colours = Colours.of(result.parameters)
        widget: Any = pg.GraphicsLayoutWidget(parent)
        widget.setBackground("w")
        widget.title_label = WrappingLabel("")
        count = len(data.items)
        groups = colour_groups(data)
        left = int(any(left_colour_bar(group) for group in groups))
        widget.addItem(widget.title_label, row=0, col=0, colspan=count + len(colour_groups(data)))
        panels = []
        for column, item in enumerate(data.items, start=left):
            across, up, _ = item.histogram.axes
            label = WrappingLabel("")
            widget.addItem(label, row=1, col=column)
            plot = widget.addPlot(row=2, col=column)
            plot.setLabel("bottom", across, units=UNITS[AXES.index(across)])
            plot.setLabel("left", up, units=UNITS[AXES.index(up)])
            if item.histogram.plane == "XY":
                plot.setAspectLocked(True)  # Both lengths: equal scales.
            # image[across, up], as the counts are; drawn from each bin's compressed colour position over plain
            # viridis (exact at any depth), the bar a legend in real values, never attached to the images.
            # (At screen resolution PyQtGraph also averages what the screen can't show: autoDownsample, Q~1.)
            image = pg.ImageItem(axisOrder="col-major", autoDownsample=at_screen(result.parameters))
            image.setLookupTable(viridis().getLookupTable(nPts=LUT_SIZE, alpha=False))
            plot.addItem(image)
            dots = None
            if item.dots is not None:
                image.setVisible(False)
                dots = pg.ScatterPlotItem(pxMode=True, size=DOT_SIZE, symbol="s", pen=None)
                plot.addItem(dots)
            plot.hideButtons()  # (Its auto-range button would break the shared scale.)
            panels.append(PlanePanel(label, plot, image, dots))
        groups = colour_groups(data)
        split = len(groups) > 1
        if split:
            widget.setMinimumSize(640, 360)  # Leave room for both numerical axes and the images.
        widget.plane_bars = []
        widget.bar_labels = []
        for index, group_data in enumerate(groups):
            bar: Any = pg.ColorBarItem(values=(0.0, 1.0), colorMap=bar_map(bar_colours(data, colours)),
                                  width=BAR_WIDTH, interactive=False, colorMapMenu=False)
            on_left = left_colour_bar(group_data)
            side = "left" if on_left else "right"
            other = bar.getAxis("right" if on_left else "left")
            other.setStyle(showValues=False)
            other.setTicks([])
            other.setWidth(0)
            axis = InsideColourAxis(side)
            bar.setAxisItems({side: axis})
            axis.unlinkFromView()  # setAxisItems links it; ticks must keep the physical value range.
            bar.axis = axis
            bar_column = 0 if on_left else count + left
            bar.inset_column = bar_column
            if split:
                unit = "mm²" if group_data.items[0].histogram.plane == "XY" else "mm·ms"
                heading = "/".join(item.histogram.plane for item in group_data.items)
                label = WrappingLabel(f"{heading}<br>{unit}", size="7.5pt")
                document = label.item.document()
                if document is not None:
                    document.setDocumentMargin(0)
                widget.addItem(label, row=1, col=bar_column)
                widget.bar_labels.append(label)
            widget.addItem(bar, row=2, col=bar_column)
            widget.ci.layout.setColumnFixedWidth(bar_column, max(40, BAR_WIDTH + 4))
            bar.setVisible(data.dot_colour != NO_COLOUR)
            widget.plane_bars.append(bar)
        widget.plane_bar = widget.plane_bars[0]
        widget.legend_label = WrappingLabel("")
        widget.addItem(widget.legend_label, row=3, col=0, colspan=count + len(groups))
        widget.plane_panels = panels
        widget.plane_layout = planes_layout(result)
        widget.plane_scale = SpaceScale(widget, panels)
        fill(widget, result)
        return cast(QWidget, widget)

    def update(self, widget: QWidget, result: AnalysisResult) -> bool:
        """A rerun (e.g. Live's next shots) updates the images in place, in every library: a zoom or pan stays,
        else the axes follow the new ranges. Another colour scale or set of planes draws it anew in PyQtGraph."""
        if nothing_text(result.data):
            return False
        if isinstance(widget, pg.GraphicsLayoutWidget):
            if getattr(widget, "plane_layout", None) != planes_layout(result):
                return False
            fill(cast(Any, widget), result)
            return True
        return (plotly_update(widget, planes_plotly(result))
                or matplotlib_update(widget, lambda figure: planes_matplotlib(result, figure)))


def drawn_cells(values: Mapping[str, Any], shapes: Sequence[tuple[int, int]]) -> list[int]:
    """Each plane's cells drawn: every bin, or at screen resolution (Draw at, Q~1). Dots count every bin, as
    before: their local density reads the whole image."""
    if values.get(DRAW.name) == DOTS or not at_screen(values):
        return [across * up for across, up in shapes]
    return [rows * columns for rows, columns in (display_shape(shape) for shape in shapes)]


def nothing_text(data: Planes) -> str:
    """Why there is nothing to draw ("" when there is)."""
    if not data.items:
        return "No plane is on: turn on XY, XT or YT under Planes"
    first = data.items[0].histogram
    return (empty_text(data.total_shots, len(data.shots), first.total)
            or ("" if any(item.histogram.summed for item in data.items)
                else "No events inside the summed axis's bounds (View range)"))


def planes_layout(result: AnalysisResult
                  ) -> tuple[tuple[str, ...], Colours, str, tuple[tuple[str, ...], ...], tuple[bool, ...], bool]:
    """The planes, colour transform, dot colouring, unit groups, colour bar sides (left for XY's rate) and whether
    at screen resolution (its images' ``autoDownsample``) a PyQtGraph drawing was built for."""
    data: Planes = result.data
    groups = colour_groups(data)
    return (tuple(item.histogram.plane for item in data.items), Colours.of(result.parameters), data.dot_colour,
            tuple(tuple(item.histogram.plane for item in group.items) for group in groups),
            tuple(left_colour_bar(group) for group in groups), at_screen(result.parameters))


def dot_brushes(item: PlaneCounts, data: Planes, colours: Colours, area: str = WHITE,
                picked: Optional[npt.NDArray[np.intp]] = None) -> Any:
    """The dots' brushes in PyQtGraph: viridis at each one's colour position (in ``LUT_SIZE`` steps), or one
    tint for the ``area``'s background. ``picked``: the dots drawn (default all)."""
    if data.dot_colour == NO_COLOUR:
        return pg.mkBrush(*DOT_TINTS[area])
    table = [pg.mkBrush(*colour) for colour in viridis().getLookupTable(nPts=LUT_SIZE, alpha=False)]
    positions = dot_positions(item, data, colours)
    steps = np.rint((positions if picked is None else positions[picked]) * (LUT_SIZE - 1)).astype(np.intp)
    return [table[step] for step in steps]


def panel_title(item: PlaneCounts, screen: bool = False) -> str:
    return f"<b>{item.histogram.plane}</b> · {plane_title(item, dots_note(item, screen))}{notes_html(notes(item))}"


def fill(widget: Any, result: AnalysisResult) -> None:
    data: Planes = result.data
    colours = Colours.of(result.parameters)
    area = background(result.parameters)
    screen = at_screen(result.parameters)
    widget.title_label.setText(planes_title(data) + notes_html([f"⚠ {note}" for note in data.notes]))
    for panel, item in zip(widget.plane_panels, data.items):
        histogram = item.histogram
        panel.label.setText(panel_title(item, screen))
        panel.plot.getViewBox().setBackgroundColor(AREA_COLOURS[area] if area == BLACK else None)
        if item.dots is not None and panel.dots is not None:
            picked = dot_pick(item, screen)
            panel.dots.setData(x=item.dots.h[picked], y=item.dots.v[picked],
                               brush=dot_brushes(item, data, colours, area, picked))
        else:
            panel.image.setImage(colour_positions(item, colours, colour_group(data, item).peak), levels=(0.0, 1.0))
        h0, h1 = float(histogram.h_edges[0]), float(histogram.h_edges[-1])
        v0, v1 = float(histogram.v_edges[0]), float(histogram.v_edges[-1])
        panel.image.setRect(QRectF(h0, v0, h1 - h0, v1 - v0))
        panel.axes = (histogram.axes[0], histogram.axes[1])
        panel.extent = ((h0, h1), (v0, v1))
    groups = colour_groups(data)
    for bar, group_data in zip(widget.plane_bars, groups):
        low, high = group_data.bar_range
        width = bar.axis.fit_labels(low, high)
        bar.layout.setColumnFixedWidth(1, width)
        widget.ci.layout.setColumnFixedWidth(bar.inset_column, max(40, width + 4))
        bar.setLevels((low, high))
    widget.legend_label.setText(bar_label(data, colours))
    widget.legend_label.setVisible(data.dot_colour != NO_COLOUR)
    widget.plane_scale.schedule()  # Fitted to the new images unless zoomed.


def colour_stops(colours: Colours, stops: int = LUT_SIZE) -> npt.NDArray[np.float64]:
    """Sample evenly in colour space, retaining faint logarithmic and power-law values."""
    positions = np.linspace(0.0, 1.0, stops)
    if colours.scale == LOG:
        return np.concatenate(([0.0], 10.0 ** ((positions - 1.0) * colours.decades)))
    if colours.scale != LINEAR:
        exponent = colours.gamma if colours.scale == POWER else 0.5
        return positions ** (1.0 / exponent)
    return positions


def plotly_scale(colours: Colours, stops: int = LUT_SIZE) -> list[list[Any]]:
    """A Plotly colour scale over the bar's linear range showing each value's compressed colour."""
    from plotly.colors import sample_colorscale

    positions = colour_stops(colours, stops)
    picked = sample_colorscale("Viridis", compress(positions, colours.scale, colours.gamma, colours.decades).tolist())
    return [[float(position), colour] for position, colour in zip(positions, picked)]


def axis_suffix(column: int) -> str:
    """Plotly's name suffix for a subplot's axes ("" for the first, then "2", "3")."""
    return "" if column == 1 else str(column)


def plotly_image(item: PlaneCounts, screen: bool) -> tuple[npt.NDArray[np.floating[Any]], Optional[Display]]:
    """The image Plotly draws and how it was reduced (None: every bin): at screen resolution at most
    ``PLOTLY_SIDE`` a side (its JSON grows with every cell), from the worker's display image; else every bin."""
    if not screen:
        return item.image, None
    source = item.display
    image = source.image if source is not None else item.image
    h_edges = source.h_edges if source is not None else item.histogram.h_edges
    v_edges = source.v_edges if source is not None else item.histogram.v_edges
    further = display_of(image, h_edges, v_edges, PLOTLY_SIDE)
    if further is None:
        return image, source
    if source is None:
        return further.image, further
    factors = (source.factors[0] * further.factors[0], source.factors[1] * further.factors[1])
    return further.image, Display(further.image, further.h_edges, further.v_edges, factors)


def planes_plotly(result: AnalysisResult) -> go.Figure:
    """The planes side by side, with a separate colour axis for each physical quantity."""
    from plotly.subplots import make_subplots

    data: Planes = result.data
    colours = Colours.of(result.parameters)
    count = len(data.items)
    screen = at_screen(result.parameters)
    drawn = [plotly_image(item, screen) for item in data.items]
    titles = [f"{item.histogram.plane} · {plane_title(item, display_note(display) if display is not None else '')}"
              + "".join(f" · {note}" for note in notes(item)) for item, (_, display) in zip(data.items, drawn)]
    figure = make_subplots(rows=1, cols=count, subplot_titles=titles,
                           horizontal_spacing=0.07 if count > 1 else 0.02)
    time_axis: Optional[str] = None
    area = background(result.parameters)
    tint = DOT_TINTS[area]
    groups = colour_groups(data)
    for column, (item, (image, display)) in enumerate(zip(data.items, drawn), start=1):
        histogram = item.histogram
        across, up, _ = histogram.axes
        group_index = next(index for index, group in enumerate(groups)
                           if any(candidate is item for candidate in group.items))
        colour_axis = "coloraxis" + (str(group_index + 1) if group_index else "")
        h_edges, v_edges = ((display.h_edges, display.v_edges) if display is not None
                            else (histogram.h_edges, histogram.v_edges))
        centres_h = (h_edges[:-1] + h_edges[1:]) / 2
        centres_v = (v_edges[:-1] + v_edges[1:]) / 2
        if item.dots is not None:
            coloured = data.dot_colour != NO_COLOUR
            marker = (dict(size=DOT_SIZE, color=dot_values(item, data), coloraxis=colour_axis) if coloured
                      else dict(size=DOT_SIZE, color="rgba({}, {}, {}, {})".format(*tint[:3], tint[3] / 255)))
            figure.add_trace(go.Scattergl(
                x=item.dots.h, y=item.dots.v, mode="markers", marker=marker, name=histogram.plane, showlegend=False,
                hovertemplate=f"{across} %{{x:.6g}}<br>{up} %{{y:.6g}}" + ("<br>%{marker.color:.4g}" if coloured
                                                                             else "")
                              + f"<extra>{histogram.plane}</extra>"), row=1, col=column)
        elif display is None:
            figure.add_trace(go.Heatmap(
                z=image.T, x=centres_h, y=centres_v, coloraxis=colour_axis, customdata=histogram.counts.T,
                name=histogram.plane,
                hovertemplate=f"{across} %{{x:.6g}}<br>{up} %{{y:.6g}}<br>%{{customdata:,}} events · %{{z:.4g}}"
                              f"<extra>{histogram.plane}</extra>"), row=1, col=column)
        else:  # (A block's mean: no one bin's events to show.)
            blocks = f"{cell_bins(display.factors[0])} × {cell_bins(display.factors[1])} bins"
            figure.add_trace(go.Heatmap(
                z=image.T, x=centres_h, y=centres_v, coloraxis=colour_axis, name=histogram.plane,
                hovertemplate=f"{across} %{{x:.6g}}<br>{up} %{{y:.6g}}<br>%{{z:.4g}} (the mean of {blocks})"
                              f"<extra>{histogram.plane}</extra>"), row=1, col=column)
        figure.update_xaxes(title_text=axis_label(across), row=1, col=column)
        figure.update_yaxes(title_text=axis_label(up), row=1, col=column)
        # Every space axis at the first plane's horizontal scale (each plane has one across; XY's Y too), and T
        # the same in XT and YT.
        if column > 1:
            figure.update_xaxes(scaleanchor="x", scaleratio=1, row=1, col=column)
        if up != "T":
            figure.update_yaxes(scaleanchor="x", scaleratio=1, row=1, col=column)
        elif time_axis is None:
            time_axis = f"y{axis_suffix(column)}"
        else:
            figure.update_yaxes(matches=time_axis, row=1, col=column)
    figure.update_annotations(font_size=10)
    if area == BLACK:
        figure.update_xaxes(gridcolor=DARK_GRID, zerolinecolor=DARK_GRID)
        figure.update_yaxes(gridcolor=DARK_GRID, zerolinecolor=DARK_GRID)
    split = len(groups) > 1
    axes = {}
    for index, group_data in enumerate(groups):
        low, high = group_data.bar_range
        label = (group_label(group_data, colours) if split else bar_label(group_data, colours))
        label = label.replace(" · ", "<br>").replace(": ", "<br>")
        on_left = left_colour_bar(group_data)
        bar: dict[str, Any] = dict(title=dict(text=label, side="right"),
                                   thickness=24, ticks="inside", ticklabelposition="inside", tickcolor="black",
                                   tickfont=dict(size=9, color="black", shadow="auto"),
                                   x=-0.12 if on_left else 1.04, xanchor="right" if on_left else "left")
        name = "coloraxis" + (str(index + 1) if index else "")
        axes[name] = dict(colorscale=plotly_scale(bar_colours(data, colours)), cmin=low, cmax=high,
                          showscale=data.dot_colour != NO_COLOUR, colorbar=bar)
    figure.update_layout(title=dict(text=plain_title(result), x=0.01, font=dict(size=13)), template="plotly_white",
                         margin=dict(l=160 if any(left_colour_bar(group) for group in groups) else 60,
                                     r=160, t=80, b=50),
                         uirevision="helab.v2.plane_histograms", plot_bgcolor=AREA_COLOURS[area], **axes)
    return figure


def matplotlib_norm(colours: Colours, peak: float) -> Any:
    """The colour scale as a Matplotlib norm over 0…peak."""
    from matplotlib import colors as typed_colors

    mpl_colors: Any = typed_colors  # (Its classes are untyped.)
    if colours.scale == LOG:
        return mpl_colors.LogNorm(vmin=peak * 10.0 ** -colours.decades, vmax=peak, clip=True)
    if colours.scale == LINEAR:
        return mpl_colors.Normalize(vmin=0.0, vmax=peak)
    return mpl_colors.PowerNorm(0.5 if colours.scale != POWER else colours.gamma, vmin=0.0, vmax=peak, clip=True)


def inset_matplotlib_ticks(colourbar: Any, on_left: bool) -> None:
    """Keep major and minor numbers inside a gradient wide enough for their actual text."""
    from matplotlib.transforms import Bbox

    axes = colourbar.ax
    original_locator = axes.get_axes_locator()
    axes.set_box_aspect(None)
    axes.tick_params(which="both", direction="in", pad=-3, labelsize=7)

    def locate(target: Any, renderer: Any) -> Any:
        bounds = (original_locator(target, renderer) if original_locator is not None
                  else target.get_position(original=True))
        # Constrained layout reapplies the default box aspect before each locator call.
        target.set_box_aspect(None)
        labels = target.get_yticklabels(which="both")
        for text in labels:
            text.set_horizontalalignment("left" if on_left else "right")
            text.set_bbox(dict(facecolor="white", alpha=0.85, edgecolor="none", pad=1))
        pixels = max((text.get_window_extent(renderer).width for text in labels if text.get_visible()), default=0)
        width = max(24.0, pixels + 8.0) / target.figure.bbox.width
        return Bbox.from_bounds(bounds.x1 - width if on_left else bounds.x0, bounds.y0, width, bounds.height)

    axes.set_axes_locator(locate)


def planes_matplotlib(result: AnalysisResult, figure: Any = None) -> Any:
    from matplotlib import colormaps

    data: Planes = result.data
    colours = Colours.of(result.parameters)
    cmap = colormaps[COLOUR_MAP].with_extremes(bad=colormaps[COLOUR_MAP](0.0), under=colormaps[COLOUR_MAP](0.0))
    figure = mpl_figure(figure)
    panes = list(figure.subplots(1, len(data.items), squeeze=False)[0])
    span = max([float(np.ptp(item.histogram.h_edges)) for item in data.items]
               + [float(np.ptp(item.histogram.v_edges)) for item in data.items if item.histogram.axes[1] != "T"])
    timed = [axes for axes, item in zip(panes, data.items) if item.histogram.axes[1] == "T"]
    for axes in timed[1:]:
        axes.sharey(timed[0])  # T the same in XT and YT.
    groups = colour_groups(data)
    norms: list[Any] = []
    for group_data in groups:
        if data.dot_colour == SUMMED:
            from matplotlib import colors as typed_colors

            norms.append(cast(Any, typed_colors).Normalize(*group_data.bar_range))
        else:
            norms.append(matplotlib_norm(colours, group_data.top))
    meshes: dict[int, Any] = {}
    area = background(result.parameters)
    screen = at_screen(result.parameters)
    for axes, item in zip(panes, data.items):
        group_index = next(index for index, group in enumerate(groups)
                           if any(candidate is item for candidate in group.items))
        norm = norms[group_index]
        mesh: Any = None
        histogram = item.histogram
        across, up, _ = histogram.axes
        axes.set_facecolor(AREA_COLOURS[area])
        drawn: Optional[str] = None
        if item.dots is not None:
            picked = dot_pick(item, screen)
            drawn = dots_note(item, screen)
            if data.dot_colour == NO_COLOUR:
                axes.scatter(item.dots.h[picked], item.dots.v[picked], s=DOT_SIZE / 2, marker="s", linewidths=0,
                             rasterized=True, color=tuple(channel / 255 for channel in DOT_TINTS[area]))
            else:
                mesh = axes.scatter(item.dots.h[picked], item.dots.v[picked], c=dot_values(item, data)[picked],
                                    s=DOT_SIZE / 2, marker="s", linewidths=0, rasterized=True, cmap=cmap, norm=norm)
        else:
            image = item.shown.T
            shown = np.where(image > 0, image, np.nan) if colours.scale == LOG else image
            if screen:
                # One raster at screen resolution (Q~1: pcolormesh drew a quad a bin, 1.9 s at 4,000²); the bins are
                # regular, so it is the same picture where the screen shows every cell.
                h_edges, v_edges = ((item.display.h_edges, item.display.v_edges) if item.display is not None
                                    else (histogram.h_edges, histogram.v_edges))
                mesh = axes.imshow(shown, origin="lower", extent=(h_edges[0], h_edges[-1], v_edges[0], v_edges[-1]),
                                   aspect="auto", interpolation="nearest", cmap=cmap, norm=norm)
                drawn = display_note(item.display) if item.display is not None else None
            else:
                mesh = axes.pcolormesh(histogram.h_edges, histogram.v_edges, shown, cmap=cmap,
                                       norm=norm, shading="flat")
        if mesh is not None:
            meshes[group_index] = mesh
        axes.set_title(histogram.plane + (f" · {drawn}" if drawn else ""), fontsize=9)
        axes.set_xlabel(axis_label(across), fontsize=8)
        axes.set_ylabel(axis_label(up), fontsize=8)
        axes.tick_params(labelsize=7)
        # The same span on every space axis (equal widths: the same scale across); XY at equal scales.
        centre = middle((histogram.h_edges[0], histogram.h_edges[-1]))
        axes.set_xlim(centre - span / 2, centre + span / 2)
        if histogram.plane == "XY":
            mid = middle((histogram.v_edges[0], histogram.v_edges[-1]))
            axes.set_ylim(mid - span / 2, mid + span / 2)
            axes.set_aspect("equal", adjustable="datalim")
    for group_index, mesh in meshes.items():
        group_data = groups[group_index]
        group_axes = [axes for axes, item in zip(panes, data.items)
                      if any(candidate is item for candidate in group_data.items)]
        label = (group_label(group_data, colours) if len(groups) > 1 else bar_label(data, colours))
        label = label.replace(" · ", "\n").replace(": ", "\n")
        on_left = left_colour_bar(group_data)
        colourbar = figure.colorbar(mesh, ax=group_axes, label=label, aspect=12, pad=0.03,
                                   location="left" if on_left else "right")
        inset_matplotlib_ticks(colourbar, on_left)
    figure.suptitle(plain_title(result), fontsize=9, wrap=True)
    return figure
