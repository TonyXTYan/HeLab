import sys
import os

from PIL.ImageDraw import Outline
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QTreeView,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
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
    QEvent,
    QObject,
    pyqtSignal,
    QRunnable,
    QThreadPool,
    QThread,
    QItemSelectionModel,
    QPoint,
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

# STATUS_DATA_ROLE = Qt.ItemDataRole.UserRole + 1 # I don't think this is doing anything?

# Define WorkerSignals to communicate between threads
class StatusWorkerSignals(QObject):
    # finished = pyqtSignal(str, str, int)  # file_path, status, count
    finished = pyqtSignal(str, str, int, list)  # file_path, status, count, extra_icons
# Define the Worker class with cancellation support
class StatusWorker(QRunnable):
    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self.signals = StatusWorkerSignals()
        self._is_canceled = False

    def run(self):
        logging.debug(f"Worker started for: {self.file_path}")
        if self._is_canceled:
            logging.debug(f"Worker canceled for: {self.file_path}")
            return

        # Simulate a long-running computation
        time.sleep(random.uniform(0.2, 0.5))  # Simulate computation delay

        # Replace the following with your actual status computation logic
        statuses = ['ok', 'warning', 'critical', 'nothing']
        status = random.choice(statuses)
        # count = random.randint(1, 100)
        count = random.randint(10**(length := random.randint(0, 5)), 10**(length + 1) - 1)

        # Determine extra icons based on status and count
        # extra_icons = []
        # if count > 50:
        #     extra_icons.append('database')  # Represented by 'icon_database'
        # if count % 2 == 0:
        #     extra_icons.append('report')  # Represented by 'icon_report'
        # if status == 'critical':
        #     extra_icons.append('ram')  # Represented by 'icon_ram'
        extra_icons = sorted(random.sample(CustomFileSystemModel.STATUS_ICONS_EXTRA_NAME, random.randint(0, 4)), key=CustomFileSystemModel.STATUS_ICONS_EXTRA_NAME_SORT_KEY.get)


        logging.debug(f"Worker finished for: {self.file_path} with status: {status}, count: {count}, extra icons: {extra_icons}")
        self.signals.finished.emit(self.file_path, status, count, extra_icons)

    def cancel(self):
        self._is_canceled = True

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


