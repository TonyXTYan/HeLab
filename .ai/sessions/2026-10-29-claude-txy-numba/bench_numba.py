"""Numba backend measurements beyond ``dev/txy/time_samples.py``: first-call cost and within-shot.

    python .ai/sessions/2026-10-29-claude-txy-numba/bench_numba.py first-call
    python .ai/sessions/2026-10-29-claude-txy-numba/bench_numba.py within [--pieces 1 2 4 8 12] [--large 3]
    python .ai/sessions/2026-10-29-claude-txy-numba/bench_numba.py reconstruct [--positions all]
    python .ai/sessions/2026-10-29-claude-txy-numba/bench_numba.py threads [--positions all] [--workers 1 4 12]

``first-call``: in fresh processes, the import of numba, the first conversion with an empty cache
(``NUMBA_CACHE_DIR`` a new folder under ``.ai/temp/txy/``: compiles), the first with that cache
filled (loads), and the next call. ``within``: reconstruction only (parse excluded) of the
``--large`` largest shots of each set, best of 3, the whole shot against its pieces matched
serially, on a thread pool and with ``prange``. ``reconstruct``: reconstruction only, reference
against numba, per shot, all shots. ``threads``: reconstruction only of all shots (parsed first), on
a thread pool of each size: the wall time shows whether the backend runs without the GIL. Run from the checkout's root after ``source
.ai/local/floor-env.sh``.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "dev" / "txy"))

from _common import TEMP, guard, sample_arguments  # noqa: E402

guard()

FIRST_CALL = """
import json, sys, time
clock = time.perf_counter
start = clock()
import numba
imported = clock()
from helab.convert.profile import MATLAB_2019
from helab.convert.raw import parse_raw
from helab.convert.reconstruct import reconstruct
pulses = parse_raw(open(sys.argv[1], "rb").read())
ready = clock()
reconstruct(pulses, MATLAB_2019, "numba")
first = clock()
reconstruct(pulses, MATLAB_2019, "numba")
second = clock()
print(json.dumps({"import_numba": imported - start, "first_call": first - ready, "second_call": second - first}))
"""


def first_call() -> None:
    sample = ROOT / "tests" / "data" / "convert" / "cases" / "basic" / "d1.txt"
    TEMP.mkdir(parents=True, exist_ok=True)
    rows = []
    for attempt in range(3):
        cache = Path(tempfile.mkdtemp(prefix="numba-cache-", dir=TEMP))
        env = dict(os.environ, NUMBA_CACHE_DIR=str(cache))
        for label in ("empty cache (compile)", "cache filled (load)"):
            done = subprocess.run([sys.executable, "-c", FIRST_CALL, str(sample)], capture_output=True, text=True,
                                  env=env, cwd=ROOT, check=True)
            row = json.loads(done.stdout.splitlines()[-1])
            rows.append((label, row))
            print(f"{attempt} {label:24} import numba {row['import_numba'] * 1e3:7.1f} ms, first call "
                  f"{row['first_call'] * 1e3:8.1f} ms, next call {row['second_call'] * 1e6:7.1f} µs", flush=True)
        size = sum(path.stat().st_size for path in cache.rglob("*") if path.is_file())
        print(f"  cache folder: {size / 1e3:.0f} kB in {sum(1 for _ in cache.rglob('*.nbc'))} .nbc files")


def large_shots(args: argparse.Namespace) -> list[tuple[str, bytes]]:
    from helab.convert.samples import load_manifest, read_verified
    sets = load_manifest(args.root)
    out = []
    for s in sets:
        for shot in sorted(s.shots, key=lambda x: x.raw_bytes)[-args.large:]:
            out.append((shot.label, read_verified(shot.raw_path, shot.raw_sha256)))
    return out


def best(function: object, repeat: int = 3) -> float:
    times = []
    for _ in range(repeat):
        start = time.perf_counter()
        function()  # type: ignore[operator]
        times.append(time.perf_counter() - start)
    return min(times)


def within(args: argparse.Namespace) -> None:
    import numpy as np

    from helab.convert.backends.numba_backend import piece_bounds, reconstruct_numba, reconstruct_numba_pieces
    from helab.convert.profile import builtin_profile
    from helab.convert.raw import parse_raw
    profile = builtin_profile(args.profile)
    shots = [(label, len(data), parse_raw(data)) for label, data in large_shots(args)]
    reconstruct_numba(shots[0][2], profile)
    for mode in ("serial", "prange"):
        reconstruct_numba_pieces(shots[0][2], profile, 2, mode)  # type: ignore[arg-type]
    total_bytes = sum(size for _, size, _ in shots)
    print(f"{len(shots)} shots, {total_bytes / 1e6:.1f} MB raw, {sum(p.times.shape[0] for *_, p in shots):,} pulses;"
          f" reconstruction only, best of 3, MB/s of raw")
    results: dict[str, float] = {}
    whole = sum(best(lambda p=p: reconstruct_numba(p, profile)) for *_, p in shots)
    results["whole"] = whole
    print(f"  whole shot (registered backend)    {total_bytes / 1e6 / whole:8.1f} MB/s  {whole * 1e3:8.1f} ms")
    with ThreadPoolExecutor(max(args.pieces)) as pool:
        for k in args.pieces:
            cuts = [int(piece_bounds(p, profile, k).shape[0] - 1) for *_, p in shots]
            for mode in ("serial", "threads", "prange"):
                seconds = sum(best(lambda p=p: reconstruct_numba_pieces(p, profile, k, mode, pool))  # type: ignore[misc]
                              for *_, p in shots)
                results[f"{mode}-{k}"] = seconds
                print(f"  {k:3} pieces asked ({min(cuts)}–{max(cuts)} cut) {mode:8} {total_bytes / 1e6 / seconds:8.1f} MB/s"
                      f"  {seconds * 1e3:8.1f} ms", flush=True)
    for *_, p in shots[:2]:
        assert np.array_equal(reconstruct_numba_pieces(p, profile, max(args.pieces), "prange"),
                              reconstruct_numba(p, profile))


def reconstruct_only(args: argparse.Namespace) -> None:
    from helab.convert.profile import builtin_profile
    from helab.convert.raw import parse_raw
    from helab.convert.reconstruct import NoRowsError, reconstruct
    from helab.convert.samples import load_manifest, read_verified, select_shots
    profile = builtin_profile(args.profile)
    shots = select_shots(load_manifest(args.root), args.positions, args.sets)
    totals = {"reference": 0.0, "numba": 0.0}
    raw = 0
    reconstruct(parse_raw(b"5,1\r\n0,10\r\n"), profile, "numba")
    for shot in shots:
        data = read_verified(shot.raw_path, shot.raw_sha256)
        raw += len(data)
        pulses = parse_raw(data)
        for backend in totals:
            start = time.perf_counter()
            try:
                reconstruct(pulses, profile, backend)
            except NoRowsError:
                pass
            totals[backend] += time.perf_counter() - start
    for backend, seconds in totals.items():
        print(f"{backend:10} {len(shots)} shots {raw / 1e6:.1f} MB: reconstruction {raw / 1e6 / seconds:8.1f} MB/s"
              f" ({seconds:.2f} s)")
    print(f"speed-up {totals['reference'] / totals['numba']:.0f}x")


def threads(args: argparse.Namespace) -> None:
    from helab.convert.profile import builtin_profile
    from helab.convert.raw import parse_raw
    from helab.convert.reconstruct import NoRowsError, reconstruct
    from helab.convert.samples import load_manifest, read_verified, select_shots
    profile = builtin_profile(args.profile)
    shots = select_shots(load_manifest(args.root), args.positions, args.sets)
    raw = 0
    inputs = []
    for shot in shots:
        data = read_verified(shot.raw_path, shot.raw_sha256)
        raw += len(data)
        inputs.append(parse_raw(data))

    def one(pulses: object) -> None:
        try:
            reconstruct(pulses, profile, "numba")  # type: ignore[arg-type]
        except NoRowsError:
            pass

    one(inputs[0])
    for workers in args.workers:
        with ThreadPoolExecutor(workers) as pool:
            start = time.perf_counter()
            list(pool.map(one, inputs))
            wall = time.perf_counter() - start
        print(f"{workers:3} threads: {len(inputs)} shots {raw / 1e6:.1f} MB reconstructed in {wall:.3f} s wall,"
              f" {raw / 1e6 / wall:8.1f} MB/s", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("what", choices=("first-call", "within", "reconstruct", "threads"))
    sample_arguments(parser)
    parser.add_argument("--pieces", type=int, nargs="*", default=[1, 2, 4, 8, 12])
    parser.add_argument("--large", type=int, default=3)
    parser.add_argument("--workers", type=int, nargs="*", default=[1, 2, 4, 8, 12])
    args = parser.parse_args()
    print(f"load average {os.getloadavg()[0]:.1f} {os.getloadavg()[1]:.1f}")
    {"first-call": lambda: first_call(), "within": lambda: within(args),
     "reconstruct": lambda: reconstruct_only(args), "threads": lambda: threads(args)}[args.what]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
