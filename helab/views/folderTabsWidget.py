# tabWidget.py
import gc
import logging
import os
import sys
from typing import Tuple, List, Dict

from PyQt6.QtCore import QDir, QThreadPool, Qt, QSize
from PyQt6.QtWidgets import QTabWidget, QWidget, QMessageBox, QTabBar
from cachetools import LRUCache, TTLCache

from helab.models.helabFileSystemModel import helabFileSystemModel
from helab.views.folderExplorer import FolderExplorer
from helab.workers.directoryCheckWorker import DirectoryCheckWorker
from helab.workers.statusDeepWorker import StatusDeepWorker
from helab.workers.statusWorker import StatusWorker


class FolderTabWidget(QTabWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setTabsClosable(True)
        self.setMovable(True)
        self.tabCloseRequested.connect(self.removeTab)
        self._tab_switching_enabled = True

        self.setStyleSheet("""
                    QTabBar::tab {
                        height: 30px;  /* Set the desired height */
                    }
                """)

        # Initialize shared resources
        self.status_cache: LRUCache[str, Tuple[str, int, List[str]]] = LRUCache(maxsize=10*1000)
        self.hasChildren_cache: TTLCache[str, bool] = TTLCache(maxsize=100*1000, ttl=24*60*60)

        thread_pool = QThreadPool.globalInstance()
        if thread_pool is None:
            logging.fatal("QThreadPool.globalInstance() returned None. Exiting.")
            sys.exit(1)
        self.thread_pool: QThreadPool = thread_pool
        self.running_workers_status: Dict[str, StatusWorker] = {}
        self.running_workers_deep: Dict[str, StatusDeepWorker] = {}
        self.running_workers_hasChildren: Dict[str, DirectoryCheckWorker] = {}
        self.tab_back_button_enabled = False

        self.currentChanged.connect(self.on_current_tab_changed)


    def set_tab_switching_enable(self) -> None:
        self._tab_switching_enabled = True
        # self.setTabsClosable(True)
        self.setMovable(True)
        # self.setTabEnabled()
        tab_bar = self.tabBar()
        if tab_bar:
            for index in range(self.count()):
                if tab_bar:
                    close_button = tab_bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
                    if close_button:
                        close_button.setEnabled(True)  # Enable the close button
            tab_bar.setEnabled(True)

    def set_tab_switching_disable(self) -> None:
        self._tab_switching_enabled = False
        # self.setTabsClosable(False)
        self.setMovable(False)
        tab_bar = self.tabBar()
        if tab_bar:
            for index in range(self.count()):
                close_button = tab_bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
                if close_button:
                    close_button.setEnabled(False)  # Disable the close button
            tab_bar.setEnabled(False)

    def add_new_folder_explorer_tab(self) -> None:
        # Create a new FolderExplorer instance
        dirPath = QDir.rootPath()
        view_path = dirPath
        # target_path = r'/Volumes/tonyNVME Gold/dld output'

        target_paths = [
            '/Volumes/tonyNVME Gold/dld output',
            '/Users/tonyyan/.cache/2024_Momentum_Bells_V2 - 20241200',
            # '/Users/tonyyan/Library/CloudStorage/OneDrive-AustralianNationalUniversity/SharePoint - Testing MS Teams/2024_Momentum_Bells_V2 - 20241200',
            # Don't use OneDrive it's shit (cause file system hangs)
            os.getcwd(),
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
        folder_explorer = FolderExplorer(
            dir_path = dirPath,
            target_path = target_path,
            view_path = view_path,
            columns_to_show = columns_to_show,
            status_cache = self.status_cache,
            hasChildren_cache = self.hasChildren_cache,
            thread_pool = self.thread_pool,
            running_workers_status = self.running_workers_status,
            running_workers_deep = self.running_workers_deep,
            running_workers_hasChildren = self.running_workers_hasChildren
        )
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
            self.setTabText(index, "Root path")
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
        self.running_workers_hasChildren.clear()

        logging.info("Status cache cleared.")
        self.refresh_current_folder_explorer()


    def refresh_current_folder_explorer(self) -> None:
        current_folder_explorer = self.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            current_folder_explorer.refresh()
            logging.debug("FolderTabWidget.refresh_current_folder_explorer() completed.")
        else:
            logging.warning("Current tab is not a FolderExplorer instance.")

    def rescan_current_folder_explorer(self) -> None:
        current_folder_explorer = self.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            current_folder_explorer.rescan()
            logging.info("FolderTabWidget.rescan_current_folder_explorer() returned.")
        else:
            logging.warning("Current tab is not a FolderExplorer instance.")

    def on_current_tab_changed(self, index: int) -> None:
        logging.debug(f"(TabWidget) Current tab changed to index {index}")
        current_folder_explorer = self.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            logging.debug(f"Current tab dir_path: {current_folder_explorer.dir_path}, view_path: {current_folder_explorer.view_path}, target_path: {current_folder_explorer.target_path}")
        else:
            logging.warning("Current tab is not a FolderExplorer instance.")
        # current_folder_explorer = self.currentWidget()
        # if isinstance(current_folder_explorer, FolderExplorer):
        #     current_folder_explorer.update_back_button_state()
        #     self.tab_back_button_enabled = current_folder_explorer.back_button_enabled

    def on_stop_button_clicked(self) -> None:
        current_folder_explorer = self.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            current_folder_explorer.on_stop_button_clicked()
            # self.tab_back_button_enabled = current_folder_explorer.back_button_enabled
        else:
            logging.warning("on_stop_button_clicked: Current tab is not a FolderExplorer instance.")

    def removeTab(self, index: int) -> None:
        # Remove the tab
        # self.widget(index).close_cleanup
        logging.debug(f"Removing tab at index {index}")
        current_folder_explorer = self.widget(index)
        queue_depth = len(self.running_workers_status) + len(self.running_workers_deep)
        if queue_depth > 0:
            QMessageBox.warning(self, "Please wait for background taks to finish",
                                "There are ongoing background tasks. Please wait for them to complete or cancel them before closing the tab.",
                                QMessageBox.StandardButton.Ok)
            return
        if isinstance(current_folder_explorer, FolderExplorer):
            # if current_folder_explorer.is_running_status_worker():
            #     logging.debug(f"Stopping status worker for tab at index {index}")
            #     current_folder_explorer.stop_status_worker()
            #     return
            current_folder_explorer.on_stop_button_clicked()
            current_folder_explorer.close_cleanup()
            current_folder_explorer.deleteLater()
        super().removeTab(index)
        # gc.collect()