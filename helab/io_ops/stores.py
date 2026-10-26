"""Opening the disk cache for a request, and the store results that go with events."""
from __future__ import annotations

import math
import os
import sys
from typing import Any, Iterable, TYPE_CHECKING, cast

from helab.io_ops.events import DataRootField, RemovedEvent, StoreField, UsageFields
from helab.io_ops.infra import Emit, _cached_volume_id, _mounts

if TYPE_CHECKING:
    from helab.utils.cache_paths import CachePaths, Mount
    from helab.utils.cache_store import CacheStore
    from helab.utils.data_roots import LocalVolumes


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
    from helab.utils.cache_store import OPEN_FAILED, StoreError
    from helab.utils.data_roots import VolumeUnverified
    try:
        return _cache_store(cache_options["directory"], [path], local_lane=local_lane,
                            verified_volumes=verified_volumes, offline=bool(cache_options.get("offline"))), False
    except VolumeUnverified:
        raise
    except UnresolvedRemotePath as exc:
        send({"kind": "cache_skipped", "paths": [path], "mounts": [
            {"path": exc.mount_path, "type": exc.mount_type, "detail": str(exc)}]})
        return None, True
    except (StoreError, OSError) as exc:
        # Optional cache metadata must not prevent browsing source folders. (The prefix once: the
        # store's own open errors already carry it.)
        message = str(exc) if str(exc).startswith(OPEN_FAILED) else f"{OPEN_FAILED}: {exc}"
        send({"kind": "cache_warning", "message": message})
        return None, False


def _cache_store(root: str, source_paths: list[str] | None = None,
                 *, local_lane: bool = False, allow_unrooted: bool = False,
                 verified_volumes: list[list[str]] | None = None, offline: bool = False) -> CacheStore:
    """Open root-keyed records; the local lane uses only captured volume IDs.

    Source helpers record the share or volume at each source path's mount (``mount_hints``).
    ``offline`` (cache-only browsing) keys a path below a mount path nothing is mounted at now
    through that hint: the share or volume last seen there, whose cached data it still names.

    With ``verified_volumes`` (the mounts the app's last data-root verification checked), the
    local lane trusts only those hints and the system volume's: a disk swapped in at the same
    mount path and device would otherwise inherit the previous disk's ID, and its cached data.
    A source path on another hinted mount raises ``VolumeUnverified``.
    """
    from helab.utils.cache_paths import CachePaths, UnresolvedRemotePath, _inside, _normal
    from helab.utils.cache_store import OPEN_FAILED, CacheStore, StoreError
    from helab.utils.data_roots import (DataRoots, LocalVolumes, NoDataRoot, RootLocation, VolumeUnverified,
                                        current_local_volumes, fixed_mount)
    store: CacheStore | None = None
    held: list[str] = []
    try:
        mounts = _mounts("disk cache keys")
        paths = CachePaths(mounts)
        try:
            store = CacheStore(root, root_mode=True)
        except OSError as exc:  # Its folder can't be made (the store's own errors are StoreErrors).
            raise StoreError(f"{OPEN_FAILED}: {exc}") from exc
        if local_lane:
            known = {(path, source): identifier for path, source, identifier in store.volume_locations()}
            hinted = [mount for mount in mounts if (mount.path, mount.source) in known]
            if verified_volumes is not None:
                verified = {(path, source) for path, source in verified_volumes}
                held = [mount.path for mount in hinted
                        if (mount.path, mount.source) not in verified and not fixed_mount(mount)]
                hinted = [mount for mount in hinted if mount.path not in held]
            volumes = LocalVolumes((mount, known[(mount.path, mount.source)]) for mount in hinted)
            if offline:
                paths, volumes = _offline_mounts(store, mounts, volumes)
        else:
            volumes = current_local_volumes(mounts, paths=source_paths or (), id_reader=_cached_volume_id)
            if not store.read_only:
                known = {(path, source): identifier for path, source, identifier in store.volume_locations()}
                for mount, identifier in volumes.volumes:
                    if known.get((mount.path, mount.source)) != identifier:
                        store.record_volume(mount.path, mount.source, identifier)
                _record_mount_hints(store, mounts, paths, volumes, source_paths or ())
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
    except (UnresolvedRemotePath, StoreError):
        # (The store's own errors say what failed: opening it, or reading its roots or volumes.)
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


def _mount_tops(mounts: list[Mount], paths: CachePaths, volumes: LocalVolumes,
                source_paths: Iterable[str]) -> dict[str, str]:
    """Each source path's mount (not the system volume's) and its location's top: the share
    (``smb://server/share``) or the volume (``vol://<id>``)."""
    from helab.utils.cache_paths import UnresolvedRemotePath, _inside, _normal
    from helab.utils.data_roots import fixed_mount
    tops: dict[str, str] = {}
    for path in source_paths:
        matches = [mount for mount in mounts if _inside(_normal(path), _normal(mount.path))]
        if not matches:
            continue
        mount = max(matches, key=lambda entry: len(_normal(entry.path)))
        if fixed_mount(mount) or mount.path in tops:
            continue
        try:
            top = paths.key(mount.path)
            if not top.startswith("smb://"):
                top = volumes.location(mount.path)
        except UnresolvedRemotePath:  # (NoDataRoot: a volume without an ID.)
            continue
        tops[mount.path] = top
    return tops


