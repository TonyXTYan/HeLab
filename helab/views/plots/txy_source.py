"""A plot's TXY source (Q6.6): which TXY its data is made of, in its settings page.

The choices (``txy_sources``): MATLAB's with HeLab's filling the shots MATLAB lacks (the default: the
folder's tab data, which Live follows), HeLab's wherever they exist, and both as two datasets (MATLAB's
only, HeLab's only) for comparing, one plot on each. A plot on another source than the default loads
its own dataset of the folder (RAM only) through ``FolderCache`` and loads it again when Live finds new
shots. The row also names the profile HeLab converts with and, from the folder's date, the plate
profile the swap dates suggest (Q6.10: shown, never applied).
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from helab.analysis.dataset_view import DatasetView
from helab.convert.profile import UNCALIBRATED, suggested_plates
from helab.utils import txy_sources


def folder_day(view: DatasetView) -> str:
    """The folder's date (``YYYY-MM-DD``, local): its first shot's, "" when no shot has a time."""
    times = view.shot_times()
    return datetime.fromtimestamp(min(times.values())).strftime("%Y-%m-%d") if times else ""


def plate_note(view: DatasetView, profile_name: str) -> str:
    """``plates-2022 suggested for this folder's date (2023-02-04)`` when the swap dates suggest
    another profile than the one HeLab converts with; "" otherwise."""
    day = folder_day(view)
    suggested = suggested_plates(day) if day else None
    if suggested is None or suggested == profile_name:
        return ""
    return f"{suggested}{' (uncalibrated)' if suggested in UNCALIBRATED else ''} suggested for this folder's date ({day})"


class TxySourceRow(QWidget):
    """``TXY: [choice ▾]`` and one line under it: the profile HeLab converts with, and a plate
    suggestion when there is one. ``changed`` is called with the source chosen."""

    def __init__(self, source: str, changed: Callable[[str], None], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._changed = changed
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("TXY:"))
        self.combo = QComboBox()
        for value in txy_sources.SOURCES:
            self.combo.addItem(txy_sources.LABELS[value], value)
        self.combo.setToolTip(
            "Which TXY this plot's data is made of (MATLAB's d_txy_forc, HeLab's d_txy_helab). Both, as two "
            "datasets: one plot on MATLAB's, another on HeLab's, to compare. Only HeLab's TXY made with the "
            "profile HeLab converts with (Settings → TXY converter) are used.")
        row.addWidget(self.combo, 1)
        layout.addLayout(row)
        self.note = QLabel()
        self.note.setWordWrap(False)
        layout.addWidget(self.note)
        self.set_source(source)
        self.combo.currentIndexChanged.connect(self._picked)

    def set_source(self, source: str) -> None:
        index = self.combo.findData(source)
        if index >= 0 and index != self.combo.currentIndex():
            self.combo.blockSignals(True)
            self.combo.setCurrentIndex(index)
            self.combo.blockSignals(False)

    def source(self) -> str:
        return str(self.combo.currentData())

    def show_profile(self, view: DatasetView, profile_name: str) -> None:
        """One line: the profile, the data's TXY and a plate suggestion (detail in the tooltip)."""
        suggestion = plate_note(view, profile_name)
        self.note.setText(f"HeLab converts with {profile_name}" + (f" · {suggestion}" if suggestion else ""))
        self.note.setToolTip(f"{view.txy_text()}\nHeLab's TXY are loaded only when made with the profile HeLab "
                             f"converts with ({profile_name}; Settings → TXY converter)."
                             + (f"\nThe plate swap dates suggest {suggestion}; it is not applied: choose it in "
                                "Settings → TXY converter to convert with it." if suggestion else ""))

    def _picked(self) -> None:
        self._changed(self.source())
