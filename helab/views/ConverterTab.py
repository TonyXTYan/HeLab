"""Settings → TXY converter: which detector profile, backend and output HeLab's conversions use, and
the profile manager (Q6.11).

The built-in profiles (``helab.convert.profile``: ``matlab-2019``, the default; ``matlab-2023-lab-edit``;
the plate profiles, ``plates-2025`` marked uncalibrated) are read-only; the user's are JSON files in the
app folder (``helab.convert.user_profiles``, ``constants.profiles_folder``). Any profile can be
duplicated, exported, and a user profile edited (a form over ``DetectorProfile``'s fields, with its
validation and content hash), imported or deleted (asked first: nothing is removed without asking).
The profile, backend and output are saved with the dialog's Save; profile files are written at once.
"""
from __future__ import annotations

import dataclasses
import logging
import os
from typing import Any, Optional

from PyQt6.QtCore import QSettings, Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout,
    QWidget,
)

from helab.convert.profile import (BUILTIN_PROFILES, CANDIDATE_HANDLING, DEFAULT_PROFILE, PLATE_SWAPS, POSITION_FORMULAS,
                                   UNCALIBRATED, DetectorProfile, ProfileError, file_tag)
from helab.convert.user_profiles import ProfileLibrary, Unreadable, check_name, duplicate
from helab.utils import txy_sources
from helab.utils.colours import AMBER
from helab.utils.constants import (
    CONVERT_BACKEND_SETTING, CONVERT_OUTPUT_SETTING, CONVERT_PROFILE_SETTING, TXY_SOURCE_SETTING, profiles_folder,
    read_convert_backend, read_convert_output, read_txy_source,
)
from helab.utils.folder_cache import FolderCache
from helab.utils.settings_defaults import CONVERT_OUTPUTS, read_setting

# Backends by name (``reconstruct._MODULES``), without importing them: whether one can run here is the
# conversion's to say (an optional package or compiled extension may be missing).
BACKEND_NOTES = {"numpy": "numpy (default; always available)", "reference": "reference (plain Python, slow)",
                 "rust": "rust (optional, compiled)", "cython": "cython (optional, compiled)",
                 "numba": "numba (optional)", "mlx": "mlx (optional; Apple GPU)"}
OUTPUT_LABELS = {"cache": "The disk cache's folder (by the folder's data root; else temp)",
                 "temp": "HeLab's temp folder"}
CHOICE_FIELDS = {"x2_handling": CANDIDATE_HANDLING, "y_handling": CANDIDATE_HANDLING,
                 "position_formula": POSITION_FORMULAS}


def plate_dates() -> dict[str, str]:
    return {name: since for since, name in PLATE_SWAPS}


def profile_label(profile: DetectorProfile, builtin: bool) -> str:
    marks = ["built in" if builtin else "yours"]
    if profile.name in UNCALIBRATED:
        marks.append("uncalibrated")
    elif profile.calibrated:
        marks.append("calibrated")
    if profile.name == DEFAULT_PROFILE:
        marks.append("default")
    return f"{profile.name} v{profile.version} · {' · '.join(marks)} · {profile.content_hash()[:12]}"


