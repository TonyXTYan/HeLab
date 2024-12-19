import logging
import os

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable

from helab.utils.osCached import os_isdir, os_listdir, os_scandir, os_scandir_async


class WorkerSignals(QObject):
    finished = pyqtSignal(str, bool)

class DirectoryCheckWorker(QRunnable):
    finished = pyqtSignal(bool)

    def __init__(self, dir_path: str) -> None:
        super().__init__()
        self.dir_path = dir_path
        self.signals = WorkerSignals()
        self._is_canceled = False

    def run(self) -> None:
        if self._is_canceled: return
        # wtf = os_scandir(self.dir_path)
        try:
            entries = [entry for entry in os_listdir(self.dir_path) if not entry.endswith('.txt') and entry not in ['cache', 'out', 'output']]
            result = any(os_isdir(os.path.join(self.dir_path, entry)) for entry in entries)
            num_non_txt_paths = len(entries)
            # result = any(   #TODO test this live
            #     # os.path.isdir(os.path.join(self.dir_path, entry))
            #     # for entry in os.listdir(self.dir_path)
            #     os_isdir(os.path.join(self.dir_path, entry))
            #     for entry in os_listdir(self.dir_path)
            #     if not entry.endswith('.txt')
            # )
            # num_non_txt_paths = sum(
            #     1
            #     for entry in os_listdir(self.dir_path)
            #     if not entry.endswith('.txt')
            # )

            # logging.debug(f"DirectoryCheckWorker started for: {self.dir_path}")
            # result = any(entity.is_dir() for entity in os_scandir(self.dir_path))
            # future = os_scandir_async(self.dir_path)
            # result = any(entity.is_dir() for entity in future.result())
        except Exception as e:
            # logging.error(f"DirectoryCheckWorker error for: {self.dir_path}, {e}")
            result = False
            num_non_txt_paths = None
        # logging.debug(f"DirectoryCheckWorker finished for: {self.dir_path}, result = {result}")
        logging.debug(f"DirectoryCheckWorker finished for: {self.dir_path}, result = {result}, num_non_txt_paths = {num_non_txt_paths}")
        self.signals.finished.emit(self.dir_path, result)

    def cancel(self) -> None:
        self._is_canceled = True