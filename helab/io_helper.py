"""Isolated filesystem helper. Importing this module must not start Qt or Dash.

One JSON request on stdin, bounded JSON event batches on stdout. The parent may
kill this process when an OS filesystem call stalls; it never waits in the GUI.
"""
from __future__ import annotations

import json
import base64
import hashlib
import math
import os
import re
import sys
import time
from typing import Any, Callable

Emit = Callable[[dict[str, Any]], None]
RAW = re.compile(r"^d(\d+)\.txt$")
TXY = re.compile(r"^d_txy_forc(\d+)\.txt$")
# Another computer may still be writing a file modified this recently; it is
# left for the next load rather than read half-written. Tests set it to 0.
SETTLE_SECONDS = float(os.environ.get("HELAB_SETTLE_SECONDS", "5"))


def emit(event: dict[str, Any]) -> None:
    print(json.dumps(event, ensure_ascii=True), flush=True)


class Pause:
    """Cooperative pause: the parent creates ``pause`` in the request's private
    folder while the current tab browses or loads, and removes it to resume.

    Checked between files and entries, so a call already in progress finishes.
    """
    CHECK_INTERVAL = 0.02
    POLL = 0.05
    flag: str | None = None
    last_check = 0.0

    @classmethod
    def configure(cls, control: str | None) -> None:
        cls.flag = os.path.join(control, "pause") if control else None
        cls.last_check = 0.0

    @classmethod
    def checkpoint(cls, send: Emit) -> None:
        now = time.monotonic()
        if cls.flag is None or now - cls.last_check < cls.CHECK_INTERVAL:
            return
        cls.last_check = now
        if not os.path.exists(cls.flag):
            return
        send({"kind": "paused"})
        while os.path.exists(cls.flag):
            time.sleep(cls.POLL)
        send({"kind": "resumed"})


class Heartbeat:
    """Tell the parent a slow listing is still progressing (resets its no-progress timer)."""
    INTERVAL = 1.0

    def __init__(self, send: Emit, phase: str) -> None:
        self.send, self.phase, self.count = send, phase, 0
        self.last = time.monotonic()

    def __call__(self, count: int = 1) -> None:
        Pause.checkpoint(self.send)
        self.count += count
        now = time.monotonic()
        if now - self.last >= self.INTERVAL:
            self.send({"kind": "heartbeat", "phase": self.phase, "entries": self.count})
            self.last = now


def _disk_cached(cache: Any, path: str) -> bool:
    # Membership reads local metadata, without reading/decompressing array data.
    try:
        return cache is not None and path in cache
    except Exception:
        return False


def _cache_info(cache: Any, path: str) -> dict[str, Any]:
    """Small persisted metadata only; older cached arrays have no save date."""
    try:
        info = cache.get(("snapshot-cache-info", path)) if cache is not None else None
        if isinstance(info, dict):
            saved_at = info.get("saved_at")
            if (isinstance(saved_at, (int, float)) and math.isfinite(saved_at) and saved_at > 0
                    and isinstance(info.get("signature"), str)):
                return info
        return {}
    except Exception:
        return {}


def _open_cache(cache_options: dict[str, Any] | None) -> Any:
    if not cache_options:
        return None
    try:
        from diskcache import FanoutCache
        return FanoutCache(cache_options["directory"], **cache_options["params"])
    except Exception:
        # Optional cache metadata must not prevent browsing source folders.
        return None


def _send_saved(cache: Any, path: str, send: Emit, identity: object) -> Any:
    """Send this folder's saved history and summary; returns the history (None if unreadable)."""
    from helab.utils.scan_history import read_history, for_identity
    history = read_history(cache, path)
    if history is not None:
        history = for_identity(history, identity)
    send({"kind": "scan_history", "history": history})
    previous = _scan_info(cache, path)
    if previous.get("identity") is not None and identity is not None and previous["identity"] != identity:
        previous = {}
    if previous:
        send({"kind": "scan_cached", "status": previous})
    return history


def _classify(raw: set[int], txy: set[int], has_dirs: bool) -> tuple[str, int]:
    common = raw & txy
    if not raw and not txy:
        return ("unknown" if has_dirs else "nothing"), -1
    if raw == txy:
        return "ok", len(common)
    if common:
        return ("fixable" if txy <= raw else "critical" if raw <= txy else "warning"), len(common)
    return ("warning", len(raw | txy)) if not raw or not txy else ("critical", 0)


