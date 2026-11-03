"""Loading TXY data (``load``) and cached reads (``cached``), with the dataset save."""
from __future__ import annotations

import os
import time
from typing import Any, Callable, TYPE_CHECKING

from helab.io_ops import fingerprints, helab_txy, infra, txy_cache
from helab.io_ops.events import DiskCachedField, PendingSaveEvent, RawMtimeField
from helab.io_ops.fingerprints import (DEFAULT_CHECK_LEVEL, _as_of, _cached_signature, _clock_ahead,
                                       _fingerprint_signature, _mtime_unchanged, _quick_mtime, _raw_list,
                                       _samples_unchanged, _saved_fingerprint, _saved_raw_times, _settled,
                                       _touch)
from helab.io_ops.identity import _location_identity
from helab.io_ops.infra import (Emit, Heartbeat, Pause, _entry_stat, _is_dir, _read_gate, _read_marker,
                                _scandir, _stat, emit)
from helab.io_ops.stores import _cache_info, _data_root, _deadline, _open_store
from helab.io_ops.summary import _save_summary, _summary
from helab.utils import file_kinds, large_folder, txy_sources

if TYPE_CHECKING:
    from helab.utils.cache_store import CacheStore, SaveGuard


def read_cached(path: str, output: str, send: Emit = emit,
                cache_options: dict[str, Any] | None = None, *,
                limits: dict[str, Any] | None = None, allow_large: bool = False,
                verified_volumes: list[list[str]] | None = None, txy: dict[str, Any] | None = None) -> None:
    """Send a folder's dataset from the local disk cache, never touching the source folder.

    The caller shows it as not yet checked; a later ``load`` with it as the RAM
    base checks the folder. A large dataset (its TXY files' size) stops with
    ``too_large`` before it is read, unless ``allow_large``. On a volume not yet
    verified (``verified_volumes``) it fails with ``VolumeUnverified``; the app
    reads it again once verification has checked that volume. In store-v4 it is the view of ``txy``'s source
    (the tab's); without one, the folder's view used last, the priority modes' first (stage 2).
    """
    import numpy as np
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
        access = txy_cache.Access.for_cached_read(store, path, txy)
        record = access.row(path)
        if record.value is not None and _too_large(
                large_folder.estimate(_saved_fingerprint(record.value)), limits, allow_large, send):
            return
        found = access.full(path)
        if found.failed:
            raise ValueError(found.error)
        if found.value is None:
            raise ValueError("No cached data for this folder")
        row, loader = found.value
        # Checked again on what was read: the dataset may have been replaced since.
        if _too_large(large_folder.estimate(_saved_fingerprint(row)), limits, allow_large, send):
            return
        data = loader()
        if data is None:
            raise ValueError("No cached data for this folder")
        access.touch(path)
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
          "raw_times": _raw_list(_saved_raw_times(row), shots), "txy": _txy_record(info),
          "signature": info.get("signature") or _fingerprint_signature(fingerprint)})


def _txy_record(info: dict[str, Any]) -> dict[str, Any]:
    """A cached dataset's ``txy`` (data cached before HeLab's TXY were looked for: MATLAB's alone)."""
    record = info.get(txy_sources.TXY_FIELD)
    return dict(record) if isinstance(record, dict) else helab_txy.default_record()


def _helab_unchanged(path: str, store: CacheStore | None, txy: dict[str, Any], saved: dict[str, Any]) -> bool:
    """Nothing converted, and no other profile asked for, since ``saved`` (a dataset's ``txy``) was
    made: HeLab's folders have the mtimes it recorded (none, for data made before any existed)."""
    source = txy_sources.requested_source(txy.get("source"))
    if not saved.get("source"):
        # Made before HeLab's TXY were looked for (MATLAB's alone; no HeLab TXY named so then): as
        # every source but HeLab only (a list without External) reads it while no HeLab folder or shot has
        # turned up since.
        if txy_sources.EXTERNAL not in txy_sources.entries_of(source):
            return False
    elif txy_sources.source_text(saved.get("source")) != source:
        return False
    if not txy_sources.wants_helab(source):
        return True
    state = helab_txy.folder_state(helab_txy.folders(path, txy, helab_txy.store_key(store, path)), time.time())
    if (state or saved.get("origins")) and helab_txy.saved_wanted(saved) != helab_txy.wanted_key(
            {**txy, "source": source}):
        return False
    return helab_txy.state_unchanged(saved.get("folders") or [], state)


def _unchanged_since_cache(path: str, send: Emit, store: CacheStore,
                           base_signature: str, memory: list[list[int]], check_level: str,
                           txy: dict[str, Any] | None = None, held_origins: dict[int, str] | None = None,
                           access: txy_cache.Access | None = None) -> bool | None:
    """One folder stat instead of listing and checking every file.

    When the caller holds the cached dataset (``base_signature``), the cache has
    no files that were still being written, and the folder's mtime is the one its
    listing saw (``_mtime_unchanged``), nothing can have been added or
    removed: ``loaded`` names the caller's shots and True is returned. None: the
    check doesn't apply (no such cached dataset), and the folder wasn't looked at. HeLab's TXY
    (``txy``) count as unchanged only while HeLab's folders are (``_helab_unchanged``). The signature is
    the folder's MATLAB TXY only, so the cached dataset is the one held only while every shot both have
    has the same (size, mtime) and kind in each (``held_origins``: the held shots' HeLab origins): another
    HeLab on this computer may have saved the folder with a shot from another TXY (Codex on PR #10).
    """
    access = access or txy_cache.Access(store, txy_sources.requested_source((txy or {}).get("source")), txy or {})
    found = access.row(path)
    if found.value is None:
        return None
    row = found.value
    info = _with_sizes(_cache_info(row["info"]), row)
    as_of = _as_of(info)
    if info.get("signature") != base_signature or info.get("unsettled") or as_of is None:
        return None
    fingerprint = [list(entry) for entry in _saved_fingerprint(row)]
    record = _txy_record(info)
    cached = {int(entry[0]): (int(entry[1]), int(entry[2])) for entry in fingerprint}
    cached_origins = helab_txy.origins_from(record.get("origins"))
    for shot, size, modified_ns in memory:
        if int(shot) in cached and (cached[int(shot)] != (int(size), int(modified_ns))
                                    or (held_origins or {}).get(int(shot), "") != cached_origins.get(int(shot), "")):
            return None
    folder = _stat(path, "cached check: folder")
    modified = folder.st_mtime
    if (not _mtime_unchanged(info, folder, as_of)
            or not _samples_unchanged(path, fingerprint, info.get("names"), check_level)
            or not _helab_unchanged(path, store, txy or {}, record)):
        return False
    held = sorted({int(entry[0]) for entry in memory} & {int(entry[0]) for entry in fingerprint})
    problematic = [value for value in row["problematic"] if isinstance(value, int) and value in held]
    access.touch(path)
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
          "raw_times": _raw_list(_saved_raw_times(row), held), "txy": record,
          "memory_shots": held, "base_signature": base_signature, "signature": base_signature})
    return True


