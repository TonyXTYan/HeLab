"""The shared text I/O on every sample shot, stage 1's paths beside the fast ones, and the
backend's first-call cost.

    source .ai/local/floor-env.sh
    python .ai/sessions/2026-10-29-claude-txy-numpy/bench_io.py

Raw MB/s (SI) of the raw files: parse (bytes to arrays), format (hits to TXY bytes), and the
atomic write alone (under .ai/temp/txy/bench/). Best of three, one thread, then 8 threads.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dev" / "txy"))
from _common import TEMP, guard  # noqa: E402

guard()

import numpy as np  # noqa: E402

from helab.convert import fastio, raw  # noqa: E402
from helab.convert.profile import MATLAB_2019  # noqa: E402
from helab.convert.raw import RawPulses  # noqa: E402
from helab.convert.reconstruct import reconstruct  # noqa: E402
from helab.convert.samples import load_manifest, read_verified, select_shots  # noqa: E402
from helab.convert.txy import format_txy_by_value, write_atomic  # noqa: E402

STRICT = re.compile(rb"(?:[0-9]+,[0-9]+\r\n)*|(?:[0-9]+,[0-9]+\n)*")


def stage1_parse(data: bytes) -> RawPulses:
    """Stage 1's strict path (the regex, then int per field)."""
    if not STRICT.fullmatch(data):
        return raw._parse_textscan(data)
    fields = data.replace(b"\r\n", b"\n").replace(b"\n", b",").split(b",")[:-1]
    values = np.array([int(field) for field in fields], dtype=np.float64).reshape(-1, 2)
    return RawPulses(np.ascontiguousarray(values[:, 0]), np.ascontiguousarray(values[:, 1]))


def best(label: str, work: list[object], size: int, function: object, threads: int = 1) -> None:
    times = []
    for _ in range(3):
        start = time.perf_counter()
        if threads == 1:
            for item in work:
                function(item)  # type: ignore[operator]
        else:
            with ThreadPoolExecutor(threads) as pool:
                list(pool.map(function, work))  # type: ignore[arg-type]
        times.append(time.perf_counter() - start)
    print(f"{label:34} {size / 1e6 / min(times):8.0f} MB/s")


FIRST = """
import time
start = time.perf_counter()
import helab.convert.backends.numpy_backend
imported = time.perf_counter()
from helab.convert.pipeline import convert_raw
from helab.convert.profile import MATLAB_2019
data = open(%r, "rb").read()
a = time.perf_counter(); convert_raw(data, MATLAB_2019, "numpy"); b = time.perf_counter()
convert_raw(data, MATLAB_2019, "numpy"); c = time.perf_counter()
print(f"import {1e3 * (imported - start):.0f} ms, first convert {1e3 * (b - a):.1f} ms, second {1e3 * (c - b):.1f} ms")
"""


def main() -> int:
    shots = select_shots(load_manifest("~/HeLab-samples/txy-v1"), "all")
    datas = [read_verified(shot.raw_path, shot.raw_sha256) for shot in shots]
    size = sum(map(len, datas))
    hits = [reconstruct(fastio_pulses(data), MATLAB_2019, "numpy") if len(data) > 500 else np.empty((0, 3))
            for data in datas]
    print(f"{len(datas)} shots, {size / 1e6:.1f} MB raw, {sum(h.shape[0] for h in hits)} hits")
    best("parse, stage 1 (regex + int)", list(datas), size, stage1_parse)
    best("parse, fastio", list(datas), size, raw.parse_raw)
    best("parse, fastio, 8 threads", list(datas), size, raw.parse_raw, 8)
    best("format, stage 1 (value by value)", list(hits), size, format_txy_by_value)
    best("format, fastio", list(hits), size, fastio.format_txy)
    best("format, fastio, 8 threads", list(hits), size, fastio.format_txy, 8)
    folder = TEMP / "bench"
    folder.mkdir(parents=True, exist_ok=True)
    texts = [fastio.format_txy(h) for h in hits]
    best("atomic write only (fsync, rename)", [(folder / f"d{k}.txy", t) for k, t in enumerate(texts)], size,
         lambda job: write_atomic(*job))
    for shot in (shots[0], max(shots, key=lambda s: s.raw_bytes)):
        done = subprocess.run([sys.executable, "-c", FIRST % str(shot.raw_path)], capture_output=True, text=True,
                              cwd=ROOT)
        print(f"first call, {shot.label} ({shot.raw_bytes / 1e6:.2f} MB): {done.stdout.strip() or done.stderr}")
    return 0


def fastio_pulses(data: bytes) -> RawPulses:
    return raw.parse_raw(data)


if __name__ == "__main__":
    sys.exit(main())
