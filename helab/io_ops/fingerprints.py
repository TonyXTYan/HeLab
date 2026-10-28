"""Shot files: settling, fingerprints and signatures, raw shot times and sampled checks."""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import time
from typing import Any, Iterable, TYPE_CHECKING

from helab.io_ops.infra import Emit, _entry_stat, _stat
from helab.io_ops.stores import _cache_info
from helab.utils import file_kinds

if TYPE_CHECKING:
    from helab.utils.cache_store import CacheStore


# Another computer may still be writing a file modified this recently; it is
# left for the next load rather than read half-written. Tests set it to 0.
# Settle age only, by Tony's decision (2026-10-19): a TXY write never takes longer, so an older
# file is read as it is; its content isn't checked. The converter writing to a temporary name and
# renaming it remains the real fix.
SETTLE_SECONDS = float(os.environ.get("HELAB_SETTLE_SECONDS", "5"))

# A folder modified this close to when its listing began (either way: the server's clock may differ
# a little from ours) may change again within the same mtime step (FAT and some shares keep 2 s),
# which a later stat wouldn't see: its mtime isn't kept for the quick check (``_quick_mtime``), nor
# compared by Live's next check (``live``, which reads this one). Tests, with no settle age, have no
# margin either.
RACY_SECONDS = min(2.0, SETTLE_SECONDS)


# A source file's mtime more than this ahead of our clock means the computers' clocks are out of
# sync (FAT and some shares round mtimes to 2 s, plus jitter): ``_clock_ahead`` says so. Such a file
# still counts as being written (``_settled``), by Tony's decision (2026-10-22, R-22).
FUTURE_SECONDS = 2.0


def _clock_ahead(path: str, fingerprint: Iterable[tuple[int, int, int]], send: Emit) -> float:
    """How far the newest of the folder's files is ahead of our clock, in seconds, sent as
    ``clock_skew`` (with its share or volume, the app's once-per-location key) when that is over
    FUTURE_SECONDS; else 0."""
    from helab.io_ops.identity import _mount_source
    newest = max((item[2] for item in fingerprint), default=None)
    ahead = 0.0 if newest is None else newest / 1e9 - time.time()
    if ahead <= FUTURE_SECONDS:
        return 0.0
    mount = _mount_source(path, "clock skew: location")
    send({"kind": "clock_skew", "path": path, "seconds": ahead, "location": mount[0] if mount else path})
    return ahead


def _quick_mtime(folder: os.stat_result, listed_at: float) -> int | None:
    """The folder's mtime (ns), stat'ed just before the listing that began at ``listed_at``, for the
    quick checks: a folder whose mtime is still exactly this one has had nothing added or removed
    since. It is the server's clock, so it is compared only with itself, never with our time, except
    for the ``RACY_SECONDS`` margin: within it, None (the next check lists the folder)."""
    return None if abs(listed_at - folder.st_mtime) < RACY_SECONDS else folder.st_mtime_ns


def _mtime_unchanged(saved: dict[str, Any], folder: os.stat_result, as_of: float) -> bool:
    """Whether a folder stat'ed now is as a listing left it: its mtime exactly the one that listing
    saw (``folder_mtime_ns``; None: too close to the listing, so no). Data saved before it was kept
    compares the mtime with the listing's time (``as_of``) instead, which trusts the two clocks."""
    if "folder_mtime_ns" not in saved:
        return folder.st_mtime <= as_of
    return isinstance(saved["folder_mtime_ns"], int) and saved["folder_mtime_ns"] == folder.st_mtime_ns


