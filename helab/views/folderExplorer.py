import gc
import glob
import logging
import os
import pickle
import platform
import stat
import subprocess
import sys
import warnings
from typing import Optional, Dict, List, Tuple

import numpy as np
import pandas as pd
from PyQt6.QtCore import QSize, QDir, QItemSelectionModel, Qt, pyqtSignal, QThreadPool, QModelIndex, QItemSelection, \
    QPoint, QFileInfo, QTimer, QRunnable, QObject, QThread
from PyQt6.QtGui import QAction, QFontInfo, QGuiApplication
from PyQt6.QtWidgets import QWidget, QHeaderView, QHBoxLayout, QVBoxLayout, QPushButton, QTreeView, QMenu, QApplication
from cachetools import LRUCache, TTLCache
from diskcache import FanoutCache

from helab.utils.constants import *
from helab.utils.cachingSetup import *
from helab.utils.threadingSetup import *
from helab.models.helabFileSystemModel import helabFileSystemModel
from helab.utils.os_cached import os_isdir
from helab.views.statusIconDelegate import StatusIconDelegate
from helab.views.statusTreeView import StatusTreeView
from helab.workers.directoryCheckWorker import DirectoryCheckWorker
from helab.workers.loadFolderToRamWorker import LoadFolderToRamWorker
from helab.workers.statusDeepWorker import StatusDeepWorker
from helab.workers.statusWorker import StatusWorker, StatusReport

import numpy.typing as npt
from numpy import float64

