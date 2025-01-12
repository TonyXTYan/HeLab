from __future__ import annotations

import time
from typing import TYPE_CHECKING, List, Tuple, Optional
import logging

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, Qt, QModelIndex

# from helab.models.helabFileSystemModel import helabFileSystemModel
from helab.utils.cachingSetup import status_cache
from helab.utils.threadingSetup import all_pools_total_activeThreadCount
from helab.workers.statusWorker import StatusReport

if TYPE_CHECKING:
    from helab.models.helabFileSystemModel import helabFileSystemModel

class StatusRescanWorkerSignals(QObject):
    finished = pyqtSignal(bool)
    cancelled = pyqtSignal(bool)

class StatusRescanWorker(QRunnable):
    def __init__(self,
                 # model: helabFileSystemModel,
                 rows: List[Tuple[QModelIndex, str]],
                 model_folder_opened_path: Optional[str] = None,
                 user_intend: bool = False,
                 ) -> None:
        super().__init__()
        # self.model = model
        self.rows = rows
        self.model_folder_opened_path = model_folder_opened_path
        # self.folder_opened_path = folder_opened_path
        self.signals = StatusRescanWorkerSignals()
        self.user_intend = user_intend
        self._is_cancelled = False
        # self._is_cancelled_scan_again = False   # TODO what is this for?

    def run(self) -> None:
        logging.debug(f"StatusRescanWorker.run: started with {len(self.rows)} rows and {self.model_folder_opened_path = }, {self.user_intend = }")
        if not self.user_intend:
            time.sleep(0.5)
            # delay_processing_countdown = 5
            # while 1 < all_pools_total_activeThreadCount():
            #     # logging.debug(f"StatusRescanWorker.run: waiting for 0 < {all_pools_total_activeThreadCount() = }")
            #     time.sleep(1.0)
            #     delay_processing_countdown -= 1
            #     if delay_processing_countdown <= 0:
            #         break
        else:
            time.sleep(0.01)

        # rows = self.model.get_visible_rows()
        for index, path in self.rows:
            if self._is_cancelled:
                self.setAutoDelete(True)
                # self.signals.cancelled.emit(self._is_cancelled_scan_again, self.user_intend)
                self.signals.cancelled.emit(self.user_intend)
                return
            time.sleep(0.05)
            status_report = status_cache.get(path)
            if isinstance(status_report, StatusReport):
                vpath, vfile, vdata = status_report.validate_ok()
                # logging.debug(f"rescan: got {vpath = }, {vfile = }, {vdata = } \tat {path}")
                if not vfile:
                    logging.debug(f"StatusRescanWorker: status_cache pop {path}")
                    status_cache.pop(path)
                    # self.fetch_status(path)
                elif not vpath or not vdata:
                    logging.debug(f"StatusRescanWorker: got {vpath = }, {vfile = }, {vdata = } \tat {path}")
                    # status_cache.pop(path)
                    # self.fetch_status(path)

                if any(i in status_report.extra_icons for i in ['ram', 'ram_single', 'ram_opened']):
                    if path == self.model_folder_opened_path:
                        status_report.update_ram_status(is_opened=True)
                    else:
                        status_report.update_ram_status(is_opened=False)

                # index = self.model.index(path)
                # if index.isValid():
                #     self.model.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
            # logging.debug(f"StatusRescanWorker.run: checked {path = }")
        time.sleep(0.01)
        self.setAutoDelete(True)
        self.signals.finished.emit(self.user_intend)


    def cancel(self, scan_again:bool=True) -> None:
        self._is_cancelled = True
        # self._is_cancelled_scan_again = scan_again