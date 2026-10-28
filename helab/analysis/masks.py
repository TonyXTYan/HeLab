"""Masks every plot can share (D9): circles in the detector's XY plane that keep or cut events,
applied to the chosen shots' events before a plot bins them, crops them or counts them.

A plot adds ``MASK_SPECS`` to its parameters (the Mask group: none, a preset, or custom circles
typed as ``x, y, r[, keep|cut]`` in mm, separated by ";" or new lines), applies
``mask_from(values).apply`` (or ``Mask.keeps``, ``masked_counts_per_shot``) in ``compute`` and puts
``mask_brief`` in its settings line. The mask is
part of the run's parameters, so it is in the result's ``reuse_key`` and record.

**The rule** is the lab's ``masktxy_2d_circle`` (Core_BEC_Analysis ``lib/txy_tools``): an event
stays when it is inside every keep circle and outside every cut circle (the circles are ANDed,
so two keep circles keep only their overlap). **Inside means strictly closer than r** to the
centre (``radial_diff < radius`` there): an event exactly on a circle counts as outside, so a cut
circle keeps it and a keep circle drops it. The mask is in XY only: T is never masked.

**Presets** (``PRESETS``): the earlier detector's hot spots, ported as they are from Core's
``hotspot_mask.m`` (the list "updated 2020-06-14", one keep circle of r 38 mm and 13 cut
circles), moved into HeLab's unrotated frame. The lab rotated XY by ``dld_xy_rot`` = 0.61 rad
before masking (``import_mcp_tdc_data``: ``txy · [1 0 0; 0 cos α −sin α; 0 sin α cos α]`` with
α = −0.61, so a rotated point is R(+0.61) · (x, y)); HeLab never rotates (Tony, 2026-10-20), so
each centre is turned back by R(−0.61) (``unrotate``); radii and the keep circle at the origin
don't change. The current detector's preset is empty until the hot-spot finder (D15) gives one.
"""
from __future__ import annotations

import functools
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import numpy.typing as npt

from helab.analysis.dataset_view import DatasetView, Events, txy
from helab.analysis.parameters import ParameterSpec

MM = 1e-3  # the text's unit (mm) in the events' metres

# Modes and presets

NONE, PRESET, CUSTOM = "none", "preset", "custom"
EARLIER, CURRENT = "earlier detector (2020)", "current detector"
MASK_GROUP = "Mask"


@dataclass(frozen=True)
class Circle:
    """A circle in XY, in metres in HeLab's (unrotated) frame; ``keep``: events inside stay
    (else events inside are cut)."""
    x: float
    y: float
    r: float
    keep: bool = False

    def inside(self, x: npt.NDArray[np.float64], y: npt.NDArray[np.float64]) -> npt.NDArray[np.bool_]:
        """Strictly inside (as ``masktxy_2d_circle``: distance < r)."""
        return np.asarray((x - self.x) ** 2 + (y - self.y) ** 2 < self.r ** 2)

    def text(self) -> str:
        """``x, y, r, cut`` in mm, as the custom circles are typed."""
        return (f"{mm_text(self.x)}, {mm_text(self.y)}, {mm_text(self.r)}, "
                f"{'keep' if self.keep else 'cut'}")


def mm_text(metres: float) -> str:
    """A length in mm to 0.001 mm, trailing zeros dropped, with an ASCII minus (it is meant to be
    typed and pasted): ``32.5``, ``-3.6``, ``0``."""
    text = f"{metres / MM:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


LEGACY_ROTATION = 0.61  # rad: ``dld_xy_rot`` when the earlier detector's list was made


def rotate(x: float, y: float, angle: float) -> tuple[float, float]:
    """(x, y) turned by ``angle`` (counter-clockwise for a positive angle): what the lab's import
    did to an event with ``dld_xy_rot`` = ``angle``."""
    c, s = math.cos(angle), math.sin(angle)
    return x * c - y * s, x * s + y * c


