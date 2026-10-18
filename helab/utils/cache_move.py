"""Moving the disk cache folder, and recovering a move a crash interrupted (roadmap S9).

A move is recorded in ``cache-move.json`` in the per-user app folder (outside every cache)
before anything is touched, and after each step:

- rename (same disk): ``started`` → ``renamed`` → ``setting_updated``
- copy (another disk): ``started`` → ``copied`` → ``verified`` → ``setting_updated`` → ``old_deleted``

The **cutover** is the ``dir_caches`` setting naming the destination, saved and synced; the
source is deleted only after it is recorded. Recovery (:func:`recover`) checks the folders
themselves and uses the step only where they can't tell. Every action is idempotent, so a
crash during recovery is recovered the same way next time.

The pure-Python parts run in an isolated helper (check, move, cleanup, abort) or at startup;
nothing here starts Qt. ``crash`` hooks let tests stop a move after any meaningful transition.
"""
from __future__ import annotations

import errno
import json
import os
import shutil
import sqlite3
import time
from typing import Any, Callable

from helab.utils.cache_location import cache_location_problem
from helab.utils.cache_store import LAYOUT_VERSION, STORE_DIRNAME, store_root
from helab.utils.number_format import byte_size

RECORD_NAME = "cache-move.json"
RENAME, COPY = "rename", "copy"
STEPS = {RENAME: ("started", "renamed", "setting_updated"),
         COPY: ("started", "copied", "verified", "setting_updated", "old_deleted")}
# SQLite's shared-memory index is rebuilt when the database opens; it is never copied.
SKIP_SUFFIXES = ("-shm",)

Crash = Callable[[str], None]


def _no_crash(point: str) -> None:
    pass


class MoveError(Exception):
    """A move that can't go on, in plain words for the user."""


class MoveCancelled(Exception):
    pass


# The move record

def record_path(app_dir: str) -> str:
    return os.path.join(app_dir, RECORD_NAME)


def read_record(app_dir: str) -> dict[str, Any] | None:
    try:
        with open(record_path(app_dir), encoding="utf-8") as file:
            record = json.load(file)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        # Written atomically, so a record is whole or absent; anything else isn't ours.
        return None
    if not (isinstance(record, dict) and record.get("method") in STEPS
            and record.get("step") in STEPS[record["method"]]
            and all(isinstance(record.get(key), str) for key in ("from", "to", "store_id"))):
        return None
    return record


def write_record(app_dir: str, record: dict[str, Any]) -> None:
    """Atomically: a temp file, fsync, then rename over the record."""
    os.makedirs(app_dir, exist_ok=True)
    temp = record_path(app_dir) + ".tmp"
    with open(temp, "w", encoding="utf-8") as file:
        json.dump(record, file)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp, record_path(app_dir))
    _fsync_dir(app_dir)


def set_step(app_dir: str, record: dict[str, Any], step: str) -> dict[str, Any]:
    record = {**record, "step": step}
    write_record(app_dir, record)
    return record


def delete_record(app_dir: str) -> None:
    try:
        os.remove(record_path(app_dir))
    except FileNotFoundError:
        pass
    _fsync_dir(app_dir)


def _fsync_dir(path: str) -> None:
    if os.name == "nt":
        return  # Directories can't be opened for fsync on Windows; the rename is durable there.
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


# The store, read without opening it for writing

def _connect_read_only(cache_dir: str) -> sqlite3.Connection | None:
    """The store's database for reading only, or None if there is none (never created here).
    Opened normally with ``query_only``: a read-only open of a WAL database fails without its
    shared-memory file, which a copy doesn't carry."""
    database = os.path.join(store_root(cache_dir), "records.sqlite")
    if not os.path.isfile(database):
        return None
    conn = sqlite3.connect(database, timeout=5)
    conn.execute("PRAGMA query_only = 1")
    return conn


def store_id_at(cache_dir: str) -> str | None:
    """The ``store_id`` of the store in ``cache_dir`` if it holds one with this layout, else None."""
    try:
        conn = _connect_read_only(cache_dir)
        if conn is None:
            return None
        try:
            meta = {key: json.loads(value) for key, value in conn.execute(
                "SELECT key, value FROM meta WHERE key IN ('store_id', 'layout_version')")}
        finally:
            conn.close()
    except (sqlite3.Error, ValueError):
        return None
    if meta.get("layout_version") != LAYOUT_VERSION or not isinstance(meta.get("store_id"), str):
        return None
    return str(meta["store_id"])


