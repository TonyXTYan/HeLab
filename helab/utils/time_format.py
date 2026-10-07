"""Time labels shared by folder summaries and memory-only tooltips."""


def relative_age(seconds: float) -> str:
    age = max(0, int(seconds))
    return ("just now" if age < 1 else f"{age}s ago" if age < 60 else
            f"{age // 60}m ago" if age < 3600 else f"{age // 3600}h ago" if age < 86400 else
            f"{age // 86400}d ago")


def duration(seconds: float) -> str:
    elapsed = max(0, int(seconds))
    return f"{elapsed} s" if elapsed < 60 else f"{elapsed // 60} min {elapsed % 60} s"
