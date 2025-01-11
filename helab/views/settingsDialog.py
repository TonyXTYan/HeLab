# settingsDialog.py
import logging
import sys
from re import S
from typing import Optional, Dict, Any

from PyQt6.QtGui import QCloseEvent, QDesktopServices
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox, QLineEdit, QLabel, QTabWidget, \
    QWidget, QComboBox, QFormLayout, QScrollArea, QSpinBox, QFileDialog, QSpacerItem
from PyQt6.QtCore import QSettings, QUrl
from diskcache import FanoutCache

from helab.utils.cachingSetup import *
from helab.utils.constants import *


class SettingsDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
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
        self.dir_temps_reset_btn.clicked.connect(lambda: self.dir_temps_edit.setText(get_path_from_setting_or_use_default("dir_temps", DIR_TEMPS_CANDIDATES)))
        self.dir_caches_reset_btn.clicked.connect(lambda: self.dir_caches_edit.setText(get_path_from_setting_or_use_default("dir_caches", DIR_CACHES_CANDIDATES)))



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
        # Cache Tab
        self.cache_tab = QWidget()
        self.cache_layout = QVBoxLayout(self.cache_tab)

        self.cache_widgets = []
        self.cache_params_ui: Dict[str, Dict[str, Any]] = {}

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        experimental_label = QLabel(
            "Warning: Changing these settings may cause unexpected behaviour. \n"
            "To change the cache settings, please edit in the raw .py file.")
        experimental_label.setWordWrap(True)
        scroll_layout.addWidget(experimental_label)


        force_save_button = QPushButton("Force Save Cache to Disk")
        force_save_button.clicked.connect(self.save_cache_to_disk)
        scroll_layout.addWidget(force_save_button)

        clear_all_button = QPushButton("Clear All Caches")
        clear_all_button.clicked.connect(self.clear_all_caches)
        scroll_layout.addWidget(clear_all_button)

        for cache_name, cache in caches.items():
            cache_widget = QWidget()
            cache_layout = QHBoxLayout(cache_widget)

            # cache_label = QLabel(f"<b>{cache_name}</b>")
            cache_label = QLabel(cache_name)
            cache_label.setStyleSheet("font-weight: bold")
            cache_layout.addWidget(cache_label)

            cache_hits_label = QLabel()
            cache_layout.addWidget(cache_hits_label)

            cache_miss_label = QLabel()
            cache_layout.addWidget(cache_miss_label)

            cache_size_label = QLabel()
            cache_layout.addWidget(cache_size_label)

            clear_button = QPushButton("Clear Cache")
            clear_button.clicked.connect(lambda _, c=cache: self.clear_cache(c))
            cache_layout.addWidget(clear_button)

            # # logging.debug(f"Cache: {cache_name}, {sys.getsizeof(cache)}")
            # connection = cache._sql
            # ram_usage = connection.execeute("PRAGMA cache_size").fetchone()[0]
            # ram_highwater = connection.execeute("PRAGMA memory_highwater").fetchone()[0]
            # logging.debug(f"Cache: {cache_name}, {ram_usage = }, {ram_highwater = }")

            # hits, miss = cache.stats()

            self.cache_widgets.append({
                'cache_name': cache_name,
                'cache': cache,
                'hits_label': cache_hits_label,
                'miss_label': cache_miss_label,
                'size_label': cache_size_label,
            })
            scroll_layout.addWidget(cache_widget)


            form_widget = QWidget()
            form_layout = QFormLayout(form_widget)

            # form_layout.addRow(QLabel(f"<b>{cache_name}</b>"), QLabel(""))
            self.cache_params_ui[cache_name] = {}
            param_keys = CACHE_PARAMS_DEFAULTS.keys()
            existing_params = load_cache_param(cache_name)
            for pkey in param_keys:
                lbl = QLabel(pkey)
                if pkey == "statistics":
                    pass
                elif pkey == "sqlite_journal_mode":
                    cb = QComboBox()
                    modes = [
                        "delete",
                        "truncate",
                        "persist",
                        "memory",
                        "wal",
                        "off"
                    ]
                    cb.addItems(modes)
                    idx = cb.findText(str(existing_params[pkey]))
                    if idx >= 0:
                        cb.setCurrentIndex(idx)
                    form_layout.addRow(lbl, cb)
                    self.cache_params_ui[cache_name][pkey] = cb
                elif pkey == "eviction_policy":
                    # example: a combo box for known policies
                    cb = QComboBox()
                    policies = [
                        "least-recently-stored",
                        "least-recently-used",
                        "least-frequently-used",
                        "none"
                    ]
                    cb.addItems(policies)
                    idx = cb.findText(str(existing_params[pkey]))
                    if idx >= 0:
                        cb.setCurrentIndex(idx)
                    form_layout.addRow(lbl, cb)
                    self.cache_params_ui[cache_name][pkey] = cb
                else:
                    # # Use a line edit for numeric/bool/string
                    # le = QLineEdit(str(existing_params[pkey]))
                    # form_layout.addRow(lbl, le)
                    # self.cache_params_ui[cache_name][pkey] = le
                    number_filed = QSpinBox()
                    number_filed.setMaximum(1<<14)
                    # number_filed.setValue(existing_params[pkey])

                     # Auto-select unit for the existing value
                    size_in_bytes = existing_params[pkey]

                    units = ["B", "KB", "MB", "GB", "TB"] if pkey != "sqlite_cache_size" else ["I", "K", "M", "G", "T"]

                    unit_idx = 0
                    while size_in_bytes >= 1024 and unit_idx < len(units) - 1:
                        size_in_bytes >>= 10
                        unit_idx += 1
                    if (unit_idx >= 3 and size_in_bytes > 100) or unit_idx >= 4:
                        logging.warning(f"Cache {cache_name} param {pkey} is large: {size_in_bytes} {units[unit_idx]}")

                    number_filed.setValue(size_in_bytes)
                    unit_selector = QComboBox()
                    unit_selector.addItems(units)
                    unit_selector.setCurrentIndex(unit_idx)

                    unit_layout = QHBoxLayout()
                    unit_layout.addWidget(number_filed)
                    unit_layout.addWidget(unit_selector)

                    unit_widget = QWidget()
                    unit_widget.setLayout(unit_layout)
                    form_layout.addRow(lbl, unit_widget)
                    self.cache_params_ui[cache_name][pkey] = (number_filed, unit_selector)

            # self.cache_layout.addWidget(form_widget)
            # self.cache_layout.addWidget(cache_widget)

            scroll_layout.addWidget(form_widget)
            form_widget.setEnabled(False)

        scroll_area.setWidget(scroll_content)
        self.cache_layout.addWidget(scroll_area)
        # self.cache_layout.addWidget(clear_all_button)
        self.tabs.addTab(self.cache_tab, "Cache")
        self.update_cache_info()

    def browse_dir_temps(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select DIR_TEMPS Folder")
        if folder:
            self.dir_temps_edit.setText(folder)

    def browse_dir_caches(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select DIR_CACHES Folder")
        if folder:
            self.dir_caches_edit.setText(folder)

    def save_cache_to_disk(self) -> None:
        for cache_info in self.cache_widgets:
            cache = cache_info['cache']
            cache.close()
        self.update_cache_info()


    def load_settings(self) -> None:
        settings = QSettings("ANU", "HeLab")
        self.example_checkbox.setChecked(settings.value("example_checkbox", False, type=bool))
        self.example_text.setText(settings.value("example_text", "", type=str))
        self.dir_temps_edit.setText(settings.value("dir_temps", DIR_TEMPS, type=str))
        self.dir_caches_edit.setText(settings.value("dir_caches", DIR_CACHES, type=str))
        logging.debug("Settings loaded")

    def save_settings(self) -> None:
        settings = QSettings("ANU", "HeLab")
        settings.setValue("example_checkbox", self.example_checkbox.isChecked())
        settings.setValue("example_text", self.example_text.text())
        settings.setValue("dir_temps", self.dir_temps_edit.text())
        settings.setValue("dir_caches", self.dir_caches_edit.text())

        # Save DiskCache parameters overrides
        for cache_name, param_widgets in self.cache_params_ui.items():
            for param_key, widget in param_widgets.items():
                setting_path = f"diskcache/{cache_name}/{param_key}"
                default_val = CACHE_PARAMS_DEFAULTS[param_key]

                # If it's a combo
                if isinstance(widget, QComboBox):
                    val_str = widget.currentText()
                    settings.setValue(setting_path, val_str)

                # If it's a line edit
                elif isinstance(widget, QLineEdit):
                    text_val = widget.text().strip()
                    if isinstance(default_val, bool):
                        val = text_val.lower() in ("true", "1", "yes")
                    elif isinstance(default_val, int):
                        try:
                            val = int(text_val) # type: ignore
                        except ValueError:
                            val = default_val   # type: ignore
                    else:
                        val = text_val # type: ignore   #TODO: FIXME: TYPING ERROR
                    settings.setValue(setting_path, val)

                # Handle (QSpinBox, QComboBox) tuple
                elif isinstance(widget, tuple) and len(widget) == 2:
                    number_filed, unit_selector = widget
                    base_val = number_filed.value()
                    unit = unit_selector.currentText()
                    if param_key != "sqlite_cache_size":
                        factors = ["B", "KB", "MB", "GB", "TB"]
                    else:
                        factors = ["I", "K", "M", "G", "T"]

                    factor_idx = factors.index(unit)
                    for _ in range(factor_idx):
                        base_val <<= 10
                    settings.setValue(setting_path, base_val)


        self.accept()
        logging.debug("Settings saved")

    def clear_cache(self, cache: FanoutCache) -> None:
        cache.clear()
        self.update_cache_info()

    def clear_all_caches(self) -> None:
        for cache_info in self.cache_widgets:
            cache_info['cache'].clear()
        self.update_cache_info()

    def update_cache_info(self) -> None:
        for cache_info in self.cache_widgets:
            cache = cache_info['cache']
            size_label = cache_info['size_label']
            hits_label = cache_info['hits_label']
            miss_label = cache_info['miss_label']
            hits, miss = cache.stats()
            hits_label.setText(f"Hits: {fnum(hits)}")
            miss_label.setText(f"Miss: {fnum(miss)}")
            size_label.setText(f"Size: {fnum(cache.volume())}B")


    def closeEvent(self, a0: QCloseEvent|None) -> None:
        # self.save_settings()
        # TODO warning box if unsaved changes


        logging.warning("Settings dialog closed")
        super().closeEvent(a0)
        self.deleteLater()

    def reset_settings(self) -> None:
        settings = QSettings("ANU", "HeLab")
        settings.clear()
        self.load_settings()
        logging.debug("Settings reset to default")