def _unchanged_since_memory(path: str, send: Emit, store: CacheStore | None, base_signature: str,
                            memory: list[list[int]], check: dict[str, Any], check_level: str,
                            txy: dict[str, Any] | None = None) -> bool:
    """The quick check of data held in RAM without a disk cache (no .helab-root, Don't cache, or one
    not saved yet), as ``_unchanged_since_cache`` from the dataset's own load: its listing time,
    file names, identity and folder mtime (``memory_check``). The folder must be at the same location
    (and under the same data root, whose marker is read), not modified since that listing, with no file then
    still being written, and a sample of its files unchanged; else the load checks every file."""
    fingerprint, names, listed_at = check.get("fingerprint"), check.get("names"), check.get("listed_at")
    if (check.get("signature") != base_signature or check.get("unsettled")
            or not isinstance(listed_at, (int, float)) or not isinstance(fingerprint, list)
            or not isinstance(names, list) or len(names) != len(fingerprint)):
        return False
    identity = check.get("identity")
    if not identity or _location_identity(path, "memory check: identity") != identity:
        return False
    root = check.get("data_root")
    if isinstance(root, dict) and root.get("path"):
        try:
            if _read_marker(str(root["path"]), "memory check: root").uuid != root.get("uuid"):
                return False
        except (OSError, ValueError):
            return False
    folder = _stat(path, "memory check: folder")
    modified = folder.st_mtime
    record = check.get(txy_sources.TXY_FIELD)
    record = dict(record) if isinstance(record, dict) else helab_txy.default_record()
    if (not _mtime_unchanged(check, folder, listed_at)
            or not _samples_unchanged(path, fingerprint, names, check_level, "memory check: sample")
            or not _helab_unchanged(path, store, txy or {}, record)):
        return False
    held = sorted({int(entry[0]) for entry in memory} & {int(entry[0]) for entry in fingerprint})
    problematic = [value for value in check.get("problematic") or () if isinstance(value, int) and value in held]
    send({"kind": "load_source", "source": "memory", "cache_reason": ""})
    send({"kind": "loaded", "rows": 0, "bytes": 0, "files": len(held), "loaded_at": time.time(),
          "total_files": len(fingerprint), "failed_files": len(fingerprint) - len(held), "unsettled_files": 0,
          "problematic": problematic, "source": "memory", "cached": True, **_data_root(store, path),
          "disk_cache_pending": False, "cache_info": {}, "unchanged": True, "modified": modified,
          "modified_observed_at": time.time(),
          "load_counts": {"reused_memory": len(held), "reused_disk": 0, "new": 0, "modified": 0,
                          "removed": 0, "read": 0, "new_loaded": 0, "modified_loaded": 0},
          "cache_reason": "Folder not modified since loaded", "fingerprint": fingerprint,
          "memory_shots": held, "base_signature": base_signature, "signature": base_signature,
          # Still the folder as of that listing, for the next quick check.
          "listed_at": listed_at, "names": names, "identity": identity, "txy": record,
          "folder_mtime_ns": check.get("folder_mtime_ns")})
    return True


