"""Saved folder listings, for browsing cached folders offline (cache-only browsing C2).

A ``list`` helper saves each folder it lists completely: its subfolder names and its own counts
(the store's ``listings`` kind, keyed like every record by the folder's ``root://`` key, so only
below data roots). The write is optional: it never fails or holds up the listing, and it is
skipped while the saved listing says the same and is under ``REFRESH_SECONDS`` old. Reading them
back (``read_listing``) is local-lane work: the disk cache only, never the source folder.
"""
from __future__ import annotations

import math
import os
from typing import Any, Iterable, Mapping, TYPE_CHECKING

from helab.io_ops import metadata, stores
from helab.io_ops.events import OfflineListingEvent, ResultsField
from helab.io_ops.infra import Emit, emit
from helab.io_ops.stores import _data_root, _open_store
from helab.io_ops.summary import SUMMARY_STATUSES
from helab.utils import file_kinds

if TYPE_CHECKING:
    from helab.utils.cache_store import CacheStore, Read, SaveGuard

# A listing that says the same as the saved one is written again only once this old, so browsing
# back and forth costs no writes and the saved date stays at most this far behind.
REFRESH_SECONDS = 3600.0
# Seconds a listing's write waits for the store's write lock before it gives up (it is retried by
# the folder's next listing).
WRITE_WAIT = 0.5
# What a listing's own status keeps: its counts, as a folder summary does, never the shot lists.
_STATUS_KEYS = ("status", "count", "raw_count", "txy_count", "empty", "has_dirs", "files")


def listing_record(names: Iterable[str], status: Mapping[str, Any]) -> dict[str, Any]:
    """The saved form of a completed listing: its subfolders' names (sorted) and the folder's own
    counts from its ``status`` event, with ``listed_at`` (when the listing started)."""
    return {"version": 1, "names": sorted(set(names)), "listed_at": float(status["scanned_at"]),
            "status": status["status"], "count": int(status["count"]),
            "raw_count": len(status["raw"]), "txy_count": len(status["txy"]),
            "empty": bool(status["empty"]), "has_dirs": bool(status["has_dirs"]),
            "files": dict(status.get("files") or {})}


def valid_listing(info: object) -> dict[str, Any]:
    """A saved listing if it is complete, else {}."""
    if (isinstance(info, dict) and info.get("version") == 1
            and isinstance(info.get("names"), list) and all(isinstance(name, str) and name for name in info["names"])
            and isinstance(info.get("listed_at"), (float, int)) and math.isfinite(info["listed_at"])
            and 0 < info["listed_at"] < 253402300799
            and info.get("status") in SUMMARY_STATUSES
            and isinstance(info.get("count"), int)  # (-1 for a folder with nothing, as ``_classify`` gives it.)
            and all(isinstance(info.get(key), int) and info[key] >= 0 for key in ("raw_count", "txy_count"))
            and isinstance(info.get("empty"), bool) and isinstance(info.get("has_dirs"), bool)
            and file_kinds.valid_files(info.get("files", {}))):
        return info
    return {}


def _same(saved: Mapping[str, Any], record: Mapping[str, Any]) -> bool:
    return saved.get("names") == record["names"] and all(saved.get(key) == record[key] for key in _STATUS_KEYS)


def listing_guard(store: CacheStore | None, path: str) -> SaveGuard | None:
    """The save guard a listing takes before its scandir: a Clear of listings, of the folder or of
    its data root after that makes its save a no-op. None without a key or a readable store."""
    if store is None:
        return None
    try:
        return store.guard([path], ("listings",))
    except Exception:  # No data root here, an unreadable store or one from before listings: no save.
        return None


