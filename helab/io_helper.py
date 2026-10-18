"""Isolated filesystem helper. Importing this module must not start Qt or Dash.

One JSON request on stdin, bounded JSON event batches on stdout. The parent may
kill this process when an OS filesystem call stalls; it never waits in the GUI.
"""
from __future__ import annotations

import json
import base64
import contextlib
import hashlib
import math
import os
import random
import sys
import time
from typing import TYPE_CHECKING, Any, Callable, Literal

from helab.utils import file_kinds, large_folder

if TYPE_CHECKING:
    from helab.utils.cache_paths import Mount
    from helab.utils.cache_store import CacheStore, SaveGuard
    from helab.utils.data_roots import LocalVolumes

Emit = Callable[[dict[str, Any]], None]
# Another computer may still be writing a file modified this recently; it is
# left for the next load rather than read half-written. Tests set it to 0.
SETTLE_SECONDS = float(os.environ.get("HELAB_SETTLE_SECONDS", "5"))
# One helper handles one request. Reusing a volume ID within that request avoids
# repeated diskutil calls during discovery and listing without persisting stale IDs.
_volume_id_cache: dict[tuple[str, str], str | None] = {}


def _cached_volume_id(mount: Any) -> str | None:
    from helab.utils.data_roots import _volume_id
    key = (str(mount.path), str(mount.source))
    if key not in _volume_id_cache:
        _volume_id_cache[key] = _volume_id(mount)
    return _volume_id_cache[key]


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


def _cache_info(info: object) -> dict[str, Any]:
    """A dataset record's ``info`` if it is usable (a save date and signature), else {}."""
    if isinstance(info, dict):
        saved_at = info.get("saved_at")
        if (isinstance(saved_at, (int, float)) and math.isfinite(saved_at) and saved_at > 0
                and isinstance(info.get("signature"), str)):
            return info
    return {}


def _data_root(store: CacheStore | None, path: str) -> dict[str, Any]:
    """``data_root`` for a result: the folder holding the marker that ``path`` is keyed by, so
    the app knows the root of a folder whose root folder it hasn't listed (a restored tab deep
    inside one). Empty without one."""
    import sqlite3
    from helab.utils.cache_paths import UnresolvedRemotePath
    from helab.utils.cache_store import StoreError
    if store is None:
        return {}
    try:
        key = store._path_key(path)
        if not key.startswith("root://"):
            return {}
        identifier, _, suffix = key[len("root://"):].partition("/")
        folder = path
        for _ in suffix.split("/") if suffix else ():
            folder = os.path.dirname(folder)
        found = store.root_at(store._location_key(folder))
    except (UnresolvedRemotePath, StoreError, sqlite3.Error):
        return {}
    return {"data_root": {"path": folder, "uuid": identifier,
                          "label": found[1] if found is not None and found[0] == identifier else ""}}


def _open_store(cache_options: dict[str, Any] | None, send: Emit, path: str,
                *, local_lane: bool = False,
                verified_volumes: list[list[str]] | None = None) -> CacheStore | None:
    """The disk cache, or None without one or if it can't be opened.

    An opening error is sent as a ``cache_warning``; what the cache holds is then
    unknown, never "nothing saved" (callers check ``cache_options`` to tell).
    A volume not yet verified (``VolumeUnverified``) is raised to the caller.
    """
    return _store_or_off(cache_options, send, path, local_lane=local_lane,
                         verified_volumes=verified_volumes)[0]


def _store_or_off(cache_options: dict[str, Any] | None, send: Emit, path: str,
                  *, local_lane: bool = False,
                  verified_volumes: list[list[str]] | None = None) -> tuple[CacheStore | None, bool]:
    """``_open_store``, and whether this folder has no disk cache by design.

    That is a folder without a confirmed data root or on an unsupported mount (``cache_skipped``):
    nothing is saved for it, so nothing saved can be missed, unlike a cache that can't be opened.
    """
    if not cache_options:
        return None, False
    from helab.utils.cache_paths import UnresolvedRemotePath
    from helab.utils.cache_store import StoreError
    from helab.utils.data_roots import VolumeUnverified
    try:
        return _cache_store(cache_options["directory"], [path], local_lane=local_lane,
                            verified_volumes=verified_volumes), False
    except VolumeUnverified:
        raise
    except UnresolvedRemotePath as exc:
        send({"kind": "cache_skipped", "paths": [path], "mounts": [
            {"path": exc.mount_path, "type": exc.mount_type, "detail": str(exc)}]})
        return None, True
    except (StoreError, OSError) as exc:
        # Optional cache metadata must not prevent browsing source folders.
        send({"kind": "cache_warning", "message": f"Disk cache could not be opened: {exc}"})
        return None, False


def _cache_store(root: str, source_paths: list[str] | None = None,
                 *, local_lane: bool = False, allow_unrooted: bool = False,
                 verified_volumes: list[list[str]] | None = None) -> CacheStore:
    """Open root-keyed records; the local lane uses only captured volume IDs.

    With ``verified_volumes`` (the mounts the app's last data-root verification checked), the
    local lane trusts only those hints and the system volume's: a disk swapped in at the same
    mount path and device would otherwise inherit the previous disk's ID, and its cached data.
    A source path on another hinted mount raises ``VolumeUnverified``.
    """
    from helab.utils.cache_paths import CachePaths, UnresolvedRemotePath, _inside, _normal, current_mounts
    from helab.utils.cache_store import CacheStore, StoreError
    from helab.utils.data_roots import (DataRoots, LocalVolumes, NoDataRoot, RootLocation, VolumeUnverified,
                                        current_local_volumes, fixed_mount)
    store: CacheStore | None = None
    held: list[str] = []
    try:
        mounts = current_mounts()
        paths = CachePaths(mounts)
        store = CacheStore(root, root_mode=True)
        if local_lane:
            known = {(path, source): identifier for path, source, identifier in store.volume_locations()}
            hinted = [mount for mount in mounts if (mount.path, mount.source) in known]
            if verified_volumes is not None:
                verified = {(path, source) for path, source in verified_volumes}
                held = [mount.path for mount in hinted
                        if (mount.path, mount.source) not in verified and not fixed_mount(mount)]
                hinted = [mount for mount in hinted if mount.path not in held]
            volumes = LocalVolumes((mount, known[(mount.path, mount.source)]) for mount in hinted)
        else:
            volumes = current_local_volumes(mounts, paths=source_paths or (), id_reader=_cached_volume_id)
            if not store.read_only:
                known = {(path, source): identifier for path, source, identifier in store.volume_locations()}
                for mount, identifier in volumes.volumes:
                    if known.get((mount.path, mount.source)) != identifier:
                        store.record_volume(mount.path, mount.source, identifier)
        resolver = DataRoots(paths, (RootLocation(*row) for row in store.root_locations()),
                             local_location=volumes.location, local_source=volumes.source,
                             case_insensitive_volumes=sys.platform == "win32")
        for path in source_paths or ():
            if not allow_unrooted:
                try:
                    resolver.key(path)
                except NoDataRoot:
                    if not any(_inside(_normal(path), _normal(mount)) for mount in held):
                        raise
                    raise VolumeUnverified(path) from None
    except UnresolvedRemotePath:
        if store is not None:
            store.close()
        raise
    except Exception as exc:
        if store is not None:
            store.close()
        raise StoreError(f"Mount information is unavailable: {exc}") from exc
    store._path_key = resolver.key
    store._source_path = resolver.source
    store._location_key = resolver.location
    store._location_source = lambda location: (paths.source(location) if location.startswith("smb://")
                                               else volumes.source(location))
    return store


