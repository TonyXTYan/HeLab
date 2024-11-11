# settingsDialog.py
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox, QLineEdit, QLabel, QTabWidget, QWidget
from PyQt6.QtCore import QSettings

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(400, 300)
        self.layout = QVBoxLayout(self)

        # Create tab widget
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)

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

        # Second tab
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
        self.layout.addLayout(self.button_layout)

        self.save_button.clicked.connect(self.save_settings)
        self.cancel_button.clicked.connect(self.reject)

        self.load_settings()

    def load_settings(self):
        settings = QSettings("ANU", "HeLab")
        self.example_checkbox.setChecked(settings.value("example_checkbox", False, type=bool))
        self.example_text.setText(settings.value("example_text", "", type=str))

    def save_settings(self):
        settings = QSettings("ANU", "HeLab")
        settings.setValue("example_checkbox", self.example_checkbox.isChecked())
        settings.setValue("example_text", self.example_text.text())
        self.accept()