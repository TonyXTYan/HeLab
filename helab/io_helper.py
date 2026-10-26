"""Isolated filesystem helper. Importing this module must not start Qt or Dash.

One JSON request on stdin, bounded JSON event batches on stdout. The parent may
kill this process when an OS filesystem call stalls; it never waits in the GUI.
This module is the process entry: it reads the request and dispatches it to its
operation in ``helab.io_ops``.
"""
from __future__ import annotations

import json
import sys
import time

from helab.io_ops import stores
from helab.io_ops.admin import cache_admin, cache_move_job
from helab.io_ops.browse import list_folder
from helab.io_ops.events import UnverifiedField
from helab.io_ops.fingerprints import DEFAULT_CHECK_LEVEL
from helab.io_ops.icons import folder_icons
from helab.io_ops.infra import Pause, SOURCE_GUARD, _end_trace, _guard, _isdir, _start_trace, emit
from helab.io_ops.live import live_check
from helab.io_ops.loading import load, read_cached
from helab.io_ops.results import result_find, result_save
from helab.io_ops.markers import (create_root, reassign_root, remove_root, save_marker_copy, verify_known_roots,
                                  verify_volumes)
from helab.io_ops.save_held import save_held
from helab.io_ops.scanning import save_scan_history, save_subtrees, scan
from helab.io_ops.stores import _deadline, _removed_event, _usage
from helab.io_ops.trace_check import trace_check


# Operations that need the disk cache on.
CACHE_ONLY = ("cached", "invalidate", "subtree_save", "scan_history", "cache_admin", "volumes_verify",
              "root_reassign", "root_remove", "result_find", "result_save")


# Requests acting on the source folder they name (``path``, or an icon batch's ``paths``), which
# ``_guard`` checks first under tests; the others name a folder only as a cache key.
SOURCE_OPERATIONS = frozenset({"list", "icons", "scan", "details", "load", "root_create", "root_reassign",
                               "root_remove", "marker_save"})


