"""Time MATLAB's own converter on copies of the 309 sample shots, as the backends were timed.

    source venv/bin/activate   # with HELAB_DIR_*_OVERRIDE set (see run.sh)
    python .ai/sessions/2026-10-30-claude-matlab-bench/bench_matlab.py --variant 2019 [--single] [--repeats 3]

Copies every sample shot's raw file (``~/HeLab-samples/txy-v1``, read-only, checked by SHA-256) to
``.ai/temp/txy/matlab-bench/shots/<set>/d<N>.txt`` and runs MATLAB headless once per repeat. The
generated script calls exactly what MATLAB's converter calls per shot, with ``tic``/``toc`` around
each part: ``dld_read_5channels_reconst_multi_imp(file,1,0,1,0)`` (read + reconstruct) and
``dlmwrite(..., 'precision', 8)`` (write; the 2019 ``dld_raw_to_txy_counts`` skips an empty result,
the 2023 ``dld_raw_to_txy`` writes it). One untimed shot first, as the Python backends' warm-up.
``--single`` starts MATLAB with ``-singleCompThread`` (one core, comparable to the per-core table);
without it MATLAB uses its default implicit multithreading, as the lab runs it.

Appends one JSON line per repeat to ``timing/runs.jsonl`` beside this file; per-shot times go to
``timing/shots-<variant>-<mode>-<n>.csv``. Never touches the share, the sample set or ``legacy/``.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dev" / "txy"))
from _common import TEMP, guard  # noqa: E402

guard()
from helab.convert.samples import load_manifest, read_verified, select_shots  # noqa: E402

MATLAB = "/Applications/MATLAB_R2025b.app/bin/matlab"
VARIANTS = {
    "2019": (ROOT / "legacy/tdc_autoconverter/lib", True),
    "2023": (ROOT / "legacy/DLD_front_panel/lib/Core_BEC_Analysis/lib/import_mcp_tdc_data", False),
}
WORK = TEMP / "matlab-bench"
OUT = HERE / "timing"


def quote(path: Path) -> str:
    return str(path).replace("'", "''")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variant", choices=sorted(VARIANTS), default="2019")
    parser.add_argument("--single", action="store_true", help="MATLAB with -singleCompThread")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    folder, skip_empty = VARIANTS[args.variant]
    mode = "single" if args.single else "default"
    shots = select_shots(load_manifest(os.path.expanduser("~/HeLab-samples/txy-v1")), "all")
    OUT.mkdir(parents=True, exist_ok=True)

    sizes: dict[tuple[str, int], int] = {}
    expected: dict[tuple[str, int], str] = {}
    for shot in shots:
        target = WORK / "shots" / shot.set_name / f"d{shot.shot}.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != shot.raw_sha256:
            target.write_bytes(read_verified(shot.raw_path, shot.raw_sha256))
        sizes[(shot.set_name, shot.shot)] = shot.raw_bytes
        expected[(shot.set_name, shot.shot)] = shot.txy_sha256
    warm = WORK / "warm"
    warm.mkdir(parents=True, exist_ok=True)
    first = shots[0]
    (warm / f"d{first.shot}.txt").write_bytes(read_verified(first.raw_path, first.raw_sha256))

    for repeat in range(1, args.repeats + 1):
        for txy in (WORK / "shots").rglob("d_txy_forc*.txt"):
            txy.unlink()
        times = OUT / f"shots-{args.variant}-{mode}-{repeat}.csv"
        lines = [f"addpath('{quote(folder)}');",
                 f"fid = fopen('{quote(times)}', 'w'); fprintf(fid, 'set,shot,read_reconstruct,write,hits\\n');",
                 f"h = dld_read_5channels_reconst_multi_imp('{quote(warm / 'd')}{first.shot}',1,0,1,0);",
                 f"dlmwrite('{quote(warm / 'd')}_txy_forc{first.shot}.txt', h, 'precision', 8);",
                 "loop = tic;"]
        for shot in shots:
            base = quote(WORK / "shots" / shot.set_name / "d")
            write = f"dlmwrite('{base}_txy_forc{shot.shot}.txt', h, 'precision', 8);"
            if skip_empty:
                write = f"if ~isempty(h), {write} end"  # the caller adds the ";"
            lines.append(f"t = tic; h = dld_read_5channels_reconst_multi_imp('{base}{shot.shot}',1,0,1,0); "
                         f"tr = toc(t); t = tic; {write}; tw = toc(t); "
                         f"fprintf(fid, '{shot.set_name},{shot.shot},%.6f,%.6f,%d\\n', tr, tw, size(h,1));")
        lines += ["total = toc(loop); fclose(fid);",
                  f"fid = fopen('{quote(times)}.total', 'w'); fprintf(fid, '%.6f\\n', total); fclose(fid);"]
        script = WORK / f"bench_{args.variant}_{mode}.m"
        script.write_text("\n".join(lines) + "\n")
        command = [MATLAB, "-nodisplay", "-nosplash"] + (["-singleCompThread"] if args.single else [])
        load_before = os.getloadavg()
        start = time.perf_counter()
        done = subprocess.run(command + ["-batch", f"run('{quote(script)}')"], cwd=WORK)
        wall = time.perf_counter() - start
        if done.returncode:
            return done.returncode
        loop = float(Path(f"{times}.total").read_text())
        with times.open() as fh:
            rows = list(csv.DictReader(fh))
        rr = [float(r["read_reconstruct"]) for r in rows]
        ww = [float(r["write"]) for r in rows]
        per_shot = [a + b for a, b in zip(rr, ww)]
        total_bytes = sum(sizes[(r["set"], int(r["shot"]))] for r in rows)
        identical = 0
        for r in rows:
            txy = WORK / "shots" / r["set"] / f"d_txy_forc{r['shot']}.txt"
            if txy.exists() and hashlib.sha256(txy.read_bytes()).hexdigest() == expected[(r["set"], int(r["shot"]))]:
                identical += 1
        summary = {
            "variant": args.variant, "mode": mode, "repeat": repeat, "matlab": MATLAB, "shots": len(rows),
            "raw_mb": total_bytes / 1e6, "hits": sum(int(r["hits"]) for r in rows),
            "read_reconstruct_s": sum(rr), "write_s": sum(ww), "loop_s": loop, "process_wall_s": wall,
            "startup_s": wall - loop,
            "mb_per_s_total": total_bytes / 1e6 / sum(per_shot),
            "mb_per_s_read_reconstruct": total_bytes / 1e6 / sum(rr),
            "mb_per_s_write": total_bytes / 1e6 / sum(ww),
            "latency_ms_median": statistics.median(per_shot) * 1e3, "latency_ms_max": max(per_shot) * 1e3,
            "identical_to_sample_txy": identical, "load_before": load_before, "load_after": os.getloadavg(),
            "time": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        }
        with (OUT / "runs.jsonl").open("a") as fh:
            fh.write(json.dumps(summary) + "\n")
        print(json.dumps(summary), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