def list_folder(path: str, send: Emit = emit, cache_options: dict[str, Any] | None = None, *,
                identity: object = None) -> None:
    """Browse step 1: names only, so a slow volume shows subfolders and counts first.

    One scandir with no per-entry stat (``is_dir`` uses the listing's file type).
    Each subfolder's saved summary, scan history and cache flags are read from the
    local cache, never the source, so saved badges appear with the names; their
    identity is checked by the ``details`` scan (step 2), which also adds the
    signature and dates. Nothing is written.
    """
    from helab.utils.scan_history import read_history
    cache = _open_cache(cache_options)
    try:
        _send_saved(cache, path, send, identity)
        raw: set[int] = set()
        txy: set[int] = set()
        entries: list[dict[str, Any]] = []
        has_dirs = False
        empty = True
        listed_at = time.time()
        beat = Heartbeat(send, "listing")
        with os.scandir(path) as directory:
            for entry in directory:
                beat()
                empty = False
                if match := RAW.fullmatch(entry.name):
                    raw.add(int(match.group(1)))
                elif match := TXY.fullmatch(entry.name):
                    txy.add(int(match.group(1)))
                elif entry.is_dir(follow_symlinks=False):
                    has_dirs = True
                    child: dict[str, Any] = {"path": entry.path, "name": entry.name}
                    if cache is not None:
                        child.update(scan_history=read_history(cache, entry.path),
                                     scan_status=_scan_info(cache, entry.path),
                                     disk_cached=_disk_cached(cache, entry.path),
                                     cache_info=_cache_info(cache, entry.path))
                    entries.append(child)
                    if len(entries) >= 128:
                        send({"kind": "entries", "entries": entries})
                        entries = []
        if entries:
            send({"kind": "entries", "entries": entries})
        status, count = _classify(raw, txy, has_dirs)
        report: dict[str, Any] = {"kind": "status", "details": False, "status": status, "count": count,
                                  "empty": empty, "has_dirs": has_dirs, "scanned_at": listed_at,
                                  "raw": sorted(raw), "txy": sorted(txy)}
        if cache is not None:
            report.update(disk_cached=_disk_cached(cache, path), cache_info=_cache_info(cache, path))
        send(report)
    finally:
        if cache is not None:
            cache.close()


def scan(path: str, send: Emit = emit, cache_options: dict[str, Any] | None = None, *,
         manual: bool = True, automatic: bool = False,
         operation_id: str = "", revision: int = 0, identity: object = None) -> None:
    """Full scan: a basic scan, or browse step 2 (``details``). Saves summary and history."""
    from uuid import uuid4
    from helab.utils.scan_history import begin_scan, write_outcome
    send({"kind": "scan_mode", "mode": "metadata"})
    cache = _open_cache(cache_options)
    try:
        history = _send_saved(cache, path, send, identity)
        blocked = history is not None and history["blocked"]
        if not manual and (blocked or automatic and history is None):
            # Browsing a blocked folder lists it (step 1) without this scan.
            send({"kind": "scan_mode", "mode": "skipped"})
            return
        operation_id = operation_id or uuid4().hex
        revision = revision or time.time_ns()
        if cache is not None:
            try:
                history, revision = begin_scan(cache, path, operation_id, revision, identity)
                send({"kind": "scan_history", "history": history, "revision": revision})
            except Exception as exc:
                send({"kind": "scan_history_warning", "message": str(exc)})
        send({"kind": "scan_mode", "mode": "scan"})
        report = _scan(path, send, cache)
        if cache is not None:
            try:
                history = write_outcome(cache, path, {"operation_id": operation_id, "revision": revision,
                    "kind": "success", "at": report["scanned_at"], "identity": report["identity"]})
                send({"kind": "scan_history", "history": history, "revision": revision, "saved": True})
            except Exception as exc:
                send({"kind": "scan_history_warning", "message": str(exc)})
    finally:
        if cache is not None:
            cache.close()


def _scan_info(cache: Any, path: str) -> dict[str, Any]:
    """Restore metadata independently of the compressed dataset."""
    try:
        info = cache.get(("folder-scan-v1", path)) if cache is not None else None
        if (isinstance(info, dict) and info.get("version") == 1
                and isinstance(info.get("signature"), str)
                and info.get("status") in ("ok", "warning", "critical", "fixable", "unknown", "nothing")
                and isinstance(info.get("count"), int)
                and isinstance(info.get("scanned_at"), (float, int))
                and math.isfinite(info["scanned_at"]) and 0 < info["scanned_at"] < 253402300799
                and all(isinstance(info.get(key), int) and info[key] >= 0
                        for key in ("raw_count", "txy_count"))):
            return info
    except Exception:
        pass
    return {}


