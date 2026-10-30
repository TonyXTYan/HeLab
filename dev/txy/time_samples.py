"""Time the converter on sample shots: reading, reconstruction and writing apart.

    python dev/txy/time_samples.py [--positions all] [--backend reference]
        [--parallelism serial|processes|threads] [--workers N] [--json OUT]

Writes the TXY to ``.ai/temp/txy/timing/<set>/`` (atomic), never beside the samples. Prints raw
MB/s (SI) per stage and in total, and latency per shot, for all shots and split into small and
large ones (the three largest of each set are its "large"). Final timings are taken serially on an
idle machine (stage 2); this gives the shape.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import sys
import time

from _common import TEMP, guard, sample_arguments

guard()

from helab.convert.profile import builtin_profile  # noqa: E402
from helab.convert.samples import load_manifest, select_shots  # noqa: E402
from helab.convert.timing import Parallelism, ShotJob, ShotTiming, summarise, time_shots  # noqa: E402


def report(title: str, timings: list[ShotTiming], wall: float | None) -> dict[str, float]:
    s = summarise(timings, wall)
    row = {"shots": s.shots, "raw_MB": s.raw_bytes / 1e6, "hits": s.hits,
           "read_MBps": s.mb_per_s(s.read), "reconstruct_MBps": s.mb_per_s(s.reconstruct),
           "write_MBps": s.mb_per_s(s.write), "total_MBps": s.mb_per_s(s.read + s.reconstruct + s.write),
           "latency_median_s": s.latency_median, "latency_max_s": s.latency_max}
    if wall is not None:
        row["wall_MBps"] = s.mb_per_s(wall)
    print(f"{title:8} {s.shots:4} shots {s.raw_bytes / 1e6:8.1f} MB | MB/s read {row['read_MBps']:6.2f} "
          f"reconstruct {row['reconstruct_MBps']:6.2f} write {row['write_MBps']:6.2f} total "
          f"{row['total_MBps']:6.2f}" + (f" wall {row['wall_MBps']:6.2f}" if wall is not None else "")
          + f" | latency median {s.latency_median * 1e3:7.1f} ms max {s.latency_max * 1e3:7.1f} ms")
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sample_arguments(parser)
    parser.add_argument("--parallelism", choices=[p.value for p in Parallelism], default="serial")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    profile = builtin_profile(args.profile)
    sets = load_manifest(args.root)
    shots = select_shots(sets, args.positions, args.sets)
    large = {shot.label for s in sets for shot in sorted(s.shots, key=lambda x: x.raw_bytes)[-3:]}
    jobs = []
    for shot in shots:
        out = TEMP / "timing" / shot.set_name
        out.mkdir(parents=True, exist_ok=True)
        jobs.append(ShotJob(shot.label, shot.raw_path, out / f"d_txy_helab_m19v1_{shot.shot}.txt"))
    start = time.perf_counter()
    timings = time_shots(jobs, profile, args.backend, Parallelism(args.parallelism), args.workers)
    wall = time.perf_counter() - start
    print(f"backend {args.backend}, profile {profile.name}, {args.parallelism}"
          f"{'' if args.workers is None else f' x{args.workers}'}, {platform.machine()} {os.cpu_count()} cores")
    rows = {"all": report("all", timings, wall),
            "small": report("small", [t for t in timings if t.label not in large], None),
            "large": report("large", [t for t in timings if t.label in large], None)}
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"backend": args.backend, "profile": profile.name,
                                         "parallelism": args.parallelism, "workers": args.workers,
                                         "machine": platform.platform(), "summary": rows,
                                         "shots": [t.__dict__ for t in timings]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
