"""Basic scans and details (``scan``/``details``), and the history and subfolder-status saves."""
from __future__ import annotations

import time
from typing import Any, TYPE_CHECKING

from helab.io_ops import metadata, stores
from helab.io_ops.fingerprints import _saved_fingerprint, _settled
from helab.io_ops.infra import Emit, Heartbeat, _entry_stat, _is_dir, _scandir, _stat, emit
from helab.io_ops.markers import _marker_temporary
from helab.io_ops.metadata import _dataset_flags, _saved_folders, _send_guard
from helab.io_ops.stores import _data_root, _store_or_off
from helab.io_ops.summary import _save_summary, _summary
from helab.utils import file_kinds

if TYPE_CHECKING:
    from helab.utils.cache_store import CacheStore, SaveGuard


def scan(path: str, send: Emit = emit, cache_options: dict[str, Any] | None = None, *,
         manual: bool = True, automatic: bool = False,
         operation_id: str = "", revision: int = 0) -> None:
    """Full scan: a basic scan, or browse step 2 (``details``). Saves summary and history.

    A folder with no disk cache (off, or off by design for it) has no saved history: the app's
    session history is then the only one, and it skips blocked folders before submitting.
    """
    from uuid import uuid4
    from helab.utils.cache_store import StoreError
    from helab.utils.scan_history import ScanSkipped, begin_scan, write_outcome
    send({"kind": "scan_mode", "mode": "metadata"})
    store, cache_off = _store_or_off(cache_options, send, path)
    # Whether this folder has saved history that may be unreadable now.
    saved_history = bool(cache_options) and not cache_off
    try:
        guard: SaveGuard | None = None
        if store is not None:
            try:
                # Taken first, before anything is read: a Clear from now on stops its saves,
                # including the failure the app saves for it later (it gets this guard).
                guard = _send_guard(store, path, send)
            except StoreError:
                guard = None
        history, _ = metadata._send_saved(store, path, send)
        blocked = history is not None and history["blocked"]
        if not manual and (blocked or automatic and history is None and saved_history):
            # Browsing a blocked folder lists it (step 1) without this scan.
            send({"kind": "scan_mode", "mode": "skipped"})
            return
        operation_id = operation_id or uuid4().hex
        revision = revision or time.time_ns()
        if guard is None and saved_history:
            send({"kind": "scan_history_warning", "message": "The cache could not be opened"})
            if not manual:
                # Without the saved history this may be a blocked folder.
                send({"kind": "scan_mode", "mode": "skipped"})
                return
        if store is not None and guard is not None:
            try:
                history, revision = begin_scan(store, path, operation_id, revision, guard,
                                               manual=manual, automatic=automatic)
                send({"kind": "scan_history", "history": history, "revision": revision})
            except ScanSkipped as skipped:
                if skipped.history is not None:
                    send({"kind": "scan_history", "history": skipped.history})
                send({"kind": "scan_mode", "mode": "skipped"})
                return
            except Exception as exc:
                send({"kind": "scan_history_warning", "message": str(exc)})
                if not manual:
                    # Without the saved history this may be a blocked folder.
                    send({"kind": "scan_mode", "mode": "skipped"})
                    return
        send({"kind": "scan_mode", "mode": "scan"})
        report = _scan(path, send, store, guard, bool(cache_options))
        if store is not None and guard is not None:
            try:
                history = write_outcome(store, path, {"operation_id": operation_id, "revision": revision,
                    "kind": "success", "at": report["scanned_at"]}, guard)
                send({"kind": "scan_history", "history": history, "revision": revision, "saved": True})
            except Exception as exc:
                send({"kind": "scan_history_warning", "message": str(exc)})
    finally:
        if store is not None:
            store.close()


def save_subtrees(cache_options: dict[str, Any], records: list[dict[str, Any]], send: Emit = emit,
                  *, verified_volumes: list[list[str]] | None = None) -> None:
    """Save (or, with status "", remove) folders' statuses derived from their subfolders.

    Resolvable paths are saved in one transaction; paths without a data root (or on a volume
    not yet verified, ``verified_volumes``) are reported as skipped: a later listing derives
    them again. A failed write raises rather than reporting saved.
    """
    from helab.utils.cache_paths import UnresolvedRemotePath
    skipped: list[str] = []
    saved: list[str] = []
    with stores._cache_store(cache_options["directory"], local_lane=True, verified_volumes=verified_volumes) as store:
        batch: dict[str, dict[str, Any] | None] = {}
        for record in records:
            path = str(record["path"])
            try:
                store._path_key(path)
            except UnresolvedRemotePath:
                skipped.append(path)
                continue
            batch[path] = ({"version": 1, **{k: v for k, v in record.items() if k != "path"}}
                           if record["status"] else None)
        if batch:
            store.save_records("subtrees", batch, store.guard(list(batch), ("subtrees",)))
            saved = list(batch)
    if skipped:
        send({"kind": "cache_warning", "message":
              f"Subfolder status cache skipped {len(skipped)} folder(s) without a usable data root."})
    result: dict[str, Any] = {"kind": "subtree_saved", "paths": saved}
    if skipped:
        result["skipped"] = skipped
    send(result)


