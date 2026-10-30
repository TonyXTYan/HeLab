"""The pyqtgraph parameter tree of a plot's settings, built from ``ParameterSpec``s."""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Sequence, cast

from PyQt6.QtCore import QEvent, QObject, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFocusEvent, QKeyEvent
from PyQt6.QtWidgets import QApplication, QTabWidget, QTextEdit, QWidget
import pyqtgraph.functions as fn
from pyqtgraph.parametertree import Parameter, ParameterTree, registerParameterType
from pyqtgraph.parametertree.parameterTypes.basetypes import SimpleParameter, WidgetParameterItem
from pyqtgraph.parametertree.parameterTypes.list import ListParameter, ListParameterItem
from pyqtgraph.parametertree.parameterTypes.numeric import NumericParameterItem
from pyqtgraph.widgets.SpinBox import SpinBox

from helab.analysis.parameters import ParameterSpec, tree_children

# Numbers use HeLab's spin box, under their own type names so pyqtgraph's own stay as they are.
NUMBER_TYPES = {"float": "helab_float", "int": "helab_int"}


# A number (one decimal mark, "." or ",", and an exponent allowed), then an optional SI prefix
# ("u" for µ too).
SI_PREFIX_LETTERS = "".join(prefix for prefix in fn.SI_PREFIX_EXPONENTS if prefix.strip())
NUMBER = re.compile(r"(?P<number>[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?)\s*"
                    r"(?P<prefix>[" + SI_PREFIX_LETTERS + r"]?)")
# A number with thousands separators, as a fixed-prefix box shows it: "20,450.5", "-1,000". The
# first group never starts with 0 ("0,450" is no grouping).
GROUPED = re.compile(r"(?P<number>[+-]?[1-9]\d{0,2}(?:,\d{3})+(?:\.\d*)?)(?![\d,])")
FIXED_DECIMALS = 9  # a fixed-prefix box shows up to this many decimals (trailing zeros dropped)
# … and plain digits between these sizes (in its unit); beyond them, exponent form ("1e-57 ms").
FIXED_RANGE = (1e-6, 1e12)
MINUS = "−"  # U+2212, as the plots write negative numbers; "-" is read too


