"""HeLab's updater for a source checkout (``roadmaps/app-updates.md``, stage 2). Standard library only: it imports
nothing from HeLab, because HeLab copies this one file out of the checkout it replaces (to
``<app folder>/updates/updater-<token>.py``) and runs it with the base Python, outside the venv.

    python updater-<token>.py REQUEST.json [--check]

The request (JSON, written by ``helab.updates.launch``) names everything: the checkout, its venv, HeLab's app
folder and process, the mode (``branch``: fast-forward only to the commit the check found green, one of the
branch's own (first-parent) commits; ``releases``:
the release tag, checked to be on the repo's ``main``), the target, the tools and the relaunch command. Nothing
comes from the command line but the request's path and ``--check``.

``--check`` is the dry run, while HeLab runs: it fetches the target and prints the refusals and the plan as one
JSON line, changing nothing else. Without it, the updater:

1. takes ``update.lock`` in the app folder, with its token in it, and holds it until the code and the venv are
   as they will stay (a rollback included): a HeLab or a ``helab convert`` started meanwhile finds it and stops,
   unless it is the start this update makes (step 5); a second updater stops too;
2. opens a handle on HeLab's process (safe against pid reuse), then writes ``ready-<token>``, after which HeLab
   quits through its normal path;
3. waits for that process, then for HeLab's locks (``running.lock``, ``instances/*.lock``, ``move.lock``) and
   for every process still running from the checkout's venv (macOS and Linux: ``ps``, by the program's folder;
   Windows: each program's path, and the modules each Python loaded): **no file changes before**, and the same
   is checked again before the code moves and before the venv is swapped;
4. checks every refusal again, records the previous state (``previous.json``), stashes if asked (never drops or
   pops a stash), moves the code (``git checkout --detach <tag>`` or ``git merge --ff-only``), runs
   ``git submodule update``, and only when ``requirements.lock`` or ``setup.py`` changed builds a new venv beside
   the old one (``uv venv --relocatable``), checks it imports HeLab, and swaps it in (the old one kept for
   Restore; a ``venv`` symlink stays a symlink). The swap's renames are one step: one that fails undoes those
   before it;
5. starts HeLab again, detached, with ``HELAB_UPDATE_TOKEN``, and waits for its started mark; a HeLab that exits
   before marking its start is rolled back (code and venv), once its helpers have gone too, and the old one
   started. A slow one is never killed.

Any refusal or failure leaves the previous version in place and starts it again (unless the old HeLab never
quit); ``last.json`` and the log say what happened, and the next HeLab shows it (the new one, on the start it
concerns: it waits for this outcome after writing its mark). ``action: restore`` goes back to ``previous.json``'s commit and venv
the same way.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    import msvcrt
else:
    import fcntl
    import select

BRANCH = "branch"
RELEASES = "releases"
UPDATE = "update"
RESTORE = "restore"
# Seconds: for HeLab to quit (it may be in its quit window, finishing saves), then for its helpers and locks, and
# for the new HeLab to mark its start.
TIMEOUTS = {"helab": 1800.0, "others": 120.0, "started": 180.0, "ready": 15.0}
POLL = 0.25
# What makes the venv be rebuilt (Q65.3, Q~5): a new lock, or new entry points or package data.
REBUILD_FILES = ("requirements.lock", "setup.py")
# Q~8 (a): a successful update that rebuilt the venv deletes the venv kept before the one it keeps. False keeps
# every older one (renamed ``<venv>.previous-<UTC>``) until deleted by hand.
DELETE_OLDER_VENV = True
_LOCK_OFFSET = 1 << 30  # (cache_locks: Windows locks a byte range far past the token.)
UPDATE_LOCK = "update.lock"  # (cache_locks.UPDATE_LOCK: in the app folder.)
GITHUB_REMOTE = re.compile(r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
                           r"(?P<owner>[A-Za-z0-9-]+)/(?P<name>[A-Za-z0-9._-]+?)(?:\.git)?/?")
SHA = re.compile(r"[0-9a-f]{40,64}")
TAG = re.compile(r"v[0-9A-Za-z.+-]+")
# Windows: the updater runs under pythonw.exe (no console), so each console child (git, uv, python) would open a
# console window of its own.
NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


class Refused(Exception):
    """A reason not to update, said as is to the person who asked."""


class Failed(Exception):
    """The update started but couldn't finish: rolled back."""


# -- The request ---------------------------------------------------------------------------------------

@dataclass
class Job:
    token: str
    action: str
    checkout: Path
    venv: Path  # As HeLab sees it (sys.prefix); a symlink stays one.
    app_dir: Path
    pid: int
    mode: str
    repository: str
    branch: str
    tag: str
    target: str
    stash: bool
    git: list[str]
    uv: list[str]
    python: str  # The base interpreter (``uv venv --python``).
    relaunch: list[str]
    timeouts: dict[str, float] = field(default_factory=lambda: dict(TIMEOUTS))

    @property
    def updates(self) -> Path:
        return self.app_dir / "updates"


def _strings(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) and all(isinstance(i, str) for i in value) else []


def read_job(path: Path) -> Job:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("the request isn't an object")
    timeouts = dict(TIMEOUTS)
    for key, value in (data.get("timeouts") or {}).items():
        if key in timeouts and isinstance(value, (int, float)):
            timeouts[key] = float(value)
    job = Job(token=str(data["token"]), action=str(data.get("action", UPDATE)), checkout=Path(str(data["checkout"])),
              venv=Path(str(data["venv"])), app_dir=Path(str(data["app_dir"])), pid=int(data["pid"]),
              mode=str(data.get("mode", "")), repository=str(data.get("repository", "")),
              branch=str(data.get("branch", "")), tag=str(data.get("tag", "")), target=str(data.get("target", "")),
              stash=bool(data.get("stash", False)), git=_strings(data.get("git")) or ["git"],
              uv=_strings(data.get("uv")), python=str(data.get("python", "")),
              relaunch=_strings(data.get("relaunch")), timeouts=timeouts)
    if not re.fullmatch(r"[0-9a-f]{8,64}", job.token):
        raise ValueError("bad token")
    if job.action not in (UPDATE, RESTORE):
        raise ValueError(f"unknown action {job.action!r}")
    return job