def valid_at(cache_dir: str, store_id: str) -> bool:
    return store_id_at(cache_dir) == store_id


def verify(cache_dir: str, store_id: str) -> str:
    """Why the copy in ``cache_dir`` isn't the store ``store_id``, or "" if it is: its database
    passes ``integrity_check``, has the same id and layout, and every dataset file the
    datasets and pending saves name exists with its recorded size."""
    try:
        conn = _connect_read_only(cache_dir)
        if conn is None:
            return "the copied cache has no database"
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return "the copied database is damaged"
            files = conn.execute("SELECT file, bytes FROM datasets UNION ALL "
                                 "SELECT file, bytes FROM pending_saves").fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return f"the copied database can't be read ({exc})"
    if store_id_at(cache_dir) != store_id:
        return "the copied database is not the same cache"
    datasets = os.path.join(store_root(cache_dir), "datasets")
    for file, size in files:
        try:
            if os.path.getsize(os.path.join(datasets, file)) != int(size):
                return f"a copied data file has the wrong size ({file})"
        except OSError:
            return f"a data file is missing from the copy ({file})"
    return ""


def checkpoint(cache_dir: str) -> None:
    """Write everything committed into ``records.sqlite`` and empty the WAL, so the copy
    needs no ``-wal`` file. Every helper has stopped, so nothing else holds it."""
    database = os.path.join(store_root(cache_dir), "records.sqlite")
    if not os.path.isfile(database):
        return
    try:
        conn = sqlite3.connect(database, timeout=5)
        try:
            busy = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise MoveError(f"the cache database couldn't be prepared for copying ({exc})") from exc
    if busy:
        raise MoveError("the cache is still in use; try again in a moment")


# Checks

def folder_bytes(path: str) -> int:
    total = 0
    for folder, _, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(folder, name)).st_size
            except OSError:
                pass
    return total


def _existing(path: str) -> str:
    """``path``, or its nearest existing parent."""
    path = os.path.abspath(path)
    while not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path


def _inside(path: str, folder: str) -> bool:
    path, folder = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(folder))
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def same_disk(source: str, target: str) -> bool:
    return os.stat(source).st_dev == os.stat(_existing(target)).st_dev


def check_target(source: str, target: str, app_dir: str = "") -> dict[str, Any]:
    """Whether the cache in ``source`` can move to ``target``: ``problem`` ("" if it can, else
    why, in plain words), ``bytes`` to move, ``free`` space there and the ``method``.
    ``app_dir`` holds the move's record and locks, which must stay put: a cache folder
    containing it can't be moved."""
    size = folder_bytes(source)
    result: dict[str, Any] = {"bytes": size, "free": None, "method": "", "problem": ""}
    name = os.path.basename(os.path.normpath(target)) or target

    def refuse(problem: str) -> dict[str, Any]:
        result["problem"] = problem
        return result
    if not os.path.isabs(target):
        return refuse("Choose a full folder path.")
    if app_dir and (_inside(app_dir, source) or _inside(app_dir, target)):
        return refuse(f"The cache folder contains HeLab's own folder ({app_dir}), which can't move with it. "
                      "Move the cache by hand while HeLab is closed, or choose its folder again.")
    if _inside(target, source):
        return refuse("The new folder can't be inside the current cache folder.")
    if os.path.exists(target):
        if not os.path.isdir(target):
            return refuse(f"{target} is a file, not a folder.")
        if os.listdir(target):
            return refuse(f"'{name}' isn't empty. Choose an empty or new folder.")
    if problem := cache_location_problem(target):
        return refuse(f"'{name}' is {problem}, where the cache can't work safely.")
    parent = _existing(target)
    probe = os.path.join(parent, f".helab-probe-{os.getpid()}")
    try:
        with open(probe, "w", encoding="utf-8"):
            pass
        os.remove(probe)
    except OSError:
        return refuse(f"HeLab can't write to '{os.path.basename(parent) or parent}'.")
    method = RENAME if same_disk(source, target) else COPY
    result["method"] = method
    free = shutil.disk_usage(parent).free
    result["free"] = free
    if method == COPY and free < size:
        volume = os.path.basename(_mount(parent)) or _mount(parent)
        return refuse(f"Not enough space on '{volume}': needs {byte_size(size)}, {byte_size(free)} free.")
    return result


