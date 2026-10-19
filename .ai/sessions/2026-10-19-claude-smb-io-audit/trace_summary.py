"""Summarise a HeLab I/O trace (HELAB_IO_TRACE=<file>): what helpers did to source folders, how often, why.

    python trace_summary.py TRACE.jsonl [--under /Volumes/dld_output] [--minutes] [--young 5]

Standalone (no HeLab import). Lines with ``op`` "phase" (written by scenarios.py) split the trace into
phases; without them the whole trace is one phase, and ``--minutes`` adds a per-minute timeline.
Lines from the fake acquisition writer (``writer_*``) mark when each file was being written: any
helper operation on a file inside that window is listed as touching a file still being written.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import os
from typing import Any, Iterable

# Helper lines that are bookkeeping, not operations on a source folder.
NOT_SOURCE = {"request", "request_end", "mounts", "volume_id", "phase"}
# What each operation costs on SMB, roughly (requests to the server; a cached attribute may need none).
COST = {"scandir": "CREATE + QUERY_DIRECTORY×n + CLOSE", "stat": "CREATE/QUERY_INFO (or cached)",
        "lstat": "CREATE/QUERY_INFO (or cached)", "entry_stat": "QUERY_INFO (macOS); none (Windows)",
        "read": "CREATE + READ×n + CLOSE", "read_tail": "CREATE + READ + CLOSE",
        "marker_open": "CREATE (a missing one: CREATE fails)", "marker_fstat": "QUERY_INFO (or cached)",
        "marker_read": "READ + CLOSE", "icon": "several (native lookup)", "marker_write": "CREATE + WRITE + CLOSE"}


def tail_marker_icon(op: str) -> bool:
    return op in ("read_tail", "icon") or op.startswith("marker_")


def load(path: str) -> tuple[list[dict[str, Any]], int]:
    records, bad = [], 0
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1
    records.sort(key=lambda record: record.get("t", 0))
    return records, bad


def phases(records: list[dict[str, Any]]) -> list[tuple[str, float, float, list[dict[str, Any]]]]:
    marks = [record for record in records if record.get("op") == "phase"]
    end = max((record.get("t", 0) for record in records), default=0.0)
    if not marks:
        start = min((record.get("t", 0) for record in records), default=0.0)
        return [("whole trace", start, end, records)]
    result = []
    for index, mark in enumerate(marks):
        stop = marks[index + 1]["t"] if index + 1 < len(marks) else end
        result.append((mark["name"], mark["t"], stop,
                       [record for record in records if mark["t"] <= record.get("t", 0) < stop
                        and record.get("op") != "phase"]))
    return result


def source_ops(records: Iterable[dict[str, Any]], under: str) -> list[dict[str, Any]]:
    return [record for record in records
            if record.get("op") not in NOT_SOURCE and not str(record.get("op", "")).startswith(("writer", "gui:"))
            and str(record.get("path", "")).startswith(under)]


# Requests a tab asks for (its browsing, loads, Live, icons); the rest are the app's own jobs.
TAB_REQUESTS = ("resolve", "list", "details", "scan", "load", "live", "cached", "icons", "root_create")


def tab_names(records: list[dict[str, Any]]) -> dict[str, str]:
    """Tabs' owner ids by first appearance: tab1 (with tab1:bg, tab1:live, tab1:live-save), tab2…"""
    names: dict[str, str] = {}
    for record in records:
        if record.get("op") != "request" or record.get("request") not in TAB_REQUESTS:
            continue
        for owner in record.get("tabs") or ():
            base = str(owner).partition(":")[0]
            if base not in names:
                names[base] = f"tab{len(names) + 1}"
    return names


def who(record: dict[str, Any], names: dict[str, str]) -> str:
    labels = set()
    for owner in record.get("tabs") or []:
        base, colon, suffix = str(owner).partition(":")
        labels.add(names[base] + colon + suffix if base in names else "app")
    return ",".join(sorted(labels)) or "app"


