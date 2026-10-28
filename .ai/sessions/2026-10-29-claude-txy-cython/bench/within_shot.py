"""Reconstruction alone on sample shots: within-shot threads, the kernel's stages, first-call cost.

    python .ai/sessions/2026-10-29-claude-txy-cython/bench/within_shot.py [--repeat 5] [--json OUT]

Run from the checkout's root after ``source .ai/local/floor-env.sh``. Reads the sample set
read-only; writes only the JSON. Each figure is the best of ``--repeat`` runs (the machine is
shared, so the best is the least disturbed). "large" are the three largest shots of each set.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "dev" / "txy"))

from _common import guard  # noqa: E402

guard()

import numpy as np  # noqa: E402

from helab.convert.backends.cython import (cut_points, kernel, reconstruct_cython,  # noqa: E402
                                           search_offsets)
from helab.convert.profile import MATLAB_2019  # noqa: E402
from helab.convert.raw import RawPulses, parse_raw  # noqa: E402
from helab.convert.samples import load_manifest, read_verified, select_shots  # noqa: E402

FIRST_CALL = """
import time
start = time.perf_counter()
from helab.convert.raw import parse_raw
from helab.convert.profile import MATLAB_2019
imported_helab = time.perf_counter()
from helab.convert.reconstruct import reconstruct
import helab.convert.backends.cython as backend
assert backend.kernel() is not None
imported = time.perf_counter()
pulses = parse_raw(open(%r, 'rb').read())
t0 = time.perf_counter(); reconstruct(pulses, MATLAB_2019, 'cython'); t1 = time.perf_counter()
reconstruct(pulses, MATLAB_2019, 'cython'); t2 = time.perf_counter()
print(imported - imported_helab, t1 - t0, t2 - t1)
"""


def best(repeat: int, call: object) -> float:
    assert callable(call)
    times = []
    for _ in range(repeat):
        start = time.perf_counter()
        call()
        times.append(time.perf_counter() - start)
    return min(times)


def stages(pulses: RawPulses, repeat: int) -> dict[str, float]:
    """The kernel's three calls timed apart (serial, one piece), as reconstruct_cython makes them."""
    module = kernel()
    assert module is not None
    profile = MATLAB_2019
    empty = np.empty(0)
    prepare = best(repeat, lambda: module.prepare(pulses.channels, pulses.times, True, empty, empty))
    channels, times = module.prepare(pulses.channels, pulses.times, True, empty, empty)
    search = search_offsets(profile.search_depth, len(pulses))
    out = np.empty((len(pulses) // 4 + 1, 5))
    settings = (search, 3200.0, 3400.0, 3400.0, 400.0, 0.0, 1.0, 2.0, 3.0, 3200.0, 3200.0, True, out)

    def match() -> None:
        module.match(channels.copy(), times, 0, len(pulses), 1, *settings)

    match_s = best(repeat, match) - best(repeat, channels.copy)
    hits, *_ = module.match(channels.copy(), times, 0, len(pulses), 1, *settings)
    assemble = best(repeat, lambda: module.assemble([(out, hits)], False, 0.0, 0.0, 25e-12, 5.2632e5, 5.2632e5))
    return {"prepare": prepare, "match": match_s, "assemble": assemble}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default="~/HeLab-samples/txy-v1")
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--threads", type=int, nargs="*", default=[1, 2, 4, 8, 12])
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    sets = load_manifest(args.root)
    shots = select_shots(sets, "all", None)
    large = {shot.label for s in sets for shot in sorted(s.shots, key=lambda x: x.raw_bytes)[-3:]}
    loaded = [(shot, parse_raw(read_verified(shot.raw_path, shot.raw_sha256))) for shot in shots]
    result: dict[str, object] = {"machine": platform.platform(), "cores": os.cpu_count(),
                                 "load_before": os.getloadavg()}

    # Within one shot: reconstruct_cython(threads=k), summed over the shots of each group.
    within: dict[str, dict[str, float]] = {}
    for group in ("all", "large", "small"):
        chosen = [(s, p) for s, p in loaded if group == "all" or (s.label in large) == (group == "large")]
        raw_mb = sum(s.raw_bytes for s, _ in chosen) / 1e6
        row = {}
        for threads in args.threads:
            seconds = sum(best(args.repeat, lambda p=p: reconstruct_cython(p, MATLAB_2019, threads))  # type: ignore[misc]
                          for _, p in chosen)
            row[str(threads)] = raw_mb / seconds
        pieces = [len(cut_points(kernel().prepare(p.channels, p.times, True, np.empty(0), np.empty(0))[1],  # type: ignore[union-attr]
                                 3200.0, max(args.threads))) + 1 for _, p in chosen]
        within[group] = row
        print(f"within-shot {group:5} {len(chosen):3} shots {raw_mb:7.1f} MB: reconstruct MB/s by threads "
              + "  ".join(f"{k}: {v:7.1f}" for k, v in row.items())
              + f"  (pieces at {max(args.threads)}: min {min(pieces)})", flush=True)
    result["within_shot_reconstruct_MBps"] = within

    # The kernel's stages on the large shots.
    totals = {"prepare": 0.0, "match": 0.0, "assemble": 0.0}
    for shot, pulses in loaded:
        if shot.label in large:
            for name, seconds in stages(pulses, args.repeat).items():
                totals[name] += seconds
    raw_mb = sum(s.raw_bytes for s, _ in loaded if s.label in large) / 1e6
    result["large_stage_MBps"] = {name: raw_mb / seconds for name, seconds in totals.items()}
    print("kernel stages, large shots, MB/s: " + "  ".join(f"{k} {raw_mb / v:8.1f}" for k, v in totals.items()))

    # First call: import and the first conversion in a fresh process, against the second.
    smallest = min(shots, key=lambda s: s.raw_bytes)
    runs = []
    for _ in range(args.repeat):
        done = subprocess.run([sys.executable, "-c", FIRST_CALL % str(smallest.raw_path)], capture_output=True,
                              text=True, check=True, env=dict(os.environ), cwd=ROOT)
        runs.append([float(x) for x in done.stdout.split()])
    imported, first, second = (min(column) for column in zip(*runs))
    result["first_call_s"] = {"import_backend_and_kernel": imported, "first_reconstruct": first,
                              "second_reconstruct": second, "shot": smallest.label}
    print(f"first call ({smallest.label}): import backend + kernel {imported * 1e3:.2f} ms, first reconstruct "
          f"{first * 1e3:.3f} ms, second {second * 1e3:.3f} ms")
    result["load_after"] = os.getloadavg()
    if args.json is not None:
        args.json.write_text(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
