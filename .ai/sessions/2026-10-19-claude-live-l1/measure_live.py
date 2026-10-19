"""Measure Live checks through the real IOService and helper processes (no GUI, no cache).

1. What a check costs, end to end (submit → last event) and inside the helper, for an unchanged
   folder (one stat), a listing with nothing new, and one new file, at several folder sizes.
2. Whether checks every few seconds starve a background load: its paused share of wall time
   with Live checks holding background work like any foreground load ("old"), and only while
   they read a file ("new", the rule this branch uses).

Run from the floor root after ``source .ai/local/floor-env.sh && source venv/bin/activate``:
    python .ai/sessions/2026-10-19-claude-live-l1/measure_live.py [--scratch DIR]
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time
from typing import Any

for name in ("HELAB_APP_DIR_OVERRIDE", "HELAB_DIR_CACHES_OVERRIDE", "HELAB_DIR_TEMPS_OVERRIDE"):
    if not os.environ.get(name):
        sys.exit(f"{name} is not set: source .ai/local/floor-env.sh first")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("HELAB_SETTLE_SECONDS", "0")

from PyQt6.QtCore import QCoreApplication  # noqa: E402

from helab.utils.io_service import IORequest, IOService  # noqa: E402

app = QCoreApplication(sys.argv)


def make_folder(root: Path, count: int, rows: int = 1) -> Path:
    folder = root / f"run{count}"
    folder.mkdir()
    line = "".join(f"{i},2,3\n" for i in range(rows))
    for shot in range(1, count + 1):
        (folder / f"d_txy_forc{shot}.txt").write_text(line)
    old = time.time() - 300
    for file in folder.iterdir():
        os.utime(file, (old, old))
    os.utime(folder, (old, old))
    return folder


def memory(folder: Path) -> list[list[int]]:
    entries = []
    for file in folder.iterdir():
        info = file.stat()
        entries.append([int(file.name[10:-4]), info.st_size, info.st_mtime_ns])
    return sorted(entries)


def wait(service: IOService, owner: str, timeout: float = 120.0) -> list[dict[str, Any]]:
    """Run the event loop until the owner's request reports done or error; its events."""
    events: list[dict[str, Any]] = []

    def collect(request: IORequest, event: dict[str, Any]) -> None:
        if request.owner == owner:
            events.append({**event, "_at": time.monotonic()})
    service.resultReady.connect(collect)
    deadline = time.monotonic() + timeout
    while not any(event["kind"] in ("done", "error") for event in events) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    service.resultReady.disconnect(collect)
    return events


def check(service: IOService, folder: Path, held: list[list[int]], since: int | None) -> tuple[float, dict[str, Any]]:
    owner = f"live-{time.monotonic_ns()}"
    started = time.monotonic()
    service.submit(owner, 0, str(folder), "load", {"live": True, "memory": held, "live_since": since})
    events = wait(service, owner)
    result = next(event for event in events if event["kind"] in ("live_unchanged", "loaded", "error"))
    if result["kind"] == "error":
        raise RuntimeError(result["message"])
    return events[-1]["_at"] - started, result


def costs(service: IOService, root: Path) -> None:
    print("Check cost (local APFS; median of 5; end to end includes the helper process):")
    for count in (100, 1000, 10000):
        folder = make_folder(root, count)
        held = memory(folder)
        since = check(service, folder, held, None)[1]["live_since"]
        rows: dict[str, list[tuple[float, float]]] = {"unchanged (one stat)": [], "listed, nothing new": [],
                                                       "one new file": []}
        for _ in range(5):
            total, result = check(service, folder, held, since)
            rows["unchanged (one stat)"].append((total, result["live_seconds"]))
            total, result = check(service, folder, held, None)
            rows["listed, nothing new"].append((total, result["live_seconds"]))
            new = folder / f"d_txy_forc{count + 1}.txt"
            new.write_text("1,2,3\n")
            old = time.time() - 60
            os.utime(new, (old, old))
            total, result = check(service, folder, held, None)
            rows["one new file"].append((total, result["live_seconds"]))
            new.unlink()
            old = time.time() - 300
            os.utime(folder, (old, old))
            since = check(service, folder, held, None)[1]["live_since"]
        for label, values in rows.items():
            print(f"  {count:>6,} files, {label:<22} end to end {statistics.median(v[0] for v in values) * 1000:7.0f} ms"
                  f" · in the helper {statistics.median(v[1] for v in values) * 1000:7.1f} ms")


