"""Convert sample shots and check them byte for byte against a reference TXY.

    python dev/txy/check_samples.py [--positions even|odd|all] [--profile …] [--backend …]
        [--reference-dir DIR] [--json OUT]

The reference is MATLAB's ``d_txy_forc<N>.txt`` in the sample set (SHA-256 checked), or, with
``--reference-dir``, ``DIR/<set>/d_txy_forc<N>.txt`` (MATLAB run on copies, e.g. by
``matlab_variant.py``; a missing file there means MATLAB wrote none). Prints a table per set and
each mismatch's first differing line; exits 1 on any mismatch.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

from _common import guard, sample_arguments

guard()

from helab.convert.check import CheckResult, check_txy  # noqa: E402
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
    if args.reference_dir is not None:
        shots = [shot for shot in shots if (args.reference_dir / shot.set_name / f"d{shot.shot}.txt").exists()]
    per_set: dict[str, list[tuple[int, CheckResult]]] = defaultdict(list)
    counted: dict[str, int] = defaultdict(int)
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
        if not result.identical:
            print(f"  {shot.label} (position {shot.position}): {result.describe()}", flush=True)
    print(f"\nprofile {profile.name} ({profile.content_hash()[:12]}), backend {args.backend}, "
          f"positions {args.positions}")
    print(f"{'set':32} {'shots':>5} {'identical':>9}")
    bad = 0
    for name, results in per_set.items():
        same = sum(result.identical for _, result in results)
        bad += len(results) - same
        print(f"{name:32} {len(results):5} {same:9}")
    total = sum(len(results) for results in per_set.values())
    print(f"{'all':32} {total:5} {total - bad:9}")
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
