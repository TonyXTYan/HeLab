"""Settings → Lab parameters: the constants that normally never change (g, the He* mass, the
scattering length, the detector), app-wide (roadmaps/dld-front-panel-port.md, "Constants at
three levels"). Each row shows its value with its unit, its source, whether it is still a
borrowed (unconfirmed) value, and Restore default. CODATA values are shown read-only.

Folders set their own values (right-click › Folder constants…) and plots can override any of
them in their own settings; runs resolve the three when they start."""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QGridLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from helab.analysis.constant_layers import FIXED_PREFIX, LIMITS, SI_UNITS
from helab.analysis.parameter_tree import UnitSpinBox
from helab.analysis.physics import Constant
from helab.utils.colours import AMBER
from helab.utils.lab_parameters import editable, lab_rows, read_lab_constants, write_lab_constants

__all__ = ["AMBER", "LabParametersTab", "UNCONFIRMED", "UNCONFIRMED_TIP", "constant_editor", "name_label", "number"]
UNCONFIRMED = "unconfirmed"
UNCONFIRMED_TIP = "A value borrowed from the legacy code, not yet checked on the current setup"


def constant_editor(constant: Constant, value: float) -> UnitSpinBox:
    """A spin box for one constant: its unit, lengths always in mm and times in ms (grouped, as the
    plots show them), an SI prefix for Hz, scientific notation otherwise; steps of a tenth of the
    value's decade, positive values only (at most the row's maximum). A coded row (the trap's axial
    axis) takes its codes, whole numbers, with their labels in the tooltip (a drop-down: proposed)."""
    box = UnitSpinBox()
    if constant.choices:
        box.setOpts(value=int(value), int=True, step=1, bounds=[min(constant.choices), max(constant.choices)])
        box.setToolTip(constant.source)
        fit_width(box)
        return box
    box.setOpts(value=value, suffix=constant.unit, siPrefix=constant.unit in SI_UNITS, dec=True, step=0.1,
                minStep=LIMITS[0], decimals=8, bounds=[LIMITS[0], min(LIMITS[1], constant.maximum)],
                fixedPrefix=FIXED_PREFIX.get(constant.unit))
    box.setToolTip(constant.source)
    fit_width(box)
    box.sigValueChanged.connect(lambda *_: fit_width(box))
    return box


# The widest a constant's value usually shows: grouped digits, decimals and a sign, in the box's unit.
WIDE_NUMBER = "−0,000.000000"
EDITOR_EXTRA = 40  # px: the spin buttons and the frame


def fit_width(box: UnitSpinBox) -> None:
    """At least wide enough for the value shown and for ``WIDE_NUMBER`` with the unit, so a number
    is never cut ("3.09078 ms" for 416.09078 ms); it only grows."""
    metrics = box.fontMetrics()
    unit = f" {box.opts.get('fixedPrefix') or ''}{box.opts.get('suffix') or ''}"
    widest = max(metrics.horizontalAdvance(box.text()), metrics.horizontalAdvance(WIDE_NUMBER + unit))
    box.setMinimumWidth(max(box.minimumWidth(), widest + EDITOR_EXTRA))


def name_label(constant: Constant) -> QLabel:
    """A constant's name over its source, wrapped, wide enough for a few words a line (a narrow
    column wrapped the source a word a line and cut it off)."""
    label = QLabel(f"{constant.title}<br><small>{constant.source}</small>")
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setWordWrap(True)
    label.setToolTip(constant.source)
    label.setMinimumWidth(label.fontMetrics().horizontalAdvance("M" * 14))
    label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    return label


def number(box: UnitSpinBox) -> float:
    return float(box.value())


class LabParametersTab(QWidget):
    def __init__(self, settings: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        intro = QLabel("Constants for every folder and plot. A folder can set its own values (right-click › "
                       "Folder constants…), and a plot can override any value in its own settings. Values "
                       "marked unconfirmed are borrowed from the legacy code: check them on the current setup.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setColumnStretch(0, 1)
        self.editors: dict[str, UnitSpinBox] = {}
        self.status: dict[str, QLabel] = {}
        self.restore_buttons: dict[str, QPushButton] = {}
        self.read_only: dict[str, QLabel] = {}
        for row, constant in enumerate(lab_rows()):
            grid.addWidget(name_label(constant), row, 0)
            status = QLabel()
            status.setWordWrap(True)
            self.status[constant.key] = status
            grid.addWidget(status, row, 2)
            if not editable(constant):
                value = QLabel(f"{constant.value:.10g} {constant.unit}")
                value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                self.read_only[constant.key] = value
                grid.addWidget(value, row, 1)
                status.setText("CODATA, read-only")
                continue
            box = constant_editor(constant, constant.value)
            box.sigValueChanged.connect(lambda *_, key=constant.key: self._update(key))
            self.editors[constant.key] = box
            grid.addWidget(box, row, 1)
            restore = QPushButton("Restore")
            restore.setToolTip(f"Default: {constant.value:.10g} {constant.unit}")
            restore.clicked.connect(lambda _=False, key=constant.key: self.restore(key))
            self.restore_buttons[constant.key] = restore
            grid.addWidget(restore, row, 3)
        grid.setRowStretch(len(lab_rows()), 1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.load(settings)

    def load(self, settings: QSettings) -> None:
        saved = read_lab_constants(settings)
        for key, box in self.editors.items():
            box.setValue(saved.get(key, self._default(key)))
            self._update(key)

    def values(self) -> dict[str, float]:
        """The values set (not at their defaults)."""
        return {key: number(box) for key, box in self.editors.items() if number(box) != self._default(key)}

    def save(self, settings: QSettings) -> None:
        write_lab_constants(settings, self.values())

    def restore(self, key: str) -> None:
        self.editors[key].setValue(self._default(key))
        self._update(key)

    def is_set(self, key: str) -> bool:
        return number(self.editors[key]) != self._default(key)

    @staticmethod
    def _default(key: str) -> float:
        return next(constant.value for constant in lab_rows() if constant.key == key)

    def _update(self, key: str) -> None:
        constant = next(constant for constant in lab_rows() if constant.key == key)
        changed = self.is_set(key)
        self.restore_buttons[key].setEnabled(changed)
        parts: list[str] = ["set here" if changed else "default"]
        if constant.shown_only:
            parts.append("shown only")
        status = self.status[key]
        text = " · ".join(parts)
        if constant.unconfirmed and not changed:
            status.setText(f'{text} · <span style="color: {AMBER}">{UNCONFIRMED}</span>')
            status.setToolTip(UNCONFIRMED_TIP)
        else:
            status.setText(text)
            status.setToolTip("Shown, and used to flag incomplete shots; never in a physics formula"
                              if constant.shown_only else "")

    def status_text(self, key: str) -> str:
        """The status column as plain text (for tests)."""
        import re
        return re.sub(r"<[^>]+>", "", self.status[key].text())

    def editor_value(self, key: str) -> Any:
        return number(self.editors[key])
