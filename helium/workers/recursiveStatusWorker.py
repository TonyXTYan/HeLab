import os
import random
import time

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable
from setuptools import logging

from helium.models.heliumFileSystemModel import CustomFileSystemModel


class RecursiveStatusWorkerSignals(QObject):
    finished = pyqtSignal(list)  # list of directory paths

class RecursiveStatusWorker(QRunnable):
    def __init__(self, root_path):
        super().__init__()
        self.root_path = root_path
        self.signals = RecursiveStatusWorkerSignals()
        self._is_cancelled = False

    def run(self):
        logging.debug(f"Recursive Worker started for: {self.root_path}")
        directory_list = [self.root_path]
        try:
            for root, dirs, _ in os.walk(self.root_path):
                if self._is_cancelled:
                    logging.debug(f"Recursive worker cancelled: {self.root_path}")
                    return
                for dir_name in dirs:
                    if self._is_cancelled:
                        logging.debug(f"Recursive worker cancelled during walk: {self.root_path}")
                        return
                    dir_path = os.path.join(root, dir_name)
                    directory_list.append(dir_path)
        except Exception as e:
            logging.error(f"Error in RecursiveStatusWorker: {e}")
            return
        self.signals.finished.emit(directory_list)
        logging.debug(f"Recursive worker finished for: {self.root_path}")

    def cancel(self):
        self._is_cancelled = True