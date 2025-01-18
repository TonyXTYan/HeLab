#helab/workers/DirectoryCheckWorker.py
import logging
import os
import time

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, QThread, QTimer

from helab.utils.caching_setup import *
from helab.utils.os_cached import *
from helab.utils.threading_setup import running_workers_hasChildren, thread_pool_general

from typing import Optional, Callable

class WorkerSignals(QObject):
    finished = pyqtSignal(str, bool)
    canceled = pyqtSignal(str)


class DirectoryCheckWorker(QRunnable):
    # finished = pyqtSignal(bool)

    def __init__(self, dir_path: str) -> None:
        super().__init__()
        self.dir_path = dir_path
        self.signals = WorkerSignals()
        self._is_cancelled = False

    def run(self) -> None:
        if self._is_cancelled:
            self.setAutoDelete(True)
            OSCMgmt.pop_has_children(self.dir_path)
            self.signals.canceled.emit(self.dir_path)
            return
        # wtf = os_scandir(self.model_root_path)
        try:
            # entries = [entry for entry in os_listdir(self.model_root_path) if not entry.endswith('.txt') and entry not in ['cache', 'out', 'output']]
            # entries = os_listdir_filtered(self.dir_path)
            # time.sleep(0.001)
            # result = any(os_isdir(os.path.join(self.dir_path, entry)) for entry in entries)
            # time.sleep(0.001)
            # sub_dirs = os_listdirdir(self.dir_path)
            # result = len(sub_dirs) > 0
            # num_non_txt_paths = len(entries)

            result = os_has_children(self.dir_path) # REVIEW: emmm do I still need this to be on a separate thread?

        except Exception as e:
            result = False
            # sub_dirs = []
            # num_non_txt_paths = None
        # logging.debug(f"DirectoryCheckWorker finished for: {self.model_root_path}, result = {result}")
        OSCMgmt.set_has_children(self.dir_path, result)
        # logging.debug(f"DirectoryCheckWorker finished for: {self.dir_path}, result = {result}, {num_non_txt_paths = }")
        # logging.debug(f"DirectoryCheckWorker: debug check: {OSCMgmt.has_children(self.dir_path) = }, {OSCMgmt.has_children_contains(self.dir_path) = }")
        logging.debug(f"DirectoryCheckWorker: {self.dir_path = }, {result = }")
        self.setAutoDelete(True)
        # time.sleep(0.001)
        self.signals.finished.emit(self.dir_path, result)

    def cancel(self) -> None:
        self._is_cancelled = True


    @staticmethod
    def has_children(dir_path: str,
                     on_finished: Optional[Callable[[str, bool], None]] = None,
                     on_cancelled: Optional[Callable[[str], None]] = None
                     ) -> bool:
        hc = OSCMgmt.has_children(dir_path)
        if hc is not None: return hc

        if dir_path in running_workers_hasChildren:
            return False
        else:
            # logging.debug(f"hasChildren new DirectoryCheckWorker at: {dir_path}")

            def callback_finished(p: str, h: bool) -> None:
                DirectoryCheckWorker.on_has_children_finished(p, h)
                if on_finished is not None:
                    QTimer.singleShot(0, lambda: on_finished(p, h))        # type: ignore[reportOptionalCall, unused-ignore]
            def callback_cancelled(p: str) -> None:
                DirectoryCheckWorker.on_has_children_canceled(p)
                if on_cancelled is not None:
                    QTimer.singleShot(0, lambda: on_cancelled(p))             # type: ignore[reportOptionalCall, unused-ignore]

            worker = DirectoryCheckWorker(dir_path)
            worker.signals.finished.connect(callback_finished)
            worker.signals.canceled.connect(callback_cancelled)
            # worker.setAutoDelete(True)
            thread_pool_general.start(worker,
                                      priority=QThread.Priority.NormalPriority.value)  # type: ignore[call-overload]
            # QTimer.singleShot(10, lambda: thread_pool_general.start(worker))
            running_workers_hasChildren[dir_path] = worker
            return False

    @staticmethod
    def on_has_children_finished(dir_path: str, has_children: bool) -> None:
        # Remove the worker from the running_workers_hasChildren dictionary
        if dir_path in running_workers_hasChildren:
            del running_workers_hasChildren[dir_path]
            hc = OSCMgmt.has_children(dir_path)
            if hc is None:
                logging.warning(f"on_has_children_finished: OSCMgmt.has_children is None: {dir_path}")
                return
            if hc != has_children:
                logging.warning(f"on_has_children_finished: OSCMgmt.has_children != has_children: {dir_path}")
                return
        else:
            logging.warning(f"on_has_children_finished: running_workers_hasChildren has no: {dir_path}")


    @staticmethod
    def on_has_children_canceled(dir_path: str) -> None:
        logging.debug("on_has_children_canceled: {dir_path = }")
        if dir_path in running_workers_hasChildren:
            del running_workers_hasChildren[dir_path]
        else:
            logging.warning(f"on_has_children_canceled: running_workers_hasChildren has no: {dir_path}")
        pass