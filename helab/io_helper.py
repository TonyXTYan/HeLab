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
         cache_options: dict[str, Any] | None = None,
         memory: list[list[int]] | None = None) -> None:
    """Load converted TXY files, reusing unchanged shots from RAM and disk cache.

    ``memory`` lists ``[shot, size, mtime_ns]`` for shots the caller already holds
    in RAM. Unchanged ones are neither read nor sent; ``loaded`` names them in
    ``memory_shots``. The disk cache is updated after ``loaded`` is sent.
    """
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
    if cache_options:
        try:
            from diskcache import FanoutCache
            import blosc
            import pickle
            cache = FanoutCache(cache_options["directory"], **cache_options["params"])
            with cache.transact():
                cache_epoch = cache.get(("snapshot-epoch", path))
                saved_fingerprint: Any = cache.get(("snapshot-fingerprint", path))
                packed = cache.get(path) if saved_fingerprint is not None else None
                previous = cache.get(("snapshot-problematic", path), [])
            previous = [value for value in previous if isinstance(value, int)] \
                if isinstance(previous, list) else []

            def unpack() -> dict[int, Any] | None:
                if not isinstance(packed, bytes):
                    return None
                unpacked = pickle.loads(blosc.decompress(packed))
                valid = isinstance(unpacked, dict) and all(
                    isinstance(shot, int) and isinstance(array, np.ndarray)
                    and array.ndim == 2 and array.shape[1] == 3
                    for shot, array in unpacked.items())
                return unpacked if valid else None

            if saved_fingerprint == fingerprint:
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
    read = 0 if cached else len(files) - len(in_memory | reused)
    if in_memory or (from_disk and not cached):
        parts = [f"{len(in_memory)} shots from memory"] if in_memory else []
        parts += [f"{len(from_disk)} shots from disk cache"] if from_disk else []
        cache_reason = f"Reused {', '.join(parts)}; read {read} new or changed TXY files"
    elif cached:
        cache_reason = ""
    source = "updated" if in_memory else "disk" if cached else "merged" if reused else "files"
    send({"kind": "load_source", "source": source, "cache_reason": cache_reason})
    rows = size = loaded = 0
    last_progress = 0.0

    def read_txy(shot: int, filename: str) -> Any:
        frame = pd.read_csv(filename, sep=",", names=["t", "x", "y"], dtype=np.float64)
        if frame.isna().any().any():
            problematic.append(shot)
        array = np.asarray(frame.dropna(), dtype=np.float64)
        data[shot] = array
        return array

    for i, (shot, filename) in enumerate(files):
        try:
            array = None
            if shot in in_memory:
                # Unchanged and already in the caller's RAM: nothing to read or send.
                loaded += 1
            elif shot in reused:
                array = data[shot]
            elif not cached:
                array = read_txy(shot, filename)
            if array is not None:
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
            send({"kind": "progress", "progress": (i + 1) / len(files)})
            last_progress = now
    if not loaded:
        raise ValueError("No readable TXY files in this folder")

    def changed() -> bool:
        return fingerprint != [(shot, info.st_size, info.st_mtime_ns)
                               for shot, filename in files for info in (os.stat(filename),)]

    if changed():
        if cache is not None:
            cache.close()
        raise ValueError("Folder changed while loading — Refresh to retry")
    send({"kind": "loaded", "rows": rows, "bytes": size, "files": loaded,
          "problematic": sorted(set(problematic)),
          "source": source, "cached": cached,
          "disk_cached": cached or _disk_cached(cache, path),
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
                try:
                    read_txy(shot, filename)
                except (OSError, ValueError, pd.errors.ParserError):
                    problematic.append(shot)
        if changed():
            return
        import blosc
        import pickle
        packed = blosc.compress(pickle.dumps(dict(sorted(data.items())), protocol=pickle.HIGHEST_PROTOCOL),
                                typesize=8, cname="zstd", clevel=9, shuffle=blosc.NOSHUFFLE)
        with cache.transact():
            if cache.get(("snapshot-epoch", path)) == cache_epoch and cache.set(path, packed):
                cache.set(("snapshot-fingerprint", path), fingerprint)
                cache.set(("snapshot-problematic", path), sorted(set(problematic)))
        send({"kind": "disk_cached", "disk_cached": _disk_cached(cache, path)})
    except Exception as exc:
        send({"kind": "cache_warning", "message": str(exc)})
    finally:
        cache.close()


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
            load(request["path"], request["output"], cache_options=request.get("cache"),
                 memory=request.get("memory"))
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
