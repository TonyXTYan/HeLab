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
from dataclasses import dataclass, field
import json
import math
import os
import pathlib
import sqlite3
import time
from typing import (Any, Callable, Generator, Generic, Iterable, Literal, Mapping, NotRequired, Sequence, TypeVar,
                    TypedDict, cast)
import uuid

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
DEFAULT_BUDGET = 8 << 30
# The diskcache folders of earlier versions, deleted at startup.
OLD_CACHE_DIRS = ("data_ram_cache", "status_cache", "os_file_system_cache")

Kind = Literal["datasets", "summaries", "histories", "subtrees"]
KINDS: tuple[Kind, ...] = ("datasets", "summaries", "histories", "subtrees")
RECORD_TABLES: dict[Kind, str] = {
    "summaries": "folder_summaries", "histories": "scan_histories", "subtrees": "subtrees"}
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
RESULT_FORMAT = "npz-json-1"
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
CREATE TABLE IF NOT EXISTS folder_prefs (
    path TEXT PRIMARY KEY, no_cache INTEGER NOT NULL DEFAULT 0, no_auto_load INTEGER NOT NULL DEFAULT 0,
    set_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS folder_constants (path TEXT PRIMARY KEY, record TEXT NOT NULL, set_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS presets (
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
"""


def _root_epoch(key: str) -> str | None:
    """The ``folder_epochs`` row a data root's Clear bumps, for a ``root://<uuid>/…`` key (a name
    no folder key has)."""
    return f"root-clear://{key[7:].partition('/')[0]}" if key.startswith("root://") else None


def _results_root_epoch(key: str) -> str | None:
    """The ``folder_epochs`` row a data root's Clear cached analysis bumps (its results only; Clear
    cached data's ``root-clear://`` leaves results, and their saves, alone)."""
    return f"root-results-clear://{key[7:].partition('/')[0]}" if key.startswith("root://") else None


def _results_epoch(key: str) -> str:
    """The ``folder_epochs`` row a removal of one folder's results bumps (``results:<key>``): a
    dataset removal of the folder bumps the folder's own row, which result saves don't check."""
    return f"results:{key}"


class StoreError(Exception):
    """The store can't be opened, read or written. Never means "nothing saved"."""


class StoreReadOnly(StoreError):
    """A newer HeLab wrote this store's layout; this one only reads it."""


NOT_CACHED = "Not cached: your choice"


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
    """What one removal did. ``paths`` is None for a removal by kind (every path)."""
    kinds: tuple[Kind, ...]
    paths: tuple[str, ...] | None
    datasets: int = 0
    dataset_bytes: int = 0


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
    """A saved result found: its row and data file's bytes; ``exact`` False for an outdated one."""
    row: ResultRow
    data: bytes
    exact: bool


@dataclass(frozen=True)
class ResultCount:
    """A folder's saved results (the row badge, Folder details): how many and their files' bytes,
    as of the store's ``writes``-th write transaction (newer measurements win, as for usage)."""
    count: int
    bytes: int
    store_id: str
    writes: int

    def event(self) -> dict[str, Any]:
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

    def event(self) -> dict[str, Any]:
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
    """What Make room removes for a pending save: other folders' datasets, least recently used first."""
    paths: tuple[str, ...]
    bytes: int
    oldest_last_used: float | None
    newest_last_used: float | None
    # False: the folder alone is bigger than the budget, so nothing can make room.
    possible: bool


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


def store_root(caches_dir: str) -> str:
    return os.path.join(caches_dir, STORE_DIRNAME)


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
                 root_mode: bool = False) -> None:
        busy_timeout = BUSY_TIMEOUT if busy_timeout is None else busy_timeout
        self.root = root
        self._path_key = path_key or (lambda path: path)
        self._source_path = source_path or (lambda path: path)
        self._location_key: Callable[[str], str] = lambda path: path
        # A root location's folder on this computer now, or the location itself if not mounted.
        self._location_source: Callable[[str], str] = lambda location: location
        self._expected_layout = ROOT_LAYOUT_VERSION if root_mode else LAYOUT_VERSION
        self._root_mode = root_mode
        self.datasets_dir = os.path.join(root, "datasets")
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
                self._constants_table = _has_table(self._conn, "folder_constants")
                self._presets_table = _has_table(self._conn, "presets")
                # (Nor the results table: it then has no results saved, and saves none.)
                self._results_table = _has_table(self._conn, "results")
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
            finally:
                probe.close()
            if version is not None and version > self._expected_layout:
                self.read_only = True
                return self._connect(busy_timeout, read_only=True)
            if version is not None and version < self._expected_layout:
                raise sqlite3.DatabaseError(f"unsupported layout version {version}")
        os.makedirs(self.datasets_dir, exist_ok=True)
        os.makedirs(self.results_dir, exist_ok=True)
        conn = self._connect(busy_timeout, read_only=False)
        try:
            if _layout_version(conn) is None:
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for statement in SCHEMA.split(";"):
                        if statement.strip():
                            conn.execute(statement)
                    for statement in ROOT_SCHEMA.split(";"):
                        if statement.strip():
                            conn.execute(statement)
                    defaults: dict[str, object] = {
                        "layout_version": self._expected_layout, "store_id": uuid.uuid4().hex, "created_at": time.time(),
                        **{f"gen_{kind}": 0 for kind in KINDS}, "gen_results": 0}
                    # Another helper may have created it meanwhile: keep its values.
                    conn.executemany("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                                     [(key, _dumps(value)) for key, value in defaults.items()])
                    conn.execute("COMMIT")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
            version = _layout_version(conn)
            if version != self._expected_layout:
                raise sqlite3.DatabaseError(f"unsupported layout version {version}")
            _migrate(conn)
        except BaseException:
            conn.close()
            raise
        return conn

    def close(self) -> None:
        self._conn.close()

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

    def forget_root_tree(self, locations: list[str], identifier: str) -> list[str]:
        """Its marker was deleted: forget these locations of ``identifier`` and its locations below
        them. Data rows stay with the UUID. Returns the locations forgotten."""
        with self.transaction():
            rows = [str(row[0]) for row in self._conn.execute(
                "SELECT location FROM roots WHERE uuid=?", (identifier,))]
            gone = [location for location in rows if any(
                location == top or location.startswith(top.rstrip("/") + "/") for top in locations)]
            self._conn.executemany("DELETE FROM roots WHERE location=?", [(location,) for location in gone])
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
        tables = ("folder_epochs", "folder_summaries", "scan_histories", "subtrees",
                  "folder_prefs", "folder_constants", "pending_saves", "datasets")
        timestamps = {"folder_summaries": "saved_at", "scan_histories": "saved_at",
                      "subtrees": "saved_at", "folder_prefs": "set_at", "folder_constants": "set_at",
                      "pending_saves": "created_at", "datasets": "last_used"}
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
                            if not source_wins:
                                self._conn.execute(f"DELETE FROM {table} WHERE path=?", (source,))
                                continue
                            self._conn.execute(f"DELETE FROM {table} WHERE path=?", (target,))
                        self._conn.execute(f"UPDATE {table} SET path=? WHERE path=?", (target, source))
                moved.update(self._rekey_results(old, new))
            return sorted(moved)
        except sqlite3.Error as exc:
            raise StoreError(f"Data-root subtree could not be re-keyed: {exc}") from exc

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
                return {"no_cache": no_cache, "no_auto_load": no_auto_load, "set_at": set_at}, removal
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    def clear_prefs(self, set_at: float | None = None) -> list[str]:
        """Turn every folder's flags off (the Cache tab's Folder preferences row), keeping each row's
        ``set_at`` as the time of this choice; the paths that had a flag."""
        now = time.time() if set_at is None else set_at
        try:
            with self.transaction():
                # A choice saved after this Clear (e.g. while it waited for the lock) stays.
                paths = [path for (path,) in self._conn.execute(
                    "SELECT path FROM folder_prefs WHERE (no_cache OR no_auto_load) AND set_at <= ?", (now,))]
                self._conn.execute("UPDATE folder_prefs SET no_cache = 0, no_auto_load = 0, set_at = ? "
                                   "WHERE set_at <= ?", (now, now))
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

    def read_presets(self) -> Read[list[dict[str, Any]]]:
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

    def write_presets(self, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Save these preset rows (a ``record`` of None deletes) in one transaction, each unless a
        later choice (``set_at``, e.g. in another HeLab) is saved for it; the rows saved now."""
        saved: list[dict[str, Any]] = []
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
                epochs = {path: self._epoch(path) for path in paths}
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
                if root := _root_epoch(path):
                    epochs[root] = self._epoch(root)
                meta = self._meta()
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return SaveGuard({kind: int(meta[f"gen_{kind}"]) for kind in kinds}, epochs, int(job_seq))

    def _epoch(self, path: str) -> int:
        row = self._conn.execute("SELECT epoch FROM folder_epochs WHERE path = ?", (path,)).fetchone()
        return int(row[0]) if row else 0

    def _guard_holds(self, guard: SaveGuard, kind: Kind, path: str) -> bool:
        if kind not in guard.generations or path not in guard.epochs:
            # A delayed write may have re-resolved a local mount path to a
            # different SMB share. Never replace the original keyed guard with
            # a fresh one: that would let the old outcome write to the new share.
            raise ValueError(f"The save guard doesn't cover {kind} for {path}")
        meta = self._meta()
        # A data root's Clear cached data bumps its root epoch: a guard taken before it (or one
        # without it) no longer holds for any folder below that root.
        root = _root_epoch(path)
        return (int(meta[f"gen_{kind}"]) == guard.generations[kind]
                and self._epoch(path) == guard.epochs[path]
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
        result: dict[str, Read[dict[str, Any]]] = {}
        for path in unique:
            key = self._path_key(path)
            if key not in rows:
                result[path] = _missing()
                continue
            try:
                value = json.loads(rows[key])
            except ValueError as exc:
                result[path] = _error(f"Saved {kind} record is unreadable: {exc}")
                continue
            result[path] = _found(value) if isinstance(value, dict) else _error(f"Saved {kind} record is not an object")
        return result

    def save_record(self, kind: Kind, path: str, record: Mapping[str, Any] | None, guard: SaveGuard, *,
                    saved_at: float | None = None) -> None:
        """Save (or with None, delete) one record, if ``guard`` still holds."""
        self.save_records(kind, {path: record}, guard, saved_at=saved_at)

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
                superseded = []
                for old_id, old in self._conn.execute("SELECT pending_id, file FROM pending_saves "
                                                      "WHERE path = ? AND job_seq < ?",
                                                      (path, guard.job_seq)).fetchall():
                    self._retire(old, now)
                    superseded.append(old_id)
                self._conn.execute("DELETE FROM pending_saves WHERE path = ? AND job_seq < ?", (path, guard.job_seq))
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
            self._retire(existing[0], now)
            self._conn.execute("DELETE FROM pending_saves WHERE path = ?", (path,))
        pending_id = uuid.uuid4().hex
        self._conn.execute(
            "INSERT INTO pending_saves (pending_id, path, reason, file, bytes, record, gen_datasets, epoch, "
            "job_seq, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pending_id, path, reason, file, size, _dumps(record), guard.generations["datasets"],
             guard.epochs[path], guard.job_seq, now))
        return pending_id

    def adopt_pending(self, pending_id: str, *, budget: int | None = None, budget_set_at: float | None = None,
                      make_room: bool = False, expected_room: Sequence[str] | None = None) -> AdoptResult:
        """Make a pending save the folder's dataset (Save update, or Make room).

        Raises :class:`SaveRejected` if it is gone, or (discarding it) if the folder
        was cleared or newer data was cached since its job started; nothing else is
        removed then. With a ``budget`` the fit rule is checked against current usage:
        if it doesn't fit, the save stays pending as ``over_budget`` and the result says
        what Make room would remove. With ``make_room``, least recently used **other**
        datasets are removed until it fits, in the same transaction. With ``expected_room``
        (the folders the user was told it removes), Make room removes exactly those or nothing:
        if the plan changed (e.g. a new budget), it stays pending with the new plan.
        """
        now = time.time()
        rejection: SaveRejected | None = None
        result: AdoptResult | None = None
        try:
            with self.transaction():
                row = self._conn.execute(
                    "SELECT path, file, bytes, record, gen_datasets, epoch, job_seq FROM pending_saves "
                    "WHERE pending_id = ?", (pending_id,)).fetchone()
                if row is None:
                    raise SaveRejected("gone", "This save is no longer waiting")
                path, file, size, record, generation, epoch, job_seq = row
                budget = self._active_budget(budget, budget_set_at)
                stored = self._stored_job_seq(path)
                if (int(self._meta()["gen_datasets"]) != generation or self._epoch(path) != epoch):
                    rejection = SaveRejected("cleared", "Cache was cleared before saving completed")
                elif self._no_cache(path):
                    rejection = SaveRejected("no_cache", NOT_CACHED)
                elif stored is not None and stored >= job_seq:
                    rejection = SaveRejected("newer", "Newer data is already cached")
                if rejection is not None:
                    self._retire(file, now)
                    self._conn.execute("DELETE FROM pending_saves WHERE pending_id = ?", (pending_id,))
                else:
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

    def _adopt_in_savepoint(self, pending_id: str, budget: int | None, make_room: bool, *,
                            keep: bool, expected: Sequence[str] | None = None) -> tuple[bool, Removal | None]:
        """Adopt a pending save inside a savepoint, with Make room if asked, and measure.

        The decision is made on the real result, records included. It is kept only if
        ``keep`` and it fits; otherwise everything is rolled back. Returns whether it
        fits and what Make room removed (or would remove).
        """
        path, file, size, record, job_seq = self._conn.execute(
            "SELECT path, file, bytes, record, job_seq FROM pending_saves WHERE pending_id = ?",
            (pending_id,)).fetchone()
        self._conn.execute("SAVEPOINT adopt_fit")
        try:
            self._upsert_dataset(path, file, int(size), json.loads(record), int(job_seq), time.time())
            self._conn.execute("DELETE FROM pending_saves WHERE pending_id = ?", (pending_id,))
            removed: list[Removal] = []
            if budget is not None and make_room:
                # Least recently used other folders, one at a time, until it really fits.
                others = [other for (other,) in self._conn.execute(
                    "SELECT path FROM datasets WHERE path != ? ORDER BY last_used, path", (path,))]
                for other in others:
                    if self._live() <= budget:
                        break
                    removed.append(self.remove(("datasets",), [other], _stored_keys=True))
            fits = budget is None or self._live() <= budget
            planned = {other for item in removed for other in item.paths or ()}
            if expected is not None and make_room and planned != set(expected):
                fits = False  # Not what the user agreed to remove: nothing is.
        except BaseException:
            self._conn.execute("ROLLBACK TO adopt_fit")
            self._conn.execute("RELEASE adopt_fit")
            raise
        if not (keep and fits):
            self._conn.execute("ROLLBACK TO adopt_fit")
        self._conn.execute("RELEASE adopt_fit")
        removal = None if not removed else Removal(
            ("datasets",), tuple(other for item in removed for other in item.paths or ()),
            sum(item.datasets for item in removed), sum(item.dataset_bytes for item in removed))
        return fits, removal

    def _room_plan(self, pending_id: str, budget: int) -> RoomPlan:
        """Make room, tried and rolled back: exactly what it would remove."""
        fits, removal = self._adopt_in_savepoint(pending_id, budget, True, keep=False)
        paths = () if removal is None or not fits else tuple(removal.paths or ())
        # A literal path saved while a share was unmounted can later resemble a
        # mounted path. Match stored rows through the display mapping, never re-key it.
        used = [] if not paths else [float(last_used) for key, last_used in self._conn.execute(
            "SELECT path, last_used FROM datasets") if self._source_path(str(key)) in paths]
        return RoomPlan(paths, 0 if removal is None or not fits else removal.dataset_bytes,
                        min(used, default=None), max(used, default=None), fits)

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
                row = self._conn.execute("SELECT file FROM pending_saves WHERE pending_id = ?",
                                         (pending_id,)).fetchone()
                if row is None:
                    return False
                self._retire(row[0], time.time())
                self._conn.execute("DELETE FROM pending_saves WHERE pending_id = ?", (pending_id,))
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc
        return True

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

    def read_dataset_infos(self, paths: Sequence[str]) -> dict[str, Read[DatasetInfo]]:
        """Each folder's dataset sizes and ``info``, without its fingerprint: for listings."""
        unique = list(dict.fromkeys(paths))
        keys = list(dict.fromkeys(self._path_key(path) for path in unique))
        rows: dict[str, tuple[int, int, str, float, int]] = {}
        try:
            with self.transaction(write=False):
                for start in range(0, len(keys), 500):
                    chunk = keys[start:start + 500]
                    for path, size, ram_bytes, info, last_used, source in self._conn.execute(
                            f"SELECT path, bytes, ram_bytes, info, last_used, (SELECT COALESCE(SUM("
                            f"json_extract(f.value, '$[1]')), 0) FROM json_each(fingerprint) f) FROM datasets "
                            f"WHERE path IN ({','.join('?' * len(chunk))})", chunk):
                        rows[path] = (size, ram_bytes, info, last_used, source)
        except (sqlite3.Error, StoreError) as exc:
            failure = _error(f"Disk cache could not be read: {exc}")
            return {path: failure for path in unique}
        result: dict[str, Read[DatasetInfo]] = {}
        for path in unique:
            key = self._path_key(path)
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
            raise ValueError(f"The save guard doesn't cover results for {key}")
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
                    hold: bool = True) -> ResultSave:
        """Point the row of ``path``'s result ``lookup`` at a file from :meth:`write_result_file`,
        replacing (retiring) one saved before under the same key, if ``guard`` still holds and the
        folder may be cached (``no_cache``). Within the one disk budget, measured in the same
        transaction with the row written: a save that doesn't fit isn't made (``saved`` False,
        nothing removed to make room); with ``hold`` it waits in ``pending_results`` for the user's
        answer (``pending_id``; ``label``: the plot's name, for the question), else its file is
        retired. A rejected save raises :class:`SaveRejected` and retires ``file`` too."""
        key = self._path_key(path)
        now = time.time()
        size = self._size(file)
        text = _dumps(record)
        try:
            with self.transaction():
                self._check_result_guard(guard, key)
                self._check_cacheable(key)
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
                except SaveRejected as rejected:
                    rejection = rejected
                except ValueError:  # (Its guard names the folder's old key: a nested root re-keyed it since.)
                    rejection = SaveRejected("cleared", "The folder's data root changed before saving completed")
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
            try:
                with self.transaction(write=False):
                    row = self._result_row(key, "lookup = ?", (lookup,))
                    exact = row is not None
                    if row is None and family:
                        row = self._result_row(key, "family = ? AND lookup <> ?", (family, lookup))
            except (sqlite3.Error, StoreError, ValueError) as exc:
                return _error(f"Disk cache could not be read: {exc}")
            if row is None:
                return _missing()
            try:
                with open(self._store_file(row["file"]), "rb") as handle:
                    return _found(ResultFound(row, handle.read(), exact))
            except FileNotFoundError:
                if attempt:
                    return _error("Cached result file is missing")
            except OSError as exc:
                return _error(f"Cached result file could not be read: {exc}")
        return _error("Cached result file is missing")  # (Not reached.)

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
                       cutoff: float | None = None, _stored_keys: bool = False) -> ResultRemoval:
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
                elif paths is not None:
                    keys = tuple(dict.fromkeys(path if _stored_keys else self._path_key(path) for path in paths))
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

    # Removals and cleanup

    def root_usage(self) -> dict[str, dict[str, int]]:
        """Per data root UUID: folders with cached records or data, and their datasets' bytes; its
        saved results (``results``) and their files' bytes (``result_bytes``) apart."""
        usage: dict[str, dict[str, int]] = {}
        folders: dict[str, set[str]] = {}
        try:
            with self.transaction(write=False):
                for table in (*TABLES.values(), "pending_saves"):
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
                return self.remove(KINDS, paths, _stored_keys=True)
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
                    for (file,) in self._conn.execute(f"SELECT file FROM pending_saves{where}", args).fetchall():
                        self._retire(file, now)
                    self._conn.execute(f"DELETE FROM pending_saves{where}", args)
                for kind in kinds:
                    if selected is None or selected:
                        self._conn.execute(f"DELETE FROM {TABLES[kind]}{where}", args)
                    if selected is None:
                        self._conn.execute("UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) "
                                           "WHERE key = ?", (f"gen_{kind}",))
                for path in selected or ():
                    self._conn.execute("INSERT INTO folder_epochs (path, epoch) VALUES (?, 1) "
                                       "ON CONFLICT (path) DO UPDATE SET epoch = epoch + 1", (path,))
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
        return int(datasets) + self._result_files() + max(0, self._records_bytes() - int(pending))

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

    def trim(self, budget: int, set_at: float | None = None) -> Removal:
        """Remove least recently used datasets until live usage fits ``budget``, and record it
        as the active budget (set at ``set_at``). Only on the user's request (lowering the
        budget); never automatic."""
        try:
            with self.transaction():
                budget = self._active_budget(budget, set_at) or budget
                # Measured after each removal: a dataset's records are freed with its file.
                victims: list[Removal] = []
                for (path,) in self._conn.execute("SELECT path FROM datasets ORDER BY last_used, path").fetchall():
                    if self._live() <= budget:
                        break
                    victims.append(self.remove(("datasets",), [path], _stored_keys=True))
                return Removal(("datasets",), tuple(path for item in victims for path in item.paths or ()),
                               sum(item.datasets for item in victims), sum(item.dataset_bytes for item in victims))
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    def purge_datasets(self, cutoff: float) -> Removal:
        """Remove cached data not used since ``cutoff`` (a timestamp)."""
        try:
            with self.transaction():
                paths = [path for (path,) in self._conn.execute(
                    "SELECT path FROM datasets WHERE last_used < ?", (cutoff,))]
                return self.remove(("datasets",), paths, _stored_keys=True)
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be written: {exc}") from exc

    def purge_records(self, cutoff: float, include_failures: bool = False) -> list[Removal]:
        """Remove folder records not checked (saved) since ``cutoff``: summaries and subfolder
        status, and scan histories without failures, or all old histories with ``include_failures``."""
        removals = []
        try:
            with self.transaction():
                for kind, query in _RECORD_PURGES.items():
                    if kind == "histories" and not include_failures:
                        query += " AND json_array_length(record, '$.failures') = 0"
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
                for kind in ("summaries", "subtrees"):
                    ages[kind] = [float(saved_at) for (saved_at,) in self._conn.execute(
                        f"SELECT saved_at FROM {RECORD_TABLES[kind]} ORDER BY saved_at")]
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
                result_bytes = self._results_live()
                pending_results = self.pending_result_rows()
                live, writes = self._live(), self._writes()
                records_bytes = live - sum(size for _, size in dataset_ages) - self._result_files()
                no_cache, no_auto_load = self._conn.execute(
                    "SELECT COALESCE(SUM(no_cache), 0), COALESCE(SUM(no_auto_load), 0) FROM folder_prefs").fetchone()
                prefs = {"no_cache": int(no_cache), "no_auto_load": int(no_auto_load)}
                deadline = self.next_deadline()
        except sqlite3.Error as exc:
            raise StoreError(f"Disk cache could not be read: {exc}") from exc
        retired_bytes = sum(self._size_or_zero(file) for file in retired)
        orphans = [name for name in self._listed_files() if name not in known]
        return {
            "layout_version": self.layout_version, "store_id": self.store_id, "read_only": self.read_only,
            "root": self.root, "usage": live, "budget": budget, "records_bytes": records_bytes,
            "datasets": {"count": len(dataset_ages), "bytes": sum(size for _, size in dataset_ages),
                         "ram_bytes": ram_bytes,
                         "last_used": dataset_ages[-1][0] if dataset_ages else None},
            # Saved results (R2): their files and rows, within ``usage``.
            "results": {"count": len(result_ages), "bytes": result_bytes,
                        "last_used": max((used for used, _ in result_ages), default=None)},
            "summaries": {"count": len(ages["summaries"])}, "subtrees": {"count": len(ages["subtrees"])},
            "histories": {"count": len(ages["histories"]), "blocked": blocked}, "prefs": prefs,
            "pending": pending, "pending_results": pending_results,
            "retired": {"count": len(retired), "bytes": retired_bytes},
            "orphans": {"count": len(orphans), "bytes": sum(self._size_or_zero(name) for name in orphans)},
            "ages": ages, "next_deadline": deadline, "checked_at": time.time(),
            **Usage(live, self.store_id, writes).event()}

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
        return known

    def _listed_files(self) -> list[str]:
        """The files in ``datasets/`` and ``results/``, by the names rows give them ([] for a folder
        that can't be listed: leftovers are only tidied up, the next sweep tries again)."""
        names: list[str] = []
        for folder, prefix in ((self.datasets_dir, ""), (self.results_dir, RESULTS_DIRNAME + "/")):
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
                expired = self._conn.execute("SELECT pending_id, file FROM pending_saves WHERE created_at <= ?",
                                             (now - PENDING_MAX_AGE,)).fetchall()
                for _, file in expired:
                    self._retire(file, now)
                self._conn.executemany("DELETE FROM pending_saves WHERE pending_id = ?",
                                       [(pending_id,) for pending_id, _ in expired])
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
                     [pending_id for pending_id, _ in (*expired, *expired_results)], still_open, deadline)

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
    "histories": "SELECT path FROM scan_histories WHERE saved_at < ?"}


