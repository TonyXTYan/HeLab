from __future__ import annotations

from helab.utils.load_clock import LoadClock
from helab.utils.time_format import byte_rate, clock


def test_stopwatch_labels() -> None:
    assert clock(0) == "0:00"
    assert clock(42.9) == "0:42"
    assert clock(725) == "12:05"
    assert clock(3723) == "1:02:03"
    assert clock(-5) == "0:00"


def test_elapsed_counts_only_running_time() -> None:
    timer = LoadClock()
    assert timer.elapsed(10.0) == 0.0
    timer.run(10.0)
    timer.run(11.0)  # Already running: the start is kept.
    assert timer.elapsed(12.0) == 2.0
    timer.stop(12.0)
    assert timer.elapsed(50.0) == 2.0  # Queued or paused.
    timer.run(50.0)
    assert timer.elapsed(51.5) == 3.5 and timer.running


def test_estimate_waits_for_enough_samples_and_uses_bytes_read() -> None:
    timer = LoadClock()
    timer.run(0.0)
    timer.sample(0, 100, 0, now=0.0)
    timer.sample(10, 100, 1, now=1.0)
    assert timer.remaining(1.0) is None  # Too early and too few samples.
    timer.sample(20, 100, 2, now=2.0)
    assert timer.rates() == (10.0, 1.0)
    assert timer.remaining(2.0) == 8.0
    assert timer.remaining(3.0) == 7.0  # Counts down between progress reports.
    timer.sample(100, 100, 10, now=4.0)
    assert timer.remaining(4.0) == 0.0


def test_window_drops_old_samples_and_retry_restarts_the_rate() -> None:
    timer = LoadClock()
    timer.run(0.0)
    for second in range(30):
        # Slow at first, then 5 bytes per second.
        timer.sample(second if second < 15 else 15 + (second - 15) * 5, 10_000, second, now=float(second))
    rates = timer.rates()
    assert rates is not None and rates[0] == 5.0
    timer.restart_rate()
    assert timer.rates() is None and timer.remaining(30.0) is None
    assert timer.elapsed(30.0) == 30.0


def test_no_estimate_when_nothing_needs_reading() -> None:
    timer = LoadClock()
    timer.run(0.0)
    for second in range(5):
        timer.sample(0, 0, second, now=float(second))
    assert timer.remaining(5.0) is None


def test_stalled_read_has_no_estimate() -> None:
    timer = LoadClock()
    timer.run(0.0)
    for second in range(4):
        timer.sample(second * 10, 100, second, now=float(second))
    assert timer.remaining(3.0) == 7.0 and timer.stalled_for(3.0) == 0.0
    # One slow file: after 5 s without progress the countdown would be wrong.
    assert timer.stalled_for(8.0) == 0.0 and timer.remaining(8.0) == 2.0
    assert timer.stalled_for(9.0) == 6.0 and timer.remaining(9.0) is None
    timer.stop(9.0)  # Paused: the stall does not grow.
    assert timer.stalled_for(60.0) == 6.0
    timer.run(60.0)
    timer.sample(40, 100, 4, now=61.0)
    assert timer.stalled_for(61.0) == 0.0 and timer.remaining(61.0) is not None
    timer.sample(100, 100, 10, now=62.0)
    assert timer.done_reading and timer.stalled_for(100.0) == 0.0


def test_byte_rate_labels() -> None:
    """Disk units (Q26.1): SI on macOS and Linux (and in the tests, conftest), KiB… on Windows."""
    values = (0, 850, 12_500, 10_000_000, 99_960_000, 1.2e9)
    for platform in ("darwin", "linux", None):
        assert [byte_rate(value, platform=platform) for value in values] == [
            "0 B/s", "850 B/s", "12.5 kB/s", "10.0 MB/s", "100 MB/s", "1.20 GB/s"]
    assert [byte_rate(value, platform="win32") for value in values] == [
        "0 B/s", "850 B/s", "12.2 KiB/s", "9.54 MiB/s", "95.3 MiB/s", "1.12 GiB/s"]
