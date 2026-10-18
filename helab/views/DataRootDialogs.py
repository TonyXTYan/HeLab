"""Place .helab-root here…: the checks before writing a folder's marker, and the dialog that hands
out its exact contents when HeLab can't write it (data roots, D3)."""
from __future__ import annotations

import ntpath
import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (QAbstractButton, QApplication, QDialog, QDialogButtonBox, QFileDialog, QLabel,
                             QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from helab.utils.folder_cache import PLACE_ROOT_ACTION, FolderCache, marker_path

TITLE = "Place .helab-root"
CONFIRM = ("HeLab will write a small hidden file, .helab-root, in {path}. Its subfolders will use the "
           "disk cache too. The folder's modified date changes once.")
NOT_TOP = ("This folder isn't the top of its drive or share ({top}). Place .helab-root at the top, so every "
           "computer sees the same marker; put it here only if this folder is also shared on its own.")
NESTED = ("This folder is already inside data root “{label}” ({marker}). A .helab-root here gives it its "
          "own identity, and its subfolders' cached data moves to it.")
HOME = ("A home folder holds more than data, and other computers rarely see it at this path. "
        "Place .helab-root at the top of the drive or share the data is on.")
STARTUP = ("This is the top of the startup disk, which holds the system (on macOS it is read-only): "
           "mark the top folder holding the data instead, e.g. ~/data.")
VOLUMES = "This is the folder of mounted drives, not a drive: choose a drive or share inside it."
ADMIN = "Writing in {drive} may need administrator rights. If Windows refuses, HeLab shows the file to place by hand."
MANUAL_TITLE = "Place the data-root file manually"
MANUAL_TEXT = "HeLab can't write {name} in {folder} ({reason}).\nPut this file in {folder}, then Retry / Refresh that folder."
# A visible name for Save as…: save panels refuse or hide names starting with a dot.
SAVE_NAME = "helab-root.txt"
SAVED_TEXT = "Saved as {target}. Rename it to {name} and move it into {folder}, then Retry / Refresh that folder."


def _system_folders() -> dict[str, str]:
    """Folders that warn, and why. A marker belongs as high as every computer sees the data,
    so a drive's top is fine, the Windows system drive's included (Tony, 2026-10-18)."""
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        drive = _system_drive()
        return {ntpath.normcase(path): HOME for path in (ntpath.join(drive, "Users"), home)}
    return {"/": STARTUP, "/System/Volumes/Data": STARTUP, "/Volumes": VOLUMES,
            "/Users": HOME, "/home": HOME, home: HOME}


def _system_drive() -> str:
    return os.environ.get("SystemDrive", "C:") + "\\"


def _system_mount(mount: str) -> bool:
    """The startup disk's top (read-only on macOS, the system's on Linux): never suggest it."""
    return sys.platform != "win32" and mount in ("/", "/System/Volumes/Data", "/home")


def placement_checks(cache: FolderCache, path: str) -> tuple[str | None, list[str]]:
    """Before writing: the top of the folder's drive or share when it isn't that (to offer placing
    the marker there instead), and the warnings to show. Memory only."""
    warnings: list[str] = []
    normal = ntpath.normcase(path) if sys.platform == "win32" else path
    if (warning := _system_folders().get(normal)) is not None:
        warnings.append(warning)
    top = cache.mount_of(path)
    if top is None or top == path or _system_mount(top):
        top = None
    else:
        warnings.append(NOT_TOP.format(top=top))
    if (root := cache.root_of(path)) is not None and root[0] != path:
        warnings.append(NESTED.format(label=root[2] or os.path.basename(root[0]), marker=marker_path(root[0])))
    return top, warnings


def placement_notes(path: str, top: str | None) -> list[str]:
    """Not warnings (Return still places): writing at the Windows system drive's top may need admin."""
    drive = _system_drive()
    if sys.platform == "win32" and any(folder is not None and ntpath.normcase(folder) == ntpath.normcase(drive)
                                       for folder in (path, top)):
        return [ADMIN.format(drive=drive)]
    return []


class PlaceRootBox(QMessageBox):
    """The confirmation: "Place at <top>" first when the folder isn't the top of its drive or share,
    then "Place here" (or "Place .helab-root"), and Cancel. With warnings Cancel is the default, so
    Return never writes into a folder the user didn't click."""

    def __init__(self, parent: QWidget | None, cache: FolderCache, path: str) -> None:
        self.top, warnings = placement_checks(cache, path)
        super().__init__(QMessageBox.Icon.Warning if warnings else QMessageBox.Icon.Question, TITLE,
                         CONFIRM.format(path=path), parent=parent)
        self.path = path
        if info := warnings + placement_notes(path, self.top):
            self.setInformativeText("\n\n".join(info))
        self.at_top: QAbstractButton | None = (
            self.addButton(f"Place at {self.top}", QMessageBox.ButtonRole.AcceptRole) if self.top else None)
        self.here: QAbstractButton | None = self.addButton("Place here" if self.top else "Place .helab-root",
                                                           QMessageBox.ButtonRole.AcceptRole)
        cancel = self.addButton(QMessageBox.StandardButton.Cancel)
        if warnings and cancel is not None:
            self.setDefaultButton(cancel)
        elif isinstance(self.here, QPushButton):
            self.setDefaultButton(self.here)

    def choice(self) -> str | None:
        """The folder to write the marker in, from the button clicked; None for Cancel."""
        clicked = self.clickedButton()
        if clicked is not None and clicked is self.at_top:
            return self.top
        return self.path if clicked is not None and clicked is self.here else None


def ask_place_root(parent: QWidget | None, cache: FolderCache, path: str) -> str | None:
    """Confirm, with the checks' warnings: the folder to write the marker in, or None."""
    box = PlaceRootBox(parent, cache, path)
    box.exec()
    return box.choice()


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
        self.intro = intro
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
        save.setToolTip(f"Save it as {SAVE_NAME} in a folder you can write, then rename it to {name} and "
                        f"move it into {folder}")
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
                                                                                       SAVE_NAME))
        if target:
            self.write(target)

    def write(self, target: str) -> None:
        """The exact bytes HeLab would have written (a local folder the user chose, not the source)."""
        try:
            with open(target, "wb") as stream:
                stream.write(self.contents.encode("utf-8"))
        except OSError as exc:
            QMessageBox.warning(self, MANUAL_TITLE, f"Couldn't save {target}: {exc}")
            return
        if os.path.basename(target) != self.name:
            self.intro.setText(SAVED_TEXT.format(target=target, name=self.name, folder=self.folder))


__all__ = ["PLACE_ROOT_ACTION", "ManualMarkerDialog", "ask_place_root", "placement_checks"]
