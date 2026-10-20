"""Right-click › Folder constants…: the values a folder sets for the analyses (fall distance and
time, trap frequencies, release time and trap origin), kept in HeLab's store by the folder's data
root, never next to the data.

A folder's values apply to it and to its subfolders that don't set their own, up to its data
root (proposed, for Tony). Each row says where its value comes from now: this folder, a folder
above (inherited), the lab (Settings → Lab parameters), derived (the fall time), the table's
default, or "from the data" (the release time and trap origin, which plots detect unless set). A
folder without a disk cache keeps its values for this session only, and says so.

Memory only: what FolderCache knows; saving goes through a helper (``set_folder_constants``)."""
from __future__ import annotations

import math
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QGridLayout, QLabel, QLayout, QPushButton,
                             QVBoxLayout, QWidget)

from helab.analysis.constant_layers import folder_layer
from helab.analysis.parameter_tree import UnitSpinBox
from helab.analysis.physics import CONSTANTS, TABLE, Constant, ResolvedConstants, resolve
from helab.utils.folder_cache import FolderCache
from helab.utils.colours import AMBER as AMBER
from helab.views.LabParametersTab import UNCONFIRMED_TIP, constant_editor, name_label, number

FOLDER_ROWS: tuple[Constant, ...] = tuple(constant for constant in CONSTANTS if constant.level == "folder")
INHERITANCE_NOTE = ("A folder's values apply to it and to its subfolders that don't set their own, up to its "
                    "data root. Plots can still override any value in their own settings.")
DERIVED = "derived, √(2h/g)"
FROM_THE_DATA = "from the data (Release time plot)"


def short_name(path: str) -> str:
    return os.path.basename(path.rstrip(os.sep)) or path