def purge_estimate(inventory: Mapping[str, Any], cutoff: float, *, datasets: bool,
                   include_failures: bool = False) -> dict[str, int]:
    """What a purge with this ``cutoff`` removes, from an :meth:`CacheStore.inventory`:
    ``{"datasets", "bytes"}`` for cached data, else rows per record kind. Uses the
    same comparisons as the purge, so it equals what is freed if nothing changed since."""
    ages = inventory["ages"]
    if datasets:
        old = [size for last_used, size in ages["datasets"] if last_used < cutoff]
        return {"datasets": len(old), "bytes": sum(old)}
    return {"summaries": sum(saved_at < cutoff for saved_at in ages["summaries"]),
            "subtrees": sum(saved_at < cutoff for saved_at in ages["subtrees"]),
            "histories": sum(saved_at < cutoff and (include_failures or not failures)
                             for saved_at, failures in ages["histories"])}


def results_purge_estimate(inventory: Mapping[str, Any], cutoff: float) -> dict[str, int]:
    """What a purge of saved results not shown since ``cutoff`` removes (``remove_results(cutoff=…)``),
    from an inventory: ``{"results", "bytes"}`` (their files)."""
    old = [size for last_used, size in inventory["ages"].get("results", ()) if last_used < cutoff]
    return {"results": len(old), "bytes": sum(old)}