def _summary(path: str, raw: set[int], txy: set[int], has_dirs: bool, empty: bool,
             fingerprint: list[tuple[int, int, int]], scanned_at: float) -> dict[str, Any]:
    """A complete status for this folder, as a scan or load computes it."""
    folder_stat = os.stat(path)
    status, count = _classify(raw, txy, has_dirs)
    return {"kind": "status", "details": True, "status": status, "count": count, "empty": empty,
            "has_dirs": has_dirs, "scanned_at": scanned_at,
            "identity": [folder_stat.st_dev, folder_stat.st_ino],
            "raw": sorted(raw), "txy": sorted(txy), "modified": folder_stat.st_mtime,
            "signature": hashlib.sha256(json.dumps(sorted(fingerprint)).encode()).hexdigest()}


def _save_summary(cache: Any, path: str, report: dict[str, Any]) -> None:
    # Optional persistence never turns a successful source check into a failure.
    try:
        cache.set(("folder-scan-v1", path), {"version": 1, **{
            key: value for key, value in report.items()
            if key not in ("kind", "details", "disk_cached", "cache_info", "raw", "txy")},
            "raw_count": len(report["raw"]), "txy_count": len(report["txy"])})
    except Exception:
        pass


def _scan(path: str, send: Emit, cache: Any) -> dict[str, Any]:
    from helab.utils.scan_history import read_history, for_identity
    raw: set[int] = set()
    txy: set[int] = set()
    entries: list[dict[str, Any]] = []
    has_dirs = False
    empty = True
    fingerprint: list[tuple[int, int, int]] = []
    beat = Heartbeat(send, "listing")
    # Do not traverse directory symlinks or recursively probe children.
    with os.scandir(path) as directory:
        for entry in directory:
            beat()
            empty = False
            if match := RAW.fullmatch(entry.name):
                raw.add(int(match.group(1)))
            if match := TXY.fullmatch(entry.name):
                txy.add(int(match.group(1)))
                # Match load()'s fingerprint of the actual converted file,
                # including when the file itself is a symlink.
                info = entry.stat()
                fingerprint.append((int(match.group(1)), info.st_size, info.st_mtime_ns))
            if entry.is_dir(follow_symlinks=False):
                has_dirs = True
                try:
                    # Windows DirEntry.stat() reports zero device/inode IDs.
                    # Use the same source as _summary so saved metadata belongs
                    # to this directory, and replacements are detected reliably.
                    stat = os.stat(entry.path, follow_symlinks=False)
                    modified = stat.st_mtime
                    identity = [stat.st_dev, stat.st_ino]
                except OSError:
                    modified = None
                    identity = None
                history = read_history(cache, entry.path)
                if history is not None:
                    history = for_identity(history, identity)
                summary = _scan_info(cache, entry.path)
                if summary.get("identity") is not None and identity is not None and summary["identity"] != identity:
                    summary = {}
                entries.append({"path": entry.path, "name": entry.name, "modified": modified,
                                "identity": identity, "scan_history": history,
                                "modified_observed_at": time.time(),
                                "disk_cached": _disk_cached(cache, entry.path),
                                "cache_info": _cache_info(cache, entry.path),
                                "scan_status": summary})
                if len(entries) >= 128:
                    send({"kind": "entries", "entries": entries})
                    entries = []
    if entries:
        send({"kind": "entries", "entries": entries})
    # Like load(), files that may still be being written are not in the signature,
    # so a scan during acquisition agrees with the data loaded meanwhile.
    settled = _settled(fingerprint)
    report = {**_summary(path, raw, txy, has_dirs, empty, settled, time.time()),
              "unsettled": len(fingerprint) - len(settled),
              "disk_cached": _disk_cached(cache, path), "cache_info": _cache_info(cache, path)}
    # Publish the completed source check before optional cache writes, so even a
    # stalled cache writer cannot turn it into a failed basic scan.
    send(report)
    if cache is not None:
        _save_summary(cache, path, report)
    return report