def _run(command: list[str], *, timeout: float, cwd: Path | None = None,
         env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Every program the updater runs and waits for: its output read as UTF-8 (never the Windows code page, so
    no decoding error), no console window, no input."""
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, cwd=cwd, env=env, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)


class Log:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, text: str) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self.path.open("a", encoding="utf-8") as file:
                file.write(f"{stamp} {text}\n")
        except OSError:
            pass


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# -- Where it may run ----------------------------------------------------------------------------------

def guard(job: Job) -> None:
    """Under HeLab's tests (``HELAB_TEST_SOURCE_GUARD``): only folders below the test's own root."""
    if not os.environ.get("HELAB_TEST_SOURCE_GUARD"):
        return
    root = os.environ.get("HELAB_UPDATER_TEST_ROOT", "")
    if not root:
        raise Refused("Under tests, the updater needs HELAB_UPDATER_TEST_ROOT.")
    base = Path(root).resolve()
    for path in (job.checkout, job.app_dir, job.venv):
        try:
            path.resolve().relative_to(base)
        except ValueError:
            raise Refused(f"Under tests, the updater only works below {base}: not {path}.") from None


def ssh_session(env: dict[str, str] | os._Environ[str]) -> bool:
    return any(env.get(name) for name in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"))


def elevated() -> bool:
    if os.environ.get("HELAB_TEST_SOURCE_GUARD") and os.environ.get("HELAB_UPDATER_TEST_ELEVATED") is not None:
        return os.environ["HELAB_UPDATER_TEST_ELEVATED"] == "1"  # (CI's Windows runners run elevated.)
    if sys.platform == "win32":
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except OSError:
            return False
    return os.geteuid() == 0


# -- Locks and processes -------------------------------------------------------------------------------

def lock_held(path: Path) -> bool:
    """Whether a process holds HeLab's OS lock at ``path`` (``cache_locks.locked_elsewhere``)."""
    if not path.exists():
        return False
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        return True
    try:
        if sys.platform == "win32":
            os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError:
                return True
            os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


class UpdateLock:
    """``<app folder>/update.lock``, held with this run's token written in it while HeLab's code and venv change.

    HeLab's start and ``helab convert`` look at it once they hold their own lock (``cache_locks.update_in_progress``)
    and stop, unless they are the start this update makes (their ``HELAB_UPDATE_TOKEN`` is the token in it). The
    updater takes it first and only then waits for their locks to be free, so whichever comes second sees the
    other. The same OS lock as HeLab's (``cache_locks.FileLock``: ``flock``; on Windows a byte far past the token,
    which stays readable): the OS frees it when this process ends, however it ends."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd = -1

    def take(self, token: str, seconds: float = 3.0) -> bool:
        """Whether it is held now. Tried for ``seconds``: a HeLab looking at it holds it for an instant."""
        deadline = time.monotonic() + seconds
        while not self._try(token):
            if time.monotonic() > deadline:
                return False
            time.sleep(0.05)
        return True

    def _try(self, token: str) -> bool:
        if self._fd >= 0:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
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
            self.release()
            return False
        return True

    def release(self) -> None:
        fd, self._fd = self._fd, -1
        if fd < 0:
            return
        try:
            if sys.platform == "win32":
                os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            os.close(fd)


def helab_locks(app_dir: Path, own_pid: int | None) -> list[str]:
    """HeLab's locks still held, but ``own_pid``'s (the HeLab that asked, while it runs: ``--check``)."""
    held = []
    if own_pid is None and lock_held(app_dir / "running.lock"):
        held.append("HeLab is still running")
    if lock_held(app_dir / "move.lock"):
        held.append("a cache move's helper is still running")
    instances = app_dir / "instances"
    for path in sorted(instances.glob("*.lock")) if instances.is_dir() else []:
        if own_pid is not None and path.name == f"{own_pid}.lock":
            continue
        if lock_held(path):
            held.append(f"another HeLab (a helab convert, process {path.stem}) is running")
    return held


class ProcessHandle:
    """A handle on a process that stays true to it if its pid is reused: Windows ``OpenProcess``, macOS a
    kqueue ``NOTE_EXIT``, Linux ``pidfd_open``; elsewhere polling."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self._handle: Any = None
        self._fd = -1
        self._kqueue: Any = None
        self.gone = False
        if sys.platform == "win32":
            synchronize = 0x00100000
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.restype = wintypes.HANDLE
            self._handle = kernel.OpenProcess(synchronize, False, pid)
            self.gone = not self._handle
        elif hasattr(os, "pidfd_open"):
            try:
                self._fd = getattr(os, "pidfd_open")(pid)
            except OSError:
                self.gone = True
        elif sys.platform == "darwin":
            self._kqueue = select.kqueue()
            event = select.kevent(pid, filter=select.KQ_FILTER_PROC, flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                                  fflags=select.KQ_NOTE_EXIT)
            try:
                self._kqueue.control([event], 0, 0)
            except OSError:
                self.gone = True
        else:
            self.gone = not _alive(pid)

    def wait(self, seconds: float) -> bool:
        """Whether it has exited, waiting at most ``seconds``."""
        if self.gone:
            return True
        if sys.platform == "win32":
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            self.gone = kernel.WaitForSingleObject(self._handle, int(seconds * 1000)) == 0
        elif self._fd >= 0:
            ready, _, _ = select.select([self._fd], [], [], seconds)
            self.gone = bool(ready)
        elif self._kqueue is not None:
            self.gone = bool(self._kqueue.control(None, 1, seconds))
        else:
            deadline = time.monotonic() + seconds
            while _alive(self.pid) and time.monotonic() < deadline:
                time.sleep(POLL)
            self.gone = not _alive(self.pid)
        return self.gone

    def close(self) -> None:
        if sys.platform == "win32" and self._handle:
            ctypes.WinDLL("kernel32").CloseHandle(self._handle)
        if self._fd >= 0:
            os.close(self._fd)
        if self._kqueue is not None:
            self._kqueue.close()


def _alive(pid: int) -> bool:
    if sys.platform == "win32":
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a)) == os.path.normcase(str(b))


