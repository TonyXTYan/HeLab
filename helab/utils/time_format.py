"""Time labels shared by folder summaries and memory-only tooltips."""


def relative_age(seconds: float) -> str:
    age = max(0, int(seconds))
    return ("just now" if age < 1 else f"{age}s ago" if age < 60 else
            f"{age // 60}m ago" if age < 3600 else f"{age // 3600}h ago" if age < 86400 else
            f"{age // 86400}d ago")


def duration(seconds: float) -> str:
    elapsed = max(0, int(seconds))
    return f"{elapsed} s" if elapsed < 60 else f"{elapsed // 60} min {elapsed % 60} s"


def clock(seconds: float) -> str:
    """Stopwatch label: ``0:42``, ``12:05``, ``1:02:03``."""
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    return f"{hours}:{rest // 60:02}:{rest % 60:02}" if hours else f"{rest // 60}:{rest % 60:02}"


def byte_rate(per_second: float) -> str:
    """Three significant figures: ``850 B/s``, ``12.5 MB/s``, ``1.20 GB/s``."""
    value = max(0.0, per_second)
    for unit in ("B", "kB", "MB", "GB"):
        if value < 999.5 or unit == "GB":
            break
        value /= 1000
    digits = 0 if value >= 99.95 or unit == "B" else 1 if value >= 9.995 else 2
    return f"{value:.{digits}f} {unit}/s"
