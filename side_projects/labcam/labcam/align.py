"""Keeps the boxes on their instruments if the camera is nudged: each frame is matched to a reference frame.

ORB features on a half-size grey copy, a similarity transform (shift, turn, scale) by RANSAC. The boxes are
drawn in the reference frame's coordinates and moved by that transform. Too few matches means the camera
moved too far (or something blocks it): the last good transform is kept and the page says so.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from .config import Corners
from .detectors import Image

log = logging.getLogger("labcam.align")

SCALE = 0.5
MIN_INLIERS = 25


@dataclass
class Alignment:
    matrix: NDArray[np.float64]  # 2x3, reference → current frame
    inliers: int
    ok: bool
    note: str = ""

    @property
    def shift(self) -> tuple[float, float]:
        return float(self.matrix[0, 2]), float(self.matrix[1, 2])

    @property
    def angle(self) -> float:
        return math.degrees(math.atan2(self.matrix[1, 0], self.matrix[0, 0]))

    def move(self, corners: Corners) -> Corners:
        """Reference-frame points → current frame."""
        points = np.column_stack([np.array(corners, np.float64), np.ones(len(corners))])
        return [(float(x), float(y)) for x, y in points @ self.matrix.T]

    def back(self, corners: Corners) -> Corners:
        """Current-frame points → reference frame."""
        inverse = cv2.invertAffineTransform(self.matrix)
        points = np.column_stack([np.array(corners, np.float64), np.ones(len(corners))])
        return [(float(x), float(y)) for x, y in points @ inverse.T]


IDENTITY = Alignment(np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]), 0, True, "no reference frame yet")


class Aligner:
    def __init__(self) -> None:
        self.orb = cv2.ORB.create(nfeatures=1500)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        self.reference: Image | None = None
        self._ref_features: tuple[list[cv2.KeyPoint], Image] | None = None
        self.current = IDENTITY

    def set_reference(self, frame: Image) -> None:
        self.reference = frame.copy()
        self._ref_features = self._features(frame)
        self.current = Alignment(IDENTITY.matrix.copy(), len(self._ref_features[0]), True, "reference set")
        log.info("reference frame set (%d features)", len(self._ref_features[0]))

    def _features(self, frame: Image) -> tuple[list[cv2.KeyPoint], Image]:
        small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), None, fx=SCALE, fy=SCALE)
        keypoints, descriptors = self.orb.detectAndCompute(small, None)
        return list(keypoints), (descriptors if descriptors is not None else np.zeros((0, 32), np.uint8))

    def update(self, frame: Image) -> Alignment:
        if self._ref_features is None:
            return self.current
        ref_points, ref_desc = self._ref_features
        points, desc = self._features(frame)
        if len(points) < MIN_INLIERS or len(ref_points) < MIN_INLIERS:
            return self._lost(f"too few features ({len(points)})")
        matches = self.matcher.match(ref_desc, desc)
        if len(matches) < MIN_INLIERS:
            return self._lost(f"too few matches ({len(matches)})")
        src = np.array([ref_points[m.queryIdx].pt for m in matches], np.float32) / SCALE
        dst = np.array([points[m.trainIdx].pt for m in matches], np.float32) / SCALE
        matrix, inlier_mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0)
        inliers = int(inlier_mask.sum()) if inlier_mask is not None else 0
        if matrix is None or inliers < MIN_INLIERS:
            return self._lost(f"only {inliers} consistent matches")
        was_ok = self.current.ok
        self.current = Alignment(matrix.astype(np.float64), inliers, True)
        dx, dy = self.current.shift
        if not was_ok:
            log.info("alignment found again: shift %.1f, %.1f px, %d matches", dx, dy, inliers)
        if math.hypot(dx, dy) > 5:
            self.current.note = f"camera moved {dx:+.0f}, {dy:+.0f} px since the reference"
        return self.current

    def _lost(self, why: str) -> Alignment:
        if self.current.ok:
            log.warning("alignment lost: %s; keeping the last boxes", why)
        self.current = Alignment(self.current.matrix, 0, False, f"alignment lost: {why}")
        return self.current
