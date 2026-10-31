"""Disk cache maintenance (``cache_admin``) and moving the cache (``cache_move``)."""
from __future__ import annotations

import contextlib
import os
import time
from typing import Any

from helab.io_ops import helab_txy, stores
from helab.io_ops.events import AdminResultFields
from helab.io_ops.infra import Emit, Heartbeat, emit
from helab.io_ops.markers import _location_path, _root_rows
from helab.io_ops.stores import (_cache_info, _deadline, _raw_removed_event, _removal_events, _removed_event,
                                 _results_removed_event, _store_fields,
                                 _usage)


# Why a folder's constants weren't saved (``cache_admin`` "constants"; the app keeps them for the
# session, and saves them again when a root is found or volumes are verified). FolderCache has
# the same texts (it doesn't import this module).
NO_ROOT_CONSTANTS = "no .helab-root found here or above"
UNVERIFIED_CONSTANTS = "its drive isn't verified yet this session"

ADMIN_ACTIONS = ("inventory", "clear", "purge", "trim", "adopt", "discard", "sweep", "budget", "prefs",
                 "convert_prefs", "clear_prefs", "clear_converted_txy", "mark_used",
                 "constants", "presets", "forget_root", "root_same", "clear_root", "clear_results",
                 "clear_root_results", "adopt_result", "discard_result", "identity", "clear_raw")


