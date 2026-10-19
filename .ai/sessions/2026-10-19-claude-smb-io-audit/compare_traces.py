"""Compare two I/O traces phase by phase (before and after a change): one markdown table.

    python compare_traces.py BEFORE AFTER [--under PREFIX] [--under-after PREFIX]

BEFORE and AFTER are recordings' folders or single trace files (earlier builds).

Counts per phase (``op`` "phase" lines, as scenarios.py writes them; a trace without them, such as one
recorded with Help › Record I/O trace, is one "whole trace" row; phases match by name, else by the name
before " (" when that is unique, marked † with the earlier name below the table): helpers started, listings, stats
(stat, lstat, a listed entry's stat), .helab-root opens (Part 1 traced a marker read as one
``marker_read`` line, later traces as ``marker_open`` + ``marker_fstat`` + ``marker_read``: opens are
counted in both), whole-file reads, tail reads and icon lookups. Standalone (no HeLab import).
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from typing import Any


def trace_files(path: str) -> list[str]:
    """A trace file, or a recording folder's files (one per helper, ``*.jsonl``)."""
    if not os.path.isdir(path):
        return [path]
    return sorted(os.path.join(path, name) for name in os.listdir(path) if name.endswith(".jsonl"))


def records(path: str) -> list[dict[str, Any]]:
    found = []
    for file in trace_files(path):
        with open(file, encoding="utf-8") as stream:
            for line in stream:
                try:
                    found.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return sorted(found, key=lambda record: record.get("t", 0))


def per_phase(path: str, under: str) -> dict[str, Counter[str]]:
    items = records(path)
    split = "marker_open" in {record.get("op") for record in items}
    marks = [record for record in items if record.get("op") == "phase"]
    if not marks and items:
        marks = [{"name": "whole trace", "t": items[0].get("t", 0)}]
    result: dict[str, Counter[str]] = {}
    for index, mark in enumerate(marks):
        stop = marks[index + 1]["t"] if index + 1 < len(marks) else float("inf")
        counts: Counter[str] = Counter()
        for record in items:
            if not mark["t"] <= record.get("t", 0) < stop:
                continue
            op = str(record.get("op", ""))
            if op == "request":
                counts["helpers"] += 1
            if not str(record.get("path", "")).startswith(under):
                continue
            if op == "scandir":
                counts["listings"] += 1
            elif op in ("stat", "lstat", "entry_stat"):
                counts["stats"] += 1
            elif op == ("marker_open" if split else "marker_read"):
                counts["marker opens"] += 1
            elif op == "read":
                counts["reads"] += 1
            elif op == "read_tail":
                counts["tail reads"] += 1
            elif op == "icon":
                counts["icons"] += 1
        counts["seconds"] = round((stop if stop != float("inf") else items[-1].get("t", 0)) - mark["t"])
        result[mark["name"]] = counts
    return result


COLUMNS = ("helpers", "listings", "stats", "marker opens", "reads", "tail reads", "icons")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("--under", default="", help="count only paths starting with this (before)")
    parser.add_argument("--under-after", default=None, help="the same for the after trace (default: --under)")
    args = parser.parse_args()
    before = per_phase(args.before, args.under)
    after = per_phase(args.after, args.under if args.under_after is None else args.under_after)
    short = Counter(name.partition(" (")[0] for name in before)
    by_short = {name.partition(" (")[0]: name for name in before if short[name.partition(" (")[0]] == 1}
    renamed: list[tuple[str, str]] = []
    print("| Phase | s | " + " | ".join(f"{column} (before → after)" for column in COLUMNS) + " |")
    print("|---|---|" + "|".join("---" for _ in COLUMNS) + "|")
    for name, counts in after.items():
        old_name = name if name in before else by_short.get(name.partition(" (")[0], "")
        old = before.get(old_name, Counter())
        label = name
        if old_name and old_name != name:
            renamed.append((name, old_name))
            label = f"{name} †"
        cells = []
        for column in COLUMNS:
            a, b = old[column], counts[column]
            cells.append(f"{a:,}" if a == b else f"{a:,} → **{b:,}**")
        print(f"| {label} | {counts['seconds']} | " + " | ".join(cells) + " |")
    for name, old_name in renamed:
        print(f"\n† Before: “{old_name}”.")


if __name__ == "__main__":
    main()
