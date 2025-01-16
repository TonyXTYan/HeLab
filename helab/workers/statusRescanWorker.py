from __future__ import annotations

import time
import warnings
from typing import TYPE_CHECKING, List, Tuple, Optional
import logging

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, Qt, QModelIndex

# from helab.models.helabFileSystemModel import helabFileSystemModel
from helab.utils.cachingSetup import status_cache
from helab.utils.threadingSetup import all_pools_total_activeThreadCount
from helab.workers.statusWorker import StatusReport, StatusWorker

if TYPE_CHECKING:
    from helab.models.helabFileSystemModel import helabFileSystemModel

class StatusRescanWorkerSignals(QObject):
    finished = pyqtSignal(bool)
    cancelled = pyqtSignal(bool, bool)

class StatusRescanWorker(QRunnable):
    def __init__(self,
                 # model: helabFileSystemModel,
                 rows: List[Tuple[QModelIndex, str]],
                 model_folder_opened_path: Optional[str] = None,
                 user_requested_scan: bool = False,
                 ) -> None:
        super().__init__()
        # self.model = model
        self.rows = rows
        self.model_folder_opened_path = model_folder_opened_path
        # self.folder_opened_path = folder_opened_path
        self.signals = StatusRescanWorkerSignals()
        self.user_requested_scan = user_requested_scan
        self._is_cancelled = False
        self._is_cancelled_but_scan_again = False

    def run(self) -> None:
        logging.debug(f"StatusRescanWorker.run: started with {len(self.rows)} rows and {self.model_folder_opened_path = }, {self.user_requested_scan = }")
        if not self.user_requested_scan:
            time.sleep(0.010)
        else:
            time.sleep(0.001)

        for index, path in self.rows:
            if self._is_cancelled:
                self.setAutoDelete(True)
                self.signals.cancelled.emit(self._is_cancelled_but_scan_again, self.user_requested_scan)
                return
            time.sleep(0.001)
            self.validate_this(path, self.model_folder_opened_path)

            # logging.debug(f"StatusRescanWorker.run: checked {path = }")

        time.sleep(0.001)
        self.setAutoDelete(True)
        self.signals.finished.emit(self.user_requested_scan)

    @staticmethod
    def validate_this(path: str, model_folder_opened_path: Optional[str] = None) -> None:
        status_report = status_cache.get(path)
        if isinstance(status_report, StatusReport):
            vpath, vfile, vdata = status_report.validate_ok()
            # logging.debug(f"rescan: got {vpath = }, {vfile = }, {vdata = } \tat {path}")
            if not vfile:
                logging.debug(f"StatusRescanWorker: status_cache pop {path}")
                status_cache.pop(path)
                # self.fetch_status(path)
            elif not vpath or not vdata:
                logging.warning(f"StatusRescanWorker: got {vpath = }, {vfile = }, {vdata = } \tat {path}")
                warnings.warn(
                    f"StatusRescanWorker: unimplemented data validation for {path = }, {vpath = }, {vfile = }, {vdata = }",
                    RuntimeWarning)

            if any(i in status_report.extra_icons for i in ['ram', 'ram_single', 'ram_opened']):
                if path == model_folder_opened_path:
                    status_report.update_ram_status(is_opened=True)
                else:
                    status_report.update_ram_status(is_opened=False)

            if not all(hasattr(status_report, i) for i in StatusReport.ATTRIBUTES_OPTIONAL):
                logging.warning(f"StatusRescanWorker: missing attributes in {path = }, {status_report = }")
                warnings.warn(f"StatusRescanWorker: missing attributes in {path = }, {status_report = }", RuntimeWarning)
                status_cache.pop(path)
        StatusWorker.fetch_status(path)

    def cancel(self, allow_retry_scan: bool = True) -> None:
        self._is_cancelled = True
        self._is_cancelled_but_scan_again = allow_retry_scan

    def update_info(self, rows: List[Tuple[QModelIndex, str]], model_folder_opened_path: Optional[str] = None) -> None:
        warnings.warn("StatusRescanWorker.update_info: dont use this method, just cancel and scan angain", DeprecationWarning)
        # maybe move the initialisation rescan scripts to this class here.
        self.rows = rows
        self.model_folder_opened_path = model_folder_opened_path
        self._is_cancelled = False