def save_listing(store: CacheStore | None, guard: SaveGuard | None, path: str, names: Iterable[str],
                 status: Mapping[str, Any]) -> str:
    """Save a completed listing of ``path`` under ``guard``, best effort. Returns "saved",
    "unchanged" (the saved one says the same and is recent, or a later listing's is saved), or
    "skipped" (no store or guard, the store busy or failing, or the guard no longer holding)."""
    if store is None or guard is None or store.read_only:
        return "skipped"
    record = listing_record(names, status)
    try:
        # A first look without the write lock: most listings are unchanged and write nothing.
        saved = valid_listing(store.read_record("listings", path).value)
        if saved and (saved["listed_at"] > record["listed_at"]
                      or _same(saved, record) and record["listed_at"] - saved["listed_at"] < REFRESH_SECONDS):
            return "unchanged"
        # Decided again under the write lock: another helper may have saved a newer one since.
        with store.waiting(WRITE_WAIT):
            written = store.save_listing(path, record, guard, same=lambda other: _same(other, record),
                                         refresh_seconds=REFRESH_SECONDS)
    except Exception:  # SaveRejected (cleared meanwhile), StoreError (busy, failing), a re-keyed folder.
        return "skipped"
    return "saved" if written else "unchanged"


def read_listing(store: CacheStore, path: str) -> Read[dict[str, Any]]:
    """The folder's saved listing: found (valid), missing, or an error (unknown, never "none")."""
    from helab.utils.cache_store import _error, _found
    found = store.read_record("listings", path)
    if found.value is None:
        return found
    listing = valid_listing(found.value)
    return _found(listing) if listing else _error("Saved listing is unreadable")


def saved_listing(path: str, cache_options: dict[str, Any] | None, *,
                  verified_volumes: list[list[str]] | None = None) -> Read[dict[str, Any]]:
    """Read ``path``'s saved listing in the local lane: the disk cache only, never the source
    folder (``VolumeUnverified`` is raised, as for cached reads, until its volume is verified)."""
    from helab.utils.cache_store import _error, _missing
    events: list[Any] = []
    store = _open_store(cache_options, events.append, path, local_lane=True, verified_volumes=verified_volumes)
    if store is None:
        warning = next((event for event in events if event.get("kind") == "cache_warning"), None)
        return _error(str(warning["message"])) if warning else _missing()
    try:
        return read_listing(store, path)
    finally:
        store.close()


def _listing_status(listing: Mapping[str, Any]) -> dict[str, Any]:
    """A folder summary (as ``scan_cached`` carries one) from a saved listing's counts, for a folder
    whose full summary isn't saved: its row shows them as saved results."""
    return {"version": 1, "status": listing["status"], "count": listing["count"],
            "raw_count": listing["raw_count"], "txy_count": listing["txy_count"], "empty": listing["empty"],
            "has_dirs": listing["has_dirs"], "files": listing["files"], "scanned_at": listing["listed_at"],
            "signature": "", "from_listing": True}


def _roots_below(store: CacheStore, path: str) -> list[str]:
    """The subfolders of ``path`` that lead down to a known data root (offline, a folder above the
    roots has no saved listing), by their source paths here: mounted, or hinted (``mount_hints``)."""
    from helab.utils.cache_paths import _inside, _normal
    names: set[str] = set()
    for location, _, decision in store.root_locations():
        if decision != "confirmed":
            continue
        root = store._location_source(location)
        if root.startswith(("smb://", "vol://")) or _normal(root) == _normal(path) or not _inside(
                _normal(root), _normal(path)):
            continue
        names.add(root[len(path.rstrip("/\\")):].lstrip("/\\").replace("\\", "/").split("/")[0])
    return sorted(name for name in names if name)


