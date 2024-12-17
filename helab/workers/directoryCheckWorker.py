import os

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable

from helab.utils.osCached import os_isdir, os_listdir, os_scandir


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
        try:
            # result = any(
            #     # os.path.isdir(os.path.join(self.dir_path, entry))
            #     # for entry in os.listdir(self.dir_path)
            #     os_isdir(os.path.join(self.dir_path, entry))
            #     for entry in os_listdir(self.dir_path)
            # )
            result = any(entity.is_dir() for entity in os_scandir(self.dir_path))
        except Exception:
            result = False
        self.signals.finished.emit(self.dir_path, result)

    def cancel(self) -> None:
        self._is_canceled = True