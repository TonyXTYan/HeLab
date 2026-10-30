"""2D density images of a loaded folder's events: XY, XT or YT (PyQtGraph ``ImageItem`` with a
colour bar), ported from the DLD front panel's 2D Plot (``dld_2dplotter_window_a.m``).

The events in the view range (a box over T, X and Y: auto-crop or manual bounds, so the
third axis acts as a window) are binned with ``np.histogram2d``, optionally blurred with a
Gaussian (σ in bins; the total is kept) and shown as counts per bin or as a rate per shot
(counts / shots / bin area). Range compression (sqrt, log, power) is in the colour map only:
the image stays linear and the colour bar reads real values. X and Y are shown in mm, T in
ms (``display_units``). Unlike the old GUI: no X/Y rotation, the bin
area divides by the real bin count, and an empty range says so instead of crashing.

The Mask group (D9, ``masks``) keeps or cuts events in XY circles before anything else; the XY
projection draws its circles (dashed: keep white, cut red). The second action, **Find hot
spots** (D15's placeholder, ``hotspots``), shows the summed XY image with the bins far above its
median grouped into circles (dashed amber), lists them in the record and offers them to copy
into a plot's custom Mask: it never applies them."""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, List, Mapping, Optional, cast

import numpy as np
import numpy.typing as npt
import pyqtgraph as pg
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtWidgets import QApplication, QGraphicsEllipseItem, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from scipy.ndimage import gaussian_filter

from helab.analysis.dataset_view import DatasetView, Events
from helab.analysis.display_units import (LENGTH_UNIT, T_UNIT, WIDTH_DIGITS, axis_label, axis_scale, axis_text,
                                         axis_unit)
from helab.analysis.empty import empty_pane, empty_text
from helab.analysis.follow import LivePolicy
from helab.analysis.hotspots import (DEFAULT_ALPHA, DEFAULT_BIN, DEFAULT_MIN_EXCESS, DEFAULT_SCALE, HotSpotSearch,
                                     find_hot_spots, plural, search_lines)
from helab.analysis.masks import (MASK_SPECS, Circle, Mask, all_masked_text, mask_brief, mask_from, mask_warnings,
                                  masked_text)
from helab.analysis.parameters import ParameterSpec
from helab.analysis.plot_axes import GroupedAxis
from helab.analysis.plot_text import add_label, lines_html
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.analysis.selection import (SHOT_SPECS, keep_fraction, keep_spec, manual, manual_box, newest_brief,
                                      newest_colour, newest_events, newest_shot, newest_specs, range_brief,
                                      range_specs, range_warnings, select_shots, selection_text, shots_brief,
                                      shots_text)
from helab.analysis.stats import AXES, CropBox, crop_box, freedman_diaconis_bins
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.dld import group
from helab.utils.colours import AMBER
from helab.utils.accessible import identify

# Projections: (horizontal axis, vertical axis) as T/X/Y column indices. T runs along the
# horizontal axis of XT and YT, as time does in a plot.
PROJECTIONS = {"XY": (1, 2), "XT": (0, 1), "YT": (0, 2)}
PROJECTION = ParameterSpec("projection", "Projection", "choice", "XY", choices=tuple(PROJECTIONS),
                           tip="XY: the detector's plane (X across, Y up). XT and YT: X or Y against T "
                               "(T across). The view range's third axis selects the events shown (a window).")
RANGE = range_specs(
    "The image covers a box over T, X and Y holding at least this share of the events, found as the 3D "
    "scatter finds its crop (a heuristic, not the narrowest box). Its third axis is a window: events "
    "outside it are left out. 100 % covers every event.", fixed=True)
IMAGE_GROUP = "Image"
MAX_IMAGE_BINS = 1000  # per axis: 1000 × 1000 float64 is 8 MB
AUTO_BINS_CAP = 400  # automatic bins per axis stop here (Freedman–Diaconis grows with the events)
BINS = ParameterSpec(
    "bins", "Bins per axis (0 = auto)", "int", 0, (0, MAX_IMAGE_BINS), group=IMAGE_GROUP,
    tip=f"Bins along each axis of the image. 0 = automatic, per axis (Freedman–Diaconis: width "
        f"2·IQR·n^-1/3, at most {AUTO_BINS_CAP}).")
