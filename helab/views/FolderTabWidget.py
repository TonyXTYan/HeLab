# tabWidget.py
import gc
import logging
import os
import platform
import sys
from types import ModuleType
from typing import Tuple, List, Dict, Any

from PIL.TiffTags import lookup
from PyQt6.QtCore import QDir, QThreadPool, Qt, QSize, QTimer
from PyQt6.QtWidgets import QTabWidget, QWidget, QMessageBox, QTabBar, QAbstractItemView
# from cachetools import LRUCache, TTLCache
# from matplotlib.backend_bases import CloseEvent

from helab.utils.constants import *
from helab.utils.threading_setup import *
from helab.utils.caching_setup import *
from helab.models.HelabFileSystemModel import HelabFileSystemModel
from helab.views.FolderExplorer import FolderExplorer
from helab.workers.DirectoryCheckWorker import DirectoryCheckWorker
from helab.workers.LoadFolderToRamWorker import LoadFolderToRamWorker
from helab.workers.StatusDeepWorker import StatusDeepWorker
from helab.workers.StatusWorker import StatusWorker
from helab.models.StatusReport import StatusReport


def root_on_target_drive(model_root_path: str, target_path: str, path: ModuleType = os.path) -> str:
    """Root a tab on the target's drive when it differs from the default root.

    On Windows QDir.rootPath() is C:/, so a target on a mapped drive (Y:\\) or a
    UNC share would otherwise fail validation and fall back to C:. POSIX paths
    have no drive, so they are returned unchanged.
    """
    target_drive: str = path.splitdrive(target_path)[0]
    sep: str = path.sep
    if target_drive and path.normcase(target_drive) != path.normcase(path.splitdrive(model_root_path)[0]):
        return target_drive + sep
    return model_root_path


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
        # self.status_cache: LRUCache[str, Tuple[str, int, List[str]]] = LRUCache(maxsize=10*1000)
        # self.hasChildren_cache: TTLCache[str, bool] = TTLCache(maxsize=100*1000, ttl=24*60*60)
        self.status_cache = status_cache
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
                    current_folder_explorer = self.widget(index)
                    if isinstance(current_folder_explorer, FolderExplorer):
                        # current_folder_explorer.tree.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)     # Just click to select multiple items
                        # current_folder_explorer.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)  # Hold Cmd or Shift to select multiple items
                        # current_folder_explorer.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
                        # current_folder_explorer.tree.setEnabled(True)
                        pass
            # tab_bar.setEnabled(True)

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
                current_folder_explorer = self.widget(index)
                if isinstance(current_folder_explorer, FolderExplorer):
                    # current_folder_explorer.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
                    # current_folder_explorer.tree.setEnabled(False)
                    pass
            # tab_bar.setEnabled(False)

    def add_new_folder_explorer_tab(self,
                                    model_root_path: str|None = QDir.rootPath(),
                                    view_path: str|None = None,
                                    target_path: str|None = None,
                                    set_initial_expand_to_parent_level: bool = True,
                                    ) -> None:
        # Create a new FolderExplorer instance
        # model_root_path = QDir.rootPath()
        # model_root_path = QDir.drives()
        # view_path = QDir.rootPath()
        # view_path = model_root_path

        # model_root_path = ""
        # view_path = ""
        # target_path = r'/Volumes/tonyNVME Gold/dld output'

        logging.debug(f"folderTabsWidget.add_new_folder_explorer_tab: called  {model_root_path = }, {target_path = }, {view_path = }")

        if model_root_path is None:
            model_root_path = QDir.rootPath()

        default_candidates = DEV_POTENTIAL_DATA_PATHS if target_path is None else None
        if target_path is None:
            target_path = DEFAULT_DATA_PATH

        model_root_path = root_on_target_drive(model_root_path, target_path)

        if view_path is None:
            view_path = model_root_path

        try:
            if not os.path.commonpath([model_root_path, target_path]) == os.path.abspath(model_root_path):
                logging.warning(
                    f"Target path {target_path} is not under the root path {model_root_path}. Adjusting model_root_path accordingly.")
                model_root_path = os.path.dirname(target_path)
        except ValueError as e:
            logging.error(f"Error validating target path: {e}")
            model_root_path = QDir.rootPath()
            target_path = QDir.rootPath()
            view_path = QDir.rootPath()

        columns_to_show = [
            HelabFileSystemModel.COLUMN_NAME,
            HelabFileSystemModel.COLUMN_DATE_MODIFIED,
            HelabFileSystemModel.COLUMN_STATUS_NUMBER,
            HelabFileSystemModel.COLUMN_STATUS_ICON,
            HelabFileSystemModel.COLUMN_RIGHTFILL
        ]

        logging.debug(f"folderTabsWidget.add_new_folder_explorer_tab: cleaned {model_root_path = }, {target_path = }, {view_path = }")
        # on M4M: add_new_folder_explorer_tab: model_root_path = '/', target_path = '/Volumes/tonyNVME Gold/dld output', view_path = '/'


        folder_explorer = FolderExplorer(
            model_root_path= model_root_path,
            target_path = target_path,
            view_path = view_path,
            columns_to_show = columns_to_show,
            set_initial_expand_to_parent_level = False,
            default_candidates = default_candidates,
        )
        index = self.addTab(folder_explorer, 'File Explorer')

        # folder_explorer.rootPathChanged.connect(lambda path, idx=index: self.update_folder_explorer_tab_title_on_root_change(path, idx))\
        # folder_explorer.on_selection_changed.connect(lambda path, idx=index: self.update_folder_explorer_tab_title(path, idx))
        folder_explorer.rootPathChanged.connect(lambda _ : self.update_tab_titles())

        # selection_model = folder_explorer.get_selection_model()
        # selection_model.selectionChanged.connect(self.update_folder_explorer_tab_title_on_selection_change)

        folder_explorer.emit_root_path_changed()

        self.setCurrentIndex(index)

        # The explorer schedules exactly one initial scan after signal wiring.
        # QTimer.singleShot(600, lambda: self.rescan_current_folder_explorer(user_requested_scan = False))


        # Add the FolderExplorer as a new tab
        # self.tab_widget.addTab(folder_explorer, 'File Explorer')

    def update_tab_titles(self) -> None:
        for index in range(self.count()):
            current_folder_explorer = self.widget(index)
            if isinstance(current_folder_explorer, FolderExplorer):
                self.setTabText(index, current_folder_explorer.tab_title_update())
            else:
                logging.critical(f"update_tab_titles: Current tab {index = } is not a FolderExplorer instance.")

    def update_folder_explorer_tab_title_on_root_change(self, selected_path: str, index: int) -> None:
        logging.debug(f"update_folder_explorer_tab_title: {index = } and {selected_path = }")
        # self.tab_widget.setTabText(index, os.selected_path.basename(selected_path))
        if platform.system() == 'Windows':
            drive, tail = os.path.splitdrive(selected_path)
            if tail in ('\\', '/'):
                self.setTabText(index, drive)
            else:
                self.setTabText(index, os.path.basename(selected_path))
        else:
            if selected_path == "/":
                self.setTabText(index, "/")
            else:
                self.setTabText(index, os.path.basename(selected_path))
        logging.debug(f"update_folder_explorer_tab_title: {self.tabText(index) = }")


    def update_folder_explorer_tab_title_on_selection_change(self, selected: List[str], deselected: List[str]) -> None:
        current_folder_explorer = self.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            selected_path = current_folder_explorer.selected_path_globally
            if selected_path:
                # self.setTabText(self.currentIndex(), os.path.basename(selected_path))
                self.update_folder_explorer_tab_title_on_root_change(selected_path, self.currentIndex())
            else:
                self.setTabText(self.currentIndex(), "File Explorer")
        else:
            logging.warning("Current tab is not a FolderExplorer instance.")

    def on_back_button_clicked(self) -> None:
        # Get the current folder explorer
        current_folder_explorer = self.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            current_folder_explorer.on_back_button_clicked()
            self.tab_back_button_enabled = current_folder_explorer.back_button_enabled
            logging.debug(f"folderTabWidget.on_back_button_clicked: {self.tab_back_button_enabled = }")

    def clear_status_cache(self) -> None:
        for index in range(self.count()):
            explorer = self.widget(index)
            if isinstance(explorer, FolderExplorer):
                explorer.rescan(True)
        running_workers_status.clear()
        running_workers_deep.clear()
        running_workers_hasChildren.clear()

        logging.info("Status cache cleared.")
        self.refresh_current_folder_explorer()


    def refresh_current_folder_explorer(self) -> None:
        current_folder_explorer = self.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            current_folder_explorer.refresh()
            logging.debug("FolderTabWidget.refresh_current_folder_explorer() completed.")
        else:
            logging.warning("Current tab is not a FolderExplorer instance.")

    def rescan_current_folder_explorer(self, user_intend: bool = False) -> None:
        try:
            current_folder_explorer = self.currentWidget()
        except RuntimeError:
            logging.debug("FolderTabWidget.rescan_current_folder_explorer: widget has been deleted, skipping deferred rescan.")
            return
        if isinstance(current_folder_explorer, FolderExplorer):
            current_folder_explorer.rescan(user_intend)
            logging.debug("FolderTabWidget.rescan_current_folder_explorer() returned.")
        else:
            logging.warning("Current tab is not a FolderExplorer instance.")

    def on_current_tab_changed(self, index: int) -> None:
        logging.debug(f"folderTabWidget.on_current_tab_changed: to index {index}")
        self.update_tab_titles()
        current_folder_explorer = self.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            # The current tab's browsing and selected load use the foreground I/O lane.
            current_folder_explorer.claim_foreground()
            currently_selected_path = current_folder_explorer.get_selected_path_from_model()
            logging.debug(f"Current tab dir_path: {current_folder_explorer.model_root_path}"
                          f", view_path: {current_folder_explorer.view_path}"
                          f", target_path: {current_folder_explorer.target_path}"
                          f", selected_path = {currently_selected_path}"
                          # f", {current_folder_explorer.get_selected_path() = }"
                          )
        else:
            currently_selected_path = ""
            if index == -1:
                logging.debug("folderTabWidget.on_current_tab_changed: index is -1")
            else:
                logging.warning(f"folderTabWidget.on_current_tab_changed: current tab {index = } is not a FolderExplorer instance.")
        # current_folder_explorer = self.currentWidget()
        # if isinstance(current_folder_explorer, FolderExplorer):
        #     current_folder_explorer.update_back_button_state()
        #     self.tab_back_button_enabled = current_folder_explorer.back_button_enabled

        for ii in range(self.count()):
            logging.debug(f"folderTabWidget.on_current_tab_changed: checking tab {ii}")
            if ii == index:
                continue
            other_folder_explorer = self.widget(ii)
            if isinstance(other_folder_explorer, FolderExplorer):
                logging.debug(f"folderTabWidget.on_current_tab_changed: {ii = }, {other_folder_explorer.folder_opened_path = }")
                if (other_folder_explorer.folder_opened_path is not None and
                    other_folder_explorer.folder_opened_path != currently_selected_path):
                    # Each tab owns its snapshot and pending requests. Switching
                    # tabs does not read caches or invalidate another tab's data.
                    pass
                # other_folder_explorer.clear_selection()
            else:
                logging.warning("folderTabWidget.on_current_tab_changed: other tab is not a FolderExplorer instance.")

    def update_all_path_selection(self, path: str) -> None:
        for index in range(self.count()):
            current_folder_explorer = self.widget(index)
            if isinstance(current_folder_explorer, FolderExplorer):
                current_folder_explorer.selected_path_globally = path
            else:
                logging.warning("Current tab is not a FolderExplorer instance.")

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

    def closeEvent(self, a0: Any) -> None:
        # Close all tabs
        for index in reversed(range(self.count())):
            self.removeTab(0)

        if a0 is not None:
            super().closeEvent(a0)
        logging.debug("FolderTabWidget.closeEvent: finished")