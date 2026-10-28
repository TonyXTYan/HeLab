"""Convert sample shots and check them byte for byte against a reference TXY.

    python dev/txy/check_samples.py [--positions even|odd|all] [--profile …] [--backend …]
        [--reference-dir DIR] [--json OUT]

The reference is MATLAB's ``d_txy_forc<N>.txt`` in the sample set (SHA-256 checked), or, with
``--reference-dir``, ``DIR/<set>/d_txy_forc<N>.txt`` (MATLAB run on copies, e.g. by
``matlab_variant.py``; a missing file there means MATLAB wrote none). Prints a table per set and
each mismatch's first differing line. A mismatch listed in ``reference_exceptions.py`` (for the
sample set's own references) counts as explained only when its proof holds again; exits 1 on any
other mismatch.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

from _common import guard, sample_arguments

guard()

from reference_exceptions import EXCEPTIONS  # noqa: E402

from helab.convert.check import FAULT_KINDS as KINDS, CheckResult, check_txy, prove_fault  # noqa: E402
from helab.convert.pipeline import convert_raw  # noqa: E402
from helab.convert.profile import builtin_profile  # noqa: E402
from helab.convert.reconstruct import NoRowsError  # noqa: E402
from helab.convert.samples import load_manifest, read_verified, select_shots  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sample_arguments(parser)
    parser.add_argument("--reference-dir", type=Path)
    parser.add_argument("--json", type=Path, help="write the results here")
    args = parser.parse_args()
    profile = builtin_profile(args.profile)
    shots = select_shots(load_manifest(args.root), args.positions, args.sets)
    selected = len(shots)
    if args.reference_dir is not None:
        # Only the shots MATLAB was run on (their raw copy is there).
        shots = [shot for shot in shots if (args.reference_dir / shot.set_name / f"d{shot.shot}.txt").exists()]
    per_set: dict[str, list[tuple[int, CheckResult]]] = defaultdict(list)
    counted: dict[str, int] = defaultdict(int)
    explained: dict[tuple[str, str], int] = defaultdict(int)
    for shot in shots:
        if args.limit is not None and counted[shot.set_name] >= args.limit:
            continue
        counted[shot.set_name] += 1
        raw = read_verified(shot.raw_path, shot.raw_sha256)
        if args.reference_dir is None:
            reference: bytes | None = read_verified(shot.txy_path, shot.txy_sha256)
        else:
            path = args.reference_dir / shot.set_name / f"d_txy_forc{shot.shot}.txt"
            reference = path.read_bytes() if path.exists() else None
        try:
            ours = convert_raw(raw, profile, args.backend)
        except NoRowsError:
            ours = None
        result = check_txy(ours, reference)
        per_set[shot.set_name].append((shot.shot, result))
        exception = EXCEPTIONS.get((shot.set_name, shot.shot, shot.txy_sha256)) if args.reference_dir is None else None
        if not result.identical:
            if exception is not None and reference is not None and prove_fault(exception, raw, reference, profile,
                                                                         args.backend):
                explained[(shot.set_name, exception.kind)] += 1
                print(f"  {shot.label} (position {shot.position}): {exception.kind}, proof holds: {exception.why}")
            else:
                print(f"  {shot.label} (position {shot.position}): {result.describe()}", flush=True)
        elif exception is not None:
            print(f"  {shot.label}: listed as an exception but identical; remove it from reference_exceptions.py")
    print(f"\nprofile {profile.name} ({profile.content_hash()[:12]}), backend {args.backend}, "
          f"positions {args.positions}")
    print("(cut: MATLAB read a half-written raw file; variant: re-converted by another MATLAB variant; "
          "empty: no hits, the reference a 0-byte file from another wrapper; each proved again above)")
    print(f"{'set':32} {'shots':>5} {'identical':>9} " + " ".join(f"{kind:>7}" for kind in KINDS) + f" {'differ':>6}")
    bad = 0
    columns = [0] * (len(KINDS) + 3)
    for name, results in per_set.items():
        same = sum(result.identical for _, result in results)
        kinds = [explained[(name, kind)] for kind in KINDS]
        differ = len(results) - same - sum(kinds)
        bad += differ
        row = [len(results), same, *kinds, differ]
        columns = [a + b for a, b in zip(columns, row)]
        print(f"{name:32} {row[0]:5} {row[1]:9} " + " ".join(f"{k:7}" for k in kinds) + f" {differ:6}")
    print(f"{'all':32} {columns[0]:5} {columns[1]:9} " + " ".join(f"{k:7}" for k in columns[2:-1])
          + f" {columns[-1]:6}")
    print(f"checked {columns[0]} of {selected} selected shots"
          + ("" if args.reference_dir is None else f" (those with a copy in {args.reference_dir})")
          + ("" if args.limit is None else f", at most {args.limit} per set"))
    if columns[0] == 0:
        print("no shots were checked")
        return 1
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "profile": profile.name, "profile_hash": profile.content_hash(), "backend": args.backend,
            "positions": args.positions,
            "sets": {name: [{"shot": shot, "identical": r.identical, "ours_hits": r.ours_hits,
                             "reference_hits": r.reference_hits, "line": r.line, "ours_line": r.ours_line,
                             "reference_line": r.reference_line} for shot, r in results]
                     for name, results in per_set.items()}}, indent=1))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
