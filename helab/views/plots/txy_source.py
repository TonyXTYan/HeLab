"""A plot's TXY choice (Q6.6, Q18.2): which TXY its data is made of, in its settings page.

The sources (``txy_sources``): HeLab's where they exist with MATLAB's for the rest (the default for tabs
and Live), MATLAB's with HeLab's filling the shots MATLAB lacks, and HeLab's only or MATLAB's only for
comparing, one plot on each; and for HeLab's, the profile whose TXY are read, chosen by its tag (the
conversion profile's unless another is picked). "As the tab" follows the folder's tab (the setting in
Settings → TXY converter). A plot on another choice than the tab's loads its own dataset of the folder
(RAM only) through ``FolderCache`` and loads it again when Live finds new shots. The row also names the
profile HeLab converts with and, from the folder's date, the plate profile the swap dates suggest (Q6.10:
shown, never applied).
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from helab.analysis.dataset_view import DatasetView
from helab.convert.profile import BUILTIN_PROFILES, UNCALIBRATED, DetectorProfile, file_tag, suggested_plates
from helab.utils import txy_sources
from helab.utils.accessible import identify


def known_profiles() -> dict[str, DetectorProfile]:
    """The built-in and user profiles by name (a user profile folder that can't be read gives none)."""
    from helab.convert.user_profiles import ProfileLibrary
    from helab.utils.constants import profiles_folder
    try:
        user = ProfileLibrary(profiles_folder()).profiles()
    except OSError:
        user = {}
    return {**dict(BUILTIN_PROFILES), **user}


def profile_by_tag(tag: str) -> Optional[DetectorProfile]:
    """The known profile whose TXY carry ``tag`` (``profile.file_tag``), or None."""
    return next((profile for profile in known_profiles().values() if file_tag(profile) == tag), None)


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
    """``TXY: [source ▾] [profile ▾]`` and one line under it: the profile HeLab converts with, and a plate
    suggestion when there is one. ``changed`` is called with the source ("": as the tab) and the profile's
    name ("": the conversion profile's) chosen."""

    def __init__(self, source: str, changed: Callable[[str, str], None], profile: str = "",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._changed = changed
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("TXY:"))
        self.combo = identify(QComboBox(), "txy_source", "TXY source", "Which TXY this plot's data is made of")
        self.combo.addItem("As the folder's tab", "")
        for value in txy_sources.SOURCES:
            self.combo.addItem(txy_sources.LABELS[value], value)
        self.combo.setToolTip(
            "Which TXY this plot's data is made of (MATLAB's d_txy_forc, HeLab's d_txy_helab_<tag>). HeLab's only "
            "and MATLAB's only: one plot on each, to compare. As the folder's tab: the source tabs and Live read "
            "(Settings → TXY converter).")
        row.addWidget(self.combo, 2)
        self.profile_combo = identify(QComboBox(), "txy_profile", "TXY profile", "Whose HeLab TXY are read")
        self.profile_combo.setToolTip("Whose HeLab TXY are read: those of the profile HeLab converts with "
                                      "(Settings → TXY converter), or another's, by the tag in their names.")
        self.profile_combo.addItem("Conversion profile", "")
        for name, item in sorted(known_profiles().items()):
            self.profile_combo.addItem(f"{name} ({file_tag(item)})", name)
        row.addWidget(self.profile_combo, 1)
        layout.addLayout(row)
        self.note = identify(QLabel(), "txy_note")
        self.note.setWordWrap(False)
        layout.addWidget(self.note)
        self.set_source(source, profile)
        self.combo.currentIndexChanged.connect(self._picked)
        self.profile_combo.currentIndexChanged.connect(self._picked)

    def set_source(self, source: str, profile: str = "") -> None:
        for combo, value in ((self.combo, source), (self.profile_combo, profile)):
            index = combo.findData(value)
            if index < 0 and combo is self.profile_combo and value:
                combo.addItem(value, value)  # (A profile no longer listed: still named.)
                index = combo.findData(value)
            if index >= 0 and index != combo.currentIndex():
                combo.blockSignals(True)
                combo.setCurrentIndex(index)
                combo.blockSignals(False)
        self.profile_combo.setEnabled(self.source() != txy_sources.MATLAB_ONLY)

    def source(self) -> str:
        return str(self.combo.currentData() or "")

    def profile(self) -> str:
        return str(self.profile_combo.currentData() or "")

    def show_profile(self, view: DatasetView, profile_name: str) -> None:
        """One line: the profile, the data's TXY and a plate suggestion (detail in the tooltip)."""
        suggestion = plate_note(view, profile_name)
        self.note.setText(f"HeLab converts with {profile_name}" + (f" · {suggestion}" if suggestion else ""))
        self.note.setToolTip(f"{view.txy_text()}\nHeLab's TXY are read by their profile's tag (the profile "
                             f"chosen here, else the one HeLab converts with: {profile_name}; Settings → TXY "
                             "converter)."
                             + (f"\nThe plate swap dates suggest {suggestion}; it is not applied: choose it in "
                                "Settings → TXY converter to convert with it." if suggestion else ""))

    def _picked(self) -> None:
        self.profile_combo.setEnabled(self.source() != txy_sources.MATLAB_ONLY)
        self._changed(self.source(), self.profile())