def _under(path: str, folders: list[str]) -> bool:
    lowered = os.path.normcase(path)
    return any(lowered.startswith(os.path.normcase(folder) + os.sep) or lowered == os.path.normcase(folder)
               for folder in folders)


def running_from(job: Job) -> list[str]:
    """Processes still running HeLab's code from the checkout's venv (helpers, a second HeLab), but this one."""
    folders = sorted({str(job.venv), str(job.venv.resolve())})
    found: list[str] = []
    if sys.platform == "win32":
        return _windows_images(folders + [str(job.checkout), str(job.checkout.resolve())])
    try:
        # -ww: procps (Linux) cuts a piped listing to 80 columns, which would hide a helper's venv path.
        listing = _processes(["ps", "-A", "-ww", "-o", "pid=,command="])
        # macOS: a venv made from a framework Python (python.org's, Homebrew's, CI's) re-execs as ``Python.app``,
        # so its command line no longer names the venv; its environment does (``__PYVENV_LAUNCHER__``, set by the
        # venv's stub). Read with -E (this user's processes), matched only, never shown or logged.
        environments = _processes(["ps", "-A", "-ww", "-E", "-o", "pid=,command="]) if sys.platform == "darwin" else {}
    except (OSError, subprocess.SubprocessError):
        return ["the process list couldn't be read (ps)"]
    places = sorted(set(folders) | {str(job.checkout), str(job.checkout.resolve())})
    launchers = [f"{LAUNCHER_ENV}={folder.rstrip(os.sep)}{os.sep}" for folder in folders]
    # (As for the plain match, a process counts when its command names HeLab: a helper re-exec'd as Python.app still
    # runs ``-m helab.io_helper``; a REPL, Jupyter or pytest run from the venv doesn't hold up the update.)
    for pid, command in listing.items():
        if pid == os.getpid():
            continue
        # (By folder only: ``--helab-io-helper`` names a frozen HeLab's helper, which never runs a checkout's code,
        # so it would only ever match another HeLab, a HeLab.app or another checkout's tests.)
        launched = "helab" in command and any(launcher in environments.get(pid, "") for launcher in launchers)
        if _runs_helab_from(command, places) or launched:
            found.append(f"process {pid}: {command[:160]}")
    return found


# The variable macOS's venv stub sets for a framework Python (the venv's own ``bin/python``).
LAUNCHER_ENV = "__PYVENV_LAUNCHER__"


def _processes(command: list[str]) -> dict[int, str]:
    """``ps``'s listing: pid → the rest of its line."""
    listing = _run(command, timeout=20)
    found: dict[int, str] = {}
    for line in listing.stdout.splitlines():
        pid, _, rest = line.strip().partition(" ")
        if pid.isdigit():
            found[int(pid)] = rest.strip()
    return found


def _runs_helab_from(command: str, folders: list[str]) -> bool:
    """Whether ``command`` (a process's whole command line, as ``ps`` shows it) runs a program from one of
    ``folders`` (the venv's, or the checkout's) and names HeLab after it: ``<venv>/bin/python -m helab.io_helper``,
    ``<venv>/bin/helab convert``. Matched on the folder as a prefix, never by splitting at spaces (a checkout
    under ``My Projects``)."""
    for folder in folders:
        prefix = folder.rstrip(os.sep) + os.sep
        if command.startswith(prefix) and "helab" in command[len(prefix):]:
            return True
    return False


def _windows_images(folders: list[str]) -> list[str]:
    """Processes whose program is in one of ``folders``, or a Python that has loaded a module (a ``.pyd`` or
    ``.dll``) from one of them (Windows only: a venv's ``python.exe`` hands over to the base one, whose image isn't
    in the venv). By the path each module was loaded from: a file uv hard-linked into this venv and loaded by
    another venv's Python, through that venv's path, isn't this venv's."""
    if sys.platform == "win32":
        return _windows_images_win(folders)
    return []


if sys.platform == "win32":
    class _Module(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("th32ModuleID", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("GlblcntUsage", wintypes.DWORD), ("ProccntUsage", wintypes.DWORD),
                    ("modBaseAddr", ctypes.c_void_p), ("modBaseSize", wintypes.DWORD), ("hModule", ctypes.c_void_p),
                    ("szModule", ctypes.c_wchar * 256), ("szExePath", ctypes.c_wchar * 260)]

    def _kernel() -> Any:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                      ctypes.POINTER(wintypes.DWORD)]
        for name in ("Process32FirstW", "Process32NextW", "Module32FirstW", "Module32NextW"):
            getattr(kernel, name).argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        return kernel

    def _windows_modules_win(kernel: Any, pid: int, folders: list[str]) -> str:
        """The first module ``pid`` loaded from one of ``folders``, or "" (also when it can't be read)."""
        snapshot = None
        for _ in range(5):  # (ERROR_BAD_LENGTH while the process loads a module: try again.)
            snapshot = kernel.CreateToolhelp32Snapshot(0x8 | 0x10, pid)  # TH32CS_SNAPMODULE | SNAPMODULE32
            if snapshot and snapshot != wintypes.HANDLE(-1).value:
                break
            snapshot = None
            if ctypes.get_last_error() != 24:
                return ""
        if snapshot is None:
            return ""
        try:
            module = _Module()
            module.dwSize = ctypes.sizeof(_Module)
            more = kernel.Module32FirstW(snapshot, ctypes.byref(module))
            while more:
                if _under(module.szExePath, folders):
                    return str(module.szExePath)
                more = kernel.Module32NextW(snapshot, ctypes.byref(module))
        finally:
            kernel.CloseHandle(snapshot)
        return ""

    def _windows_images_win(folders: list[str]) -> list[str]:
        """Processes whose program is in one of ``folders``, and Pythons with a module from one of them (ctypes: a
        toolhelp snapshot, each image's path, each Python's modules)."""
        class Entry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD),
                        ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                        ("szExeFile", ctypes.c_wchar * 260)]
        kernel = _kernel()
        snapshot = kernel.CreateToolhelp32Snapshot(0x2, 0)
        found: list[str] = []
        if not snapshot or snapshot == wintypes.HANDLE(-1).value:
            return ["the process list couldn't be read"]
        try:
            entry = Entry()
            entry.dwSize = ctypes.sizeof(Entry)
            more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                pid = int(entry.th32ProcessID)
                if pid not in (0, os.getpid()):
                    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
                    if handle:
                        try:
                            size = wintypes.DWORD(1024)
                            buffer = ctypes.create_unicode_buffer(1024)
                            if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)) and _under(
                                    buffer.value, folders):
                                found.append(f"process {pid}: {buffer.value}")
                        finally:
                            kernel.CloseHandle(handle)
                    if not (found and found[-1].startswith(f"process {pid}:")) and str(
                            entry.szExeFile).lower().startswith("python"):
                        loaded = _windows_modules_win(kernel, pid, folders)
                        if loaded:
                            found.append(f"process {pid} ({entry.szExeFile}) has {loaded} loaded")
                more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel.CloseHandle(snapshot)
        return found


