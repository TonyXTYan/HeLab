"""HeLab's own TXY files and the index of what made them.

HeLab writes a shot's TXY as ``d_txy_helab_<tag>_<N>.txt`` (Q18.4: ``<tag>`` the profile's,
``profile.file_tag``; ``.txt`` like MATLAB's ``d_txy_forc<N>.txt``), byte for byte in MATLAB's format,
so the file carries no header. What made it is a row in one SQLite file per base (Q26.2, Q19.8),
``<base>/converted-txy/index.sqlite`` (``TxyIndex``; base the cache or the temp folder): a ``folders``
table (HeLab's folder for a source folder, by its name: the source's key and path, the TXY bytes there,
when it was last used) and a ``shots`` table (``Provenance``: the raw file's fingerprint (size, mtime,
SHA-256), the profile's name, version, tag and content hash, the backend, and the TXY's size, mtime,
SHA-256 and hit count). Never in a source folder, even when the TXY goes beside the raw files: there
the name's tag says which profile made it, and it is current while it is newer than its raw file
(``beside_stale``). Files of the untagged names of HeLab before Q18.4 (``d_txy_helab_<N>.txy``) and
the per-shot ``d_txy_helab_<tag>_<N>.json`` and ``folder.json`` of the builds before the index are
not read any more: ignored, never removed but by Settings › Cache's Clear.

**The row is written before the TXY's rename** (``txy.write_atomic``'s ``before_rename``), with the
size and mtime of the very file being renamed (a rename keeps both), so a quick check that sees
HeLab's folder changed finds the row already there, and a conversion stopped between the two leaves a
row that matches no TXY on disk: the shot is converted again. A failed write removes its row only if
it is still its own (``forget``: another conversion may have written its own since).

The index is rebuildable: missing, unreadable, busy for a reader or of another schema, it only means
shots convert again. A writer that finds it damaged (SQLite's "malformed" or "not a database") or of
a newer schema sets it aside, with its journal, as ``index-damaged-<UTC>-<8 hex>.sqlite`` (or
``index-newer-…``; ``SET_ASIDE_PATTERN``) and starts a new one (on Windows, not while another process
has it open: the conversion then fails with ``IndexUnavailable`` and is tried again later). Settings ›
Cache's Clear removes damaged ones; a newer HeLab's index, live or set aside, is never ours to clear. Journal mode DELETE (a rollback journal, SQLite's default): writes are rare and tiny (a
row per shot), each a short ``BEGIN IMMEDIATE`` transaction with a busy timeout (and tried again
where SQLite answers busy at once rather than risk a deadlock, ``_patient``), so the app's
helpers and ``helab convert`` write side by side; WAL's shared memory would gain nothing here and
leaves ``-wal``/``-shm`` files beside it. The cache folder is never on a network share
(``cache_location`` refuses one), so the index is on a local disk.

``stale`` says why a TXY no longer stands for its raw file and the profile asked for (no row, the
raw file or the TXY changed, another profile hash), so a shot is converted again when a profile
improves. Profiles with one hash convert every file alike, so the backend and the profile's name and
version are recorded but don't make a TXY stale.

Qt-free; standard library only.
"""
from __future__ import annotations

import contextlib
from dataclasses import astuple, dataclass, fields
import os
import pathlib
import re
import secrets
import sqlite3
import time
from typing import Any, Callable, Iterable, Literal, TypeVar, overload

# The tag (``profile.TAG_PATTERN``, or ``u`` and hex digits) and the shot as HeLab writes them: ASCII
# digits, no leading zeros (``txy_name``). Groups ``tag`` and ``shot``.
_NAME = r"d_txy_helab_(?P<tag>[a-z][a-z0-9]{1,15})_(?P<shot>0|[1-9][0-9]*)"
TXY_PATTERN = re.compile(rf"^{_NAME}\.txt$", re.ASCII)
# The same name without groups, for patterns that join several (``io_ops.convert.partial``).
BARE_NAME = r"d_txy_helab_[a-z][a-z0-9]{1,15}_(?:0|[1-9][0-9]*)"

