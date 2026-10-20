"""Folder status from the files found: classification, the saved summary and its validation."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, TYPE_CHECKING

from helab.io_ops.events import FolderSummary
from helab.io_ops.infra import Emit, _stat
from helab.utils import file_kinds

if TYPE_CHECKING:
    from helab.utils.cache_store import CacheStore, SaveGuard


def _shots(found: dict[str, set[int]]) -> tuple[set[int], set[int]]:
    return found.get(file_kinds.RAW.name, set()), found.get(file_kinds.TXY.name, set())


def _classify(raw: set[int], txy: set[int], has_dirs: bool) -> tuple[str, int]:
    common = raw & txy
    if not raw and not txy:
        return ("unknown" if has_dirs else "nothing"), -1
    if raw == txy:
        return "ok", len(common)
    if common:
        return ("fixable" if txy <= raw else "critical" if raw <= txy else "warning"), len(common)
    return ("warning", len(raw | txy)) if not raw or not txy else ("critical", 0)


SUMMARY_STATUSES = ("ok", "warning", "critical", "fixable", "unknown", "nothing")


def _valid_summary(info: object) -> dict[str, Any]:
    """A saved folder summary if it is complete, else {}."""
    if (isinstance(info, dict) and info.get("version") == 1
            and isinstance(info.get("signature"), str)
            and info.get("status") in SUMMARY_STATUSES
            and isinstance(info.get("count"), int)
            and isinstance(info.get("scanned_at"), (float, int))
            and math.isfinite(info["scanned_at"]) and 0 < info["scanned_at"] < 253402300799
            and all(isinstance(info.get(key), int) and info[key] >= 0
                    for key in ("raw_count", "txy_count"))
            and ("files" not in info or file_kinds.valid_files(info["files"]))):
        return info
    return {}


def _summary(path: str, found: dict[str, set[int]], sizes: dict[str, int], has_dirs: bool, empty: bool,
             fingerprint: list[tuple[int, int, int]], scanned_at: float) -> FolderSummary:
    """A complete status for this folder, as a scan or load computes it."""
    folder_stat = _stat(path, "folder mtime")
    raw, txy = _shots(found)
    status, count = _classify(raw, txy, has_dirs)
    return {"kind": "status", "details": True, "status": status, "count": count, "empty": empty,
            "has_dirs": has_dirs, "scanned_at": scanned_at,
            "raw": sorted(raw), "txy": sorted(txy), "files": file_kinds.files_summary(found, sizes),
            "modified": folder_stat.st_mtime,
            "signature": hashlib.sha256(json.dumps(sorted(fingerprint)).encode()).hexdigest()}


def _valid_subtree(info: object) -> dict[str, Any]:
    """A folder's saved status derived from its subfolders (not their contents), else {}."""
    if (isinstance(info, dict) and info.get("version") == 1
            and info.get("status") in ("something", "nothing")
            and isinstance(info.get("derived_at"), (float, int))
            and math.isfinite(info["derived_at"]) and 0 < info["derived_at"] < 253402300799
            and isinstance(info.get("older"), bool)
            and all(isinstance(info.get(key), int) and info[key] >= 0 for key in ("data", "checked", "total"))):
        return info
    return {}


def _save_summary(store: CacheStore, path: str, report: Mapping[str, Any], guard: SaveGuard, send: Emit) -> None:
    # Optional persistence never turns a successful source check into a failure,
    # but a failed save is reported, not silently dropped.
    try:
        store.save_record("summaries", path, {"version": 1, **{
            key: value for key, value in report.items()
            if key not in ("kind", "details", "disk_cached", "cache_info", "raw", "txy")},
            "raw_count": len(report["raw"]), "txy_count": len(report["txy"])}, guard)
    except Exception as exc:
        send({"kind": "summary_save_failed", "message": f"Folder summary could not be saved: {exc}"})