# -- Git ----------------------------------------------------------------------------------------------

def git(job: Job, *arguments: str, check: bool = True, timeout: float = 600) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="", SSH_ASKPASS="")
    done = _run([*job.git, "-C", str(job.checkout), *arguments], timeout=timeout, env=env)
    if check and done.returncode != 0:
        raise Failed(f"git {' '.join(arguments)} failed: {(done.stderr or done.stdout).strip()[:500]}")
    return done


def out(job: Job, *arguments: str) -> str:
    return git(job, *arguments).stdout.strip()


def source_for(job: Job) -> str:
    """The remote whose URL names the repo (by URL, never by remote name), else the repo's URL (Q~6 (a))."""
    listed = git(job, "config", "--get-regexp", r"^remote\..*\.url$", check=False).stdout
    for line in listed.splitlines():
        key, _, url = line.partition(" ")
        match = GITHUB_REMOTE.fullmatch(url.strip())
        if match and f"{match['owner']}/{match['name']}".lower() == job.repository.lower():
            return key[len("remote."):-len(".url")]
    return f"https://github.com/{job.repository}"


def fetch(job: Job, log: Log) -> str:
    """Fetch the target and check it; its commit."""
    source = source_for(job)
    log(f"Fetching from {source}")
    if job.mode == RELEASES:
        if not TAG.fullmatch(job.tag):
            raise Refused(f"{job.tag!r} isn't a release tag.")
        done = git(job, "fetch", "--no-tags", source, f"refs/tags/{job.tag}:refs/tags/{job.tag}", check=False)
        if done.returncode != 0:
            if "clobber" in done.stderr or "rejected" in done.stderr:
                raise Refused(f"This checkout's tag {job.tag} names another commit than the repo's: the tag moved. "
                              "HeLab doesn't update to it.")
            raise Refused(f"Couldn't fetch {job.tag} from {job.repository}: {done.stderr.strip()[:300]}")
        commit = out(job, "rev-parse", f"refs/tags/{job.tag}^{{commit}}")
        git(job, "fetch", "--no-tags", source, "refs/heads/main")
        main = out(job, "rev-parse", "FETCH_HEAD")
        if git(job, "merge-base", "--is-ancestor", commit, main, check=False).returncode != 0:
            raise Refused(f"{job.tag} isn't on {job.repository}'s main: HeLab only updates to releases made there.")
    else:
        done = git(job, "fetch", "--no-tags", source, f"refs/heads/{job.branch}", check=False)
        if done.returncode != 0:
            raise Refused(f"Couldn't fetch {job.branch} from {job.repository}: {done.stderr.strip()[:300]}")
        tip = out(job, "rev-parse", "FETCH_HEAD")
        commit = job.target
        if not SHA.fullmatch(commit) or git(job, "merge-base", "--is-ancestor", commit, tip,
                                            check=False).returncode != 0:
            raise Refused(f"The commit the check found isn't on {job.repository}'s {job.branch}.")
        # The branch's own commits only (its first-parent line, back to this checkout's commit): never one merged
        # in from another branch, whose state the branch never had.
        line = out(job, "rev-list", "--first-parent", tip, "^HEAD").split()
        if commit not in line:
            raise Refused(f"{commit[:7]} came into {job.branch} from another branch (by a merge): HeLab only moves "
                          f"to {job.branch}'s own commits.")
    if job.target and commit != job.target:
        raise Refused(f"The repo's {job.tag or job.branch} is now {commit[:7]}, not the {job.target[:7]} the check "
                      "found. Check for updates again.")
    return commit


@dataclass
class Plan:
    previous: str = ""  # The commit before
    previous_branch: str = ""  # The branch the checkout was on ("" detached)
    target: str = ""
    rebuild: bool = False
    stash: bool = False  # Local changes would be stashed.
    refusals: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)


def python_minor(job: Job, commit: str) -> str:
    shown = git(job, "show", f"{commit}:requirements.lock", check=False).stdout
    match = re.search(r"--python-version[ =](\d+\.\d+)", shown)
    return match[1] if match else ""


