"""A raw DLD file (``d<N>.txt``: ``channel,time`` lines in TDC bins) to channel and time arrays,
exactly as MATLAB's converter reads it.

MATLAB reads with ``textscan(fid, '%f64%f64', 'Delimiter', ',', 'MultipleDelimsAsOne', 0,
'ReturnOnError', true, 'CollectOutput', true)`` (``tdc_importer`` at the end of
``dld_read_5channels_reconst_multi_imp.m``). What that does, measured with MATLAB R2025b
(``.ai/sessions/2026-10-29-claude-txy-reference/notes.md``):

- fields are numbers (sign, digits, a point, an exponent written ``e`` or ``d``) or
  ``Inf``/``NaN`` in any case; spaces, tabs and backspaces around them are skipped;
- a comma ends a field. The first line ending (after any ``\\n`` at the very start) sets which
  endings end a line: after ``\\r\\n``, all of ``\\r\\n``, ``\\r`` and ``\\n``; after ``\\n``, only
  ``\\n`` (a later ``\\r`` is a character like any other, so it stops the read); after ``\\r``, only
  ``\\r`` (a later ``\\n`` stops it); ``\\r\\r\\n`` counts as ``\\r\\n``, ``\\n\\r`` as ``\\n``. The read
  then starts at the first byte in that mode (so in ``\\r`` mode a leading ``\\n`` stops it at
  once). An empty field between commas or at a line's
  start reads as NaN; a line ended early is filled with NaN; blank lines and a comma ending a
  full line are ignored;
- a field followed directly by something that isn't a comma, an end of line or a blank is ended
  there, and the rest starts the next field (``0,12abc`` reads 0, 12 and then fails);
- the first field that isn't a number stops the read: a half-read line is kept, filled with NaN,
  a line not yet started is not. A file that ends mid-line is read the same way (``1,`` and ``1``
  give 1, NaN; ``1,3`` of ``1,300`` gives 1, 3);
- an empty file gives no rows. The file is read as bytes: a UTF-8 BOM stops the read at once.

Raw files as the TDC writes them (``\\d+,\\d+\\r\\n`` lines, or all ``\\n``: ``_STRICT_CRLF`` and
``_STRICT_LF``) take a fast path with the same result (``fastio.parse_strict``, NumPy); any other
file, a mix of line endings for one, takes the general reader.

The done-writing checks are stage 4's, at the end of this module (MATLAB reads whatever is there,
and so does ``parse_raw``): ``settled_by_age`` (unmodified for the settle age, not dated in the
future) and ``not_done`` (no rows, no final newline, a first line off the trigger channel). The
helper's ``io_ops.convert`` adds the checks that need the file system: the size and mtime the same
at two checks and while the file is read.

Qt-free; standard library and NumPy only.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
import re

import numpy as np
import numpy.typing as npt

from helab.convert import fastio

Floats = npt.NDArray[np.float64]

# A whole file of well-formed TDC lines, all with one line ending: what fastio.parse_strict reads
# (its tests check it accepts exactly these).
_STRICT_CRLF = re.compile(rb"(?:[0-9]+,[0-9]+\r\n)*")
_STRICT_LF = re.compile(rb"(?:[0-9]+,[0-9]+\n)*")
# One numeric field as textscan's %f reads it (it backtracks: "1e" reads 1, "-" reads nothing).
_NUMBER = re.compile(rb"[+-]?(?:(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?|[iI][nN][fF]|[nN][aA][nN])")
_BLANK = b" \t\b"
_EOL = b"\r\n"
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
    strict = fastio.parse_strict(data)
    if strict is not None:
        return RawPulses(channels=strict[0], times=strict[1])
    return _parse_textscan(data)


def _parse_textscan(data: bytes) -> RawPulses:
    rows: list[float] = []
    row: list[float] = []
    # The mode: the first \r/\n run after any \n at the very start of the file (only \n are
    # skipped there). Reading starts at byte 0 in that mode (Lens's R2-1, MATLAB R2025b).
    pos, end = 0, len(data)
    first = _LINE_END.search(data, len(data) - len(data.lstrip(b"\n")))
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


# The done-writing checks (stage 4; not part of MATLAB's read). Evidence: 2019-halos d3667, which
# MATLAB converted 0.25 s after its last write and so lost the end of the shot.

# Why a raw file isn't converted yet, or can't be: the codes events carry (``io_ops.convert``).
SETTLING = "settling"  # modified within the settle age (or dated a little ahead of this computer's clock)
FUTURE = "future"  # dated well ahead of this computer's clock: the computers' clocks differ
CHANGED = "changed"  # its size or mtime differ between two checks, or changed while it was read
NO_FINAL_NEWLINE = "no_final_newline"  # the writer may be mid-line
NOT_TRIGGER_FIRST = "not_trigger_first"  # the first line isn't on the profile's trigger channel
NO_ROWS = "no_rows"  # 0 bytes or blank lines only: MATLAB fails on it (Q10.2)
# Not yet done: skipped now and looked at again when the file changes. A file still failing the
# format checks (NO_FINAL_NEWLINE, NOT_TRIGGER_FIRST, NO_ROWS) once unmodified for 20 s is damaged
# (``io_ops.convert.DAMAGED_SECONDS``, Q18.5): final, as are a failed read or conversion.
WAITING = (SETTLING, FUTURE, CHANGED, NO_FINAL_NEWLINE, NOT_TRIGGER_FIRST, NO_ROWS)

_FIRST_FIELD = re.compile(rb"[ \t]*([0-9]+)[ \t]*,")


def settled_by_age(mtime_ns: int, now: float, settle_seconds: float) -> bool:
    """Unmodified for ``settle_seconds`` as of ``now`` (seconds since the epoch), and not dated in
    the future; with no settle age (tests) every file is."""
    if settle_seconds <= 0:
        return True
    return mtime_ns / 1e9 <= now - settle_seconds


def not_done(data: bytes, channel_trigger: int) -> tuple[str, str] | None:
    """Why a settled raw file's bytes don't look finished: (code, message), or None. The TDC writes
    one ``channel,time`` line per pulse, the trigger's first, and ends every line, so a file that
    ends mid-line or starts on another channel is still being written (or isn't a whole shot)."""
    if not data.strip():
        return NO_ROWS, "The raw file has no rows (0 bytes or blank lines only)"
    if not data.endswith(b"\n"):  # (A lone \r at the end may be half of the TDC's \r\n.)
        return NO_FINAL_NEWLINE, "The raw file doesn't end with a newline: it may still be being written"
    first = _FIRST_FIELD.match(data, len(data) - len(data.lstrip(b"\r\n")))
    if first is None or int(first.group(1)) != channel_trigger:
        found = "no channel" if first is None else f"channel {int(first.group(1))}"
        return NOT_TRIGGER_FIRST, (f"The raw file's first line is on {found}, not the trigger channel "
                                   f"{channel_trigger}: it may not be a whole shot")
    return None
