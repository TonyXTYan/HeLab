"""The disk cache: SQLite records and compressed dataset files (``store-v3``).

Only isolated helpers open a store; the GUI process never does. Design, rules
and the reasons behind them: ``roadmaps/cache-storage-and-settings.md``.

- Records are JSON text in ``records.sqlite`` (WAL), readable with ``sqlite3``.
- Datasets are files in ``datasets/``, never inside SQLite. A replaced or removed
  file is retired, and only the sweep deletes it, after a grace period, so a
  reader that looked up the old row can still open it.
- Reads answer found, missing or error. An error is never "nothing saved".
- Every write checks a :class:`SaveGuard` taken when its job started, so a save
  that was already running can't bring back removed data or overwrite newer data.
"""
from __future__ import annotations

import contextlib
import dataclasses
from dataclasses import dataclass, field
import json
import math
import os
import pathlib
import shutil
import sqlite3
import stat
import time
from typing import (Any, Callable, Collection, Generator, Generic, Iterable, Literal, Mapping, NotRequired, Sequence,
                    TypeVar, TypedDict, cast)
import uuid

from helab.io_ops.events import PresetRowFields, ResultCountField, UsageFields
from helab.utils import store_v4
from helab.utils.legacy_store import LegacyStore, LegacyUnavailable

LAYOUT_VERSION = 3
STORE_DIRNAME = "store-v3"
ROOT_LAYOUT_VERSION = LAYOUT_VERSION
ROOT_STORE_DIRNAME = STORE_DIRNAME
DATASET_FORMAT = "blosc-pickle-1"
BUSY_TIMEOUT = 30.0
# Opening while another process's last connection closes (and removes the WAL files) can fail with
# SQLite's "disk I/O error" on Windows, which the busy timeout doesn't cover: try again shortly,
# 5 attempts over about 1.5 s.
OPEN_ATTEMPTS = 5
OPEN_RETRY_SECONDS = 0.1
_sleep = time.sleep  # (Tests replace it.)
OPEN_FAILED = "Disk cache could not be opened"
# Retired dataset files outlive any reader that looked up their row.
RETIRE_GRACE = 600.0
# A file still open (Windows) is retried this much later.
RETRY_OPEN = 60.0
# Pending saves the user hasn't answered, and files no row names (a killed writer).
PENDING_MAX_AGE = 3600.0
ORPHAN_MIN_AGE = 3600.0
# Over this share of the budget, a save that grows a cached folder's dataset asks first.
APPROVAL_SHARE = 0.8
# The diskcache folders of earlier versions, deleted at startup.
OLD_CACHE_DIRS = ("data_ram_cache", "status_cache", "os_file_system_cache")

# ``listings``: each listed folder's subfolder names and own counts, for browsing it offline
# (cache-only browsing C2; written by ``list`` helpers, ``io_ops.listings``).
Kind = Literal["datasets", "summaries", "histories", "subtrees", "listings"]
KINDS: tuple[Kind, ...] = ("datasets", "summaries", "histories", "subtrees", "listings")
# What a purge of cached data by age can take (A47.4): datasets, and in store-v4 TXY layers and raw layers.
PURGE_KINDS: tuple[str, ...] = ("datasets", "txy", "raw")
RECORD_TABLES: dict[Kind, str] = {
    "summaries": "folder_summaries", "histories": "scan_histories", "subtrees": "subtrees", "listings": "listings"}
TABLES: dict[Kind, str] = {"datasets": "datasets", **RECORD_TABLES}

T = TypeVar("T")

# Disk-cached analysis results (result caching R2, roadmaps/result-caching.md): kept beside the
# datasets with a generation (``gen_results``) and clearing of their own, never touched by the
# dataset kinds above (Rule 1), but within the one disk budget (Tony, 2026-10-22). One row per folder (``path``, its ``root://`` key, as datasets
# are keyed) and exact reuse key: ``lookup`` is the SHA-256 of the canonical key JSON, without the
# folder, so a nested root's re-key moves rows by ``path`` alone; ``family`` the SHA-256 of the same
# plot and settings without the script's identity, environment and data, which finds an outdated
# result of the folder. ``record`` is the result's record (JSON, no data); its data (NumPy arrays
# and a JSON tree, never a pickle) is a file in ``results/``, retired and swept like dataset files
# (``retired_files`` names it ``results/<file>``).
RESULTS_DIRNAME = "results"
# What a result row takes in the records database beyond its text columns and their copies in the
# indexes (ids, numbers, b-tree slack), measured: about 400 bytes.
RESULT_ROW_BYTES = 400
RESULT_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS results ("
    "result_id TEXT PRIMARY KEY, path TEXT NOT NULL, lookup TEXT NOT NULL, family TEXT NOT NULL, "
    "analysis_id TEXT NOT NULL, action TEXT NOT NULL, record TEXT NOT NULL, file TEXT NOT NULL, "
    "bytes INTEGER NOT NULL, computed_at REAL NOT NULL, saved_at REAL NOT NULL, last_used REAL NOT NULL, "
    "UNIQUE (path, lookup))",
    "CREATE INDEX IF NOT EXISTS results_family ON results (path, family)",
    "CREATE INDEX IF NOT EXISTS results_last_used ON results (last_used)",
    # A result that didn't fit the budget waits here for the user's answer (Make room or Discard,
    # Tony 2026-10-22): its file in ``results/``, the save guard its run took (JSON), the plot's name.
    # Like a dataset's pending save, it doesn't count toward the budget, and it expires after
    # ``PENDING_MAX_AGE`` unanswered. Added after c31ac10, as a table of its own.
    "CREATE TABLE IF NOT EXISTS pending_results ("
    "pending_id TEXT PRIMARY KEY, path TEXT NOT NULL, lookup TEXT NOT NULL, family TEXT NOT NULL, "
    "analysis_id TEXT NOT NULL, action TEXT NOT NULL, label TEXT NOT NULL, record TEXT NOT NULL, "
    "file TEXT NOT NULL, bytes INTEGER NOT NULL, computed_at REAL NOT NULL, guard TEXT NOT NULL, "
    "created_at REAL NOT NULL, UNIQUE (path, lookup))")

