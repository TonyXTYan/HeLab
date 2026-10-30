"""Labcam's detectors on drawn images and on a saved camera frame.

Run from side_projects/labcam with its own environment (`uv run pytest`). HeLab's own pytest collects this
file too and skips it, since HeLab's environment has no OpenCV.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

HOME = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOME))

from labcam import config, region  # noqa: E402
from labcam.detectors import Dot, Needle, TraceLevel  # noqa: E402
from labcam.wavemeter import digits_for, vote, with_point  # noqa: E402

SAMPLE = HOME / "tests" / "sample_mirrored.jpg"  # a camera frame, kept out of Git
needs_sample = pytest.mark.skipif(not SAMPLE.exists(), reason="no sample camera frame (tests/sample_mirrored.jpg)")


def inst(kind: str, **options: float) -> config.Instrument:
    return config.Instrument("x", kind, "x", config.rect_corners(0, 0, 100, 60), dict(options))


def screen(trace_y: int | None = None, background: int = 40, colour: int = 220) -> np.ndarray:
    image = np.full((60, 100, 3), background, np.uint8)
    if trace_y is not None:
        cv2.line(image, (0, trace_y), (99, trace_y), (colour, colour, colour), 2)
    return image


@pytest.mark.parametrize(("y", "status", "word"), [(30, "ok", "middle"), (8, "off", "high"), (52, "off", "low")])
def test_trace_level(y: int, status: str, word: str) -> None:
    reading = TraceLevel(inst("trace", tolerance=0.15)).update(screen(y))
    assert reading.status == status
    assert reading.text.startswith(word)
    assert reading.values["level"] == pytest.approx((y + 0.5) / 59, abs=0.03)


def test_trace_dark_on_light_and_missing() -> None:
    assert TraceLevel(inst("trace")).update(screen(30, background=200, colour=30)).status == "ok"
    assert TraceLevel(inst("trace")).update(screen(None)).status == "unknown"


def test_needle() -> None:
    meter = np.full((60, 100, 3), 235, np.uint8)
    cv2.line(meter, (75, 58), (80, 5), (20, 20, 20), 1)
    reading = Needle(inst("needle", tolerance=0.2)).update(meter)
    assert reading.status == "off"
    assert reading.values["offset"] == pytest.approx(0.55, abs=0.1)
    assert Needle(inst("needle")).update(np.full((60, 100, 3), 235, np.uint8)).status == "unknown"


def test_dot_still_then_moving() -> None:
    dot = Dot(inst("dot", still_px=2.0, window=60))

    def frame(x: int) -> np.ndarray:
        image = np.full((60, 100, 3), 120, np.uint8)
        cv2.circle(image, (x, 30), 2, (255, 255, 255), -1)
        return image

    for _ in range(4):
        reading = dot.update(frame(40))
    assert reading.status == "off" and reading.text.startswith("still")
    reading = dot.update(frame(60))
    assert reading.status == "ok" and reading.text.startswith("moving")
    assert dot.update(np.full((60, 100, 3), 120, np.uint8)).status == "unknown"


def test_wavemeter_digits_and_vote() -> None:
    assert digits_for("1083.482nm", "####.###") == "1083482"
    assert digits_for("103.482", "####.###") is None
    assert with_point("10?3482", "####.###") == "10?3.482"
    winner, shares = vote(["1083482", "1083422", "1083482"])
    assert winner == "1083482"
    assert shares[5] == pytest.approx(2 / 3)


def test_region_round_trip() -> None:
    r = region.make([(10, 10), (110, 20), (110, 80), (10, 70)])
    points = [(0.0, 0.0), (50.0, 30.0)]
    assert np.allclose(r.unmap(r.map(points)), points, atol=1e-6)
    image = np.zeros((100, 200, 3), np.uint8)
    assert region.cut(image, r, 2.0).shape[:2] == (r.height * 2, r.width * 2)


def test_config_corners_and_box(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        '{"instruments": {"a": {"kind": "dot", "box": [1, 2, 3, 4]},'
        ' "b": {"kind": "trace", "corners": [[0, 0], [5, 0], [5, 5], [0, 5]], "tolerance": 0.1}}}'
    )
    cfg = config.load(path)
    assert cfg.instruments["a"].corners == [(1, 2), (4, 2), (4, 6), (1, 6)]
    assert cfg.instruments["b"].option("tolerance", 0.5) == 0.1


@needs_sample
def test_sample_frame_scopes() -> None:
    """The saved frame (2026-10-30): both left scopes' traces sit near the middle of their screens."""
    frame = cv2.flip(cv2.imread(str(SAMPLE)), 1)
    cfg = config.load(HOME / "config.json")
    for name in ("left_top", "left_middle"):
        inst_ = cfg.instruments[name]
        reading = TraceLevel(inst_).update(region.cut(frame, region.make(inst_.corners)))
        assert reading.status == "ok", (name, reading)
        assert 0.4 < float(reading.values["level"] or 0) < 0.6


@needs_sample
def test_sample_frame_dot() -> None:
    frame = cv2.flip(cv2.imread(str(SAMPLE)), 1)
    inst_ = config.load(HOME / "config.json").instruments["scope_dot"]
    dot = Dot(inst_)
    cut = region.cut(frame, region.make(inst_.corners))
    for _ in range(3):
        reading = dot.update(cut)
        time.sleep(0.01)
    assert reading.status == "off"  # one frame again and again: still
    assert reading.values["x"] == pytest.approx(58, abs=4)
