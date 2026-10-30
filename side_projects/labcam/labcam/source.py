"""Frames from the camera: an MJPEG stream over HTTP (kept latest-only), or a still image for testing."""

from __future__ import annotations

import logging
import threading
import time
import urllib.request
from pathlib import Path

log = logging.getLogger("labcam.source")

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"
MAX_BUFFER = 8_000_000


class FrameSource:
    """Keeps the newest JPEG from the source; `latest()` never waits on the network."""

    def __init__(self, source: str) -> None:
        self.source = source
        self._jpeg: bytes | None = None
        self._seq = 0
        self._at = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.frames_received = 0
        self.connected = False
        self.error = ""
        self._thread = threading.Thread(target=self._run, name="labcam-source", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def latest(self) -> tuple[int, float, bytes | None]:
        """(sequence number, time received, JPEG bytes) of the newest frame."""
        with self._lock:
            return self._seq, self._at, self._jpeg

    def _put(self, jpeg: bytes) -> None:
        with self._lock:
            self._jpeg = jpeg
            self._seq += 1
            self._at = time.time()
        self.frames_received += 1

    def _run(self) -> None:
        if not self.source.startswith(("http://", "https://")):
            self._still(Path(self.source))
            return
        delay = 1.0
        while not self._stop.is_set():
            try:
                self._read_stream()
                delay = 1.0
            except Exception as exc:  # network errors of every kind: retry with backoff
                if self.connected or self.error != str(exc):
                    log.warning("stream %s lost: %s (retrying in %.0f s)", self.source, exc, delay)
                self.connected = False
                self.error = str(exc)
                self._stop.wait(delay)
                delay = min(delay * 2, 30.0)

    def _read_stream(self) -> None:
        with urllib.request.urlopen(self.source, timeout=10) as response:
            log.info("connected to %s", self.source)
            self.connected = True
            self.error = ""
            buffer = b""
            while not self._stop.is_set():
                chunk = response.read1(65536)
                if not chunk:
                    raise ConnectionError("stream ended")
                buffer += chunk
                # Keep only complete JPEGs; the newest wins.
                while True:
                    start = buffer.find(SOI)
                    if start < 0:
                        buffer = b""
                        break
                    end = buffer.find(EOI, start + 2)
                    if end < 0:
                        buffer = buffer[start:]
                        break
                    self._put(buffer[start : end + 2])
                    buffer = buffer[end + 2 :]
                if len(buffer) > MAX_BUFFER:
                    log.warning("dropping %d bytes without a complete JPEG", len(buffer))
                    buffer = b""

    def _still(self, path: Path) -> None:
        """A JPEG file, offered again every second (for testing without the camera)."""
        data = path.read_bytes()
        self.connected = True
        log.info("using still image %s", path)
        while not self._stop.is_set():
            self._put(data)
            self._stop.wait(1.0)
