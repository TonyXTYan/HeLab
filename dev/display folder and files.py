import sys
import os
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QTreeView,
    QVBoxLayout,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
    QHeaderView,
    QPushButton,
    QMenu,
)
from PyQt6.QtCore import (
    QModelIndex,
    QDir,
    Qt,
    QRect,
    QSize,
    QTimer,
    QObject,
    pyqtSignal,
    QRunnable,
    QThreadPool, QThread,QItemSelectionModel,
)
from PyQt6.QtGui import (
    QFileSystemModel,
    QColor,
    QIcon,
    QPainter,
    QFont,
    QAction,
)
from pytablericons import TablerIcons, OutlineIcon, FilledIcon
import random
import logging
import hashlib
from cachetools import LRUCache
from pympler import asizeof
import time

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

STATUS_DATA_ROLE = Qt.ItemDataRole.UserRole + 1

# Define WorkerSignals to communicate between threads
class WorkerSignals(QObject):
    finished = pyqtSignal(str, str, int)  # file_path, status, count

# Define the Worker class
class Worker(QRunnable):
    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self.signals = WorkerSignals()

    def run(self):
        logging.debug(f"Worker started  for: {self.file_path}")
        # Simulate a long-running computation
        time.sleep(random.uniform(0.2, 0.5))  # Simulate computation delay

        # Replace the following with your actual status computation logic
        statuses = ['ok', 'warning', 'critical', 'nothing']
        status = random.choice(statuses)
        # count = random.randint(1, 100)
        count = random.randint(10**(length := random.randint(0, 5)), 10**(length + 1) - 1)


        logging.debug(f"Worker finished for: {self.file_path} with status: {status}, count: {count}")
        self.signals.finished.emit(self.file_path, status, count)