def _settled(fingerprint: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    """Fingerprints of files not modified within SETTLE_SECONDS (nor in the future)."""
    if SETTLE_SECONDS <= 0:
        return fingerprint
    settle_after = time.time() - SETTLE_SECONDS
    return [item for item in fingerprint if item[2] / 1e9 <= settle_after]


def _fingerprint_signature(fingerprint: Any) -> str:
    return hashlib.sha256(json.dumps(fingerprint).encode()).hexdigest()


def _as_of(info: dict[str, Any]) -> float | None:
    """When a cached dataset's file list was taken (older caches: when it was saved)."""
    for key in ("snapshot_at", "saved_at"):
        value = info.get(key)
        if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
            return float(value)
    return None


def _touch(store: CacheStore, path: str) -> None:
    """Record that the cached dataset was used; best effort (e.g. a read-only cache)."""
    from helab.utils.cache_store import StoreError
    try:
        store.touch_dataset(path)
    except StoreError:
        pass


def _saved_fingerprint(row: Any) -> list[tuple[int, int, int]]:
    return [(int(shot), int(size), int(modified)) for shot, size, modified in row["fingerprint"]]


def _saved_raw_times(row: Any) -> dict[int, int]:
    """A cached dataset's shot times: each shot's raw ``d<N>.txt`` mtime (ns), where one was found.
    Datasets cached before shot times have none."""
    return file_kinds.raw_times(row.get("raw_times"))


def _raw_mtime(entry: os.DirEntry[str] | None, reason: str) -> int | None:
    """A shot's time: its raw ``d<N>.txt`` file's mtime (ns), from the listing's entry (one stat on
    macOS and Linux; none on Windows, where the listing has it). None without one, or if it's gone:
    the shot's time is then its TXY file's (``DatasetView.shot_time``). The TXY file's mtime is
    when it was converted, and a converter catching up gives many shots the same time (Tony,
    2026-10-20). Raw files never affect a shot's fingerprint, so deleting one changes nothing else.
    A raw file modified within ``SETTLE_SECONDS`` (or in the future) may still be written: no time
    yet, so a later listing stats it again."""
    if entry is None:
        return None
    try:
        modified = _entry_stat(entry, reason).st_mtime_ns
    except OSError:
        return None
    return modified if modified / 1e9 <= time.time() - SETTLE_SECONDS else None


def _raw_list(times: dict[int, int], shots: Iterable[int]) -> list[list[int]]:
    """``[shot, raw mtime_ns]`` for those of ``shots`` with a known time, by shot, as events and the
    cache carry them."""
    return [[shot, times[shot]] for shot in sorted(set(shots)) if shot in times]


# helab.utils.constants.DEFAULT_CHECK_LEVEL; not imported, since constants resolves the app's
# folders at import, which a helper must not do.
DEFAULT_CHECK_LEVEL = "medium"


def _sample_indices(count: int, level: str) -> list[int] | None:
    """Which cached files the quick check stats, by Settings → General's check level; None for
    Full (every file: the folder is listed). Random files differ each time, so repeated checks
    cover more of the folder."""
    if count <= 0 or level == "full":
        return None
    ends = {count - 1} if level == "swift" else {0, count - 1}
    extra = {"medium": max(3, math.ceil(count / 100)), "high": max(10, math.ceil(count * 3 / 100))}.get(level, 0)
    rest = [index for index in range(count) if index not in ends]
    return sorted(ends | set(random.sample(rest, min(extra, len(rest)))))


def _samples_unchanged(path: str, fingerprint: list[list[int]], names: object, level: str,
                       reason: str = "cached check: sample") -> bool:
    """Whether a sample of the cached TXY files still has the cached size and mtime_ns.

    Another folder moved into this path keeps its own, older mtime, so the folder stat alone
    would take its cached data for this folder's; so would a folder whose files were deleted.
    Size and mtime work alike on every OS, file system and mount, unlike inode numbers.
    Caches saved without file names get a full check.
    """
    indices = _sample_indices(len(fingerprint), level)
    if indices is None or not isinstance(names, list) or len(names) != len(fingerprint):
        return False
    try:
        for index in indices:
            info = _stat(os.path.join(path, str(names[index])), reason)
            if (info.st_size, info.st_mtime_ns) != tuple(fingerprint[index][1:]):
                return False
    except (OSError, TypeError, ValueError):
        return False
    return True


def _cached_signature(row: Any) -> str:
    """The signature a cached read gives this dataset (``read_cached``)."""
    return str(_cache_info(row["info"]).get("signature") or _fingerprint_signature(_saved_fingerprint(row)))
