# SettingsDialog.py
import logging
import sys
from re import S
from typing import Optional, Dict, Any

from PyQt6.QtGui import QCloseEvent, QDesktopServices
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox, QLineEdit, QLabel, QTabWidget, \
    QWidget, QComboBox, QFormLayout, QScrollArea, QSpinBox, QFileDialog, QSpacerItem
from PyQt6.QtCore import QSettings, QUrl

from helab.utils.cache_store import store_root
from helab.utils.number_format import fnum
from helab.utils.constants import *


class SettingsDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, *, settings: QSettings | None = None) -> None:
        super().__init__(parent)
        self.settings = settings if settings is not None else QSettings(QSETTINGS_ORG_NAME, QSETTINGS_APP_NAME)
        self.setWindowTitle("Settings")
        self.setMinimumSize(800, 500)
        self.main_layout = QVBoxLayout(self)
        MLCM = 8 # Main Layout Contents Margin
        self.main_layout.setContentsMargins(MLCM,MLCM,MLCM,MLCM)

        # Create tab widget
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(False)
        self.tabs.setMovable(False)
        self.tabs.setStyleSheet("""
            QTabBar::tab {
                width: 150px;
            }""")

        # tab_bar = self.tabs.tabBar()
        # if tab_bar: tab_bar.setExpanding(True)
        if (tab_bar := self.tabs.tabBar()): tab_bar.setExpanding(True)
        self.main_layout.addWidget(self.tabs)

        # First tab
        self.general_tab = QWidget()
        self.general_layout = QVBoxLayout(self.general_tab)

        self.example_checkbox = QCheckBox("Enable feature X")
        self.example_text = QLineEdit()
        self.example_text.setPlaceholderText("Enter some text")

        self.general_layout.addWidget(self.example_checkbox)
        self.general_layout.addWidget(QLabel("Example Text:"))
        self.general_layout.addWidget(self.example_text)

        self.load_mode_combo = QComboBox()
        for mode, label in LOAD_MODE_LABELS.items():
            self.load_mode_combo.addItem(label, mode)
        self.general_layout.addSpacerItem(QSpacerItem(0, 10))
        self.general_layout.addWidget(QLabel("When selecting another folder:"))
        self.general_layout.addWidget(self.load_mode_combo)

        folder_io_form = QFormLayout()
        self.simultaneous_io_spin = QSpinBox()
        self.simultaneous_io_spin.setRange(1, MAX_SIMULTANEOUS_IO)
        self.simultaneous_io_spin.setToolTip(
            "Shared across all tabs for background loads, folder details, folder status checks and cache writes. "
            "One extra lane is reserved for browsing and the selected folder's load in the current tab; "
            "background work pauses while it runs. Running work finishes when the limit is lowered.")
        folder_io_form.addRow("Simultaneous background I/O operations:", self.simultaneous_io_spin)
        self.general_layout.addLayout(folder_io_form)
        self.auto_scan_visible_checkbox = QCheckBox("Automatically check folder status in view")
        self.auto_scan_visible_checkbox.setToolTip(
            "Scan visible folders that have no saved scan results. Cached results are kept until a manual scan or refresh.")
        self.general_layout.addWidget(self.auto_scan_visible_checkbox)


        # DIR_TEMPS and DIR_CACHES
        self.general_layout.addSpacerItem(QSpacerItem(0, 10))
        self.general_layout.addWidget(QLabel("Directory Settings"))
        self.dir_scroll_area = QScrollArea()
        self.dir_scroll_area.setWidgetResizable(True)
        self.dir_scroll_content = QWidget()
        self.dir_scroll_layout = QVBoxLayout(self.dir_scroll_content)
        self.dir_scroll_layout.setSpacing(0)
        # self.dir_scroll_layout.setContentsMargins(0, 0, 0, 0)
        # self.dir_scroll_area.setStyleSheet("QScrollArea {background: transparent;}")
        # self.dir_scroll_area.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget {background: transparent;}")

        self.dir_temps_edit = QLineEdit()
        self.dir_caches_edit = QLineEdit()

        self.dir_temps_edit.setText(DIR_TEMPS)
        self.dir_caches_edit.setText(DIR_CACHES)

        self.dir_temps_browse_btn = QPushButton("Browse...")
        self.dir_caches_browse_btn = QPushButton("Browse...")
        self.dir_temps_open_btn = QPushButton("Open Path")
        self.dir_caches_open_btn = QPushButton("Open Path")
        self.dir_temps_reset_btn = QPushButton("Reset to Default")
        self.dir_caches_reset_btn = QPushButton("Reset to Default")

        self.dir_temps_browse_btn.clicked.connect(self.browse_dir_temps)
        self.dir_caches_browse_btn.clicked.connect(self.browse_dir_caches)
        self.dir_temps_open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.dir_temps_edit.text())))
        self.dir_caches_open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.dir_caches_edit.text())))
        # Reset shows the persistent default; it is saved (and created on next launch) with Save.
        self.dir_temps_reset_btn.clicked.connect(lambda: self.dir_temps_edit.setText(default_app_dir("temps")))
        self.dir_caches_reset_btn.clicked.connect(lambda: self.dir_caches_edit.setText(default_app_dir("caches")))



        self.dir_scroll_layout.addWidget(QLabel("DIR_TEMPS:"))
        self.dir_scroll_layout.addWidget(self.dir_temps_edit)
        dir_temps_btn_layout = QHBoxLayout()
        dir_temps_btn_layout.addWidget(self.dir_temps_browse_btn)
        dir_temps_btn_layout.addWidget(self.dir_temps_open_btn)
        dir_temps_btn_layout.addWidget(self.dir_temps_reset_btn)
        self.dir_scroll_layout.addLayout(dir_temps_btn_layout)

        self.dir_scroll_layout.addWidget(QLabel("DIR_CACHES:"))
        self.dir_scroll_layout.addWidget(self.dir_caches_edit)
        dir_caches_btn_layout = QHBoxLayout()
        dir_caches_btn_layout.addWidget(self.dir_caches_browse_btn)
        dir_caches_btn_layout.addWidget(self.dir_caches_open_btn)
        dir_caches_btn_layout.addWidget(self.dir_caches_reset_btn)
        self.dir_scroll_layout.addLayout(dir_caches_btn_layout)

        self.dir_scroll_area.setWidget(self.dir_scroll_content)
        self.general_layout.addWidget(self.dir_scroll_area)

        # Expandable spacer
        self.general_layout.addStretch()




        self.tabs.addTab(self.general_tab, "General")

        # TODO: default load folder

        # Scripts Tab
        self.scripts_tab = QWidget()
        self.scripts_layout = QVBoxLayout(self.scripts_tab)
        self.scripts_layout.addWidget(QLabel("Scripts Settings"))
        self.tabs.addTab(self.scripts_tab, "Scripts")


        # Cache Tab
        # self.cache_tab = QWidget()
        # self.cache_layout = QVBoxLayout(self.cache_tab)
        # self.cache_layout.addWidget(QLabel("Cache Settings"))
        # self.tabs.addTab(self.cache_tab, "Cache")

        # # Placeholder tab
        # self.placeholder_tab = QWidget()
        # self.placeholder_layout = QVBoxLayout(self.placeholder_tab)
        # self.placeholder_layout.addWidget(QLabel("Placeholder text for the second tab"))
        # self.tabs.addTab(self.placeholder_tab, "Placeholder")


        self._make_tab_cache()


        # Buttons
        self.button_layout = QHBoxLayout()
        self.save_button = QPushButton("Save")
        self.cancel_button = QPushButton("Cancel")
        self.reset_button = QPushButton("Reset")
        self.button_layout.addWidget(self.save_button)
        self.button_layout.addWidget(self.cancel_button)
        self.button_layout.addWidget(self.reset_button)
        self.main_layout.addLayout(self.button_layout)

        self.save_button.clicked.connect(self.save_settings)
        self.cancel_button.clicked.connect(self.reject)
        self.reset_button.clicked.connect(self.reset_settings)

        self.load_settings()

        # self.main_layout.setStretch(0, 1)
        # self.main_layout.setStretch(1, 0)

    def _make_tab_cache(self) -> None:
        # The old diskcache tab is gone with diskcache; the store-v2 tab is rebuilt in a
        # later update (roadmaps/cache-storage-and-settings.md, S7). The GUI never opens the store.
        self.cache_tab = QWidget()
        self.cache_layout = QVBoxLayout(self.cache_tab)
        location = QLabel(f"Disk cache: {store_root(DIR_CACHES)}" if DISK_CACHE_ENABLED
                          else "Disk cache: off for this session")
        location.setWordWrap(True)
        location.setToolTip("Change the folder on the General tab.")
        self.cache_layout.addWidget(location)
        if DIR_CACHES_REFUSED:
            refused = QLabel(DIR_CACHES_REFUSED)
            refused.setWordWrap(True)
            self.cache_layout.addWidget(refused)
        self.cache_layout.addWidget(QLabel("Cache details and clearing are rebuilt in a later update."))
        self.cache_layout.addStretch(1)
        self.tabs.addTab(self.cache_tab, "Cache")

    def browse_dir_temps(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select DIR_TEMPS Folder")
        if folder:
            self.dir_temps_edit.setText(folder)

    def browse_dir_caches(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select DIR_CACHES Folder")
        if folder:
            self.dir_caches_edit.setText(folder)

    def load_settings(self) -> None:
        settings = self.settings
        self.example_checkbox.setChecked(settings.value("example_checkbox", False, type=bool))
        self.example_text.setText(settings.value("example_text", "", type=str))
        self.dir_temps_edit.setText(settings.value("dir_temps", DIR_TEMPS, type=str))
        self.dir_caches_edit.setText(settings.value("dir_caches", DIR_CACHES, type=str))
        self.load_mode_combo.setCurrentIndex(self.load_mode_combo.findData(read_load_mode(settings)))
        self.simultaneous_io_spin.setValue(read_io_concurrency(settings))
        self.auto_scan_visible_checkbox.setChecked(settings.value(AUTO_SCAN_VISIBLE_SETTING, False, type=bool))
        logging.debug("Settings loaded")

    def save_settings(self) -> None:
        settings = self.settings
        settings.setValue("example_checkbox", self.example_checkbox.isChecked())
        settings.setValue("example_text", self.example_text.text())
        settings.setValue("dir_temps", self.dir_temps_edit.text())
        settings.setValue("dir_caches", self.dir_caches_edit.text())
        settings.setValue(LOAD_MODE_SETTING, self.load_mode_combo.currentData())
        settings.setValue(SIMULTANEOUS_IO_SETTING, self.simultaneous_io_spin.value())
        settings.remove("simultaneous_folder_scans")
        settings.remove("simultaneous_folder_loads")
        settings.setValue(AUTO_SCAN_VISIBLE_SETTING, self.auto_scan_visible_checkbox.isChecked())

        self.accept()
        logging.debug("Settings saved")

    def closeEvent(self, a0: QCloseEvent|None) -> None:
        # self.save_settings()
        # TODO warning box if unsaved changes


        logging.warning("Settings dialog closed")
        super().closeEvent(a0)
        self.deleteLater()

    def reset_settings(self) -> None:
        settings = self.settings
        settings.clear()
        self.load_settings()
        logging.debug("Settings reset to default")