def saved_list_folder(path: str, send: Emit = emit, cache_options: dict[str, Any] | None = None, *,
                      verified_volumes: list[list[str]] | None = None) -> None:
    """Work Offline's listing of ``path`` (``saved_list``, local lane): what ``list`` sends, from the
    disk cache alone, never the source folder. Its own saved records and summary (or its saved
    listing's counts), then its saved subfolders with theirs, then an ``OfflineListingEvent``. A
    folder never listed while online sends ``listed`` False, with the subfolders leading down to
    known data roots. On a volume not verified yet it raises ``VolumeUnverified``, as cached reads."""
    from helab.io_ops.browse import _result_counts
    from helab.utils.cache_paths import UnresolvedRemotePath, _inside, _normal
    from helab.utils.cache_store import StoreError
    from helab.utils.data_roots import VolumeUnverified
    if not cache_options:
        raise ValueError("The disk cache is off for this session")
    store = stores._cache_store(cache_options["directory"], [path], local_lane=True, allow_unrooted=True,
                                verified_volumes=verified_volumes, offline=bool(cache_options.get("offline")))
    try:
        if any(_inside(_normal(path), _normal(mount)) for mount in store._unverified_mounts):
            raise VolumeUnverified(path)
        try:
            store._path_key(path)
        except UnresolvedRemotePath:  # No data root here: no listing, only the way down to roots.
            found: Read[dict[str, Any]] | None = None
        else:
            found = read_listing(store, path)
            if found.failed:
                raise StoreError(found.error)
        listing = found.value if found is not None else None
        # (Without a key, its own records are unknown, as for ``list`` of a folder without a root.)
        keyed = store if found is not None else None
        _, saved = metadata._send_saved(keyed, path, send)
        if listing is not None and not (saved or {}).get("scan_status"):
            send({"kind": "scan_cached", "status": _listing_status(listing)})
        names = list(listing["names"]) if listing is not None else _roots_below(store, path)
        for start in range(0, len(names), 128):
            batch: list[dict[str, Any]] = [{"path": os.path.join(path, name), "name": name}
                                           for name in names[start:start + 128]]
            records = metadata._saved_folders(store, [child["path"] for child in batch], send)
            counts = _result_counts(store, [child["path"] for child in batch])
            # A subfolder listed but never checked in full has no summary: its own listing's counts.
            unchecked = [path for path, saved in records.items() if not saved.get("scan_status")]
            listed_only = store.read_records("listings", unchecked) if unchecked else {}
            for child in batch:
                child.update(records.get(child["path"], {}))
                if (found := listed_only.get(child["path"])) is not None and (listed := valid_listing(found.value)):
                    child["scan_status"] = _listing_status(listed)
                if child["path"] in counts:
                    child["results"] = counts[child["path"]]
                if listing is None:
                    child["root_path"] = True
            send({"kind": "entries", "entries": batch})
        own = _result_counts(store, [path]).get(path) if listing is not None else None
        results: ResultsField = {} if own is None else {"results": own}
        report: OfflineListingEvent = {
            "kind": "status", "details": False, "offline": True, "listed": listing is not None,
            "listed_at": listing["listed_at"] if listing is not None else None,
            "empty": listing["empty"] if listing is not None else None,
            "has_dirs": listing["has_dirs"] if listing is not None else bool(names),
            **metadata._dataset_flags(keyed, path, send), **_data_root(keyed, path), **results}
        send(report)
    finally:
        store.close()


def newest_root_folder(send: Emit = emit, cache_options: dict[str, Any] | None = None, *,
                       verified_volumes: list[list[str]] | None = None) -> None:
    """Work Offline's start folder (``saved_list`` with ``resolve``): the data root seen most
    recently, at its folder here (mounted, or hinted: ``mount_hints``), sent as ``resolved``, as a
    default folder's lookup sends it. The disk cache only; never a source folder."""
    if not cache_options:
        raise ValueError("The disk cache is off for this session")
    with stores._cache_store(cache_options["directory"], local_lane=True, verified_volumes=verified_volumes,
                             offline=bool(cache_options.get("offline"))) as store:
        rows = sorted((row for row in store.root_rows() if row["decision"] == "confirmed"),
                      key=lambda row: row["last_seen"], reverse=True)
        for row in rows:
            folder = store._location_source(row["location"])
            if not folder.startswith(("smb://", "vol://")):
                send({"kind": "resolved", "path": folder})
                return
    raise FileNotFoundError("No data root saved to browse offline")