class ProfileEditor(QDialog):
    """A form over every ``DetectorProfile`` field (its name fixed), validated as the profile is: Save is
    possible only for a valid profile; the content hash updates as values change. A change of output
    bumps the version (the provenance tells profiles apart by name, version and hash)."""

    def __init__(self, profile: DetectorProfile, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit profile {profile.name}")
        self.original = profile
        self.result_profile: Optional[DetectorProfile] = None
        self.editors: dict[str, QWidget] = {}
        layout = QVBoxLayout(self)
        form = QFormLayout()
        inner = QWidget()
        inner.setLayout(form)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)
        for field in dataclasses.fields(DetectorProfile):
            value = getattr(profile, field.name)
            editor: QWidget
            if field.name == "name":
                editor = QLabel(profile.name)
            elif field.name == "tag":
                editor = QLabel()  # (Set by _check: a user profile is tagged by its hash.)
            elif field.name in CHOICE_FIELDS:
                combo = QComboBox()
                combo.addItems(list(CHOICE_FIELDS[field.name]))
                combo.setCurrentText(str(value))
                combo.currentIndexChanged.connect(self._check)
                editor = combo
            elif field.type == "bool":
                box = QCheckBox()
                box.setChecked(bool(value))
                box.toggled.connect(self._check)
                editor = box
            elif field.type == "int":
                spin = QSpinBox()
                spin.setRange(-1_000_000, 1_000_000)
                spin.setValue(int(value))
                spin.valueChanged.connect(self._check)
                editor = spin
            else:
                line = QLineEdit(repr(value) if field.type == "float" else str(value))
                line.textChanged.connect(self._check)
                editor = line
            self.editors[field.name] = editor
            form.addRow(field.name, editor)
        self.hash_label = QLabel()
        self.hash_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.problem = QLabel()
        self.problem.setStyleSheet(f"color: {AMBER}")
        self.problem.setWordWrap(True)
        layout.addWidget(self.hash_label)
        layout.addWidget(self.problem)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept_profile)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.resize(560, 640)
        self._check()

    def values(self) -> dict[str, Any]:
        values: dict[str, Any] = {"name": self.original.name}
        for field in dataclasses.fields(DetectorProfile):
            editor = self.editors[field.name]
            if field.name in ("name", "tag"):
                continue
            if isinstance(editor, QComboBox):
                values[field.name] = editor.currentText()
            elif isinstance(editor, QCheckBox):
                values[field.name] = editor.isChecked()
            elif isinstance(editor, QSpinBox):
                values[field.name] = editor.value()
            elif isinstance(editor, QLineEdit):
                text = editor.text().strip()
                if field.type == "float":
                    try:
                        values[field.name] = float(text)
                    except ValueError:
                        raise ProfileError(f"{field.name} must be a number, not {text!r}") from None
                else:
                    values[field.name] = editor.text()
        return values

    def profile(self) -> DetectorProfile:
        """The profile as the form has it (``ProfileError`` if it isn't valid), its version bumped when its
        output changed and the version wasn't."""
        profile = DetectorProfile(**self.values())
        if profile.content_hash() != self.original.content_hash() and profile.version == self.original.version:
            profile = profile.replace(version=profile.version + 1)
        return profile

    def _check(self) -> None:
        save = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        try:
            profile = self.profile()
        except ProfileError as error:
            self.problem.setText(str(error))
            self.hash_label.setText("Content hash: (not valid)")
            if save is not None:
                save.setEnabled(False)
            return
        changed = profile.content_hash() != self.original.content_hash()
        tag = self.editors["tag"]
        if isinstance(tag, QLabel):
            tag.setText(f"{file_tag(profile)} (from the content hash: d_txy_helab_{file_tag(profile)}_<N>.txt)")
        self.problem.setText("")
        self.hash_label.setText(f"Content hash: {profile.content_hash()}" + (
            f" (output changed: saved as v{profile.version})" if changed else " (same output)"))
        if save is not None:
            save.setEnabled(True)

    def accept_profile(self) -> None:
        try:
            self.result_profile = self.profile()
        except ProfileError as error:
            self.problem.setText(str(error))
            return
        self.accept()


