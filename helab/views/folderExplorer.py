import logging
import os
import sys
from typing import Optional, Dict, List, Tuple

from PyQt6.QtCore import QSize, QDir, QItemSelectionModel, Qt, pyqtSignal, QThreadPool, QModelIndex, QItemSelection, \
    QPoint, QFileInfo
from PyQt6.QtGui import QAction, QFontInfo
from PyQt6.QtWidgets import QWidget, QHeaderView, QHBoxLayout, QVBoxLayout, QPushButton, QTreeView, QMenu
from cachetools import LRUCache

from helab.models.helabFileSystemModel import helabFileSystemModel
from helab.views.statusIconDelegate import StatusIconDelegate
from helab.views.statusTreeView import StatusTreeView
from helab.workers.statusDeepWorker import StatusDeepWorker
from helab.workers.statusWorker import StatusWorker


class FolderExplorer(QWidget):
    rootPathChanged = pyqtSignal(str)

    def __init__(self,
                 dir_path: str,
                 target_path: str,
                 view_path: str,
                 columns_to_show: List[int],
                 status_cache: LRUCache[str, Tuple[str, int, List[str]]],
                 thread_pool: QThreadPool,
                 running_workers_status: Dict[str, StatusWorker],
                 running_workers_deep: Dict[str, StatusDeepWorker],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # appWidth = 800
        # appHeight = 800

        # self.setWindowTitle('File System Viewer')
        # self.setGeometry(300, 300, appWidth, appHeight)

        # Initialize view_path
        self.dir_path = dir_path  # System root path
        self.target_path = target_path  # Path to auto-expand upon opening
        self.view_path = view_path  # Current root path of the view
        self.columns_to_show = columns_to_show

        self.status_cache = status_cache
        self.thread_pool = thread_pool
        self.running_workers_status = running_workers_status
        self.running_workers_deep = running_workers_deep

        self.model = helabFileSystemModel(status_cache, thread_pool, running_workers_status, running_workers_deep)
        self.model.setRootPath(dir_path)
        self.model.setReadOnly(True)
        # self.model.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot | QDir.Filter.Hidden)
        self.model.setFilter(QDir.Filter.Dirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Hidden)
        # self.rootPathChanged.emit(self.dir_path)


        # self.tree = QTreeView()
        self.tree = StatusTreeView()
        self.tree.setContentsMargins(0, 0, 0, 0)
        self.tree.setModel(self.model)
        # self.tree.setRootIndex(self.model.index(dir_path))
        self.tree.setRootIndex(self.model.index(self.view_path))
        self.tree.setColumnWidth(helabFileSystemModel.COLUMN_NAME, 250)
        self.tree.setColumnWidth(helabFileSystemModel.COLUMN_DATE_MODIFIED, 160)
        self.tree.setColumnWidth(helabFileSystemModel.COLUMN_STATUS_NUMBER, 80)
        self.tree.setColumnWidth(helabFileSystemModel.COLUMN_STATUS_ICON, 60)
        self.tree.setColumnWidth(helabFileSystemModel.COLUMN_RIGHTFILL, 0)
        self.tree.setAlternatingRowColors(True)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(True)
        self.back_button_enabled = False

        # Set the custom delegate for the icon column
        icon_delegate = StatusIconDelegate(self.tree)
        self.tree.setItemDelegateForColumn(helabFileSystemModel.COLUMN_STATUS_ICON, icon_delegate)

        # Control which columns to show, #TODO: move this to updatable columns to show
        if columns_to_show is not None:
            total_columns = self.model.columnCount()
            for col in range(total_columns):
                if col not in columns_to_show:
                    self.tree.setColumnHidden(col, True)


        header = self.tree.header()
        # Make the first column auto-resizable
        if header is None:
            logging.fatal("FolderExplorer.__init__ encountered None self.tree.header()")
            logging.fatal(f"{self.tree = }")
            return

        header.setSectionResizeMode(helabFileSystemModel.COLUMN_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(helabFileSystemModel.COLUMN_NAME, QHeaderView.ResizeMode.Interactive)
        # Other columns resize to contents
        header.setSectionResizeMode(helabFileSystemModel.COLUMN_SIZE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(helabFileSystemModel.COLUMN_TYPE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(helabFileSystemModel.COLUMN_DATE_MODIFIED, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(helabFileSystemModel.COLUMN_STATUS_NUMBER, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(helabFileSystemModel.COLUMN_STATUS_ICON, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(helabFileSystemModel.COLUMN_RIGHTFILL, QHeaderView.ResizeMode.ResizeToContents)
        # self.tree.setColumnWidth(helabFileSystemModel.COLUMN_STATUS_ICON, 60)
        # self.tree.setColumnWidth(helabFileSystemModel.COLUMN_RIGHTFILL, 0)

        # Create a horizontal main_layout for buttons
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
        # main_layout.addWidget(self.back_button)    # Disabled back and stop buttons, going to move this to the main window
        # main_layout.addLayout(button_layout)
        layout.addWidget(self.tree)
        self.setLayout(layout)

        selection_model = self.get_selection_model()

        # Connect the selectionChanged signal to the slot
        selection_model.selectionChanged.connect(self.on_selection_changed)

        # Connect the double-click signal to open directories
        self.tree.doubleClicked.connect(self.on_double_click)

        # Update back button state
        self.update_back_button_state()
        self.back_button_enabled = False

        # Automatically expand the view to the desired path
        # QTimer.singleShot(1000, lambda: self.expand_to_path(target_path))
        self.expand_to_path(self.target_path)

        # **Added Lines: Set context menu policy and connect the signal**
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)

        # self.rootPathChanged.emit(self.dir_path)
        self.emit_root_path_changed()


    def on_selection_changed(self, selected: QItemSelection, deselected: QItemSelection) -> None:
        selection_model = self.get_selection_model()
        indexes = selection_model.selectedRows()
        for index in indexes:
            file_path = self.model.filePath(index)
            logging.debug(f"Selected file path: {file_path}")

    def expand_to_path(self, path: str) -> None:
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

    def on_double_click(self, index: QModelIndex) -> None:
        file_info = self.model.fileInfo(index)
        if file_info.isDir():
            logging.debug(f"Double-clicked directory: {file_info.absoluteFilePath()}")
            # Set this directory as the new root (view path)
            self.tree.setRootIndex(index)
            # self.view_path = file_info.absoluteFilePath()
            # self.tree.setRootIndex(self.model.index(self.view_path))
            # Update the back button enabled state
            self.update_back_button_state()
            # self.rootPathChanged.emit(file_info.absoluteFilePath())
            self.emit_root_path_changed()
            # logging.debug(f"Double click {index = }, path = {file_info.absoluteFilePath()}")

    def on_back_button_clicked(self) -> None:
        # Get the parent index of the current root index
        logging.debug(f"Back button clicked. Current root path: {self.view_path}")
        current_root_index = self.tree.rootIndex()
        parent_index = current_root_index.parent()
        if parent_index.isValid():
            self.tree.setRootIndex(parent_index)
        else:
            # If no parent, set to the model's root (view path)
            self.tree.setRootIndex(self.model.index(self.model.rootPath()))
        # Update the back button enabled state
        self.update_back_button_state()
        # self.rootPathChanged.emit(self.model.filePath(self.tree.rootIndex()))
        self.emit_root_path_changed()
        logging.debug(f"Back button clicked. New root path: {self.model.filePath(self.tree.rootIndex())}")

    def update_back_button_state(self) -> None:
        logging.debug(f"Updating back button state. {self.view_path = }, {self.dir_path = }, {self.target_path = }")
        # There's some very fucked up logic here that I don't understand
        logging.debug(f"{self.tree.rootIndex() == self.model.index(self.dir_path) = }")
        # if self.view_path == self.dir_path:
        if self.tree.rootIndex() == self.model.index(self.dir_path):
            self.back_button.setEnabled(False)
            self.back_button_enabled = False
        else:
            self.back_button.setEnabled(True)
            self.back_button_enabled = True

    def emit_root_path_changed(self) -> None:
        self.rootPathChanged.emit(self.model.filePath(self.tree.rootIndex()))


    def get_selection_model(self) -> QItemSelectionModel:
        logging.debug(f"CALLED ON THIS METHOD (get_selection_model) IS FUCKING DANGEROUS")
        selection_model = self.tree.selectionModel()
        if selection_model is None:
            logging.fatal("FolderExplorer.__init__ encountered None self.tree.selectionModel()")
            logging.fatal(f"{self.tree = }")
            sys.exit(1)
        if not hasattr(selection_model, "selectionChanged"):
            logging.fatal("FolderExplorer.__init__ encountered selectionModel without selectionChanged signal")
            logging.fatal(f"{ selection_model = }")
            sys.exit(1)
        if not hasattr(selection_model, "select"):
            logging.fatal("FolderExplorer.__init__ encountered selectionModel without select method")
            logging.fatal(f"{ selection_model = }")
            sys.exit(1)
        return selection_model


    def show_context_menu(self, position: QPoint) -> None:
        # Map the position to the tree view's viewport
        index = self.tree.indexAt(position)
        if not index.isValid():
            return

        selection_model = self.get_selection_model()

        # **Select the item under the cursor**
        self.tree.setCurrentIndex(index)
        selection_model.select(
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

        # action_recursive_calc_status = QAction("Deeply Recalculate Status", self)
        # action_recursive_calc_status.triggered.connect(lambda: self.context_menu_action_recursive_calc_status(file_info))
        # menu.addAction(action_recursive_calc_status)

        # Create a submenu for recursive calculation
        action_menu_deep_recalc = QMenu("Recalculate Status for enclosed folders", self)
        action_menu_deep_recalc.setWhatsThis("Recalculate the status for the selected folder and its enclosed folders.")

        action_depth_0 = QAction("This folder only (depth 0)", self)
        action_depth_0.triggered.connect(lambda: self.context_menu_action_deep_calc_status(file_info, max_depth=0))
        action_menu_deep_recalc.addAction(action_depth_0)

        action_depth_1 = QAction("Immediate subfolders (depth 1)", self)
        action_depth_1.triggered.connect(lambda: self.context_menu_action_deep_calc_status(file_info, max_depth=1))
        action_menu_deep_recalc.addAction(action_depth_1)

        action_depth_2 = QAction("Up to 2 levels deep (depth 2)", self)
        action_depth_2.triggered.connect(lambda: self.context_menu_action_deep_calc_status(file_info, max_depth=2))
        action_menu_deep_recalc.addAction(action_depth_2)

        action_depth_infinite = QAction("All subfolders (infinite depth)", self)
        action_depth_infinite.triggered.connect(lambda: self.context_menu_action_deep_calc_status(file_info, max_depth=sys.maxsize))
        action_menu_deep_recalc.addAction(action_depth_infinite)

        # Add the deep menu to the main menu
        menu.addMenu(action_menu_deep_recalc)


        action_menu_deep_fill_blanks = QMenu("Calculate blank status for enclosed folders", self)
        action_fill_depth_0 = QAction("This folder only (depth 0)", self)
        action_fill_depth_0.triggered.connect(lambda: self.context_menu_action_deep_calc_status(file_info, max_depth=0, use_cache=True))
        action_menu_deep_fill_blanks.addAction(action_fill_depth_0)

        action_fill_depth_1 = QAction("Immediate subfolders (depth 1)", self)
        action_fill_depth_1.triggered.connect(lambda: self.context_menu_action_deep_calc_status(file_info, max_depth=1, use_cache=True))
        action_menu_deep_fill_blanks.addAction(action_fill_depth_1)

        action_fill_depth_2 = QAction("Up to 2 levels deep (depth 2)", self)
        action_fill_depth_2.triggered.connect(lambda: self.context_menu_action_deep_calc_status(file_info, max_depth=2, use_cache=True))
        action_menu_deep_fill_blanks.addAction(action_fill_depth_2)

        action_fill_depth_infinite = QAction("All subfolders (infinite depth)", self)
        action_fill_depth_infinite.triggered.connect(lambda: self.context_menu_action_deep_calc_status(file_info, max_depth=sys.maxsize, use_cache=True))
        action_menu_deep_fill_blanks.addAction(action_fill_depth_infinite)

        menu.addMenu(action_menu_deep_fill_blanks)


        # **Display the context menu at the cursor's global position**
        viewport = self.tree.viewport()
        if viewport is None: return
        menu.exec(viewport.mapToGlobal(position))

    def context_menu_action_recalc_status(self, folder_info: QFileInfo) -> None:
        logging.debug(f"Recalculate Status for : {folder_info.absoluteFilePath()}")
        # Invalidate the cached status
        self.model.status_cache.pop(folder_info.absoluteFilePath(), None)
        # Trigger a fresh status computation
        self.model.fetch_status(folder_info.absoluteFilePath())

    def context_menu_action_deep_calc_status(self, folder_info: QFileInfo, max_depth: int = sys.maxsize, use_cache: bool = False) -> None:
    # WARNING: THIS METHOD IS REALLY SHIT
        if use_cache: logging.warning("Fill blank is not implemented")
        file_path = folder_info.absoluteFilePath()
        if not folder_info.isDir():
            logging.debug(f"Selected item is not a directory: {file_path}")
            return
        logging.debug(f"Deeply recalculating status for: {file_path} with {max_depth=}")
        self.model.start_deep_status_worker(file_path, max_depth)


    def on_stop_button_clicked(self) -> None:
        logging.debug("Stop all scans button clicked.")
        self.model.stop_all_scans()

    def refresh(self) -> None:
        """
        Refresh the FolderExplorer while maintaining dir_path, target_path, and view_path.
        """

        # Really should use dataEmit change? rather than making a new model every time
        # Also status_cache should be restored

        logging.debug("Refreshing FolderExplorer.")
        # Reinitialize the model with the current paths
        # self.model = helabFileSystemModel(
        #     self.status_cache,
        #     self.thread_pool,
        #     self.running_workers_status,
        #     self.running_workers_deep
        # )
        self.model.refresh()
        self.tree.setModel(self.model)
        self.model.setRootPath(self.dir_path)
        self.tree.setRootIndex(self.model.index(self.view_path))
        self.expand_to_path(self.target_path)
        logging.debug("FolderExplorer.refresh() finished.")

    def rescan(self) -> None:
        logging.debug(f"FolderExplorer.rescan() at path: {self.view_path}")
        # TODO later
        return


    def open_to_path(self, path: str) -> None:
        """
        Open the FolderExplorer to the specified path.
        """
        self.model.refresh()
        self.view_path = path
        self.tree.setRootIndex(self.model.index(path))
        self.expand_to_path(path)
        self.emit_root_path_changed()
        logging.debug(f"Opened FolderExplorer to path: {path}")

    def close_cleanup(self) -> None:
        # self.model.clearItemData()
        self.model.deleteLater()
        self.deleteLater()
        logging.debug("FolderExplorer closed and cleaned up.")
