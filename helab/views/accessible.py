"""Accessible names and stable IDs for HeLab's controls, which test runners use instead of pixels
(macOS ``app_ax_find``, Windows UI Automation; roadmaps/smoke-automation.md, items 1 and 4).

Every interactive control gets an ID (``identify``): its ``objectName`` and its accessible identifier,
the same text. Qt 6.11 gives a control's accessible identifier as macOS's AXIdentifier and Windows'
UIA AutomationId (``QAccessibleBridgeUtils::accessibleId``; without one it would be the dotted path
of every ancestor's objectName or class). An ID is unique among the controls a window shows at once,
the same in every run and language: made from what the control is (a script's analysis ID, a plot's
number, a folder tab's number), never from its text.

The accessible name is what a runner searches for: short and stable, the visible label or the
action. A button whose text says it needs none (Qt names a button by its text). The description
says what the control does, in one line, and doesn't change with state; tooltips that change stay
tooltips (Qt reads a tooltip as the description only where none is set)."""
from __future__ import annotations

import re
from typing import Optional, TypeVar

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QDialogButtonBox, QMessageBox, QToolBar, QWidget

W = TypeVar("W", bound=QWidget)

_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def id_part(text: str) -> str:
    """``text`` (a script's analysis ID, a profile's name) as part of an ID: letters, digits and
    ``_.-`` only."""
    return _UNSAFE.sub("_", text).strip("_") or "_"


def identify(widget: W, ident: str, name: str = "", description: str = "") -> W:
    """Give ``widget`` its ID, and its accessible name and description when given ("" keeps
    what it has)."""
    widget.setObjectName(ident)
    widget.setAccessibleIdentifier(ident)
    if name:
        widget.setAccessibleName(name)
    if description:
        widget.setAccessibleDescription(description)
    return widget


def identify_action(toolbar: QToolBar, action: QAction, ident: str, description: str = "") -> Optional[QWidget]:
    """The button ``toolbar`` made for ``action``: named by the action's text (Qt's), with an ID."""
    button = toolbar.widgetForAction(action)
    if button is not None:
        identify(button, ident, description=description)
    return button


def identify_buttons(box: QDialogButtonBox | QMessageBox, prefix: str) -> None:
    """IDs for a button box's or message box's buttons: ``<prefix>_<standard button>`` (``_ok``,
    ``_cancel``), or for a button added by text, ``<prefix>_<its role>`` and a number when a role
    has several. Call it after the last button is added."""
    used: dict[str, int] = {}
    for button in box.buttons():
        standard = box.standardButton(button)
        kind = id_part(str(standard.name if standard.value else box.buttonRole(button).name).lower())
        used[kind] = used.get(kind, 0) + 1
        identify(button, f"{prefix}_{kind}" + (f"_{used[kind]}" if used[kind] > 1 else ""))

