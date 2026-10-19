# SettingsDialog.py
import logging
import sys
import time
from re import S
from typing import Optional, Dict, Any

from PyQt6.QtGui import QCloseEvent, QDesktopServices
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox, QLineEdit, QLabel, QTabWidget, \
    QWidget, QComboBox, QFormLayout, QScrollArea, QSpinBox, QFileDialog, QSpacerItem, QDoubleSpinBox
from PyQt6.QtCore import QSettings, QUrl

from helab.utils.folder_cache import FolderCache, store_options
from helab.utils.number_format import fnum
from helab.utils.constants import *
from helab.views.DataRootsTab import DataRootsTab
from helab.views.CacheTab import CacheTab


class SettingsDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, *, settings: QSettings | None = None,
                 cache: FolderCache | None = None) -> None:
        super().__init__(parent)
        self.settings = settings if settings is not None else QSettings(QSETTINGS_ORG_NAME, QSETTINGS_APP_NAME)
        self.cache = cache
        self.mover: Any = None  # CacheMover, made on the first Change…
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
        self.check_level_combo = QComboBox()
        for level, label in CHECK_LEVEL_LABELS.items():
            self.check_level_combo.addItem(label, level)
        self.check_level_combo.setToolTip(
            "When a folder's cached data is shown, HeLab checks the folder. If the folder wasn't modified since "
            "it was cached, it also checks these TXY files' sizes and modified times instead of listing the "
            "folder; random files differ each time. If any differs or is missing, it lists and compares every "
            "file. Full always does that (slower on network folders). Right-click › Retry / Refresh always "
            "checks every file.")
        folder_io_form.addRow("Check of cached data:", self.check_level_combo)
        self.live_interval_spin = QDoubleSpinBox()
        self.live_interval_spin.setRange(MIN_LIVE_INTERVAL, MAX_LIVE_INTERVAL)
        self.live_interval_spin.setDecimals(1)
        self.live_interval_spin.setSingleStep(0.5)
        self.live_interval_spin.setSuffix(" s")
        self.live_interval_spin.setToolTip(
            "While Live watches a folder, its next check starts this long after the previous one ended, so "
            "checks never overlap or queue up on a slow drive. A check of an unchanged folder is one folder stat.")
        folder_io_form.addRow("Live: check again after", self.live_interval_spin)
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
        # The cache folder changes only by moving the cache (Change…), never by typing a path.
        self.dir_caches_edit.setReadOnly(True)
        self.dir_caches_edit.setText(cache_dir())

        self.dir_temps_browse_btn = QPushButton("Browse...")
        self.dir_caches_browse_btn = QPushButton("Change…")
        self.dir_caches_browse_btn.setToolTip("Move the disk cache to another folder. HeLab pauses loading and "
                                              "folder checks while it moves.")
        self.dir_temps_open_btn = QPushButton("Open Path")
        self.dir_caches_open_btn = QPushButton("Open Path")
        self.dir_temps_reset_btn = QPushButton("Reset to Default")

        self.dir_temps_browse_btn.clicked.connect(self.browse_dir_temps)
        self.dir_caches_browse_btn.clicked.connect(self.change_cache_folder)
        self.dir_caches_browse_btn.setEnabled(self.cache is not None and bool(store_options()))
        self.dir_temps_open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.dir_temps_edit.text())))
        self.dir_caches_open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.dir_caches_edit.text())))
        # Reset shows the persistent default; it is saved (and created on next launch) with Save.
        self.dir_temps_reset_btn.clicked.connect(lambda: self.dir_temps_edit.setText(default_app_dir("temps")))



        self.dir_scroll_layout.addWidget(QLabel("DIR_TEMPS:"))
        self.dir_scroll_layout.addWidget(self.dir_temps_edit)
        dir_temps_btn_layout = QHBoxLayout()
        dir_temps_btn_layout.addWidget(self.dir_temps_browse_btn)
        dir_temps_btn_layout.addWidget(self.dir_temps_open_btn)
        dir_temps_btn_layout.addWidget(self.dir_temps_reset_btn)
        self.dir_scroll_layout.addLayout(dir_temps_btn_layout)

        self.dir_scroll_layout.addWidget(QLabel("Cache folder (moving it keeps its contents):"))
        self.dir_scroll_layout.addWidget(self.dir_caches_edit)
        dir_caches_btn_layout = QHBoxLayout()
        dir_caches_btn_layout.addWidget(self.dir_caches_browse_btn)
        dir_caches_btn_layout.addWidget(self.dir_caches_open_btn)
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
        self.cache_tab.budgetApplied.connect(self._budget_applied)


        # Buttons
        self.button_layout = QHBoxLayout()
        self.save_button = QPushButton("Save")
        self.cancel_button = QPushButton("Cancel")
        self.reset_button = QPushButton("Reset all settings…")
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
        # The GUI never opens the store: the tab asks a helper (FolderCache.cache_admin).
        self.cache_tab = CacheTab(self.cache, self.settings)
        self.tabs.addTab(self.cache_tab, "Cache")
        self.roots_tab = DataRootsTab(self.cache)
        self.tabs.addTab(self.roots_tab, "Data roots")

    def show_purge(self) -> None:
        """Open at the Cache tab's Remove old entries (from the disk cache's 80% warning)."""
        self.tabs.setCurrentWidget(self.cache_tab)
        self.cache_tab.focus_purge()

    def done(self, a0: int) -> None:
        if self.mover is not None and self.mover.busy:
            return  # A cache move switches folders (or is cancelled) first.
        if self.cache_tab.applying and self.cache is not None:
            # Closed while the store records a new budget: the one in effect stays. Set again
            # now, so it is newer than the change, and sent until the store has it.
            self.cache.restore_budget()
        self.cache_tab.detach()
        self.roots_tab.detach()
        if self.mover is not None:
            # The mover outlives this dialog (e.g. deleting the old folder): stop listening.
            self.mover.switched.disconnect(self._cache_switched)
            self.mover.finished.disconnect(self._cache_move_ended)
            self.mover.window = None
            self.mover = None
        super().done(a0)

    def browse_dir_temps(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select DIR_TEMPS Folder")
        if folder:
            self.dir_temps_edit.setText(folder)

    def change_cache_folder(self, folder: str = "") -> None:
        """Move the disk cache to an empty or new folder (``CacheMover``)."""
        if self.cache is None:
            return
        from helab.views.CacheMover import cache_mover
        mover = cache_mover(self.cache, self.settings)
        if mover.running:
            return
        folder = folder or QFileDialog.getExistingDirectory(self, "Move the disk cache to an empty folder")
        if not folder:
            return
        if self.mover is None:
            self.mover = mover
            mover.switched.connect(self._cache_switched)
            mover.finished.connect(self._cache_move_ended)
        self.dir_caches_browse_btn.setEnabled(False)
        if not mover.change(folder, self):
            self.dir_caches_browse_btn.setEnabled(True)

    def _cache_switched(self) -> None:
        self.dir_caches_edit.setText(cache_dir())
        self.cache_tab.show_location()

    def _cache_move_ended(self, moved: bool) -> None:
        self.dir_caches_browse_btn.setEnabled(True)
        self._cache_switched()

    def load_settings(self) -> None:
        settings = self.settings
        self.example_checkbox.setChecked(settings.value("example_checkbox", False, type=bool))
        self.example_text.setText(settings.value("example_text", "", type=str))
        self.dir_temps_edit.setText(settings.value("dir_temps", DIR_TEMPS, type=str))
        self.dir_caches_edit.setText(cache_dir())
        self.load_mode_combo.setCurrentIndex(self.load_mode_combo.findData(read_load_mode(settings)))
        self.simultaneous_io_spin.setValue(read_io_concurrency(settings))
        self.check_level_combo.setCurrentIndex(self.check_level_combo.findData(read_check_level(settings)))
        self.live_interval_spin.setValue(read_live_interval(settings))
        self.auto_scan_visible_checkbox.setChecked(settings.value(AUTO_SCAN_VISIBLE_SETTING, False, type=bool))
        logging.debug("Settings loaded")

    def save_settings(self) -> None:
        applied = self.cache_tab.apply_budget()
        if applied is None:
            # Saved once the store has the new disk budget.
            self.save_button.setEnabled(False)
            self.reset_button.setEnabled(False)
        elif applied:
            self._write_settings()
        else:
            # Declined, or it couldn't be queued: save nothing, stay open.
            self.tabs.setCurrentWidget(self.cache_tab)

    def _budget_applied(self, applied: bool) -> None:
        self.save_button.setEnabled(True)
        self.reset_button.setEnabled(True)
        if applied:
            self._write_settings()
        else:
            self.tabs.setCurrentWidget(self.cache_tab)

    def _write_settings(self) -> None:
        settings = self.settings
        settings.setValue("example_checkbox", self.example_checkbox.isChecked())
        settings.setValue("example_text", self.example_text.text())
        settings.setValue("dir_temps", self.dir_temps_edit.text())
        settings.setValue(LOAD_MODE_SETTING, self.load_mode_combo.currentData())
        settings.setValue(SIMULTANEOUS_IO_SETTING, self.simultaneous_io_spin.value())
        settings.setValue(CHECK_LEVEL_SETTING, self.check_level_combo.currentData())
        settings.setValue(LIVE_INTERVAL_SETTING, self.live_interval_spin.value())
        settings.remove("simultaneous_folder_scans")
        settings.remove("simultaneous_folder_loads")
        settings.setValue(AUTO_SCAN_VISIBLE_SETTING, self.auto_scan_visible_checkbox.isChecked())
        self.cache_tab.save(settings)
        self.accept()
        logging.debug("Settings saved")

    def closeEvent(self, a0: QCloseEvent|None) -> None:
        # self.save_settings()
        # TODO warning box if unsaved changes


        logging.warning("Settings dialog closed")
        super().closeEvent(a0)
        self.deleteLater()

    def reset_settings(self) -> None:
        if not self.cache_tab.confirm(
                "Reset all settings?",
                "Resets every HeLab setting to its default: folders, load options, both cache budgets, window "
                "and view choices. The disk cache's contents are kept.", "Reset all settings"):
            return
        settings = self.settings
        # Where the disk cache is isn't a preference: it stays (moving it is Change…).
        caches = settings.value("dir_caches", type=str)
        settings.clear()
        if caches:
            settings.setValue("dir_caches", caches)
        self.load_settings()
        self.cache_tab.disk_budget.setValue(read_disk_budget(settings) / (1 << 30))
        self.cache_tab.ram_budget.setValue(read_ram_budget_steps(settings, self.cache_tab.ram_budget.total))
        self.cache_tab.live_autosave.setValue(read_live_autosave(settings))
        self.cache_tab.plot_auto_reload.setChecked(read_plot_auto_reload(settings))
        logging.debug("Settings reset to default")