class UnitSpinBox(SpinBox):  # type: ignore[misc]
    """pyqtgraph's spin box, reading what is typed strictly, with or without the unit:

    - A bare number is in the unit shown: "95" in a "%" box is 95 %; "5" in a box showing
      "4 ms" is 5 ms, "-5" is -5 ms and "1e-3" is 1 µs.
    - An SI prefix may come without the unit: "5 m" there is 5 ms, "5 k" 5 ks. With the unit
      it says itself: "5 s" is 5 s, "5 µs" (or "5 us") is 5 µs.
    - The decimal mark is "." or the locale's: "95,5" is 95.5 % where the comma is the decimal
      mark (German) and invalid elsewhere (pyqtgraph's own parser read it as 9 %). The box
      never shows thousands separators, so "1.000" is 1 everywhere.
    - Anything else (empty, other letters, "inf", a fraction in a whole-number box) is invalid:
      the box outlines red while typing, and its value comes back when the edit ends.
    - A number beyond the limits is set to the nearest limit when the edit ends.

    With the ``fixedPrefix`` option (an SI prefix, ``ParameterSpec.unit_prefix``) the value is
    always shown with that prefix, its digits grouped by thousands with "," and "." before the
    decimals whatever the locale (Tony, 2026-10-20): 20.45 s shows as "20,450 ms", −0.5 ms as
    "−0.5 ms" (exponent form beyond ``FIXED_RANGE``). There "," is only ever a thousands separator,
    whatever the locale, and "." the only decimal point: a comma must sit between groups of three
    digits after a first group of 1–3 not starting with 0 ("20,450.5", "1,000"); any other comma
    ("20,5", "0,450", "1,23") is invalid, so a comma never changes a value 1,000× silently.
    "−" and "-" both mean minus. A value under 1 in the box's unit also shows in the SI prefix
    that suits it in the box's tooltip ("0.0005925 ms = 592.5 ns").
    """

    def __init__(self, parent: Any = None, value: float = 0.0, **kwargs: Any) -> None:
        super().__init__(parent, value)
        self.opts["fixedPrefix"] = None  # Before setOpts: pyqtgraph accepts only keys it has.
        if kwargs:
            self.setOpts(**kwargs)

    def formatText(self) -> str:
        """pyqtgraph's text, or with ``fixedPrefix`` the value in that prefix, grouped by thousands."""
        letter = self.opts.get("fixedPrefix")
        if letter is None or self.opts["int"]:
            return str(super().formatText())
        scaled = Decimal(self.val).scaleb(-fn.SI_PREFIX_EXPONENTS[letter or " "])
        size = abs(scaled)
        if size and not FIXED_RANGE[0] <= size < FIXED_RANGE[1]:
            number = f"{scaled:.6g}"
        else:
            number = f"{scaled:,.{FIXED_DECIMALS}f}"
            if "." in number:
                number = number.rstrip("0").rstrip(".")
        if number in ("-0", ""):
            number = "0"
        number = number.replace("-", MINUS)
        prefix = self.opts["prefix"]
        unit = f"{letter}{self.opts['suffix']}"
        text = f"{prefix}{' ' if prefix else ''}{number}{' ' if unit else ''}{unit}"
        self._small_hint(scaled, text)
        return text

    def _small_hint(self, scaled: Decimal, text: str) -> None:
        """Below 1 in the box's unit, the tooltip also gives the value with its own SI prefix, on a
        line after the tooltip the box was given."""
        suffix = str(self.opts["suffix"])
        hint = ""
        if scaled and abs(scaled) < 1 and suffix:
            from helab.analysis.display_units import si_text
            hint = f"{text} = {si_text(float(self.val), suffix)}"
        old = str(getattr(self, "_hint", ""))
        base = self.toolTip()
        if old and base.endswith(old):
            base = base[:-len(old)].rstrip("\n")
        self._hint = hint
        self.setToolTip("\n".join(part for part in (base, hint) if part))

    def selectNumber(self) -> None:
        """Select the number (grouped digits too) for quick editing."""
        edit = self.lineEdit()
        if edit is None:
            return
        match = re.search(r"[+−-]?[\d.,]+(?:e[+−-]?\d+)?", edit.text())
        if match is not None:
            edit.setSelection(match.start(), match.end() - match.start())

    def interpret(self) -> Any:
        edit = self.lineEdit()
        value = None if edit is None else self.parse(edit.text())
        return False if value is None else value

    def parse(self, text: str) -> Any:
        """``text`` as this box's value (a Decimal, an int in a whole-number box), or None."""
        split = self._split(text)
        if split is None:
            return None
        number, prefix, with_unit = split
        if not prefix and not with_unit:
            prefix = self._shown_prefix()
        opts = self.opts
        value = fn.siApply(opts["evalFunc"](number.replace(",", ".")), prefix, opts["suffixPower"])
        if opts["int"]:
            return int(value) if value == int(value) else None
        return value

    def fixup(self, strn: str | None) -> str:
        """The edit ended on text that is no value in range: a number beyond the limits
        becomes the nearest limit (``setValue`` clamps); anything else goes back."""
        value = self.interpret()
        if value is False:
            self.updateText()
        else:
            self.setValue(value)
        edit = self.lineEdit()
        return edit.text() if edit is not None else strn or ""

    def _split(self, text: str) -> tuple[str, str, bool] | None:
        """(number, SI prefix, whether the unit was typed), or None if ``text`` isn't one."""
        opts = self.opts
        text = text.strip().removeprefix(opts["prefix"]).strip().replace(MINUS, "-")
        suffix = opts["suffix"]
        with_unit = bool(suffix) and text.endswith(suffix)
        if with_unit:
            text = text[:-len(suffix)].rstrip()
        if opts.get("fixedPrefix") is not None and "," in text:
            # Only a thousands separator here: valid grouping, or the text is no number.
            grouped = GROUPED.match(text)
            if grouped is None or "," in text[grouped.end():]:
                return None
            text = grouped["number"].replace(",", "") + text[grouped.end():]
        match = NUMBER.fullmatch(text)
        if match is None:
            return None
        number, prefix = match["number"], match["prefix"]
        if (prefix and not opts["siPrefix"]) or ("," in number and self.locale().decimalPoint() != ","):
            return None
        return number, prefix, with_unit

    def _shown_prefix(self) -> str:
        shown = self._split(self.lastText) if self.opts["siPrefix"] else None
        return shown[1] if shown is not None else ""