BLUR = ParameterSpec("blur", "Blur σ", "float", 0.0, (0.0, 50.0), " bins", group=IMAGE_GROUP,
                     tip="Gaussian blur of the image, its σ in bins; 0 = off. The total is kept (edges reflect). "
                         "At most a quarter of the image's longer side is used (the plot says so).")
COUNTS, PER_SHOT = "counts per bin", "rate per shot"
QUANTITY = ParameterSpec("quantity", "Show", "choice", COUNTS, choices=(COUNTS, PER_SHOT), group=IMAGE_GROUP,
                         tip="Counts per bin, or a rate per shot: counts / number of shots chosen / bin area "
                             "(per mm² for XY; per mm per ms for XT and YT).")
COLOUR_GROUP = "Colour"
LINEAR, SQRT, LOG, POWER = "linear", "sqrt", "log", "power γ"
SCALE = ParameterSpec("colour_scale", "Colour scale", "choice", LINEAR, choices=(LINEAR, SQRT, LOG, POWER),
                      group=COLOUR_GROUP,
                      tip="Compresses the colour range only: the image's values stay linear and the colour bar "
                          "reads them. sqrt brings out faint regions (the old GUI's \"LogScale\"); log spans "
                          "the decades below; power uses γ.")
GAMMA = ParameterSpec("gamma", "γ", "float", 0.5, (0.05, 5.0), group=COLOUR_GROUP, when=(SCALE.name, POWER),
                      tip="Colour position = value^γ (of the colour bar's range): below 1 brings out faint "
                          "regions, above 1 the bright ones.")
DECADES = ParameterSpec("log_decades", "Decades", "int", 3, (1, 8), group=COLOUR_GROUP, when=(SCALE.name, LOG),
                        tip="How many decades below the maximum the colours span; lower values share the "
                            "darkest colour.")
HIGHLIGHT, NEWEST_COLOUR = newest_specs(IMAGE_GROUP)
NEWEST_BLUR = 2.0  # the newest shot's contour: its image blurred at least this many bins
COLOUR_MAP = "viridis"
LUT_SIZE = 1024  # colour map samples: fine enough for the steepest compression near 0
# The mask's circles on XY (dashed) and the circles Find hot spots offers.
KEEP_COLOUR, CUT_COLOUR, FOUND_COLOUR = (255, 255, 255), (255, 60, 60), AMBER

# Find hot spots (D15's placeholder): its own settings, the view range keeping every event by default.
PLOT, FIND = "Plot", "Find hot spots"
FIND_GROUP = "Find hot spots"
FIND_RANGE = tuple(replace(spec, default=100.0) if spec.name == keep_spec("").name else spec for spec in range_specs(
    "The image covers a box over T, X and Y holding at least this share of the events. 100 % (the default here) "
    "keeps every event, so spots near the detector's edge stay in. Set T by hand to a window without atoms: "
    "a cloud is bright too.", fixed=True))
FIND_BIN = ParameterSpec("spot_bin", "Bin width", "float", DEFAULT_BIN, (1e-5, 0.01), " m", group=FIND_GROUP,
                         si=True, unit_prefix="m",
                         tip="The XY image's bins, square. A spot is found when one bin of it stands out.")
FIND_SCALE = ParameterSpec(
    "spot_background", "Background scale σ", "float", DEFAULT_SCALE, (1e-4, 0.05), " m", group=FIND_GROUP,
    si=True, unit_prefix="m",
    tip="Each bin is compared with its local background: the image smoothed with a Gaussian of this σ over the "
        "detector's filled area, leaving out spots already found. Uneven gain, the detector's edge and a cloud's "
        "wings then set their own level; spots much wider than this are found only at their edges.")
FIND_ALPHA = ParameterSpec(
    "spot_alpha", "False spots per image", "float", DEFAULT_ALPHA, (1e-9, 1.0), group=FIND_GROUP,
    tip="How many spots pure noise may produce per image: a bin is significant when P(N ≥ n | its background) "
        "(Poisson) is below this divided by the bins tested. Touching bins with P < 0.001 join its spot.")
