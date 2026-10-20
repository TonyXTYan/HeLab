"""Display units of every plot (Tony, 2026-10-20): T always in ms and X and Y always in mm, with
their digits grouped by thousands, "," between groups and "." before decimals whatever the
locale: ``20,450.1234 ms``. The TXY columns stay in s and m (``stats.UNITS``), as do stored
settings: only what is drawn and written is scaled.

- Positions and lengths along T, X and Y: ``axis_text``, ``time_text``, ``length_text``,
  ``range_text`` and, with a standard error, ``estimate_text``; axis ticks: ``tick_strings``
  (``helab.analysis.plot_axes.GroupedAxis`` draws them).
- Everything else keeps its SI prefix (``si_text``): frequencies (Hz, kHz), constants such as the
  fall distance, and durations that aren't positions on the T axis (a fall time, gaps between
  shots, elapsed times).

No Qt, no I/O.
"""
from __future__ import annotations

import math
import re
from decimal import Decimal

from helab.analysis.estimates import (MINUS, SI_PREFIX_BY_EXPONENT, Estimate, Style, decimal_exponent, format_fixed,
                                      si_prefix)

T_UNIT, T_SCALE = "ms", 1e3
LENGTH_UNIT, LENGTH_SCALE = "mm", 1e3
AXIS_NAMES = ("T", "X", "Y")  # the TXY columns, in order (``stats.AXES``)
# Each axis's display unit and its factor from the data's s or m.
AXIS_UNITS: dict[str, tuple[str, float]] = {"T": (T_UNIT, T_SCALE), "X": (LENGTH_UNIT, LENGTH_SCALE),
                                            "Y": (LENGTH_UNIT, LENGTH_SCALE)}
POSITION_DIGITS = 9  # significant digits a position keeps (trailing zeros dropped): 20,450.1234 ms
POSITION_DECIMALS = 4  # … and at most these decimals: 2,137.4758 ms
WIDTH_DIGITS = 4  # for a width along an axis (a bin, a σ): 0.1235 ms
MAX_DECIMALS = 12


def _name(axis: str | int) -> str:
    return AXIS_NAMES[axis] if isinstance(axis, int) else axis


def axis_unit(axis: str | int) -> str:
    """The unit an axis (``"T"``, ``"X"``, ``"Y"`` or its column 0–2) is shown in: ms or mm."""
    return AXIS_UNITS[_name(axis)][0]


def axis_scale(axis: str | int) -> float:
    """The factor from the data's unit (s or m) to the axis's display unit: 1,000 for each."""
    return AXIS_UNITS[_name(axis)][1]


def axis_label(axis: str | int) -> str:
    """An axis's title: ``T (ms)``, ``X (mm)``."""
    return f"{_name(axis)} ({axis_unit(axis)})"


def grouped(value: float, decimals: int) -> str:
    """``value`` with ``decimals`` decimals and its digits grouped by thousands: ``20,450.12``,
    ``−1,000``. Always "," and "." (Python's format, not the locale's); "−" (U+2212) for minus,
    never on a zero; ``–`` when it isn't a number."""
    if not math.isfinite(value):
        return "–"
    text = f"{value:,.{max(int(decimals), 0)}f}"
    if text.startswith("-") and float(text.replace(",", "")) == 0:
        text = text[1:]
    return text.replace("-", MINUS)


def number_text(value: float, digits: int = POSITION_DIGITS) -> str:
    """``value`` to ``digits`` significant digits (never dropping a whole-number digit), grouped
    by thousands, trailing zeros dropped: ``0.5``, ``999.9``, ``1,000``, ``20,450.1234``. A
    position (the default ``digits``) keeps at most ``POSITION_DECIMALS`` decimals: 0.1 µs in ms,
    0.1 µm in mm; a width (fewer digits) as many as its digits need."""
    if not math.isfinite(value):
        return "–"
    most = POSITION_DECIMALS if digits >= POSITION_DIGITS else MAX_DECIMALS
    decimals = min(max(int(digits) - 1 - decimal_exponent(value), 0), most)
    text = grouped(value, decimals)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == MINUS + "0" else text


