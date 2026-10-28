"""A backend through ``split.reconstruct_split`` with a bounded piece count, against the reference's
whole-shot TXY, on every sample shot and both built-ins.

    source .ai/local/floor-env.sh
    python .ai/sessions/2026-10-29-claude-txy-bench/compare_split.py --backend mlx [--pieces 2 8 64]

For a backend with a fixed cost per call (mlx: ~2.5 ms of GPU dispatch), the NumPy floor's
``compare_backends.py --split`` (``min_rows=1``, every safe gap, up to 741,370 pieces in one shot)
would take hours; this asks for at most ``--pieces`` pieces (``min_rows=1``). Reads the sample set
read-only (SHA-256 checked); writes nothing. Exit 1 on any difference.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dev" / "txy"))
from _common import guard  # noqa: E402

guard()

from helab.convert.profile import builtin_profile  # noqa: E402
from helab.convert.raw import parse_raw  # noqa: E402
from helab.convert.reconstruct import NoRowsError, reconstruct  # noqa: E402
from helab.convert.samples import load_manifest, read_verified, select_shots  # noqa: E402
from helab.convert.split import plan_cuts, reconstruct_split, sorted_rows  # noqa: E402
from helab.convert.txy import format_txy  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default="~/HeLab-samples/txy-v1")
    parser.add_argument("--backend", default="mlx")
    parser.add_argument("--pieces", type=int, nargs="*", default=[2, 8, 64])
    parser.add_argument("--profiles", nargs="*", default=["matlab-2019", "matlab-2023-lab-edit"])
    args = parser.parse_args()
    shots = select_shots(load_manifest(args.root), "all")
    checked = differ = 0
    cut: dict[int, list[int]] = {n: [] for n in args.pieces}
    for name in args.profiles:
        profile = builtin_profile(name)
        for shot in shots:
            pulses = parse_raw(read_verified(shot.raw_path, shot.raw_sha256))
            try:
                expected: bytes | str = format_txy(reconstruct(pulses, profile, "reference"))
            except NoRowsError:
                expected = "NoRowsError"
            for n in args.pieces:
                try:
                    got: bytes | str = format_txy(reconstruct_split(pulses, profile, args.backend, min_rows=1,
                                                                    max_pieces=n))
                except NoRowsError:
                    got = "NoRowsError"
                if len(pulses):
                    _, t = sorted_rows(pulses, profile)
                    cut[n].append(len(plan_cuts(t, profile, n, 1)) + 1)
                checked += 1
                if got != expected:
                    differ += 1
                    print(f"DIFFER {name} {shot.label} pieces {n}")
    for n, counts in cut.items():
        print(f"  asked {n:3} pieces: cut into {min(counts)}–{max(counts)} (median {sorted(counts)[len(counts) // 2]})")
    print(f"{args.backend} split vs reference: {checked} conversions ({len(shots)} shots x {len(args.profiles)} "
          f"profiles x pieces {args.pieces}), {differ} differ")
    return 1 if differ else 0


if __name__ == "__main__":
    sys.exit(main())