FIND_MIN_EXCESS = ParameterSpec(
    "spot_min_excess", "Minimum excess (one bin)", "int", DEFAULT_MIN_EXCESS, (0, 1_000_000), " events",
    group=FIND_GROUP, tip="A spot of a single bin is offered only with at least this many events above its "
                          "background; spots of 2 bins or more always are.")

def compress(position: npt.NDArray[np.float64], scale: str, gamma: float = 0.5, decades: int = 3
             ) -> npt.NDArray[np.float64]:
    """Where in the colour map a value sits, from its linear position in the colour bar's range
    (0…1): the colour range compression. Monotonic, 0 → 0 and 1 → 1."""
    x = np.clip(position, 0.0, 1.0)
    if scale == SQRT:
        return np.sqrt(x)
    if scale == POWER:
        return x ** gamma
    if scale == LOG:
        floor = 10.0 ** -decades
        return np.clip(np.log10(np.maximum(x, floor)) / decades + 1.0, 0.0, 1.0)
    return x


def colour_map(scale: str, gamma: float = 0.5, decades: int = 3) -> pg.ColorMap:
    """Viridis, resampled so that a linear value shows the colour of its compressed position: the
    colour bar's gradient over its linear axis in real values. (Only the bar's: pyqtgraph applies
    a bar's map in 256 steps, which loses the compression below 1/256 of the maximum, so the image
    is drawn from ``display_image`` instead.)"""
    base: Any = pg.colormap.get(COLOUR_MAP)
    positions = np.linspace(0.0, 1.0, LUT_SIZE)
    colours = base.map(compress(positions, scale, gamma, decades), mode="byte")
    return pg.ColorMap(positions, colours, name=f"{COLOUR_MAP} ({scale})")


def display_image(image: npt.NDArray[np.float64], peak: float, scale: str, gamma: float = 0.5, decades: int = 3
                  ) -> npt.NDArray[np.float64]:
    """What the image item draws: each value's compressed position (0…1) in the colour map, over
    plain viridis with levels 0…1. The result's image stays linear; this copy is only drawn."""
    return compress(image / peak if peak > 0 else np.zeros_like(image), scale, gamma, decades)


def viridis_lut() -> npt.NDArray[np.uint8]:
    base: Any = pg.colormap.get(COLOUR_MAP)
    return cast(npt.NDArray[np.uint8], base.getLookupTable(nPts=LUT_SIZE, alpha=False))


@dataclass(frozen=True)
class DensityImage:
    projection: str
    box: CropBox  # the view range over T/X/Y (the events kept: those inside it)
    edges_h: npt.NDArray[np.float64]  # the horizontal axis's bin edges, in s or m
    edges_v: npt.NDArray[np.float64]
    image: npt.NDArray[np.float64]  # (horizontal bins, vertical bins): counts or rate, blurred if set
    shots: tuple[int, ...]  # the shot numbers used
    total_shots: int  # the shots loaded
    per_shot: bool = False
    blur: float = 0.0
    automatic_bins: bool = True
    warnings: tuple[str, ...] = ()  # settings not followed as given (``range_warnings``)
    # The highlighted newest shot (None: off): its image on the same bins, for a contour.
    newest_shot: int | None = None
    newest: npt.NDArray[np.float64] = field(default_factory=lambda: np.zeros((0, 0)))
    newest_events: int = 0
    colour: tuple[int, int, int] = (214, 39, 40)
    masked: int = 0  # events the mask took out of the chosen shots (before the view range)
    circles: tuple[Circle, ...] = ()  # the mask's circles (drawn on XY)
    found: tuple[Circle, ...] = ()  # circles Find hot spots offers (drawn on XY)

    @property
    def total(self) -> int:
        """Events in the chosen shots."""
        return self.box.total

    @property
    def events(self) -> int:
        """Events inside the view range: those binned."""
        return self.box.kept

    @property
    def axes(self) -> tuple[int, int]:
        return PROJECTIONS[self.projection]

    def scale(self, axis: int) -> float:
        return axis_scale(axis)

    def unit(self, axis: int) -> str:
        return axis_unit(axis)

    def rect(self) -> QRectF:
        """The image's place in display units (mm, ms)."""
        (h, v), eh, ev = self.axes, self.edges_h, self.edges_v
        sh, sv = self.scale(h), self.scale(v)
        return QRectF(eh[0] * sh, ev[0] * sv, (eh[-1] - eh[0]) * sh, (ev[-1] - ev[0]) * sv)

    def quantity_text(self) -> str:
        """The colour bar's label."""
        if not self.per_shot:
            return "Events per bin" + (" (blurred)" if self.blur else "")
        h, v = self.axes
        area = f"{LENGTH_UNIT}²" if h != 0 and v != 0 else f"({LENGTH_UNIT}·{T_UNIT})"
        return f"Events / {area} / shot" + (" (blurred)" if self.blur else "")