def plan(job: Job, log: Log, *, running: bool) -> Plan:
    """Every refusal, and what the update would do. ``running``: HeLab still runs (``--check``)."""
    found = Plan()
    refuse = found.refusals.append
    if ssh_session(os.environ):
        refuse("HeLab was started from an SSH session: update it from the computer's own desktop.")
    if elevated():
        refuse("HeLab runs with administrator rights: start it as yourself to update it.")
    if not shutil.which(job.git[0]) and not Path(job.git[0]).is_file():
        refuse("git isn't installed (or HeLab can't find it).")
        return found
    if git(job, "rev-parse", "--show-toplevel", check=False).returncode != 0:
        refuse(f"{job.checkout} isn't a git checkout.")
        return found
    top = Path(out(job, "rev-parse", "--show-toplevel"))
    if not _same(top.resolve(), job.checkout.resolve()):
        refuse(f"{job.checkout} isn't the top of its git checkout.")
        return found
    if running:
        # (The dry run. The real run has waited for these, ``wait_for_helab``, and waits again before each
        # change, ``check_quiet``: a start that honours ``update.lock`` holds its own lock for a moment.)
        for held in helab_locks(job.app_dir, job.pid):
            refuse(f"Not while {held}.")
        if lock_held(job.app_dir / UPDATE_LOCK):
            refuse("Not while another update of HeLab is running.")
    found.previous = out(job, "rev-parse", "HEAD")
    head = git(job, "symbolic-ref", "-q", "HEAD", check=False).stdout.strip()
    found.previous_branch = head.removeprefix("refs/heads/") if head.startswith("refs/heads/") else ""
    changes = git(job, "status", "--porcelain=v1", "--untracked-files=no", "--ignore-submodules=dirty").stdout
    if changes.strip():
        if job.stash:
            found.stash = True
            found.steps.append("Stash this checkout's changes (git stash push; never dropped: git stash list)")
        else:
            names = ", ".join(line[3:] for line in changes.splitlines()[:5])
            refuse(f"This checkout has changes ({names}): commit or stash them first, or let HeLab stash them.")
    if job.action == RESTORE:
        previous = read_json(job.updates / "previous.json")
        if not previous or not _same(Path(str(previous.get("checkout", ""))), job.checkout):
            refuse("No previous version of this checkout is kept.")
            return found
        if previous.get("to") != found.previous:
            refuse("The checkout moved since the update: Restore would leave that out. Restore it by hand.")
            return found
        found.target = str(previous.get("from", ""))
        found.rebuild = bool(previous.get("rebuilt"))
        if found.rebuild and not Path(str(venv_real(job)) + ".previous").is_dir():
            refuse("The previous venv isn't there any more.")
        found.steps.append(f"Go back to {found.target[:7]}" + (" and the previous venv" if found.rebuild else ""))
        return found
    if job.mode == BRANCH:
        if not found.previous_branch:
            refuse("This checkout isn't on a branch (it is on a release tag, or detached): it updates to releases.")
            return found
        if found.previous_branch != job.branch:
            refuse(f"This checkout is on {found.previous_branch}, not {job.branch}.")
            return found
    elif job.mode != RELEASES:
        refuse(f"Unknown update mode {job.mode!r}.")
        return found
    try:
        found.target = fetch(job, log)
    except Failed as failed:
        refuse(str(failed))
        return found
    except Refused as refused:
        refuse(str(refused))
        return found
    if job.mode == BRANCH and git(job, "merge-base", "--is-ancestor", found.previous, found.target,
                                  check=False).returncode != 0:
        refuse(f"{job.branch} on GitHub doesn't contain this checkout's commit: it can't fast-forward.")
    if found.target == found.previous:
        refuse("This checkout is already on that version.")
    # (--no-renames: a file the update renames into place is added there too.)
    added = set(out(job, "diff", "--name-only", "--no-renames", "--diff-filter=A", found.previous,
                    found.target).splitlines())
    untracked = set(out(job, "ls-files", "--others", "--exclude-standard").splitlines())
    if added & untracked:
        refuse("Files the update adds exist here untracked: " + ", ".join(sorted(added & untracked)[:8]) + ".")
    wanted = python_minor(job, found.target)
    have = f"{sys.version_info[0]}.{sys.version_info[1]}"
    if wanted and wanted != have:
        refuse(f"The new version needs Python {wanted}; HeLab's is {have}. Rebuild its venv by hand.")
    found.rebuild = git(job, "diff", "--quiet", found.previous, found.target, "--", *REBUILD_FILES,
                        check=False).returncode != 0
    if found.rebuild:
        if not job.uv or not (shutil.which(job.uv[0]) or Path(job.uv[0]).is_file()):
            refuse("The new version needs new packages, and uv isn't installed (or HeLab can't find it).")
        if not (_same(job.venv.resolve(), (job.checkout / "venv").resolve()) or _same(job.venv, job.checkout / "venv")):
            refuse(f"The new version needs new packages, and HeLab's Python environment ({job.venv}) isn't this "
                   "checkout's venv: update it by hand.")
    what = (f"fast-forward {job.branch} {found.previous[:7]} → {found.target[:7]}" if job.mode == BRANCH
            else f"check out {job.tag} ({found.target[:7]})")
    found.steps.append(f"Fetch from {job.repository} and {what}")
    found.steps.append("Build a new venv for the new requirements first (a few minutes); the old one is kept"
                       if found.rebuild else "Keep the venv (the requirements didn't change)")
    return found


# -- The venv ------------------------------------------------------------------------------------------

def venv_real(job: Job) -> Path:
    """The venv's real folder: what is rebuilt and swapped (``venv`` itself stays, a symlink included)."""
    return job.venv.resolve()


def venv_python(folder: Path, windowed: bool = False) -> Path:
    if sys.platform == "win32":
        return folder / "Scripts" / ("pythonw.exe" if windowed else "python.exe")
    return folder / "bin" / "python"


def _rename(source: Path, destination: Path, log: Log) -> None:
    """A rename that retries for a few seconds (Windows: antivirus and the indexer hold files briefly)."""
    for attempt in range(40):
        try:
            os.replace(source, destination)
            log(f"Renamed {source} → {destination}")
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.25)


def target_version(job: Job, commit: str) -> str:
    shown = git(job, "show", f"{commit}:helab/_version.py", check=False).stdout
    match = re.search(r"__version__\s*=\s*[\"']([^\"']+)[\"']", shown)
    return match[1] if match else ""


