"""The pyqtgraph parameter tree of a plot's settings, built from ``ParameterSpec``s."""
from __future__ import annotations

from math import isinf, isnan
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


class UnitSpinBox(SpinBox):  # type: ignore[misc]
    """pyqtgraph's spin box, which also takes a number typed without its unit: "95" in a
    "%" box is 95 %, and "5" in a box showing "4 mm" is 5 mm (the prefix shown is kept)."""

    def interpret(self) -> Any:
        opts, edit = self.opts, self.lineEdit()
        if edit is None:
            return False
        text = edit.text().removeprefix(opts["prefix"]).strip()
        suffix = opts["suffix"]
        if suffix and text and not text.endswith(suffix):
            text = f"{text} {self._shown_prefix()}{suffix}"
        try:
            number, prefix, _ = fn.siParse(text, opts["regex"], suffix=suffix)
            value = opts["evalFunc"](number.replace(",", "."))
            if (opts["int"] or opts["finite"]) and (isinf(value) or isnan(value)):
                return False
            applied = fn.siApply(value, prefix)
        except Exception:
            return False
        return int(applied) if opts["int"] else applied

    def _shown_prefix(self) -> str:
        if not self.opts["siPrefix"]:
            return ""
        try:
            return str(fn.siParse(self.lastText, self.opts["regex"], suffix=self.opts["suffix"])[1])
        except Exception:
            return ""


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