def colour_bar_label(data: DensityImage, scale: str, gamma: float = 0.5, decades: int = 3) -> str:
    """The colour bar's label: the quantity, and with a compressed colour scale, that only the
    colours are compressed (the bar's numbers are the real values, on a linear axis)."""
    text = data.quantity_text()
    if scale == LINEAR:
        return text
    how = {SQRT: "sqrt", LOG: f"log, {decades} decades", POWER: f"power γ {gamma:g}"}.get(scale, scale)
    return f"{text} · colours {how}, values linear"


def empty_density(view: DatasetView, projection: str, shots: tuple[int, ...], values: Mapping[str, Any],
                  box: CropBox | None = None) -> DensityImage:
    nan = (math.nan,) * len(AXES)
    return DensityImage(projection, box or CropBox(nan, nan, 0, 0, keep_fraction(values), 0),
                        np.array([0.0, 1.0]), np.array([0.0, 1.0]), np.zeros((1, 1)), shots, len(view.shots),
                        warnings=range_warnings(values))


def span(box: CropBox, axis: int) -> tuple[float, float]:
    """The box's bounds on ``axis``, widened to half a mm or ms each way when they meet (all
    events at one value)."""
    lower, upper = box.lower[axis], box.upper[axis]
    if not upper > lower:
        lower, upper = lower - 0.5e-3, upper + 0.5e-3
    return lower, upper


def automatic_bins(along_h: npt.NDArray[np.float64], along_v: npt.NDArray[np.float64], span_h: tuple[float, float],
                   span_v: tuple[float, float], square: bool) -> tuple[int, int]:
    """Bins per axis, each from Freedman–Diaconis, at most ``AUTO_BINS_CAP``. ``square`` (XY, both
    in mm, aspect locked): one bin width for both axes, the smaller of the two, so pixels are
    square (to within one bin's rounding), and widened when an axis would pass the cap."""
    count_h = min(freedman_diaconis_bins(along_h, *span_h), AUTO_BINS_CAP)
    count_v = min(freedman_diaconis_bins(along_v, *span_v), AUTO_BINS_CAP)
    if not square:
        return count_h, count_v
    width_h, width_v = span_h[1] - span_h[0], span_v[1] - span_v[0]
    width = max(min(width_h / count_h, width_v / count_v), width_h / AUTO_BINS_CAP, width_v / AUTO_BINS_CAP)
    return (min(max(round(width_h / width), 1), AUTO_BINS_CAP), min(max(round(width_v / width), 1), AUTO_BINS_CAP))


def blur_limit(shape: tuple[int, ...]) -> float:
    """The largest blur σ used, in bins: a quarter of the image's longer side (at least 1). Beyond
    it the image is nearly flat, and the cost (σ per pixel) keeps a Live rerun bounded."""
    return max(1.0, max(shape) / 4)


def blurred(counts: npt.NDArray[np.float64], sigma: float) -> npt.NDArray[np.float64]:
    """``counts`` with a Gaussian blur of ``sigma`` bins (0: as they are). Edges reflect, so the
    total is kept."""
    if sigma <= 0:
        return counts
    return cast(npt.NDArray[np.float64], gaussian_filter(counts, sigma=sigma, mode="reflect"))


def image_title(data: DensityImage) -> tuple[str, str]:
    """The figure's two title lines: what it shows, then how it was binned (and any warning)."""
    bins = data.image.shape
    how = "automatic" if data.automatic_bins else "set"
    first = (f"{data.projection} · {shots_text(data.shots, data.total_shots)} · {data.events:,} of "
             f"{data.total:,} events in range{masked_text(data.masked)}")
    second = f"{bins[0]:,} × {bins[1]:,} bins ({how})"
    if data.blur:
        second += f" · blur σ {data.blur:g} bin{'' if data.blur == 1 else 's'}"
    if data.newest_shot is not None:
        second += f" · shot {data.newest_shot} contoured ({data.newest_events:,} events in range)"
    return first, second + "".join(f" · ⚠ {warning}" for warning in data.warnings)


