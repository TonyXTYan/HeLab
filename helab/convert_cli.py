"""``helab convert --watch <folder>``: HeLab's converter without the GUI (Q9.5).

Watches a folder and converts its raw files to ``d_txy_helab_<tag>_<N>.txt`` as they settle, by the
same code as the app's helper (``io_ops.convert.convert_folder``, run in this process): the same
settle checks, outputs and provenance. Logs to the terminal and to HeLab's log folder; Ctrl-C
stops it between two writes (every TXY is written atomically, so none is left half-written).

    helab convert --watch FOLDER [--once] [--profile NAME|FILE.json] [--backend NAME]
                  [--output temp|cache|cache-forced|beside] [--workers N] [--interval SECONDS] [--again]

The packaged app takes the same subcommand: ``HeLab convert --watch …`` (``helab/main.py``
dispatches it before anything starts Qt widgets, caches or Dash).

``--output`` defaults to the setting (``converted_txy_output``: cache, else temp). ``beside``
writes the TXY next to the raw files for this run, the command line standing for the folder's
flag (Q9.7). A folder marked Don't cache converts to the temp folder (Q27.4: the store's flag, read
by the conversion), as with the setting's default, unless the command line asks for the cache (Q~2,
standing for the user as in Q12.4). A typed ``--output cache``: one warning names the folder and, on
a terminal, it asks once per run whether to write to the cache folder anyway (no by default: temp);
without a terminal, temp. ``--output cache-forced``: the cache folder, said in one log line naming
the folder, with no question. Its provenance rows go to the same
``converted-txy/index.sqlite`` as the app's, safely beside a running HeLab writing it too (SQLite
transactions, ``helab.convert.provenance``). It registers as a running HeLab (``cache_locks``), so no cache move runs meanwhile,
and finds the folder's data root (the nearest ``.helab-root`` at or above it) once at the start.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import Any, TYPE_CHECKING

from helab.io_ops.events import HelperEvent

if TYPE_CHECKING:
    from helab.io_ops.convert import ConvertRequest

LOG = logging.getLogger("helab.convert")
# The cache folder even for a folder marked Don't cache, without asking (Q~2; the command line only).
CACHE_FORCED = "cache-forced"
DEFAULT_INTERVAL = 3.0


def _arguments(argv: list[str]) -> argparse.Namespace:
    from helab.convert.pipeline import APP_BACKEND
    from helab.convert.profile import DEFAULT_PROFILE
    from helab.convert.reconstruct import _MODULES
    parser = argparse.ArgumentParser(
        prog="helab convert", description="Convert a folder's raw DLD files (d<N>.txt) to HeLab TXY files "
        "(d_txy_helab_<tag>_<N>.txt) as they arrive, without the GUI.")
    parser.add_argument("--watch", metavar="FOLDER", required=True, help="the folder of raw files")
    parser.add_argument("--once", action="store_true", help="convert what is there now, then exit")
    parser.add_argument("--profile", default=DEFAULT_PROFILE,
                        help=f"a built-in detector profile's name or a profile JSON file (default {DEFAULT_PROFILE})")
    parser.add_argument("--backend", default=APP_BACKEND, choices=sorted(_MODULES),
                        help=f"the converter backend (default {APP_BACKEND})")
    parser.add_argument("--output", choices=("temp", "cache", CACHE_FORCED, "beside"),
                        help="where the TXY go (default: the setting, cache unless changed). A folder marked "
                        "Don't cache goes to the temp folder; a typed --output cache asks first on a terminal "
                        f"(else temp); --output {CACHE_FORCED} writes to the cache folder without asking")
    parser.add_argument("--workers", type=int, help="processes converting at once (default: a few)")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                        help=f"seconds between checks of the folder (default {DEFAULT_INTERVAL:g})")
    parser.add_argument("--again", action="store_true",
                        help="convert every shot again, current ones too (cache and temp only)")
    args = parser.parse_args(argv)
    if args.interval <= 0 or args.workers is not None and args.workers < 1:
        parser.error("--interval must be positive and --workers at least 1")
    return args


def _profile(choice: str) -> dict[str, Any]:
    from helab.convert.profile import BUILTIN_PROFILES, DetectorProfile
    if choice in BUILTIN_PROFILES:
        return BUILTIN_PROFILES[choice].to_dict()
    with open(choice, encoding="utf-8") as file:
        return DetectorProfile.from_json(file.read()).to_dict()


def _start_cache() -> tuple[dict[str, Any], object]:
    """As the app starts: wait out another HeLab's cache move, register as a running HeLab (held
    until this process ends), and the disk cache's options ({} when it is off). A move a crash
    interrupted is left for the app to finish: the disk cache stays off for this run."""
    from helab.utils.cache_locks import startup
    from helab.utils.cache_move import read_record
    from helab.utils.cache_store import store_root
    from helab.utils.constants import app_folder, cache_dir, cache_dir_enabled, cache_dir_refused, start_cache_dir
    from helab.utils.settings_store import app_settings
    settings = app_settings()
    waited: list[bool] = []

    def wait() -> None:
        if not waited:
            LOG.info("Another HeLab is moving the cache: waiting...")
            waited.append(True)
        time.sleep(0.2)

    def recover(token: str) -> str:
        if read_record(app_folder()) is not None:
            start_cache_dir(settings, usable=False, reason="an interrupted cache move: start HeLab once to finish it")
            return "An interrupted cache move is waiting: start HeLab once to finish it. The disk cache is off meanwhile."
        start_cache_dir(settings)
        return ""
    message, instance = startup(app_folder(), recover, wait)
    if message:
        LOG.warning(message)
    if not cache_dir_enabled():
        LOG.warning("The disk cache is off: %s", cache_dir_refused() or "its folder can't be used")
        return {}, instance
    return {"directory": store_root(cache_dir())}, instance


def _discover_root(folder: str, cache: dict[str, Any], send: Any) -> None:
    """Record the nearest ``.helab-root`` at or above ``folder`` (as a listing of that folder would),
    so its TXY are keyed by the data root even if HeLab never listed it."""
    from helab.io_ops import markers
    from helab.io_ops.infra import _lstat
    from helab.utils.data_roots import MARKER_NAME
    if not cache:
        return
    current = os.path.abspath(folder)
    while True:
        try:
            _lstat(os.path.join(current, MARKER_NAME), "convert: data root")
        except OSError:
            parent = os.path.dirname(current)
            if parent == current:
                return
            current = parent
            continue
        markers._discover_root(current, True, cache, send)
        return


class _Log:
    """Helper events as log lines: each shot's outcome once (a waiting shot again only when its
    reason changes). Our own text is ASCII ("->", "..."): a console or pipe on Windows may encode
    stderr in a code page without arrows, which Python writes as ``\\u2192``."""

    def __init__(self) -> None:
        self.waiting: dict[str, str] = {}
        self.kept: set[int] = set()
        self.skewed: set[str] = set()
        self.summary: dict[str, Any] = {}  # The last ``convert_summary``.
        self.plans = 0
        # For the ``convert_done`` milestone: this run's no-hit shots, and the last line's unconvertible,
        # waiting and kept counts (None: none yet). A run that changed nothing logs none.
        self.no_hits = 0
        self.logged_counts: tuple[int, int, int] | None = None

    def __call__(self, event: HelperEvent) -> None:
        if event["kind"] == "convert_plan":
            self.plans += 1
            self.no_hits = 0
            if event["todo"] or self.plans == 1:
                profile = event["profile"]
                workers = (f"; {event['workers']} worker{'' if event['workers'] == 1 else 's'}" if event["todo"]
                           else "")
                LOG.info("%s: %d of %d raw files to convert -> %s (%s; profile %s v%d %s; backend %s%s)",
                         event["path"], event["todo"], event["raw"], event["txy_folder"], event["output"],
                         profile["name"], profile["version"], profile["hash"][:12], event["backend"], workers)
            if event["fallback"] and self.plans == 1:
                LOG.warning("Writing to %s: %s", event["output"], event["fallback"])
        elif event["kind"] == "shot_converted":
            self.waiting.pop(event["raw_name"], None)
            self.no_hits += event["hits"] == 0
            times = event["seconds"]
            seconds = times["read"] + times["parse"] + times["reconstruct"] + times["format"] + times["write"]
            LOG.info("%s -> %s: %d hit%s (%.2f s)%s", event["raw_name"], os.path.basename(event["txy"]),
                     event["hits"], "" if event["hits"] == 1 else "s", seconds,
                     f"; replaced: {event['replaced']}" if event["replaced"] else "")
        elif event["kind"] == "shot_waiting":
            if self.waiting.get(event["raw_name"]) != event["reason"]:
                self.waiting[event["raw_name"]] = event["reason"]
                LOG.info("%s waits: %s", event["raw_name"], event["message"])
        elif event["kind"] == "shot_unconvertible":
            self.waiting.pop(event["raw_name"], None)
            LOG.warning("%s can't be converted: %s", event["raw_name"], event["message"])
        elif event["kind"] == "shot_kept":
            if event["shot"] not in self.kept:
                self.kept.add(event["shot"])
                LOG.warning("Shot %d: %s kept (%s)", event["shot"], event["txy"], event["reason"])
        elif event["kind"] == "convert_summary":
            self.summary = dict(event)
            if event["converted"]:
                LOG.info("%d converted, %d current, %d waiting, %d unconvertible (%.1f s)", event["converted"],
                         len(event["current"]), len(event["waiting"]), len(event["unconvertible"]), event["seconds"])
            counts = (len(event["unconvertible"]), len(event["waiting"]), len(event["kept"]))
            if event["converted"] or self.no_hits or counts != self.logged_counts:
                from helab.utils import app_log
                app_log.milestone("convert_done", folder=event["path"], by="cli", converted=event["converted"],
                                  no_hit=self.no_hits, unconvertible=counts[0], waiting=counts[1], kept=counts[2],
                                  output=event["output"], seconds=event["seconds"])
                self.logged_counts = counts
        elif event["kind"] == "partial_removed":
            LOG.info("Removed a leftover temporary file of an interrupted conversion: %s (%d bytes, %.0f h old)",
                     os.path.join(event["folder"], event["file"]), event["size"], event["age"] / 3600)
        elif event["kind"] == "clock_skew":
            if event["location"] not in self.skewed:
                self.skewed.add(event["location"])
                LOG.warning("Files in %s are dated %.0f s ahead of this computer's clock: the clocks differ, so "
                            "those shots wait until that time has passed", event["path"], event["seconds"])
        elif event["kind"] == "convert_progress":
            LOG.debug("%d of %d done", event["done"], event["todo"])
        elif event["kind"] == "cache_warning":
            LOG.warning("%s", event["message"])
        elif event["kind"] == "root_found" or event["kind"] == "root_changed":
            LOG.info("Data root: %s", event["path"])
        elif event["kind"] == "root_duplicate":
            LOG.warning("The .helab-root at %s is also at another location: confirm it in HeLab (RAM only until "
                        "then, so these TXY go to the temp folder)", event["path"])


def _on_terminal() -> bool:
    """Whether stdin is a terminal. It is None in the windowed app (``console=False``) and when closed
    (``0<&-``); a closed file object raises ValueError."""
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except ValueError:
        return False


def _ask(question: str) -> bool:
    """Yes only for "y" or "yes"; no by default (Enter, end of input). The question goes to stderr
    with the log, so a redirected stdout doesn't hide it."""
    sys.stderr.write(question)
    sys.stderr.flush()
    return sys.stdin.readline().strip().lower() in ("y", "yes")