def _mount(path: str) -> str:
    path = os.path.abspath(path)
    while not os.path.ismount(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path


# The move (in a helper; the cutover is the app's)

def staging_path(target: str) -> str:
    """Where a copy is made before it takes the target's name: a sibling, so the final rename is
    on the same disk. Only HeLab writes there, so undoing a copy never deletes anything else."""
    parent, name = os.path.split(os.path.normpath(target))
    return os.path.join(parent, f".{name}.helab-moving")


def marker_name(move_id: str) -> str:
    return f".helab-move-{move_id}"


def owned(path: str, record: dict[str, Any]) -> bool:
    """Whether ``path`` is this move's copy: it holds the marker the move put in the staging
    folder it created. Nothing else is ever deleted as "the copy"."""
    return bool(record.get("id")) and os.path.isfile(os.path.join(path, marker_name(str(record["id"]))))


def start(source: str, target: str, app_dir: str, method: str, move_id: str = "") -> dict[str, Any]:
    """Record the move before touching anything; the store's id tells the folders apart later,
    and ``id`` this move from any other (a later move's record is never touched)."""
    if read_record(app_dir) is not None:
        raise MoveError("an earlier cache move hasn't finished (restart HeLab to finish it)")
    store_id = store_id_at(source)
    if store_id is None:
        raise MoveError("the current cache folder has no readable cache to move")
    if os.path.exists(target) and (not os.path.isdir(target) or os.listdir(target)):
        raise MoveError(f"'{os.path.basename(os.path.normpath(target))}' isn't empty anymore")
    record = {"from": source, "to": target, "method": method, "step": "started", "store_id": store_id,
              "id": move_id or os.urandom(8).hex(), "staging": staging_path(target)}
    write_record(app_dir, record)
    return record


def move(record: dict[str, Any], app_dir: str, progress: Callable[[int, int], None],
         cancelled: Callable[[], bool], crash: Crash = _no_crash) -> dict[str, Any]:
    """Rename, or checkpoint, copy and verify; returns the record at ``renamed``/``verified``.
    Raises :class:`MoveError` or :class:`MoveCancelled` before the cutover; the caller then
    calls :func:`abort`."""
    source, target = record["from"], record["to"]
    crash("started")
    if record["method"] == RENAME:
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if os.path.isdir(target):
                os.rmdir(target)  # Empty (checked): a rename needs the name free on Windows.
            os.rename(source, target)
        except OSError as exc:
            if exc.errno == errno.EXDEV:
                raise MoveError("the folders are on different disks after all; try again") from exc
            raise MoveError(f"the cache folder couldn't be renamed ({exc.strerror or exc})") from exc
        crash("rename")
        record = set_step(app_dir, record, "renamed")
        crash("renamed")
        return record
    staging = record.get("staging") or staging_path(target)
    try:
        os.makedirs(os.path.dirname(staging), exist_ok=True)
        os.mkdir(staging)  # Created by this move, exclusively; then marked as its own.
    except FileExistsError:
        raise MoveError(f"a folder is in the way ({staging}); delete it and try again") from None
    with open(os.path.join(staging, marker_name(str(record["id"]))), "w", encoding="utf-8"):
        pass
    checkpoint(source)
    _copy_tree(source, staging, progress, cancelled)
    # The copy takes the target's name only if the target is still empty (or absent).
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.isdir(target):
            os.rmdir(target)
        os.rename(staging, target)
    except OSError as exc:
        raise MoveError(f"'{os.path.basename(os.path.normpath(target))}' isn't empty anymore "
                        f"({exc.strerror or exc})") from exc
    crash("copy")
    record = set_step(app_dir, record, "copied")
    crash("copied")
    if cancelled():
        raise MoveCancelled()
    problem = verify(target, record["store_id"])
    if problem:
        raise MoveError(f"The copy failed verification: {problem}.")
    crash("verify")
    record = set_step(app_dir, record, "verified")
    crash("verified")
    return record


def _copy_tree(source: str, target: str, progress: Callable[[int, int], None], cancelled: Callable[[], bool]) -> None:
    total = folder_bytes(source)
    done = 0
    os.makedirs(target, exist_ok=True)
    for folder, dirs, files in os.walk(source):
        dirs.sort()
        destination = os.path.join(target, os.path.relpath(folder, source))
        os.makedirs(destination, exist_ok=True)
        for name in sorted(files):
            if cancelled():
                raise MoveCancelled()
            if name.endswith(SKIP_SUFFIXES):
                continue
            path = os.path.join(folder, name)
            try:
                shutil.copy2(path, os.path.join(destination, name))
            except OSError as exc:
                if exc.errno == errno.ENOSPC:
                    raise MoveError("The disk filled up while copying the cache.") from exc
                raise MoveError(f"Copying {name} failed: {exc.strerror or exc}") from exc
            done += os.lstat(path).st_size
            progress(done, total)
    _fsync_dir(target)


def abort(app_dir: str, record: dict[str, Any], *, before_cutover: bool = False) -> list[str]:
    """Undo a move before its cutover, then delete the record. A copy is deleted (its staging
    folder, or the target once it took that name: only ever HeLab's own copy); a rename is
    renamed back. ``before_cutover``: a verified copy whose setting couldn't be saved is
    discarded too. Returns folders left for the user; the record then stays for recovery."""
    if record["step"] in ("setting_updated", "old_deleted"):
        return []  # After the cutover: never undone.
    left: list[str] = []
    if record["method"] == RENAME:
        if not valid_at(record["from"], record["store_id"]) and valid_at(record["to"], record["store_id"]):
            try:
                os.rename(record["to"], record["from"])
            except OSError:
                return [record["to"]]
    else:
        steps = ("started", "copied", "verified") if before_cutover else ("started", "copied")
        if record["step"] in steps:
            left = _remove_copy(record)
    if not left:
        delete_record(app_dir)
    return left


def _remove_copy(record: dict[str, Any]) -> list[str]:
    """Delete this move's copy (the staging folder, or the target once it took that name), only
    where this move's marker shows it is the copy."""
    left: list[str] = []
    for path in (record.get("staging") or staging_path(record["to"]), record["to"]):
        if owned(path, record) and not _inside(path, record["from"]):
            left += _remove_tree(path)
    return left


def store_at(record: dict[str, Any]) -> str:
    """Which of the move's folders holds the store now ("" if neither)."""
    for path in (record["from"], record["to"]):
        if valid_at(path, record["store_id"]):
            return str(path)
    return ""


def cutover(app_dir: str, record: dict[str, Any], write_setting: Callable[[str], bool],
            crash: Crash = _no_crash) -> dict[str, Any] | None:
    """Point the setting at the destination: written and synced first, then recorded. None if
    the setting couldn't be saved (still before the cutover)."""
    if not write_setting(record["to"]):
        return None
    crash("setting")
    record = set_step(app_dir, record, "setting_updated")
    crash("setting_updated")
    return record


def undo_rename(app_dir: str, record: dict[str, Any]) -> bool:
    """A rename whose setting couldn't be saved: rename it back. False if that fails too; the
    record then stays, HeLab uses the destination this session and the next start repairs the
    setting (the store is valid at the destination only)."""
    try:
        os.rename(record["to"], record["from"])
    except OSError:
        return False
    try:
        delete_record(app_dir)
    except OSError:
        pass  # Renamed back; the next start finds the store at the source and deletes the record.
    return True


def cleanup(app_dir: str, record: dict[str, Any], crash: Crash = _no_crash) -> list[str]:
    """After the cutover: delete the old folder (copy only), then the record. Folders that
    couldn't be deleted are returned and the record stays, so the next start finishes it."""
    if record["step"] not in ("setting_updated", "old_deleted"):
        return []  # Before the cutover: nothing may be deleted, and the record is still needed.
    if record.get("id"):
        try:
            os.remove(os.path.join(record["to"], marker_name(str(record["id"]))))
        except OSError:
            pass  # A stray marker in the cache folder is harmless.
    if record["method"] == COPY and record["step"] == "setting_updated":
        left = _remove_tree(record["from"])
        crash("cleanup")
        if left:
            return left
        record = set_step(app_dir, record, "old_deleted")
        crash("old_deleted")
    delete_record(app_dir)
    return []


def _remove_tree(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    shutil.rmtree(path, ignore_errors=True)
    return [path] if os.path.exists(path) else []


# Recovery at startup, before any cache is opened

def _set_aside(app_dir: str) -> None:
    """Nothing left to recover: keep the record for the log under another name, so it no longer
    holds up the cache at every start."""
    try:
        os.replace(record_path(app_dir), os.path.join(app_dir, f"cache-move.failed-{int(time.time())}.json"))
    except OSError:
        pass


def usable_after_recovery(app_dir: str, setting: str) -> bool:
    """Whether HeLab may open the cache the setting names: no move is left to recover, or the
    setting already names the move's store (e.g. only a partial copy is left to delete)."""
    record = read_record(app_dir)
    return record is None or valid_at(setting, record["store_id"])


def recover(app_dir: str, read_setting: Callable[[], str], write_setting: Callable[[str], bool],
            crash: Crash = _no_crash) -> str:
    """Resolve a leftover move record (see the roadmap's table); what was repaired, for the user,
    or "" if there was nothing to do. The record stays if something is left for next time."""
    record = read_record(app_dir)
    if record is None:
        return ""
    source, target, store_id = record["from"], record["to"], record["store_id"]
    # A folder that is now somewhere the cache can't work (e.g. made a link into a synced
    # folder) is never opened, used or trusted: as if it held no store.
    at_from = not cache_location_problem(source) and valid_at(source, store_id)
    at_to = not cache_location_problem(target) and valid_at(target, store_id)

    def use(path: str) -> bool:
        return read_setting() == path or write_setting(path)
    if record["method"] == RENAME:
        if at_to and not at_from:
            if not use(target):
                return f"HeLab finished moving the cache to {target} but couldn't save that setting; it tries again."
            delete_record(app_dir)
            return f"An interrupted cache move to {target} was finished."
        if at_from:
            if not use(source):
                return f"An interrupted cache move was undone, but the setting couldn't be saved; it tries again."
            delete_record(app_dir)
            return f"An interrupted cache move was undone; the cache stays in {source}."
        _set_aside(app_dir)
        return (f"An interrupted cache move left no readable cache in {source} or {target}. "
                "HeLab starts a new, empty cache.")
    step = record["step"]
    if step in ("started", "copied"):
        # The copy was never verified: the source is the cache.
        if not use(source):
            return "An interrupted cache move was undone, but the setting couldn't be saved; it tries again."
        crash("recover-setting")
        left = _remove_copy(record)
        if left:
            return f"An interrupted cache move was undone. Its partial copy in {target} couldn't be deleted (safe to delete)."
        delete_record(app_dir)
        return f"An interrupted cache move was undone; the cache stays in {source}."
    if step == "old_deleted" and at_to:
        delete_record(app_dir)
        return ""
    # verified or later: the copy was checked, so the move goes forward (unless it is now unreadable).
    if not at_to:
        if at_from:
            if not use(source):
                return (f"The cache copy in {target} was unreadable; HeLab goes back to {source} but couldn't "
                        "save that setting; it tries again.")
            delete_record(app_dir)
            return f"The cache copy in {target} was unreadable; HeLab kept using {source}."
        _set_aside(app_dir)
        return f"The cache copy in {target} was unreadable and {source} is gone; HeLab starts a new, empty cache."
    if step == "verified":
        if not use(target):
            return f"HeLab finished moving the cache to {target} but couldn't save that setting; it tries again."
        crash("recover-setting")
        record = set_step(app_dir, record, "setting_updated")
        crash("recover-recorded")
    left = cleanup(app_dir, record, crash)
    if left:
        return (f"The cache now lives in {target}. The old folder {source} couldn't be fully deleted "
                "(safe to delete); HeLab tries again next time.")
    return f"An interrupted cache move to {target} was finished."


__all__ = ["COPY", "RENAME", "STORE_DIRNAME", "MoveCancelled", "MoveError", "abort", "check_target", "cleanup",
           "cutover", "move", "read_record", "recover", "start", "store_id_at", "verify", "write_record"]
