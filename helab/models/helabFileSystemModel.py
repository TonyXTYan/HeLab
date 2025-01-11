# helab/models/helabFileSystemModel.py
import logging
import os
import sys

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
        # Cache the standard icons
        # style = QApplication.style()

        self.status_cache = status_cache
        self.hasChildren_cache = hasChildren_cache

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

        # QTimer.singleShot(300, self.refresh)


    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return super().columnCount(parent) + 3  # Add three extra columns

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid():
            return None
        column = index.column()
        file_info = self.fileInfo(index)
        path = file_info.absoluteFilePath()
        statusReport = self.fetch_status(path)
        status = statusReport.status
        count = statusReport.count
        extra_icons = statusReport.extra_icons
        
        # # if ['ram', 'ram_single', 'ram_opened'] in extra_icons:
        # if any(i in extra_icons for i in ['ram', 'ram_single', 'ram_opened']):
        #     if path == self.folder_opened_path:
        #         statusReport.update_ram_status(is_opened=True)
        #     else:
        #         statusReport.update_ram_status(is_opened=False)

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
                if status == 'loading':
                    return '...'
                # elif status == 'nothing':
                #     return ''
                # elif status == 'missing':
                #     return ''
                elif status in ['nothing', 'something', 'missing', 'unknown']:
                    return ''
                return str(count)
            elif role == Qt.ItemDataRole.TextAlignmentRole:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            else:
                return None
        elif column == self.COLUMN_STATUS_ICON:
            if role == Qt.ItemDataRole.DecorationRole:
                # status, _, _  = self.fetch_status(file_info.absoluteFilePath())
                # icon = self.status_icons.get(status)
                icon = StatusIcons.ICONS_STATUS.get(status)
                return icon
            elif role == self.STATUS_EXTRA_ICONS_ROLE:
                return statusReport.return_extra_icons_paintable()

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
        # logging.debug(f"Getting status for: {folder_path}")
        # Check if the status is already cached
        # status_data = self.status_cache.get(folder_path)
        status_data = cast(StatusReport, self.status_cache.get(folder_path))
        if status_data is not None:
            if not isinstance(status_data, StatusReport):
                logging.warning(f"fetch_status: status_data is not StatusReport: {status_data}")
                del self.status_cache[folder_path]
                return self.fetch_status(folder_path)
            if status_data.status == 'loading':
            # if status_data[0] == 'loading':
                # logging.debug(f"Status is loading for: {folder_path}")
                # return status_data
                # if folder_path in self.running_workers_status and self.running_workers_status[folder_path] is not None:
                        # logging.debug(f"Worker still running for: {folder_path}")
                if folder_path in running_workers_status: # legit loading
                    return status_data
                else: # loading but worker is gone (unexpected)
                    logging.warning(f"fetch_status: loading but worker is gone for: {folder_path}")
                    del self.status_cache[folder_path]
                    return self.fetch_status(folder_path)
            else:
                return status_data
        else: # status_data is None from cache
            # Check if a worker is already running for this folder_path
            loading_status = StatusReport(folder_path, 'loading', -300, [])
            if folder_path in running_workers_status:
                # logging.debug(f"fetch_status worker already running for: {folder_path}")
                # return ('loading', 0, [])
                # return self.status_cache.get(folder_path, ('loading', 0, []))
                self.status_cache[folder_path] = loading_status
                return loading_status
            # else: # not in running_workers_status

            logging.debug(f"fetch_status: not cached for: {folder_path}")
            # Set status to 'loading' in cache with empty extra_icons
            # self.status_cache[folder_path] = ('loading', 0, [])
            # self.status_cache[folder_path] = StatusReport(folder_path, 'loading', -300, [])
            # Emit dataChanged to update the view with 'loading' status

            # index = self.index(folder_path, self.COLUMN_STATUS_NUMBER)
            # if index.isValid():
            #     self.dataChanged.emit(
            #         index,
            #         index,
            #         [Qt.ItemDataRole.DisplayRole]
            #     )
            # index_icon = self.index(folder_path, self.COLUMN_STATUS_ICON)
            # if index_icon.isValid():
            #     self.dataChanged.emit(
            #         index_icon,
            #         index_icon,
            #         [Qt.ItemDataRole.DecorationRole]
            #     )

            # Create and start the worker
            worker = StatusWorker(folder_path)
            worker.signals.finished.connect(self.handle_status_computed)
            thread_pool_general.start(worker, priority=QThread.Priority.IdlePriority.value)
            worker.setAutoDelete(True)
            running_workers_status[folder_path] = worker
            # self.running_workers.add(worker)
            # return ('loading', 0, [])
            # QTimer.singleShot(5, lambda: thread_pool_general.start(worker, priority=QThread.Priority.LowPriority.value))
            # return StatusReport(folder_path, 'loading', 0, [])
            return loading_status

    def handle_status_computed(self, status_report: StatusReport) -> None:
        file_path = status_report.path
        status = status_report.status
        count = status_report.count
        extra_icons = status_report.extra_icons

    # def handle_status_computed(self, file_path: str, status: str, count: int, extra_icons: List[str]) -> None:
        # logging.debug(f"Status computed for: {file_path}: {status}, {count}, Cached: {asizeof.asizeof(self.status_cache) / 1000} KB")
        # size_in_kb: int = asizeof.asizeof(self.status_cache) // 1000  # type: ignore
        size_in_kb = self.status_cache.volume() // 1000
        logging.debug(f"fetch_status computed for: {file_path}: {status}, {count}, Cached: {size_in_kb} KB")
        # Update the cache with the computed status and extra icons
        # self.status_cache[file_path] = (status, count, extra_icons)
        self.status_cache[file_path] = status_report

        # self.running_workers.discard(self.sender())
        # Remove the worker from the running_workers dictionary
        if file_path in running_workers_status:
            del running_workers_status[file_path]
            logging.debug(f"handle_status_computed: Worker removed from running_workers for: {file_path}")

        status = status_report.status
        current_index = self.index(file_path)
        if status != 'nothing':
            # Emit dataChanged for the parent directory
            parent_index = current_index.parent()
            if parent_index.isValid():
                parent_path = self.filePath(parent_index)
                if parent_path in self.status_cache:
                    del self.status_cache[parent_path]
                self.fetch_status(parent_path)
                # status_report_parent = self.fetch_status(parent_path)
                # logging.debug(f"handle_status_computed: Emitting dataChanged for parent: ({status_report_parent.status}) {parent_path}")
                # self.dataChanged.emit(
                #     parent_index,
                #     parent_index,
                #     [Qt.ItemDataRole.DisplayRole]
                # )
                # if status_report_parent.status == 'nothing':
                #     status_cache[parent_path] = StatusReport(parent_path, 'something', -2, [])
                # QTimer.singleShot(100, lambda: self.fetch_status(parent_path))
        elif status == 'nothing':
            if self.hasChildren(current_index):
                # list children
                # for child in self.fetchMore(current_index):
                entries = os_listdir_filtered(file_path)
                for entry in entries:
                    child_path = os.path.join(file_path, entry)
                    # status_report_child = self.fetch_status(child_path)
                    status_report_child = self.status_cache.get(child_path)
                    if isinstance(status_report_child, StatusReport):
                        child_status = status_report_child.status
                        if child_status in ['ok', 'fixable', 'warning', 'critical', 'something']:
                            status_cache[file_path] = StatusReport(file_path, 'something', -2, [])
                            break
                    else:
                        status_cache[file_path] = StatusReport(file_path, 'unknown', -3, [])
                    # logging.debug(f"handle_status_computed: Child status: {child_status} for: {child_path}")
                    # if status_report_child.status == 'nothing':
                    #     status_cache[child_path] = StatusReport(child_path, 'something', -2, [])
                # pass
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

    def on_directory_loaded(self, path: str) -> None:
        # Invalidate cache entries for the loaded directory
        # self.invalidate_cache_for_directory(path)
        logging.debug(f"on_directory_loaded: (popped) {path}")
        QTimer.singleShot(10, lambda: self.status_cache.pop(path))
        # self.status_cache.pop(path, None)
        # joblib_memory.cache(func=os_scandir).clear()
        # joblib_memory.clear(warn=False, func=os_listdir, args=(path,))
        # joblib_memory.clear
        os_listdir_cache.pop(path, None)
        os_scandir_cache.pop(path, None)
        # os_isdir_cache.pop(path, None)

    def on_file_renamed(self, path: str, old_name: str, new_name: str) -> None:
        # Remove the old path from the cache
        old_path = os.path.join(path, old_name)
        new_path = os.path.join(path, new_name)
        self.status_cache.pop(old_path, None)
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
        # Iterate through the changed rows
        for row in range(topLeft.row(), bottomRight.row() + 1):
            for column in range(topLeft.column(), bottomRight.column() + 1):
                index = self.index(row, column, topLeft.parent())
                file_path = self.filePath(index)
                # logging.debug(f"on_data_changed: {file_path}")
                pass

        # self.refresh()

    def on_model_reset(self) -> None:
        # Clear the entire cache
        self.status_cache.clear()
        logging.debug(f"(CLEAR) Model reset")

    def invalidate_cache_for_directory(self, directory_path: str) -> None:
        # Remove all cached entries under the given directory
        # keys_to_remove = [key for key in self.status_cache if key.startswith(directory_path)]
        keys_to_remove = [
            key for key in self.status_cache
            if isinstance(key, str) and key.startswith(directory_path)
        ]
        for key in keys_to_remove:
            del self.status_cache[key]

    def stop_all_scans(self) -> None:
        logging.debug("Stopping all scans...")
        #TODO: use cancel_all_workers() ?
        # Iterate through all running workers and cancel them
        for file_path, worker in list(running_workers_status.items()):
            worker.cancel()
            # self.running_workers.remove(worker)
            del running_workers_status[file_path]
            # self.status_cache.pop(file_path, None)
            # del self.status_cache[file_path]
            logging.debug(f"Worker canceled for: {file_path}")

        # Cancel all StatusDeepWorker instances
        # for worker in list(self.running_workers_deep):
        for folder_path, workerD in list(running_workers_deep.items()):
            workerD.cancel()
            # self.running_workers_deep.remove(worker)
            del running_workers_deep[folder_path]
            # del self.status_cache[folder_path]
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
            self.status_cache.pop(root_path)
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
        worker.setAutoDelete(True)
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

        # self.status_cache.pop(root_path)
        # self.fetch_status(root_path)

        # for d in directory_list:
        #     self.status_cache.pop(d)
        #     self.fetch_status(d)

        if current_depth > 0:
            for d in directory_list:
                self.start_deep_status_worker(d, current_depth-1, invalidate_cache)


    # def process_next_directories(self, root_path: str) -> None:
    #     # Process a batch of directories
    #     batch_size = 100  # Adjust as needed
    #     count = 0
    #     try:
    #         while count < batch_size:
    #             model_root_path = next(self.directory_iterator)
    #             logging.debug(f"Recalculating status for: {model_root_path}")
    #             self.status_cache.pop(model_root_path, None)
    #             self.fetch_status(model_root_path)     #### THIS IS WHERE THE RECURSIVE STATUS RECALCULATION HAPPENS
    #             count += 1
    #     except StopIteration:
    #         # No more directories
    #         del self.running_workers_deep[root_path]
    #         logging.debug("Finished processing directories for status recalculation")
    #         return
    #     # Schedule next batch
    #     QTimer.singleShot(0, lambda: self.process_next_directories(root_path))
    #     # THIS IS BUGGY, MIGHT NEED REWRITE?!

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

        # cached_result = self.hasChildren_cache.get(model_root_path)
        cached_result = cast(Optional[bool], self.hasChildren_cache.get(dir_path))
        if cached_result is not None:
            # logging.debug(f"hasChildren used cache for: {model_root_path}: {cached_result}")
            return cached_result
        else:
            if dir_path in running_workers_hasChildren:
                return False
            else:
                logging.debug(f"hasChildren new DirectoryCheckWorker at: {dir_path}")
                # logging.debug(f"lisdir: {os_listdir.cache_info()}, scandir: {os_scandir_list.cache_info()}, isdir: {os_isdir.cache_info()}, hasChildren_cache: {self.hasChildren_cache.currsize}") # type: ignore[attr-defined]
                # logging.debug(f"os_listdir_cache: {os_listdir_cache.currsize}, os_scandir_cache: {os_scandir_cache.currsize}, os_isdir_cache: {os_isdir_cache.currsize}, hasChildren_cache: {self.hasChildren_cache.currsize}")
                # logging.debug(f"os_listdir_cache: {os_listdir_cache.volume()}, os_scandir_cache: {os_scandir_cache.volume()}, os_isdir_cache: {os_isdir_cache.volume()}, hasChildren_cache: {self.hasChildren_cache.currsize}")
                # logging.debug(f"hasChildren_cache: {self.hasChildren_cache.currsize}")
                worker = DirectoryCheckWorker(dir_path)
                worker.signals.finished.connect(self.on_has_children_finished)
                worker.setAutoDelete(True)
                thread_pool_general.start(worker, priority=QThread.Priority.LowestPriority.value) # type: ignore[call-overload]
                # QTimer.singleShot(10, lambda: thread_pool_general.start(worker))
                running_workers_hasChildren[dir_path] = worker
                return False




        # directory = QDir(model_root_path)
        # directory.setFilter(QDir.Filter.Dirs | QDir.Filter.NoDotAndDotDot)
        # return directory.exists() and directory.count() > 0  # '.' and '..''


        # try:
        #     return any(
        #         # os.path.isdir(os.path.join(model_root_path, entry))
        #         # for entry in os.listdir(model_root_path)
        #         os_isdir(os.path.join(model_root_path, entry))
        #         for entry in os_listdir(model_root_path)
        #     )
        # except Exception as e:
        #     return False

        # # Start the worker
        # worker = DirectoryCheckWorker(model_root_path)
        # worker.signals.finished.connect(self.on_has_children_finished)
        # threadpool = QThreadPool.globalInstance()
        # threadpool.start(worker)
        #
        # return True  # Return False initially, update will be handled in on_has_children_finished

    # def on_has_children_finished(self, model_root_path: str, has_children: bool):
    #     index = self.index(model_root_path)
    #     if index.isValid():
    #         # Notify the view that the data has changed
    #         self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
    #         # Optionally, you can refresh the children if needed
    #         if has_children:
    #             self.fetchMore(index)

    def on_has_children_finished(self, dir_path: str, has_children: bool) -> None:
        # Update the cache with the computed result
        if has_children is not None:
            self.hasChildren_cache[dir_path] = has_children
        else:
            logging.warning(f"on_has_children_finished: has_children is None for: {dir_path}")
        # logging.debug(f"hasChildren computed for: {model_root_path}: {has_children}, in cache: {self.hasChildren_cache[model_root_path]}")

        # Remove the worker from the running_workers_hasChildren dictionary
        if dir_path in running_workers_hasChildren:
            del running_workers_hasChildren[dir_path]
            # logging.debug(f"Worker removed from running_workers_hasChildren for: {model_root_path}")

            # logging.debug(f"on_has_children_finished for: {dir_path}: {has_children}, value in cache: {self.hasChildren_cache[dir_path]}")
            # logging.debug(f"lisdir: {os_listdir.cache_info()}, scandir: {os_scandir_list.cache_info()}, isdir: {os_isdir.cache_info()}, hasChildren_cache: {self.hasChildren_cache.currsize}") # type: ignore[attr-defined]
        else:
            logging.warning(f"on_has_children_finished: running_workers_hasChildren has no: {dir_path}")

        #update view ?
        # self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])

        # Retrieve QModelIndex for the directory
        index = self.index(dir_path)
        # Emit dataChanged for the directory
        if index.isValid():
            self.dataChanged.emit(
                index,
                index,
                [Qt.ItemDataRole.DisplayRole]
            )

    def get_visible_rows(self, parent: QModelIndex = QModelIndex()) -> List[Tuple[QModelIndex, str]]:
        """Get all visible rows in the model."""
        rows = []
        row_count = self.rowCount(parent)

        for row in range(row_count):
            index = self.index(row, 0, parent)
            filepath = self.filePath(index)
            rows.append((index, filepath))

            # If item has children and is expanded, recursively get its items
            if self.hasChildren(index):
                rows.extend(self.get_visible_rows(index))

        return rows

    def rescan(self) -> None:
        # logging.info("helabFileSystemModel.rescan: called")

        if self.rescan_worker is not None:
            logging.warning("helabFileSystemModel.rescan: already running")
            self.rescan_worker.cancel(scan_again=True)
            return
        else:
            logging.debug("helabFileSystemModel.rescan: starting")

        worker = StatusRescanWorker(self)
        worker.signals.finished.connect(self.on_rescan_finished)
        worker.signals.cancelled.connect(self.on_rescan_cancelled)
        worker.setAutoDelete(True)
        # thread_pool_general.start(worker, priority=QThread.Priority.LowestPriority.value)
        QTimer.singleShot(1, lambda: thread_pool_general.start(worker, priority=QThread.Priority.HighPriority.value))    # type: ignore[call-overload]
        # self.refresh()
        self.rescan_worker = worker
        pass

    def on_rescan_finished(self) -> None:
        logging.info("helabFileSystemModel.on_rescan_finished")
        self.refresh()
        self.rescan_worker = None

    def on_rescan_cancelled(self, scan_again:bool = True) -> None:
        logging.info("helabFileSystemModel.on_rescan_cancelled")
        self.refresh()
        self.rescan_worker = None
        if scan_again: QTimer.singleShot(100, self.rescan)

    def on_item_expanded(self, index: QModelIndex) -> None:
        logging.debug(f"helabFileSystemModel.on_item_expanded: {self.filePath(index)}")
        self.rescan()

    def rescan_cancel_if_any(self) -> None:
        if self.rescan_worker is not None:
            self.rescan_worker.cancel(scan_again=False)
            self.rescan_worker = None
            logging.info("helabFileSystemModel.rescan_cancel_if_any: cancelled")