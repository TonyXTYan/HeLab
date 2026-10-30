"""`python -m labcam [--source URL|image.jpg] [--port 8090]`: watch the camera and serve the page."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys

from . import config as config_module
from .config import HOME
from .engine import Engine
from .server import RingHandler, serve
from .source import FrameSource
from .wavemeter import TESSERACT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="MJPEG stream URL or a JPEG file (default: config.json's)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--debug", action="store_true", help="also write DEBUG lines to the log file")
    args = parser.parse_args()

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    # Windows consoles default to a code page without "→" or "µ": replace what they can't show.
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="backslashreplace")
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    (HOME / "logs").mkdir(exist_ok=True)
    file = logging.handlers.RotatingFileHandler(HOME / "logs" / "labcam.log", maxBytes=2_000_000, backupCount=10,
                                                encoding="utf-8")
    file.setLevel(logging.DEBUG if args.debug else logging.INFO)
    ring = RingHandler()
    ring.setLevel(logging.DEBUG)
    for handler in (console, file, ring):
        handler.setFormatter(fmt)
        root.addHandler(handler)

    cfg = config_module.load()
    if args.source:
        cfg.source = args.source
    log = logging.getLogger("labcam")
    if "CAMERA-HOST" in cfg.source:
        parser.error("set the camera's stream with --source, or \"source\" in config.local.json (see the README)")
    log.info("labcam starting: source %s, %d instruments, tesseract %s", cfg.source, len(cfg.instruments),
             TESSERACT or "not found (wavemeter off)")
    source = FrameSource(cfg.source)
    engine = Engine(cfg, source)
    source.start()
    engine.start()
    try:
        serve(engine, ring, args.host, args.port)
    except KeyboardInterrupt:
        log.info("stopped")


if __name__ == "__main__":
    main()