def unrotate(x: float, y: float, angle: float = LEGACY_ROTATION) -> tuple[float, float]:
    """A point of the lab's rotated frame back in HeLab's: ``rotate`` by −``angle``."""
    return rotate(x, y, -angle)


# Core_BEC_Analysis lib/txy_tools/hotspot_mask.m (commit 408d856, 2021-11-05; the list "updated
# 2020-06-14"), as written there: (x, y, r) in m in the frame rotated by 0.61 rad, polarity 1 =
# keep, 0 = cut; "start from north then go clockwise".
EARLIER_ROTATED: tuple[tuple[float, float, float, int], ...] = (
    (0.0, -0.0e-3, 38e-3, 1),
    (5.788e-3, 35.61e-3, 4e-3, 0),
    (13.99e-3, 31.79e-3, 2.5e-3, 0),
    (22.69e-3, 28.41e-3, 3e-3, 0),
    (29.82e-3, 20.82e-3, 3e-3, 0),
    (30.5e-3, 5.0e-3, 4.5e-3, 0),
    (35.6e-3, 5.6e-3, 4.5e-3, 0),
    (30.5e-3, -15.71e-3, 6e-3, 0),
    (25.36e-3, -19.8e-3, 3e-3, 0),
    (27.79e-3, -23.24e-3, 3.5e-3, 0),
    (23.81e-3, -26.49e-3, 3e-3, 0),
    (19.16e-3, -29.46e-3, 4e-3, 0),
    (2.48e-3, -34.8e-3, 2e-3, 0),
    (26.96e-3, 21.46e-3, 1e-3, 0),
)


def from_rotated(rows: Iterable[tuple[float, float, float, int]], angle: float = LEGACY_ROTATION
                 ) -> tuple[Circle, ...]:
    """The lab's (x, y, r, polarity) rows, in the frame rotated by ``angle``, as HeLab circles."""
    return tuple(Circle(*unrotate(x, y, angle), r, bool(polarity)) for x, y, r, polarity in rows)


PRESETS: dict[str, tuple[Circle, ...]] = {
    EARLIER: from_rotated(EARLIER_ROTATED),
    CURRENT: (),  # TODO(D15): the current detector's hot spots, from the finder on its data.
}

MASK_MODE = ParameterSpec(
    "mask_mode", "Mask", "choice", NONE, choices=(NONE, PRESET, CUSTOM), group=MASK_GROUP,
    tip="Circles in XY that keep or cut events before the plot uses them: none, a preset (a detector's "
        "hot spots), or circles typed below. An event stays when it is inside every keep circle and outside "
        "every cut circle; one exactly on a circle counts as outside. T is never masked.")
@dataclass(frozen=True)
class PresetSpec(ParameterSpec):
    """The preset choice, whose record text also lists the preset's circles (in mm), so a plot's
    record says what was masked even if a preset changes later."""

    def text(self, value: Any) -> str:
        circles = PRESETS.get(str(value), ())
        listed = "; ".join(circle.text() for circle in circles) or "no circles"
        return f"{super().text(value)} ({listed})"


MASK_PRESET = PresetSpec(
    "mask_preset", "Preset", "choice", EARLIER, choices=tuple(PRESETS), group=MASK_GROUP,
    when=(MASK_MODE.name, PRESET),
    tip=f"{EARLIER}: the lab's hot-spot mask for the earlier detector (Core hotspot_mask.m, 2020-06-14): a keep "
        f"circle of r 38 mm and 13 cut circles, turned back from the lab's 0.61 rad XY rotation (HeLab doesn't "
        f"rotate). {CURRENT}: empty until the hot-spot finder (Density images › Find hot spots) gives one.")
MASK_CIRCLES = ParameterSpec(
    "mask_circles", "Circles (mm)", "text", "", group=MASK_GROUP, when=(MASK_MODE.name, CUSTOM),
    tip="One circle per line (or separated by \";\"): x, y, r in mm, then keep or cut (cut if left out), "
        "e.g. \"0, 0, 38, keep; 30.5, 5, 4.5\". Use \".\" for decimals: \",\" separates the numbers. "
        "Density images › Find hot spots offers circles to copy here.")
