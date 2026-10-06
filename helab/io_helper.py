"""Isolated filesystem helper. Importing this module must not start Qt or Dash.

One JSON request on stdin, bounded JSON event batches on stdout. The parent may
kill this process when an OS filesystem call stalls; it never waits in the GUI.
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import sys
import time
from typing import Any, Callable

Emit = Callable[[dict[str, Any]], None]
RAW = re.compile(r"^d(\d+)\.txt$")
TXY = re.compile(r"^d_txy_forc(\d+)\.txt$")


def emit(event: dict[str, Any]) -> None:
    print(json.dumps(event, ensure_ascii=True), flush=True)


def _disk_cached(cache: Any, path: str) -> bool:
    # Membership reads local metadata, without reading/decompressing array data.
    try:
        return cache is not None and path in cache
    except Exception:
        return False


def scan(path: str, send: Emit = emit, cache_options: dict[str, Any] | None = None) -> None:
    cache: Any = None
    if cache_options and os.path.isdir(cache_options["directory"]):
        try:
            from diskcache import FanoutCache
            cache = FanoutCache(cache_options["directory"], **cache_options["params"])
        except Exception:
            # Optional cache metadata must not prevent browsing source folders.
            pass
    try:
        _scan(path, send, cache)
    finally:
        if cache is not None:
            cache.close()


def _scan(path: str, send: Emit, cache: Any) -> None:
    raw: set[int] = set()
    txy: set[int] = set()
    entries: list[dict[str, Any]] = []
    has_dirs = False
    fingerprint: list[tuple[int, int, int]] = []
    # Do not traverse directory symlinks or recursively probe children.
    with os.scandir(path) as directory:
        for entry in directory:
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
                    modified = entry.stat(follow_symlinks=False).st_mtime
                except OSError:
                    modified = None
                entries.append({"path": entry.path, "name": entry.name, "modified": modified,
                                "disk_cached": _disk_cached(cache, entry.path)})
                if len(entries) >= 128:
                    send({"kind": "entries", "entries": entries})
                    entries = []
    if entries:
        send({"kind": "entries", "entries": entries})
    common = raw & txy
    if not raw and not txy:
        status, count = ("unknown" if has_dirs else "nothing"), -1
    elif raw == txy:
        status, count = "ok", len(common)
    elif common:
        status = "fixable" if txy <= raw else "critical" if raw <= txy else "warning"
        count = len(common)
    else:
        status, count = ("warning", len(raw | txy)) if not raw or not txy else ("critical", 0)
    send({"kind": "status", "status": status, "count": count,
          "raw": sorted(raw), "txy": sorted(txy), "modified": os.stat(path).st_mtime,
          "disk_cached": _disk_cached(cache, path),
          "signature": hashlib.sha256(json.dumps(sorted(fingerprint)).encode()).hexdigest()})


def load(path: str, output: str, send: Emit = emit,
         cache_options: dict[str, Any] | None = None) -> None:
    # These imports are deliberately local: scanning does not initialize numpy,
    # pandas, any HeLab caches, or a QApplication.
    import numpy as np
    import pandas as pd

    files: list[tuple[int, str]] = []
    with os.scandir(path) as directory:
        for entry in directory:
            if match := TXY.fullmatch(entry.name):
                files.append((int(match.group(1)), entry.path))
    if not files:
        raise ValueError("No converted TXY files in this folder")
    files.sort()
    fingerprint = [(shot, info.st_size, info.st_mtime_ns)
                   for shot, filename in files for info in (os.stat(filename),)]
    total_size = sum(size for _, size, _ in fingerprint)
    if total_size > 1 << 30:
        raise ValueError("Folder exceeds the 1 GiB input limit")
    cache = None
    cache_epoch: Any = None
    data: dict[int, Any] = {}
    cached = False
    cache_reason = "Disk cache unavailable" if cache_options is None else "No saved cache fingerprint"
    problematic: list[int] = []
    if cache_options:
        try:
            from diskcache import FanoutCache
            import blosc
            import pickle
            cache = FanoutCache(cache_options["directory"], **cache_options["params"])
            with cache.transact():
                cache_epoch = cache.get(("snapshot-epoch", path))
                saved_fingerprint = cache.get(("snapshot-fingerprint", path))
                packed = cache.get(path) if saved_fingerprint == fingerprint else None
                previous = cache.get(("snapshot-problematic", path), [])
            if saved_fingerprint == fingerprint:
                cache_reason = "Cached dataset missing"
                if isinstance(packed, bytes):
                    data = pickle.loads(blosc.decompress(packed))
                    cached = isinstance(data, dict) and all(
                        isinstance(shot, int) and isinstance(array, np.ndarray)
                        and array.ndim == 2 and array.shape[1] == 3
                        for shot, array in data.items())
                    if not cached:
                        data = {}
                        cache_reason = "Cached dataset invalid"
                    elif isinstance(previous, list):
                        problematic = [value for value in previous if isinstance(value, int)]
            elif saved_fingerprint is not None:
                cache_reason = "TXY files changed since caching"
        except Exception as exc:
            # A cache miss/failure must not prevent loading the actual files.
            data, cached = {}, False
            cache_reason = f"Cache read failed: {type(exc).__name__}: {exc}"
            send({"kind": "cache_warning", "message": cache_reason})
    if cached:
        cache_reason = ""
    source = "disk" if cached else "files"
    send({"kind": "load_source", "source": source, "cache_reason": cache_reason})
    rows = size = loaded = 0
    last_progress = 0.0
    for i, (shot, filename) in enumerate(files):
        try:
            if cached:
                if shot not in data:
                    continue
                array = data[shot]
            else:
                frame = pd.read_csv(filename, sep=",", names=["t", "x", "y"], dtype=np.float64)
                if frame.isna().any().any():
                    problematic.append(shot)
                array = np.asarray(frame.dropna(), dtype=np.float64)
                data[shot] = array
            artifact = os.path.join(output, f"{shot}.npy")
            np.save(artifact, array, allow_pickle=False)
            rows += len(array)
            size += array.nbytes
            loaded += 1
            send({"kind": "shot", "shot": shot, "artifact": artifact})
        except (OSError, ValueError, pd.errors.ParserError):
            problematic.append(shot)
        now = time.monotonic()
        if now - last_progress >= 0.1 or i + 1 == len(files):
            send({"kind": "progress", "progress": (i + 1) / len(files) * (0.95 if cache is not None and not cached else 1.0)})
            last_progress = now
    if not loaded:
        raise ValueError("No readable TXY files in this folder")
    final_fingerprint = [(shot, info.st_size, info.st_mtime_ns)
                         for shot, filename in files for info in (os.stat(filename),)]
    if final_fingerprint != fingerprint:
        if cache is not None:
            cache.close()
        raise ValueError("Folder changed while loading — Refresh to retry")
    disk_cached = cached
    if cache is not None:
        try:
            if not cached:
                import blosc
                import pickle
                send({"kind": "progress", "progress": 0.99})
                packed = blosc.compress(pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL),
                                        typesize=8, cname="zstd", clevel=9, shuffle=blosc.NOSHUFFLE)
                with cache.transact():
                    if cache.get(("snapshot-epoch", path)) == cache_epoch and cache.set(path, packed):
                        cache.set(("snapshot-fingerprint", path), fingerprint)
                        cache.set(("snapshot-problematic", path), problematic)
            disk_cached = _disk_cached(cache, path)
        except Exception as exc:
            send({"kind": "cache_warning", "message": str(exc)})
        finally:
            cache.close()
    send({"kind": "loaded", "rows": rows, "bytes": size, "files": loaded,
          "problematic": sorted(set(problematic)),
          "source": source, "cached": cached,
          "disk_cached": disk_cached,
          "cache_reason": cache_reason,
          "signature": hashlib.sha256(json.dumps(fingerprint).encode()).hexdigest()})


def main() -> None:
    try:
        request = json.loads(sys.stdin.readline())
        operation = request["operation"]
        if operation == "drives":
            import ctypes
            mask = ctypes.windll.kernel32.GetLogicalDrives()  # type: ignore[attr-defined]
            emit({"kind": "drives", "paths": [f"{chr(65 + i)}:\\" for i in range(26) if mask & (1 << i)]})
        elif operation == "resolve":
            for path in request["candidates"]:
                if path and os.path.isdir(path):
                    emit({"kind": "resolved", "path": path})
                    break
            else:
                raise FileNotFoundError("No available default data folder")
        elif operation == "scan":
            scan(request["path"], cache_options=request.get("cache"))
        elif operation == "load":
            load(request["path"], request["output"], cache_options=request.get("cache"))
        elif operation == "invalidate":
            from diskcache import FanoutCache
            options = request["cache"]
            with FanoutCache(options["directory"], **options["params"]) as cache:
                with cache.transact():
                    # A load started before clearing cannot repopulate this entry.
                    from uuid import uuid4
                    cache.set(("snapshot-epoch", request["path"]), uuid4().hex)
                    for key in (request["path"], ("snapshot-fingerprint", request["path"]),
                                ("snapshot-problematic", request["path"])):
                        cache.pop(key, None)
        else:
            raise ValueError(f"Unknown operation: {operation}")
        emit({"kind": "done"})
    except Exception as exc:
        emit({"kind": "error", "message": str(exc)})


if __name__ == "__main__":
    main()
