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

from labcam import config, history, locks, region  # noqa: E402
from labcam.detectors import Dot, Needle, Reading, TraceLevel  # noqa: E402
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
    assert word in reading.text
    assert reading.values["shape"] == "line"
    assert reading.values["level"] == pytest.approx((y + 0.5) / 59, abs=0.03)


def test_trace_block_and_wavy() -> None:
    block = screen(None)
    cv2.rectangle(block, (0, 15), (99, 45), (220, 220, 220), -1)
    reading = TraceLevel(inst("trace")).update(block)
    assert reading.values["shape"] == "block" and reading.status == "off"
    wavy = screen(None)
    points = np.array([(x, int(30 + 20 * np.sin(x / 6))) for x in range(100)], np.int32)
    cv2.polylines(wavy, [points], False, (220, 220, 220), 2)
    assert TraceLevel(inst("trace")).update(wavy).values["shape"] == "wavy"


def test_locks() -> None:
    instruments = {
        "top": config.Instrument("top", "trace", "Top", config.rect_corners(0, 0, 1, 1), {}),
        "dot": config.Instrument("dot", "dot", "Dot", config.rect_corners(0, 0, 1, 1), {}),
        "needle": config.Instrument("needle", "needle", "Needle", config.rect_corners(0, 0, 1, 1), {"tolerance": 0.2}),
    }
    readings = {
        "top": Reading("ok", "flat line", {"shape": "line", "level": 0.5}, 0.9),
        "dot": Reading("ok", "still", {"spread_px": 0.5, "limit_px": 10.0}, 0.8),
        "needle": Reading("ok", "middle", {"offset": 0.05}, 0.7),
    }
    specs = ["top:flat", "dot:still", "needle:middle"]
    lock = locks.evaluate(specs, instruments, readings)
    assert (lock.state, lock.confidence) == ("locked", 0.7)
    readings["top"] = Reading("off", "block", {"shape": "block"}, 0.95)
    lock = locks.evaluate(specs, instruments, readings)
    assert (lock.state, lock.confidence) == ("lost", 0.95) and "block" in lock.summary
    readings["top"] = Reading("unknown", "no signal", {"shape": "none"}, 0.5)
    assert locks.evaluate(specs, instruments, readings).state == "unknown"


def test_history_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(history, "DATA", tmp_path)
    instruments = {"top": config.Instrument("top", "trace", "Top", config.rect_corners(0, 0, 1, 1), {})}
    recorder = history.Recorder()
    for shape in ("line", "block"):
        readings = {"top": Reading("ok", shape, {"shape": shape, "level": 0.5, "thickness": 0.05}, 0.9)}
        lock = locks.evaluate(["top:flat"], instruments, readings)
        recorder.record(time.time(), instruments, readings, {"He3": lock})
    data = history.series(1)
    assert data["rows"] == 2
    assert data["columns"]["He3"] == ["locked", "lost"]
    assert data["columns"]["top.thickness"] == [0.05, 0.05]
    assert (tmp_path / f"locks-{time.strftime('%Y-%m-%d')}.csv").exists()


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
    dot = Dot(inst("dot", still=0.1, window=60))

    def frame(x: int) -> np.ndarray:
        image = np.full((60, 100, 3), 120, np.uint8)
        cv2.circle(image, (x, 30), 2, (255, 255, 255), -1)
        return image

    for _ in range(4):
        reading = dot.update(frame(40))
    assert reading.status == "ok" and reading.text.startswith("still")  # still is what's wanted by default
    reading = dot.update(frame(60))
    assert reading.status == "ok"  # one odd position is outvoted
    for _ in range(3):
        reading = dot.update(frame(60))
    assert reading.status == "off" and reading.text.startswith("moving")  # 20 px of a 100 px screen
    gone = dot.update(np.full((60, 100, 3), 120, np.uint8))
    assert gone.status == "off" and gone.text == "dot gone"


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
    assert reading.status == "ok"  # one frame again and again: still
    assert reading.values["x"] == pytest.approx(58, abs=4)


@needs_sample
def test_hand_in_front_holds_the_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A hand over the left top scope: it reads "covered?", and He4 keeps its last state, said so."""
    from unittest import mock

    from labcam import engine
    from labcam.source import FrameSource

    monkeypatch.setattr(history, "DATA", tmp_path)
    cfg = config.load(HOME / "config.json")
    cfg.analysis_hz = 100
    eng = engine.Engine(cfg, FrameSource(str(SAMPLE)))
    frame = cv2.imread(str(SAMPLE))
    hand = cv2.flip(frame, 1)
    corners = np.array(cfg.instruments["left_top"].corners)
    cx, cy = corners.mean(axis=0).astype(int)
    cv2.ellipse(hand, (int(cx) - 25, int(cy) + 20), (45, 60), 20, 0, 360, (120, 150, 200), -1)
    hand = cv2.flip(hand, 1)  # back to the camera's mirrored view
    clock = [time.time()]
    with mock.patch("time.time", lambda: clock[0]):
        for image, frames in ((frame, 40), (hand, 6)):
            jpeg = cv2.imencode(".jpg", image)[1].tobytes()
            for _ in range(frames):
                eng._frame(jpeg)
                clock[0] += 0.5
            if image is frame:
                he4 = eng.locks["He4"].state
    assert "left_top" in eng.covered
    assert eng.readings["left_top"].status == "unknown"
    assert eng.locks["He4"].state == he4 and "covered" in eng.locks["He4"].summary


def test_history_thins_rows_and_reads_gzip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import gzip

    monkeypatch.setattr(history, "DATA", tmp_path)
    instruments = {"top": config.Instrument("top", "trace", "Top", config.rect_corners(0, 0, 1, 1), {})}
    line = {"top": Reading("ok", "line", {"shape": "line", "level": 0.5}, 0.9)}
    block = {"top": Reading("off", "block", {"shape": "block"}, 0.9)}
    recorder = history.Recorder()
    start = time.time() - 60
    for i in range(20):  # 0.5 s apart: rows at 0, 5 s and the lock change at 7 s
        readings = block if i == 14 else line
        recorder.record(start + i * 0.5, instruments, readings,
                        {"He3": locks.evaluate(["top:flat"], instruments, readings)})
    data = history.series(1)
    assert data["columns"]["He3"] == ["locked", "locked", "lost", "locked"]
    # An earlier day's file, gzipped, is read too.
    old = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    with gzip.open(tmp_path / f"history-{old}.csv.gz", "wt", encoding="utf-8") as f:
        f.write("time,He3\n" + time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 3600 * 20)) + ",lost\n")
    assert history.series(24)["rows"] == 5


def test_old_days_deleted_and_compressed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import gzip

    monkeypatch.setattr(history, "DATA", tmp_path)
    day = lambda n: time.strftime("%Y-%m-%d", time.localtime(time.time() - n * 86400))  # noqa: E731
    (tmp_path / f"history-{day(0)}.csv").write_text("time\n")
    (tmp_path / f"history-{day(2)}.csv").write_text("time\nx\n")
    (tmp_path / f"locks-{day(9)}.csv.gz").write_bytes(gzip.compress(b"time\n"))
    history.compress_old()
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [f"history-{day(0)}.csv", f"history-{day(2)}.csv.gz"])