def trim_estimate(inventory: Mapping[str, Any], budget: int) -> dict[str, int]:
    """What :meth:`CacheStore.trim` to ``budget`` removes, from an inventory: least recently
    used datasets until usage fits. An upper bound, since each dataset's records go with it."""
    usage, count, freed = int(inventory["usage"]), 0, 0
    for _, size in sorted(inventory["ages"]["datasets"]):
        if usage <= budget:
            break
        usage, count, freed = usage - int(size), count + 1, freed + int(size)
    return {"datasets": count, "bytes": freed}


def _has_raw_times(conn: sqlite3.Connection) -> bool:
    return any(row[1] == "raw_times" for row in conn.execute("PRAGMA table_info(datasets)"))


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


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
    (result caching R2). ``SCHEMA`` gives a new store all of them; a store created before one is
    never created again, so without this it would lack it for good. Older HeLabs name the tables
    and columns they use, so they keep working with these (they never read or clear results).
    Checked again under the write lock: several helpers may open an old store at once, and only
    the first one changes it."""
    def missing() -> tuple[bool, bool, bool, bool]:
        return (not _has_table(conn, "folder_constants"),
                _has_table(conn, "datasets") and not _has_raw_times(conn),
                not _has_table(conn, "presets"),
                not _has_table(conn, "results") or not _has_table(conn, "pending_results") or conn.execute(
                    "SELECT 1 FROM meta WHERE key = 'gen_results'").fetchone() is None)
    if not any(missing()):
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        constants, raw_times, presets, results = missing()  # (Another helper may have added them meanwhile.)
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
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


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
