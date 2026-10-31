"""A raw file's pulses as caching v2 stores them (the raw layer, stage 1): arrays plus the facts the
checks need, encoded so that decoding gives pulses every converter backend turns into byte-identical
TXY (stage 1 design addendum §6).

- **Compact** (``COMPACT``, ``i8-i64d-1``): a file the strict fast path read (``fastio.parse_strict``),
  every channel an integer in 0–127 and every time below 2^62 (each is then an integer float64, so
  its int64 is exact, and so are the deltas). Arrays ``channel`` (``|i1``) and ``time`` (``<i8``: row
  0's time, then each row's delta from the one before), in **row 0 first, then the other rows in
  stable time order**. Every backend and ``split`` read only ``times[0]`` and a stable argsort of the
  times (``numpy_backend``, ``reference``, ``split.sorted_rows``): row 0 sorts first among equal times
  either way, and the rest keep their file order among equals, so the sorted rows are the same.
  Sorted times compress better (deltas ≥ 0).
- **Float** (``FLOAT``, ``f64-1``): any other file (the general reader: NaN, signs, decimals, other
  line endings, …): ``channels`` and ``times`` (``<f8``) exactly as ``raw.parse_raw`` gives them, in
  file order.

``Facts`` keep what the done-writing checks read from the text (``raw.not_done``), so ``not_done``
here gives the same answer without the file, for any trigger channel.

``RAW_PARSER_VERSION`` is bumped only when ``parse_raw``'s output changes for some input: a layer of
an older parser is then read again from its file while that file is there.

Qt-free; standard library, NumPy and ``helab.utils.hlb``.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

import numpy as np
import numpy.typing as npt

from helab.convert import fastio, raw
from helab.convert.raw import RawPulses
from helab.utils import hlb

RAW_PARSER_VERSION = 1
COMPACT = "i8-i64d-1"
FLOAT = "f64-1"
ENCODINGS = (COMPACT, FLOAT)
KIND = "raw"
# Times at or above this keep the float encoding (an int64 delta of two of them can't overflow).
_TIME_LIMIT = float(2 ** 62)
_CHANNEL_LIMIT = 127
_ENDINGS = ("none", "crlf", "lf", "cr", "mixed")
_READERS = ("strict", "general")


@dataclass(frozen=True)
class Facts:
    """What the done-writing checks and the converter read from a raw file's text: ``rows`` parsed,
    ``t_zero`` (the first row's time, NaN for none), ``first_channel`` (the integer ``not_done`` reads
    on the first line, None when it finds none), ``blank`` (nothing but whitespace), ``final_newline``,
    ``line_endings`` (``none``, ``crlf``, ``lf``, ``cr``, ``mixed``) and ``reader`` (``strict`` or
    ``general``)."""
    rows: int
    t_zero: float
    first_channel: int | None
    blank: bool
    final_newline: bool
    line_endings: str
    reader: str

    def to_json(self) -> dict[str, Any]:
        return {"rows": self.rows, "t_zero": repr(self.t_zero), "first_channel": self.first_channel,
                "blank": self.blank, "final_newline": self.final_newline, "line_endings": self.line_endings,
                "reader": self.reader}

    @classmethod
    def from_json(cls, value: Any) -> Facts:
        """``to_json``'s object back (``hlb.HlbError`` for anything else)."""
        if not isinstance(value, dict):
            raise hlb.HlbError("The raw layer's facts aren't an object")
        try:
            rows, t_zero, first = value["rows"], float(value["t_zero"]), value["first_channel"]
            flags = (value["blank"], value["final_newline"])
            endings, reader = value["line_endings"], value["reader"]
        except (KeyError, TypeError, ValueError) as exc:
            raise hlb.HlbError(f"The raw layer's facts are malformed ({exc})") from None
        if (not isinstance(rows, int) or isinstance(rows, bool) or rows < 0
                or not (first is None or isinstance(first, int) and not isinstance(first, bool))
                or not all(isinstance(flag, bool) for flag in flags)
                or endings not in _ENDINGS or reader not in _READERS):
            raise hlb.HlbError("The raw layer's facts are malformed")
        return cls(rows, t_zero, first, flags[0], flags[1], endings, reader)


@dataclass(frozen=True)
class RawLayer:
    """A raw file's layer: its ``encoding`` (``COMPACT`` or ``FLOAT``), ``arrays`` and ``facts``."""
    encoding: str
    arrays: dict[str, npt.NDArray[Any]]
    facts: Facts

    @property
    def pulses(self) -> int:
        return self.facts.rows


def _endings(data: bytes) -> str:
    crlf = data.count(b"\r\n")
    cr, lf = data.count(b"\r") - crlf, data.count(b"\n") - crlf
    kinds = [name for name, count in (("crlf", crlf), ("lf", lf), ("cr", cr)) if count]
    return "none" if not kinds else kinds[0] if len(kinds) == 1 else "mixed"