def empty_reason(data: DensityImage) -> str:
    """Why there is nothing to draw ("" when there is)."""
    text = empty_text(data.total_shots, len(data.shots), data.total)
    if text and data.masked and data.shots:
        return all_masked_text(data.masked)
    if text:
        return text
    if not data.events:
        warned = "".join(f" · ⚠ {warning}" for warning in data.warnings)
        return (f"None of the {data.total:,} events in the chosen shots is inside the view range "
                f"(View range settings){warned}")
    return ""


def contour_level(newest: npt.NDArray[np.float64]) -> float:
    """The newest shot's contour: half its image's maximum."""
    peak = float(newest.max()) if newest.size else 0.0
    return peak / 2 if peak > 0 else math.inf


class DensityPlot(QWidget):
    """A density image with its colour bar and title (``graphics``, a PyQtGraph layout);
    ``show_data`` draws a newer result in place, keeping the user's zoom and pan."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.graphics: Any = pg.GraphicsLayoutWidget(self)
        self.graphics.setBackground("w")
        layout.addWidget(self.graphics)
        self.title: Any = add_label(self.graphics, row=0, col=0, colspan=2)
        self.plot: Any = self.graphics.addPlot(row=1, col=0, axisItems={"bottom": GroupedAxis("bottom"),
                                                                        "left": GroupedAxis("left")})
        self.image: Any = pg.ImageItem(axisOrder="col-major")
        self.image.setLookupTable(viridis_lut())
        self.plot.addItem(self.image)
        # The newest shot's contour, in the image's pixel coordinates (empty: none).
        self.contour: Any = pg.IsocurveItem(axisOrder="col-major")
        self.contour.setParentItem(self.image)
        self.bar: Any = None
        self.projection = ""
        self.scale_key: tuple[str, float, int] = ("", 0.0, 0)
        self.circle_items: list[QGraphicsEllipseItem] = []  # the mask's and the found circles

    def show_data(self, result: AnalysisResult, data: DensityImage, lines: tuple[str, str] | None = None) -> None:
        """Draw ``data``; ``lines``: the title's two lines (default ``image_title``)."""
        values = result.parameters
        h, v = data.axes
        self.projection = data.projection
        first, second = lines or image_title(data)
        self.title.setText(lines_html((f"{result.input.short()} · {first}", second)))
        self.plot.setLabel("bottom", axis_label(h))
        self.plot.setLabel("left", axis_label(v))
        self.plot.setAspectLocked(data.projection == "XY")  # X and Y both in mm: their true shape
        peak = float(data.image.max()) if data.image.size else 0.0
        levels = (0.0, peak if peak > 0 else 1.0)
        key = (str(values.get(SCALE.name, LINEAR)), float(values.get(GAMMA.name, GAMMA.default)),
               int(values.get(DECADES.name, DECADES.default)))
        # The colours come from the compressed copy (exact at any depth); the bar is a legend only:
        # its gradient and its linear axis in real values, never attached to the image.
        self.image.setImage(display_image(data.image, peak, *key), levels=(0.0, 1.0))
        self.image.setRect(data.rect())
        if self.bar is None:
            self.bar = pg.ColorBarItem(values=levels, colorMap=colour_map(*key), interactive=False,
                                       label=colour_bar_label(data, *key))
            self.graphics.addItem(self.bar, row=1, col=1)
        else:
            if key != self.scale_key:
                self.bar.setColorMap(colour_map(*key))
            self.bar.setLevels(levels)
            self.bar.getAxis("left").setLabel(colour_bar_label(data, *key))  # ColorBarItem labels its left axis.
        self.scale_key = key
        if data.newest_shot is not None and data.newest.size and data.newest.max() > 0:
            self.contour.setPen(pg.mkPen(data.colour, width=2))
            self.contour.setData(data.newest, contour_level(data.newest))
        else:
            self.contour.setData(None)
        self.draw_circles(data)

    def draw_circles(self, data: DensityImage) -> None:
        """The mask's circles (keep white, cut red) and the found ones (amber), dashed, on XY only."""
        for item in self.circle_items:
            self.plot.removeItem(item)
        self.circle_items = []
        if data.projection != "XY":
            return
        scale = axis_scale(1)
        drawn: list[tuple[Circle, Any]] = [(circle, KEEP_COLOUR if circle.keep else CUT_COLOUR)
                                           for circle in data.circles]
        drawn += [(circle, FOUND_COLOUR) for circle in data.found]
        for circle, colour in drawn:
            r = circle.r * scale
            item = QGraphicsEllipseItem(QRectF(circle.x * scale - r, circle.y * scale - r, 2 * r, 2 * r))
            item.setPen(pg.mkPen(colour, width=2, style=Qt.PenStyle.DashLine))
            item.setZValue(10)  # Over the image and the newest shot's contour.
            self.plot.addItem(item, ignoreBounds=True)  # The view's auto-range stays the image's.
            self.circle_items.append(item)