class FolderExplorer(QWidget):
    rootPathChanged = pyqtSignal(str)
    itemExpandedSignal = pyqtSignal(QModelIndex)

    def __init__(self,
                 model_root_path: str,
                 target_path: str,
                 view_path: str,
                 columns_to_show: List[int],
                 parent: QWidget | None = None,
                 set_initial_expand_to_parent_level: bool = True,
                 ) -> None:
        super().__init__(parent)

        # Initialize view_path
        self.model_root_path = model_root_path  # System root path
        self.target_path = target_path  # Path to auto-expand upon opening
        self.view_path = view_path  # Current root path of the view
        self.columns_to_show = columns_to_show

        self.auto_load_ram = True

        self.folder_opened_data: Optional[Dict[int, npt.NDArray[np.float64]]] = None
        self.folder_opened_path: Optional[str] = None

        self.model = helabFileSystemModel()
        self.model.setRootPath(self.model_root_path)
        self.model.setReadOnly(True)
        # self.model.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot | QDir.Filter.Hidden)
        self.model.setFilter(QDir.Filter.Dirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Hidden)

        # self.tree = QTreeView()
        self.tree = StatusTreeView()
        self.tree.setContentsMargins(0, 0, 0, 0)
        self.tree.setModel(self.model)
        # self.tree.setRootIndex(self.model.index(model_root_path))
        self.tree.setRootIndex(self.model.index(self.view_path))
        self.tree.setColumnWidth(helabFileSystemModel.COLUMN_NAME, 270)
        self.tree.setColumnWidth(helabFileSystemModel.COLUMN_DATE_MODIFIED, 160)
        self.tree.setColumnWidth(helabFileSystemModel.COLUMN_STATUS_NUMBER, 60)
        self.tree.setColumnWidth(helabFileSystemModel.COLUMN_STATUS_ICON, 60)
        self.tree.setColumnWidth(helabFileSystemModel.COLUMN_RIGHTFILL, 0)
        self.tree.setAlternatingRowColors(True)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(True)
        self.back_button_enabled = False
        self.tree.itemExpandedSignal.connect(self.itemExpandedSignal.emit)
        # self.tree.setStyle(OptionalBranchIconStyle())
        # self.tree.setItemsExpandable(False)

        # # Set the custom delegate for the icon column
        # icon_delegate = StatusIconDelegate(self.tree)
        # self.tree.setItemDelegateForColumn(helabFileSystemModel.COLUMN_STATUS_ICON, icon_delegate)

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
        self.selected_path = self.target_path

        # **Added Lines: Set context menu policy and connect the signal**
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)

        self.emit_root_path_changed()
        # selection_model.emitSelectionChanged(selection_model.selection(), selection_model.selection())
        # self.emit_selection_changed()
        # QTimer.singleShot(15, self._set_initial_rootIndex)

        if set_initial_expand_to_parent_level: self._set_initial_rootIndex()

        QTimer.singleShot(30, self.emit_selection_changed)


    def _set_initial_rootIndex(self) -> None:
        # self.tree.setRootIndex(self.model.index(self.view_path))
        # current_root_index = self.tree.rootIndex()
        # current_view_index = self.model.index(self.view_path)
        # currnet_index = self.model.index
        index = self.model.index(self.target_path)
        parent_index = index.parent()
        logging.debug(f"_set_initial_rootIndex: index = {self.model.filePath(index)}, parent_index = {self.model.filePath(parent_index)}")
        if parent_index.isValid():
            self.tree.setRootIndex(parent_index)
            logging.debug(f"_set_initial_rootIndex: {self.model.filePath(parent_index)}")
        else:
            # If no parent, set to the model's root (view path)
            self.tree.setRootIndex(self.model.index(self.model.rootPath()))
        self.update_back_button_state()
        self.emit_root_path_changed()

    def emit_selection_changed(self) -> None:
        selection_model = self.get_selection_model()
        # selection_model.emitSelectionChanged(selection_model.selection(), selection_model.selection())
        current_selection = selection_model.selection()
        if not current_selection.isEmpty():
            # Deselect and reselect to trigger the signal
            selection_model.clearSelection()
            selection_model.select(current_selection, QItemSelectionModel.SelectionFlag.Select)

    def on_selection_changed(self, selected: QItemSelection, deselected: QItemSelection) -> None:

        # TODO: enable multi-row selection

        selected_indexes = selected.indexes()
        deselected_indexes = deselected.indexes()
        ncols = self.model.columnCount()
        exclusion_list = [ncols, ncols-1, 0, 1]

        if len(selected_indexes) not in exclusion_list:
            logging.critical(f"folderExplorer.on_selection_changed: selected_indexes unexpected {len(selected_indexes) = }, {self.model.columnCount() = }")
            logging.critical(f"they are {[self.model.filePath(si) for si in selected_indexes]}")
            # logging.fatal(f"WTF {len(selected_indexes) != self.model.columnCount()}")
        # if self.auto_load_ram:
        for si in selected_indexes:
            file_path = self.model.filePath(si)
            self.selected_path = file_path
            logging.info(f"folderExplorer.on_selection_changed: selected {file_path = }")
            if self.auto_load_ram:
                self.load_to_ram_cache(self.model.fileInfo(si))
                logging.debug(f"folderExplorer.on_selection_changed: load_to_ram_cache requested at {file_path = }")
            else:
                logging.debug(f"folderExplorer.on_selection_changed: auto_load_ram disabled at {file_path = }")
            break
        # else:
        #     logging.debug(f"folderExplorer.on_selection_changed: auto_load_ram disabled")

        # if len(deselected_indexes) != self.model.columnCount() and len(deselected_indexes) != 0:
        if len(deselected_indexes) not in exclusion_list:
            logging.critical(f"folderExplorer.on_selection_changed: deselected_indexes unexpected {len(deselected_indexes) = }, {self.model.columnCount() = }")
            logging.critical(f"they are {[self.model.filePath(di) for di in deselected_indexes]}")
        for di in deselected_indexes:
            file_path = self.model.filePath(di)
            logging.info(f"folderExplorer.on_selection_changed: deselected {file_path = }")
            # self.selected_path = file_path
            status_report = status_cache.get(file_path)
            if status_report is not None and isinstance(status_report, StatusReport):
                # logging.debug(f"{status_report.status = }")
                status_report.update_ram_status()
                if file_path in running_workers_ramLoading:
                    status_report.set_loading_ram_status()
                    if file_path in data_ram_cache:
                        running_workers_ramLoading[file_path].cancel(message=LoadFolderToRamWorker.CANCEL_MSG_ALREADY_CACHED_AND_NO_LONGER_SELECTED)

                # logging.debug(f"folderExplorer.on_selection_changed: {file_path = } is in running_workers_ramLoading")
                # self.running_workers_ramLoading[file_path].cancel()
                # self.running_workers_ramLoading.pop(file_path)
                gc.collect()
            break



    def expand_to_path(self, path: str) -> None:
        # Ensure that the path to expand is under the current view_path
        if not os.path.commonpath([self.view_path, path]) == os.path.abspath(self.view_path):
            logging.warning(f"expand_to_path: Path {path} is not under the current view path {self.view_path}.")
            return
        index = self.model.index(path)
        if not index.isValid():
            logging.warning(f"expand_to_path: Invalid path: {path}")
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
            self.target_path = file_info.absoluteFilePath()

            self.update_back_button_state()
            # self.rootPathChanged.emit(file_info.absoluteFilePath())
            self.emit_root_path_changed()
            # logging.debug(f"Double click {index = }, path = {file_info.absoluteFilePath()}")
            self.model.rescan(user_requested_scan= False)

    def on_back_button_clicked(self) -> None:
        # Get the parent index of the current root index
        logging.debug(f"on_back_button_clicked: Current root path: {self.view_path}")
        current_root_index = self.tree.rootIndex()
        parent_index = current_root_index.parent()
        if parent_index.isValid():
            logging.debug(f"on_back_button_clicked: valid {parent_index = }")
            self.tree.setRootIndex(parent_index)
        else:
            # If no parent, set to the model's root (view path)
            # logging.debug(f"on_back_button_clicked: invalid {parent_index = }")
            # if platform.system() == "Windows":
            #     drives = QDir.drives()
            #     self.model.setRootPath("")
            #     self.tree.setRootIndex(self.model.index(""))
            #     logging.debug("on_back_button_clicked: Showing all drives")
            # else:
            self.tree.setRootIndex(self.model.index(self.model.rootPath()))
        # Update the back button enabled state
        self.update_back_button_state()
        # self.robotPathChanged.emit(self.model.filePath(self.tree.rootIndex()))
        self.emit_root_path_changed()
        self.model.rescan(user_requested_scan= False)
        logging.debug(f"on_back_button_clicked: New root path: {self.model.filePath(self.tree.rootIndex())}")

    def update_back_button_state(self) -> None:
        # logging.debug(f"update_back_button_state: called on {self.view_path = }, {self.model_root_path = }, {self.target_path = }")
        # There's some very fucked up logic here that I don't understand
        # logging.debug(f"update_back_button_state: {self.tree.rootIndex() == self.model.index(self.model_root_path) = }")
        # logging.debug(f"update_back_button_state: rootIndex = {self.model.filePath(self.tree.rootIndex())}")
        # if self.view_path == self.model_root_path:
        if self.tree.rootIndex() == self.model.index(self.model_root_path):
            self.back_button.setEnabled(False)
            self.back_button_enabled = False
            # logging.debug(f"update_back_button_state: Back button disabled")
        else:
            self.back_button.setEnabled(True)
            self.back_button_enabled = True
            # logging.debug(f"update_back_button_state: Back button enabled")

    def emit_root_path_changed(self) -> None:
        self.rootPathChanged.emit(self.model.filePath(self.tree.rootIndex()))


    def get_selection_model(self) -> QItemSelectionModel:
        # logging.warning(f"get_selection_model: CALLED (this is dangerous)")
        selection_model = self.tree.selectionModel()
        if selection_model is None:
            logging.fatal("FolderExplorer.__init__ encountered None self.tree.selectionModel()")
            logging.fatal(f"{self.tree = }")
            # sys.exit(1)
            raise RuntimeError("FolderExplorer.__init__ encountered None self.tree.selectionModel()")
        if not hasattr(selection_model, "selectionChanged"):
            logging.fatal("FolderExplorer.__init__ encountered selectionModel without selectionChanged signal")
            logging.fatal(f"{ selection_model = }")
            # sys.exit(1)
            raise RuntimeError("FolderExplorer.__init__ encountered selectionModel without selectionChanged signal")
        if not hasattr(selection_model, "select"):
            logging.fatal("FolderExplorer.__init__ encountered selectionModel without select method")
            logging.fatal(f"{ selection_model = }")
            # sys.exit(1)
            raise RuntimeError("FolderExplorer.__init__ encountered selectionModel without select method")
        return selection_model

    
    def show_context_menu(self, position: QPoint) -> None:
        # Map the position to the tree view's viewport
        index = self.tree.indexAt(position)
        if not index.isValid():
            return

        selection_model = self.get_selection_model()

        # **Select the item under the cursor**
        # TODO: change to allow multi row selection.
        self.tree.setCurrentIndex(index)
        selection_model.select(
            index,
            QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Select
        )

        # Retrieve file information after selection
        file_info = self.model.fileInfo(index)

        # **Create and populate the context menu**
        menu = QMenu(self)


        # Add the new action to open in file manager
        action_open_in_file_manager = QAction("Open in File Manager", self)
        action_open_in_file_manager.triggered.connect(lambda: self.open_in_file_manager(file_info))
        menu.addAction(action_open_in_file_manager)


        action_copy_pathname = QAction("Copy Pathname to Clipboard", self)
        action_copy_pathname.triggered.connect(lambda: self.copy_pathname_to_clipboard(file_info))
        menu.addAction(action_copy_pathname)


        # action_recalc_status = QAction("Recalculate Status", self)
        # action_recalc_status.triggered.connect(lambda: self.context_menu_action_recalc_status(file_info))
        # menu.addAction(action_recalc_status)

        # action_recursive_calc_status = QAction("Deeply Recalculate Status", self)
        # action_recursive_calc_status.triggered.connect(lambda: self.context_menu_action_recursive_calc_status(file_info))
        # menu.addAction(action_recursive_calc_status)

        # Create a submenu for recursive calculation
        action_menu_deep_recalc = QMenu("Recalculate Status (Rebuild cache)", self)
        # action_menu_deep_recalc.setWhatsThis("Recalculate the status for the selected folder and its enclosed folders.")
        # action_menu_deep_recalc.triggered.connect(lambda: self.context_menu_action_deep_calc_status(file_info, current_depth=0))

        action_depth_0 = QAction("Depth 0 - Selected folder", self)
        action_depth_0.triggered.connect(lambda: self.context_menu_action_deep_calc_status(file_info, max_depth=0, invalidate_cache=True))
        action_menu_deep_recalc.addAction(action_depth_0)

        action_depth_1 = QAction("Depth 1 - Immediate subfolders)", self)
        action_depth_1.triggered.connect(lambda: self.context_menu_action_deep_calc_status(file_info, max_depth=1, invalidate_cache=True))
        action_menu_deep_recalc.addAction(action_depth_1)

        action_depth_2 = QAction("Depth 2", self)
        action_depth_2.triggered.connect(lambda: self.context_menu_action_deep_calc_status(file_info, max_depth=2, invalidate_cache=True))
        action_menu_deep_recalc.addAction(action_depth_2)

        action_depth_3 = QAction("Depth 3", self)
        action_depth_3.triggered.connect(lambda: self.context_menu_action_deep_calc_status(file_info, max_depth=3, invalidate_cache=True))
        action_menu_deep_recalc.addAction(action_depth_3)

        action_depth_infinite = QAction("Depth ∞ - All subfolders", self)
        action_depth_infinite.triggered.connect(lambda: self.context_menu_action_deep_calc_status(file_info, max_depth=MAX_DEPTH_INT, invalidate_cache=True))
        # action_depth_infinite.triggered.connect(lambda: self.context_menu_action_deep_calc_status(file_info, current_depth=1<<15))
        action_menu_deep_recalc.addAction(action_depth_infinite)

        # Add the deep menu to the main menu
        menu.addMenu(action_menu_deep_recalc)


        action_menu_deep_fill_blanks = QMenu("Recalculate Status (Fill blanks)", self)
        action_fill_depth_0 = QAction("Depth 0 - Selected folder", self)
        action_fill_depth_0.triggered.connect(lambda: self.context_menu_action_deep_calc_status(file_info, max_depth=0, invalidate_cache=False))
        action_menu_deep_fill_blanks.addAction(action_fill_depth_0)

        action_fill_depth_1 = QAction("Depth 1 - Immediate subfolders", self)
        action_fill_depth_1.triggered.connect(lambda: self.context_menu_action_deep_calc_status(file_info, max_depth=1, invalidate_cache=False))
        action_menu_deep_fill_blanks.addAction(action_fill_depth_1)

        action_fill_depth_2 = QAction("Depth 2", self)
        action_fill_depth_2.triggered.connect(lambda: self.context_menu_action_deep_calc_status(file_info, max_depth=2, invalidate_cache=False))
        action_menu_deep_fill_blanks.addAction(action_fill_depth_2)

        action_fill_depth_3 = QAction("Depth 3", self)
        action_fill_depth_3.triggered.connect(lambda: self.context_menu_action_deep_calc_status(file_info, max_depth=3, invalidate_cache=False))
        action_menu_deep_fill_blanks.addAction(action_fill_depth_3)

        action_fill_depth_infinite = QAction("Depth ∞ - All subfolders", self)
        action_fill_depth_infinite.triggered.connect(lambda: self.context_menu_action_deep_calc_status(file_info, max_depth=MAX_DEPTH_INT, invalidate_cache=False))
        action_menu_deep_fill_blanks.addAction(action_fill_depth_infinite)

        menu.addMenu(action_menu_deep_fill_blanks)



        action_menu_pop_cache = QMenu("Remove Cache Here", self)

        action_pop_cache_osfs_related = QAction("File System Cache", self)
        action_pop_cache_osfs_related.triggered.connect(lambda: self.context_menu_action_pop_cache(file_info, cache_name="osfs_system_cache"))
        action_menu_pop_cache.addAction(action_pop_cache_osfs_related)

        action_pop_cache_depth_hasChildren = QAction("hasChildren Cache", self)
        action_pop_cache_depth_hasChildren.triggered.connect(lambda: self.context_menu_action_pop_cache(file_info, cache_name="hasChildren_cache"))
        action_menu_pop_cache.addAction(action_pop_cache_depth_hasChildren)

        action_pop_cache_depth_status = QAction("status_cache", self)
        action_pop_cache_depth_status.triggered.connect(lambda: self.context_menu_action_pop_cache(file_info, cache_name="status_cache"))
        action_menu_pop_cache.addAction(action_pop_cache_depth_status)

        action_pop_cache_depth_data_ram = QAction("data_ram Cache", self)
        action_pop_cache_depth_data_ram.triggered.connect(lambda: self.context_menu_action_pop_cache(file_info, cache_name="data_ram_cache"))
        action_menu_pop_cache.addAction(action_pop_cache_depth_data_ram)

        action_pop_cache_all = QAction("All Caches", self)
        action_pop_cache_all.triggered.connect(lambda: self.context_menu_action_pop_cache(file_info, cache_name="all"))
        action_menu_pop_cache.addAction(action_pop_cache_all)

        menu.addMenu(action_menu_pop_cache)


        menu.addSeparator()

        action_menu_debug = QMenu("Debug", self)
        action_debug_1 = QAction("get_valid_status_report", self)
        action_debug_1.triggered.connect(lambda: self.get_valid_status_report(file_info))
        action_menu_debug.addAction(action_debug_1)

        # action_debug_2 = QAction("Debug Action 2", self)
        # action_debug_2.triggered.connect(lambda: self.action_debug_2_run(file_info))
        # action_menu_debug.addAction(action_debug_2)

        action_debug_3 = QAction("load_to_ram_cache", self)
        action_debug_3.triggered.connect(lambda: self.load_to_ram_cache(file_info))
        action_menu_debug.addAction(action_debug_3)


        action_dump_data_to_temp_dir = QAction("Dump data_ram_cache to DIR_TEMPS", self)
        action_dump_data_to_temp_dir.triggered.connect(lambda: self.on_click_dump_data_to_temp_dir(file_info))
        action_menu_debug.addAction(action_dump_data_to_temp_dir)


        menu.addMenu(action_menu_debug)


        # **Display the context menu at the cursor's global position**
        viewport = self.tree.viewport()
        if viewport is None: return
        menu.exec(viewport.mapToGlobal(position))

    def context_menu_action_pop_cache(self, file_info: QFileInfo, cache_name: str) -> None:
        path = file_info.absoluteFilePath()
        try:
            match cache_name:
                case "status_cache":
                    status_cache.pop(path)
                    w = running_workers_status.pop(path)
                    if w: w.cancel()
                case "hasChildren_cache":
                    hasChildren_cache.pop(path)
                case "data_ram_cache":
                    data_ram_cache.pop(path)
                    status_report = status_cache.get(path)
                    if isinstance(status_report, StatusReport):
                        status_report.update_ram_status(is_opened=path==self.selected_path)
                case "osfs_system_cache":
                    os_listdir_cache.pop(path)
                    os_isdir_cache.pop(path)
                    os_scandir_cache.pop(path)
                case "all":
                    status_cache.pop(path)
                    hasChildren_cache.pop(path)
                    data_ram_cache.pop(path)
                    os_listdir_cache.pop(path)
                    os_isdir_cache.pop(path)
                    os_scandir_cache.pop(path)
                case _:
                    raise ValueError(f"Invalid cache_name: {cache_name} at {path = }")
            logging.debug(f"context_menu_action_pop_cache: {cache_name = }, {path = }")
        except KeyError:
            logging.warning(f"context_menu_action_pop_cache: KeyError {path = }")
            pass
        except Exception as e:
            logging.error(f"context_menu_action_pop_cache: {e = }")
            pass
        pass

    def get_valid_status_report(self, file_info: QFileInfo) -> Tuple[int, StatusReport | None]:
        file_path = file_info.absoluteFilePath()
        logging.debug(f"get_valid_status_report: file_path = {file_path}")
        # logging.warning(f"THIS IS STRICTLY FOR DEBUGGING PURPOSES")

        status_report = status_cache.get(file_path)
        if status_report is None:
            logging.warning(f"  status_cache is None for {file_path = }")
            return (-1, None)
        if not isinstance(status_report, StatusReport):
            logging.warning(f"  status_cache is not a StatusReport for {file_path = }")
            return (-2, None)

        logging.debug(f"  {status_report.status = }")

        if not status_report.status in StatusReport.STATUS_CONTAINS_DATA:
            # logging.warning(f"  status is not STATUS_OK for {file_path = }")
            return (-3, None)

        return (0, status_report)

    def action_debug_2_run(self, file_info: QFileInfo) -> None:
        logging.fatal(f"action_debug_2_run: THIS IS NO LONGER USED")
        warnings.warn("action_debug_2_run", DeprecationWarning)
        try:
            folder_path = file_info.absoluteFilePath()
            if not self.get_valid_status_report(file_info)[0] == 0 : return
            try:
                data_files = data_ram_cache[folder_path]
                if not data_files is None:
                    logging.warning(f"action_debug_2_run: {folder_path = } already in cache")
                    return
            except KeyError:
                pass
            except Exception as e:
                logging.error(f"StatusWorker._run_helper_v1: error accessing cache for {folder_path}: {e}")
                pass

            logging.warning(f"{self.selected_path == folder_path = }")

            file_pattern = os.path.join(folder_path, 'd_txy_forc*.txt')
            files = glob.glob(file_pattern)
            # logging.debug(f"{files}")
            data_dict = {}
            for file in files:
                # Extract the base filename
                basename = os.path.basename(file)  # e.g., 'd_txy_forc11.txt'

                # Extract the number using string manipulation or regex
                # Here, we'll use string methods
                number_str = basename.split('forc')[1].split('.txt')[0]  # '11'
                number = int(number_str)

                # Load the data into a DataFrame
                # Adjust the separator if your data uses a different delimiter (e.g., comma, space)
                df = pd.read_csv(file, sep=',', names=['t', 'x', 'y'])

                # Alternatively, if the separator is whitespace:
                # df = pd.read_csv(file, delim_whitespace=True, names=['t', 'x', 'y'])

                # Store the DataFrame in the dictionary
                data_dict[number] = df

            # Add a 'file_number' column to each DataFrame
            for number, df in data_dict.items():
                df['file_number'] = number

            # Concatenate all DataFrames
            combined_df = pd.concat(data_dict.values())

            # Set 'file_number' as the index
            combined_df.set_index('file_number', inplace=True)

            # Optional: Sort the index for better organization
            combined_df.sort_index(inplace=True)

            print(combined_df)

            data_ram_cache[folder_path] = combined_df

            status_cache.pop(folder_path)
            self.model.fetch_status(folder_path)

            logging.warning(f"action_debug_2_run: {folder_path = } DONE")
        except Exception as e:
            logging.critical(f"action_debug_2_run: {e = }")

    def load_to_ram_cache(self, file_info: QFileInfo) -> None:
        folder_path = file_info.absoluteFilePath()

        if folder_path in running_workers_ramLoading:
            logging.warning(f"load_to_ram_cache: already running {folder_path = }")
            # self.on_load_folder_to_ram_finished(folder_path, [], None)
            return

        # don't return here even if it's in cache, need to decompress the data using the worker thread
        # if folder_path in data_ram_cache:
        #     logging.warning(f"load_to_ram_cache: already in cache {folder_path = }")
        #     self.on_load_folder_to_ram_finished_helper(folder_path, data_ram_cache[folder_path])
        #     return

        check, status_report = self.get_valid_status_report(file_info)
        if check != 0 :
            logging.debug(f"load_to_ram_cache: called on not-data-folder path: {folder_path}")
            return
        if status_report is None:
            logging.critical(f"load_to_ram_cache: Impossible logic case status_report is None at {folder_path = }")
            return
        # status_report.extra_icons.append('loading')
        # status_cache[folder_path] = status_report
        status_report.set_loading_ram_status()

        worker = LoadFolderToRamWorker(folder_path)
        worker.signals.finished.connect(self.on_load_folder_to_ram_finished)
        worker.signals.loading.connect(self.on_load_folder_to_ram_loading)
        worker.signals.error.connect(self.on_load_folder_to_ram_error)
        worker.setAutoDelete(True)
        running_workers_ramLoading[folder_path] = worker
        # self.thread_pool.start(worker, priority=QThread.Priority.LowPriority.value)
        QTimer.singleShot(10, lambda: thread_pool_load_data_ram.start(worker, priority=QThread.Priority.IdlePriority.value)) # type: ignore[call-overload]
        pass
    
    def on_load_folder_to_ram_finished(self, folder_path: str, problematic_txy_ns: List[int], data: object) -> None:
        logging.debug(f"on_load_folder_to_ram_finished: {folder_path = }")
        running_workers_ramLoading.pop(folder_path, None)
        self.on_load_folder_to_ram_finished_helper(folder_path, problematic_txy_ns, data)

    def on_load_folder_to_ram_finished_helper(self, folder_path: str, problematic_txy_ns: Optional[List[int]], data: object) -> None:
        #TODO: move these methods to LoadFolderToRamWorker
        if isinstance(data, dict):
            self.folder_opened_path = folder_path
            self.model.folder_opened_path = folder_path
            self.folder_opened_data = data
            status_report = status_cache.get(folder_path)
            if status_report is not None and isinstance(status_report, StatusReport):
                # status_report.extra_icons.remove('loading')
                # status_report.update_extend_extras('')
                if folder_path == self.selected_path:
                    status_report.update_ram_status(is_opened=True,  update_cache=True)
                else:
                    status_report.update_ram_status(is_opened=False, update_cache=True)

                if problematic_txy_ns is not None and len(problematic_txy_ns) > 0:
                    status_report.update_problematic_txy_ns(problematic_txy_ns)

                # status_cache[folder_path] = status_report
                index = self.model.index(folder_path, helabFileSystemModel.COLUMN_STATUS_ICON)
                if index.isValid():
                    self.model.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
                    logging.debug(f"on_load_folder_to_ram_finished: loadded {fnum(LoadFolderToRamWorker.get_total_rows_in_dict_of_numpy(data))} rows "
                                  f"{fnum(LoadFolderToRamWorker.get_approx_size_of_dict_of_numpy(data))}B at {folder_path = }")
                else:
                    logging.error(f"on_load_folder_to_ram_finished: invalid index at {folder_path} ({index = })")
            else:
                logging.error(f"on_load_folder_to_ram_finished: {folder_path = } is not in status_cache")
                self.model.fetch_status(folder_path)

        else:
            logging.critical(f"on_load_folder_to_ram_finished: {type(data) = } is not dict, {folder_path = }")
            status_cache.pop(folder_path)
            self.model.fetch_status(folder_path)
        pass

    def on_load_folder_to_ram_error(self, folder_path: str, error: str) -> None:
        logging.error(f"on_load_folder_to_ram_error: {folder_path = }, {error = }")
        running_workers_ramLoading.pop(folder_path, None)
        status_report = status_cache.get(folder_path, None)
        status_report_exist = isinstance(status_report, StatusReport)
        if not status_report_exist:
            logging.error(f"on_load_folder_to_ram_error: not cached in in status_cache {folder_path = }")

        if error in [LoadFolderToRamWorker.CANCEL_MSG_NOTHING_HERE,
                     LoadFolderToRamWorker.CANCEL_MSG_ALREADY_CACHED_AND_NO_LONGER_SELECTED]:
            if status_report_exist:
                status_report.cancel_loading_ram_status()
                # QTimer.singleShot(100, status_report.validate_ram_status)
                self.model.throttled_data_changed_emitter.add_update(folder_path)
            return
        else:
            status_cache.pop(folder_path, None)
            self.model.fetch_status(folder_path)
            data_ram_cache.pop(folder_path, None)

    def on_load_folder_to_ram_loading(self, folder_path: str, progress: float) -> None:
        # logging.debug(f"on_load_folder_to_ram_loading: {folder_path = }, {progress = }")
        status_report = status_cache.get(folder_path)
        if status_report is not None and isinstance(status_report, StatusReport):
            status_report.set_loading_ram_progress(progress)
            # index = self.model.index(folder_path, helabFileSystemModel.COLUMN_STATUS_ICON)
            # if index.isValid():
            #     self.model.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
            self.model.throttled_data_changed_emitter.add_update(folder_path)
        pass


    # def context_menu_action_recalc_status(self, folder_info: QFileInfo) -> None:
    #     logging.debug(f"Recalculate Status for : {folder_info.absoluteFilePath()}")
    #     # Invalidate the cached status
    #     self.model.status_cache.pop(folder_info.absoluteFilePath(), None)
    #     # Trigger a fresh status computation
    #     self.model.fetch_status(folder_info.absoluteFilePath())

    def context_menu_action_deep_calc_status(self, folder_info: QFileInfo, max_depth: int = MAX_DEPTH_INT, invalidate_cache: bool = True) -> None:
    # WARNING: THIS METHOD IS REALLY SHIT
    #     if not invalidate_cache: logging.warning("context_menu_action_deep_calc_status: Fill blank is not implemented")
        file_path = folder_info.absoluteFilePath()

        if not os_isdir(file_path):
            logging.debug(f"context_menu_action_deep_calc_status: Selected item is not a directory: {file_path}")
            return
        logging.debug(f"context_menu_action_deep_calc_status: {file_path = } with {max_depth = }")
        self.model.start_deep_status_worker(file_path, max_depth, invalidate_cache)

    def open_in_file_manager(self, folder_info: QFileInfo) -> None:
        path = folder_info.absoluteFilePath()
        if platform.system() == "Darwin":  # macOS
            subprocess.run(["open", path])
        elif platform.system() == "Windows":  # Windows
            subprocess.run(["explorer", path])
        elif platform.system() == "Linux":  # Unix/Linux
            subprocess.run(["xdg-open", path])
        else:
            pass

    def copy_pathname_to_clipboard(self, folder_info: QFileInfo) -> None:
        path = folder_info.absoluteFilePath()
        # clipboard = QApplication.clipboard()
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            logging.error("copy_pathname_to_clipboard: clipboard is None")
            return
        clipboard.setText(path)
        logging.info(f"copy_pathname_to_clipboard: {path = }")

    def on_stop_button_clicked(self) -> None:
        logging.debug("Stop all scans button clicked.")
        self.model.stop_all_scans()

    def on_click_dump_data_to_temp_dir(self, folder_info: QFileInfo) -> None:
        try:
            folder_path = folder_info.absoluteFilePath()
            if folder_path in data_ram_cache:
                data_compressed = data_ram_cache[folder_path]
                # data_pd = LoadFolderToRamWorker.decompress_dataframe(data_compressed)
                # temp_path = os.path.join(DIR_TEMPS, hash_str(folder_path))
                temp_path = QDir(DIR_TEMPS).filePath(hash_str(folder_path))
                # data_pd.to_pickle(temp_path)
                # pickle
                with open(temp_path, 'wb') as f:
                    pickle.dump(data_compressed, f)
                logging.debug(f"on_click_dump_data_to_temp_dir: {folder_path = } to {temp_path = }")
        except Exception as e:
            logging.error(f"on_click_dump_data_to_temp_dir: {type(e).__name__} - {e}")
            pass

    def refresh(self) -> None:
        """
        Refresh the FolderExplorer while maintaining model_root_path, target_path, and view_path.
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
        current_root_index = self.tree.rootIndex()
        self.model.refresh()
        self.tree.setModel(self.model)
        self.model.setRootPath(self.model_root_path)
        # self.tree.setRootIndex(self.model.index(self.view_path))
        self.tree.setRootIndex(current_root_index)
        # self.expand_to_path(self.target_path)
        # self._set_initial_rootIndex()
        logging.debug("FolderExplorer.refresh() finished.")

    def rescan(self, user_intend: bool = False) -> None:
        logging.debug(f"FolderExplorer.rescan() view_path: {self.view_path} model_root_path: {self.model_root_path} target_path: {self.target_path}")
        self.model.rescan(user_requested_scan= user_intend)
        pass


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
        # FIXME: code duplication
        if self.folder_opened_path is not None:
            try:
                status_report = status_cache[self.folder_opened_path]
                if isinstance(status_report, StatusReport):
                    status_report.update_ram_status(is_opened=False)
                    index = self.model.index(self.folder_opened_path, helabFileSystemModel.COLUMN_STATUS_ICON)
                    if index.isValid():
                        self.model.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
                    else:
                        logging.error(f"folderExplorer.close_cleanup: invalid index at {self.folder_opened_path} ({index = })")
            except KeyError:
                logging.critical(f"folderExplorer.close_cleanup: impossible logic case, Key not found in status_cache[{self.folder_opened_path}]")
            except Exception as e:
                logging.error(f"folderExplorer.close_cleanup: {e = }")

        self.folder_opened_data = None
        self.folder_opened_path = None
        # self.model.folder_opened_path = None
        # self.model.rescan_cancel_if_any()
        self.model.close_cleanup()

        # self.model.clearItemData()
        # self.model.deleteLater()
        self.deleteLater()
        logging.debug("FolderExplorer.close_cleanup: finished")