def _cache_anyway(folder: str, cache: dict[str, Any], forced: bool) -> bool:
    """A typed ``--output cache`` or ``cache-forced`` on a folder marked Don't cache (Q~2): one line
    naming the folder, then for ``cache`` the user's answer on a terminal (temp without one). Asked
    once, before the first check, so ``--watch`` doesn't ask again per pass or per shot."""
    from helab.io_ops import convert
    reason = convert.dont_cache(folder, cache) if cache else ""
    if not reason:
        return False
    if forced:
        LOG.warning("%s: %s; writing to the cache folder anyway (--output %s)", folder, reason, CACHE_FORCED)
        return True
    if not _on_terminal():
        LOG.warning("%s: %s; writing to the temp folder (--output %s writes to the cache folder)", folder, reason,
                    CACHE_FORCED)
        return False
    LOG.warning("%s: %s, and --output cache asks for the cache folder", folder, reason)
    return _ask("Write to the cache folder anyway? [y/N] ")


def _request(args: argparse.Namespace, folder: str, profile: dict[str, Any], cache: dict[str, Any]) -> ConvertRequest:
    from helab.utils.constants import DIR_TEMPS, read_convert_output
    from helab.utils.settings_store import app_settings
    typed = args.output
    output = "cache" if typed == CACHE_FORCED else typed or read_convert_output(app_settings())
    # --watch: the first pass only records each file (seen=[]), the second converts those unchanged
    # since. --once: one check (seen None), so a file must be unmodified for ONCE_SETTLE_SECONDS.
    request: ConvertRequest = {"path": folder, "profile": profile, "temps": DIR_TEMPS, "backend": args.backend,
                               "seen": None if args.once else [],
                               "destination": read_convert_output(app_settings()) if output == "beside" else output,
                               "cache": cache, "redo": "always" if args.again else "stale"}
    if output == "beside":
        request["beside"] = request["beside_confirmed"] = True
    # Only a typed --output cache: the setting's default leaves the folder's flag the last word.
    if typed in ("cache", CACHE_FORCED) and _cache_anyway(folder, cache, typed == CACHE_FORCED):
        request["cache_confirmed"] = True
    if args.workers:
        request["workers"] = args.workers
    return request


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s", stream=sys.stderr)
    args = _arguments(argv)
    from helab.convert.profile import ProfileError
    from helab.io_ops.convert import convert_folder
    from helab.utils import app_log
    from helab.utils.constants import app_folder
    app_log.start_log_file(app_folder())
    folder = os.path.abspath(args.watch)
    if not os.path.isdir(folder):
        LOG.error("Not a folder: %s", folder)
        return 2
    try:
        profile = _profile(args.profile)
    except (OSError, ProfileError) as exc:
        LOG.error("Profile %s: %s", args.profile, exc)
        return 2
    cache, instance = _start_cache()
    log = _Log()
    _discover_root(folder, cache, log)
    try:
        request = _request(args, folder, profile, cache)
    except KeyboardInterrupt:
        LOG.info("Stopped")
        return 0
    LOG.info("Watching %s%s (Ctrl-C stops)", folder, " once (files unmodified for a minute)" if args.once
             else f" every {args.interval:g} s (a file is converted once unchanged between two checks)")
    status = 0
    try:
        while True:
            try:
                convert_folder(folder, request, log)
            except (OSError, ValueError, RuntimeError) as exc:
                LOG.error("Conversion of %s failed: %s", folder, exc)
                if args.once:
                    status = 1
                    break
            else:
                summary = log.summary
                request["seen"] = summary.get("waiting", [])
                request["done"] = summary.get("current", [])
                request["skip"] = summary.get("unconvertible", [])
                request["kept"] = summary.get("kept", [])
                request["redo"] = "stale"
                if args.once:
                    if summary.get("waiting"):
                        LOG.info("%d raw file%s still waiting: run again later", len(summary["waiting"]),
                                 "" if len(summary["waiting"]) == 1 else "s")
                    break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        LOG.info("Stopped")
    LOG.debug("Instance lock %s released as this process ends", instance)
    return status
