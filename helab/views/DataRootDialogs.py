"""Place .helab-root here…: the checks before writing a folder's marker, and the dialog that hands
out its exact contents when HeLab can't write it (data roots, D3)."""
from __future__ import annotations

import ntpath
import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog, QLabel, QMessageBox,
                             QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from helab.utils.folder_cache import PLACE_ROOT_ACTION, FolderCache, marker_path

TITLE = "Place .helab-root"
CONFIRM = ("HeLab will write a small hidden file, .helab-root, in {path}. Its subfolders will use the "
           "disk cache too. The folder's modified date changes once.")
NOT_TOP = ("This folder isn't the top of its drive or share ({top}). Place .helab-root as high up as "
           "possible, unless this folder is also shared on its own, so other computers see it as a top folder.")
NESTED = ("This folder is already inside data root “{label}” ({marker}). A .helab-root here gives it its "
          "own identity, and its subfolders' cached data moves to it.")
SYSTEM = ("This is a system or home folder: a .helab-root here would cover everything under it. "
          "Place it in a data folder instead.")
MANUAL_TITLE = "Place the data-root file manually"
MANUAL_TEXT = "HeLab can't write {name} in {folder} ({reason}).\nPut this file in {folder}, then Retry / Refresh that folder."


def _system_folders() -> set[str]:
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        drive = os.environ.get("SystemDrive", "C:") + "\\"
        return {ntpath.normcase(path) for path in (drive, ntpath.join(drive, "Users"), home)}
    return {"/", "/System/Volumes/Data", "/Users", "/home", "/Volumes", home}


def _system_mount(mount: str) -> bool:
    """A system volume's top can't take a marker (read-only, or needs admin): never suggest it."""
    if sys.platform == "win32":
        return ntpath.normcase(mount) == ntpath.normcase(os.environ.get("SystemDrive", "C:") + "\\")
    return mount in ("/", "/System/Volumes/Data", "/home")


def placement_checks(cache: FolderCache, path: str) -> tuple[str | None, list[str]]:
    """Before writing: the top of the folder's drive or share when it isn't that (to offer placing
    the marker there instead), and the warnings to show. Memory only."""
    warnings: list[str] = []
    normal = ntpath.normcase(path) if sys.platform == "win32" else path
    if normal in _system_folders():
        warnings.append(SYSTEM)
    top = cache.mount_of(path)
    if top is None or top == path or _system_mount(top):
        top = None
    else:
        warnings.append(NOT_TOP.format(top=top))
    if (root := cache.root_of(path)) is not None and root[0] != path:
        warnings.append(NESTED.format(label=root[2] or os.path.basename(root[0]), marker=marker_path(root[0])))
    return top, warnings


def ask_place_root(parent: QWidget | None, cache: FolderCache, path: str) -> str | None:
    """Confirm, with the checks' warnings: the folder to write the marker in, or None."""
    top, warnings = placement_checks(cache, path)
    box = QMessageBox(QMessageBox.Icon.Warning if warnings else QMessageBox.Icon.Question, TITLE,
                      CONFIRM.format(path=path), parent=parent)
    if warnings:
        box.setInformativeText("\n\n".join(warnings))
    at_top = box.addButton(f"Place at {top}", QMessageBox.ButtonRole.AcceptRole) if top else None
    here = box.addButton("Place here" if top else "Place .helab-root", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(at_top or here)
    box.exec()
    clicked = box.clickedButton()
    return top if clicked is at_top and top else path if clicked is here else None


class ManualMarkerDialog(QDialog):
    """No write permission: the exact file name and contents, to Copy or Save as… and move into place."""

    def __init__(self, parent: QWidget | None, folder: str, name: str, contents: str, reason: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(MANUAL_TITLE)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.folder, self.name, self.contents = folder, name, contents
        layout = QVBoxLayout(self)
        intro = QLabel(MANUAL_TEXT.format(name=name, folder=folder, reason=reason))
        intro.setWordWrap(True)
        intro.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(intro)
        layout.addWidget(QLabel(f"File name: {name}"))
        self.text = QPlainTextEdit(contents)
        self.text.setReadOnly(True)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        layout.addWidget(self.text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        copy = QPushButton("Copy")
        copy.setToolTip("Copy the file's contents")
        copy.clicked.connect(self.copy)
        save = QPushButton("Save as…")
        save.setToolTip(f"Save {name} in a folder you can write, then move it into {folder}")
        save.clicked.connect(self.save_as)
        buttons.addButton(copy, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(save, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    def copy(self) -> None:
        if (clipboard := QApplication.clipboard()) is not None:
            clipboard.setText(self.contents)

    def save_as(self) -> None:
        target, _ = QFileDialog.getSaveFileName(self, "Save .helab-root", os.path.join(os.path.expanduser("~"),
                                                                                       self.name))
        if target:
            self.write(target)

    def write(self, target: str) -> None:
        """The exact bytes HeLab would have written (a local folder the user chose, not the source)."""
        try:
            with open(target, "wb") as stream:
                stream.write(self.contents.encode("utf-8"))
        except OSError as exc:
            QMessageBox.warning(self, MANUAL_TITLE, f"Couldn't save {target}: {exc}")


__all__ = ["PLACE_ROOT_ACTION", "ManualMarkerDialog", "ask_place_root", "placement_checks"]
