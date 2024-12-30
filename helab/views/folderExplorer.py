import glob
import logging
import os
import platform
import subprocess
import sys
from typing import Optional, Dict, List, Tuple

import pandas as pd
from PyQt6.QtCore import QSize, QDir, QItemSelectionModel, Qt, pyqtSignal, QThreadPool, QModelIndex, QItemSelection, \
    QPoint, QFileInfo, QTimer
from PyQt6.QtGui import QAction, QFontInfo
from PyQt6.QtWidgets import QWidget, QHeaderView, QHBoxLayout, QVBoxLayout, QPushButton, QTreeView, QMenu
from cachetools import LRUCache, TTLCache
from diskcache import FanoutCache

from helab.utils.cachingSetup import status_cache, data_ram_cache
from helab.utils.constants import *
from helab.models.helabFileSystemModel import helabFileSystemModel
from helab.utils.os_cached import os_isdir
from helab.views.statusIconDelegate import StatusIconDelegate
from helab.views.statusTreeView import StatusTreeView
from helab.workers.directoryCheckWorker import DirectoryCheckWorker
from helab.workers.statusDeepWorker import StatusDeepWorker
from helab.workers.statusWorker import StatusWorker, StatusReport


class FolderExplorer(QWidget):
    rootPathChanged = pyqtSignal(str)
    itemExpandedSignal = pyqtSignal(QModelIndex)

    def __init__(self,
                 model_root_path: str,
                 target_path: str,
                 view_path: str,
                 columns_to_show: List[int],
                 status_cache: FanoutCache,
                 hasChildren_cache: FanoutCache,
                 thread_pool: QThreadPool,
                 running_workers_status: Dict[str, StatusWorker],
                 running_workers_deep: Dict[str, StatusDeepWorker],
                 running_workers_hasChildren: Dict[str, DirectoryCheckWorker],
                 parent: QWidget | None = None,
                 set_initial_expand_to_parent_level: bool = True,
                 ) -> None:
        super().__init__(parent)
        # appWidth = 800
        # appHeight = 800

        # self.setWindowTitle('File System Viewer')
        # self.setGeometry(300, 300, appWidth, appHeight)

        # Initialize view_path
        self.model_root_path = model_root_path  # System root path
        self.target_path = target_path  # Path to auto-expand upon opening
        self.view_path = view_path  # Current root path of the view
        self.columns_to_show = columns_to_show

        self.status_cache = status_cache
        self.hasChildren_cache = hasChildren_cache
        self.thread_pool = thread_pool
        self.running_workers_status = running_workers_status
        self.running_workers_deep = running_workers_deep
        self.running_workers_hasChildren = running_workers_hasChildren

        self.model = helabFileSystemModel(
            status_cache = status_cache,
            hasChildren_cache = hasChildren_cache,
            thread_pool = thread_pool,
            running_workers_status = running_workers_status,
            running_workers_deep = running_workers_deep,
            running_workers_hasChildren = running_workers_hasChildren
        )
        self.model.setRootPath(self.model_root_path)
        self.model.setReadOnly(True)
        # self.model.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot | QDir.Filter.Hidden)
        self.model.setFilter(QDir.Filter.Dirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Hidden)
        # self.rootPathChanged.emit(self.model_root_path)

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
        self.selected_path = self.target_path

        # **Added Lines: Set context menu policy and connect the signal**
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)

        # self.rootPathChanged.emit(self.model_root_path)
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
        selection_model = self.get_selection_model()
        indexes = selection_model.selectedRows()

        # there_should_only_be_one_index = len(indexes) == 1
        if len(indexes) > 1:
            logging.critical(f"on_selection_changed: DIDN'T THINK THIS WAS POSSIBLE {len(indexes) = }")

        for index in indexes:
            file_path = self.model.filePath(index)
            logging.debug(f"folderExplorer.on_selection_changed: {file_path = }")
            self.selected_path = file_path

            self.action_debug_2_run(self.model.fileInfo(index))





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
        # logging.debug(f"CALLED ON THIS METHOD (get_selection_model) IS FUCKING DANGEROUS")
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

        menu.addSeparator()

        action_menu_debug = QMenu("Debug", self)
        action_debug_1 = QAction("Debug Action 1", self)
        action_debug_1.triggered.connect(lambda: self.action_debug_1_run(file_info))
        action_menu_debug.addAction(action_debug_1)

        action_debug_2 = QAction("Debug Action 2", self)
        action_debug_2.triggered.connect(lambda: self.action_debug_2_run(file_info))
        action_menu_debug.addAction(action_debug_2)

        menu.addMenu(action_menu_debug)


        # **Display the context menu at the cursor's global position**
        viewport = self.tree.viewport()
        if viewport is None: return
        menu.exec(viewport.mapToGlobal(position))


    def action_debug_1_run(self, file_info: QFileInfo) -> int:
        file_path = file_info.absoluteFilePath()
        logging.warning(f"action_debug_1_run: file_path = {file_path}")
        logging.warning(f"THIS IS STRICTLY FOR DEBUGGING PURPOSES")

        status_report = status_cache[file_path]
        if status_report is None:
            logging.warning(f"status_cache is None for {file_path = }")
            return -1
        if not isinstance(status_report, StatusReport):
            logging.warning(f"status_cache is not a StatusReport for {file_path = }")
            return -2

        logging.warning(f"{status_report.status = }")

        if not status_report.status in ['ok', 'fixable', 'warning', 'critical']:
            logging.warning(f"status is not STATUS_OK for {file_path = }")
            return -3

        return 0

    def action_debug_2_run(self, file_info: QFileInfo) -> None:
        try:
            folder_path = file_info.absoluteFilePath()
            if not self.action_debug_1_run(file_info) == 0 : return
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

    def on_stop_button_clicked(self) -> None:
        logging.debug("Stop all scans button clicked.")
        self.model.stop_all_scans()

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

    def rescan(self) -> None:
        logging.debug(f"FolderExplorer.rescan() view_path: {self.view_path} model_root_path: {self.model_root_path} target_path: {self.target_path}")

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