INDEX_NAME = "index.sqlite"
# ``PRAGMA user_version`` of the index this HeLab writes (0: a new file).
SCHEMA = 1
# How long a statement waits for another process's transaction (each is a row or two).
BUSY_SECONDS = 10.0
# An index set aside (damaged, or of a newer schema), and its journal if it had one.
SET_ASIDE_PATTERN = re.compile(
    r"^index-(?:damaged|newer)-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\.sqlite(?:-journal|-wal|-shm)?$", re.ASCII)
_COMPANIONS = ("-journal", "-wal", "-shm")
# SQLite's primary result codes for a file that isn't a sound database (SQLITE_CORRUPT, SQLITE_NOTADB),
# and for another connection's lock (SQLITE_BUSY, SQLITE_LOCKED).
_DAMAGED_CODES = (11, 26)
_BUSY_CODES = (5, 6)
T = TypeVar("T")


def txy_name(tag: str, shot: int) -> str:
    return f"d_txy_helab_{tag}_{shot}.txt"


def parse_txy_name(name: str) -> tuple[str, int] | None:
    """A HeLab TXY name's tag and shot, or None for any other name."""
    found = TXY_PATTERN.fullmatch(name)
    return (found["tag"], int(found["shot"])) if found else None


def beside_stale(raw_mtime_ns: int, txy_mtime_ns: int) -> str | None:
    """Why a TXY beside its raw file is out of date, or None (Q18.4: no record is kept there, so a
    TXY of the profile's tag is current while it is newer than the raw file)."""
    if txy_mtime_ns <= raw_mtime_ns:
        return "the raw file is newer than the TXY"
    return None


@dataclass(frozen=True, kw_only=True)
class Provenance:
    shot: int
    raw_name: str
    raw_size: int
    raw_mtime_ns: int
    raw_sha256: str
    profile_name: str
    profile_version: int
    profile_hash: str
    profile_tag: str
    profile_calibrated: bool
    backend: str
    # Where the TXY went: "beside" (next to the raw file), "cache" or "temp"; its file name, and its
    # size and mtime as written (the temporary file's, which the rename keeps).
    output: str
    txy_name: str
    txy_size: int
    txy_mtime_ns: int
    txy_sha256: str
    hits: int
    converted_at: float
    helab_version: str
    read_seconds: float
    parse_seconds: float
    reconstruct_seconds: float
    format_seconds: float
    write_seconds: float


_FIELDS = tuple(field.name for field in fields(Provenance))
_SQL_TYPES = {"int": "INTEGER", "bool": "INTEGER", "float": "REAL", "str": "TEXT"}
_TYPES: dict[str, type | tuple[type, ...]] = {"int": int, "bool": int, "float": (int, float), "str": str}
_TABLES = (
    # HeLab's folder for a source folder (``io_ops.convert.folder_for``), by its name: which source it
    # stands for (updated when it moved), its TXY's bytes (beside ones aren't there), when last used.
    "CREATE TABLE folders (folder TEXT PRIMARY KEY, key TEXT NOT NULL, source TEXT NOT NULL,"
    " bytes INTEGER NOT NULL, last_used REAL NOT NULL)",
    "CREATE TABLE shots (folder TEXT NOT NULL, "
    + ", ".join(f"{field.name} {_SQL_TYPES[str(field.type)]} NOT NULL" for field in fields(Provenance))
    + ", PRIMARY KEY (folder, profile_tag, shot))",
)


def stale(record: Provenance | None, *, raw_size: int, raw_mtime_ns: int, profile_hash: str,
          txy: tuple[int, int] | None) -> str | None:
    """Why a shot's TXY should be made again, or None when it is current: ``txy`` is the TXY's size
    and mtime now (None: no TXY), the raw values are its file's now."""
    if txy is None:
        return "no TXY"
    if record is None:
        return "no provenance record"
    if (record.raw_size, record.raw_mtime_ns) != (raw_size, raw_mtime_ns):
        return "the raw file changed since it was converted"
    if (record.txy_size, record.txy_mtime_ns) != txy:
        return "the TXY changed since it was written"
    if record.profile_hash != profile_hash:
        return f"converted with another profile ({record.profile_name} v{record.profile_version})"
    return None


