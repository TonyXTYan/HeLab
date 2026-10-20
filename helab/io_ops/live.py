"""Live checks (``load`` with ``live``): one folder stat, else a names-only listing."""
from __future__ import annotations

import os
import time
from typing import Any

from helab.io_ops import fingerprints, infra
from helab.io_ops.fingerprints import (DEFAULT_CHECK_LEVEL, _fingerprint_signature, _raw_list,
                                       _sample_indices, _settled)
from helab.io_ops.identity import _folder_identity
from helab.io_ops.infra import Emit, Heartbeat, Pause, _is_dir, _read_gate, _scandir, _stat, emit
from helab.io_ops.summary import _summary
from helab.utils import file_kinds


# A folder modified this close to a check (or later: another computer's clock) may change again
# within the same timestamp tick, which the next check's stat wouldn't see: that check lists it.
RACY_SECONDS = 2.0


def live_check(path: str, output: str, send: Emit = emit, memory: list[list[int]] | None = None,
               known: list[list[int]] | None = None, since: int | None = None, *,
               identity: str = "", seen: list[list[int]] | None = None,
               check_level: str = DEFAULT_CHECK_LEVEL, listed_mtime: int | None = None,
               seen_names: list[str] | None = None, identity_root: str | None = None,
               recent: list[int] | None = None) -> None:
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

    ``recent`` names the held shots Live itself read recently (``FolderExplorer.LIVE_REREAD_SECONDS``,
    by Tony's decision): one of those that changed (its writer paused longer than the settle age, so
    Live read it unfinished) is read again like a new file, once settled and unchanged a check apart,
    and replaces the held one (``live_reread``: its old and new size and mtime) instead of stopping
    the check. Until then it is waiting (``live_seen``), and listings look at it besides the sample.
    Other held shots that changed still stop it (a change long after reading suggests a remount or a
    copy).
    """
    started = time.monotonic()
    if memory is None:
        raise ValueError("Live needs the folder's loaded data — Retry")
    try:
        folder = _stat(path, "live: folder")
    except FileNotFoundError:
        raise OSError("Folder not found — is its drive connected?") from None
    racy = abs(time.time() - folder.st_mtime) < RACY_SECONDS
    held = {int(shot): (int(size), int(modified)) for shot, size, modified in memory}
    rereadable = {int(shot) for shot in recent or ()} & set(held)

    current_identity = ""
    current_root: str | None = identity_root
    waiting: list[list[int]] = []  # New files not read yet, as stat'ed now (the next ``seen``).
    file_names: dict[int, str] = {}  # Their names.

    def state(listed: bool, unsettled: int, safe: bool) -> dict[str, Any]:
        # ``live_since``: what the next check may compare the folder's mtime with (None: list it).
        return {"live_since": folder.st_mtime_ns if safe and not racy and not unsettled else None,
                "live_listed": listed, "live_seconds": time.monotonic() - started,
                "unsettled_files": unsettled, "live_identity": current_identity, "live_seen": waiting,
                "live_seen_names": [file_names[int(entry[0])] for entry in waiting],
                # The folder's mtime as of this check's listing (or the last one's), unless racy.
                "live_listed_mtime": None if racy else folder.st_mtime_ns,
                "live_identity_root": current_root}

    if since is not None and since == folder.st_mtime_ns:
        send({"kind": "live_unchanged", **state(False, 0, True), "total_files": len(held)})
        return
    previous = {int(shot): (int(size), int(modified)) for shot, size, modified in seen or ()}
    if (listed_mtime is not None and listed_mtime == folder.st_mtime_ns and not racy and seen
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
                    names[shot] = entry.path
                    file_names[shot] = entry.name
                elif kind is file_kinds.RAW:
                    raw_entries[shot] = entry
            elif not has_dirs and _is_dir(entry):
                has_dirs = True

    def mismatch(reason: str, shots: list[int]) -> None:
        send({"kind": "shots_missing", "reason": reason, "missing": shots[:20], "missing_count": len(shots),
              "known_count": len(held), "listed_count": len(names)})

    missing = sorted(set(held) - set(names))
    if missing:
        mismatch("missing", missing)
        return
    current_identity, current_root = _folder_identity(path, identity_root)
    if identity and current_identity and current_identity != identity:
        # Another folder at this path (a remount, another drive): nothing held is its.
        mismatch("root", sorted(held))
        return
    beat = Heartbeat(send, "verifying")
    ordered = sorted(held)
    indices = _sample_indices(len(ordered), check_level)
    sampled = [ordered[index] for index in (range(len(ordered)) if indices is None else indices)]
    # Held shots the previous check saw changed (to read again once unchanged): looked at again.
    sampled += sorted((set(previous) & set(held)) - set(sampled))
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
    # Changed held shots Live read recently are read again as new files are.
    candidates += rereads
    aged = {item[0] for item in _settled(candidates)}
    # Settled by age, and the same size and mtime as the previous check saw.
    to_read = [item for item in candidates if failed.get(item[0]) != item[1:]
               and item[0] in aged and previous.get(item[0]) == item[1:]]
    waiting[:] = [list(item) for item in candidates
                  if failed.get(item[0]) != item[1:] and item not in to_read]
    young = len(waiting)
    if not to_read:
        send({"kind": "live_unchanged", **state(True, young, True), "total_files": len(names)})
        return
    import numpy as np
    import pandas as pd

    replacing = {item[0] for item in to_read} & set(held)
    fingerprint = [(shot, *held[shot]) for shot in held if shot not in replacing] + still_failed
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

    def progress(done: int) -> dict[str, Any]:
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
        filename = names[shot]
        Pause.checkpoint(send)
        send({"kind": "file_started", "filename": filename})
        read += 1
        read_bytes += item[1]
        try:
            array = None
            if unchanged(filename, item, f"live: before {what}"):
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
                np.save(artifact, array, allow_pickle=False)
                rows += len(array)
                size += array.nbytes
                if again:
                    replaced.add(shot)
                else:
                    loaded += 1
                if (found_time := fingerprints._raw_mtime(raw_entries.get(shot), "live: shot time")) is not None:
                    raw_times[shot] = found_time
                fingerprint.append(item)
                send({"kind": "shot", "shot": shot, "artifact": artifact, "fingerprint": list(item),
                      "problematic": shot in problematic,
                      **({"raw_mtime": raw_times[shot]} if shot in raw_times else {})})
        except (OSError, ValueError, pd.errors.ParserError):
            # Sent back with ``known`` next time: not read again unless it changes.
            unreadable.add(shot)
            problematic.append(shot)
            fingerprint.append(item)
            if again:
                replaced.add(shot)
        if again and shot in replaced:
            reread.append({"shot": shot, "path": filename, "old": list(held[shot]), "new": list(item[1:]),
                           "read": shot not in unreadable})
        send({"kind": "file_finished", "filename": filename})
        now = time.monotonic()
        if now - last_progress >= 0.1 or i + 1 == len(to_read):
            send(progress(i + 1))
            last_progress = now
    unsettled = young + len(late)
    if not loaded and not replaced and unreadable == {shot for shot, _, _ in still_failed}:
        # Everything new was still being written.
        send({"kind": "live_unchanged", **state(True, unsettled, False), "total_files": len(names)})
        return
    fingerprint.sort()
    txy_bytes = sum(item[1] for item in fingerprint)
    summary = _summary(path, found, {file_kinds.TXY.name: txy_bytes}, has_dirs, False, fingerprint, listed_at)
    summary["unsettled"] = unsettled
    send({"kind": "scan_summary", "status": summary})
    kept = sorted(set(held) - replaced)
    again_note = (f" ({len(replaced):,} changed after Live read {'it' if len(replaced) == 1 else 'them'}, read "
                  "again)" if replaced else "")
    send({"kind": "loaded", "rows": rows, "bytes": size,
          "files": len(kept) + loaded + len(replaced - unreadable), "loaded_at": time.time(),
          "total_files": len(names), "failed_files": len(unreadable), "unsettled_files": unsettled,
          "problematic": sorted(set(problematic)), "source": "updated", "cached": False,
          "disk_cache_pending": False, "load_counts": {
              "reused_memory": len(kept), "reused_disk": 0, "new": len(to_read) - len(replacing),
              "modified": len(replacing), "removed": 0, "read": read, "new_loaded": loaded,
              "modified_loaded": len(replaced - unreadable)},
          "cache_reason": f"Live: reused {len(kept)} shots from memory; read {read} TXY files{again_note}",
          "live_reread": reread, "raw_times": _raw_list(raw_times, raw_times),
          "fingerprint": [list(item) for item in fingerprint], "memory_shots": kept,
          "base_signature": "", "modified": summary["modified"], "modified_observed_at": time.time(),
          "signature": _fingerprint_signature(fingerprint), **state(True, unsettled, True)})
