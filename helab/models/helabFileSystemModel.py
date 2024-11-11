import logging
import os
import sys

from PyQt6.QtCore import Qt, QThreadPool, QThread, QModelIndex, QTimer
from PyQt6.QtGui import QFileSystemModel, QIcon, QColor
from PyQt6.QtWidgets import QApplication
from cachetools import LRUCache
from pympler import asizeof
from pytablericons import TablerIcons, OutlineIcon, FilledIcon

from helab.workers.statusDeepWorker import StatusDeepWorker
# from helab.utils.loggingSetup import setup_logging

from helab.workers.statusWorker import StatusWorker
from helab.resources.icons import tablerIcon, StatusIcons


class CustomFileSystemModel(QFileSystemModel):
    COLUMN_NAME = 0
    COLUMN_SIZE = 1
    COLUMN_TYPE = 2
    COLUMN_DATE_MODIFIED = 3
    COLUMN_STATUS_NUMBER = 4
    COLUMN_STATUS_ICON = 5
    COLUMN_RIGHTFILL = 6
    STATUS_EXTRA_ICONS_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Cache the standard icons
        style = QApplication.style()

        # self.icon_ok = tablerIcon(OutlineIcon.CIRCLE_CHECK, '#00bb39')
        # self.icon_critical = tablerIcon(OutlineIcon.XBOX_X, '#e50000')
        # self.icon_warning = tablerIcon(OutlineIcon.ALERT_CIRCLE, '#f8c350')
        # self.icon_loading = tablerIcon(OutlineIcon.LOADER, '#000000')   #TODO: replace this with PERCENTAGE
        # self.icon_live = tablerIcon(OutlineIcon.LIVE_PHOTO, '#000000')
        # self.icon_nothing = tablerIcon(FilledIcon.POINT, '#bbbbbb')
        # self.status_icons = {
        #     'ok': StatusIcons.ICON_OK,
        #     'warning': self.icon_warning,
        #     'critical': self.icon_critical,
        #     'loading': self.icon_loading,
        #     'nothing': self.icon_nothing
        # }
        # self.icon_database = tablerIcon(OutlineIcon.DATABASE, '#444444')
        # self.icon_report = tablerIcon(OutlineIcon.REPORT_ANALYTICS, '#444444')
        # self.icon_chart3d = tablerIcon(OutlineIcon.CHART_SCATTER_3D, '#444444')
        # self.icon_ram = tablerIcon(OutlineIcon.CONTAINER, '#444444')

        # Map icon keys to QIcons for easy retrieval
        # self.status_icons_extra = {
        #     'database': self.icon_database,
        #     'report': self.icon_report,
        #     'chart3d': self.icon_chart3d,
        #     'ram': self.icon_ram,
        #     'live': self.icon_live
        # }

        # # Initialize the cache
        # Initialize the cache with a maximum size to prevent unlimited growth
        self.status_cache = LRUCache(maxsize=10000)  # Store up to 10000 entries

        # Initialize the thread pool
        self.thread_pool = QThreadPool()        # Might need to move this to a global queue system
        self.thread_pool.setMaxThreadCount(8)
        self.thread_pool.setThreadPriority(QThread.Priority.LowPriority)
        logging.debug(f"Multithreading with maximum {self.thread_pool.maxThreadCount()} threads")

        # Initialize a set to keep track of running workers
        self.running_workers_status = {}
        self.running_workers_deep = {}

        # # Connect the status_updated signal to a slot
        # self.status_updated.connect(self.on_status_updated)

        # Connect signals to cache invalidation methods
        self.directoryLoaded.connect(self.on_directory_loaded)
        self.fileRenamed.connect(self.on_file_renamed)
        self.dataChanged.connect(self.on_data_changed)
        self.modelReset.connect(self.on_model_reset)

    def columnCount(self, parent=QModelIndex()):
        return super().columnCount(parent) + 3  # Add three extra columns

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        column = index.column()
        file_info = self.fileInfo(index)

        if column == self.COLUMN_DATE_MODIFIED:
            if role == Qt.ItemDataRole.DisplayRole:
                date_time = file_info.lastModified()
                return date_time.toString("yyyy-MM-dd HH:mm:ss")
            else:
                return None
        elif column == self.COLUMN_STATUS_NUMBER:
            if role == Qt.ItemDataRole.DisplayRole:
                # print(index, file_info.absoluteFilePath())
                status, count, _ = self.fetch_status(file_info.absoluteFilePath())
                if status == 'loading':
                    return '...'
                elif status == 'nothing':
                    return ''
                return str(count)
            elif role == Qt.ItemDataRole.TextAlignmentRole:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            else:
                return None
        elif column == self.COLUMN_STATUS_ICON:
            if role == Qt.ItemDataRole.DecorationRole:
                status, _, _  = self.fetch_status(file_info.absoluteFilePath())
                # icon = self.status_icons.get(status)
                icon = StatusIcons.ICONS_STATUS.get(status)
                return icon
            elif role == self.STATUS_EXTRA_ICONS_ROLE:
                # Retrieve extra icons from the cache
                _, _, extra_icons = self.fetch_status(file_info.absoluteFilePath())
                # return [self.status_icons_extra.get(icon_key) for icon_key in extra_icons]
                return [StatusIcons.ICONS_EXTRA.get(icon_key) for icon_key in extra_icons]
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

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                if section == self.COLUMN_STATUS_NUMBER:
                    return "Counts"
                elif section == self.COLUMN_STATUS_ICON:
                    return "Status"
        return super().headerData(section, orientation, role)

    def fetch_status(self, folder_path):
        # logging.debug(f"Getting status for: {folder_path}")
        # Check if the status is already cached
        status_data = self.status_cache.get(folder_path)
        if status_data is not None:
            return status_data
        else:
            # Check if a worker is already running for this folder_path
            if folder_path in self.running_workers_status:
                logging.debug(f"Worker already running for: {folder_path}")
                return self.status_cache.get(folder_path, ('loading', 0, []))

            logging.debug(f"Status not cached for: {folder_path}")
            # Set status to 'loading' in cache with empty extra_icons
            self.status_cache[folder_path] = ('loading', 0, [])
            # Emit dataChanged to update the view with 'loading' status
            index = self.index(folder_path, self.COLUMN_STATUS_NUMBER)
            if index.isValid():
                self.dataChanged.emit(
                    index,
                    index,
                    [Qt.ItemDataRole.DisplayRole]
                )
            index_icon = self.index(folder_path, self.COLUMN_STATUS_ICON)
            if index_icon.isValid():
                self.dataChanged.emit(
                    index_icon,
                    index_icon,
                    [Qt.ItemDataRole.DecorationRole]
                )
            # Create and start the worker
            worker = StatusWorker(folder_path)
            worker.signals.finished.connect(self.handle_status_computed)
            self.thread_pool.start(worker)
            # self.running_workers.add(worker)
            self.running_workers_status[folder_path] = worker
            return ('loading', 0, [])

    def handle_status_computed(self, file_path, status, count, extra_icons):
        logging.debug(f"Status computed for: {file_path}: {status}, {count}, Cached: {asizeof.asizeof(self.status_cache) / 1000} KB")
        # Update the cache with the computed status and extra icons
        self.status_cache[file_path] = (status, count, extra_icons)

        # Retrieve QModelIndex for Status Number and Status Icon columns
        status_number_index = self.index(file_path, self.COLUMN_STATUS_NUMBER)
        status_icon_index = self.index(file_path, self.COLUMN_STATUS_ICON)

        # Emit dataChanged for Status Number column
        if status_number_index.isValid():
            self.dataChanged.emit(
                status_number_index,
                status_number_index,
                [Qt.ItemDataRole.DisplayRole]
            )

        # Emit dataChanged for Status Icon column
        if status_icon_index.isValid():
            self.dataChanged.emit(
                status_icon_index,
                status_icon_index,
                [Qt.ItemDataRole.DecorationRole]
            )
        # self.running_workers.discard(self.sender())
        # Remove the worker from the running_workers dictionary
        if file_path in self.running_workers_status:
            del self.running_workers_status[file_path]
            logging.debug(f"Worker removed from running_workers for: {file_path}")

    def on_directory_loaded(self, path):
        # Invalidate cache entries for the loaded directory
        # self.invalidate_cache_for_directory(path)
        logging.debug(f"Directory loaded: {path} \t ditch cache??")

    def on_file_renamed(self, path, old_name, new_name):
        # Remove the old path from the cache
        old_path = os.path.join(path, old_name)
        new_path = os.path.join(path, new_name)
        self.status_cache.pop(old_path, None)
        logging.debug(f"(POP)File renamed: {old_path} -> {new_path}")
        # Optionally, recompute the status for the new path
        # self.get_status(new_path)

    def on_data_changed(self, topLeft, bottomRight, roles):
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
                logging.debug(f"Data changed for: {file_path}")

    def on_model_reset(self):
        # Clear the entire cache
        self.status_cache.clear()
        logging.debug(f"(CLEAR) Model reset")

    def invalidate_cache_for_directory(self, directory_path):
        # Remove all cached entries under the given directory
        keys_to_remove = [key for key in self.status_cache if key.startswith(directory_path)]
        for key in keys_to_remove:
            del self.status_cache[key]

    def stop_all_scans(self):
        logging.debug("Stopping all scans...")
        # Iterate through all running workers and cancel them
        for file_path, worker in list(self.running_workers_status.items()):
            worker.cancel()
            # self.running_workers.remove(worker)
            del self.running_workers_status[file_path]
            logging.debug(f"Worker canceled for: {file_path}")
        # Cancel all StatusDeepWorker instances
        # for worker in list(self.running_workers_deep):
        for folder_path, worker in list(self.running_workers_deep.items()):
            worker.cancel()
            # self.running_workers_deep.remove(worker)
            del self.running_workers_deep[folder_path]
            logging.debug(f"Cancelled StatusDeepWorker for: {worker.root_path}")

        # Optionally, clear the thread pool's queue if possible
        # Note: QThreadPool does not provide a direct method to clear pending tasks
        # So, we rely on workers to check for cancellation
        logging.debug("All scans have been requested to stop.")

    def start_deep_status_worker(self, root_path: str, max_depth: int = sys.maxsize):
        # Create and start a StatusDeepWorker
        worker = StatusDeepWorker(root_path, max_depth)
        worker.signals.finished.connect(self.process_deep_status)
        self.thread_pool.start(worker)
        # Track the StatusDeepWorker
        self.running_workers_deep[root_path] = worker
        logging.debug(f"Started StatusDeepWorker for: {root_path}")

    def process_deep_status(self, directory_list):
        logging.debug(f"Processing {len(directory_list)} directories for status recalculation")
        self.directory_iterator = iter(directory_list)
        self.process_next_directories()

        # After processing is done, remove all workers
        # Note: StatusDeepWorker does not have a direct reference here
        # So, we assume it's already removed from running_workers_deep when canceled

    def process_next_directories(self):
        # Process a batch of directories
        batch_size = 100  # Adjust as needed
        count = 0
        try:
            while count < batch_size:
                dir_path = next(self.directory_iterator)
                logging.debug(f"Recalculating status for: {dir_path}")
                self.status_cache.pop(dir_path, None)
                self.fetch_status(dir_path)
                count += 1
        except StopIteration:
            # No more directories
            logging.debug("Finished processing directories for status recalculation")
            return
        # Schedule next batch
        QTimer.singleShot(0, self.process_next_directories)
        # THIS IS BUGGY, MIGHT NEED REWRITE?!

    def context_menu_action_deep_calc_status(self, folder_info):
        file_path = folder_info.absoluteFilePath()
        if not folder_info.isDir():
            logging.debug(f"Selected item is not a directory: {file_path}")
            return
        logging.debug(f"Deep recalculating status for: {file_path}")
        # Start the deep status worker
        self.start_deep_status_worker(file_path)
