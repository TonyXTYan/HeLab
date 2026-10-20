"""Saving a folder from RAM (Live's save, ``load`` with ``save_memory``): no TXY read."""
from __future__ import annotations

import os
import time
from typing import Any, TYPE_CHECKING

from helab.io_ops import fingerprints, infra
from helab.io_ops.events import RawMtimeField
from helab.io_ops.fingerprints import _fingerprint_signature, _raw_list, _settled
from helab.io_ops.identity import _folder_identity, _location_identity
from helab.io_ops.infra import Emit, Heartbeat, Pause, _entry_stat, _is_dir, _read_gate, _scandir, _stat
from helab.io_ops.loading import _save_failed, _write_dataset
from helab.io_ops.stores import _data_root, _open_store
from helab.io_ops.summary import _summary
from helab.utils import file_kinds

if TYPE_CHECKING:
    from helab.utils.cache_store import SaveGuard


def save_held(path: str, send: Emit, cache_options: dict[str, Any] | None, held: list[list[int]],
              problematic: list[int], held_dir: str, *, identity: str = "", identity_root: str | None = None,
              no_cache: bool = False, recent: list[int] | None = None, output: str | None = None,
              raw_times: list[list[int]] | None = None) -> None:
    """Live's save: the folder's data the app holds in RAM written to the disk cache, without reading
    TXY files again. ``held`` is that data's fingerprint (unreadable shots included), its arrays
    are in ``held_dir`` (local files the app wrote), ``problematic`` its problematic shots,
    ``raw_times`` its shot times (``[shot, raw mtime_ns]``), saved as they are for the shots saved as
    held: their raw files aren't stat'ed (a shot read again gets its time anew).

    The folder is listed once. Every held file must still be there with the size and mtime it had
    when it was read (else ``shots_missing``: missing or changed; TXY files are written once), and
    the folder must be the session's (``identity``, checked as Live does: reason root), before
    ``loaded`` names the held shots and the dataset is saved under a load's guard, budget and
    pending-save rules. Files the folder has and the data doesn't (Live hasn't read them yet) count
    as unsettled, so the next quick check of the cache is a full one.

    Except, by Tony's decision, the shots Live itself read recently (``recent``, as for
    ``live_check``): one of those that changed is read again before the save, if settled by age and
    unchanged while read (its new data sent as a ``shot`` artifact in ``output``; ``live_reread``),
    else saved as held and counted as unsettled; it isn't a mismatch."""
    import numpy as np
    import pandas as pd
    from helab.utils.cache_store import StoreError
    store = _open_store(cache_options, send, path)
    try:
        guard: SaveGuard | None = None
        if store is not None:
            try:
                guard = store.start_dataset_job(path, ("summaries",))
            except StoreError as exc:
                send({"kind": "cache_warning", "message": f"Disk cache can't be updated: {exc}"})
            prefs = store.read_prefs([path])[path]
            if prefs.failed:
                send({"kind": "cache_warning", "message": f"Disk cache not used: the folder's settings couldn't be "
                                                         f"read ({prefs.error})"})
            no_cache = no_cache or prefs.failed or bool(prefs.value and prefs.value.get("no_cache"))
        fingerprint = sorted((int(shot), int(size), int(modified)) for shot, size, modified in held)
        known = {shot for shot, _, _ in fingerprint}
        listed: dict[int, tuple[int, int]] = {}
        file_names: dict[int, str] = {}
        raw_entries: dict[int, os.DirEntry[str]] = {}  # For the times of shots read again.
        found: dict[str, set[int]] = {}  # (For the summary of a save that reads shots again.)
        has_dirs = False
        listed_at = time.time()
        beat = Heartbeat(send, "listing")
        with _scandir(path, "save: listing") as directory:
            for entry in directory:
                beat()
                if matched := file_kinds.match(entry.name):
                    found.setdefault(matched[0].name, set()).add(matched[1])
                    if matched[0].loaded:
                        info = _entry_stat(entry, "save: checking")
                        listed[matched[1]] = (info.st_size, info.st_mtime_ns)
                        file_names[matched[1]] = entry.name
                    elif matched[0] is file_kinds.RAW:
                        raw_entries[matched[1]] = entry
                elif not has_dirs and _is_dir(entry):
                    has_dirs = True

        def mismatch(reason: str, shots: list[int]) -> None:
            send({"kind": "shots_missing", "reason": reason, "missing": shots[:20], "missing_count": len(shots),
                  "known_count": len(known), "listed_count": len(listed)})
        if missing := sorted(known - set(listed)):
            mismatch("missing", missing)
            return
        if identity:
            current, _ = _folder_identity(path, identity_root, "save: identity")
            if current and current != identity:
                mismatch("root", sorted(known))
                return
        changed = [shot for shot, size, modified in fingerprint if listed[shot] != (size, modified)]
        rereadable = {int(shot) for shot in recent or ()} if output else set()
        if stale := [shot for shot in changed if shot not in rereadable]:
            mismatch("changed", stale)
            return
        data = {shot: np.load(os.path.join(held_dir, f"{shot}.npy"), allow_pickle=False)
                for shot in sorted(known) if os.path.exists(os.path.join(held_dir, f"{shot}.npy"))}
        unsettled = len(set(listed) - known)
        problematic = sorted(set(problematic) & known)
        # Recently read by Live and changed since: read again, once settled (else saved as held).
        was = {shot: (size, modified) for shot, size, modified in fingerprint}
        items = [(shot, *listed[shot]) for shot in changed]
        settled = {item[0] for item in _settled(items)}
        replaced: dict[int, tuple[int, int, int]] = {}
        reread: list[dict[str, Any]] = []
        times = file_kinds.raw_times(raw_times)

        def now(filename: str, reason: str) -> tuple[int, int]:
            info = _stat(filename, reason)
            return info.st_size, info.st_mtime_ns
        for item in items:
            shot = item[0]
            filename = os.path.join(path, file_names[shot])
            if shot not in settled:
                unsettled += 1
                continue
            Pause.checkpoint(send)
            try:
                array, invalid = None, False
                if now(filename, "save: before read again") == item[1:]:
                    _read_gate(filename)
                    frame = infra._read_txy_file(filename, "save: read again")
                    invalid = bool(frame.isna().any().any())
                    array = np.asarray(frame.dropna(), dtype=np.float64)
                    if now(filename, "save: after read again") != item[1:]:
                        array = None
                if array is None:
                    unsettled += 1  # Changed while read: saved as held.
                    continue
                assert output is not None
                artifact = os.path.join(output, f"{shot}.npy")
                np.save(artifact, array, allow_pickle=False)
                data[shot] = array
                problematic = sorted((set(problematic) - {shot}) | ({shot} if invalid else set()))
                times.pop(shot, None)
                if (found_time := fingerprints._raw_mtime(raw_entries.get(shot), "save: shot time")) is not None:
                    times[shot] = found_time
                known_time: RawMtimeField = {"raw_mtime": times[shot]} if shot in times else {}
                send({"kind": "shot", "shot": shot, "artifact": artifact, "fingerprint": list(item),
                      "problematic": invalid, **known_time})
            except (OSError, ValueError, pd.errors.ParserError):
                data.pop(shot, None)  # Unreadable now: known by its new fingerprint, as a load keeps it.
                problematic = sorted(set(problematic) | {shot})
                times.pop(shot, None)  # (The held time was the old file's.)
            replaced[shot] = item
            reread.append({"shot": shot, "path": filename, "old": list(was[shot]), "new": list(item[1:]),
                           "read": shot in data})
        fingerprint = sorted(replaced.get(entry[0], entry) for entry in fingerprint)
        names = [file_names[shot] for shot, _, _ in fingerprint]
        saving = store is not None and guard is not None and not no_cache and bool(data)
        had_dataset = False
        if saving:
            assert store is not None
            row = store.read_dataset_row(path)
            had_dataset = row.value is not None
        kept = sorted(set(data) - set(replaced))
        again = [entry for entry in reread if entry["read"]]
        counts = {"reused_memory": len(kept), "reused_disk": 0, "new": 0, "modified": len(replaced), "removed": 0,
                  "read": len(replaced), "new_loaded": 0, "modified_loaded": len(again)}
        signature = _fingerprint_signature([list(entry) for entry in fingerprint])
        if replaced:
            # A new fingerprint: the folder's summary as of this listing, before ``loaded``, as a Live
            # check sends it (the app adopts it as Live's, so the folder's status matches the data).
            summary = _summary(path, found, {file_kinds.TXY.name: sum(entry[1] for entry in fingerprint)}, has_dirs,
                               False, fingerprint, listed_at)
            summary["unsettled"] = unsettled
            send({"kind": "scan_summary", "status": summary})
        send({"kind": "load_source", "source": "updated", "cache_reason": ""})
        send({"kind": "loaded", "rows": sum(len(data[entry["shot"]]) for entry in again),
              "bytes": sum(data[entry["shot"]].nbytes for entry in again), "files": len(data),
              "loaded_at": time.time(),
              "total_files": len(listed), "failed_files": len(known) - len(data), "unsettled_files": unsettled,
              "problematic": problematic, "source": "updated", "cached": False, **_data_root(store, path),
              "disk_cache_pending": saving, "cache_info": {}, "load_counts": counts,
              "cache_reason": f"Saved {len(kept)} shots from memory; " + (
                  f"read {len(replaced):,} that changed after Live read them again" if replaced else "no TXY file read"),
              "live_reread": reread, "raw_times": _raw_list(times, replaced),
              "fingerprint": [list(entry) for entry in fingerprint], "memory_shots": kept,
              "base_signature": signature, "signature": signature,
              "listed_at": listed_at, "names": names, "identity": _location_identity(path, "save: identity")})
        if not saving:
            return
        assert store is not None and guard is not None
        try:
            _write_dataset(store, path, guard, data, fingerprint, problematic, names, listed_at, counts, unsettled,
                           had_dataset, (cache_options or {}).get("budget"), (cache_options or {}).get("budget_set_at"),
                           send, times)
        except Exception as exc:
            _save_failed(store, exc, send)
    finally:
        if store is not None:
            store.close()
