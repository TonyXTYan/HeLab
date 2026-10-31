"""Locks that keep other HeLab instances away from a cache move (roadmap S9).

All live in the per-user app folder, outside every cache folder:

- ``cache.lock``: held exclusively by a move from its check until its old folder is deleted,
  and by every HeLab during startup while it resolves a move record and registers itself.
- ``move.lock``: held by the helper process doing a move step (move, cleanup, abort or
  recovery), which can outlive the HeLab that started it; startup waits for it too.
- ``instances/<pid>.lock``: held by each running HeLab for its whole life.
- ``running.lock``: held by the one HeLab app running on this computer (Q39.1), for its life; a
  second start finds it held and stops. (``helab convert`` doesn't take it.)

They are OS file locks (``flock``; ``msvcrt.locking`` on Windows): exclusive, and released by
the OS when their process ends, so a crashed HeLab never leaves one stuck and no takeover is
needed. The files themselves stay. Nothing here starts Qt.
"""
from __future__ import annotations

import os
import sys
from typing import Callable

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


# Windows locks a byte range, which others then can't read: lock one far past the token.
_LOCK_OFFSET = 1 << 30


class FileLock:
    def __init__(self, path: str) -> None:
        self.path = path
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def try_lock(self, token: str = "") -> bool:
        """Take it if no process (this one included, through another ``FileLock``) holds it, and
        write ``token`` in it: who holds it, for others to check (:func:`read_token`)."""
        if self._fd is not None:
            return True
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            if sys.platform == "win32":
                os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        try:
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, token.encode())
            os.fsync(fd)
        except OSError:
            self.unlock()
            return False
        return True

    def unlock(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            if sys.platform == "win32":
                os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def locked_elsewhere(path: str) -> bool:
    """Whether another process (or another lock in this one) holds the lock at ``path``."""
    if not os.path.exists(path):
        return False
    probe = FileLock(path)
    if probe.try_lock():
        probe.unlock()
        return False
    return True


def read_token(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as file:
            return file.read()
    except OSError:
        return ""


def held_with(path: str, token: str) -> bool:
    """Whether a live process holds the lock at ``path`` with ``token`` written in it: a move
    helper checks this, so it acts only while the HeLab that asked for it still holds the cache."""
    return bool(token) and locked_elsewhere(path) and read_token(path) == token


def cache_lock(app_dir: str) -> FileLock:
    return FileLock(os.path.join(app_dir, "cache.lock"))


def move_lock(app_dir: str) -> FileLock:
    return FileLock(os.path.join(app_dir, "move.lock"))


def instances_dir(app_dir: str) -> str:
    return os.path.join(app_dir, "instances")


def instance_lock(app_dir: str) -> FileLock:
    return FileLock(os.path.join(instances_dir(app_dir), f"{os.getpid()}.lock"))


def take_running(app_dir: str) -> tuple[FileLock | None, str]:
    """This app's claim to be the one HeLab running on this computer (Q39.1), to hold for its life;
    or None and the running one's pid as it wrote it ("" if unknown). One that ended, crashed
    included, holds nothing, whatever pid its file still names."""
    lock = FileLock(os.path.join(app_dir, "running.lock"))
    if lock.try_lock(str(os.getpid())):
        return lock, ""
    return None, read_token(lock.path)


def other_instances(app_dir: str) -> list[int]:
    """Pids of other running HeLabs; the files of ones that ended are removed on the way."""
    pids: list[int] = []
    try:
        names = os.listdir(instances_dir(app_dir))
    except FileNotFoundError:
        return []
    for name in names:
        if not name.endswith(".lock") or name == f"{os.getpid()}.lock":
            continue
        path = os.path.join(instances_dir(app_dir), name)
        probe = FileLock(path)
        if not probe.try_lock():
            pids.append(int(name[:-5]) if name[:-5].isdigit() else -1)
            continue
        try:
            os.remove(path)  # Its HeLab has ended.
        except OSError:
            pass
        finally:
            probe.unlock()
    return pids


def startup(app_dir: str, run_recovery: Callable[[str], str], wait: Callable[[], None]) -> tuple[str, FileLock]:
    """Before any cache is opened: wait out a move in another HeLab (or its still-running
    helper), resolve a leftover move record (``run_recovery``, given this startup's lock token
    for its helper), and register this instance. Returns what recovery repaired ("" if
    nothing) and this instance's lock, held for the app's life."""
    lock = cache_lock(app_dir)
    token = f"startup-{os.getpid()}-{os.urandom(8).hex()}"
    while True:
        if lock.try_lock(token):
            if not locked_elsewhere(move_lock(app_dir).path):
                break
            lock.unlock()
        wait()  # "Another HeLab is moving the cache…"
    try:
        message = run_recovery(token)
        instance = instance_lock(app_dir)
        instance.try_lock()
    finally:
        lock.unlock()
    return message, instance


def lock_for_move(app_dir: str, token: str) -> tuple[FileLock | None, str]:
    """``cache.lock`` for a move (holding ``token``, its move id), or why not: another HeLab
    is running, starting or moving."""
    lock = cache_lock(app_dir)
    if not lock.try_lock(token):
        return None, "Another HeLab is starting or moving the cache. Try again in a moment."
    if locked_elsewhere(move_lock(app_dir).path):
        lock.unlock()
        return None, "The previous cache move is still finishing. Try again in a moment."
    others = other_instances(app_dir)
    if others:
        lock.unlock()
        count = len(others)
        return None, (f"Another HeLab is running ({count} window{'' if count == 1 else 's'}). "
                      "Close it before moving the cache.")
    return lock, ""