def main() -> None:
    started = time.monotonic()
    try:
        request = json.loads(sys.stdin.readline())
        operation = request["operation"]
        Pause.configure(request.get("control"))
        _start_trace(request)
        if operation in CACHE_ONLY and not request.get("cache"):
            raise ValueError("The disk cache is off for this session")
        if SOURCE_GUARD is not None and operation in SOURCE_OPERATIONS:
            for path in [request.get("path", ""), *request.get("paths", [])]:
                _guard(str(path))
        if operation == "drives":
            if sys.platform == "win32":
                import ctypes
                mask = ctypes.windll.kernel32.GetLogicalDrives()
                emit({"kind": "drives", "paths": [f"{chr(65 + i)}:\\" for i in range(26) if mask & (1 << i)]})
            else:
                raise OSError("Drive enumeration is only supported on Windows")
        elif operation == "resolve":
            for path in request["candidates"]:
                if path and _isdir(path, "resolve"):
                    emit({"kind": "resolved", "path": path})
                    break
            else:
                raise FileNotFoundError("No available default data folder")
        elif operation == "list":
            list_folder(request["path"], cache_options=request.get("cache"))
        elif operation == "icons":
            folder_icons(request["paths"])
        elif operation in ("scan", "details"):
            scan(request["path"], cache_options=request.get("cache"), manual=request.get("scan_manual", False),
                 automatic=request.get("automatic", False),
                 operation_id=request.get("scan_operation_id", ""), revision=request.get("scan_revision", 0))
        elif operation == "scan_history":
            save_scan_history(request["cache"], request["path"], request["outcome"], request.get("guard"),
                              verified_volumes=request.get("verified_volumes"))
        elif operation == "subtree_save":
            save_subtrees(request["cache"], request["records"],
                          verified_volumes=request.get("verified_volumes"))
        elif operation == "load" and request.get("live"):
            live_check(request["path"], request["output"], memory=request.get("memory"),
                       known=request.get("known"), since=request.get("live_since"),
                       identity=str(request.get("identity") or ""), seen=request.get("seen"),
                       check_level=str(request.get("check_level") or DEFAULT_CHECK_LEVEL),
                       listed_mtime=request.get("listed_mtime"), seen_names=request.get("seen_names"),
                       identity_root=request.get("identity_root"), recent=request.get("recent"))
        elif operation == "load" and request.get("save_memory") and request.get("held_dir"):
            save_held(request["path"], emit, request.get("cache"), request.get("held") or [],
                      request.get("held_problematic") or [], request["held_dir"],
                      identity=str(request.get("identity") or ""), identity_root=request.get("identity_root"),
                      no_cache=bool(request.get("no_cache")), recent=request.get("recent"),
                      output=request.get("output"), raw_times=request.get("held_raw_times"))
        elif operation == "load":
            load(request["path"], request["output"], cache_options=request.get("cache"),
                 memory=request.get("memory"), base_signature=request.get("base_signature", ""),
                 expected=request.get("signature", ""), limits=request.get("limits"),
                 allow_large=bool(request.get("allow_large")), no_cache=bool(request.get("no_cache")),
                 full_check=bool(request.get("full_check")), cache_base=bool(request.get("cache_base")),
                 check_level=str(request.get("check_level") or DEFAULT_CHECK_LEVEL),
                 allow_missing=bool(request.get("allow_missing")), memory_check=request.get("memory_check"),
                 memory_raw_times=request.get("memory_raw_times"))
        elif operation == "cached":
            read_cached(request["path"], request["output"], cache_options=request.get("cache"),
                        limits=request.get("limits"), allow_large=bool(request.get("allow_large")),
                        verified_volumes=request.get("verified_volumes"))
        elif operation == "result_find":
            result_find(request["path"], request["output"], request.get("cache"), str(request["lookup"]),
                        str(request.get("family") or ""), verified_volumes=request.get("verified_volumes"))
        elif operation == "result_save":
            result_save(request["path"], request.get("cache"), request["blob_file"], lookup=str(request["lookup"]),
                        family=str(request.get("family") or ""), record=request["record"],
                        analysis_id=str(request["analysis_id"]), action=str(request["action"]),
                        computed_at=float(request["computed_at"]), guard=request["guard"],
                        verified_volumes=request.get("verified_volumes"), label=str(request.get("label") or ""))
        elif operation == "invalidate":
            with stores._cache_store(request["cache"]["directory"], [request["path"]], local_lane=True,
                                     offline=bool(request["cache"].get("offline"))) as store:
                # Bumps the folder's epoch: a load started before cannot save it back.
                emit(_removed_event(store.remove(("datasets",), [request["path"]])))
                emit({"kind": "admin_result", "action": "invalidate", "next_deadline": _deadline(store),
                      **_usage(store)})
        elif operation == "cache_move":
            cache_move_job(request["move"])
        elif operation == "cache_admin":
            cache_admin(request["cache"], request["action"], **request.get("params", {}))
        elif operation == "roots_verify":
            verify_known_roots(request["cache"], volume_ids=request.get("volume_ids"))
        elif operation == "volumes_verify":
            verify_volumes(request["cache"])
        elif operation == "trace_check":
            trace_check(request["temps"], request["folder"], emit)
        elif operation == "root_create":
            create_root(request["path"], request.get("cache"))
        elif operation == "root_reassign":
            reassign_root(request["path"], request["cache"], request["old_uuid"], request["keep"])
        elif operation == "root_remove":
            remove_root(request["path"], request["cache"], request["uuid"], request.get("location", ""))
        elif operation == "marker_save":
            save_marker_copy(request["path"], request["contents"], bool(request.get("replace")))
        else:
            raise ValueError(f"Unknown operation: {operation}")
        emit({"kind": "done"})
        _end_trace(started)
    except Exception as exc:
        _end_trace(started, str(exc))
        from helab.utils.data_roots import VolumeUnverified
        unverified: UnverifiedField = {"unverified": True} if isinstance(exc, VolumeUnverified) else {}
        emit({"kind": "error", "message": str(exc), **unverified})


if __name__ == "__main__":
    main()