class IndexUnavailable(OSError):
    """The index can't be written now (busy past the timeout, the disk, permissions): a conversion
    then fails as a failed TXY write does, and is tried again."""


def damaged(error: sqlite3.Error) -> bool:
    """SQLite says the file isn't a sound database (not busy, not missing)."""
    code = getattr(error, "sqlite_errorcode", None)
    if isinstance(code, int):
        return code & 0xFF in _DAMAGED_CODES
    text = str(error)
    return "malformed" in text or "not a database" in text


def _busy(error: sqlite3.Error) -> bool:
    code = getattr(error, "sqlite_errorcode", None)
    if isinstance(code, int):
        return code & 0xFF in _BUSY_CODES
    return "locked" in str(error) or "busy" in str(error)


def _patient(action: Callable[[], T]) -> T:
    """``action`` (one short transaction that rolls itself back when it fails), tried again while
    another connection's lock is in the way, for up to ``BUSY_SECONDS``. SQLite waits out a lock by
    itself (the busy timeout) except where waiting could deadlock: then it answers busy at once, and
    the transaction must be tried again (seen on Windows with two writers creating the index)."""
    deadline = time.monotonic() + BUSY_SECONDS
    delay = 0.005
    while True:
        try:
            return action()
        except sqlite3.OperationalError as error:
            if not _busy(error) or time.monotonic() + delay > deadline:
                raise
        time.sleep(delay)
        delay = min(2 * delay, 0.1)


def set_aside(path: str, reason: str) -> str:
    """Rename the index at ``path`` (and its journal first, so a new index never takes it for its
    own) to ``index-<reason>-<UTC>-<8 hex>.sqlite`` beside it; returns the new name's path."""
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    aside = os.path.join(os.path.dirname(path), f"index-{reason}-{stamp}-{secrets.token_hex(4)}.sqlite")
    for suffix in _COMPANIONS:
        if os.path.lexists(path + suffix):
            os.rename(path + suffix, aside + suffix)
    os.rename(path, aside)
    return aside


def _row(values: tuple[Any, ...]) -> Provenance | None:
    """A ``shots`` row (without its folder) as a record, or None when a value isn't of its type."""
    checked: dict[str, Any] = {}
    for field, value in zip(fields(Provenance), values):
        kind = str(field.type)
        if not isinstance(value, _TYPES[kind]) or isinstance(value, bool):
            return None
        if kind == "float" and isinstance(value, int):
            value = float(value)
        checked[field.name] = bool(value) if kind == "bool" else value
    return Provenance(**checked)