@dataclass(frozen=True)
class HotSpots:
    """Find hot spots' result: the summed XY image it searched (with the found circles) and the
    search (None when there was nothing to search)."""
    density: DensityImage
    search: HotSpotSearch | None = None

    def text(self) -> str:
        """The found circles as a Mask's custom text ("" for none)."""
        return self.search.text() if self.search is not None else ""


def spots_title(data: HotSpots) -> tuple[str, str]:
    """The finder's two title lines: the image, then what it found."""
    first, _ = image_title(data.density)
    search = data.search
    if search is None:
        return first, ""
    width = float(search.edges_x[1] - search.edges_x[0])
    rule = (f"bins of {axis_text('X', width, WIDTH_DIGITS)}, P < {search.alpha:g} / {search.tested:,} against a "
            f"local background (σ {axis_text('X', search.scale, WIDTH_DIGITS)})")
    second = (f"{plural(search.found, 'hot spot')} (amber, to review) · {rule}" if search.found
              else f"No hot spots · {rule}")
    notes = "".join(f" · {note}" for note in search.notes)  # Plain: how the bins were chosen.
    return first, second + notes + "".join(f" · ⚠ {warning}" for warning in data.density.warnings)


class HotSpotsPlot(DensityPlot):
    """The finder's image with its circles, and a button copying them as a Mask's custom text
    (nothing is applied: the user pastes them into a plot's Mask)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 2, 6, 4)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.copy_button = identify(QPushButton("Copy circles"), "density_copy_circles")
        self.copy_button.setToolTip("Copies the circles as a Mask's custom circles (cut, in mm), to paste into "
                                    "any plot's Mask › custom. Nothing is applied by itself.")
        self.copy_button.clicked.connect(self.copy)
        bar.addWidget(self.summary, 1)
        bar.addWidget(self.copy_button)
        layout = self.layout()
        assert isinstance(layout, QVBoxLayout)
        layout.addLayout(bar)
        self.text = ""

    def show_spots(self, result: AnalysisResult, data: HotSpots) -> None:
        self.show_data(result, data.density, spots_title(data))
        self.text = data.text()
        count = len(data.search.spots) if data.search is not None else 0
        self.copy_button.setEnabled(bool(self.text))
        self.summary.setText(f"{count:,} circle{'' if count == 1 else 's'} to review: copy them into a plot's "
                             f"Mask › custom to cut them" if count else "No circles to copy")

    def copy(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None and self.text:
            clipboard.setText(self.text)


class DensityImages(DatasetAnalysis):
    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata(
            name="Density images",
            description="2D density image of the loaded events: XY, XT or YT, blurred and colour-compressed as set; "
                        "Find hot spots offers circles to mask",
            group=group.NAME,
            file_path=__file__,
            analysis_id="helab.density_images",
            version="2",
        )

    def get_actions(self) -> List[str]:
        return [PLOT, FIND]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        if action_name == FIND:
            return [*SHOT_SPECS, *FIND_RANGE, *MASK_SPECS, FIND_BIN, FIND_SCALE, FIND_ALPHA, FIND_MIN_EXCESS, SCALE,
                    GAMMA, DECADES]
        return [*SHOT_SPECS, PROJECTION, *RANGE, *MASK_SPECS, BINS, BLUR, QUANTITY, HIGHLIGHT, NEWEST_COLOUR, SCALE,
                GAMMA, DECADES]

    def live_policy(self, action_name: str) -> LivePolicy:
        # The auto-crop of a large folder takes a second or more (as the scatter's): at most one
        # rerun every 2 s while Live adds shots.
        return LivePolicy(min_delay=2.0)

    @staticmethod
    def _scale_brief(values: Mapping[str, Any]) -> str:
        scale = str(values[SCALE.name])
        if scale == POWER:
            scale = f"power γ {float(values[GAMMA.name]):g}"
        elif scale == LOG:
            scale = f"log {int(values[DECADES.name])} decades"
        return f"colour {scale}" if scale != LINEAR else ""

    def describe_run(self, action_name: str, values: Mapping[str, Any], view: DatasetView) -> tuple[str, str]:
        if action_name == FIND:
            settings: tuple[str, ...] = (
                shots_brief(values), range_brief(values, fixed=True), mask_brief(values),
                f"bins {axis_text('X', float(values[FIND_BIN.name]), WIDTH_DIGITS)}",
                f"background σ {axis_text('X', float(values[FIND_SCALE.name]), WIDTH_DIGITS)}",
                f"{float(values[FIND_ALPHA.name]):g} false spots per image", self._scale_brief(values))
            return selection_text(view, values), " · ".join(part for part in settings if part)
        bins = int(values[BINS.name])
        blur = float(values[BLUR.name])
        settings = (str(values[PROJECTION.name]), shots_brief(values), range_brief(values, fixed=True), mask_brief(values),
                    f"bins {bins:,}" if bins else "bins auto", f"blur {blur:g}" if blur else "",
                    "per shot" if values[QUANTITY.name] == PER_SHOT else "", self._scale_brief(values),
                    newest_brief(values))
        return selection_text(view, values), " · ".join(part for part in settings if part)

    def describe_result(self, action_name: str, result: AnalysisResult) -> str:
        return str(result.found.get("brief", ""))

    def result_found(self, action_name: str, data: Any) -> dict[str, Any]:
        """Find hot spots: ``brief`` (how many spots) and ``record_lines`` (the rule, each spot and
        the circles as mask text), kept when the plot is released."""
        if not isinstance(data, HotSpots) or data.search is None:
            return {}
        search = data.search
        found = len(search.spots) + search.left_out
        lines = search_lines(search)
        if search.spots:
            lines.append("As mask circles (Mask › custom): " + "; ".join(circle.text() for circle in search.circles))
        return {"brief": f"{found:,} hot spot{'' if found == 1 else 's'} found", "record_lines": lines}

    def parameter_warnings(self, action_name: str, values: Mapping[str, Any]) -> List[str]:
        return [*range_warnings(values), *mask_warnings(values)]

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        values, view = context.parameters, context.view
        shots = select_shots(view, values)
        mask = mask_from(values)  # Circles that can't be read fail the run, saying which.
        events, masked = mask.apply(view.events(shots))
        context.check()
        if action_name == FIND:
            return self._find(context, shots, events, mask, masked)
        projection = str(values.get(PROJECTION.name, PROJECTION.default))
        if projection not in PROJECTIONS:
            projection = str(PROJECTION.default)
        data = self._image(context, projection, shots, events, mask)
        return replace(data, masked=masked, circles=mask.circles)

    def _image(self, context: AnalysisContext, projection: str, shots: tuple[int, ...], events: Events,
               mask: Mask) -> DensityImage:
        values, view = context.parameters, context.view
        if not len(events):
            return empty_density(view, projection, shots, values)
        box = manual_box(events, values) if manual(values) else crop_box(events, keep_fraction(values),
                                                                         context.cancelled)
        context.check()
        if not box.kept:
            return empty_density(view, projection, shots, values, box)
        inside = events[box.contains(events)]
        h, v = PROJECTIONS[projection]
        (low_h, high_h), (low_v, high_v) = span(box, h), span(box, v)
        bins = int(values.get(BINS.name, 0))
        counts_h, counts_v = (bins, bins) if bins else automatic_bins(inside[:, h], inside[:, v], (low_h, high_h),
                                                                      (low_v, high_v), projection == "XY")
        context.check()
        counts, edges_h, edges_v = np.histogram2d(inside[:, h], inside[:, v], bins=(counts_h, counts_v),
                                                  range=((low_h, high_h), (low_v, high_v)))
        context.check()
        asked = float(values.get(BLUR.name, 0.0))
        sigma = min(asked, blur_limit(counts.shape))
        warnings = range_warnings(values)
        if sigma < asked:
            warnings += (f"blur σ {asked:g} bins is over a quarter of the image's {max(counts.shape):,} bins: "
                         f"using {sigma:g}",)
        image = blurred(counts, sigma)
        per_shot = values.get(QUANTITY.name) == PER_SHOT
        data = DensityImage(projection, box, edges_h, edges_v, image, shots, len(view.shots), per_shot, sigma,
                            bins == 0, warnings)
        if per_shot:
            # The bin area in display units (mm², or mm · ms), from the real bin count.
            area = float(edges_h[1] - edges_h[0]) * data.scale(h) * float(edges_v[1] - edges_v[0]) * data.scale(v)
            data = replace(data, image=image / (len(shots) * area))
        newest = newest_shot(values, shots)
        if newest is None:
            return data
        context.check()
        fresh = mask.apply(newest_events(view, newest))[0]
        fresh = fresh[box.contains(fresh)] if len(fresh) else fresh
        own = (np.histogram2d(fresh[:, h], fresh[:, v], bins=(edges_h, edges_v))[0] if len(fresh)
               else np.zeros_like(counts))
        # One shot's image is sparse: blurred at least 2 bins, so its contour is a shape, not specks.
        return replace(data, newest_shot=newest, newest=blurred(own, max(sigma, NEWEST_BLUR)),
                       newest_events=len(fresh), colour=newest_colour(values))

    def _find(self, context: AnalysisContext, shots: tuple[int, ...], events: Events, mask: Mask,
              masked: int) -> HotSpots:
        """The summed XY image over the view range and its hot spots (``hotspots.find_hot_spots``)."""
        values, view = context.parameters, context.view
        empty = replace(empty_density(view, "XY", shots, values), masked=masked, circles=mask.circles)
        if not len(events):
            return HotSpots(empty)
        box = manual_box(events, values) if manual(values) else crop_box(events, keep_fraction(values),
                                                                         context.cancelled)
        context.check()
        if not box.kept:
            return HotSpots(replace(empty, box=box))
        inside = events[box.contains(events)]
        search = find_hot_spots(inside[:, 1], inside[:, 2], span(box, 1), span(box, 2),
                                float(values[FIND_BIN.name]), float(values[FIND_SCALE.name]),
                                float(values[FIND_ALPHA.name]), int(values[FIND_MIN_EXCESS.name]))
        image = DensityImage("XY", box, search.edges_x, search.edges_y, search.image, shots, len(view.shots),
                             automatic_bins=False, warnings=range_warnings(values), masked=masked,
                             circles=mask.circles, found=search.circles)
        return HotSpots(image, search)

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        if isinstance(result.data, HotSpots):
            spots: HotSpots = result.data
            reason = empty_reason(spots.density)
            if reason:
                return empty_pane(reason, parent)
            plot = HotSpotsPlot(parent)
            plot.show_spots(result, spots)
            return plot
        data: DensityImage = result.data
        reason = empty_reason(data)
        if reason:
            return empty_pane(reason, parent)
        widget = DensityPlot(parent)
        widget.show_data(result, data)
        return widget

    def update(self, widget: QWidget, result: AnalysisResult) -> bool:
        """A rerun (e.g. Live's next shots) draws in place, keeping the zoom and pan, while the
        projection stays; otherwise (or to or from an empty plot) it is drawn anew."""
        if isinstance(result.data, HotSpots):
            if not isinstance(widget, HotSpotsPlot) or empty_reason(result.data.density):
                return False
            widget.show_spots(result, result.data)
            return True
        data: DensityImage = result.data
        if (not isinstance(widget, DensityPlot) or isinstance(widget, HotSpotsPlot) or empty_reason(data)
                or widget.projection != data.projection):
            return False
        widget.show_data(result, data)
        return True
