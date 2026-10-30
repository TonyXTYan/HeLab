"""Markdown tables from ``timing/runs.jsonl`` and ``timing/first_call.jsonl`` (``run_all.sh``):
the median of the repeats and their spread (min–max) for each measure.

    python .ai/sessions/2026-10-29-claude-txy-bench/summarise.py [--timing DIR] > timing/tables.md
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
import sys
from typing import Any, Callable

BACKENDS = ["reference", "numpy", "numba", "cython", "rust", "mlx"]


def cell(values: list[float], digits: int = 0) -> str:
    if not values:
        return "–"
    med = statistics.median(values)
    if len(values) == 1:
        return f"{med:,.{digits}f}"
    return f"{med:,.{digits}f} ({min(values):,.{digits}f}–{max(values):,.{digits}f})"


def table(title: str, header: list[str], rows: list[list[str]]) -> str:
    lines = [f"### {title}", "", "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timing", type=Path, default=Path(__file__).with_name("timing"))
    args = parser.parse_args()
    runs = [json.loads(line) for line in (args.timing / "runs.jsonl").read_text().splitlines() if line.strip()]
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        groups[(run["backend"], run["mode"], run["workers"] or 1, run["shots"], run["profile"])].append(run)
    present = [b for b in BACKENDS if any(k[0] == b for k in groups)]

    def get(backend: str, mode: str, workers: int = 1, shots: str = "all", profile: str = "matlab-2019"
            ) -> list[dict[str, Any]]:
        return groups.get((backend, mode, workers, shots, profile), [])

    def vals(items: list[dict[str, Any]], part: str, key: str, scale: float = 1.0) -> list[float]:
        return [r["summary"][part][key] * scale for r in items if key in r["summary"][part]]

    def loads(items: list[dict[str, Any]]) -> str:
        values = [r["load_before"][0] for r in items]
        return f"{min(values):.1f}–{max(values):.1f}" if values else "–"

    out: list[str] = []
    rows = []
    for b in present:
        s = get(b, "serial")
        rows.append([b, cell(vals(s, "all", "read_MBps")), cell(vals(s, "all", "reconstruct_MBps")),
                     cell(vals(s, "small", "reconstruct_MBps")), cell(vals(s, "large", "reconstruct_MBps")),
                     cell(vals(s, "all", "write_MBps")), cell(vals(s, "all", "total_MBps"), 1), loads(s)])
    out.append(table("Serial, one core, all 309 shots (raw MB/s; median of repeats, min–max)",
                     ["backend", "read", "reconstruct", "reconstruct small", "reconstruct large", "write",
                      "total per core", "load"], rows))
    rows = []
    for b in present:
        s = get(b, "serial")
        rows.append([b, cell(vals(s, "all", "latency_median_s", 1e3), 1), cell(vals(s, "all", "latency_max_s", 1e3), 1),
                     cell(vals(s, "small", "latency_median_s", 1e3), 1),
                     cell(vals(s, "small", "latency_max_s", 1e3), 1),
                     cell(vals(s, "large", "latency_median_s", 1e3), 1),
                     cell(vals(s, "large", "latency_max_s", 1e3), 1)])
    out.append(table("Latency per shot, serial (read + reconstruct + write, ms)",
                     ["backend", "all median", "all max", "small median", "small max", "large median",
                      "large max"], rows))
    rows = []
    for b in present:
        s = get(b, "serial", profile="matlab-2023-lab-edit")
        rows.append([b, cell(vals(s, "all", "reconstruct_MBps")), cell(vals(s, "all", "total_MBps"), 1),
                     cell(vals(s, "all", "latency_max_s", 1e3), 1), loads(s)])
    out.append(table("Serial, `matlab-2023-lab-edit` (raw MB/s)",
                     ["backend", "reconstruct", "total per core", "latency max ms", "load"], rows))

    def scaling(title: str, mode: str, workers: list[int], key: str = "wall_MBps",
                only: Callable[[str], bool] = lambda b: True) -> None:
        rows = []
        for b in present:
            if not only(b) or not any(get(b, mode, w) for w in workers):
                continue
            rows.append([b] + [cell(vals(get(b, mode, w), "all", key)) for w in workers]
                        + [loads([r for w in workers for r in get(b, mode, w)])])
        out.append(table(title, ["backend"] + [f"×{w}" for w in workers] + ["load"], rows))

    scaling("Across shots, warm process pool: wall MB/s (pool started and each worker warmed first)",
            "processes-warm", [1, 2, 4, 8, 12, 16])
    scaling("Across shots, warm process pool: per-core MB/s (raw bytes over the sum of stage times)",
            "processes-warm", [1, 2, 4, 8, 12, 16], key="total_MBps")
    scaling("Across shots, cold process pool (`time_shots(PROCESSES)` as is: pool start, imports, first "
            "call inside wall): wall MB/s", "processes-cold", [1, 4, 12])
    scaling("Across shots, threads (backends that release the GIL; numpy for comparison): wall MB/s",
            "threads", [1, 4, 8])
    rows = []
    for b in present:
        serial = get(b, "serial")
        line = [b, cell(vals(serial, "large", "reconstruct_MBps")), cell(vals(serial, "large", "latency_max_s", 1e3), 1)]
        for w in (2, 4, 8):
            items = get(b, "within-shot", w, "large")
            line += [cell(vals(items, "all", "reconstruct_MBps")), cell(vals(items, "all", "latency_max_s", 1e3), 1)]
        rows.append(line)
    out.append(table("Within one shot (`split.reconstruct_split`), the 24 large shots: reconstruct MB/s and max "
                     "latency ms (threads for backends that release the GIL, processes otherwise)",
                     ["backend", "serial rec", "serial max", "×2 rec", "×2 max", "×4 rec", "×4 max", "×8 rec",
                      "×8 max"], rows))

    first = args.timing / "first_call.jsonl"
    if first.exists():
        calls = [json.loads(line) for line in first.read_text().splitlines() if line.strip()]
        rows = []
        for b in present:
            for cache in (None, "warm", "cold"):
                items = [c for c in calls if c["backend"] == b and c.get("cache") == cache]
                if not items:
                    continue
                f = lambda k: cell([c[k] * 1e3 for c in items], 1)  # noqa: E731
                rows.append([b + (f" ({cache} cache)" if cache else ""), f("import_s"), f("start_s"),
                             f("small_first_s"), f("small_second_s"), f("large_first_s"), f("large_second_s")])
        sample = calls[0] if calls else {}
        out.append(table(f"First call, fresh interpreter (ms; small = {sample.get('small')} "
                         f"{sample.get('small_MB', 0):.2f} MB, large = {sample.get('large')} "
                         f"{sample.get('large_MB', 0):.1f} MB; `convert_raw`, no file written)",
                         ["backend", "import helab.convert", "backend start", "small 1st", "small 2nd",
                          "large 1st", "large 2nd"], rows))
    sys.stdout.write("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