MASK_SPECS: tuple[ParameterSpec, ...] = (MASK_MODE, MASK_PRESET, MASK_CIRCLES)
MAX_CIRCLES = 500


class MaskError(ValueError):
    """Custom circles that can't be read: the message says which one and why."""


SEPARATORS = re.compile(r"[;\n\r]+")
POLARITY = {"keep": True, "k": True, "1": True, "cut": False, "c": False, "0": False}


def parse_circles(text: str) -> tuple[Circle, ...]:
    """The circles typed as ``x, y, r[, keep|cut]`` in mm, separated by ";" or new lines (blank
    ones skipped; "−" reads as minus; keep/cut also as 1/0, the lab's polarity). Raises
    ``MaskError`` naming the first circle that can't be read."""
    circles: list[Circle] = []
    for number, item in enumerate((part.strip() for part in SEPARATORS.split(text)), start=1):
        if not item:
            continue
        fields = [field.strip() for field in item.replace("−", "-").split(",")]
        where = f"Mask circle “{item}”"
        polarity = len(fields) == 4 and fields[3] in ("0", "1")  # the lab's 1 = keep, 0 = cut
        if len(fields) > 3 and not polarity and all(_number(field) for field in fields[3:]):
            # "1,5, 2, 3": a decimal comma, as German writes it.
            raise MaskError(f"{where}: use “.” for decimals: “,” separates x, y, r (and keep or cut)")
        if len(fields) not in (3, 4):
            raise MaskError(f"{where}: needs x, y and r in mm, then optionally keep or cut, separated by "
                            f"commas (decimals with \".\")")
        try:
            x, y, r = (float(field) for field in fields[:3])
        except ValueError:
            raise MaskError(f"{where}: x, y and r must be numbers in mm (decimals with \".\")") from None
        if not all(math.isfinite(value) for value in (x, y, r)):
            raise MaskError(f"{where}: x, y and r must be finite numbers")
        if r <= 0:
            raise MaskError(f"{where}: the radius must be above 0 mm")
        keep = False
        if len(fields) == 4:
            word = fields[3].lower()
            if word not in POLARITY:
                raise MaskError(f"{where}: the fourth value must be keep or cut, not “{fields[3]}”")
            keep = POLARITY[word]
        circles.append(Circle(x * MM, y * MM, r * MM, keep))
        if len(circles) > MAX_CIRCLES:
            raise MaskError(f"More than {MAX_CIRCLES} mask circles")
    return tuple(circles)


def _number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def format_circles(circles: Sequence[Circle]) -> str:
    """Circles as the custom text reads them, one per line."""
    return "\n".join(circle.text() for circle in circles)


# Applying a mask

