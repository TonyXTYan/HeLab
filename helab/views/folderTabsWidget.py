# tabWidget.py
import logging
import os
import sys
from typing import Tuple, List, Dict

from PyQt6.QtCore import QDir, QThreadPool, Qt
from PyQt6.QtWidgets import QTabWidget, QWidget
from cachetools import LRUCache

from helab.models.helabFileSystemModel import helabFileSystemModel
from helab.views.folderExplorer import FolderExplorer
from helab.workers.statusDeepWorker import StatusDeepWorker
from helab.workers.statusWorker import StatusWorker


class FolderTabWidget(QTabWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setTabsClosable(True)
        self.tabCloseRequested.connect(self.removeTab)

        # Initialize shared resources
        self.status_cache: LRUCache[str, Tuple[str, int, List[str]]] = LRUCache(maxsize=10000)
        thread_pool = QThreadPool.globalInstance()
        if thread_pool is None:
            logging.fatal("QThreadPool.globalInstance() returned None. Exiting.")
            sys.exit(1)
        self.thread_pool: QThreadPool = thread_pool
        self.running_workers_status: Dict[str, StatusWorker] = {}
        self.running_workers_deep: Dict[str, StatusDeepWorker] = {}
        self.tab_back_button_enabled = False

        self.currentChanged.connect(self.on_current_tab_changed)

    def add_new_folder_explorer_tab(self) -> None:
        # Create a new FolderExplorer instance
        dirPath = QDir.rootPath()
        view_path = dirPath
        # target_path = r'/Volumes/tonyNVME Gold/dld output'

        target_paths = [
            '/Volumes/tonyNVME Gold/dld output',
            '/Users/tonyyan/Documents/_ANU/_He_BEC_Group/HeLab',
            'C:\\Users\\XinTong\\Documents',
            'O:\\'
            ''
        ]

        target_path = next((path for path in target_paths if os.path.exists(path)), '')

        try:
            if not os.path.commonpath([dirPath, target_path]) == os.path.abspath(dirPath):
                logging.warning(
                    f"Target path {target_path} is not under the root path {dirPath}. Adjusting dirPath accordingly.")
                dirPath = os.path.dirname(target_path)
        except ValueError as e:
            logging.error(f"Error validating target path: {e}")
            dirPath = QDir.rootPath()
            target_path = QDir.rootPath()

        columns_to_show = [
            helabFileSystemModel.COLUMN_NAME,
            helabFileSystemModel.COLUMN_DATE_MODIFIED,
            helabFileSystemModel.COLUMN_STATUS_NUMBER,
            helabFileSystemModel.COLUMN_STATUS_ICON,
            helabFileSystemModel.COLUMN_RIGHTFILL
        ]
        folder_explorer = FolderExplorer(dirPath, target_path, view_path, columns_to_show, status_cache=self.status_cache, thread_pool=self.thread_pool, running_workers_status=self.running_workers_status, running_workers_deep=self.running_workers_deep)
        index = self.addTab(folder_explorer, 'File Explorer')

        folder_explorer.rootPathChanged.connect(lambda path, idx=index: self.update_folder_explorer_tab_title(path, idx))
        folder_explorer.emit_root_path_changed()

        self.setCurrentIndex(index)

        # Add the FolderExplorer as a new tab
        # self.tab_widget.addTab(folder_explorer, 'File Explorer')

    def update_folder_explorer_tab_title(self, path: str, index: int) -> None:
        logging.debug(f"Updating tab title for index {index} to {path}")
        # self.tab_widget.setTabText(index, os.path.basename(path))
        if path == "/":
            self.setTabText(index, "Path /")
        else:
            self.setTabText(index, os.path.basename(path))

    def on_back_button_clicked(self) -> None:
        # Get the current folder explorer
        current_folder_explorer = self.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            current_folder_explorer.on_back_button_clicked()
            self.tab_back_button_enabled = current_folder_explorer.back_button_enabled


    def clear_status_cache(self) -> None:
        self.status_cache.clear()
        self.running_workers_status.clear()
        self.running_workers_deep.clear()

        logging.info("Status cache cleared.")
        self.refresh_current_folder_explorer()


    def refresh_current_folder_explorer(self) -> None:
        current_folder_explorer = self.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            current_folder_explorer.refresh()
            logging.info("Current FolderExplorer tab has been refreshed.")
        else:
            logging.warning("Current tab is not a FolderExplorer instance.")

    def on_current_tab_changed(self, index: int) -> None:
        logging.debug(f"(TabWidget) Current tab changed to index {index}")
        # current_folder_explorer = self.currentWidget()
        # if isinstance(current_folder_explorer, FolderExplorer):
        #     current_folder_explorer.update_back_button_state()
        #     self.tab_back_button_enabled = current_folder_explorer.back_button_enabled