def _discover_root(path: str, present: bool, cache_options: dict[str, Any] | None,
                   send: Emit) -> bool:
    """Reconcile the marker found by a source listing with the local roots table.

    Returns whether this location's root changed (found, replaced, removed or now pending),
    so the folder's records may have another key.
    """
    if not cache_options:
        return False
    from helab.utils.cache_paths import UnresolvedRemotePath
    from helab.utils.cache_store import KINDS, StoreError
    from helab.utils.data_roots import NoDataRoot, read_marker
    try:
        with _cache_store(cache_options["directory"], [path], allow_unrooted=True) as store:
            location = store._location_key(path)
            old = store.root_at(location)
            if not present:
                if old is not None:
                    store.forget_root(location)
                    send({"kind": "root_changed", "path": path, "location": location,
                          "reason": "marker removed"})
                return old is not None
            try:
                marker = read_marker(path)
            except OSError as exc:
                send({"kind": "cache_warning", "message": f"Cannot read {path}/.helab-root: {exc}"})
                return False
            except ValueError as exc:
                if old is not None:
                    store.forget_root(location)
                send({"kind": "cache_warning", "message": f"Invalid {path}/.helab-root: {exc}"})
                return old is not None
            duplicates = store.other_root_locations(marker.uuid, location)
            decision: Literal["confirmed", "pending"] = (
                "pending" if old is not None and old[0] == marker.uuid and old[2] == "pending"
                else "confirmed" if old is not None and old[0] == marker.uuid
                else "pending" if duplicates else "confirmed")
            old_key = ""
            if decision == "confirmed" and old is None:
                try:
                    old_key = store._path_key(path)
                except NoDataRoot:
                    pass
            store.record_root(location, marker.uuid,
                              "smb" if location.startswith("smb://") else "vol",
                              marker.label, decision=decision)
            changed = old is None or old[0] != marker.uuid or old[2] != decision
            if decision == "pending":
                # Hints for the user's answer (D4): where else it is, and each marker file's details.
                others: list[dict[str, Any]] = [{"location": other, "path": _location_path(store, other),
                                                 "marker": None} for other in duplicates]
                for other in others:
                    if other["path"]:
                        other["marker"] = _marker_hint(str(other["path"]))
                send({"kind": "root_duplicate", "path": path, "location": location,
                      "uuid": marker.uuid, "label": marker.label, "other_locations": duplicates,
                      "marker": _marker_hint(path), "others": others})
                return changed
            if old_key and old_key != f"root://{marker.uuid}":
                moved = store.rekey_subtree(old_key, f"root://{marker.uuid}")
                if moved:
                    sources = [store._source_path(key) for key in moved]
                    send({"kind": "removed", "kinds": list(KINDS), "paths": sources})
                    send({"kind": "root_rekeyed", "path": path, "count": len(moved)})
            send({"kind": "root_changed" if old and old[0] != marker.uuid else "root_found",
                  "path": path, "location": location, "uuid": marker.uuid, "label": marker.label})
            return changed
    except UnresolvedRemotePath:
        # The subsequent optional-cache open reports the typed skip once.
        return False
    except StoreError as exc:
        send({"kind": "cache_warning", "message": f"Data root could not be recorded: {exc}"})
        return False


def _mount_fingerprint() -> list[list[str]] | None:
    from helab.utils.cache_paths import current_mounts
    try:
        return sorted([[mount.path, mount.source] for mount in current_mounts()])
    except (OSError, RuntimeError):
        return None


def verify_volumes(cache_options: dict[str, Any], send: Emit = emit,
                   mounts: list[Mount] | None = None) -> LocalVolumes:
    """Refresh the saved volume IDs of mounts that have them, and send ``volumes_verified``:
    the mounts whose hints the local lane may trust now.

    Reads only mounted volumes' IDs (diskutil, GetVolumeInformationW), never source folders,
    so it runs on the local lane at startup and after a mount change (``volumes_verify``).
    """
    from helab.utils.cache_paths import current_mounts
    from helab.utils.cache_store import CacheStore
    from helab.utils.data_roots import current_local_volumes
    mounts = current_mounts() if mounts is None else mounts
    with CacheStore(cache_options["directory"], root_mode=True) as store:
        known_mounts = {(path, source) for path, source, _ in store.volume_locations()}
    local = current_local_volumes(mounts, paths=[mount.path for mount in mounts
                                                 if (mount.path, mount.source) in known_mounts],
                                  id_reader=_cached_volume_id)
    verified: list[list[str]] = []
    if local.volumes:
        with CacheStore(cache_options["directory"], root_mode=True) as store:
            known = {(path, source): identifier for path, source, identifier in store.volume_locations()}
            for mount, identifier in local.volumes:
                if known.get((mount.path, mount.source)) != identifier and not store.read_only:
                    store.record_volume(mount.path, mount.source, identifier)
                    known[(mount.path, mount.source)] = identifier
                if known.get((mount.path, mount.source)) == identifier:
                    verified.append([mount.path, mount.source])
    send({"kind": "volumes_verified", "volumes": sorted(verified)})
    return local


def verify_known_roots(cache_options: dict[str, Any], send: Emit = emit) -> None:
    """Check remembered marker locations in a background source helper.

    Only the recorded marker folders are visited. Missing mounts are left alone;
    a mounted folder whose marker changed is reconciled like a listing.
    """
    from helab.utils.cache_paths import CachePaths, current_mounts
    from helab.utils.cache_store import CacheStore
    from helab.utils.data_roots import MARKER_NAME
    mounts = current_mounts()
    with CacheStore(cache_options["directory"], root_mode=True) as store:
        roots = store.root_locations()
    local = verify_volumes(cache_options, send, mounts)
    locations = CachePaths(mounts)
    beat = Heartbeat(send, "verifying data roots")
    for location, _, _ in roots:
        beat()
        source = (locations.source(location) if location.startswith("smb://")
                  else local.source(location))
        if source == location or not os.path.isdir(source):
            continue
        try:
            os.lstat(os.path.join(source, MARKER_NAME))
            present = True
        except FileNotFoundError:
            present = False
        except OSError:
            continue  # Unknown: the root is kept, as for a marker that can't be read.
        _discover_root(source, present, cache_options, send)
    send({"kind": "roots_verified", "mounts": sorted([[mount.path, mount.source] for mount in mounts])})


