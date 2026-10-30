"""Laser lock states from the instruments: each laser is locked when all its signs are as they should be.

`config.json` → "locks": {"He4": ["left_top:flat", "scope_dot:still", "lockin:middle"], ...}. A sign is
`<instrument>:<condition>`:
- `flat`: a scope's trace is a flat thin line (shape `line`);
- `still` / `moving`: the scope dot's spread over its window is within / beyond `still_px`;
- `middle`: the needle (or a trace's level) is within its `tolerance` of the middle;
- `ok`: the instrument's own status is `ok`.

A laser is `locked` when every sign holds (sure as its least sure sign), `lost` when any fails (sure as its
surest failing sign), and `unknown` when none fails but some can't be told.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Instrument
from .detectors import Reading


@dataclass
class Sign:
    name: str  # as configured, e.g. "left_top:flat"
    holds: bool | None  # None: can't tell
    confidence: float
    why: str


@dataclass
class Lock:
    state: str  # locked, lost, unknown
    confidence: float
    signs: list[Sign] = field(default_factory=list)
    held: str = ""  # why the state is held from before (an instrument covered)

    @property
    def summary(self) -> str:
        if self.held:
            return self.held
        failing = [s.why for s in self.signs if s.holds is False]
        unsure = [s.why for s in self.signs if s.holds is None]
        if self.state != "locked" and not failing and not unsure and self.signs:
            return "signs hold now; locked once they have held for 10 s"
        if self.state == "lost":
            return "; ".join(failing) or "can't tell now: " + "; ".join(unsure)
        if self.state == "unknown":
            return "can't tell: " + "; ".join(unsure)
        return "all signs as locked"


def sign(spec: str, instruments: dict[str, Instrument], readings: dict[str, Reading]) -> Sign:
    name, _, condition = spec.partition(":")
    reading = readings.get(name)
    inst = instruments.get(name)
    if reading is None or inst is None:
        return Sign(spec, None, 0.0, f"{name}: no reading")
    label = inst.label
    values = reading.values
    if reading.status == "unknown" and condition != "ok":
        return Sign(spec, None, reading.confidence, f"{label}: {reading.text}")
    if condition == "flat":
        shape = values.get("shape")
        if shape in (None, "none"):
            return Sign(spec, None, reading.confidence, f"{label}: no trace")
        return Sign(spec, shape == "line", reading.confidence, f"{label}: {shape}")
    if condition in ("still", "moving"):
        spread = values.get("spread_px")
        if not isinstance(spread, (int, float)):
            return Sign(spec, None, 0.0, f"{label}: {reading.text}")
        still = spread <= inst.option("still_px", 2.0)
        return Sign(spec, still == (condition == "still"), reading.confidence, f"{label}: {reading.text}")
    if condition == "middle":
        offset = values.get("offset", values.get("level"))
        if not isinstance(offset, (int, float)):
            return Sign(spec, None, 0.0, f"{label}: {reading.text}")
        centre = 0.0 if "offset" in values else 0.5
        holds = abs(offset - centre) <= inst.option("tolerance", 0.2)
        return Sign(spec, holds, reading.confidence, f"{label}: {reading.text}")
    if condition == "ok":
        status_holds: bool | None = None if reading.status == "unknown" else reading.status == "ok"
        return Sign(spec, status_holds, reading.confidence, f"{label}: {reading.text}")
    return Sign(spec, None, 0.0, f"{spec}: unknown condition")


def evaluate(specs: list[str], instruments: dict[str, Instrument], readings: dict[str, Reading]) -> Lock:
    signs = [sign(spec, instruments, readings) for spec in specs]
    failing = [s for s in signs if s.holds is False]
    if failing:
        return Lock("lost", round(max(s.confidence for s in failing), 2), signs)
    if any(s.holds is None for s in signs) or not signs:
        return Lock("unknown", 0.0, signs)
    return Lock("locked", round(min(s.confidence for s in signs), 2), signs)
