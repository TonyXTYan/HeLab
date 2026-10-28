"""Stage 2's final timings: one run of stage 1's harness (``helab.convert.timing``) per call.

    source .ai/local/floor-env.sh; export NUMBA_CACHE_DIR=$PWD/.ai/temp/txy/numba-cache
    python .ai/sessions/2026-10-29-claude-txy-bench/bench.py --backend numpy --mode serial
        [--workers N] [--shots all|large] [--profile matlab-2019] [--out runs.jsonl]

Modes (all through ``timing.time_shot``, which reads, reconstructs and writes atomically):

- ``serial``: one shot after another in this process, after one untimed warm-up conversion (the
  first call's import/JIT/GPU start is measured apart, ``first_call.py``);
- ``processes-warm``: a process pool whose workers each converted a shot before the clock starts
  (the steady state of long-lived helpers); wall excludes the pool's start;
- ``processes-cold``: ``timing.time_shots(PROCESSES)`` as it is: wall includes starting the pool,
  each worker's imports and first call (a one-off folder conversion);
- ``threads``: ``timing.time_shots(THREADS)`` after a warm-up in this process;
- ``within-shot``: shots one after another, each cut by ``split.reconstruct_split`` into up to
  ``workers`` pieces on a warmed pool (threads for a backend with ``releases_gil``, processes
  otherwise, as the harness chooses).

Appends one JSON line (summary for all, small and large shots, the load before and after, the
machine) to ``--out``; per-shot timings go to ``.ai/temp/txy/bench/``. TXY are written under
``.ai/temp/txy/timing/`` as ``time_samples.py`` does. Reads the sample set read-only.
"""
from __future__ import annotations

import argparse
from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor
import json
import os
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dev" / "txy"))
from _common import TEMP, guard  # noqa: E402

guard()

from helab.convert.profile import DetectorProfile, builtin_profile  # noqa: E402
from helab.convert.reconstruct import get_backend  # noqa: E402
from helab.convert.samples import load_manifest, select_shots  # noqa: E402
from helab.convert.timing import Parallelism, ShotJob, ShotTiming, summarise, time_shot, time_shots  # noqa: E402

WARM_SHOT = "2023-03-momentum-bells/d1"  # any shot; converted once, untimed, before the clock


def jobs_for(root: str, shots: str) -> tuple[list[ShotJob], set[str]]:
    sets = load_manifest(root)
    large = {shot.label for s in sets for shot in sorted(s.shots, key=lambda x: x.raw_bytes)[-3:]}
    chosen = [s for s in select_shots(sets, "all") if shots == "all" or s.label in large]
    jobs = []
    for shot in chosen:
        out = TEMP / "timing" / shot.set_name
        out.mkdir(parents=True, exist_ok=True)
        jobs.append(ShotJob(shot.label, shot.raw_path, out / f"d_txy_helab_{shot.shot}.txy"))
    return jobs, large


def warm_job(root: str) -> ShotJob:
    shot = next(s for s in select_shots(load_manifest(root), "all") if s.label == WARM_SHOT)
    out = TEMP / "bench-warm"
    out.mkdir(parents=True, exist_ok=True)
    return ShotJob("warm", shot.raw_path, out / f"warm-{os.getpid()}.txy")


def _warm_worker(job: ShotJob, profile: DetectorProfile, backend: str) -> None:
    time_shot(job, profile, backend)


def _pid() -> int:
    time.sleep(0.05)  # keep a worker busy so every worker answers once
    return os.getpid()


def row(timings: list[ShotTiming], wall: float | None) -> dict[str, float]:
    s = summarise(timings, wall)
    out = {"shots": s.shots, "raw_MB": s.raw_bytes / 1e6, "hits": s.hits,
           "read_s": s.read, "reconstruct_s": s.reconstruct, "write_s": s.write,
           "read_MBps": s.mb_per_s(s.read), "reconstruct_MBps": s.mb_per_s(s.reconstruct),
           "write_MBps": s.mb_per_s(s.write), "total_MBps": s.mb_per_s(s.read + s.reconstruct + s.write),
           "latency_median_s": s.latency_median, "latency_max_s": s.latency_max}
    if wall is not None:
        out["wall_s"] = wall
        out["wall_MBps"] = s.mb_per_s(wall)
    return out


