"""A raw DLD file (``d<N>.txt``: ``channel,time`` lines in TDC bins) to channel and time arrays,
exactly as MATLAB's converter reads it.

MATLAB reads with ``textscan(fid, '%f64%f64', 'Delimiter', ',', 'MultipleDelimsAsOne', 0,
'ReturnOnError', true, 'CollectOutput', true)`` (``tdc_importer`` at the end of
``dld_read_5channels_reconst_multi_imp.m``). What that does, measured with MATLAB R2025b
(``.ai/sessions/2026-10-29-claude-txy-reference/notes.md``):

- fields are numbers (sign, digits, a point, an exponent written ``e`` or ``d``) or
  ``Inf``/``NaN`` in any case; spaces, tabs and backspaces around them are skipped;
- a comma ends a field. The first non-blank line's ending sets which endings end a line: after
  ``\\r\\n``, all of ``\\r\\n``, ``\\r`` and ``\\n``; after ``\\n``, only ``\\n`` (a later ``\\r`` is
  a character like any other, so it stops the read); after ``\\r``, only ``\\r`` (a later ``\\n``
  stops it); ``\\r\\r\\n`` counts as ``\\r\\n``, ``\\n\\r`` as ``\\n``. Blank lines before it don't count. An empty field between commas or at a line's
  start reads as NaN; a line ended early is filled with NaN; blank lines and a comma ending a
  full line are ignored;
- a field followed directly by something that isn't a comma, an end of line or a blank is ended
  there, and the rest starts the next field (``0,12abc`` reads 0, 12 and then fails);
- the first field that isn't a number stops the read: a half-read line is kept, filled with NaN,
  a line not yet started is not. A file that ends mid-line is read the same way (``1,`` and ``1``
  give 1, NaN; ``1,3`` of ``1,300`` gives 1, 3);
- an empty file gives no rows. The file is read as bytes: a UTF-8 BOM stops the read at once.

Raw files as the TDC writes them (``\\d+,\\d+\\r\\n`` lines, or all ``\\n``) take a fast path with the
same result; a file mixing line endings takes the general reader.

The done-writing checks (unchanged for ``SETTLE_SECONDS``, ending in a newline, the first line on
the trigger channel) are stage 4's and go at the end of this module; MATLAB reads whatever
is there, and so does ``parse_raw``.

Qt-free; standard library and NumPy only.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
import re

import numpy as np
import numpy.typing as npt

Floats = npt.NDArray[np.float64]

# A whole file of well-formed TDC lines, all with one line ending.
_STRICT_CRLF = re.compile(rb"(?:[0-9]+,[0-9]+\r\n)*")
_STRICT_LF = re.compile(rb"(?:[0-9]+,[0-9]+\n)*")
# One numeric field as textscan's %f reads it (it backtracks: "1e" reads 1, "-" reads nothing).
_NUMBER = re.compile(rb"[+-]?(?:(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?|[iI][nN][fF]|[nN][aA][nN])")
_BLANK = b" \t\b"
_EOL = b"\r\n"
_LEADING = re.compile(rb"[ \t\b\r\n]*")
_LINE_END = re.compile(rb"\r+\n?|\n")
_COLUMNS = 2


@dataclass(frozen=True)
class RawPulses:
    """The rows of a raw file in file order: ``channels[i]`` and ``times[i]`` (TDC bins), both
    float64 as MATLAB holds them, NaN where textscan filled a field."""
    channels: Floats
    times: Floats

    def __post_init__(self) -> None:
        if self.channels.shape != self.times.shape or self.channels.ndim != 1:
            raise ValueError("channels and times must be 1-D arrays of one length")

    def __len__(self) -> int:
        return int(self.channels.shape[0])


def read_raw(path: str | os.PathLike[str]) -> RawPulses:
    with open(path, "rb") as file:
        return parse_raw(file.read())


def parse_raw(data: bytes) -> RawPulses:
    if _STRICT_CRLF.fullmatch(data) or _STRICT_LF.fullmatch(data):
        return _parse_strict(data)
    return _parse_textscan(data)


def _parse_strict(data: bytes) -> RawPulses:
    fields = data.replace(b"\r\n", b"\n").replace(b"\n", b",").split(b",")[:-1]
    # int → float64 rounds to nearest like textscan's decimal conversion (exact below 2^53).
    values = np.array([int(field) for field in fields], dtype=np.float64).reshape(-1, _COLUMNS)
    return _pulses(values)


def _parse_textscan(data: bytes) -> RawPulses:
    rows: list[float] = []
    row: list[float] = []
    # Blank lines first are skipped whatever their endings; the first line's ending sets the rest.
    pos, end = _LEADING.match(data).end(), len(data)  # type: ignore[union-attr]
    first = _LINE_END.search(data, pos)
    eol = _EOL if first is None or first.group().endswith(b"\r\n") else first.group()[:1]

    def finish() -> None:
        rows.extend(row + [math.nan] * (_COLUMNS - len(row)))
        row.clear()

    while True:
        while pos < end and data[pos] in _BLANK:
            pos += 1
        if pos >= end:
            if row:
                finish()
            break
        char = data[pos]
        if char in eol:
            pos += 2 if eol == _EOL and data[pos:pos + 2] == b"\r\n" else 1
            if row:
                finish()
            continue
        if char == ord(","):
            row.append(math.nan)  # an empty field
            pos += 1
        else:
            match = _NUMBER.match(data, pos)
            if match is None:
                if row:
                    finish()
                break
            row.append(_number(match.group()))
            pos = match.end()
            while pos < end and data[pos] in _BLANK:
                pos += 1
            if pos < end and data[pos] == ord(","):
                pos += 1
        if len(row) == _COLUMNS:
            finish()
    return _pulses(np.array(rows, dtype=np.float64).reshape(-1, _COLUMNS))


def _number(text: bytes) -> float:
    return float(text.replace(b"d", b"e").replace(b"D", b"e"))


def _pulses(values: Floats) -> RawPulses:
    return RawPulses(channels=np.ascontiguousarray(values[:, 0]), times=np.ascontiguousarray(values[:, 1]))


# Stage 4: the done-writing checks go here, run before read_raw: refuse a raw file modified
# within SETTLE_SECONDS, whose size changes between checks, that doesn't end in a newline, or
# whose first line isn't on the profile's channel_trigger. Not part of MATLAB's read.
