"""The watcher: takes the newest frame, runs the checks when due, draws the overlay, keeps state and logs."""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from . import history
from . import locks as locks_module
from .align import Aligner
from . import region as regions
from .config import HOME, Config, Corners
from .detectors import Detector, Dot, Image, Motion, Needle, Reading, TraceLevel
from .overlay import Item, draw
from .source import FrameSource
from .wavemeter import Wavemeter

log = logging.getLogger("labcam.engine")

KINDS: dict[str, type[Detector]] = {
    "trace": TraceLevel,
    "needle": Needle,
    "dot": Dot,
    "motion": Motion,
    "wavemeter": Wavemeter,
}
ALIGN_EVERY = 5.0  # s
LOCK_SETTLE = 3
LOCK_AFTER = 10.0  # s
COVER_ACCEPT = 600.0  # s: surroundings changed this long become the usual ones
COVER_PAD = 10.0  # px around a moving area that still counts as in front of an instrument


def _ring(frame: Image, corners: Corners, size: tuple[int, int] = (64, 48)) -> Any:
    """The band around a region: the region grown by 25 % about its centre, straightened to `size`, grey,
    without its middle 80 % (the region itself), with its mean taken off so a change of light overall doesn't
    count. None if it falls outside the frame."""
    points = np.array(corners, np.float64)
    centre = points.mean(axis=0)
    outer = [(float(x), float(y)) for x, y in centre + (points - centre) * 1.25]
    h, w = frame.shape[:2]
    if min(min(p) for p in outer) < 0 or max(p[0] for p in outer) >= w or max(p[1] for p in outer) >= h:
        return None
    grey = cv2.cvtColor(cv2.resize(regions.cut(frame, regions.make(outer)), size), cv2.COLOR_BGR2GRAY).astype(np.float32)
    keep = np.ones(grey.shape, bool)
    dy, dx = int(size[1] * 0.1), int(size[0] * 0.1)
    keep[dy:-dy, dx:-dx] = False
    band = grey[keep]
    return band - band.mean()


