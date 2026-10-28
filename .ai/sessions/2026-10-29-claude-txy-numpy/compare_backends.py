"""Convert every sample shot with two backends and compare the TXY bytes (both profiles).

    source .ai/local/floor-env.sh
    python .ai/sessions/2026-10-29-claude-txy-numpy/compare_backends.py [--backend numpy]
        [--against reference] [--profiles matlab-2019 matlab-2023-lab-edit] [--split]

Reads the sample set read-only (SHA-256 checked); writes nothing. ``--split`` converts the
backend's side through ``helab.convert.split`` with forced small pieces. Exit 1 on any difference.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dev" / "txy"))
from _common import guard  # noqa: E402

guard()

from helab.convert.profile import builtin_profile  # noqa: E402
from helab.convert.raw import parse_raw  # noqa: E402
from helab.convert.reconstruct import NoRowsError, reconstruct  # noqa: E402
from helab.convert.samples import load_manifest, read_verified, select_shots  # noqa: E402
from helab.convert.txy import format_txy  # noqa: E402


def convert(raw: bytes, profile_name: str, backend: str, split: bool) -> bytes | str:
    profile = builtin_profile(profile_name)
    pulses = parse_raw(raw)
    try:
        if split:
            from helab.convert.split import reconstruct_split
            hits = reconstruct_split(pulses, profile, backend, min_rows=1, max_pieces=None)
        else:
            hits = reconstruct(pulses, profile, backend)
    except NoRowsError:
        return "error"
    return format_txy(hits)


def one(args: tuple[str, str, str, str, str, bool]) -> tuple[str, str, bool]:
    label, path, sha, profile, backend, split = args
    raw = read_verified(Path(path), sha)
    against = convert(raw, profile, ARGS_AGAINST, False)
    ours = convert(raw, profile, backend, split)
    return label, profile, ours == against


ARGS_AGAINST = "reference"


def main() -> int:
    global ARGS_AGAINST
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="~/HeLab-samples/txy-v1")
    parser.add_argument("--backend", default="numpy")
    parser.add_argument("--against", default="reference")
    parser.add_argument("--profiles", nargs="*", default=["matlab-2019", "matlab-2023-lab-edit"])
    parser.add_argument("--split", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    ARGS_AGAINST = args.against
    os.environ["COMPARE_AGAINST"] = args.against
    shots = select_shots(load_manifest(args.root), "all")
    jobs = [(s.label, str(s.raw_path), s.raw_sha256, p, args.backend, args.split) for p in args.profiles for s in shots]
    with ProcessPoolExecutor(args.workers, initializer=_init, initargs=(args.against,)) as pool:
        results = list(pool.map(one, jobs, chunksize=4))
    bad = [r for r in results if not r[2]]
    for label, profile, _ in bad:
        print("differs:", profile, label)
    print(f"{len(results) - len(bad)} of {len(results)} identical ({args.backend}{' split' if args.split else ''} "
          f"vs {args.against}, {', '.join(args.profiles)})")
    return 1 if bad else 0


def _init(against: str) -> None:
    global ARGS_AGAINST
    ARGS_AGAINST = against


if __name__ == "__main__":
    sys.exit(main())
