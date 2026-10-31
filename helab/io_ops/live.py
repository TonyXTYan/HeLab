"""Live checks (``load`` with ``live``): one folder stat, else a names-only listing."""
from __future__ import annotations

import os
import time
from typing import Any

from helab.io_ops import fingerprints, helab_txy, infra
from helab.io_ops.events import LiveState, ProgressEvent, RawMtimeField
from helab.io_ops.fingerprints import (DEFAULT_CHECK_LEVEL, _clock_ahead, _fingerprint_signature, _raw_list,
                                       _sample_indices, _settled)
from helab.io_ops.identity import _folder_identity
from helab.io_ops.infra import Emit, Heartbeat, Pause, _is_dir, _read_gate, _scandir, _stat, emit
from helab.io_ops.summary import _summary
from helab.utils import file_kinds, txy_sources
from helab.utils.time_format import span


def _stop_if_ahead(path: str, files: list[tuple[int, int, int]], send: Emit) -> None:
    """New files dated in the future (another computer's clock ahead of ours) are never settled, so
    Live would wait for them for as long as the clocks differ: the check fails instead, as an error
    stop (Live keeps its data, says why, and offers Retry), by Tony's decision (2026-10-22, R-22)."""
    if ahead := _clock_ahead(path, files, send):
        raise ValueError(f"the folder's new files are dated {span(ahead)} ahead of this computer's clock: "
                         "the computers' clocks are out of sync — Retry")


