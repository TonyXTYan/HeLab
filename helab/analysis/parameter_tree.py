"""The pyqtgraph parameter tree of a plot's settings tab, built from ``ParameterSpec``s."""
from __future__ import annotations

from typing import Any, Sequence

from pyqtgraph.parametertree import Parameter

from helab.analysis.parameters import ParameterSpec, tree_children


def build_tree(specs: Sequence[ParameterSpec]) -> Parameter:
    """The root of a tree with the declared parameters in their groups; parameters that apply
    only under one choice are shown only then."""
    root = Parameter.create(name="params", type="group", children=tree_children(specs))
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
