"""Display units of the plots (roadmaps/dld-front-panel-port.md, Decided: axis units): X and Y
in mm; T in ms or s, chosen from its range; frequencies and times in short SI form. The TXY
columns stay in s and m (``stats.UNITS``): only what is drawn and written is scaled."""
from __future__ import annotations

import math

LENGTH_UNIT, LENGTH_SCALE = "mm", 1e3


def time_unit(lower: float, upper: float) -> tuple[str, float]:
    """T's display unit and scale from its range: ms while both ends are under 10 s (T is
    typically 0.3–0.5 s after the trigger), else s. (The density images' rule.)"""
    largest = max(abs(lower), abs(upper))
    return ("ms", 1e3) if math.isfinite(largest) and largest < 10.0 else ("s", 1.0)


_PREFIXES = ((1e9, "G"), (1e6, "M"), (1e3, "k"), (1.0, ""), (1e-3, "m"), (1e-6, "µ"), (1e-9, "n"))


def si_text(value: float, unit: str, digits: int = 4) -> str:
    """``value`` with one SI prefix and ``digits`` significant figures: ``1.25 kHz``,
    ``50 ns``, ``0 Hz``; ``–`` when it isn't a number."""
    if not math.isfinite(value):
        return "–"
    if value == 0:
        return f"0 {unit}"
    value = float(f"{value:.{digits}g}")  # rounded first: 0.99999 ms is 1 ms, not 1000 µs
    size = abs(value)
    factor, prefix = next(((f, p) for f, p in _PREFIXES if size >= f * (1 - 1e-12)), _PREFIXES[-1])
    return f"{value / factor:.{digits}g} {prefix}{unit}".replace("-", "−")


def frequency_text(hz: float) -> str:
    return si_text(hz, "Hz")


def time_text(seconds: float) -> str:
    return si_text(seconds, "s")
