"""The data file kinds a folder can hold, matched, counted and sized from one table.

A later format (e.g. another converter's output) is a new entry here, not a rewrite.
Imported by isolated helpers: nothing here may start Qt.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class FileKind:
    name: str
    # Group 1 is the shot number.
    pattern: re.Pattern[str]
    # Read into a dataset by a load.
    loaded: bool
    # Its total size is measured (one stat per file). Unmeasured kinds save no ``bytes``.
    sized: bool
    # Estimated bytes in RAM per byte on disk; 1.0 overestimates TXY (about 0.69x), the safe side.
    ram_per_byte: float = 1.0


RAW = FileKind("raw", re.compile(r"^d(\d+)\.txt$"), loaded=False, sized=False)
TXY = FileKind("txy", re.compile(r"^d_txy_forc(\d+)\.txt$"), loaded=True, sized=True)
FILE_KINDS: tuple[FileKind, ...] = (RAW, TXY)


def match(name: str) -> tuple[FileKind, int] | None:
    """The kind a file name belongs to, and its shot number."""
    for kind in FILE_KINDS:
        if found := kind.pattern.fullmatch(name):
            return kind, int(found.group(1))
    return None


def files_summary(shots: dict[str, set[int]], sizes: dict[str, int]) -> dict[str, dict[str, int]]:
    """A summary's ``files``: each kind's count, and ``bytes`` only where it was measured."""
    summary: dict[str, dict[str, int]] = {}
    for kind in FILE_KINDS:
        entry = {"count": len(shots.get(kind.name, ()))}
        if kind.sized and kind.name in sizes:
            entry["bytes"] = sizes[kind.name]
        summary[kind.name] = entry
    return summary


def valid_files(value: Any) -> bool:
    """A saved ``files`` entry: counts, and sizes where present, are non-negative integers."""
    return isinstance(value, dict) and all(
        isinstance(entry, dict) and type(entry.get("count")) is int and entry["count"] >= 0
        and ("bytes" not in entry or type(entry["bytes"]) is int and entry["bytes"] >= 0)
        for entry in value.values())


def raw_times(entries: Any) -> dict[int, int]:
    """Shot times as datasets carry them (``raw_times``: ``[shot, mtime_ns]`` of each shot's RAW
    file, where one was found), by shot. Malformed entries are skipped; none: no times known."""
    times: dict[int, int] = {}
    for entry in entries if isinstance(entries, (list, tuple)) else ():
        if isinstance(entry, (list, tuple)) and len(entry) == 2 and all(type(value) is int for value in entry):
            times[entry[0]] = entry[1]
    return times
