"""Short number labels shared by Folder details, Settings and the log."""
from typing import Optional


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
