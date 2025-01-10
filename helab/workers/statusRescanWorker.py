from __future__ import annotations
from typing import TYPE_CHECKING
import logging

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, Qt

# from helab.models.helabFileSystemModel import helabFileSystemModel
from helab.utils.cachingSetup import status_cache
from helab.workers.statusWorker import StatusReport

if TYPE_CHECKING:
    from helab.models.helabFileSystemModel import helabFileSystemModel

class StatusRescanWorkerSignals(QObject):
    finished = pyqtSignal()
    cancelled = pyqtSignal()

class StatusRescanWorker(QRunnable):
    def __init__(self,
                 model: helabFileSystemModel,
                 ) -> None:
        super().__init__()
        self.model = model
        # self.rows = rows
        # self.folder_opened_path = folder_opened_path
        self.signals = StatusRescanWorkerSignals()
        self._is_cancelled = False

    def run(self) -> None:
        rows = self.model.get_visible_rows()
        for index, path in rows:
            if self._is_cancelled:
                self.signals.cancelled.emit()
                return
            status_report = status_cache.get(path)
            if isinstance(status_report, StatusReport):
                vpath, vfile, vdata = status_report.validate_ok()
                # logging.debug(f"rescan: got {vpath = }, {vfile = }, {vdata = } \tat {path}")
                if not vfile:
                    logging.debug(f"rescan: status_cache pop {path}")
                    status_cache.pop(path)
                    # self.fetch_status(path)
                elif not vpath or not vdata:
                    logging.debug(f"rescan: got {vpath = }, {vfile = }, {vdata = } \tat {path}")
                    # status_cache.pop(path)
                    # self.fetch_status(path)

                if any(i in status_report.extra_icons for i in ['ram', 'ram_single', 'ram_opened']):
                    if path == self.model.folder_opened_path:
                        status_report.update_ram_status(is_opened=True)
                    else:
                        status_report.update_ram_status(is_opened=False)
                index = self.model.index(path)
                if index.isValid():
                    self.model.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
        self.signals.finished.emit()


    def cancel(self) -> None:
        self._is_cancelled = True