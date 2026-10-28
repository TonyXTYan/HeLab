"""Fast text reading and writing for the converter, byte for byte as the general paths.

``parse_strict`` reads a raw file as the TDC writes it, every line ``<digits>,<digits>`` ended
by ``\\r\\n``, or every line by ``\\n`` (``raw._STRICT_CRLF``/``_STRICT_LF`` describe the same
files), with NumPy and no Python per value; anything else gives None and ``raw`` takes the
general reader. A field longer than 18 digits (beyond int64) also gives None. The values are
the int64 digits converted to float64, which rounds to nearest like textscan's decimal reading.

``format_txy`` formats hits as ``dlmwrite(…, 'precision', 8)`` does: one ``%`` over a block of
rows (Python's ``%.8g``, the same conversion as ``txy.format_value``, done in C), with MATLAB's
spellings ``NaN``, ``Inf`` and ``-Inf`` put back afterwards (finite ``%.8g`` text never holds an
``n`` or an ``i``, so the replacement can't touch a number).

Qt-free; standard library and NumPy only.
"""
from __future__ import annotations

import numpy as np
import numpy.typing as npt

Floats = npt.NDArray[np.float64]
Hits = npt.NDArray[np.float64]

_COMMA, _CR, _LF = ord(","), ord("\r"), ord("\n")
_MAX_DIGITS = 18  # 10**18 − 1 fits in int64
_POWERS = 10 ** np.arange(_MAX_DIGITS, dtype=np.int64)
_BLOCK = 1 << 16  # rows formatted per ``%``, to bound the temporary tuple


def parse_strict(data: bytes) -> tuple[Floats, Floats] | None:
    """Channels and times of a strict raw file, or None when the file isn't strict."""
    if not data:
        return np.empty(0), np.empty(0)
    a = np.frombuffer(data, np.uint8)
    if a[-1] != _LF or bool((a > ord("9")).any()):
        return None
    # Everything below "0" is a separator; the rest are digits.
    sep = np.flatnonzero(a < ord("0"))
    crlf = a[-2] == _CR if len(a) > 1 else False
    width = 3 if crlf else 2
    if len(sep) % width:
        return None
    lines = sep.reshape(-1, width)
    pattern = np.array([_COMMA, _CR, _LF] if crlf else [_COMMA, _LF], dtype=np.uint8)
    if not bool((a[lines] == pattern).all()):
        return None
    comma, end = lines[:, 0], lines[:, 1]  # end: the \r or \n after the time
    if crlf and not bool((lines[:, 2] - end == 1).all()):
        return None
    start = np.empty(len(lines), dtype=np.intp)
    start[0] = 0
    start[1:] = lines[:-1, -1] + 1
    channels = _digits(a, start, comma)
    times = _digits(a, comma + 1, end)
    if channels is None or times is None:
        return None
    return channels, times


def _digits(a: npt.NDArray[np.uint8], start: npt.NDArray[np.intp], end: npt.NDArray[np.intp]) -> Floats | None:
    """The decimal value of each field ``a[start:end]`` (all digits), or None when a field is
    empty or too long for int64."""
    lengths = end - start
    if not len(lengths) or int(lengths.min()) < 1:
        return None
    width = int(lengths.max())
    if width > _MAX_DIGITS:
        return None
    # Each field right-aligned in a (fields, width) block; places before its start count 0.
    index = end[:, None] + np.arange(-width, 0)
    digits = a[np.maximum(index, 0)].astype(np.int64) - ord("0")
    digits[index < start[:, None]] = 0
    values: Floats = (digits @ _POWERS[width - 1::-1]).astype(np.float64)
    return values


def format_txy(hits: Hits) -> bytes:
    """``(n, 3)`` hits as dlmwrite precision-8 text (the caller checks the shape)."""
    parts = []
    for first in range(0, hits.shape[0], _BLOCK):
        block = hits[first:first + _BLOCK]
        parts.append(("%.8g,%.8g,%.8g\n" * block.shape[0]) % tuple(block.ravel().tolist()))
    text = "".join(parts).encode("ascii")
    if not bool(np.isfinite(hits).all()):
        text = text.replace(b"nan", b"NaN").replace(b"inf", b"Inf")
    return text
