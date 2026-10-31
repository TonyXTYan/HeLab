"""Caching v2's store-v4: what layout 4 adds to ``CacheStore`` (stage 1 design addendum §3, §4, §8).

``CacheStore`` serves both layouts and takes the layout from its folder's name (``store-v3`` or
``store-v4``), so a v3 path is never opened as v4 or the reverse. Store-v4 holds every store-v3
table (``datasets`` included through stage 1: T~3), plus:

- ``makers``: one row per HeLab session (Q28.4): its id, start time and a JSON record of what made
  it (HeLab's version, commit, modified flag, the machine's random id and hostname, Python, NumPy,
  SciPy, blosc). ``datasets``, ``results`` and ``raw_layers`` rows keep their maker's id. The session
  is the GUI's run (or one ``helab convert``): its first ``store_root`` call under v4 puts the maker in
  this process's environment (``MAKER_ENV``), which the helpers it starts inherit.
- ``raw_layers``: one row per raw file (filled from step 5).
- ``meta``: ``format`` (``FORMAT``: an additive change keeps it; a store of a newer format opens read
  only, never rewritten), ``gen_raw``, ``legacy_v3`` (the store-v3 choice, step 6), ``legacy_bytes``,
  ``imported_v3``.
- **Per-kind folder epochs** (cache-2): a record kind's removal bumps ``<kind>:<key>`` only, so a purge
  of old records no longer fences a folder's dataset save (``epoch_key``).

The user's own state in store-v3 (folder flags, converter flags, constants, presets, data-root
answers, volumes, mount hints, the budget) is imported once (``import_legacy``, Q22.4), whatever the
store-v3 choice, through ``LegacyStore``.

Qt-free; standard library only (``build_info`` and NumPy/SciPy versions read lazily).
"""
from __future__ import annotations

import json
import os
import platform
import socket
import sqlite3
import sys
import time
import uuid
from typing import Any, Callable

