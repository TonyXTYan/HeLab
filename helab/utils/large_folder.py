"""The large-folder check: how much RAM a load would take, and whether it may start.

The estimate is the loaded kinds' size on disk, unscaled (``FileKind.ram_per_byte``; TXY
takes about 0.69x of it in RAM, so it errs on the safe side). Above the RAM budget or 10%
of RAM a load needs the user's yes; above 30% of RAM it is refused. Imported by isolated
helpers: nothing here may start Qt. See roadmaps/cache-storage-and-settings.md.
"""
from __future__ import annotations

from typing import Any, Iterable, Literal

WARN_RAM_SHARE = 0.10
REFUSE_RAM_SHARE = 0.30

Verdict = Literal["", "large", "refused"]


def total_ram() -> int:
    import psutil
    return int(psutil.virtual_memory().total)


def limits(ram_budget: int, total: int) -> dict[str, int]:
    """Sent with every load and cached read: warn above ``warn``, refuse above ``refuse``."""
    return {"warn": int(min(ram_budget, WARN_RAM_SHARE * total)), "refuse": int(REFUSE_RAM_SHARE * total)}


def verdict(estimate: int | None, bounds: dict[str, Any] | None, allow_large: bool = False) -> Verdict:
    """"refused" above ``refuse`` (no override), "large" above ``warn`` unless the user allowed
    it, else "". Without ``bounds`` (an older caller) only the 30% refusal applies."""
    if estimate is None:
        return ""
    refuse = (bounds or {}).get("refuse")
    if refuse is None:
        refuse = int(REFUSE_RAM_SHARE * total_ram())
    if estimate > int(refuse):
        return "refused"
    warn = (bounds or {}).get("warn")
    if warn is not None and estimate > int(warn) and not allow_large:
        return "large"
    return ""


def estimate(fingerprint: Iterable[Iterable[Any]], held: Iterable[int] = ()) -> int:
    """Bytes in RAM for the shots of a ``[shot, size, mtime]`` fingerprint not already ``held``."""
    skip = set(held)
    total = 0
    for entry in fingerprint:
        shot, size = list(entry)[:2]
        if int(shot) not in skip:
            total += int(size)
    return total
