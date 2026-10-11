"""Short number labels shared by Folder details, Settings and the log."""
from typing import Optional


def byte_size(num: int | float) -> str:
    """Sizes in binary units, as budgets are set: ``850 B``, ``706 MB``, ``1.2 GB``, ``8.0 GB``."""
    value = max(0.0, float(num))
    unit = "B"
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if value < 1023.5 or unit == "TB":
            break
        value /= 1024
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
