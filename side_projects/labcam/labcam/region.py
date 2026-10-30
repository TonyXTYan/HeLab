"""An instrument's region in the current frame: four corners, cut out and straightened into a rectangle."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from .config import Corners, Point
from .detectors import Image


@dataclass
class Region:
    corners: Corners  # in the current frame
    width: int
    height: int
    to_frame: NDArray[np.float64]  # 3x3 homography, region → frame

    def map(self, points: Sequence[Point]) -> list[Point]:
        if not points:
            return []
        array = np.array(points, np.float64).reshape(-1, 1, 2)
        return [(float(x), float(y)) for x, y in cv2.perspectiveTransform(array, self.to_frame).reshape(-1, 2)]

    def unmap(self, points: Sequence[Point]) -> list[Point]:
        """Frame → region coordinates."""
        array = np.array(points, np.float64).reshape(-1, 1, 2)
        inverse = np.linalg.inv(self.to_frame)
        return [(float(x), float(y)) for x, y in cv2.perspectiveTransform(array, inverse).reshape(-1, 2)]

    def map_marks(self, marks: list[tuple[Any, ...]], scale: float = 1.0) -> list[tuple[Any, ...]]:
        """Marks from a region cut at `scale` → frame coordinates."""

        def to(points: Sequence[Point]) -> list[Point]:
            return self.map([(x / scale, y / scale) for x, y in points])

        out: list[tuple[Any, ...]] = []
        for mark in marks:
            if mark[0] in ("line", "loop", "dash"):
                out.append((mark[0], to(mark[1])))
            elif mark[0] == "circle":
                out.append(("circle", to([mark[1]])[0], mark[2] / scale))
            elif mark[0] == "point":
                out.append(("point", to([mark[1]])[0]))
        return out


def make(corners: Corners) -> Region:
    tl, tr, br, bl = corners
    width = max(2, int(round(max(math.dist(tl, tr), math.dist(bl, br)))))
    height = max(2, int(round(max(math.dist(tl, bl), math.dist(tr, br)))))
    target = np.array([(0, 0), (width - 1, 0), (width - 1, height - 1), (0, height - 1)], np.float32)
    to_frame = cv2.getPerspectiveTransform(target, np.array(corners, np.float32)).astype(np.float64)
    return Region(list(corners), width, height, to_frame)


def cut(frame: Image, region: Region, scale: float = 1.0) -> Image:
    """The region straightened to `width` x `height` times `scale` (outside the frame is black)."""
    to_frame = region.to_frame @ np.diag([1 / scale, 1 / scale, 1.0])
    size = (int(round(region.width * scale)), int(round(region.height * scale)))
    flags = (cv2.INTER_CUBIC if scale > 1 else cv2.INTER_LINEAR) | cv2.WARP_INVERSE_MAP
    return cv2.warpPerspective(frame, to_frame, size, flags=flags)
