"""A folder's saved records (history, summary, subfolder status, flags, constants) for listings and scans."""
from __future__ import annotations

import os
from typing import Any, TYPE_CHECKING, cast

from helab.io_ops.events import DatasetFlags
from helab.io_ops.infra import Emit
from helab.io_ops.stores import _cache_info
from helab.io_ops.summary import _valid_subtree, _valid_summary

if TYPE_CHECKING:
    from helab.utils.cache_store import CacheStore, SaveGuard


def _saved_folders(store: CacheStore, paths: list[str], send: Emit) -> dict[str, dict[str, Any]]:
    """Each folder's saved history, summary, subfolder status and dataset flags, in a few queries.

    A read error is unknown, never "nothing saved": a history that can't be read is
    None, and an unreadable summary, subfolder status or dataset leaves its keys out,
    so the GUI keeps what it knew. The error is sent as a ``cache_warning``.
    Saved statuses are last-known results for their paths until those folders are checked.
    """
    from helab.utils.cache_paths import UnresolvedRemotePath
    usable: list[str] = []
    refused: list[str] = []
    mounts: dict[str, dict[str, str]] = {}
    keys: dict[str, str] = {}
    for path in paths:
        try:
            keys[path] = store._path_key(path)
        except UnresolvedRemotePath as exc:
            refused.append(path)
            mounts[exc.mount_path] = {"path": exc.mount_path, "type": exc.mount_type, "detail": str(exc)}
        else:
            usable.append(path)
    if refused:
        # A child mount does not make the parent's own saved result uncertain.
        # FolderCache associates cache_warning with the request root, so report
        # this separately rather than putting a false warning on that parent.
        send({"kind": "cache_skipped", "paths": refused, "mounts": list(mounts.values())})
    paths = usable
    if not paths:
        return {}
    # Each read below keys every path: they use these keys (the resolver is pure for this call).
    resolve = store._path_key
    store._path_key = lambda path: keys[path] if path in keys else resolve(path)
    try:
        return _read_saved(store, paths, send)
    finally:
        store._path_key = resolve


def _read_saved(store: CacheStore, paths: list[str], send: Emit) -> dict[str, dict[str, Any]]:
    """``_saved_folders``' reads, for paths that have keys."""
    from helab.utils.scan_history import read_histories
    histories = read_histories(store, paths)
    summaries = store.read_records("summaries", paths)
    subtrees = store.read_records("subtrees", paths)
    datasets = store.read_dataset_infos(paths)
    prefs = store.read_prefs(paths)
    constants = store.read_constants(paths)
    saved: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for path in paths:
        history = histories[path]
        entry: dict[str, Any] = {"scan_history": history}
        if summaries[path].failed:
            errors.append(summaries[path].error)
        else:
            summary = _valid_summary(summaries[path].value)
            entry["scan_status"] = summary
        if subtrees[path].failed:
            errors.append(subtrees[path].error)
        else:
            entry["subtree"] = _valid_subtree(subtrees[path].value)
        if prefs[path].failed:
            errors.append(prefs[path].error)
        else:
            # The user's choices for this folder alone (never inherited).
            entry["prefs"] = prefs[path].value or {}
        if constants[path].failed:
            errors.append(constants[path].error)
        elif constants[path].value is not None:
            # The folder's own constants; its subfolders inherit them (the app decides). Only when
            # set: with ``saved_read``, no key means none set (most folders: a smaller listing).
            entry["constants"] = constants[path].value
        dataset = datasets[path]
        if dataset.failed:
            errors.append(dataset.error)
        else:
            entry["disk_cached"] = dataset.value is not None
            entry["cache_info"] = {} if dataset.value is None else _listed_sizes(
                _cache_info(dataset.value["info"]), dataset.value)
        entry["saved_read"] = (history is not None and not summaries[path].failed
                               and not subtrees[path].failed and not prefs[path].failed
                               and not constants[path].failed
                               and not dataset.failed)
        saved[path] = entry
    if errors:
        more = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
        send({"kind": "cache_warning", "message": f"{errors[0]}{more}"})
    return saved


def _listed_sizes(info: dict[str, Any], dataset: Any) -> dict[str, Any]:
    """A listed dataset's ``info`` with its TXY files' size and its size in RAM."""
    if not info:
        return info
    return {**info, "txy_bytes": int(dataset["source_bytes"]), "ram_bytes": int(dataset["ram_bytes"]),
            "disk_bytes": int(dataset["bytes"])}


def _dataset_flags(store: CacheStore | None, path: str, send: Emit) -> DatasetFlags:
    """The folder's ``disk_cached`` and ``cache_info``; left out if unknown."""
    if store is None:
        return {}
    saved = _saved_folders(store, [path], send)[path]
    return cast(DatasetFlags, {key: saved[key] for key in ("disk_cached", "cache_info") if key in saved})


def _send_saved(store: CacheStore | None, path: str, send: Emit) -> tuple[Any, dict[str, Any] | None]:
    """Send this folder's saved records; return the history and read result."""
    if store is None:
        send({"kind": "scan_history", "history": None})
        return None, None
    saved = _saved_folders(store, [path], send)[path]
    send({"kind": "scan_history", "history": saved["scan_history"]})
    if saved.get("scan_status"):
        send({"kind": "scan_cached", "status": saved["scan_status"]})
    if saved.get("subtree"):
        send({"kind": "subtree_cached", "subtree": saved["subtree"]})
    if "prefs" in saved:
        send({"kind": "folder_prefs", "path": path, "prefs": saved["prefs"]})
    _send_constants(store, path, saved, send)
    return saved["scan_history"], saved


def _send_constants(store: CacheStore, path: str, saved: dict[str, Any], send: Emit) -> None:
    """The folder's own constants and those of the folders above it (with keys in this store), which
    it inherits: the app needs them even when it never listed those folders (a tab's top folder).
    One read; only folders that set some (a folder whose record can't be read is left out too:
    unknown, never "none set")."""
    folders: dict[str, Any] = {path: saved["constants"]} if "constants" in saved else {}
    above: list[str] = []
    child, parent = path, os.path.dirname(path)
    while parent and parent != child and len(above) < 64:
        above.append(parent)
        child, parent = parent, os.path.dirname(parent)
    found = store.read_constants(above, keyed_only=True) if above else {}
    folders.update({folder: read.value for folder, read in found.items() if read.value is not None})
    if any(read.failed for read in found.values()):
        send({"kind": "cache_warning", "message": next(read.error for read in found.values() if read.failed)})
    if folders:
        send({"kind": "folder_constants", "folders": folders})


def _send_guard(store: CacheStore | None, path: str, send: Emit) -> SaveGuard | None:
    """Take a listing or scan's save guard when it starts and send it to the app, which hands
    it to the history write that records this job's failure: a Clear after the job started
    then discards that write too. Raises ``StoreError`` if it can't be read."""
    if store is None:
        return None
    guard = store.guard([path], ("summaries", "histories"))
    send({"kind": "save_guard", "guard": {"generations": dict(guard.generations), "epochs": dict(guard.epochs)}})
    return guard
