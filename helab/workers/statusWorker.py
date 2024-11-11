import random
import time

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, QTimer
import logging

from PyQt6.QtTest import QTest

from helab.resources.icons import StatusIcons


# from helab.models.helabFileSystemModel import CustomFileSystemModel


# Define WorkerSignals to communicate between threads
class StatusWorkerSignals(QObject):
    finished = pyqtSignal(str, str, int, list)  # file_path, status, count, extra_icons
# Define the Worker class with cancellation support
class StatusWorker(QRunnable):
    def __init__(self, file_path: str):
        # QObject.__init__(self)
        # QRunnable.__init__()
        super().__init__()
        self.file_path = file_path
        self.signals = StatusWorkerSignals()
        self._is_canceled = False

    def run(self) -> None:
        logging.debug(f"Worker started for: {self.file_path}")
        if self._is_canceled:
            logging.debug(f"Worker canceled for: {self.file_path}")
            return

        # Simulate a long-running computation
        QTest.qWait(random.randint(100, 300))  # Simulate computation delay
        # time.sleep(random.uniform(0.2, 0.5))  # Simulate computation delay
        # QTimer.singleShot(random.randint(200, 500), self._compute_status)

        # Replace the following with your actual status computation logic
        statuses = ['ok', 'warning', 'critical', 'nothing']
        status = random.choice(statuses)
        # count = random.randint(1, 100)
        count = random.randint(10**(length := random.randint(0, 5)), 10**(length + 1) - 1)

        extra_icons = sorted(random.sample(StatusIcons.STATUS_ICONS_EXTRA_NAME, random.randint(0, 4)), key=StatusIcons.STATUS_ICONS_EXTRA_NAME_SORT_KEY.get)
        # extra_icons = []

        logging.debug(f"Worker finished for: {self.file_path} with status: {status}, count: {count}, extra icons: {extra_icons}")
        self.signals.finished.emit(self.file_path, status, count, extra_icons)

    def cancel(self):
        self._is_canceled = True

    # def _compute_status(self):
    #     # Replace the following with your actual status computation logic
    #     statuses = ['ok', 'warning', 'critical', 'nothing']
    #     status = random.choice(statuses)
    #     # count = random.randint(1, 100)
    #     count = random.randint(10**(length := random.randint(0, 5)), 10**(length + 1) - 1)
    #
    #     extra_icons = sorted(random.sample(StatusIcons.STATUS_ICONS_EXTRA_NAME, random.randint(0, 4)), key=StatusIcons.STATUS_ICONS_EXTRA_NAME_SORT_KEY.get)
    #     # extra_icons = []
    #
    #     logging.debug(f"Worker finished for: {self.file_path} with status: {status}, count: {count}, extra icons: {extra_icons}")
    #     self.signals.finished.emit(self.file_path, status, count, extra_icons)