def _saved_folders(store: CacheStore, paths: list[str], send: Emit) -> dict[str, dict[str, Any]]:
    """Each folder's saved history, summary, subfolder status and dataset flags, in a few queries.

    A read error is unknown, never "nothing saved": a history that can't be read is
    None, and an unreadable summary, subfolder status or dataset leaves its keys out,
    so the GUI keeps what it knew. The error is sent as a ``cache_warning``.
    Saved statuses are last-known results for their paths until those folders are checked.
    """
    from helab.utils.cache_paths import UnresolvedRemotePath
    from helab.utils.scan_history import read_histories
    usable: list[str] = []
    refused: list[str] = []
    mounts: dict[str, dict[str, str]] = {}
    for path in paths:
        try:
            store._path_key(path)
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
    histories = read_histories(store, paths)
    summaries = store.read_records("summaries", paths)
    subtrees = store.read_records("subtrees", paths)
    datasets = store.read_dataset_infos(paths)
    prefs = store.read_prefs(paths)
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
        dataset = datasets[path]
        if dataset.failed:
            errors.append(dataset.error)
        else:
            entry["disk_cached"] = dataset.value is not None
            entry["cache_info"] = {} if dataset.value is None else _listed_sizes(
                _cache_info(dataset.value["info"]), dataset.value)
        entry["saved_read"] = (history is not None and not summaries[path].failed
                               and not subtrees[path].failed and not prefs[path].failed
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


def _dataset_flags(store: CacheStore | None, path: str, send: Emit) -> dict[str, Any]:
    """The folder's ``disk_cached`` and ``cache_info``; left out if unknown."""
    if store is None:
        return {}
    saved = _saved_folders(store, [path], send)[path]
    return {key: saved[key] for key in ("disk_cached", "cache_info") if key in saved}


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
    return saved["scan_history"], saved


def _send_guard(store: CacheStore | None, path: str, send: Emit) -> SaveGuard | None:
    """Take a listing or scan's save guard when it starts and send it to the app, which hands
    it to the history write that records this job's failure: a Clear after the job started
    then discards that write too. Raises ``StoreError`` if it can't be read."""
    if store is None:
        return None
    guard = store.guard([path], ("summaries", "histories"))
    send({"kind": "save_guard", "guard": {"generations": dict(guard.generations), "epochs": dict(guard.epochs)}})
    return guard


def _shots(found: dict[str, set[int]]) -> tuple[set[int], set[int]]:
    return found.get(file_kinds.RAW.name, set()), found.get(file_kinds.TXY.name, set())


def _classify(raw: set[int], txy: set[int], has_dirs: bool) -> tuple[str, int]:
    common = raw & txy
    if not raw and not txy:
        return ("unknown" if has_dirs else "nothing"), -1
    if raw == txy:
        return "ok", len(common)
    if common:
        return ("fixable" if txy <= raw else "critical" if raw <= txy else "warning"), len(common)
    return ("warning", len(raw | txy)) if not raw or not txy else ("critical", 0)


def list_folder(path: str, send: Emit = emit, cache_options: dict[str, Any] | None = None) -> None:
    """Browse step 1: names only, so a slow volume shows subfolders and counts first.

    One scandir with no per-entry stat (``is_dir`` uses the listing's file type).
    Each subfolder's saved summary, scan history and cache flags are read from the
    local cache, never the source, so saved badges appear with the names.
    The ``details`` scan (step 2) adds the signature and dates. A listing writes
    only root-discovery metadata; a failed listing's history is saved later by
    the app, with the guard this sends first.

    The folder's own marker is looked up (one lstat) and reconciled before the
    scandir, so the names stream with the right root's saved results. A marker
    the scandir doesn't find (or finds unexpectedly) is reconciled after it, and
    if that changes the folder's key the entries are sent again (``replace``).
    """
    from helab.utils.cache_store import StoreError
    from helab.utils.data_roots import MARKER_NAME
    store: CacheStore | None = None
    try:
        marker_before = False  # Absent, or unknown: decided by the scandir below.
        if cache_options:
            try:
                os.lstat(os.path.join(path, MARKER_NAME))
                marker_before = True
            except OSError:
                pass
        if marker_before:
            _discover_root(path, True, cache_options, send)
        early_events: list[dict[str, Any]] = []
        store = _open_store(cache_options, early_events.append, path)
        if store is not None or marker_before:
            for event in early_events:
                send(event)
            early_events.clear()
        try:
            _send_guard(store, path, send)
        except StoreError:
            pass
        _, root_saved = _send_saved(store, path, send)
        before_key = store._path_key(path) if store is not None else ""
        found: dict[str, set[int]] = {}
        entries: list[dict[str, Any]] = []
        batch: list[dict[str, Any]] = []

        def flush() -> None:
            nonlocal batch
            if not batch:
                return
            if store is not None:
                saved = _saved_folders(store, [child["path"] for child in batch], send)
                for child in batch:
                    child.update(saved.get(child["path"], {}))
            send({"kind": "entries", "entries": batch})
            entries.extend(batch)
            batch = []

        has_dirs = False
        empty = True
        marker_present = False
        listed_at = time.time()
        beat = Heartbeat(send, "listing")
        with os.scandir(path) as directory:
            for entry in directory:
                beat()
                if entry.name == MARKER_NAME:
                    marker_present = True
                    continue
                if _marker_temporary(entry.name):
                    continue
                empty = False
                if matched := file_kinds.match(entry.name):
                    found.setdefault(matched[0].name, set()).add(matched[1])
                elif entry.is_dir(follow_symlinks=False):
                    has_dirs = True
                    batch.append({"path": entry.path, "name": entry.name})
                    if len(batch) >= 128:
                        flush()
        flush()
        after_key = before_key
        # A marker seen only now, or one removed (its row is forgotten). Without one, a store
        # already open tells whether this location has a row to forget.
        if (marker_present != marker_before or not marker_present and (
                store is None or store.root_at(store._location_key(path)) is not None)) and (
                _discover_root(path, marker_present, cache_options, send)):
            if store is not None:
                store.close()
            early_events.clear()  # The new store's own are sent instead.
            store = _open_store(cache_options, send, path)
            after_key = store._path_key(path) if store is not None else ""
            if after_key != before_key:
                _, root_saved = _send_saved(store, path, send)
        for event in early_events:
            send(event)
        if before_key != after_key:
            for start in range(0, len(entries), 128):
                patch = [{"path": child["path"], "name": child["name"]}
                         for child in entries[start:start + 128]]
                if store is not None:
                    saved = _saved_folders(store, [child["path"] for child in patch], send)
                    for child in patch:
                        child.update(saved.get(child["path"], {}))
                send({"kind": "entries", "entries": patch, "replace": True})
        raw, txy = _shots(found)
        status, count = _classify(raw, txy, has_dirs)
        report: dict[str, Any] = {"kind": "status", "details": False, "status": status, "count": count,
                                  "empty": empty, "has_dirs": has_dirs, "scanned_at": listed_at,
                                  "raw": sorted(raw), "txy": sorted(txy),
                                  "files": file_kinds.files_summary(found, {}), **_dataset_flags(store, path, send),
                                  **_data_root(store, path)}
        if root_saved is not None:
            report["saved_root"] = root_saved
        # Only the cache needs it (its volume checks); without it a listing reads nothing more.
        if cache_options and (mounts := _mount_fingerprint()) is not None:
            send({"kind": "mounts_seen", "mounts": mounts})
        send(report)
    finally:
        if store is not None:
            store.close()


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
        history, _ = _send_saved(store, path, send)
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


SUMMARY_STATUSES = ("ok", "warning", "critical", "fixable", "unknown", "nothing")


def _valid_summary(info: object) -> dict[str, Any]:
    """A saved folder summary if it is complete, else {}."""
    if (isinstance(info, dict) and info.get("version") == 1
            and isinstance(info.get("signature"), str)
            and info.get("status") in SUMMARY_STATUSES
            and isinstance(info.get("count"), int)
            and isinstance(info.get("scanned_at"), (float, int))
            and math.isfinite(info["scanned_at"]) and 0 < info["scanned_at"] < 253402300799
            and all(isinstance(info.get(key), int) and info[key] >= 0
                    for key in ("raw_count", "txy_count"))
            and ("files" not in info or file_kinds.valid_files(info["files"]))):
        return info
    return {}


def _summary(path: str, found: dict[str, set[int]], sizes: dict[str, int], has_dirs: bool, empty: bool,
             fingerprint: list[tuple[int, int, int]], scanned_at: float) -> dict[str, Any]:
    """A complete status for this folder, as a scan or load computes it."""
    folder_stat = os.stat(path)
    raw, txy = _shots(found)
    status, count = _classify(raw, txy, has_dirs)
    return {"kind": "status", "details": True, "status": status, "count": count, "empty": empty,
            "has_dirs": has_dirs, "scanned_at": scanned_at,
            "raw": sorted(raw), "txy": sorted(txy), "files": file_kinds.files_summary(found, sizes),
            "modified": folder_stat.st_mtime,
            "signature": hashlib.sha256(json.dumps(sorted(fingerprint)).encode()).hexdigest()}


def _valid_subtree(info: object) -> dict[str, Any]:
    """A folder's saved status derived from its subfolders (not their contents), else {}."""
    if (isinstance(info, dict) and info.get("version") == 1
            and info.get("status") in ("something", "nothing")
            and isinstance(info.get("derived_at"), (float, int))
            and math.isfinite(info["derived_at"]) and 0 < info["derived_at"] < 253402300799
            and isinstance(info.get("older"), bool)
            and all(isinstance(info.get(key), int) and info[key] >= 0 for key in ("data", "checked", "total"))):
        return info
    return {}


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
    with _cache_store(cache_options["directory"], local_lane=True, verified_volumes=verified_volumes) as store:
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
        store = _cache_store(cache_options["directory"], [path], local_lane=True,
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


def _save_summary(store: CacheStore, path: str, report: dict[str, Any], guard: SaveGuard, send: Emit) -> None:
    # Optional persistence never turns a successful source check into a failure,
    # but a failed save is reported, not silently dropped.
    try:
        store.save_record("summaries", path, {"version": 1, **{
            key: value for key, value in report.items()
            if key not in ("kind", "details", "disk_cached", "cache_info", "raw", "txy")},
            "raw_count": len(report["raw"]), "txy_count": len(report["txy"])}, guard)
    except Exception as exc:
        send({"kind": "summary_save_failed", "message": f"Folder summary could not be saved: {exc}"})


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
    with os.scandir(path) as directory:
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
                    info = entry.stat()
                    fingerprint.append((shot, info.st_size, info.st_mtime_ns))
                    txy_bytes += info.st_size
            if entry.is_dir(follow_symlinks=False):
                has_dirs = True
                try:
                    stat = os.stat(entry.path, follow_symlinks=False)
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


def _samples_unchanged(path: str, fingerprint: list[list[int]], names: object, level: str) -> bool:
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
            info = os.stat(os.path.join(path, str(names[index])))
            if (info.st_size, info.st_mtime_ns) != tuple(fingerprint[index][1:]):
                return False
    except (OSError, TypeError, ValueError):
        return False
    return True


def _cached_signature(row: Any) -> str:
    """The signature a cached read gives this dataset (``read_cached``)."""
    return str(_cache_info(row["info"]).get("signature") or _fingerprint_signature(_saved_fingerprint(row)))


def read_cached(path: str, output: str, send: Emit = emit,
                cache_options: dict[str, Any] | None = None, *,
                limits: dict[str, Any] | None = None, allow_large: bool = False,
                verified_volumes: list[list[str]] | None = None) -> None:
    """Send a folder's dataset from the local disk cache, never touching the source folder.

    The caller shows it as not yet checked; a later ``load`` with it as the RAM
    base checks the folder. A large dataset (its TXY files' size) stops with
    ``too_large`` before it is read, unless ``allow_large``. On a volume not yet
    verified (``verified_volumes``) it fails with ``VolumeUnverified``; the app
    reads it again once verification has checked that volume.
    """
    import numpy as np
    from helab.utils.cache_store import unpack_dataset
    store = _open_store(cache_options, send, path, local_lane=True, verified_volumes=verified_volumes)
    if store is None:
        raise ValueError("Disk cache unavailable")
    try:
        flags = store.read_prefs([path])[path]
        if flags.failed:
            # Unknown whether the user chose not to cache it: don't read it.
            raise ValueError(f"The folder's settings couldn't be read: {flags.error}")
        if flags.value and flags.value.get("no_cache"):
            raise ValueError(NOT_CACHED_REASON)  # Chosen since the read was asked for.
        record = store.read_dataset_row(path)
        if record.value is not None and _too_large(
                large_folder.estimate(_saved_fingerprint(record.value)), limits, allow_large, send):
            return
        found = store.read_dataset(path)
        if found.failed:
            raise ValueError(found.error)
        if found.value is None:
            raise ValueError("No cached data for this folder")
        row, packed = found.value
        # Checked again on what was read: the dataset may have been replaced since.
        if _too_large(large_folder.estimate(_saved_fingerprint(row)), limits, allow_large, send):
            return
        data = unpack_dataset(packed)
        if data is None:
            raise ValueError("No cached data for this folder")
        _touch(store, path)
        root = _data_root(store, path)
    finally:
        store.close()
    saved = _saved_fingerprint(row)
    fingerprint = [list(entry) for entry in saved]
    by_shot = {int(entry[0]): entry for entry in fingerprint}
    problematic = {value for value in row["problematic"] if isinstance(value, int)}
    info = _with_sizes(_cache_info(row["info"]), row)
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
          "total_files": len(fingerprint) + unsettled, "failed_files": len(fingerprint) - len(shots),
          "unsettled_files": unsettled,
          "problematic": sorted(problematic & set(shots)), "source": "disk", "cached": True,
          "disk_cached": True, "disk_cache_pending": False, "cache_info": info,
          "load_counts": {"reused_memory": 0, "reused_disk": len(shots), "new": 0, "modified": 0,
                          "removed": 0, "read": 0, "new_loaded": 0, "modified_loaded": 0},
          "cache_reason": "", "fingerprint": fingerprint, "memory_shots": [], "verified": False, **root,
          "signature": info.get("signature") or _fingerprint_signature(fingerprint)})


