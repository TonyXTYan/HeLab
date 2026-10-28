"""Sample shots whose reference TXY isn't the 2019 converter's output for the raw file as it is
now, each with a proof the checker runs again every time (not just a note).

- ``cut``: MATLAB read the raw file while it was still being written. The proof: our output for
  the raw file cut after ``lines`` lines is the reference, byte for byte.
- ``profile``: another MATLAB variant re-converted the shot later. The proof: our output with the
  profile changed by ``changes`` is the reference.

Keyed by sample set, shot and the reference TXY's SHA-256, so a changed reference is no longer
excused. The checker fails on any mismatch not listed here and on a listed one whose proof fails.

Found by the builder on 2026-10-29 (``.ai/sessions/2026-10-29-claude-txy-reference/notes.md``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from helab.convert.check import check_txy
from helab.convert.pipeline import convert_raw
from helab.convert.profile import DetectorProfile
from helab.convert.reconstruct import NoRowsError


@dataclass(frozen=True)
class Exception_:
    kind: str  # "cut" or "profile"
    why: str
    lines: int = 0
    changes: dict[str, Any] = field(default_factory=dict)


EXCEPTIONS: dict[tuple[str, int, str], Exception_] = {
    ("2019-halos-old-plates", 3667, "832daf96e6a010da4e2c9f577b87a0ccba7dbfa08ecc0929966fefe35cc3519f"): Exception_(
        "cut", "TXY written 0.25 s after the raw file's last change: MATLAB read it half-written "
               "(identical when cut to 40,956-40,966 of 41,092 lines)", lines=40956),
    ("2022-07-old-plates-he3he4", 3, "66724120c76cb6d473dffe077098aadd0106473eaa2182b3c9f1b7115aff394a"): Exception_(
        "profile", "re-converted 2023-02-08 by a third MATLAB variant: matlab-2019 plus a 2 us x1 dead time",
        changes={"dead_time_x1": 2e-6}),
    ("2022-11-ghost-counts-mcp", 5, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"): Exception_(
        "profile", "trigger-only raw file, no hits; the 0-byte TXY (written 54 days later) comes from a "
                   "wrapper that writes empty files, as the 2023 dld_raw_to_txy does",
        changes={"write_empty_txy": True}),
}


def prove(exception: Exception_, raw: bytes, reference: bytes, profile: DetectorProfile, backend: str) -> bool:
    if exception.kind == "cut":
        cut = b"".join(raw.splitlines(keepends=True)[:exception.lines])
        data, used = cut, profile
    else:
        data, used = raw, profile.replace(**exception.changes)
    try:
        ours = convert_raw(data, used, backend)
    except NoRowsError:
        ours = None
    return check_txy(ours, reference).identical
