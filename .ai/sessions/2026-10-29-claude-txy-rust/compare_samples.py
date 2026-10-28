"""Every sample shot through the rust backend, whole and split, against the reference, bit for bit.

    source .ai/local/floor-env.sh
    python .ai/sessions/2026-10-29-claude-txy-rust/compare_samples.py [--positions all] [--profile …]

For each shot: the reference's hits, and rust's (1) whole, (2) cut at every gap the cut rule allows
(``piece_rows=1``) on one thread, (3) the same on 8 threads, (4) about four pieces per thread on 8
threads (what a caller would use). All four must equal the reference's hits as bytes
(``ndarray.tobytes``, so −0 and every bit count) and give the same TXY text; ``NoRowsError`` must
match too. Prints the shot count, the pieces seen and any difference; exits 1 on one.
The sample set is read only (SHA-256 checked); nothing is written.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "dev" / "txy"))

from _common import guard, sample_arguments  # noqa: E402

guard()

from helab.convert.backends.reference import reconstruct_reference  # noqa: E402
from helab.convert.backends.rust import reconstruct_rust  # noqa: E402
from helab.convert.profile import builtin_profile  # noqa: E402
from helab.convert.raw import parse_raw  # noqa: E402
from helab.convert.reconstruct import NoRowsError  # noqa: E402
from helab.convert.samples import load_manifest, read_verified, select_shots  # noqa: E402
from helab.convert.txy import format_txy  # noqa: E402

VARIANTS = {"whole": (1, 0), "every-gap": (1, 1), "every-gap x8": (8, 1), "auto x8": (8, 0)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sample_arguments(parser)
    args = parser.parse_args()
    profile = builtin_profile(args.profile)
    shots = select_shots(load_manifest(args.root), args.positions, args.sets)
    differ = 0
    pieces_max = {name: 0 for name in VARIANTS}
    pieces_total = {name: 0 for name in VARIANTS}
    for shot in shots:
        pulses = parse_raw(read_verified(shot.raw_path, shot.raw_sha256))
        try:
            reference = reconstruct_reference(pulses, profile)
        except NoRowsError:
            reference = None
        for name, (threads, piece_rows) in VARIANTS.items():
            try:
                ours, pieces = reconstruct_rust(pulses, profile, threads, piece_rows)
            except NoRowsError:
                ours, pieces = None, 0
            pieces_max[name] = max(pieces_max[name], pieces)
            pieces_total[name] += pieces
            same = (ours is None and reference is None) or (
                ours is not None and reference is not None and ours.shape == reference.shape
                and ours.tobytes() == reference.tobytes() and format_txy(ours) == format_txy(reference))
            if not same:
                differ += 1
                print(f"DIFFER {shot.label} {name}: rust {None if ours is None else ours.shape}, "
                      f"reference {None if reference is None else reference.shape}")
    print(f"profile {profile.name}: {len(shots)} shots x {len(VARIANTS)} rust variants, {differ} differ")
    for name in VARIANTS:
        print(f"  {name:13} pieces per shot: mean {pieces_total[name] / max(len(shots), 1):9.1f}, max {pieces_max[name]}")
    return 1 if differ or not shots else 0


if __name__ == "__main__":
    sys.exit(main())
