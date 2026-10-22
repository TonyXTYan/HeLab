"""Data roots: discovering, verifying, placing, reassigning and removing ``.helab-root`` markers."""
from __future__ import annotations

import contextlib
import os
import sqlite3
import sys
from typing import Any, Literal, TYPE_CHECKING

from helab.io_ops import infra, stores
from helab.io_ops.infra import (Emit, Heartbeat, _cached_volume_id, _isdir, _lstat, _mounts, _read_marker,
                                _stat, _trace, _traced_error, emit)

if TYPE_CHECKING:
    from helab.utils.cache_paths import Mount
    from helab.utils.cache_store import CacheStore
    from helab.utils.data_roots import LocalVolumes


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
    from helab.utils.data_roots import NoDataRoot
    try:
        with stores._cache_store(cache_options["directory"], [path], allow_unrooted=True) as store:
            location = store._location_key(path)
            old = store.root_at(location)
            if not present:
                if old is not None:
                    store.forget_root(location)
                    send({"kind": "root_changed", "path": path, "location": location,
                          "reason": "marker removed"})
                return old is not None
            try:
                marker = _read_marker(path, "root discovery")
            except OSError as exc:
                send({"kind": "cache_warning", "message": f"Cannot read {path}/.helab-root: {exc}"})
                return False
            except ValueError as exc:
                send({"kind": "cache_warning", "message": f"Invalid {path}/.helab-root: {exc}"})
                if old is not None:
                    # Gone like a removed marker: the app drops the root and what RAM holds under it.
                    store.forget_root(location)
                    send({"kind": "root_changed", "path": path, "location": location,
                          "reason": "marker invalid"})
                return old is not None
            duplicates = store.other_root_locations(marker.uuid, location)
            # Pending only while another location of this UUID is confirmed: one still waiting whose
            # other locations have all been forgotten since is confirmed.
            decision: Literal["confirmed", "pending"] = (
                "confirmed" if old is not None and old[0] == marker.uuid and old[2] == "confirmed"
                else "pending" if duplicates else "confirmed")
            old_key = ""
            if decision == "confirmed" and old is None:
                try:
                    old_key = store._path_key(path)
                except NoDataRoot:
                    pass
            new_key = f"root://{marker.uuid}"
            moved: list[str] = []
            # One transaction: a re-key that fails (a busy store, a table it can't read) leaves no
            # root record either, so the next listing finds the marker new again and retries it;
            # otherwise the rows below would stay under the outer root's key for good.
            with store.transaction():
                store.record_root(location, marker.uuid,
                                  "smb" if location.startswith("smb://") else "vol",
                                  marker.label, decision=decision)
                if old_key and old_key != new_key:
                    moved = store.rekey_subtree(old_key, new_key)
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
    except (StoreError, sqlite3.Error) as exc:
        # A write's own statement or commit failing is SQLite's error, not the store's.
        send({"kind": "cache_warning", "message": f"Data root could not be recorded: {exc}"})
        return False


def verify_volumes(cache_options: dict[str, Any], send: Emit = emit,
                   mounts: list[Mount] | None = None) -> LocalVolumes:
    """Refresh the saved volume IDs of mounts that have them, and send ``volumes_verified``:
    the mounts whose hints the local lane may trust now.

    Reads only mounted volumes' IDs (diskutil, GetVolumeInformationW), never source folders,
    so it runs on the local lane at startup and after a mount change (``volumes_verify``).
    """
    from helab.utils.cache_store import CacheStore
    from helab.utils.data_roots import current_local_volumes
    mounts = _mounts("volumes_verify") if mounts is None else mounts
    with CacheStore(cache_options["directory"], root_mode=True) as store:
        known_mounts = {(path, source) for path, source, _ in store.volume_locations()}
    local = current_local_volumes(mounts, paths=[mount.path for mount in mounts
                                                 if (mount.path, mount.source) in known_mounts],
                                  id_reader=_cached_volume_id)
    verified: list[list[str]] = []
    ids: list[list[str]] = []
    if local.volumes:
        with CacheStore(cache_options["directory"], root_mode=True) as store:
            known = {(path, source): identifier for path, source, identifier in store.volume_locations()}
            for mount, identifier in local.volumes:
                if known.get((mount.path, mount.source)) != identifier and not store.read_only:
                    store.record_volume(mount.path, mount.source, identifier)
                    known[(mount.path, mount.source)] = identifier
                if known.get((mount.path, mount.source)) == identifier:
                    verified.append([mount.path, mount.source])
                    ids.append([mount.path, mount.source, identifier])
    # ``ids``: for the marker check that follows (``verify_known_roots``), so it needn't ask again.
    send({"kind": "volumes_verified", "volumes": sorted(verified), "ids": sorted(ids)})
    return local