def axis_text(axis: str | int, value: float, digits: int = POSITION_DIGITS) -> str:
    """A value along an axis (data in s or m) in its display unit: ``20,450.1234 ms``, ``−2.5 mm``."""
    return f"{number_text(value * axis_scale(axis), digits)} {axis_unit(axis)}"


def time_text(seconds: float, digits: int = POSITION_DIGITS) -> str:
    """A time on the T axis, or a width along it (``digits=WIDTH_DIGITS``), in ms."""
    return axis_text("T", seconds, digits)


def length_text(metres: float, digits: int = POSITION_DIGITS) -> str:
    """A position or width along X or Y, in mm."""
    return axis_text("X", metres, digits)


def range_text(axis: str | int, low: float, high: float, digits: int = POSITION_DIGITS) -> str:
    """``T 20,450–20,550 ms``, ``X −2–3.5 mm``: an axis's name and both ends in its unit."""
    scale = axis_scale(axis)
    return (f"{_name(axis)} {number_text(low * scale, digits)}–{number_text(high * scale, digits)} "
            f"{axis_unit(axis)}")


GROUPABLE = re.compile(r"(?<![\d.])\d{4,}")


def group_digits(text: str) -> str:
    """Thousands groups in every whole number of ``text`` (digits after a "." are left alone):
    ``(20450.12 ± 0.12) ms`` → ``(20,450.12 ± 0.12) ms``."""
    return GROUPABLE.sub(lambda match: f"{int(match.group()):,}", text)


def estimate_text(axis: str | int, estimate: Estimate, style: Style = "pm", digits: int = 2) -> str:
    """A value ± its SE along an axis (data in s or m), in its display unit, the error to
    ``digits`` significant digits and the value to the same place: ``(20,450.12 ± 0.12) ms``."""
    scale = axis_scale(axis)
    return group_digits(format_fixed(estimate.value * scale, estimate.se * scale, style, axis_unit(axis), digits))


def tick_strings(values: list[float], scale: float, spacing: float) -> list[str]:
    """Tick labels grouped by thousands, with the decimals the tick spacing needs (as pyqtgraph
    picks them, but never in exponent form, and enough to write the spacing itself): spacing 100
    → ``20,400``, 0.5 → ``20,450.5``, 2.5 → ``12,002.5``, 0.25 → ``0.75``."""
    step = abs(spacing * scale)
    places = 0
    if math.isfinite(step) and step > 0:
        places = max(0, math.ceil(-math.log10(step)))
        while places < MAX_DECIMALS and abs(round(step, places) - step) > 1e-9 * step:
            places += 1
    return [grouped(value * scale, min(places, MAX_DECIMALS)) for value in values]


def si_text(value: float, unit: str, digits: int = 4) -> str:
    """``value`` with one SI prefix (``estimates.si_prefix``: y…Y, as the spin boxes pick them) and
    ``digits`` significant figures: ``1.25 kHz``, ``50 ns``, ``0 Hz``, ``−2 mm``; ``–`` when it
    isn't a number. Rounded before the prefix is chosen, with carry: 0.99999 ms is ``1 ms``, never
    ``1000 µs``. For what isn't a T, X or Y position (those are always in ms or mm: ``axis_text``)."""
    if not math.isfinite(value):
        return "–"
    if value == 0:
        return f"0 {unit}"
    digits = max(int(digits), 1)
    value = float(f"{value:.{digits}g}")
    exponent, prefix = si_prefix(value)
    scaled = float(Decimal(value).scaleb(-exponent))
    text = f"{scaled:.{digits}g}"
    if abs(float(text)) >= 1000 and exponent < 24:  # float noise carried it over: the next prefix
        exponent += 3
        prefix = SI_PREFIX_BY_EXPONENT[exponent]
        text = f"{float(Decimal(value).scaleb(-exponent)):.{digits}g}"
    return f"{text} {prefix}{unit}".replace("-", MINUS)


def frequency_text(hz: float) -> str:
    return si_text(hz, "Hz")
