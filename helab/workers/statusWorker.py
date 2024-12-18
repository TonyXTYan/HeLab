import os
import random
import re
import time

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, QTimer
import logging

from PyQt6.QtTest import QTest

from helab.resources.icons import StatusIcons, IconsInitUtil
from helab.utils.osCached import os_isdir, os_listdir, os_scandir, os_scandir_async


# from helab.models.helabFileSystemModel import helabFileSystemModel


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
        logging.debug(f"StatusWorker started for: {self.file_path}")
        if self._is_canceled:
            logging.debug(f"StatusWorker canceled for: {self.file_path}")
            self.signals.finished.emit(self.file_path, 'canceled', -1, [])
            return

        # self._run_helper_simulate()
        self._run_helper_v1()

    def _run_helper_simulate(self) -> None:
        # Simulate a long-running computation
        # QTest.qWait(int(random.randint(300, 500)))  # Simulate computation delay
        time.sleep(random.uniform(0.2, 0.4))  # Simulate computation delay
        # QTimer.singleShot(random.randint(200, 500), self._compute_status)

        # Replace the following with your actual status computation logic
        # statuses = ['ok', 'warning', 'critical', 'nothing']
        statuses = StatusIcons.STATUS_ICONS_NAME
        status = random.choice(statuses)
        # count = random.randint(1, 100)
        count = random.randint(10 ** (length := random.randint(0, 5)), 10 ** (length + 1) - 1)

        extra_icons = sorted(
            random.sample(StatusIcons.STATUS_ICONS_EXTRA_NAME, random.randint(0, 4)),
            key=lambda x: StatusIcons.STATUS_ICONS_EXTRA_NAME_SORT_KEY.get(x, 0)
        )
        # extra_icons = []

        logging.debug(
            f"StatusWorker._run_helper_simulate: path = {self.file_path}, status = {status}, count = {count}, extra icons = {extra_icons}")
        self.signals.finished.emit(self.file_path, status, count, extra_icons)

    def _run_helper_v1(self) -> None:
        # This method is designed currently to work only with downstairs lab data structure.
        # Expected data format: 
        #   about.txt
        #   d123.txt                  # raw data collected by TDC Launcher in channels and timestamps (?)
        #   d_txy_forc123.txt         # tdc_autoconverter d123.txt in (t, x, y) format 
        #   log_KeysightMatlab.txt    # Optional
        #   log_LabviewMatlab.txt     # Optional


        try:
            # check if self.file_path is a directory
            # if not os.path.isdir(self.file_path):
            if not os_isdir(self.file_path):
                logging.error(f"StatusWorker._run_helper_v1: {self.file_path} is not a directory")
                self.signals.finished.emit(self.file_path, 'missing', -1, [])
                return
            # check if self.file_path contains any directory
            # dirs = os.listdir(self.file_path)

            # list all files in the directory
            # files = os.listdir(self.file_path)
            # future = os_scandir_async(self.file_path)
            # files_scan = future.result()
            files_scan = os_scandir(self.file_path)
            files = [entry.name for entry in files_scan if entry.is_file()]
            # with os_scandir(self.file_path) as it:
            #     files = [entry.name for entry in it if entry.is_file()]
            logging.debug(f"StatusWorker._run_helper_v1: files in {self.file_path}: counted {len(files)}")

        except PermissionError as e:
            logging.error(f"StatusWorker._run_helper_v1: PermissionError accessing {self.file_path}: {e}")
            self.signals.finished.emit(self.file_path, 'missing', -1, [])
            return
        except Exception as e:
            logging.error(f"StatusWorker._run_helper_v1: Error accessing {self.file_path}: {e}")
            self.signals.finished.emit(self.file_path, 'missing', -1, [])
            return


        # pattern match and list all files of d123.txt
        d_pattern = re.compile(r'^d\d+\.txt$')
        d_files = [f for f in files if d_pattern.match(f)]
        d_files_len = len(d_files)

        # pattern match and list all files of d_txy_forc123.txt
        d_txy_pattern = re.compile(r'^d_txy_forc\d+\.txt$')
        d_txy_files = [f for f in files if d_txy_pattern.match(f)]
        d_txy_files_len = len(d_txy_files)

        logging.debug(f"StatusWorker._run_helper_v1: d_files: {d_files_len}, d_txy_files: {d_txy_files_len}")

        if self._is_canceled:
            self.signals.finished.emit(self.file_path, 'canceled', -1, [])
            return

        if d_files_len == 0 and d_txy_files_len == 0:
            self.signals.finished.emit(self.file_path, 'nothing', -1, [])
        elif d_files_len == 0 or d_txy_files_len == 0:
            self.signals.finished.emit(self.file_path, 'warning', max(d_files_len, d_txy_files_len), [])
        elif d_files_len != d_txy_files_len:
            self.signals.finished.emit(self.file_path, 'warning', max(d_files_len, d_txy_files_len), [])
        elif d_files_len == d_txy_files_len:
            self.signals.finished.emit(self.file_path, 'ok', max(d_files_len, d_txy_files_len), [])
        else:
            self.signals.finished.emit(self.file_path, 'critical', max(d_files_len, d_txy_files_len), [])
            logging.error(f"StatusWorker._run_helper_v1: unexpected condition for {self.file_path}")
        # self._run_helper_simulate()
        # return

    def cancel(self) -> None:
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





