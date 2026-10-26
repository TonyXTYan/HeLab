"""Saved folder listings, for browsing cached folders offline (cache-only browsing C2).

A ``list`` helper saves each folder it lists completely: its subfolder names and its own counts
(the store's ``listings`` kind, keyed like every record by the folder's ``root://`` key, so only
below data roots). The write is optional: it never fails or holds up the listing, and it is
skipped while the saved listing says the same and is under ``REFRESH_SECONDS`` old. Reading them
back (``read_listing``) is local-lane work: the disk cache only, never the source folder.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, TYPE_CHECKING

from helab.io_ops.stores import _open_store
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
        saved = valid_listing(store.read_record("listings", path).value)
        if saved and (saved["listed_at"] > record["listed_at"]
                      or _same(saved, record) and record["listed_at"] - saved["listed_at"] < REFRESH_SECONDS):
            return "unchanged"
        with store.waiting(WRITE_WAIT):
            store.save_record("listings", path, record, guard, saved_at=record["listed_at"])
    except Exception:  # SaveRejected (cleared meanwhile), StoreError (busy, failing), a re-keyed folder.
        return "skipped"
    return "saved"


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
