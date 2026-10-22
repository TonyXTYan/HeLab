# FolderTabWidget.py
import logging
import os
from types import ModuleType
from typing import Any

from PyQt6.QtCore import QDir
from PyQt6.QtWidgets import QTabWidget, QWidget, QTabBar

from helab.utils.constants import DEFAULT_DATA_PATH, DEV_POTENTIAL_DATA_PATHS
from helab.models.SnapshotFileSystemModel import SnapshotFileSystemModel
from helab.views.FolderExplorer import FolderExplorer


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

        self.setStyleSheet("""
                    QTabBar::tab {
                        height: 30px;  /* Set the desired height */
                    }
                """)

        self.tab_back_button_enabled = False

        self.currentChanged.connect(self.on_current_tab_changed)

    def set_tab_switching_enable(self) -> None:
        """Tabs can be moved and closed (each tab's close button)."""
        self.setMovable(True)
        tab_bar = self.tabBar()
        if tab_bar:
            for index in range(self.count()):
                close_button = tab_bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
                if close_button:
                    close_button.setEnabled(True)

    def add_new_folder_explorer_tab(self,
                                    model_root_path: str|None = QDir.rootPath(),
                                    view_path: str|None = None,
                                    target_path: str|None = None,
                                    set_initial_expand_to_parent_level: bool = True,
                                    ) -> None:
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
            SnapshotFileSystemModel.COLUMN_NAME,
            SnapshotFileSystemModel.COLUMN_DATE_MODIFIED,
            SnapshotFileSystemModel.COLUMN_STATUS_NUMBER,
            SnapshotFileSystemModel.COLUMN_STATUS_ICON,
            SnapshotFileSystemModel.COLUMN_RIGHTFILL
        ]

        logging.debug(f"folderTabsWidget.add_new_folder_explorer_tab: cleaned {model_root_path = }, {target_path = }, {view_path = }")

        folder_explorer = FolderExplorer(
            model_root_path= model_root_path,
            target_path = target_path,
            view_path = view_path,
            columns_to_show = columns_to_show,
            set_initial_expand_to_parent_level = False,
            default_candidates = default_candidates,
        )
        index = self.addTab(folder_explorer, 'File Explorer')
        folder_explorer.rootPathChanged.connect(lambda _ : self.update_tab_titles())
        folder_explorer.emit_root_path_changed()
        self.setCurrentIndex(index)
        # (The explorer schedules exactly one initial scan after signal wiring.)

    def update_tab_titles(self) -> None:
        for index in range(self.count()):
            current_folder_explorer = self.widget(index)
            if isinstance(current_folder_explorer, FolderExplorer):
                self.setTabText(index, current_folder_explorer.tab_title_update())
            else:
                logging.critical(f"update_tab_titles: Current tab {index = } is not a FolderExplorer instance.")

    def on_back_button_clicked(self) -> None:
        current_folder_explorer = self.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            current_folder_explorer.on_back_button_clicked()
            self.tab_back_button_enabled = current_folder_explorer.back_button_enabled
            logging.debug(f"folderTabWidget.on_back_button_clicked: {self.tab_back_button_enabled = }")

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
                          f", selected_path = {currently_selected_path}")
        elif index == -1:
            logging.debug("folderTabWidget.on_current_tab_changed: index is -1")
        else:
            logging.warning(f"folderTabWidget.on_current_tab_changed: current tab {index = } is not a FolderExplorer instance.")
        # Each tab owns its snapshot and pending requests: switching tabs does not read caches or
        # invalidate another tab's data.

    def on_stop_button_clicked(self) -> None:
        current_folder_explorer = self.currentWidget()
        if isinstance(current_folder_explorer, FolderExplorer):
            current_folder_explorer.on_stop_button_clicked()
        else:
            logging.warning("on_stop_button_clicked: Current tab is not a FolderExplorer instance.")

    def removeTab(self, index: int) -> None:
        logging.debug(f"Removing tab at index {index}")
        current_folder_explorer = self.widget(index)
        if isinstance(current_folder_explorer, FolderExplorer):
            current_folder_explorer.on_stop_button_clicked()
            current_folder_explorer.close_cleanup()
            current_folder_explorer.deleteLater()
        super().removeTab(index)

    def closeEvent(self, a0: Any) -> None:
        for index in reversed(range(self.count())):
            self.removeTab(0)

        if a0 is not None:
            super().closeEvent(a0)
        logging.debug("FolderTabWidget.closeEvent: finished")