#helab/workers/StatusWorker.py
from __future__ import annotations

import warnings
from datetime import datetime
import os
import random
import re
import time
from copy import deepcopy
from typing import Optional, Set, List, Tuple, cast, Callable, Any

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, QTimer, QDir, QThread, QModelIndex, Qt, QFileInfo
import logging

from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest

from helab.utils.caching_setup import *
from helab.utils.threading_setup import *
from helab.resources.icons import StatusIcons, IconsInitUtil, circular_progress_QIcon_cached
from helab.utils.os_cached import os_isdir, os_listdir, os_listdir_filtered, os_listdirdir, OSCMgmt
from helab.utils.constants import *
from helab.workers.DirectoryCheckWorker import DirectoryCheckWorker



# Define WorkerSignals to communicate between threads
class StatusWorkerSignals(QObject):
    # finished = pyqtSignal(str, str, int, list)  # path, status, count, extra_icons
    # finished = pyqtSignal(StatusReport)  # path, status, count, extra_icons
    finished = pyqtSignal(str) # path

# Define the Worker class with cancellation support

class StatusWorker(QRunnable):

    def __init__(self, file_path: str, invalidate_cache:bool=False):
        # QObject.__init__(self)
        # QRunnable.__init__()
        super().__init__()
        self.path = file_path
        self.signals = StatusWorkerSignals()
        self._is_cancelled = False
        self.invalidate_cache = invalidate_cache

        self._time_started = datetime.now()

    def run(self) -> None:
        logging.debug(f"StatusWorker started for: {self.path}")
        if self._check_cancel_status(): return
        # self._run_helper_simulate()
        time.sleep(0.050)   # Give some time for the main GUI thread to update.
        self._run_helper_v1()

    def _check_cancel_status(self) -> bool:
        if self._is_cancelled:
            logging.debug(f"StatusWorker canceled for: {self.path}")
            # self.signals.finished.emit(StatusReport(self.path, 'canceled', -1, []))
            self._finished_emit_helper(StatusReport(self.path, 'cancelled', -1, []))
            return True
        else: return False

    def _finished_emit_helper(self, status_report: StatusReport) -> None:
        if self.path in status_cache:
            logging.debug(f"StatusWorker._finished_emit_helper: updating cache for {self.path} with status = {status_report.status}")

        if self.path != status_report.path: logging.critical(f"StatusWorker._finished_emit_helper: path mismatch: {self.path = }, {status_report.path = }")

        status_report = status_report._update_cache()
        status_report = status_report.review_path_children()
        status_report = status_report.review_path_parent()

        status_report._update_cache()

        sr = status_cache[self.path]
        time.sleep(random.uniform(0.010, 0.030))
        if isinstance(sr, StatusReport):
            if sr != status_report:
                logging.error(f"StatusWorker._finished_emit_helper: updated but not equal for {self.path = }")
            logging.info(f"StatusWorker._finished_emit_helper: updated to {self.path = }, {sr.status = }, {sr.count = }, {sr.extra_icons = }")
        else:
            logging.error(f"StatusWorker._finished_emit_helper: updated but not found for {self.path = }")


        if status_report.path in running_workers_status:
            worker = running_workers_status[status_report.path]
            if worker is self:
                pass
            else:
                logging.error(f"_finished_emit_helper: worker mismatch for {status_report.path}")
            del running_workers_status[status_report.path]
        else:
            logging.warning(f"_finished_emit_helper: worker not in running_workers_status for {status_report.path}")

        time.sleep(0.001)
        self.setAutoDelete(True)
        self.signals.finished.emit(self.path)

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
            f"StatusWorker._run_helper_simulate: path = {self.path}, status = {status}, count = {count}, extra icons = {extra_icons}")
        # self.signals.finished.emit(StatusReport(self.path, status, count, extra_icons))
        self._finished_emit_helper(StatusReport(self.path, status, count, extra_icons))

    def _run_helper_v1(self) -> None:
        # This method is designed currently to work only with downstairs lab data structure.
        # Expected data format: 
        #   about.txt
        #   d123.txt                  # raw data collected by TDC Launcher in channels and timestamps (?)
        #   d_txy_forc123.txt         # tdc_autoconverter d123.txt in (t, x, y) format 
        #   log_KeysightMatlab.txt    # Optional
        #   log_LabviewMatlab.txt     # Optional

        try:
            # check if self.path is a directory
            # if not os.path.isdir(self.path):
            if not os_isdir(self.path, self.invalidate_cache):
                logging.error(f"StatusWorker._run_helper_v1: {self.path} is not a directory")
                # self.signals.finished.emit(StatusReport(self.path, 'missing', -1, []))
                self._finished_emit_helper(StatusReport(self.path, 'missing', -1, []))
                return
            # check if self.path contains any directory
            # dirs = os.listdir(self.path)

            # just_for_the_sake_of_testing = os_scandir(self.path)

            if self._check_cancel_status(): return
            time.sleep(0.001)  # slight delay to void GIL
            files_filtered = os_listdir_filtered(self.path, self.invalidate_cache)
            time.sleep(0.001)
            files_filtered_len = len(files_filtered)
            time.sleep(0.001)

            if self._check_cancel_status(): return

            # list all files in the directory
            files = os_listdir(self.path, self.invalidate_cache)

            if self._check_cancel_status(): return

            # future = os_scandir_async(self.path)
            # files_scan = future.result()
            # files_scan = os_scandir(self.path)
            # files = [entry.name for entry in files_scan if entry.is_file()]
            # with os_scandir(self.path) as it:
            #     files = [entry.name for entry in it if entry.is_file()]
            logging.debug(f"StatusWorker._run_helper_v1: files in {self.path}: counted {len(files)}")

        except PermissionError as e:
            logging.error(f"StatusWorker._run_helper_v1: PermissionError accessing {self.path}: {e}")
            # self.signals.finished.emit(StatusReport(self.path, 'missing', -1, []))
            self._finished_emit_helper(StatusReport(self.path, 'missing', -1, []))
            return
        except Exception as e:
            logging.error(f"StatusWorker._run_helper_v1: Error accessing {self.path}: {e}")
            # self.signals.finished.emit(StatusReport(self.path, 'missing', -1, []))
            self._finished_emit_helper(StatusReport(self.path, 'missing', -1, []))
            return

        time.sleep(0.001)  # slight delay to void GIL

        # pattern match and list all files of d123.txt
        # d_dld_pattern = re.compile(r'^d\d+\.txt$')
        d_dld_pattern = re.compile(r'^d(\d+)\.txt$')
        # d_files = [f for f in files if d_dld_pattern.match(f)]
        d_dld_shots = [int(match.group(1)) for f in files if (match := d_dld_pattern.match(f))]
        d_dld_files_len = len(d_dld_shots)

        # pattern match and list all files of d_txy_forc123.txt
        # d_txy_pattern = re.compile(r'^d_txy_forc\d+\.txt$')
        d_txy_pattern = re.compile(r'^d_txy_forc(\d+)\.txt$')
        # d_txy_files = [f for f in files if d_txy_pattern.match(f)]
        d_txy_shots = [int(match.group(1)) for f in files if (match := d_txy_pattern.match(f))]
        d_txy_files_len = len(d_txy_shots)

        d_union_shots = set(d_dld_shots) | set(d_txy_shots)
        d_inter_shots = set(d_dld_shots) & set(d_txy_shots)
        d_only_dld_shots = set(d_dld_shots) - d_inter_shots
        d_only_txy_shots = set(d_txy_shots) - d_inter_shots

        d_union_shots_len = len(d_union_shots)
        d_inter_shots_len = len(d_inter_shots)
        d_only_dld_shots_len = len(d_only_dld_shots)
        d_only_txy_shots_len = len(d_only_txy_shots)

        if self._check_cancel_status(): return

        logging.debug(f"StatusWorker._run_helper_v1: d_dld_files: {d_dld_files_len}, d_txy_files: {d_txy_files_len}, "
                      f"d_union_shots: {d_union_shots_len}, d_inter_shots: {d_inter_shots_len}, "
                      f"d_only_dld_shots: {d_only_dld_shots_len}, d_only_txy_shots: {d_only_txy_shots_len}, "
                      f"files_filtered_len: {files_filtered_len}"
                      )

        if len(d_dld_shots) != len(set(d_dld_shots)):
            logging.fatal(f"StatusWorker._run_helper_v1: IMPOSSIBLE?! {self.path = }\t d_dld_shots contains duplicates: {d_dld_shots[:min(10, len(d_dld_shots))]}")
        if len(d_txy_shots) != len(set(d_txy_shots)):
            logging.fatal(f"StatusWorker._run_helper_v1: IMPOSSIBLE?! {self.path = }\t d_txy_shots contains duplicates: {d_txy_shots[:min(10, len(d_txy_shots))]}")


        emit_status = 'cancelled'
        emit_counts = -2
        emit_eicons = []
        if (d_only_dld_shots_len == 0 and d_only_txy_shots_len == 0) and d_union_shots_len == 0:
            # no data files found
            assert d_union_shots_len == d_inter_shots_len, "Impossible logic! d_union_shots_len != d_inter_shots_len"
            emit_status, emit_counts = 'nothing', -1
        elif (d_only_dld_shots_len == 0 and d_only_txy_shots_len == 0) and d_union_shots_len > 0:
            # consistent data folder
            assert d_union_shots_len == d_inter_shots_len, "Impossible logic! d_union_shots_len != d_inter_shots_len"
            emit_status, emit_counts = 'ok', d_union_shots_len
        elif (d_only_dld_shots_len > 0 and d_only_txy_shots_len == 0) and d_inter_shots_len > 0:
            emit_status, emit_counts = 'fixable', d_inter_shots_len
        elif (d_only_dld_shots_len > 0 and d_only_txy_shots_len > 0) and d_inter_shots_len > 0:
            # inconsistent data folder
            emit_status, emit_counts = 'warning', d_inter_shots_len
        elif (d_only_dld_shots_len == 0 and d_only_txy_shots_len > 0) and d_inter_shots_len > 0:
            emit_status, emit_counts = 'critical', d_inter_shots_len
        elif (d_only_dld_shots_len > 0 or d_only_txy_shots_len > 0) and d_inter_shots_len == 0:
            # terribly inconsistent data folder
            if d_only_dld_shots_len == 0:
                logging.warning(f"StatusWorker._run_helper_v1: folder only contain txy data: {d_only_txy_shots_len} at {self.path}")
                emit_status, emit_counts = 'warning', d_only_txy_shots_len
            elif d_only_txy_shots_len == 0:
                logging.warning(f"StatusWorker._run_helper_v1: folder only contain dld data: {d_only_dld_shots_len} at {self.path}")
                emit_status, emit_counts = 'warning', d_only_dld_shots_len
            else:
                # This means there are some dld files and some txy files but none of them are matching
                logging.critical(f"StatusWorker._run_helper_v1: serverly fucked up dataset at {self.path} (no matching pairs)")
                emit_status, emit_counts = 'critical', 0
        else:
            logging.fatal(f"StatusWorker._run_helper_v1: unexpected condition for {self.path}"
                          f"d_dld_files: {d_dld_files_len}, d_txy_files: {d_txy_files_len}, "
                          f"d_union_shots: {d_union_shots_len}, d_inter_shots: {d_inter_shots_len}, "
                          f"d_only_dld_shots: {d_only_dld_shots_len}, d_only_txy_shots: {d_only_txy_shots_len}"
                          )
            assert False, "Impossible logic! Unexpected condition. Exiting problem."

        if emit_counts >= 0:
            try:
                # data_files = data_ram_cache.__getitem__(self.path)
                data_files = data_ram_cache[self.path]
                if not data_files is None:
                    emit_eicons.append('ram')
                    logging.debug(f"StatusWorker._run_helper_v1: data in data_ram_cache for {self.path}")
                else:
                    logging.warning(f"StatusWorker._run_helper_v1: data_ram_cache None for {self.path}")
            except KeyError:
                logging.debug(f"StatusWorker._run_helper_v1: no key in data_ram_cache {self.path}")
                pass
            except Exception as e:
                logging.error(f"StatusWorker._run_helper_v1: error accessing cache for {self.path}: {e}")
                pass

        # self.signals.finished.emit(StatusReport(self.path, emit_status, emit_counts, emit_eicons, d_dld_shots, d_txy_shots, datetime.now()))
        self._finished_emit_helper(StatusReport(self.path, emit_status, emit_counts, emit_eicons, d_dld_shots, d_txy_shots, datetime.now()))

    def cancel(self) -> None:
        self._is_cancelled = True


from helab.models.StatusReport import StatusReport