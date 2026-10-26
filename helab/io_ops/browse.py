"""Browse step 1: a folder's names, counts and saved results (``list``)."""
from __future__ import annotations

import os
import time
from typing import Any, TYPE_CHECKING

from helab.io_ops import listings, markers, metadata
from helab.io_ops.events import HelperEvent, ListedStatusEvent, ResultCountField, ResultsField, SavedRootField
from helab.io_ops.infra import Emit, Heartbeat, _is_dir, _lstat, _mounts, _scandir, emit
from helab.io_ops.markers import _marker_temporary
from helab.io_ops.metadata import _dataset_flags, _saved_folders, _send_guard
from helab.io_ops.stores import _data_root, _open_store
from helab.io_ops.summary import _classify, _shots
from helab.utils import file_kinds

if TYPE_CHECKING:
    from helab.utils.cache_store import CacheStore


def _mount_fingerprint() -> list[list[str]] | None:
    try:
        return sorted([[mount.path, mount.source] for mount in _mounts("mounts seen")])
    except (OSError, RuntimeError):
        return None


def _may_have_root(store: CacheStore | None, path: str) -> bool:
    """Whether this location may have a root row to forget: unknown without a store, or when its
    roots can't be read (``_discover_root`` then says why)."""
    from helab.utils.cache_store import StoreError
    if store is None:
        return True
    try:
        return store.root_at(store._location_key(path)) is not None
    except StoreError:
        return True


def _result_counts(store: CacheStore | None, paths: list[str]) -> dict[str, ResultCountField]:
    """Each folder's saved analysis results (R2, the row badge), from the store's records alone;
    left out when unknown (no key, a read error: the app keeps what it knew)."""
    from helab.utils.cache_store import StoreError
    if store is None:
        return {}
    try:
        counts = store.result_counts(paths)
    except StoreError:
        return {}
    return {path: count.event() for path, count in counts.items()}


def list_folder(path: str, send: Emit = emit, cache_options: dict[str, Any] | None = None) -> None:
    """Browse step 1: names only, so a slow volume shows subfolders and counts first.

    One scandir with no per-entry stat (``is_dir`` uses the listing's file type).
    Each subfolder's saved summary, scan history and cache flags are read from the
    local cache, never the source, so saved badges appear with the names.
    The ``details`` scan (step 2) adds the signature and dates. A listing writes
    only root-discovery metadata and, once it has sent its status, the folder's
    saved listing (``io_ops.listings``, for browsing it offline; best effort); a
    failed listing's history is saved later by the app, with the guard this sends first.

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
                _lstat(os.path.join(path, MARKER_NAME), "listing: marker")
                marker_before = True
            except OSError:
                pass
        if marker_before:
            markers._discover_root(path, True, cache_options, send)
        early_events: list[HelperEvent] = []
        store = _open_store(cache_options, early_events.append, path)
        if store is not None or marker_before:
            for event in early_events:
                send(event)
            early_events.clear()
        try:
            _send_guard(store, path, send)
        except StoreError:
            pass
        listing_guard = listings.listing_guard(store, path)
        _, root_saved = metadata._send_saved(store, path, send)
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
                counts = _result_counts(store, [child["path"] for child in batch])
                for child in batch:
                    child.update(saved.get(child["path"], {}))
                    if child["path"] in counts:
                        child["results"] = counts[child["path"]]
            send({"kind": "entries", "entries": batch})
            entries.extend(batch)
            batch = []

        has_dirs = False
        empty = True
        marker_present = False
        listed_at = time.time()
        beat = Heartbeat(send, "listing")
        with _scandir(path, "listing") as directory:
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
                elif _is_dir(entry):
                    has_dirs = True
                    batch.append({"path": entry.path, "name": entry.name})
                    if len(batch) >= 128:
                        flush()
        flush()
        after_key = before_key
        # A marker seen only now, or one removed (its row is forgotten). Without one, a store
        # already open tells whether this location has a row to forget.
        if (marker_present != marker_before or not marker_present and _may_have_root(store, path)) and (
                markers._discover_root(path, marker_present, cache_options, send)):
            if store is not None:
                store.close()
            early_events.clear()  # The new store's own are sent instead.
            store = _open_store(cache_options, send, path)
            after_key = store._path_key(path) if store is not None else ""
            if after_key != before_key:
                _, root_saved = metadata._send_saved(store, path, send)
        for event in early_events:
            send(event)
        if before_key != after_key:
            for start in range(0, len(entries), 128):
                patch = [{"path": child["path"], "name": child["name"]}
                         for child in entries[start:start + 128]]
                if store is not None:
                    saved = _saved_folders(store, [child["path"] for child in patch], send)
                    counts = _result_counts(store, [child["path"] for child in patch])
                    for child in patch:
                        child.update(saved.get(child["path"], {}))
                        if child["path"] in counts:
                            child["results"] = counts[child["path"]]
                send({"kind": "entries", "entries": patch, "replace": True})
        raw, txy = _shots(found)
        status, count = _classify(raw, txy, has_dirs)
        saved_root: SavedRootField = {} if root_saved is None else {"saved_root": root_saved}
        own = _result_counts(store, [path]).get(path)
        results: ResultsField = {} if own is None else {"results": own}
        report: ListedStatusEvent = {"kind": "status", "details": False, "status": status, "count": count,
                                     "empty": empty, "has_dirs": has_dirs, "scanned_at": listed_at,
                                     "raw": sorted(raw), "txy": sorted(txy),
                                     "files": file_kinds.files_summary(found, {}),
                                     **_dataset_flags(store, path, send), **_data_root(store, path), **saved_root,
                                     **results}
        # Only the cache needs it (its volume checks); without it a listing reads nothing more.
        if cache_options and (mounts := _mount_fingerprint()) is not None:
            send({"kind": "mounts_seen", "mounts": mounts})
        send(report)
        # After the status, so the tab never waits for it; a re-keyed folder's guard no longer
        # covers it (skipped: its next listing saves it).
        listings.save_listing(store, listing_guard, path, (child["name"] for child in entries), report)
    finally:
        if store is not None:
            store.close()