def facts_of(data: bytes, pulses: RawPulses, strict: bool) -> Facts:
    first = raw._FIRST_FIELD.match(data, len(data) - len(data.lstrip(b"\r\n")))
    return Facts(rows=len(pulses), t_zero=float(pulses.times[0]) if len(pulses) else math.nan,
                 first_channel=None if first is None else int(first.group(1)), blank=not data.strip(),
                 final_newline=data.endswith(b"\n"), line_endings=_endings(data),
                 reader="strict" if strict else "general")


def encode(data: bytes) -> RawLayer:
    """The layer of a raw file's bytes, read as ``raw.parse_raw`` reads them."""
    strict = fastio.parse_strict(data)
    if strict is None:
        pulses = raw.parse_raw(data)  # (The general reader: parse_strict says None again at once.)
    else:
        pulses = RawPulses(channels=strict[0], times=strict[1])
    facts = facts_of(data, pulses, strict is not None)
    channels, times = pulses.channels, pulses.times
    # (The strict path reads only digits: every value is a non-negative integer float64.)
    compact = strict is not None and (not len(pulses) or (
        float(channels.max()) <= _CHANNEL_LIMIT and float(times.max()) < _TIME_LIMIT))
    if not compact:
        return RawLayer(FLOAT, {"channels": np.ascontiguousarray(channels, dtype="<f8"),
                                "times": np.ascontiguousarray(times, dtype="<f8")}, facts)
    order = np.concatenate((np.zeros(min(1, len(times)), dtype=np.intp),
                            1 + np.argsort(times[1:], kind="stable"))) if len(times) else np.empty(0, np.intp)
    ticks = times[order].astype(np.int64)
    deltas = np.empty_like(ticks)
    if len(ticks):
        deltas[0] = ticks[0]
        np.subtract(ticks[1:], ticks[:-1], out=deltas[1:])
    return RawLayer(COMPACT, {"channel": channels[order].astype("|i1"), "time": deltas.astype("<i8")}, facts)


_ARRAYS: dict[str, dict[str, np.dtype[Any]]] = {COMPACT: {"channel": np.dtype("|i1"), "time": np.dtype("<i8")},
                                                 FLOAT: {"channels": np.dtype("<f8"), "times": np.dtype("<f8")}}


def check(layer: RawLayer) -> None:
    """``hlb.HlbError`` unless the layer's arrays are its encoding's, 1-D, one per row."""
    expected = _ARRAYS.get(layer.encoding)
    if expected is None:
        raise hlb.HlbError(f"Raw layer encoding {layer.encoding!r} isn't one this HeLab reads")
    for name, dtype in expected.items():
        array = layer.arrays.get(name)
        if array is None or array.dtype != dtype or array.shape != (layer.facts.rows,):
            raise hlb.HlbError(f"The raw layer's {name!r} array is missing, of the wrong type or length")


def decode(layer: RawLayer) -> RawPulses:
    """The pulses a layer holds (``COMPACT``: in its stored order; ``FLOAT``: in file order)."""
    check(layer)
    arrays = layer.arrays
    if layer.encoding == COMPACT:
        channels = arrays["channel"].astype(np.float64)
        times = np.cumsum(arrays["time"], dtype=np.int64).astype(np.float64)
    else:
        channels, times = arrays["channels"].astype(np.float64), arrays["times"].astype(np.float64)
    return RawPulses(channels=channels, times=times)


def not_done(facts: Facts, channel_trigger: int) -> tuple[str, str] | None:
    """``raw.not_done`` of the file the facts were taken from: the same code and message."""
    if facts.blank:
        return raw.NO_ROWS, "The raw file has no rows (0 bytes or blank lines only)"
    if not facts.final_newline:
        return raw.NO_FINAL_NEWLINE, "The raw file doesn't end with a newline: it may still be being written"
    if facts.first_channel is None or facts.first_channel != channel_trigger:
        found = "no channel" if facts.first_channel is None else f"channel {facts.first_channel}"
        return raw.NOT_TRIGGER_FIRST, (f"The raw file's first line is on {found}, not the trigger channel "
                                       f"{channel_trigger}: it may not be a whole shot")
    return None


def to_hlb(layer: RawLayer, *, maker: Mapping[str, Any] | None = None,
           meta: Mapping[str, Any] | None = None) -> bytes:
    """The layer as a ``.hlb`` container (``kind`` ``raw``); ``meta`` adds fields (the file's name and
    fingerprint, for a file found alone)."""
    return hlb.pack(layer.arrays, kind=KIND, maker=maker, meta={
        **(meta or {}), "encoding": layer.encoding, "parser": RAW_PARSER_VERSION, "facts": layer.facts.to_json()})


def from_hlb(data: bytes) -> tuple[RawLayer, dict[str, Any]]:
    """A container's layer and its header (``hlb.HlbError`` if it isn't a raw layer this HeLab reads)."""
    header, arrays = hlb.unpack(data)
    meta = header.get("meta", {})
    if header.get("kind") != KIND or meta.get("encoding") not in ENCODINGS:
        raise hlb.HlbError("Not a raw layer this HeLab reads")
    layer = RawLayer(str(meta["encoding"]), arrays, Facts.from_json(meta.get("facts")))
    check(layer)
    return layer, header
