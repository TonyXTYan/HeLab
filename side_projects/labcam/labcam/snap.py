"""Snaps a screen's region to the screen's own edges, starting from rough corners.

From the inside out, along many short lines across each edge, the colour's distance from the screen's colour
(`background` when given, else the median of the region's middle) is followed; the first place it reaches
half its largest value on that line is the screen's edge. So
the edge found is the inner one: a shadow along the bezel, or the bezel itself, stays outside, and what the
screen shows (a trace, a block) doesn't count as long as it isn't on every line. Each side's points get a
robust line fit (a side turning more than MAX_TURN keeps its angle and moves by the median offset); adjacent
sides meet at the new corners.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from .config import Corners
from .detectors import Image

SAMPLES = 15  # lines across each side
REACH = 0.25  # how far a side may move, as a fraction of the region's smaller size
MAX_TURN = 4.0  # degrees a side may turn


@dataclass
class Snap:
    corners: Corners
    found: list[int]  # per side, how many of its lines found an edge
    moved: float  # largest corner move, px

    @property
    def ok(self) -> bool:
        return min(self.found) >= SAMPLES // 2


def _line_intersection(a: tuple[np.ndarray, np.ndarray], b: tuple[np.ndarray, np.ndarray]) -> np.ndarray | None:
    (p, d), (q, e) = a, b
    m = np.array([d, -e]).T
    if abs(np.linalg.det(m)) < 1e-9:
        return None
    t, _ = np.linalg.solve(m, q - p)
    point: np.ndarray = p + t * d
    return point


def snap(frame: Image, corners: Corners, background: list[float] | None = None, min_jump: float = 25.0) -> Snap:
    pts = np.array(corners, np.float64)
    centre = pts.mean(axis=0)
    sides = [math.dist(corners[i], corners[(i + 1) % 4]) for i in range(4)]
    reach = REACH * min(sides)
    lab = cv2.GaussianBlur(frame, (3, 3), 0).astype(np.float32)
    h, w = lab.shape[:2]

    if background is not None:
        screen = np.array(background, np.float32)
    else:
        inner = (centre + (pts - centre) * 0.5).astype(np.float32)
        mask = np.zeros((h, w), np.uint8)
        cv2.fillPoly(mask, [np.round(inner).astype(np.int32)], 255)
        screen = np.median(lab[mask > 0], axis=0)

    def colour_at(xy: np.ndarray) -> np.ndarray | None:
        x, y = int(round(xy[0])), int(round(xy[1]))
        if 0 <= x < w and 0 <= y < h:
            value: np.ndarray = lab[y, x]
            return value
        return None

    lines: list[tuple[np.ndarray, np.ndarray] | None] = []
    found: list[int] = []
    for i in range(4):
        a, b = pts[i], pts[(i + 1) % 4]
        along = (b - a) / max(1e-9, np.linalg.norm(b - a))
        normal = np.array([along[1], -along[0]])
        if np.dot(normal, centre - (a + b) / 2) > 0:  # point outwards
            normal = -normal
        hits, offsets = [], []
        for t in np.linspace(0.15, 0.85, SAMPLES):
            base = a + (b - a) * t
            # The colour's distance from the screen's along a short line across the side, inside to outside.
            steps = np.arange(-reach, reach, 0.5)
            profile = []
            for s in steps:
                c = colour_at(base + normal * s)
                profile.append(np.nan if c is None else float(np.abs(c - screen).max()))
            d = np.array(profile)
            if np.isnan(d).any() or d.max() < min_jump:
                continue
            # The edge: the first place, from inside, where the distance reaches half its largest value along
            # the line and stays there for 2 px. Whatever lies beyond (a shadow, the bezel) is then outside.
            level = max(min_jump, 0.5 * float(d.max()))
            over = d >= level
            run = np.convolve(over.astype(int), np.ones(4, int), "valid") == 4
            first = int(np.argmax(run)) if run.any() else -1
            if first <= 0 or d[: max(1, first // 2)].mean() > 0.5 * level:  # starts unlike the screen: no edge here
                continue
            hits.append(base + normal * (steps[first] - 0.5))
            offsets.append(steps[first] - 0.5)
        found.append(len(hits))
        if len(hits) >= SAMPLES // 2:
            vx, vy, x0, y0 = cv2.fitLine(np.array(hits, np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
            direction = np.array([vx, vy], np.float64)
            turn = math.degrees(math.acos(min(1.0, abs(float(np.dot(direction, along))))))
            if turn > MAX_TURN:
                # Too steep a change for a camera that hasn't moved: keep the side's angle, move it by the
                # median offset (a shadow or reflection along part of a side tilts a free fit).
                lines.append((a + normal * float(np.median(offsets)), along))
            else:
                lines.append((np.array([x0, y0], np.float64), direction))
        else:
            lines.append(None)
    new = []
    for i in range(4):
        before, after = lines[(i - 1) % 4], lines[i]  # corner i joins side i-1 and side i
        point = _line_intersection(before, after) if before is not None and after is not None else None
        new.append(pts[i] if point is None else point)
    moved = max(math.dist(tuple(p), tuple(q)) for p, q in zip(pts, new))
    return Snap([(round(float(x), 1), round(float(y), 1)) for x, y in new], found, round(moved, 1))