class FolderConstantsDialog(QDialog):
    def __init__(self, path: str, cache: FolderCache, owner: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path, self.cache, self.owner = path, cache, owner
        self.setWindowTitle(f"Folder constants · {short_name(path)}")
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)  # Never smaller than its content.
        heading = QLabel(path)
        heading.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(heading)
        note = QLabel(INHERITANCE_NOTE)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.session_label = QLabel()
        self.session_label.setWordWrap(True)
        self.session_label.setStyleSheet(f"color: {AMBER};")
        layout.addWidget(self.session_label)
        grid = QGridLayout()
        grid.setColumnStretch(0, 1)
        self.set_here: dict[str, QCheckBox] = {}
        self.editors: dict[str, UnitSpinBox] = {}
        self.sources: dict[str, QLabel] = {}
        self.restore_buttons: dict[str, QPushButton] = {}
        own = cache.folder_constants(path)
        # Rows whose box holds a real value: the folder's own, or one typed since. An optional row
        # with nothing to start from (from the data) is saved only once typed (``untyped``).
        self._typed: set[str] = set(own)
        for row, constant in enumerate(FOLDER_ROWS):
            grid.addWidget(name_label(constant), row, 0)
            check = QCheckBox("Set by hand" if constant.key == "fall_time" else "Set here")
            check.setChecked(constant.key in own)
            check.setToolTip("Set the fall time by hand instead of deriving it, √(2h/g), from the fall distance"
                             if constant.key == "fall_time" else
                             "This folder's own value, instead of taking it from the data" if constant.optional
                             else "This folder's own value")
            self.set_here[constant.key] = check
            box = constant_editor(constant, own.get(constant.key, 1.0))
            box.sigValueChanged.connect(lambda *_, key=constant.key: self._typed.add(key))
            self.editors[constant.key] = box
            grid.addWidget(check, row, 1)
            grid.addWidget(box, row, 2)
            source = QLabel()
            self.sources[constant.key] = source
            grid.addWidget(source, row, 3)
            restore = QPushButton("Restore")
            restore.setToolTip("Use the value from the folder above, the lab or the default again")
            restore.clicked.connect(lambda _=False, key=constant.key: self.restore(key))
            self.restore_buttons[constant.key] = restore
            grid.addWidget(restore, row, 4)
        layout.addLayout(grid)
        self.notes_label = QLabel()
        self.notes_label.setWordWrap(True)
        self.notes_label.setStyleSheet(f"color: {AMBER};")
        layout.addWidget(self.notes_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update()
        for check in self.set_here.values():
            check.toggled.connect(lambda *_: self._update())
        for box in self.editors.values():
            box.sigValueChanged.connect(lambda *_: self._update())
        self.adjustSize()  # Sized to its content once the values (and their widths) are in.

    def _above(self) -> dict[str, tuple[float, str]]:
        """What the folder inherits: the nearest folder above it (never itself) setting each value."""
        parent = os.path.dirname(self.path)
        if parent == self.path or self.cache.constants_root(self.path) == self.path:
            return {}
        return self.cache.inherited_constants(parent)

    def values(self) -> dict[str, float]:
        """What this folder sets, as the dialog shows it (not a row still waiting for a value)."""
        waiting = self.untyped()
        return {key: number(self.editors[key]) for key, check in self.set_here.items()
                if check.isChecked() and key not in waiting}

    def untyped(self) -> list[str]:
        """Rows set here that have no value yet: optional ones (from the data) with nothing above to
        start from, not typed since, or a time still at 0. Save waits for them: 0 means nothing."""
        return [key for key, check in self.set_here.items()
                if check.isChecked() and TABLE[key].optional
                and (not TABLE[key].allows(number(self.editors[key]))
                     or (key not in self._typed and not self._resolved_without(key).is_set(key)))]

    def _resolved_without(self, key: str) -> ResolvedConstants:
        own = {other: (number(self.editors[other]), self.path) for other, check in self.set_here.items()
               if check.isChecked() and other != key and (not TABLE[other].optional or other in self._typed)
               and TABLE[other].allows(number(self.editors[other]))}
        return resolve(lab=self.cache.lab_constants, folder=folder_layer({**self._above(), **own}))

    def _found(self, without: str = "") -> dict[str, tuple[float, str]]:
        """Each value of the folder layer, with the folder setting it: this folder's (as the dialog
        shows them, but ``without``), else the nearest folder above's."""
        own = {key: (value, self.path) for key, value in self.values().items() if key != without}
        return {**self._above(), **own}

    def resolved(self, without: str = "") -> ResolvedConstants:
        """What a run on this folder would use with the dialog's values (no plot overrides)."""
        return resolve(lab=self.cache.lab_constants, folder=folder_layer(self._found(without)))

    def source_text(self, key: str) -> str:
        if self.set_here[key].isChecked():
            return "this folder"
        origin = self.resolved().origins[key]
        if origin == "folder":
            return f"inherited from {short_name(self._found()[key][1])}"
        if origin == "derived":
            return DERIVED
        if origin == "detected":
            return FROM_THE_DATA
        return "lab" if origin == "lab" else "default"

    def restore(self, key: str) -> None:
        self.set_here[key].setChecked(False)

    def _update(self) -> None:
        reason = self.cache.constants_session_only(self.path)
        self.session_label.setText(f"RAM only · kept for this session only: {reason}" if reason else "")
        self.session_label.setVisible(bool(reason))
        for key, check in self.set_here.items():
            box = self.editors[key]
            box.setEnabled(check.isChecked())
            if not check.isChecked():
                self._typed.discard(key)  # Checked again, it starts over.
                # The value it would have without this folder's own: what checking it starts from.
                # An optional row with no value (from the data) starts from 0.
                value = self.resolved(without=key).value(key)
                box.blockSignals(True)
                box.setValue(value if math.isfinite(value) else 0.0)
                box.blockSignals(False)
        resolved = self.resolved()
        for key, check in self.set_here.items():
            source = self.source_text(key)
            unconfirmed = key in resolved.unconfirmed
            label = self.sources[key]
            label.setText(f'{source} · <span style="color: {AMBER}">unconfirmed</span>' if unconfirmed else source)
            label.setToolTip(UNCONFIRMED_TIP if unconfirmed else "")
            self.restore_buttons[key].setEnabled(check.isChecked())
        waiting = self.untyped()
        notes = [*resolved.notes, *(f"Type a value for {TABLE[key].title} (it has none to start from), or clear Set "
                                    "here, to save" for key in waiting)]
        self.notes_label.setText("\n".join(f"⚠ {note}" for note in notes))
        self.notes_label.setVisible(bool(notes))
        if self.save_button is not None:
            self.save_button.setEnabled(not waiting)

    def save(self) -> None:
        if self.untyped():
            return
        self.cache.set_folder_constants(self.path, self.values(), owner=self.owner)
        self.accept()
