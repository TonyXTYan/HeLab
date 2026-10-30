"""Timings the harness doesn't take, for the rust backend's results.md.

    source .ai/local/floor-env.sh
    python .ai/sessions/2026-10-29-claude-txy-rust/bench_rust.py [--positions all] [--repeat 3]

1. ``within``: reconstruction only, one shot at a time, split on 1, 2, 4, 8 and 16 Rust threads
   (``reconstruct_rust(threads=…)``): raw MB/s over all shots and over the large ones (the three
   largest of each set), the best of ``--repeat``.
2. ``stages``: inside the rust reconstruction of the large shots: the Python wrapper and copies,
   the sort alone (NumPy's stable argsort, for scale) against the whole call.
3. ``io``: reading and writing: ``raw.parse_raw`` (Python) against the Rust ``parse_strict``, and
   ``txy.format_txy`` (Python) against the Rust ``format_txy``, on every shot (bytes in memory, no
   disk), with the outputs compared.
4. ``first``: first-call cost, in a fresh interpreter: importing the backend module, importing the
   compiled module, the first and the second call on a small shot.

The sample set is read only; nothing is written. Prints one line per measure.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "dev" / "txy"))

from _common import guard, sample_arguments  # noqa: E402

guard()

import numpy as np  # noqa: E402

from helab.convert.backends.rust import native, reconstruct_rust  # noqa: E402
from helab.convert.profile import builtin_profile  # noqa: E402
from helab.convert.raw import parse_raw  # noqa: E402
from helab.convert.samples import load_manifest, read_verified, select_shots  # noqa: E402
from helab.convert.txy import format_txy  # noqa: E402

FIRST_CALL = """
import time
t0 = time.perf_counter()
import helab.convert.backends.rust as rust
t1 = time.perf_counter()
module = rust.native()
t2 = time.perf_counter()
from helab.convert.profile import MATLAB_2019
from helab.convert.raw import parse_raw
pulses = parse_raw(b"5,1000\\r\\n0,10000\\r\\n1,10400\\r\\n2,10100\\r\\n3,10300\\r\\n")
t3 = time.perf_counter()
rust.reconstruct_rust(pulses, MATLAB_2019)
t4 = time.perf_counter()
rust.reconstruct_rust(pulses, MATLAB_2019)
t5 = time.perf_counter()
print(t1 - t0, t2 - t1, t4 - t3, t5 - t4)
"""


def best(repeat: int, run: object) -> float:
    assert callable(run)
    times = []
    for _ in range(repeat):
        start = time.perf_counter()
        run()
        times.append(time.perf_counter() - start)
    return min(times)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sample_arguments(parser)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--only", nargs="*", default=["within", "stages", "io", "first"])
    args = parser.parse_args()
    module = native()
    assert module is not None, "build native/rust first"
    profile = builtin_profile(args.profile)
    sets = load_manifest(args.root)
    shots = select_shots(sets, args.positions, args.sets)
    large = {shot.label for s in sets for shot in sorted(s.shots, key=lambda x: x.raw_bytes)[-3:]}
    data = {shot.label: read_verified(shot.raw_path, shot.raw_sha256) for shot in shots}
    pulses = {label: parse_raw(raw) for label, raw in data.items()}
    total = sum(len(raw) for raw in data.values()) / 1e6
    total_large = sum(len(data[label]) for label in data if label in large) / 1e6
    print(f"{len(shots)} shots, {total:.1f} MB ({total_large:.1f} MB in the {len(large & set(data))} large); "
          f"{platform.machine()} {os.cpu_count()} cores; load {os.getloadavg()[0]:.1f}; profile {profile.name}")

    if "within" in args.only:
        for threads in (1, 2, 4, 8, 16):
            seconds = {label: best(args.repeat, lambda p=p: reconstruct_rust(p, profile, threads))
                       for label, p in pulses.items()}
            all_s, large_s = sum(seconds.values()), sum(s for label, s in seconds.items() if label in large)
            print(f"within  threads {threads:2}: reconstruct {total / all_s:7.1f} MB/s all, "
                  f"{total_large / large_s:7.1f} MB/s large; load {os.getloadavg()[0]:.1f}")

    if "stages" in args.only:
        whole = copies = sort = 0.0
        for label in large & set(pulses):
            p = pulses[label]
            whole += best(args.repeat, lambda p=p: reconstruct_rust(p, profile))
            copies += best(args.repeat, lambda p=p: (np.ascontiguousarray(p.channels).copy(),
                                                       np.ascontiguousarray(p.times).copy()))
            sort += best(args.repeat, lambda p=p: np.argsort(p.times, kind="stable"))
        print(f"stages  large shots: whole call {whole * 1e3:.1f} ms ({total_large / whole:.1f} MB/s); "
              f"input copies {copies * 1e3:.1f} ms; NumPy stable argsort alone {sort * 1e3:.1f} ms")

    if "io" in args.only:
        py_read = rs_read = py_write = rs_write = 0.0
        strict = 0
        hits = {label: reconstruct_rust(p, profile)[0] for label, p in pulses.items() if len(p)}
        for label, raw in data.items():
            py_read += best(args.repeat, lambda raw=raw: parse_raw(raw))
            rs_read += best(args.repeat, lambda raw=raw: module.parse_strict(raw))
            got = module.parse_strict(raw)
            if got is not None:
                strict += 1
                ref = pulses[label]
                assert got[0].tobytes() == ref.channels.tobytes() and got[1].tobytes() == ref.times.tobytes(), label
        written = 0
        for label, h in hits.items():
            flat = np.ascontiguousarray(h.ravel())
            py_write += best(args.repeat, lambda h=h: format_txy(h))
            rs_write += best(args.repeat, lambda flat=flat: module.format_txy(flat))
            text = format_txy(h)
            assert module.format_txy(flat) == text, label
            written += len(text)
        print(f"io      read  (raw MB/s): Python parse_raw {total / py_read:7.1f}, Rust parse_strict {total / rs_read:7.1f}"
              f" ({strict} of {len(data)} files strict, identical arrays)")
        print(f"io      write (raw MB/s): Python format_txy {total / py_write:7.1f}, Rust format_txy {total / rs_write:7.1f}"
              f" ({written / 1e6:.1f} MB of TXY text, identical bytes)")

    if "first" in args.only:
        runs = []
        for _ in range(5):
            out = subprocess.run([sys.executable, "-c", FIRST_CALL], capture_output=True, text=True, check=True,
                                 cwd=ROOT, env=dict(os.environ))
            runs.append([float(x) for x in out.stdout.split()])
        med = np.median(np.array(runs), axis=0) * 1e3
        print(f"first   (median of 5 fresh interpreters, ms): import backend module {med[0]:.2f}, import "
              f"helab_convert_rs {med[1]:.2f}, first call {med[2]:.3f}, second call {med[3]:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