class ConverterTab(QWidget):
    def __init__(self, cache: Optional[FolderCache], settings: QSettings, parent: Optional[QWidget] = None,
                 folder: Optional[str] = None) -> None:
        super().__init__(parent)
        self.cache = cache
        self.settings = settings
        self.library = ProfileLibrary(folder or profiles_folder())
        self.user: dict[str, DetectorProfile] = {}
        self.unreadable: list[Unreadable] = []
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        grid.addWidget(QLabel("Conversions use the profile"), 0, 0)
        self.profile_combo = QComboBox()
        self.profile_combo.setToolTip("The detector profile HeLab's conversions use. HeLab's TXY made with another "
                                      "profile's output aren't loaded until converted again.")
        grid.addWidget(self.profile_combo, 0, 1)
        grid.addWidget(QLabel("Backend"), 1, 0)
        self.backend_combo = QComboBox()
        for name, label in BACKEND_NOTES.items():
            self.backend_combo.addItem(label, name)
        self.backend_combo.setToolTip("Every backend writes the same TXY byte for byte; an optional one that "
                                      "can't run here makes the conversion say why.")
        grid.addWidget(self.backend_combo, 1, 1)
        grid.addWidget(QLabel("HeLab's TXY go to"), 2, 0)
        self.output_combo = QComboBox()
        for name in CONVERT_OUTPUTS:
            self.output_combo.addItem(OUTPUT_LABELS[name], name)
        self.output_combo.setToolTip("Folders set to write them beside the raw files do that instead.")
        grid.addWidget(self.output_combo, 2, 1)
        grid.addWidget(QLabel("Tabs and Live read (when a folder loads again)"), 3, 0)
        self.source_combo = QComboBox()
        for name in txy_sources.SOURCES:
            self.source_combo.addItem(txy_sources.LABELS[name], name)
        self.source_combo.setToolTip("Which TXY a folder's tab and Live load (Q18.2): HeLab's are those of the "
                                     "profile conversions use (its tag in their names). A change applies when a "
                                     "folder loads again (Refresh, or selecting it again): the data a tab shows "
                                     "now stays until then, and a load already running finishes first. A plot "
                                     "can choose another source or profile in its settings.")
        grid.addWidget(self.source_combo, 3, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        profiles_label = QLabel("Profiles (changes to profiles are saved at once; the choices above with Save)")
        layout.addWidget(profiles_label)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._selected)
        layout.addWidget(self.list, 1)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.details)
        buttons = QHBoxLayout()
        self.duplicate_button = QPushButton("Duplicate…")
        self.edit_button = QPushButton("Edit…")
        self.delete_button = QPushButton("Delete…")
        self.import_button = QPushButton("Import…")
        self.export_button = QPushButton("Export…")
        self.folder_button = QPushButton("Show folder")
        for button, slot in ((self.duplicate_button, self.duplicate_selected), (self.edit_button, self.edit_selected),
                             (self.delete_button, self.delete_selected), (self.import_button, self.import_file),
                             (self.export_button, self.export_selected), (self.folder_button, self.show_folder)):
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.refresh(read_setting(settings, CONVERT_PROFILE_SETTING, typed=True) or DEFAULT_PROFILE)
        self.backend_combo.setCurrentIndex(max(0, self.backend_combo.findData(read_convert_backend(settings))))
        self.output_combo.setCurrentIndex(max(0, self.output_combo.findData(read_convert_output(settings))))
        self.source_combo.setCurrentIndex(max(0, self.source_combo.findData(read_txy_source(settings))))

    # The list

    def profiles(self) -> dict[str, DetectorProfile]:
        return {**dict(BUILTIN_PROFILES), **self.user}

    def refresh(self, chosen: str = "", select: str = "") -> None:
        """Read the user's profiles again; keep (or set) the profile conversions use and the selection."""
        chosen = chosen or str(self.profile_combo.currentData() or DEFAULT_PROFILE)
        select = select or (self.selected() or "")
        found, self.unreadable = self.library.scan()
        self.user = {entry.profile.name: entry.profile for entry in found}
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for name, profile in self.profiles().items():
            self.profile_combo.addItem(f"{name} v{profile.version}" + (" (uncalibrated)" if name in UNCALIBRATED
                                                                       else ""), name)
        missing = chosen not in self.profiles()
        if missing:
            self.profile_combo.addItem(f"{chosen} (not found: conversions use {DEFAULT_PROFILE})", chosen)
        self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(chosen)))
        self.profile_combo.blockSignals(False)
        self.list.clear()
        for name, profile in self.profiles().items():
            item = QListWidgetItem(profile_label(profile, name in BUILTIN_PROFILES))
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(item)
            if name == select:
                self.list.setCurrentItem(item)
        for entry in self.unreadable:
            item = QListWidgetItem(f"⚠ {os.path.basename(entry.file)}: {entry.reason}")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setToolTip(entry.file)
            self.list.addItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._selected()

    def selected(self) -> Optional[str]:
        item = self.list.currentItem()
        name = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return str(name) if name else None

    def _selected(self, *_: Any) -> None:
        name = self.selected()
        profile = self.profiles().get(name or "")
        builtin = name in BUILTIN_PROFILES
        self.edit_button.setEnabled(profile is not None and not builtin)
        self.delete_button.setEnabled(profile is not None and not builtin)
        self.duplicate_button.setEnabled(profile is not None)
        self.export_button.setEnabled(profile is not None)
        if profile is None:
            self.details.setText("")
            return
        since = plate_dates().get(profile.name)
        file = "" if builtin else f"\nFile: {self.library.file_for(profile.name)}"
        self.details.setText(
            f"{profile.notes}\n" + (f"Plates in since {since}.\n" if since else "")
            + f"Content hash: {profile.content_hash()}\nTXY files: d_txy_helab_{file_tag(profile)}_<N>.txt" + file)

    # Actions (each writes its file at once; every removal asks first)

    def confirm(self, title: str, text: str, verb: str) -> bool:
        box = QMessageBox(QMessageBox.Icon.Warning, title, text, parent=self)
        accept = box.addButton(verb, QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return box.clickedButton() is accept

    def ask_name(self, title: str, suggestion: str) -> Optional[str]:
        """A name for a new user profile (None: cancelled); asked again until it is usable or free."""
        name = suggestion
        while True:
            text, ok = QInputDialog.getText(self, title, "Profile name:", text=name)
            if not ok:
                return None
            name = text.strip()
            problem = check_name(name) or (f"A profile named {name!r} exists already"
                                           if self.library.exists(name) else None)
            if problem is None:
                return name
            self.say(problem)

    def say(self, text: str) -> None:
        QMessageBox.information(self, "TXY converter", text)

    def edit(self, profile: DetectorProfile) -> Optional[DetectorProfile]:
        editor = ProfileEditor(profile, self)
        return editor.result_profile if editor.exec() == QDialog.DialogCode.Accepted else None

    def duplicate_selected(self) -> None:
        profile = self.profiles().get(self.selected() or "")
        if profile is None:
            return
        name = self.ask_name("Duplicate profile", self.library.free_name(f"{profile.name}-copy"))
        if name is None:
            return
        self._save(duplicate(profile, name), select=name)

    def edit_selected(self) -> None:
        name = self.selected()
        profile = self.user.get(name or "")
        if profile is None:
            return
        changed = self.edit(profile)
        if changed is not None and changed != profile:
            self._save(changed, replace=True, select=changed.name)

    def delete_selected(self) -> None:
        name = self.selected()
        if name is None or name not in self.user:
            return
        in_use = name == self.profile_combo.currentData()
        if not self.confirm("Delete this profile?",
                            f"Deletes {self.library.file_for(name)}." + (
                                f" Conversions use it now: they will use {DEFAULT_PROFILE} instead." if in_use
                                else "") + " HeLab's TXY made with it stay; they are loaded only while their "
                            "output's profile is the one conversions use.", "Delete"):
            return
        try:
            self.library.delete(name)
        except OSError as error:
            self.say(f"Couldn't delete {name}: {error}")
            return
        if in_use:
            # Deleted at once, so the setting follows at once (not with Save): it never names a deleted profile.
            self.settings.setValue(CONVERT_PROFILE_SETTING, DEFAULT_PROFILE)
            if self.cache is not None:
                self.cache.set_convert_profile(BUILTIN_PROFILES[DEFAULT_PROFILE])
        self.refresh(DEFAULT_PROFILE if in_use else "")

    def import_file(self, path: str = "") -> None:
        path = path or QFileDialog.getOpenFileName(self, "Import a detector profile", "", "Profiles (*.json)")[0]
        if not path:
            return
        try:
            profile = self.library.read_file(path)
        except ProfileError as error:
            self.say(f"Not imported: {error}")
            return
        name = profile.name
        if check_name(name) is not None or self.library.exists(name):
            asked = self.ask_name("Import profile: choose a name", self.library.free_name(name))
            if asked is None:
                return
            name = asked
        self._save(profile.replace(name=name), select=name)

    def export_selected(self, path: str = "") -> None:
        profile = self.profiles().get(self.selected() or "")
        if profile is None:
            return
        path = path or QFileDialog.getSaveFileName(self, "Export the profile", f"{profile.name}.json",
                                                   "Profiles (*.json)")[0]
        if not path:
            return
        try:
            self.library.export(profile, path)
        except OSError as error:
            self.say(f"Couldn't export {profile.name}: {error}")

    def show_folder(self) -> None:
        os.makedirs(self.library.folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.library.folder))

    def _save(self, profile: DetectorProfile, *, replace: bool = False, select: str = "") -> None:
        try:
            self.library.save(profile, replace=replace)
        except (ProfileError, OSError) as error:
            self.say(f"Not saved: {error}")
            return
        logging.info("Detector profile %s v%d saved (%s)", profile.name, profile.version, profile.content_hash()[:12])
        self.refresh(select=select)
        if self.cache is not None and profile.name == self.profile_combo.currentData():
            self.cache.set_convert_profile(profile)  # (An edit of the profile in use: its new output now.)

    # Saved with the dialog

    def chosen_profile(self) -> DetectorProfile:
        return self.profiles().get(str(self.profile_combo.currentData()), BUILTIN_PROFILES[DEFAULT_PROFILE])

    def save(self, settings: QSettings) -> None:
        name = str(self.profile_combo.currentData() or DEFAULT_PROFILE)
        settings.setValue(CONVERT_PROFILE_SETTING, name if name in self.profiles() else DEFAULT_PROFILE)
        settings.setValue(CONVERT_BACKEND_SETTING, self.backend_combo.currentData())
        settings.setValue(CONVERT_OUTPUT_SETTING, self.output_combo.currentData())
        source = str(self.source_combo.currentData() or txy_sources.DEFAULT_SOURCE)
        settings.setValue(TXY_SOURCE_SETTING, source)
        if self.cache is not None:
            self.cache.set_convert_profile(self.chosen_profile())
            self.cache.set_tab_source(source)


__all__ = ["ConverterTab", "ProfileEditor", "plate_dates", "profile_label"]
