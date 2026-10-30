"""Short number labels shared by Folder details, Settings and the log."""
import os
import sys
from typing import Literal, Mapping, Optional

# What a byte count measures (Tony, Q26.1): a size on disk (files, folders, the disk cache and its
# budget, read rates) is in SI units on macOS and Linux and in powers of 1024 on Windows, as each
# OS's own file manager shows it; RAM is in powers of 1024 on every OS. Every call says which.
ByteKind = Literal["disk", "ram"]
SI_UNITS = ("B", "kB", "MB", "GB", "TB")
BINARY_UNITS = ("B", "KiB", "MiB", "GiB", "TiB")
# The platform whose disk units HeLab shows: ``sys.platform``, unless this variable names another
# (the tests pin ``darwin``; ``win32`` shows Windows' units on a Mac). Read once, at import.
UNITS_PLATFORM_OVERRIDE = "HELAB_UNITS_PLATFORM_OVERRIDE"


def units_platform(environ: Mapping[str, str]) -> str:
    return environ.get(UNITS_PLATFORM_OVERRIDE) or sys.platform


PLATFORM = units_platform(os.environ)


def binary_units(kind: ByteKind, platform: Optional[str] = None) -> bool:
    """Powers of 1024 (KiB…): RAM everywhere, disk on Windows. ``platform`` defaults to ``PLATFORM``."""
    return kind == "ram" or (platform or PLATFORM) == "win32"


def byte_unit(power: int, kind: ByteKind, platform: Optional[str] = None) -> tuple[int, str]:
    """``base ** power`` bytes and its label: ``byte_unit(3, "disk")`` is ``(10**9, "GB")`` on macOS
    and Linux, ``(2**30, "GiB")`` on Windows; ``byte_unit(3, "ram")`` is ``(2**30, "GiB")``."""
    binary = binary_units(kind, platform)
    return (1024 if binary else 1000) ** power, (BINARY_UNITS if binary else SI_UNITS)[power]


def scaled(num: int | float, kind: ByteKind, platform: Optional[str] = None) -> tuple[float, str]:
    """``num`` bytes in the largest unit that keeps it under 999.5 (TB or TiB at most)."""
    base, units = (1024, BINARY_UNITS) if binary_units(kind, platform) else (1000, SI_UNITS)
    value = max(0.0, float(num))
    unit = units[0]
    for unit in units:
        if value < 999.5 or unit == units[-1]:
            break
        value /= base
    return value, unit


def byte_size(num: int | float, kind: ByteKind, *, platform: Optional[str] = None) -> str:
    """A size in ``kind``'s units (``binary_units``): ``850 B``, ``706 MB``, ``1.2 GB``, ``8.6 GB``
    in SI; ``706 MiB``, ``1.2 GiB``, ``8.0 GiB`` in powers of 1024."""
    value, unit = scaled(num, kind, platform)
    return f"{value:.0f} {unit}" if unit == "B" or value >= 99.95 else f"{value:.1f} {unit}"


def fnum(num: Optional[int]) -> str:
    """
    Format a number with a suffix for thousands, millions, etc.
    :param num: The number to format
    :return:    The formatted number

    e.g.

    - `fnum(123)`  -> `'   123'`
    - `fnum(1234)` -> `'1.234K'`
    - `fnum(123000)`  -> `'123.0K'`
    - `fnum(1234567)` -> `'1.235M'`
    - `fnum(123456789000)` -> `'123.5G'`
    """
    if num is None: return "NA"
    suffixes = ['K', 'M', 'G', 'T', 'P', 'E']
    for i, suffix in reversed(list(enumerate(suffixes, 1))):
        divisor = 1000 ** i
        if num >= divisor:
            val = num / divisor
            decimals = 3 if val < 10 else 2 if val < 100 else 1
            formatted = f"{val:.{decimals}f}{suffix}"
            return formatted.rjust(6)[-6:]
    return f"{num}".rjust(6)[-6:]
