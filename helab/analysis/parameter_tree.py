"""The pyqtgraph parameter tree of a plot's settings, built from ``ParameterSpec``s."""
from __future__ import annotations

import re
from typing import Any, Sequence, cast

from PyQt6.QtWidgets import QTabWidget, QWidget
import pyqtgraph.functions as fn
from pyqtgraph.parametertree import Parameter, ParameterTree, registerParameterType
from pyqtgraph.parametertree.parameterTypes.basetypes import SimpleParameter
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
    """

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
        text = text.strip().removeprefix(opts["prefix"]).strip()
        suffix = opts["suffix"]
        with_unit = bool(suffix) and text.endswith(suffix)
        if with_unit:
            text = text[:-len(suffix)].rstrip()
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


class UnitNumberItem(NumericParameterItem):  # type: ignore[misc]
    def makeWidget(self) -> UnitSpinBox:
        """``NumericParameterItem.makeWidget`` with a ``UnitSpinBox``."""
        opts = self.param.opts
        options: dict[str, Any] = {"value": 0, "min": None, "max": None, "step": 1.0, "dec": False,
                                   "siPrefix": False, "suffix": "", "decimals": 3}
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


def _with_number_types(children: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for child in children:
        child["type"] = NUMBER_TYPES.get(child["type"], child["type"])
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
        if spec.when is not None:
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