def _unchanged_since_cache(path: str, send: Emit, store: CacheStore,
                           base_signature: str, memory: list[list[int]], check_level: str) -> bool:
    """One folder stat instead of listing and checking every file.

    When the caller holds the cached dataset (``base_signature``), the cache has
    no files that were still being written, and the folder has not been modified
    since the dataset's file list was taken, nothing can have been added or
    removed: ``loaded`` names the caller's shots and True is returned.
    """
    found = store.read_dataset_row(path)
    if found.value is None:
        return False
    row = found.value
    info = _with_sizes(_cache_info(row["info"]), row)
    as_of = _as_of(info)
    if info.get("signature") != base_signature or info.get("unsettled") or as_of is None:
        return False
    modified = os.stat(path).st_mtime
    fingerprint = [list(entry) for entry in _saved_fingerprint(row)]
    if modified > as_of or not _samples_unchanged(path, fingerprint, info.get("names"), check_level):
        return False
    held = sorted({int(entry[0]) for entry in memory} & {int(entry[0]) for entry in fingerprint})
    problematic = [value for value in row["problematic"] if isinstance(value, int) and value in held]
    _touch(store, path)
    send({"kind": "load_source", "source": "memory", "cache_reason": ""})
    send({"kind": "loaded", "rows": 0, "bytes": 0, "files": len(held), "loaded_at": time.time(),
          "total_files": len(fingerprint), "failed_files": len(fingerprint) - len(held), "unsettled_files": 0,
          "problematic": problematic, "source": "memory", "cached": True, "disk_cached": True,
          **_data_root(store, path),
          "disk_cache_pending": False, "cache_info": info, "unchanged": True, "modified": modified,
          "modified_observed_at": time.time(),
          "load_counts": {"reused_memory": len(held), "reused_disk": 0, "new": 0, "modified": 0,
                          "removed": 0, "read": 0, "new_loaded": 0, "modified_loaded": 0},
          "cache_reason": "Folder not modified since cached", "fingerprint": fingerprint,
          "memory_shots": held, "base_signature": base_signature, "signature": base_signature})
    return True


def load(path: str, output: str, send: Emit = emit,
         cache_options: dict[str, Any] | None = None,
         memory: list[list[int]] | None = None, base_signature: str = "",
         expected: str = "", *, limits: dict[str, Any] | None = None, allow_large: bool = False,
         no_cache: bool = False, full_check: bool = False, cache_base: bool = False,
         check_level: str = DEFAULT_CHECK_LEVEL, allow_missing: bool = False) -> None:
    """Load converted TXY files, reusing unchanged shots from RAM and disk cache.

    ``memory`` lists ``[shot, size, mtime_ns]`` for shots the caller already holds
    in RAM. Unchanged ones are neither read nor sent; ``loaded`` names them in
    ``memory_shots``. The disk cache is updated after ``loaded`` is sent.
    ``base_signature`` names the dataset those shots belong to; if it is the cached
    dataset and the folder is unmodified since, one folder stat is the whole check, unless
    ``full_check`` (Retry / Refresh): then every TXY file's size and mtime is compared.
    ``cache_base``: the caller is reading this folder's cached dataset at the same time (a
    ``cached`` request), so the cached shots count as held: ``memory_shots`` then names
    shots of that dataset (``base_signature``), which the caller takes from it.
    Shots cached or held that the folder no longer lists stop the load with ``shots_missing``
    before any file is read, unless ``allow_missing``.
    After its scan phase (saved as the folder's summary), a load whose new data is large
    (``limits``) stops with ``too_large`` before reading anything, unless ``allow_large``.
    A folder the user chose not to cache (``no_cache``, or its saved flag) is read into RAM
    only: its cached data is neither used nor written.
    """
    from helab.utils.cache_store import StoreError
    store = _open_store(cache_options, send, path)
    no_cache_reason = NOT_CACHED_REASON
    try:
        guard: SaveGuard | None = None
        if store is not None:
            try:
                # Taken first, before anything is read or imported: only a later job's
                # save may replace this one's, and a removal from now on stops it.
                guard = store.start_dataset_job(path, ("summaries",))
            except StoreError as exc:
                send({"kind": "cache_warning", "message": f"Disk cache can't be updated: {exc}"})
            prefs = store.read_prefs([path])[path]
            if prefs.failed:
                # Unknown whether the user chose not to cache it: load from the files, without the cache.
                send({"kind": "cache_warning", "message": f"Disk cache not used: the folder's settings couldn't be "
                                                         f"read ({prefs.error})"})
            chosen = no_cache or bool(prefs.value and prefs.value.get("no_cache"))
            if prefs.failed and not chosen:
                no_cache_reason = "Disk cache not used: the folder's settings couldn't be read"
            no_cache = chosen or prefs.failed
        _load(path, output, send, store, guard, bool(cache_options), memory, base_signature, expected,
              (cache_options or {}).get("budget"), (cache_options or {}).get("budget_set_at"),
              limits=limits, allow_large=allow_large, no_cache=no_cache, no_cache_reason=no_cache_reason,
              full_check=full_check, cache_base=cache_base, check_level=check_level,
              allow_missing=allow_missing)
    finally:
        if store is not None:
            store.close()


