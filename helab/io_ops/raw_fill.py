"""Caching v2's ``raw_fill``: one folder's raw files into store-v4's raw layers (stage 1, step 5).

The app runs it on the background lane after a folder's data was saved to the disk cache (a load,
Live's saves; ``FolderCache.schedule_raw_fill``), so loads keep their speed (Q22.1); it pauses for
the current tab's work, is refused offline, and is held during a cache move, like a load. Only in
store-v4 (the switch on), for a folder with a data root and not marked Don't cache; never for
listings or scans (Q19.10).

One run lists the folder once (marking each cached shot seen, or gone: its layer is then the only
copy, kept, Q22.6), skips shots already cached from the same file and parser (so a killed run
resumes for the price of one listing), and reads the rest as the converter does: settled files only
(unmodified for the settle time, not dated in the future), the same ``fstat`` before and after the
read, and finished (``raw.not_done``'s checks that need no profile: not blank, ending with a newline;
a TDC that paused mid-file longer than the settle time isn't cached half-written, C3-2), else the shot
waits for a later run. It saves them in batches of at most ``BATCH_SHOTS`` shots
or ``BATCH_BYTES`` of raw text (one transaction and one fit check each, ``CacheStore.save_raw_batch``),
each batch's ``.hlb`` files published just before its save. A batch that doesn't fit the budget is
not saved and nothing asks (T~1): the run stops. A raw file overwritten in place since it was cached
(another fingerprint) is replaced and sent as ``raw_overwritten`` (Q22.5, Q28.6).

It yields: after about ``WORK_SECONDS`` of work it ends with ``more`` set, and the app queues the next
run at the back of the background lane, so scans and Live's saves never wait behind a large folder.
Heartbeats go out while it lists and reads, and from a ticker while each shot encodes (zstd 9 on a large
file outlasts the no-progress timeout on a slow PC, C3-1).

Every source-folder call stays in this process, traced and guarded like the other helpers'.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import time
from typing import Any, Mapping, Sequence

from helab.io_ops import fingerprints, stores
from helab.io_ops.events import RawFillDoneEvent
from helab.io_ops.infra import Emit, Heartbeat, Pause, _entry_stat, _guard, _scandir, _trace, _traced_error, emit
from helab.utils import file_kinds

BATCH_SHOTS = 50
BATCH_BYTES = 64 * 1024 * 1024
WORK_SECONDS = 30.0
READ_BLOCK = 8 * 1024 * 1024


@dataclass(frozen=True)
class RawRead:
    """A raw file read as done: its shot, name, fingerprint, bytes and when it was read."""
    shot: int
    name: str
    size: int
    mtime_ns: int
    data: bytes
    read_at: float


@dataclass(frozen=True)
class _Listed:
    shot: int
    name: str
    path: str
    size: int
    mtime_ns: int


def _done(path: str, send: Emit, *, reason: str = "", saved: int = 0, kept: int = 0, refused: int = 0,
          waiting: int = 0, gone: int = 0, more: bool = False, store: Any = None) -> None:
    event: RawFillDoneEvent = {"kind": "raw_fill_done", "path": path, "reason": reason, "saved": saved, "kept": kept,
                               "refused": refused, "waiting": waiting, "gone": gone, "more": more}
    if store is not None:  # (Its saves moved usage and retired files: the next sweep may be due sooner.)
        usage = stores._usage(store)
        if "usage" in usage and "usage_seq" in usage:
            event["usage"], event["usage_seq"] = usage["usage"], usage["usage_seq"]
        event["next_deadline"] = stores._deadline(store)
    send(event)


def _read_settled(item: _Listed, beat: Heartbeat) -> bytes | None:
    """The raw file's bytes, or None when it changed since the listing (before or during the read)."""
    _guard(item.path)
    try:
        with open(item.path, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns) != (item.size, item.mtime_ns):
                _trace("read", item.path, "raw fill: raw", bytes=0, changed=True)
                return None
            blocks: list[bytes] = []
            while block := stream.read(READ_BLOCK):
                blocks.append(block)
                beat(0)
            after = os.fstat(stream.fileno())
    except OSError as exc:
        _traced_error("read", item.path, "raw fill: raw", exc)
        raise
    data = b"".join(blocks)
    _trace("read", item.path, "raw fill: raw", bytes=len(data))
    if (after.st_size, after.st_mtime_ns, len(data)) != (item.size, item.mtime_ns, item.size):
        return None
    return data


def _unfinished(data: bytes) -> bool:
    """``raw.not_done``'s checks that need no profile: blank, or not ending with a newline (still being
    written). The trigger-first check needs the profile's trigger channel, which a fill doesn't have."""
    return not data.strip() or not data.endswith(b"\n")