class EndsEditOnReturn:
    """A tree row's editor that Return or Enter closes once the box has taken the value (the box's
    own Return commits it; an invalid entry gives the value back, as Tab does), and Escape closes
    with the value put back, uncommitted. Closing deselects the row, so it shows its value and a
    click opens the editor again. Before, Return committed but left the editor open, which looked
    as if nothing had been taken (known-issues, the computer-use smoke pass)."""

    def widgetEventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if isinstance(ev, QKeyEvent) and ev.type() == QEvent.Type.KeyPress and getattr(self, "hideWidget", False):
            if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                QTimer.singleShot(0, self._close_editor)  # After the box's own Return, which commits.
            elif ev.key() == Qt.Key.Key_Escape:
                widget = getattr(self, "widget")
                widget.setValue(getattr(self, "param").value())
                if isinstance(widget, SpinBox):
                    widget.updateText()  # (setValue keeps the typed text when the value is the same.)
                QTimer.singleShot(0, self._close_editor)
                return True
        return bool(super().widgetEventFilter(obj, ev))  # type: ignore[misc]

    def _close_editor(self) -> None:
        tree = cast(Any, self).treeWidget()
        if tree is not None and tree.currentItem() is self:
            tree.clearSelection()  # (pyqtgraph hides a deselected row's editor.)
            tree.setFocus(Qt.FocusReason.OtherFocusReason)


class UnitNumberItem(EndsEditOnReturn, NumericParameterItem):  # type: ignore[misc]
    def makeWidget(self) -> UnitSpinBox:
        """``NumericParameterItem.makeWidget`` with a ``UnitSpinBox``."""
        opts = self.param.opts
        options: dict[str, Any] = {"value": 0, "min": None, "max": None, "step": 1.0, "dec": False,
                                   "siPrefix": False, "suffix": "", "decimals": 3, "fixedPrefix": None}
        if opts["type"] == NUMBER_TYPES["int"]:
            options.update(int=True, minStep=1.0)
        options.update({key: opts[key] for key in options if key in opts})
        if opts.get("limits") is not None:
            options["min"], options["max"] = opts["limits"]
        widget = UnitSpinBox()
        widget.setOpts(**options)
        setattr(widget, "sigChanged", widget.sigValueChanged)  # The names WidgetParameterItem connects.
        setattr(widget, "sigChanging", widget.sigValueChanging)
        return widget


class UnitNumberParameter(SimpleParameter):  # type: ignore[misc]
    @property
    def itemClass(self) -> type:
        return UnitNumberItem

    def _interpretValue(self, v: Any) -> Any:
        return int(v) if self.opts["type"] == NUMBER_TYPES["int"] else float(v)


for _name in NUMBER_TYPES.values():
    registerParameterType(_name, UnitNumberParameter, override=True)


