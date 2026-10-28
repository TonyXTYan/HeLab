"""First-call cost per backend, each in a fresh interpreter: imports, backend start, first and second
conversion of the smallest non-empty sample shot and of the largest.

    source .ai/local/floor-env.sh; export NUMBA_CACHE_DIR=$PWD/.ai/temp/txy/numba-cache
    python .ai/sessions/2026-10-29-claude-txy-bench/first_call.py [--repeats 3]
        [--backends reference numpy numba cython rust mlx] [--out timing/first_call.jsonl]

Per child: ``import`` (helab.convert's pipeline, profile and registry, NumPy included), ``start``
(``get_backend(b).unavailable(profile)``: imports the backend module and its package, checks the
GPU for mlx), then ``convert_raw`` on the small shot twice and on the large shot twice. numba runs
twice per repeat: with the warm cache in ``NUMBA_CACHE_DIR`` and with a new empty one (compile).
Nothing is written but the JSON lines.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dev" / "txy"))
from _common import guard  # noqa: E402

guard()


def child(backend: str, root: str) -> None:
    clock = time.perf_counter
    t0 = clock()
    from helab.convert.pipeline import convert_raw
    from helab.convert.profile import builtin_profile
    from helab.convert.reconstruct import get_backend
    from helab.convert.samples import load_manifest, read_verified, select_shots
    t1 = clock()
    profile = builtin_profile("matlab-2019")
    problem = get_backend(backend).unavailable(profile)
    t2 = clock()
    if problem:
        raise SystemExit(problem)
    shots = select_shots(load_manifest(root), "all")
    small = min((s for s in shots if s.raw_bytes > 20_000), key=lambda s: s.raw_bytes)
    large = max(shots, key=lambda s: s.raw_bytes)
    data = {s.label: read_verified(s.raw_path, s.raw_sha256) for s in (small, large)}
    out: dict[str, object] = {"backend": backend, "import_s": t1 - t0, "start_s": t2 - t1,
                              "small": small.label, "small_MB": small.raw_bytes / 1e6,
                              "large": large.label, "large_MB": large.raw_bytes / 1e6}
    for name, shot in (("small", small), ("large", large)):
        for n in ("first", "second"):
            start = clock()
            convert_raw(data[shot.label], profile, backend)
            out[f"{name}_{n}_s"] = clock() - start
    print(json.dumps(out))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default="~/HeLab-samples/txy-v1")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--backends", nargs="*", default=["reference", "numpy", "numba", "cython", "rust", "mlx"])
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("timing") / "first_call.jsonl")
    parser.add_argument("--child")
    args = parser.parse_args()
    if args.child:
        child(args.child, args.root)
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for repeat in range(args.repeats):
        for backend in args.backends:
            variants = [("warm", None)]
            if backend == "numba":
                variants.append(("cold", tempfile.mkdtemp(prefix="numba-cold-", dir=ROOT / ".ai" / "temp")))
            for cache, folder in variants:
                env = dict(os.environ)
                if folder:
                    env["NUMBA_CACHE_DIR"] = folder
                load = os.getloadavg()
                result = subprocess.run([sys.executable, __file__, "--root", args.root, "--child", backend],
                                        env=env, capture_output=True, text=True, check=True)
                record = json.loads(result.stdout.strip().splitlines()[-1])
                record.update({"repeat": repeat, "cache": cache if backend == "numba" else None,
                               "load_before": load})
                with args.out.open("a") as stream:
                    stream.write(json.dumps(record) + "\n")
                print(f"{backend:9} {record['cache'] or '':4} import {record['import_s'] * 1e3:6.1f} ms start "
                      f"{record['start_s'] * 1e3:6.1f} ms small {record['small_first_s'] * 1e3:7.1f} / "
                      f"{record['small_second_s'] * 1e3:6.1f} ms large {record['large_first_s'] * 1e3:7.1f} / "
                      f"{record['large_second_s'] * 1e3:6.1f} ms (load {load[0]:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
