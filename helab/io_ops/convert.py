"""Converting a folder's raw files to HeLab's own TXY (TXY converter stage 4, ``convert``).

``convert_folder`` lists the folder once, decides for each raw file ``d<N>.txt`` (of the shots
asked for) whether it is done, waiting or to convert, converts those with a detector profile and
backend (``helab.convert``), and writes each ``d_txy_helab_<tag>_<N>.txt`` atomically (``<tag>``: the
profile's, ``profile.file_tag``, Q18.4)
(``txy.write_atomic``: a temporary name, fsync, rename) with its provenance row in HeLab's index
(``helab.convert.provenance``: ``converted-txy/index.sqlite`` of the base, written before the rename). ``helab convert --watch`` runs this same
function in its own process (``helab.convert_cli``); the app runs it in a helper.

**Settle checks** (A10.1; 2019-halos d3667 is the evidence: MATLAB converted it 0.25 s after its
last write). A raw file is converted only when it is unmodified for ``fingerprints.SETTLE_SECONDS``
(the settle time, Settings → General, default 5 s; sent with each request, Q33.7) by this computer's clock and not dated in the future; its (size, mtime) are the same at two
checks a check interval apart, the previous conversion's (the caller sends its ``waiting`` list
back as ``seen``: a file not in it waits for the next check) and this one's, and the same again
before and after it is read; it ends with a newline; and its first line is on the profile's
trigger channel (``raw.not_done``). Otherwise it waits (``shot_waiting``) and nothing is written;
it is looked at again by a later conversion, never read twice in a row as if done. The age alone
can be fooled (a source clock behind ours, a share's stale attribute cache), so the app always
sends ``seen``; only ``helab convert --once`` sends None (one check), and then a file must be
unmodified for ``ONCE_SETTLE_SECONDS`` (60 s) instead. A file dated more than
``fingerprints.FUTURE_SECONDS`` ahead waits as ``future``, and ``clock_skew`` says so once per
conversion. A file that still fails the format checks (no final newline, its first line off the
trigger channel, no rows) once unmodified for ``DAMAGED_SECONDS`` (20 s; a shot arrives about every
30 s), both by its mtime against this clock and since this computer first saw it with that size and
mtime (each ``waiting`` entry carries that time, sent back in ``seen``; so a source clock behind ours
can't make a file paused mid-write look old; ``--once``, one look with no history, goes by the mtime
alone and wants ``ONCE_SETTLE_SECONDS``, as its settle rule does, Q23.7), is **damaged** (Q18.5): unconvertible (``shot_unconvertible``, reason ``damaged``, the check in
``problem``), no TXY, skipped from then on while unchanged, so it never holds up later shots. One the
converter fails on is unconvertible too.

**Output** (Q9.3, Q9.7). ``beside`` writes the TXY next to the raw files, only when the folder's
``write_beside`` flag is on in the store (or the command line asked, ``beside_confirmed``), and
never replaces a file there (a TXY in a source folder is never modified); one of the profile's tag is
current there while it is newer than its raw file (``provenance.beside_stale``: what any computer can
tell from the folder alone); nothing else is written to a source folder: the temporary name is
renamed, and the provenance row goes to HeLab's index (before the rename, as everywhere: a row
whose TXY was never renamed into place stands for nothing). A beside conversion also removes its own leftover temporary files there (a
helper killed mid-write), only those matching exactly the name ``write_atomic`` gives
(``partial()``), regular files (links aren't followed) unmodified for ``PARTIAL_MAX_AGE`` (1 h), each
sent as ``partial_removed``.
``cache`` writes under the cache folder, keyed by the folder's data root like the store
(``root://<uuid>/<relative>``); a folder without one, with the disk cache off, or marked Don't cache
(Q19.5, Q27.4: the store's flag, read here; unless ``cache_confirmed``, Q30.2) goes to ``temp``
(HeLab's temp folder) and ``convert_plan`` says why (``fallback``). HeLab's folder for a source folder is
``<base>/converted-txy/<hash of its key>/``; the base's ``converted-txy/index.sqlite`` names the key
and path (its ``folders`` row, updated when the folder moved) and holds the shots' rows. A
conversion there removes its leftover temporary TXY the same way, and old builds' JSON
temporaries (``own_partial()``).

**Clear fence** (A19.2). A conversion into the cache or temp folder reads the index's fence token
when it starts (``provenance.fence_of``); each TXY's row is written only while it is unchanged, and the
rename is made under the index's write lock with the token checked again (``TxyIndex.hold``), so
Settings › Cache's Clear (which sets a new token before it removes anything) never leaves a TXY this
conversion wrote: one refused waits (``shot_waiting``, reason ``cleared``), and so does every shot after it,
unread; a later conversion converts them. Beside the raw files nothing is fenced (Clear never removes
those TXY).

**Processes.** Reads, writes and every source-folder call stay in this process (traced, guarded
and paused like the other helpers'). With ``workers`` > 1, conversions run across shots in a pool
of spawned processes (4–8 give 3–5×, the NumPy floor measured), or, for one large shot, its pieces
(``split``). A worker only computes: killed with this helper (a cancel, a timeout, a cache move),
it notices its parent's end through a pipe and exits, and has nothing to write.

Heartbeats: while reading (per block) and while a shot computes, up to its budget
(``compute_budget``: ``COMPUTE_SECONDS`` plus a second per ``COMPUTE_RATE`` bytes); a read that
stalls, or a backend that hangs past its budget, sends none, so the app's no-progress timeout still
stops it.
"""
from __future__ import annotations

import concurrent.futures
import contextlib
import dataclasses
import errno
import functools
import hashlib
import os
import re
import sys
import threading
import time
from typing import Any, Callable, Iterable, Mapping, NotRequired, TypedDict, TYPE_CHECKING

from helab.io_ops import fingerprints, stores
from helab.io_ops.events import ConvertProfile, ConvertSeconds, HelperEvent, ShotUnconvertibleEvent
from helab.io_ops.infra import (Emit, Heartbeat, Pause, _entry_stat, _guard, _isdir, _scandir, _trace, _traced_error,
                                emit)