LAYOUT = 4
DIRNAME = "store-v4"
FORMAT = 1
RAW_DIRNAME = "raw"
MAKER_ENV = "HELAB_STORE_MAKER"
MACHINE_FILE = "machine-id"

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS makers (maker TEXT PRIMARY KEY, started_at REAL NOT NULL, record TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS raw_layers ("
    "path TEXT NOT NULL, shot INTEGER NOT NULL, name TEXT NOT NULL, size INTEGER NOT NULL, "
    "mtime_ns INTEGER NOT NULL, sha256 TEXT NOT NULL, parser INTEGER NOT NULL, encoding TEXT NOT NULL, "
    "facts TEXT NOT NULL, pulses INTEGER NOT NULL, file TEXT NOT NULL, bytes INTEGER NOT NULL, "
    "seen_at REAL NOT NULL, gone_at REAL, maker TEXT NOT NULL, job_seq INTEGER NOT NULL, "
    "saved_at REAL NOT NULL, last_used REAL NOT NULL, PRIMARY KEY (path, shot))",
    "CREATE INDEX IF NOT EXISTS raw_layers_last_used ON raw_layers (last_used)",
    "CREATE INDEX IF NOT EXISTS raw_layers_file ON raw_layers (file)",
    "ALTER TABLE datasets ADD COLUMN maker TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE results ADD COLUMN maker TEXT NOT NULL DEFAULT ''",
)
META_DEFAULTS: dict[str, object] = {"format": FORMAT, "gen_raw": 0}

# The user's own state imported from store-v3 once (Q22.4): each table's columns, as both layouts have them.
IMPORTED: dict[str, tuple[str, ...]] = {
    "folder_prefs": ("path", "no_cache", "no_auto_load", "set_at"),
    "convert_prefs": ("path", "write_beside", "set_at"),
    "folder_constants": ("path", "record", "set_at"),
    "presets": ("kind", "scope", "name", "record", "set_at"),
    "roots": ("location", "uuid", "kind", "label", "first_seen", "last_seen", "verified_at", "decision"),
    "root_volumes": ("mount_path", "mount_source", "volume_id", "seen_at"),
    "mount_hints": ("mount_path", "location", "seen_at"),
}
IMPORTED_META = ("budget",)  # ({"bytes", "set_at"}: the budget the app set last.)
# The record kinds whose removal bumps only their own epoch row in v4.
_RECORD_KINDS = ("summaries", "histories", "subtrees", "listings")


def epoch_key(layout: int, kind: str, key: str) -> str:
    """The ``folder_epochs`` row a removal of ``kind`` for ``key`` bumps and a save of it checks: the
    folder's own row in store-v3 (one for every kind) and for datasets; in store-v4 ``<kind>:<key>`` for
    a record kind (cache-2)."""
    return f"{kind}:{key}" if layout >= LAYOUT and kind in _RECORD_KINDS else key


def migrate(conn: sqlite3.Connection) -> None:
    """Tables and columns added **within** layout 4 after it shipped, on every writable open (the
    ``_migrate`` rule, AGENTS.md): none yet. Each addition goes here, checked again under the write
    lock, and ``SCHEMA`` gives a new store all of them."""
    additions: list[tuple[Callable[[], bool], tuple[str, ...]]] = []
    if not any(missing() for missing, _ in additions):
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        for missing, statements in additions:
            if missing():
                for statement in statements:
                    conn.execute(statement)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


# Makers (Q28.4)

def _versions() -> dict[str, str]:
    found = {"python": platform.python_version()}
    for name in ("numpy", "scipy", "blosc"):
        try:
            module = __import__(name)
            found[name] = str(getattr(module, "__version__", "unknown"))
        except Exception:
            found[name] = "missing"
    return found


def machine_id(app_folder: str | None = None) -> str:
    """This machine's random id, made once in the app folder (``machine-id``): not its name, which the
    record keeps apart. "" when the app folder can't hold it."""
    if app_folder is None:
        app_folder = os.environ.get("HELAB_APP_DIR_OVERRIDE") or _default_app_folder()
    path = os.path.join(app_folder, MACHINE_FILE)
    try:
        with open(path, encoding="ascii") as handle:
            found = handle.read().strip()
        if len(found) == 32 and all(c in "0123456789abcdef" for c in found):
            return found
    except OSError:
        pass
    made = uuid.uuid4().hex
    try:
        os.makedirs(app_folder, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(made + "\n")
        return made
    except FileExistsError:
        return machine_id(app_folder) if os.path.getsize(path) else ""
    except OSError:
        return ""


def _default_app_folder() -> str:
    from helab.utils.constants import app_folder
    return app_folder()


def maker_record() -> dict[str, Any]:
    """What made this session's rows (Q28.4). It holds the hostname: a ``.hlb`` or result shared off this
    machine carries it."""
    from helab.build_info import get_build_info
    info = get_build_info()
    return {"helab_version": info.version, "commit": info.commit, "modified": info.dirty, "branch": info.branch,
            "frozen": bool(getattr(sys, "frozen", False)), "machine": machine_id(), "hostname": socket.gethostname(),
            "platform": sys.platform, "arch": platform.machine(), **_versions()}


def session_maker() -> dict[str, Any]:
    """This session's maker (``{"maker", "started_at", "record"}``): from the environment (the GUI's or
    ``helab convert``'s, inherited by its helpers), else made now and put there, so the helpers this
    process starts share it."""
    text = os.environ.get(MAKER_ENV)
    if text:
        try:
            found = json.loads(text)
            if (isinstance(found, dict) and isinstance(found.get("maker"), str) and found["maker"]
                    and isinstance(found.get("started_at"), (int, float)) and isinstance(found.get("record"), dict)):
                return found
        except ValueError:
            pass
    made = {"maker": uuid.uuid4().hex, "started_at": time.time(), "record": maker_record()}
    os.environ[MAKER_ENV] = json.dumps(made, separators=(",", ":"))
    return made


def ensure_maker(conn: sqlite3.Connection, maker: dict[str, Any]) -> str:
    """The maker's row (inside the caller's write transaction); its id."""
    conn.execute("INSERT OR IGNORE INTO makers (maker, started_at, record) VALUES (?, ?, ?)",
                 (str(maker["maker"]), float(maker["started_at"]),
                  json.dumps(maker["record"], separators=(",", ":"), sort_keys=True)))
    return str(maker["maker"])


# The one-time import from store-v3 (Q22.4)

def import_legacy(conn: sqlite3.Connection, legacy_root: str, now: float) -> bool:
    """Bring the user's own state from the store-v3 beside this store into it, once: the rows of
    ``IMPORTED``'s tables v4 doesn't have yet, and the budget, then ``meta.imported_v3``. Inside its own
    write transaction, checked again under the lock. False when v3 is there but couldn't be read (the
    next writable open tries again); True when done, or nothing to import (no v3)."""
    from helab.utils.legacy_store import LegacyStore, LegacyUnavailable, present
    if _imported(conn):
        return True
    legacy: LegacyStore | None = None
    rows: dict[str, list[tuple[Any, ...]]] = {}
    meta: dict[str, Any] = {}
    v3_id: str | None = None
    if present(legacy_root):
        try:
            legacy = LegacyStore(legacy_root)
            rows = {table: legacy.rows(table, columns) for table, columns in IMPORTED.items()}
            meta = {key: legacy.meta[key] for key in IMPORTED_META if key in legacy.meta}
            v3_id = legacy.store_id
        except LegacyUnavailable:
            return False
        finally:
            if legacy is not None:
                legacy.close()
    conn.execute("BEGIN IMMEDIATE")
    try:
        if not _imported(conn):
            for table, found in rows.items():
                columns = IMPORTED[table]
                conn.executemany(f"INSERT OR IGNORE INTO {table} ({', '.join(columns)}) "
                                 f"VALUES ({', '.join('?' * len(columns))})", found)
            for key, value in meta.items():
                conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)", (key, json.dumps(value)))
            conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('imported_v3', ?)",
                         (json.dumps({"v3_store_id": v3_id, "at": now,
                                      "rows": {table: len(found) for table, found in rows.items()}}),))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return True


def _imported(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM meta WHERE key = 'imported_v3'").fetchone() is not None


def legacy_choice(meta: dict[str, Any]) -> str | None:
    """The store-v3 choice in v4's ``meta`` (``keep``, ``ignore``, ``clear``), None while unanswered
    (behaving as Keep, Q22.3)."""
    value = meta.get("legacy_v3")
    choice = value.get("choice") if isinstance(value, dict) else None
    return choice if choice in ("keep", "ignore", "clear") else None