def verify_known_roots(cache_options: dict[str, Any], send: Emit = emit,
                       volume_ids: list[list[str]] | None = None) -> None:
    """Check remembered marker locations in a background source helper.

    Only the recorded marker folders are visited. Missing mounts are left alone;
    a mounted folder whose marker changed is reconciled like a listing.
    ``volume_ids`` ([path, device, ID]): the volume check just made (``volumes_verify``), used
    instead of checking the volumes again; local volumes it didn't check are left alone.
    """
    from helab.utils.cache_paths import CachePaths
    from helab.utils.cache_store import CacheStore
    from helab.utils.data_roots import MARKER_NAME, LocalVolumes
    mounts = _mounts("roots_verify")
    with CacheStore(cache_options["directory"], root_mode=True) as store:
        roots = store.root_locations()
    if volume_ids is None:
        local = verify_volumes(cache_options, send, mounts)
    else:
        checked = {(str(path), str(source)): str(identifier) for path, source, identifier in volume_ids}
        infra._volume_id_cache.update(checked)  # (So reconciling a root doesn't ask for its volume's ID.)
        local = LocalVolumes((mount, checked[(mount.path, mount.source)]) for mount in mounts
                             if (mount.path, mount.source) in checked)
    locations = CachePaths(mounts)
    beat = Heartbeat(send, "verifying data roots")
    for location, _, _ in roots:
        beat()
        source = (locations.source(location) if location.startswith("smb://")
                  else local.source(location))
        if source == location or not _isdir(source, "roots_verify: root folder"):
            continue
        try:
            _lstat(os.path.join(source, MARKER_NAME), "roots_verify: marker")
            present = True
        except FileNotFoundError:
            present = False
        except OSError:
            continue  # Unknown: the root is kept, as for a marker that can't be read.
        _discover_root(source, present, cache_options, send)
    send({"kind": "roots_verified", "mounts": sorted([[mount.path, mount.source] for mount in mounts])})


def _marker_temporary(name: str) -> bool:
    """A marker being replaced (``reassign_root``'s temporary file, left by a crash): not data."""
    return name.startswith(".helab-root.") and name.endswith(".tmp")


def _marker_hint(folder: str) -> dict[str, Any] | None:
    """A marker file's size, modified time and file number: hints whether two locations are one
    folder. (The device number differs for every mount, even of one share, so it is left out.)"""
    from helab.utils.data_roots import MARKER_NAME
    try:
        found = _lstat(os.path.join(folder, MARKER_NAME), "root duplicate: hint")
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
    from helab.utils.data_roots import MARKER_NAME, new_marker
    current = _read_marker(path, "root_reassign")
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
        _traced_error("marker_write", file, "root_reassign", exc)
        with contextlib.suppress(OSError):
            os.remove(temporary)
        send({"kind": "root_manual", "path": path, "name": MARKER_NAME,
              "contents": contents.decode("utf-8"), "reason": str(exc), "replace": True})
        return
    _trace("marker_write", file, "root_reassign", bytes=len(contents))
    _hide(file)
    with stores._cache_store(cache_options["directory"], [path], allow_unrooted=True) as store:
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
    from helab.utils.data_roots import MARKER_NAME, new_marker
    marker, contents = new_marker(path)
    file = os.path.join(path, MARKER_NAME)
    created = False
    try:
        descriptor = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
    except FileExistsError:
        # Another PC (or an earlier click) was first: adopt it.
        _trace("marker_write", file, "root_create", error="FileExistsError")
    except OSError as exc:
        _traced_error("marker_write", file, "root_create", exc)
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
        _trace("marker_write", file, "root_create", bytes=len(contents))
        _hide(file)
    try:
        found = _read_marker(path, "root_create")
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
    from helab.utils.data_roots import MARKER_NAME
    file = os.path.join(path, MARKER_NAME)
    try:
        found = _lstat(file, "root_remove")
    except FileNotFoundError:
        raise ValueError(f"There is no {MARKER_NAME} in {path} now. Refresh the list.") from None
    if not stat.S_ISREG(found.st_mode):
        raise ValueError(f"{file} isn't a file: HeLab leaves it alone.")
    try:
        marker = _read_marker(path, "root_remove")
    except ValueError as exc:
        raise ValueError(f"{file} can't be read as a .helab-root ({exc}): HeLab never deletes it.") from None
    if marker.uuid != expected:
        raise ValueError(f"The {MARKER_NAME} in {path} changed since HeLab found it. Refresh the list.")
    try:
        if sys.platform == "win32" and not found.st_mode & stat.S_IWRITE:
            os.chmod(file, stat.S_IWRITE)  # Read-only blocks deleting on Windows (hidden doesn't).
        os.remove(file)
    except OSError as exc:
        _traced_error("marker_remove", file, "root_remove", exc)
        send({"kind": "root_remove_refused", "path": path, "file": file, "reason": exc.strerror or str(exc)})
        return
    _trace("marker_remove", file, "root_remove")
    with stores._cache_store(cache_options["directory"], [path], allow_unrooted=True) as store:
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
            flags = _stat(file, "hide").st_flags
            _trace("chflags", file, "hide")
            os.chflags(file, flags | stat.UF_HIDDEN)
        return
    if sys.platform != "win32":
        return
    import ctypes
    kernel32 = getattr(ctypes, "windll").kernel32
    _trace("get_attributes", file, "hide")
    attributes = kernel32.GetFileAttributesW(file)
    if attributes != -1 and attributes != 0xFFFFFFFF:
        _trace("set_attributes", file, "hide")
        kernel32.SetFileAttributesW(file, attributes | 0x2)  # FILE_ATTRIBUTE_HIDDEN
