"""Opening the disk cache for a request, and the store results that go with events."""
from __future__ import annotations

import math
import os
import sys
from typing import Any, TYPE_CHECKING, cast

from helab.io_ops.events import DataRootField, RemovedEvent, UsageFields
from helab.io_ops.infra import Emit, _cached_volume_id, _mounts

if TYPE_CHECKING:
    from helab.utils.cache_store import CacheStore


def _cache_info(info: object) -> dict[str, Any]:
    """A dataset record's ``info`` if it is usable (a save date and signature), else {}."""
    if isinstance(info, dict):
        saved_at = info.get("saved_at")
        if (isinstance(saved_at, (int, float)) and math.isfinite(saved_at) and saved_at > 0
                and isinstance(info.get("signature"), str)):
            return info
    return {}


def _data_root(store: CacheStore | None, path: str) -> DataRootField:
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
    from helab.utils.cache_paths import CachePaths, UnresolvedRemotePath, _inside, _normal
    from helab.utils.cache_store import CacheStore, StoreError
    from helab.utils.data_roots import (DataRoots, LocalVolumes, NoDataRoot, RootLocation, VolumeUnverified,
                                        current_local_volumes, fixed_mount)
    store: CacheStore | None = None
    held: list[str] = []
    try:
        mounts = _mounts("disk cache keys")
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
    store._unverified_mounts = held
    store._source_path = resolver.source
    store._location_key = resolver.location
    store._location_source = lambda location: (paths.source(location) if location.startswith("smb://")
                                               else volumes.source(location))
    return store


def _deadline(store: CacheStore) -> float | None:
    from helab.utils.cache_store import StoreError
    try:
        return store.next_deadline()
    except StoreError:
        return None


def _usage(store: CacheStore) -> UsageFields:
    """The store's live usage and when it was measured, for the app's 80% pause; {} if unreadable."""
    from helab.utils.cache_store import StoreError
    try:
        return cast(UsageFields, store.measure_usage().event())
    except StoreError:
        return {}


def _removed_event(removal: Any) -> RemovedEvent:
    """What a removal did, for ``FolderCache.removed``; ``paths`` None means every path of those kinds."""
    return {"kind": "removed", "kinds": list(removal.kinds),
            "paths": None if removal.paths is None else list(removal.paths),
            "datasets": removal.datasets, "bytes": removal.dataset_bytes}