class CustomFileSystemModel(QFileSystemModel):
    COLUMN_NAME = 0
    COLUMN_SIZE = 1
    COLUMN_TYPE = 2
    COLUMN_DATE_MODIFIED = 3
    COLUMN_STATUS_NUMBER = 4
    COLUMN_STATUS_ICON = 5
    COLUMN_RIGHTFILL = 6
    # STATUS_DATA_ROLE = Qt.ItemDataRole.UserRole + 1

    # status_updated = pyqtSignal(str, str, int)  # file_path, status, count

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Cache the standard icons
        style = QApplication.style()
        # self.icon_ok = style.standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        # self.icon_warning = style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        # self.icon_critical = style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical)
        def tablerIcon(icon, color, size=128):
            return QIcon(
                TablerIcons
                .load(icon, color=color)
                .toqpixmap()
                .scaled(size, size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                )
            )
        self.icon_ok = tablerIcon(OutlineIcon.CIRCLE_CHECK, '#00bb39')
        self.icon_critical = tablerIcon(OutlineIcon.XBOX_X, '#e50000')
        self.icon_warning = tablerIcon(OutlineIcon.ALERT_CIRCLE, '#f8c350')
        self.icon_loading = tablerIcon(OutlineIcon.LOADER, '#000000')
        self.icon_live = tablerIcon(OutlineIcon.LIVE_PHOTO, '#000000')
        self.icon_nothing = tablerIcon(FilledIcon.POINT, '#bbbbbb')
        self.status_icons = {
            'ok': self.icon_ok,
            'warning': self.icon_warning,
            'critical': self.icon_critical,
            'loading': self.icon_loading,
            'nothing': self.icon_nothing
        }
        # # Initialize the cache
        # self.status_cache = {}
        # Initialize the cache with a maximum size to prevent unlimited growth
        self.status_cache = LRUCache(maxsize=10000)  # Store up to 10000 entries

        # Initialize the thread pool
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(8)
        self.thread_pool.setThreadPriority(QThread.Priority.LowPriority)
        logging.debug(f"Multithreading with maximum {self.thread_pool.maxThreadCount()} threads")

        # # Connect the status_updated signal to a slot
        # self.status_updated.connect(self.on_status_updated)

        # Connect signals to cache invalidation methods
        self.directoryLoaded.connect(self.on_directory_loaded)
        self.fileRenamed.connect(self.on_file_renamed)
        # self.dataChanged.connect(self.on_data_changed)
        self.modelReset.connect(self.on_model_reset)

    def columnCount(self, parent=QModelIndex()):
        return super().columnCount(parent) + 3  # Add three extra columns

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        column = index.column()
        file_info = self.fileInfo(index)

        # logging.debug(f"Cached status: {asizeof.asizeof(self.status_cache) / 1000} KB")
        if column == self.COLUMN_DATE_MODIFIED:
            if role == Qt.ItemDataRole.DisplayRole:
                date_time = file_info.lastModified()
                return date_time.toString("yyyy-MM-dd HH:mm:ss")
            else:
                return None
        # elif column == self.COLUMN_STATUS_NUMBER:
        #     if role == Qt.ItemDataRole.DisplayRole:
        #         status, count = self.get_status(file_info.absoluteFilePath())
        #         return str(count)
        #     elif role == Qt.ItemDataRole.TextAlignmentRole:
        #         return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        #     else:
        #         return None
        # elif column == self.COLUMN_STATUS_NUMBER:
        #     if role == Qt.ItemDataRole.DisplayRole:
        #         # Try to retrieve the cached status from the index's data
        #         status_data = super().data(index, STATUS_DATA_ROLE)
        #         # logging.debug(status_data)
        #         # print(status_data)
        #         if status_data is None:
        #             # Compute and set the status data
        #             status, count = self.get_status(file_info.absoluteFilePath())
        #             # Store the status data in the model
        #             self.setData(index, (status, count), STATUS_DATA_ROLE)
        #             # print(status, count)
        #             # print(index.data(STATUS_DATA_ROLE))
        #             # print(super().data(index, STATUS_DATA_ROLE))
        #         # else:
        #             _, count = status_data
        #         return str(count)
        #     # elif role == Qt.ItemDataRole.TextAlignmentRole:
        #     #     return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        #     else:
        #         return None
        # elif column == self.COLUMN_STATUS_ICON:
        #     # if role == Qt.ItemDataRole.DecorationRole:
        #     #     status, _ = self.get_status(file_info.absoluteFilePath())
        #     #     icon = self.status_icons.get(status)
        #     #     return icon
        #     # else:
        #     #     return None
        #     if role == Qt.ItemDataRole.DecorationRole:
        #         status_data = index.data(STATUS_DATA_ROLE)
        #         if status_data is None:
        #             # Compute and store the status data
        #             status, count = self.get_status(file_info.absoluteFilePath())
        #             self.setData(index, (status, count), STATUS_DATA_ROLE)
        #         else:
        #             # logging.debug(status_data)
        #             status, _ = status_data
        #         icon = self.status_icons.get(status)
        #         return icon
        #     elif role == STATUS_DATA_ROLE:
        #         return super().data(index, role)
        #     else:
        #         return None
        elif column == self.COLUMN_STATUS_NUMBER:
            if role == Qt.ItemDataRole.DisplayRole:
                # print(index, file_info.absoluteFilePath())
                status, count = self.get_status(file_info.absoluteFilePath())
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
                status, _ = self.get_status(file_info.absoluteFilePath())
                icon = self.status_icons.get(status)
                return icon
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
                    return "Number"
                elif section == self.COLUMN_STATUS_ICON:
                    return "Status"
        return super().headerData(section, orientation, role)

    def get_status(self, folder_path):
        # ok_num = self.get_ok_num(file_or_folder_path)
        # warning_num = self.get_warning_num(file_or_folder_path)
        # critical_num = self.get_critical_num(file_or_folder_path)
        # if critical_num > 0:
        #     return ('critical', critical_num)
        # elif warning_num > 0:
        #     return ('warning', warning_num)
        # else:
        #     return ('ok', ok_num)

        # statuses = ['ok', 'warning', 'critical', 'loading']
        # status = random.choice(statuses)
        # count = random.randint(10**(length := random.randint(0, 5)), 10**(length + 1) - 1)
        # return (status, count)


        # # Check if the status is already cached
        # if file_or_folder_path in self.status_cache:
        #     return self.status_cache[file_or_folder_path]

        # # Attempt to retrieve the status from the cache
        # status_data = self.status_cache.get(file_or_folder_path)
        # if status_data is not None:
        #     return status_data
        # else:
        #     # # Simulate the costly computation
        #     # statuses = ['ok', 'warning', 'critical', 'loading']
        #     # status = random.choice(statuses)
        #     # count = random.randint(10 ** (length := random.randint(0, 5)), 10 ** (length + 1) - 1)
        #     # result = (status, count)
        #     # # Store the result in the cache
        #     # self.status_cache[file_or_folder_path] = result
        #     # return result
        #
        #     # Set status to 'loading' in cache
        #     self.status_cache[file_or_folder_path] = ('loading', 0)
        #     # Emit dataChanged to update the view with 'loading' status
        #     index = self.index(file_or_folder_path)
        #     if index.isValid():
        #         self.dataChanged.emit(index, index, [Qt.ItemDataRole.DecorationRole, Qt.ItemDataRole.DisplayRole])
        #     # Create and start the worker
        #     worker = Worker(file_or_folder_path)
        #     worker.signals.finished.connect(self.on_status_computed)
        #     self.thread_pool.start(worker)
        #     return ('loading', 0)
        #

        # logging.debug(f"Getting status for: {folder_path}")
        # Check if the status is already cached
        status_data = self.status_cache.get(folder_path)
        if status_data is not None:
            return status_data
        else:
            logging.debug(f"Status not cached for: {folder_path}")
            # Set status to 'loading' in cache
            self.status_cache[folder_path] = ('loading', 0)
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
            worker = Worker(folder_path)
            worker.signals.finished.connect(self.on_status_computed)
            self.thread_pool.start(worker)
            return ('loading', 0)

    # def on_status_computed(self, file_path, status, count):
    #     logging.debug(f"Status computed for {file_path}: {status}, {count}")
    #     # Update the cache with the computed status
    #     self.status_cache[file_path] = (status, count)
    #     # Emit dataChanged to refresh the view
    #     index = self.index(file_path)
    #     if index.isValid():
    #         self.dataChanged.emit(index, index, [Qt.ItemDataRole.DecorationRole, Qt.ItemDataRole.DisplayRole])
    def on_status_computed(self, file_path, status, count):
        logging.debug(f"Status computed for: {file_path}: {status}, {count}, Cached: {asizeof.asizeof(self.status_cache) / 1000} KB")
        # Update the cache with the computed status
        self.status_cache[file_path] = (status, count)

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

    # def on_data_changed(self, topLeft, bottomRight, roles):
    #     # UNTESTED!
    #     # If a file's data changes, invalidate its cache entry
    #     if Qt.ItemDataRole.DisplayRole in roles or Qt.ItemDataRole.DecorationRole in roles:
    #         for row in range(topLeft.row(), bottomRight.row() + 1):
    #             index = self.index(row, self.COLUMN_NAME, topLeft.parent())
    #             file_path = self.filePath(index)
    #             self.status_cache.pop(file_path, None)
    #             self.get_status(file_path)

    # def on_data_changed(self, path):
    #     # Invalidate the cache entry for the changed file
    #     self.status_cache.pop(path, None)
    #     logging.debug(f"(POP)Data changed for: {path}")

    def on_model_reset(self):
        # Clear the entire cache
        self.status_cache.clear()
        logging.debug(f"(CLEAR) Model reset")

    def invalidate_cache_for_directory(self, directory_path):
        # Remove all cached entries under the given directory
        keys_to_remove = [key for key in self.status_cache if key.startswith(directory_path)]
        for key in keys_to_remove:
            del self.status_cache[key]


    # def get_ok_num(self, file_or_folder_path):
    #     # Placeholder function to compute ok_num
    #     return 9999 + len(file_or_folder_path)  # For testing purposes
    #
    # def get_warning_num(self, file_or_folder_path):
    #     # Placeholder function to compute warn_num
    #     # Replace with actual computation
    #     return random.randint(0, 1000)  # For testing purposes
    #
    # def get_critical_num(self, file_or_folder_path):
    #     # Placeholder function to compute critical_num
    #     # Replace with actual computation
    #     return file_or_folder_path.count('a')  # For testing purposes






class CenteredIconDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        # Clear the icon to prevent the default drawing
        option.icon = QIcon()

    def paint(self, painter, option, index):
        # Call the base class paint method (which won't draw the icon now)
        super().paint(painter, option, index)
        # Draw your centered icon
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon:
            rect = option.rect
            icon_size = icon.actualSize(option.decorationSize)
            x = rect.left() + (rect.width() - icon_size.width()) // 2
            y = rect.top() + (rect.height() - icon_size.height()) // 2
            icon.paint(painter, QRect(x, y, icon_size.width(), icon_size.height()))
        # If no icon, nothing else to do

    def sizeHint(self, option, index):
        # Ensure the size hint accommodates the icon
        size = super().sizeHint(option, index)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon:
            icon_size = icon.actualSize(option.decorationSize)
            size.setHeight(max(size.height(), icon_size.height()))
        return size



class FileSystemView(QWidget):
    def __init__(self, dir_path, target_path, columns_to_show=None):
        super().__init__()
        appWidth = 800
        appHeight = 800

        self.setWindowTitle('File System Viewer')
        self.setGeometry(300, 300, appWidth, appHeight)

        self.model = CustomFileSystemModel()
        self.model.setRootPath(dir_path)
        self.model.setReadOnly(True)
        # self.model.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot | QDir.Filter.Hidden)
        self.model.setFilter(QDir.Filter.Dirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Hidden)

        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(dir_path))
        self.tree.setColumnWidth(CustomFileSystemModel.COLUMN_NAME, 250)
        self.tree.setColumnWidth(CustomFileSystemModel.COLUMN_DATE_MODIFIED, 160)
        self.tree.setColumnWidth(CustomFileSystemModel.COLUMN_STATUS_NUMBER, 80)
        self.tree.setColumnWidth(CustomFileSystemModel.COLUMN_STATUS_ICON, 60)
        self.tree.setColumnWidth(CustomFileSystemModel.COLUMN_RIGHTFILL, 0)
        self.tree.setAlternatingRowColors(True)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(True)

        # Set the custom delegate for the icon column
        icon_delegate = CenteredIconDelegate(self.tree)
        self.tree.setItemDelegateForColumn(CustomFileSystemModel.COLUMN_STATUS_ICON, icon_delegate)

        # Control which columns to show
        if columns_to_show is not None:
            total_columns = self.model.columnCount()
            for col in range(total_columns):
                if col not in columns_to_show:
                    self.tree.setColumnHidden(col, True)

        header = self.tree.header()
        # Make the first column auto-resizable
        header.setSectionResizeMode(CustomFileSystemModel.COLUMN_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(CustomFileSystemModel.COLUMN_NAME, QHeaderView.ResizeMode.Interactive)
        # Other columns resize to contents
        header.setSectionResizeMode(CustomFileSystemModel.COLUMN_SIZE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(CustomFileSystemModel.COLUMN_TYPE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(CustomFileSystemModel.COLUMN_DATE_MODIFIED, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(CustomFileSystemModel.COLUMN_STATUS_NUMBER, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(CustomFileSystemModel.COLUMN_STATUS_ICON, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(CustomFileSystemModel.COLUMN_RIGHTFILL, QHeaderView.ResizeMode.ResizeToContents)
        # self.tree.setColumnWidth(CustomFileSystemModel.COLUMN_STATUS_ICON, 60)
        # self.tree.setColumnWidth(CustomFileSystemModel.COLUMN_RIGHTFILL, 0)

        # Create a back button
        self.back_button = QPushButton('Back')
        self.back_button.clicked.connect(self.on_back_button_clicked)

        layout = QVBoxLayout()
        layout.addWidget(self.back_button)
        layout.addWidget(self.tree)
        self.setLayout(layout)

        # Connect the selectionChanged signal to the slot
        self.tree.selectionModel().selectionChanged.connect(self.on_selection_changed)

        # Connect the double-click signal to open directories
        self.tree.doubleClicked.connect(self.on_double_click)

        # Update back button state
        self.update_back_button_state()

        # Automatically expand the view to the desired path
        # QTimer.singleShot(1000, lambda: self.expand_to_path(target_path))
        self.expand_to_path(target_path)

        # **Added Lines: Set context menu policy and connect the signal**
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)


    def on_selection_changed(self, selected, deselected):
        indexes = self.tree.selectionModel().selectedRows()
        for index in indexes:
            file_path = self.model.filePath(index)
            logging.debug(f"Selected file path: {file_path}")

    def expand_to_path(self, path):
        index = self.model.index(path)
        if not index.isValid():
            logging.warning(f"Invalid path: {path}")
            return
        # Expand all parent items
        parent_index = index.parent()
        while parent_index.isValid():
            self.tree.expand(parent_index)
            parent_index = parent_index.parent()
        # Expand the target index
        self.tree.expand(index)
        # Set the current selection to the target index
        self.tree.setCurrentIndex(index)
        # Update the tree view to ensure it's fully rendered
        # self.tree.update()
        # QTimer.singleShot(1000, lambda: self.tree.update())
        # Scroll to the target index
        # self.tree.scrollTo(index, QTreeView.ScrollHint.PositionAtCenter)
        self.tree.scrollTo(index, QTreeView.ScrollHint.EnsureVisible)
        # QTimer.singleShot(1000, lambda: self.tree.scrollTo(index, QTreeView.ScrollHint.EnsureVisible))

        # self.tree.setFocus()

    def on_double_click(self, index):
        file_info = self.model.fileInfo(index)
        if file_info.isDir():
            logging.debug(f"Double-clicked directory: {file_info.absoluteFilePath()}")
            # Set this directory as the new root
            self.tree.setRootIndex(index)
            # Update the back button enabled state
            self.update_back_button_state()

    def on_back_button_clicked(self):
        current_root_index = self.tree.rootIndex()
        parent_index = current_root_index.parent()
        if parent_index.isValid():
            self.tree.setRootIndex(parent_index)
        else:
            # If no parent, set to the model's root
            self.tree.setRootIndex(self.model.index(self.model.rootPath()))
        # Update the back button enabled state
        self.update_back_button_state()

    def update_back_button_state(self):
        current_root_index = self.tree.rootIndex()
        if current_root_index == self.model.index(self.model.rootPath()):
            self.back_button.setEnabled(False)
        else:
            self.back_button.setEnabled(True)

    # def contextMenuEvent(self, event):
    #     index = self.tree.indexAt(event.pos())
    #     if not index.isValid():
    #         return
    #
    #     # # **Added Line: Select the item under the cursor**
    #     # self.tree.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.ClearAndSelect)
    #
    #     folder_info = self.model.fileInfo(index)
    #     menu = QMenu(self)
    #     logging.debug(f"Context menu for: {folder_info.absoluteFilePath()}")
    #
    #     action1 = QAction("QAction 1", self)
    #     action1.triggered.connect(lambda: self.context_menu_action_1(folder_info))
    #     menu.addAction(action1)
    #
    #     action2 = QAction("QAction 2", self)
    #     action2.triggered.connect(lambda: self.context_menu_action_2(folder_info))
    #     menu.addAction(action2)
    #
    #     menu.exec(event.globalPos())

    def show_context_menu(self, position):
        # Map the position to the tree view's viewport
        index = self.tree.indexAt(position)
        if not index.isValid():
            return

        # **Select the item under the cursor**
        self.tree.setCurrentIndex(index)
        self.tree.selectionModel().select(
            index,
            QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Select
        )

        # Retrieve file information after selection
        file_info = self.model.fileInfo(index)

        # **Create and populate the context menu**
        menu = QMenu(self)

        action1 = QAction("Recalculate Status", self)
        action1.triggered.connect(lambda: self.context_menu_action_1(file_info))
        menu.addAction(action1)

        action2 = QAction("Recursively Recalculate Status", self)
        action2.triggered.connect(lambda: self.context_menu_action_2(file_info))
        menu.addAction(action2)

        # **Display the context menu at the cursor's global position**
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def context_menu_action_1(self, folder_info):
        logging.debug(f"QAction 1: {folder_info.absoluteFilePath()}")
        # Invalidate the cached status
        self.model.status_cache.pop(folder_info.absoluteFilePath(), None)
        # Trigger a fresh status computation
        self.model.get_status(folder_info.absoluteFilePath())

    # def context_menu_action_2(self, folder_info):
    #     logging.debug(f"QAction 2: {folder_info.absoluteFilePath()}")
    def context_menu_action_2(self, folder_info):
    # WARNING: THIS METHOD IS REALLY SHIT
        file_path = folder_info.absoluteFilePath()
        if not folder_info.isDir():
            logging.debug(f"Selected item is not a directory: {file_path}")
            return
        logging.debug(f"Recursively recalculating status for: {file_path}")
        for root, dirs, _ in os.walk(file_path):
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                logging.debug(f"Recalculating status for: {dir_path}")
                # Invalidate the cached status for the directory
                self.model.status_cache.pop(dir_path, None)
                # Trigger a fresh status computation for the directory
                self.model.get_status(dir_path)


if __name__ == '__main__':

    font = QFont("SF Mono")

    app = QApplication(sys.argv)
    app.setFont(font)

    dirPath = r''  # Replace with your directory path
    target_path = r'/Users/tonyyan/Downloads'  # Replace with the path you want to view

    # Specify columns to show; show Name, Date Modified, Number, and Status Icon columns
    columns_to_show = [
        CustomFileSystemModel.COLUMN_NAME,
        CustomFileSystemModel.COLUMN_DATE_MODIFIED,
        CustomFileSystemModel.COLUMN_STATUS_NUMBER,
        CustomFileSystemModel.COLUMN_STATUS_ICON,
        CustomFileSystemModel.COLUMN_RIGHTFILL
    ]
    demo = FileSystemView(dirPath, target_path, columns_to_show)
    demo.show()
    sys.exit(app.exec())