class Engine:
    def __init__(self, config: Config, source: FrameSource) -> None:
        self.config = config
        self.source = source
        self.aligner = Aligner()
        self.detectors = {name: KINDS[inst.kind](inst) for name, inst in config.instruments.items()}
        self.readings: dict[str, Reading] = {}
        self.raw_readings: dict[str, Reading] = {}  # before the status debounce; locks read these
        self.covered: dict[str, str] = {}  # instrument → why it may be hidden this analysis
        self.surround_change: dict[str, float] = {}
        self._usual_rings: dict[str, Any] = {}
        self._covered_since: dict[str, float] = {}
        self.regions: dict[str, regions.Region] = {}
        self.marks: dict[str, list[tuple[Any, ...]]] = {}
        self.overlay_jpeg: bytes | None = None
        self.raw_frame: Image | None = None
        self.frame_seq = 0
        self.changed = threading.Condition()
        self.timings: dict[str, float] = {}
        self.analysis_count = 0
        self._last_analysis = 0.0
        self._last_align = 0.0
        self._last_slow: dict[str, float] = {}
        self._slow_busy = threading.Event()
        self._streaks: dict[str, tuple[str, int]] = {}
        self._reference_wanted = not self._load_reference()
        self._stop = threading.Event()
        self.locks: dict[str, locks_module.Lock] = {}
        self._lock_streaks: dict[str, tuple[str, int, float]] = {}
        self.recorder = history.Recorder()
        self._thread = threading.Thread(target=self._run, name="labcam-engine", daemon=True)

    # Reference frame -----------------------------------------------------------------------------------

    def _load_reference(self) -> bool:
        path = HOME / "reference.jpg"
        if not path.exists():
            return False
        image = cv2.imread(str(path))
        if image is None:
            log.warning("reference.jpg unreadable; a new one will be taken")
            return False
        self.aligner.set_reference(image)
        return True

    def set_reference(self) -> str:
        """Makes the current frame the reference (the boxes are kept as drawn on it)."""
        frame = self.raw_frame
        if frame is None:
            return "no frame yet"
        cv2.imwrite(str(HOME / "reference.jpg"), frame)
        self.aligner.set_reference(frame)
        return "reference frame set"

    # Boxes ---------------------------------------------------------------------------------------------

    def set_corners(self, name: str, corners: Corners) -> None:
        """`corners` in the current frame; stored in the reference frame's coordinates."""
        stored = self.aligner.current.back(corners)
        self.config.set_corners(name, stored)
        self.detectors[name].reset()
        log.info("region of %s set to %s (reference frame)", name, [(round(x), round(y)) for x, y in stored])

    # Loop ----------------------------------------------------------------------------------------------

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        seen = 0
        while not self._stop.is_set():
            started = time.monotonic()
            seq, _, jpeg = self.source.latest()
            if jpeg is not None and seq != seen:
                seen = seq
                try:
                    self._frame(jpeg)
                except Exception:
                    log.exception("frame %d failed", seq)
            wait = 1.0 / max(0.2, self.config.stream_fps) - (time.monotonic() - started)
            self._stop.wait(max(0.01, wait))

    def _frame(self, jpeg: bytes) -> None:
        t0 = time.monotonic()
        frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            log.warning("undecodable frame (%d bytes)", len(jpeg))
            return
        if self.config.mirror:
            frame = cv2.flip(frame, 1)
        self.raw_frame = frame
        self.timings["decode_ms"] = (time.monotonic() - t0) * 1000
        if self._reference_wanted:
            self.set_reference()
            self._reference_wanted = False
        now = time.time()
        if now - self._last_analysis >= 1.0 / max(0.05, self.config.analysis_hz):
            self._last_analysis = now
            self._analyse(frame, now)
        t1 = time.monotonic()
        items = [
            Item(self.config.instruments[n].label, self.config.instruments[n].kind, self.regions[n].corners, r,
                 self.marks.get(n, []))
            for n, r in self.readings.items()
            if n in self.regions
        ]
        alignment = self.aligner.current
        header = "ALIGNMENT LOST" if not alignment.ok else ("" if not alignment.note else "camera moved")
        image = draw(frame, items, header)
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, self.config.jpeg_quality])
        self.timings["draw_ms"] = (time.monotonic() - t1) * 1000
        if ok:
            with self.changed:
                self.overlay_jpeg = encoded.tobytes()
                self.frame_seq += 1
                self.changed.notify_all()

    def _analyse(self, frame: Image, now: float) -> None:
        t0 = time.monotonic()
        if now - self._last_align >= ALIGN_EVERY:
            self._last_align = now
            self.aligner.update(frame)
            self.timings["align_ms"] = (time.monotonic() - t0) * 1000
        alignment = self.aligner.current
        with self.config.lock:
            instruments = dict(self.config.instruments)
        self.regions = {name: regions.make(alignment.move(inst.corners)) for name, inst in instruments.items()}
        for name, detector in self.detectors.items():
            if isinstance(detector, Motion):
                own = self.regions[name]
                detector.ignore = [own.unmap(r.corners) for n, r in self.regions.items() if n != name]
        # Movement first: the other instruments use it to tell when someone is in front of them.
        order = sorted(self.detectors.items(), key=lambda item: not isinstance(item[1], Motion))
        self.covered = {}
        for name, detector in order:
            if not isinstance(detector, Motion):
                why = self._cover(frame, name)
                if why:
                    self.covered[name] = why
            if isinstance(detector, Wavemeter):
                # OCR is slow: it runs on its own thread, one field at a time, so the overlay keeps moving.
                due = now - self._last_slow.get(name, 0.0) >= self.config.instruments[name].option("every", 2.0)
                if due and not self._slow_busy.is_set():
                    self._last_slow[name] = now
                    self._slow_busy.set()
                    threading.Thread(target=self._run_slow, args=(name, detector, frame, self.regions[name]),
                                     name="labcam-ocr", daemon=True).start()
                continue
            self._run_detector(name, detector, frame, self.regions[name])
        self.analysis_count += 1
        self.timings["analysis_ms"] = (time.monotonic() - t0) * 1000
        self._update_locks()
        self.recorder.record(now, self.config.instruments, self.readings, self.locks)

    def _cover(self, frame: Image, name: str) -> str:
        """Why the instrument may be hidden right now ("" if it isn't): movement over its region, or its
        surroundings (the frame around the screen, which doesn't change by itself) unlike the reference's."""
        region = self.regions[name]
        polygon = np.array(region.corners, np.float32)
        area = max(1.0, abs(cv2.contourArea(polygon)))
        for mark in self.marks.get("people", []) if self.readings.get("people", None) else []:
            if mark[0] != "loop":
                continue
            box = np.array(mark[1], np.float32)
            x0, y0 = box.min(axis=0) - COVER_PAD
            x1, y1 = box.max(axis=0) + COVER_PAD
            clipped = polygon.copy()
            clipped[:, 0] = clipped[:, 0].clip(x0, x1)
            clipped[:, 1] = clipped[:, 1].clip(y0, y1)
            if abs(cv2.contourArea(clipped)) / area > 0.15:
                return "movement in front"
        # Compared with this instrument's usual surroundings: a running average of its band, updated while
        # nothing is in front, so slow changes (light, a cable moved for good) don't count but a hand does.
        inst = self.config.instruments[name]
        ring = _ring(frame, region.corners)
        if ring is None:
            return ""
        usual = self._usual_rings.get(name)
        if usual is None:
            self._usual_rings[name] = ring
            return ""
        change = float(np.mean(np.abs(ring - usual)))
        self.surround_change[name] = round(change, 1)
        now = time.time()
        if change > inst.option("cover_change", 15.0):
            since = self._covered_since.setdefault(name, now)
            if now - since > COVER_ACCEPT:
                log.info("%s: surroundings changed for %.0f min; taking them as the new usual", name, COVER_ACCEPT / 60)
                self._usual_rings[name] = ring
                self._covered_since.pop(name, None)
                return ""
            return f"its surroundings changed ({change:.0f}): something in front?"
        self._covered_since.pop(name, None)
        self._usual_rings[name] = 0.95 * usual + 0.05 * ring
        return ""

    def _run_slow(self, name: str, detector: Detector, frame: Image, region: regions.Region) -> None:
        try:
            self._run_detector(name, detector, frame, region)
        finally:
            self._slow_busy.clear()

    def _run_detector(self, name: str, detector: Detector, frame: Image, region: regions.Region) -> None:
        t = time.monotonic()
        covered = self.covered.get(name, "")
        try:
            reading = detector.update(regions.cut(frame, region, detector.oversample))
            if covered and reading.status != "unknown":
                reading = dataclasses.replace(reading, status="unknown", text=f"covered? ({reading.text})",
                                              note=covered, confidence=0.0)
            self.marks[name] = region.map_marks(reading.marks, detector.oversample)
        except Exception as exc:
            note = f"{type(exc).__name__}: {exc}"
            previous_note = self.readings[name].note if name in self.readings else ""
            if note != previous_note:  # once per distinct error, not every analysis
                log.exception("%s failed", name)
            reading = Reading("unknown", "error", note=note)
        self.timings[f"{name}_ms"] = (time.monotonic() - t) * 1000
        self.raw_readings[name] = dataclasses.replace(reading)
        previous = self.readings.get(name)
        # A new status counts only after `settle` analyses in a row (default 3): a flickering signal
        # keeps its status, with a note, instead of flipping it and the log every half second.
        settle = int(self.config.instruments[name].option("settle", 3))
        streak_status, streak = self._streaks.get(name, ("", 0))
        streak = streak + 1 if reading.status == streak_status else 1
        self._streaks[name] = (reading.status, streak)
        if previous is not None and reading.status != previous.status and streak < settle:
            reading.note = (f"{reading.note}; " if reading.note else "") + f"{reading.status} {streak}/{settle}, still shown as {previous.status}"
            reading.status = previous.status
        if previous is None or previous.status != reading.status:
            level = logging.WARNING if reading.status == "off" else logging.INFO
            log.log(level, "%s: %s → %s (%s)%s", name, previous.status if previous else "start", reading.status,
                    reading.text, f"; {reading.note}" if reading.note else "")
        self.readings[name] = reading

    # Output --------------------------------------------------------------------------------------------

    def _update_locks(self) -> None:
        """Each laser's lock from its signs. `lost` and `unknown` count after LOCK_SETTLE analyses in a row;
        `locked` only after every sign has held for LOCK_AFTER seconds, so a lock signal passing through a
        flat moment isn't taken for a lock."""
        now = time.time()
        for laser, specs in self.config.locks.items():
            lock = locks_module.evaluate(specs, self.config.instruments, self.raw_readings)
            previous = self.locks.get(laser)
            hidden = [self.config.instruments[s.split(":")[0]].label for s in specs if s.split(":")[0] in self.covered]
            if lock.state == "unknown" and hidden and previous is not None and previous.state != "unknown":
                # Someone in front: keep what was last seen rather than call it lost or unknown.
                lock = locks_module.Lock(previous.state, round(previous.confidence * 0.5, 2), lock.signs,
                                         held=f"{previous.state} before; now covered: {', '.join(hidden)}")
            streak_state, streak, since = self._lock_streaks.get(laser, ("", 0, now))
            if lock.state == streak_state:
                streak += 1
            else:
                streak, since = 1, now
            self._lock_streaks[laser] = (lock.state, streak, since)
            if previous is None and lock.state == "locked":
                lock = locks_module.Lock("unknown", 0.0, lock.signs)  # locked only after LOCK_AFTER, from the start too
            if previous is not None and lock.state != previous.state:
                waiting = (now - since < LOCK_AFTER) if lock.state == "locked" else (streak < LOCK_SETTLE)
                if waiting:
                    lock = locks_module.Lock(previous.state, previous.confidence, lock.signs)
            if previous is None or previous.state != lock.state:
                level = logging.WARNING if lock.state == "lost" else logging.INFO
                log.log(level, "%s %s (sure %.0f%%): %s", laser, lock.state.upper(), lock.confidence * 100, lock.summary)
            self.locks[laser] = lock

    def state(self) -> dict[str, Any]:
        alignment = self.aligner.current
        _, at, _ = self.source.latest()
        return {
            "now": time.time(),
            "source": {
                "url": self.source.source,
                "connected": self.source.connected,
                "error": self.source.error,
                "frames": self.source.frames_received,
                "last_frame_age": round(time.time() - at, 2) if at else None,
            },
            "alignment": {
                "ok": alignment.ok,
                "inliers": alignment.inliers,
                "shift": [round(v, 1) for v in alignment.shift],
                "angle": round(alignment.angle, 2),
                "note": alignment.note,
            },
            "covered": self.covered,
            "surround_change": self.surround_change,
            "analyses": self.analysis_count,
            "locks": {
                laser: {"state": lock.state, "confidence": lock.confidence, "why": lock.summary,
                        "signs": [{"sign": s.name, "holds": s.holds, "why": s.why} for s in lock.signs]}
                for laser, lock in self.locks.items()
            },
            "timings_ms": {k: round(v, 1) for k, v in self.timings.items()},
            "instruments": {
                name: {
                    "label": inst.label,
                    "kind": inst.kind,
                    "corners": [[round(x, 1), round(y, 1)] for x, y in
                                (self.regions[name].corners if name in self.regions else inst.corners)],
                    "reading": {k: v for k, v in asdict(self.readings[name]).items() if k != "marks"}
                    if name in self.readings
                    else None,
                }
                for name, inst in self.config.instruments.items()
            },
        }


def latest_csv(kind: str = "history") -> Path | None:
    found = [p for p in history.files(kind) if p.suffix == ".csv"]
    return found[-1] if found else None