@dataclass(frozen=True)
class Mask:
    """The circles a run masks with (none: nothing masked) and where they came from."""
    circles: tuple[Circle, ...] = ()
    source: str = NONE  # NONE, CUSTOM or a preset's name

    @property
    def active(self) -> bool:
        return bool(self.circles)

    def keeps(self, events: Events) -> npt.NDArray[np.bool_]:
        """Which of ``events`` (T/X/Y rows, in s and m) the mask keeps: from the mask's lookup grid
        (``raster``), with the exact test only for events in cells a circle's edge crosses (and
        for non-finite positions). The same answer as ``keeps_exactly``, much faster."""
        events = np.asarray(events)
        if not self.circles or not len(events):
            return np.ones(len(events), dtype=bool)
        x, y = events[:, 1], events[:, 2]
        grid = raster(self.circles)
        with np.errstate(invalid="ignore"):
            ix = np.floor((x - grid.x0) / grid.cell)
            iy = np.floor((y - grid.y0) / grid.cell)
        on_grid = (ix >= 0) & (ix < grid.nx) & (iy >= 0) & (iy < grid.ny)  # False for nan
        kept = np.full(len(events), grid.outside_kept)
        status = grid.status[ix[on_grid].astype(np.intp), iy[on_grid].astype(np.intp)]
        kept[on_grid] = status == KEPT
        exact = np.zeros(len(events), dtype=bool)
        exact[on_grid] = status == EDGE
        exact |= ~(np.isfinite(x) & np.isfinite(y))
        if exact.any():
            kept[exact] = _keeps(self.circles, x[exact], y[exact])
        return kept

    def keeps_exactly(self, events: Events) -> npt.NDArray[np.bool_]:
        """``keeps`` by testing every event against every circle (the reference)."""
        events = np.asarray(events)
        if not self.circles or not len(events):
            return np.ones(len(events), dtype=bool)
        return _keeps(self.circles, events[:, 1], events[:, 2])

    def apply(self, events: Events) -> tuple[Events, int]:
        """(the events kept, how many were masked out); ``events`` as they are with no circles."""
        if not self.circles or not len(events):
            return events, 0
        kept = self.keeps(events)
        return events[kept], int(len(events) - np.count_nonzero(kept))

    def counts(self) -> tuple[int, int]:
        """(keep circles, cut circles)."""
        keep = sum(1 for circle in self.circles if circle.keep)
        return keep, len(self.circles) - keep

    def brief(self) -> str:
        """``mask: 3 cut circles``, ``mask: earlier detector (2020), 1 keep and 13 cut circles``; ""
        for no mask."""
        if self.source == NONE:
            return ""
        keep, cut = self.counts()
        parts = [f"{keep} keep" if keep else "", f"{cut} cut" if cut else ""]
        circles = " and ".join(part for part in parts if part)
        what = f"{circles} circle{'' if keep + cut == 1 else 's'}" if circles else "no circles"
        return f"mask: {self.source}, {what}" if self.source != CUSTOM else f"mask: {what}"


def _keeps(circles: Sequence[Circle], x: npt.NDArray[np.float64], y: npt.NDArray[np.float64]
           ) -> npt.NDArray[np.bool_]:
    kept = np.ones(len(x), dtype=bool)
    for circle in circles:
        inside = circle.inside(x, y)
        kept &= inside if circle.keep else ~inside
    return kept


# The lookup grid: each cell is dropped, kept, or crossed by a circle's edge (tested exactly).
DROPPED, KEPT, EDGE = 0, 1, 2
GRID_CELL = 0.1e-3  # m (0.05 mm: 4× the cells to build, no faster to look up)
MAX_CELLS = 4_000_000  # coarser cells beyond (the edge cells are tested exactly anyway)
MARGIN = 1e-9  # m: a cell is decided only this far from a circle's edge (rounding in the cell index)


@dataclass(frozen=True)
class Raster:
    x0: float
    y0: float
    cell: float
    nx: int
    ny: int
    status: npt.NDArray[np.int8]  # (nx, ny): DROPPED, KEPT or EDGE
    outside_kept: bool  # off the grid (outside every circle): kept unless there are keep circles


@functools.lru_cache(maxsize=16)
def raster(circles: tuple[Circle, ...]) -> Raster:
    """The circles' lookup grid over their bounding box (made once per set of circles)."""
    x0 = min(circle.x - circle.r for circle in circles)
    y0 = min(circle.y - circle.r for circle in circles)
    width = max(circle.x + circle.r for circle in circles) - x0
    height = max(circle.y + circle.r for circle in circles) - y0
    cell = max(GRID_CELL, math.sqrt(width * height / MAX_CELLS))
    nx, ny = int(width / cell) + 1, int(height / cell) + 1
    low_x, low_y = x0 + cell * np.arange(nx), y0 + cell * np.arange(ny)
    high_x, high_y = low_x + cell, low_y + cell
    dropped = np.zeros((nx, ny), dtype=bool)
    edge = np.zeros((nx, ny), dtype=bool)
    for circle in circles:
        near_x = np.maximum.reduce([low_x - circle.x, np.zeros(nx), circle.x - high_x])
        near_y = np.maximum.reduce([low_y - circle.y, np.zeros(ny), circle.y - high_y])
        far_x = np.maximum(np.abs(low_x - circle.x), np.abs(high_x - circle.x))
        far_y = np.maximum(np.abs(low_y - circle.y), np.abs(high_y - circle.y))
        nearest = np.sqrt(near_x[:, None] ** 2 + near_y[None, :] ** 2)
        farthest = np.sqrt(far_x[:, None] ** 2 + far_y[None, :] ** 2)
        inside = farthest < circle.r - MARGIN  # every point of the cell strictly inside
        outside = nearest >= circle.r + MARGIN  # no point of the cell inside
        dropped |= outside if circle.keep else inside
        edge |= ~(inside | outside)
    status = np.where(dropped, DROPPED, np.where(edge, EDGE, KEPT)).astype(np.int8)
    return Raster(x0, y0, cell, nx, ny, status, not any(circle.keep for circle in circles))