class CustomFileSystemModel(QFileSystemModel):
    COLUMN_NAME = 0
    COLUMN_SIZE = 1
    COLUMN_TYPE = 2
    COLUMN_DATE_MODIFIED = 3
    COLUMN_STATUS_NUMBER = 4
    COLUMN_STATUS_ICON = 5
    COLUMN_RIGHTFILL = 6
    STATUS_EXTRA_ICONS_ROLE = Qt.ItemDataRole.UserRole + 1

    STATUS_ICONS_NAME = ['ok', 'warning', 'critical', 'loading', 'nothing']
    STATUS_ICONS_EXTRA_NAME = ['database', 'report', 'chart3d', 'ram', 'live']
    STATUS_ICONS_EXTRA_NAME_SORT_KEY = {
        'database': 10,
        'report': 31,
        'chart3d': 30,
        'ram': 11,
        'live': 0,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Cache the standard icons
        style = QApplication.style()
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
        self.icon_loading = tablerIcon(OutlineIcon.LOADER, '#000000')   #TODO: replace this with PERCENTAGE
        self.icon_live = tablerIcon(OutlineIcon.LIVE_PHOTO, '#000000')
        self.icon_nothing = tablerIcon(FilledIcon.POINT, '#bbbbbb')
        self.status_icons = {
            'ok': self.icon_ok,
            'warning': self.icon_warning,
            'critical': self.icon_critical,
            'loading': self.icon_loading,
            'nothing': self.icon_nothing
        }
        self.icon_database = tablerIcon(OutlineIcon.DATABASE, '#444444')
        self.icon_report = tablerIcon(OutlineIcon.REPORT_ANALYTICS, '#444444')
        self.icon_chart3d = tablerIcon(OutlineIcon.CHART_SCATTER_3D, '#444444')
        self.icon_ram = tablerIcon(OutlineIcon.CONTAINER, '#444444')

        # Map icon keys to QIcons for easy retrieval
        self.status_icons_extra = {
            'database': self.icon_database,
            'report': self.icon_report,
            'chart3d': self.icon_chart3d,
            'ram': self.icon_ram,
            'live': self.icon_live
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

        # Initialize a set to keep track of running workers
        self.running_workers = {}

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
                icon = self.status_icons.get(status)
                return icon
            elif role == self.STATUS_EXTRA_ICONS_ROLE:
                # # Example logic to determine which extra icons to show
                # status, count = self.get_status(file_info.absoluteFilePath())
                # extra_icons = []
                # if count > 50:
                #     extra_icons.append(self.icon_database)
                # if count % 2 == 0:
                #     extra_icons.append(self.icon_report)
                # if status == 'critical':
                #     extra_icons.append(self.icon_ram)
                # return extra_icons
                # Retrieve extra icons from the cache
                _, _, extra_icons = self.fetch_status(file_info.absoluteFilePath())
                return [self.status_icons_extra.get(icon_key) for icon_key in extra_icons]
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
            if folder_path in self.running_workers:
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
            self.running_workers[folder_path] = worker
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
        if file_path in self.running_workers:
            del self.running_workers[file_path]
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
    #     # self.status_cache.pop(path, None)
    #     # logging.debug(f"(POP)Data changed for: {path}")
    #     logging.debug(f"Data changed for: {path}")
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
        for file_path, worker in list(self.running_workers.items()):
            worker.cancel()
            # self.running_workers.remove(worker)
            del self.running_workers[file_path]
            logging.debug(f"Worker canceled for: {file_path}")
        # Optionally, clear the thread pool's queue if possible
        # Note: QThreadPool does not provide a direct method to clear pending tasks
        # So, we rely on workers to check for cancellation
        logging.debug("All scans have been requested to stop.")


class StatusIconDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        # Clear the icon to prevent the default drawing
        option.icon = QIcon()

    def paint(self, painter, option, index):
        # Paint the base item (text, etc.) without the default decoration
        option_copy = QStyleOptionViewItem(option)
        option_copy.decorationSize = QSize(0, 0)  # Prevent default decoration
        super().paint(painter, option_copy, index)

        # Retrieve the main status icon
        status_icon = index.data(Qt.ItemDataRole.DecorationRole)
        # Retrieve the extra icons
        extra_icons = index.data(CustomFileSystemModel.STATUS_EXTRA_ICONS_ROLE)
        rect = option.rect
        x = rect.left() + 5  # Some padding from the left
        y = rect.top() + (rect.height() - option.decorationSize.height()) // 2

        # Draw the status icon
        if status_icon:
            icon_size = option.decorationSize
            status_icon.paint(painter, QRect(x, y, icon_size.width(), icon_size.height()))
            x += icon_size.width() + 2  # Spacing between icons

        # Draw the extra icons
        if extra_icons:
            for icon in extra_icons:
                if icon:
                    icon_size = option.decorationSize
                    icon.paint(painter, QRect(x, y, icon_size.width(), icon_size.height()))
                    x += icon_size.width() + 2  # Spacing between icons

    def sizeHint(self, option, index):
        # Ensure the size hint accommodates all icons
        base_size = super().sizeHint(option, index)
        status_icon = index.data(Qt.ItemDataRole.DecorationRole)
        extra_icons = index.data(CustomFileSystemModel.STATUS_EXTRA_ICONS_ROLE)
        total_width = base_size.width()
        if status_icon:
            total_width += option.decorationSize.width() + 4  # Status icon and spacing
        if extra_icons:
            total_width += len(extra_icons) * (option.decorationSize.width() + 4)  # Extra icons and spacing
        return QSize(total_width, base_size.height())


class StatusHoverIconInfo(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        # Update window flags to include WindowStaysOnTopHint and remove FramelessWindowHint
        self.setWindowFlags(
            Qt.WindowType.Popup |
            Qt.WindowType.WindowStaysOnTopHint
        )
        # self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        layout = QVBoxLayout()
        # Reduce the margins and spacing to minimize padding
        layout.setContentsMargins(8, 6, 8, 2)  # left, top, right, bottom
        layout.setSpacing(4)  # space between widgets

        self.label = QLabel("Detailed Info")
        self.button1 = QPushButton("Action 1")
        self.button2 = QPushButton("Action 2")

        # Connect buttons to placeholder functions
        self.button1.clicked.connect(self.action1)
        self.button2.clicked.connect(self.action2)

        layout.addWidget(self.label)

        button_layout = QHBoxLayout()
        # Remove margins and reduce spacing between buttons
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(2)

        button_layout.addWidget(self.button1)
        button_layout.addWidget(self.button2)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def set_info(self, info_text):
        self.label.setText(info_text)

    # Placeholder function for Action 1
    def action1(self):
        logging.debug("Action 1 triggered")
        # You can replace the print statement with actual functionality later

    # Placeholder function for Action 2
    def action2(self):
        logging.debug("Action 2 triggered")
        # You can replace the print statement with actual functionality later

class StatusTreeView(QTreeView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.popup = StatusHoverIconInfo()
        self.popup.setParent(None)  # Make it a top-level window
        self.popup.installEventFilter(self)
        self.current_hover_index = QModelIndex()
        self.popup_visible = False

        # Timer to delay hiding the popup
        self.hover_timer = QTimer()
        self.hover_timer.setSingleShot(True)
        self.hover_timer.timeout.connect(self.hide_popup)

        self.popup.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj == self.popup:
            if event.type() == QEvent.Type.Enter:
                # Stop the hide timer when cursor enters the popup
                self.hover_timer.stop()
            elif event.type() == QEvent.Type.Leave:
                # Start the hide timer when cursor leaves the popup
                self.hover_timer.start(500)  # Delay hiding by 500 ms
        return super().eventFilter(obj, event)

    def mouseMoveEvent(self, event):
        pos = event.pos()
        index = self.indexAt(pos)
        if index.isValid() and index.column() == CustomFileSystemModel.COLUMN_STATUS_ICON:
            # Determine if the mouse is over the icon area
            rect = self.visualRect(index)
            icon_size = self.iconSize()
            padding = 5  # Adjust based on your delegate's padding
            status_icon_rect = QRect(
                rect.left() + padding,
                rect.top() + (rect.height() - icon_size.height()) // 2,
                icon_size.width(),
                icon_size.height()
            )
            extra_icons = index.data(CustomFileSystemModel.STATUS_EXTRA_ICONS_ROLE)
            extra_icon_rects = []
            if extra_icons:
                x_offset = status_icon_rect.right() + 2  # 2px spacing between icons
                for _ in extra_icons:
                    extra_rect = QRect(
                        x_offset,
                        rect.top() + (rect.height() - icon_size.height()) // 2,
                        icon_size.width(),
                        icon_size.height()
                    )
                    extra_icon_rects.append(extra_rect)
                    x_offset += icon_size.width() + 2

            # Check if the mouse is within any icon rect
            over_icon = False
            if status_icon_rect.contains(event.pos()):
                over_icon = True
            else:
                for extra_rect in extra_icon_rects:
                    if extra_rect.contains(event.pos()):
                        over_icon = True
                        break

            if over_icon:
                if index != self.current_hover_index:
                    self.current_hover_index = index
                    self.show_popup(event.globalPosition().toPoint(), index)
            else:
                self.hover_timer.start(300)  # Delay hiding by 300ms
        else:
            self.hover_timer.start(300)  # Delay hiding by 300ms
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.hover_timer.start(300)  # Delay hiding by 300ms
        super().leaveEvent(event)

    def show_popup(self, global_pos, index):
        if not index.isValid():
            return
        # Get data from the model
        file_path = self.model().filePath(index)
        # status, count, extra_icons = self.model().get_status(file_path)
        status, count, extra_icons = self.model().fetch_status(file_path)
        info_text = f"Path: {file_path}\nStatus: {status}\nCount: {count}\nExtra Icons: {', '.join(extra_icons) if extra_icons else 'None'}"
        self.popup.set_info(info_text)
        # Position the popup near the cursor
        # self.popup.move(global_pos + QPoint(10, 10))  # Slight offset
        self.popup.move(global_pos - QPoint(1, 1))  # Slight offset
        self.popup.show()
        self.popup_visible = True

    def hide_popup(self):
        if self.popup_visible and self.popup is not None:
            try:
                self.popup.hide()
            except RuntimeError:
                logging.error("Attempted to hide a deleted popup")
            # self.popup.hide()
            self.popup_visible = False
            self.current_hover_index = QModelIndex()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.hide_popup()


class FolderExplorer(QWidget):
    def __init__(self, dir_path, target_path, view_path, columns_to_show=None):
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

        # Initialize view_path
        self.dir_path = dir_path  # System root path
        self.target_path = target_path  # Path to auto-expand upon opening
        self.view_path = view_path  # Current root path of the view

        # self.tree = QTreeView()
        self.tree = StatusTreeView()
        self.tree.setModel(self.model)
        # self.tree.setRootIndex(self.model.index(dir_path))
        self.tree.setRootIndex(self.model.index(self.view_path))
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
        icon_delegate = StatusIconDelegate(self.tree)
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

        # Create a horizontal layout for buttons
        button_layout = QHBoxLayout()
        # Create a back button
        self.back_button = QPushButton('Back')
        self.back_button.clicked.connect(self.on_back_button_clicked)
        button_layout.addWidget(self.back_button)

        # Create the "Stop all scans" button
        self.stop_button = QPushButton('Stop all scans')
        self.stop_button.clicked.connect(self.on_stop_button_clicked)
        button_layout.addWidget(self.stop_button)

        # Add stretch to push buttons to the left
        button_layout.addStretch()


        layout = QVBoxLayout()
        # layout.addWidget(self.back_button)
        layout.addLayout(button_layout)
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
        self.expand_to_path(self.target_path)

        # **Added Lines: Set context menu policy and connect the signal**
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)


    def on_selection_changed(self, selected, deselected):
        indexes = self.tree.selectionModel().selectedRows()
        for index in indexes:
            file_path = self.model.filePath(index)
            logging.debug(f"Selected file path: {file_path}")

    def expand_to_path(self, path):
        # Ensure that the path to expand is under the current view_path
        if not os.path.commonpath([self.view_path, path]) == os.path.abspath(self.view_path):
            logging.warning(f"Path {path} is not under the current view path {self.view_path}.")
            return
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
        logging.debug(f"Expanded to path: {path}")

    def on_double_click(self, index):
        file_info = self.model.fileInfo(index)
        if file_info.isDir():
            logging.debug(f"Double-clicked directory: {file_info.absoluteFilePath()}")
            # Set this directory as the new root (view path)
            self.tree.setRootIndex(index)
            # self.view_path = file_info.absoluteFilePath()
            # self.tree.setRootIndex(self.model.index(self.view_path))
            # Update the back button enabled state
            self.update_back_button_state()

    def on_back_button_clicked(self):
        current_root_index = self.tree.rootIndex()
        parent_index = current_root_index.parent()
        if parent_index.isValid():
            self.tree.setRootIndex(parent_index)
        else:
            # If no parent, set to the model's root (view path)
            self.tree.setRootIndex(self.model.index(self.model.rootPath()))
        # Update the back button enabled state
        self.update_back_button_state()
        # if self.view_path != self.dir_path:
        #     self.view_path = self.dir_path
        #     self.tree.setRootIndex(self.model.index(self.view_path))
        #     # Update the back button enabled state
        #     self.update_back_button_state()
        #     logging.debug(f"Back button clicked. Set view_path to dirPath: {self.view_path}")

    def update_back_button_state(self):
        # current_root_index = self.tree.rootIndex()
        # # current_root_index = QDir.rootPath()  # Start from the root directory
        # if current_root_index == self.model.index(self.model.rootPath()):
        #     self.back_button.setEnabled(False)
        # else:
        #     self.back_button.setEnabled(True)
        if self.view_path == self.dir_path:
            self.back_button.setEnabled(False)
        else:
            self.back_button.setEnabled(True)


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

        action_recalc_status = QAction("Recalculate Status", self)
        action_recalc_status.triggered.connect(lambda: self.context_menu_action_recalc_status(file_info))
        menu.addAction(action_recalc_status)

        action_recursive_calc_status = QAction("Recursively Recalculate Status", self)
        action_recursive_calc_status.triggered.connect(lambda: self.context_menu_action_recursive_calc_status(file_info))
        menu.addAction(action_recursive_calc_status)

        # **Display the context menu at the cursor's global position**
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def context_menu_action_recalc_status(self, folder_info):
        logging.debug(f"QAction 1: {folder_info.absoluteFilePath()}")
        # Invalidate the cached status
        self.model.status_cache.pop(folder_info.absoluteFilePath(), None)
        # Trigger a fresh status computation
        self.model.fetch_status(folder_info.absoluteFilePath())

    # def context_menu_action_2(self, folder_info):
    #     logging.debug(f"QAction 2: {folder_info.absoluteFilePath()}")
    def context_menu_action_recursive_calc_status(self, folder_info):
    # WARNING: THIS METHOD IS REALLY SHIT
        file_path = folder_info.absoluteFilePath()
        if not folder_info.isDir():
            logging.debug(f"Selected item is not a directory: {file_path}")
            return
        logging.debug(f"Recursively recalculating status for: {file_path}")
        # for root, dirs, _ in os.walk(file_path):
        #     for dir_name in dirs:
        #         dir_path = os.path.join(root, dir_name)
        #         logging.debug(f"Recalculating status for: {dir_path}")
        #         # Invalidate the cached status for the directory
        #         self.model.status_cache.pop(dir_path, None)
        #         # Trigger a fresh status computation for the directory
        #         self.model.fetch_status(dir_path)
        # Create a worker to perform os.walk
        worker = RecursiveStatusWorker(file_path)
        worker.signals.finished.connect(self.process_recursive_status)
        self.model.thread_pool.start(worker)

    def process_recursive_status(self, directory_list):
        logging.debug(f"Processing {len(directory_list)} directories for status recalculation")
        self.directory_iterator = iter(directory_list)
        self.process_next_directories()

    def process_next_directories(self):
        # Process a batch of directories
        batch_size = 100  # Adjust as needed
        count = 0
        try:
            while count < batch_size:
                dir_path = next(self.directory_iterator)
                logging.debug(f"Recalculating status for: {dir_path}")
                self.model.status_cache.pop(dir_path, None)
                self.model.fetch_status(dir_path)
                count += 1
        except StopIteration:
            # No more directories
            logging.debug("Finished processing directories for status recalculation")
            return
        # Schedule next batch
        QTimer.singleShot(0, self.process_next_directories)

    def on_stop_button_clicked(self):
        logging.debug("Stop all scans button clicked.")
        self.model.stop_all_scans()


if __name__ == '__main__':

    font = QFont("SF Mono")

    app = QApplication(sys.argv)
    app.setFont(font)

    dirPath = QDir.rootPath()  # Start from the root directory
    # dirPath = r''  # Replace with your directory path
    # target_path = r'/Users/tonyyan/Downloads'  # Replace with the path you want to view
    # dirPath = r''
    target_path = r'/Users/tonyyan/Library/CloudStorage/OneDrive-AustralianNationalUniversity/_He_BEC_data_root_copy'
    # target_path = r'/Users/tonyyan/Library/CloudStorage/OneDrive-AustralianNationalUniversity'
    # view_path = r'/Users/tonyyan/Library/CloudStorage/OneDrive-AustralianNationalUniversity/_He_BEC_data_root_copy'
    view_path = r'/Users/tonyyan/Library/CloudStorage/OneDrive-AustralianNationalUniversity'

    logging.debug(f"Root path: {dirPath}")
    logging.debug(f"Target path: {target_path}")
    # Validate that target_path is under dirPath
    if not os.path.commonpath([dirPath, target_path]) == os.path.abspath(dirPath):
        logging.warning(
            f"Target path {target_path} is not under the root path {dirPath}. Adjusting dirPath accordingly.")
        dirPath = os.path.dirname(target_path)


    # Specify columns to show; show Name, Date Modified, Number, and Status Icon columns
    columns_to_show = [
        CustomFileSystemModel.COLUMN_NAME,
        CustomFileSystemModel.COLUMN_DATE_MODIFIED,
        CustomFileSystemModel.COLUMN_STATUS_NUMBER,
        CustomFileSystemModel.COLUMN_STATUS_ICON,
        CustomFileSystemModel.COLUMN_RIGHTFILL
    ]
    demo = FolderExplorer(dirPath, target_path, view_path, columns_to_show)
    demo.show()
    # demo.open_view_path(view_path)

    sys.exit(app.exec())
