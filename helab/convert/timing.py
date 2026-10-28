"""The timing harness: convert shots and time reading, reconstruction and writing apart.

``time_shot`` converts one raw file (read and parse, reconstruct, format and write atomically)
and returns a ``ShotTiming``; ``time_shots`` runs a list of them with a ``Parallelism``:

- ``serial``: one after another, in this process;
- ``processes``: across shots, in a pool of worker processes;
- ``threads``: across shots, in a thread pool (worth timing only for a backend that releases
  the GIL, ``Backend.releases_gil``);
- ``within-shot``: one shot cut at pulse gaps longer than the match window, the pieces
  reconstructed in parallel (stage 2: each backend that offers it).

``summarise`` gives raw MB/s (SI, 10^6 bytes) per stage and overall, and per-shot latency.
Stage 2 calls this per backend and per parallelism level; stage 1 times the reference serially.

Qt-free; standard library and NumPy only.
"""
from __future__ import annotations

from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
import enum
import os
from pathlib import Path
import statistics
import time
from typing import Iterable, Sequence

from helab.convert.profile import DetectorProfile
from helab.convert.raw import parse_raw
from helab.convert.reconstruct import DEFAULT_BACKEND, NoRowsError, reconstruct
from helab.convert.txy import format_txy, write_atomic


class Parallelism(enum.Enum):
    SERIAL = "serial"
    PROCESSES = "processes"
    THREADS = "threads"
    WITHIN_SHOT = "within-shot"


@dataclass(frozen=True)
class ShotTiming:
    """Seconds per stage: ``read`` is the file read plus the parse, ``write`` the formatting plus
    the atomic write (0 when no file is written). ``hits`` is None when MATLAB would fail on the
    file (no rows)."""
    label: str
    raw_bytes: int
    hits: int | None
    read: float
    reconstruct: float
    write: float

    @property
    def total(self) -> float:
        return self.read + self.reconstruct + self.write


@dataclass(frozen=True)
class ShotJob:
    label: str
    raw_path: Path
    txy_path: Path


def time_shot(job: ShotJob, profile: DetectorProfile, backend: str = DEFAULT_BACKEND) -> ShotTiming:
    clock = time.perf_counter
    start = clock()
    data = job.raw_path.read_bytes()
    pulses = parse_raw(data)
    read_done = clock()
    try:
        hits = reconstruct(pulses, profile, backend)
    except NoRowsError:
        done = clock()
        return ShotTiming(job.label, len(data), None, read_done - start, done - read_done, 0.0)
    reconstruct_done = clock()
    if hits.shape[0] or profile.write_empty_txy:
        write_atomic(job.txy_path, format_txy(hits))
    done = clock()
    return ShotTiming(job.label, len(data), int(hits.shape[0]), read_done - start, reconstruct_done - read_done,
                      done - reconstruct_done)


def time_shots(jobs: Sequence[ShotJob], profile: DetectorProfile, backend: str = DEFAULT_BACKEND,
               parallelism: Parallelism = Parallelism.SERIAL, workers: int | None = None) -> list[ShotTiming]:
    if parallelism is Parallelism.SERIAL:
        return [time_shot(job, profile, backend) for job in jobs]
    if parallelism is Parallelism.WITHIN_SHOT:
        raise NotImplementedError("Parallelism within one shot comes with stage 2's backends")
    count = workers or os.cpu_count() or 1
    pool: Executor = (ProcessPoolExecutor(count) if parallelism is Parallelism.PROCESSES
                      else ThreadPoolExecutor(count))
    with pool:
        return list(pool.map(time_shot, jobs, [profile] * len(jobs), [backend] * len(jobs)))


@dataclass(frozen=True)
class TimingSummary:
    shots: int
    raw_bytes: int
    hits: int
    read: float
    reconstruct: float
    write: float
    wall: float | None
    latency_median: float
    latency_max: float

    def mb_per_s(self, seconds: float) -> float:
        return self.raw_bytes / 1e6 / seconds if seconds > 0 else float("inf")


def summarise(timings: Iterable[ShotTiming], wall: float | None = None) -> TimingSummary:
    """Sums per stage (CPU-side seconds, adding across workers) and, when given, the wall time
    the whole run took (the throughput a parallel run reaches)."""
    items = list(timings)
    totals = [item.total for item in items] or [0.0]
    return TimingSummary(
        shots=len(items), raw_bytes=sum(item.raw_bytes for item in items),
        hits=sum(item.hits or 0 for item in items),
        read=sum(item.read for item in items), reconstruct=sum(item.reconstruct for item in items),
        write=sum(item.write for item in items), wall=wall,
        latency_median=statistics.median(totals), latency_max=max(totals))
