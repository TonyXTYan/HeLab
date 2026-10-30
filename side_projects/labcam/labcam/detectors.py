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
    """A digital scope's signal: its shape and its height on the screen (0 top, 1 bottom).

    Each column of the screen is compared with its own median colour, so a faint thin line (only ~20 levels
    off the screen) still stands out while the screen's overall colour drifts with the light; a pixel at least
    `contrast` away is signal. `margin` (fraction) trims the screen's edges (bezel, menus, labels).
    - thickness: the median column's count of signal pixels, as a fraction of the height (a line ≈ 0.04–0.12,
      a stray label or grid dot adds a pixel, not an extent);
    - filled: how far the columns' median colour is from the empty screen's (`background`, [B, G, R]); a block
      covering most of the screen makes the median the block's colour, so it reads as filled even when the
      leftover screen is what differs per column;
    - waviness: how far the columns' median signal rows spread (10–90 %), as a fraction of the height;
    - shape: `block` (thicker than `thin` or filled beyond `fill`), `line` (flatter than `flat`), `wavy`, or
      `none` (an empty screen). For a laser lock's error signal a flat thin line means locked;
    - level: the median of the columns' median signal rows.
    `ok` is a flat thin line within `tolerance` of the middle.
    """

    MIN_COLUMNS = 0.3

    def __init__(self, inst: Instrument) -> None:
        super().__init__(inst)
        self.reset()

    def reset(self) -> None:
        raw = self.inst.options.get("background")
        self.background: Any = np.array(raw, np.float32) if raw is not None else None

    def update(self, roi: Image) -> Reading:
        h, w = roi.shape[:2]
        margin = self.inst.option("margin", 0.08)
        top, bottom = int(h * margin), h - int(h * margin)
        left, right = int(w * margin), w - int(w * margin)
        inner = cv2.GaussianBlur(roi[top:bottom, left:right], (3, 3), 0).astype(np.float32)
        if inner.shape[0] < 5 or inner.shape[1] < 5:
            return Reading("unknown", "region too small")
        column_colour = np.median(inner, axis=0, keepdims=True)
        signal = np.abs(inner - column_colour).max(axis=2) >= self.inst.option("contrast", 25.0)
        filled = 0.0
        if self.background is not None:
            filled = float(np.median(np.abs(column_colour[0] - self.background).max(axis=1)))
        fill_limit = self.inst.option("fill", 40.0)
        columns = np.nonzero(signal.any(axis=0))[0]
        found = len(columns) / signal.shape[1]
        scale = max(1, h - 1)
        thin, flat = self.inst.option("thin", 0.2), self.inst.option("flat", 0.12)
        tol = self.inst.option("tolerance", 0.15)
        if found < self.MIN_COLUMNS:
            if filled > fill_limit:
                return Reading("off", "block (fills the screen)", {"shape": "block", "filled": round(filled), "found": round(found, 2)},
                               round(min(1.0, filled / (2 * fill_limit)), 2))
            if self.background is not None:
                return Reading("off", "empty screen", {"shape": "none", "filled": round(filled), "found": round(found, 2)}, 0.6,
                               "no trace on the screen: off-screen or switched off?")
            return Reading("unknown", "no signal", {"shape": "none", "found": round(found, 2)}, 0.5,
                           f"signal seen in {found:.0%} of columns")
        counts = signal.sum(axis=0)[columns]
        medians = [float(np.median(np.nonzero(signal[:, c])[0])) for c in columns]
        thickness = float(np.median(counts)) / scale
        waviness = float(np.percentile(medians, 90) - np.percentile(medians, 10)) / scale
        level = (float(np.median(medians)) + top) / scale
        blocked = thickness > thin or filled > fill_limit
        shape = "block" if blocked else ("line" if waviness <= flat else "wavy")
        if shape == "line" and self.background is not None:
            # Follow slow light changes from frames that show the empty screen around a thin line.
            self.background = 0.95 * self.background + 0.05 * np.median(column_colour[0], axis=0)
        centred = abs(level - 0.5) <= tol
        status = "ok" if shape == "line" and centred else "off"
        place = "middle" if centred else ("high" if level < 0.5 else "low")
        text = {"line": f"flat line, {place} ({level:.2f})", "wavy": f"wavy ({waviness:.2f}), {place}",
                "block": f"block ({thickness:.2f} thick)" if thickness > thin else "block (fills the screen)"}[shape]
        # Sure: how clearly past its thresholds, and how much of the screen shows a signal.
        if shape == "block":
            margin_of = max((thickness - thin) / thin, (filled - fill_limit) / fill_limit)
        else:
            margin_of = min((thin - thickness) / thin, (fill_limit - filled) / fill_limit, abs(waviness - flat) / flat)
        confidence = round(min(found if shape != "block" else 1.0, 0.5 + min(0.5, max(0.0, margin_of))), 2)
        y = level * (h - 1)
        marks: list[tuple[Any, ...]] = [
            ("line", [(left, y), (right, y)]),
            ("dash", [(0, (0.5 - tol) * h), (w, (0.5 - tol) * h)]),
            ("dash", [(0, (0.5 + tol) * h), (w, (0.5 + tol) * h)]),
        ]
        return Reading(
            status,
            text,
            {"shape": shape, "level": round(level, 3), "thickness": round(thickness, 3),
             "waviness": round(waviness, 3), "filled": round(filled), "found": round(found, 2)},
            confidence,
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
                x_mid_line = (x1 + x2) / 2
                near_edge = min(x_mid_line, w - x_mid_line) < self.inst.option("edge", 0.08) * w  # the meter's frame
                if angle <= 50 and not near_edge and (best is None or length > best[4]):
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
    """An analogue scope's spot: where it is, and whether it moved over the last `window` seconds by more than
    `still` (a fraction of the screen's width, default 0.1; the 15–85 % range of its positions, so a few odd
    frames don't count), or disappeared. `want` ("still", the default, or "moving") says which is `ok`.

    The spot is the brightest compact area above the screen's own background (a large median blur), away from
    the region's edges. How sure: how clearly the spot stands out, and how far its movement is from the limit.
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
        # Not at the region's edges: the bright bezel just outside the screen can outshine the spot there.
        edge_y, edge_x = (max(1, int(n * self.inst.option("margin", 0.08))) for n in excess.shape)
        excess[:edge_y], excess[-edge_y:], excess[:, :edge_x], excess[:, -edge_x:] = 0, 0, 0, 0
        peak = float(excess.max())
        now = time.time()
        window = self.inst.option("window", 10.0)
        while self.history and now - self.history[0][0] > window:
            self.history.popleft()
        want_still = self.inst.options.get("want", "still") == "still"
        gone_status = "off" if want_still else "unknown"
        if peak < self.MIN_CONTRAST:
            # The engine reads a covered screen as "covered?" before this; here the screen is clear and empty.
            return Reading(gone_status, "dot gone", {"gone": "yes", "contrast": round(peak, 1)},
                           round(min(1.0, 0.5 + (self.MIN_CONTRAST - peak) / self.MIN_CONTRAST), 2),
                           "nothing bright on the screen")
        _, labels, stats, centroids = cv2.connectedComponentsWithStats((excess >= 0.6 * peak).astype(np.uint8))
        py, px = np.unravel_index(int(np.argmax(excess)), excess.shape)
        label = int(labels[py, px])
        if int(stats[label, cv2.CC_STAT_AREA]) > 0.05 * gray.size:
            return Reading("unknown", "no dot", {"contrast": round(peak, 1)}, 0.2, "bright area too big for a dot")
        cx, cy = (float(v) for v in centroids[label])
        self.history.append((now, cx, cy))
        xs = np.array([p[1] for p in self.history])
        ys = np.array([p[2] for p in self.history])
        # The 15–85 % range, so a few frames that caught something else (a reflection, a hand, a cable
        # swinging past) don't count as the spot moving; a spot that wanders does.
        spread = float(max(np.subtract(*np.percentile(xs, [85, 15])), np.subtract(*np.percentile(ys, [85, 15])))) \
            if len(self.history) > 1 else 0.0
        limit = self.inst.option("still", 0.1) * gray.shape[1]
        moving = spread > limit
        marks: list[tuple[Any, ...]] = [("circle", (cx, cy), 6)]
        marks += [("point", (x, y)) for _, x, y in list(self.history)[-20:]]
        status = "ok" if moving != want_still else "off"
        share = spread / gray.shape[1]
        text = f"moving ({share:.0%} of the screen)" if moving else f"still ({spread:.1f} px in {window:.0f} s)"
        if len(self.history) < 3:
            status, text = "unknown", "watching…"
        seen = min(1.0, peak / (2 * self.MIN_CONTRAST))  # a spot twice the needed contrast is plainly there
        clear = min(1.0, abs(spread - limit) / limit)  # how far from the limit
        return Reading(
            status,
            text,
            {"x": round(cx, 1), "y": round(cy, 1), "spread_px": round(spread, 2), "limit_px": round(limit, 1),
             "contrast": round(peak, 1)},
            round(seen * (0.5 + 0.5 * clear), 2),
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
