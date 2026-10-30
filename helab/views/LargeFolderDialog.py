"""Asks before a deliberate load of a large folder (roadmap S8): the estimate, the RAM budget
and the computer's RAM, and a tick box that enables Load anyway."""
from __future__ import annotations

import os

from PyQt6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from helab.utils.number_format import byte_size


class LargeFolderDialog(QDialog):
    def __init__(self, path: str, estimate: int, ram_budget: int, total: int,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        name = os.path.basename(path.rstrip(os.sep)) or path
        self.setWindowTitle("Load a large folder?")
        layout = QVBoxLayout(self)
        self.text = QLabel(
            f"{name} would take about {byte_size(estimate, 'ram')} in RAM (its TXY files' size on disk).\n"
            f"RAM budget {byte_size(ram_budget, 'ram')} · this computer has {byte_size(total, 'ram')} of RAM.\n"
            "While it loads, HeLab may briefly use about 2–3× this.")
        self.text.setToolTip(path)
        layout.addWidget(self.text)
        self.understood = QCheckBox("I understand this may slow down or stop HeLab")
        layout.addWidget(self.understood)
        buttons = QDialogButtonBox()
        load_button = buttons.addButton("Load anyway", QDialogButtonBox.ButtonRole.AcceptRole)
        assert load_button is not None
        self.load_button = load_button
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.load_button.setEnabled(False)
        self.understood.toggled.connect(self.load_button.setEnabled)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def confirm_large(path: str, estimate: int, ram_budget: int, total: int, parent: QWidget | None = None) -> bool:
    return LargeFolderDialog(path, estimate, ram_budget, total, parent).exec() == QDialog.DialogCode.Accepted
