"""The byte checker: a converted TXY against a reference one, and the proofs for references that
aren't the converter's output for the raw file as it is now.

Identical means byte for byte. On a mismatch the result names the first differing line (1-based)
with both sides' text, ``ENDED`` where one side has no such line, and the line marked
``NO_FINAL_NEWLINE`` where the sides differ only in one lacking the final newline; and each side's
hit count (its lines). ``None`` for a whole side means no file: MATLAB's ``dld_raw_to_txy_counts``
writes none for an empty result, and ours matches it only by writing none too.

A ``ReferenceFault`` says why a reference differs and ``prove_fault`` checks it again from the
raw file, so a listed exception is never just taken on trust:

- ``cut``: MATLAB read the raw file while it was still being written; converting the raw file
  cut after ``lines`` lines gives the reference.
- ``variant``: another MATLAB variant made it; converting with the profile changed by
  ``changes`` gives the reference.
- ``empty``: no hits, and the reference is a 0-byte file from a wrapper that writes empty files;
  our profile writes no file, and with ``write_empty_txy`` on we write exactly 0 bytes.

``convert_via_layer`` converts through caching v2's raw layer (``raw_layer``: encoded, packed as a
``.hlb``, read back and decoded, all in memory), for the sample checker's ``--via-layer``: its output
must equal ``convert_raw``'s byte for byte.

Qt-free; standard library and NumPy only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from helab.convert.pipeline import convert_raw
from helab.convert.profile import DetectorProfile
from helab.convert.reconstruct import DEFAULT_BACKEND, NoRowsError, reconstruct
from helab.convert.txy import format_txy

ENDED = "(ended)"
NO_FINAL_NEWLINE = " (no final newline)"
FAULT_KINDS = ("cut", "variant", "empty")


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
    ours_lines, reference_lines = _lines(ours), _lines(reference)
    for index in range(max(len(ours_lines), len(reference_lines))):
        a = ours_lines[index] if index < len(ours_lines) else ENDED
        b = reference_lines[index] if index < len(reference_lines) else ENDED
        if a != b:
            return CheckResult(False, ours_hits, reference_hits, line=index + 1, ours_line=a, reference_line=b)
    # The same lines: one side lacks the final newline.
    last = ours_lines[-1]
    return CheckResult(False, ours_hits, reference_hits, line=len(ours_lines),
                       ours_line=last + ("" if ours.endswith(b"\n") else NO_FINAL_NEWLINE),
                       reference_line=last + ("" if reference.endswith(b"\n") else NO_FINAL_NEWLINE))


@dataclass(frozen=True)
class ReferenceFault:
    kind: str
    why: str
    lines: int = 0
    changes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in FAULT_KINDS:
            raise ValueError(f"A reference fault is one of {FAULT_KINDS}, not {self.kind!r}")


def prove_fault(fault: ReferenceFault, raw: bytes, reference: bytes, profile: DetectorProfile,
                backend: str = DEFAULT_BACKEND) -> bool:
    """Whether the fault explains the reference: the conversion it names gives it byte for byte."""
    if fault.kind == "cut":
        cut = b"".join(raw.splitlines(keepends=True)[:fault.lines])
        return check_txy(_convert(cut, profile, backend), reference).identical
    if fault.kind == "variant":
        return check_txy(_convert(raw, profile.replace(**fault.changes), backend), reference).identical
    return (reference == b"" and _convert(raw, profile.replace(write_empty_txy=False), backend) is None
            and _convert(raw, profile.replace(write_empty_txy=True), backend) == b"")


def convert_via_layer(data: bytes, profile: DetectorProfile, backend: str = DEFAULT_BACKEND) -> bytes | None:
    """``convert_raw`` of the raw file's layer instead of its text: nothing is written anywhere."""
    from helab.convert import raw_layer
    layer, _ = raw_layer.from_hlb(raw_layer.to_hlb(raw_layer.encode(data)))
    hits = reconstruct(raw_layer.decode(layer), profile, backend)
    if hits.shape[0] == 0 and not profile.write_empty_txy:
        return None
    return format_txy(hits)


def _convert(data: bytes, profile: DetectorProfile, backend: str) -> bytes | None:
    try:
        return convert_raw(data, profile, backend)
    except NoRowsError:
        return None


def _lines(data: bytes) -> list[str]:
    """The lines, without the empty piece after a final newline."""
    if not data:
        return []
    pieces = data.split(b"\n")
    if data.endswith(b"\n"):
        pieces.pop()
    return [piece.decode("ascii", errors="backslashreplace") for piece in pieces]


def _count(data: bytes) -> int:
    """Lines, counting a last one without its newline."""
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def _hits(count: int | None) -> str:
    return "no file" if count is None else f"{count} hits"