def _load(path: str, output: str, send: Emit, store: CacheStore | None, guard: SaveGuard | None, cache_on: bool,
          memory: list[list[int]] | None, base_signature: str, expected: str, budget: int | None,
          budget_set_at: float | None = None, *, limits: dict[str, Any] | None = None,
          allow_large: bool = False, no_cache: bool = False, no_cache_reason: str = "",
          full_check: bool = False, cache_base: bool = False, check_level: str = DEFAULT_CHECK_LEVEL,
          allow_missing: bool = False) -> None:
    from helab.utils.cache_store import StoreError
    held_from = "memory"  # Where the shots counted as held are: the caller's RAM, or its cached read.
    if cache_base and not memory and not no_cache and store is not None:
        # The caller reads the cached dataset itself, beside this check: count its shots as held.
        cached_row = store.read_dataset_row(path).value
        if cached_row is not None:
            memory = [list(entry) for entry in _saved_fingerprint(cached_row)]
            base_signature = _cached_signature(cached_row)
            held_from = "the disk cache"
    if (not no_cache and not full_check and base_signature and store is not None and memory and expected in ("", base_signature)
            and _unchanged_since_cache(path, send, store, base_signature, memory, check_level)):
        return
    # These imports are deliberately local: scanning does not initialize numpy,
    # pandas, any HeLab caches, or a QApplication.
    import numpy as np
    import pandas as pd

    files: list[tuple[int, str]] = []
    found: dict[str, set[int]] = {}
    has_dirs = False
    # Files added after this listing are not in the dataset; freshness compares against it.
    listed_at = time.time()
    beat = Heartbeat(send, "listing")
    with os.scandir(path) as directory:
        for entry in directory:
            beat()
            if matched := file_kinds.match(entry.name):
                kind, shot = matched
                found.setdefault(kind.name, set()).add(shot)
                if kind.loaded:
                    files.append((shot, entry.path))
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
    txy_bytes = sum(size for _, size, _ in fingerprint)
    # Files another computer may still be writing are left out entirely (not in
    # the fingerprint), so the next load sees them as new and reads them whole.
    young = {item[0] for item in fingerprint} - {item[0] for item in _settled(fingerprint)}
    if young:
        files = [item for item in files if item[0] not in young]
        fingerprint = [item for item in fingerprint if item[0] not in young]
        if not files:
            raise ValueError("TXY files are still being written — Retry")
    # This listing and fingerprint are a complete status check of this folder, so
    # browsing skips its details scan (step 2) while this load runs, unless the
    # folder has subfolders (their dates come from step 2). Sent and saved before any
    # file is read; a basic scan's success is still needed to clear a failure.
    summary = _summary(path, found, {file_kinds.TXY.name: txy_bytes}, has_dirs, False, fingerprint, listed_at)
    summary["unsettled"] = len(young)
    send({"kind": "scan_summary", "status": summary})
    current = {shot: (size, modified) for shot, size, modified in fingerprint}
    in_memory = {int(shot) for shot, size, modified in memory or ()
                 if current.get(int(shot)) == (size, modified)}
    if guard is not None and store is not None:
        _save_summary(store, path, summary, guard, send)
    # What this load would add to RAM: shots the caller doesn't hold already.
    if _too_large(large_folder.estimate(fingerprint, in_memory), limits, allow_large, send):
        return
    data: dict[int, Any] = {}
    cached = False
    cache_reason = "Disk cache unavailable" if store is None else "No saved cache fingerprint"
    problematic: list[int] = []
    reused: set[int] = set()
    baseline: dict[int, tuple[int, int]] = {}
    cache_info: dict[str, Any] = {}
    # None: the cache couldn't be opened or read, so whether it holds this folder is unknown.
    had_dataset: bool | None = None if cache_on and store is None else False
    # TXY files are written once: shots cached (or held in RAM) that the folder no longer has mean
    # another folder now sits at this path, or files were deleted. Stop before reading anything,
    # or unpacking the cache; the user decides (``allow_missing``: load the folder as it is now).
    listed = found.get(file_kinds.TXY.name, set())
    held = {int(entry[0]) for entry in memory or ()}
    missing_checked = False

    def stop_if_missing(known: set[int]) -> bool:
        missing = sorted(known - listed)
        if not missing or allow_missing:
            return False
        send({"kind": "shots_missing", "missing": missing[:20], "missing_count": len(missing),
              "known_count": len(known), "listed_count": len(listed)})
        return True

    if no_cache:
        # Not cached: the user's choice. Its cached data (if any) is neither read nor written.
        cache_reason, had_dataset = no_cache_reason or NOT_CACHED_REASON, None
    elif store is not None:
        from helab.utils.cache_store import unpack_dataset
        try:
            row_read = store.read_dataset_row(path)
            if row_read.failed:
                raise StoreError(row_read.error)
            row = row_read.value
            missing_checked = True
            if stop_if_missing(held | ({int(entry[0]) for entry in row["fingerprint"]} if row is not None else set())):
                return
            packed: bytes | None = None
            if row is not None and not (_saved_fingerprint(row) == fingerprint and in_memory >= set(current)):
                # The dataset itself is needed: read it with its row, which may have changed meanwhile.
                full = store.read_dataset(path)
                if full.failed:
                    raise StoreError(full.error)
                row, packed = full.value if full.value is not None else (None, None)
            had_dataset = row is not None
            saved_fingerprint = _saved_fingerprint(row) if row is not None else None
            previous = [value for value in row["problematic"] if isinstance(value, int)] if row is not None else []
            cache_info = _with_sizes(_cache_info(row["info"]), row) if row is not None else {}
            if saved_fingerprint is not None:
                baseline = {shot: (size, modified) for shot, size, modified in saved_fingerprint}

            # Unpacking brings the whole cached dataset into RAM, more than the folder now holds if
            # it shrank: when that is too large, the cache isn't used and the files are read.
            too_big = packed is not None and row is not None and bool(large_folder.verdict(
                large_folder.estimate(_saved_fingerprint(row)), limits, allow_large))

            def unpack() -> dict[int, Any] | None:
                return unpack_dataset(packed) if packed is not None and not too_big else None

            if saved_fingerprint == fingerprint and packed is None:
                # The caller already holds every shot: no need to decompress the cache.
                cached, problematic = True, previous
            elif saved_fingerprint == fingerprint:
                cache_reason = "Cached dataset invalid"
                unpacked = unpack()
                if unpacked is not None:
                    data, cached, problematic = unpacked, True, previous
                    reused = set(data)
            elif saved_fingerprint is not None:
                cache_reason = "TXY files changed since caching"
                # Keep shots whose converted file is unchanged; only new or
                # modified TXY files are read and merged into the dataset.
                data = {shot: array for shot, array in (unpack() or {}).items()
                        if shot in current and baseline.get(shot) == current[shot]}
                reused = set(data)
                problematic = [shot for shot in previous if shot in reused]
            if too_big:
                cache_reason = "Cached dataset too large to reuse"
        except Exception as exc:
            # A cache miss/failure must not prevent loading the actual files.
            data, cached, reused, problematic = {}, False, set(), []
            if isinstance(exc, StoreError):
                had_dataset = None
            cache_reason = f"Cache read failed: {type(exc).__name__}: {exc}"
            send({"kind": "cache_warning", "message": cache_reason})
    if not missing_checked and stop_if_missing(held):
        return
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
        parts = [f"{len(in_memory)} shots from {held_from}"] if in_memory else []
        parts += [f"{len(from_disk)} shots from disk cache"] if from_disk else []
        cache_reason = f"Reused {', '.join(parts)}; read {read} new or changed TXY files"
    elif cached:
        cache_reason = ""
    source = "updated" if in_memory else "disk" if cached else "merged" if reused else "files"
    send({"kind": "load_source", "source": source, "cache_reason": cache_reason})
    # Bytes of the TXY files this load reads; the caller's time estimate uses only these.
    total_read_bytes = 0 if cached else sum(
        file_size for shot, file_size, _ in fingerprint if shot not in in_memory | reused)
    read_bytes = 0
    send({"kind": "progress", "progress": len(young) / (len(files) + len(young)),
          "checked_files": len(young), "loaded_files": 0,
          "total_files": len(files) + len(young), "failed_files": 0, "unsettled_files": len(young),
          "read_bytes": 0, "read_files": 0, "total_read_bytes": total_read_bytes})
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
                read_bytes += fingerprint[i][1]
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
                  "failed_files": i + 1 - loaded - len(late),
                  "read_bytes": read_bytes, "read_files": load_counts["read"],
                  "total_read_bytes": total_read_bytes})
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
        raise ValueError("Folder changed while loading — Retry")
    send({"kind": "loaded", "rows": rows, "bytes": size, "files": loaded,
          "loaded_at": time.time(),
          "total_files": len(files) + len(young), "failed_files": len(files) - loaded - len(late),
          "unsettled_files": unsettled,
          "problematic": sorted(set(problematic)),
          "source": source, "cached": cached, **_data_root(store, path),
          # Left out when the cache couldn't be read: unknown, not "not cached".
          **({} if had_dataset is None and not cached else {"disk_cached": cached or bool(had_dataset)}),
          "disk_cache_pending": guard is not None and not cached and not no_cache,
          "cache_info": cache_info, "load_counts": load_counts,
          "cache_reason": cache_reason,
          "fingerprint": fingerprint, "memory_shots": sorted(in_memory), "base_signature": base_signature,
          "signature": hashlib.sha256(json.dumps(fingerprint).encode()).hexdigest()})
    if store is not None and (cached or reused):
        _touch(store, path)
    names = [os.path.basename(filename) for _, filename in files]
    if cached and not young and store is not None and guard is not None and not no_cache:
        # This listing found the cache complete: it dates from now (a later non-TXY change no longer
        # rules out the quick check), and older caches get their file names for its samples.
        from helab.utils.cache_store import SaveRejected
        try:
            store.confirm_dataset(path, fingerprint, names, listed_at, guard)
        except (StoreError, SaveRejected):
            pass  # Best effort: the next full check tries again.
    if store is None or guard is None or cached or no_cache:
        return
    # The caller already has its data; updating the disk cache no longer
    # delays it. Shots only the caller holds are read again for completeness.
    try:
        from helab.utils.cache_store import DATASET_FORMAT, pack_dataset
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
        file = store.write_dataset_file(pack_dataset(data))
        info = {"saved_at": time.time(), "snapshot_at": listed_at, "signature": hashlib.sha256(
            json.dumps(fingerprint).encode()).hexdigest(), "action": "updated" if had_dataset else "created",
            "counts": load_counts, "unsettled": unsettled, "kind": file_kinds.TXY.name, "format": DATASET_FORMAT,
            # Its TXY files' names, in fingerprint order, for the quick check's samples.
            "names": names,
            # For the large-folder check before a later cached read.
            "txy_bytes": large_folder.estimate(fingerprint),
            "ram_bytes": sum(int(array.nbytes) for array in data.values()),
            "disk_bytes": os.path.getsize(os.path.join(store.datasets_dir, file))}
        result = store.save_dataset(path, file, {
            "ram_bytes": sum(int(array.nbytes) for array in data.values()),
            "rows": sum(len(array) for array in data.values()), "shots": len(data),
            "fingerprint": [list(entry) for entry in fingerprint], "problematic": sorted(set(problematic)),
            "info": info}, guard, budget=budget, budget_set_at=budget_set_at)
        if not result.saved:
            # Held for the user's answer (Make room / Save update); nothing waits for it.
            send(_pending_event(store, path, result))
            return
        # The replaced file was retired: the next cleanup deadline may be new.
        send({"kind": "cache_saved", "cache_info": info, "superseded": list(result.superseded), "job_seq": result.job_seq,
              "next_deadline": _deadline(store),
              "usage": result.usage, "usage_seq": [store.store_id, result.usage_seq]})
        send({"kind": "disk_cached", "disk_cached": True})
    except Exception as exc:
        # A rejected save retired its file: the next cleanup deadline may be new.
        send({"kind": "cache_save_failed", "message": str(exc), "next_deadline": _deadline(store)})
        send({"kind": "cache_warning", "message": str(exc)})


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