# The converter's per-folder choices (TXY converter stage 4), flags like ``folder_prefs`` (the user's,
# one row per folder's ``root://`` key, the newest ``set_at`` winning; never removed by Clear all,
# purges or making room; turned off by Clear folder preferences; moved by a nested root's re-key):
# ``write_beside``, HeLab's TXY written beside the folder's raw files (Q9.7). A table of its own, so
# older HeLabs' writes of ``folder_prefs`` rows (INSERT OR REPLACE) never touch it.
CONVERT_PREFS_SCHEMA = ("CREATE TABLE IF NOT EXISTS convert_prefs (path TEXT PRIMARY KEY, "
                        "write_beside INTEGER NOT NULL DEFAULT 0, set_at REAL NOT NULL);\n")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS folder_epochs (
    path TEXT PRIMARY KEY, epoch INTEGER NOT NULL DEFAULT 0, job_seq INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS folder_summaries (
    path TEXT PRIMARY KEY, record TEXT NOT NULL, identity TEXT, saved_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS folder_summaries_saved_at ON folder_summaries (saved_at);
CREATE TABLE IF NOT EXISTS scan_histories (path TEXT PRIMARY KEY, record TEXT NOT NULL, saved_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS scan_histories_saved_at ON scan_histories (saved_at);
CREATE TABLE IF NOT EXISTS subtrees (path TEXT PRIMARY KEY, record TEXT NOT NULL, saved_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS subtrees_saved_at ON subtrees (saved_at);
CREATE TABLE IF NOT EXISTS listings (path TEXT PRIMARY KEY, record TEXT NOT NULL, saved_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS listings_saved_at ON listings (saved_at);
CREATE TABLE IF NOT EXISTS folder_prefs (
    path TEXT PRIMARY KEY, no_cache INTEGER NOT NULL DEFAULT 0, no_auto_load INTEGER NOT NULL DEFAULT 0,
    set_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS folder_constants (path TEXT PRIMARY KEY, record TEXT NOT NULL, set_at REAL NOT NULL);
""" + CONVERT_PREFS_SCHEMA + """CREATE TABLE IF NOT EXISTS presets (
    kind TEXT NOT NULL, scope TEXT NOT NULL, name TEXT NOT NULL, record TEXT, set_at REAL NOT NULL,
    PRIMARY KEY (kind, scope, name));
CREATE TABLE IF NOT EXISTS pending_saves (
    pending_id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE,
    reason TEXT NOT NULL CHECK (reason IN ('over_budget', 'needs_approval')),
    file TEXT NOT NULL, bytes INTEGER NOT NULL, record TEXT NOT NULL,
    gen_datasets INTEGER NOT NULL, epoch INTEGER NOT NULL, job_seq INTEGER NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS retired_files (file TEXT PRIMARY KEY, retired_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS datasets (
    path TEXT PRIMARY KEY, file TEXT NOT NULL, bytes INTEGER NOT NULL, ram_bytes INTEGER NOT NULL,
    rows INTEGER NOT NULL, shots INTEGER NOT NULL, fingerprint TEXT NOT NULL, problematic TEXT NOT NULL,
    info TEXT NOT NULL, last_used REAL NOT NULL, job_seq INTEGER NOT NULL,
    raw_times TEXT NOT NULL DEFAULT '[]');
CREATE INDEX IF NOT EXISTS datasets_last_used ON datasets (last_used);
""" + "".join(f"{statement};\n" for statement in RESULT_SCHEMA)

# Cache-only browsing (D1): the share or volume last seen at each mount path, as its location's top
# (``smb://server/share`` or ``vol://<id>``), recorded by source helpers. Only offline requests use
# them, and only for a mount path nothing is mounted at now, so a folder on an unmounted share keeps
# its cache key.
MOUNT_HINTS_SCHEMA = ("CREATE TABLE IF NOT EXISTS mount_hints "
                      "(mount_path TEXT PRIMARY KEY, location TEXT NOT NULL, seen_at REAL NOT NULL);\n")
ROOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS roots (
    location TEXT PRIMARY KEY, uuid TEXT NOT NULL, kind TEXT NOT NULL,
    label TEXT NOT NULL, first_seen REAL NOT NULL, last_seen REAL NOT NULL,
    verified_at REAL NOT NULL, decision TEXT NOT NULL
        CHECK (decision IN ('confirmed', 'pending')));
CREATE INDEX IF NOT EXISTS roots_uuid ON roots (uuid);
CREATE TABLE IF NOT EXISTS root_volumes (
    mount_path TEXT NOT NULL, mount_source TEXT NOT NULL, volume_id TEXT NOT NULL,
    seen_at REAL NOT NULL, PRIMARY KEY (mount_path, mount_source));
""" + MOUNT_HINTS_SCHEMA


def _root_epoch(key: str) -> str | None:
    """The ``folder_epochs`` row a data root's Clear bumps, for a ``root://<uuid>/…`` key (a name
    no folder key has)."""
    return f"root-clear://{key[7:].partition('/')[0]}" if key.startswith("root://") else None


def _results_root_epoch(key: str) -> str | None:
    """The ``folder_epochs`` row a data root's Clear cached analysis bumps (its results only; Clear
    cached data's ``root-clear://`` leaves results, and their saves, alone)."""
    return f"root-results-clear://{key[7:].partition('/')[0]}" if key.startswith("root://") else None


# A ``folder_epochs`` row store-v4 writes when a save deletes a record (``<prefix><kind>:<key>``): no guard
# reads it; it only stops store-v3's row being read through again (C2-1).
_LEGACY_HIDDEN = "legacy-hidden:"


def _raw_epoch(key: str) -> str:
    """The ``folder_epochs`` row a removal of one folder's raw layers bumps (``raw:<key>``, store-v4)."""
    return f"raw:{key}"


_RAW_COLUMNS = ("path, shot, name, size, mtime_ns, sha256, parser, encoding, facts, pulses, file, bytes, seen_at, "
                "gone_at, maker, job_seq, saved_at, last_used")


def _results_epoch(key: str) -> str:
    """The ``folder_epochs`` row a removal of one folder's results bumps (``results:<key>``): a
    dataset removal of the folder bumps the folder's own row, which result saves don't check."""
    return f"results:{key}"


class StoreError(Exception):
    """The store can't be opened, read or written. Never means "nothing saved"."""


class StoreReadOnly(StoreError):
    """A newer HeLab wrote this store's layout; this one only reads it."""


NOT_CACHED = "Not cached: your choice"
# A save whose guard names another key than the folder's now (a nested root re-keyed it, or a mount
# path resolves to another share): rejected as "cleared", never re-guarded under the new key.
REKEYED = "The folder's data root changed before saving completed"


class SaveRejected(Exception):
    """The save guard discarded a write; nothing was written."""

    def __init__(self, reason: Literal["cleared", "newer", "gone", "no_cache"], message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Read(Generic[T]):
    """One read's answer: found (with a value), missing, or error (with a message)."""
    status: Literal["found", "missing", "error"]
    value: T | None = None
    error: str = ""

    @property
    def found(self) -> bool:
        return self.status == "found"

    @property
    def missing(self) -> bool:
        return self.status == "missing"

    @property
    def failed(self) -> bool:
        return self.status == "error"


def _found(value: T) -> Read[T]:
    return Read("found", value)


def _missing() -> Read[Any]:
    return Read("missing")


def _error(message: str) -> Read[Any]:
    return Read("error", error=message)


@dataclass(frozen=True)
class SaveGuard:
    """Values read when a job started; its writes succeed only while they hold."""
    generations: Mapping[str, int]
    epochs: Mapping[str, int]
    job_seq: int = 0


class DatasetRecord(TypedDict):
    """What a load saves with its dataset file. ``info`` holds ``saved_at``,
    ``snapshot_at``, ``signature``, ``counts``, ``unsettled``, ``kind``, ``format``, ``names`` and
    ``folder_mtime_ns`` (the folder's mtime before the listing, for the quick check; None when too
    close to it; rows saved before it have none, and the quick check then compares ``snapshot_at``).
    ``raw_times``: ``[shot, mtime_ns]`` of each shot's raw ``d<N>.txt`` file where one was found (the
    shot's time). Kept out of ``info``, which listings read for every subfolder, and out of the
    fingerprint, which raw files never affect. Rows saved before it have none (``[]``)."""
    ram_bytes: int
    rows: int
    shots: int
    fingerprint: list[list[int]]
    problematic: list[int]
    info: dict[str, Any]
    raw_times: NotRequired[list[list[int]]]


class DatasetRow(DatasetRecord):
    path: str
    file: str
    bytes: int
    last_used: float
    job_seq: int


class DatasetInfo(TypedDict):
    bytes: int
    ram_bytes: int
    # Its TXY files' size on disk (the large-folder estimate), from the fingerprint.
    source_bytes: int
    info: dict[str, Any]
    last_used: float


@dataclass(frozen=True)
class Removal:
    """What one removal did. ``paths`` is None for a removal by kind (every path). In store-v4 it may
    also take raw layers (Make room, a root's Clear): their folders (``raw_paths``; ``only_copy_paths``
    for those whose raw files were gone at the last look) and bytes."""
    kinds: tuple[Kind, ...]
    paths: tuple[str, ...] | None
    datasets: int = 0
    dataset_bytes: int = 0
    raw_paths: tuple[str, ...] = ()
    only_copy_paths: tuple[str, ...] = ()
    raw_rows: int = 0
    raw_bytes: int = 0
    # Stage 2's TXY layers ((folder, layer) pairs) by Make room's groups (Q45.6): rebuildable from the raw
    # layer here, those whose sources the last listing saw, and only copies.
    txy_layers: tuple[tuple[str, str], ...] = ()
    txy_seen: tuple[tuple[str, str], ...] = ()
    txy_only: tuple[tuple[str, str], ...] = ()
    txy_bytes: int = 0


@dataclass(frozen=True)
class ResultRemoval:
    """What one removal of saved results did. ``paths`` is None for every result; ``root`` the
    data root's UUID for a root's Clear cached analysis."""
    paths: tuple[str, ...] | None
    results: int = 0
    bytes: int = 0
    root: str | None = None
    # Make room's eviction: the saved results it removed, (folder, lookup, result_id) each. Not a
    # clear: no epoch moves, so every save and waiting result, a newer copy of those keys' included,
    # stays valid (a replacement saved gets a new result_id: never one of these).
    evicted: tuple[tuple[str, str, str], ...] = ()


class ResultRow(TypedDict):
    """A saved result's row: its record (the result without data, JSON) and data file."""
    result_id: str
    path: str
    lookup: str
    family: str
    analysis_id: str
    action: str
    record: Any
    file: str
    bytes: int
    computed_at: float
    saved_at: float
    last_used: float


@dataclass(frozen=True)
class ResultFound:
    """A saved result found: its row and data file's bytes; ``exact`` False for an outdated one;
    ``legacy``: read from store-v3 under Keep (store-v4 had none; its ``result_id`` is v3's)."""
    row: ResultRow
    data: bytes
    exact: bool
    legacy: bool = False


@dataclass(frozen=True)
class ResultCount:
    """A folder's saved results (the row badge, Folder details): how many and their files' bytes,
    as of the store's ``writes``-th write transaction (newer measurements win, as for usage)."""
    count: int
    bytes: int
    store_id: str
    writes: int

    def event(self) -> ResultCountField:
        return {"count": self.count, "bytes": self.bytes, "seq": [self.store_id, self.writes]}


@dataclass(frozen=True)
class ResultSave:
    """A result save: made, or not (``reason`` "over_budget": it doesn't fit the disk budget)."""
    saved: bool
    reason: str = ""
    bytes: int = 0  # its file (and, saved, its record)
    usage: int = 0  # live bytes when the save was decided
    usage_seq: int = 0
    budget: int | None = None
    pending_id: str = ""  # Not saved: it waits for the user's answer (``pending_results``).
    result_id: str = ""  # Saved: its row's id (new for every save, a replacement's too).
    folder: ResultCount | None = None  # Saved: the folder's saved results after it.


@dataclass(frozen=True)
class ResultRoom:
    """What Make room removes for a waiting result: least recently shown other saved results (never
    cached datasets); ``possible`` False if removing all of them isn't enough."""
    result_ids: tuple[str, ...]
    bytes: int
    newest_last_used: float | None
    possible: bool


@dataclass(frozen=True)
class ResultAdopt:
    adopted: bool
    path: str
    bytes: int
    room: ResultRoom | None = None  # Not adopted: it doesn't fit, and what Make room would remove.
    removal: ResultRemoval | None = None  # Adopted with Make room: what was removed.
    result_id: str = ""  # Adopted: its saved row's id.
    # Adopted: the saved results of its folder and of those Make room took from, after it (by source path).
    folders: dict[str, ResultCount] = field(default_factory=dict)


@dataclass(frozen=True)
class Usage:
    """The store's live bytes as of its ``writes``-th write transaction.

    Measurements are ordered by ``writes``, never by clock time: a slow inventory that
    finishes after a Clear still measured the store before it. Equal counts measured
    the same contents.
    """
    bytes: int
    store_id: str
    writes: int

    def event(self) -> UsageFields:
        """For a helper event: ``usage`` and ``usage_seq`` (``FolderCache._note_usage``)."""
        return {"usage": self.bytes, "usage_seq": [self.store_id, self.writes]}


@dataclass(frozen=True)
class SaveResult:
    """A dataset save: saved, or held as a pending save until the user answers."""
    pending_id: str = ""
    reason: str = ""  # "over_budget" or "needs_approval" when held
    bytes: int = 0  # what the save adds: its file and its records
    usage: int = 0  # live bytes when the save was decided
    usage_seq: int = 0  # the store's write count then (:class:`Usage`)
    budget: int | None = None
    job_seq: int = 0
    # The folder's current dataset bytes, which the save replaces (0: none).
    replaces: int = 0
    # Older jobs' pending saves this save (or pending save) replaced.
    superseded: tuple[str, ...] = ()

    @property
    def saved(self) -> bool:
        return not self.pending_id


@dataclass(frozen=True)
class RoomPlan:
    """What Make room removes for a pending save: other folders' datasets, least recently used first;
    in store-v4 then other folders' raw layers whose files were still there, then those that are the
    only copy (D8). ``bytes`` is the datasets'; ``raw_bytes`` the raw layers'."""
    paths: tuple[str, ...]
    bytes: int
    oldest_last_used: float | None
    newest_last_used: float | None
    # False: the folder alone is bigger than the budget, so nothing can make room.
    possible: bool
    raw_paths: tuple[str, ...] = ()
    only_copy_paths: tuple[str, ...] = ()
    raw_bytes: int = 0
    # Stage 2 (Q45.6): (folder, layer) pairs by group, and the layers' bytes.
    txy_layers: tuple[tuple[str, str], ...] = ()
    txy_seen: tuple[tuple[str, str], ...] = ()
    txy_only: tuple[tuple[str, str], ...] = ()
    txy_bytes: int = 0

    @property
    def items(self) -> tuple[str, ...]:
        """Everything the plan removes, as ``adopt_pending``'s ``expected_room`` names it: a folder's
        dataset by its path, its raw layer as ``raw:<path>``, an only copy as ``raw-only:<path>``, and a
        TXY layer as ``txy:``, ``txy-seen:`` or ``txy-only:<layer>:<path>`` (``txy_item``)."""
        return room_items(self.paths, self.raw_paths, self.only_copy_paths, self.txy_layers, self.txy_seen,
                          self.txy_only)


def room_items(paths: Sequence[str], raw_paths: Sequence[str] = (), only_copy: Sequence[str] = (),
               txy: Sequence[tuple[str, str]] = (), txy_seen: Sequence[tuple[str, str]] = (),
               txy_only: Sequence[tuple[str, str]] = ()) -> tuple[str, ...]:
    """Make room's items in its order (Q45.6): datasets, rebuildable layers, layers seen, raw layers seen,
    then only copies (TXY layers, then raw layers)."""
    return (*paths, *(txy_item(TXY_ITEM, path, layer) for path, layer in txy),
            *(txy_item(TXY_SEEN_ITEM, path, layer) for path, layer in txy_seen),
            *(RAW_ITEM + path for path in raw_paths),
            *(txy_item(TXY_ONLY_ITEM, path, layer) for path, layer in txy_only),
            *(ONLY_COPY_ITEM + path for path in only_copy))


RAW_ITEM, ONLY_COPY_ITEM = "raw:", "raw-only:"
TXY_ITEM, TXY_SEEN_ITEM, TXY_ONLY_ITEM = "txy:", "txy-seen:", "txy-only:"
# A store-v3 being cleared is renamed ``store-v3.clearing-<8 hex>`` first (``clear_legacy``, C3-4).
LEGACY_CLEARING = ".clearing-"


@dataclass(frozen=True)
class RawEntry:
    """One raw file's layer to save (``write_raw_file`` published its ``.hlb``): its shot and name, the
    fingerprint and SHA-256 of the bytes read, the parser and encoding, the facts and pulse count."""
    shot: int
    name: str
    size: int
    mtime_ns: int
    sha256: str
    parser: int
    encoding: str
    facts: Mapping[str, Any]
    pulses: int
    file: str
    # When its file was read (this computer's clock): the evidence the file was there then (C2-10).
    # None: the save's time.
    read_at: float | None = None


@dataclass(frozen=True)
class RawRow:
    """A ``raw_layers`` row."""
    path: str
    shot: int
    name: str
    size: int
    mtime_ns: int
    sha256: str
    parser: int
    encoding: str
    facts: dict[str, Any]
    pulses: int
    file: str
    bytes: int
    seen_at: float
    gone_at: float | None
    maker: str
    job_seq: int
    saved_at: float
    last_used: float


@dataclass(frozen=True)
class RawOverwrite:
    """A raw file overwritten in place since HeLab cached it (Q22.5, Q28.6): the shot, its file's name,
    and the old and new (size, mtime_ns, sha256)."""
    shot: int
    name: str
    old: tuple[int, int, str]
    new: tuple[int, int, str]


@dataclass(frozen=True)
class RawSave:
    """One raw batch's save: the shots ``saved`` (new or replaced), ``kept`` (the same file already
    cached), ``refused`` (a job that listed the folder later saved another version), ``overwritten``
    (raw files changed in place), or nothing at all when it didn't fit (``reason`` ``over_budget``:
    never a pending save, T~1). With usage after it, in the store's write order."""
    saved: tuple[int, ...]
    kept: tuple[int, ...]
    refused: tuple[int, ...]
    overwritten: tuple[RawOverwrite, ...]
    reason: str
    bytes: int
    usage: int
    usage_seq: int
    budget: int | None


@dataclass(frozen=True)
class RawRemoval:
    """What a removal of raw layers did: the folders (None: every one), rows and bytes."""
    paths: tuple[str, ...] | None
    rows: int
    bytes: int


# TXY layers (store-v4, caching v2 stage 2: design addendum §2–§8).

def _txy_epoch(key: str) -> str:
    """The ``folder_epochs`` row a removal of one folder's TXY layers bumps (``txy:<key>``, store-v4)."""
    return f"txy:{key}"


TXY_KINDS = ("raw", "txy")
# A layer of more segments than this is compacted when it fits (Q45.7); a hit row is three float64.
COMPACT_SEGMENTS = 8
TXY_ROW_BYTES = 24
_MATLAB_LAYER, _HELAB_LAYER = "matlab", "helab:"
_TXY_LAYER_COLUMNS = ("path, layer, tags, entries, rows, ram_bytes, bytes, precision, gone_at, job_seq, saved_at, "
                      "last_used")  # (A shot's fingerprint: its raw file's, or its TXY file's: Q45.3.)


@dataclass(frozen=True)
class TxyShot:
    """One shot of a save's layer part: its source's fingerprint and ``kind`` (``raw``: the raw file's,
    wherever one is listed; ``txy``: the TXY file's, Q45.3), its hit count, and whether it was problematic."""
    shot: int
    size: int
    mtime_ns: int
    kind: str
    rows: int
    problematic: bool = False


@dataclass(frozen=True)
class TxyPart:
    """One layer's new segment in a save unit (``write_txy_file`` published it): the shots it holds, the
    layer's tag names (display only, Q22.2) and precision (``g8`` or ``f64``)."""
    layer: str
    file: str
    shots: tuple[TxyShot, ...]
    tags: tuple[str, ...] = ()
    precision: str = "g8"

    def to_json(self, size: int, guard: SaveGuard) -> dict[str, Any]:
        """As a waiting save keeps it (``pending_saves.parts``), with its job's guard (Q45.8)."""
        return {"layer": self.layer, "file": self.file, "bytes": size, "tags": list(self.tags),
                "precision": self.precision, "job_seq": guard.job_seq,
                "shots": [[item.shot, item.size, item.mtime_ns, item.kind, item.rows, int(item.problematic)]
                          for item in self.shots],
                "guard": {"generations": dict(guard.generations), "epochs": dict(guard.epochs)}}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> TxyPart:
        return cls(str(value["layer"]), str(value["file"]),
                   tuple(TxyShot(int(shot), int(size), int(mtime), str(kind), int(rows), bool(flag))
                         for shot, size, mtime, kind, rows, flag in value["shots"]),
                   tuple(str(tag) for tag in value.get("tags", ())), str(value.get("precision", "g8")))


@dataclass(frozen=True)
class TxyEntry:
    """A shot of a ``txy_layers`` row: its fingerprint and kind, the segment holding it (``seq``), its hit
    count, whether problematic, and the job that saved it (only a later job replaces it)."""
    shot: int
    size: int
    mtime_ns: int
    kind: str
    seq: int
    rows: int
    problematic: bool
    job_seq: int

    def to_json(self) -> list[Any]:
        return [self.shot, self.size, self.mtime_ns, self.kind, self.seq, self.rows, int(self.problematic),
                self.job_seq]

    @classmethod
    def from_json(cls, value: Sequence[Any]) -> TxyEntry:
        shot, size, mtime, kind, seq, rows, flag, job_seq = value
        return cls(int(shot), int(size), int(mtime), str(kind), int(seq), int(rows), bool(flag), int(job_seq))


@dataclass(frozen=True)
class TxyLayerRow:
    """A folder's layer: its shots (``entries``), totals, precision, when a listing last found some of its
    sources gone (``gone_at``: the layer is then an only copy, Q45.6), and its segments (seq → file, bytes)."""
    path: str
    layer: str
    tags: tuple[str, ...]
    entries: dict[int, TxyEntry]
    rows: int
    ram_bytes: int
    bytes: int
    precision: str
    gone_at: float | None
    job_seq: int
    saved_at: float
    last_used: float
    segments: dict[int, tuple[str, int]]


class ViewRecord(TypedDict):
    """What a save keeps of a composition (``txy_views``): ``fingerprint`` ``[shot, size, mtime_ns, kind,
    layer, [entry size, entry mtime_ns, entry kind]]`` of each shot (the last: the layer entry's key the view
    was saved with; a view saved before it has five items), ``problematic``, ``info`` (today's
    ``datasets.info``: listing, signature, the TXY record) and ``raw_times``."""
    fingerprint: list[list[Any]]
    problematic: list[int]
    info: dict[str, Any]
    raw_times: NotRequired[list[list[int]]]


@dataclass(frozen=True)
class ViewRow:
    path: str
    source: str
    tag: str
    fingerprint: list[list[Any]]
    problematic: list[int]
    raw_times: list[list[int]]
    info: dict[str, Any]
    job_seq: int
    last_used: float


@dataclass(frozen=True)
class TxySave:
    """One save unit's outcome: the layers ``saved``, or the whole unit held as ``pending_id`` (``reason``
    ``over_budget`` or ``needs_approval``; one waiting unit per folder, Q45.8); ``refused`` (layer, shot)
    pairs a later job saved; ``dropped`` layers the folder's policy doesn't write (``raw``: no HeLab layer).
    With usage after it, in the store's write order."""
    saved: tuple[str, ...]
    refused: tuple[tuple[str, int], ...]
    dropped: tuple[str, ...]
    reason: str
    pending_id: str
    bytes: int
    usage: int
    usage_seq: int
    budget: int | None


@dataclass(frozen=True)
class TxyRemoval:
    """What a removal of TXY layers did: the folders (None: every one), layers and bytes."""
    paths: tuple[str, ...] | None
    layers: int
    bytes: int


def _combined_removal(removed: Sequence[Removal]) -> Removal | None:
    """Make room's or ``trim``'s removals as one (None for none), in the order they were made."""
    if not removed:
        return None
    return Removal(("datasets",), tuple(path for item in removed for path in item.paths or ()),
                   sum(item.datasets for item in removed), sum(item.dataset_bytes for item in removed),
                   tuple(path for item in removed for path in item.raw_paths),
                   tuple(path for item in removed for path in item.only_copy_paths),
                   sum(item.raw_rows for item in removed), sum(item.raw_bytes for item in removed),
                   tuple(pair for item in removed for pair in item.txy_layers),
                   tuple(pair for item in removed for pair in item.txy_seen),
                   tuple(pair for item in removed for pair in item.txy_only),
                   sum(item.txy_bytes for item in removed))


def _removal_items(removal: Removal) -> tuple[str, ...]:
    """A removal as Make room's items (``room_items``)."""
    return room_items(removal.paths or (), removal.raw_paths, removal.only_copy_paths, removal.txy_layers,
                      removal.txy_seen, removal.txy_only)


def txy_item(prefix: str, path: str, layer: str) -> str:
    """A folder's layer as Make room names it (``<prefix><layer>:<path>``; compared, never parsed)."""
    return f"{prefix}{layer}:{path}"


@dataclass(frozen=True)
class AdoptResult:
    path: str
    adopted: bool
    bytes: int
    # Not adopted: it doesn't fit, and this is what Make room would remove.
    room: RoomPlan | None = None
    # Adopted with Make room: what was removed.
    removal: Removal | None = None


@dataclass(frozen=True)
class Sweep:
    deleted_files: int = 0
    expired_pending: int = 0
    expired_ids: list[str] = field(default_factory=list)
    still_open: list[str] = field(default_factory=list)
    next_deadline: float | None = None


# The live store's layout in this process (caching v2's switch, Q28.3): read once, at the first
# ``store_root``, from the ``store_v4`` settings row; never again, so a running HeLab never changes
# store under its helpers. Helpers never read it: they open the folder they are sent.
_live_layout: int | None = None


def live_layout() -> int:
    global _live_layout
    if _live_layout is None:
        from helab.utils.cache_setting import store_v4_enabled
        from helab.utils.settings_store import app_settings
        _live_layout = store_v4.LAYOUT if store_v4_enabled(app_settings()) else LAYOUT_VERSION
    return _live_layout


def _reset_live_layout(layout: int | None = None) -> None:
    """Tests: the layout the next ``store_root`` uses (None: read the setting again)."""
    global _live_layout
    _live_layout = layout


# Keep's read-through of an older HeLab's store-v3 lasts through v0.0.8 only (Tony, V~3, 2026-11-03): from
# v0.0.9 store-v4 reads it no more and counts it in no budget; Settings › Cache's Older cache Clear… (or Make
# room's Clear old stores…) still removes it.
LEGACY_READ_UNTIL = (0, 0, 9)


def legacy_read_through(version: str | None = None) -> bool:
    """Whether Keep still reads store-v3 (V~3): this HeLab's release (``helab._version``) before
    ``LEGACY_READ_UNTIL``."""
    import re
    from helab._version import __version__
    found = re.match(r"(\d+)\.(\d+)\.(\d+)", version or __version__)
    if found is None:
        return False
    return tuple(int(part) for part in found.groups()) < LEGACY_READ_UNTIL


def store_root(caches_dir: str) -> str:
    """The live store's folder in the cache folder: store-v3, or store-v4 with the switch on. Under v4
    this process's session maker goes into its environment first, for the helpers it starts."""
    layout = live_layout()
    if layout >= store_v4.LAYOUT:
        store_v4.session_maker()
    return store_root_for(caches_dir, layout)


def store_root_for(caches_dir: str, layout: int) -> str:
    return os.path.join(caches_dir, store_v4.DIRNAME if layout >= store_v4.LAYOUT else STORE_DIRNAME)


def layout_of(root: str) -> int:
    """A store folder's layout, from its name: ``store-v4`` is layout 4, anything else 3."""
    return store_v4.LAYOUT if os.path.basename(os.path.normpath(root)) == store_v4.DIRNAME else LAYOUT_VERSION


def remove_old_caches(caches_dir: str, progress: Callable[[], None] = lambda: None) -> list[str]:
    """Delete the diskcache folders HeLab used before this store; their contents are dropped,
    not migrated. Returns the folders now gone. ``progress`` is called per deleted entry."""
    removed = []
    for name in OLD_CACHE_DIRS:
        folder = os.path.join(caches_dir, name)
        if os.path.islink(folder) or not os.path.isdir(folder):
            continue
        for parent, folders, files in os.walk(folder, topdown=False):
            for entry in files:
                with contextlib.suppress(OSError):
                    os.remove(os.path.join(parent, entry))
                progress()
            for entry in folders:
                with contextlib.suppress(OSError):
                    os.rmdir(os.path.join(parent, entry))
        with contextlib.suppress(OSError):
            os.rmdir(folder)
        if not os.path.exists(folder):
            removed.append(name)
    return removed


def pack_dataset(data: Mapping[int, Any]) -> bytes:
    """Blosc zstd-9 pickle of ``{shot: float64 array (n, 3)}`` (``DATASET_FORMAT``)."""
    import blosc
    import pickle
    packed: bytes = blosc.compress(pickle.dumps(dict(sorted(data.items())), protocol=pickle.HIGHEST_PROTOCOL),
                                   typesize=8, cname="zstd", clevel=9, shuffle=blosc.NOSHUFFLE)
    return packed


def unpack_dataset(packed: bytes) -> dict[int, Any] | None:
    """The shots in a dataset file, or None if it isn't a valid dataset."""
    import blosc
    import numpy as np
    import pickle
    unpacked = pickle.loads(blosc.decompress(packed))
    valid = isinstance(unpacked, dict) and all(
        isinstance(shot, int) and isinstance(array, np.ndarray) and array.ndim == 2 and array.shape[1] == 3
        for shot, array in unpacked.items())
    return cast(dict[int, Any], unpacked) if valid else None


def _dumps(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))


def _constant_values(values: object) -> dict[str, float]:
    """A folder's constants as saved: names with finite numbers (which constants exist, and
    their limits, is the app's business: ``helab.analysis.constant_layers.clean_layer``)."""
    if not isinstance(values, Mapping):
        return {}
    return {str(key): float(value) for key, value in values.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)}


def _record_bytes(record: Mapping[str, Any]) -> int:
    """About what a dataset row adds to the records database (its JSON columns)."""
    return len(_dumps(record))


class CacheStore:
    """One connection to a store. Not thread-safe: one per helper process."""

    def __init__(self, root: str, *, busy_timeout: float | None = None,
                 path_key: Callable[[str], str] | None = None,
                 source_path: Callable[[str], str] | None = None,
                 root_mode: bool = False, maker: dict[str, Any] | None = None) -> None:
        busy_timeout = BUSY_TIMEOUT if busy_timeout is None else busy_timeout
        self._busy_timeout = busy_timeout
        self.root = root
        self._path_key = path_key or (lambda path: path)
        self._source_path = source_path or (lambda path: path)
        self._location_key: Callable[[str], str] = lambda path: path
        # A root location's folder on this computer now, or the location itself if not mounted.
        self._location_source: Callable[[str], str] = lambda location: location
        # The layout is the folder's: store-v3 or store-v4 (caching v2, ``store_v4``).
        self.layout = layout_of(root)
        self._expected_layout = self.layout
        self._root_mode = root_mode
        self._maker = maker
        self._legacy: LegacyStore | None = None
        self._legacy_tried = False
        self.datasets_dir = os.path.join(root, "datasets")
        self.raw_dir = os.path.join(root, store_v4.RAW_DIRNAME)
        self.txy_dir = os.path.join(root, store_v4.TXY_DIRNAME)
        self.results_dir = os.path.join(root, RESULTS_DIRNAME)
        self.database = os.path.join(root, "records.sqlite")
        self.read_only = False
        self._depth = 0
        # Mount paths whose volume hints the opener didn't trust (io_helper's local lane, with
        # ``verified_volumes``): a folder there has no key until they are verified.
        self._unverified_mounts: list[str] = []
        self._writing = False
        for attempt in range(OPEN_ATTEMPTS):
            conn: sqlite3.Connection | None = None
            self.read_only = False  # (An attempt that failed may have set it.)
            try:
                self._conn = conn = self._open(busy_timeout)
                # (A read-only store may lack the column or the table: it then has no raw times, and
                # no folder sets constants.)
                self._raw_times = "raw_times" if _has_raw_times(self._conn) else "'[]'"
                # (store-v4's waiting layer parts, Q45.8; a read-only store from before stage 2 has none.)
                self._pending_parts = _has_column(self._conn, "pending_saves", "parts")
                self._constants_table = _has_table(self._conn, "folder_constants")
                self._presets_table = _has_table(self._conn, "presets")
                # (Nor the results table: it then has no results saved, and saves none.)
                self._results_table = _has_table(self._conn, "results")
                # (Nor the listings table: no folder was listed for offline browsing.)
                self._listings_table = _has_table(self._conn, "listings")
                self._mount_hints_table = _has_table(self._conn, "mount_hints")
                self._pending_results = _has_table(self._conn, "pending_results")
                meta = self._meta()
                self.layout_version = int(meta["layout_version"])
                self.store_id = str(meta["store_id"])
                break
            except sqlite3.Error as exc:
                if conn is not None:
                    conn.close()
                if _transient_io_error(exc) and attempt + 1 < OPEN_ATTEMPTS:
                    _sleep(OPEN_RETRY_SECONDS * 2 ** attempt)
                    continue
                raise StoreError(f"{OPEN_FAILED}: {exc}") from exc

    # Opening and transactions

    def _connect(self, busy_timeout: float, read_only: bool) -> sqlite3.Connection:
        if read_only:
            # Percent-encoded, so "%", "?" or "#" in the folder name aren't read as URI syntax.
            uri = pathlib.Path(os.path.abspath(self.database)).as_uri()
            conn = sqlite3.connect(f"{uri}?mode=ro", uri=True,
                                   timeout=busy_timeout, isolation_level=None)
        else:
            conn = sqlite3.connect(self.database, timeout=busy_timeout, isolation_level=None)
        # A lock held longer than this is an error, never a miss.
        conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout * 1000)}")
        return conn

    def _open(self, busy_timeout: float) -> sqlite3.Connection:
        if os.path.exists(self.database):
            # Read the layout before writing anything: a newer layout is left untouched.
            probe = self._connect(busy_timeout, read_only=True)
            try:
                version = _layout_version(probe)
                # (A store-v4 of a newer format: read, never rewritten.)
                newer_format = version == store_v4.LAYOUT and _store_format(probe) > store_v4.FORMAT
            finally:
                probe.close()
            if version is not None and version > self._expected_layout or (
                    version == self._expected_layout and newer_format):
                self.read_only = True
                return self._connect(busy_timeout, read_only=True)
            if version is not None and version < self._expected_layout:
                raise sqlite3.DatabaseError(f"unsupported layout version {version}")
        os.makedirs(self.datasets_dir, exist_ok=True)
        os.makedirs(self.results_dir, exist_ok=True)
        if self.layout >= store_v4.LAYOUT:
            os.makedirs(self.raw_dir, exist_ok=True)
            os.makedirs(self.txy_dir, exist_ok=True)
        conn = self._connect(busy_timeout, read_only=False)
        try:
            if _layout_version(conn) is None:
                _wal(conn, busy_timeout)
                conn.execute("BEGIN IMMEDIATE")
                try:
                    # Checked again under the write lock: another helper opening the same new store may have
                    # made it meanwhile, and store-v4's schema adds columns (ALTER TABLE), which can't run twice.
                    if _layout_version(conn) is not None:
                        conn.execute("COMMIT")
                    else:
                        self._create(conn)
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
            version = _layout_version(conn)
            if version != self._expected_layout:
                raise sqlite3.DatabaseError(f"unsupported layout version {version}")
            _migrate(conn)
            if self.layout >= store_v4.LAYOUT:
                store_v4.migrate(conn)
                # The user's own state in store-v3, once (Q22.4; v3 read only, through LegacyStore).
                store_v4.import_legacy(conn, self.legacy_root, time.time())
        except BaseException:
            conn.close()
            raise
        return conn

    def _create(self, conn: sqlite3.Connection) -> None:
        """A new store's tables and meta (inside the caller's write transaction), then COMMIT."""
        for statement in SCHEMA.split(";"):
            if statement.strip():
                conn.execute(statement)
        for statement in ROOT_SCHEMA.split(";"):
            if statement.strip():
                conn.execute(statement)
        if self.layout >= store_v4.LAYOUT:
            for statement in (*store_v4.SCHEMA, *store_v4.STAGE2_SCHEMA):
                conn.execute(statement)
        defaults: dict[str, object] = {
            "layout_version": self._expected_layout, "store_id": uuid.uuid4().hex, "created_at": time.time(),
            **{f"gen_{kind}": 0 for kind in KINDS}, "gen_results": 0,
            **(store_v4.META_DEFAULTS if self.layout >= store_v4.LAYOUT else {})}
        # Another helper may have created it meanwhile: keep its values.
        conn.executemany("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                         [(key, _dumps(value)) for key, value in defaults.items()])
        conn.execute("COMMIT")

    def close(self) -> None:
        if self._legacy is not None:
            self._legacy.close()
            self._legacy = None
        self._conn.close()

    # store-v3 beside a store-v4 (caching v2): read only, through LegacyStore alone.

    @property
    def legacy_root(self) -> str:
        from helab.utils.legacy_store import legacy_root
        return legacy_root(self.root)

    def _kept_legacy(self) -> LegacyStore | None:
        """store-v3, read only, while it is kept (Keep, or not answered yet: Q22.3); None under v3
        itself, after Ignore or Clear, or when there is none or it can't be read now, and from v0.0.9 on
        (Keep's read-through ends then, V~3: only Settings › Cache's Older cache Clear…, or Make room's
        Clear old stores…, remains)."""
        if self.layout < store_v4.LAYOUT or not legacy_read_through():
            return None
        if self._legacy_choice() not in (None, "keep"):
            return None
        if self._legacy is None and not self._legacy_tried:
            self._legacy_tried = True
            from helab.utils.legacy_store import present
            if present(self.legacy_root):
                with contextlib.suppress(LegacyUnavailable):
                    self._legacy = LegacyStore(self.legacy_root)
        return self._legacy

    def _legacy_choice(self, meta: dict[str, Any] | None = None) -> str | None:
        """The store-v3 choice (``store_v4.legacy_choice``) for the store-v3 here now (C3-3). After Clear, a
        store-v3 present again is one an older HeLab made since: unanswered (kept meanwhile, and asked about
        again). Under Keep, ``measure_legacy`` compares the ``store_id`` it reads anyway. Ignore holds for
        whatever store-v3 is here: an ignored one is never opened to tell."""
        choice = store_v4.legacy_choice(self._meta() if meta is None else meta)
        if choice == "clear":
            from helab.utils.legacy_store import present
            if present(self.legacy_root):
                return None
        return choice

    def _legacy_leftovers(self) -> list[dict[str, Any]]:
        """``store-v3.clearing-<8 hex>`` folders beside this store: a Clear of store-v3 renamed it aside and
        couldn't remove all of it (a file held open, say on Windows; C3-4). HeLab's own, already asked for:
        Settings › Cache's Older cache row shows them with its Clear…; never removed without asking."""
        from helab.utils.legacy_store import DIRNAME
        prefix = DIRNAME + LEGACY_CLEARING
        found: list[dict[str, Any]] = []
        with contextlib.suppress(OSError):
            for entry in sorted(os.scandir(os.path.dirname(self.legacy_root)), key=lambda item: item.name):
                suffix = entry.name[len(prefix):]
                if (entry.name.startswith(prefix) and len(suffix) == 8
                        and all(char in "0123456789abcdef" for char in suffix)
                        and entry.is_dir(follow_symlinks=False)):
                    found.append({"name": entry.name, "bytes": _folder_bytes(entry.path)})
        return found

    def _legacy_hidden(self, kind: str, key: str) -> bool:
        """Whether store-v4 has removed ``kind`` (a record kind, or ``results``) for ``key`` since it was
        made, so store-v3's row must not be read through (C2-1): the kind's generation, the key's epoch
        or its root's moved, or a save deleted the row (a tombstone, ``_LEGACY_HIDDEN``). (Inside a
        transaction.)"""
        meta = self._meta()
        results = kind == "results"
        if int(meta.get("gen_results" if results else f"gen_{kind}", 0)):
            return True
        epoch = _results_epoch(key) if results else store_v4.epoch_key(self.layout, kind, key)
        root = _results_root_epoch(key) if results else _root_epoch(key)
        return bool(self._epoch(epoch) or (root is not None and self._epoch(root))
                    or self._epoch(f"{_LEGACY_HIDDEN}{kind}:{key}"))

    def _legacy_purged(self, kind: str) -> tuple[float | None, float | None]:
        """The purges by age of ``kind`` in store-v4: the latest cutoff, and the latest of those that took
        scan histories with failures too (C2-7); store-v3's rows from before them are hidden too."""
        found = self._meta().get("legacy_purged")
        entry = found.get(kind) if isinstance(found, dict) else None
        if not isinstance(entry, list) or len(entry) != 2 or not isinstance(entry[0], (int, float)):
            return None, None
        failures = entry[1]
        return float(entry[0]), float(failures) if isinstance(failures, (int, float)) and not isinstance(
            failures, bool) else None

    def _note_purge(self, kind: str, cutoff: float, include_failures: bool = False) -> None:
        """Record a purge by age (inside its transaction) while store-v3 may be read through: each of the
        two cutoffs only ever grows."""
        if self.layout < store_v4.LAYOUT:
            return
        found = self._meta().get("legacy_purged")
        purged = dict(found) if isinstance(found, dict) else {}
        before, failures = self._legacy_purged(kind)
        latest = cutoff if before is None else max(before, cutoff)
        if include_failures:
            failures = cutoff if failures is None else max(failures, cutoff)
        purged[kind] = [latest, failures]
        self._conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('legacy_purged', ?)", (_dumps(purged),))

    def _maker_id(self) -> str:
        """In store-v4, this session's maker row (written inside the caller's write transaction) and
        its id; "" in store-v3, which keeps none."""
        if self.layout < store_v4.LAYOUT:
            return ""
        if self._maker is None:
            self._maker = store_v4.session_maker()
        return store_v4.ensure_maker(self._conn, self._maker)

    def __enter__(self) -> CacheStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def root_locations(self) -> list[tuple[str, str, str]]:
        """Return the local root-location index without touching source folders."""
        try:
            rows = self._conn.execute("SELECT location, uuid, decision FROM roots").fetchall()
        except sqlite3.Error as exc:
            raise StoreError(f"Data roots could not be read: {exc}") from exc
        return [(str(location), str(identifier), str(decision))
                for location, identifier, decision in rows]

    def root_rows(self) -> list[dict[str, Any]]:
        """Every remembered root location, for Settings → Cache."""
        try:
            rows = self._conn.execute(
                "SELECT location, uuid, kind, label, first_seen, last_seen, decision FROM roots "
                "ORDER BY label, location").fetchall()
        except sqlite3.Error as exc:
            raise StoreError(f"Data roots could not be read: {exc}") from exc
        return [{"location": str(location), "uuid": str(identifier), "kind": str(kind), "label": str(label),
                 "first_seen": float(first), "last_seen": float(last), "decision": str(decision)}
                for location, identifier, kind, label, first, last, decision in rows]

    def root_at(self, location: str) -> tuple[str, str, str] | None:
        try:
            row = self._conn.execute(
                "SELECT uuid, label, decision FROM roots WHERE location=?", (location,)).fetchone()
        except sqlite3.Error as exc:
            raise StoreError(f"Data roots could not be read: {exc}") from exc
        return (str(row[0]), str(row[1]), str(row[2])) if row is not None else None

    def other_root_locations(self, identifier: str, location: str) -> list[str]:
        try:
            rows = self._conn.execute(
                "SELECT location FROM roots WHERE uuid=? AND location<>? AND decision='confirmed'",
                (identifier, location)).fetchall()
        except sqlite3.Error as exc:
            raise StoreError(f"Data roots could not be read: {exc}") from exc
        return [str(row[0]) for row in rows]

    def volume_locations(self) -> list[tuple[str, str, str]]:
        """Mounted-volume hints captured earlier by source helpers."""
        try:
            rows = self._conn.execute(
                "SELECT mount_path, mount_source, volume_id FROM root_volumes").fetchall()
        except sqlite3.Error as exc:
            raise StoreError(f"Data-root volumes could not be read: {exc}") from exc
        return [(str(path), str(source), str(identifier)) for path, source, identifier in rows]

    def mount_hints(self) -> dict[str, str]:
        """The share or volume last seen at each mount path (location tops), for offline keys; {}
        for a read-only store from before them."""
        if not self._mount_hints_table:
            return {}
        try:
            rows = self._conn.execute("SELECT mount_path, location FROM mount_hints").fetchall()
        except sqlite3.Error as exc:
            raise StoreError(f"Mount hints could not be read: {exc}") from exc
        return {str(path): str(location) for path, location in rows}

    def record_mount_hint(self, mount_path: str, location: str) -> None:
        with self.transaction():
            self._conn.execute(
                "INSERT INTO mount_hints (mount_path, location, seen_at) VALUES (?, ?, ?) "
                "ON CONFLICT(mount_path) DO UPDATE SET location=excluded.location, seen_at=excluded.seen_at",
                (mount_path, location, time.time()))

    def record_volume(self, mount_path: str, mount_source: str, identifier: str) -> None:
        with self.transaction():
            self._conn.execute(
                "INSERT INTO root_volumes (mount_path, mount_source, volume_id, seen_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(mount_path, mount_source) DO UPDATE SET "
                "volume_id=excluded.volume_id, seen_at=excluded.seen_at",
                (mount_path, mount_source, identifier, time.time()))

    def forget_root(self, location: str) -> None:
        """A listing saw that this folder no longer contains its marker."""
        with self.transaction():
            self._conn.execute("DELETE FROM roots WHERE location=?", (location,))
            if self.layout >= store_v4.LAYOUT:
                store_v4.note_forgotten(self._conn, [location])  # (Not brought back by a later import: C2-5.)

    def forget_root_tree(self, locations: list[str], identifier: str) -> list[str]:
        """Its marker was deleted: forget these locations of ``identifier`` and its locations below
        them. Data rows stay with the UUID. Returns the locations forgotten."""
        with self.transaction():
            rows = [str(row[0]) for row in self._conn.execute(
                "SELECT location FROM roots WHERE uuid=?", (identifier,))]
            gone = [location for location in rows if any(
                location == top or location.startswith(top.rstrip("/") + "/") for top in locations)]
            self._conn.executemany("DELETE FROM roots WHERE location=?", [(location,) for location in gone])
            if self.layout >= store_v4.LAYOUT:
                store_v4.note_forgotten(self._conn, gone)  # (Not brought back by a later import: C2-5.)
        return gone

    def confirm_root(self, location: str, identifier: str) -> bool:
        """The user said a pending location is the same folder as the root's others (D4)."""
        with self.transaction():
            changed = self._conn.execute(
                "UPDATE roots SET decision='confirmed', verified_at=? WHERE location=? AND uuid=?",
                (time.time(), location, identifier)).rowcount
        return bool(changed)

    def reassign_roots(self, old: str, new: str, label: str, *, only: str | None = None,
                       keep: str | None = None) -> list[str]:
        """A copy got a new marker (D4): move its location (``only``), or every confirmed location of
        ``old`` but ``keep`` (the copy is the folder those reach), to ``new``. Data rows stay with
        ``old``, so the copy starts fresh. Returns the locations moved."""
        now = time.time()
        with self.transaction():
            if only is not None:
                rows = self._conn.execute("SELECT location FROM roots WHERE location=? AND uuid=?",
                                          (only, old)).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT location FROM roots WHERE uuid=? AND decision='confirmed' AND location<>?",
                    (old, keep or "")).fetchall()
            moved = [str(row[0]) for row in rows]
            self._conn.executemany(
                "UPDATE roots SET uuid=?, label=?, decision='confirmed', first_seen=?, last_seen=?, verified_at=? "
                "WHERE location=?", [(new, label, now, now, now, location) for location in moved])
        return moved

    def record_root(self, location: str, identifier: str, kind: str,
                    label: str, *, decision: Literal["confirmed", "pending"]) -> None:
        """Record a marker decision, retaining the location's first sighting."""
        now = time.time()
        with self.transaction():
            self._conn.execute(
                "INSERT INTO roots (location, uuid, kind, label, first_seen, last_seen, verified_at, decision) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(location) DO UPDATE SET "
                "uuid=excluded.uuid, kind=excluded.kind, label=excluded.label, "
                "first_seen=CASE WHEN roots.uuid=excluded.uuid THEN roots.first_seen ELSE excluded.first_seen END, "
                "last_seen=excluded.last_seen, verified_at=excluded.verified_at, decision=excluded.decision",
                (location, identifier, kind, label, now, now, now, decision))

    def rekey_subtree(self, old: str, new: str) -> list[str]:
        """Move rows below a newly found nested marker in one transaction.

        The newer row wins a collision. Replaced dataset files are retired so
        concurrent readers can finish before the sweep deletes them.
        Returns the old stored keys whose in-memory flags must be reset.
        """
        if not old.startswith("root://") or not new.startswith("root://") or old == new:
            return []
        tables = ("folder_epochs", "folder_summaries", "scan_histories", "subtrees", "listings",
                  "folder_prefs", "convert_prefs", "folder_constants", "pending_saves", "datasets",
                  "cache_policy", "txy_source_prefs")
        timestamps = {"folder_summaries": "saved_at", "scan_histories": "saved_at",
                      "subtrees": "saved_at", "listings": "saved_at", "folder_prefs": "set_at",
                      "convert_prefs": "set_at", "folder_constants": "set_at",
                      "pending_saves": "created_at", "datasets": "last_used",
                      "cache_policy": "set_at", "txy_source_prefs": "set_at"}
        moved: set[str] = set()
        try:
            with self.transaction():
                for table in tables:
                    if not _has_table(self._conn, table):
                        continue  # (A store this HeLab couldn't bring up to date: nothing to move.)
                    columns = [str(row[1]) for row in self._conn.execute(f"PRAGMA table_info({table})")]
                    rows = self._conn.execute(
                        f"SELECT * FROM {table} WHERE path=? OR (path>=? AND path<?)",
                        (old, old + "/", old + "0")).fetchall()
                    for row in rows:
                        values = dict(zip(columns, row))
                        source = str(values["path"])
                        target = new + source[len(old):]
                        previous = self._conn.execute(
                            f"SELECT * FROM {table} WHERE path=?", (target,)).fetchone()
                        moved.add(source)
                        if previous is not None:
                            existing = dict(zip(columns, previous))
                            if table == "folder_epochs":
                                self._conn.execute(
                                    "UPDATE folder_epochs SET epoch=?, job_seq=? WHERE path=?",
                                    (max(int(values["epoch"]), int(existing["epoch"])),
                                     max(int(values["job_seq"]), int(existing["job_seq"])), target))
                                self._conn.execute("DELETE FROM folder_epochs WHERE path=?", (source,))
                                continue
                            stamp = timestamps[table]
                            source_wins = float(values[stamp]) > float(existing[stamp])
                            if table in ("datasets", "pending_saves"):
                                loser = existing if source_wins else values
                                self._retire(str(loser["file"]), time.time())
                                for part in json.loads(str(loser.get("parts") or "[]")):
                                    self._retire(str(part["file"]), time.time())
                            if not source_wins:
                                self._conn.execute(f"DELETE FROM {table} WHERE path=?", (source,))
                                continue
                            self._conn.execute(f"DELETE FROM {table} WHERE path=?", (target,))
                        self._conn.execute(f"UPDATE {table} SET path=? WHERE path=?", (target, source))
                moved.update(self._rekey_results(old, new))
                moved.update(self._rekey_sets(old, new))
            return sorted(moved)
        except sqlite3.Error as exc:
            raise StoreError(f"Data-root subtree could not be re-keyed: {exc}") from exc

    def _rekey_sets(self, old: str, new: str) -> set[str]:
        """:meth:`rekey_subtree` of store-v4's tables with many rows per folder (S2-0: stage 1 left raw layers
        under the old key, unused but counted). A raw layer row moves per shot (the newer saved wins); a
        folder's TXY layers, segments and views move as one set (a folder held at both keys keeps the newer
        set). The loser's files are retired."""
        if self.layout < store_v4.LAYOUT:
            return set()
        moved: set[str] = set()
        now = time.time()
        span = (old, old + "/", old + "0")

        def folders(table: str) -> list[str]:
            return sorted({str(path) for (path,) in self._conn.execute(
                f"SELECT DISTINCT path FROM {table} WHERE path=? OR (path>=? AND path<?)", span)})

        for source in folders("raw_layers"):
            target = new + source[len(old):]
            moved.add(source)
            for shot, saved_at, file in self._conn.execute("SELECT shot, saved_at, file FROM raw_layers WHERE path=?",
                                                           (source,)).fetchall():
                previous = self._conn.execute("SELECT saved_at, file FROM raw_layers WHERE path=? AND shot=?",
                                              (target, shot)).fetchone()
                if previous is not None:
                    if float(previous[0]) >= float(saved_at):
                        self._retire(str(file), now)
                        self._conn.execute("DELETE FROM raw_layers WHERE path=? AND shot=?", (source, shot))
                        continue
                    self._retire(str(previous[1]), now)
                    self._conn.execute("DELETE FROM raw_layers WHERE path=? AND shot=?", (target, shot))
                self._conn.execute("UPDATE raw_layers SET path=? WHERE path=? AND shot=?", (target, source, shot))

        def newest(key: str) -> float | None:
            row = self._conn.execute("SELECT MAX(stamp) FROM (SELECT saved_at AS stamp FROM txy_layers WHERE path=? "
                                     "UNION ALL SELECT last_used FROM txy_views WHERE path=?)", (key, key)).fetchone()
            return None if row[0] is None else float(row[0])

        def drop(key: str) -> None:
            for (file,) in self._conn.execute("SELECT file FROM txy_segments WHERE path=?", (key,)).fetchall():
                self._retire(str(file), now)
            for table in ("txy_segments", "txy_layers", "txy_views"):
                self._conn.execute(f"DELETE FROM {table} WHERE path=?", (key,))

        for source in sorted({*folders("txy_layers"), *folders("txy_views")}):
            target = new + source[len(old):]
            moved.add(source)
            theirs, mine = newest(target), newest(source)
            if theirs is not None:
                if theirs >= (mine or 0.0):
                    drop(source)
                    continue
                drop(target)
            for table in ("txy_segments", "txy_layers", "txy_views"):
                self._conn.execute(f"UPDATE {table} SET path=? WHERE path=?", (target, source))
        return moved

    def _rekey_results(self, old: str, new: str) -> set[str]:
        """:meth:`rekey_subtree` of saved results (many rows per folder): each moves to its new
        key; under one key saved at both, the newer one wins and the other's file is retired."""
        if not self._results_table:
            return set()
        moved: set[str] = set()
        rows = self._conn.execute("SELECT result_id, path, lookup, saved_at, file FROM results "
                                  "WHERE path=? OR (path>=? AND path<?)", (old, old + "/", old + "0")).fetchall()
        for result_id, source, lookup, saved_at, file in rows:
            target = new + str(source)[len(old):]
            moved.add(str(source))
            previous = self._conn.execute("SELECT result_id, saved_at, file FROM results WHERE path=? AND lookup=?",
                                          (target, lookup)).fetchone()
            if previous is not None:
                if float(previous[1]) >= float(saved_at):
                    self._retire(str(file), time.time())
                    self._conn.execute("DELETE FROM results WHERE result_id=?", (result_id,))
                    continue
                self._retire(str(previous[2]), time.time())
                self._conn.execute("DELETE FROM results WHERE result_id=?", (previous[0],))
            self._conn.execute("UPDATE results SET path=? WHERE result_id=?", (target, result_id))
        if self._pending_results:
            # Results waiting for an answer move too; under a key held at both, the newer stays.
            for pending_id, source, lookup, created_at, file in self._conn.execute(
                    "SELECT pending_id, path, lookup, created_at, file FROM pending_results "
                    "WHERE path=? OR (path>=? AND path<?)", (old, old + "/", old + "0")).fetchall():
                target = new + str(source)[len(old):]
                moved.add(str(source))
                previous = self._conn.execute("SELECT pending_id, created_at, file FROM pending_results "
                                              "WHERE path=? AND lookup=?", (target, lookup)).fetchone()
                if previous is not None:
                    loser = (pending_id, file) if float(previous[1]) >= float(created_at) else (previous[0], previous[2])
                    self._retire(str(loser[1]), time.time())
                    self._conn.execute("DELETE FROM pending_results WHERE pending_id=?", (loser[0],))
                    if loser[0] == pending_id:
                        continue
                self._conn.execute("UPDATE pending_results SET path=? WHERE pending_id=?", (target, pending_id))
        return moved

    @contextlib.contextmanager
    def waiting(self, seconds: float) -> Generator[None, None, None]:
        """Wait at most ``seconds`` for the store's locks meanwhile (an optional write, such as a
        listing's, gives up rather than hold up its helper), then the store's own wait again."""
        self._conn.execute(f"PRAGMA busy_timeout = {int(seconds * 1000)}")
        try:
            yield
        finally:
            self._conn.execute(f"PRAGMA busy_timeout = {int(self._busy_timeout * 1000)}")

    @contextlib.contextmanager
    def transaction(self, write: bool = True) -> Generator[None, None, None]:
        """One SQLite transaction; nested calls join the outer one.

        A write transaction takes the write lock at once (``BEGIN IMMEDIATE``),
        so what it reads stays true until it commits.
        """
        if self._depth:
            if write and not self._writing:
                raise StoreError("A write inside a read transaction")
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        if write and self.read_only:
            raise StoreReadOnly("This disk cache was written by a newer HeLab and is read-only")
        try:
            self._conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache is busy or unavailable: {exc}") from exc
        self._depth, self._writing = 1, write
        try:
            if write:
                # Counts write transactions: orders usage measurements (see :meth:`usage`).
                self._conn.execute("INSERT INTO meta (key, value) VALUES ('writes', '1') "
                                   "ON CONFLICT (key) DO UPDATE SET value = CAST(value AS INTEGER) + 1")
            yield
            self._conn.execute("COMMIT")
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                self._conn.execute("ROLLBACK")
            raise
        finally:
            self._depth, self._writing = 0, False

    # Folder preferences (S10): set by the user, never removed to make room or by Clear all.

    def _no_cache(self, path: str) -> bool:
        row = self._conn.execute("SELECT no_cache FROM folder_prefs WHERE path = ?", (path,)).fetchone()
        return bool(row and row[0])

    def _check_cacheable(self, path: str) -> None:
        """Checked in every dataset save's transaction: a folder the user chose not to cache is
        never saved, even by a load that started before they chose."""
        if self._no_cache(path):
            raise SaveRejected("no_cache", NOT_CACHED)

    def read_prefs(self, paths: Sequence[str]) -> dict[str, Read[dict[str, Any]]]:
        """Each folder's flags (``no_cache``, ``no_auto_load``, ``set_at``); missing if none set."""
        unique = list(dict.fromkeys(paths))
        keys = list(dict.fromkeys(self._path_key(path) for path in unique))
        rows: dict[str, dict[str, Any]] = {}
        try:
            with self.transaction(write=False):
                for start in range(0, len(keys), 500):
                    chunk = keys[start:start + 500]
                    for path, no_cache, no_auto_load, set_at in self._conn.execute(
                            f"SELECT path, no_cache, no_auto_load, set_at FROM folder_prefs "
                            f"WHERE path IN ({','.join('?' * len(chunk))})", chunk):
                        rows[path] = {"no_cache": bool(no_cache), "no_auto_load": bool(no_auto_load),
                                      "set_at": float(set_at)}
        except (sqlite3.Error, StoreError) as exc:
            failure: Read[dict[str, Any]] = _error(f"Disk cache could not be read: {exc}")
            return {path: failure for path in unique}
        return {path: _found(rows[self._path_key(path)]) if self._path_key(path) in rows else _missing()
                for path in unique}

    def set_prefs(self, path: str, no_cache: bool, no_auto_load: bool, set_at: float) -> dict[str, Any]:
        """Set a folder's flags, unless a later choice (``set_at``, e.g. in another HeLab) is saved;
        returns the flags now saved. Flags turned off keep their row (with its ``set_at``), so an
        older choice arriving late can't bring them back."""
        return self.set_prefs_removing(path, no_cache, no_auto_load, set_at, remove_cached=False)[0]

    def set_prefs_removing(self, path: str, no_cache: bool, no_auto_load: bool, set_at: float, *,
                           remove_cached: bool) -> tuple[dict[str, Any], Removal | None]:
        """:meth:`set_prefs`, and with ``remove_cached`` also remove the folder's cached data, in
        the same transaction and only if this choice was the one saved (a superseded request
        removes nothing)."""
        path = self._path_key(path)
        try:
            with self.transaction():
                row = self._conn.execute("SELECT no_cache, no_auto_load, set_at FROM folder_prefs WHERE path = ?",
                                         (path,)).fetchone()
                cleared = float(self._meta().get("prefs_cleared_at", 0.0))
                if row is not None and float(row[2]) > set_at:
                    return {"no_cache": bool(row[0]), "no_auto_load": bool(row[1]), "set_at": float(row[2])}, None
                if cleared > set_at:
                    # Chosen before a Clear: that folder (saved or not) stays cleared.
                    return {"no_cache": False, "no_auto_load": False, "set_at": cleared}, None
                self._conn.execute("INSERT OR REPLACE INTO folder_prefs (path, no_cache, no_auto_load, set_at) "
                                   "VALUES (?, ?, ?, ?)", (path, int(no_cache), int(no_auto_load), set_at))
                removal = self.remove(("datasets",), [path], _stored_keys=True) if remove_cached and no_cache else None
                if removal is not None:
                    # store-v4: its raw and TXY layers whose sources were seen go too; an only copy stays, since
                    # nothing named it to the user (C2-9, Q22.6).
                    removal = self._with_layers_removed(removal, " WHERE path = ? AND gone_at IS NULL", (path,), [path])
                return {"no_cache": no_cache, "no_auto_load": no_auto_load, "set_at": set_at}, removal
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    def read_convert_prefs(self, paths: Sequence[str]) -> dict[str, Read[dict[str, Any]]]:
        """Each folder's converter flags (``write_beside``, ``set_at``); missing if none set. A
        folder Clear folder preferences cleared after its row was set reads as cleared."""
        unique = list(dict.fromkeys(paths))
        keys = list(dict.fromkeys(self._path_key(path) for path in unique))
        rows: dict[str, dict[str, Any]] = {}
        try:
            with self.transaction(write=False):
                if not _has_table(self._conn, "convert_prefs"):
                    keys = []  # (A read-only store from before it: none set.)
                for start in range(0, len(keys), 500):
                    chunk = keys[start:start + 500]
                    for path, write_beside, set_at in self._conn.execute(
                            f"SELECT path, write_beside, set_at FROM convert_prefs "
                            f"WHERE path IN ({','.join('?' * len(chunk))})", chunk):
                        rows[path] = {"write_beside": bool(write_beside), "set_at": float(set_at)}
        except (sqlite3.Error, StoreError) as exc:
            failure: Read[dict[str, Any]] = _error(f"Disk cache could not be read: {exc}")
            return {path: failure for path in unique}
        return {path: _found(rows[self._path_key(path)]) if self._path_key(path) in rows else _missing()
                for path in unique}

    def set_convert_prefs(self, path: str, write_beside: bool, set_at: float) -> dict[str, Any]:
        """Set a folder's converter flags unless a later choice is saved (as :meth:`set_prefs`);
        returns the flags now saved. A flag turned off keeps its row."""
        path = self._path_key(path)
        try:
            with self.transaction():
                row = self._conn.execute("SELECT write_beside, set_at FROM convert_prefs WHERE path = ?",
                                         (path,)).fetchone()
                cleared = float(self._meta().get("prefs_cleared_at", 0.0))
                if row is not None and float(row[1]) > set_at:
                    return {"write_beside": bool(row[0]), "set_at": float(row[1])}
                if cleared > set_at:
                    return {"write_beside": False, "set_at": cleared}
                self._conn.execute("INSERT OR REPLACE INTO convert_prefs (path, write_beside, set_at) VALUES (?, ?, ?)",
                                   (path, int(write_beside), set_at))
                return {"write_beside": write_beside, "set_at": set_at}
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    def clear_prefs(self, set_at: float | None = None) -> list[str]:
        """Turn every folder's flags off (the Cache tab's Folder preferences row), the converter's
        too, keeping each row's ``set_at`` as the time of this choice; the paths that had a flag."""
        now = time.time() if set_at is None else set_at
        try:
            with self.transaction():
                # A choice saved after this Clear (e.g. while it waited for the lock) stays.
                paths = [path for (path,) in self._conn.execute(
                    "SELECT path FROM folder_prefs WHERE (no_cache OR no_auto_load) AND set_at <= ?", (now,))]
                self._conn.execute("UPDATE folder_prefs SET no_cache = 0, no_auto_load = 0, set_at = ? "
                                   "WHERE set_at <= ?", (now, now))
                if _has_table(self._conn, "convert_prefs"):
                    paths += [path for (path,) in self._conn.execute(
                        "SELECT path FROM convert_prefs WHERE write_beside AND set_at <= ?", (now,))
                        if path not in paths]
                    self._conn.execute("UPDATE convert_prefs SET write_beside = 0, set_at = ? WHERE set_at <= ?",
                                       (now, now))
                if self.layout >= store_v4.LAYOUT:  # (Stage 2's per-folder choices: back to the global ones.)
                    paths += [path for (path,) in self._conn.execute(
                        "SELECT path FROM cache_policy WHERE policy != '' AND set_at <= ? UNION "
                        "SELECT path FROM txy_source_prefs WHERE source != '' AND set_at <= ?", (now, now))
                        if path not in paths]
                    self._conn.execute("UPDATE cache_policy SET policy = '', set_at = ? WHERE set_at <= ?", (now, now))
                    self._conn.execute("UPDATE txy_source_prefs SET source = '', tag = '', set_at = ? WHERE set_at <= ?",
                                       (now, now))
                # Also stops a choice made before the Clear for a folder with no row yet.
                self._conn.execute("INSERT INTO meta (key, value) VALUES ('prefs_cleared_at', ?) ON CONFLICT (key) "
                                   "DO UPDATE SET value = MAX(CAST(value AS REAL), CAST(excluded.value AS REAL))",
                                   (_dumps(now),))
                return [self._source_path(path) for path in paths]
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    # Folder constants (F0b): a folder's own values of the analyses' constants (fall distance, trap
    # frequencies…), set by the user. Like the flags, never removed to make room, by Clear all,
    # purges or a data root's Clear cached data; a nested root's re-key moves them.

    def read_constants(self, paths: Sequence[str], *, keyed_only: bool = False) -> dict[str, Read[dict[str, Any]]]:
        """Each folder's own constants, ``{"values": {key: number}, "set_at"}``; missing if never
        set. With ``keyed_only``, a path without a key here (above every data root, on an
        unsupported mount) is left out of the answer instead of raising."""
        keys: dict[str, str] = {}
        for path in dict.fromkeys(paths):
            try:
                keys[path] = self._path_key(path)
            except Exception:
                if not keyed_only:
                    raise
        stored = list(dict.fromkeys(keys.values()))
        rows: dict[str, dict[str, Any]] = {}
        if not self._constants_table:
            # A read-only store (written by a newer HeLab) without the table: none set here.
            return {path: _missing() for path in keys}
        try:
            with self.transaction(write=False):
                for start in range(0, len(stored), 500):
                    chunk = stored[start:start + 500]
                    for key, record, set_at in self._conn.execute(
                            f"SELECT path, record, set_at FROM folder_constants "
                            f"WHERE path IN ({','.join('?' * len(chunk))})", chunk):
                        rows[key] = {"values": _constant_values(json.loads(record)), "set_at": float(set_at)}
        except (sqlite3.Error, StoreError, ValueError) as exc:
            failure: Read[dict[str, Any]] = _error(f"Disk cache could not be read: {exc}")
            return {path: failure for path in keys}
        return {path: _found(rows[key]) if key in rows else _missing() for path, key in keys.items()}

    def set_constants(self, path: str, values: Mapping[str, Any], set_at: float) -> dict[str, Any]:
        """Set a folder's own constants (all of them: a key left out is restored), unless a later
        choice (``set_at``, e.g. in another HeLab) is saved; returns what is saved now. Restoring
        every value keeps the row (with its ``set_at``), so an older choice arriving late can't
        bring them back."""
        key = self._path_key(path)
        chosen = _constant_values(values)
        try:
            with self.transaction():
                row = self._conn.execute("SELECT record, set_at FROM folder_constants WHERE path = ?",
                                         (key,)).fetchone()
                if row is not None and float(row[1]) > set_at:
                    return {"values": _constant_values(json.loads(row[0])), "set_at": float(row[1])}
                self._conn.execute("INSERT OR REPLACE INTO folder_constants (path, record, set_at) VALUES (?, ?, ?)",
                                   (key, _dumps(chosen), set_at))
                return {"values": chosen, "set_at": set_at}
        except (sqlite3.Error, ValueError) as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    # Presets (roadmaps/presets-and-workspaces.md): the user's plot presets, one row each (``kind``
    # "script", ``scope`` its script and action; or "arrangement", ``scope`` ""), its JSON
    # ``record``, or NULL once deleted: the row stays, with its ``set_at``, so an older write from
    # another HeLab can't bring it back. Keyed by no folder: nothing removes them (not Clear all,
    # purges, making room, a data root's Clear cached data…, nor a re-key).

    def read_presets(self) -> Read[list[PresetRowFields]]:
        """Every preset row, deleted ones too: ``{"kind", "scope", "name", "record" (None if
        deleted), "set_at"}``. A read-only store (written by a newer HeLab) without the table has
        none."""
        if not self._presets_table:
            return _found([])
        try:
            with self.transaction(write=False):
                rows = self._conn.execute("SELECT kind, scope, name, record, set_at FROM presets").fetchall()
        except (sqlite3.Error, StoreError) as exc:
            return _error(f"Disk cache could not be read: {exc}")
        return _found([{"kind": str(kind), "scope": str(scope), "name": str(name),
                        "record": None if record is None else str(record), "set_at": float(set_at)}
                       for kind, scope, name, record, set_at in rows])

    def write_presets(self, rows: Sequence[Mapping[str, Any]]) -> list[PresetRowFields]:
        """Save these preset rows (a ``record`` of None deletes) in one transaction, each unless a
        later choice (``set_at``, e.g. in another HeLab) is saved for it; the rows saved now."""
        saved: list[PresetRowFields] = []
        try:
            with self.transaction():
                for row in rows:
                    key = (str(row["kind"]), str(row["scope"]), str(row["name"]))
                    if key[0] not in ("script", "arrangement") or not key[2]:
                        raise ValueError(f"not a preset: {key}")
                    record = None if row.get("record") is None else str(row["record"])
                    set_at = float(row["set_at"])
                    found = self._conn.execute("SELECT record, set_at FROM presets WHERE kind = ? AND scope = ? "
                                               "AND name = ?", key).fetchone()
                    if found is not None and float(found[1]) > set_at:
                        record, set_at = found[0], float(found[1])  # A later choice stays.
                    else:
                        self._conn.execute("INSERT OR REPLACE INTO presets (kind, scope, name, record, set_at) "
                                           "VALUES (?, ?, ?, ?, ?)", (*key, record, set_at))
                    saved.append({"kind": key[0], "scope": key[1], "name": key[2], "record": record,
                                  "set_at": set_at})
        except (sqlite3.Error, ValueError, KeyError, TypeError) as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return saved

    def _meta(self) -> dict[str, Any]:
        return {key: json.loads(value) for key, value in self._conn.execute("SELECT key, value FROM meta")}

    # Save guard

    def guard(self, paths: Sequence[str], kinds: Iterable[Kind]) -> SaveGuard:
        """The generations and folder epochs a job's later writes must still see."""
        kinds = tuple(kinds)
        paths = [self._path_key(path) for path in paths]
        try:
            with self.transaction(write=False):
                meta = self._meta()
                epochs = {key: self._epoch(key) for path in paths for key in self._epoch_keys(kinds, path)}
                epochs.update({root: self._epoch(root) for path in paths if (root := _root_epoch(path))})
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be read: {exc}") from exc
        return SaveGuard({kind: int(meta[f"gen_{kind}"]) for kind in kinds}, epochs)

    def start_dataset_job(self, path: str, kinds: Iterable[Kind] = ("datasets",)) -> SaveGuard:
        """A guard for a job that may save ``path``'s dataset, with its job sequence.

        Every such job takes the next ``job_seq`` when it starts; only a save from a
        later-started job can replace a dataset or supersede a pending save.
        """
        path = self._path_key(path)
        kinds = tuple(dict.fromkeys(("datasets", *kinds)))
        try:
            with self.transaction():
                self._conn.execute("INSERT INTO folder_epochs (path, job_seq) VALUES (?, 1) "
                                   "ON CONFLICT (path) DO UPDATE SET job_seq = job_seq + 1", (path,))
                epoch, job_seq = self._conn.execute(
                    "SELECT epoch, job_seq FROM folder_epochs WHERE path = ?", (path,)).fetchone()
                epochs = {path: int(epoch)}
                epochs.update({key: self._epoch(key) for key in self._epoch_keys(kinds, path)})
                if root := _root_epoch(path):
                    epochs[root] = self._epoch(root)
                meta = self._meta()
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return SaveGuard({kind: int(meta[f"gen_{kind}"]) for kind in kinds}, epochs, int(job_seq))

    def _epoch_keys(self, kinds: Iterable[Kind], path: str) -> list[str]:
        """The ``folder_epochs`` rows ``kinds`` of ``path`` use: the folder's own in store-v3, and per kind
        for records in store-v4 (cache-2: ``store_v4.epoch_key``)."""
        return list(dict.fromkeys(store_v4.epoch_key(self.layout, kind, path) for kind in kinds))

    def _epoch(self, path: str) -> int:
        row = self._conn.execute("SELECT epoch FROM folder_epochs WHERE path = ?", (path,)).fetchone()
        return int(row[0]) if row else 0

    def _guard_holds(self, guard: SaveGuard, kind: Kind, path: str) -> bool:
        epoch = store_v4.epoch_key(self.layout, kind, path)
        if kind not in guard.generations or epoch not in guard.epochs:
            # A delayed write may have re-resolved a local mount path to a
            # different SMB share, or a nested root re-keyed the folder since the
            # guard was taken. Never replace the original keyed guard with a fresh
            # one: that would let the old outcome write under the new key. Rejected
            # like a Clear, so a published file is retired at once (cache-5).
            raise SaveRejected("cleared", REKEYED)
        meta = self._meta()
        # A data root's Clear cached data bumps its root epoch: a guard taken before it (or one
        # without it) no longer holds for any folder below that root.
        root = _root_epoch(path)
        return (int(meta[f"gen_{kind}"]) == guard.generations[kind]
                and self._epoch(epoch) == guard.epochs[epoch]
                and (root is None or self._epoch(root) == guard.epochs.get(root, 0)))

    def _check(self, guard: SaveGuard, kind: Kind, path: str) -> None:
        if not self._guard_holds(guard, kind, path):
            raise SaveRejected("cleared", "Cache was cleared before saving completed")

    # Records

    def read_record(self, kind: Kind, path: str) -> Read[dict[str, Any]]:
        return self.read_records(kind, [path])[path]

    def read_records(self, kind: Kind, paths: Sequence[str]) -> dict[str, Read[dict[str, Any]]]:
        """Each path's record: found, missing, or (for that path, or all on a database error) error."""
        table = RECORD_TABLES[kind]
        unique = list(dict.fromkeys(paths))
        if kind == "listings" and not self._listings_table:
            return {path: _missing() for path in unique}  # (A read-only store from before listings.)
        keys = list(dict.fromkeys(self._path_key(path) for path in unique))
        rows: dict[str, str] = {}
        try:
            with self.transaction(write=False):
                for start in range(0, len(keys), 500):
                    chunk = keys[start:start + 500]
                    rows.update(self._conn.execute(
                        f"SELECT path, record FROM {table} WHERE path IN ({','.join('?' * len(chunk))})",
                        chunk).fetchall())
        except (sqlite3.Error, StoreError) as exc:
            failure = _error(f"Disk cache could not be read: {exc}")
            return {path: failure for path in unique}
        missing = [key for key in keys if key not in rows]
        legacy = self._kept_legacy() if missing else None
        unread: Read[dict[str, Any]] | None = None
        if legacy is not None:
            # Keep (Q22.3): what store-v4 has no row for and never removed (C2-1), store-v3 may have.
            try:
                with self.transaction(write=False):
                    missing = [key for key in missing if not self._legacy_hidden(kind, key)]
                    before, failures = self._legacy_purged(kind)
                rows.update(legacy.records(table, missing, before=before,
                                           failures_before=failures if kind == "histories" else before))
            except LegacyUnavailable as exc:
                unread = _error(f"Disk cache could not be read: {exc}")  # (Never "nothing saved".)
            except sqlite3.Error as exc:
                unread = _error(f"Disk cache could not be read: {exc}")
        result: dict[str, Read[dict[str, Any]]] = {}
        for path in unique:
            key = self._path_key(path)
            result[path] = (self._record_answer(kind, rows[key]) if key in rows
                            else unread if unread is not None else _missing())
        return result

    @staticmethod
    def _record_answer(kind: Kind, text: str) -> Read[dict[str, Any]]:
        try:
            value = json.loads(text)
        except ValueError as exc:
            return _error(f"Saved {kind} record is unreadable: {exc}")
        return _found(value) if isinstance(value, dict) else _error(f"Saved {kind} record is not an object")

    def save_record(self, kind: Kind, path: str, record: Mapping[str, Any] | None, guard: SaveGuard, *,
                    saved_at: float | None = None) -> None:
        """Save (or with None, delete) one record, if ``guard`` still holds."""
        self.save_records(kind, {path: record}, guard, saved_at=saved_at)

    def save_listing(self, path: str, record: Mapping[str, Any], guard: SaveGuard, *,
                     same: Callable[[Mapping[str, Any]], bool], refresh_seconds: float) -> bool:
        """Save a folder's listing (``io_ops.listings``) if ``guard`` holds and, in the same write
        transaction, the saved one is neither newer (``listed_at``) nor ``same`` and under
        ``refresh_seconds`` older: two helpers listing a folder at once never let the older
        observation replace the newer (Vernier, review round 1). Whether it was written."""
        listed_at = float(record["listed_at"])
        try:
            with self.transaction():
                key = self._path_key(path)
                self._check(guard, "listings", key)
                row = self._conn.execute("SELECT record FROM listings WHERE path = ?", (key,)).fetchone()
                try:
                    saved = json.loads(row[0]) if row is not None else None
                except ValueError:
                    saved = None  # Unreadable: replaced.
                if isinstance(saved, dict) and isinstance(saved.get("listed_at"), (int, float)):
                    if float(saved["listed_at"]) > listed_at or (
                            same(saved) and listed_at - float(saved["listed_at"]) < refresh_seconds):
                        return False
                self._conn.execute("INSERT OR REPLACE INTO listings (path, record, saved_at) VALUES (?, ?, ?)",
                                   (key, _dumps(record), listed_at))
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return True

    def save_records(self, kind: Kind, records: Mapping[str, Mapping[str, Any] | None], guard: SaveGuard, *,
                     saved_at: float | None = None) -> None:
        """Save a batch in one transaction: all of it, or (on a rejection or error) none."""
        table = RECORD_TABLES[kind]
        saved_at = time.time() if saved_at is None else saved_at
        try:
            with self.transaction():
                for source, record in records.items():
                    path = self._path_key(source)
                    self._check(guard, kind, path)
                    if record is None:
                        self._conn.execute(f"DELETE FROM {table} WHERE path = ?", (path,))
                        if self.layout >= store_v4.LAYOUT:  # (store-v3's row isn't read through after it: C2-1.)
                            self._conn.execute("INSERT INTO folder_epochs (path, epoch) VALUES (?, 1) ON CONFLICT "
                                               "(path) DO UPDATE SET epoch = epoch + 1",
                                               (f"{_LEGACY_HIDDEN}{kind}:{path}",))
                    elif kind == "summaries":
                        self._conn.execute(
                            "INSERT OR REPLACE INTO folder_summaries (path, record, identity, saved_at) "
                            "VALUES (?, ?, ?, ?)",
                            (path, _dumps(record), None, saved_at))
                    else:
                        self._conn.execute(f"INSERT OR REPLACE INTO {table} (path, record, saved_at) VALUES (?, ?, ?)",
                                           (path, _dumps(record), saved_at))
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    # Datasets

    def write_dataset_file(self, packed: bytes) -> str:
        """Publish a compressed dataset under its final name; no row names it yet.

        A killed writer leaves at most a ``tmp-`` or an unreferenced file, which the
        sweep deletes once it is over an hour old.
        """
        if self.read_only:
            raise StoreReadOnly("This disk cache was written by a newer HeLab and is read-only")
        name = uuid.uuid4().hex
        temporary = os.path.join(self.datasets_dir, f"tmp-{name}")
        final = f"{name}.blosc"
        try:
            with open(temporary, "wb") as handle:
                handle.write(packed)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, os.path.join(self.datasets_dir, final))
        except OSError as exc:
            with contextlib.suppress(OSError):
                os.remove(temporary)
            raise StoreError(f"Cached data file could not be written: {exc}") from exc
        _fsync_dir(self.datasets_dir)
        return final

    def _file_bytes(self, file: str) -> int:
        try:
            return os.path.getsize(os.path.join(self.datasets_dir, file))
        except OSError as exc:
            raise StoreError(f"Cached data file is unavailable: {exc}") from exc

    def _retire(self, file: str, now: float) -> None:
        self._conn.execute("INSERT OR IGNORE INTO retired_files (file, retired_at) VALUES (?, ?)", (file, now))

    def _stored_job_seq(self, path: str) -> int | None:
        row = self._conn.execute("SELECT job_seq FROM datasets WHERE path = ?", (path,)).fetchone()
        return int(row[0]) if row else None

    def _reject_file(self, file: str, rejection: SaveRejected) -> SaveRejected:
        """Retire a published file whose save was rejected, in its own transaction.

        Never one a row still names: a repeated save of the same file is rejected too.
        """
        with contextlib.suppress(sqlite3.Error, StoreError):
            with self.transaction():
                if self._conn.execute("SELECT 1 FROM datasets WHERE file = ? UNION ALL "
                                      "SELECT 1 FROM pending_saves WHERE file = ?", (file, file)).fetchone() is None:
                    self._retire(file, time.time())
        return rejection

    def save_dataset(self, path: str, file: str, record: DatasetRecord, guard: SaveGuard, *,
                     budget: int | None = None, budget_set_at: float | None = None) -> SaveResult:
        """Point ``path``'s dataset row at a file from :meth:`write_dataset_file`.

        The previous file, and those of older jobs' pending saves, are retired, never
        deleted here. A rejected save retires ``file`` and raises :class:`SaveRejected`.

        With a ``budget``, the same transaction checks the fit rule. A save that
        doesn't fit, or one that grows a cached folder's dataset while usage is at
        least ``APPROVAL_SHARE`` of the budget, becomes a pending save instead:
        nothing is removed to make room without the user's answer. With ``budget_set_at``
        (when the app set it), a budget the app set later wins (:meth:`_active_budget`).
        """
        path = self._path_key(path)
        now = time.time()
        size = self._file_bytes(file)
        try:
            with self.transaction():
                self._check(guard, "datasets", path)
                self._check_cacheable(path)
                stored = self._stored_job_seq(path)
                if stored is not None and stored >= guard.job_seq:
                    raise SaveRejected("newer", "Newer data is already cached")
                budget = self._active_budget(budget, budget_set_at)
                live, current = self._live(), self._dataset_bytes(path)
                # Decided after writing the row, so its records (e.g. a large fingerprint) count too;
                # a save that doesn't stand is rolled back to here.
                self._conn.execute("SAVEPOINT budget_check")
                self._upsert_dataset(path, file, size, record, guard.job_seq, now)
                superseded = self._retire_pending(" WHERE path = ? AND job_seq < ?", (path, guard.job_seq), now)
                usage, writes = self._live(), self._writes()
                reason: Literal["over_budget", "needs_approval"] | None = None
                if budget is not None and usage > budget:
                    reason = "over_budget"
                elif (budget is not None and current is not None and size > current
                      and live >= APPROVAL_SHARE * budget):
                    reason = "needs_approval"
                if reason is not None:
                    self._conn.execute("ROLLBACK TO budget_check")
                    self._conn.execute("RELEASE budget_check")
                    replaced = [old for (old,) in self._conn.execute(
                        "SELECT pending_id FROM pending_saves WHERE path = ?", (path,))]
                    pending_id = self._insert_pending(path, file, size, record, guard, reason, now)
                    return SaveResult(pending_id, reason, size + _record_bytes(record), live, self._writes(),
                                      budget, guard.job_seq, current or 0, tuple(replaced))
                self._conn.execute("RELEASE budget_check")
        except SaveRejected as rejection:
            raise self._reject_file(file, rejection) from None
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return SaveResult(bytes=size + _record_bytes(record), usage=usage, usage_seq=writes, budget=budget,
                          job_seq=guard.job_seq,
                          superseded=tuple(superseded))

    def _upsert_dataset(self, path: str, file: str, size: int, record: DatasetRecord, job_seq: int,
                        now: float) -> None:
        previous = self._conn.execute("SELECT file FROM datasets WHERE path = ?", (path,)).fetchone()
        info = {"format": DATASET_FORMAT, **record["info"]}
        self._conn.execute(
            "INSERT OR REPLACE INTO datasets (path, file, bytes, ram_bytes, rows, shots, fingerprint, problematic, "
            "info, last_used, job_seq, raw_times) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (path, file, size, int(record["ram_bytes"]), int(record["rows"]), int(record["shots"]),
             _dumps(record["fingerprint"]), _dumps(record["problematic"]), _dumps(info), now, job_seq,
             _dumps(record.get("raw_times", []))))
        if self.layout >= store_v4.LAYOUT:  # (Which session made it, Q28.4.)
            self._conn.execute("UPDATE datasets SET maker = ? WHERE path = ?", (self._maker_id(), path))
        if previous and previous[0] != file:
            self._retire(previous[0], now)

    def add_pending(self, path: str, file: str, record: DatasetRecord, guard: SaveGuard,
                    reason: Literal["over_budget", "needs_approval"]) -> str:
        """Keep a dataset waiting for the user's answer; returns its ``pending_id``.

        One per folder: a later job's pending save replaces an earlier one, and an
        earlier job's arriving later is discarded, like a save that is already
        older than the stored dataset.
        """
        path = self._path_key(path)
        now = time.time()
        size = self._file_bytes(file)
        try:
            with self.transaction():
                self._check(guard, "datasets", path)
                self._check_cacheable(path)
                stored = self._stored_job_seq(path)
                if stored is not None and stored >= guard.job_seq:
                    raise SaveRejected("newer", "Newer data is already cached")
                return self._insert_pending(path, file, size, record, guard, reason, now)
        except SaveRejected as rejection:
            raise self._reject_file(file, rejection) from None
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    def _insert_pending(self, path: str, file: str, size: int, record: DatasetRecord, guard: SaveGuard,
                        reason: Literal["over_budget", "needs_approval"], now: float) -> str:
        existing = self._conn.execute("SELECT file, job_seq FROM pending_saves WHERE path = ?", (path,)).fetchone()
        if existing and int(existing[1]) >= guard.job_seq:
            raise SaveRejected("newer", "Newer data is already waiting to be cached")
        if existing:
            self._retire_pending(" WHERE path = ?", (path,), now)
        pending_id = uuid.uuid4().hex
        self._conn.execute(
            "INSERT INTO pending_saves (pending_id, path, reason, file, bytes, record, gen_datasets, epoch, "
            "job_seq, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pending_id, path, reason, file, size, _dumps(record), guard.generations["datasets"],
             guard.epochs[path], guard.job_seq, now))
        return pending_id

    def adopt_pending(self, pending_id: str, *, budget: int | None = None, budget_set_at: float | None = None,
                      make_room: bool = False, expected_room: Sequence[str] | None = None) -> AdoptResult:
        """Make a pending save the folder's dataset or layers (Save update, or Make room).

        Raises :class:`SaveRejected` if it is gone, or (discarding it) if the folder
        was cleared or newer data was cached since its job started; nothing else is
        removed then. A waiting layer unit (store-v4, Q45.8) is checked part by part: a part
        whose job's guard no longer holds is dropped with its file, the rest still apply. With
        a ``budget`` the fit rule is checked against current usage: if it doesn't fit, the save
        stays pending as ``over_budget`` and the result says what Make room would remove. With
        ``make_room``, other folders' data is removed in Make room's order (``_free_space``) until
        it fits, in the same transaction. With ``expected_room`` (what the user was told it
        removes), Make room removes exactly that or nothing: if the plan changed (e.g. a new
        budget), it stays pending with the new plan.
        """
        now = time.time()
        rejection: SaveRejected | None = None
        result: AdoptResult | None = None
        try:
            with self.transaction():
                parts_column = "parts" if self._pending_parts else "'[]'"
                row = self._conn.execute(
                    f"SELECT path, file, bytes, record, gen_datasets, epoch, job_seq, {parts_column} FROM pending_saves "
                    "WHERE pending_id = ?", (pending_id,)).fetchone()
                if row is None:
                    raise SaveRejected("gone", "This save is no longer waiting")
                path, file, size, record, generation, epoch, job_seq, parts = row
                budget = self._active_budget(budget, budget_set_at)
                parts = json.loads(parts or "[]")
                if parts:
                    rejection = self._check_txy_pending(pending_id, str(path), parts, now)
                else:
                    stored = self._stored_job_seq(path)
                    if (int(self._meta()["gen_datasets"]) != generation or self._epoch(path) != epoch):
                        rejection = SaveRejected("cleared", "Cache was cleared before saving completed")
                    elif self._no_cache(path):
                        rejection = SaveRejected("no_cache", NOT_CACHED)
                    elif stored is not None and stored >= job_seq:
                        rejection = SaveRejected("newer", "Newer data is already cached")
                if rejection is not None:
                    self._retire_pending(" WHERE pending_id = ?", (pending_id,), now)
                else:
                    (size,) = self._conn.execute("SELECT bytes FROM pending_saves WHERE pending_id = ?",
                                                 (pending_id,)).fetchone()
                    needed = int(size) + len(record)
                    fits, removal = self._adopt_in_savepoint(pending_id, budget, make_room, keep=True,
                                                             expected=expected_room)
                    if fits:
                        result = AdoptResult(self._source_path(str(path)), True, needed, removal=removal)
                    else:
                        assert budget is not None  # Without a budget everything fits.
                        self._conn.execute("UPDATE pending_saves SET reason = 'over_budget' WHERE pending_id = ?",
                                           (pending_id,))
                        result = AdoptResult(self._source_path(str(path)), False, needed,
                                             room=self._room_plan(pending_id, budget))
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        if rejection is not None:
            raise rejection
        assert result is not None
        return result

    def _check_txy_pending(self, pending_id: str, key: str, parts: list[dict[str, Any]],
                           now: float) -> SaveRejected | None:
        """A waiting layer unit before it is adopted (inside a transaction): rejected whole for a folder now
        set to Don't cache; otherwise each part whose job's guard no longer holds (a Clear since) is dropped
        and its file retired, and the unit is rejected only when no part is left."""
        if self._no_cache(key):
            return SaveRejected("no_cache", NOT_CACHED)
        try:
            standing = [part for part in parts if self._txy_guard_holds(part["guard"], key)]
        except SaveRejected as rekeyed:
            return rekeyed
        if not standing:
            return SaveRejected("cleared", "Cached TXY data was cleared before saving completed")
        if len(standing) < len(parts):
            for part in parts:
                if part not in standing:
                    self._retire(str(part["file"]), now)
            self._conn.execute("UPDATE pending_saves SET parts = ?, file = ?, bytes = ? WHERE pending_id = ?",
                               (_dumps(standing), str(standing[0]["file"]),
                                sum(int(part["bytes"]) for part in standing), pending_id))
        return None

    def _adopt_in_savepoint(self, pending_id: str, budget: int | None, make_room: bool, *,
                            keep: bool, expected: Sequence[str] | None = None) -> tuple[bool, Removal | None]:
        """Adopt a pending save inside a savepoint, with Make room if asked, and measure.

        The decision is made on the real result, records included. It is kept only if
        ``keep`` and it fits; otherwise everything is rolled back. Returns whether it
        fits and what Make room removed (or would remove).
        """
        parts_column = "parts" if self._pending_parts else "'[]'"
        path, file, size, record, job_seq, parts = self._conn.execute(
            f"SELECT path, file, bytes, record, job_seq, {parts_column} FROM pending_saves WHERE pending_id = ?",
            (pending_id,)).fetchone()
        self._conn.execute("SAVEPOINT adopt_fit")
        try:
            now = time.time()
            waiting = json.loads(parts or "[]")
            if waiting:
                unit = json.loads(record)
                for part in waiting:  # (Each part under its own job's sequence: Q45.8.)
                    self._apply_txy_unit(str(path), str(unit.get("source", "")), str(unit.get("tag", "")),
                                         [TxyPart.from_json(part)], {str(part["file"]): int(part["bytes"])}, None,
                                         int(part["job_seq"]), now, part.get("seen_at"))
                if unit.get("view") is not None:
                    self._apply_txy_unit(str(path), str(unit.get("source", "")), str(unit.get("tag", "")), [], {},
                                         unit["view"], int(unit.get("view_job_seq", job_seq)), now)
            else:
                self._upsert_dataset(path, file, int(size), json.loads(record), int(job_seq), now)
            self._conn.execute("DELETE FROM pending_saves WHERE pending_id = ?", (pending_id,))
            removed = self._free_space(budget, str(path)) if budget is not None and make_room else []
            fits = budget is None or self._live() <= budget
            removal = _combined_removal(removed)
            planned = set(() if removal is None else _removal_items(removal))
            if expected is not None and make_room and planned != set(expected):
                fits = False  # Not what the user agreed to remove: nothing is.
        except BaseException:
            self._conn.execute("ROLLBACK TO adopt_fit")
            self._conn.execute("RELEASE adopt_fit")
            raise
        if not (keep and fits):
            self._conn.execute("ROLLBACK TO adopt_fit")
        self._conn.execute("RELEASE adopt_fit")
        return fits, removal

    def _room_plan(self, pending_id: str, budget: int) -> RoomPlan:
        """Make room, tried and rolled back: exactly what it would remove."""
        fits, removal = self._adopt_in_savepoint(pending_id, budget, True, keep=False)
        paths = () if removal is None or not fits else tuple(removal.paths or ())
        # A literal path saved while a share was unmounted can later resemble a
        # mounted path. Match stored rows through the display mapping, never re-key it.
        used = [] if not paths else [float(last_used) for key, last_used in self._conn.execute(
            "SELECT path, last_used FROM datasets") if self._source_path(str(key)) in paths]
        if removal is None or not fits:
            return RoomPlan(paths, 0, min(used, default=None), max(used, default=None), fits)
        return RoomPlan(paths, removal.dataset_bytes, min(used, default=None), max(used, default=None), fits,
                        removal.raw_paths, removal.only_copy_paths, removal.raw_bytes, removal.txy_layers,
                        removal.txy_seen, removal.txy_only, removal.txy_bytes)

    def room_plan(self, pending_id: str, budget: int) -> RoomPlan:
        """What Make room would remove for a pending save: least recently used other
        folders' datasets, never its own. ``possible`` is False if even removing all of
        them isn't enough. Tried in the store and rolled back, so it is exact."""
        try:
            with self.transaction():
                if self._conn.execute("SELECT 1 FROM pending_saves WHERE pending_id = ?",
                                      (pending_id,)).fetchone() is None:
                    raise SaveRejected("gone", "This save is no longer waiting")
                return self._room_plan(pending_id, budget)
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be read: {exc}") from exc

    def discard_pending(self, pending_id: str) -> bool:
        """Drop a pending save and retire its file; False if it was already gone."""
        try:
            with self.transaction():
                if not self._retire_pending(" WHERE pending_id = ?", (pending_id,), time.time()):
                    return False
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return True

    def _view_infos(self, keys: Sequence[str], wanted: tuple[str, str] | None,
                    damaged: dict[str, str]) -> dict[str, tuple[int, int, str, float, int]]:
        """store-v4 (inside a transaction): each folder's view as ``read_dataset_infos`` reads a dataset (bytes,
        RAM bytes, info, last used, its TXY files' bytes): the ``wanted`` view, else the most recently used. A
        folder whose view can't be read goes into ``damaged`` (key → why), never failing the others (SV-1)."""
        marks = ",".join("?" * len(keys))
        chosen: dict[str, tuple[str, str, str, float]] = {}
        for path, source, tag, fingerprint, info, last_used in self._conn.execute(
                f"SELECT path, source, tag, fingerprint, info, last_used FROM txy_views WHERE path IN ({marks}) "
                "ORDER BY last_used", tuple(keys)):
            key = str(path)
            if key in chosen and wanted is not None and chosen[key][0] == "wanted":
                continue
            chosen[key] = ("wanted" if wanted is not None and (source, tag) == wanted else "", str(fingerprint),
                           str(info), float(last_used))
        layers: dict[tuple[str, str], tuple[int, int, int]] = {
            (str(path), str(layer)): (int(size), int(count), int(rows_)) for path, layer, size, count, rows_ in
            self._conn.execute(f"SELECT path, layer, bytes, shots, rows FROM txy_layers WHERE path IN ({marks})",
                               tuple(keys))}
        found: dict[str, tuple[int, int, str, float, int]] = {}
        for key, (_, fingerprint, info, last_used) in chosen.items():
            try:
                entries = json.loads(fingerprint)
                named: dict[str, int] = {}
                for entry in entries:
                    named[str(entry[4])] = named.get(str(entry[4]), 0) + 1
                source_bytes = sum(int(entry[1]) for entry in entries)
            except (ValueError, IndexError, TypeError, KeyError) as exc:
                damaged[key] = f"{type(exc).__name__}: {exc}"
                continue
            size = sum(layers[(key, layer)][0] for layer in named if (key, layer) in layers)
            # (A layer's rows by the share of its shots the view names: listings read no entries.)
            rows = sum(layers[(key, layer)][2] * count // max(1, layers[(key, layer)][1])
                       for layer, count in named.items() if (key, layer) in layers)
            found[key] = (size, rows * TXY_ROW_BYTES, info, last_used, source_bytes)
        return found

    def cached_matlab_shots(self, path: str) -> Read[set[int]]:
        """The shots cached from the folder's MATLAB TXY, for a scan's mismatch rule (TXY files are written once):
        its dataset's (store-v3), or its most recently used view's MATLAB layer shots (store-v4); missing when
        nothing is cached."""
        if self.layout < store_v4.LAYOUT:
            row = self.read_dataset_row(path)
            if row.value is None:
                return _error(row.error) if row.failed else _missing()
            return _found({int(entry[0]) for entry in row.value["fingerprint"] if isinstance(entry, (list, tuple))
                           and entry})
        views = sorted(self.folder_views(path), key=lambda view: view[2])
        if not views:
            return _missing()
        view = self.read_view(path, views[-1][0], views[-1][1])
        if view.value is None:
            return _error(view.error) if view.failed else _missing()
        return _found({int(entry[0]) for entry in view.value.fingerprint if str(entry[4]) == _MATLAB_LAYER})

    def read_dataset_row(self, path: str) -> Read[DatasetRow]:
        """The dataset's record without its data, e.g. for the one-stat check."""
        key = self._path_key(path)
        try:
            with self.transaction(write=False):
                row = self._conn.execute(
                    "SELECT path, file, bytes, ram_bytes, rows, shots, fingerprint, problematic, info, last_used, "
                    f"job_seq, {self._raw_times} FROM datasets WHERE path = ?", (key,)).fetchone()
        except (sqlite3.Error, StoreError) as exc:
            return _error(f"Disk cache could not be read: {exc}")
        if row is None:
            return _missing()
        try:
            return _found(cast(DatasetRow, {
                "path": self._source_path(str(row[0])), "file": row[1], "bytes": row[2],
                "ram_bytes": row[3], "rows": row[4],
                "shots": row[5], "fingerprint": json.loads(row[6]), "problematic": json.loads(row[7]),
                "info": json.loads(row[8]), "last_used": row[9], "job_seq": row[10],
                "raw_times": json.loads(row[11])}))
        except ValueError as exc:
            return _error(f"Saved dataset record is unreadable: {exc}")

    def read_dataset_infos(self, paths: Sequence[str],
                           wanted: tuple[str, str] | None = None) -> dict[str, Read[DatasetInfo]]:
        """Each folder's dataset sizes and ``info``, without its fingerprint: for listings. In store-v4 a folder's
        cached data is its views and TXY layers: found when it has a view (that of ``wanted``, a (source, tag)
        view key, when it has one, else its most recently used), with that view's info and the bytes of the
        layers it names; a folder with only stage 1's dataset (a seed) answers from that."""
        unique = list(dict.fromkeys(paths))
        keys = list(dict.fromkeys(self._path_key(path) for path in unique))
        rows: dict[str, tuple[int, int, str, float, int]] = {}
        damaged: dict[str, str] = {}  # (store-v4: a folder whose view can't be read; the others list on, SV-1.)
        try:
            with self.transaction(write=False):
                for start in range(0, len(keys), 500):
                    chunk = keys[start:start + 500]
                    for path, size, ram_bytes, info, last_used, source in self._conn.execute(
                            f"SELECT path, bytes, ram_bytes, info, last_used, (SELECT COALESCE(SUM("
                            f"json_extract(f.value, '$[1]')), 0) FROM json_each(fingerprint) f) FROM datasets "
                            f"WHERE path IN ({','.join('?' * len(chunk))})", chunk):
                        rows[path] = (size, ram_bytes, info, last_used, source)
                    if self.layout >= store_v4.LAYOUT:
                        rows.update(self._view_infos(chunk, wanted, damaged))
        except (sqlite3.Error, StoreError) as exc:
            failure = _error(f"Disk cache could not be read: {exc}")
            return {path: failure for path in unique}
        result: dict[str, Read[DatasetInfo]] = {}
        for path in unique:
            key = self._path_key(path)
            if key in damaged:
                result[path] = _error(f"Saved view record is unreadable: {damaged[key]}")
                continue
            if key not in rows:
                result[path] = _missing()
                continue
            size, ram_bytes, info, last_used, source = rows[key]
            try:
                result[path] = _found(DatasetInfo(bytes=int(size), ram_bytes=int(ram_bytes), info=json.loads(info),
                                                  last_used=float(last_used), source_bytes=int(source or 0)))
            except ValueError as exc:
                result[path] = _error(f"Saved dataset record is unreadable: {exc}")
        return result

    def _read_file(self, file: str) -> bytes:
        with open(self._store_file(file), "rb") as handle:
            return handle.read()

    def read_dataset(self, path: str) -> Read[tuple[DatasetRow, bytes]]:
        """The dataset's record and its compressed file.

        A writer may replace the file just after the row was read. A missing file
        is answered by re-reading the row once: another file is opened, no row is
        "missing", and the same row is an error. The re-read needs a fresh snapshot,
        so this never runs inside a transaction.
        """
        if self._depth:
            raise RuntimeError("read_dataset can't run inside a transaction")
        found = self.read_dataset_row(path)
        if not found.found or found.value is None:
            return cast(Read[tuple[DatasetRow, bytes]], found)
        row = found.value
        try:
            return _found((row, self._read_file(row["file"])))
        except FileNotFoundError:
            pass
        except OSError as exc:
            return _error(f"Cached data file could not be read: {exc}")
        again = self.read_dataset_row(path)
        if not again.found or again.value is None:
            return cast(Read[tuple[DatasetRow, bytes]], again)
        if again.value["file"] == row["file"]:
            return _error("Cached data file is missing")
        try:
            return _found((again.value, self._read_file(again.value["file"])))
        except OSError as exc:
            return _error(f"Cached data file could not be read: {exc}")

    def legacy_dataset(self, path: str, *, with_file: bool = True) -> Read[tuple[DatasetRow, bytes]]:
        """store-v3's dataset of ``path`` under Keep (store-v4, Q45.5): its row and file, read only through
        ``LegacyStore``, for a load to copy its shots into the layers. Missing in store-v3, after Ignore or
        Clear, with no store-v3, or when store-v4 removed the folder's datasets since it was made
        (``_legacy_hidden``: never read through again). ``with_file`` False: the row alone (its file b"")."""
        if self.layout < store_v4.LAYOUT:
            return _missing()
        key = self._path_key(path)
        try:
            with self.transaction(write=False):
                hidden = self._legacy_hidden("datasets", key)
        except (sqlite3.Error, StoreError) as exc:
            return _error(f"Disk cache could not be read: {exc}")
        legacy = None if hidden else self._kept_legacy()
        if legacy is None:
            return _missing()
        try:
            row = legacy.dataset_row(key)
            if row is None:
                return _missing()
            record = cast(DatasetRow, {
                **row, "path": self._source_path(key), "fingerprint": json.loads(row["fingerprint"]),
                "problematic": json.loads(row["problematic"]), "info": json.loads(row["info"]),
                "raw_times": json.loads(row.get("raw_times") or "[]")})
            return _found((record, legacy.read_file(str(row["file"])) if with_file else b""))
        except (LegacyUnavailable, OSError, ValueError) as exc:
            return _error(f"store-v3's cached data could not be read: {exc}")

    def confirm_dataset(self, path: str, fingerprint: Sequence[Sequence[int]], names: Sequence[str],
                        snapshot_at: float, guard: SaveGuard,
                        raw_times: Sequence[Sequence[int]] | None = None,
                        folder_mtime_ns: int | None = None) -> bool:
        """Record that a full listing at ``snapshot_at`` found a cached dataset's TXY files all
        unchanged (none still being written), without rewriting it: its file list now dates from
        then (``snapshot_at``, so a later non-TXY change such as Finder's ``.DS_Store`` no longer
        rules out the quick check), nothing is unsettled, and its file names (for the quick check's
        samples; older caches have none) are kept, and so are ``raw_times`` when given (shot times
        the row lacked, which the listing found). The folder's mtime before that listing
        (``folder_mtime_ns``, for the quick check; None: too close to it) replaces the saved one,
        unless the row's file list is newer than this listing. Only while the row still has
        ``fingerprint``, under the job's save guard. Returns whether it was recorded."""
        path = self._path_key(path)
        try:
            with self.transaction():
                self._check(guard, "datasets", path)
                row = self._conn.execute("SELECT fingerprint, info FROM datasets WHERE path = ?", (path,)).fetchone()
                if row is None or json.loads(row[0]) != [list(entry) for entry in fingerprint]:
                    return False
                info = json.loads(row[1])
                if not isinstance(info, dict):
                    return False
                previous = info.get("snapshot_at")
                mtime = {"folder_mtime_ns": folder_mtime_ns}
                if isinstance(previous, (int, float)) and math.isfinite(previous) and previous > snapshot_at:
                    snapshot_at, mtime = float(previous), {}  # (Its mtime goes with its own listing.)
                self._conn.execute("UPDATE datasets SET info = ? WHERE path = ?", (_dumps(
                    {**info, "names": list(names), "snapshot_at": snapshot_at, "unsettled": 0, **mtime}), path))
                if raw_times is not None:
                    self._conn.execute("UPDATE datasets SET raw_times = ? WHERE path = ?",
                                       (_dumps([list(entry) for entry in raw_times]), path))
                return True
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    def touch_dataset(self, path: str, now: float | None = None) -> None:
        """Record that the dataset was used: shown from the cache, reused or confirmed."""
        path = self._path_key(path)
        try:
            with self.transaction():
                self._conn.execute("UPDATE datasets SET last_used = ? WHERE path = ?",
                                   (time.time() if now is None else now, path))
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    # Results (result caching R2): saved analysis results, reused on an exact key match.

    def _store_file(self, file: str) -> str:
        """A file the store names: a dataset file, or a result file (``results/<name>``)."""
        if file.startswith(RESULTS_DIRNAME + "/"):
            return os.path.join(self.results_dir, file[len(RESULTS_DIRNAME) + 1:])
        if file.startswith(store_v4.RAW_DIRNAME + "/"):
            return os.path.join(self.raw_dir, file[len(store_v4.RAW_DIRNAME) + 1:])
        if file.startswith(store_v4.TXY_DIRNAME + "/"):
            return os.path.join(self.txy_dir, file[len(store_v4.TXY_DIRNAME) + 1:])
        return os.path.join(self.datasets_dir, file)

    def start_result_job(self, path: str) -> SaveGuard:
        """A guard for a job that may save a result of ``path``: the results' generation (Clear
        cached analysis of every result), the folder's results epoch and its root's (a root's Clear
        cached analysis). Never the dataset kinds' or ``root-clear://``: clearing cached data leaves
        results; nor Make room's eviction, which removes old saved results only: a newer copy of one,
        saving or waiting, is checked against the budget in its own transaction like any save."""
        key = self._path_key(path)
        if not self._results_table:
            raise StoreReadOnly("This disk cache was written by a newer HeLab and is read-only")
        try:
            with self.transaction(write=False):
                epochs = {_results_epoch(key): self._epoch(_results_epoch(key))}
                if root := _results_root_epoch(key):
                    epochs[root] = self._epoch(root)
                generation = int(self._meta()["gen_results"])
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be read: {exc}") from exc
        return SaveGuard({"results": generation}, epochs)

    def _check_result_guard(self, guard: SaveGuard, key: str) -> None:
        folder, root = _results_epoch(key), _results_root_epoch(key)
        if "results" not in guard.generations or folder not in guard.epochs:
            raise SaveRejected("cleared", REKEYED)  # (As ``_guard_holds``.)
        if (int(self._meta()["gen_results"]) != guard.generations["results"]
                or self._epoch(folder) != guard.epochs[folder]
                or (root is not None and self._epoch(root) != guard.epochs.get(root, 0))):
            raise SaveRejected("cleared", "Cached analysis was cleared before saving completed")

    def write_result_file(self, packed: bytes) -> str:
        """Publish a result's data file under its final name (``results/<name>``); no row names it
        yet (a killed writer's file is an orphan the sweep deletes after an hour)."""
        if self.read_only:
            raise StoreReadOnly("This disk cache was written by a newer HeLab and is read-only")
        name = uuid.uuid4().hex
        temporary = os.path.join(self.results_dir, f"tmp-{name}")
        final = f"{name}.npz"
        try:
            os.makedirs(self.results_dir, exist_ok=True)
            with open(temporary, "wb") as handle:
                handle.write(packed)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, os.path.join(self.results_dir, final))
        except OSError as exc:
            with contextlib.suppress(OSError):
                os.remove(temporary)
            raise StoreError(f"Cached result file could not be written: {exc}") from exc
        _fsync_dir(self.results_dir)
        return f"{RESULTS_DIRNAME}/{final}"

    def save_result(self, path: str, lookup: str, family: str, record: Mapping[str, Any], file: str,
                    guard: SaveGuard, *, analysis_id: str, action: str, computed_at: float,
                    budget: int | None = None, budget_set_at: float | None = None, label: str = "",
                    hold: bool = True, only_new: bool = False) -> ResultSave:
        """Point the row of ``path``'s result ``lookup`` at a file from :meth:`write_result_file`,
        replacing (retiring) one saved before under the same key, if ``guard`` still holds and the
        folder may be cached (``no_cache``). Within the one disk budget, measured in the same
        transaction with the row written: a save that doesn't fit isn't made (``saved`` False,
        nothing removed to make room); with ``hold`` it waits in ``pending_results`` for the user's
        answer (``pending_id``; ``label``: the plot's name, for the question), else its file is
        retired. ``only_new``: saved only if no result of that key is saved now (a copy of store-v3's on use,
        A42.1, never over a newer one: ``reason`` "exists", its file retired). A rejected save raises
        :class:`SaveRejected` and retires ``file`` too."""
        key = self._path_key(path)
        now = time.time()
        size = self._size(file)
        text = _dumps(record)
        try:
            with self.transaction():
                self._check_result_guard(guard, key)
                self._check_cacheable(key)
                if only_new and self._conn.execute("SELECT 1 FROM results WHERE path = ? AND lookup = ?",
                                                   (key, lookup)).fetchone() is not None:
                    self._retire(file, now)
                    return ResultSave(False, "exists", size, self._live(), self._writes(), budget)
                budget = self._active_budget(budget, budget_set_at)
                self._conn.execute("SAVEPOINT result_fit")
                previous, result_id = self._upsert_result(key, lookup, family, analysis_id, action, text, file, size,
                                               computed_at, now)
                usage, writes = self._live(), self._writes()
                if budget is not None and usage > budget:
                    self._conn.execute("ROLLBACK TO result_fit")
                    self._conn.execute("RELEASE result_fit")
                    pending_id = ""
                    if hold and self._pending_results:
                        pending_id = self._insert_pending_result(key, lookup, family, analysis_id, action, label,
                                                                 text, file, size, computed_at, guard, now)
                    else:
                        self._retire(file, now)
                    return ResultSave(False, "over_budget", size, self._live(), writes, budget, pending_id)
                self._conn.execute("RELEASE result_fit")
                if previous is not None and previous != file:
                    self._retire(previous, now)
                self._drop_pending_result(key, lookup, now)  # (Saved after all: no question about it.)
                folder = self._folder_results([key])[key]
        except SaveRejected as rejection:
            raise self._reject_result_file(file, rejection) from None
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return ResultSave(True, "", size + len(text), usage, writes, budget, result_id=result_id, folder=folder)

    def _upsert_result(self, key: str, lookup: str, family: str, analysis_id: str, action: str, record: str,
                       file: str, size: int, computed_at: float, now: float) -> tuple[str | None, str]:
        """Write a result's row under a new ``result_id`` (a replacement's too, so Make room's plan,
        which names ids, never removes a copy saved after it was made); the file of the one it
        replaces (the caller retires it), if any, and the new id."""
        previous = self._conn.execute("SELECT file FROM results WHERE path = ? AND lookup = ?",
                                      (key, lookup)).fetchone()
        result_id = uuid.uuid4().hex
        self._conn.execute(
            "INSERT INTO results (result_id, path, lookup, family, analysis_id, action, record, file, bytes, "
            "computed_at, saved_at, last_used) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (path, lookup) DO UPDATE SET result_id = excluded.result_id, family = excluded.family, "
            "record = excluded.record, file = excluded.file, bytes = excluded.bytes, "
            "computed_at = excluded.computed_at, saved_at = excluded.saved_at, last_used = excluded.last_used",
            (result_id, key, lookup, family, analysis_id, action, record, file, size, computed_at, now, now))
        if self.layout >= store_v4.LAYOUT:  # (Which session made it, Q28.4.)
            self._conn.execute("UPDATE results SET maker = ? WHERE result_id = ?", (self._maker_id(), result_id))
        return None if previous is None else str(previous[0]), result_id

    def _insert_pending_result(self, key: str, lookup: str, family: str, analysis_id: str, action: str, label: str,
                               record: str, file: str, size: int, computed_at: float, guard: SaveGuard,
                               now: float) -> str:
        """Hold a result for the user's answer, replacing (retiring) one held under the same key."""
        self._drop_pending_result(key, lookup, now)
        pending_id = uuid.uuid4().hex
        self._conn.execute(
            "INSERT INTO pending_results (pending_id, path, lookup, family, analysis_id, action, label, record, file, "
            "bytes, computed_at, guard, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pending_id, key, lookup, family, analysis_id, action, label, record, file, size, computed_at,
             _dumps({"generations": dict(guard.generations), "epochs": dict(guard.epochs)}), now))
        return pending_id

    def _drop_pending_result(self, key: str, lookup: str, now: float) -> None:
        if not self._pending_results:
            return
        for (file,) in self._conn.execute("SELECT file FROM pending_results WHERE path = ? AND lookup = ?",
                                          (key, lookup)).fetchall():
            self._retire(str(file), now)
        self._conn.execute("DELETE FROM pending_results WHERE path = ? AND lookup = ?", (key, lookup))

    def adopt_pending_result(self, pending_id: str, *, budget: int | None = None, budget_set_at: float | None = None,
                             make_room: bool = False, expected_room: Sequence[str] | None = None) -> ResultAdopt:
        """Save a waiting result (Make room): with ``make_room``, least recently shown **other saved
        results** are removed until it fits, in the same transaction (never cached datasets: Clear
        cached data is the user's own; never a waiting result, nor a save running); with
        ``expected_room`` (the result ids the user was told) exactly those or nothing. Raises :class:`SaveRejected` (discarding it) if it is gone, its
        run's guard no longer holds (a Clear cached analysis since) or the folder isn't to be cached.
        Not fitting, it keeps waiting and the answer says what Make room would remove."""
        now = time.time()
        rejection: SaveRejected | None = None
        result: ResultAdopt | None = None
        try:
            with self.transaction():
                row = self._conn.execute(
                    "SELECT path, file, bytes, guard FROM pending_results WHERE pending_id = ?",
                    (pending_id,)).fetchone() if self._pending_results else None
                if row is None:
                    raise SaveRejected("gone", "This save is no longer waiting")
                path, file, size, guard_text = str(row[0]), str(row[1]), int(row[2]), json.loads(row[3])
                guard = SaveGuard(dict(guard_text["generations"]), dict(guard_text["epochs"]))
                budget = self._active_budget(budget, budget_set_at)
                try:
                    self._check_result_guard(guard, path)
                    self._check_cacheable(path)
                except SaveRejected as rejected:  # (Its guard may name the folder's old key: ``REKEYED``.)
                    rejection = rejected
                if rejection is not None:
                    self._retire(file, now)
                    self._conn.execute("DELETE FROM pending_results WHERE pending_id = ?", (pending_id,))
                else:
                    fits, removed, result_id = self._adopt_result_savepoint(pending_id, budget, make_room, keep=True,
                                                                            expected=expected_room)
                    if fits:
                        touched = list(dict.fromkeys([path, *(item[1] for item in removed)]))
                        folders = {self._source_path(key): count
                                   for key, count in self._folder_results(touched).items()}
                        removal = None if not removed else ResultRemoval(
                            tuple(sorted({self._source_path(item[1]) for item in removed})), len(removed),
                            sum(item[2] for item in removed),
                            evicted=tuple((self._source_path(item[1]), item[4], item[0]) for item in removed))
                        result = ResultAdopt(True, self._source_path(path), size, removal=removal,
                                             result_id=result_id, folders=folders)
                    else:
                        assert budget is not None
                        result = ResultAdopt(False, self._source_path(path), size,
                                             room=self._result_room(pending_id, budget))
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        if rejection is not None:
            raise rejection
        assert result is not None
        return result

    def _adopt_result_savepoint(self, pending_id: str, budget: int | None, make_room: bool, *, keep: bool,
                                expected: Sequence[str] | None = None
                                ) -> tuple[bool, list[tuple[str, str, int, float, str]], str]:
        """Adopt a waiting result inside a savepoint, with Make room if asked; kept only if ``keep``
        and it fits. Whether it fits, the results Make room removed (or would): (result_id, path,
        bytes, last_used, lookup), and the adopted row's id."""
        row = self._conn.execute(
            "SELECT path, lookup, family, analysis_id, action, record, file, bytes, computed_at FROM pending_results "
            "WHERE pending_id = ?", (pending_id,)).fetchone()
        path, lookup = str(row[0]), str(row[1])
        now = time.time()
        self._conn.execute("SAVEPOINT adopt_result")
        removed: list[tuple[str, str, int, float, str]] = []
        try:
            previous, result_id = self._upsert_result(path, lookup, str(row[2]), str(row[3]), str(row[4]),
                                                      str(row[5]), str(row[6]), int(row[7]), float(row[8]), now)
            self._conn.execute("DELETE FROM pending_results WHERE pending_id = ?", (pending_id,))
            if previous is not None and previous != row[6]:
                self._retire(previous, now)
            if budget is not None and make_room:
                others = self._conn.execute(
                    "SELECT result_id, path, bytes, last_used, file, lookup FROM results "
                    "WHERE NOT (path = ? AND lookup = ?) ORDER BY last_used, result_id", (path, lookup)).fetchall()
                for other_id, other, size, last_used, file, key in others:
                    if self._live() <= budget:
                        break
                    # Only these saved rows go, by the user's answer, oldest shown first. No epoch moves
                    # (that is for clears): a newer copy of one, waiting or being saved, keeps its guard
                    # and is checked against the budget in its own transaction like any save.
                    self._retire(str(file), now)
                    self._conn.execute("DELETE FROM results WHERE result_id = ?", (other_id,))
                    removed.append((str(other_id), str(other), int(size), float(last_used), str(key)))
            fits = budget is None or self._live() <= budget
            if expected is not None and make_room and {item[0] for item in removed} != set(expected):
                fits = False  # Not what the user agreed to remove: nothing is.
        except BaseException:
            self._conn.execute("ROLLBACK TO adopt_result")
            self._conn.execute("RELEASE adopt_result")
            raise
        if not (keep and fits):
            self._conn.execute("ROLLBACK TO adopt_result")
        self._conn.execute("RELEASE adopt_result")
        return fits, removed, result_id

    def _result_room(self, pending_id: str, budget: int) -> ResultRoom:
        fits, removed, _ = self._adopt_result_savepoint(pending_id, budget, True, keep=False)
        return ResultRoom(tuple(item[0] for item in removed) if fits else (),
                          sum(item[2] for item in removed) if fits else 0,
                          max((item[3] for item in removed), default=None) if fits else None, fits)

    def result_room_plan(self, pending_id: str, budget: int) -> ResultRoom:
        """What Make room would remove for a waiting result, tried in the store and rolled back."""
        try:
            with self.transaction():
                if not self._pending_results or self._conn.execute(
                        "SELECT 1 FROM pending_results WHERE pending_id = ?", (pending_id,)).fetchone() is None:
                    raise SaveRejected("gone", "This save is no longer waiting")
                return self._result_room(pending_id, budget)
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be read: {exc}") from exc

    def discard_pending_result(self, pending_id: str) -> bool:
        """Discard a waiting result (its file retired); False if it was already gone."""
        if not self._pending_results:
            return False
        try:
            with self.transaction():
                row = self._conn.execute("SELECT file FROM pending_results WHERE pending_id = ?",
                                         (pending_id,)).fetchone()
                if row is None:
                    return False
                self._retire(str(row[0]), time.time())
                self._conn.execute("DELETE FROM pending_results WHERE pending_id = ?", (pending_id,))
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return True

    def pending_result_rows(self) -> list[dict[str, Any]]:
        """Results waiting for an answer, oldest first, for the inventory (inside a transaction)."""
        if not self._pending_results:
            return []
        return [{"pending_id": str(pending_id), "path": self._source_path(str(path)), "label": str(label),
                 "analysis_id": str(analysis_id), "bytes": int(size), "created_at": float(created_at),
                 "reason": "over_budget", "result": True}
                for pending_id, path, label, analysis_id, size, created_at in self._conn.execute(
                    "SELECT pending_id, path, label, analysis_id, bytes, created_at FROM pending_results "
                    "ORDER BY created_at")]

    def _size(self, file: str) -> int:
        try:
            return os.path.getsize(self._store_file(file))
        except OSError as exc:
            raise StoreError(f"Cached file is unavailable: {exc}") from exc

    def _reject_result_file(self, file: str, rejection: SaveRejected) -> SaveRejected:
        with contextlib.suppress(sqlite3.Error, StoreError):
            with self.transaction():
                if self._conn.execute("SELECT 1 FROM results WHERE file = ?", (file,)).fetchone() is None:
                    self._retire(file, time.time())
        return rejection

    def _result_row(self, key: str, where: str, args: tuple[Any, ...]) -> ResultRow | None:
        row = self._conn.execute(
            "SELECT result_id, path, lookup, family, analysis_id, action, record, file, bytes, computed_at, "
            f"saved_at, last_used FROM results WHERE path = ? AND {where} ORDER BY computed_at DESC LIMIT 1",
            (key, *args)).fetchone()
        if row is None:
            return None
        return ResultRow(result_id=str(row[0]), path=self._source_path(str(row[1])), lookup=str(row[2]),
                         family=str(row[3]), analysis_id=str(row[4]), action=str(row[5]), record=json.loads(row[6]),
                         file=str(row[7]), bytes=int(row[8]), computed_at=float(row[9]), saved_at=float(row[10]),
                         last_used=float(row[11]))

    def find_result(self, path: str, lookup: str, family: str = "") -> Read[ResultFound]:
        """``path``'s result saved under ``lookup`` with its data file (``exact``), else with a
        ``family`` the newest one of the same plot and settings whose script or data differ (an
        outdated result, ``exact`` False), else missing. A file replaced meanwhile is answered by
        looking again once (as :meth:`read_dataset`); an error is never "nothing saved"."""
        if self._depth:
            raise RuntimeError("find_result can't run inside a transaction")
        key = self._path_key(path)
        if not self._results_table:
            return _missing()  # (A read-only store without results: none saved.)
        for attempt in range(2):
            legacy: LegacyStore | None = None
            try:
                with self.transaction(write=False):
                    row = self._result_row(key, "lookup = ?", (lookup,))
                    exact = row is not None
                    if row is None and (legacy := self._kept_legacy()) is not None:
                        # Keep (Q22.3): an exact match in store-v3 before an outdated one here.
                        row = self._legacy_result(legacy, key, "lookup = ?", (lookup,))
                        exact = row is not None
                    if row is None and family:
                        row, legacy = self._result_row(key, "family = ? AND lookup <> ?", (family, lookup)), None
                        if row is None and (legacy := self._kept_legacy()) is not None:
                            row = self._legacy_result(legacy, key, "family = ? AND lookup <> ?", (family, lookup))
            except (sqlite3.Error, StoreError, ValueError, LegacyUnavailable) as exc:
                return _error(f"Disk cache could not be read: {exc}")
            if row is None:
                return _missing()
            try:
                if legacy is not None:
                    return _found(ResultFound(row, legacy.read_file(row["file"]), exact, legacy=True))
                with open(self._store_file(row["file"]), "rb") as handle:
                    return _found(ResultFound(row, handle.read(), exact))
            except FileNotFoundError:
                if attempt:
                    return _error("Cached result file is missing")
            except OSError as exc:
                return _error(f"Cached result file could not be read: {exc}")
        return _error("Cached result file is missing")  # (Not reached.)

    def _legacy_result(self, legacy: LegacyStore, key: str, where: str, args: tuple[Any, ...]) -> ResultRow | None:
        """``_result_row`` of store-v3 (Keep), its path given as this store shows it; none for a key
        store-v4 removed results of (C2-1), nor one older than v4's last purge by age."""
        if self._legacy_hidden("results", key):
            return None
        row = legacy.result_row(key, where, args, since=self._legacy_purged("results")[0])
        if row is None:
            return None
        return ResultRow(result_id=str(row[0]), path=self._source_path(str(row[1])), lookup=str(row[2]),
                         family=str(row[3]), analysis_id=str(row[4]), action=str(row[5]), record=json.loads(row[6]),
                         file=str(row[7]), bytes=int(row[8]), computed_at=float(row[9]), saved_at=float(row[10]),
                         last_used=float(row[11]))

    def _folder_results(self, keys: Sequence[str]) -> dict[str, ResultCount]:
        """Each folder's saved results (count and files' bytes; zero if none), as of this
        transaction's write count (``seq``), for the folder row's badge (inside a transaction)."""
        counts = {key: ResultCount(0, 0, self.store_id, self._writes()) for key in keys}
        if not self._results_table:
            return counts
        stored = list(counts)
        for start in range(0, len(stored), 500):
            chunk = stored[start:start + 500]
            for key, count, size in self._conn.execute(
                    f"SELECT path, COUNT(*), COALESCE(SUM(bytes), 0) FROM results "
                    f"WHERE path IN ({','.join('?' * len(chunk))}) GROUP BY path", chunk):
                counts[str(key)] = ResultCount(int(count), int(size), self.store_id, counts[str(key)].writes)
        legacy = self._kept_legacy()
        if legacy is not None:
            # Keep (Q22.3): store-v3's results of these folders count too (read through, not copied):
            # those that can be found, so not a lookup v4 has (C2-4) nor any of a key v4 removed (C2-1).
            readable = [key for key in stored if not self._legacy_hidden("results", key)]
            with contextlib.suppress(LegacyUnavailable):
                found = legacy.result_lookups(readable, since=self._legacy_purged("results")[0])
                for key, rows in found.items():
                    have = counts[key]
                    mine = {str(lookup) for (lookup,) in self._conn.execute(
                        "SELECT lookup FROM results WHERE path = ?", (key,))}
                    extra = [size for lookup, size in rows if lookup not in mine]
                    counts[key] = ResultCount(have.count + len(extra), have.bytes + sum(extra), self.store_id,
                                              have.writes)
        return counts

    def result_counts(self, paths: Sequence[str]) -> dict[str, ResultCount]:
        """Each folder's saved results, by source path, for a listing's entries; a path without a
        key here (above every data root, an unsupported mount) is left out."""
        keys: dict[str, str] = {}
        for path in dict.fromkeys(paths):
            try:
                keys[path] = self._path_key(path)
            except Exception:
                continue
        try:
            with self.transaction(write=False):
                counts = self._folder_results(list(dict.fromkeys(keys.values())))
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be read: {exc}") from exc
        return {path: counts[key] for path, key in keys.items()}

    def touch_result(self, path: str, lookup: str, now: float | None = None) -> None:
        """Record that a saved result was shown (purges by age go by it)."""
        key = self._path_key(path)
        try:
            with self.transaction():
                self._conn.execute("UPDATE results SET last_used = ? WHERE path = ? AND lookup = ?",
                                   (time.time() if now is None else now, key, lookup))
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    def remove_results(self, paths: Iterable[str] | None = None, *, root: str | None = None,
                       cutoff: float | None = None) -> ResultRemoval:
        """The one removal of saved results (Clear cached analysis, purges by age): every result
        (bumping ``gen_results``), a data root's (``root``, its UUID: bumping its results epoch),
        those of ``paths`` (each folder's results epoch), or those not used since ``cutoff``
        (each folder's results epoch). One transaction; files are retired. Datasets and records
        stay."""
        now = time.time()
        args: tuple[Any, ...]
        if not self._results_table:
            raise StoreReadOnly("This disk cache was written by a newer HeLab and is read-only")
        try:
            with self.transaction():
                if root is not None:
                    top = f"root://{root}"
                    where, args = " WHERE path = ? OR substr(path, 1, ?) = ?", (top, len(top) + 1, top + "/")
                    self._conn.execute("INSERT INTO folder_epochs (path, epoch) VALUES (?, 1) ON CONFLICT (path) "
                                       "DO UPDATE SET epoch = epoch + 1", (_results_root_epoch(top),))
                elif cutoff is not None:
                    where, args = " WHERE last_used < ?", (cutoff,)
                    self._note_purge("results", cutoff)
                elif paths is not None:
                    keys = tuple(dict.fromkeys(self._path_key(path) for path in paths))
                    where, args = f" WHERE path IN ({','.join('?' * len(keys)) or 'NULL'})", keys
                else:
                    where, args = "", ()
                    self._conn.execute("UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) "
                                       "WHERE key = 'gen_results'")
                rows = self._conn.execute(f"SELECT path, file, bytes FROM results{where}", args).fetchall()
                for _, file, _ in rows:
                    self._retire(str(file), now)
                self._conn.execute(f"DELETE FROM results{where}", args)
                waiting: list[str] = []
                if self._pending_results and cutoff is None:
                    # Results waiting for an answer go with the saved ones they would join (not by age).
                    for folder, file in self._conn.execute(f"SELECT path, file FROM pending_results{where}",
                                                           args).fetchall():
                        self._retire(str(file), now)
                        waiting.append(str(folder))
                    self._conn.execute(f"DELETE FROM pending_results{where}", args)
                elif self._pending_results:
                    # A purge moves the epochs of the folders it took results from: their waiting
                    # results' guards no longer hold (Make room would refuse them), so they go too.
                    for folder in sorted({str(path) for path, _, _ in rows}):
                        for (file,) in self._conn.execute("SELECT file FROM pending_results WHERE path = ?",
                                                          (folder,)).fetchall():
                            self._retire(str(file), now)
                        self._conn.execute("DELETE FROM pending_results WHERE path = ?", (folder,))
                by_path = root is None and cutoff is None and paths is not None
                folders = sorted({str(path) for path, _, _ in rows} | set(waiting)
                                 | (set(map(str, args)) if by_path else set()))
                if root is not None or cutoff is not None or paths is not None:
                    for folder in folders:
                        self._conn.execute("INSERT INTO folder_epochs (path, epoch) VALUES (?, 1) ON CONFLICT (path) "
                                           "DO UPDATE SET epoch = epoch + 1", (_results_epoch(folder),))
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        everything = root is None and cutoff is None and paths is None
        return ResultRemoval(None if everything else tuple(self._source_path(path) for path in folders),
                             len(rows), sum(int(size) for _, _, size in rows), root)

    # Raw layers (store-v4, caching v2 stage 1): one row per raw file, its pulses in ``raw/<uuid>.hlb``.

    def _needs_v4(self) -> None:
        if self.layout < store_v4.LAYOUT:
            raise StoreError("Raw layers are kept only in store-v4")

    def write_raw_file(self, packed: bytes) -> str:
        """Publish a raw layer's ``.hlb`` under its final name (``raw/<name>``); no row names it yet (a
        killed writer's file is an orphan the sweep deletes after an hour, the existing rule)."""
        return self._write_v4_file(self.raw_dir, store_v4.RAW_DIRNAME, packed, "raw layer")

    def _write_v4_file(self, folder: str, dirname: str, packed: bytes, what: str) -> str:
        """Publish a store-v4 ``.hlb`` in ``folder`` (temporary name, fsync, rename): ``<dirname>/<name>``."""
        self._needs_v4()
        if self.read_only:
            raise StoreReadOnly("This disk cache was written by a newer HeLab and is read-only")
        name = uuid.uuid4().hex
        temporary = os.path.join(folder, f"tmp-{name}")
        final = f"{name}.hlb"
        try:
            os.makedirs(folder, exist_ok=True)
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o666)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(packed)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, os.path.join(folder, final))
        except OSError as exc:
            with contextlib.suppress(OSError):
                os.remove(temporary)
            raise StoreError(f"Cached {what} could not be written: {exc}") from exc
        _fsync_dir(folder)
        return f"{dirname}/{final}"

    def start_raw_job(self, path: str) -> SaveGuard:
        """A guard for a job that may save ``path``'s raw layers: ``gen_raw``, the folder's ``raw:``
        epoch and its root's, and the folder's next ``job_seq`` (shared with its dataset saves, so a
        later listing's version wins whichever job saved it)."""
        self._needs_v4()
        key = self._path_key(path)
        try:
            with self.transaction():
                self._conn.execute("INSERT INTO folder_epochs (path, job_seq) VALUES (?, 1) "
                                   "ON CONFLICT (path) DO UPDATE SET job_seq = job_seq + 1", (key,))
                (job_seq,) = self._conn.execute("SELECT job_seq FROM folder_epochs WHERE path = ?", (key,)).fetchone()
                epochs = {_raw_epoch(key): self._epoch(_raw_epoch(key))}
                if root := _root_epoch(key):
                    epochs[root] = self._epoch(root)
                generation = int(self._meta()["gen_raw"])
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return SaveGuard({"raw": generation}, epochs, int(job_seq))

    def _check_raw_guard(self, guard: SaveGuard, key: str) -> None:
        epoch, root = _raw_epoch(key), _root_epoch(key)
        if "raw" not in guard.generations or epoch not in guard.epochs:
            raise SaveRejected("cleared", REKEYED)  # (As ``_guard_holds``.)
        if (int(self._meta()["gen_raw"]) != guard.generations["raw"] or self._epoch(epoch) != guard.epochs[epoch]
                or (root is not None and self._epoch(root) != guard.epochs.get(root, 0))):
            raise SaveRejected("cleared", "Raw pulses were cleared before saving completed")

    def save_raw_batch(self, path: str, entries: Sequence[RawEntry], guard: SaveGuard, *,
                       budget: int | None = None, budget_set_at: float | None = None,
                       now: float | None = None) -> RawSave:
        """Save one batch of a folder's raw layers (``raw_fill``, a conversion) in one transaction with
        one fit check, if ``guard`` holds and the folder may be cached. A shot already cached from the
        same file (fingerprint and parser) is kept (seen now); one cached from another version of the
        file is replaced only by a job that started later (``job_seq``), and named in ``overwritten``
        when the file changed in place; the replaced files are retired. A batch that doesn't fit the
        budget saves nothing and never waits for an answer (T~1): its files are retired. A rejected
        batch raises :class:`SaveRejected` and retires its files."""
        self._needs_v4()
        key = self._path_key(path)
        now = time.time() if now is None else now
        files = [entry.file for entry in entries]
        sizes = {entry.file: self._size(entry.file) for entry in entries}
        saved: list[int] = []
        kept: list[int] = []
        refused: list[int] = []
        overwritten: list[RawOverwrite] = []
        unused: list[str] = []
        retired: list[str] = []
        try:
            with self.transaction():
                self._check_raw_guard(guard, key)
                self._check_cacheable(key)
                budget = self._active_budget(budget, budget_set_at)
                self._conn.execute("SAVEPOINT raw_fit")
                maker = self._maker_id()
                for entry in entries:
                    row = self._conn.execute(
                        "SELECT size, mtime_ns, sha256, parser, file, job_seq, gone_at FROM raw_layers "
                        "WHERE path = ? AND shot = ?", (key, entry.shot)).fetchone()
                    read_at = now if entry.read_at is None else entry.read_at
                    if row is not None and (int(row[0]), int(row[1]), int(row[3])) == (
                            entry.size, entry.mtime_ns, entry.parser):
                        # (Seen when read: it clears an only-copy mark only if newer than it, C2-10.)
                        self._conn.execute(
                            "UPDATE raw_layers SET seen_at = MAX(seen_at, ?), last_used = ?, "
                            "gone_at = CASE WHEN gone_at IS NOT NULL AND gone_at >= ? THEN gone_at END "
                            "WHERE path = ? AND shot = ?", (read_at, now, read_at, key, entry.shot))
                        kept.append(entry.shot)
                        unused.append(entry.file)
                        continue
                    if row is not None and int(row[5]) > guard.job_seq:
                        refused.append(entry.shot)  # (A job that listed the folder later saved its version.)
                        unused.append(entry.file)
                        continue
                    # A listing at or after this batch read the file found the shot gone: still the only
                    # copy (C2-11); one before the read is outdated by it.
                    gone_at = (float(row[6]) if row is not None and row[6] is not None and float(row[6]) >= read_at
                               else None)
                    if row is not None:
                        retired.append(str(row[4]))
                        if (int(row[0]), int(row[1])) != (entry.size, entry.mtime_ns):
                            overwritten.append(RawOverwrite(
                                entry.shot, entry.name, (int(row[0]), int(row[1]), str(row[2])),
                                (entry.size, entry.mtime_ns, entry.sha256)))
                    self._conn.execute(
                        "INSERT OR REPLACE INTO raw_layers (path, shot, name, size, mtime_ns, sha256, parser, "
                        "encoding, facts, pulses, file, bytes, seen_at, gone_at, maker, job_seq, saved_at, last_used) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (key, entry.shot, entry.name, entry.size, entry.mtime_ns, entry.sha256, entry.parser,
                         entry.encoding, _dumps(dict(entry.facts)), entry.pulses, entry.file, sizes[entry.file],
                         read_at, gone_at, maker, guard.job_seq, now, now))
                    saved.append(entry.shot)
                usage, writes = self._live(), self._writes()
                if budget is not None and usage > budget and saved:
                    self._conn.execute("ROLLBACK TO raw_fit")
                    self._conn.execute("RELEASE raw_fit")
                    for file in files:
                        self._retire(file, now)
                    return RawSave((), (), (), (), "over_budget", sum(sizes.values()), self._live(), self._writes(),
                                   budget)
                self._conn.execute("RELEASE raw_fit")
                for file in (*unused, *retired):
                    self._retire(file, now)
        except SaveRejected as rejection:
            raise self._reject_raw_files(files, rejection) from None
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return RawSave(tuple(saved), tuple(kept), tuple(refused), tuple(overwritten), "",
                       sum(sizes[entry.file] for entry in entries if entry.shot in saved), usage, writes, budget)

    def _reject_raw_files(self, files: Sequence[str], rejection: SaveRejected) -> SaveRejected:
        """Retire a rejected batch's files, in their own transaction (never one a row names)."""
        with contextlib.suppress(sqlite3.Error, StoreError):
            with self.transaction():
                now = time.time()
                for file in files:
                    if self._conn.execute("SELECT 1 FROM raw_layers WHERE file = ?", (file,)).fetchone() is None:
                        self._retire(file, now)
        return rejection

    def mark_raw_seen(self, path: str, present: Mapping[int, tuple[int, int]], seen_at: float) -> tuple[int, int]:
        """A full listing of ``path`` found these raw files (shot: (size, mtime_ns)): rows of the same
        fingerprint are seen now; rows whose shot it didn't find get ``gone_at`` (their layer is then the
        only copy HeLab knows of: kept, Q22.6; Make room lists it last). (seen, gone) counts."""
        self._needs_v4()
        key = self._path_key(path)
        seen = gone = 0
        try:
            with self.transaction():
                # Each mark goes by when its evidence was taken, so an older listing landing late can't
                # undo a newer one (C2-10): seen clears gone only if newer than it; gone needs a listing newer
                # than the last sighting.
                for shot, size, mtime_ns in self._conn.execute(
                        "SELECT shot, size, mtime_ns FROM raw_layers WHERE path = ?", (key,)).fetchall():
                    if present.get(int(shot)) == (int(size), int(mtime_ns)):
                        self._conn.execute(
                            "UPDATE raw_layers SET seen_at = MAX(seen_at, ?), "
                            "gone_at = CASE WHEN gone_at IS NOT NULL AND gone_at >= ? THEN gone_at END "
                            "WHERE path = ? AND shot = ?", (seen_at, seen_at, key, shot))
                        seen += 1
                    elif int(shot) not in present:
                        gone += self._conn.execute(
                            "UPDATE raw_layers SET gone_at = COALESCE(gone_at, ?) WHERE path = ? AND shot = ? "
                            "AND seen_at < ?", (seen_at, key, shot, seen_at)).rowcount
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return seen, gone

    def raw_rows(self, path: str) -> Read[dict[int, RawRow]]:
        """``path``'s raw layer rows by shot (a ``raw_fill`` resumes from them)."""
        if self.layout < store_v4.LAYOUT:
            return _missing()
        key = self._path_key(path)
        try:
            with self.transaction(write=False):
                found = {int(row[1]): self._raw_row(row) for row in self._conn.execute(
                    f"SELECT {_RAW_COLUMNS} FROM raw_layers WHERE path = ?", (key,))}
        except (sqlite3.Error, StoreError, ValueError) as exc:
            return _error(f"Disk cache could not be read: {exc}")
        return _found(found)

    def _raw_row(self, row: Sequence[Any]) -> RawRow:
        return RawRow(self._source_path(str(row[0])), int(row[1]), str(row[2]), int(row[3]), int(row[4]), str(row[5]),
                      int(row[6]), str(row[7]), json.loads(row[8]), int(row[9]), str(row[10]), int(row[11]),
                      float(row[12]), None if row[13] is None else float(row[13]), str(row[14]), int(row[15]),
                      float(row[16]), float(row[17]))

    def read_raw(self, path: str, shot: int) -> Read[tuple[RawRow, bytes]]:
        """A shot's raw layer row and its ``.hlb`` bytes; a file replaced meanwhile is looked up once more."""
        if self.layout < store_v4.LAYOUT:
            return _missing()
        key = self._path_key(path)
        for attempt in range(2):
            try:
                with self.transaction(write=False):
                    row = self._conn.execute(f"SELECT {_RAW_COLUMNS} FROM raw_layers WHERE path = ? AND shot = ?",
                                             (key, shot)).fetchone()
            except (sqlite3.Error, StoreError) as exc:
                return _error(f"Disk cache could not be read: {exc}")
            if row is None:
                return _missing()
            found = self._raw_row(row)
            try:
                with open(self._store_file(found.file), "rb") as handle:
                    return _found((found, handle.read()))
            except FileNotFoundError:
                if attempt:
                    return _error("Cached raw layer file is missing")
            except OSError as exc:
                return _error(f"Cached raw layer file could not be read: {exc}")
        return _error("Cached raw layer file is missing")  # (Not reached.)

    def _remove_raw_rows(self, where: str, args: Sequence[Any], now: float) -> tuple[list[str], int, int]:
        """Delete the raw rows ``where`` selects (inside a transaction), retire their files and bump each
        folder's ``raw:`` epoch: (folder keys, rows, bytes)."""
        found = self._conn.execute(f"SELECT path, file, bytes FROM raw_layers{where}", tuple(args)).fetchall()
        for _, file, _ in found:
            self._retire(str(file), now)
        self._conn.execute(f"DELETE FROM raw_layers{where}", tuple(args))
        keys = sorted({str(key) for key, _, _ in found})
        for key in keys:
            self._conn.execute("INSERT INTO folder_epochs (path, epoch) VALUES (?, 1) ON CONFLICT (path) "
                               "DO UPDATE SET epoch = epoch + 1", (_raw_epoch(key),))
        return keys, len(found), sum(int(size) for _, _, size in found)

    def remove_raw(self, paths: Iterable[str] | None = None) -> RawRemoval:
        """Clear raw pulses (the user asked: Settings › Cache, Clear all): every folder's (bumping
        ``gen_raw``) or these folders' (each one's ``raw:`` epoch), so a batch already being saved can't
        bring them back. Files are retired; nothing else is touched."""
        if self.layout < store_v4.LAYOUT:
            return RawRemoval(None if paths is None else (), 0, 0)
        now = time.time()
        try:
            with self.transaction():
                if paths is None:
                    self._conn.execute("UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) "
                                       "WHERE key = 'gen_raw'")
                    _, count, size = self._remove_raw_rows("", (), now)
                    return RawRemoval(None, count, size)
                keys = list(dict.fromkeys(self._path_key(path) for path in paths))
                for key in keys:  # (A folder with no rows is fenced too: a batch may be on its way.)
                    self._conn.execute("INSERT INTO folder_epochs (path, epoch) VALUES (?, 1) ON CONFLICT (path) "
                                       "DO UPDATE SET epoch = epoch + 1", (_raw_epoch(key),))
                _, count, size = self._remove_raw_rows(
                    f" WHERE path IN ({','.join('?' * len(keys)) or 'NULL'})", keys, now)
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return RawRemoval(tuple(self._source_path(key) for key in keys), count, size)

    # (``remove_raw_following``'s rows, and its question's estimate: one condition for both, S4-1.)
    _FOLLOWING = " WHERE path NOT IN (SELECT path FROM cache_policy WHERE policy != '')"

    def remove_raw_following(self) -> RawRemoval:
        """S4~1 for the global policy (the user asked, after Settings › Cache's TXY only): the raw pulses of every
        folder that follows Settings' policy (none of its own), each folder's ``raw:`` epoch bumped as
        :meth:`remove_raw` does; folders with their own policy keep theirs."""
        if self.layout < store_v4.LAYOUT:
            return RawRemoval((), 0, 0)
        now = time.time()
        try:
            with self.transaction():
                keys = [str(key) for (key,) in self._conn.execute(
                    f"SELECT DISTINCT path FROM raw_layers{self._FOLLOWING}")]
                for key in keys:
                    self._conn.execute("INSERT INTO folder_epochs (path, epoch) VALUES (?, 1) ON CONFLICT (path) "
                                       "DO UPDATE SET epoch = epoch + 1", (_raw_epoch(key),))
                _, count, size = self._remove_raw_rows(
                    f" WHERE path IN ({','.join('?' * len(keys)) or 'NULL'})", keys, now)
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return RawRemoval(tuple(self._source_path(key) for key in keys), count, size)

    def _raw_summary(self) -> dict[str, Any]:
        """store-v4's raw layers for Settings › Cache (inside a transaction): rows, bytes, folders, the
        rows whose raw files were gone at the last look (``only_copy``), when one was last used."""
        if self.layout < store_v4.LAYOUT:
            return {"count": 0, "bytes": 0, "folders": 0, "only_copy": 0, "only_copy_bytes": 0, "last_used": None}
        count, size, folders, last = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(bytes), 0), COUNT(DISTINCT path), MAX(last_used) FROM raw_layers").fetchone()
        only, only_bytes = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(bytes), 0) FROM raw_layers WHERE gone_at IS NOT NULL").fetchone()
        # What Settings' TXY only would remove (``remove_raw_following``, by its own condition: S4-1).
        f_count, f_size, f_folders, f_only = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(bytes), 0), COUNT(DISTINCT path), COALESCE(SUM(gone_at IS NOT NULL), 0) "
            f"FROM raw_layers{self._FOLLOWING}").fetchone()
        return {"count": int(count), "bytes": int(size), "folders": int(folders), "only_copy": int(only),
                "only_copy_bytes": int(only_bytes), "last_used": None if last is None else float(last),
                "following": {"count": int(f_count), "bytes": int(f_size), "folders": int(f_folders),
                              "only_copy": int(f_only)}}

    def _raw_live(self) -> int:
        if self.layout < store_v4.LAYOUT:
            return 0
        return int(self._conn.execute("SELECT COALESCE(SUM(bytes), 0) FROM raw_layers").fetchone()[0])

    # TXY layers (store-v4, caching v2 stage 2: design addendum §2–§8). A folder's ``matlab`` and
    # ``helab:<profile hash>`` layers hold each shot once, in append-only segments (``txy/<uuid>.hlb``); a
    # view (``txy_views``) is what one source mode and tag loads. Nothing here runs under store-v3.

    def write_txy_file(self, packed: bytes) -> str:
        """Publish a TXY segment's ``.hlb`` (``txy/<name>``); no row names it yet (an orphan otherwise, the
        sweep's existing rule)."""
        return self._write_v4_file(self.txy_dir, store_v4.TXY_DIRNAME, packed, "TXY segment")

    def start_txy_job(self, path: str) -> SaveGuard:
        """A guard for a job that may save ``path``'s TXY layers and views: ``gen_txy`` and ``gen_datasets``, the
        folder's ``txy:`` epoch, its own (a Clear of its datasets: a load may seed layers from them, Q45.4) and
        its root's, and the folder's next ``job_seq`` (shared with its raw and dataset saves)."""
        self._needs_v4()
        key = self._path_key(path)
        try:
            with self.transaction():
                self._conn.execute("INSERT INTO folder_epochs (path, job_seq) VALUES (?, 1) "
                                   "ON CONFLICT (path) DO UPDATE SET job_seq = job_seq + 1", (key,))
                (job_seq,) = self._conn.execute("SELECT job_seq FROM folder_epochs WHERE path = ?", (key,)).fetchone()
                epochs = {_txy_epoch(key): self._epoch(_txy_epoch(key)), key: self._epoch(key)}
                if root := _root_epoch(key):
                    epochs[root] = self._epoch(root)
                meta = self._meta()
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return SaveGuard({"txy": int(meta["gen_txy"]), "datasets": int(meta["gen_datasets"])}, epochs, int(job_seq))

    def _txy_guard_holds(self, guard: Mapping[str, Any], key: str) -> bool:
        """Whether a TXY guard (a ``SaveGuard``'s generations and epochs) still holds for ``key``; raises for
        a guard of another key (a re-key since, as ``_guard_holds``)."""
        generations, epochs = guard["generations"], guard["epochs"]
        epoch, root = _txy_epoch(key), _root_epoch(key)
        if "txy" not in generations or epoch not in epochs:
            raise SaveRejected("cleared", REKEYED)
        meta = self._meta()
        return (int(meta["gen_txy"]) == int(generations["txy"]) and self._epoch(epoch) == int(epochs[epoch])
                and (root is None or self._epoch(root) == int(epochs.get(root, 0)))
                # (A Clear of the folder's datasets since, by kind or for it: a seed from them is stale.)
                and ("datasets" not in generations or int(meta["gen_datasets"]) == int(generations["datasets"]))
                and (key not in epochs or self._epoch(key) == int(epochs[key])))

    def _check_txy_guard(self, guard: SaveGuard, key: str) -> None:
        if not self._txy_guard_holds({"generations": guard.generations, "epochs": guard.epochs}, key):
            raise SaveRejected("cleared", "Cached TXY data was cleared before saving completed")

    def policy_of(self, path: str, default: str = store_v4.DEFAULT_POLICY) -> str:
        """``path``'s cache policy (Q45.1): its own choice, else ``default`` (the app's global one); store-v3 has
        none (``raw+used``: raw rows are store-v4's anyway)."""
        if self.layout < store_v4.LAYOUT:
            return store_v4.DEFAULT_POLICY
        try:
            with self.transaction(write=False):
                return self._policy(self._path_key(path), default)
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be read: {exc}") from exc

    def _policy(self, key: str, default: str) -> str:
        """The folder's cache policy (Q45.1): its own row, else the global setting the app sent."""
        row = self._conn.execute("SELECT policy FROM cache_policy WHERE path = ?", (key,)).fetchone()
        if row is not None and row[0] in store_v4.POLICIES:
            return str(row[0])
        return default if default in store_v4.POLICIES else store_v4.DEFAULT_POLICY

    def save_txy(self, path: str, source: str, tag: str, parts: Sequence[TxyPart], view: ViewRecord | None,
                 guard: SaveGuard, *, budget: int | None = None, budget_set_at: float | None = None,
                 default_policy: str = store_v4.DEFAULT_POLICY, hold: bool = True, seen_at: float | None = None,
                 now: float | None = None) -> TxySave:
        """Save one unit (design addendum §5): each part's new segment, the layer rows and the view, in one
        transaction with one fit check, if ``guard`` holds and the folder may be cached. Under policy ``raw``
        HeLab layers aren't written (their files are retired). A shot a later job saved is kept (``refused``).
        Over the budget, or growing a folder's layers while usage is at 80 % or more, the unit waits as the
        folder's one pending save, merged with one already waiting (Q45.8); without ``hold`` (a plot's own TXY
        choice, Q19.3) it is dropped instead, its files retired, and nothing asks. ``seen_at``: when the job's
        listing saw these sources, a new layer's first sighting (S2-3: a listing after it that found one gone
        still counts; default: now). A rejected unit raises :class:`SaveRejected` and retires its files."""
        self._needs_v4()
        key = self._path_key(path)
        now = time.time() if now is None else now
        files = [part.file for part in parts]
        try:
            with self.transaction():
                self._check_txy_guard(guard, key)
                self._check_cacheable(key)
                policy = self._policy(key, default_policy)
                kept = [part for part in parts
                        if not (policy == "raw" and part.layer.startswith(_HELAB_LAYER))]
                dropped = tuple(part.layer for part in parts if part not in kept)
                for part in parts:
                    if part not in kept:
                        self._retire(part.file, now)
                sizes = {part.file: self._size(part.file) for part in kept}
                budget = self._active_budget(budget, budget_set_at)
                before = self._live()
                had = self._conn.execute("SELECT 1 FROM txy_layers WHERE path = ?", (key,)).fetchone() is not None
                self._conn.execute("SAVEPOINT txy_fit")
                refused = self._apply_txy_unit(key, source, tag, kept, sizes, view, guard.job_seq, now, seen_at)
                usage = self._live()
                grows = sum(sizes.values()) > 0
                reason = ""
                if budget is not None and grows and usage > budget:
                    reason = "over_budget"
                elif (budget is not None and had and grows and usage > before
                      and before >= APPROVAL_SHARE * budget):
                    reason = "needs_approval"
                if reason:
                    self._conn.execute("ROLLBACK TO txy_fit")
                    self._conn.execute("RELEASE txy_fit")
                    if not hold:
                        for part in kept:
                            self._retire(part.file, now)
                        return TxySave((), (), dropped, reason, "", sum(sizes.values()), self._live(), self._writes(),
                                       budget)
                    pending_id = self._insert_txy_pending(key, source, tag, kept, sizes, view, guard, reason, now,
                                                          seen_at)
                    return TxySave((), (), dropped, reason, pending_id, sum(sizes.values()), self._live(),
                                   self._writes(), budget)
                self._conn.execute("RELEASE txy_fit")
                usage, writes = self._live(), self._writes()
        except SaveRejected as rejection:
            raise self._reject_txy_files(files, rejection) from None
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return TxySave(tuple(part.layer for part in kept), refused, dropped, "", "", sum(sizes.values()), usage,
                       writes, budget)

    def _apply_txy_unit(self, key: str, source: str, tag: str, parts: Sequence[TxyPart], sizes: Mapping[str, int],
                        view: ViewRecord | None, job_seq: int, now: float,
                        seen_at: float | None = None) -> tuple[tuple[str, int], ...]:
        """Write a unit's parts and view (inside a write transaction): each part a new segment of its layer
        holding the shots it replaces or adds; a shot whose entry a later job saved is kept and named; a
        segment left without a live shot is deleted and its file retired. The view is replaced only by a
        job that started no earlier than its own."""
        maker = self._maker_id()
        refused: list[tuple[str, int]] = []
        for part in parts:
            row = self._conn.execute("SELECT tags, entries, precision FROM txy_layers WHERE path = ? AND layer = ?",
                                     (key, part.layer)).fetchone()
            entries = {} if row is None else {entry.shot: entry for entry in map(TxyEntry.from_json,
                                                                                    json.loads(row[1]))}
            (seq,) = self._conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM txy_segments "
                                        "WHERE path = ? AND layer = ?", (key, part.layer)).fetchone()
            applied = 0
            superseded: dict[int, int] = {}
            for item in part.shots:
                old = entries.get(item.shot)
                if old is not None and old.job_seq > job_seq:
                    refused.append((part.layer, item.shot))
                    continue
                if old is not None:
                    superseded[old.seq] = superseded.get(old.seq, 0) + 1
                entries[item.shot] = TxyEntry(item.shot, item.size, item.mtime_ns, item.kind, int(seq), item.rows,
                                              item.problematic, job_seq)
                applied += 1
            for old_seq, count in superseded.items():
                self._conn.execute("UPDATE txy_segments SET live_shots = live_shots - ? WHERE path = ? AND layer = ? "
                                   "AND seq = ?", (count, key, part.layer, old_seq))
            if applied:
                self._conn.execute("INSERT INTO txy_segments (path, layer, seq, file, bytes, live_shots, all_shots) "
                                   "VALUES (?, ?, ?, ?, ?, ?, ?)",
                                   (key, part.layer, int(seq), part.file, sizes[part.file], applied, len(part.shots)))
            else:
                self._retire(part.file, now)
            for (file,) in self._conn.execute("SELECT file FROM txy_segments WHERE path = ? AND layer = ? "
                                              "AND live_shots <= 0", (key, part.layer)).fetchall():
                self._retire(str(file), now)
            self._conn.execute("DELETE FROM txy_segments WHERE path = ? AND layer = ? AND live_shots <= 0",
                               (key, part.layer))
            tags = sorted({*(json.loads(row[0]) if row is not None else ()), *part.tags})
            self._write_layer_row(key, part.layer, tags, entries, part.precision, maker, job_seq, now,
                                  keep_gone=row is not None, seen_at=seen_at)
        if view is not None:
            stored = self._conn.execute("SELECT job_seq FROM txy_views WHERE path = ? AND source = ? AND tag = ?",
                                        (key, source, tag)).fetchone()
            if stored is None or int(stored[0]) <= job_seq:
                self._conn.execute(
                    "INSERT OR REPLACE INTO txy_views (path, source, tag, fingerprint, problematic, raw_times, info, "
                    "maker, job_seq, last_used) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (key, source, tag, _dumps(view["fingerprint"]), _dumps(view["problematic"]),
                     _dumps(view.get("raw_times", [])), _dumps(view["info"]), maker, job_seq, now))
        return tuple(refused)

    def _write_layer_row(self, key: str, layer: str, tags: Sequence[str], entries: Mapping[int, TxyEntry],
                         precision: str, maker: str, job_seq: int, now: float, *, keep_gone: bool = True,
                         seen_at: float | None = None) -> None:
        """A layer row from its entries; its bytes are its segments'. ``gone_at`` stays as a listing set it."""
        (size,) = self._conn.execute("SELECT COALESCE(SUM(bytes), 0) FROM txy_segments WHERE path = ? AND layer = ?",
                                     (key, layer)).fetchone()
        rows = sum(entry.rows for entry in entries.values())
        stored = self._conn.execute("SELECT gone_at, seen_at, job_seq FROM txy_layers WHERE path = ? AND layer = ?",
                                    (key, layer)).fetchone()
        # (A new layer was seen when the job that saves it listed its sources, S2-3; an existing one keeps its
        # marks, S2-2.)
        gone = stored[0] if stored is not None and keep_gone else None
        seen = float(stored[1]) if stored is not None else (now if seen_at is None else seen_at)
        self._conn.execute(
            "INSERT OR REPLACE INTO txy_layers (path, layer, tags, entries, shots, rows, ram_bytes, bytes, precision, "
            "gone_at, seen_at, maker, job_seq, saved_at, last_used) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (key, layer, _dumps(list(tags)),
             _dumps([entry.to_json() for _, entry in sorted(entries.items())]), len(entries), rows,
             rows * TXY_ROW_BYTES, int(size), precision, gone, seen, maker,
             max(job_seq, int(stored[2]) if stored is not None else 0), now, now))

    def _insert_txy_pending(self, key: str, source: str, tag: str, parts: Sequence[TxyPart],
                            sizes: Mapping[str, int], view: ViewRecord | None, guard: SaveGuard, reason: str,
                            now: float, seen_at: float | None = None) -> str:
        """Keep a unit waiting for the user's answer as the folder's one pending save (Q45.8): merged with a
        unit already waiting, layer by layer (a later job's part replaces an earlier one's; an earlier one's
        arriving later is dropped), the later job's view kept. A dataset waiting from stage 1 is replaced by
        a later job, as today. Returns the new ``pending_id``."""
        existing = self._conn.execute("SELECT pending_id, file, job_seq, parts, record FROM pending_saves "
                                      "WHERE path = ?", (key,)).fetchone()
        merged: dict[str, dict[str, Any]] = {}
        record: dict[str, Any] = {"source": source, "tag": tag, "view": view, "view_job_seq": guard.job_seq}
        if existing is not None:
            old_parts = json.loads(existing[3] or "[]")
            if not old_parts:  # (A dataset waiting: the earlier job's loses, as ``_insert_pending``.)
                if int(existing[2]) >= guard.job_seq:
                    raise SaveRejected("newer", "Newer data is already waiting to be cached")
                self._retire(str(existing[1]), now)
            else:
                merged = {str(part["layer"]): part for part in old_parts}
                old_record = json.loads(existing[4])
                if view is None or int(old_record.get("view_job_seq", 0)) > guard.job_seq:
                    record = old_record  # (The view of the job that started later, or the only one.)
            self._conn.execute("DELETE FROM pending_saves WHERE path = ?", (key,))
        for part in parts:
            previous = merged.get(part.layer)
            if previous is not None and int(previous["job_seq"]) > guard.job_seq:
                self._retire(part.file, now)
                continue
            if previous is not None:
                self._retire(str(previous["file"]), now)
            merged[part.layer] = {**part.to_json(sizes[part.file], guard), "seen_at": seen_at}
        if not merged:
            raise SaveRejected("newer", "Newer data is already waiting to be cached")
        pending_id = uuid.uuid4().hex
        ordered = [merged[layer] for layer in sorted(merged)]
        self._conn.execute(
            "INSERT INTO pending_saves (pending_id, path, reason, file, bytes, record, gen_datasets, epoch, job_seq, "
            "created_at, parts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pending_id, key, reason, str(ordered[0]["file"]), sum(int(part["bytes"]) for part in ordered),
             _dumps(record), int(guard.generations["txy"]), int(guard.epochs[_txy_epoch(key)]),
             max(int(part["job_seq"]) for part in ordered), now, _dumps(ordered)))
        return pending_id

    def _reject_txy_files(self, files: Sequence[str], rejection: SaveRejected) -> SaveRejected:
        """Retire a rejected unit's files, in their own transaction (never one a row or a waiting part names)."""
        with contextlib.suppress(sqlite3.Error, StoreError):
            with self.transaction():
                named = self._known_files()
                now = time.time()
                for file in files:
                    if file not in named:
                        self._retire(file, now)
        return rejection

    def txy_layers(self, path: str) -> Read[dict[str, TxyLayerRow]]:
        """``path``'s TXY layers by layer, with their entries and segments."""
        if self.layout < store_v4.LAYOUT:
            return _missing()
        key = self._path_key(path)
        try:
            with self.transaction(write=False):
                found = {str(row[1]): self._layer_row(row) for row in self._conn.execute(
                    f"SELECT {_TXY_LAYER_COLUMNS} FROM txy_layers WHERE path = ?", (key,)).fetchall()}
        except (sqlite3.Error, StoreError, ValueError) as exc:
            return _error(f"Disk cache could not be read: {exc}")
        return _found(found)

    def _layer_row(self, row: Sequence[Any]) -> TxyLayerRow:
        segments = {int(seq): (str(file), int(size)) for seq, file, size in self._conn.execute(
            "SELECT seq, file, bytes FROM txy_segments WHERE path = ? AND layer = ?", (row[0], row[1]))}
        return TxyLayerRow(self._source_path(str(row[0])), str(row[1]), tuple(json.loads(row[2])),
                           {entry.shot: entry for entry in map(TxyEntry.from_json, json.loads(row[3]))},
                           int(row[4]), int(row[5]), int(row[6]), str(row[7]),
                           None if row[8] is None else float(row[8]), int(row[9]), float(row[10]), float(row[11]),
                           segments)

    def read_view(self, path: str, source: str, tag: str) -> Read[ViewRow]:
        """A composition's view (design addendum §4): found, missing, or an error (never "nothing saved")."""
        if self.layout < store_v4.LAYOUT:
            return _missing()
        key = self._path_key(path)
        try:
            with self.transaction(write=False):
                row = self._conn.execute(
                    "SELECT fingerprint, problematic, raw_times, info, job_seq, last_used FROM txy_views "
                    "WHERE path = ? AND source = ? AND tag = ?", (key, source, tag)).fetchone()
        except (sqlite3.Error, StoreError) as exc:
            return _error(f"Disk cache could not be read: {exc}")
        if row is None:
            return _missing()
        try:
            return _found(ViewRow(self._source_path(key), source, tag, json.loads(row[0]), json.loads(row[1]),
                                  json.loads(row[2]), json.loads(row[3]), int(row[4]), float(row[5])))
        except ValueError as exc:
            return _error(f"Saved view record is unreadable: {exc}")

    def folder_views(self, path: str) -> list[tuple[str, str, float]]:
        """A folder's views: (source, profile, last used) each ([] in store-v3, or when unreadable)."""
        if self.layout < store_v4.LAYOUT:
            return []
        key = self._path_key(path)
        try:
            with self.transaction(write=False):
                return [(str(source), str(tag), float(used)) for source, tag, used in self._conn.execute(
                    "SELECT source, tag, last_used FROM txy_views WHERE path = ?", (key,))]
        except (sqlite3.Error, StoreError):
            return []

    def read_txy_shots(self, path: str, layer: str, shots: Iterable[int] | None = None, *,
                       keys: Mapping[int, tuple[int, int, str]] | None = None) -> Read[dict[int, Any]]:
        """Shots of a layer (every one, or ``shots`` it holds) as read-only float64 (n, 3) arrays, each from
        the segment its entry names; a segment replaced meanwhile (compaction) is looked up once more. With
        ``keys`` (shot → the entry's (size, mtime_ns, kind) a view saved), a shot whose entry now has another
        key (another view's save replaced it, C-1) is left out, checked on the row its segments are read by."""
        from helab.convert import txy_layer
        from helab.utils import hlb
        if self.layout < store_v4.LAYOUT:
            return _missing()
        wanted = None if shots is None else {int(shot) for shot in shots}
        for attempt in range(2):
            rows = self.txy_layers(path)
            if rows.failed:
                return _error(rows.error)
            row = (rows.value or {}).get(layer)
            if row is None:
                return _missing()
            by_seq: dict[int, list[int]] = {}
            for shot, entry in row.entries.items():
                if keys is not None and keys.get(shot) != (entry.size, entry.mtime_ns, entry.kind):
                    continue
                if wanted is None or shot in wanted:
                    by_seq.setdefault(entry.seq, []).append(shot)
            found: dict[int, Any] = {}
            try:
                for seq, needed in sorted(by_seq.items()):
                    file = row.segments[seq][0]
                    with open(self._store_file(file), "rb") as handle:
                        held, _, _ = txy_layer.unpack_segment(handle.read())
                    for shot in needed:
                        found[shot] = held[shot]
                return _found(found)
            except (FileNotFoundError, KeyError):
                if attempt:
                    return _error("A cached TXY segment is missing")
            except (OSError, hlb.HlbError) as exc:
                return _error(f"A cached TXY segment could not be read: {exc}")
        return _error("A cached TXY segment is missing")  # (Not reached.)

    def confirm_view(self, path: str, source: str, tag: str, fingerprint: Sequence[Sequence[Any]],
                     info: Mapping[str, Any], guard: SaveGuard, *, raw_times: Sequence[Sequence[int]] | None = None,
                     now: float | None = None) -> bool:
        """A load that found every shot of a view unchanged (A40.3): only the view's ``info`` (signature,
        listing, ``unsettled``, the TXY record with its folders) is written, if the guard holds, the view
        still has this fingerprint and no later job wrote it. Nothing is rewritten. Whether it was written."""
        self._needs_v4()
        key = self._path_key(path)
        now = time.time() if now is None else now
        try:
            with self.transaction():
                if not self._txy_guard_holds({"generations": guard.generations, "epochs": guard.epochs}, key):
                    return False
                row = self._conn.execute("SELECT fingerprint, job_seq FROM txy_views WHERE path = ? AND source = ? "
                                         "AND tag = ?", (key, source, tag)).fetchone()
                if row is None or json.loads(row[0]) != [list(item) for item in fingerprint] or int(row[1]) > guard.job_seq:
                    return False
                self._conn.execute("UPDATE txy_views SET info = ?, job_seq = ?, last_used = ? WHERE path = ? "
                                   "AND source = ? AND tag = ?", (_dumps(dict(info)), guard.job_seq, now, key, source,
                                                                  tag))
                if raw_times is not None:  # (Shot times a cache saved before them lacked.)
                    self._conn.execute("UPDATE txy_views SET raw_times = ? WHERE path = ? AND source = ? AND tag = ?",
                                       (_dumps([list(item) for item in raw_times]), key, source, tag))
                return True
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    def touch_txy(self, path: str, layers: Iterable[str], view: tuple[str, str] | None = None) -> None:
        """Mark a folder's layers (and a view) used now, for Make room's least-recently-used order."""
        if self.layout < store_v4.LAYOUT or self.read_only:
            return
        key = self._path_key(path)
        now = time.time()
        with contextlib.suppress(sqlite3.Error, StoreError):
            with self.transaction():
                for layer in layers:
                    self._conn.execute("UPDATE txy_layers SET last_used = ? WHERE path = ? AND layer = ?",
                                       (now, key, layer))
                if view is not None:
                    self._conn.execute("UPDATE txy_views SET last_used = ? WHERE path = ? AND source = ? AND tag = ?",
                                       (now, key, *view))

    def compaction_due(self, row: TxyLayerRow) -> bool:
        """Q45.7: a layer of more than ``COMPACT_SEGMENTS`` segments, or more than half of whose stored bytes
        are shots a later segment replaced."""
        if len(row.segments) > COMPACT_SEGMENTS:
            return True
        live: dict[int, int] = {}
        for entry in row.entries.values():
            live[entry.seq] = live.get(entry.seq, 0) + 1
        counts = {int(seq): (int(live_shots), int(all_shots)) for seq, live_shots, all_shots in self._conn.execute(
            "SELECT seq, live_shots, all_shots FROM txy_segments WHERE path = ? AND layer = ?",
            (self._path_key(row.path), row.layer))}
        stale = sum(size * (1 - counts[seq][0] / max(1, counts[seq][1])) for seq, (_, size) in row.segments.items()
                    if seq in counts)
        return stale > row.bytes / 2

    def compact_txy(self, path: str, layer: str, guard: SaveGuard, *, budget: int | None = None,
                    budget_set_at: float | None = None, force: bool = False) -> bool:
        """Rewrite a layer as one segment of its current shots when due (Q45.7), only if the new segment fits
        beside the old ones (counted before they are retired); otherwise it waits for a later save and never
        asks. Nothing changes if the layer changed meanwhile or the guard no longer holds. Whether it did."""
        from helab.convert import txy_layer
        self._needs_v4()
        key = self._path_key(path)
        rows = self.txy_layers(path)
        row = (rows.value or {}).get(layer)
        if row is None or not row.entries or not (force or self.compaction_due(row)):
            return False
        data = self.read_txy_shots(path, layer)
        if data.value is None:
            return False
        packed = txy_layer.pack_segment(data.value, layer=layer, tags=row.tags, precision=row.precision,
                                        problematic=[shot for shot, entry in row.entries.items() if entry.problematic],
                                        maker=self._maker_record())
        file = self.write_txy_file(packed)
        now = time.time()
        done = False
        try:
            with self.transaction():
                current = self._conn.execute("SELECT entries FROM txy_layers WHERE path = ? AND layer = ?",
                                             (key, layer)).fetchone()
                if (current is not None and self._txy_guard_holds(
                        {"generations": guard.generations, "epochs": guard.epochs}, key)
                        and json.loads(current[0]) == [entry.to_json() for _, entry in sorted(row.entries.items())]):
                    budget = self._active_budget(budget, budget_set_at)
                    self._conn.execute("SAVEPOINT txy_compact")
                    (seq,) = self._conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM txy_segments WHERE path = ? "
                                                "AND layer = ?", (key, layer)).fetchone()
                    self._conn.execute("INSERT INTO txy_segments (path, layer, seq, file, bytes, live_shots, all_shots) "
                                       "VALUES (?, ?, ?, ?, ?, ?, ?)", (key, layer, int(seq), file, self._size(file),
                                                                       len(row.entries), len(row.entries)))
                    if budget is not None and self._live() > budget:
                        self._conn.execute("ROLLBACK TO txy_compact")
                    else:
                        for (old,) in self._conn.execute("SELECT file FROM txy_segments WHERE path = ? AND layer = ? "
                                                         "AND seq != ?", (key, layer, int(seq))).fetchall():
                            self._retire(str(old), now)
                        self._conn.execute("DELETE FROM txy_segments WHERE path = ? AND layer = ? AND seq != ?",
                                           (key, layer, int(seq)))
                        entries = {shot: dataclasses.replace(entry, seq=int(seq))
                                   for shot, entry in row.entries.items()}
                        self._write_layer_row(key, layer, row.tags, entries, row.precision, self._maker_id(),
                                              row.job_seq, now)
                        done = True
                    self._conn.execute("RELEASE txy_compact")
                if not done:
                    self._retire(file, now)
        except SaveRejected:
            self._reject_txy_files([file], SaveRejected("cleared", REKEYED))
            return False
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return done

    def _maker_record(self) -> dict[str, Any]:
        """This session's maker for an ``.hlb`` header ({} in store-v3)."""
        if self.layout < store_v4.LAYOUT:
            return {}
        if self._maker is None:
            self._maker = store_v4.session_maker()
        return {"maker": self._maker["maker"], "record": self._maker["record"]}

    def mark_txy_seen(self, path: str, present: Mapping[str, Mapping[int, tuple[int, int]]], seen_at: float) -> int:
        """A full listing of ``path`` taken at ``seen_at`` found these sources: ``"raw"`` the raw files
        (``{shot: (size, mtime_ns)}``), and by layer name the TXY files of that layer's own source (``"matlab"``:
        MATLAB's; ``"helab:<hash>"``: HeLab's of that profile). An entry keyed by its raw file is checked against
        the raw files, one keyed by its TXY file against its own layer's TXY only (C-2: another profile's TXY of
        the shot is no copy of it; a layer the listing names no TXY for has none). A layer with an entry whose
        source it didn't find is an only copy (``gone_at``, Q45.6); one whose sources are all there is seen
        (``seen_at``). Each mark goes by when its
        evidence was taken (C2-10's rule, S2-2): a sighting clears a gone mark only if newer than it, and a gone
        mark needs a listing newer than the last sighting, so an older listing landing late undoes nothing.
        The layers marked gone."""
        self._needs_v4()
        key = self._path_key(path)
        gone = 0
        try:
            with self.transaction():
                for layer, entries in self._conn.execute("SELECT layer, entries FROM txy_layers WHERE path = ?",
                                                         (key,)).fetchall():
                    missing = any(entry.shot not in present.get("raw" if entry.kind == "raw" else str(layer), {})
                                  for entry in map(TxyEntry.from_json, json.loads(entries)))
                    if missing:
                        gone += self._conn.execute(
                            "UPDATE txy_layers SET gone_at = COALESCE(gone_at, ?) WHERE path = ? AND layer = ? "
                            "AND seen_at < ?", (seen_at, key, layer, seen_at)).rowcount
                    else:
                        self._conn.execute(
                            "UPDATE txy_layers SET seen_at = MAX(seen_at, ?), "
                            "gone_at = CASE WHEN gone_at IS NOT NULL AND gone_at >= ? THEN gone_at END "
                            "WHERE path = ? AND layer = ?", (seen_at, seen_at, key, layer))
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return gone

    def _remove_txy_rows(self, where: str, args: Sequence[Any], now: float) -> tuple[list[tuple[str, str]], int]:
        """Delete the layers ``where`` selects (inside a transaction), with their segments and the folders'
        views (derived: a view without its layer would be incomplete) and waiting parts; retire their files
        and bump each folder's ``txy:`` epoch: ((folder key, layer) pairs, bytes)."""
        found = [(str(key), str(layer)) for key, layer in self._conn.execute(
            f"SELECT path, layer FROM txy_layers{where}", tuple(args)).fetchall()]
        size = 0
        for key, layer in found:
            for file, bytes_ in self._conn.execute("SELECT file, bytes FROM txy_segments WHERE path = ? AND layer = ?",
                                                   (key, layer)).fetchall():
                self._retire(str(file), now)
                size += int(bytes_)
            self._conn.execute("DELETE FROM txy_segments WHERE path = ? AND layer = ?", (key, layer))
            self._conn.execute("DELETE FROM txy_layers WHERE path = ? AND layer = ?", (key, layer))
        for key in sorted({key for key, _ in found}):
            self._conn.execute("DELETE FROM txy_views WHERE path = ?", (key,))
            self._conn.execute("INSERT INTO folder_epochs (path, epoch) VALUES (?, 1) ON CONFLICT (path) "
                               "DO UPDATE SET epoch = epoch + 1", (_txy_epoch(key),))
        return found, size

    def remove_txy(self, paths: Iterable[str] | None = None) -> TxyRemoval:
        """Clear cached TXY data (the user asked: Settings › Cache, Clear all, a folder's clear): every
        folder's (bumping ``gen_txy``) or these folders' (each one's ``txy:`` epoch), so a unit already being
        saved can't bring it back. Layers, segments, views and waiting layer parts go; files are retired."""
        if self.layout < store_v4.LAYOUT:
            return TxyRemoval(None if paths is None else (), 0, 0)
        now = time.time()
        try:
            with self.transaction():
                if paths is None:
                    self._conn.execute("UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) "
                                       "WHERE key = 'gen_txy'")
                    found, size = self._remove_txy_rows("", (), now)
                    self._conn.execute("DELETE FROM txy_views")
                    self._retire_pending(" WHERE parts != '[]'", (), now)
                    return TxyRemoval(None, len(found), size)
                keys = list(dict.fromkeys(self._path_key(path) for path in paths))
                for key in keys:  # (A folder with no layers is fenced too: a unit may be on its way.)
                    self._conn.execute("INSERT INTO folder_epochs (path, epoch) VALUES (?, 1) ON CONFLICT (path) "
                                       "DO UPDATE SET epoch = epoch + 1", (_txy_epoch(key),))
                marks = ','.join('?' * len(keys)) or 'NULL'
                found, size = self._remove_txy_rows(f" WHERE path IN ({marks})", keys, now)
                self._conn.execute(f"DELETE FROM txy_views WHERE path IN ({marks})", keys)
                self._retire_pending(f" WHERE parts != '[]' AND path IN ({marks})", keys, now)
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return TxyRemoval(tuple(self._source_path(key) for key in keys), len(found), size)

    def _retire_pending(self, where: str, args: Sequence[Any], now: float) -> list[str]:
        """Delete the pending saves ``where`` selects (inside a transaction), retiring each one's file and
        its layer parts' files: their ids."""
        columns = "pending_id, file, parts" if self._pending_parts else "pending_id, file, '[]'"
        found = self._conn.execute(f"SELECT {columns} FROM pending_saves{where}", tuple(args)).fetchall()
        for _, file, parts in found:
            self._retire(str(file), now)
            for part in json.loads(parts or "[]"):
                self._retire(str(part["file"]), now)
        self._conn.execute(f"DELETE FROM pending_saves{where}", tuple(args))
        return [str(pending_id) for pending_id, _, _ in found]

    def _txy_live(self) -> int:
        if self.layout < store_v4.LAYOUT:
            return 0
        return int(self._conn.execute("SELECT COALESCE(SUM(bytes), 0) FROM txy_segments").fetchone()[0])

    def _txy_summary(self) -> dict[str, Any]:
        """store-v4's TXY layers for Settings › Cache (inside a transaction): layers, folders, shots, bytes,
        the layers that are only copies (``only_copy``) and their folders (``only_copy_folders``), their tag
        names, when one was last used."""
        summary: dict[str, Any] = {"layers": 0, "folders": 0, "shots": 0, "bytes": 0, "only_copy": 0,
                                   "only_copy_folders": 0, "only_copy_bytes": 0, "tags": {}, "last_used": None}
        if self.layout < store_v4.LAYOUT:
            return summary
        tags: dict[str, int] = {}
        folders: set[str] = set()
        only_folders: set[str] = set()
        for path, layer, layer_tags, shots, size, gone_at, last_used in self._conn.execute(
                "SELECT path, layer, tags, shots, bytes, gone_at, last_used FROM txy_layers").fetchall():
            folders.add(str(path))
            summary["layers"] += 1
            summary["shots"] += int(shots)
            summary["bytes"] += int(size)
            if gone_at is not None:
                summary["only_copy"] += 1
                summary["only_copy_bytes"] += int(size)
                only_folders.add(str(path))
            for name in json.loads(layer_tags) or (["External"] if layer == _MATLAB_LAYER else []):
                tags[str(name)] = tags.get(str(name), 0) + 1
            summary["last_used"] = max(float(last_used), summary["last_used"] or 0.0)
        summary.update(folders=len(folders), tags=tags, only_copy_folders=len(only_folders))
        return summary

    def _txy_groups(self, exclude: str | None) -> dict[str, list[tuple[str, str]]]:
        """Other folders' layers by Make room's groups (Q45.6), least recently used first (inside a
        transaction): ``rebuildable`` (HeLab layers whose every shot is raw-keyed with its raw row held),
        ``seen`` (the rest whose sources the last listing found) and ``only`` (a source gone: only copies)."""
        groups: dict[str, list[tuple[str, str]]] = {"rebuildable": [], "seen": [], "only": []}
        held: dict[str, set[tuple[int, int, int]]] = {}
        for key, layer, entries, gone_at in self._conn.execute(
                "SELECT path, layer, entries, gone_at FROM txy_layers WHERE path IS NOT ? "
                "ORDER BY last_used, path, layer", (exclude,)).fetchall():
            key = str(key)
            if gone_at is not None:
                groups["only"].append((key, str(layer)))
                continue
            if key not in held:
                held[key] = {(int(shot), int(size), int(mtime)) for shot, size, mtime in self._conn.execute(
                    "SELECT shot, size, mtime_ns FROM raw_layers WHERE path = ?", (key,))}
            parsed = list(map(TxyEntry.from_json, json.loads(entries)))
            rebuildable = str(layer).startswith(_HELAB_LAYER) and all(
                entry.kind == "raw" and (entry.shot, entry.size, entry.mtime_ns) in held[key] for entry in parsed)
            groups["rebuildable" if rebuildable else "seen"].append((key, str(layer)))
        return groups

    def _free_space(self, budget: int, exclude: str | None, *, only_copies: bool = True) -> list[Removal]:
        """Make room's and ``trim``'s one order (Q45.6, A42.2), inside a transaction: other folders' whole rows,
        least recently used first within each group, until live usage fits ``budget``: (1) datasets, then in
        store-v4 (2) HeLab layers rebuildable here, (3) layers whose sources were seen, (4) raw layers seen,
        (5) only copies: TXY layers, then raw layers. Never ``exclude`` (the folder being saved). Without
        ``only_copies`` it stops before group 5 (S2-1: only a plan that names them may take only copies)."""
        removed: list[Removal] = []
        for (other,) in self._conn.execute("SELECT path FROM datasets WHERE path IS NOT ? ORDER BY last_used, path",
                                           (exclude,)).fetchall():
            if self._live() <= budget:
                return removed
            removed.append(self.remove(("datasets",), [other], _stored_keys=True))
        if self.layout < store_v4.LAYOUT:
            return removed
        groups = self._txy_groups(exclude)

        def take_layers(group: str) -> bool:
            for key, layer in groups[group]:
                if self._live() <= budget:
                    return True
                pairs, size = self._remove_txy_rows(" WHERE path = ? AND layer = ?", (key, layer), time.time())
                named = tuple((self._source_path(path), name) for path, name in pairs)
                removed.append(Removal((), (), txy_layers=named if group == "rebuildable" else (),
                                       txy_seen=named if group == "seen" else (),
                                       txy_only=named if group == "only" else (), txy_bytes=size))
            return self._live() <= budget

        def take_raw(only_copy: bool) -> bool:
            gone = "IS NOT NULL" if only_copy else "IS NULL"
            for (other,) in self._conn.execute(
                    f"SELECT path FROM raw_layers WHERE gone_at {gone} AND path IS NOT ? GROUP BY path "
                    "ORDER BY MAX(last_used), path", (exclude,)).fetchall():
                if self._live() <= budget:
                    return True
                _, count, size = self._remove_raw_rows(f" WHERE path = ? AND gone_at {gone}", (other,), time.time())
                folder = (self._source_path(str(other)),)
                removed.append(Removal((), (), raw_paths=() if only_copy else folder,
                                       only_copy_paths=folder if only_copy else (), raw_rows=count, raw_bytes=size))
            return self._live() <= budget

        if take_layers("rebuildable") or take_layers("seen") or take_raw(False) or not only_copies:
            return removed
        if not take_layers("only"):
            take_raw(True)
        return removed

    # The user's per-folder choices for stage 2 (Q45.1, Q45.2): like ``convert_prefs``, never removed by
    # Clear all, purges or Make room; Clear folder preferences resets them ("" follows the global setting).

    def set_cache_policy(self, path: str, policy: str, set_at: float) -> dict[str, Any]:
        """Set a folder's cache policy (``raw+used``, ``raw``, ``txy``; "" follows the global one) unless a
        later choice is saved; the policy now saved."""
        self._needs_v4()
        if policy not in ("", *store_v4.POLICIES):
            raise ValueError(f"Not a cache policy: {policy!r}")
        return self._set_folder_choice("cache_policy", path, {"policy": policy}, set_at)

    def set_txy_source_pref(self, path: str, source: str, tag: str, set_at: float) -> dict[str, Any]:
        """Set a folder's TXY source (Q18.2's mode and a tag; "" follows the global one, Q45.2) unless a later
        choice is saved; the choice now saved."""
        self._needs_v4()
        from helab.utils.txy_sources import parse_list
        if source and parse_list(source, tag) is None:
            raise ValueError(f"Not a TXY source or priority list: {source!r}")  # (Q53.2: a mode, or a list's text.)
        return self._set_folder_choice("txy_source_prefs", path, {"source": source, "tag": tag if source else ""},
                                       set_at)

    def _set_folder_choice(self, table: str, path: str, values: Mapping[str, Any], set_at: float) -> dict[str, Any]:
        key = self._path_key(path)
        names = list(values)
        try:
            with self.transaction():
                row = self._conn.execute(f"SELECT {', '.join(names)}, set_at FROM {table} WHERE path = ?",
                                         (key,)).fetchone()
                cleared = float(self._meta().get("prefs_cleared_at", 0.0))
                if row is not None and float(row[-1]) > set_at:
                    return {**dict(zip(names, row[:-1])), "set_at": float(row[-1])}
                if cleared > set_at:
                    return {**{name: "" for name in names}, "set_at": cleared}
                self._conn.execute(f"INSERT OR REPLACE INTO {table} (path, {', '.join(names)}, set_at) VALUES "
                                   f"(?, {', '.join('?' * len(names))}, ?)", (key, *values.values(), set_at))
                return {**dict(values), "set_at": set_at}
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    def folder_raw(self, path: str) -> dict[str, int]:
        """A folder's raw pulses (store-v4's raw layers): ``shots``, ``bytes`` and ``only_copy`` (shots whose raw
        files were gone at the last look), for S4~1's offer; zeros in store-v3."""
        if self.layout < store_v4.LAYOUT:
            return {"shots": 0, "bytes": 0, "only_copy": 0}
        key = self._path_key(path)
        try:
            with self.transaction(write=False):
                shots, size, only = self._conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(bytes), 0), COALESCE(SUM(gone_at IS NOT NULL), 0) FROM raw_layers "
                    "WHERE path = ?", (key,)).fetchone()
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be read: {exc}") from exc
        return {"shots": int(shots), "bytes": int(size), "only_copy": int(only)}

    def read_folder_choices(self, paths: Sequence[str]) -> dict[str, Read[dict[str, Any]]]:
        """Each folder's stage 2 choices: ``policy``, ``source`` and ``tag`` ("" for none) with when each was
        set; missing if neither is set (or in store-v3)."""
        unique = list(dict.fromkeys(paths))
        if self.layout < store_v4.LAYOUT:
            return {path: _missing() for path in unique}
        keys = {path: self._path_key(path) for path in unique}
        rows: dict[str, dict[str, Any]] = {}
        try:
            with self.transaction(write=False):
                wanted = list(dict.fromkeys(keys.values()))
                for start in range(0, len(wanted), 500):
                    chunk = wanted[start:start + 500]
                    marks = ','.join('?' * len(chunk))
                    for key, policy, set_at in self._conn.execute(
                            f"SELECT path, policy, set_at FROM cache_policy WHERE path IN ({marks})", chunk):
                        rows.setdefault(str(key), {}).update(policy=str(policy), policy_set_at=float(set_at))
                    for key, source, tag, set_at in self._conn.execute(
                            f"SELECT path, source, tag, set_at FROM txy_source_prefs WHERE path IN ({marks})", chunk):
                        rows.setdefault(str(key), {}).update(source=str(source), tag=str(tag),
                                                             source_set_at=float(set_at))
        except (sqlite3.Error, StoreError) as exc:
            failure: Read[dict[str, Any]] = _error(f"Disk cache could not be read: {exc}")
            return {path: failure for path in unique}
        return {path: _found({"policy": "", "source": "", "tag": "", **rows[keys[path]]}) if keys[path] in rows
                else _missing() for path in unique}

    def _legacy_counted(self) -> int:
        """store-v3's live bytes while it is kept (Keep, or not answered: D9), as last measured
        (``meta.legacy_bytes``, ``measure_legacy``); 0 under v3, after Ignore or Clear, or with none."""
        if self.layout < store_v4.LAYOUT:
            return 0
        meta = self._meta()
        measured = meta.get("legacy_bytes")
        if (self._legacy_choice(meta) not in (None, "keep") or not isinstance(measured, dict)
                or not legacy_read_through()):
            return 0
        from helab.utils.legacy_store import present
        return int(measured.get("bytes", 0)) if present(self.legacy_root) else 0

    # Removals and cleanup

    def root_usage(self) -> dict[str, dict[str, int]]:
        """Per data root UUID: folders with cached records or data, and their datasets' bytes; its
        saved results (``results``) and their files' bytes (``result_bytes``) apart."""
        usage: dict[str, dict[str, int]] = {}
        folders: dict[str, set[str]] = {}
        try:
            with self.transaction(write=False):
                for table in (*TABLES.values(), "pending_saves"):
                    if table == "listings" and not self._listings_table:
                        continue  # (A read-only store from before listings.)
                    for path, size in self._conn.execute(
                            f"SELECT path, {'bytes' if table == 'datasets' else '0'} FROM {table} "
                            "WHERE substr(path, 1, 7) = 'root://'"):
                        identifier = str(path)[7:].partition("/")[0]
                        entry = usage.setdefault(identifier, {"folders": 0, "bytes": 0})
                        entry["bytes"] += int(size)
                        folders.setdefault(identifier, set()).add(str(path))
                if self._results_table:
                    for path, size in self._conn.execute(
                            "SELECT path, bytes FROM results WHERE substr(path, 1, 7) = 'root://'"):
                        entry = usage.setdefault(str(path)[7:].partition("/")[0], {"folders": 0, "bytes": 0})
                        entry["results"] = entry.get("results", 0) + 1
                        entry["result_bytes"] = entry.get("result_bytes", 0) + int(size)
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be read: {exc}") from exc
        for identifier, paths in folders.items():
            usage[identifier]["folders"] = len(paths)
        for entry in usage.values():
            entry.setdefault("results", 0)
            entry.setdefault("result_bytes", 0)
        return usage

    def clear_root(self, identifier: str) -> Removal:
        """Settings › Data roots › Clear cached data…: every record and dataset keyed below this
        data root (``root://<uuid>``), in one transaction. Its root epoch is bumped, so a save
        already running anywhere below it can't bring data back. ``roots``, folder flags and the
        marker stay; dataset files are retired (the sweep deletes them)."""
        top = f"root://{identifier}"
        try:
            with self.transaction():
                paths = sorted({str(path) for table in (*TABLES.values(), "pending_saves")
                                for (path,) in self._conn.execute(
                                    f"SELECT path FROM {table} WHERE path = ? OR substr(path, 1, ?) = ?",
                                    (top, len(top) + 1, top + "/"))})
                self._conn.execute("INSERT INTO folder_epochs (path, epoch) VALUES (?, 1) "
                                   "ON CONFLICT (path) DO UPDATE SET epoch = epoch + 1", (_root_epoch(top),))
                removal = self.remove(KINDS, paths, _stored_keys=True)
                if self.layout < store_v4.LAYOUT:
                    return removal
                # store-v4: its raw layers are cached data too (the root epoch fences their saves).
                keys, count, size = self._remove_raw_rows(" WHERE path = ? OR substr(path, 1, ?) = ?",
                                                          (top, len(top) + 1, top + "/"), time.time())
                # (And its TXY layers, stage 2: each folder's ``txy:`` epoch is bumped, the root's already was.)
                pairs, txy_bytes = self._remove_txy_rows(" WHERE path = ? OR substr(path, 1, ?) = ?",
                                                         (top, len(top) + 1, top + "/"), time.time())
                self._retire_pending(" WHERE parts != '[]' AND (path = ? OR substr(path, 1, ?) = ?)",
                                     (top, len(top) + 1, top + "/"), time.time())
                self._conn.execute("DELETE FROM txy_views WHERE path = ? OR substr(path, 1, ?) = ?",
                                   (top, len(top) + 1, top + "/"))
                return dataclasses.replace(removal, raw_paths=tuple(self._source_path(key) for key in keys),
                                           raw_rows=count, raw_bytes=size,
                                           txy_seen=tuple((self._source_path(key), layer) for key, layer in pairs),
                                           txy_bytes=txy_bytes)
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    def remove(self, kinds: Iterable[Kind], paths: Iterable[str] | None = None, *,
               _stored_keys: bool = False) -> Removal:
        """The one removal function: Clear, purges, trim, Make room, don't-cache, per-folder clear.

        In one transaction it deletes the rows, bumps each path's folder epoch (by
        path) or each kind's generation (by kind, which also stops a folder's first
        save still in flight), and retires dataset files, including those of
        pending saves, whose adoption would fail anyway. Internal purges pass
        ``_stored_keys`` because a stored key must not be interpreted again as
        a source path under the mount table currently in effect.
        """
        kinds = tuple(dict.fromkeys(kinds))
        selected = None if paths is None else tuple(dict.fromkeys(
            path if _stored_keys else self._path_key(path) for path in paths))
        now = time.time()
        datasets = dataset_bytes = 0
        where, args = "", cast(tuple[str, ...], ())
        try:
            with self.transaction():
                if selected is not None:
                    where = f" WHERE path IN ({','.join('?' * len(selected))})"
                    args = selected
                if "datasets" in kinds and (selected is None or selected):
                    for file, size in self._conn.execute(f"SELECT file, bytes FROM datasets{where}", args).fetchall():
                        self._retire(file, now)
                        datasets += 1
                        dataset_bytes += int(size)
                    self._retire_pending(where, args, now)
                for kind in kinds:
                    if selected is None or selected:
                        self._conn.execute(f"DELETE FROM {TABLES[kind]}{where}", args)
                    if selected is None:
                        self._conn.execute("UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) "
                                           "WHERE key = ?", (f"gen_{kind}",))
                for path in selected or ():
                    # (One row per folder in store-v3; in store-v4 only the kinds removed: cache-2.)
                    for key in self._epoch_keys(kinds, path):
                        self._conn.execute("INSERT INTO folder_epochs (path, epoch) VALUES (?, 1) "
                                           "ON CONFLICT (path) DO UPDATE SET epoch = epoch + 1", (key,))
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return Removal(kinds, None if selected is None else tuple(self._source_path(path) for path in selected),
                       datasets, dataset_bytes)

    # Budget

    def _records_bytes(self) -> int:
        """The records database's size as this connection sees it: pages in use (not free
        pages, nor the WAL file, which grows and shrinks with checkpoints, not with records)."""
        pages = self._conn.execute("PRAGMA page_count").fetchone()[0]
        free = self._conn.execute("PRAGMA freelist_count").fetchone()[0]
        page_size = self._conn.execute("PRAGMA page_size").fetchone()[0]
        return (int(pages) - int(free)) * int(page_size)

    def _live(self) -> int:
        """Live bytes: dataset and result files rows point to, plus the records database (saved
        results count toward the one disk budget, Tony 2026-10-22). Retired files and pending
        saves don't count."""
        datasets = self._conn.execute("SELECT COALESCE(SUM(bytes), 0) FROM datasets").fetchone()[0]
        # A pending save's record lives in the database too, but like its file it doesn't count.
        pending = self._conn.execute("SELECT COALESCE(SUM(LENGTH(record)), 0) FROM pending_saves").fetchone()[0]
        if self._pending_results:  # (Nor a result waiting for the user's answer.)
            pending += self._conn.execute("SELECT COALESCE(SUM(LENGTH(record) + LENGTH(guard)), 0) "
                                          "FROM pending_results").fetchone()[0]
        # (store-v4: its raw layers, and store-v3's bytes while it is kept, D9.)
        return (int(datasets) + self._result_files() + self._raw_live() + self._txy_live() + self._legacy_counted()
                + max(0, self._records_bytes() - int(pending)))

    def _result_files(self) -> int:
        if not self._results_table:
            return 0
        return int(self._conn.execute("SELECT COALESCE(SUM(bytes), 0) FROM results").fetchone()[0])

    def _result_records(self) -> int:
        """About what the results' rows take in the records database (their JSON and keys)."""
        if not self._results_table:
            return 0
        return int(self._conn.execute(
            "SELECT COALESCE(SUM(LENGTH(record) + 2 * (LENGTH(lookup) + LENGTH(family)) + 3 * LENGTH(path) + "
            f"{RESULT_ROW_BYTES}), 0) FROM results").fetchone()[0])

    def _results_live(self) -> int:
        """What saved results take of the live bytes: their files and about their rows."""
        return self._result_files() + self._result_records()

    def _dataset_bytes(self, path: str) -> int | None:
        row = self._conn.execute("SELECT bytes FROM datasets WHERE path = ?", (path,)).fetchone()
        return None if row is None else int(row[0])

    def _writes(self) -> int:
        row = self._conn.execute("SELECT value FROM meta WHERE key = 'writes'").fetchone()
        return 0 if row is None else int(row[0])

    def usage(self) -> int:
        return self.measure_usage().bytes

    def measure_usage(self) -> Usage:
        """Live usage, with when it was measured in the store's own order (:class:`Usage`)."""
        try:
            with self.transaction(write=False):
                return Usage(self._live(), self.store_id, self._writes())
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be read: {exc}") from exc

    def _active_budget(self, budget: int | None, set_at: float | None) -> int | None:
        """The budget the app set last: ``budget`` (set at ``set_at``), or a later one another
        job recorded. A job keeps the budget of its request, and a helper that started before
        the user lowered it would otherwise save over the new one. Records ``budget`` if newer;
        call inside a write transaction."""
        if budget is None or set_at is None:
            return budget
        row = self._conn.execute("SELECT value FROM meta WHERE key = 'budget'").fetchone()
        recorded = json.loads(row[0]) if row is not None else None
        if isinstance(recorded, dict) and float(recorded.get("set_at", 0)) >= set_at:
            return int(recorded["bytes"])
        self._conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('budget', ?)",
                           (_dumps({"bytes": int(budget), "set_at": float(set_at)}),))
        return budget

    def record_budget(self, budget: int, set_at: float) -> int:
        """Record the app's budget (unless a later one is recorded); the active budget."""
        active = self.lower_budget(budget, set_at, fit=False)
        assert active is not None
        return active

    def lower_budget(self, budget: int, set_at: float, *, fit: bool = True) -> int | None:
        """Record the app's budget, only if the live data fits it (``fit``); None (nothing
        recorded) if it doesn't: lowering it then needs the user's yes and a trim. Checked in
        the same transaction, so data cached since the app last looked counts."""
        try:
            with self.transaction():
                if fit and self._live() > budget:
                    return None
                return self._active_budget(budget, set_at)
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    def trim(self, budget: int, set_at: float | None = None, expected: Sequence[str] | None = None) -> Removal:
        """Remove other data in Make room's order (``_free_space``: datasets, then in store-v4 TXY layers and
        raw layers; Q45.6, A42.2) until live usage fits ``budget``, and record it as the active budget (set at
        ``set_at``). Only on the user's request (lowering the budget, after a question); never automatic.
        Only copies (group 5) go only with ``expected``, the plan the user was shown (``trim_plan``'s
        ``items``): then exactly that is removed, or nothing if the plan changed since (S2-1)."""
        try:
            with self.transaction():
                budget = self._active_budget(budget, set_at) or budget
                if expected is None:
                    # Measured after each removal: a dataset's records are freed with its file.
                    return (_combined_removal(self._free_space(budget, None, only_copies=False))
                            or Removal(("datasets",), ()))
                self._conn.execute("SAVEPOINT trim_plan")
                removal = _combined_removal(self._free_space(budget, None))
                if set(() if removal is None else _removal_items(removal)) != set(expected):
                    self._conn.execute("ROLLBACK TO trim_plan")  # (Not what the user agreed to: nothing goes.)
                    self._conn.execute("RELEASE trim_plan")
                    return Removal(("datasets",), ())
                self._conn.execute("RELEASE trim_plan")
                return removal or Removal(("datasets",), ())
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    def trim_plan(self, budget: int) -> RoomPlan:
        """What lowering the budget to ``budget`` would remove, only copies included and named (the question
        step 5 asks from it, S2-1): tried and rolled back, so it is exact. ``possible`` False when even
        removing all of it isn't enough."""
        try:
            with self.transaction():
                self._conn.execute("SAVEPOINT trim_plan")
                try:
                    removal = _combined_removal(self._free_space(budget, None))
                    fits = self._live() <= budget
                finally:
                    self._conn.execute("ROLLBACK TO trim_plan")
                    self._conn.execute("RELEASE trim_plan")
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be read: {exc}") from exc
        if removal is None:
            return RoomPlan((), 0, None, None, fits)
        return RoomPlan(tuple(removal.paths or ()), removal.dataset_bytes, None, None, fits, removal.raw_paths,
                        removal.only_copy_paths, removal.raw_bytes, removal.txy_layers, removal.txy_seen,
                        removal.txy_only, removal.txy_bytes)

    def purge_datasets(self, cutoff: float) -> Removal:
        """Remove datasets not used since ``cutoff`` (a timestamp): :meth:`purge_cached` of datasets alone."""
        return self.purge_cached(cutoff, ("datasets",))

    def purge_cached(self, cutoff: float, kinds: Iterable[str] = PURGE_KINDS) -> Removal:
        """Remove cached data of ``kinds`` (any of :data:`PURGE_KINDS`) not used since ``cutoff`` (a timestamp), in
        one transaction: ``datasets``; in store-v4 ``txy``, TXY layers with their segments and their folders' views;
        ``raw``, raw layers. Only layers whose sources were seen go: only copies stay, named only by Make room and
        Clear (A47.4, Q47.1; S3-1, Q22.6, C2-9). store-v3 has datasets only."""
        asked = set(kinds)
        if unknown := asked - set(PURGE_KINDS):
            raise ValueError(f"Unknown purge kinds: {sorted(unknown)}")
        try:
            with self.transaction():
                paths = [path for (path,) in self._conn.execute(
                    "SELECT path FROM datasets WHERE last_used < ?", (cutoff,))] if "datasets" in asked else []
                removal = (self.remove(("datasets",), paths, _stored_keys=True) if "datasets" in asked
                           else Removal((), ()))
                return self._with_layers_removed(removal, " WHERE last_used < ? AND gone_at IS NULL", (cutoff,), [],
                                                 kinds=asked)
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    def clear_folder_data(self, path: str) -> Removal:
        """A folder's Clear data cache (``invalidate``): its dataset, and in store-v4 its TXY layers and views and
        its raw layers whose sources were seen; an only copy stays unless a question names it (S3-1, C2-9).
        Bumps the folder's epoch, so a load already running (its dataset or TXY guard) can't save it back."""
        key = self._path_key(path)
        try:
            with self.transaction():
                removal = self.remove(("datasets",), [key], _stored_keys=True)
                return self._with_layers_removed(removal, " WHERE path = ? AND gone_at IS NULL", (key,), [key])
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    def _with_layers_removed(self, removal: Removal, where: str, args: Sequence[Any],
                             folders: Sequence[str], *, kinds: Collection[str] = ("raw", "txy")) -> Removal:
        """In store-v4 (inside a transaction), also remove the raw and TXY layers ``where`` selects (with the
        TXY layers' folders' views; ``kinds`` says which of the two) and every view of ``folders``; ``removal``
        with them (unchanged in store-v3)."""
        if self.layout < store_v4.LAYOUT:
            return removal
        now = time.time()
        keys, count, size = self._remove_raw_rows(where, args, now) if "raw" in kinds else ([], 0, 0)
        pairs, txy_bytes = self._remove_txy_rows(where, args, now) if "txy" in kinds else ([], 0)
        for key in folders:
            self._conn.execute("DELETE FROM txy_views WHERE path = ?", (key,))
        return dataclasses.replace(removal, raw_paths=tuple(self._source_path(key) for key in keys), raw_rows=count,
                                   raw_bytes=size,
                                   txy_seen=tuple((self._source_path(key), layer) for key, layer in pairs),
                                   txy_bytes=txy_bytes)

    def purge_records(self, cutoff: float, include_failures: bool = False) -> list[Removal]:
        """Remove folder records not checked (saved) since ``cutoff``: summaries, subfolder
        status and listings, and scan histories without failures, or all old histories with ``include_failures``."""
        removals = []
        try:
            with self.transaction():
                for kind, query in _RECORD_PURGES.items():
                    if kind == "histories" and not include_failures:
                        query += " AND json_array_length(record, '$.failures') = 0"
                    self._note_purge(kind, cutoff, include_failures)
                    paths = [path for (path,) in self._conn.execute(query, (cutoff,))]
                    if paths:
                        removals.append(self.remove((kind,), paths, _stored_keys=True))
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return removals

    def inventory(self, budget: int | None = None) -> dict[str, Any]:
        """Everything the Cache tab shows, and what its purge estimates need (see :func:`purge_estimate`)."""
        try:
            with self.transaction(write=False):
                dataset_ages = [[float(last_used), int(size)] for last_used, size in self._conn.execute(
                    "SELECT last_used, bytes FROM datasets ORDER BY last_used")]
                ram_bytes = int(self._conn.execute("SELECT COALESCE(SUM(ram_bytes), 0) FROM datasets").fetchone()[0])
                ages: dict[str, Any] = {"datasets": dataset_ages}
                for kind in ("summaries", "subtrees", "listings"):
                    ages[kind] = [float(saved_at) for (saved_at,) in self._conn.execute(
                        f"SELECT saved_at FROM {RECORD_TABLES[kind]} ORDER BY saved_at")
                    ] if kind != "listings" or self._listings_table else []
                ages["histories"] = [[float(saved_at), bool(failures)] for saved_at, failures in self._conn.execute(
                    "SELECT saved_at, json_array_length(record, '$.failures') > 0 FROM scan_histories "
                    "ORDER BY saved_at")]
                blocked = int(self._conn.execute(
                    "SELECT COUNT(*) FROM scan_histories WHERE json_extract(record, '$.blocked') = 1").fetchone()[0])
                # With what each replaces now (the folder's cached dataset), for the Save update question.
                pending = [{"pending_id": pending_id, "path": self._source_path(str(path)),
                            "reason": reason, "bytes": int(size),
                            "replaces": int(replaces), "created_at": float(created_at), "job_seq": int(job_seq)}
                           for pending_id, path, reason, size, replaces, created_at, job_seq in self._conn.execute(
                               "SELECT p.pending_id, p.path, p.reason, p.bytes + LENGTH(p.record), "
                               "COALESCE(d.bytes, 0), p.created_at, p.job_seq FROM pending_saves p "
                               "LEFT JOIN datasets d ON d.path = p.path ORDER BY p.created_at")]
                retired = [file for (file,) in self._conn.execute("SELECT file FROM retired_files")]
                known = self._known_files()
                result_ages = [[float(last_used), int(size)] for last_used, size in self._conn.execute(
                    "SELECT last_used, bytes FROM results ORDER BY last_used")] if self._results_table else []
                ages["results"] = result_ages
                if self.layout >= store_v4.LAYOUT:
                    # (store-v4: what a purge of cached data takes besides datasets, only copies left out: S3-1's
                    # purge, for its question, C2S2-2.)
                    ages["txy"] = [[float(used), int(size), str(path)] for path, used, size in self._conn.execute(
                        "SELECT path, last_used, bytes FROM txy_layers WHERE gone_at IS NULL ORDER BY last_used")]
                    ages["raw"] = [[float(used), int(size), str(path)] for path, used, size in self._conn.execute(
                        "SELECT path, last_used, bytes FROM raw_layers WHERE gone_at IS NULL ORDER BY last_used")]
                result_bytes = self._results_live()
                pending_results = self.pending_result_rows()
                live, writes = self._live(), self._writes()
                raw = self._raw_summary()
                txy = self._txy_summary()
                records_bytes = (live - sum(size for _, size in dataset_ages) - self._result_files() - raw["bytes"]
                                 - txy["bytes"] - self._legacy_counted())
                no_cache, no_auto_load = self._conn.execute(
                    "SELECT COALESCE(SUM(no_cache), 0), COALESCE(SUM(no_auto_load), 0) FROM folder_prefs").fetchone()
                prefs = {"no_cache": int(no_cache), "no_auto_load": int(no_auto_load)}
                if _has_table(self._conn, "convert_prefs"):
                    prefs["write_beside"] = int(self._conn.execute(
                        "SELECT COALESCE(SUM(write_beside), 0) FROM convert_prefs").fetchone()[0])
                deadline = self.next_deadline()
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be read: {exc}") from exc
        retired_bytes = sum(self._size_or_zero(file) for file in retired)
        orphans = [name for name in self._listed_files() if name not in known]
        legacy = self.measure_legacy() if self.layout >= store_v4.LAYOUT else None
        return {
            **({"legacy": legacy, "raw": raw, "txy": txy,
                "older_stores": older_stores(os.path.dirname(os.path.abspath(self.root)), self.layout)}
               if legacy is not None else {}),
            "layout_version": self.layout_version, "store_id": self.store_id, "read_only": self.read_only,
            "root": self.root, "usage": live, "budget": budget, "records_bytes": records_bytes,
            "datasets": {"count": len(dataset_ages), "bytes": sum(size for _, size in dataset_ages),
                         "ram_bytes": ram_bytes,
                         "last_used": dataset_ages[-1][0] if dataset_ages else None},
            # Saved results (R2): their files and rows, within ``usage``.
            "results": {"count": len(result_ages), "bytes": result_bytes,
                        "last_used": max((used for used, _ in result_ages), default=None)},
            "summaries": {"count": len(ages["summaries"])}, "subtrees": {"count": len(ages["subtrees"])},
            "listings": {"count": len(ages["listings"])},
            "histories": {"count": len(ages["histories"]), "blocked": blocked}, "prefs": prefs,
            "pending": pending, "pending_results": pending_results,
            "retired": {"count": len(retired), "bytes": retired_bytes},
            "orphans": {"count": len(orphans), "bytes": sum(self._size_or_zero(name) for name in orphans)},
            "ages": ages, "next_deadline": deadline, "checked_at": time.time(),
            **Usage(live, self.store_id, writes).event()}

    def measure_legacy(self) -> dict[str, Any]:
        """store-v3 beside this store-v4, for Settings › Cache and the budget under Keep (gap 8): whether
        it is there, the choice, and its size. Kept (Keep, or not answered): its live bytes measured
        through ``LegacyStore`` and recorded in ``meta.legacy_bytes`` with its write count (fit checks
        read that, never v3). After Ignore: the folder's bytes on disk, v3 not opened. A Clear cut short
        adds ``leftover`` (``_legacy_leftovers``) and ``leftover_bytes``."""
        from helab.utils.legacy_store import present
        meta = self._meta()
        choice = self._legacy_choice(meta)
        found: dict[str, Any] = {"present": present(self.legacy_root), "choice": choice, "bytes": 0}
        leftover = self._legacy_leftovers()
        if leftover:
            found.update({"leftover": leftover, "leftover_bytes": sum(item["bytes"] for item in leftover)})
        if not found["present"]:
            return found
        legacy = self._kept_legacy()
        if legacy is None:
            found["bytes"] = _folder_bytes(self.legacy_root)
            found["counted"] = False
            return found
        try:
            measured = {"bytes": legacy.live_bytes(), "writes": legacy.writes(), "measured_at": time.time(),
                        "v3_store_id": legacy.store_id}
        except LegacyUnavailable as exc:
            return {**found, "error": str(exc)}
        answered = meta.get("legacy_v3")
        answered_id = answered.get("v3_store_id") if isinstance(answered, dict) else None
        if choice == "keep" and answered_id and answered_id != legacy.store_id:
            found["choice"] = None  # (Kept, but another store-v3 than the one answered for: asked again, C3-3.)
        if not self.read_only:
            with contextlib.suppress(sqlite3.Error, StoreError):
                with self.transaction():
                    self._conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('legacy_bytes', ?)",
                                       (_dumps(measured),))
        return {**found, "bytes": measured["bytes"], "store_id": legacy.store_id, "counted": True}

    def set_legacy_choice(self, choice: str) -> dict[str, Any]:
        """The user's answer about store-v3 (step 6, Q19.4): ``keep`` (read for what store-v4 lacks, counted
        in the budget) or ``ignore`` (left on disk, never opened). Recorded in ``meta.legacy_v3`` with v3's
        ``store_id``, so a store-v3 an older HeLab makes again later is asked about again where that can be
        told without opening an ignored one (``_legacy_choice``, C3-3). Returns ``measure_legacy()`` under
        the new choice."""
        self._needs_v4()
        if choice not in ("keep", "ignore"):
            raise ValueError(f"Not a store-v3 choice: {choice!r}")
        legacy_id: str | None = None
        from helab.utils.legacy_store import present
        if present(self.legacy_root):
            with contextlib.suppress(LegacyUnavailable):
                with LegacyStore(self.legacy_root) as legacy:
                    legacy_id = legacy.store_id
        try:
            with self.transaction():
                self._conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('legacy_v3', ?)",
                                   (_dumps({"choice": choice, "v3_store_id": legacy_id, "set_at": time.time()}),))
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        if choice == "ignore" and self._legacy is not None:
            self._legacy.close()
            self._legacy = None
        self._legacy_tried = False
        return self.measure_legacy()

    def clear_legacy(self) -> int:
        """Remove store-v3 (the user asked: Settings › Cache's Clear…, the store-v3 question's Clear, Make
        room's Clear old stores…; Q28.5), and record the choice ``clear``; its bytes. The caller has checked
        that no other HeLab runs (``cache_locks.other_instances``, as a cache move does). The folder is first
        renamed aside, so a removal cut short never leaves a half store-v3 to read; never through a link. What
        an earlier Clear left aside (``_legacy_leftovers``: a file held open) goes too, and what is still left
        is reported by ``measure_legacy`` (C3-4); the bytes returned are those actually removed."""
        self._needs_v4()
        from helab.utils.legacy_store import present
        root = self.legacy_root
        if self._legacy is not None:
            self._legacy.close()
            self._legacy = None
        targets = [os.path.join(os.path.dirname(root), item["name"]) for item in self._legacy_leftovers()]
        if os.path.lexists(root):
            if os.path.islink(root) or not os.path.isdir(root):
                raise StoreError("store-v3 isn't a folder here: left as it is")
            aside = f"{root}{LEGACY_CLEARING}{uuid.uuid4().hex[:8]}"
            try:
                os.rename(root, aside)
            except OSError as exc:
                raise StoreError(f"store-v3 couldn't be removed ({exc}); is an older HeLab still using it?") from exc
            targets.append(aside)
        removed = 0
        for target in targets:
            before = _folder_bytes(target)
            shutil.rmtree(target, ignore_errors=True)
            removed += before - (_folder_bytes(target) if os.path.lexists(target) else 0)
        try:
            with self.transaction():
                self._conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('legacy_v3', ?)",
                                   (_dumps({"choice": "clear", "v3_store_id": None, "set_at": time.time()}),))
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        self._legacy_tried = False
        assert not present(root)
        return removed

    def _size_or_zero(self, file: str) -> int:
        try:
            return os.path.getsize(self._store_file(file))
        except OSError:
            return 0

    def _known_files(self) -> set[str]:
        """Every file a row names: datasets, pending saves, results and retired files (inside a
        transaction)."""
        known = {str(file) for (file,) in self._conn.execute(
            "SELECT file FROM datasets UNION SELECT file FROM pending_saves UNION SELECT file FROM retired_files")}
        if self._results_table:
            known.update(str(file) for (file,) in self._conn.execute("SELECT file FROM results"))
        if self._pending_results:
            known.update(str(file) for (file,) in self._conn.execute("SELECT file FROM pending_results"))
        if self.layout >= store_v4.LAYOUT:
            known.update(str(file) for (file,) in self._conn.execute("SELECT file FROM raw_layers"))
            known.update(str(file) for (file,) in self._conn.execute("SELECT file FROM txy_segments"))
        if self._pending_parts:  # (A waiting layer unit's segment files, Q45.8.)
            known.update(str(file) for (file,) in self._conn.execute(
                "SELECT json_extract(part.value, '$.file') FROM pending_saves, json_each(pending_saves.parts) AS part"))
        return known

    def _listed_files(self) -> list[str]:
        """The files in ``datasets/`` and ``results/``, by the names rows give them ([] for a folder
        that can't be listed: leftovers are only tidied up, the next sweep tries again)."""
        names: list[str] = []
        folders = [(self.datasets_dir, ""), (self.results_dir, RESULTS_DIRNAME + "/")]
        if self.layout >= store_v4.LAYOUT:  # (store-v4's raw layers and TXY segments: the same orphan rule.)
            folders.append((self.raw_dir, store_v4.RAW_DIRNAME + "/"))
            folders.append((self.txy_dir, store_v4.TXY_DIRNAME + "/"))
        for folder, prefix in folders:
            try:
                names += [prefix + name for name in os.listdir(folder)
                          if not (prefix == "" and name == RESULTS_DIRNAME)]
            except OSError:
                continue
        return names

    def next_deadline(self) -> float | None:
        """When the next sweep has something to do: a retired file's or pending save's expiry."""
        try:
            with self.transaction(write=False):
                retired = self._conn.execute("SELECT MIN(retired_at) FROM retired_files").fetchone()[0]
                pending = self._conn.execute("SELECT MIN(created_at) FROM pending_saves").fetchone()[0]
                if self._pending_results:
                    waiting = self._conn.execute("SELECT MIN(created_at) FROM pending_results").fetchone()[0]
                    if waiting is not None and (pending is None or waiting < pending):
                        pending = waiting
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be read: {exc}") from exc
        deadlines = [value for value in (None if retired is None else retired + RETIRE_GRACE,
                                         None if pending is None else pending + PENDING_MAX_AGE)
                     if value is not None]
        return min(deadlines) if deadlines else None

    def sweep(self, now: float | None = None) -> Sweep:
        """Delete retired files past their grace period, expire pending saves over an
        hour old, and delete files no row names that are over an hour old."""
        now = time.time() if now is None else now
        try:
            with self.transaction():
                expired = self._retire_pending(" WHERE created_at <= ?", (now - PENDING_MAX_AGE,), now)
                expired_results = self._conn.execute(
                    "SELECT pending_id, file FROM pending_results WHERE created_at <= ?",
                    (now - PENDING_MAX_AGE,)).fetchall() if self._pending_results else []
                for _, file in expired_results:
                    self._retire(file, now)
                self._conn.executemany("DELETE FROM pending_results WHERE pending_id = ?",
                                       [(pending_id,) for pending_id, _ in expired_results])
                due = [file for (file,) in self._conn.execute(
                    "SELECT file FROM retired_files WHERE retired_at <= ?", (now - RETIRE_GRACE,)).fetchall()]
            deleted, still_open = 0, []
            for file in due:
                try:
                    os.remove(self._store_file(file))
                    deleted += 1
                except FileNotFoundError:
                    pass
                except OSError:
                    # Windows can't delete an open file: try again on a later sweep.
                    still_open.append(file)
                    continue
                with self.transaction():
                    self._conn.execute("DELETE FROM retired_files WHERE file = ?", (file,))
            deleted += self._sweep_orphans(now)
            deadline = self.next_deadline()
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be cleaned up: {exc}") from exc
        if deadline is not None and deadline <= now:
            # Only files still open are past due: retry them shortly, not at once.
            deadline = now + RETRY_OPEN
        return Sweep(deleted, len(expired) + len(expired_results),
                     [*expired, *(pending_id for pending_id, _ in expired_results)], still_open, deadline)

    def _sweep_orphans(self, now: float) -> int:
        names = self._listed_files()
        with self.transaction(write=False):
            known = self._known_files()
        deleted = 0
        for name in names:
            if name in known:
                continue
            full = self._store_file(name)
            try:
                # Younger files may belong to a writer that hasn't committed yet.
                if os.path.getmtime(full) > now - ORPHAN_MIN_AGE:
                    continue
                os.remove(full)
                deleted += 1
            except OSError:
                continue
        return deleted


