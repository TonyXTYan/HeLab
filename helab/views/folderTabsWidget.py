# tabWidget.py
import logging
import os

from PyQt6.QtCore import QDir, QThreadPool, Qt
from PyQt6.QtWidgets import QTabWidget
from cachetools import LRUCache

from helab.models.helabFileSystemModel import helabFileSystemModel
from helab.views.folderExplorer import FolderExplorer


class FolderTabWidget(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabsClosable(True)
        self.tabCloseRequested.connect(self.removeTab)

        # Initialize shared resources
        self.status_cache = LRUCache(maxsize=10000)
        self.thread_pool = QThreadPool.globalInstance()
        self.running_workers_status = {}
        self.running_workers_deep = {}

    def add_new_folder_explorer_tab(self):
        # Create a new FolderExplorer instance
        dirPath = QDir.rootPath()
        view_path = dirPath
        target_path = r'/Volumes/tonyNVME Gold/dld output'
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

        # Add the FolderExplorer as a new tab
        # self.tab_widget.addTab(folder_explorer, 'File Explorer')

    def update_folder_explorer_tab_title(self, path, index):
        logging.debug(f"Updating tab title for index {index} to {path}")
        # self.tab_widget.setTabText(index, os.path.basename(path))
        if path == "/":
            self.setTabText(index, "Path /")
        else:
            self.setTabText(index, os.path.basename(path))

    def on_back_button_clicked(self):
        # Get the current folder explorer
        current_folder_explorer = self.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            current_folder_explorer.on_back_button_clicked()

    def clear_status_cache(self):
        self.status_cache.clear()
        self.running_workers_status.clear()
        self.running_workers_deep.clear()

        logging.info("Status cache cleared.")
        self.refresh_current_folder_explorer()


    def refresh_current_folder_explorer(self):
        current_folder_explorer = self.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            current_folder_explorer.refresh()
            logging.info("Current FolderExplorer tab has been refreshed.")
        else:
            logging.warning("Current tab is not a FolderExplorer instance.")