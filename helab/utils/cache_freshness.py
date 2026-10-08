"""Freshness hints from metadata already held in memory."""
from datetime import datetime
from enum import Enum
import math


class CacheFreshness(Enum):
    UNCHANGED = ""
    UNKNOWN = "Freshness unknown"
    POSSIBLY_OLD = "May be outdated"
    CHANGED = "Changes detected"


def metadata_date(value: object) -> float | None:
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        try:
            timestamp = float(value)
        except OverflowError:
            return None
        if math.isfinite(timestamp) and 0 < timestamp < 253402300799:
            return timestamp
    return None


def cache_freshness(saved_at: object, modified: object, *, changed: bool = False) -> CacheFreshness:
    if changed:
        return CacheFreshness.CHANGED
    saved, folder = metadata_date(saved_at), metadata_date(modified)
    if saved is None or folder is None:
        return CacheFreshness.UNKNOWN
    return CacheFreshness.POSSIBLY_OLD if folder > saved else CacheFreshness.UNCHANGED


def data_as_of(info: dict[str, object]) -> float | None:
    """When a cached dataset's file list was taken; older caches only have a save date."""
    as_of = metadata_date(info.get("snapshot_at"))
    return as_of if as_of is not None else metadata_date(info.get("saved_at"))


def freshness_tooltip(label: str, saved_at: object, modified: object,
                      freshness: CacheFreshness, action: str, *, as_of: object = None) -> str:
    def exact(value: object) -> str:
        timestamp = metadata_date(value)
        if timestamp is not None:
            try:
                return datetime.fromtimestamp(timestamp).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
            except (ValueError, OverflowError, OSError):
                pass
        return "Date not recorded"

    reason = {
        CacheFreshness.UNKNOWN: "Freshness unknown: a cache/scan date or folder modification date is missing.",
        CacheFreshness.POSSIBLY_OLD: "May be outdated: observed folder modification time is newer.",
        CacheFreshness.CHANGED: "Changes detected: a later folder status check found different TXY fingerprints.",
        CacheFreshness.UNCHANGED: "No newer folder modification time observed; TXY contents have not been verified by this comparison.",
    }[freshness]
    saved, listed = metadata_date(saved_at), metadata_date(as_of)
    # A long load can finish well after its file list was taken.
    listing = (f"\nIncludes files present at: {exact(listed)}"
               if saved is not None and listed is not None and saved - listed >= 1 else "")
    return f"{label}: {exact(saved_at)}{listing}\nObserved folder modified: {exact(modified)}\n{reason}\n{action}"
