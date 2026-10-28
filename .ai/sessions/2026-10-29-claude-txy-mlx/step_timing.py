"""Time the mlx backend's steps on the sample shots, and its first-call cost.

    python .ai/sessions/2026-10-29-claude-txy-mlx/step_timing.py [--profile …] [--repeat 3]
    python .ai/sessions/2026-10-29-claude-txy-mlx/step_timing.py --first-call

Run from the floor's root after ``source .ai/local/floor-env.sh``. Reads the sample set (read
only); writes nothing. Per shot (best of ``--repeat``): prepare (sort, time zero, integers, dead
time), the first-choice search on the GPU (MLX, including the transfer both ways) and on the CPU
(NumPy), the greedy pass, the output; then the reference's reconstruction once, for scale.
Sums for all shots, small and large (the three largest per set). ``--first-call``: in a fresh
process, the import of mlx, the device check and the first conversion of a small shot, then the
second.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "dev" / "txy"))
sys.path.insert(0, str(ROOT))

from _common import guard, sample_arguments  # noqa: E402

guard()

from helab.convert.profile import builtin_profile  # noqa: E402
from helab.convert.raw import parse_raw  # noqa: E402
from helab.convert.samples import load_manifest, read_verified, select_shots  # noqa: E402

STEPS = ("prepare", "gpu_search", "cpu_search", "resolve", "assemble", "reference")


def first_call() -> None:
    clock = time.perf_counter
    start = clock()
    from helab.convert.backends import mlx_gpu
    imported = clock()
    reason = mlx_gpu._unavailable(None)          # imports mlx.core and asks for Metal
    checked = clock()
    case = (ROOT / "tests" / "data" / "convert" / "cases" / "basic" / "d1.txt").read_bytes()
    pulses = parse_raw(case)
    profile = builtin_profile()
    mlx_gpu.reconstruct_mlx(pulses, profile)
    first = clock()
    mlx_gpu.reconstruct_mlx(pulses, profile)
    second = clock()
    print(f"unavailable: {reason}")
    print(f"import helab backend module {1e3 * (imported - start):8.1f} ms")
    print(f"import mlx + Metal check    {1e3 * (checked - imported):8.1f} ms")
    print(f"first conversion (basic)    {1e3 * (first - checked):8.1f} ms")
    print(f"second conversion (basic)   {1e3 * (second - first):8.1f} ms")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sample_arguments(parser)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--first-call", action="store_true")
    parser.add_argument("--no-reference", action="store_true")
    args = parser.parse_args()
    if args.first_call:
        first_call()
        return 0
    from helab.convert.backends import mlx_gpu
    from helab.convert.backends.reference import reconstruct_reference
    profile = builtin_profile(args.profile)
    sets = load_manifest(args.root)
    shots = select_shots(sets, args.positions, args.sets)
    large = {shot.label for s in sets for shot in sorted(s.shots, key=lambda x: x.raw_bytes)[-3:]}
    clock = time.perf_counter
    # Warm up MLX (compile the kernels) on a large shot first.
    biggest = max(shots, key=lambda s: s.raw_bytes)
    warm = mlx_gpu.prepare(parse_raw(read_verified(biggest.raw_path, biggest.raw_sha256)), profile)
    assert warm is not None
    mlx_gpu.first_choices_mlx(warm)
    totals: dict[str, dict[str, float]] = {group: dict.fromkeys(STEPS, 0.0) for group in ("all", "small", "large")}
    sizes = {group: 0 for group in totals}
    for shot in shots:
        pulses = parse_raw(read_verified(shot.raw_path, shot.raw_sha256))
        if pulses.times.size == 0:
            continue
        best = dict.fromkeys(STEPS, float("inf"))
        for _ in range(args.repeat):
            t0 = clock()
            prep = mlx_gpu.prepare(pulses, profile)
            t1 = clock()
            assert prep is not None
            gpu = mlx_gpu.first_choices_mlx(prep)
            t2 = clock()
            mlx_gpu.first_choices_numpy(prep)
            t3 = clock()
            final = mlx_gpu.resolve(prep, gpu)
            t4 = clock()
            mlx_gpu.assemble(prep, final, profile)
            t5 = clock()
            for step, seconds in zip(STEPS, (t1 - t0, t2 - t1, t3 - t2, t4 - t3, t5 - t4)):
                best[step] = min(best[step], seconds)
        if not args.no_reference:
            t0 = clock()
            reconstruct_reference(pulses, profile)
            best["reference"] = clock() - t0
        else:
            best["reference"] = 0.0
        for group in ("all", "large" if shot.label in large else "small"):
            sizes[group] += shot.raw_bytes
            for step in STEPS:
                totals[group][step] += best[step]
    print(f"profile {profile.name}, {len(shots)} shots, best of {args.repeat}; MB/s of raw file per step "
          f"(seconds in brackets)")
    print(f"{'group':6} {'MB':>7} " + " ".join(f"{step:>18}" for step in STEPS))
    for group, steps in totals.items():
        mb = sizes[group] / 1e6
        print(f"{group:6} {mb:7.1f} " + " ".join(
            f"{mb / s if s else float('inf'):9.1f} ({s:6.2f})" for s in steps.values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
