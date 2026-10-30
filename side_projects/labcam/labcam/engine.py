"""The watcher: takes the newest frame, runs the checks when due, draws the overlay, keeps state and logs."""

from __future__ import annotations

import csv
import logging
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np

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
DATA = HOME / "data"


class Engine:
    def __init__(self, config: Config, source: FrameSource) -> None:
        self.config = config
        self.source = source
        self.aligner = Aligner()
        self.detectors = {name: KINDS[inst.kind](inst) for name, inst in config.instruments.items()}
        self.readings: dict[str, Reading] = {}
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
        self._csv_day = ""
        self._csv: Any = None
        self._csv_writer: Any = None
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
        for name, detector in self.detectors.items():
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
        self._record(now)

    def _run_slow(self, name: str, detector: Detector, frame: Image, region: regions.Region) -> None:
        try:
            self._run_detector(name, detector, frame, region)
        finally:
            self._slow_busy.clear()

    def _run_detector(self, name: str, detector: Detector, frame: Image, region: regions.Region) -> None:
        t = time.monotonic()
        try:
            reading = detector.update(regions.cut(frame, region, detector.oversample))
            self.marks[name] = region.map_marks(reading.marks, detector.oversample)
        except Exception as exc:
            note = f"{type(exc).__name__}: {exc}"
            previous_note = self.readings[name].note if name in self.readings else ""
            if note != previous_note:  # once per distinct error, not every analysis
                log.exception("%s failed", name)
            reading = Reading("unknown", "error", note=note)
        self.timings[f"{name}_ms"] = (time.monotonic() - t) * 1000
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

    def _record(self, now: float) -> None:
        """One CSV row per analysis: data/readings-<date>.csv."""
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        names = list(self.config.instruments)
        if day != self._csv_day:
            if self._csv is not None:
                self._csv.close()
            DATA.mkdir(exist_ok=True)
            path = DATA / f"readings-{day}.csv"
            new = not path.exists()
            self._csv = path.open("a", newline="", encoding="utf-8")
            self._csv_writer = csv.writer(self._csv)
            if new:
                self._csv_writer.writerow(["time"] + [f"{n}_{c}" for n in names for c in ("status", "text")])
            self._csv_day = day
        row = [time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now))]
        for n in names:
            r = self.readings.get(n)
            row += [r.status, r.text] if r else ["", ""]
        self._csv_writer.writerow(row)
        self._csv.flush()

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
            "analyses": self.analysis_count,
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


def latest_csv() -> Path | None:
    files = sorted(DATA.glob("readings-*.csv"))
    return files[-1] if files else None
