"""Converting a folder's raw files to HeLab's own TXY (TXY converter stage 4, ``convert``).

``convert_folder`` lists the folder once, decides for each raw file ``d<N>.txt`` (of the shots
asked for) whether it is done, waiting or to convert, converts those with a detector profile and
backend (``helab.convert``), and writes each ``d_txy_helab_<N>.txy`` atomically
(``txy.write_atomic``: a temporary name, fsync, rename) with its provenance record
(``helab.convert.provenance``) in HeLab's own folder. ``helab convert --watch`` runs this same
function in its own process (``helab.convert_cli``); the app runs it in a helper.

**Settle checks** (A10.1; 2019-halos d3667 is the evidence: MATLAB converted it 0.25 s after its
last write). A raw file is converted only when it is unmodified for ``fingerprints.SETTLE_SECONDS``
(5 s) by this computer's clock and not dated in the future; its (size, mtime) are the same at two
checks a check interval apart, the previous conversion's (the caller sends its ``waiting`` list
back as ``seen``: a file not in it waits for the next check) and this one's, and the same again
before and after it is read; it ends with a newline; and its first line is on the profile's
trigger channel (``raw.not_done``). Otherwise it waits (``shot_waiting``) and nothing is written;
it is looked at again by a later conversion, never read twice in a row as if done. The age alone
can be fooled (a source clock behind ours, a share's stale attribute cache), so the app always
sends ``seen``; only ``helab convert --once`` sends None (one check), and then a file must be
unmodified for ``ONCE_SETTLE_SECONDS`` (60 s) instead. A file dated more than
``fingerprints.FUTURE_SECONDS`` ahead waits as ``future``, and ``clock_skew`` says so once per
conversion. A settled file with no rows is unconvertible (``shot_unconvertible``, Q10.2); so is one
the converter fails on.

**Output** (Q9.3, Q9.7). ``beside`` writes the TXY next to the raw files, only when the folder's
``write_beside`` flag is on in the store (or the command line asked, ``beside_confirmed``), and
never replaces a file there (a TXY in a source folder is never modified); nothing else is written
to a source folder: the temporary name is renamed, and the provenance stays in HeLab's folder
(written before the TXY there, so a conversion stopped between them leaves a stale record, never a
TXY kept for good). A beside conversion also removes its own leftover temporary files there (a
helper killed mid-write), only those matching exactly the name ``write_atomic`` gives
(``partial()``), regular files (links aren't followed) unmodified for ``PARTIAL_MAX_AGE`` (1 h), each
sent as ``partial_removed``.
``cache`` writes under the cache folder, keyed by the folder's data root like the store
(``root://<uuid>/<relative>``); a folder without one, or with the disk cache off, goes to ``temp``
(HeLab's temp folder) and ``convert_plan`` says why (``fallback``). HeLab's folder for a source
folder is ``<base>/converted-txy/<hash of its key>/``, with ``folder.json`` naming the key and path.

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
import functools
import hashlib
import json
import os
import re
import sys
import threading
import time
from typing import Any, Callable, Iterable, NotRequired, TypedDict, TYPE_CHECKING

from helab.io_ops import fingerprints, stores
from helab.io_ops.events import ConvertProfile, ConvertSeconds, HelperEvent
from helab.io_ops.infra import Emit, Heartbeat, Pause, _entry_stat, _guard, _scandir, _trace, _traced_error, emit
from helab.utils import file_kinds

if TYPE_CHECKING:
    from multiprocessing.connection import Connection

    from helab.convert.pipeline import Converted
    from helab.convert.profile import DetectorProfile


OUTPUTS = ("cache", "temp")
FOLDER_NAME = "converted-txy"
FOLDER_RECORD = "folder.json"
READ_BLOCK = 8 * 1024 * 1024
# One shot this large (raw bytes) is cut into pieces for the pool, for Live's latency.
SPLIT_BYTES = 20 * 10**6
PROGRESS_INTERVAL = 0.25
# A single check (seen None: ``helab convert --once`` only) wants a file this long unmodified.
ONCE_SETTLE_SECONDS = 60.0
# Heartbeats while a shot computes stop after this, plus a second per COMPUTE_RATE raw bytes (ten
# times slower than the plain-Python reference): a hung backend then times out.
COMPUTE_SECONDS = 60.0
COMPUTE_RATE = 10**6
# Leftover temporary TXY of a killed beside write: removed once this old, by a beside conversion.
PARTIAL_MAX_AGE = 3600.0
# Workers when the request doesn't say: across shots in processes. A frozen app's spawned workers
# need multiprocessing.freeze_support() first in helab/main.py (there) and a check in the built
# app (the packaging floor), so it converts in-process until that is done.
DEFAULT_WORKERS = 1 if getattr(sys, "frozen", False) else max(1, min(4, (os.cpu_count() or 2) // 2))


class ConvertRequest(TypedDict):
    """The ``convert`` operation's payload (``IOService.submit(..., "convert", payload)``).

    ``profile``: ``DetectorProfile.to_dict()`` (a built-in's or the user's). ``output``: the
    setting (``cache``, default, or ``temp``). ``beside``: the app believes the folder's
    ``write_beside`` flag is on (checked again in the store here); ``beside_confirmed``: the user
    asked for beside for this run (the command line only). ``temps``: HeLab's temp folder.
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
    output: NotRequired[str]
    beside: NotRequired[bool]
    beside_confirmed: NotRequired[bool]
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
    return {"name": profile.name, "version": profile.version, "hash": profile.content_hash(),
            "calibrated": profile.calibrated}


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
    from helab.convert.provenance import TXY_PATTERN
    from helab.convert.txy import partial_pattern
    return partial_pattern(TXY_PATTERN.pattern.removeprefix("^").removesuffix("$"))


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