def table(rows: list[list[Any]], header: list[str]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join(out)


def per_minute(count: int, seconds: float) -> str:
    return f"{count / seconds * 60:,.1f}" if seconds > 0 else "–"


def writes_in_progress(records: list[dict[str, Any]]) -> dict[str, list[tuple[float, float]]]:
    """Each file's write windows, from the fake writer's lines."""
    started: dict[str, float] = {}
    windows: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for record in records:
        if record.get("op") == "writer_start":
            started[record["path"]] = record["t"]
        elif record.get("op") == "writer_end" and record["path"] in started:
            windows[record["path"]].append((started.pop(record["path"]), record["t"]))
    for path, t in started.items():
        windows[path].append((t, float("inf")))
    return windows


def young_touches(records: list[dict[str, Any]], young: float) -> list[dict[str, Any]]:
    """Operations on a file whose mtime (as the operation itself saw it, else the latest one seen)
    was under ``young`` seconds old: files that may still be being written."""
    mtimes: dict[str, int] = {}
    found = []
    for record in records:
        path = str(record.get("path", ""))
        if "mtime_ns" in record:
            mtimes[path] = int(record["mtime_ns"])
        if record.get("op") in ("stat", "lstat", "entry_stat", "read", "read_tail") and path in mtimes:
            age = record["t"] - mtimes[path] / 1e9
            if age < young and os.path.basename(path).startswith("d"):
                found.append({**record, "age": age})
    return found


def report(path: str, under: str, minutes: bool, young: float) -> str:
    records, bad = load(path)
    names = tab_names(records)
    lines = [f"# I/O trace summary: {path}", ""]
    if bad:
        lines += [f"{bad} unreadable line(s) skipped.", ""]
    rows = []
    for name, start, stop, items in phases(records):
        ops = source_ops(items, under)
        seconds = stop - start
        helpers = sum(record.get("op") == "request" for record in items)
        gui = sum(str(record.get("op", "")).startswith("gui:") for record in items)
        reads = [record for record in ops if record["op"] == "read"]
        rows.append([name, f"{seconds:,.0f}", helpers, len(ops), per_minute(len(ops), seconds),
                     sum(record["op"] == "scandir" for record in ops),
                     sum(record["op"] in ("stat", "lstat", "entry_stat") for record in ops),
                     f"{len(reads)} ({sum(int(r.get('bytes', 0)) for r in reads) / 1e6:,.1f} MB)",
                     sum(tail_marker_icon(record["op"]) for record in ops), gui])
    lines += ["## Phases", "", table(rows, ["Phase", "Seconds", "Helpers", "Source ops", "Ops/min", "Listings",
                                             "Stats", "Reads", "Tail/marker/icon", "GUI-process"]), ""]
    for name, start, stop, items in phases(records):
        ops = source_ops(items, under)
        if not ops and not any(record.get("op") == "request" for record in items):
            continue
        seconds = stop - start
        lines += [f"## {name} ({seconds:,.0f} s)", ""]
        started = Counter((record.get("request", ""), who(record, names), ",".join(record.get("flags") or []))
                          for record in items if record.get("op") == "request")
        lines += [table([[kind, tabs, flags or "–", count, per_minute(count, seconds)]
                         for (kind, tabs, flags), count in started.most_common()],
                        ["Request", "For", "Flags", "Helpers", "Per min"]), ""]
        by = Counter((record.get("request", ""), record["op"], record["reason"]) for record in ops)
        lines += [table([[kind, op, reason, count, per_minute(count, seconds), COST.get(op, "")]
                         for (kind, op, reason), count in by.most_common()],
                        ["Request", "Op", "Reason", "Count", "Per min", "SMB cost (rough)"]), ""]
        repeated = Counter((record["op"], record["path"]) for record in ops)
        hot = [(op, target, count) for (op, target), count in repeated.most_common(8) if count > 2]
        if hot:
            lines += ["Most repeated:", "", table([[op, target.removeprefix(under), count] for op, target, count in hot],
                                                  ["Op", "Path", "Times"]), ""]
        if minutes and seconds > 60:
            buckets = Counter(int((record["t"] - start) // 60) for record in ops)
            lines += ["Per minute: " + ", ".join(f"{minute}: {buckets.get(minute, 0)}"
                                                 for minute in range(int(seconds // 60) + 1)), ""]
    windows = writes_in_progress(records)
    if windows:
        during = [record for record in source_ops(records, under)
                  if any(start <= record["t"] <= stop for start, stop in windows.get(record["path"], ()))]
        lines += ["## Files touched while the fake writer was writing them", ""]
        lines += [table([[record["op"], record["reason"], record.get("request", ""),
                          os.path.basename(record["path"]), f"{record['t']:.2f}"] for record in during],
                        ["Op", "Reason", "Request", "File", "t"]) if during else "None.", ""]
    touched = young_touches(source_ops(records, under), young)
    lines += [f"## Operations on files modified under {young:g} s before (by the mtime they saw)", ""]
    if touched:
        summary = Counter((record["op"], record["reason"], record.get("request", "")) for record in touched)
        lines += [table([[op, reason, kind, count, f"{min(r['age'] for r in touched if (r['op'], r['reason']) == (op, reason)):.2f}"]
                         for (op, reason, kind), count in summary.most_common()],
                        ["Op", "Reason", "Request", "Count", "Youngest age (s)"]), ""]
    else:
        lines += ["None.", ""]
    gui = [record for record in records if str(record.get("op", "")).startswith("gui:")]
    lines += ["## GUI-process source calls (scenarios.py's hook)", "",
              table([[r["op"], r["path"]] for r in gui[:20]], ["Call", "Path"]) if gui else "None.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("trace")
    parser.add_argument("--under", default="", help="count only paths starting with this (e.g. the share)")
    parser.add_argument("--minutes", action="store_true", help="per-minute counts for long phases")
    parser.add_argument("--young", type=float, default=5.0, help="seconds a file counts as maybe being written")
    args = parser.parse_args()
    print(report(args.trace, args.under, args.minutes, args.young).rstrip("\n"))


if __name__ == "__main__":
    main()
