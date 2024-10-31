import os
import logging
import sys
from PyQt6.QtCore import QObject, pyqtSignal, QRunnable

class StatusDeepWorkerSignals(QObject):
    finished = pyqtSignal(list)  # list of directory paths

class StatusDeepWorker(QRunnable):
    def __init__(self, root_path: str, max_depth: int = sys.maxsize):
        super().__init__()
        self.root_path = root_path
        self.max_depth = max_depth
        self.signals = StatusDeepWorkerSignals()
        self._is_cancelled = False

    def run(self) -> None:
        logging.debug(f"Deep Worker started for: {self.root_path}")
        directory_list = []
        queue = [(self.root_path, 0)]  # Each item is a tuple (path, depth)
        try:
            while queue:
                if self._is_cancelled:
                    logging.debug(f"Deep worker cancelled: {self.root_path}")
                    return
                current_path, current_depth = queue.pop(0)
                if current_depth > self.max_depth:
                    continue
                directory_list.append(current_path)
                if current_depth < self.max_depth:
                    try:
                        dirs = [
                            d for d in os.listdir(current_path)
                            if os.path.isdir(os.path.join(current_path, d))
                        ]
                    except PermissionError as e:
                        logging.error(f"PermissionError accessing {current_path}: {e}")
                        continue
                    for dir_name in dirs:
                        dir_path = os.path.join(current_path, dir_name)
                        if self._is_cancelled:
                            logging.debug(f"Deep worker cancelled during BFS: {self.root_path}")
                            return
                        queue.append((dir_path, current_depth + 1))
        except Exception as e:
            logging.error(f"Error in StatusDeepWorker: {e}")
            return
        self.signals.finished.emit(directory_list)
        logging.debug(f"Deep worker finished for: {self.root_path}")

    def cancel(self):
        self._is_cancelled = True