from helab.utils import file_kinds

if TYPE_CHECKING:
    from helab.utils.cache_store import CacheStore

    # A pipe's end: Windows' Pipe() gives PipeConnection, the others Connection.
    if sys.platform == "win32":
        from multiprocessing.connection import PipeConnection as Connection
    else:
        from multiprocessing.connection import Connection

    from helab.convert.pipeline import Converted
    from helab.convert.profile import DetectorProfile


OUTPUTS = ("cache", "temp")
FOLDER_NAME = "converted-txy"
READ_BLOCK = 8 * 1024 * 1024
# One shot this large (raw bytes) is cut into pieces for the pool, for Live's latency.
SPLIT_BYTES = 20 * 10**6
PROGRESS_INTERVAL = 0.25
# A single check (seen None: ``helab convert --once`` only) wants a file this long unmodified, to read it
# and to call it damaged (Q23.7: by its mtime alone, with no first seen to go by).
ONCE_SETTLE_SECONDS = 60.0
# Heartbeats while a shot computes stop after this, plus a second per COMPUTE_RATE raw bytes (ten
# times slower than the plain-Python reference): a hung backend then times out.
COMPUTE_SECONDS = 60.0
COMPUTE_RATE = 10**6
# A raw file unmodified this long that still fails the format checks is damaged (Q18.5, Tony: "damaged
# timeout 20s"; raw files arrive about one per 30 s).
DAMAGED_SECONDS = 20.0
DAMAGED = "damaged"
# A shot's ``shot_waiting`` reason when HeLab's TXY were cleared while this conversion ran (A19.2).
CLEARED = "cleared"
CLEARED_TEXT = "HeLab's converted TXY were cleared while this conversion ran: converted again at the next check"
# Leftover temporary TXY of a killed beside write: removed once this old, by a beside conversion.
PARTIAL_MAX_AGE = 3600.0
# Workers when the request doesn't say: across shots in processes. A frozen app's spawned workers
# need multiprocessing.freeze_support() first in helab/main.py (there) and a check in the built
# app (the packaging floor), so it converts in-process until that is done.
DEFAULT_WORKERS = 1 if getattr(sys, "frozen", False) else max(1, min(4, (os.cpu_count() or 2) // 2))
# Windows' full-path limit without long paths turned on (MAX_PATH, the terminating NUL included): a
# path of this many characters or more is refused, as WinError 206 or 3, or a FileNotFoundError
# (Q23.6: user profiles' 33-character tags make HeLab's names 50 characters plus the shot's digits, 26
# more while temporary).
WINDOWS_MAX_PATH = 260
# The OS whose path rules ``path_too_long`` applies (tests patch it to try Windows' on any OS).
PLATFORM = sys.platform


def path_too_long(exc: BaseException, path: str, platform: str | None = None,
                  folder_exists: Callable[[str], bool] | None = None) -> str | None:
    """What to tell the user when the OS refused ``path`` (or the name in ``exc``, e.g. the TXY's
    longer temporary one) for its length: ENAMETOOLONG anywhere; on Windows WinError 206, or WinError
    3 or FileNotFoundError on a path of WINDOWS_MAX_PATH characters or more while ``path``'s folder
    still exists (``folder_exists``, a traced stat by default; gone, the folder was moved or its drive
    dropped: not a length, so the run fails as before and the next check tries again). None for any
    other error (a Windows PC with long paths turned on, or any other OS, may just write it)."""
    if not isinstance(exc, OSError):
        return None
    given = exc.filename
    given = os.fspath(given) if isinstance(given, (str, os.PathLike)) else ""
    name = given if isinstance(given, str) and len(given) > len(path) else path
    winerror = getattr(exc, "winerror", None)
    windows = (PLATFORM if platform is None else platform) == "win32"
    not_found = winerror == 3 or isinstance(exc, FileNotFoundError)
    if windows and not_found and winerror != 206 and len(name) >= WINDOWS_MAX_PATH:
        exists = folder_exists or (lambda folder: _isdir(folder, "convert: too long or gone"))
        if not exists(os.path.dirname(path)):
            return None
    if windows and (winerror == 206 or not_found and len(name) >= WINDOWS_MAX_PATH):
        return (f"Path too long for Windows ({len(name):,} characters; the limit is {WINDOWS_MAX_PATH - 1} "
                f"unless long paths are turned on in Windows): {name}. Choose a shorter cache or temp folder "
                "(Settings), or a shorter folder path")
    if exc.errno == errno.ENAMETOOLONG:
        return (f"Path too long for this computer ({len(name):,} characters, or a name over 255): {name}. "
                "Choose a shorter cache or temp folder (Settings), or a shorter folder path")
    return None


class ConvertRequest(TypedDict):
    """The ``convert`` operation's payload (``IOService.submit(..., "convert", payload)``).

    ``profile``: ``DetectorProfile.to_dict()`` (a built-in's or the user's). ``destination``: the
    setting (``cache``, default, or ``temp``). ``beside``: the app believes the folder's
    ``write_beside`` flag is on (checked again in the store here); ``beside_confirmed``: the user
    asked for beside for this run (the command line only). ``cache_confirmed``: the user typed
    ``--output cache`` and confirmed it for a Don't cache folder (the command line only, Q30.2; anywhere
    else that folder's flag wins and its TXY go to the temp folder). ``temps``: HeLab's temp folder.
    ``cache``: ``store_options()``. ``shots``: only these (None: every raw file).
    ``seen`` (required): the previous conversion's ``waiting`` list, ``[]`` for a folder's first
    conversion (which then only records: every file waits for a second check); None only from
    ``helab convert --once`` (one check, ``ONCE_SETTLE_SECONDS``). Live and every other caller in
    the app always send a list. ``done``, ``kept``, ``skip``: the previous ``current``, ``kept`` and
    ``unconvertible`` lists, not checked again while unchanged. ``redo``: ``stale`` (convert a shot
    whose TXY isn't current, the default) or ``always``. ``workers``: processes for converting."""
    path: str
    profile: dict[str, Any]
    temps: str
    seen: list[list[Any]] | None
    backend: NotRequired[str]
    # ("destination", not "output": IOService gives every request its private folder as "output".)
    destination: NotRequired[str]
    beside: NotRequired[bool]
    beside_confirmed: NotRequired[bool]
    cache_confirmed: NotRequired[bool]
    cache: NotRequired[dict[str, Any]]
    shots: NotRequired[list[int] | None]
    done: NotRequired[list[list[Any]]]
    kept: NotRequired[list[list[Any]]]
    skip: NotRequired[list[list[Any]]]
    redo: NotRequired[str]
    workers: NotRequired[int]


class _Shot:
    """One raw file as this conversion saw it."""

    def __init__(self, shot: int, name: str, path: str, size: int, mtime_ns: int) -> None:
        self.shot, self.name, self.path, self.size, self.mtime_ns = shot, name, path, size, mtime_ns
        self.replaced = ""

    @property
    def entry(self) -> list[Any]:
        return [self.name, self.size, self.mtime_ns]


class _Places(TypedDict):
    output: str
    fallback: str
    folder: str
    txy_folder: str
    key: str


def folder_for(base: str, identity: str) -> str:
    """HeLab's folder for a source folder under ``base`` (the cache or temp folder): the same for
    every machine that keys it alike (its ``root://`` key), else for its absolute path."""
    return os.path.join(base, FOLDER_NAME, hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24])


def _profile_info(profile: DetectorProfile) -> ConvertProfile:
    from helab.convert.profile import file_tag
    return {"name": profile.name, "version": profile.version, "hash": profile.content_hash(),
            "tag": file_tag(profile), "calibrated": profile.calibrated}


def _locked(send: Emit) -> Emit:
    """``send`` safe to call from the heartbeat thread and this one."""
    lock = threading.Lock()

    def locked(event: HelperEvent) -> None:
        with lock:
            send(event)
    return locked


@functools.cache
def partial() -> re.Pattern[str]:
    """The temporary names ``txy.write_atomic`` gives HeLab's TXY, and nothing else. (Built on first
    use: every helper imports this module, and ``txy`` brings NumPy.)"""
    from helab.convert.provenance import BARE_NAME
    from helab.convert.txy import partial_pattern
    return partial_pattern(BARE_NAME + r"\.txt")


@functools.cache
def own_partial() -> re.Pattern[str]:
    """``partial()``, and the temporary names ``write_atomic`` gave the JSON of builds before the index
    (Q26.2) in HeLab's own folder (each shot's ``d_txy_helab_<tag>_<N>.json``, ``folder.json``), and
    nothing else. (The index's own journal is SQLite's, never housekeeping's.)"""
    from helab.convert.provenance import BARE_NAME
    from helab.convert.txy import partial_pattern
    return partial_pattern("|".join((BARE_NAME + r"\.(?:txt|json)", r"folder\.json")))


def journal_for(base: str) -> str:
    """The journal mode for a new index in ``base`` (the cache or temp folder): WAL where the folder is
    local, a rollback journal where ``cache_location_problem`` objects (a network drive, a UNC path, a
    synced folder: the temp folder is the user's to set), since WAL's shared memory needs a local disk."""
    from helab.convert.provenance import DELETE, WAL
    from helab.utils import cache_location
    return DELETE if cache_location.cache_location_problem(base) else WAL


def compute_budget(raw_bytes: int) -> float:
    """Seconds a shot of ``raw_bytes`` may compute while heartbeats go on."""
    return COMPUTE_SECONDS + raw_bytes / COMPUTE_RATE


class _Ticker:
    """Heartbeats from a thread while this process or its workers compute (not while reading: a
    stalled read must still time out), for at most ``budget`` seconds: a backend that hangs then
    times out."""

    def __init__(self, send: Emit, phase: str, budget: float) -> None:
        self.send, self.phase, self.budget = send, phase, budget
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        until = time.monotonic() + self.budget
        while not self.stop.wait(Heartbeat.INTERVAL) and time.monotonic() < until:
            self.send({"kind": "heartbeat", "phase": self.phase, "entries": 0})

    def __enter__(self) -> _Ticker:
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop.set()
        self.thread.join()


def _not_cached(store: CacheStore, path: str) -> str:
    """Why the folder's TXY don't go to the cache folder: its Don't cache flag (Q19.5, Q27.4, as for
    its datasets), or that flag unread (then not the cache either); "" when they may."""
    prefs = store.read_prefs([path])[path]
    if prefs.status == "error":
        return f"the folder's Don't cache flag couldn't be read ({prefs.error})"
    if prefs.value and prefs.value.get("no_cache"):
        return "you chose Don't cache for this folder"
    return ""


def dont_cache(path: str, cache: dict[str, Any]) -> str:
    """``_not_cached`` before a conversion (``helab convert --output cache`` asks first, Q30.2). "" also
    when the store can't be read or the folder has no data root: those send it to temp anyway."""
    from helab.utils.cache_paths import UnresolvedRemotePath
    from helab.utils.cache_store import StoreError
    try:
        with stores._cache_store(cache["directory"], [path]) as store:
            store._path_key(path)
            return _not_cached(store, path)
    except (UnresolvedRemotePath, StoreError, OSError):
        return ""


def _places(path: str, request: ConvertRequest) -> _Places:
    """Where this conversion writes (``convert_plan``'s fields)."""
    from helab.utils.cache_paths import UnresolvedRemotePath
    from helab.utils.cache_store import StoreError
    from helab.utils.data_roots import NoDataRoot
    output = str(request.get("destination") or "cache")
    if output not in OUTPUTS:
        raise ValueError(f"Unknown converter destination {output!r} (have {', '.join(OUTPUTS)})")
    cache_options = request.get("cache") or {}
    key, problem, flag, flag_problem, not_cached = "", "", False, "", ""
    if cache_options:
        try:
            with stores._cache_store(cache_options["directory"], [path]) as store:
                key = store._path_key(path)
                if output == "cache" and not request.get("cache_confirmed"):
                    not_cached = _not_cached(store, path)
                if request.get("beside") and not request.get("beside_confirmed"):
                    found = store.read_convert_prefs([path])[path]
                    if found.status == "error":
                        flag_problem = f"the folder's flag couldn't be read ({found.error})"
                    flag = bool(found.value and found.value.get("write_beside"))
        except UnresolvedRemotePath as exc:
            problem = "no .helab-root found here or above" if isinstance(exc, NoDataRoot) else str(exc)
        except (StoreError, OSError) as exc:
            problem = f"the disk cache couldn't be read ({exc})"
    else:
        problem = "the disk cache is off this session"
    fallback = ""
    beside = bool(request.get("beside_confirmed")) or bool(request.get("beside")) and flag
    if request.get("beside") and not beside:
        fallback = (flag_problem or "writing beside the raw files is off for this folder" if not problem
                    else f"writing beside the raw files needs the folder's flag, and {problem}")
    if output == "cache" and (not key or not_cached):
        output = "temp"
        why = not_cached or problem
        if beside:
            fallback = f"the provenance rows go to the temp folder's index: {why}"
        else:
            fallback = fallback or why
    base = os.path.dirname(os.path.abspath(cache_options["directory"])) if output == "cache" else request["temps"]
    folder = folder_for(base, key or "path:" + os.path.abspath(path))
    return {"output": "beside" if beside else output, "fallback": fallback, "folder": folder,
            "txy_folder": path if beside else folder, "key": key}


def _stats(entries: list[list[Any]] | None) -> dict[str, tuple[int, int]]:
    """Raw files' (size, mtime) by name, from a summary's ``[name, size, mtime_ns]`` lists."""
    return {str(entry[0]): (int(entry[1]), int(entry[2])) for entry in entries or []
            if isinstance(entry, (list, tuple)) and len(entry) >= 3}


def _read_raw(shot: _Shot, beat: Heartbeat) -> bytes | str:
    """The raw file's bytes, or why it isn't read as done (``CHANGED``: its size or mtime differ
    from the listing's, before or after the read). Traced like the other source reads."""
    from helab.convert.raw import CHANGED
    _guard(shot.path)
    try:
        with open(shot.path, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns) != (shot.size, shot.mtime_ns):
                _trace("read", shot.path, "convert: raw", bytes=0, changed=True)
                return CHANGED
            blocks: list[bytes] = []
            while block := stream.read(READ_BLOCK):
                blocks.append(block)
                beat(0)
            after = os.fstat(stream.fileno())
    except OSError as exc:
        _traced_error("read", shot.path, "convert: raw", exc)
        raise
    data = b"".join(blocks)
    _trace("read", shot.path, "convert: raw", bytes=len(data))
    if (after.st_size, after.st_mtime_ns, len(data)) != (shot.size, shot.mtime_ns, shot.size):
        return CHANGED
    return data


# Worker processes (spawned). Each watches its parent through a pipe and exits when it ends.

def _worker_start(parent: Connection, numba_folder: str) -> None:
    def watch() -> None:
        try:
            parent.recv()
        except (EOFError, OSError):
            pass
        os._exit(0)
    threading.Thread(target=watch, daemon=True).start()
    if numba_folder:
        from helab.convert.backends import numba_backend
        numba_backend.set_cache_folder(numba_folder)


def _worker_convert(data: bytes, profile: dict[str, Any], backend: str) -> Converted:
    from helab.convert.pipeline import convert_shot
    from helab.convert.profile import DetectorProfile
    return convert_shot(data, DetectorProfile.from_dict(profile), backend)


class _Pool:
    """The worker processes, started when the first shot is handed to them (none for a
    conversion whose shots all turn out waiting or empty)."""

    def __init__(self, workers: int, numba_folder: str) -> None:
        self.workers, self.numba_folder = workers, numba_folder
        self._executor: concurrent.futures.ProcessPoolExecutor | None = None
        self._pipe: tuple[Connection, Connection] | None = None

    @property
    def executor(self) -> concurrent.futures.ProcessPoolExecutor:
        if self._executor is None:
            import multiprocessing
            context = multiprocessing.get_context("spawn")
            reader, writer = self._pipe = context.Pipe(duplex=False)
            self._executor = concurrent.futures.ProcessPoolExecutor(
                self.workers, mp_context=context, initializer=_worker_start, initargs=(reader, self.numba_folder))
        return self._executor

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
        if self._pipe is not None:
            for end in self._pipe:
                end.close()


def convert_folder(path: str, request: ConvertRequest, send: Emit = emit) -> None:
    from helab._version import __version__
    import sqlite3
    from helab.convert import provenance, raw, txy
    from helab.convert.pipeline import APP_BACKEND, convert_shot
    from helab.convert.profile import DetectorProfile
    from helab.convert.reconstruct import BackendError, NoRowsError, get_backend
    started = time.monotonic()
    send = _locked(send)
    profile = DetectorProfile.from_dict(request["profile"])
    backend = str(request.get("backend") or APP_BACKEND)
    places = _places(path, request)
    # The Clear fence's token now (A19.2), before anything is listed: a Clear from here on refuses
    # this conversion's writes. (Beside: none; Clear never removes those TXY.)
    fence = None if places["output"] == "beside" else provenance.fence_of(os.path.dirname(places["folder"]))
    cleared = False
    # Caching v2 (store-v4): the raw layers of the shots this conversion reads, saved as it goes.
    raw_rows = _RawRows.start(path, places, request, send)
    numba_folder = ""
    if backend == "numba":
        # Its compiled code goes in HeLab's temp folder (Q18.1): numba no longer ships (Q11.2), so
        # only a developer who installed it has any.
        numba_folder = os.path.join(request["temps"], "numba")
        from helab.convert.backends import numba_backend
        numba_backend.set_cache_folder(numba_folder)
    reason = get_backend(backend).unavailable(profile)
    if reason is not None:
        raise BackendError(f"Backend {backend!r} can't run: {reason}")
    profile_info = _profile_info(profile)
    profile_hash, tag = profile_info["hash"], profile_info["tag"]
    beside = places["output"] == "beside"
    wanted = None if request.get("shots") is None else {int(shot) for shot in request.get("shots") or []}

    if "seen" not in request:
        raise ValueError("A conversion needs `seen`: the previous conversion's waiting list, [] for the first")
    seen_list = request["seen"]
    seen = None if seen_list is None else _stats(seen_list)
    # Files the previous conversion read and found unfinished (no final newline, another first
    # channel, no rows yet): their (size, mtime), reason and message.
    unfinished = {str(entry[0]): ((int(entry[1]), int(entry[2])), str(entry[3]), str(entry[4]))
                  for entry in seen_list or [] if isinstance(entry, (list, tuple)) and len(entry) >= 5
                  and entry[3] in (raw.NO_FINAL_NEWLINE, raw.NOT_TRIGGER_FIRST, raw.NO_ROWS)}
    # When this computer first saw each waiting file with its (size, mtime): this clock's time, carried
    # in the waiting entries (their sixth field; none from before it was sent).
    first_seen = {str(entry[0]): ((int(entry[1]), int(entry[2])), float(entry[5]))
                  for entry in seen_list or [] if isinstance(entry, (list, tuple)) and len(entry) >= 6
                  and isinstance(entry[5], (int, float)) and not isinstance(entry[5], bool)}
    done, kept_before, skip = _stats(request.get("done")), _stats(request.get("kept")), _stats(request.get("skip"))
    redo = str(request.get("redo") or "stale")
    if seen is not None:
        # The previous check saw its done and kept shots too, with these sizes and dates.
        seen = {**done, **kept_before, **seen}

    # The listing: raw files, and (beside) HeLab's TXY of this profile's tag already there (size, mtime).
    raws: list[_Shot] = []
    beside_txy: dict[int, tuple[int, int]] = {}
    partials: list[os.DirEntry[str]] = []
    beat = Heartbeat(send, "listing")
    with _scandir(path, "convert: listing") as directory:
        for entry in directory:
            beat()
            matched = file_kinds.match(entry.name)
            if matched is None:
                if beside and partial().match(entry.name):
                    partials.append(entry)
                continue
            kind, number = matched
            if wanted is not None and number not in wanted:
                continue
            if kind is file_kinds.RAW:
                info = _entry_stat(entry, "convert: raw")
                raws.append(_Shot(number, entry.name, entry.path, info.st_size, info.st_mtime_ns))
            elif kind is file_kinds.HELAB_TXY and beside and (provenance.parse_txy_name(entry.name) or ("",))[0] == tag:
                info = _entry_stat(entry, "convert: existing TXY")
                beside_txy[number] = (info.st_size, info.st_mtime_ns)
    raws.sort(key=lambda item: item.shot)

    for leftover in partials:
        _remove_partial(path, leftover, send)
    current: list[list[Any]] = []
    waiting: list[list[Any]] = []
    unconvertible: list[list[Any]] = []
    kept: list[list[Any]] = []
    todo: list[_Shot] = []
    now = time.time()
    settle = fingerprints.SETTLE_SECONDS
    if seen is None and settle > 0:
        settle = max(settle, ONCE_SETTLE_SECONDS)  # (One check: the age must stand for the second.)
    skewed = fingerprints._clock_ahead(path, [(shot.shot, shot.size, shot.mtime_ns) for shot in raws], send)
    # HeLab's index for this folder's TXY of the profile's tag (beside, the TXY's date says it).
    root, folder_name = os.path.dirname(places["folder"]), os.path.basename(places["folder"])
    records = {} if beside or not raws else provenance.read_shots(
        root, folder_name, tag=tag, shots=[shot.shot for shot in raws], repair=True)
    # A done or kept shot counts as such only while its TXY is still there: beside, by the listing; in HeLab's
    # folder (cache or temp), by one listing of it, so TXY cleared there (Settings › Cache), or another
    # destination, are looked at again.
    there = set(beside_txy) if beside else _txy_shots(places["folder"], tag) if done or kept_before else set()

    def seen_since(shot: _Shot) -> float:
        """When this computer first saw the file with its size and mtime now (this check, if not before)."""
        found = first_seen.get(shot.name)
        return found[1] if found is not None and found[0] == (shot.size, shot.mtime_ns) else now

    def wait(shot: _Shot, code: str, message: str) -> None:
        waiting.append([*shot.entry, code, message, seen_since(shot)])
        send({"kind": "shot_waiting", "path": path, "shot": shot.shot, "raw_name": shot.name, "raw_size": shot.size,
              "raw_mtime_ns": shot.mtime_ns, "reason": code, "message": message})

    def refuse(shot: _Shot, code: str, message: str, problem: str = "") -> None:
        unconvertible.append(shot.entry)
        event: ShotUnconvertibleEvent = {
            "kind": "shot_unconvertible", "path": path, "shot": shot.shot, "raw_name": shot.name,
            "raw_size": shot.size, "raw_mtime_ns": shot.mtime_ns, "reason": code, "message": message}
        if problem:
            event["problem"] = problem
        send(event)

    def unfinished_or_damaged(shot: _Shot, code: str, message: str) -> None:
        """A file failing the format checks: damaged once unmodified for DAMAGED_SECONDS by its mtime and
        since this computer first saw it so, else waiting. ``--once`` (one look, no history) goes by the
        mtime alone, so it wants ONCE_SETTLE_SECONDS, as its settle rule does (Q23.7), and never less than
        two looks."""
        age = now - shot.mtime_ns / 1e9
        limit = max(ONCE_SETTLE_SECONDS, DAMAGED_SECONDS)
        if seen is not None:
            age, limit = min(age, now - seen_since(shot)), DAMAGED_SECONDS
        if age >= limit:
            refuse(shot, DAMAGED, f"Damaged: {message} (unchanged for {age:,.0f} s)", code)
        else:
            wait(shot, code, message)

    for shot in raws:
        stat = (shot.size, shot.mtime_ns)
        if skip.get(shot.name) == stat:
            unconvertible.append(shot.entry)
            continue
        if done.get(shot.name) == stat and redo != "always" and shot.shot in there:
            current.append(shot.entry)
            continue
        if kept_before.get(shot.name) == stat and shot.shot in there:
            kept.append(shot.entry)
            continue
        # A current TXY needs no read, so it is told apart first (a folder's first conversion
        # finds its converted shots current rather than waiting).
        txy_size: int | None
        if beside:
            there_now = beside_txy.get(shot.shot)
            txy_size = None if there_now is None else there_now[0]
            why = "no TXY" if there_now is None else provenance.beside_stale(shot.mtime_ns, there_now[1])
        else:
            try:
                info = os.stat(os.path.join(places["folder"], provenance.txy_name(tag, shot.shot)))
                txy_size, txy_now = info.st_size, (info.st_size, info.st_mtime_ns)
            except OSError:
                txy_size, txy_now = None, None
            why = provenance.stale(records.get((tag, shot.shot)), raw_size=shot.size, raw_mtime_ns=shot.mtime_ns,
                                   profile_hash=profile_hash, txy=txy_now)
        if why is None and redo != "always":
            current.append(shot.entry)
            continue
        if beside and txy_size is not None:
            kept.append(shot.entry)
            send({"kind": "shot_kept", "path": path, "shot": shot.shot,
                  "txy": os.path.join(path, provenance.txy_name(tag, shot.shot)),
                  "reason": f"{why or 'converted again on request'}; a TXY in a source folder is never replaced"})
            continue
        if skewed and shot.mtime_ns / 1e9 > now + fingerprints.FUTURE_SECONDS:
            wait(shot, raw.FUTURE, f"Dated {shot.mtime_ns / 1e9 - now:.0f} s ahead of this computer's clock: "
                 "the computers' clocks differ, so it waits until that time has passed")
            continue
        if not raw.settled_by_age(shot.mtime_ns, now, settle):
            wait(shot, raw.SETTLING, f"Modified within {settle:g} s: may still be being written")
            continue
        if seen is not None and seen.get(shot.name) != stat:
            wait(shot, raw.CHANGED, "Not seen with this size and date at the previous check: checked again at the next"
                 if shot.name not in seen else "Its size or date changed since the previous check")
            continue
        if shot.name in unfinished and unfinished[shot.name][0] == stat:
            # Read before and found unfinished, and unchanged since: still so, without reading it again
            # (or damaged by now).
            unfinished_or_damaged(shot, *unfinished[shot.name][1:])
            continue
        shot.replaced = "" if txy_size is None else (why or "converted again on request")
        todo.append(shot)

    workers = max(1, int(request.get("workers") or DEFAULT_WORKERS))
    single_large = len(todo) == 1 and todo[0].size >= SPLIT_BYTES
    workers = max(1, min(workers, len(todo))) if not single_large else workers
    send({"kind": "convert_plan", "path": path, **places, "profile": profile_info, "backend": backend,
          "workers": workers, "raw": len(raws), "todo": len(todo)})
    index: provenance.TxyIndex | None = None
    if todo:
        if not beside:
            try:
                os.makedirs(places["folder"], exist_ok=True)
            except OSError as exc:
                if (too_long := path_too_long(exc, places["folder"])) is not None:
                    raise OSError(too_long) from exc  # (The whole folder's error, said plainly.)
                raise
        _remove_own_partials(path, places["folder"], send)
        index = provenance.open_index(root, write=True, journal=journal_for(os.path.dirname(root)))
    index_path = os.path.join(root, provenance.INDEX_NAME)

    converted = 0
    handled = 0
    raw_bytes = 0
    last_progress = 0.0

    def progress(force: bool = False) -> None:
        nonlocal last_progress
        if force or time.monotonic() - last_progress >= PROGRESS_INTERVAL:
            last_progress = time.monotonic()
            send({"kind": "convert_progress", "path": path, "done": handled, "todo": len(todo),
                  "converted": converted, "raw_bytes": raw_bytes})

    def fenced() -> bool:
        """A Clear has set another fence token since this conversion started (False when unread now:
        each write checks it again)."""
        if fence is None or index is None:
            return False
        try:
            return index.fence() != fence
        except sqlite3.Error:
            return False

    def finish(shot: _Shot, data: bytes, read_seconds: float, result: Converted | BaseException) -> None:
        nonlocal converted, handled, cleared
        handled += 1
        if cleared:
            wait(shot, CLEARED, CLEARED_TEXT)
        elif isinstance(result, NoRowsError):
            refuse(shot, raw.NO_ROWS, f"The raw file has no rows: {result}")
        elif isinstance(result, BaseException):
            refuse(shot, "failed", f"Conversion failed: {type(result).__name__}: {result}")
        else:
            write_started = time.perf_counter()
            target = os.path.join(places["txy_folder"], provenance.txy_name(tag, shot.shot))
            seconds: ConvertSeconds = {"read": read_seconds, "parse": result.parse_seconds,
                                       "reconstruct": result.reconstruct_seconds, "format": result.format_seconds,
                                       "write": 0.0}
            record = provenance.Provenance(
                shot=shot.shot, raw_name=shot.name,
                raw_size=shot.size, raw_mtime_ns=shot.mtime_ns, raw_sha256=hashlib.sha256(data).hexdigest(),
                profile_name=profile.name, profile_version=profile.version, profile_hash=profile_hash,
                profile_tag=tag, profile_calibrated=profile.calibrated, backend=backend, output=places["output"],
                txy_name=provenance.txy_name(tag, shot.shot), txy_size=len(result.txy), txy_mtime_ns=0,
                txy_sha256=hashlib.sha256(result.txy).hexdigest(), hits=result.hits, converted_at=time.time(),
                helab_version=__version__, read_seconds=read_seconds, parse_seconds=result.parse_seconds,
                reconstruct_seconds=result.reconstruct_seconds, format_seconds=result.format_seconds,
                write_seconds=0.0)
            assert index is not None
            written: list[provenance.Provenance] = []

            def pin(info: os.stat_result) -> None:
                """The row first, naming the very file about to be renamed in (its size and mtime): a
                quick check that sees the folder changed finds it, and stopped before the rename, the
                row matches no TXY there, so the shot is converted again."""
                assert index is not None
                pinned = dataclasses.replace(record, txy_size=info.st_size, txy_mtime_ns=info.st_mtime_ns)
                index.record(folder_name, places["key"], path, pinned, time.time(), fence=fence)
                written.append(pinned)
                if fence is not None:
                    # The rename alone under the index's lock, the token checked again: a Clear's comes
                    # before (refused here) or after it (and finds the TXY).
                    index.hold(fence)

            assert index is not None
            if beside:
                _guard(target)
            try:
                try:
                    txy.write_atomic(target, result.txy, replace=not beside, before_rename=pin,
                                     after_rename=index.release)
                finally:
                    index.release()  # (Refused or failed before the rename: let go all the same.)
            except BaseException as exc:
                if written:
                    # Its row goes, unless another conversion has written its own since: then that one stands.
                    with contextlib.suppress(OSError):
                        index.forget(folder_name, written[0])
                if isinstance(exc, provenance.Cleared) or (isinstance(exc, FileNotFoundError) and fenced()):
                    # (Refused by the fence; or a Clear meanwhile took this write's temporary file.)
                    cleared = True
                    wait(shot, CLEARED, CLEARED_TEXT)
                    progress()
                    return
                if (too_long := path_too_long(exc, target)) is not None:
                    refuse(shot, "failed", too_long)  # (Not converted again while unchanged: Q23.6.)
                    progress()
                    return
                if not (beside and isinstance(exc, FileExistsError)):
                    raise
                # (Another conversion wrote it since the listing; it stays.)
                kept.append(shot.entry)
                send({"kind": "shot_kept", "path": path, "shot": shot.shot, "txy": target,
                      "reason": "written by another conversion meanwhile; a TXY in a source folder is never "
                                "replaced"})
                progress()
                return
            if beside:
                _trace("write", target, "convert: TXY beside", bytes=len(result.txy))
            seconds["write"] = time.perf_counter() - write_started
            converted += 1
            current.append(shot.entry)
            if raw_rows is not None:
                raw_rows.add(shot.shot, shot.name, shot.size, shot.mtime_ns, data, read_at.get(shot.shot, time.time()))
            send({"kind": "shot_converted", "path": path, "shot": shot.shot, "raw_name": shot.name,
                  "raw_size": shot.size, "raw_mtime_ns": shot.mtime_ns, "raw_sha256": record.raw_sha256,
                  "output": places["output"], "txy": target, "txy_size": len(result.txy), "provenance": index_path,
                  "hits": result.hits, "replaced": shot.replaced, "profile": profile_info, "backend": backend,
                  "seconds": seconds})
        progress()

    read_at: dict[int, float] = {}

    def read(shot: _Shot) -> tuple[bytes, float] | None:
        """The shot's bytes and read time, or None when it waits (sent here)."""
        nonlocal handled, raw_bytes, cleared
        cleared = cleared or fenced()
        if cleared:
            handled += 1
            wait(shot, CLEARED, CLEARED_TEXT)
            return None
        read_started = time.perf_counter()
        reader = Heartbeat(send, "reading")
        read_at[shot.shot] = time.time()
        try:
            data = _read_raw(shot, reader)
        except OSError as exc:
            handled += 1
            wait(shot, "read_failed", f"Couldn't be read: {exc}")
            return None
        if isinstance(data, str):
            handled += 1
            wait(shot, data, "Its size or date changed while it was read")
            return None
        raw_bytes += len(data)
        problem = raw.not_done(data, profile.channel_trigger)
        if problem is not None:
            handled += 1
            unfinished_or_damaged(shot, *problem)
            return None
        return data, time.perf_counter() - read_started

    pool = _Pool(workers, numba_folder) if workers > 1 and todo else None
    try:
        if pool is None or single_large:
            for shot in todo:
                Pause.checkpoint(send)
                got = read(shot)
                if got is None:
                    progress()
                    continue
                data, read_seconds = got
                outcome: Converted | BaseException
                try:
                    with _Ticker(send, "converting", compute_budget(len(data))):
                        outcome = convert_shot(data, profile, backend,
                                               executor=pool.executor if pool is not None else None,
                                               max_pieces=workers if pool is not None else None)
                except Exception as exc:  # (A failed shot is reported; the next one is tried.)
                    outcome = exc
                finish(shot, data, read_seconds, outcome)
        else:
            _convert_in_pool(pool, todo, read, finish, progress, request["profile"], backend, workers, send)
    finally:
        if pool is not None:
            pool.close()
        if index is not None:
            index.close()
    if raw_rows is not None:
        raw_rows.flush()
    progress(force=True)
    send({"kind": "convert_summary", "path": path, "output": places["output"], "folder": places["folder"],
          "txy_folder": places["txy_folder"], "converted": converted, "current": current, "waiting": waiting,
          "unconvertible": unconvertible, "kept": kept, "seconds": time.monotonic() - started})


class _RawRows:
    """A conversion's raw layers (caching v2, store-v4): the shots it read and converted, saved in
    batches under one raw guard taken as it starts (``io_ops.raw_fill.save_batch``), as a ``raw_fill`` would
    have saved them. Only for a folder with a data root whose output is the cache folder or beside the raw
    files, online. It never fails the conversion: a store that can't take them (busy, a Clear since, the
    budget, Don't cache) sends one ``cache_warning`` or nothing, and the rest of this run's go unsaved."""

    def __init__(self, path: str, cache: Mapping[str, Any], guard: Any, send: Emit) -> None:
        self.path, self.cache, self.guard, self.send = path, cache, guard, send
        self.batch: list[Any] = []

    @classmethod
    def start(cls, path: str, places: _Places, request: ConvertRequest, send: Emit) -> _RawRows | None:
        from helab.utils.cache_store import StoreError, layout_of
        from helab.utils.store_v4 import LAYOUT
        cache = request.get("cache") or {}
        if (not cache or cache.get("offline") or not places["key"] or places["output"] not in ("cache", "beside")
                or layout_of(str(cache["directory"])) < LAYOUT):
            return None
        try:
            with stores._cache_store(cache["directory"], [path]) as store:
                if store.read_only:
                    return None
                return cls(path, cache, store.start_raw_job(path), send)
        except (StoreError, OSError, ValueError) as exc:
            send({"kind": "cache_warning", "message": f"Raw pulses of {path} aren't cached this time: {exc}"})
            return None

    def add(self, shot: int, name: str, size: int, mtime_ns: int, data: bytes, read_at: float) -> None:
        from helab.io_ops.raw_fill import BATCH_SHOTS, RawRead
        if self.guard is None:
            return
        self.batch.append(RawRead(shot, name, size, mtime_ns, data, read_at))
        if len(self.batch) >= BATCH_SHOTS:
            self.flush()

    def flush(self) -> None:
        from helab.io_ops.raw_fill import save_batch
        from helab.utils.cache_store import SaveRejected, StoreError
        batch, self.batch = self.batch, []
        if not batch or self.guard is None:
            return
        try:
            with stores._cache_store(self.cache["directory"], [self.path]) as store:
                result = save_batch(store, self.path, batch, self.guard, self.cache, self.send)
            if result.reason:
                self.guard = None  # (Over the budget: the rest isn't tried either, T~1.)
        except SaveRejected:
            self.guard = None  # (Cleared since, or Don't cache: nothing more this run.)
        except (StoreError, OSError, ValueError) as exc:
            self.guard = None
            self.send({"kind": "cache_warning", "message": f"Raw pulses of {self.path} weren't cached: {exc}"})


def _remove_partial(path: str, entry: os.DirEntry[str], send: Emit) -> None:
    """Remove a leftover temporary TXY of a beside write (``partial()``) once ``PARTIAL_MAX_AGE`` old:
    a regular file (a link is left alone, never followed), as the listing found it."""
    import stat
    try:
        info = _entry_stat(entry, "convert: leftover", follow_symlinks=False)
    except OSError:
        return
    age = time.time() - info.st_mtime
    if not stat.S_ISREG(info.st_mode) or age < PARTIAL_MAX_AGE:
        return
    _guard(entry.path)
    try:
        os.unlink(entry.path)
    except OSError as exc:
        _traced_error("unlink", entry.path, "convert: leftover", exc)
        return
    _trace("unlink", entry.path, "convert: leftover", age=round(age))
    send({"kind": "partial_removed", "path": path, "folder": path, "file": entry.name, "size": info.st_size,
          "age": age})


def _txy_shots(folder: str, tag: str) -> set[int]:
    """The shots with HeLab's TXY of ``tag`` in HeLab's ``folder`` (none when it can't be listed: they are
    then checked one by one)."""
    from helab.convert.provenance import parse_txy_name
    try:
        with os.scandir(folder) as entries:
            return {parsed[1] for entry in entries if (parsed := parse_txy_name(entry.name)) and parsed[0] == tag}
    except OSError:
        return set()


def _remove_own_partials(path: str, folder: str, send: Emit) -> None:
    """The same in HeLab's own folder for ``path`` (a helper killed mid-write there leaves one too;
    on Windows that is likely, the flush to disk taking most of a write), old builds' records' too
    (``own_partial()``)."""
    import stat
    try:
        entries = [entry for entry in os.scandir(folder) if own_partial().match(entry.name)]
    except OSError:
        return
    for entry in entries:
        try:
            info = entry.stat(follow_symlinks=False)
            age = time.time() - info.st_mtime
            if not stat.S_ISREG(info.st_mode) or age < PARTIAL_MAX_AGE:
                continue
            os.unlink(entry.path)
        except OSError:
            continue
        send({"kind": "partial_removed", "path": path, "folder": folder, "file": entry.name, "size": info.st_size,
              "age": age})


def still_computing(deadlines: Iterable[float], now: float) -> bool:
    """Whether heartbeats go on: some shot in flight is within its compute budget."""
    return any(now < deadline for deadline in deadlines)


def _convert_in_pool(pool: _Pool, todo: list[_Shot], read: Callable[[_Shot], tuple[bytes, float] | None],
                     finish: Callable[[_Shot, bytes, float, Converted | BaseException], None],
                     progress: Callable[[], None], profile: dict[str, Any], backend: str, workers: int,
                     send: Emit) -> None:
    """Read here, one shot after another, while the workers convert; write each as it is done.
    At most two shots per worker in flight, so memory stays bounded."""
    flight: dict[concurrent.futures.Future[Converted], tuple[_Shot, bytes, float]] = {}
    # Each shot's heartbeat deadline, from when it was handed over (``compute_budget``).
    deadlines: dict[concurrent.futures.Future[Converted], float] = {}

    def collect(block: bool) -> None:
        while flight:
            finished, _ = concurrent.futures.wait(list(flight), timeout=Heartbeat.INTERVAL if block else 0,
                                                  return_when=concurrent.futures.FIRST_COMPLETED)
            if not finished:
                if not block:
                    return
                if still_computing(deadlines.values(), time.monotonic()):
                    send({"kind": "heartbeat", "phase": "converting", "entries": len(flight)})
                continue
            for future in sorted(finished, key=lambda item: flight[item][0].shot):
                shot, data, read_seconds = flight.pop(future)
                deadlines.pop(future, None)
                error = future.exception()
                if isinstance(error, concurrent.futures.BrokenExecutor):
                    raise error  # (Not the shot's fault: the conversion fails, and is tried again.)
                finish(shot, data, read_seconds, error if error is not None else future.result())
            if not block or len(flight) < 2 * workers:
                return

    for shot in todo:
        Pause.checkpoint(send)
        got = read(shot)
        if got is None:
            progress()
        else:
            data, read_seconds = got
            future = pool.executor.submit(_worker_convert, data, profile, backend)
            flight[future] = (shot, data, read_seconds)
            deadlines[future] = time.monotonic() + compute_budget(len(data))
        collect(block=len(flight) >= 2 * workers)
    while flight:
        collect(block=True)
