"""Saved analysis results (result caching R2): finding one for a run, and saving one, on the local
lane. Neither ever touches a source folder; both open only the local disk cache.

``result_find`` answers ``result_found`` (an exact match, or with ``family`` an outdated one of the
same plot and settings), ``result_missing`` or ``error`` (never "nothing saved"), each with the save
guard a later save of the run must still see (``guard``: the results' generation and the folder's
and its root's results epochs, taken now, when the run starts). The data goes to the helper's
private folder (``artifact``), which the app's reader thread reads, so the GUI process never opens
the store. ``result_save`` writes the packed data the app put in the private folder (``blob_file``)
as a result file and its row, within the disk budget, under that guard: ``result_saved`` or
``result_not_saved`` (its ``reason``). A folder without a disk cache (no data root, a pending
duplicate, an unsupported mount) has nothing saved and saves nothing (``ram_only``).
"""
from __future__ import annotations

import os
from typing import Any, cast

from helab.io_ops.events import (FolderResultsField, ResultCountField, ResultFoundEvent, ResultGuard,
                                 ResultMissingEvent)
from helab.io_ops.infra import Emit, emit
from helab.io_ops.stores import _deadline, _store_or_off, _usage


def _guard_fields(guard: Any) -> ResultGuard:
    return {"generations": dict(guard.generations), "epochs": dict(guard.epochs)}


def result_find(path: str, output: str, cache_options: dict[str, Any] | None, lookup: str, family: str = "",
                send: Emit = emit, *, verified_volumes: list[list[str]] | None = None) -> None:
    from helab.utils.cache_store import StoreError, StoreReadOnly
    store, off = _store_or_off(cache_options, send, path, local_lane=True, verified_volumes=verified_volumes)
    if store is None:
        if off:
            send({"kind": "result_missing", "ram_only": True})
            return
        raise ValueError("Disk cache unavailable")
    try:
        flags = store.read_prefs([path])[path]
        if flags.failed:
            raise ValueError(f"The folder's settings couldn't be read: {flags.error}")
        if flags.value and flags.value.get("no_cache"):
            send({"kind": "result_missing", "no_cache": True})
            return
        guard: ResultGuard | None
        try:
            guard = _guard_fields(store.start_result_job(path))
        except StoreReadOnly:
            guard = None  # (Read, never saved: a newer HeLab's store.)
        found = store.find_result(path, lookup, family)
        if found.failed:
            raise ValueError(found.error)
        if found.value is None:
            missing: ResultMissingEvent = {"kind": "result_missing"}
            if guard is not None:
                missing["guard"] = guard
            send(missing)
            return
        row = found.value.row
        artifact = os.path.join(output, "result.npz")
        with open(artifact, "wb") as handle:
            handle.write(found.value.data)
        if found.value.exact and not store.read_only:
            try:
                store.touch_result(path, lookup)
            except StoreError:
                pass  # (Only purges by age go by it.)
        event: ResultFoundEvent = {"kind": "result_found", "artifact": artifact, "exact": found.value.exact,
                                   "record": row["record"], "computed_at": row["computed_at"], "bytes": row["bytes"],
                                   "lookup": row["lookup"], "result_id": row["result_id"]}
        if guard is not None:
            event["guard"] = guard
        send(event)
    finally:
        store.close()


def result_save(path: str, cache_options: dict[str, Any] | None, blob_file: str, *, lookup: str, family: str,
                record: Any, analysis_id: str, action: str, computed_at: float, guard: dict[str, Any],
                send: Emit = emit, verified_volumes: list[list[str]] | None = None, label: str = "") -> None:
    from dataclasses import asdict
    from helab.utils.cache_store import SaveGuard, SaveRejected, StoreError
    store, off = _store_or_off(cache_options, send, path, local_lane=True, verified_volumes=verified_volumes)
    if store is None:
        if off:
            send({"kind": "result_not_saved", "reason": "ram_only", "message": "no disk cache for this folder",
                  "bytes": 0, "budget": None})
            return
        raise ValueError("Disk cache unavailable")
    try:
        with open(blob_file, "rb") as handle:
            packed = handle.read()
        file = store.write_result_file(packed)
        options = cache_options or {}
        try:
            saved = store.save_result(
                path, lookup, family, record, file,
                SaveGuard(dict(guard["generations"]), dict(guard["epochs"])), analysis_id=analysis_id,
                action=action, computed_at=computed_at, budget=options.get("budget"),
                budget_set_at=options.get("budget_set_at"), label=label)
        except SaveRejected as rejection:
            send({"kind": "result_not_saved", "reason": rejection.reason, "message": str(rejection),
                  "bytes": len(packed), "budget": None, "next_deadline": _deadline(store), **_usage(store)})
            return
        if not saved.saved and saved.pending_id:
            # Waits for the user's answer (Make room or Discard), with what Make room would remove.
            room: dict[str, Any] | None = None
            if saved.budget is not None:
                try:
                    room = asdict(store.result_room_plan(saved.pending_id, saved.budget))
                except (SaveRejected, StoreError):
                    room = None
            send({"kind": "result_pending", "pending_id": saved.pending_id, "path": path, "label": label,
                  "bytes": saved.bytes, "budget": saved.budget, "room": room, "next_deadline": _deadline(store),
                  **_usage(store)})
            return
        if not saved.saved:
            send({"kind": "result_not_saved", "reason": saved.reason, "message": "it doesn't fit the disk cache's budget",
                  "bytes": saved.bytes, "budget": saved.budget, "next_deadline": _deadline(store), **_usage(store)})
            return
        folder: FolderResultsField = ({} if saved.folder is None else
                                      {"folder_results": cast(ResultCountField, saved.folder.event())})
        send({"kind": "result_saved", "bytes": saved.bytes, "result_id": saved.result_id,
              "next_deadline": _deadline(store), **folder, **_usage(store)})
    finally:
        store.close()