def live_check(path: str, output: str, send: Emit = emit, memory: list[list[int]] | None = None,
               known: list[list[int]] | None = None, since: int | None = None, *,
               identity: str = "", seen: list[list[int]] | None = None,
               check_level: str = DEFAULT_CHECK_LEVEL, listed_mtime: int | None = None,
               seen_names: list[str] | None = None, identity_root: str | None = None,
               recent: list[int] | None = None, txy: dict[str, Any] | None = None,
               memory_origins: dict[str, str] | None = None, helab_since: dict[str, Any] | None = None) -> None:
    """One check of a folder watched live: new settled TXY files are read and sent like a load's.

    ``memory`` lists ``[shot, size, mtime_ns]`` for the shots the caller holds; TXY files are
    written once, so they are trusted once the folder is shown to be the same one. An empty
    list is Live started before the folder's first shot: every TXY file found is new. ``known``
    lists shots the caller knows but couldn't read: read again only if they changed. ``since``
    is the folder's mtime (ns) the previous check said is safe to compare: while the folder
    still has it, nothing was added or removed, and one stat is the whole check.

    Otherwise the folder is listed by name. Before held shots are reused, the folder must still
    be the session's (``identity``: its data root, else its location) and a sample of held shots
    (as the check level samples cached data) must keep their sizes and mtimes; held shots it no
    longer lists, a sample that changed or another folder stop the check with ``shots_missing``
    (``reason``: missing, changed or root). Only files the caller doesn't hold are stat'ed. A new
    file is read only once it is settled by age and has shown the same size and mtime on the
    previous check too (``seen``): stale or coarse metadata can't make a file being written look
    finished twice a check apart. (Metadata only: its content isn't checked.) It is stat'ed again
    just before and after it is read. Files not read yet are counted as still being written and
    sent back (``live_seen``). Nothing new: ``live_unchanged``; else ``loaded`` with
    ``memory_shots`` (source ``updated``). The disk cache is neither read nor written: the app
    saves the data from RAM (``save_held``), every N new shots and when Live stops.

    While files are still being written the folder isn't listed every check: when its mtime is
    still the one the last listing saw (``listed_mtime``, sent back as ``live_listed_mtime``),
    nothing was added or removed, and only the files that listing saw being written
    (``seen_names``, sent back as ``live_seen_names``) are stat'ed. Once one of them is ready to
    read, the check lists the folder as above. The identity check reads only the marker the first
    listing found (``identity_root``, sent back as ``live_identity_root``; "": none, the location).

    ``recent`` names the held shots Live itself read recently (``LiveController.LIVE_REREAD_SECONDS``,
    by Tony's decision): one of those that changed (its writer paused longer than the settle age, so
    Live read it unfinished) is read again like a new file, once settled and unchanged a check apart,
    and replaces the held one (``live_reread``: its old and new size and mtime) instead of stopping
    the check. Every listing stats the ``recent`` shots besides the sample, so a change to one the
    sample leaves out is still found; until it is read it is waiting (``live_seen``).
    Other held shots that changed still stop it (a change long after reading suggests a remount or a
    copy).

    HeLab's TXY (Q6.6) are read as the load's ``txy`` asks (``helab_txy``): found in HeLab's folders
    or beside, current only, under the same settle rules; a held shot keeps the kind of TXY it was read
    from while that TXY is there (``memory_origins``). The folders' state and the profile asked for
    (``live_helab``, sent back as ``helab_since``) must be unchanged too before one stat (or the pending
    files) is the whole check, so a shot converted since, or a profile change, is found. Only MATLAB's
    TXY, written once, feed the mismatch rule: a held shot read from HeLab's TXY that is gone, changed or
    no longer current (cleared, converted again) is read again from the TXY the source takes now, like a
    new file, or dropped when there is none.
    """
    started = time.monotonic()
    if memory is None:
        raise ValueError("Live needs the folder's loaded data — Retry")
    try:
        folder = _stat(path, "live: folder")
    except FileNotFoundError:
        raise OSError("Folder not found — is its drive connected?") from None
    # A folder modified this close to the check (or later: another computer's clock) may change again
    # within the same timestamp tick, which the next check's stat wouldn't see: that check lists it.
    # One margin with the quick check's (``fingerprints.RACY_SECONDS``, codebase review 2, C-12).
    racy = abs(time.time() - folder.st_mtime) < fingerprints.RACY_SECONDS
    held = {int(shot): (int(size), int(modified)) for shot, size, modified in memory}
    rereadable = {int(shot) for shot in recent or ()} & set(held)
    txy = dict(txy or {})
    txy_source = txy["source"] = txy_sources.requested_source(txy.get("source"))
    held_origins = {shot: origin for shot, origin in helab_txy.origins_from(memory_origins).items() if shot in held}
    # HeLab's folders now: unchanged since the last check, nothing was converted since (``helab_since``).
    helab_key = ""
    helab_state: list[list[Any]] = []
    wanted_hash, wanted_tag = str(txy.get("profile_hash") or ""), str(txy.get("profile_tag") or "")
    if txy_sources.wants_helab(txy_source):
        helab_key = _helab_key(path, txy)
        helab_state = helab_txy.folder_state(helab_txy.folders(path, txy, helab_key), time.time())
    since_helab = helab_since if isinstance(helab_since, dict) else {}
    # (No HeLab folder now nor then: nothing to compare, whatever the profile.)
    helab_same = (helab_txy.state_unchanged(since_helab.get("folders", []), helab_state)
                  and (not helab_state or (since_helab.get("profile_hash"), since_helab.get("profile_tag", ""))
                       == (wanted_hash, wanted_tag))) \
        if txy_sources.wants_helab(txy_source) else True

    current_identity = ""
    current_root: str | None = identity_root
    waiting: list[list[int]] = []  # New files not read yet, as stat'ed now (the next ``seen``).
    file_names: dict[int, str] = {}  # Their names.

    def state(listed: bool, unsettled: int, safe: bool) -> LiveState:
        # ``live_since``: what the next check may compare the folder's mtime with (None: list it).
        return {"live_since": folder.st_mtime_ns if safe and not racy and not unsettled else None,
                "live_listed": listed, "live_seconds": time.monotonic() - started,
                "unsettled_files": unsettled, "live_identity": current_identity, "live_seen": waiting,
                "live_seen_names": [file_names[int(entry[0])] for entry in waiting],
                # The folder's mtime as of this check's listing (or the last one's), unless racy.
                "live_listed_mtime": None if racy else folder.st_mtime_ns,
                "live_identity_root": current_root,
                "live_helab": {"folders": helab_state, "profile_hash": wanted_hash, "profile_tag": wanted_tag,
                               "key": helab_key,
                               "key_asked": bool(txy.get("key_asked")) or (not txy.get("key")
                                                                           and bool(txy.get("cache_directory")))}}

    if since is not None and since == folder.st_mtime_ns and helab_same:
        send({"kind": "live_unchanged", **state(False, 0, True), "total_files": len(held)})
        return
    previous = {int(shot): (int(size), int(modified)) for shot, size, modified in seen or ()}
    if (listed_mtime is not None and listed_mtime == folder.st_mtime_ns and not racy and seen and helab_same
            and seen_names is not None and len(seen_names) == len(seen)):
        # Nothing added or removed since the last listing: the files it saw being written are looked at.
        pending: list[tuple[int, int, int]] | None = []
        for (shot, _, _), name in zip(seen, seen_names):
            try:
                info = _stat(os.path.join(path, name), "live: pending file")
            except FileNotFoundError:
                pending = None  # (Gone: the listing says what's there now.)
                break
            assert pending is not None
            pending.append((int(shot), info.st_size, info.st_mtime_ns))
            file_names[int(shot)] = name
        if pending is not None:
            _stop_if_ahead(path, pending, send)
            aged = {item[0] for item in _settled(pending)}
            if not any(item[0] in aged and previous.get(item[0]) == item[1:] for item in pending):
                waiting[:] = [list(item) for item in pending]
                send({"kind": "live_unchanged", **state(False, len(pending), False),
                      "total_files": len(set(held) | {int(entry[0]) for entry in known or ()}
                                         | {item[0] for item in pending})})
                return
        file_names.clear()
    found: dict[str, set[int]] = {}
    names: dict[int, str] = {}
    raw_entries: dict[int, os.DirEntry[str]] = {}  # For new shots' times (``_raw_mtime``).
    beside_entries: dict[int, os.DirEntry[str]] = {}  # HeLab's TXY beside the raw files.
    matlab: dict[int, str] = {}
    has_dirs = False
    listed_at = time.time()
    beat = Heartbeat(send, "listing")
    with _scandir(path, "live: listing") as directory:
        for entry in directory:
            beat()
            if matched := file_kinds.match(entry.name):
                kind, shot = matched
                found.setdefault(kind.name, set()).add(shot)
                if kind.loaded:
                    matlab[shot] = entry.path
                elif kind is file_kinds.RAW:
                    raw_entries[shot] = entry
                elif kind is file_kinds.HELAB_TXY and helab_txy.beside_wanted(entry.name, txy):
                    beside_entries[shot] = entry
            elif not has_dirs and _is_dir(entry):
                has_dirs = True
    helab_found: dict[int, helab_txy.HelabShot] = {}
    if txy_sources.wants_helab(txy_source):
        trusted = {shot: (*held[shot], origin) for shot, origin in held_origins.items()}
        helab_found = helab_txy.find(path, txy, helab_key, beside_entries, raw_entries, trusted,
                                     helab_txy.could_take(txy_source, raw_entries, matlab, held_origins))
    # Each shot's TXY as the source asks; a held shot keeps its kind while that TXY is there (one held from
    # MATLAB's too: "" its origin, so a HeLab TXY converted since doesn't replace it).
    chosen = helab_txy.compose(txy_source, matlab, helab_found, {shot: held_origins.get(shot, "") for shot in held})
    origins = {shot: origin for shot, (_, origin) in chosen.items() if origin}

    def pending_name(shot: int, filename: str, origin: str) -> str:
        # The pending check joins a name to the folder: HeLab's in their own folder are named in full.
        return filename if origin and os.path.dirname(filename) != os.path.dirname(
            beside_entries[shot].path if shot in beside_entries else os.path.join(path, "_")) \
            else os.path.basename(filename)
    for shot, (filename, origin) in chosen.items():
        names[shot] = filename
        file_names[shot] = pending_name(shot, filename, origin)
    # A held shot kept on MATLAB's TXY (the held-kind rule) that the source takes from HeLab's now, one
    # converted during Live under HeLab priority: read again from HeLab's like a changed shot, as a HeLab-held
    # shot converted again is, instead of at the folder's next load (A39.2, Q38.2: Tony 2026-10-31). Its MATLAB
    # TXY, written once, still feeds the mismatch rule (``names``) until then.
    switching: dict[int, str] = {}
    for shot in sorted(set(held) - set(held_origins)):
        if (shot in helab_found and chosen.get(shot, ("", "?"))[1] == ""
                and txy_sources.choose(txy_source, shot in matlab, True) == txy_sources.HELAB):
            converted_shot = helab_found[shot]
            switching[shot] = converted_shot.file
            origins[shot] = txy_sources.helab_origin(converted_shot.profile_hash)
            file_names[shot] = pending_name(shot, converted_shot.file, origins[shot])

    def mismatch(reason: str, shots: list[int]) -> None:
        send({"kind": "shots_missing", "reason": reason, "missing": shots[:20], "missing_count": len(shots),
              "known_count": len(held), "listed_count": len(names)})

    # Held shots read from HeLab's TXY (Q6.6): not written once like MATLAB's, so never a mismatch. One whose
    # TXY the source takes now is the one it was read from, unchanged, is kept; another is read again like
    # a new file (``rereads``) or, with no TXY to take now, dropped.
    held_helab = set(held_origins)
    dropped = sorted(shot for shot in held_helab if shot not in names)
    helab_rereads: list[tuple[int, int, int]] = []
    for shot in sorted(held_helab - set(dropped)):
        origin = origins.get(shot, "")
        found_shot = helab_found.get(shot)
        if origin and found_shot is not None:
            stat_now: tuple[int, int] | None = (found_shot.size, found_shot.mtime_ns)
        else:
            try:
                info = _stat(names[shot], "live: held from HeLab's")
                stat_now = (info.st_size, info.st_mtime_ns)
            except FileNotFoundError:
                stat_now = None
        if stat_now is None:
            dropped.append(shot)
        elif origin != held_origins[shot] or stat_now != held[shot]:
            helab_rereads.append((shot, *stat_now))
    helab_rereads += [(shot, helab_found[shot].size, helab_found[shot].mtime_ns) for shot in switching]
    # Read again because HeLab's TXY of them is new (converted since), not because a writer paused: said apart.
    converted = {item[0] for item in helab_rereads}
    missing = sorted(set(held) - set(names) - held_helab)
    if missing:
        mismatch("missing", missing)
        return
    current_identity, current_root = _folder_identity(path, identity_root)
    if identity and current_identity and current_identity != identity:
        # Another folder at this path (a remount, another drive): nothing held is its.
        mismatch("root", sorted(held))
        return
    beat = Heartbeat(send, "verifying")
    ordered = sorted(set(held) - held_helab)
    indices = _sample_indices(len(ordered), check_level)
    sampled = [ordered[index] for index in (range(len(ordered)) if indices is None else indices)]
    # Held shots Live read recently (a writer may resume one after a newer shot arrived) and those the
    # previous check saw changed (to read again once unchanged): looked at besides the sample.
    sampled += sorted((((set(previous) & set(held)) | rereadable) - held_helab) - set(sampled))
    changed: list[int] = []
    rereads: list[tuple[int, int, int]] = []  # Recently read held shots that changed, as stat'ed now.
    for shot in sampled:
        try:
            info = _stat(names[shot], "live: sample")
        except FileNotFoundError:
            changed.append(shot)
            continue
        if (info.st_size, info.st_mtime_ns) != held[shot]:
            if shot in rereadable:
                rereads.append((shot, info.st_size, info.st_mtime_ns))
            else:
                changed.append(shot)
        beat()
    if changed:
        mismatch("changed", changed)
        return
    failed = {int(shot): (int(size), int(modified)) for shot, size, modified in known or ()}
    beat = Heartbeat(send, "checking")
    candidates: list[tuple[int, int, int]] = []
    for shot in sorted(set(names) - set(held)):
        try:
            info = _stat(names[shot], "live: new file")
        except FileNotFoundError:
            continue  # Gone since the listing (e.g. renamed by its writer).
        candidates.append((shot, info.st_size, info.st_mtime_ns))
        beat()
    # Known unreadable and unchanged since: still unreadable, not read again.
    still_failed = [item for item in candidates if failed.get(item[0]) == item[1:]]
    # Changed held shots Live read recently, and held ones whose HeLab TXY changed, are read again as new
    # files are.
    candidates += rereads + helab_rereads
    _stop_if_ahead(path, candidates, send)
    aged = {item[0] for item in _settled(candidates)}
    # Settled by age, and the same size and mtime as the previous check saw.
    to_read = [item for item in candidates if failed.get(item[0]) != item[1:]
               and item[0] in aged and previous.get(item[0]) == item[1:]]
    waiting[:] = [list(item) for item in candidates
                  if failed.get(item[0]) != item[1:] and item not in to_read]
    young = len(waiting)
    if not to_read and not dropped:
        send({"kind": "live_unchanged", **state(True, young, True), "total_files": len(names)})
        return
    import numpy as np
    import pandas as pd

    replacing = {item[0] for item in to_read} & set(held)
    gone = set(dropped)
    fingerprint = [(shot, *held[shot]) for shot in held if shot not in replacing and shot not in gone] + still_failed
    # Unreadable shots stay in the fingerprint but not in the data, as a load keeps them.
    unreadable = {shot for shot, _, _ in still_failed}
    problematic = sorted(unreadable)
    late: set[int] = set()
    replaced: set[int] = set()  # Held shots read again: their new data, or now unreadable.
    reread: list[dict[str, Any]] = []
    # The times of the shots read (new, or held and read again: a changed TXY file gets its time
    # anew, as a load's does; the app keeps held times only for unchanged shots).
    raw_times: dict[int, int] = {}
    rows = size = loaded = read = read_bytes = 0
    total_read_bytes = sum(item[1] for item in to_read)
    last_progress = 0.0

    def progress(done: int) -> ProgressEvent:
        checked = len(held) - len(replacing) + len(still_failed) + young + done
        return {"kind": "progress", "progress": checked / max(1, len(names)), "checked_files": checked,
                "loaded_files": len(held) - len(replacing) + loaded, "total_files": len(names),
                "failed_files": len(unreadable), "unsettled_files": young + len(late),
                "read_bytes": read_bytes, "read_files": read, "total_read_bytes": total_read_bytes}

    def unchanged(filename: str, item: tuple[int, int, int], reason: str) -> bool:
        info = _stat(filename, reason)
        return (info.st_size, info.st_mtime_ns) == item[1:]

    send(progress(0))
    for i, item in enumerate(to_read):
        shot = item[0]
        again = shot in replacing
        what = "read again" if again else "read"
        filename = switching.get(shot, names[shot])
        Pause.checkpoint(send)
        send({"kind": "file_started", "filename": filename})
        read += 1
        read_bytes += item[1]
        try:
            array = None
            if unchanged(filename, item, f"live: before {what}"):
                if shot in origins and item[1] == 0:
                    array = np.empty((0, 3), dtype=np.float64)  # HeLab's TXY of a shot with no hits (Q10.3).
                else:
                    _read_gate(filename)
                    frame = infra._read_txy_file(filename, f"live: {what}")
                    if frame.isna().any().any():
                        problematic.append(shot)
                    array = np.asarray(frame.dropna(), dtype=np.float64)
                if not unchanged(filename, item, f"live: after {what}"):
                    array = None
            if array is None:
                # Changed while read: still being written; the next check reads it again.
                late.add(shot)
                waiting.append(list(item))
                problematic[:] = [value for value in problematic if value != shot]
                if again:
                    fingerprint.append((shot, *held[shot]))  # (Held as it was until then.)
            else:
                artifact = os.path.join(output, f"{shot}.npy")
                infra._save_artifact(artifact, array)
                rows += len(array)
                size += array.nbytes
                if again:
                    replaced.add(shot)
                else:
                    loaded += 1
                if (found_time := fingerprints._raw_mtime(raw_entries.get(shot), "live: shot time")) is not None:
                    raw_times[shot] = found_time
                fingerprint.append(item)
                known_time: RawMtimeField = {"raw_mtime": raw_times[shot]} if shot in raw_times else {}
                send({"kind": "shot", "shot": shot, "artifact": artifact, "fingerprint": list(item),
                      "problematic": shot in problematic, **known_time})
        except (OSError, ValueError, pd.errors.ParserError):
            # Sent back with ``known`` next time: not read again unless it changes.
            unreadable.add(shot)
            problematic.append(shot)
            fingerprint.append(item)
            if again:
                replaced.add(shot)
        if again and shot in replaced:
            reread.append({"shot": shot, "path": filename, "old": list(held[shot]), "new": list(item[1:]),
                           "read": shot not in unreadable, **({"converted": True} if shot in converted else {})})
        send({"kind": "file_finished", "filename": filename})
        now = time.monotonic()
        if now - last_progress >= 0.1 or i + 1 == len(to_read):
            send(progress(i + 1))
            last_progress = now
    unsettled = young + len(late)
    if not loaded and not replaced and not gone and unreadable == {shot for shot, _, _ in still_failed}:
        # Everything new was still being written.
        send({"kind": "live_unchanged", **state(True, unsettled, False), "total_files": len(names)})
        return
    fingerprint.sort()
    # The dataset's origins: held shots kept as they were, read ones as chosen now.
    kept_origins = {shot: origin for shot, origin in held_origins.items() if shot not in replaced and shot not in gone}
    data_origins = {**kept_origins, **{shot: origins[shot] for shot, _, _ in fingerprint
                                       if shot in origins and (shot not in held or shot in replaced)}}
    # The folder's MATLAB TXY as this data stands for them (``helab_txy.folder_print``): its own MATLAB
    # shots, plus the settled MATLAB TXY of shots it holds from HeLab's, which a scan counts too.
    shadowed: dict[int, tuple[int, int, int]] = {}
    for shot in sorted(set(data_origins) & set(matlab)):
        try:
            info = _stat(matlab[shot], "live: MATLAB's TXY")
        except FileNotFoundError:
            continue
        shadowed[shot] = (shot, info.st_size, info.st_mtime_ns)
    matlab_print = helab_txy.folder_print(fingerprint, data_origins, shadowed)
    txy_bytes = sum(item[1] for item in matlab_print)
    summary = _summary(path, found, {file_kinds.TXY.name: txy_bytes}, has_dirs, False, matlab_print, listed_at)
    summary["unsettled"] = unsettled
    send({"kind": "scan_summary", "status": summary})
    kept = sorted(set(held) - replaced - gone)
    again_note = (f" ({len(replaced):,} changed after Live read {'it' if len(replaced) == 1 else 'them'}, read "
                  "again)" if replaced else "")
    send({"kind": "loaded", "rows": rows, "bytes": size,
          "files": len(kept) + loaded + len(replaced - unreadable), "loaded_at": time.time(),
          "total_files": len(names), "failed_files": len(unreadable), "unsettled_files": unsettled,
          "problematic": sorted(set(problematic)), "source": "updated", "cached": False,
          "disk_cache_pending": False, "load_counts": {
              "reused_memory": len(kept), "reused_disk": 0, "new": len(to_read) - len(replacing),
              "modified": len(replacing), "removed": len(gone), "read": read, "new_loaded": loaded,
              "modified_loaded": len(replaced - unreadable)},
          "cache_reason": f"Live: reused {len(kept)} shots from memory; read {read} TXY files{again_note}",
          "live_reread": reread, "raw_times": _raw_list(raw_times, raw_times),
          "fingerprint": [list(item) for item in fingerprint], "memory_shots": kept,
          "base_signature": "", "modified": summary["modified"], "modified_observed_at": time.time(),
          "signature": str(summary["signature"]),
          "txy": helab_txy.record(txy_source, data_origins, helab_found, txy.get("profiles"), txy, helab_state),
          **state(True, unsettled, True)})


def _helab_key(path: str, txy: dict[str, Any]) -> str:
    """The folder's data-root key for finding HeLab's folders: the app's (``txy["key"]``), else the store's,
    as a load finds it (the store's folder: ``txy["cache_directory"]``), else "" (by path)."""
    key = str(txy.get("key") or "")
    directory = str(txy.get("cache_directory") or "")
    if key or not directory or txy.get("key_asked"):
        return key  # (``key_asked``: an earlier check of this session asked the store and found none.)
    from helab.io_ops import stores
    try:
        with stores._cache_store(directory, local_lane=True) as store:
            return helab_txy.store_key(store, path)
    except Exception:  # (No store to ask: HeLab's folders by path only.)
        return ""
