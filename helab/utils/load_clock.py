"""Elapsed time and remaining-time estimate of one folder load, from memory only."""
from __future__ import annotations

from collections import deque
from time import monotonic
from typing import ClassVar


class LoadClock:
    """Runs only while the load's helper works: queued and paused time is left out.

    The rate comes from the bytes of TXY files actually read (shots reused from
    RAM or the disk cache cost almost nothing), averaged over the last
    ``WINDOW_SECONDS`` of running time.
    """

    WINDOW_SECONDS: ClassVar[float] = 10.0
    # No estimate until the load has run this long and reported this often.
    MIN_SECONDS: ClassVar[float] = 2.0
    MIN_SAMPLES: ClassVar[int] = 3
    # A read with no progress this long (a slow or hung file) has no estimate:
    # counting down from the last rate would show "~0:01 left" while stuck.
    STALL_SECONDS: ClassVar[float] = 5.0

    def __init__(self) -> None:
        self._active = 0.0
        self._since: float | None = None
        self._samples: deque[tuple[float, int, int]] = deque()
        self.read_bytes = 0
        self.total_bytes: int | None = None

    @property
    def running(self) -> bool:
        return self._since is not None

    def run(self, now: float | None = None) -> None:
        if self._since is None:
            self._since = monotonic() if now is None else now

    def stop(self, now: float | None = None) -> None:
        if self._since is not None:
            self._active += (monotonic() if now is None else now) - self._since
            self._since = None

    def elapsed(self, now: float | None = None) -> float:
        if self._since is None:
            return self._active
        return self._active + (monotonic() if now is None else now) - self._since

    def restart_rate(self) -> None:
        """A retry restarts the helper's counters; elapsed time continues."""
        self._samples.clear()
        self.read_bytes, self.total_bytes = 0, None

    def sample(self, read_bytes: int, total_bytes: int, read_files: int, now: float | None = None) -> None:
        """Counters from one progress event; a new total or a smaller count restarts the rate."""
        if total_bytes != self.total_bytes or read_bytes < self.read_bytes:
            self._samples.clear()
        self.read_bytes, self.total_bytes = read_bytes, total_bytes
        at = self.elapsed(now)
        self._samples.append((at, read_bytes, read_files))
        while len(self._samples) > 2 and at - self._samples[1][0] >= self.WINDOW_SECONDS:
            self._samples.popleft()

    def rates(self) -> tuple[float, float] | None:
        """(bytes, files) read per running second over the window, once there is a span to measure."""
        if len(self._samples) < 2:
            return None
        (t0, b0, f0), (t1, b1, f1) = self._samples[0], self._samples[-1]
        span = t1 - t0
        return ((b1 - b0) / span, (f1 - f0) / span) if span > 0 else None

    @property
    def done_reading(self) -> bool:
        """Every file this load reads has been read; it is assembling or saving the data."""
        return bool(self.total_bytes) and self.read_bytes >= (self.total_bytes or 0)

    def stalled_for(self, now: float | None = None) -> float:
        """Running seconds since the last progress report while files remain, if over ``STALL_SECONDS``."""
        if not self._samples or not self.total_bytes or self.done_reading:
            return 0.0
        since = self.elapsed(now) - self._samples[-1][0]
        return since if since > self.STALL_SECONDS else 0.0

    def remaining(self, now: float | None = None) -> float | None:
        """Seconds left reading files, or None while there is nothing to estimate from.

        None also when no file needs reading (every shot reused) and while stalled.
        """
        if not self.total_bytes:
            return None
        if self.done_reading:
            return 0.0
        elapsed = self.elapsed(now)
        rates = self.rates()
        if (elapsed < self.MIN_SECONDS or len(self._samples) < self.MIN_SAMPLES or not rates or rates[0] <= 0
                or self.stalled_for(now)):
            return None
        since_sample = elapsed - self._samples[-1][0]
        return max(0.0, (self.total_bytes - self.read_bytes) / rates[0] - since_sample)