class TxyIndex:
    """One base's ``converted-txy/index.sqlite``: open with ``open_index``, close after use (the
    app's helpers and ``helab convert`` each hold it only while they look or write)."""

    def __init__(self, conn: sqlite3.Connection, path: str) -> None:
        self.conn, self.path = conn, path
        self.root = os.path.dirname(path)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> TxyIndex:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # Reads (a reader's errors are the caller's: ``read_shots`` treats any as no rows).

    def shots(self, folder: str, *, tag: str = "",
              shots: Iterable[int] | None = None) -> dict[tuple[str, int], Provenance]:
        """``folder``'s rows by (tag, shot): of ``tag`` only unless "", of ``shots`` only unless None."""
        query = f"SELECT {', '.join(_FIELDS)} FROM shots WHERE folder = ?"
        arguments: list[Any] = [folder]
        if tag:
            query += " AND profile_tag = ?"
            arguments.append(tag)
        wanted = None if shots is None else set(shots)
        found: dict[tuple[str, int], Provenance] = {}
        for values in self.conn.execute(query, arguments):
            record = _row(tuple(values))
            if record is not None and (wanted is None or record.shot in wanted):
                found[(record.profile_tag, record.shot)] = record
        return found

    def folders(self) -> list[tuple[str, str, str, int, float]]:
        """Every folder's (name, key, source, bytes, last used)."""
        return [(str(row[0]), str(row[1]), str(row[2]), int(row[3]), float(row[4])) for row in self.conn.execute(
            "SELECT folder, key, source, bytes, last_used FROM folders ORDER BY folder")]

    # Writes: each a short transaction.

    def _write(self, statements: list[tuple[str, tuple[Any, ...]]]) -> int:
        """Run ``statements`` in one ``BEGIN IMMEDIATE`` transaction; returns the first's rows changed.
        A damaged index is set aside and the statements run once more in a new one; any other
        failure is ``IndexUnavailable``."""
        for attempt in range(2):
            try:
                return _patient(lambda: self._transaction(statements))
            except sqlite3.Error as error:
                if attempt or not damaged(error):
                    raise IndexUnavailable(f"HeLab's TXY index couldn't be written ({error})") from error
            self.conn.close()
            try:
                set_aside(self.path, "damaged")
            except OSError as error:
                raise IndexUnavailable(f"HeLab's TXY index is damaged and couldn't be set aside ({error})") from error
            self.conn = open_index(self.root, write=True).conn
        raise AssertionError("unreachable")

    def _transaction(self, statements: list[tuple[str, tuple[Any, ...]]]) -> int:
        changed = -1
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            for statement, arguments in statements:
                count = self.conn.execute(statement, arguments).rowcount
                changed = count if changed < 0 else changed
            self.conn.execute("COMMIT")
        except BaseException:
            if self.conn.in_transaction:
                with contextlib.suppress(sqlite3.Error):
                    self.conn.execute("ROLLBACK")
            raise
        return max(changed, 0)

    @staticmethod
    def _bytes(folder: str) -> tuple[str, tuple[Any, ...]]:
        return ("UPDATE folders SET bytes = (SELECT coalesce(sum(txy_size), 0) FROM shots"
                " WHERE folder = ?1 AND output != 'beside') WHERE folder = ?1", (folder,))

    def record(self, folder: str, key: str, source: str, record: Provenance, now: float) -> None:
        """Write ``record`` (replacing the shot's row of its tag) and the folder's row: its source
        and key as this conversion saw them, its bytes, used now."""
        columns = ", ".join(_FIELDS)
        self._write([
            ("INSERT INTO folders (folder, key, source, bytes, last_used) VALUES (?, ?, ?, 0, ?)"
             " ON CONFLICT (folder) DO UPDATE SET key = excluded.key, source = excluded.source,"
             " last_used = excluded.last_used", (folder, key, source, now)),
            (f"INSERT OR REPLACE INTO shots (folder, {columns}) VALUES ({', '.join('?' * (len(_FIELDS) + 1))})",
             (folder, *astuple(record))),
            self._bytes(folder)])

    def forget(self, folder: str, record: Provenance) -> bool:
        """Remove ``record``'s row if it is still this one (its TXY's SHA-256 and mtime): another
        conversion may have written its own since. Whether it was removed."""
        return bool(self._write([
            ("DELETE FROM shots WHERE folder = ? AND profile_tag = ? AND shot = ? AND txy_sha256 = ?"
             " AND txy_mtime_ns = ?", (folder, record.profile_tag, record.shot, record.txy_sha256,
                                       record.txy_mtime_ns)),
            self._bytes(folder)]))

    def forget_removed(self, folder: str, removed: Iterable[tuple[str, int, int]]) -> None:
        """Drop the rows of TXY removed from ``folder`` ((name, size, mtime): only rows naming that
        very file), and the folder's row once no shot of it is left (beside ones keep it)."""
        statements: list[tuple[str, tuple[Any, ...]]] = [
            ("DELETE FROM shots WHERE folder = ? AND txy_name = ? AND txy_size = ? AND txy_mtime_ns = ?"
             " AND output != 'beside'", (folder, *entry)) for entry in removed]
        self._write([*statements, self._bytes(folder),
                     ("DELETE FROM folders WHERE folder = ?1 AND NOT EXISTS (SELECT 1 FROM shots WHERE folder = ?1)",
                      (folder,))])

    def touch(self, folder: str, now: float, older: float) -> None:
        """Mark ``folder`` used now if its last use is ``older`` seconds ago or more (a load took a TXY
        from it: one small write an hour at most). One statement, its own transaction; its errors are
        the caller's (a load ignores them, and never sets the index aside)."""
        self.conn.execute("UPDATE folders SET last_used = ? WHERE folder = ? AND last_used <= ?",
                          (now, folder, now - older))