def load(path: str, output: str, send: Emit = emit,
         cache_options: dict[str, Any] | None = None,
         memory: list[list[int]] | None = None, base_signature: str = "",
         expected: str = "", *, limits: dict[str, Any] | None = None, allow_large: bool = False,
         no_cache: bool = False, full_check: bool = False, cache_base: bool = False,
         check_level: str = DEFAULT_CHECK_LEVEL, allow_missing: bool = False,
         memory_check: dict[str, Any] | None = None, memory_raw_times: list[list[int]] | None = None,
         txy: dict[str, Any] | None = None, memory_origins: dict[str, str] | None = None) -> None:
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
    before any file is read, unless ``allow_missing``. ``memory_check``: what the held data's own
    load saw (listing time, names, identity), for its quick check when no cached dataset has one.
    ``memory_raw_times``: the held shots' times (``[shot, raw mtime_ns]``), so a held shot whose TXY
    file is unchanged never has its raw file stat'ed again (not even when the cache save reads it).
    After its scan phase (saved as the folder's summary), a load whose new data is large
    (``limits``) stops with ``too_large`` before reading anything, unless ``allow_large``.
    A folder the user chose not to cache (``no_cache``, or its saved flag) is read into RAM
    only: its cached data is neither used nor written. In store-v4 a ``no_cache`` request (a plot's own
    TXY choice) is cached all the same under its own view (Q19.3), quietly: it never waits for an answer,
    and it sends none of the tab's cache events; only the folder's saved flag keeps it RAM only.
    ``txy``: which TXY to load (``txy_sources``: the source, the profile HeLab's must be made with,
    and where HeLab's folders are, ``helab_txy``); without it, MATLAB's with HeLab's current ones
    filling the shots MATLAB lacks. ``memory_origins``: the held shots' origins (``{shot: origin}``,
    HeLab's only): a held shot is reused only from the same kind of TXY.
    """
    from helab.utils.cache_store import StoreError
    store = _open_store(cache_options, send, path)
    no_cache_reason = NOT_CACHED_REASON
    quiet = False
    try:
        guard: SaveGuard | None = None
        txy_guard: SaveGuard | None = None
        if store is not None:
            try:
                # Taken first, before anything is read or imported: only a later job's
                # save may replace this one's, and a removal from now on stops it.
                guard = store.start_dataset_job(path, ("summaries",))
                if txy_cache.layered(store):  # (store-v4: the TXY layers' and views' guard, stage 2.)
                    txy_guard = store.start_txy_job(path)
            except StoreError as exc:
                send({"kind": "cache_warning", "message": f"Disk cache can't be updated: {exc}"})
            prefs = store.read_prefs([path])[path]
            if prefs.failed:
                # Unknown whether the user chose not to cache it: load from the files, without the cache.
                send({"kind": "cache_warning", "message": f"Disk cache not used: the folder's settings couldn't be "
                                                         f"read ({prefs.error})"})
            # (store-v4: a plot's own TXY choice asks no_cache, and is cached quietly instead, Q19.3.)
            quiet = no_cache and txy_cache.layered(store)
            chosen = (no_cache and not quiet) or bool(prefs.value and prefs.value.get("no_cache"))
            if prefs.failed and not chosen:
                no_cache_reason = "Disk cache not used: the folder's settings couldn't be read"
            no_cache = chosen or prefs.failed
            quiet = quiet and not no_cache
            if txy_cache.layered(store):
                # The folder's own TXY source and policy (store-v4, Q45.1, Q45.2): told to the app, which applies
                # the source to the tab's Live and later loads; and to this load if it is the tab's.
                choices = store.read_folder_choices([path])[path]
                if choices.value is not None:
                    send({"kind": "folder_choices", "path": path, "choices": choices.value})
                    # (A tag the app resolved, a user profile's too, stays the app's: TP-1.)
                    txy = txy_sources.with_choices(txy or {}, choices.value, helab_txy.tag_lookup(txy or {}))
        _load(path, output, send, store, guard, bool(cache_options), memory, base_signature, expected,
              (cache_options or {}).get("budget"), (cache_options or {}).get("budget_set_at"),
              limits=limits, allow_large=allow_large, no_cache=no_cache, no_cache_reason=no_cache_reason,
              full_check=full_check, cache_base=cache_base, check_level=check_level,
              allow_missing=allow_missing, memory_check=memory_check, memory_raw_times=memory_raw_times,
              txy=txy, memory_origins=memory_origins, txy_guard=txy_guard,
              cache_options=cache_options or {}, quiet=quiet)
    finally:
        if store is not None:
            store.close()


def _load(path: str, output: str, send: Emit, store: CacheStore | None, guard: SaveGuard | None, cache_on: bool,
          memory: list[list[int]] | None, base_signature: str, expected: str, budget: int | None,
          budget_set_at: float | None = None, *, limits: dict[str, Any] | None = None,
          allow_large: bool = False, no_cache: bool = False, no_cache_reason: str = "",
          full_check: bool = False, cache_base: bool = False, check_level: str = DEFAULT_CHECK_LEVEL,
          allow_missing: bool = False, memory_check: dict[str, Any] | None = None,
          memory_raw_times: list[list[int]] | None = None, txy: dict[str, Any] | None = None,
          memory_origins: dict[str, str] | None = None, txy_guard: SaveGuard | None = None,
          cache_options: dict[str, Any] | None = None, quiet: bool = False) -> None:
    from helab.utils.cache_store import StoreError
    txy = dict(txy or {})
    txy_source = txy["source"] = txy_sources.requested_source(txy.get("source"))
    # The folder's cached data: its dataset (store-v3), or its view and TXY layers (store-v4, stage 2).
    access = txy_cache.Access(store, txy_source, txy) if store is not None else None
    # The held shots' origins (HeLab's; the rest are MATLAB's).
    held_origins = helab_txy.origins_from(memory_origins)
    held_from = "memory"  # Where the shots counted as held are: the caller's RAM, or its cached read.
    if cache_base and not memory and not no_cache and access is not None:
        # The caller reads the cached dataset itself, beside this check: count its shots as held.
        cached_row = access.row(path).value
        if cached_row is not None:
            memory = [list(entry) for entry in _saved_fingerprint(cached_row)]
            base_signature = _cached_signature(cached_row)
            held_origins = helab_txy.origins_from(_txy_record(_cache_info(cached_row["info"])).get("origins"))
            held_from = "the disk cache"
    quick: bool | None = None
    if (not no_cache and not full_check and base_signature and store is not None and memory
            and expected in ("", base_signature)):
        quick = _unchanged_since_cache(path, send, store, base_signature, memory, check_level, txy, held_origins,
                                       access)
        if quick:
            return
    if (quick is None and memory_check and not full_check and base_signature and memory
            and expected in ("", base_signature)
            and _unchanged_since_memory(path, send, store, base_signature, memory, memory_check, check_level,
                                        txy)):
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
    # Before the listing: a later quick check needs the folder's mtime still this one (``_quick_mtime``).
    folder = _stat(path, "folder mtime")
    folder_mtime_ns = _quick_mtime(folder, listed_at)
    beat = Heartbeat(send, "listing")
    # The fingerprint comes with the listing: each TXY entry's stat (free on Windows, where the
    # listing has it; one call on macOS and Linux, as a separate stat would be).
    listed_stats: dict[int, tuple[int, int]] = {}
    # Raw files, for shot times: stat'ed later, only for shots whose time isn't known (``raw_time``).
    raw_entries: dict[int, os.DirEntry[str]] = {}
    # HeLab's TXY beside the raw files, by tag (their provenance is in HeLab's folder, ``helab_txy``).
    beside: helab_txy.Beside = {}
    # MATLAB's TXY: file and (size, mtime), by shot.
    matlab: dict[int, str] = {}
    matlab_stats: dict[int, tuple[int, int]] = {}
    with _scandir(path, "load: listing") as directory:
        for entry in directory:
            beat()
            if matched := file_kinds.match(entry.name):
                kind, shot = matched
                found.setdefault(kind.name, set()).add(shot)
                if kind.loaded:
                    matlab[shot] = entry.path
                    entry_info = _entry_stat(entry, "load: checking")
                    matlab_stats[shot] = (entry_info.st_size, entry_info.st_mtime_ns)
                elif kind is file_kinds.RAW:
                    raw_entries[shot] = entry
                elif kind is file_kinds.HELAB_TXY:
                    helab_txy.add_beside(beside, entry.name, shot, entry, txy)
            elif not has_dirs and _is_dir(entry):
                has_dirs = True
    # HeLab's current TXY (Q6.6), as the source asks; their folders' state first, for the next quick check.
    helab_key = helab_txy.store_key(store, path) or str(txy.get("key") or "")
    helab_state: list[list[Any]] = []
    helab_found: dict[int, helab_txy.HelabShot] = {}
    # Caching v2 stage 3 (store-v4 only, R~1): raw files without a current HeLab TXY, converted on read.
    on_read: dict[int, helab_txy.HelabShot] = {}
    # The HeLab shots each shot's choice takes (a text, or a raw file converted on read).
    helab_chosen: dict[int, helab_txy.HelabShot] = {}
    fell_back: set[int] = set()  # (Shots taken from beyond the list's own entries, Q~2.)
    if txy_sources.wants_helab(txy_source):
        helab_state = helab_txy.folder_state(helab_txy.folders(path, txy, helab_key), listed_at)
        trusted = {int(shot): (int(size), int(modified), held_origins[int(shot)])
                   for shot, size, modified in memory or () if int(shot) in held_origins}
        convert_here = access is not None and access.layered and not no_cache

        def can_convert(profile_hash: str) -> bool:
            assert access is not None
            return access.profile_for(txy_sources.helab_origin(profile_hash)) is not None
        listed_found = helab_txy.find_list(path, txy, helab_key, beside, raw_entries, matlab, trusted,
                                           can_convert=can_convert if convert_here else None)
        helab_found = listed_found.texts()
        on_read = listed_found.on_read
        chosen, helab_chosen, fell_back = helab_txy.compose_list(listed_found, matlab)
    else:
        chosen = helab_txy.compose(txy_source, matlab, {})
    # (Those a conversion now serves: the rest of on_read lost to another entry's TXY by the list's order.)
    on_read = {shot: found for shot, found in on_read.items() if chosen.get(shot, ("", ""))[0] == found.file}
    origins = {shot: origin for shot, (_, origin) in chosen.items() if origin}
    for shot, (filename, origin) in chosen.items():
        files.append((shot, filename))
        helab_shot = helab_chosen.get(shot)
        listed_stats[shot] = (matlab_stats[shot] if not origin or helab_shot is None
                              else (helab_shot.size, helab_shot.mtime_ns))
    def matlab_dir(shot: int) -> str:
        """A file of the source folder's listing, as its entries name it (beside TXY are among them)."""
        entry = helab_txy.beside_any(beside, shot)
        return entry.path if entry is not None else os.path.join(path, "_")

    if not files:
        raise ValueError("No current HeLab TXY in this folder"
                         if txy_sources.EXTERNAL not in txy_sources.entries_of(txy_source)
                         else "No converted TXY files in this folder")
    files.sort()

    def stat_files(phase: str, reason: str) -> list[tuple[int, int, int]]:
        beat = Heartbeat(send, phase)
        result: list[tuple[int, int, int]] = []
        for shot, filename in files:
            info = _stat(filename, reason)
            result.append((shot, info.st_size, info.st_mtime_ns))
            beat()
        return result

    fingerprint = [(shot, *listed_stats[shot]) for shot, _ in files]
    # The folder's own status (a scan's): its MATLAB TXY, whichever TXY this load takes.
    matlab_print = [(shot, *matlab_stats[shot]) for shot in sorted(matlab_stats)]
    txy_bytes = sum(size for _, size, _ in matlab_print)
    # Files another computer may still be writing are left out entirely (not in
    # the fingerprint), so the next load sees them as new and reads them whole.
    # One settle cutoff for this load's TXY and the folder's MATLAB TXY (its status, below).
    settled = set(_settled(sorted(set(fingerprint) | set(matlab_print))))
    young = {item[0] for item in fingerprint if item not in settled}
    _clock_ahead(path, fingerprint, send)  # (Dated in the future: still being written, and the app warns.)
    if young:
        files = [item for item in files if item[0] not in young]
        fingerprint = [item for item in fingerprint if item[0] not in young]
        if not files:
            raise ValueError("TXY files are still being written — Retry")
    # This listing and fingerprint are a complete status check of this folder, so
    # browsing skips its details scan (step 2) while this load runs, unless the
    # folder has subfolders (their dates come from step 2). Sent and saved before any
    # file is read; a basic scan's success is still needed to clear a failure.
    matlab_settled = [item for item in matlab_print if item in settled]
    summary = _summary(path, found, {file_kinds.TXY.name: txy_bytes}, has_dirs, False, matlab_settled, listed_at,
                       folder)
    summary["unsettled"] = len(matlab_print) - len(matlab_settled)
    send({"kind": "scan_summary", "status": summary})
    current = {shot: (size, modified) for shot, size, modified in fingerprint}
    in_memory = {int(shot) for shot, size, modified in memory or ()
                 if current.get(int(shot)) == (size, modified)
                 and held_origins.get(int(shot), "") == origins.get(int(shot), "")}
    if guard is not None and store is not None:
        _save_summary(store, path, summary, guard, send)
        if access is not None and not no_cache:
            # (store-v4: this listing's sources, for Make room's only copies, Q45.6.)
            access.mark_seen(path, raw_entries, matlab,
                             {shot: found.profile_hash for shot, found in helab_found.items()}, listed_at)
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
    # A shot the source leaves out (HeLab only) whose MATLAB TXY is there isn't missing: the load is without it.
    listed = set(chosen) | set(matlab)
    # Only MATLAB's TXY, written once, feed the mismatch rule (Q6.6): a shot held or cached from HeLab's TXY
    # may go (cleared) or change (converted again) legitimately; it is then read anew, or removed.
    from_helab = set(held_origins)
    held = {int(entry[0]) for entry in memory or ()}
    missing_checked = False
    # Shot times (raw files' mtimes): the caller's or the cache's, else stat'ed from the listing
    # (``raw_time``). Raw d<N>.txt files are never rewritten (Tony, 2026-10-20): a shot's time is
    # stat'ed once, and again only when its TXY fingerprint changed, which may be another run's
    # shot of that number (a folder copied over this one). That check is free (the fingerprint
    # comes with the listing) and covers the copy; a raw file is never re-stat'ed while its TXY
    # file is unchanged.
    raw_times: dict[int, int] = {}
    saved_raw: dict[int, int] = {}
    if held_from == "memory":  # The caller's times of the shots it holds unchanged.
        raw_times.update({shot: value for shot, value in file_kinds.raw_times(memory_raw_times).items()
                          if shot in in_memory})

    def raw_time(shot: int) -> None:
        if shot not in raw_times and (found_time := fingerprints._raw_mtime(raw_entries.get(shot), "load: shot time")) is not None:
            raw_times[shot] = found_time

    def stop_if_missing(known: set[int], helab: set[int] | None = None) -> bool:
        missing = sorted(known - listed - from_helab - (helab or set()))
        if not missing or allow_missing:
            return False
        send({"kind": "shots_missing", "missing": missing[:20], "missing_count": len(missing),
              "known_count": len(known), "listed_count": len(listed)})
        return True

    if no_cache:
        # Not cached: the user's choice. Its cached data (if any) is neither read nor written.
        cache_reason, had_dataset = no_cache_reason or NOT_CACHED_REASON, None
    elif store is not None:
        try:
            assert access is not None
            row_read = access.row(path)
            if row_read.failed:
                raise StoreError(row_read.error)
            row = row_read.value
            missing_checked = True
            saved_origins = helab_txy.origins_from(_txy_record(_cache_info(row["info"])).get("origins")) \
                if row is not None else {}
            if stop_if_missing(held | ({int(entry[0]) for entry in row["fingerprint"]} if row is not None else set()),
                               set(saved_origins)):
                return
            # The cached data's loader, when it is needed (store-v3: the dataset file; store-v4: the layers).
            packed: Callable[[], dict[int, Any] | None] | None = None
            same_kind = {shot for shot in current if saved_origins.get(shot, "") == origins.get(shot, "")}
            signed = (not access.signature_matters
                      or (row is not None and _cache_info(row["info"]).get("signature") == summary["signature"]))
            if row is not None and not (_saved_fingerprint(row) == fingerprint and saved_origins == origins
                                        and signed and in_memory >= set(current)):
                # The dataset itself is needed: read it with its row, which may have changed meanwhile.
                full = access.full(path)
                if full.failed:
                    raise StoreError(full.error)
                row, packed = full.value if full.value is not None else (None, None)
            had_dataset = row is not None
            saved_fingerprint = _saved_fingerprint(row) if row is not None else None
            previous = [value for value in row["problematic"] if isinstance(value, int)] if row is not None else []
            cache_info = _with_sizes(_cache_info(row["info"]), row) if row is not None else {}
            if row is not None:
                # Read with its row, which may have changed meanwhile.
                saved_origins = helab_txy.origins_from(_txy_record(_cache_info(row["info"])).get("origins"))
                same_kind = {shot for shot in current if saved_origins.get(shot, "") == origins.get(shot, "")}
            if saved_fingerprint is not None:
                # A shot cached from the other kind of TXY counts as modified (its fingerprint is left out).
                baseline = {shot: (size, modified) for shot, size, modified in saved_fingerprint
                            if shot not in current or shot in same_kind}
            if row is not None:
                # Only for shots whose TXY file is unchanged (raw files are never rewritten): a
                # changed one may be another run's shot of that number (a folder copied over this
                # one), so its raw file is stat'ed.
                saved_raw = {shot: value for shot, value in _saved_raw_times(row).items()
                             if shot in current and baseline.get(shot) == current[shot] and shot in same_kind}
                raw_times.update(saved_raw)

            # Unpacking brings the whole cached dataset into RAM, more than the folder now holds if
            # it shrank: when that is too large, the cache isn't used and the files are read.
            too_big = packed is not None and row is not None and bool(large_folder.verdict(
                large_folder.estimate(_saved_fingerprint(row)), limits, allow_large))

            def unpack() -> dict[int, Any] | None:
                return packed() if packed is not None and not too_big else None

            # The signature too: from the folder's MATLAB TXY, it changes without the fingerprint when one
            # arrives or settles for a shot held from HeLab's; in store-v3 such a dataset is saved again, with
            # no TXY read (area review io-5, 2026-10-31); in store-v4 only the view's info is (A40.3).
            whole = (saved_fingerprint == fingerprint and saved_origins == origins
                     and (not access.signature_matters or cache_info.get("signature") == summary["signature"]))
            if whole and packed is None:
                # The caller already holds every shot: no need to decompress the cache.
                cached, problematic = True, previous
            elif whole:
                cache_reason = "Cached dataset invalid"
                unpacked = unpack()
                complete = unpacked is not None and (
                    not access.layered or set(unpacked) >= set(current) - set(previous))
                if unpacked is not None and complete:
                    data, cached, problematic = unpacked, True, previous
                    reused = set(data)
                elif unpacked:
                    # (store-v4: a layer lacks some of the view's shots, a policy or Make room since: read them.)
                    cache_reason = "Some cached shots are gone"
                    data = {shot: array for shot, array in unpacked.items() if shot in current}
                    reused = set(data)
                    problematic = [shot for shot in previous if shot in reused]
            elif saved_fingerprint is not None:
                cache_reason = "TXY files changed since caching"
                # Keep shots whose converted file is unchanged; only new or
                # modified TXY files are read and merged into the dataset.
                data = {shot: array for shot, array in (unpack() or {}).items()
                        if shot in current and baseline.get(shot) == current[shot] and shot in same_kind}
                reused = set(data)
                problematic = [shot for shot in previous if shot in reused]
            if too_big:
                cache_reason = "Cached dataset too large to reuse"
            if cached and access.seed:
                # (store-v4: data from stage 1's dataset or store-v3's, Q45.4, Q45.5: saved into the layers.)
                cached = False
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
    baseline.update({int(shot): (size, modified) for shot, size, modified in memory or ()
                     if int(shot) not in current or held_origins.get(int(shot), "") == origins.get(int(shot), "")})
    new_shots = set(current) - set(baseline)
    modified_shots = {shot for shot in current.keys() & baseline.keys()
                      if current[shot] != baseline[shot]}
    # Shots held before that this load is without: left out by the TXY source while their TXY is still
    # there (or held from HeLab's, which the source no longer reads), else removed (Q38.3, A39.4).
    gone = baseline.keys() - current.keys()
    left_out = {shot for shot in gone if shot in matlab or shot in helab_found
                or held_origins.get(shot) and not txy_sources.wants_helab(txy_source)}
    load_counts = {"reused_memory": len(in_memory), "reused_disk": 0,
                   "new": len(new_shots), "modified": len(modified_shots),
                   "removed": len(gone - left_out), "left_out": len(left_out),
                   "read": 0, "new_loaded": 0, "modified_loaded": 0,
                   # The folder's TXY by kind, as this load found them: MATLAB's, and HeLab's current ones of
                   # the profile conversions use (looked for only when the source reads HeLab's).
                   "txy_matlab": len(matlab),
                   **({"txy_helab": len(helab_found)} if txy_sources.wants_helab(txy_source) else {}),
                   # Stage 3: the shots HeLab's TXY of which this load makes from raw files, and those it did.
                   **({"helab_on_read": len(on_read), "converted": 0} if on_read else {})}
    read = 0 if cached else len(files) - len(in_memory | reused)
    if in_memory or (from_disk and not cached):
        parts = [f"{len(in_memory)} shots from {held_from}"] if in_memory else []
        parts += [f"{len(from_disk)} shots from disk cache"] if from_disk else []
        cache_reason = f"Reused {', '.join(parts)}" + (
            f"; {read} new or changed TXY file{'' if read == 1 else 's'} to read" if read else "")
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

    def unchanged(index: int, filename: str, reason: str) -> bool:
        info = _stat(filename, reason)
        return (info.st_size, info.st_mtime_ns) == fingerprint[index][1:]

    # store-v4: each shot's layer key (MATLAB's by its TXY file, HeLab's by its raw file where listed, Q45.3).
    keys = txy_cache.entry_keys(fingerprint, origins, raw_entries) if access is not None and access.layered else {}

    def from_raw(shot: int) -> Any:
        """store-v4: a HeLab shot from the raw layer when it holds this raw file (design addendum §4, step 2),
        before any file is announced (so a file's per-file timeout never covers it) and under the converter's
        ticker for its raw size (S3-2); None when it can't (the text is read)."""
        if access is None or not access.layered or shot not in origins or listed_stats[shot][0] == 0:
            return None
        from helab.io_ops.convert import _Ticker, compute_budget
        key = keys.get(shot)
        with _Ticker(send, "converting", compute_budget(key[0] if key else 0)):
            converted = access.from_raw(path, shot, key, origins[shot])
        if converted is not None:
            data[shot] = converted
        return converted

    def convert_on_read(shot: int, index: int, filename: str) -> Any:
        """Stage 3 (store-v4): a HeLab shot made from its raw file (none current in the raw layer, no text), as
        the converter would make it, before any file is announced (``txy_cache.convert_raw_file``); no text is
        written (Q19.1) and no raw row (R~2: ``raw_fill``'s). None when it can't be: late (the next load tries
        again), or problematic (damaged, or a conversion that failed)."""
        assert access is not None
        profile = access.profile_for(origins[shot])
        size, mtime_ns = fingerprint[index][1:]
        if profile is None:
            problematic.append(shot)
            return None
        outcome, array = txy_cache.convert_raw_file(filename, shot, size, mtime_ns, profile, access.backend, send)
        if outcome == txy_cache.LATE:
            late.add(shot)
            return None
        if outcome != txy_cache.CONVERTED:
            problematic.append(shot)  # (Damaged or failed: unreadable until it changes.)
            return None
        load_counts["converted"] += 1
        data[shot] = array
        return array

    def read_txy(shot: int, filename: str, reason: str = "load: read") -> Any:
        if shot in origins and listed_stats[shot][0] == 0:
            # HeLab's TXY of a shot with no hits (Q10.3): converted, empty.
            data[shot] = np.empty((0, 3), dtype=np.float64)
            return data[shot]
        _read_gate(filename)
        frame = infra._read_txy_file(filename, reason)
        if frame.isna().any().any():
            problematic.append(shot)
        array = np.asarray(frame.dropna(), dtype=np.float64)
        data[shot] = array
        return array

    for i, (shot, filename) in enumerate(files):
        Pause.checkpoint(send)
        # Only a file read is announced (the file being read, its per-file timeouts); a reused
        # shot counts in the progress events alone.
        reading = shot not in in_memory and shot not in reused and not cached
        converted = from_raw(shot) if reading else None
        on_read_failed = False
        if reading and converted is None and shot in on_read:
            converted = convert_on_read(shot, i, filename)
            on_read_failed = converted is None
        # (Converted from the raw layer or the raw file: no TXY file read.)
        reading = reading and converted is None and not on_read_failed
        if reading:
            send({"kind": "file_started", "filename": filename})
        try:
            array = None
            if converted is not None:
                load_counts["read"] += 1
                array = converted
            elif on_read_failed:
                pass  # (Late or problematic, as ``convert_on_read`` said.)
            elif shot in in_memory:
                # Unchanged and already in the caller's RAM: nothing to read or send. Its time is the
                # caller's or the cache's; one still missing (its raw file was still being written
                # when it was read, or a cache saved before shot times) the listing can give, and
                # only that one is stat'ed (``raw_time`` skips shots with a time).
                raw_time(shot)
                loaded += 1
            elif shot in reused:
                array = data[shot]
            elif not cached:
                load_counts["read"] += 1
                read_bytes += fingerprint[i][1]
                if unchanged(i, filename, "load: before read"):
                    array = read_txy(shot, filename)
                    if not unchanged(i, filename, "load: after read"):
                        data.pop(shot, None)
                        array = None
                if array is None:
                    late.add(shot)
                    problematic[:] = [value for value in problematic if value != shot]
            if array is not None:
                artifact = os.path.join(output, f"{shot}.npy")
                infra._save_artifact(artifact, array)
                rows += len(array)
                size += array.nbytes
                loaded += 1
                raw_time(shot)
                known_time: RawMtimeField = {"raw_mtime": raw_times[shot]} if shot in raw_times else {}
                send({"kind": "shot", "shot": shot, "artifact": artifact,
                      "fingerprint": fingerprint[i], "problematic": shot in problematic, **known_time})
                load_counts["new_loaded"] += int(shot in new_shots)
                load_counts["modified_loaded"] += int(shot in modified_shots)
                load_counts["reused_disk"] += int(shot in from_disk)
        except (OSError, ValueError, pd.errors.ParserError):
            problematic.append(shot)
        if reading:
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
        return settled != [item for item in stat_files("verifying", verify_reason) if item[0] not in late]

    verify_reason = "load: verifying"  # (The trace's only: the second check is the cache save's.)
    if changed():
        raise ValueError("Folder changed while loading — Retry")
    # HeLab's not beside the raw files are named in full (a quick check's samples join them to the folder).
    names = [filename if shot in origins and os.path.dirname(filename) != os.path.dirname(matlab_dir(shot))
             else os.path.basename(filename) for shot, filename in files]
    txy_record = helab_txy.record(txy_source, origins, helab_chosen, None, txy, helab_state, on_read, fell_back,
                                  {shot for shot, _ in files})
    # Left out when the cache couldn't be read: unknown, not "not cached" (and for a quiet load: the folder's
    # cache state is its tab's, never a plot choice's).
    # store-v4: the folder is disk cached when it has any view, this TXY choice's or another's (as listings say,
    # read_dataset_infos), so its badge doesn't drop while this choice's first save is on its way.
    other_view = (not had_dataset and had_dataset is not None and access is not None and access.layered
                  and store is not None and bool(store.folder_views(path)))
    known_cached: DiskCachedField = {} if (had_dataset is None and not cached) or quiet else {
        "disk_cached": cached or bool(had_dataset) or other_view}
    send({"kind": "loaded", "rows": rows, "bytes": size, "files": loaded,
          "loaded_at": time.time(),
          "total_files": len(files) + len(young), "failed_files": len(files) - loaded - len(late),
          "unsettled_files": unsettled,
          "problematic": sorted(set(problematic)),
          "source": source, "cached": cached, **_data_root(store, path), **known_cached,
          "disk_cache_pending": guard is not None and not cached and not no_cache and not quiet,
          "cache_info": cache_info, "load_counts": load_counts,
          "cache_reason": cache_reason, "raw_times": _raw_list(raw_times, current),
          "fingerprint": fingerprint, "memory_shots": sorted(in_memory), "base_signature": base_signature,
          # The folder's, as its scan computes it (every source's dataset of it has this one).
          "signature": str(summary["signature"]), "txy": txy_record,
          # For a quick check of this data held in RAM (``_unchanged_since_memory``).
          "listed_at": listed_at, "names": names, "identity": _location_identity(path, "load: identity"),
          "folder_mtime_ns": folder_mtime_ns})
    if access is not None and (cached or reused):
        access.touch(path)
    if cached and not young and store is not None and guard is not None and not no_cache:
        # This listing found the cache complete: it dates from now (a later non-TXY change no longer
        # rules out the quick check), and older caches get their file names for its samples.
        from helab.utils.cache_store import SaveRejected
        filled = _raw_list(raw_times, current)
        try:
            assert access is not None
            access.confirm(path, fingerprint, names, listed_at, guard, txy_guard,
                           filled if filled != _raw_list(saved_raw, current) else None, folder_mtime_ns,
                           signature=str(summary["signature"]), txy_record=txy_record)
        except (StoreError, SaveRejected):
            pass  # Best effort: the next full check tries again.
    if store is None or guard is None or cached or no_cache:
        return
    # The caller already has its data; updating the disk cache no longer
    # delays it. Shots only the caller holds are read again for completeness.
    assert access is not None
    # store-v3 writes the dataset whole, so a shot only the caller holds is read again; store-v4 only those its
    # layers lack under their key (a held shot already kept isn't read from the share again).
    lacking = access.lacking(path, {shot for shot in in_memory if shot not in data}, keys, origins)
    try:
        reread = False
        for shot, filename in files:
            if shot in lacking:
                Pause.checkpoint(send)
                if from_raw(shot) is not None:
                    raw_time(shot)
                    continue  # (From the raw layer, before any file is announced: S3-2.)
                send({"kind": "file_started", "filename": filename})
                reread = True
                try:
                    read_txy(shot, filename, "cache save: read")
                except (OSError, ValueError, pd.errors.ParserError):
                    raise ValueError(f"Could not cache previously loaded shot {shot}") from None
                raw_time(shot)
                send({"kind": "file_finished", "filename": filename})
        verify_reason = "cache save: verifying"
        # Checked again only if files were read since the check above (else nothing came between).
        if reread and changed():
            raise ValueError("Folder changed before cache could be saved")
        if access.layered:
            if txy_guard is None:
                return
            access.write(path, txy_guard, data, fingerprint, problematic,
                         _dataset_info(data, fingerprint, names, listed_at, load_counts, unsettled, bool(had_dataset),
                                       folder_mtime_ns, txy_record, str(summary["signature"])),
                         keys, origins, _raw_list(raw_times, (entry[0] for entry in fingerprint)), txy_record,
                         cache_options or {}, _quietly(send) if quiet else send, hold=not quiet, seen_at=listed_at)
            return
        _write_dataset(store, path, guard, data, fingerprint, problematic, names, listed_at, load_counts,
                       unsettled, bool(had_dataset), budget, budget_set_at, send, raw_times, folder_mtime_ns,
                       txy_record, str(summary["signature"]))
    except Exception as exc:
        _save_failed(store, exc, send)


def _write_dataset(store: CacheStore, path: str, guard: SaveGuard, data: dict[int, Any],
                   fingerprint: list[tuple[int, int, int]], problematic: list[int], names: list[str],
                   listed_at: float, counts: dict[str, int], unsettled: int, had_dataset: bool,
                   budget: int | None, budget_set_at: float | None, send: Emit,
                   raw_times: dict[int, int] | None = None, folder_mtime_ns: int | None = None,
                   txy_record: dict[str, Any] | None = None, signature: str = "") -> None:
    """Save a folder's dataset to the disk cache within the budget (a pending save that doesn't fit),
    under the guard its job took when it started; ``cache_saved`` and ``disk_cached``, or the pending
    event. ``raw_times``: its shots' times, where known. ``folder_mtime_ns``: the folder's mtime before
    the listing (``_quick_mtime``; None: no quick check until a listing records one). ``txy_record``:
    which TXY it is made of (``helab_txy.record``; None: MATLAB's alone); ``signature`` the folder's (default:
    from its MATLAB TXY in ``fingerprint``). Raises on failure
    (``_save_failed``)."""
    from helab.utils.cache_store import DATASET_FORMAT, pack_dataset
    file = store.write_dataset_file(pack_dataset(data))
    info = {**_dataset_info(data, fingerprint, names, listed_at, counts, unsettled, had_dataset, folder_mtime_ns,
                            txy_record, signature),
            "format": DATASET_FORMAT, "disk_bytes": os.path.getsize(os.path.join(store.datasets_dir, file))}
    result = store.save_dataset(path, file, {
        "ram_bytes": sum(int(array.nbytes) for array in data.values()),
        "rows": sum(len(array) for array in data.values()), "shots": len(data),
        "fingerprint": [list(entry) for entry in fingerprint], "problematic": sorted(set(problematic)),
        "raw_times": _raw_list(raw_times or {}, (entry[0] for entry in fingerprint)),
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


def _dataset_info(data: dict[int, Any], fingerprint: list[tuple[int, int, int]], names: list[str], listed_at: float,
                  counts: dict[str, int], unsettled: int, had_dataset: bool, folder_mtime_ns: int | None,
                  txy_record: dict[str, Any] | None, signature: str) -> dict[str, Any]:
    """A saved load's ``info``: what its quick check and its listing need (a dataset's, or a store-v4 view's)."""
    record = txy_record or helab_txy.default_record()
    return {"saved_at": time.time(), "snapshot_at": listed_at,
            "signature": signature or helab_txy.matlab_signature(fingerprint,
                                                                 helab_txy.origins_from(record.get("origins"))),
            "action": "updated" if had_dataset else "created", txy_sources.TXY_FIELD: record,
            "counts": counts, "unsettled": unsettled, "kind": file_kinds.TXY.name,
            # Its TXY files' names, in fingerprint order, for the quick check's samples.
            "names": names, "folder_mtime_ns": folder_mtime_ns,
            # For the large-folder check before a later cached read.
            "txy_bytes": large_folder.estimate(fingerprint),
            "ram_bytes": sum(int(array.nbytes) for array in data.values())}


QUIET_KINDS = ("cache_saved", "disk_cached", "cache_full", "cache_approval", "cache_warning")


def _quietly(send: Emit) -> Emit:
    """``send`` without the cache events a plot choice's save mustn't give the folder's tab (Q19.3)."""
    def quiet(event: Any) -> None:
        if event.get("kind") not in QUIET_KINDS:
            send(event)
    return quiet


def _save_failed(store: CacheStore, exc: Exception, send: Emit) -> None:
    # A rejected save retired its file: the next cleanup deadline may be new.
    send({"kind": "cache_save_failed", "message": str(exc), "next_deadline": _deadline(store)})
    send({"kind": "cache_warning", "message": str(exc)})


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


def _pending_event(store: CacheStore, path: str, result: Any) -> PendingSaveEvent:
    """``cache_full`` (doesn't fit) or ``cache_approval`` (grows the cache over 80%) for a pending save."""
    from dataclasses import asdict
    event: PendingSaveEvent = {
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
