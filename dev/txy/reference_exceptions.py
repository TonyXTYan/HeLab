"""Sample shots whose reference TXY isn't the 2019 converter's output for the raw file as it is
now: the list, each with the fault that explains it (``helab.convert.check.ReferenceFault``:
``cut``, ``variant`` or ``empty``), which ``check_samples.py`` proves again every time with
``prove_fault``.

Keyed by sample set, shot and the reference TXY's SHA-256, so a changed reference is no longer
excused. The checker fails on any mismatch not listed here and on a listed one whose proof fails,
and reports each class apart from "identical".

Found by the builder (Forge) and the cross-checker (Lens) on 2026-10-29, each proof confirmed by
both (``.ai/sessions/2026-10-29-claude-txy-reference/notes.md``). The empty class: the 2023
``dld_raw_to_txy`` writes empty files, and so did the lab's live converter in 2020 (2020-halos
d400's was written 2 s after its raw file).
"""
from __future__ import annotations

from helab.convert.check import ReferenceFault

EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
SECOND_2023_02 = "re-converted 2023-02-08 by a third MATLAB variant: matlab-2019 plus a 2 us x1 dead time"
EMPTY_WHY = "no hits; 2019 writes no file, the reference is 0 bytes (a wrapper that writes empty files)"

EXCEPTIONS: dict[tuple[str, int, str], ReferenceFault] = {
    ("2019-halos-old-plates", 3667, "832daf96e6a010da4e2c9f577b87a0ccba7dbfa08ecc0929966fefe35cc3519f"): ReferenceFault(
        "cut", "TXY written 0.25 s after the raw file's last change: MATLAB read it half-written "
               "(identical when cut to 40,956-40,966 of 41,092 lines)", lines=40956),
    ("2022-07-old-plates-he3he4", 2, "8179e4dffbf9cd28d1ae1950296caf89927230bf7e70bcf24f1fefc414423fc1"): ReferenceFault(
        "variant", SECOND_2023_02, changes={"dead_time_x1": 2e-6}),
    ("2022-07-old-plates-he3he4", 3, "66724120c76cb6d473dffe077098aadd0106473eaa2182b3c9f1b7115aff394a"): ReferenceFault(
        "variant", SECOND_2023_02, changes={"dead_time_x1": 2e-6}),
    ("2020-halos-weak-trap", 400, EMPTY_SHA256): ReferenceFault("empty", EMPTY_WHY),
    ("2022-11-ghost-counts-mcp", 5, EMPTY_SHA256): ReferenceFault("empty", EMPTY_WHY),
    ("2023-02-new-plates-he3he4", 187, EMPTY_SHA256): ReferenceFault("empty", EMPTY_WHY),
}