class CommitTextEdit(QTextEdit):
    """A multi-line text box whose value is committed only when the edit ends: focus leaves it,
    Ctrl+Enter, or ``commit`` (the plot's Rerun calls ``commit_pending_text``). So a Live rerun
    never runs with half-typed text (e.g. mask circles), and every keystroke doesn't count."""

    sigCommitted = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptRichText(False)
        self._committed = ""

    def sizeHint(self) -> QSize:
        return QSize(300, 90)

    def value(self) -> str:
        return self._committed

    def setValue(self, text: str) -> None:
        self._committed = str(text)
        if self.toPlainText() != self._committed:
            self.setPlainText(self._committed)

    def commit(self) -> None:
        text = self.toPlainText()
        if text != self._committed:
            self._committed = text
            self.sigCommitted.emit()

    def focusOutEvent(self, e: QFocusEvent | None) -> None:
        self.commit()
        super().focusOutEvent(e)

    def keyPressEvent(self, e: QKeyEvent | None) -> None:
        if (e is not None and e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.commit()
            return
        super().keyPressEvent(e)


def commit_pending_text() -> None:
    """Commit the text box being typed in, if any (before a deliberate run reads the settings)."""
    focus = QApplication.focusWidget()
    if isinstance(focus, CommitTextEdit):
        focus.commit()


class CommitTextItem(WidgetParameterItem):  # type: ignore[misc]
    def makeWidget(self) -> CommitTextEdit:
        self.hideWidget = False
        self.asSubItem = True
        widget = CommitTextEdit()
        setattr(widget, "sigChanged", widget.sigCommitted)  # The name WidgetParameterItem connects.
        return widget


class CommitTextParameter(Parameter):  # type: ignore[misc]
    @property
    def itemClass(self) -> type:
        return CommitTextItem


TEXT_TYPE = "helab_text"
registerParameterType(TEXT_TYPE, CommitTextParameter, override=True)


class ChoiceItem(EndsEditOnReturn, ListParameterItem):  # type: ignore[misc]
    """pyqtgraph's drop-down row, which Return and Escape close (``EndsEditOnReturn``)."""


class ChoiceParameter(ListParameter):  # type: ignore[misc]
    @property
    def itemClass(self) -> type:
        return ChoiceItem


CHOICE_TYPE = "helab_list"
registerParameterType(CHOICE_TYPE, ChoiceParameter, override=True)
TREE_TYPES = {**NUMBER_TYPES, "text": TEXT_TYPE, "list": CHOICE_TYPE}


def _with_number_types(children: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for child in children:
        child["type"] = TREE_TYPES.get(child["type"], child["type"])
        _with_number_types(child.get("children", []))
    return children


def build_tree(specs: Sequence[ParameterSpec]) -> Parameter:
    """The root of a tree with the declared parameters in their groups; parameters that apply
    only under one choice are shown only then."""
    root = Parameter.create(name="params", type="group", children=_with_number_types(tree_children(specs)))
    apply_visibility(root, specs)
    root.sigTreeStateChanged.connect(lambda *_: apply_visibility(root, specs))
    return root


def parameter_of(root: Parameter, spec: ParameterSpec) -> Parameter:
    return root.child(spec.group, spec.name) if spec.group else root.child(spec.name)


def tree_values(root: Parameter, specs: Sequence[ParameterSpec]) -> dict[str, Any]:
    """Every declared parameter's current value in the tree."""
    return {spec.name: parameter_of(root, spec).value() for spec in specs}


def apply_visibility(root: Parameter, specs: Sequence[ParameterSpec]) -> None:
    values = tree_values(root, specs)
    for spec in specs:
        if spec.when is not None or spec.shown_with is not None:
            parameter_of(root, spec).setOpts(visible=spec.applies(values))


def settings_widget(root: Parameter, specs: Sequence[ParameterSpec]) -> QWidget:
    """The tree of ``root``; when the parameters name more than one ``page``, a tab per page
    (in declaration order) holding its parameters and groups, all still under ``root``."""
    pages: dict[str, list[Parameter]] = {}
    placed: set[str] = set()
    for spec in specs:
        top = spec.group or spec.name
        if top not in placed:
            placed.add(top)
            pages.setdefault(spec.page, []).append(root.child(top))
    if len(pages) <= 1:
        tree = ParameterTree()
        tree.setParameters(root, showTop=False)
        return cast(QWidget, tree)
    tabs = QTabWidget()
    tabs.setDocumentMode(True)
    for page, parameters in pages.items():
        tree = ParameterTree()
        for parameter in parameters:
            tree.addParameters(parameter, showTop=True)
        tabs.addTab(tree, page or "Settings")
    return tabs