def cache_admin(cache_options: dict[str, Any], action: str, send: Emit = emit, **params: Any) -> None:
    """Disk cache maintenance on the local lane; never touches source folders.

    Every removal sends ``removed`` (kinds and paths), and every action ends with
    ``admin_result`` carrying the store's next cleanup deadline. ``sweep`` also
    deletes the old diskcache folders (at startup).
    """
    from dataclasses import asdict
    from helab.utils.cache_store import (
        KINDS, CacheStore, Kind, SaveRejected, StoreError, StoreReadOnly, remove_old_caches,
    )
    if action not in ADMIN_ACTIONS:
        raise ValueError(f"Unknown cache action: {action}")
    if action == "mark_used":
        # The converted TXY's last uses loads didn't write (Q30.3, A30.4); the index only, not the store.
        send({"kind": "admin_result", "action": action, "next_deadline": None,
              "unwritten": helab_txy.mark_used(list(params.get("marks") or []))})
        return
    root = cache_options["directory"]
    budget = params.get("budget", cache_options.get("budget"))
    # When the app set it: a budget set later (e.g. lowered while this job waited) wins.
    budget_set_at = params.get("budget_set_at", cache_options.get("budget_set_at"))
    result: AdminResultFields = {}
    old: list[str] = []
    if action == "sweep":
        old = remove_old_caches(os.path.dirname(os.path.abspath(root)), Heartbeat(send, "cleaning up"))
    # A constants or converter-flag write trusts only the volume hints this session verified, like the other local
    # writes keyed by a source folder (scan history, subfolder status). ``prefs`` (the folder flags)
    # names a source folder too but trusts every hint, by design (cache-store.md: "flags still trust
    # every hint"); the other actions name no source folder.
    verified_volumes = params.get("verified_volumes") if action in ("constants", "convert_prefs") else None
    with stores._cache_store(root, local_lane=True, verified_volumes=verified_volumes,
                             offline=bool(cache_options.get("offline"))) as store:
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
                for entry in inventory["pending_results"]:
                    with contextlib.suppress(SaveRejected, StoreError):
                        entry["room"] = asdict(store.result_room_plan(entry["pending_id"], int(budget)))
            inventory["roots"] = _root_rows(store, send)
            # HeLab's own TXY under the cache and temp folders: not in the store, outside the budget (Q12.3, Q27.5).
            inventory["converted_txy"] = helab_txy.converted_summary(
                helab_txy.converted_roots(root, str(params.get("temps") or "")))
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
            # (Kind ``raw``: store-v4's raw layers, cleared with everything when no kinds are named.)
            asked = tuple(params.get("kinds") or (*KINDS, "raw"))
            unknown = set(asked) - set(KINDS) - {"raw"}
            if unknown:
                raise ValueError(f"Unknown cache kinds: {sorted(unknown)}")
            kinds: tuple[Kind, ...] = tuple(kind for kind in KINDS if kind in asked)
            if kinds:
                send(_removed_event(store.remove(kinds)))
            if "raw" in asked and store.layout >= 4:
                raw = store.remove_raw()
                send(_raw_removed_event(None, raw.rows, raw.bytes))
        elif action == "purge":
            cutoff = float(params["cutoff"])
            if params["what"] == "results":
                # Saved analysis results not shown since ``cutoff`` (R2).
                purged = store.remove_results(cutoff=cutoff)
                send(_results_removed_event(purged))
                result["removed"] = {"results": purged.results}
                result["bytes"] = purged.bytes
                removals = []
            elif params["what"] == "datasets":
                removals = [store.purge_datasets(cutoff)]
            elif params["what"] == "records":
                removals = store.purge_records(cutoff, bool(params.get("include_failures")))
            else:
                raise ValueError(f"Unknown purge: {params['what']}")
            for removal in removals:
                send(_removed_event(removal))
            if removals:
                result["removed"] = {kind: len(removal.paths or ()) for removal in removals for kind in removal.kinds}
                result["bytes"] = sum(removal.dataset_bytes for removal in removals)
        elif action == "trim":
            removal = store.trim(int(budget or params["budget"]), budget_set_at)
            send(_removed_event(removal))
            result.update({"datasets": removal.datasets, "bytes": removal.dataset_bytes})
        elif action == "adopt":
            try:
                adopted = store.adopt_pending(params["pending_id"], budget=budget, budget_set_at=budget_set_at,
                                              expected_room=params.get("room_paths"),
                                              make_room=bool(params.get("make_room")))
            except SaveRejected as rejection:
                result.update({"adopted": False, "rejected": rejection.reason, "message": str(rejection)})
            else:
                if adopted.removal is not None:
                    for event in _removal_events(adopted.removal):
                        send(event)
                result.update({"adopted": adopted.adopted, "path": adopted.path, "bytes": adopted.bytes,
                               "room": None if adopted.room is None else asdict(adopted.room)})
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
        elif action == "convert_prefs":
            # The converter's flags for one folder (``write_beside``, Q9.7): set when given, newest
            # choice wins; without it, read. A folder without a data root has none (an error).
            path = str(params["path"])
            if params.get("write_beside") is None:
                read = store.read_convert_prefs([path])[path]
                if read.status == "error":
                    raise StoreError(read.error)
                prefs = read.value or {"write_beside": False, "set_at": 0.0}
            else:
                prefs = store.set_convert_prefs(path, bool(params["write_beside"]),
                                                float(params.get("set_at") or time.time()))
            send({"kind": "convert_prefs", "path": path, "prefs": prefs})
        elif action == "constants":
            # A folder's own constants (Folder constants…): every value it sets, newest choice wins.
            from helab.utils.cache_paths import UnresolvedRemotePath, _inside, _normal
            from helab.utils.data_roots import NoDataRoot
            path = str(params["path"])
            try:
                saved_constants = store.set_constants(path, dict(params.get("values") or {}),
                                                      float(params.get("set_at") or time.time()))
            except UnresolvedRemotePath as exc:
                # No disk cache for this folder (no data root, an unsupported mount), or not yet
                # (its volume not verified this session): the app keeps its values for the session
                # only, and saves them again when roots are found or volumes verified.
                unverified = isinstance(exc, NoDataRoot) and any(
                    _inside(_normal(path), _normal(mount)) for mount in store._unverified_mounts)
                reason = (UNVERIFIED_CONSTANTS if unverified
                          else NO_ROOT_CONSTANTS if isinstance(exc, NoDataRoot) else str(exc))
                send({"kind": "folder_constants", "folders": {}, "session_only": {path: reason}})
            else:
                send({"kind": "folder_constants", "folders": {path: saved_constants}})
        elif action == "presets":
            # The user's presets: write these rows (newest choice wins each), then read them all.
            # (Only a read when there's nothing to write: a read-only store still answers it.) Only
            # to the store they were meant for: in another (one recreated since), whose names the
            # app hasn't seen, they could replace a preset unasked; it reads that one instead.
            rows = list(params.get("rows") or ()) if params.get("store") == store.store_id else []
            written = store.write_presets(rows) if rows else []
            stored = store.read_presets()
            if stored.failed:
                send({"kind": "presets", "saved": written, "error": stored.error, "store": store.store_id})
            else:
                send({"kind": "presets", "saved": written, "rows": stored.value or [],
                      "store": store.store_id})
        elif action == "clear_converted_txy":
            # The user asked (Settings → Cache's Clear, confirmed): HeLab's TXY under the cache and temp folders.
            roots = helab_txy.converted_roots(root, str(params.get("temps") or ""))
            gone = sum(helab_txy.clear_converted(converted)["bytes"] for converted in roots.values())
            send({"kind": "removed", "kinds": ["converted_txy"], "paths": None, "datasets": 0, "bytes": gone})
            result["converted_txy"] = helab_txy.converted_summary(roots)
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
        elif action == "clear_raw":
            # The user asked (Settings › Cache's Clear raw pulses, confirmed): every folder's raw layers, or
            # these folders' (``paths``); store-v4 only. Fenced: a batch being saved can't bring them back.
            paths = params.get("paths")
            raw = store.remove_raw(None if paths is None else [str(path) for path in paths])
            send(_raw_removed_event(raw.paths, raw.rows, raw.bytes))
            result.update({"raw": raw.rows, "bytes": raw.bytes})
        elif action == "clear_root":
            # Everything cached below one data root on this computer but its saved results (Clear
            # cached analysis, Tony 2026-10-22); roots, flags and marker stay.
            for event in _removal_events(store.clear_root(str(params["uuid"]))):
                send(event)
        elif action == "clear_root_results":
            # A data root's Clear cached analysis: its saved results only (R2).
            cleared = store.remove_results(root=str(params["uuid"]))
            send(_results_removed_event(cleared))
            result.update({"results": cleared.results, "bytes": cleared.bytes})
        elif action == "adopt_result":
            # A waiting result's Make room (R2): only other saved results make room, never cached data.
            # It names the store it waits in: another (recreated since) doesn't have it.
            try:
                if params.get("store") and params["store"] != store.store_id:
                    raise SaveRejected("gone", "This save waited in a disk cache recreated since")
                taken = store.adopt_pending_result(params["pending_id"], budget=budget, budget_set_at=budget_set_at,
                                                   make_room=bool(params.get("make_room")),
                                                   expected_room=params.get("room_ids"))
            except SaveRejected as rejection:
                result.update({"adopted": False, "rejected": rejection.reason, "message": str(rejection)})
            else:
                if taken.removal is not None:
                    send(_results_removed_event(taken.removal, evicted=True))
                result.update({"adopted": taken.adopted, "path": taken.path, "bytes": taken.bytes,
                               "room": None if taken.room is None else asdict(taken.room)})
                if taken.adopted:
                    result["result_id"] = taken.result_id
                    result["folder_results"] = {folder: count.event()
                                                for folder, count in taken.folders.items()}
        elif action == "discard_result":
            result["discarded"] = store.discard_pending_result(params["pending_id"])
        elif action == "clear_results":
            # The Cache tab's Clear cached analysis: every saved result; datasets and records stay.
            cleared = store.remove_results()
            send(_results_removed_event(cleared))
            result.update({"results": cleared.results, "bytes": cleared.bytes})
        elif action == "root_same":
            # Same folder (D4): the pending location uses the root's cached data from now on.
            location, identifier = str(params["location"]), str(params["uuid"])
            result["confirmed"] = store.confirm_root(location, identifier)
            if result["confirmed"]:
                found = store.root_at(location)
                send({"kind": "root_confirmed", "location": location, "uuid": identifier,
                      "path": _location_path(store, location), "label": found[1] if found else ""})
        elif action == "identity":
            pass  # Which store is in the cache folder now: its ``store`` (FolderCache.store_answer's probe).
        elif action == "budget":
            if budget is not None and budget_set_at is not None:
                # Lowering it (``fit``): not recorded if the data cached by now doesn't fit.
                active = store.lower_budget(int(budget), float(budget_set_at), fit=bool(params.get("fit")))
                result.update({"budget": active if active is not None else budget, "recorded": active is not None})
        send({"kind": "admin_result", "action": action, **result, **_store_fields(store),
              "next_deadline": _deadline(store), **_usage(store)})


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
        # (``layout``: the live store's, so it is the move's primary: C2-6. The app sends it.)
        record = mover.start(move["from"], move["to"], app_dir, move["method"], move.get("id", ""),
                             move.get("layout"))
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
        from helab.utils.settings_defaults import DIR_CACHES_SETTING, read_setting
        settings = open_settings(move["settings"])
        unsaved: list[str] = []

        def write(path: str) -> bool:
            if write_cache_setting(settings, path):
                return True
            unsaved.append(path)  # The attempted value may linger in memory here, never on disk.
            return False
        message = mover.recover(app_dir, lambda: str(read_setting(settings, DIR_CACHES_SETTING, typed=True)), write)
        # Usable only if the setting HeLab will read names the store: never after a failed write.
        usable = not unsaved and mover.usable_after_recovery(
            app_dir, str(read_setting(settings, DIR_CACHES_SETTING, typed=True)))
        send({"kind": "move_recovered", "message": message, "usable": usable})
    else:
        raise ValueError(f"Unknown cache move action: {action}")
