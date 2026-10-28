"""The byte checker: a converted TXY against a reference one.

Identical means byte for byte. On a mismatch the result names the first differing line (1-based,
both sides' text, ``None`` where one side has ended) and each side's hit count (its lines).
``None`` for a whole side means no file: MATLAB's ``dld_raw_to_txy_counts`` writes none for an
empty result, and ours matches it only by writing none too.

Qt-free; standard library only.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CheckResult:
    identical: bool
    ours_hits: int | None
    reference_hits: int | None
    line: int | None = None
    ours_line: str | None = None
    reference_line: str | None = None

    def describe(self) -> str:
        if self.identical:
            return f"identical ({_hits(self.ours_hits)})"
        where = "" if self.line is None else (
            f", first difference at line {self.line}: ours {self.ours_line!r}, reference {self.reference_line!r}")
        return f"differs: ours {_hits(self.ours_hits)}, reference {_hits(self.reference_hits)}{where}"


def check_txy(ours: bytes | None, reference: bytes | None) -> CheckResult:
    ours_hits = None if ours is None else _count(ours)
    reference_hits = None if reference is None else _count(reference)
    if ours == reference:
        return CheckResult(True, ours_hits, reference_hits)
    if ours is None or reference is None:
        return CheckResult(False, ours_hits, reference_hits)
    ours_lines = ours.split(b"\n")
    reference_lines = reference.split(b"\n")
    for index in range(max(len(ours_lines), len(reference_lines))):
        a = ours_lines[index] if index < len(ours_lines) else None
        b = reference_lines[index] if index < len(reference_lines) else None
        if a != b:
            return CheckResult(False, ours_hits, reference_hits, line=index + 1, ours_line=_text(a),
                               reference_line=_text(b))
    raise AssertionError("unequal bytes split into equal lines")  # pragma: no cover


def _count(data: bytes) -> int:
    """Lines, counting a last one without its newline."""
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def _text(line: bytes | None) -> str | None:
    return None if line is None else line.decode("ascii", errors="backslashreplace")


def _hits(count: int | None) -> str:
    return "no file" if count is None else f"{count} hits"
