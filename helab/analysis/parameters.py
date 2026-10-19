"""Parameters an analysis declares: defaults, limits and units, validated before a run."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

Kind = Literal["float", "int", "bool"]


@dataclass(frozen=True)
class ParameterSpec:
    name: str  # the key the analysis reads
    title: str  # what the parameter tree shows
    kind: Kind
    default: float | int | bool
    limits: tuple[float, float] | None = None
    suffix: str = ""
    tip: str = ""

    def coerce(self, value: Any) -> float | int | bool:
        """``value`` as this parameter's type, clamped to its limits."""
        if self.kind == "bool":
            return bool(value)
        number: float | int = int(value) if self.kind == "int" else float(value)
        if self.limits is not None:
            lower, upper = self.limits
            number = min(max(number, type(number)(lower)), type(number)(upper))
        return number

    def tree_item(self, value: Any = None) -> dict[str, Any]:
        """A pyqtgraph ``Parameter`` definition."""
        item: dict[str, Any] = {"name": self.name, "title": self.title, "type": self.kind,
                                "value": self.coerce(self.default if value is None else value),
                                "default": self.default}
        if self.limits is not None:
            item["limits"] = self.limits
        if self.suffix:
            item["suffix"] = self.suffix
        if self.tip:
            item["tip"] = self.tip
        return item


def effective(specs: Sequence[ParameterSpec], values: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Every declared parameter, from ``values`` where given, else its default; unknown keys dropped."""
    values = values or {}
    return {spec.name: spec.coerce(values.get(spec.name, spec.default)) for spec in specs}


def describe(specs: Sequence[ParameterSpec], values: Mapping[str, Any]) -> str:
    """``title value suffix`` pairs for a source line, in declaration order."""
    parts = []
    for spec in specs:
        if spec.name in values:
            value = values[spec.name]
            shown = f"{value:g}" if isinstance(value, float) else str(value)
            parts.append(f"{spec.title} {shown}{spec.suffix.strip() and ' ' + spec.suffix.strip()}")
    return ", ".join(parts)
