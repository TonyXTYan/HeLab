"""Latency of one large, dense shot: a sample shot's pulses repeated ``--copies`` times, each
copy 1 s later (made in memory; nothing written), converted whole and split across a process
pool, both checked identical.

    source .ai/local/floor-env.sh
    python .ai/sessions/2026-10-29-claude-txy-numpy/time_large.py [--backend numpy] [--copies 10]
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dev" / "txy"))
from _common import guard  # noqa: E402

guard()

import numpy as np  # noqa: E402

from helab.convert.profile import builtin_profile  # noqa: E402
from helab.convert.raw import RawPulses, parse_raw  # noqa: E402
from helab.convert.reconstruct import reconstruct  # noqa: E402
from helab.convert.samples import load_manifest, read_verified, select_shots  # noqa: E402
from helab.convert.split import reconstruct_split  # noqa: E402
from helab.convert.txy import format_txy  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="~/HeLab-samples/txy-v1")
    parser.add_argument("--shot", default="2022-07-old-plates-he3he4/d1")
    parser.add_argument("--copies", type=int, default=10)
    parser.add_argument("--backend", default="numpy")
    parser.add_argument("--profile", default="matlab-2019")
    parser.add_argument("--workers", type=int, nargs="*", default=[2, 4, 8])
    args = parser.parse_args()
    profile = builtin_profile(args.profile)
    shot = next(s for s in select_shots(load_manifest(args.root), "all") if s.label == args.shot)
    raw = read_verified(shot.raw_path, shot.raw_sha256)
    one = parse_raw(raw)
    span = 40e9  # 1 s in 25 ps bins
    pulses = RawPulses(np.tile(one.channels, args.copies),
                       np.concatenate([one.times + k * span for k in range(args.copies)]))
    size = len(raw) * args.copies / 1e6
    start = time.perf_counter()
    whole = format_txy(reconstruct(pulses, profile, args.backend))
    serial = time.perf_counter() - start
    print(f"{args.backend}: {len(pulses)} rows (~{size:.0f} MB raw), whole {serial * 1e3:.0f} ms "
          f"({size / serial:.0f} MB/s)")
    for workers in args.workers:
        with ProcessPoolExecutor(workers) as pool:
            reconstruct_split(pulses, profile, args.backend, executor=pool, max_pieces=workers)  # warm the pool
            start = time.perf_counter()
            split = format_txy(reconstruct_split(pulses, profile, args.backend, executor=pool, max_pieces=workers))
            took = time.perf_counter() - start
        assert split == whole
        print(f"  split x{workers}: {took * 1e3:.0f} ms ({size / took:.0f} MB/s), identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