def _connect(path: str, mode: str) -> sqlite3.Connection:
    uri = pathlib.Path(os.path.abspath(path)).as_uri()
    return sqlite3.connect(f"{uri}?mode={mode}", uri=True, timeout=BUSY_SECONDS, isolation_level=None)


def _prepare(conn: sqlite3.Connection) -> int:
    """The index's schema, its tables made first in a new file (``user_version`` 0)."""
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version == 0:
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("BEGIN IMMEDIATE")
        try:
            if conn.execute("PRAGMA user_version").fetchone()[0] == 0:  # (Not made meanwhile.)
                for table in _TABLES:
                    conn.execute(table)
                conn.execute(f"PRAGMA user_version = {SCHEMA}")
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                with contextlib.suppress(sqlite3.Error):
                    conn.execute("ROLLBACK")
            raise
        version = SCHEMA
    if version == SCHEMA:
        conn.execute("SELECT count(*) FROM folders").fetchone()
    return version


@overload
def open_index(root: str, *, write: Literal[True]) -> TxyIndex: ...


@overload
def open_index(root: str, *, write: Literal[False]) -> TxyIndex | None: ...


def open_index(root: str, *, write: bool) -> TxyIndex | None:
    """The index in ``root`` (a base's ``converted-txy`` folder). A reader (``write`` False) gets None
    when there is none, or it can't be read or is of another schema. A writer gets one it can write,
    created if missing, a damaged or newer one set aside first (``set_aside``); otherwise
    ``IndexUnavailable``."""
    path = os.path.join(root, INDEX_NAME)
    if not write:
        if not os.path.isfile(path):
            return None
        conn: sqlite3.Connection | None = None
        try:
            conn = _connect(path, "rw")
            if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA:
                conn.close()
                return None
            return TxyIndex(conn, path)
        except sqlite3.Error:
            if conn is not None:
                conn.close()
            return None
    for attempt in range(2):
        try:
            os.makedirs(root, exist_ok=True)
            conn = _connect(path, "rwc")
        except (OSError, sqlite3.Error) as error:
            raise IndexUnavailable(f"HeLab's TXY index couldn't be opened ({error})") from error
        try:
            writer = conn
            version = _patient(lambda: _prepare(writer))
            if version == SCHEMA:
                return TxyIndex(conn, path)
            reason = "newer" if version > SCHEMA else "damaged"
        except sqlite3.Error as error:
            if not damaged(error):
                conn.close()
                raise IndexUnavailable(f"HeLab's TXY index couldn't be opened ({error})") from error
            reason = "damaged"
        conn.close()
        if attempt:
            break
        try:
            set_aside(path, reason)
        except OSError as error:
            raise IndexUnavailable(f"HeLab's TXY index is {reason} and couldn't be set aside ({error})") from error
    raise IndexUnavailable("HeLab's TXY index is still unusable after setting it aside")


def read_shots(root: str, folder: str, *, tag: str = "", shots: Iterable[int] | None = None,
               repair: bool = False) -> dict[tuple[str, int], Provenance]:
    """``TxyIndex.shots`` of the index in ``root``, or nothing when it can't be read (its shots then
    convert again). ``repair`` (a conversion, which writes next): one found damaged is set aside."""
    index = open_index(root, write=False)
    if index is None:
        return {}
    try:
        rows = index.shots(folder, tag=tag, shots=shots)
    except sqlite3.Error as error:
        index.close()  # (First: Windows renames no file a handle holds open.)
        if repair and damaged(error):
            with contextlib.suppress(OSError):
                set_aside(index.path, "damaged")
        return {}
    index.close()
    return rows


def index_schema(root: str) -> int | None:
    """The ``user_version`` of the index in ``root``: None when there is none or it can't be read
    (damaged, or busy); ``SCHEMA`` is this HeLab's, above it a newer HeLab's (never ours to change)."""
    path = os.path.join(root, INDEX_NAME)
    if not os.path.isfile(path):
        return None
    try:
        conn = _connect(path, "rw")
    except sqlite3.Error:
        return None
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    except sqlite3.Error:
        return None
    finally:
        conn.close()
