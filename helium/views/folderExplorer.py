import logging
import os

from PyQt6.QtCore import QSize, QDir, QItemSelectionModel, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QWidget, QHeaderView, QHBoxLayout, QVBoxLayout, QPushButton, QTreeView, QMenu

from helium.models.heliumFileSystemModel import CustomFileSystemModel
from helium.views.statusIconDelegate import StatusIconDelegate
from helium.views.statusTreeView import StatusTreeView


class FolderExplorer(QWidget):
    def __init__(self, dir_path, target_path, view_path, columns_to_show=None, parent=None):
        super().__init__(parent)
        # appWidth = 800
        # appHeight = 800

        # self.setWindowTitle('File System Viewer')
        # self.setGeometry(300, 300, appWidth, appHeight)

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
        self.tree.setContentsMargins(0, 0, 0, 0)
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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
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


    def update_back_button_state(self):
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
        logging.debug(f"Recalculate Status for : {folder_info.absoluteFilePath()}")
        # Invalidate the cached status
        self.model.status_cache.pop(folder_info.absoluteFilePath(), None)
        # Trigger a fresh status computation
        self.model.fetch_status(folder_info.absoluteFilePath())

    def context_menu_action_recursive_calc_status(self, folder_info):
    # WARNING: THIS METHOD IS REALLY SHIT
        file_path = folder_info.absoluteFilePath()
        if not folder_info.isDir():
            logging.debug(f"Selected item is not a directory: {file_path}")
            return
        logging.debug(f"Recursively recalculating status for: {file_path}")
        self.model.start_recursive_status_worker(file_path)


    def on_stop_button_clicked(self):
        logging.debug("Stop all scans button clicked.")
        self.model.stop_all_scans()