def save_scan_history(cache_options: dict[str, Any], path: str, outcome: dict[str, Any],
                      saved_guard: dict[str, Any] | None, send: Emit = emit,
                      *, verified_volumes: list[list[str]] | None = None) -> None:
    """Save a scan's outcome. A folder with no disk cache by design keeps it in the app's RAM."""
    from helab.utils.cache_paths import UnresolvedRemotePath
    from helab.utils.cache_store import SaveGuard as Guard
    from helab.utils.data_roots import VolumeUnverified
    from helab.utils.scan_history import write_outcome
    try:
        store = stores._cache_store(cache_options["directory"], [path], local_lane=True,
                             verified_volumes=verified_volumes)
    except VolumeUnverified:
        raise
    except UnresolvedRemotePath as exc:
        send({"kind": "cache_skipped", "paths": [path], "mounts": [
            {"path": exc.mount_path, "type": exc.mount_type, "detail": str(exc)}]})
        return
    with store:
        # The scan's own guard when the app has it: a Clear after that scan started
        # must not get its outcome back.
        guard = (Guard(saved_guard["generations"], saved_guard["epochs"]) if saved_guard
                 else store.guard([path], ("histories",)))
        send({"kind": "scan_history_saved", "history": write_outcome(store, path, outcome, guard)})


def _scan(path: str, send: Emit, store: CacheStore | None, guard: SaveGuard | None,
          cache_on: bool = False) -> dict[str, Any]:
    found: dict[str, set[int]] = {}
    entries: list[dict[str, Any]] = []
    has_dirs = False
    empty = True
    fingerprint: list[tuple[int, int, int]] = []
    txy_bytes = 0

    def flush() -> None:
        if store is not None:
            saved = _saved_folders(store, [child["path"] for child in entries], send)
            for child in entries:
                child.update(saved.get(child["path"], {}))
        send({"kind": "entries", "entries": entries})

    beat = Heartbeat(send, "listing")
    # Do not traverse directory symlinks or recursively probe children.
    with _scandir(path, "listing") as directory:
        for entry in directory:
            beat()
            if entry.name == ".helab-root" or _marker_temporary(entry.name):
                continue
            empty = False
            if matched := file_kinds.match(entry.name):
                kind, shot = matched
                found.setdefault(kind.name, set()).add(shot)
                if kind is file_kinds.TXY:
                    # Match load()'s fingerprint of the actual converted file,
                    # including when the file itself is a symlink.
                    info = _entry_stat(entry, "fingerprint")
                    fingerprint.append((shot, info.st_size, info.st_mtime_ns))
                    txy_bytes += info.st_size
            if _is_dir(entry):
                has_dirs = True
                try:
                    stat = _stat(entry.path, "subfolder date", follow_symlinks=False)
                    modified: float | None = stat.st_mtime
                except OSError:
                    modified = None
                entries.append({"path": entry.path, "name": entry.name, "modified": modified,
                                "modified_observed_at": time.time()})
                if len(entries) >= 128:
                    flush()
                    entries = []
    if entries:
        flush()
    if store is not None:
        _check_cached_shots(store, path, found, send)
    # Like load(), files that may still be being written are not in the signature,
    # so a scan during acquisition agrees with the data loaded meanwhile.
    settled = _settled(fingerprint)
    report = {**_summary(path, found, {file_kinds.TXY.name: txy_bytes}, has_dirs, empty, settled, time.time()),
              "unsettled": len(fingerprint) - len(settled),
              # Without a cache nothing is cached; a cache that couldn't be opened is unknown.
              **({} if cache_on else {"disk_cached": False, "cache_info": {}}), **_dataset_flags(store, path, send),
              **_data_root(store, path)}
    # Publish the completed source check before optional cache writes, so even a
    # stalled cache writer cannot turn it into a failed basic scan.
    send(report)
    if store is not None and guard is not None:
        _save_summary(store, path, report, guard, send)
    return report


def _check_cached_shots(store: CacheStore, path: str, found: dict[str, set[int]], send: Emit) -> None:
    """Send ``cache_mismatch`` if shots cached for this folder are no longer in it (as a load's
    ``shots_missing``): TXY files are written once, so another folder may sit at this path.
    Reads only the dataset's record (its fingerprint), never its data; unreadable is no answer."""
    row = store.read_dataset_row(path).value
    if row is None:
        return
    known = {int(entry[0]) for entry in _saved_fingerprint(row)}
    listed = found.get(file_kinds.TXY.name, set())
    missing = sorted(known - listed)
    if missing:
        send({"kind": "cache_mismatch", "missing": missing[:20], "missing_count": len(missing),
              "known_count": len(known), "listed_count": len(listed)})
