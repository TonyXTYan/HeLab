# settingsDialog.py
import logging
from re import S
from typing import Optional

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox, QLineEdit, QLabel, QTabWidget, QWidget
from PyQt6.QtCore import QSettings
from diskcache import FanoutCache

from helab.utils.cachingSetup import *


class SettingsDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(800, 400)
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

        self.tabs.addTab(self.general_tab, "General")


        # TODO: default load folder


        # Scripts Tab
        self.scripts_tab = QWidget()
        self.scripts_layout = QVBoxLayout(self.scripts_tab)
        self.scripts_layout.addWidget(QLabel("Scripts Settings"))
        self.tabs.addTab(self.scripts_tab, "Scripts")


        # Cache Tab
        self.cache_tab = QWidget()
        self.cache_layout = QVBoxLayout(self.cache_tab)
        self.cache_layout.addWidget(QLabel("Cache Settings"))
        self.tabs.addTab(self.cache_tab, "Cache")



        # Placeholder tab
        self.placeholder_tab = QWidget()
        self.placeholder_layout = QVBoxLayout(self.placeholder_tab)
        self.placeholder_layout.addWidget(QLabel("Placeholder text for the second tab"))

        self.tabs.addTab(self.placeholder_tab, "Placeholder")


        # Buttons
        self.button_layout = QHBoxLayout()
        self.save_button = QPushButton("Save")
        self.cancel_button = QPushButton("Cancel")
        self.button_layout.addWidget(self.save_button)
        self.button_layout.addWidget(self.cancel_button)
        self.main_layout.addLayout(self.button_layout)

        self.save_button.clicked.connect(self.save_settings)
        self.cancel_button.clicked.connect(self.reject)

        self.load_settings()

        # self.main_layout.setStretch(0, 1)
        # self.main_layout.setStretch(1, 0)


        # Cache Tab
        self.cache_tab = QWidget()
        self.cache_layout = QVBoxLayout(self.cache_tab)

        self.caches = [
            ('os_listdir_cache', os_listdir_cache),
            ('os_scandir_cache', os_scandir_cache),
            ('os_isdir_cache', os_isdir_cache),
            ('status_cache', status_cache),
            ('hasChildren_cache', hasChildren_cache),
        ]

        self.cache_widgets = []

        for cache_name, cache in self.caches:
            cache_widget = QWidget()
            cache_layout = QHBoxLayout(cache_widget)

            cache_label = QLabel(cache_name)
            cache_layout.addWidget(cache_label)

            cache_size_label = QLabel()
            cache_layout.addWidget(cache_size_label)

            clear_button = QPushButton("Clear Cache")
            clear_button.clicked.connect(lambda _, c=cache: self.clear_cache(c))
            cache_layout.addWidget(clear_button)

            self.cache_widgets.append({
                'cache_name': cache_name,
                'cache': cache,
                'size_label': cache_size_label,
            })

            self.cache_layout.addWidget(cache_widget)

        clear_all_button = QPushButton("Clear All Caches")
        clear_all_button.clicked.connect(self.clear_all_caches)
        self.cache_layout.addWidget(clear_all_button)

        self.tabs.addTab(self.cache_tab, "Cache")

        self.update_cache_info()


    def load_settings(self) -> None:
        settings = QSettings("ANU", "HeLab")
        self.example_checkbox.setChecked(settings.value("example_checkbox", False, type=bool))
        self.example_text.setText(settings.value("example_text", "", type=str))
        logging.debug("Settings loaded")

    def save_settings(self) -> None:
        settings = QSettings("ANU", "HeLab")
        settings.setValue("example_checkbox", self.example_checkbox.isChecked())
        settings.setValue("example_text", self.example_text.text())
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
            cache_size_MB = cache.volume() / 1000 / 1000  # MB
            size_label.setText(f"Size: {cache_size_MB:<6.2f} MB")