def _settled(fingerprint: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    """Fingerprints of files not modified within SETTLE_SECONDS (nor in the future)."""
    if SETTLE_SECONDS <= 0:
        return fingerprint
    settle_after = time.time() - SETTLE_SECONDS
    return [item for item in fingerprint if item[2] / 1e9 <= settle_after]


def _unpack(packed: Any) -> dict[int, Any] | None:
    """A cached dataset: Blosc-compressed pickle of ``{shot: float64 array (n, 3)}``."""
    import blosc
    import numpy as np
    import pickle
    if not isinstance(packed, bytes):
        return None
    unpacked = pickle.loads(blosc.decompress(packed))
    valid = isinstance(unpacked, dict) and all(
        isinstance(shot, int) and isinstance(array, np.ndarray) and array.ndim == 2 and array.shape[1] == 3
        for shot, array in unpacked.items())
    return unpacked if valid else None


def _fingerprint_signature(fingerprint: Any) -> str:
    return hashlib.sha256(json.dumps(fingerprint).encode()).hexdigest()


def _as_of(info: dict[str, Any]) -> float | None:
    """When a cached dataset's file list was taken (older caches: when it was saved)."""
    for key in ("snapshot_at", "saved_at"):
        value = info.get(key)
        if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
            return float(value)
    return None


def read_cached(path: str, output: str, send: Emit = emit,
                cache_options: dict[str, Any] | None = None) -> None:
    """Send a folder's dataset from the local disk cache, never touching the source folder.

    The caller shows it as not yet checked; a later ``load`` with it as the RAM
    base checks the folder.
    """
    import numpy as np
    cache = _open_cache(cache_options)
    if cache is None:
        raise ValueError("Disk cache unavailable")
    try:
        with cache.transact():
            saved: Any = cache.get(("snapshot-fingerprint", path))
            packed = cache.get(path) if saved is not None else None
            previous = cache.get(("snapshot-problematic", path), [])
            info = _cache_info(cache, path)
    finally:
        cache.close()
    data = _unpack(packed) if isinstance(saved, (list, tuple)) else None
    if data is None or not isinstance(saved, (list, tuple)):
        raise ValueError("No cached data for this folder")
    fingerprint = [list(entry) for entry in saved]
    by_shot = {int(entry[0]): entry for entry in fingerprint}
    problematic = {value for value in previous if isinstance(value, int)} if isinstance(previous, list) else set()
    send({"kind": "load_source", "source": "disk", "cache_reason": ""})
    rows = size = 0
    last_progress = 0.0
    shots = sorted(shot for shot in data if shot in by_shot)
    failed = len(fingerprint) - len(shots)
    unsettled = int(info.get("unsettled", 0) or 0)
    total = len(fingerprint) + unsettled
    for i, shot in enumerate(shots):
        array = data[shot]
        artifact = os.path.join(output, f"{shot}.npy")
        np.save(artifact, array, allow_pickle=False)
        rows += len(array)
        size += array.nbytes
        send({"kind": "shot", "shot": shot, "artifact": artifact, "fingerprint": by_shot[shot],
              "problematic": shot in problematic})
        now = time.monotonic()
        if now - last_progress >= 0.1 or i + 1 == len(shots):
            checked = i + 1 + failed + unsettled
            send({"kind": "progress", "progress": checked / total, "checked_files": checked,
                  "loaded_files": i + 1, "total_files": total, "failed_files": failed,
                  "unsettled_files": unsettled})
            last_progress = now
    if not shots:
        raise ValueError("No cached data for this folder")
    send({"kind": "loaded", "rows": rows, "bytes": size, "files": len(shots), "loaded_at": time.time(),
          "total_files": len(fingerprint) + int(info.get("unsettled", 0) or 0),
          "failed_files": len(fingerprint) - len(shots),
          "unsettled_files": int(info.get("unsettled", 0) or 0),
          "problematic": sorted(problematic & set(shots)), "source": "disk", "cached": True,
          "disk_cached": True, "disk_cache_pending": False, "cache_info": info,
          "load_counts": {"reused_memory": 0, "reused_disk": len(shots), "new": 0, "modified": 0,
                          "removed": 0, "read": 0, "new_loaded": 0, "modified_loaded": 0},
          "cache_reason": "", "fingerprint": fingerprint, "memory_shots": [], "verified": False,
          "signature": info.get("signature") or _fingerprint_signature(saved)})


def _unchanged_since_cache(path: str, send: Emit, cache_options: dict[str, Any],
                           base_signature: str, memory: list[list[int]]) -> bool:
    """One folder stat instead of listing and checking every file.

    When the caller holds the cached dataset (``base_signature``), the cache has
    no files that were still being written, and the folder has not been modified
    since the dataset's file list was taken, nothing can have been added or
    removed: ``loaded`` names the caller's shots and True is returned.
    """
    cache = _open_cache(cache_options)
    if cache is None:
        return False
    try:
        with cache.transact():
            info = _cache_info(cache, path)
            saved: Any = cache.get(("snapshot-fingerprint", path))
            previous = cache.get(("snapshot-problematic", path), [])
    finally:
        cache.close()
    as_of = _as_of(info)
    if (info.get("signature") != base_signature or info.get("unsettled") or as_of is None
            or not isinstance(saved, (list, tuple))):
        return False
    modified = os.stat(path).st_mtime
    if modified > as_of:
        return False
    fingerprint = [list(entry) for entry in saved]
    held = sorted({int(entry[0]) for entry in memory} & {int(entry[0]) for entry in fingerprint})
    problematic = [value for value in previous if isinstance(value, int) and value in held] \
        if isinstance(previous, list) else []
    send({"kind": "load_source", "source": "memory", "cache_reason": ""})
    send({"kind": "loaded", "rows": 0, "bytes": 0, "files": len(held), "loaded_at": time.time(),
          "total_files": len(fingerprint), "failed_files": len(fingerprint) - len(held), "unsettled_files": 0,
          "problematic": problematic, "source": "memory", "cached": True, "disk_cached": True,
          "disk_cache_pending": False, "cache_info": info, "unchanged": True, "modified": modified,
          "modified_observed_at": time.time(),
          "load_counts": {"reused_memory": len(held), "reused_disk": 0, "new": 0, "modified": 0,
                          "removed": 0, "read": 0, "new_loaded": 0, "modified_loaded": 0},
          "cache_reason": "Folder not modified since cached", "fingerprint": fingerprint,
          "memory_shots": held, "signature": base_signature})
    return True


def load(path: str, output: str, send: Emit = emit,
         cache_options: dict[str, Any] | None = None,
         memory: list[list[int]] | None = None, base_signature: str = "",
         expected: str = "") -> None:
    """Load converted TXY files, reusing unchanged shots from RAM and disk cache.

    ``memory`` lists ``[shot, size, mtime_ns]`` for shots the caller already holds
    in RAM. Unchanged ones are neither read nor sent; ``loaded`` names them in
    ``memory_shots``. The disk cache is updated after ``loaded`` is sent.
    ``base_signature`` names the dataset those shots belong to; if it is the cached
    dataset and the folder is unmodified since, one folder stat is the whole check.
    """
    if (base_signature and cache_options and memory and expected in ("", base_signature)
            and _unchanged_since_cache(path, send, cache_options, base_signature, memory)):
        return
    # These imports are deliberately local: scanning does not initialize numpy,
    # pandas, any HeLab caches, or a QApplication.
    import numpy as np
    import pandas as pd

    files: list[tuple[int, str]] = []
    raw: set[int] = set()
    has_dirs = False
    # Files added after this listing are not in the dataset; freshness compares against it.
    listed_at = time.time()
    beat = Heartbeat(send, "listing")
    with os.scandir(path) as directory:
        for entry in directory:
            beat()
            if match := TXY.fullmatch(entry.name):
                files.append((int(match.group(1)), entry.path))
            elif match := RAW.fullmatch(entry.name):
                raw.add(int(match.group(1)))
            elif not has_dirs and entry.is_dir(follow_symlinks=False):
                has_dirs = True
    if not files:
        raise ValueError("No converted TXY files in this folder")
    files.sort()

    def stat_files(phase: str) -> list[tuple[int, int, int]]:
        beat = Heartbeat(send, phase)
        result: list[tuple[int, int, int]] = []
        for shot, filename in files:
            info = os.stat(filename)
            result.append((shot, info.st_size, info.st_mtime_ns))
            beat()
        return result

    fingerprint = stat_files("checking")
    # Files another computer may still be writing are left out entirely (not in
    # the fingerprint), so the next load sees them as new and reads them whole.
    young = {item[0] for item in fingerprint} - {item[0] for item in _settled(fingerprint)}
    if young:
        files = [item for item in files if item[0] not in young]
        fingerprint = [item for item in fingerprint if item[0] not in young]
        if not files:
            raise ValueError("TXY files are still being written — Retry")
    total_size = sum(size for _, size, _ in fingerprint)
    if total_size > 1 << 30:
        raise ValueError("Folder exceeds the 1 GiB input limit")
    # This listing and fingerprint are a complete status check of this folder, so
    # browsing skips its details scan (step 2) while this load runs, unless the
    # folder has subfolders (their dates come from step 2). Sent and saved before any
    # file is read; a basic scan's success is still needed to clear a failure.
    summary = _summary(path, raw, {shot for shot, _ in files} | young, has_dirs, False, fingerprint, listed_at)
    summary["unsettled"] = len(young)
    send({"kind": "scan_summary", "status": summary})
    current = {shot: (size, modified) for shot, size, modified in fingerprint}
    in_memory = {int(shot) for shot, size, modified in memory or ()
                 if current.get(int(shot)) == (size, modified)}
    cache = None
    cache_epoch: Any = None
    data: dict[int, Any] = {}
    cached = False
    cache_reason = "Disk cache unavailable" if cache_options is None else "No saved cache fingerprint"
    problematic: list[int] = []
    reused: set[int] = set()
    baseline: dict[int, tuple[int, int]] = {}
    cache_info: dict[str, Any] = {}
    if cache_options:
        try:
            from diskcache import FanoutCache
            cache = FanoutCache(cache_options["directory"], **cache_options["params"])
            _save_summary(cache, path, summary)
            with cache.transact():
                cache_epoch = cache.get(("snapshot-epoch", path))
                saved_fingerprint: Any = cache.get(("snapshot-fingerprint", path))
                packed = cache.get(path) if saved_fingerprint is not None else None
                previous = cache.get(("snapshot-problematic", path), [])
                cache_info = _cache_info(cache, path)
            if isinstance(saved_fingerprint, (list, tuple)):
                baseline = {int(shot): (size, modified) for shot, size, modified in saved_fingerprint}
            previous = [value for value in previous if isinstance(value, int)] \
                if isinstance(previous, list) else []

            def unpack() -> dict[int, Any] | None:
                return _unpack(packed)

            if saved_fingerprint == fingerprint and packed is not None and in_memory >= set(current):
                # The caller already holds every shot: no need to decompress the cache.
                cached, problematic = True, previous
            elif saved_fingerprint == fingerprint:
                cache_reason = "Cached dataset missing" if packed is None else "Cached dataset invalid"
                unpacked = unpack()
                if unpacked is not None:
                    data, cached, problematic = unpacked, True, previous
                    reused = set(data)
            elif saved_fingerprint is not None:
                cache_reason = "TXY files changed since caching"
                # Keep shots whose converted file is unchanged; only new or
                # modified TXY files are read and merged into the dataset.
                saved = {int(shot): (size, modified) for shot, size, modified in saved_fingerprint}
                data = {shot: array for shot, array in (unpack() or {}).items()
                        if shot in current and saved.get(shot) == current[shot]}
                reused = set(data)
                problematic = [shot for shot in previous if shot in reused]
        except Exception as exc:
            # A cache miss/failure must not prevent loading the actual files.
            data, cached, reused, problematic = {}, False, set(), []
            cache_reason = f"Cache read failed: {type(exc).__name__}: {exc}"
            send({"kind": "cache_warning", "message": cache_reason})
    from_disk = reused - in_memory
    baseline.update({int(shot): (size, modified) for shot, size, modified in memory or ()})
    new_shots = set(current) - set(baseline)
    modified_shots = {shot for shot in current.keys() & baseline.keys()
                      if current[shot] != baseline[shot]}
    load_counts = {"reused_memory": len(in_memory), "reused_disk": 0,
                   "new": len(new_shots), "modified": len(modified_shots),
                   "removed": len(baseline.keys() - current.keys()),
                   "read": 0, "new_loaded": 0, "modified_loaded": 0}
    read = 0 if cached else len(files) - len(in_memory | reused)
    if in_memory or (from_disk and not cached):
        parts = [f"{len(in_memory)} shots from memory"] if in_memory else []
        parts += [f"{len(from_disk)} shots from disk cache"] if from_disk else []
        cache_reason = f"Reused {', '.join(parts)}; read {read} new or changed TXY files"
    elif cached:
        cache_reason = ""
    source = "updated" if in_memory else "disk" if cached else "merged" if reused else "files"
    send({"kind": "load_source", "source": source, "cache_reason": cache_reason})
    send({"kind": "progress", "progress": len(young) / (len(files) + len(young)),
          "checked_files": len(young), "loaded_files": 0,
          "total_files": len(files) + len(young), "failed_files": 0, "unsettled_files": len(young)})
    rows = size = loaded = 0
    last_progress = 0.0
    # Files that changed while being read: still being written. They keep their
    # earlier fingerprint, which differs from the finished file, so the next
    # load reads them again; their data is not kept.
    late: set[int] = set()

    def unchanged(index: int, filename: str) -> bool:
        info = os.stat(filename)
        return (info.st_size, info.st_mtime_ns) == fingerprint[index][1:]

    def read_txy(shot: int, filename: str) -> Any:
        frame = pd.read_csv(filename, sep=",", names=["t", "x", "y"], dtype=np.float64)
        if frame.isna().any().any():
            problematic.append(shot)
        array = np.asarray(frame.dropna(), dtype=np.float64)
        data[shot] = array
        return array

    for i, (shot, filename) in enumerate(files):
        Pause.checkpoint(send)
        send({"kind": "file_started", "filename": filename})
        try:
            array = None
            if shot in in_memory:
                # Unchanged and already in the caller's RAM: nothing to read or send.
                loaded += 1
            elif shot in reused:
                array = data[shot]
            elif not cached:
                load_counts["read"] += 1
                if unchanged(i, filename):
                    array = read_txy(shot, filename)
                    if not unchanged(i, filename):
                        data.pop(shot, None)
                        array = None
                if array is None:
                    late.add(shot)
                    problematic[:] = [value for value in problematic if value != shot]
            if array is not None:
                artifact = os.path.join(output, f"{shot}.npy")
                np.save(artifact, array, allow_pickle=False)
                rows += len(array)
                size += array.nbytes
                loaded += 1
                send({"kind": "shot", "shot": shot, "artifact": artifact,
                      "fingerprint": fingerprint[i], "problematic": shot in problematic})
                load_counts["new_loaded"] += int(shot in new_shots)
                load_counts["modified_loaded"] += int(shot in modified_shots)
                load_counts["reused_disk"] += int(shot in from_disk)
        except (OSError, ValueError, pd.errors.ParserError):
            problematic.append(shot)
        send({"kind": "file_finished", "filename": filename})
        now = time.monotonic()
        if now - last_progress >= 0.1 or i + 1 == len(files):
            send({"kind": "progress", "progress": (i + 1 + len(young)) / (len(files) + len(young)),
                  "checked_files": i + 1 + len(young), "loaded_files": loaded,
                  "total_files": len(files) + len(young), "unsettled_files": len(young) + len(late),
                  "failed_files": i + 1 - loaded - len(late)})
            last_progress = now
    if not loaded:
        raise ValueError("TXY files are still being written — Retry" if late
                         else "No readable TXY files in this folder")
    unsettled = len(young) + len(late)

    def changed() -> bool:
        # Only the loaded files must be unchanged. Shots added during a live run
        # are left for the next load (their scan signature shows the change).
        settled = [item for item in fingerprint if item[0] not in late]
        return settled != [item for item in stat_files("verifying") if item[0] not in late]

    if changed():
        if cache is not None:
            cache.close()
        raise ValueError("Folder changed while loading — Retry")
    send({"kind": "loaded", "rows": rows, "bytes": size, "files": loaded,
          "loaded_at": time.time(),
          "total_files": len(files) + len(young), "failed_files": len(files) - loaded - len(late),
          "unsettled_files": unsettled,
          "problematic": sorted(set(problematic)),
          "source": source, "cached": cached,
          "disk_cached": cached or _disk_cached(cache, path),
          "disk_cache_pending": cache is not None and not cached,
          "cache_info": cache_info, "load_counts": load_counts,
          "cache_reason": cache_reason,
          "fingerprint": fingerprint, "memory_shots": sorted(in_memory),
          "signature": hashlib.sha256(json.dumps(fingerprint).encode()).hexdigest()})
    if cache is None or cached:
        if cache is not None:
            cache.close()
        return
    # The caller already has its data; updating the disk cache no longer
    # delays it. Shots only the caller holds are read again for completeness.
    try:
        for shot, filename in files:
            if shot in in_memory and shot not in data:
                Pause.checkpoint(send)
                send({"kind": "file_started", "filename": filename})
                try:
                    read_txy(shot, filename)
                except (OSError, ValueError, pd.errors.ParserError):
                    raise ValueError(f"Could not cache previously loaded shot {shot}") from None
                send({"kind": "file_finished", "filename": filename})
        if changed():
            raise ValueError("Folder changed before cache could be saved")
        import blosc
        import pickle
        packed = blosc.compress(pickle.dumps(dict(sorted(data.items())), protocol=pickle.HIGHEST_PROTOCOL),
                                typesize=8, cname="zstd", clevel=9, shuffle=blosc.NOSHUFFLE)
        with cache.transact():
            if cache.get(("snapshot-epoch", path)) != cache_epoch:
                raise ValueError("Cache was cleared before saving completed")
            action = "updated" if _disk_cached(cache, path) else "created"
            info = {"saved_at": time.time(), "snapshot_at": listed_at, "signature": hashlib.sha256(
                json.dumps(fingerprint).encode()).hexdigest(), "action": action, "counts": load_counts,
                "unsettled": unsettled}
            # A failed set must roll back bytes, fingerprints AND the save date.
            for key, value in ((path, packed), (("snapshot-fingerprint", path), fingerprint),
                               (("snapshot-problematic", path), sorted(set(problematic))),
                               (("snapshot-cache-info", path), info)):
                if not cache.set(key, value):
                    raise OSError("Cache write did not complete")
        send({"kind": "cache_saved", "cache_info": info})
        send({"kind": "disk_cached", "disk_cached": _disk_cached(cache, path)})
    except Exception as exc:
        send({"kind": "cache_save_failed", "message": str(exc)})
        send({"kind": "cache_warning", "message": str(exc)})
    finally:
        cache.close()


def folder_icons(paths: list[str], send: Emit = emit) -> None:
    """Resolve OS icons only in this disposable process, never while listing.

    Keep the native platform plugin: offscreen Qt does not provide macOS custom
    or volume icons. No windows are created, and macOS helpers stay out of the Dock.
    """
    os.environ.setdefault("QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM", "1")
    from PyQt6.QtCore import QBuffer, QByteArray, QFileInfo, QIODevice
    from PyQt6.QtWidgets import QApplication, QFileIconProvider

    app = QApplication.instance() or QApplication(["helab-folder-icons"])
    provider = QFileIconProvider()
    for path in paths[:64]:
        Pause.checkpoint(send)
        encoded = ""
        try:
            pixmap = provider.icon(QFileInfo(path)).pixmap(32, 32)
            data = QByteArray()
            buffer = QBuffer(data)
            if buffer.open(QIODevice.OpenModeFlag.WriteOnly) and pixmap.save(buffer, "PNG"):
                encoded = base64.b64encode(data.data()).decode("ascii")
            buffer.close()
        except Exception:
            pass  # Cosmetic lookup failures leave the generic folder icon.
        send({"kind": "folder_icon", "path": path, "png": encoded})
    # Keep the QApplication alive until every pixmap and buffer has been used.
    _ = app


def main() -> None:
    try:
        request = json.loads(sys.stdin.readline())
        operation = request["operation"]
        Pause.configure(request.get("control"))
        if operation == "drives":
            if sys.platform == "win32":
                import ctypes
                mask = ctypes.windll.kernel32.GetLogicalDrives()
                emit({"kind": "drives", "paths": [f"{chr(65 + i)}:\\" for i in range(26) if mask & (1 << i)]})
            else:
                raise OSError("Drive enumeration is only supported on Windows")
        elif operation == "resolve":
            for path in request["candidates"]:
                if path and os.path.isdir(path):
                    emit({"kind": "resolved", "path": path})
                    break
            else:
                raise FileNotFoundError("No available default data folder")
        elif operation == "list":
            list_folder(request["path"], cache_options=request.get("cache"), identity=request.get("identity"))
        elif operation == "icons":
            folder_icons(request["paths"])
        elif operation in ("scan", "details"):
            scan(request["path"], cache_options=request.get("cache"), manual=request.get("scan_manual", False),
                 automatic=request.get("automatic", False),
                 operation_id=request.get("scan_operation_id", ""), revision=request.get("scan_revision", 0),
                 identity=request.get("identity"))
        elif operation == "scan_history":
            from diskcache import FanoutCache
            from helab.utils.scan_history import write_outcome
            options = request["cache"]
            with FanoutCache(options["directory"], **options["params"]) as cache:
                history = write_outcome(cache, request["path"], request["outcome"])
                emit({"kind": "scan_history_saved", "history": history})
        elif operation == "load":
            load(request["path"], request["output"], cache_options=request.get("cache"),
                 memory=request.get("memory"), base_signature=request.get("base_signature", ""),
                 expected=request.get("signature", ""))
        elif operation == "cached":
            read_cached(request["path"], request["output"], cache_options=request.get("cache"))
        elif operation == "invalidate":
            from diskcache import FanoutCache
            options = request["cache"]
            with FanoutCache(options["directory"], **options["params"]) as cache:
                with cache.transact():
                    # A load started before clearing cannot repopulate this entry.
                    from uuid import uuid4
                    cache.set(("snapshot-epoch", request["path"]), uuid4().hex)
                    for key in (request["path"], ("snapshot-fingerprint", request["path"]),
                                ("snapshot-problematic", request["path"]),
                                ("snapshot-cache-info", request["path"])):
                        cache.pop(key, None)
        else:
            raise ValueError(f"Unknown operation: {operation}")
        emit({"kind": "done"})
    except Exception as exc:
        emit({"kind": "error", "message": str(exc)})


if __name__ == "__main__":
    main()
