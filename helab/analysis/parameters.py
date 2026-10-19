"""Parameters an analysis declares: defaults, limits and units, validated before a run.

A ``choice`` parameter picks one of its ``choices``; another parameter can say it applies
only under one of them (``when``), so the parameter tree shows it only then and the dock's
source line leaves it out otherwise. ``group`` names the tree section it sits in, and
``page`` the settings tab (a plot whose parameters name more than one page gets a tab each).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

Kind = Literal["float", "int", "bool", "choice"]
Value = float | int | bool | str


@dataclass(frozen=True)
class ParameterSpec:
    name: str  # the key the analysis reads
    title: str  # what the parameter tree shows
    kind: Kind
    default: Value
    limits: tuple[float, float] | None = None
    suffix: str = ""
    tip: str = ""
    choices: tuple[str, ...] = ()  # kind "choice": the allowed values, a drop-down in the tree
    group: str = ""  # the parameter tree section this belongs to ("" = top level)
    when: tuple[str, str] | None = None  # (choice parameter, value) this applies under; None = always
    si: bool = False  # a float in a base unit (s, m): shown with SI prefixes (4 mm), stepped by decade
    page: str = ""  # the settings tab this is on ("" = the first); a group goes on its first parameter's page

    def coerce(self, value: Any) -> Value:
        """``value`` as this parameter's type, clamped to its limits (a choice outside
        ``choices`` becomes the default)."""
        if self.kind == "bool":
            return bool(value)
        if self.kind == "choice":
            text = str(value)
            return text if text in self.choices else str(self.default)
        number: float | int = int(value) if self.kind == "int" else float(value)
        if self.limits is not None:
            lower, upper = self.limits
            number = min(max(number, type(number)(lower)), type(number)(upper))
        return number

    def applies(self, values: Mapping[str, Any]) -> bool:
        """Whether this parameter is in use under ``values`` (its ``when`` holds, or it has none)."""
        return self.when is None or str(values.get(self.when[0])) == self.when[1]

    def tree_item(self, value: Any = None) -> dict[str, Any]:
        """A pyqtgraph ``Parameter`` definition."""
        item: dict[str, Any] = {"name": self.name, "title": self.title,
                                "type": "list" if self.kind == "choice" else self.kind,
                                "value": self.coerce(self.default if value is None else value),
                                "default": self.default}
        if self.kind == "choice":
            item["limits"] = list(self.choices)
        elif self.limits is not None:
            item["limits"] = self.limits
        if self.suffix:
            item["suffix"] = self.suffix.strip()  # the spin box adds its own space
        if self.si:
            # Steps of a tenth of the value's decade: 4 mm → 5 mm, 3.85 s → 3.95 s.
            item.update(siPrefix=True, dec=True, step=0.1, decimals=6)
        if self.tip:
            item["tip"] = self.tip
        return item

    def text(self, value: Any) -> str:
        """``title value suffix`` for a source line."""
        if self.kind == "bool":
            shown = "on" if value else "off"
        elif isinstance(value, float):
            shown = f"{value:g}"
        elif isinstance(value, int):
            shown = f"{value:,}"
        else:
            shown = str(value)
        return f"{self.title} {shown}{self.suffix.strip() and ' ' + self.suffix.strip()}"


def effective(specs: Sequence[ParameterSpec], values: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Every declared parameter, from ``values`` where given, else its default; unknown keys dropped."""
    values = values or {}
    return {spec.name: spec.coerce(values.get(spec.name, spec.default)) for spec in specs}


def describe(specs: Sequence[ParameterSpec], values: Mapping[str, Any], every: bool = False) -> str:
    """``title value suffix`` pairs for a source line, in declaration order: the parameters
    in use under ``values`` (``every``: all of them, for the record)."""
    return ", ".join(spec.text(values[spec.name]) for spec in specs
                     if spec.name in values and (every or spec.applies(values)))


def tree_children(specs: Sequence[ParameterSpec]) -> list[dict[str, Any]]:
    """pyqtgraph ``Parameter`` definitions, grouped by ``group`` in declaration order."""
    children: list[dict[str, Any]] = []
    groups: dict[str, dict[str, Any]] = {}
    for spec in specs:
        item = spec.tree_item()
        if not spec.group:
            children.append(item)
            continue
        group = groups.get(spec.group)
        if group is None:
            group = groups[spec.group] = {"name": spec.group, "type": "group", "children": []}
            children.append(group)
        group["children"].append(item)
    return children