def _record_mount_hints(store: CacheStore, mounts: list[Mount], paths: CachePaths, volumes: LocalVolumes,
                        source_paths: Iterable[str]) -> None:
    """A source helper's record of the share or volume at its paths' mounts, when it changed. Optional:
    a busy or failing store skips it (the next helper records it)."""
    import contextlib
    import sqlite3
    from helab.utils.cache_store import StoreError
    tops = _mount_tops(mounts, paths, volumes, source_paths)
    if not tops:
        return
    with contextlib.suppress(StoreError, sqlite3.Error):
        saved = store.mount_hints()
        for mount_path, top in tops.items():
            if saved.get(mount_path) != top:
                store.record_mount_hint(mount_path, top)


def _volume_mount(mount: Mount) -> bool:
    """A mount someone attached, whose folders are that volume's or share's own: a share, a remote
    mount, a volume under a mount top (``/Volumes``…), a Windows drive other than the system's.
    Never the system volume, nor a system mount such as a tmpfs ``/tmp``."""
    from helab.utils import cache_paths
    from helab.utils.cache_paths import _inside, _normal
    from helab.utils.data_roots import fixed_mount
    from helab.io_ops.infra import MOUNT_TOPS
    if fixed_mount(mount):
        return False
    if mount.remote or cache_paths._smb_source(mount.source, mount.fstype) is not None:
        return True
    if sys.platform == "win32":
        return True
    return any(_inside(_normal(mount.path), _normal(top)) and _normal(mount.path) != _normal(top)
               for top in MOUNT_TOPS)


def _offline_mounts(store: CacheStore, mounts: list[Mount],
                    volumes: LocalVolumes) -> tuple[CachePaths, LocalVolumes]:
    """The mount table and local volumes with the hinted shares and volumes added back at mount
    paths nothing is mounted at now (offline keys, never source I/O). A volume or share mounted at
    the hint's path or above it now wins (``_volume_mount``): the folder there is its own, not the
    hinted one's (Vernier, review round 1)."""
    from helab.utils.cache_paths import CachePaths, Mount, _inside, _normal
    from helab.utils.data_roots import LocalVolumes
    mounted = {_normal(mount.path) for mount in mounts}
    attached = [_normal(mount.path) for mount in mounts if _volume_mount(mount)]
    shares: list[Mount] = []
    local = list(volumes.volumes)
    for mount_path, top in store.mount_hints().items():
        if _normal(mount_path) in mounted or any(_inside(_normal(mount_path), above) for above in attached):
            continue
        if top.startswith("smb://"):
            shares.append(Mount(top, mount_path, "smbfs", True))
        elif top.startswith("vol://"):
            local.append((Mount(top, mount_path, "local"), top[len("vol://"):]))
    return CachePaths([*mounts, *shares]), LocalVolumes(local)


def _deadline(store: CacheStore) -> float | None:
    from helab.utils.cache_store import StoreError
    try:
        return store.next_deadline()
    except StoreError:
        return None


def _store_fields(store: CacheStore) -> StoreField:
    """The store an answer comes from (its ``store_id``: ``FolderCache.store_answer``)."""
    return {"store": store.store_id}


def _usage(store: CacheStore) -> UsageFields:
    """The store's live usage and when it was measured, for the app's 80% pause; {} if unreadable."""
    from helab.utils.cache_store import StoreError
    try:
        return cast(UsageFields, store.measure_usage().event())
    except StoreError:
        return {}


def _results_removed_event(removal: Any, *, evicted: bool = False) -> RemovedEvent:
    """What a removal of saved results did (``CacheStore.remove_results``), kind ``results``;
    ``evicted``: saved results Make room removed for a waiting one, named by (folder, lookup,
    result_id): not a clear, so only reads and marks of those very rows are affected."""
    event: RemovedEvent = {"kind": "removed", "kinds": ["results"],
                           "paths": None if removal.paths is None else list(removal.paths),
                           "results": removal.results, "bytes": removal.bytes, "root": removal.root}
    if evicted:
        event["evicted"] = [[folder, lookup, result_id] for folder, lookup, result_id in removal.evicted]
    return event


def _removed_event(removal: Any) -> RemovedEvent:
    """What a removal did, for ``FolderCache.removed``; ``paths`` None means every path of those kinds."""
    return {"kind": "removed", "kinds": list(removal.kinds),
            "paths": None if removal.paths is None else list(removal.paths),
            "datasets": removal.datasets, "bytes": removal.dataset_bytes}
