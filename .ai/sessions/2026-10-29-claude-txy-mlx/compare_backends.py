"""Compare the mlx backend with the reference on every sample shot, and count contested x1 rows.

    python .ai/sessions/2026-10-29-claude-txy-mlx/compare_backends.py [--profile …] [--positions all]

Run from the floor's root after ``source .ai/local/floor-env.sh``. Reads the sample set (read
only, SHA-256 checked); writes nothing. For each shot: the reference's TXY bytes, the mlx
backend's (GPU), and the same pipeline with the CPU first-choice search, all compared byte for
byte; plus how many x1 rows the greedy pass had to recompute (contested) and how many of those
changed. Exits 1 on any difference.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "dev" / "txy"))
sys.path.insert(0, str(ROOT))

from _common import guard, sample_arguments  # noqa: E402

guard()

import numpy as np  # noqa: E402

from helab.convert.backends import mlx_gpu  # noqa: E402
from helab.convert.backends.reference import reconstruct_reference  # noqa: E402
from helab.convert.profile import builtin_profile  # noqa: E402
from helab.convert.raw import parse_raw  # noqa: E402
from helab.convert.reconstruct import NoRowsError  # noqa: E402
from helab.convert.samples import load_manifest, read_verified, select_shots  # noqa: E402
from helab.convert.txy import format_txy  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sample_arguments(parser)
    args = parser.parse_args()
    profile = builtin_profile(args.profile)
    shots = select_shots(load_manifest(args.root), args.positions, args.sets)
    per_set: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    bad = 0
    for shot in shots:
        pulses = parse_raw(read_verified(shot.raw_path, shot.raw_sha256))
        try:
            reference = format_txy(reconstruct_reference(pulses, profile))
        except NoRowsError:
            reference = b"error"
        outputs = []
        for gpu in (True, False):
            try:
                outputs.append(format_txy(mlx_gpu.reconstruct_mlx(pulses, profile, gpu=gpu)))
            except NoRowsError:
                outputs.append(b"error")
        row = per_set[shot.set_name]
        row[0] += 1
        same = all(output == reference for output in outputs)
        row[1] += same
        if not same:
            bad += 1
            print(f"  {shot.label}: differs (gpu {outputs[0] == reference}, cpu {outputs[1] == reference})")
        prep = mlx_gpu.prepare(pulses, profile) if pulses.times.size else None
        if prep is None:
            continue
        first = mlx_gpu.first_choices_mlx(prep)
        final = mlx_gpu.resolve(prep, first)
        changed = int(np.count_nonzero((first.x2 != final.x2) | (first.y1 != final.y1) | (first.y2 != final.y2)))
        row[2] += int(prep.x1_rows.size)
        row[3] += int(mlx_gpu.contested_at_start(prep, first).sum())
        row[4] += changed
        row[5] += int(np.count_nonzero(final.y1 != mlx_gpu.NONE))
    print(f"profile {profile.name}, positions {args.positions}")
    print(f"{'set':32} {'shots':>5} {'same':>5} {'x1 rows':>10} {'contested':>9} {'changed':>8} {'hits':>10}")
    totals = [0] * 6
    for name, row in sorted(per_set.items()):
        totals = [a + b for a, b in zip(totals, row)]
        print(f"{name:32} {row[0]:5} {row[1]:5} {row[2]:10} {row[3]:9} {row[4]:8} {row[5]:10}")
    print(f"{'all':32} {totals[0]:5} {totals[1]:5} {totals[2]:10} {totals[3]:9} {totals[4]:8} {totals[5]:10}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