NOT_CACHED_REASON = "Not cached: your choice"


def _too_large(estimate: int, limits: dict[str, Any] | None, allow_large: bool, send: Emit) -> bool:
    """Stop before reading: the data would take ``estimate`` bytes of RAM, which needs the
    user's yes (``large``) or is never loaded (``refused``)."""
    verdict = large_folder.verdict(estimate, limits, allow_large)
    if verdict:
        send({"kind": "too_large", "estimate": estimate, "refused": verdict == "refused"})
    return bool(verdict)


def _with_sizes(info: dict[str, Any], row: Any) -> dict[str, Any]:
    """A dataset's ``info`` with its TXY files' size and its size in RAM, for the large-folder check."""
    if not info:
        return info
    sizes = {"txy_bytes": large_folder.estimate(_saved_fingerprint(row)), "ram_bytes": int(row["ram_bytes"]),
             "disk_bytes": int(row["bytes"])}
    return {**info, **sizes}


def _pending_event(store: CacheStore, path: str, result: Any) -> dict[str, Any]:
    """``cache_full`` (doesn't fit) or ``cache_approval`` (grows the cache over 80%) for a pending save."""
    from dataclasses import asdict
    event: dict[str, Any] = {
        "kind": "cache_full" if result.reason == "over_budget" else "cache_approval",
        "pending_id": result.pending_id, "path": path, "reason": result.reason, "bytes": result.bytes,
        "usage": result.usage, "usage_seq": [store.store_id, result.usage_seq], "created_at": time.time(),
        "budget": result.budget, "job_seq": result.job_seq,
        "replaces": result.replaces, "superseded": list(result.superseded), "next_deadline": _deadline(store)}
    if result.reason == "over_budget" and result.budget is not None:
        from helab.utils.cache_store import SaveRejected, StoreError
        try:
            event["room"] = asdict(store.room_plan(result.pending_id, result.budget))
        except (SaveRejected, StoreError):
            pass  # Answered or expired meanwhile; the dialog asks again.
    return event


def _deadline(store: CacheStore) -> float | None:
    from helab.utils.cache_store import StoreError
    try:
        return store.next_deadline()
    except StoreError:
        return None


def _usage(store: CacheStore) -> dict[str, Any]:
    """The store's live usage and when it was measured, for the app's 80% pause; {} if unreadable."""
    from helab.utils.cache_store import StoreError
    try:
        return store.measure_usage().event()
    except StoreError:
        return {}


def _removed_event(removal: Any) -> dict[str, Any]:
    """What a removal did, for ``FolderCache.removed``; ``paths`` None means every path of those kinds."""
    return {"kind": "removed", "kinds": list(removal.kinds),
            "paths": None if removal.paths is None else list(removal.paths),
            "datasets": removal.datasets, "bytes": removal.dataset_bytes}


ADMIN_ACTIONS = ("inventory", "clear", "purge", "trim", "adopt", "discard", "sweep", "budget", "prefs", "clear_prefs",
                 "forget_root", "root_same", "clear_root")


def _marker_temporary(name: str) -> bool:
    """A marker being replaced (``reassign_root``'s temporary file, left by a crash): not data."""
    return name.startswith(".helab-root.") and name.endswith(".tmp")


def _marker_hint(folder: str) -> dict[str, Any] | None:
    """A marker file's size, modified time and file number: hints whether two locations are one
    folder. (The device number differs for every mount, even of one share, so it is left out.)"""
    from helab.utils.data_roots import MARKER_NAME
    try:
        found = os.lstat(os.path.join(folder, MARKER_NAME))
    except OSError:
        return None
    return {"size": found.st_size, "mtime": found.st_mtime, "ino": found.st_ino}


