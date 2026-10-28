"""``helab convert --watch <folder>``: HeLab's converter without the GUI (Q9.5).

Watches a folder and converts its raw files to ``d_txy_helab_<N>.txy`` as they settle, by the
same code as the app's helper (``io_ops.convert.convert_folder``, run in this process): the same
settle checks, outputs and provenance. Logs to the terminal and to HeLab's log folder; Ctrl-C
stops it between two writes (every TXY is written atomically, so none is left half-written).

    helab convert --watch FOLDER [--once] [--profile NAME|FILE.json] [--backend NAME]
                  [--output temp|cache|beside] [--workers N] [--interval SECONDS] [--again]

The packaged app takes the same subcommand: ``HeLab convert --watch …`` (``helab/main.py``
dispatches it before anything starts Qt widgets, caches or Dash).

``--output`` defaults to the setting (``converted_txy_output``: cache, else temp). ``beside``
writes the TXY next to the raw files for this run, the command line standing for the folder's
flag (Q9.7). It registers as a running HeLab (``cache_locks``), so no cache move runs meanwhile,
and finds the folder's data root (the nearest ``.helab-root`` at or above it) once at the start.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import Any

from helab.io_ops.events import HelperEvent

LOG = logging.getLogger("helab.convert")
DEFAULT_INTERVAL = 3.0


def _arguments(argv: list[str]) -> argparse.Namespace:
    from helab.convert.pipeline import APP_BACKEND
    from helab.convert.profile import DEFAULT_PROFILE
    from helab.convert.reconstruct import _MODULES
    parser = argparse.ArgumentParser(
        prog="helab convert", description="Convert a folder's raw DLD files (d<N>.txt) to HeLab TXY files "
        "(d_txy_helab_<N>.txy) as they arrive, without the GUI.")
    parser.add_argument("--watch", metavar="FOLDER", required=True, help="the folder of raw files")
    parser.add_argument("--once", action="store_true", help="convert what is there now, then exit")
    parser.add_argument("--profile", default=DEFAULT_PROFILE,
                        help=f"a built-in detector profile's name or a profile JSON file (default {DEFAULT_PROFILE})")
    parser.add_argument("--backend", default=APP_BACKEND, choices=sorted(_MODULES),
                        help=f"the converter backend (default {APP_BACKEND})")
    parser.add_argument("--output", choices=("temp", "cache", "beside"),
                        help="where the TXY go (default: the setting, cache unless changed)")
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
            LOG.info("Another HeLab is moving the cache: waiting…")
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
    reason changes)."""

    def __init__(self) -> None:
        self.waiting: dict[str, str] = {}
        self.kept: set[int] = set()
        self.summary: dict[str, Any] = {}  # The last ``convert_summary``.
        self.plans = 0

    def __call__(self, event: HelperEvent) -> None:
        if event["kind"] == "convert_plan":
            self.plans += 1
            if event["todo"] or self.plans == 1:
                profile = event["profile"]
                LOG.info("%s: %d of %d raw files to convert → %s (%s; profile %s v%d %s; backend %s; %d worker%s)",
                         event["path"], event["todo"], event["raw"], event["txy_folder"], event["output"],
                         profile["name"], profile["version"], profile["hash"][:12], event["backend"],
                         event["workers"], "" if event["workers"] == 1 else "s")
            if event["fallback"] and self.plans == 1:
                LOG.warning("Writing to %s: %s", event["output"], event["fallback"])
        elif event["kind"] == "shot_converted":
            self.waiting.pop(event["raw_name"], None)
            times = event["seconds"]
            seconds = times["read"] + times["parse"] + times["reconstruct"] + times["format"] + times["write"]
            LOG.info("%s → %s: %d hit%s (%.2f s)%s", event["raw_name"], os.path.basename(event["txy"]),
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
        elif event["kind"] == "convert_progress":
            LOG.debug("%d of %d done", event["done"], event["todo"])
        elif event["kind"] == "cache_warning":
            LOG.warning("%s", event["message"])
        elif event["kind"] == "root_found" or event["kind"] == "root_changed":
            LOG.info("Data root: %s", event["path"])
        elif event["kind"] == "root_duplicate":
            LOG.warning("The .helab-root at %s is also at another location: confirm it in HeLab (RAM only until "
                        "then, so these TXY go to the temp folder)", event["path"])


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s", stream=sys.stderr)
    args = _arguments(argv)
    from helab.convert.profile import ProfileError
    from helab.io_ops.convert import ConvertRequest, convert_folder
    from helab.utils import app_log
    from helab.utils.constants import DIR_TEMPS, app_folder, read_convert_output
    from helab.utils.settings_store import app_settings
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
    output = args.output or read_convert_output(app_settings())
    request: ConvertRequest = {"path": folder, "profile": profile, "temps": DIR_TEMPS, "backend": args.backend,
                               "output": read_convert_output(app_settings()) if output == "beside" else output,
                               "cache": cache, "redo": "always" if args.again else "stale"}
    if output == "beside":
        request["beside"] = request["beside_confirmed"] = True
    if args.workers:
        request["workers"] = args.workers
    LOG.info("Watching %s%s (Ctrl-C stops)", folder, " once" if args.once else f" every {args.interval:g} s")
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
