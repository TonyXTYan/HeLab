"""One detector per instrument kind. Each gets its region of the frame, already cut out and (for a region
given by four corners) straightened, and says what it saw and how sure it is.

Statuses: `ok` (as wanted), `off` (not as wanted: out of its band, still, someone moving), `unknown`
(couldn't tell). A detector never guesses: when it can't see clearly it says `unknown` with a note.

Marks are drawn on the overlay; their points are in the region's coordinates and the engine maps them back:
("line", [(x, y), ...]) an open polyline, ("loop", [(x, y), ...]) a closed one, ("circle", (x, y), r),
("point", (x, y)).
"""

from __future__ import annotations

import collections
import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

from .config import Instrument

if TYPE_CHECKING:  # cv2.typing is OpenCV 4.8+; Raspberry Pi OS ships 4.6
    from cv2.typing import MatLike

    Image = MatLike  # an OpenCV image (a NumPy array)
else:
    Image = Any
Point = tuple[float, float]


@dataclass
class Reading:
    status: str  # ok, off, unknown
    text: str  # short, for the overlay and the table
    values: dict[str, float | str | None] = field(default_factory=dict)
    confidence: float = 0.0
    note: str = ""
    marks: list[tuple[Any, ...]] = field(default_factory=list)
    at: float = field(default_factory=time.time)


class Detector:
    oversample = 1.0  # the region is cut at this many pixels per camera pixel

    def __init__(self, inst: Instrument) -> None:
        self.inst = inst

    def update(self, roi: Image) -> Reading:
        raise NotImplementedError

    def reset(self) -> None:
        """Forgets history (after the region changes)."""


def _rect(x: float, y: float, w: float, h: float) -> list[Point]:
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


class TraceLevel(Detector):
    """A digital scope's signal: its height on the screen (0 top, 1 bottom), and whether that is within
    `tolerance` of the middle.

    Signal pixels are those far (`contrast`) from the screen's background colour (the median colour of the
    screen), so a thin trace and a noisy band alike count. Per column, the signal's median row; the level is
    the median over columns, and the spread its 10–90 % rows. `margin` (fraction) trims the screen's edges,
    where the bezel, menus and labels sit.
    """

    MIN_COLUMNS = 0.3

    def update(self, roi: Image) -> Reading:
        h, w = roi.shape[:2]
        margin = self.inst.option("margin", 0.08)
        top, bottom = int(h * margin), h - int(h * margin)
        left, right = int(w * margin), w - int(w * margin)
        inner = cv2.GaussianBlur(roi[top:bottom, left:right], (3, 3), 0).astype(np.float32)
        if inner.shape[0] < 5 or inner.shape[1] < 5:
            return Reading("unknown", "region too small")
        background = np.median(inner.reshape(-1, 3), axis=0)
        distance = np.abs(inner - background).max(axis=2)
        signal = distance >= self.inst.option("contrast", 40.0)
        columns = signal.any(axis=0)
        found = float(columns.mean())
        if found < self.MIN_COLUMNS:
            return Reading("unknown", "no signal", {"found": round(found, 2)}, found,
                           f"signal seen in {found:.0%} of columns")
        rows = np.nonzero(signal)[0]
        per_column = [float(np.median(np.nonzero(signal[:, c])[0])) for c in np.nonzero(columns)[0]]
        level = (float(np.median(per_column)) + top) / max(1, h - 1)
        low, high = ((float(np.percentile(rows, q)) + top) / max(1, h - 1) for q in (10, 90))
        tol = self.inst.option("tolerance", 0.15)
        status = "ok" if abs(level - 0.5) <= tol else "off"
        word = "middle" if status == "ok" else ("high" if level < 0.5 else "low")
        y = level * (h - 1)
        marks: list[tuple[Any, ...]] = [
            ("line", [(left, y), (right, y)]),
            ("dash", [(0, (0.5 - tol) * h), (w, (0.5 - tol) * h)]),
            ("dash", [(0, (0.5 + tol) * h), (w, (0.5 + tol) * h)]),
        ]
        return Reading(
            status,
            f"{word} ({level:.2f})",
            {"level": round(level, 3), "spread": f"{low:.2f}–{high:.2f}", "found": round(found, 2)},
            found,
            marks=marks,
        )