def starvation(service: IOService, root: Path, rule: str, seconds: float, interval: float) -> None:
    big = root / f"bg-{rule}"
    big.mkdir()
    line = "".join(f"{i},2,3\n" for i in range(5000))
    for shot in range(1, 1001):
        (big / f"d_txy_forc{shot}.txt").write_text(line)
    (root / f"live-{rule}").mkdir()
    watched = make_folder(root / f"live-{rule}", 200)
    held = memory(watched)
    original = IOService.__dict__["live"]
    if rule == "old":
        IOService.live = staticmethod(lambda request: False)  # type: ignore[method-assign]
    service.is_foreground = lambda request: bool(request.payload.get("live"))
    paused_at: list[float] = []
    paused = 0.0
    files = pauses = loads = 0
    running = False

    def track(request: IORequest, event: dict[str, Any]) -> None:
        nonlocal paused, files, pauses, running
        if not request.owner.startswith("bg"):
            return
        if event["kind"] == "paused":
            pauses += 1
            paused_at.append(time.monotonic())
        elif event["kind"] == "resumed" and paused_at:
            paused += time.monotonic() - paused_at.pop()
        elif event["kind"] == "file_finished":
            files += 1
        elif event["kind"] in ("done", "error", "cancelled"):
            running = False
    service.resultReady.connect(track)
    started = time.monotonic()
    checks = 0
    next_check = started
    new_shot = 300
    while time.monotonic() - started < seconds:
        if not running:
            # Background work all the time: the next load as soon as one ends.
            loads += 1
            running = service.submit(f"bg{loads}", 0, str(big), "load", {})
        if rule != "none" and time.monotonic() >= next_check:
            if checks % 3 == 2:  # Every third check finds a new shot.
                file = watched / f"d_txy_forc{new_shot}.txt"
                file.write_text("1,2,3\n")
                old = time.time() - 60
                os.utime(file, (old, old))
                new_shot += 1
            check(service, watched, held, None)
            checks += 1
            next_check = time.monotonic() + interval
        app.processEvents()
        time.sleep(0.001)
    elapsed = time.monotonic() - started
    if paused_at:
        paused += time.monotonic() - paused_at.pop()
    service.cancel(f"bg{loads}")
    service.resultReady.disconnect(track)
    IOService.live = original  # type: ignore[method-assign]  # (The staticmethod itself.)
    print(f"  {rule:>4}: {checks} checks in {elapsed:.0f} s; background loads paused {pauses} times, "
          f"{paused / elapsed:.0%} of the time; {files / elapsed:,.0f} files/s")
    time.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scratch", default=tempfile.gettempdir())
    parser.add_argument("--seconds", type=float, default=20.0)
    parser.add_argument("--interval", type=float, default=3.0)
    args = parser.parse_args()
    service = IOService()
    with tempfile.TemporaryDirectory(dir=args.scratch) as directory:
        root = Path(directory)
        costs(service, root)
        print(f"Background loads (1,000 files of 5,000 rows, one after another) with Live checks {args.interval:g} s apart, every third finding "
              "one new shot (none: no checks; old: checks hold background work; new: only while reading):")
        for rule in ("none", "old", "new"):
            starvation(service, root, rule, args.seconds, args.interval)
    service.shutdown()


if __name__ == "__main__":
    main()