def _places(path: str, request: ConvertRequest) -> _Places:
    """Where this conversion writes (``convert_plan``'s fields)."""
    from helab.utils.cache_paths import UnresolvedRemotePath
    from helab.utils.cache_store import StoreError
    from helab.utils.data_roots import NoDataRoot
    output = str(request.get("output") or "cache")
    if output not in OUTPUTS:
        raise ValueError(f"Unknown converter output {output!r} (have {', '.join(OUTPUTS)})")
    cache_options = request.get("cache") or {}
    key, problem, flag, flag_problem = "", "", False, ""
    if cache_options:
        try:
            with stores._cache_store(cache_options["directory"], [path]) as store:
                key = store._path_key(path)
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
    if output == "cache" and not key:
        output = "temp"
        if beside:
            fallback = f"the provenance records go to the temp folder: {problem}"
        else:
            fallback = fallback or problem
    base = os.path.dirname(os.path.abspath(cache_options["directory"])) if output == "cache" else request["temps"]
    folder = folder_for(base, key or "path:" + os.path.abspath(path))
    return {"output": "beside" if beside else output, "fallback": fallback, "folder": folder,
            "txy_folder": path if beside else folder, "key": key}


def _stats(entries: list[list[Any]] | None) -> dict[str, tuple[int, int]]:
    """Raw files' (size, mtime) by name, from a summary's ``[name, size, mtime_ns]`` lists."""
    return {str(entry[0]): (int(entry[1]), int(entry[2])) for entry in entries or []
            if isinstance(entry, (list, tuple)) and len(entry) >= 3}


def _write_folder_record(folder: str, path: str, key: str) -> None:
    """``folder.json``: which source folder HeLab's folder stands for (rewritten when it moved)."""
    from helab.convert.txy import write_atomic
    record = os.path.join(folder, FOLDER_RECORD)
    try:
        with open(record, "rb") as stream:
            saved = json.loads(stream.read())
        if isinstance(saved, dict) and saved.get("source") == path and saved.get("key") == key:
            return
    except (OSError, ValueError):
        pass
    text = json.dumps({"helab": "converted-txy-folder", "version": 1, "key": key, "source": path,
                       "updated_at": time.time()}, indent=1) + "\n"
    write_atomic(record, text.encode("utf-8"))


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


