"""Numba against the reference on every sample shot: whole shots and within-shot pieces.

    python .ai/sessions/2026-10-29-claude-txy-numba/compare_samples.py [--positions all]
        [--profile matlab-2019] [--pieces 2 4 16 64]

For each shot: the TXY bytes of ``numba`` and ``reference`` (``convert_raw``, outcomes included),
then ``reconstruct_numba_pieces`` with each piece count, serially and with ``prange``, as hit
arrays equal to the reference's. Prints the pieces actually cut and exits 1 on any difference.
Run from the checkout's root after ``source .ai/local/floor-env.sh``.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "dev" / "txy"))

from _common import guard, sample_arguments  # noqa: E402

guard()

import numpy as np  # noqa: E402

from helab.convert.backends.numba_backend import piece_bounds, reconstruct_numba_pieces  # noqa: E402
from helab.convert.pipeline import convert_raw  # noqa: E402
from helab.convert.profile import builtin_profile  # noqa: E402
from helab.convert.raw import parse_raw  # noqa: E402
from helab.convert.reconstruct import NoRowsError, reconstruct  # noqa: E402
from helab.convert.samples import load_manifest, read_verified, select_shots  # noqa: E402


def outcome(data: bytes, profile_name: str, backend: str) -> bytes | str | None:
    try:
        return convert_raw(data, builtin_profile(profile_name), backend)
    except NoRowsError:
        return "error"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sample_arguments(parser)
    parser.add_argument("--pieces", type=int, nargs="*", default=[2, 4, 16, 64])
    args = parser.parse_args()
    profile = builtin_profile(args.profile)
    shots = select_shots(load_manifest(args.root), args.positions, args.sets)
    bad = checked = 0
    cut: dict[int, list[int]] = {k: [] for k in args.pieces}
    for shot in shots:
        raw = read_verified(shot.raw_path, shot.raw_sha256)
        checked += 1
        if outcome(raw, args.profile, "numba") != outcome(raw, args.profile, "reference"):
            bad += 1
            print(f"  {shot.label}: numba's TXY differs from the reference's", flush=True)
            continue
        pulses = parse_raw(raw)
        try:
            reference = reconstruct(pulses, profile, "reference")
        except NoRowsError:
            continue
        for k in args.pieces:
            cut[k].append(int(piece_bounds(pulses, profile, k).shape[0] - 1))
            for within in ("serial", "prange"):
                hits = reconstruct_numba_pieces(pulses, profile, k, within)  # type: ignore[arg-type]
                if not np.array_equal(hits, reference, equal_nan=True):
                    bad += 1
                    print(f"  {shot.label}: {k} pieces ({within}) differ", flush=True)
    print(f"profile {profile.name}: {checked} shots, {bad} differences")
    for k, counts in cut.items():
        if counts:
            print(f"  asked {k:3} pieces: cut into {min(counts)}–{max(counts)} (median {sorted(counts)[len(counts) // 2]})")
    return 1 if bad or not checked else 0


if __name__ == "__main__":
    sys.exit(main())
