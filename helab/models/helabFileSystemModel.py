# helab/models/helabFileSystemModel.py
import logging
import os
import sys
from datetime import datetime
from random import randint

from typing import Dict, Tuple, List, cast, Optional

from PyQt6.QtCore import Qt, QThread, QModelIndex, QTimer, QObject, QDir
from PyQt6.QtGui import QFileSystemModel, QColor

from helab.utils.cachingSetup import *
from helab.utils.threadingSetup import *
from helab.utils.constants import MAX_DEPTH_INT
from helab.utils.os_cached import os_listdir_filtered
from helab.workers.directoryCheckWorker import DirectoryCheckWorker
from helab.workers.statusDeepWorker import StatusDeepWorker
from helab.workers.statusRescanWorker import StatusRescanWorker
# from helab.utils.loggingSetup import setup_logging

from helab.workers.statusWorker import StatusWorker, StatusReport
from helab.resources.icons import tablerIcon, StatusIcons, str_to_QIcon
from helab.workers.helabFSModelThrottleDataChangedEmit import HeLabFSModelThrottleDataChangedEmit

class helabFileSystemModel(QFileSystemModel):
    COLUMN_NAME = 0
    COLUMN_SIZE = 1
    COLUMN_TYPE = 2
    COLUMN_DATE_MODIFIED = 3
    COLUMN_STATUS_NUMBER = 4
    COLUMN_STATUS_ICON = 5
    COLUMN_RIGHTFILL = 6
    STATUS_EXTRA_ICONS_ROLE = Qt.ItemDataRole.UserRole + 1

    # CACHE_HAS_CHILDREN: TTLCache[str, bool] = TTLCache(maxsize=10*1000, ttl=30)

    def __init__(self,
                 *args: QObject | None, **kwargs: QObject | None
                 ) -> None:
        super().__init__(*args, **kwargs)
        self.uuid = str(id(self))

        # Cache the standard icons
        # style = QApplication.style()

        # self.hasChildren_cache = hasChildren_cache

        self.folder_opened_path: Optional[str] = None # same as the one folderExplorer, updated by folderExplorer

        # Initialize the cache with a maximum size to prevent unlimited growth
        # self.status_cache = LRUCache(maxsize=10000)  # Store up to 10000 entries

        # Initialize the thread pool
        # self.thread_pool = QThreadPool()        # Might need to move this to a global queue system
        # self.thread_pool = QThreadPool.globalInstance()
        # self.thread_pool.setMaxThreadCount(8)
        # self.thread_pool.setThreadPriority(QThread.Priority.LowPriority)
        logging.debug(f"Multithreading with maximum {thread_pool_general.maxThreadCount()} threads")

        # Initialize a set to keep track of running workers
        # self.running_workers_status = {}
        # self.running_workers_deep = {}

        # # Connect the status_updated signal to a slot
        # self.status_updated.connect(self.on_status_updated)

        # Connect signals to cache invalidation methods
        self.directoryLoaded.connect(self.on_directory_loaded)
        self.fileRenamed.connect(self.on_file_renamed)
        self.dataChanged.connect(self.on_data_changed)
        self.modelReset.connect(self.on_model_reset)

        self.rescan_worker: Optional[StatusRescanWorker] = None

        self.throttled_data_changed_emitter = HeLabFSModelThrottleDataChangedEmit()
        self.throttled_data_changed_emitter.signals.emit_dataChanged.connect(self._throttled_data_changed_emit_now)
        running_workers_ThrottleDataChangedEmits[self.uuid] = self.throttled_data_changed_emitter
        thread_pool_gui_update.start(self.throttled_data_changed_emitter, priority=QThread.Priority.LowestPriority.value) # type: ignore[call-overload]

        # self.pending_updates = set()
        # self.update_timer = QTimer()
        # self.update_timer.setSingleShot(True)
        # self.update_timer.timeout.connect(self.emit_pending_updates)

        # QTimer.singleShot(300, self.refresh)


    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return super().columnCount(parent) + 3  # Add three extra columns

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid():
            return None
        column = index.column()
        file_info = self.fileInfo(index)
        path = file_info.absoluteFilePath()
        status_report = self.fetch_status(path)
        # status = status_report.status
        # count = status_report.count
        # extra_icons = status_report.extra_icons

        # # if ['ram', 'ram_single', 'ram_opened'] in extra_icons:
        # if any(i in extra_icons for i in ['ram', 'ram_single', 'ram_opened']):
        #     if path == self.folder_opened_path:
        #         status_report.update_ram_status(is_opened=True)
        #     else:
        #         status_report.update_ram_status(is_opened=False)

        if column == self.COLUMN_DATE_MODIFIED:
            if role == Qt.ItemDataRole.DisplayRole:
                date_time = file_info.lastModified()
                return date_time.toString("yyyy-MM-dd HH:mm:ss")
            else:
                return None
        elif column == self.COLUMN_STATUS_NUMBER:
            if role == Qt.ItemDataRole.DisplayRole:
                # print(index, file_info.absoluteFilePath())
                # status, count, _ = self.fetch_status(file_info.absoluteFilePath())
                if status_report.status == 'loading':
                    return '...'
                # elif status == 'nothing':
                #     return ''
                # elif status == 'missing':
                #     return ''
                elif status_report.status in ['nothing', 'something', 'missing', 'unknown']:
                    return ''
                return str(status_report.count)
            elif role == Qt.ItemDataRole.TextAlignmentRole:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            else:
                return None
        elif column == self.COLUMN_STATUS_ICON:
            if role == Qt.ItemDataRole.DecorationRole:
                # status, _, _  = self.fetch_status(file_info.absoluteFilePath())
                # icon = self.status_icons.get(status)
                icon = StatusIcons.ICONS_STATUS.get(status_report.status, None)
                if icon: return icon
                else:
                    # logging.warning(f"status icon not found for: {status}")   # too many calls
                    status_report.noticed_errors(StatusReport.ERROR_INVALID_STATUS_ICON)
                    return StatusIcons.ICON_BUG
            elif role == self.STATUS_EXTRA_ICONS_ROLE:
                return StatusReport.return_extra_icons_paintable(status_report)
                # return status_report.return_extra_icons_paintable()

                # Retrieve extra icons from the cache

                # _, _, extra_icons = self.fetch_status(file_info.absoluteFilePath())
                # return [self.status_icons_extra.get(icon_key) for icon_key in extra_icons]
                # return sorted([StatusIcons.ICONS_EXTRA.get(icon_key) for icon_key in extra_icons],
                #               key=lambda x: StatusIcons.STATUS_ICONS_EXTRA_NAME_SORT_KEY.get(x,0))
                        # + [circularProgressIcon(0.1), circularProgressIcon(0.45), circularProgressIcon(0.9), circularProgressIcon(1)])
                        # + [str_to_QIcon("1"), str_to_QIcon(" 2"), str_to_QIcon("69"), str_to_QIcon("100")]
            elif role == Qt.ItemDataRole.TextAlignmentRole:
                return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            else:
                return None
        elif column == self.COLUMN_RIGHTFILL:
            return None
        else:
            # For other columns, default behavior
            if role == Qt.ItemDataRole.ForegroundRole:
                if file_info.isHidden():
                    return QColor(Qt.GlobalColor.gray)
            return super().data(index, role)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                if section == self.COLUMN_STATUS_NUMBER:
                    return "Counts"
                elif section == self.COLUMN_STATUS_ICON:
                    return "Status"
        return super().headerData(section, orientation, role)

    def fetch_status(self, folder_path: str) -> StatusReport:
        return StatusWorker.fetch_status(folder_path, self.throttled_data_changed_emitter.add_update)
        # return QTimer.singleShot(0, lambda: StatusWorker.fetch_status(folder_path, self.handle_status_computed_v3))

    def fetch_status_legacy(self, folder_path: str) -> StatusReport:
        # logging.debug(f"Getting status for: {folder_path}")
        # Check if the status is already cached
        # status_data = .get(folder_path)
        status_data = cast(StatusReport, status_cache.get(folder_path))
        if status_data is not None:
            if not isinstance(status_data, StatusReport):
                logging.warning(f"fetch_status: status_data is not StatusReport: {status_data}")
                del status_cache[folder_path]
                return self.fetch_status(folder_path)
            if status_data.status == 'loading':
                if folder_path in running_workers_status: # legit loading
                    return status_data
                else: # loading but worker is gone (unexpected)
                    logging.warning(f"fetch_status: loading but worker is gone for: {folder_path}")
                    del status_cache[folder_path]
                    return self.fetch_status(folder_path)
            else:
                return status_data
        else: # status_data is None from cache
            # Check if a worker is already running for this folder_path
            loading_status = StatusReport(folder_path, 'loading', -300, [])
            if folder_path in running_workers_status:
                # logging.debug(f"fetch_status worker already running for: {folder_path}")
                # return ('loading', 0, [])
                # return status_cache.get(folder_path, ('loading', 0, []))
                status_cache[folder_path] = loading_status
                return loading_status
            # else: # not in running_workers_status

            logging.debug(f"fetch_status: not cached for: {folder_path}")

            # Create and start the worker
            worker = StatusWorker(folder_path)
            worker.signals.finished.connect(self.handle_status_computed_v2)
            thread_pool_general.start(worker, priority=QThread.Priority.LowestPriority.value)
            running_workers_status[folder_path] = worker
            return loading_status

    def handle_status_computed_v3(self, path: str) -> None:
        StatusWorker.on_fetch_status_finished_basic(path)
        self.throttled_data_changed_emitter.add_update(path)

    def handle_status_computed_v2(self, path: str) -> None:
        status_report = status_cache.get(path, None)
        if not isinstance(status_report, StatusReport):
            logging.critical(f"handle_status_computed_v2: (IMPOSSIBLE) status_report is not StatusReport: {status_report}")
            return

        logging.debug(f"handle_status_computed_v2: path = {status_report.path}, status = {status_report.status}, count = {status_report.count}, extras = {status_report.extra_icons}")
        # path = status_report.path
        if path != status_report.path:
            logging.critical(f"handle_status_computed_v2: (IMPOSSIBLE) path mismatch: {path = }, {status_report.path = }")
        if path in running_workers_status:
            worker = running_workers_status[path]
            # worker.autoDelete()
            # worker.setAutoDelete(True)
            del running_workers_status[path]
            # del worker
        else:
            logging.warning(f"handle_status_computed_v2: worker not in running_workers_status for {path}")
        if path in status_cache:
            pass
        else:
            logging.warning(f"handle_status_computed_v2: worker not in status_cache for {path}")
        pass

        self.throttled_data_changed_emitter.add_update(path)


    def handle_status_computed(self, status_report: StatusReport) -> None:
        logging.critical(f"handle_status_computed: DEPRECATED")
        file_path = status_report.path
        status = status_report.status
        count = status_report.count
        extra_icons = status_report.extra_icons

        size_in_kb = status_cache.volume()
        logging.debug(f"handle_status_computed: called {status = }, {count = }, Cached: {fnum(size_in_kb)}B from {file_path}"
                      f", activeThreads = {all_pools_total_activeThreadCount()}"
                      # f", {thread_pool_general.maxThreadCount() = }"
                      )
        # Update the cache with the computed status and extra icons
        # status_cache[file_path] = (status, count, extra_icons)
        status_cache[file_path] = status_report

        # self.running_workers.discard(self.sender())
        # Remove the worker from the running_workers dictionary
        if file_path in running_workers_status:
            del running_workers_status[file_path]
            logging.debug(f"handle_status_computed: worker removed from running_workers_status for {file_path}")

        status = status_report.status
        current_index = self.index(file_path)
        if status != 'nothing':
            # Emit dataChanged for the parent directory
            parent_index = current_index.parent()
            if parent_index.isValid():
                parent_path = self.filePath(parent_index)
                if parent_path in status_cache:
                    del status_cache[parent_path]
                self.fetch_status(parent_path)
                logging.debug(f"handle_status_computed: fetch_status again for parent: ({status}) {parent_path}")
        elif status == 'nothing':
            if self.hasChildren(current_index):
                entries = os_listdir_filtered(file_path)

                # still_unknown = True
                for entry in entries:
                    # child_path = os.path.join(file_path, entry)
                    child_path = QDir(file_path).filePath(entry)
                    status_report_child = status_cache.get(child_path)
                    if isinstance(status_report_child, StatusReport):
                        child_status = status_report_child.status
                        if child_status in ['ok', 'fixable', 'warning', 'critical', 'something']:
                            status_cache[file_path] = StatusReport(file_path, 'something', -2, [])
                            break
                    else:
                        # still_unknown = True
                        continue
                status_cache[file_path] = StatusReport(file_path, 'unknown', -3, [])
                logging.debug(f"handle_status_computed: set unknown status for {file_path}")
        else:
            pass

        # Retrieve QModelIndex for Status Number and Status Icon columns
        status_number_index = self.index(file_path, self.COLUMN_STATUS_NUMBER)
        status_icon_index = self.index(file_path, self.COLUMN_STATUS_ICON)
        # Emit dataChanged for Status Number column
        if status_number_index.isValid():
            self.dataChanged.emit(status_number_index, status_number_index, [Qt.ItemDataRole.DisplayRole] )
        # Emit dataChanged for Status Icon column
        if status_icon_index.isValid():
            self.dataChanged.emit(status_icon_index, status_icon_index, [Qt.ItemDataRole.DecorationRole] )

        logging.debug(f"handle_status_computed: dataChanged emitted for {file_path}")

    def on_directory_loaded(self, path: str) -> None:
        # Invalidate cache entries for the loaded directory
        # self.invalidate_cache_for_directory(path)
        logging.debug(f"on_directory_loaded: (popped) {path}")
        # QTimer.singleShot(10, lambda: status_cache.pop(path))
        logging.warning(f"on_directory_loaded: TODO: implement (popped) {path}")
        # status_cache.pop(path, None)

        os_listdir_cache.pop(path, None)
        os_scandir_cache.pop(path, None)
        QTimer.singleShot(1, lambda: StatusRescanWorker.validate_this(path, self.folder_opened_path))

        # os_isdir_cache.pop(path, None)

    def on_file_renamed(self, path: str, old_name: str, new_name: str) -> None:
        # Remove the old path from the cache
        # old_path = os.path.join(path, old_name)
        # new_path = os.path.join(path, new_name)
        old_path = QDir(path).filePath(old_name)
        new_path = QDir(path).filePath(new_name)
        status_cache.pop(old_path, None)
        logging.debug(f"on_file_renamed: (popped) {old_path} -> {new_path}")
        # Optionally, recompute the status for the new path
        # self.get_status(new_path)

    def on_data_changed(self, topLeft: QModelIndex, bottomRight: QModelIndex, roles: List[int]) -> None:
        """
        Handles the dataChanged signal by logging the file paths of the changed items.

        Parameters:
            topLeft (QModelIndex): The top-left index of the changed data.
            bottomRight (QModelIndex): The bottom-right index of the changed data.
            roles (List[int]): The roles that were changed.
        """
        # return

        # Iterate through the changed rows
        for row in range(topLeft.row(), bottomRight.row() + 1):
            for column in range(topLeft.column(), bottomRight.column() + 1):
                index = self.index(row, column, topLeft.parent())
                file_path = self.filePath(index)
                # logging.debug(f"on_data_changed: {file_path}")
                pass

        # self.refresh()

    def _throttled_data_changed_emit_now(self, paths: List[str]) -> None:
        # logging.debug(f"throttled_data_changed_emit_now: {len(paths)} paths")
        # time_start = datetime.now()

        # QTimer.singleShot(0, lambda: self._throttled_data_changed_emit_now(paths))
        QTimer.singleShot(0, lambda: self._bulk_data_changed(paths))

    # def _throttled_data_changed_emit_now(self, paths: List[str]) -> None:
    #     time_start = datetime.now()
    #
    #     self.throttled_data_changed_emitter.pause()
    #     for path in paths:
    #         index = self.index(path, self.COLUMN_STATUS_NUMBER)
    #         if index.isValid():
    #             self.dataChanged.emit( index, index, [Qt.ItemDataRole.DisplayRole] )
    #         index_icon = self.index(path, self.COLUMN_STATUS_ICON)
    #         if index_icon.isValid():
    #             self.dataChanged.emit( index_icon, index_icon, [Qt.ItemDataRole.DecorationRole, self.STATUS_EXTRA_ICONS_ROLE] )
    #     self.throttled_data_changed_emitter.resume()
    #
    #     time_delta = datetime.now() - time_start
    #     logging.debug(f"_throttled_data_changed_emit_now: {len(paths)} paths emitted in {round(1e-3*time_delta.microseconds)}ms")

    def _bulk_data_changed(self, paths: List[str]) -> None:
        """
        Emit dataChanged signals for the given paths.

        Warning: Please try to use this method where possible, as it emits dataChanged signals for all paths at once.

        :param paths:
        :return:
        """

        indexes = []
        for path in paths:
            idxL = self.index(path, self.COLUMN_STATUS_NUMBER)
            idxR = self.index(path, self.COLUMN_STATUS_ICON)
            if idxL.isValid() and idxR.isValid():
                indexes.extend([idxL, idxR])
        if not indexes:
            return

        min_row = min(i.row() for i in indexes)
        max_row = max(i.row() for i in indexes)
        min_col = min(i.column() for i in indexes)
        max_col = max(i.column() for i in indexes)

        top_left = self.index(min_row, min_col)
        bottom_right = self.index(max_row, max_col)
        self.dataChanged.emit(top_left, bottom_right,
            [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.DecorationRole, self.STATUS_EXTRA_ICONS_ROLE]
        )

        # time_delta = datetime.now() - time_start
        # logging.debug(f"_bulk_data_changed: {len(paths)} paths emitted in {round(1e-3*time_delta.microseconds)}ms")

    def on_model_reset(self) -> None:
        # Clear the entire cache
        status_cache.clear()
        logging.debug(f"(CLEAR) Model reset")

    def invalidate_cache_for_directory(self, directory_path: str) -> None:
        # Remove all cached entries under the given directory
        # keys_to_remove = [key for key in status_cache if key.startswith(directory_path)]
        keys_to_remove = [
            key for key in status_cache
            if isinstance(key, str) and key.startswith(directory_path)
        ]
        for key in keys_to_remove:
            del status_cache[key]

    def stop_all_scans(self) -> None:
        logging.debug("Stopping all scans...")
        #TODO: use cancel_all_workers() ?
        # Iterate through all running workers and cancel them
        for file_path, worker in list(running_workers_status.items()):
            worker.cancel()
            # self.running_workers.remove(worker)
            del running_workers_status[file_path]
            # status_cache.pop(file_path, None)
            # del status_cache[file_path]
            logging.debug(f"Worker canceled for: {file_path}")

        # Cancel all StatusDeepWorker instances
        # for worker in list(self.running_workers_deep):
        for folder_path, workerD in list(running_workers_deep.items()):
            workerD.cancel()
            # self.running_workers_deep.remove(worker)
            del running_workers_deep[folder_path]
            # del status_cache[folder_path]
            logging.debug(f"Cancelled StatusDeepWorker for: {workerD.root_path}")

        for folder_path, workerC in list(running_workers_hasChildren.items()):
            workerC.cancel()
            del running_workers_hasChildren[folder_path]
            logging.debug(f"Cancelled DirectoryCheckWorker for: {workerC.dir_path}")

        # self.running_workers_status = {}
        # self.running_workers_deep = {}

        # Optionally, clear the thread pool's queue if possible
        # Note: QThreadPool does not provide a direct method to clear pending tasks
        # So, we rely on workers to check for cancellation
        logging.debug("All scans have been requested to stop.")

    def start_deep_status_worker(self, root_path: str, current_depth: int = MAX_DEPTH_INT, invalidate_cache: bool = True) -> None:
        if invalidate_cache:
            status_cache.pop(root_path)
        self.fetch_status(root_path)

        # Create and start a StatusDeepWorker
        if current_depth < 0:
            logging.warning(f"start_deep_status_worker: stopped {current_depth = } for: {root_path}")
            return
        # elif current_depth == 0:
        #     logging.debug(f"start_deep_status_worker: depth==0 reached for: {root_path}")
        #     return

        worker = StatusDeepWorker(root_path, invalidate_cache)
        worker.signals.finished.connect(lambda rp, dr: self.process_deep_status(rp, dr, current_depth, invalidate_cache))
        # worker.setAutoDelete(True)
        thread_pool_general.start(worker, priority=QThread.Priority.IdlePriority.value) # type: ignore[call-overload]
        # Track the StatusDeepWorker
        running_workers_deep[root_path] = worker
        logging.debug(f"start_deep_status_worker started for: {root_path}, with depth: {current_depth}")

    def process_deep_status(self, root_path: str, directory_list: List[str], current_depth: int, invalidate_cache: bool = True) -> None:
        # logging.debug(f"Processing {len(directory_list)} directories for status recalculation")
        # self.directory_iterator = iter(directory_list)
        # self.process_next_directories(root_path)
        #
        # # After processing is done, remove all workers
        # # Note: StatusDeepWorker does not have a direct reference here
        # # So, we assume it's already removed from running_workers_deep when canceled

        logging.debug(f"process_deep_status: {len(directory_list) = }, {current_depth = }, at {root_path = }")
        if current_depth < 0:
            running_workers_deep.pop(root_path)
            logging.warning(f"process_deep_status: cancelled and removed from tracking: {root_path}. THIS CASE SHOULD NOT HAPPEN!")
            return
        if root_path in running_workers_deep:
            # self.running_workers_deep[root_path].cancel()
            # del self.running_workers_deep[root_path]
            running_workers_deep.pop(root_path)
            logging.debug(f"process_deep_status: Worker removed for: {root_path}")

        if current_depth > 0:
            for d in directory_list:
                self.start_deep_status_worker(d, current_depth-1, invalidate_cache)

    def context_menu_action_deep_calc_status(self, folder_info: QModelIndex) -> None:
        # file_path = folder_info.absoluteFilePath()
        # file_path = self.filePath(folder_info)
        file_info = self.fileInfo(folder_info)
        file_path = file_info.absoluteFilePath()
        if not file_info.isDir():
            logging.debug(f"Selected item is not a directory: {file_path}")
            return
        logging.debug(f"Deep recalculating status for: {file_path}")
        # Start the deep status worker
        self.start_deep_status_worker(file_path)

    def refresh(self) -> None:
        # self.beginResetModel()
        # self.endResetModel()
        self.directoryLoaded.emit(self.rootPath())
        logging.debug("helabFileSystemModel has been refreshed.")

    # @cachetools.cached(CACHE_HAS_CHILDREN)
    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:
        if not parent.isValid():
            return super().hasChildren(parent)
        file_info = self.fileInfo(parent)
        if not file_info.isDir():
            return False
        dir_path = file_info.absoluteFilePath()

        # cached_result = hasChildren_cache.get(model_root_path)
        cached_result = cast(Optional[bool], hasChildren_cache.get(dir_path))
        if cached_result is not None:
            # logging.debug(f"hasChildren used cache for: {model_root_path}: {cached_result}")
            return cached_result
        else:
            if dir_path in running_workers_hasChildren:
                return False
            else:
                logging.debug(f"hasChildren new DirectoryCheckWorker at: {dir_path}")
                # logging.debug(f"lisdir: {os_listdir.cache_info()}, scandir: {os_scandir_list.cache_info()}, isdir: {os_isdir.cache_info()}, hasChildren_cache: {hasChildren_cache.currsize}") # type: ignore[attr-defined]
                # logging.debug(f"os_listdir_cache: {os_listdir_cache.currsize}, os_scandir_cache: {os_scandir_cache.currsize}, os_isdir_cache: {os_isdir_cache.currsize}, hasChildren_cache: {hasChildren_cache.currsize}")
                # logging.debug(f"os_listdir_cache: {os_listdir_cache.volume()}, os_scandir_cache: {os_scandir_cache.volume()}, os_isdir_cache: {os_isdir_cache.volume()}, hasChildren_cache: {hasChildren_cache.currsize}")
                # logging.debug(f"hasChildren_cache: {hasChildren_cache.currsize}")
                worker = DirectoryCheckWorker(dir_path)
                worker.signals.finished.connect(self.on_has_children_finished)
                worker.signals.canceled.connect(self.on_has_children_canceled)
                # worker.setAutoDelete(True)
                thread_pool_general.start(worker, priority=QThread.Priority.NormalPriority.value) # type: ignore[call-overload]
                # QTimer.singleShot(10, lambda: thread_pool_general.start(worker))
                running_workers_hasChildren[dir_path] = worker
                return False


    def on_has_children_finished(self, dir_path: str, has_children: bool) -> None:
        # logging.debug(f"on_has_children_finished: {dir_path = }, {has_children = }")

        # # Update the cache with the computed result
        # if has_children is not None:
        #     hasChildren_cache[dir_path] = has_children
        # else:
        #     logging.warning(f"on_has_children_finished: has_children is None for: {dir_path}")
        # # logging.debug(f"hasChildren computed for: {model_root_path}: {has_children}, in cache: {hasChildren_cache[model_root_path]}")

        # Remove the worker from the running_workers_hasChildren dictionary
        if dir_path in running_workers_hasChildren:
            del running_workers_hasChildren[dir_path]
            # logging.debug(f"Worker removed from running_workers_hasChildren for: {model_root_path}")

            # logging.debug(f"on_has_children_finished for: {dir_path}: {has_children}, value in cache: {hasChildren_cache[dir_path]}")
            # logging.debug(f"lisdir: {os_listdir.cache_info()}, scandir: {os_scandir_list.cache_info()}, isdir: {os_isdir.cache_info()}, hasChildren_cache: {hasChildren_cache.currsize}") # type: ignore[attr-defined]
        else:
            logging.warning(f"on_has_children_finished: running_workers_hasChildren has no: {dir_path}")

        self.throttled_data_changed_emitter.add_update(dir_path)

    def on_has_children_canceled(self, dir_path: str) -> None:
        logging.debug("on_has_children_canceled: {dir_path = }")
        if dir_path in running_workers_hasChildren:
            del running_workers_hasChildren[dir_path]
        else:
            logging.warning(f"on_has_children_canceled: running_workers_hasChildren has no: {dir_path}")
        pass

    def get_visible_rows(self, parent: QModelIndex = QModelIndex()) -> List[Tuple[QModelIndex, str]]:
        """Get all visible rows in the model."""
        rows = []
        indexes_to_check = [parent]

        while indexes_to_check:
            current_parent = indexes_to_check.pop()
            row_count = self.rowCount(current_parent)

            for row in range(row_count):
                index = self.index(row, 0, current_parent)
                filepath = self.filePath(index)
                rows.append((index, filepath))

                # If item has children and is expanded, add its children to the list to check
                if self.hasChildren(index):
                    indexes_to_check.append(index)

        return rows

    def rescan(self, user_requested_scan: bool = False) -> None:
        # logging.info("helabFileSystemModel.rescan: called")

        if self.rescan_worker is not None:
            logging.warning("helabFileSystemModel.rescan: already running, cancelling this one and it will retry")
            self.rescan_worker.cancel(allow_retry_scan = True)
            return
        else:
            logging.debug("helabFileSystemModel.rescan: starting")

        worker = StatusRescanWorker(rows=self.get_visible_rows(), model_folder_opened_path=self.folder_opened_path, user_requested_scan=user_requested_scan)
        worker.signals.finished.connect(self.on_rescan_finished)
        worker.signals.cancelled.connect(self.on_rescan_cancelled)
        if user_requested_scan:
            thread_pool_general.start(worker, priority=QThread.Priority.HighPriority.value)   # type: ignore[call-overload]
        else:
            QTimer.singleShot(100, lambda: thread_pool_general.start(worker, priority=QThread.Priority.LowestPriority.value))    # type: ignore[call-overload]
        self.rescan_worker = worker
        pass

    def on_rescan_finished(self, u: bool = False) -> None:
        logging.info("helabFileSystemModel.on_rescan_finished")
        self.refresh()
        self.rescan_worker = None
        rows = self.get_visible_rows()
        # for index, path in rows:
        for ith, (index, path) in enumerate(rows):
            status_report = status_cache.get(path)
            if isinstance(status_report, StatusReport):
                if any(i in status_report.extra_icons for i in ['ram', 'ram_single', 'ram_opened']):
                    if path == self.folder_opened_path:
                        status_report.update_ram_status(is_opened=True)
                    else:
                        status_report.update_ram_status(is_opened=False)
            self.throttled_data_changed_emitter.add_update(path)

    def on_rescan_cancelled(self, retry: bool = False, was_user_requested_scan: bool = False) -> None:
        logging.info(f"helabFileSystemModel.on_rescan_cancelled {retry = }, {was_user_requested_scan = }")
        self.refresh()
        self.rescan_worker = None
        if retry: QTimer.singleShot(10, lambda: self.rescan(user_requested_scan=was_user_requested_scan))
        else:     QTimer.singleShot(100, lambda: self.rescan(user_requested_scan=was_user_requested_scan))


    def on_item_expanded(self, index: QModelIndex) -> None:
        logging.debug(f"helabFileSystemModel.on_item_expanded: {self.filePath(index)}")
        self.rescan()

    def rescan_cancel_if_any(self) -> None:
        if isinstance(self.rescan_worker, StatusRescanWorker):
            self.rescan_worker.cancel(allow_retry_scan = False)
            self.rescan_worker = None
            logging.info("helabFileSystemModel.rescan_cancel_if_any: cancelled")

    def close_cleanup(self) -> None:
        self.rescan_cancel_if_any()
        self.stop_all_scans()

        try:
            running_workers_ThrottleDataChangedEmits.pop(self.uuid).cancel()
        except:
            pass

        logging.info("helabFileSystemModel.close_cleanup: done")
        self.deleteLater()