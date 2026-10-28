"""Sample shots whose reference TXY isn't the 2019 converter's output for the raw file as it is
now, each with a proof the checker runs again every time (not just a note). Three classes:

- ``cut``: MATLAB read the raw file while it was still being written. The proof: our output for
  the raw file cut after ``lines`` lines is the reference, byte for byte.
- ``variant``: another MATLAB variant re-converted the shot later. The proof: our output with the
  profile changed by ``changes`` is the reference.
- ``empty``: no hits; 2019's ``dld_raw_to_txy_counts`` writes no file, but the reference is a
  0-byte file from a wrapper that writes empty ones (the 2023 ``dld_raw_to_txy``, and the lab's
  live converter in 2020: 2020-halos d400's was written 2 s after its raw file). The proof: we
  write no file, and with ``write_empty_txy`` on we write exactly the reference (0 bytes).

Keyed by sample set, shot and the reference TXY's SHA-256, so a changed reference is no longer
excused. The checker fails on any mismatch not listed here and on a listed one whose proof fails,
and reports each class apart from "identical".

Found by the builder (Forge) and the cross-checker (Lens) on 2026-10-29, each proof confirmed by
both (``.ai/sessions/2026-10-29-claude-txy-reference/notes.md``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from helab.convert.check import check_txy
from helab.convert.pipeline import convert_raw
from helab.convert.profile import DetectorProfile
from helab.convert.reconstruct import NoRowsError

KINDS = ("cut", "variant", "empty")
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
SECOND_2023_02 = "re-converted 2023-02-08 by a third MATLAB variant: matlab-2019 plus a 2 us x1 dead time"
EMPTY_WHY = "no hits; 2019 writes no file, the reference is 0 bytes (a wrapper that writes empty files)"


@dataclass(frozen=True)
class Exception_:
    kind: str
    why: str
    lines: int = 0
    changes: dict[str, Any] = field(default_factory=dict)


EXCEPTIONS: dict[tuple[str, int, str], Exception_] = {
    ("2019-halos-old-plates", 3667, "832daf96e6a010da4e2c9f577b87a0ccba7dbfa08ecc0929966fefe35cc3519f"): Exception_(
        "cut", "TXY written 0.25 s after the raw file's last change: MATLAB read it half-written "
               "(identical when cut to 40,956-40,966 of 41,092 lines)", lines=40956),
    ("2022-07-old-plates-he3he4", 2, "8179e4dffbf9cd28d1ae1950296caf89927230bf7e70bcf24f1fefc414423fc1"): Exception_(
        "variant", SECOND_2023_02, changes={"dead_time_x1": 2e-6}),
    ("2022-07-old-plates-he3he4", 3, "66724120c76cb6d473dffe077098aadd0106473eaa2182b3c9f1b7115aff394a"): Exception_(
        "variant", SECOND_2023_02, changes={"dead_time_x1": 2e-6}),
    # Written 2 s after its raw file (2020-08-06): the live autoconverter of 2020 wrote empty files.
    ("2020-halos-weak-trap", 400, EMPTY_SHA256): Exception_("empty", EMPTY_WHY),
    ("2022-11-ghost-counts-mcp", 5, EMPTY_SHA256): Exception_("empty", EMPTY_WHY),
    ("2023-02-new-plates-he3he4", 187, EMPTY_SHA256): Exception_("empty", EMPTY_WHY),
}


def _convert(data: bytes, profile: DetectorProfile, backend: str) -> bytes | None:
    try:
        return convert_raw(data, profile, backend)
    except NoRowsError:
        return None


def prove(exception: Exception_, raw: bytes, reference: bytes, profile: DetectorProfile, backend: str) -> bool:
    if exception.kind == "cut":
        cut = b"".join(raw.splitlines(keepends=True)[:exception.lines])
        return check_txy(_convert(cut, profile, backend), reference).identical
    if exception.kind == "variant":
        return check_txy(_convert(raw, profile.replace(**exception.changes), backend), reference).identical
    if exception.kind == "empty":
        return (reference == b"" and _convert(raw, profile.replace(write_empty_txy=False), backend) is None
                and _convert(raw, profile.replace(write_empty_txy=True), backend) == b"")
    raise ValueError(f"Unknown exception kind {exception.kind!r}")