class Needle(Detector):
    """An analogue meter's needle: its offset from the centre, -1 (left edge) to 1 (right edge), where it
    crosses the region's middle height.

    The needle is the longest dark, roughly vertical line in the region (black-hat filter, then Hough lines).
    """

    def update(self, roi: Image) -> Reading:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        scale = 4
        big = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        dark = cv2.morphologyEx(big, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)))
        if float(dark.max()) < 20:
            return Reading("unknown", "no needle", note="no dark line in the region")
        _, mask = cv2.threshold(dark, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        h, w = big.shape
        lines = cv2.HoughLinesP(mask, 1, math.pi / 180, threshold=max(10, h // 4), minLineLength=h * 0.35, maxLineGap=6)
        best: tuple[float, float, float, float, float] | None = None
        if lines is not None:
            for x1, y1, x2, y2 in lines.reshape(-1, 4).astype(float):
                angle = math.degrees(math.atan2(abs(x2 - x1), abs(y2 - y1)))  # 0 = vertical
                length = math.hypot(x2 - x1, y2 - y1)
                if angle <= 50 and (best is None or length > best[4]):
                    best = (x1, y1, x2, y2, length)
        if best is None:
            return Reading("unknown", "no needle", note="no long near-vertical dark line")
        x1, y1, x2, y2, length = best
        x_mid = x1 if y2 == y1 else x1 + (x2 - x1) * (h / 2 - y1) / (y2 - y1)
        offset = float(x_mid / w * 2 - 1)
        tol = self.inst.option("tolerance", 0.2)
        status = "ok" if abs(offset) <= tol else "off"
        word = "middle" if status == "ok" else ("left" if offset < 0 else "right")
        marks = [("line", [(x1 / scale, y1 / scale), (x2 / scale, y2 / scale)])]
        return Reading(status, f"{word} ({offset:+.2f})", {"offset": round(offset, 3)}, min(1.0, length / h), marks=marks)


class Dot(Detector):
    """An analogue scope's spot: where it is, and whether it moved more than `still_px` over the last
    `window` seconds (`ok` = moving, as wanted).

    The spot is the brightest compact area above the screen's own background (a large median blur).
    """

    MIN_CONTRAST = 30.0

    def __init__(self, inst: Instrument) -> None:
        super().__init__(inst)
        self.history: collections.deque[tuple[float, float, float]] = collections.deque()

    def reset(self) -> None:
        self.history.clear()

    def update(self, roi: Image) -> Reading:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        k = max(3, (min(gray.shape) // 4) | 1)
        excess = cv2.subtract(cv2.GaussianBlur(gray, (3, 3), 0), cv2.medianBlur(gray, k)).astype(np.float32)
        peak = float(excess.max())
        now = time.time()
        window = self.inst.option("window", 10.0)
        while self.history and now - self.history[0][0] > window:
            self.history.popleft()
        if peak < self.MIN_CONTRAST:
            return Reading("unknown", "no dot", {"contrast": round(peak, 1)}, 0.0, "nothing bright enough (covered?)")
        _, labels, stats, centroids = cv2.connectedComponentsWithStats((excess >= 0.6 * peak).astype(np.uint8))
        py, px = np.unravel_index(int(np.argmax(excess)), excess.shape)
        label = int(labels[py, px])
        if int(stats[label, cv2.CC_STAT_AREA]) > 0.05 * gray.size:
            return Reading("unknown", "no dot", {"contrast": round(peak, 1)}, 0.2, "bright area too big for a dot")
        cx, cy = (float(v) for v in centroids[label])
        self.history.append((now, cx, cy))
        xs = np.array([p[1] for p in self.history])
        ys = np.array([p[2] for p in self.history])
        spread = float(max(np.ptp(xs), np.ptp(ys))) if len(self.history) > 1 else 0.0
        moving = spread > self.inst.option("still_px", 2.0)
        marks: list[tuple[Any, ...]] = [("circle", (cx, cy), 6)]
        marks += [("point", (x, y)) for _, x, y in list(self.history)[-20:]]
        status = "ok" if moving else "off"
        text = f"moving ({spread:.1f} px)" if moving else f"still ({spread:.1f} px in {window:.0f} s)"
        if len(self.history) < 3:
            status, text = "unknown", "watching…"
        return Reading(
            status,
            text,
            {"x": round(cx, 1), "y": round(cy, 1), "spread_px": round(spread, 2), "contrast": round(peak, 1)},
            min(1.0, peak / 100),
            marks=marks,
        )


class Motion(Detector):
    """Movement in the region (a stand-in for people): background subtraction on a small grey copy.

    `ignore` (other instruments' regions, set by the engine) is masked out, since screens change by
    themselves. Movement counts for `hold` seconds after it stops (`off` = someone moving).
    """

    SCALE = 0.25

    def __init__(self, inst: Instrument) -> None:
        super().__init__(inst)
        self.ignore: list[list[Point]] = []
        self.last_motion = 0.0
        self.reset()

    def reset(self) -> None:
        self.subtractor = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=32, detectShadows=False)
        self.frames = 0

    def update(self, roi: Image) -> Reading:
        s = self.SCALE
        small = cv2.resize(roi, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        mask = self.subtractor.apply(cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0))
        for polygon in self.ignore:
            cv2.fillPoly(mask, [np.array([(x * s, y * s) for x, y in polygon], np.int32)], 0)
        mask = cv2.dilate(cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)), np.ones((5, 5), np.uint8))
        self.frames += 1
        if self.frames < 10:
            return Reading("unknown", "learning the background…", {"frames": self.frames})
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        min_area = self.inst.option("min_area", 0.004) * mask.size
        regions = [cv2.boundingRect(c) for c in contours if cv2.contourArea(c) >= min_area]
        now = time.time()
        if regions:
            self.last_motion = now
        present = self.last_motion > 0 and now - self.last_motion <= self.inst.option("hold", 5.0)
        marks = [("loop", _rect(x / s, y / s, w / s, h / s)) for x, y, w, h in regions]
        ago = "" if self.last_motion == 0 else f", last {now - self.last_motion:.0f} s ago"
        return Reading(
            "off" if present else "ok",
            ("movement" if present else "quiet") + ago,
            {"present": "yes" if present else "no", "regions": len(regions), "moved": round(float(np.count_nonzero(mask)) / mask.size, 4)},
            1.0,
            marks=marks,
        )
