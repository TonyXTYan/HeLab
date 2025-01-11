# helab/workers/statusDeepWorker.py
import os
import logging
import sys
from typing import List

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable

from helab.utils.os_cached import os_listdir, os_isdir, os_scandir_sns, os_listdir_filtered
from helab.utils.constants import *


class StatusDeepWorkerSignals(QObject):
    # finished = pyqtSignal(str, list, int)  # (root_path, list_of_immediate_subdirectories, current_depth)
    finished = pyqtSignal(str, list)

class StatusDeepWorker(QRunnable):
    def __init__(self, root_path: str, invalidate_cache: bool = False) -> None:
        super().__init__()
        self.root_path = root_path
        self.invalidate_cache = invalidate_cache
        # self.current_depth = current_depth
        self.signals = StatusDeepWorkerSignals()
        self._is_cancelled = False

    def run(self) -> None:
        logging.debug(f"Deep Worker started for: {self.root_path}, invalidate_cache = {self.invalidate_cache}")
        directory_list: List[str] = []

        if self._is_cancelled:
            logging.debug(f"StatusDeepWorker cancelled: {self.root_path}")
            self.signals.finished.emit(self.root_path, directory_list)
            return
        try:
            os_listdir_results = os_listdir_filtered(self.root_path, invalidate_cache=self.invalidate_cache)
            for entry in os_listdir_results:
                path = os.path.join(self.root_path, entry)
                if self._is_cancelled:
                    logging.debug(f"StatusDeepWorker cancelled during BFS: {self.root_path}")
                    self.signals.finished.emit(self.root_path, directory_list)
                    return
                if os_isdir(path):
                    directory_list.append(path)

        except PermissionError as e:
            logging.error(f"StatusDeepWorker: PermissionError accessing {self.root_path}: {e}")
        except Exception as e:
            logging.error(f"StatusDeepWorker: Error accessing {self.root_path}: {e}")
        logging.debug(f"StatusDeepWorker finished for: {self.root_path}, found {len(directory_list)} immediate subdirectories")
        self.signals.finished.emit(self.root_path, directory_list)


    def cancel(self) -> None:
        self._is_cancelled = True