_RECORD_PURGES: dict[Kind, str] = {
    "summaries": "SELECT path FROM folder_summaries WHERE saved_at < ?",
    "subtrees": "SELECT path FROM subtrees WHERE saved_at < ?",
    "histories": "SELECT path FROM scan_histories WHERE saved_at < ?",
    "listings": "SELECT path FROM listings WHERE saved_at < ?"}


def purge_estimate(inventory: Mapping[str, Any], cutoff: float, *, datasets: bool,
                   include_failures: bool = False, kinds: Iterable[str] = PURGE_KINDS) -> dict[str, int]:
    """What a purge with this ``cutoff`` removes, from an :meth:`CacheStore.inventory`:
    ``{"datasets", "bytes"}`` for cached data of ``kinds`` (:meth:`CacheStore.purge_cached`; in store-v4 also
    ``txy_folders``, ``txy_bytes``, ``raw_folders`` and ``raw_bytes`` for those asked: layers and seen raw pulses
    not used since, only copies left out, C2S2-2, A47.4; ``datasets`` is 0 when not asked; ``bytes`` all of it),
    else rows per record kind. Uses the same comparisons as the purge, so it equals what is freed if nothing
    changed since."""
    ages = inventory["ages"]
    if datasets:
        asked = set(kinds)
        old = [size for last_used, size in ages["datasets"] if last_used < cutoff] if "datasets" in asked else []
        found = {"datasets": len(old), "bytes": sum(old)}
        for kind in ("txy", "raw"):
            if kind in ages and kind in asked:
                rows = [(size, path) for last_used, size, path in ages[kind] if last_used < cutoff]
                found[f"{kind}_folders"] = len({path for _, path in rows})
                found[f"{kind}_bytes"] = sum(size for size, _ in rows)
                found["bytes"] += found[f"{kind}_bytes"]
        return found
    return {"summaries": sum(saved_at < cutoff for saved_at in ages["summaries"]),
            "subtrees": sum(saved_at < cutoff for saved_at in ages["subtrees"]),
            "listings": sum(saved_at < cutoff for saved_at in ages.get("listings", ())),
            "histories": sum(saved_at < cutoff and (include_failures or not failures)
                             for saved_at, failures in ages["histories"])}


