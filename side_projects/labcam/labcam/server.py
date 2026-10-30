"""HTTP: `/` the page, `/stream` the overlay as MJPEG, `/frame.jpg` one overlay frame, `/raw.jpg` the
un-mirrored camera frame, `/state.json` every reading, `/log` the recent log, `/readings.csv` today's data;
POST `/api/region` {name, corners} and `/api/reference` change the boxes and the reference frame."""

from __future__ import annotations

import collections
import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any

import cv2
import numpy as np

from .engine import Engine, latest_csv

log = logging.getLogger("labcam.server")


class RingHandler(logging.Handler):
    """The last `size` log lines, for the page."""

    def __init__(self, size: int = 500) -> None:
        super().__init__()
        self.lines: collections.deque[tuple[int, str]] = collections.deque(maxlen=size)
        self.seq = 0
        self._lock2 = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        line = self.format(record)
        with self._lock2:
            self.seq += 1
            self.lines.append((self.seq, line))

    def since(self, seq: int) -> list[tuple[int, str]]:
        with self._lock2:
            return [item for item in self.lines if item[0] > seq]


def make_handler(engine: Engine, ring: RingHandler) -> type[BaseHTTPRequestHandler]:
    page = resources.files("labcam").joinpath("page.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:
            log.debug("%s %s", self.address_string(), format % args)

        def _send(self, body: bytes, kind: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data: Any, status: int = 200) -> None:
            self._send(json.dumps(data).encode(), "application/json", status)

        def do_GET(self) -> None:
            path, _, query = self.path.partition("?")
            if path in ("/", "/index.html"):
                self._send(page, "text/html; charset=utf-8")
            elif path == "/state.json":
                self._json(engine.state())
            elif path == "/log":
                after = int(query.split("after=")[1]) if "after=" in query else 0
                self._json(ring.since(after))
            elif path == "/frame.jpg":
                if engine.overlay_jpeg is None:
                    self._send(b"no frame yet", "text/plain", HTTPStatus.SERVICE_UNAVAILABLE)
                else:
                    self._send(engine.overlay_jpeg, "image/jpeg")
            elif path == "/raw.jpg":
                frame = engine.raw_frame
                ok, data = cv2.imencode(".jpg", frame) if frame is not None else (False, None)
                if ok and data is not None:
                    self._send(data.tobytes(), "image/jpeg")
                else:
                    self._send(b"no frame yet", "text/plain", HTTPStatus.SERVICE_UNAVAILABLE)
            elif path == "/readings.csv":
                csv_path = latest_csv()
                if csv_path is None:
                    self._send(b"no readings yet", "text/plain", HTTPStatus.NOT_FOUND)
                else:
                    self._send(csv_path.read_bytes(), "text/csv")
            elif path == "/stream":
                self._stream()
            else:
                self._send(b"not found", "text/plain", HTTPStatus.NOT_FOUND)

        def _stream(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            seen = -1
            try:
                while True:
                    with engine.changed:
                        engine.changed.wait_for(lambda: engine.frame_seq != seen, timeout=5)
                        jpeg, seen = engine.overlay_jpeg, engine.frame_seq
                    if jpeg is None:
                        continue
                    self.wfile.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                        + str(len(jpeg)).encode()
                        + b"\r\n\r\n"
                        + jpeg
                        + b"\r\n"
                    )
            except (BrokenPipeError, ConnectionResetError):
                pass
            self.close_connection = True

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._json({"error": "not JSON"}, HTTPStatus.BAD_REQUEST)
                return
            if self.path == "/api/reference":
                self._json({"message": engine.set_reference()})
            elif self.path == "/api/region":
                name, corners = body.get("name"), body.get("corners")
                try:
                    points = [(float(x), float(y)) for x, y in corners]
                except (TypeError, ValueError):
                    points = []
                if name not in engine.config.instruments or len(points) != 4:
                    self._json({"error": "need name and corners [[x, y] × 4]"}, HTTPStatus.BAD_REQUEST)
                    return
                if abs(cv2.contourArea(np.array(points, np.float32))) < 9:
                    self._json({"error": "region too small"}, HTTPStatus.BAD_REQUEST)
                    return
                engine.set_corners(name, points)
                self._json({"message": f"{name} region saved"})
            else:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    return Handler


def serve(engine: Engine, ring: RingHandler, host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(engine, ring))
    server.daemon_threads = True
    log.info("serving on http://%s:%d/", host, port)
    server.serve_forever()
