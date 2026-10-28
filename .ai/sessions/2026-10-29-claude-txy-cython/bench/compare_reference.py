"""The cython backend against the reference on every sample shot, both built-in profiles, whole and
cut into pieces (within-shot threads).

    python .ai/sessions/2026-10-29-claude-txy-cython/bench/compare_reference.py [--threads 1 2 4 16 64]

Run from the checkout's root after ``source .ai/local/floor-env.sh``. Reads the sample set
read-only (SHA-256 checked); writes nothing. Exit 1 on any difference.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "dev" / "txy"))

from _common import guard  # noqa: E402

guard()

import numpy as np  # noqa: E402

from helab.convert.backends.cython import cut_points, kernel, reconstruct_cython  # noqa: E402
from helab.convert.profile import BUILTIN_PROFILES  # noqa: E402
from helab.convert.raw import parse_raw  # noqa: E402
from helab.convert.reconstruct import NoRowsError, reconstruct  # noqa: E402
from helab.convert.samples import load_manifest, read_verified, select_shots  # noqa: E402
from helab.convert.txy import format_txy  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default="~/HeLab-samples/txy-v1")
    parser.add_argument("--threads", type=int, nargs="*", default=[1, 2, 4, 16, 64])
    args = parser.parse_args()
    module = kernel()
    assert module is not None
    shots = select_shots(load_manifest(args.root), "all", None)
    checked = differ = 0
    pieces_seen: dict[int, int] = {}
    for shot in shots:
        pulses = parse_raw(read_verified(shot.raw_path, shot.raw_sha256))
        for profile in BUILTIN_PROFILES.values():
            try:
                reference: bytes | None = format_txy(reconstruct(pulses, profile, "reference"))
            except NoRowsError:
                reference = None
            for threads in args.threads:
                try:
                    ours: bytes | None = format_txy(reconstruct_cython(pulses, profile, threads))
                except NoRowsError:
                    ours = None
                checked += 1
                if ours != reference:
                    differ += 1
                    print(f"DIFFER {shot.label} {profile.name} threads={threads}", flush=True)
            if len(pulses):
                _, times = module.prepare(pulses.channels, pulses.times, profile.subtract_time_zero,
                                          np.empty(0), np.empty(0))
                got = len(cut_points(times, profile.search_window, max(args.threads))) + 1
                pieces_seen[got] = pieces_seen.get(got, 0) + 1
    print(f"{len(shots)} shots x {len(BUILTIN_PROFILES)} profiles x threads {args.threads}: "
          f"{checked} conversions, {differ} differ")
    print(f"pieces at threads={max(args.threads)} (pieces: shots x profiles): {dict(sorted(pieces_seen.items()))}")
    return 1 if differ else 0


if __name__ == "__main__":
    sys.exit(main())