def run(args: argparse.Namespace) -> tuple[list[ShotTiming], float]:
    profile = builtin_profile(args.profile)
    jobs, _ = jobs_for(args.root, args.shots)
    warm = warm_job(args.root)
    workers = args.workers or 1
    clock = time.perf_counter
    if args.mode == "processes-cold":
        start = clock()
        timings = time_shots(jobs, profile, args.backend, Parallelism.PROCESSES, workers)
        return timings, clock() - start
    time_shot(warm, profile, args.backend)  # this process: imports, JIT cache, GPU start
    if args.mode == "serial":
        start = clock()
        timings = [time_shot(job, profile, args.backend) for job in jobs]
        return timings, clock() - start
    if args.mode == "threads":
        start = clock()
        timings = time_shots(jobs, profile, args.backend, Parallelism.THREADS, workers)
        return timings, clock() - start
    if args.mode == "processes-warm":
        with ProcessPoolExecutor(workers, initializer=_warm_worker, initargs=(warm, profile, args.backend)) as pool:
            pids = {f.result() for f in [pool.submit(_pid) for _ in range(workers * 4)]}
            start = clock()
            timings = list(pool.map(time_shot, jobs, [profile] * len(jobs), [args.backend] * len(jobs)))
            took = clock() - start
        if len(pids) < workers:
            print(f"warning: only {len(pids)} of {workers} workers answered the warm-up", file=sys.stderr)
        return timings, took
    if args.mode == "within-shot":
        pieces: Executor = (ThreadPoolExecutor(workers) if get_backend(args.backend).releases_gil
                            else ProcessPoolExecutor(workers))
        with pieces:
            time_shot(warm, profile, args.backend, pieces, workers)
            largest = max(jobs, key=lambda j: j.raw_path.stat().st_size)
            time_shot(ShotJob("warm", largest.raw_path, warm.txy_path), profile, args.backend, pieces, workers)
            start = clock()
            timings = [time_shot(job, profile, args.backend, pieces, workers) for job in jobs]
            return timings, clock() - start
    raise SystemExit(f"unknown mode {args.mode}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default="~/HeLab-samples/txy-v1")
    parser.add_argument("--backend", required=True)
    parser.add_argument("--mode", required=True,
                        choices=["serial", "processes-warm", "processes-cold", "threads", "within-shot"])
    parser.add_argument("--workers", type=int)
    parser.add_argument("--shots", choices=["all", "large"], default="all")
    parser.add_argument("--profile", default="matlab-2019")
    parser.add_argument("--repeat", type=int, default=0, help="the repeat's number, recorded only")
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("timing") / "runs.jsonl")
    args = parser.parse_args()
    load_before = os.getloadavg()
    timings, wall = run(args)
    load_after = os.getloadavg()
    _, large = jobs_for(args.root, args.shots)
    record = {"backend": args.backend, "mode": args.mode, "workers": args.workers, "shots": args.shots,
              "profile": args.profile, "repeat": args.repeat, "load_before": load_before,
              "load_after": load_after, "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "machine": platform.platform(),
              "summary": {"all": row(timings, wall),
                          "small": row([t for t in timings if t.label not in large], None),
                          "large": row([t for t in timings if t.label in large], None)}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a") as stream:
        stream.write(json.dumps(record) + "\n")
    detail = TEMP / "bench" / f"{args.backend}-{args.mode}-{args.workers}-{args.shots}-{args.repeat}.json"
    detail.parent.mkdir(parents=True, exist_ok=True)
    detail.write_text(json.dumps([t.__dict__ for t in timings]))
    a = record["summary"]["all"]
    print(f"{args.backend:9} {args.mode:14} x{args.workers or 1:<2} {args.shots:5} r{args.repeat} "
          f"load {load_before[0]:5.2f} | read {a['read_MBps']:7.1f} rec {a['reconstruct_MBps']:7.1f} "
          f"write {a['write_MBps']:7.1f} core {a['total_MBps']:7.1f} wall {a['wall_MBps']:7.1f} MB/s | "
          f"lat {a['latency_median_s'] * 1e3:6.1f} / {a['latency_max_s'] * 1e3:6.1f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
