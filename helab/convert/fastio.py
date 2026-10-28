"""Fast text reading and writing for the converter, byte for byte as the general paths.

``parse_strict`` reads a raw file as the TDC writes it, every line ``<digits>,<digits>`` ended
by ``\\r\\n``, or every line by ``\\n`` (``raw._STRICT_CRLF``/``_STRICT_LF`` describe the same
files), with NumPy and no Python per value; anything else gives None and ``raw`` takes the
general reader, as does a field longer than 16 digits. Each field's digits are read eight at a
time from 64-bit words (SWAR) into an integer, converted to float64, which rounds to nearest
like textscan's decimal reading. NumPy releases the GIL for these steps.

``format_txy`` formats hits as ``dlmwrite(…, 'precision', 8)`` does: one ``%`` over a block of
rows (Python's ``%.8g``, the same conversion as ``txy.format_value``, done in C), with MATLAB's
spellings ``NaN``, ``Inf`` and ``-Inf`` put back afterwards (finite ``%.8g`` text never holds an
``n`` or an ``i``, so the replacement can't touch a number).

Qt-free; standard library and NumPy only.
"""
from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
import numpy.typing as npt

Floats = npt.NDArray[np.float64]
Hits = npt.NDArray[np.float64]

_COMMA, _CR, _LF = ord(","), ord("\r"), ord("\n")
_MAX_DIGITS = 16  # two 8-byte words per field
_PAD = 16  # zero bytes before the file, so every field has 16 bytes before its end
_BLOCK = 1 << 16  # rows formatted per ``%``, to bound the temporary tuple
# Eight ASCII digits in a little-endian word (first digit lowest) to their value: pairs, then
# fours, then all eight (each step's multiply wraps mod 2**64 by design). A cleared byte reads 0.
_SWAR = tuple((np.uint64(mask), np.uint64(factor), np.uint64(shift)) for mask, factor, shift in (
    (0x0F0F0F0F0F0F0F0F, 2561, 8), (0x00FF00FF00FF00FF, 6553601, 16), (0x0000FFFF0000FFFF, 42949672960001, 32)))
# _KEEP[k]: a word with its k lowest bytes cleared.
_KEEP = np.array([(~((1 << (8 * k)) - 1)) & 0xFFFFFFFFFFFFFFFF for k in range(9)], dtype=np.uint64)


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
    padded = np.concatenate((np.zeros(_PAD, dtype=np.uint8), a))
    channels = _digits(padded, start, comma)
    times = _digits(padded, comma + 1, end)
    if channels is None or times is None:
        return None
    return channels, times


def _digits(padded: npt.NDArray[np.uint8], start: npt.NDArray[np.intp],
            end: npt.NDArray[np.intp]) -> Floats | None:
    """The decimal value of each field ``a[start:end]`` (all digits; ``padded`` is ``a`` after
    ``_PAD`` zero bytes), or None when a field is empty or longer than 16 digits."""
    lengths = end - start
    if not len(lengths) or int(lengths.min()) < 1:
        return None
    longest = int(lengths.max())
    if longest > _MAX_DIGITS:
        return None
    if longest == 1:  # one digit each (the channels, usually)
        one: Floats = (padded[end + _PAD - 1] - ord("0")).astype(np.float64)
        return one
    # Each field right-aligned in 16 bytes, read as two words; the bytes before it cleared.
    block = sliding_window_view(padded, 16)[end + _PAD - 16].view(np.uint64)
    before = 16 - lengths
    block[:, 0] &= _KEEP[np.minimum(before, 8)]
    block[:, 1] &= _KEEP[np.maximum(before - 8, 0)]
    for mask, factor, shift in _SWAR:
        block = ((block & mask) * factor) >> shift
    values: Floats = (block[:, 0] * np.uint64(100_000_000) + block[:, 1]).astype(np.float64)
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