def mask_from(values: Mapping[str, Any]) -> Mask:
    """The mask the parameters set; raises ``MaskError`` for custom circles that can't be read."""
    mode = values.get(MASK_MODE.name, NONE)
    if mode == PRESET:
        name = str(values.get(MASK_PRESET.name, MASK_PRESET.default))
        name = name if name in PRESETS else str(MASK_PRESET.default)
        return Mask(PRESETS[name], name)
    if mode == CUSTOM:
        return Mask(parse_circles(str(values.get(MASK_CIRCLES.name, ""))), CUSTOM)
    return Mask()


def mask_key(values: Mapping[str, Any]) -> dict[str, Any]:
    """For a result's reuse key: a preset's circles as used (x, y, r in m, keep), so a changed
    preset never matches an older result; {} without a preset."""
    if values.get(MASK_MODE.name) != PRESET:
        return {}
    name = str(values.get(MASK_PRESET.name, MASK_PRESET.default))
    return {"mask_preset_circles": [[circle.x, circle.y, circle.r, circle.keep] for circle in PRESETS.get(name, ())]}


def mask_brief(values: Mapping[str, Any]) -> str:
    """The mask for a plot's settings line (``Mask.brief``); never raises: ``mask: ⚠ circles
    can't be read`` for custom circles that can't."""
    try:
        return mask_from(values).brief()
    except MaskError:
        return "mask: ⚠ circles can't be read"


def mask_warnings(values: Mapping[str, Any]) -> tuple[str, ...]:
    """What the settings tab and the dock's line should say about the mask: circles that can't be
    read (the run then fails with the same message) or a mask without circles (nothing masked)."""
    try:
        mask = mask_from(values)
    except MaskError as error:
        return (str(error),)
    if mask.source not in (NONE, CUSTOM) and not mask.circles:
        return (f"Mask preset “{mask.source}” has no circles yet: nothing masked",)
    if mask.source == CUSTOM and not mask.circles:
        return ("Mask: no circles typed: nothing masked",)
    return ()


def masked_counts_per_shot(view: DatasetView, shots: Sequence[int], mask: Mask
                           ) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64], int]:
    """(shot numbers, events per shot the mask keeps, events masked out in all) of ``shots``."""
    numbers = np.fromiter(shots, dtype=np.int64, count=len(shots))
    counts = np.empty(len(shots), dtype=np.int64)
    masked = 0
    for index, shot in enumerate(shots):
        events = view.shots[int(shot)]
        if mask.active:
            kept = int(np.count_nonzero(mask.keeps(txy(events))))
            masked += len(events) - kept
        else:
            kept = len(events)
        counts[index] = kept
    return numbers, counts, masked


def masked_text(masked: int) -> str:
    """`` · 1,234 masked out`` for a title ("" for none)."""
    return f" · {masked:,} masked out" if masked else ""


def all_masked_text(masked: int) -> str:
    """Why a plot is empty when the mask took every event."""
    return f"All {masked:,} events in the chosen shots are masked out (Mask settings)"
