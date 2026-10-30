"""Measure MATLAB's x2 and y handling on the sample set (the stage-1 x2 report).

    python dev/txy/x2_report.py [--positions all] [--profile matlab-2019] [--json OUT]

Per set: x1 rows tried, how many met a second x2 candidate (MATLAB keeps the first and stops),
how many found an x2 but no y pair, of those how many had a second x2, and how many of those the
second x2 would have matched (checked without using it: an estimate of what retrying the other
x2 would recover); and hits whose y search met a second pair (the first is kept).
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import dataclasses
import json
from pathlib import Path
import sys

from _common import guard, sample_arguments

guard()

from helab.convert.backends.reference import MatchStats, reconstruct_reference  # noqa: E402
from helab.convert.profile import builtin_profile  # noqa: E402
from helab.convert.raw import parse_raw  # noqa: E402
from helab.convert.reconstruct import NoRowsError  # noqa: E402
from helab.convert.samples import load_manifest, read_verified, select_shots  # noqa: E402


def pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.2f} %" if whole else "-"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sample_arguments(parser)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    profile = builtin_profile(args.profile)
    per_set: dict[str, MatchStats] = defaultdict(MatchStats)
    for shot in select_shots(load_manifest(args.root), args.positions, args.sets):
        try:
            reconstruct_reference(parse_raw(read_verified(shot.raw_path, shot.raw_sha256)), profile,
                                  per_set[shot.set_name])
        except NoRowsError:
            pass
    print(f"profile {profile.name}, positions {args.positions}\n")
    print("| Set | Hits | x2 ambiguous (of x1 with an x2) | x2 but no y | of which x2 ambiguous | "
          "retry would match (of hits) | y ambiguous (of hits) |")
    print("|---|---|---|---|---|---|---|")
    total = MatchStats()
    for name, s in per_set.items():
        for f in dataclasses.fields(MatchStats):
            setattr(total, f.name, getattr(total, f.name) + getattr(s, f.name))
    for name, s in [*per_set.items(), ("all", total)]:
        with_x2 = s.x1_rows - s.x2_missing
        print(f"| {name} | {s.hits} | {s.x2_ambiguous} ({pct(s.x2_ambiguous, with_x2)}) | {s.y_missing} | "
              f"{s.y_missing_x2_ambiguous} | {s.x2_retry_would_match} ({pct(s.x2_retry_would_match, s.hits)}) | "
              f"{s.y_ambiguous} ({pct(s.y_ambiguous, s.hits)}) |")
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({name: dataclasses.asdict(s) for name, s in [*per_set.items(), ("all", total)]},
                                        indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