def results_purge_estimate(inventory: Mapping[str, Any], cutoff: float) -> dict[str, int]:
    """What a purge of saved results not shown since ``cutoff`` removes (``remove_results(cutoff=…)``),
    from an inventory: ``{"results", "bytes"}`` (their files)."""
    old = [size for last_used, size in inventory["ages"].get("results", ()) if last_used < cutoff]
    return {"results": len(old), "bytes": sum(old)}


def trim_estimate(inventory: Mapping[str, Any], budget: int) -> dict[str, int]:
    """What :meth:`CacheStore.trim` to ``budget`` removes in store-v3, from an inventory: least recently
    used datasets until usage fits. An upper bound, since each dataset's records go with it. In store-v4
    ``trim`` takes layers too: its question comes from ``CacheStore.trim_plan`` (the admin's ``trim`` with
    ``plan_only``), never from this (S2-1)."""
    usage, count, freed = int(inventory["usage"]), 0, 0
    for _, size in sorted(inventory["ages"]["datasets"]):
        if usage <= budget:
            break
        usage, count, freed = usage - int(size), count + 1, freed + int(size)
    return {"datasets": count, "bytes": freed}


def _has_raw_times(conn: sqlite3.Connection) -> bool:
    return any(row[1] == "raw_times" for row in conn.execute("PRAGMA table_info(datasets)"))


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def _wal(conn: sqlite3.Connection, busy_timeout: float) -> None:
    """A new store's switch to WAL. SQLite doesn't wait ``busy_timeout`` for it: another helper making the same
    new store holds it, and the switch says "database is locked" at once (SR-1). Skipped when it is WAL already
    (that helper made it); else tried again until ``busy_timeout``."""
    deadline = time.monotonic() + busy_timeout
    while True:
        try:
            if str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() != "wal":
                conn.execute("PRAGMA journal_mode = WAL")
            return
        except sqlite3.OperationalError as exc:
            code = getattr(exc, "sqlite_errorcode", None)
            busy = (code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) if isinstance(code, int)
                    else "locked" in str(exc) or "busy" in str(exc))
            if not busy or time.monotonic() >= deadline:
                raise
            time.sleep(0.005)


