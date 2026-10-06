"""Event-loop heartbeat and independent diagnostics for sustained stalls."""
from __future__ import annotations

import faulthandler
import logging
import sys
import threading
import time

from PyQt6.QtCore import QObject, QTimer


class GUIWatchdog(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.last_beat = time.monotonic()
        self.max_delay = 0.0
        self.stopped = threading.Event()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._beat)
        self.timer.start(100)
        threading.Thread(target=self._watch, daemon=True, name="HeLab-GUI-watchdog").start()

    def _beat(self) -> None:
        now = time.monotonic()
        delay = now - self.last_beat
        self.max_delay = max(self.max_delay, delay)
        if delay > 0.5:
            logging.warning("GUI heartbeat delayed %.3fs", delay)
        self.last_beat = now

    def _watch(self) -> None:
        last_dump = 0.0
        while not self.stopped.wait(0.5):
            now = time.monotonic()
            if now - self.last_beat > 2.0 and now - last_dump > 30.0:
                logging.error("GUI stalled for %.2fs; capturing thread stacks", now - self.last_beat)
                try:
                    if sys.__stderr__ is not None:
                        faulthandler.dump_traceback(file=sys.__stderr__, all_threads=True)
                except (OSError, RuntimeError, ValueError):
                    logging.exception("Could not dump GUI stall traceback")
                last_dump = now

    def stop(self) -> None:
        self.timer.stop()
        self.stopped.set()