def build_venv(job: Job, commit: str, log: Log) -> Path:
    """``<venv>.new`` for the checked-out target, checked to import HeLab's version. Its own leftover first goes."""
    real = venv_real(job)
    new = Path(str(real) + ".new")
    if new.exists():
        shutil.rmtree(new)  # (This updater's own half-built folder from an earlier attempt.)
    for command in ([*job.uv, "venv", "--relocatable", "--seed", "--python", job.python, str(new)],
                    [*job.uv, "pip", "install", "--python", str(venv_python(new)), "-r",
                     str(job.checkout / "requirements.lock"), "-e", str(job.checkout)]):
        log("Running " + " ".join(command))
        done = _run(command, timeout=1800, cwd=job.checkout)
        if done.returncode != 0:
            raise Failed(f"Building the new venv failed: {(done.stderr or done.stdout).strip()[-800:]}")
    check = ("import helab._version, helab.build_info, helab.utils.settings_defaults, PyQt6.QtCore; "
             "print(helab._version.__version__)")
    env = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")}
    # Bytecode in an empty folder of its own: a ``.pyc`` written in the same second for a source of the same size
    # (two updates in a row) would otherwise pass for the new source.
    cache = job.updates / f"pycache-{job.token}"
    env["PYTHONPYCACHEPREFIX"] = str(cache)
    try:
        done = _run([str(venv_python(new)), "-c", check], timeout=300, cwd=job.checkout, env=env)
    finally:
        shutil.rmtree(cache, ignore_errors=True)  # (This check's own bytecode.)
    wanted = target_version(job, commit)
    if done.returncode != 0 or (wanted and done.stdout.strip() != wanted):
        raise Failed(f"The new venv doesn't import HeLab {wanted}: {(done.stderr or done.stdout).strip()[-800:]}")
    log(f"New venv imports HeLab {done.stdout.strip()}")
    return new


def _renames(steps: list[tuple[Path, Path]], log: Log) -> None:
    """Renames in order, as one step: when one fails (Windows: a file still held after ``_rename``'s tries), or
    the updater is interrupted between two, those already made are undone, last first, and the failure goes
    on to the caller. So a swap either happened or left every folder where it was; the active venv is never
    left missing. If an undo fails too, that is raised (the log has each rename made, to finish by hand)."""
    done: list[tuple[Path, Path]] = []
    try:
        for source, destination in steps:
            _rename(source, destination, log)
            done.append((source, destination))
    except BaseException as failed:
        log(f"A rename failed ({failed!r}): undoing the {len(done)} before it")
        for source, destination in reversed(done):
            _rename(destination, source, log)
        raise


def swap_in(job: Job, new: Path, log: Log) -> Path | None:
    """``new`` becomes the venv, the current one ``<venv>.previous``; the one kept before that is set aside
    (``<venv>.previous-<UTC>``) and returned, for ``discard_older`` once the new HeLab has started. All or
    nothing (``_renames``): if it raises, the venv, ``.previous`` and ``new`` are where they were."""
    real = venv_real(job)
    previous = Path(str(real) + ".previous")
    older = None
    steps: list[tuple[Path, Path]] = []
    if previous.exists():
        older = Path(f"{previous}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}")
        steps.append((previous, older))
    _renames([*steps, (real, previous), (new, real)], log)
    return older


def swap_back(job: Job, older: Path | None, log: Log) -> None:
    """``swap_in`` undone: ``<venv>.previous`` is the venv again, the one kept before it ``.previous`` again, and
    the venv this update built is deleted. All or nothing too: if it raises, the built venv is still the venv."""
    real = venv_real(job)
    previous = Path(str(real) + ".previous")
    failed = Path(str(real) + ".failed")
    steps: list[tuple[Path, Path]] = []
    if previous.is_dir():
        if failed.exists():
            shutil.rmtree(failed, ignore_errors=True)
        if real.exists():
            steps.append((real, failed))
        steps.append((previous, real))
    if older is not None and older.exists():
        steps.append((older, previous))
    _renames(steps, log)
    shutil.rmtree(failed, ignore_errors=True)  # (The venv this update built.)


def swap_previous(job: Job, log: Log) -> None:
    """Restore: the venv and ``<venv>.previous`` change places (through ``<venv>.restoring``), all or nothing. Its
    own undo, too."""
    real = venv_real(job)
    previous = Path(str(real) + ".previous")
    spare = Path(str(real) + ".restoring")
    _renames([(real, spare), (previous, real), (spare, previous)], log)


def discard_older(older: Path | None, log: Log) -> None:
    """Q~8: the venv kept before the previous one, once the new version has started. HeLab's only removal
    here; with ``DELETE_OLDER_VENV`` off it stays, under its dated name, until deleted by hand."""
    if older is None or not older.exists():
        return
    if DELETE_OLDER_VENV:
        shutil.rmtree(older, ignore_errors=True)
        log(f"Deleted the older venv {older}")
    else:
        log(f"Kept the older venv {older}")


# -- Relaunching ---------------------------------------------------------------------------------------

def relaunch(job: Job, token: str | None, log: Log) -> subprocess.Popen[bytes] | None:
    """HeLab again, detached, as this user in this desktop session (this process is HeLab's child there)."""
    if not job.relaunch:
        log("No relaunch command: HeLab isn't started again.")
        return None
    env = {key: value for key, value in os.environ.items() if key != "HELAB_UPDATE_TOKEN"}
    if token:
        env["HELAB_UPDATE_TOKEN"] = token
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    log("Starting " + " ".join(job.relaunch))
    try:
        return subprocess.Popen(job.relaunch, cwd=job.checkout, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                                start_new_session=sys.platform != "win32", creationflags=flags)
    except OSError as exc:
        log(f"Couldn't start HeLab: {exc}")
        return None


def started_mark(job: Job, token: str) -> Path:
    return job.updates / f"started-{token}"


def wait_started(job: Job, process: subprocess.Popen[bytes] | None, token: str) -> str:
    """"started" (the mark), "exited" (before marking it) or "unconfirmed" (still running without it)."""
    if process is None:
        return "exited"
    deadline = time.monotonic() + job.timeouts["started"]
    while time.monotonic() < deadline:
        if started_mark(job, token).exists():
            return "started"
        if process.poll() is not None:
            return "started" if started_mark(job, token).exists() else "exited"
        time.sleep(POLL)
    return "unconfirmed"