def _transient_io_error(exc: sqlite3.Error) -> bool:
    """SQLite's SQLITE_IOERR ("disk I/O error"), by its code when Python gives it, else its text."""
    code = getattr(exc, "sqlite_errorcode", None)
    if isinstance(code, int):
        return code & 0xFF == sqlite3.SQLITE_IOERR
    return "disk I/O error" in str(exc)


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring a store made by an earlier HeLab of this layout up to date, on every writable open:
    the ``folder_constants`` table (F0b), ``datasets.raw_times`` (D7; ``[]``: no raw times
    known), the ``presets`` table and the ``results`` table with its ``gen_results`` generation
    (result caching R2), and the ``listings`` table with its ``gen_listings`` generation and the
    ``mount_hints`` table (cache-only browsing C2, D1), and the ``convert_prefs`` table (TXY
    converter stage 4). ``SCHEMA`` gives a new store all of them; a store created before one is
    never created again, so without this it would lack it for good. Older HeLabs name the tables
    and columns they use, so they keep working with these (they never read or clear results).
    Checked again under the write lock: several helpers may open an old store at once, and only
    the first one changes it."""
    def missing() -> tuple[bool, bool, bool, bool, bool, bool, bool]:
        return (not _has_table(conn, "folder_constants"),
                _has_table(conn, "datasets") and not _has_raw_times(conn),
                not _has_table(conn, "presets"),
                not _has_table(conn, "results") or not _has_table(conn, "pending_results") or conn.execute(
                    "SELECT 1 FROM meta WHERE key = 'gen_results'").fetchone() is None,
                not _has_table(conn, "listings") or conn.execute(
                    "SELECT 1 FROM meta WHERE key = 'gen_listings'").fetchone() is None,
                not _has_table(conn, "mount_hints"),
                not _has_table(conn, "convert_prefs"))
    if not any(missing()):
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        constants, raw_times, presets, results, listings, hints, convert = missing()  # (Another helper may have added them meanwhile.)
        if constants:
            conn.execute("CREATE TABLE IF NOT EXISTS folder_constants "
                         "(path TEXT PRIMARY KEY, record TEXT NOT NULL, set_at REAL NOT NULL)")
        if raw_times:
            conn.execute("ALTER TABLE datasets ADD COLUMN raw_times TEXT NOT NULL DEFAULT '[]'")
        if presets:
            conn.execute("CREATE TABLE IF NOT EXISTS presets (kind TEXT NOT NULL, scope TEXT NOT NULL, "
                         "name TEXT NOT NULL, record TEXT, set_at REAL NOT NULL, PRIMARY KEY (kind, scope, name))")
        if results:
            for statement in RESULT_SCHEMA:
                conn.execute(statement)
            conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('gen_results', '0')")
        if listings:
            conn.execute("CREATE TABLE IF NOT EXISTS listings "
                         "(path TEXT PRIMARY KEY, record TEXT NOT NULL, saved_at REAL NOT NULL)")
            conn.execute("CREATE INDEX IF NOT EXISTS listings_saved_at ON listings (saved_at)")
            conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('gen_listings', '0')")
        if hints:
            conn.execute(MOUNT_HINTS_SCHEMA)
        if convert:
            conn.execute(CONVERT_PREFS_SCHEMA)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def older_stores(caches_dir: str, layout: int) -> list[dict[str, Any]]:
    """The stores of older layouts in the cache folder (store-v3 now; any ``store-v<N>`` below this one
    later), each with its folder's bytes on disk: what Make room's "Clear old stores…" offers (Q28.5),
    asked first. Nothing is opened."""
    found: list[dict[str, Any]] = []
    with contextlib.suppress(OSError):
        for entry in sorted(os.scandir(caches_dir), key=lambda item: item.name):
            name = entry.name
            if (entry.is_dir(follow_symlinks=False) and name.startswith("store-v") and name[7:].isdigit()
                    and int(name[7:]) < layout):
                found.append({"name": name, "layout": int(name[7:]), "path": entry.path,
                              "bytes": _folder_bytes(entry.path)})
    return found


def _folder_bytes(folder: str) -> int:
    """Bytes of the regular files under ``folder`` (links aren't followed)."""
    total = 0
    for top, _, names in os.walk(folder):
        for name in names:
            with contextlib.suppress(OSError):
                info = os.lstat(os.path.join(top, name))
                total += info.st_size if stat.S_ISREG(info.st_mode) else 0
    return total


def _store_format(conn: sqlite3.Connection) -> int:
    """A store-v4's ``meta.format`` (1 when not set)."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'format'").fetchone()
    return 1 if row is None else int(json.loads(row[0]))


def _layout_version(conn: sqlite3.Connection) -> int | None:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'").fetchone() is None:
        return None
    row = conn.execute("SELECT value FROM meta WHERE key = 'layout_version'").fetchone()
    return None if row is None else int(json.loads(row[0]))


def _fsync_dir(directory: str) -> None:
    """Make a rename durable where the OS allows it (not on Windows)."""
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
