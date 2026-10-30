"""What labcam saw, over time: daily CSV files under `data/`, a row every `EVERY` seconds and whenever a laser's
lock state changes (so a loss is never missed between rows).

- `locks-<date>.csv`: time, then per laser its state (locked, lost, unknown), how sure (0–1) and why;
- `history-<date>.csv`: time, the locks again, then each instrument's status and its numbers (a trace's shape,
  level and thickness, the wavemeter's value, the needle's offset, the dot's spread, movement 0/1).

A file's header is written when it is created; a day whose header no longer matches the instruments (the
config changed) continues in `<kind>-<date>-2.csv` and so on. Earlier days' files are gzipped (`.csv.gz`,
about a tenth of the size) at start and when the day changes, and days older than KEEP_DAYS (7) deleted. `series` reads both back
for the page's plots. About 2.5 MB a day before compression.
"""

from __future__ import annotations

import csv
import gzip
import logging
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, TextIO

from .config import HOME, Instrument
from .detectors import Reading
from .locks import Lock

DATA = HOME / "data"
EVERY = 5.0  # s between rows, besides rows for lock changes
KEEP_DAYS = 7  # days of data and app log kept (Tony, 2026-10-30)

log = logging.getLogger("labcam.history")

# Per instrument kind, the numbers logged besides its status.
FIELDS: dict[str, list[str]] = {
    "trace": ["shape", "level", "thickness", "waviness"],
    "wavemeter": ["value"],
    "needle": ["offset"],
    "dot": ["spread_px", "x", "y"],
    "motion": ["present", "moved"],
}


def _value(inst: Instrument, reading: Reading | None, field: str) -> Any:
    if reading is None:
        return ""
    values = reading.values
    if field == "value":
        for key in ("wavelength", "frequency", "power"):
            if key in values:
                return values[key]
        return ""
    if field == "present":
        return {"yes": 1, "no": 0}.get(str(values.get("present")), "")
    return values.get(field, "")


class _Daily:
    """Appends rows to `<kind>-<date>[-n].csv`, starting a new file for a new day or a new header."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.day = ""
        self.header: list[str] = []
        self.file: TextIO | None = None
        self.writer: Any = None

    def write(self, now: float, header: list[str], row: list[Any]) -> None:
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        if day != self.day or header != self.header:
            if self.file is not None:
                self.file.close()
                if day != self.day:
                    threading.Thread(target=compress_old, name="labcam-gzip", daemon=True).start()
            DATA.mkdir(exist_ok=True)
            n = 1
            while True:
                path = DATA / (f"{self.kind}-{day}.csv" if n == 1 else f"{self.kind}-{day}-{n}.csv")
                if not path.exists() or _header(path) == header:
                    break
                n += 1
            new = not path.exists()
            self.file = path.open("a", newline="", encoding="utf-8")
            self.writer = csv.writer(self.file)
            if new:
                self.writer.writerow(header)
            self.day, self.header = day, header
        self.writer.writerow(row)
        assert self.file is not None
        self.file.flush()


def _header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as f:
        return next(csv.reader(f), [])


def compress_old() -> None:
    """Deletes days older than KEEP_DAYS, and gzips every other day's CSV but today's (being written)."""
    today = time.strftime("%Y-%m-%d")
    oldest = time.strftime("%Y-%m-%d", time.localtime(time.time() - KEEP_DAYS * 86400))
    for path in sorted([*DATA.glob("*.csv"), *DATA.glob("*.csv.gz")]):
        match = re.search(r"\d{4}-\d{2}-\d{2}", path.name)
        if match and match.group(0) < oldest:
            try:
                path.unlink()
                log.info("deleted %s (older than %d days)", path.name, KEEP_DAYS)
            except OSError as exc:
                log.warning("couldn't delete %s: %s", path.name, exc)
    for path in sorted(DATA.glob("*.csv")):
        if today in path.name:
            continue
        target = path.with_suffix(".csv.gz")
        size = path.stat().st_size
        try:
            with path.open("rb") as src, gzip.open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            path.unlink()
            log.info("compressed %s (%.1f MB → %.2f MB)", path.name, size / 1e6, target.stat().st_size / 1e6)
        except OSError as exc:
            log.warning("couldn't compress %s: %s", path.name, exc)
            target.unlink(missing_ok=True)


class Recorder:
    def __init__(self) -> None:
        self.locks = _Daily("locks")
        self.history = _Daily("history")
        self.last = 0.0
        self.last_states: dict[str, str] = {}
        if DATA.exists():
            threading.Thread(target=compress_old, name="labcam-gzip", daemon=True).start()

    def record(self, now: float, instruments: dict[str, Instrument], readings: dict[str, Reading],
               locks: dict[str, Lock]) -> None:
        states = {laser: lock.state for laser, lock in locks.items()}
        if now - self.last < EVERY and states == self.last_states:
            return
        self.last, self.last_states = now, states
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now))
        lock_header = [c for laser in locks for c in (laser, f"{laser}_sure", f"{laser}_why")]
        lock_row = [v for lock in locks.values() for v in (lock.state, lock.confidence, lock.summary)]
        self.locks.write(now, ["time", *lock_header], [stamp, *lock_row])
        header = ["time"] + [c for laser in locks for c in (laser, f"{laser}_sure", f"{laser}_why")]
        row: list[Any] = [stamp] + [v for lock in locks.values() for v in (lock.state, lock.confidence, lock.summary)]
        for name, inst in instruments.items():
            fields = FIELDS.get(inst.kind, [])
            header += [f"{name}.status"] + [f"{name}.{f}" for f in fields]
            reading = readings.get(name)
            row += [reading.status if reading else ""] + [_value(inst, reading, f) for f in fields]
        self.history.write(now, header, row)


def files(kind: str) -> list[Path]:
    """The kind's files, oldest first: earlier days gzipped, today's plain."""
    return sorted([*DATA.glob(f"{kind}-*.csv"), *DATA.glob(f"{kind}-*.csv.gz")], key=lambda p: p.name.split(".")[0])


def series(hours: float, max_points: int = 1500) -> dict[str, Any]:
    """The last `hours` of history as columns ({"time": [...], "<column>": [...]}), thinned to `max_points`.

    Rows from files with different headers are merged by column name; missing values are None.
    """
    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - hours * 3600))
    first_day = since[:10]
    rows: list[dict[str, str]] = []
    for path in files("history"):
        if path.name.split("-", 1)[1][:10] < first_day:
            continue
        opened = gzip.open(path, "rt", newline="", encoding="utf-8") if path.suffix == ".gz" else \
            path.open(newline="", encoding="utf-8")
        with opened as f:
            rows += [r for r in csv.DictReader(f) if r.get("time", "") >= since]
    rows.sort(key=lambda r: r["time"])
    step = max(1, len(rows) // max_points)
    # Lock columns: no "." (instruments' are "<name>.<field>"), not time, and not a lock's _sure or _why.
    lasers = {k for r in rows[:1] for k in r if "." not in k and k != "time" and not k.endswith(("_sure", "_why"))}
    # Keep every row where a lock state changes, so thinning never hides a short loss.
    kept = [r for i, r in enumerate(rows) if i % step == 0 or i == 0
            or any(k in lasers and r.get(k) != rows[i - 1].get(k) for k in r)]
    columns = sorted({k for r in kept for k in r})

    def convert(text: str | None) -> Any:
        if text in (None, ""):
            return None
        try:
            return float(text)
        except ValueError:
            return text

    return {"rows": len(rows), "columns": {c: [convert(r.get(c)) for r in kept] for c in columns}}