# -- The run --------------------------------------------------------------------------------------------

def wait_for_helab(job: Job, handle: ProcessHandle, log: Log) -> None:
    log(f"Waiting for HeLab (process {job.pid}) to quit")
    if not handle.wait(job.timeouts["helab"]):
        raise Refused("HeLab didn't quit: nothing was changed.")
    busy = wait_quiet(job)
    if busy:
        raise Refused("HeLab's helpers are still running: " + "; ".join(busy[:3]) + ". Nothing was changed.")
    log("HeLab and its helpers have exited")


def wait_quiet(job: Job) -> list[str]:
    """Wait (up to ``others``) until no HeLab lock is held and nothing runs from the venv or the checkout; what
    still is, or []."""
    deadline = time.monotonic() + job.timeouts["others"]
    while True:
        busy = helab_locks(job.app_dir, None) + running_from(job)
        if not busy or time.monotonic() > deadline:
            return busy
        time.sleep(POLL * 2)


def record(job: Job, outcome: str, reason: str, previous: str, target: str, log: Log, **extra: Any) -> None:
    write_json(job.updates / "last.json", {
        "token": job.token, "action": job.action, "outcome": outcome, "reason": reason, "from": previous,
        "to": target, "checkout": str(job.checkout), "log": str(log.path),
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"), **extra})
    log(f"Outcome: {outcome}" + (f" ({reason})" if reason else ""))


def move_code(job: Job, found: Plan, log: Log) -> None:
    if job.action == RESTORE:
        previous = read_json(job.updates / "previous.json")
        branch = str(previous.get("branch", ""))
        if branch and found.previous_branch == branch:
            git(job, "reset", "--keep", found.target)  # (Only the local branch moves back; the repo keeps its commits.)
        elif branch and out(job, "rev-parse", f"refs/heads/{branch}") == found.target:
            git(job, "checkout", branch)
        else:
            git(job, "checkout", "--detach", found.target)
    elif job.mode == RELEASES:
        git(job, "checkout", "--detach", f"refs/tags/{job.tag}")
    else:
        git(job, "merge", "--ff-only", found.target)
    log(f"Checked out {out(job, 'rev-parse', 'HEAD')[:7]}")
    submodules = git(job, "submodule", "update", check=False)
    if submodules.returncode != 0:
        log(f"Warning: git submodule update failed (not HeLab's code): {submodules.stderr.strip()[:300]}")


def move_code_back(job: Job, found: Plan, log: Log) -> None:
    head = out(job, "rev-parse", "HEAD")
    if head == found.previous:
        return
    if found.previous_branch:
        current = git(job, "symbolic-ref", "-q", "HEAD", check=False).stdout.strip()
        if current == f"refs/heads/{found.previous_branch}":
            git(job, "reset", "--keep", found.previous)
        else:
            git(job, "checkout", found.previous_branch)
            if out(job, "rev-parse", "HEAD") != found.previous:
                git(job, "reset", "--keep", found.previous)
    else:
        git(job, "checkout", "--detach", found.previous)
    git(job, "submodule", "update", check=False)
    log(f"Moved the code back to {found.previous[:7]}")


def check_quiet(job: Job, change: str) -> None:
    """Before each change (the code; minutes later, the venv): still no HeLab lock held and nothing running from
    the venv or the checkout. A start made meanwhile that honours ``update.lock`` is on its way out (it holds its
    own lock for a moment before it finds this update), so this waits as ``wait_quiet`` does; one that stays
    stops the update, which is then undone like any other failure."""
    busy = wait_quiet(job)
    if busy:
        raise Failed(f"HeLab was started again while it was being updated ({'; '.join(busy[:3])}), so {change}")


def update(job: Job, log: Log) -> int:
    """The real run: wait, check, change, restart. (``main`` has checked the test guard.)

    All of it under ``update.lock`` (``UpdateLock``), released once the code and the venv are as they will stay;
    the previous version, when that is what stays, is started only after."""
    job.updates.mkdir(parents=True, exist_ok=True)
    lock = UpdateLock(job.app_dir / UPDATE_LOCK)
    if not lock.take(job.token):
        # No ready mark and no record: the HeLab that asked keeps running and says the updater didn't start, and
        # ``last.json`` is the running update's to write.
        log("Another update of HeLab is running (update.lock is held): this one changes nothing and ends.")
        return 2
    try:
        code, start_previous = _update(job, log, lock)
    finally:
        lock.release()
    if start_previous:
        relaunch(job, None, log)
    return code


def _update(job: Job, log: Log, lock: UpdateLock) -> tuple[int, bool]:
    """``update``, holding ``lock``: the exit code, and whether to start the version that stayed (the previous
    one) once the lock is released."""
    handle = ProcessHandle(job.pid)
    write_json(job.updates / f"ready-{job.token}", {"pid": os.getpid()})
    found = Plan()
    try:
        try:
            wait_for_helab(job, handle, log)
            found = plan(job, log, running=False)
            if found.refusals:
                raise Refused(" ".join(found.refusals))
        except Refused as refused:
            record(job, "refused", str(refused), found.previous, found.target, log)
            if handle.wait(0):
                return 2, True
            # (It never quit: a second one would only find it running.)
            log("HeLab is still running: not started again")
            return 2, False
    finally:
        handle.close()
    # What Restore went back to before this run: put back if this run is undone (an update that fails leaves the
    # earlier update's record, and its venv, for Restore).
    previous_record = read_json(job.updates / "previous.json")
    stash_message = ""
    moved = swapped = False
    older: Path | None = None
    try:
        check_quiet(job, "nothing was changed.")
        if found.stash:
            stash_message = f"HeLab update {found.previous[:7]} → {found.target[:7]}"
            git(job, "stash", "push", "-m", stash_message)
            log(f"Stashed this checkout's changes as \"{stash_message}\" (git stash list; git stash apply to get them back)")
        moved = True
        move_code(job, found, log)
        if job.action == RESTORE and found.rebuild:
            swap_previous(job, log)
            swapped = True
        elif found.rebuild:
            new = build_venv(job, found.target, log)
            check_quiet(job, "the update was undone.")
            older = swap_in(job, new, log)
            swapped = True
        write_json(job.updates / "previous.json", {
            "checkout": str(job.checkout), "from": found.previous, "to": found.target,
            "branch": found.previous_branch, "mode": job.mode, "tag": job.tag if job.mode == RELEASES else "",
            "rebuilt": found.rebuild, "stash": stash_message,
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    except Exception as failed:  # (Anything once a file may have changed: put it all back.)
        log(f"Failed: {failed!r}")
        undone = rollback(job, found, moved, swapped, older, previous_record, log)
        record(job, "failed", str(failed) + ("" if undone else NOT_UNDONE.format(checkout=job.checkout)),
               found.previous, found.target, log, stash=stash_message)
        return 1, True
    process = relaunch(job, job.token, log)  # (Under the lock: its token lets it, and only it, start.)
    state = wait_started(job, process, job.token)
    if state == "exited":
        log("The new version exited before it started")
        # Its helpers (and a cache move's) don't follow it out: nothing changes under them either.
        busy = wait_quiet(job)
        if busy:
            record(job, "failed", "The new version exited before it started, and its helpers still ran ("
                   + "; ".join(busy[:3]) + "), so it was left in place. Once they have gone, use Help › Restore "
                   f"previous version, or by hand: git -C \"{job.checkout}\" checkout {found.previous[:12]}",
                   found.previous, found.target, log, stash=stash_message)
            return 1, False
        if rollback(job, found, moved, swapped, older, previous_record, log):
            record(job, "rolled back", "The new version didn't start, so the previous one was put back.",
                   found.previous, found.target, log, stash=stash_message)
        else:
            record(job, "failed", "The new version didn't start" + NOT_UNDONE.format(checkout=job.checkout),
                   found.previous, found.target, log, stash=stash_message)
        return 1, True
    if state == "started":
        # (A restore says what it left, so the startup reminder skips it: design §7.)
        left = ({"mode": str(previous_record.get("mode", "")), "tag": str(previous_record.get("tag", ""))}
                if job.action == RESTORE else {})
        # Recorded first: the new HeLab is polling for it (``UPDATE_OUTCOME_WAIT_S``), and deleting the older venv
        # can take a while on a slow disk; the deletion never changes the outcome (its errors are ignored).
        record(job, "restored" if job.action == RESTORE else "updated", "", found.previous, found.target, log,
               stash=stash_message, **left)
        lock.release()  # (The code and the venv stay as they are: the older venv is nothing HeLab runs from.)
        discard_older(older, log)
    else:
        record(job, "unconfirmed", "The new version is still starting: it wasn't stopped.", found.previous,
               found.target, log, stash=stash_message)
    return 0, False


# After a failure's reason, when putting the previous version back failed as well.
NOT_UNDONE = (", and putting the previous version back failed too (see the log). Check the checkout by hand: "
              "git -C \"{checkout}\" status")


def rollback(job: Job, found: Plan, moved: bool, swapped: bool, older: Path | None,
             previous_record: dict[str, Any], log: Log) -> bool:
    """Everything this run changed, put back; whether all of it was. The venv first: if that can't be put back
    (its renames are one step, so the venv this run made active stays active), the code stays with it, and
    ``previous.json`` as it is, rather than the previous code on the new venv."""
    try:
        if swapped:
            if job.action == RESTORE:
                swap_previous(job, log)
            else:
                swap_back(job, older, log)
        else:
            new = Path(str(venv_real(job)) + ".new")
            if new.exists():
                shutil.rmtree(new, ignore_errors=True)  # (This update's own half-built venv.)
        if moved:
            move_code_back(job, found, log)
        if previous_record:
            write_json(job.updates / "previous.json", previous_record)
        elif moved:
            (job.updates / "previous.json").unlink(missing_ok=True)
    except Exception as failed:
        log(f"Rolling back failed too: {failed!r}. Fix the checkout by hand: git -C {job.checkout} status")
        return False
    return True


def check(job: Job, log: Log) -> dict[str, Any]:
    """The dry run while HeLab runs: refusals and the plan."""
    try:
        found = plan(job, log, running=True)
    except (Refused, Failed) as refused:
        found = Plan(refusals=[str(refused)])
    except (OSError, subprocess.SubprocessError) as failed:
        found = Plan(refusals=[f"The check failed: {failed}"])
    changes_only = bool(found.refusals) and all(r.startswith("This checkout has changes") for r in found.refusals)
    return {"ok": not found.refusals, "refusals": found.refusals, "steps": found.steps, "target": found.target,
            "previous": found.previous, "rebuild": found.rebuild, "stashable": changes_only}


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: updater.py REQUEST.json [--check]", file=sys.stderr)
        return 64
    # A safeguard: Python 3.13 already drops this variable at start, but if a Python ever leaves it set, nothing
    # this updater starts (ps, git, the relaunch) inherits it and passes for a process of HeLab's venv.
    os.environ.pop(LAUNCHER_ENV, None)
    job = read_job(Path(argv[0]))
    try:
        guard(job)  # (Before anything is written: no log, no ready, nothing started.)
    except Refused as refused:
        if "--check" in argv[1:]:
            print(json.dumps({"ok": False, "refusals": [str(refused)], "steps": [], "target": "", "previous": "",
                              "rebuild": False, "stashable": False}))
            return 0
        print(refused, file=sys.stderr)
        return 2
    log = Log(job.updates / f"update-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{job.token[:8]}.log")
    if "--check" in argv[1:]:
        print(json.dumps(check(job, log)))
        return 0
    log(f"HeLab updater ({job.action}, {job.mode}) for {job.checkout}, HeLab process {job.pid}")
    try:
        return update(job, log)
    except Exception as exc:  # The last word: logged, so the next HeLab can say what happened.
        log(f"Unexpected error: {exc!r}")
        record(job, "failed", f"Unexpected error: {exc!r}", "", "", log)
        relaunch(job, None, log)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
