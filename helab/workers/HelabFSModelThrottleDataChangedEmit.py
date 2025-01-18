# helab/workers/helabFSModelThrottle.py
import logging
import time
from typing import Set, Optional, List

from PyQt6.QtCore import QRunnable, QObject, pyqtSignal, QMutex, QMutexLocker


class HelabFSModelThrottleDataChangedEmitSignals(QObject):
    emit_dataChanged = pyqtSignal(list) # List[str]

class HelabFSModelThrottleDataChangedEmit(QRunnable):

    def __init__(self,
                 pending_updates: Optional[Set[str]] = None,
                 batch_size: int = 0,
                 sleep_sec_pause: float = 0.100,
                 sleep_sec_nothing: float = 0.050,
                 sleep_sec_end_loop: float = 0.010,
                 ) -> None:
        super().__init__()
        self.uuid = str(id(self))
        self.pending_updates: Set[str] = pending_updates or set()
        self._is_paused = False
        self._is_cancelled = False
        self.signals = HelabFSModelThrottleDataChangedEmitSignals()
        self._mutex = QMutex()
        self.batch_size = batch_size
        self.sleep_sec_pause = sleep_sec_pause
        self.sleep_sec_nothing = sleep_sec_nothing
        self.sleep_sec_end_loop = sleep_sec_end_loop

    def run(self) -> None:

        while not self._is_cancelled:
            # logging.debug(f"HelabFSModelThrottleDataChangedEmit running - {len(self.pending_updates)}")
            time.sleep(self.sleep_sec_end_loop)

            if self._is_paused:
                time.sleep(self.sleep_sec_pause)
                continue

            with QMutexLocker(self._mutex):
                if not self.pending_updates:
                    time.sleep(self.sleep_sec_nothing)
                    continue
                # items = []
                # for _ in range(self.batch_size):
                #     try:
                #         items.append(self.pending_updates.pop())
                #     except KeyError:
                #         break

                # items = [self.pending_updates.pop() for _ in range(self.batch_size) if self.pending_updates]

                if self.batch_size == 0:
                    items = list(self.pending_updates)
                    self.pending_updates.clear()
                else:
                    items = [self.pending_updates.pop() for _ in range(self.batch_size) if self.pending_updates]

                # item = self.pending_updates.pop()
            # self.signals.emit_dataChanged.emit(item)

            if items: self.signals.emit_dataChanged.emit(items)

            time.sleep(self.sleep_sec_end_loop)

        self.setAutoDelete(True)
        return

    def pause(self) -> None:
        self._is_paused = True

    def resume(self) -> None:
        self._is_paused = False

    def cancel(self) -> None:
        self._is_cancelled = True
        self.pending_updates.clear()

    def add_update(self, item: str) -> None:
        with QMutexLocker(self._mutex):
            self.pending_updates.add(item)
            # logging.debug(f"HelabFSModelThrottleDataChangedEmit.add_update: {item = }, pending = {len(self.pending_updates)}")

    def add_updates(self, items: Set[str] | str) -> None:
        with QMutexLocker(self._mutex):
            self.pending_updates.update(items)
            # logging.debug(f"HelabFSModelThrottleDataChangedEmit.add_updates: {items = }, pending = {len(self.pending_updates)}")

    def clear_updates(self) -> None:
        with QMutexLocker(self._mutex):
            self.pending_updates.clear()

    def is_empty(self) -> bool:
        with QMutexLocker(self._mutex):
            return not bool(self.pending_updates)

    def update_batch_size(self, batch_size: int) -> None:
        self.batch_size = batch_size

