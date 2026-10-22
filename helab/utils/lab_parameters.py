"""Settings → Lab parameters: the lab-level constants (``physics.CONSTANTS`` rows with level
"lab"), saved in QSettings under ``lab_constants/<key>``.

Only values the user set are saved; Restore default removes the key, so a later HeLab with a
corrected default uses it. CODATA values are never saved (they are shown read-only).
"""
from __future__ import annotations

from PyQt6.QtCore import QSettings

from helab.analysis.constant_layers import clean_layer
from helab.analysis.physics import CONSTANTS, Constant
from helab.utils.settings_defaults import read_setting

LAB_CONSTANTS_GROUP = "lab_constants"


def lab_rows() -> tuple[Constant, ...]:
    """The rows Settings → Lab parameters lists, in table order."""
    return tuple(constant for constant in CONSTANTS if constant.level == "lab")


def editable(constant: Constant) -> bool:
    return constant.level == "lab" and not constant.codata


def setting_key(key: str) -> str:
    return f"{LAB_CONSTANTS_GROUP}/{key}"


def read_lab_constants(settings: QSettings) -> dict[str, float]:
    """The lab values set in ``settings``: editable lab rows with finite, positive numbers (any
    other saved value, e.g. text or a newer HeLab's key, is ignored)."""
    keys = [constant.key for constant in lab_rows() if editable(constant)]
    saved: dict[str, object] = {}
    for key in keys:
        value = read_setting(settings, setting_key(key))
        if value is not None:
            saved[key] = value
    return clean_layer(saved, keys)


def write_lab_constants(settings: QSettings, values: dict[str, float]) -> None:
    """Save exactly ``values`` as the lab's (a key left out is its default again)."""
    chosen = clean_layer(values, [constant.key for constant in lab_rows() if editable(constant)])
    for constant in lab_rows():
        if constant.key in chosen:
            settings.setValue(setting_key(constant.key), chosen[constant.key])
        else:
            settings.remove(setting_key(constant.key))
