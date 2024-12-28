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
        # queue = [(self.root_path, 0)]  # Each item is a tuple (path, depth)
        # try:
        #     while queue:
        #         if self._is_cancelled:
        #             logging.debug(f"Deep worker cancelled: {self.root_path}")
        #             return
        #         current_path, current_depth = queue.pop(0)
        #         if current_depth > self.current_depth:
        #             continue
        #         directory_list.append(current_path)
        #         if current_depth < self.current_depth:
        #             try:
        #                 dirs = [
        #                     d for d in os.listdir(current_path)
        #                     if os.path.isdir(os.path.join(current_path, d))
        #                 ]
        #             except PermissionError as e:
        #                 logging.error(f"PermissionError accessing {current_path}: {e}")
        #                 continue
        #             except Exception as e:
        #                 logging.error(f"Error accessing {current_path}: {e}")
        #                 continue
        #             for dir_name in dirs:
        #                 dir_path = os.path.join(current_path, dir_name)
        #                 if self._is_cancelled:
        #                     logging.debug(f"Deep worker cancelled during BFS: {self.root_path}")
        #                     return
        #                 queue.append((dir_path, current_depth + 1))
        # except Exception as e:
        #     logging.error(f"Error in StatusDeepWorker: {e}")
        #     return
        # self.signals.finished.emit(self.root_path, directory_list)
        # logging.debug(f"Deep worker finished for: {self.root_path}")
        if self._is_cancelled:
            logging.debug(f"StatusDeepWorker cancelled: {self.root_path}")
            self.signals.finished.emit(self.root_path, directory_list, -100)
            return
        try:
            # Gather only immediate subdirectories of self.root_path
            # dirs = [
            #     d for d in os_listdir(self.root_path)
            #     if os_isdir(os.path.join(self.root_path, d))
            # ]

            # os_scandir_results =  os_scandir_sns(self.root_path)
            # for entry in os_scandir_results:
            #     # logging.debug(f"StatusDeepWorker: entry: {entry.path}")
            #     if self._is_cancelled:
            #         logging.debug(f"StatusDeepWorker cancelled during BFS: {self.root_path}")
            #         self.signals.finished.emit(self.root_path, directory_list, -100)
            #         return
            #     if entry.is_dir:
            #         directory_list.append(entry.path)

            # os_listdir_results = os_listdir(self.root_path)
            # logging.debug(f"StatusDeepWorker: os_listdir_results: {os_listdir_results}")
            os_listdir_results = os_listdir_filtered(self.root_path, invalidate_cache=self.invalidate_cache)
            for entry in os_listdir_results:
                path = os.path.join(self.root_path, entry)
                if self._is_cancelled:
                    logging.debug(f"StatusDeepWorker cancelled during BFS: {self.root_path}")
                    self.signals.finished.emit(self.root_path, directory_list, -100)
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