def save_batch(store: Any, path: str, items: Sequence[RawRead], guard: Any, cache_options: Mapping[str, Any],
               send: Emit, beat: Heartbeat | None = None) -> Any:
    """Encode ``items`` as raw layers, publish their ``.hlb`` files and save them in one batch
    (``CacheStore.save_raw_batch``); sends ``raw_overwritten`` for each file changed in place. Shared with
    ``convert`` (a conversion saves the raw rows of the shots it read). Each shot encodes under the
    converter's ticker for at most ``compute_budget`` of its size, so a long encode is progress and a hung
    one still times out. Returns the ``RawSave``."""
    from helab.convert import raw_layer
    from helab.io_ops.convert import _Ticker, compute_budget
    from helab.utils import store_v4
    from helab.utils.cache_store import RawEntry
    maker = store_v4.session_maker()
    entries: list[RawEntry] = []
    for item in items:
        with _Ticker(send, "raw layer", compute_budget(len(item.data))):
            layer = raw_layer.encode(item.data)
            sha256 = hashlib.sha256(item.data).hexdigest()
            packed = raw_layer.to_hlb(layer, maker={"maker": maker["maker"], "record": maker["record"]},
                                      meta={"name": item.name, "size": item.size, "mtime_ns": item.mtime_ns,
                                            "sha256": sha256})
        file = store.write_raw_file(packed)
        entries.append(RawEntry(item.shot, item.name, item.size, item.mtime_ns, sha256, raw_layer.RAW_PARSER_VERSION,
                                layer.encoding, layer.facts.to_json(), layer.pulses, file, read_at=item.read_at))
        if beat is not None:
            beat(0)  # (zstd 9 takes a while on a slow CPU: still progressing.)
    result = store.save_raw_batch(path, entries, guard, budget=cache_options.get("budget"),
                                  budget_set_at=cache_options.get("budget_set_at"))
    for overwrite in result.overwritten:
        send({"kind": "raw_overwritten", "path": path, "shot": overwrite.shot, "raw_name": overwrite.name,
              "old": list(overwrite.old), "new": list(overwrite.new)})
    return result


def raw_fill(path: str, cache_options: Mapping[str, Any], send: Emit = emit, *,
             work_seconds: float = WORK_SECONDS) -> None:
    """Fill ``path``'s raw layers (the module docstring); ends with ``raw_fill_done``."""
    from helab.convert import raw, raw_layer
    from helab.utils.cache_paths import UnresolvedRemotePath
    from helab.utils.cache_store import layout_of
    from helab.utils.store_v4 import LAYOUT
    started = time.monotonic()
    directory = str(cache_options["directory"])
    if layout_of(directory) < LAYOUT:
        _done(path, send, reason="store_v3")  # (Raw layers are store-v4's.)
        return
    try:
        store = stores._cache_store(directory, [path])
    except UnresolvedRemotePath:
        _done(path, send, reason="no_data_root")
        return
    with store:
        try:
            store._path_key(path)
        except UnresolvedRemotePath:
            _done(path, send, reason="no_data_root")
            return
        if store.read_only:
            _done(path, send, reason="read_only")
            return
        prefs = store.read_prefs([path])[path]
        if prefs.value and prefs.value.get("no_cache"):
            _done(path, send, reason="no_cache")
            return
        guard = store.start_raw_job(path)
        listed_at = time.time()
        listed: list[_Listed] = []
        beat = Heartbeat(send, "raw fill")
        with _scandir(path, "raw fill: listing") as directory_entries:
            for entry in directory_entries:
                beat()
                matched = file_kinds.match(entry.name)
                if matched is None or matched[0] is not file_kinds.RAW:
                    continue
                info = _entry_stat(entry, "raw fill: raw")
                listed.append(_Listed(matched[1], entry.name, entry.path, info.st_size, info.st_mtime_ns))
        listed.sort(key=lambda item: item.shot)
        _, gone = store.mark_raw_seen(path, {item.shot: (item.size, item.mtime_ns) for item in listed}, listed_at)
        rows = store.raw_rows(path)
        if rows.failed:
            raise ValueError(rows.error)
        cached = rows.value or {}
        todo = [item for item in listed if (row := cached.get(item.shot)) is None
                or (row.size, row.mtime_ns, row.parser) != (item.size, item.mtime_ns, raw_layer.RAW_PARSER_VERSION)]
        saved = kept = refused = waiting = 0
        reason, more = "", False
        batch: list[RawRead] = []
        batch_bytes = 0

        def flush() -> bool:
            """Save the batch; False when it didn't fit (the run stops)."""
            nonlocal saved, kept, refused, batch, batch_bytes, reason
            if not batch:
                return True
            last = save_batch(store, path, batch, guard, cache_options, send, beat)
            batch, batch_bytes = [], 0
            if last.reason:
                reason = str(last.reason)
                return False
            saved, kept, refused = saved + len(last.saved), kept + len(last.kept), refused + len(last.refused)
            return True

        now = time.time()
        for item in todo:
            Pause.checkpoint(send)
            if time.monotonic() - started > work_seconds:
                more = True  # (Yield: the app queues the rest at the back of the lane.)
                break
            if not raw.settled_by_age(item.mtime_ns, now, fingerprints.SETTLE_SECONDS) or (
                    item.mtime_ns / 1e9 > now + fingerprints.FUTURE_SECONDS):
                waiting += 1
                continue
            read_at = time.time()
            try:
                data = _read_settled(item, beat)
            except OSError:
                waiting += 1
                continue
            if data is None or _unfinished(data):
                waiting += 1  # (Changed since the listing, or not finished: a later run reads it.)
                continue
            batch.append(RawRead(item.shot, item.name, item.size, item.mtime_ns, data, read_at))
            batch_bytes += len(data)
            if (len(batch) >= BATCH_SHOTS or batch_bytes >= BATCH_BYTES) and not flush():
                break
        else:
            flush()
        if more and batch and not flush():
            more = False
        _done(path, send, reason=reason, saved=saved, kept=kept, refused=refused, waiting=waiting, gone=gone,
              more=more and not reason, store=store)