def _current(shot: _Shot, places: _Places, profile_hash: str, txy_size: int | None) -> str | None:
    """Why the shot's TXY should be made (again), or None if it's current."""
    from helab.convert import provenance
    record: provenance.Provenance | None = None
    try:
        with open(os.path.join(places["folder"], provenance.provenance_name(shot.shot)), "rb") as stream:
            record = provenance.Provenance.from_json(stream.read())
    except (OSError, provenance.ProvenanceError):
        pass
    return provenance.stale(record, raw_size=shot.size, raw_mtime_ns=shot.mtime_ns, profile_hash=profile_hash,
                            txy_size=txy_size)


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
    from helab.convert import provenance, raw, txy
    from helab.convert.pipeline import APP_BACKEND, convert_shot
    from helab.convert.profile import DetectorProfile
    from helab.convert.reconstruct import BackendError, NoRowsError, get_backend
    started = time.monotonic()
    send = _locked(send)
    profile = DetectorProfile.from_dict(request["profile"])
    backend = str(request.get("backend") or APP_BACKEND)
    places = _places(path, request)
    numba_folder = ""
    if backend == "numba":
        cache_options = request.get("cache") or {}
        base = (os.path.dirname(os.path.abspath(cache_options["directory"])) if cache_options
                else request["temps"])
        numba_folder = os.path.join(base, "numba")
        from helab.convert.backends import numba_backend
        numba_backend.set_cache_folder(numba_folder)
    reason = get_backend(backend).unavailable(profile)
    if reason is not None:
        raise BackendError(f"Backend {backend!r} can't run: {reason}")
    profile_info = _profile_info(profile)
    profile_hash = profile_info["hash"]
    beside = places["output"] == "beside"
    wanted = None if request.get("shots") is None else {int(shot) for shot in request.get("shots") or []}

    if "seen" not in request:
        raise ValueError("A conversion needs `seen`: the previous conversion's waiting list, [] for the first")
    seen_list = request["seen"]
    seen = None if seen_list is None else _stats(seen_list)
    # Files the previous conversion read and found unfinished (no final newline, another first
    # channel): their (size, mtime), reason and message.
    unfinished = {str(entry[0]): ((int(entry[1]), int(entry[2])), str(entry[3]), str(entry[4]))
                  for entry in seen_list or [] if isinstance(entry, (list, tuple)) and len(entry) == 5
                  and entry[3] in (raw.NO_FINAL_NEWLINE, raw.NOT_TRIGGER_FIRST)}
    done, kept_before, skip = _stats(request.get("done")), _stats(request.get("kept")), _stats(request.get("skip"))
    redo = str(request.get("redo") or "stale")

    # The listing: raw files, and (beside) HeLab's TXY already there.
    raws: list[_Shot] = []
    beside_txy: dict[int, int] = {}
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
            elif kind is file_kinds.HELAB_TXY and beside:
                beside_txy[number] = _entry_stat(entry, "convert: existing TXY").st_size
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

    def wait(shot: _Shot, code: str, message: str) -> None:
        waiting.append([*shot.entry, code, message])
        send({"kind": "shot_waiting", "path": path, "shot": shot.shot, "raw_name": shot.name, "raw_size": shot.size,
              "raw_mtime_ns": shot.mtime_ns, "reason": code, "message": message})

    def refuse(shot: _Shot, code: str, message: str) -> None:
        unconvertible.append(shot.entry)
        send({"kind": "shot_unconvertible", "path": path, "shot": shot.shot, "raw_name": shot.name,
              "raw_size": shot.size, "raw_mtime_ns": shot.mtime_ns, "reason": code, "message": message})

    for shot in raws:
        stat = (shot.size, shot.mtime_ns)
        if skip.get(shot.name) == stat:
            unconvertible.append(shot.entry)
            continue
        if done.get(shot.name) == stat and redo != "always":
            current.append(shot.entry)
            continue
        if kept_before.get(shot.name) == stat:
            kept.append(shot.entry)
            continue
        # A current TXY needs no read, so it is told apart first (a folder's first conversion
        # finds its converted shots current rather than waiting).
        if beside:
            txy_size = beside_txy.get(shot.shot)
        else:
            try:
                txy_size = os.stat(os.path.join(places["folder"], provenance.txy_name(shot.shot))).st_size
            except OSError:
                txy_size = None
        why = _current(shot, places, profile_hash, txy_size)
        if why is None and redo != "always":
            current.append(shot.entry)
            continue
        if beside and txy_size is not None:
            kept.append(shot.entry)
            send({"kind": "shot_kept", "path": path, "shot": shot.shot,
                  "txy": os.path.join(path, provenance.txy_name(shot.shot)),
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
            # Read before and found unfinished, and unchanged since: still so, without reading it again.
            wait(shot, *unfinished[shot.name][1:])
            continue
        shot.replaced = "" if txy_size is None else (why or "converted again on request")
        todo.append(shot)

    workers = max(1, int(request.get("workers") or DEFAULT_WORKERS))
    single_large = len(todo) == 1 and todo[0].size >= SPLIT_BYTES
    workers = max(1, min(workers, len(todo))) if not single_large else workers
    send({"kind": "convert_plan", "path": path, **places, "profile": profile_info, "backend": backend,
          "workers": workers, "raw": len(raws), "todo": len(todo)})
    if todo:
        os.makedirs(places["folder"], exist_ok=True)
        _write_folder_record(places["folder"], path, places["key"])

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

    def finish(shot: _Shot, data: bytes, read_seconds: float, result: Converted | BaseException) -> None:
        nonlocal converted, handled
        handled += 1
        if isinstance(result, NoRowsError):
            refuse(shot, raw.NO_ROWS, f"The raw file has no rows: {result}")
        elif isinstance(result, BaseException):
            refuse(shot, "failed", f"Conversion failed: {type(result).__name__}: {result}")
        else:
            write_started = time.perf_counter()
            target = os.path.join(places["txy_folder"], provenance.txy_name(shot.shot))
            record_path = os.path.join(places["folder"], provenance.provenance_name(shot.shot))
            seconds: ConvertSeconds = {"read": read_seconds, "parse": result.parse_seconds,
                                       "reconstruct": result.reconstruct_seconds, "format": result.format_seconds,
                                       "write": 0.0}
            record = provenance.Provenance(
                shot=shot.shot, source_folder=path, source_key=places["key"], raw_name=shot.name,
                raw_size=shot.size, raw_mtime_ns=shot.mtime_ns, raw_sha256=hashlib.sha256(data).hexdigest(),
                profile_name=profile.name, profile_version=profile.version, profile_hash=profile_hash,
                profile_calibrated=profile.calibrated, backend=backend, output=places["output"],
                txy_name=provenance.txy_name(shot.shot), txy_size=len(result.txy),
                txy_sha256=hashlib.sha256(result.txy).hexdigest(), hits=result.hits, converted_at=time.time(),
                helab_version=__version__, read_seconds=read_seconds, parse_seconds=result.parse_seconds,
                reconstruct_seconds=result.reconstruct_seconds, format_seconds=result.format_seconds,
                write_seconds=0.0)
            if beside:
                # The record first: stopped before the TXY, the shot is stale (no TXY), converted
                # again; the other way round, a TXY without its record would be kept for good.
                txy.write_atomic(record_path, record.to_json().encode("utf-8"))
                _guard(target)
                try:
                    txy.write_atomic(target, result.txy, replace=False)
                except FileExistsError:
                    # (Another conversion wrote it since the listing; it stays, and the record goes.)
                    os.unlink(record_path)
                    kept.append(shot.entry)
                    send({"kind": "shot_kept", "path": path, "shot": shot.shot, "txy": target,
                          "reason": "written by another conversion meanwhile; a TXY in a source folder is never "
                                    "replaced"})
                    progress()
                    return
                _trace("write", target, "convert: TXY beside", bytes=len(result.txy))
            else:
                # The TXY first: stopped before the record, the old record no longer matches it.
                txy.write_atomic(target, result.txy)
                txy.write_atomic(record_path, record.to_json().encode("utf-8"))
            seconds["write"] = time.perf_counter() - write_started
            converted += 1
            current.append(shot.entry)
            send({"kind": "shot_converted", "path": path, "shot": shot.shot, "raw_name": shot.name,
                  "raw_size": shot.size, "raw_mtime_ns": shot.mtime_ns, "raw_sha256": record.raw_sha256,
                  "output": places["output"], "txy": target, "txy_size": len(result.txy), "provenance": record_path,
                  "hits": result.hits, "replaced": shot.replaced, "profile": profile_info, "backend": backend,
                  "seconds": seconds})
        progress()

    def read(shot: _Shot) -> tuple[bytes, float] | None:
        """The shot's bytes and read time, or None when it waits (sent here)."""
        nonlocal handled, raw_bytes
        read_started = time.perf_counter()
        reader = Heartbeat(send, "reading")
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
            (refuse if problem[0] == raw.NO_ROWS else wait)(shot, *problem)
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
    progress(force=True)
    send({"kind": "convert_summary", "path": path, "output": places["output"], "folder": places["folder"],
          "txy_folder": places["txy_folder"], "converted": converted, "current": current, "waiting": waiting,
          "unconvertible": unconvertible, "kept": kept, "seconds": time.monotonic() - started})


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
    send({"kind": "partial_removed", "path": path, "file": entry.name, "size": info.st_size, "age": age})


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
