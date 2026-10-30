"""Draws each instrument's region, reading and marks on the frame."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from .config import Corners
from .detectors import Image, Reading

# BGR
COLOURS = {"ok": (80, 200, 80), "off": (40, 160, 255), "unknown": (170, 170, 170)}
MARK = (255, 0, 255)
FONT = cv2.FONT_HERSHEY_SIMPLEX


@dataclass
class Item:
    label: str
    kind: str
    corners: Corners  # in the frame
    reading: Reading
    marks: list[tuple[Any, ...]]  # in the frame


def _p(point: tuple[float, float]) -> tuple[int, int]:
    return int(round(point[0])), int(round(point[1]))


def _poly(points: Corners) -> Any:
    return np.array([_p(p) for p in points], np.int32)


def _label(image: Image, text: str, x: int, y: int, colour: tuple[int, int, int],
           taken: list[tuple[int, int, int, int]] | None = None) -> None:
    """A label with its baseline at y; moved down past labels already in `taken`."""
    (w, h), base = cv2.getTextSize(text, FONT, 0.45, 1)
    x = min(max(0, x), image.shape[1] - w - 6)
    y = min(max(h + 4, y), image.shape[0] - 2)
    if taken is not None:
        while any(x < tx + tw and tx < x + w + 6 and y - h - 4 < ty + th and ty < y + base for tx, ty, tw, th in taken):
            y += h + 6
        taken.append((x, y - h - 4, w + 6, h + base + 4))
    cv2.rectangle(image, (x, y - h - 4), (x + w + 6, y + base - 2), (0, 0, 0), -1)
    cv2.putText(image, text, (x + 3, y - 3), FONT, 0.45, colour, 1, cv2.LINE_AA)


def _dashed(image: Image, a: tuple[float, float], b: tuple[float, float], colour: tuple[int, int, int]) -> None:
    length = max(1.0, float(np.hypot(b[0] - a[0], b[1] - a[1])))
    for start in np.arange(0, length, 6):
        t0, t1 = start / length, min(1.0, (start + 3) / length)
        p0 = (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0)
        p1 = (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)
        cv2.line(image, _p(p0), _p(p1), colour, 1)


def draw(frame: Image, items: list[Item], header: str) -> Image:
    out = frame.copy()
    taken: list[tuple[int, int, int, int]] = []
    for item in items:
        colour = COLOURS.get(item.reading.status, COLOURS["unknown"])
        if item.kind != "motion":
            cv2.polylines(out, [_poly(item.corners)], True, colour, 1, cv2.LINE_AA)
        for mark in item.marks:
            shape = mark[0]
            if shape in ("line", "loop"):
                cv2.polylines(out, [_poly(mark[1])], shape == "loop", MARK if shape == "line" else colour, 2, cv2.LINE_AA)
            elif shape == "dash":
                _dashed(out, mark[1][0], mark[1][1], colour)
            elif shape == "circle":
                cv2.circle(out, _p(mark[1]), int(mark[2]), MARK, 2, cv2.LINE_AA)
            elif shape == "point":
                cv2.circle(out, _p(mark[1]), 1, (255, 255, 0), -1)
        text = f"{item.label}: {item.reading.text}"
        if item.kind == "motion":
            _label(out, text, 8, out.shape[0] - 10, colour)
        else:
            xs = [p[0] for p in item.corners]
            ys = [p[1] for p in item.corners]
            top = min(ys)
            _label(out, text, int(min(xs)), int(max(ys) + 16 if top < 30 else top - 4), colour, taken)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    _label(out, f"{header}  {stamp}" if header else stamp, out.shape[1] - 330, out.shape[0] - 10, (255, 255, 255))
    return out