def reassign_root(path: str, cache_options: dict[str, Any], old_uuid: str, keep: str, send: Emit = emit) -> None:
    """It's a copy… (D4): give the folder at ``path`` a new ``.helab-root`` (replacing the file in
    one step), so it no longer shares cached data with ``old_uuid``'s other locations. ``keep`` is
    the location that keeps the data: when it is the pending one, it is confirmed and the folder at
    ``path`` (with all its confirmed aliases) moves; otherwise only ``path``'s location moves.

    Without write permission nothing changes and ``root_manual`` hands out the new contents.
    """
    import uuid as uuids
    from helab.utils.data_roots import MARKER_NAME, new_marker, read_marker
    current = read_marker(path)
    if current.uuid != old_uuid:
        raise ValueError(f"The {MARKER_NAME} in {path} changed since HeLab found it. "
                         "Retry / Refresh the folder, then answer again.")
    marker, contents = new_marker(path)
    file = os.path.join(path, MARKER_NAME)
    temporary = os.path.join(path, f"{MARKER_NAME}.{uuids.uuid4().hex}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, file)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.remove(temporary)
        send({"kind": "root_manual", "path": path, "name": MARKER_NAME,
              "contents": contents.decode("utf-8"), "reason": str(exc), "replace": True})
        return
    _hide(file)
    with _cache_store(cache_options["directory"], [path], allow_unrooted=True) as store:
        location = store._location_key(path)
        keep_pending = store.root_at(keep)
        keep_path = _location_path(store, keep)
        if keep_pending is not None and keep_pending[2] == "pending":
            moved = store.reassign_roots(old_uuid, marker.uuid, marker.label, keep=keep)
            store.confirm_root(keep, old_uuid)
            if keep_path:
                send({"kind": "root_found", "path": keep_path, "location": keep, "uuid": old_uuid,
                      "label": keep_pending[1]})
        else:
            moved = store.reassign_roots(old_uuid, marker.uuid, marker.label, only=location)
        for moved_location in moved:
            if moved_path := _location_path(store, moved_location):
                send({"kind": "root_changed", "path": moved_path, "location": moved_location,
                      "uuid": marker.uuid, "label": marker.label})
    send({"kind": "root_reassigned", "path": path, "uuid": marker.uuid, "label": marker.label,
          "old_uuid": old_uuid, "moved": moved, "kept": keep_path})


def _location_path(store: CacheStore, location: str) -> str:
    """The folder of a root location on this computer now, or "" if it isn't mounted."""
    try:
        path = store._location_source(location)
    except (OSError, ValueError):
        return ""
    return "" if path.startswith(("smb://", "vol://")) else path


def _root_rows(store: CacheStore, send: Emit) -> list[dict[str, Any]] | None:
    """The roots table, each location with its folder now ("" if not mounted); None if unreadable."""
    from helab.utils.cache_store import StoreError
    try:
        rows = store.root_rows()
    except StoreError as exc:
        send({"kind": "cache_warning", "message": str(exc)})
        return None
    try:
        usage = store.root_usage()
    except StoreError as exc:
        send({"kind": "cache_warning", "message": str(exc)})
        usage = {}
    for row in rows:
        row["path"] = _location_path(store, row["location"])
        if row["uuid"] in usage:
            row["cached"] = usage[row["uuid"]]
    return rows


def create_root(path: str, cache_options: dict[str, Any] | None, send: Emit = emit) -> None:
    """Right-click › Enable disk cache here…: write the folder's ``.helab-root`` (exclusive create,
    hidden on Windows, read back), or adopt the one already there, and record it as a listing would.

    Without write permission nothing is left behind and ``root_manual`` hands the app the exact
    file name and contents to place by hand.
    """
    from helab.utils.data_roots import MARKER_NAME, new_marker, read_marker
    marker, contents = new_marker(path)
    file = os.path.join(path, MARKER_NAME)
    created = False
    try:
        descriptor = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
    except FileExistsError:
        pass  # Another PC (or an earlier click) was first: adopt it.
    except OSError as exc:
        send({"kind": "root_manual", "path": path, "name": MARKER_NAME,
              "contents": contents.decode("utf-8"), "reason": str(exc)})
        return
    else:
        created = True
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(contents)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            with contextlib.suppress(OSError):
                os.remove(file)  # Never leave a partial marker.
            send({"kind": "root_manual", "path": path, "name": MARKER_NAME,
                  "contents": contents.decode("utf-8"), "reason": str(exc)})
            return
        _hide(file)
    try:
        found = read_marker(path)
    except ValueError as exc:  # Never overwritten: the user decides what it should be.
        raise ValueError(f"A {MARKER_NAME} already exists here but can't be used: {exc}. "
                         "Fix or remove it, then try again.") from None
    _discover_root(path, True, cache_options, send)
    send({"kind": "root_created" if created and found.uuid == marker.uuid else "root_adopted",
          "path": path, "uuid": found.uuid, "label": found.label})


def remove_root(path: str, cache_options: dict[str, Any], expected: str, location: str = "",
                send: Emit = emit) -> None:
    """Settings › Data roots › Delete .helab-root…: delete the folder's marker, only when it is still
    the regular file holding ``expected`` (never an invalid or replaced one), then forget its
    location, and those below it with the same UUID, in the roots table. Cached data stays, keyed
    by the UUID. Without permission the file stays and ``root_remove_refused`` names it."""
    import stat
    from helab.utils.data_roots import MARKER_NAME, read_marker
    file = os.path.join(path, MARKER_NAME)
    try:
        found = os.lstat(file)
    except FileNotFoundError:
        raise ValueError(f"There is no {MARKER_NAME} in {path} now. Refresh the list.") from None
    if not stat.S_ISREG(found.st_mode):
        raise ValueError(f"{file} isn't a file: HeLab leaves it alone.")
    try:
        marker = read_marker(path)
    except ValueError as exc:
        raise ValueError(f"{file} can't be read as a .helab-root ({exc}): HeLab never deletes it.") from None
    if marker.uuid != expected:
        raise ValueError(f"The {MARKER_NAME} in {path} changed since HeLab found it. Refresh the list.")
    try:
        if sys.platform == "win32" and not found.st_mode & stat.S_IWRITE:
            os.chmod(file, stat.S_IWRITE)  # Read-only blocks deleting on Windows (hidden doesn't).
        os.remove(file)
    except OSError as exc:
        send({"kind": "root_remove_refused", "path": path, "file": file, "reason": exc.strerror or str(exc)})
        return
    with _cache_store(cache_options["directory"], [path], allow_unrooted=True) as store:
        here = store._location_key(path)
        forgotten = store.forget_root_tree([top for top in (location, here) if top], expected)
        for gone in forgotten:
            if gone_path := _location_path(store, gone):
                send({"kind": "root_changed", "path": gone_path, "location": gone, "reason": "removed"})
    send({"kind": "root_removed", "path": path, "uuid": expected, "forgotten": forgotten})


def _hide(file: str) -> None:
    """Hidden: the dot prefix, plus the Windows hidden attribute. From macOS, UF_HIDDEN, which
    smbfs maps to that attribute on a share (best effort: lab PCs browse those shares)."""
    if sys.platform == "darwin":
        import stat
        with contextlib.suppress(OSError, AttributeError):
            os.chflags(file, os.stat(file).st_flags | stat.UF_HIDDEN)
        return
    if sys.platform != "win32":
        return
    import ctypes
    kernel32 = getattr(ctypes, "windll").kernel32
    attributes = kernel32.GetFileAttributesW(file)
    if attributes != -1 and attributes != 0xFFFFFFFF:
        kernel32.SetFileAttributesW(file, attributes | 0x2)  # FILE_ATTRIBUTE_HIDDEN


def cache_admin(cache_options: dict[str, Any], action: str, send: Emit = emit, **params: Any) -> None:
    """Disk cache maintenance on the local lane; never touches source folders.

    Every removal sends ``removed`` (kinds and paths), and every action ends with
    ``admin_result`` carrying the store's next cleanup deadline. ``sweep`` also
    deletes the old diskcache folders (at startup).
    """
    from dataclasses import asdict
    from helab.utils.cache_store import (
        KINDS, CacheStore, SaveRejected, StoreError, StoreReadOnly, remove_old_caches,
    )
    if action not in ADMIN_ACTIONS:
        raise ValueError(f"Unknown cache action: {action}")
    root = cache_options["directory"]
    budget = params.get("budget", cache_options.get("budget"))
    # When the app set it: a budget set later (e.g. lowered while this job waited) wins.
    budget_set_at = params.get("budget_set_at", cache_options.get("budget_set_at"))
    result: dict[str, Any] = {}
    old: list[str] = []
    if action == "sweep":
        old = remove_old_caches(os.path.dirname(os.path.abspath(root)), Heartbeat(send, "cleaning up"))
    with _cache_store(root, local_lane=True) as store:
        if (budget is not None and budget_set_at is not None and not store.read_only
                and action not in ("trim", "budget")):
            # Every job tells the store the app's budget, so running loads save within it.
            # (A trim or a budget job records it in its own transaction.)
            with contextlib.suppress(StoreError):
                budget = store.record_budget(int(budget), float(budget_set_at))
        if action == "inventory":
            inventory = store.inventory(budget)
            if budget is not None and not store.read_only:
                # What Make room would remove, as the save's own event said before a restart.
                for entry in inventory["pending"]:
                    if entry["reason"] == "over_budget":
                        with contextlib.suppress(SaveRejected, StoreError):
                            entry["room"] = asdict(store.room_plan(entry["pending_id"], int(budget)))
            inventory["roots"] = _root_rows(store, send)
            send({"kind": "inventory", "inventory": inventory})
        elif action == "sweep":
            try:
                swept = store.sweep()
            except StoreReadOnly:
                send({"kind": "swept", "old_caches": old, "deleted_files": 0, "expired_pending": 0,
                      "next_deadline": None, "read_only": True})
                return
            send({"kind": "swept", "old_caches": old, "deleted_files": swept.deleted_files,
                  "expired_pending": swept.expired_pending, "expired_ids": swept.expired_ids,
                  "still_open": len(swept.still_open), "next_deadline": swept.next_deadline, **_usage(store)})
            return
        elif action == "clear":
            kinds = tuple(params.get("kinds") or KINDS)
            unknown = set(kinds) - set(KINDS)
            if unknown:
                raise ValueError(f"Unknown cache kinds: {sorted(unknown)}")
            send(_removed_event(store.remove(kinds)))
        elif action == "purge":
            cutoff = float(params["cutoff"])
            if params["what"] == "datasets":
                removals = [store.purge_datasets(cutoff)]
            elif params["what"] == "records":
                removals = store.purge_records(cutoff, bool(params.get("include_failures")))
            else:
                raise ValueError(f"Unknown purge: {params['what']}")
            for removal in removals:
                send(_removed_event(removal))
            result["removed"] = {kind: len(removal.paths or ()) for removal in removals for kind in removal.kinds}
            result["bytes"] = sum(removal.dataset_bytes for removal in removals)
        elif action == "trim":
            removal = store.trim(int(budget or params["budget"]), budget_set_at)
            send(_removed_event(removal))
            result.update(datasets=removal.datasets, bytes=removal.dataset_bytes)
        elif action == "adopt":
            try:
                adopted = store.adopt_pending(params["pending_id"], budget=budget, budget_set_at=budget_set_at,
                                              expected_room=params.get("room_paths"),
                                              make_room=bool(params.get("make_room")))
            except SaveRejected as rejection:
                result.update(adopted=False, rejected=rejection.reason, message=str(rejection))
            else:
                if adopted.removal is not None:
                    send(_removed_event(adopted.removal))
                result.update(adopted=adopted.adopted, path=adopted.path, bytes=adopted.bytes,
                              room=None if adopted.room is None else asdict(adopted.room))
                if adopted.adopted:
                    row = store.read_dataset_row(adopted.path)
                    result["cache_info"] = _cache_info(row.value["info"]) if row.value is not None else {}
        elif action == "discard":
            result["discarded"] = store.discard_pending(params["pending_id"])
        elif action == "prefs":
            # The user's flags for one folder; with ``remove_cached``, its cached data goes too
            # (ticking "Don't cache this folder" and saying yes).
            path = str(params["path"])
            saved, flag_removal = store.set_prefs_removing(
                path, bool(params.get("no_cache")), bool(params.get("no_auto_load")),
                float(params.get("set_at") or time.time()), remove_cached=bool(params.get("remove_cached")))
            send({"kind": "folder_prefs", "path": path, "prefs": saved})
            if flag_removal is not None:
                send(_removed_event(flag_removal))
        elif action == "clear_prefs":
            cleared_at = time.time()
            send({"kind": "prefs_cleared", "paths": store.clear_prefs(cleared_at), "set_at": cleared_at})
        elif action == "forget_root":
            # Only where a marker was seen: data stays with its root, and the marker in place.
            # A folder there is RAM-only until a listing finds its marker again.
            location = str(params["location"])
            path = _location_path(store, location)
            store.forget_root(location)
            result["forgotten"] = location
            if path:
                send({"kind": "root_changed", "path": path, "location": location, "reason": "forgotten"})
        elif action == "clear_root":
            # Everything cached below one data root on this computer; roots, flags and marker stay.
            send(_removed_event(store.clear_root(str(params["uuid"]))))
        elif action == "root_same":
            # Same folder (D4): the pending location uses the root's cached data from now on.
            location, identifier = str(params["location"]), str(params["uuid"])
            result["confirmed"] = store.confirm_root(location, identifier)
            if result["confirmed"]:
                found = store.root_at(location)
                send({"kind": "root_confirmed", "location": location, "uuid": identifier,
                      "path": _location_path(store, location), "label": found[1] if found else ""})
        elif action == "budget":
            if budget is not None and budget_set_at is not None:
                # Lowering it (``fit``): not recorded if the data cached by now doesn't fit.
                active = store.lower_budget(int(budget), float(budget_set_at), fit=bool(params.get("fit")))
                result.update(budget=active if active is not None else budget, recorded=active is not None)
        send({"kind": "admin_result", "action": action, **result, "next_deadline": _deadline(store),
              **_usage(store)})


def cache_move_job(move: dict[str, Any], send: Emit = emit) -> None:
    """A step of moving the cache folder (roadmap S9; the app holds every other cache user):
    ``check`` the target, ``move`` (record, rename or checkpoint+copy+verify), ``cleanup`` the
    old folder after the cutover, ``abort`` a move before it, or ``recover`` one a crash
    interrupted (at startup). Every step but ``check`` holds ``move.lock`` while it runs, so a
    HeLab starting meanwhile waits for it even if the HeLab that started it has ended."""
    from helab.utils import cache_move as mover
    from helab.utils.cache_locks import cache_lock, held_with, move_lock
    action, app_dir = move["action"], move["app_dir"]
    if action == "check":
        send({"kind": "move_check", **mover.check_target(move["from"], move["to"], app_dir)})
        return
    lock = move_lock(app_dir)
    if not lock.try_lock():
        raise ValueError("Another cache move step is still running")
    try:
        # Only while the HeLab that asked still holds the cache (its token in cache.lock): a
        # helper that outlived it must not touch anything a new HeLab is now using.
        if not held_with(cache_lock(app_dir).path, str(move.get("token", ""))):
            raise ValueError("The HeLab that asked for this cache move step is no longer moving the cache")
        _cache_move_step(mover, action, app_dir, move, send)
    finally:
        lock.unlock()


def _cache_move_step(mover: Any, action: str, app_dir: str, move: dict[str, Any], send: Emit) -> None:
    def ours(record: dict[str, Any] | None) -> bool:
        # Only this move's record: a later move's is never touched.
        return record is not None and record.get("id") == move.get("id")
    if action == "move":
        record = mover.start(move["from"], move["to"], app_dir, move["method"], move.get("id", ""))
        last = [0.0]

        def progress(done: int, total: int) -> None:
            now = time.monotonic()
            if now - last[0] >= 0.2 or done == total:
                last[0] = now
                send({"kind": "move_progress", "done": done, "total": total})
        try:
            record = mover.move(record, app_dir, progress, lambda: False)
        except (mover.MoveError, mover.MoveCancelled, OSError) as exc:
            # Before the cutover: the source is intact (a rename is renamed back); a copy is discarded.
            saved = mover.read_record(app_dir) or record
            left = mover.abort(app_dir, saved)
            message = str(exc) if isinstance(exc, mover.MoveError) else f"The move failed: {exc}"
            # Where the store is now: the source, unless undoing a rename failed.
            send({"kind": "move_failed", "message": message, "left": left, "store_at": mover.store_at(saved)})
            return
        send({"kind": "move_done", "record": record})
    elif action == "cleanup":
        saved = mover.read_record(app_dir)
        left = mover.cleanup(app_dir, saved) if saved is not None and ours(saved) else []
        send({"kind": "move_cleaned", "left": left})
    elif action == "abort":
        saved = mover.read_record(app_dir)
        left = mover.abort(app_dir, saved, before_cutover=bool(move.get("before_cutover"))) if (
            saved is not None and ours(saved)) else []
        # Where the store is now: the source, unless undoing a rename failed.
        send({"kind": "move_aborted", "left": left,
              "store_at": mover.store_at(saved) if saved is not None and ours(saved) else ""})
    elif action == "recover":
        from helab.utils.cache_setting import open_settings, write_cache_setting
        settings = open_settings(move["settings"])
        unsaved: list[str] = []

        def write(path: str) -> bool:
            if write_cache_setting(settings, path):
                return True
            unsaved.append(path)  # The attempted value may linger in memory here, never on disk.
            return False
        message = mover.recover(app_dir, lambda: str(settings.value("dir_caches", "", type=str)), write)
        # Usable only if the setting HeLab will read names the store: never after a failed write.
        usable = not unsaved and mover.usable_after_recovery(app_dir, str(settings.value("dir_caches", "", type=str)))
        send({"kind": "move_recovered", "message": message, "usable": usable})
    else:
        raise ValueError(f"Unknown cache move action: {action}")


# Operations that need the disk cache on.
CACHE_ONLY = ("cached", "invalidate", "subtree_save", "scan_history", "cache_admin", "volumes_verify",
              "root_reassign", "root_remove")


def main() -> None:
    try:
        request = json.loads(sys.stdin.readline())
        operation = request["operation"]
        Pause.configure(request.get("control"))
        if operation in CACHE_ONLY and not request.get("cache"):
            raise ValueError("The disk cache is off for this session")
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
            list_folder(request["path"], cache_options=request.get("cache"))
        elif operation == "icons":
            folder_icons(request["paths"])
        elif operation in ("scan", "details"):
            scan(request["path"], cache_options=request.get("cache"), manual=request.get("scan_manual", False),
                 automatic=request.get("automatic", False),
                 operation_id=request.get("scan_operation_id", ""), revision=request.get("scan_revision", 0))
        elif operation == "scan_history":
            save_scan_history(request["cache"], request["path"], request["outcome"], request.get("guard"),
                              verified_volumes=request.get("verified_volumes"))
        elif operation == "subtree_save":
            save_subtrees(request["cache"], request["records"],
                          verified_volumes=request.get("verified_volumes"))
        elif operation == "load":
            load(request["path"], request["output"], cache_options=request.get("cache"),
                 memory=request.get("memory"), base_signature=request.get("base_signature", ""),
                 expected=request.get("signature", ""), limits=request.get("limits"),
                 allow_large=bool(request.get("allow_large")), no_cache=bool(request.get("no_cache")),
                 full_check=bool(request.get("full_check")), cache_base=bool(request.get("cache_base")),
                 check_level=str(request.get("check_level") or DEFAULT_CHECK_LEVEL),
                 allow_missing=bool(request.get("allow_missing")))
        elif operation == "cached":
            read_cached(request["path"], request["output"], cache_options=request.get("cache"),
                        limits=request.get("limits"), allow_large=bool(request.get("allow_large")),
                        verified_volumes=request.get("verified_volumes"))
        elif operation == "invalidate":
            with _cache_store(request["cache"]["directory"], [request["path"]], local_lane=True) as store:
                # Bumps the folder's epoch: a load started before cannot save it back.
                emit(_removed_event(store.remove(("datasets",), [request["path"]])))
                emit({"kind": "admin_result", "action": "invalidate", "next_deadline": _deadline(store),
                      **_usage(store)})
        elif operation == "cache_move":
            cache_move_job(request["move"])
        elif operation == "cache_admin":
            cache_admin(request["cache"], request["action"], **request.get("params", {}))
        elif operation == "roots_verify":
            verify_known_roots(request["cache"])
        elif operation == "volumes_verify":
            verify_volumes(request["cache"])
        elif operation == "root_create":
            create_root(request["path"], request.get("cache"))
        elif operation == "root_reassign":
            reassign_root(request["path"], request["cache"], request["old_uuid"], request["keep"])
        elif operation == "root_remove":
            remove_root(request["path"], request["cache"], request["uuid"], request.get("location", ""))
        else:
            raise ValueError(f"Unknown operation: {operation}")
        emit({"kind": "done"})
    except Exception as exc:
        from helab.utils.data_roots import VolumeUnverified
        emit({"kind": "error", "message": str(exc), **({"unverified": True}
                                                        if isinstance(exc, VolumeUnverified) else {})})


if __name__ == "__main__":
    main()
