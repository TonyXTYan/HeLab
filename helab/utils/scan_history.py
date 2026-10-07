"""Compact scan outcomes; cache functions are used only by isolated helpers."""
from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict, cast

from helab.utils.cache_freshness import metadata_date
from helab.utils.time_format import relative_age


class ScanFailure(TypedDict):
    operation_id: str
    revision: int
    failed_at: float
    attempts: int
    reason: str
    kind: str


class ScanHistory(TypedDict):
    version: int
    sequence: int
    revision: int
    blocked: bool
    last_success_at: float | None
    success_revision: int
    identity: list[int] | None
    failures: list[ScanFailure]
    starts: dict[str, int]


HISTORY_LIMIT = 10
HISTORY_KEY = "folder-scan-history-v1"


def empty_history() -> ScanHistory:
    return {"version": 1, "sequence": 0, "revision": 0, "blocked": False,
            "last_success_at": None, "success_revision": 0, "identity": None,
            "failures": [], "starts": {}}


def folder_identity(value: object) -> list[int] | None:
    if (isinstance(value, (list, tuple)) and len(value) == 2
            and all(type(v) is int and v >= 0 for v in value)):
        return list(value)
    return None


def parse_history(value: object) -> ScanHistory | None:
    if value is None:
        return empty_history()
    if not isinstance(value, dict) or value.get("version") != 1:
        return None
    for key in ("sequence", "revision", "success_revision"):
        if type(value.get(key)) is not int or value[key] < 0:
            return None
    if not isinstance(value.get("blocked"), bool) or not isinstance(value.get("failures"), list):
        return None
    failures: dict[str, ScanFailure] = {}
    for entry in value["failures"]:
        if not isinstance(entry, dict):
            return None
        date = metadata_date(entry.get("failed_at"))
        if (not isinstance(entry.get("operation_id"), str) or date is None
                or type(entry.get("revision")) is not int or entry["revision"] < 0
                or type(entry.get("attempts")) is not int or not 1 <= entry["attempts"] <= 3
                or not isinstance(entry.get("reason"), str) or not isinstance(entry.get("kind"), str)):
            return None
        failures[entry["operation_id"]] = cast(ScanFailure, dict(entry))
    starts = value.get("starts", {})
    if not isinstance(starts, dict) or not all(isinstance(k, str) and type(v) is int and v > 0
                                              for k, v in starts.items()):
        return None
    history = cast(ScanHistory, {**value, "identity": folder_identity(value.get("identity")),
        "last_success_at": metadata_date(value.get("last_success_at")),
        "starts": dict(starts), "failures": sorted(failures.values(), key=lambda f: f["revision"])[-HISTORY_LIMIT:]})
    if history["blocked"] and not history["failures"]:
        return None
    return history


def read_history(cache: Any, path: str) -> ScanHistory | None:
    try:
        return parse_history(cache.get((HISTORY_KEY, path))) if cache is not None else None
    except Exception:
        return None


def for_identity(history: ScanHistory, identity: object) -> ScanHistory:
    observed = folder_identity(identity)
    if observed is not None and history["identity"] is not None and observed != history["identity"]:
        # A different directory at the same path owns a new history. Keep the
        # ordering counter so delayed writes for the old directory stay older.
        return {**empty_history(), "sequence": history["sequence"], "revision": history["revision"],
                "identity": observed}
    return {**history, "identity": observed} if observed is not None else history


def begin_scan(cache: Any, path: str, operation_id: str, revision: int,
               identity: object = None) -> tuple[ScanHistory, int]:
    with cache.transact():
        # A manual/source check can repair malformed metadata; real read errors
        # still propagate. Automatic checks never reach here with unknown state.
        history = parse_history(cache.get((HISTORY_KEY, path))) or empty_history()
        history = for_identity(history, identity)
        starts = dict(history["starts"])
        issued = starts.get(operation_id, max(revision, history["sequence"] + 1))
        starts[operation_id] = issued
        starts = dict(list(starts.items())[-64:])
        updated: ScanHistory = {**history, "sequence": max(history["sequence"], issued), "starts": starts}
        if not cache.set((HISTORY_KEY, path), updated):
            raise OSError("Scan history write was rejected")
        return updated, issued


def apply_outcome(history: ScanHistory, outcome: dict[str, Any]) -> ScanHistory:
    revision = int(outcome["revision"])
    identity = folder_identity(outcome.get("identity"))
    if identity is not None and history["identity"] is not None and identity != history["identity"]:
        if revision <= history["revision"] or revision < history["sequence"]:
            return history
        history = for_identity(history, identity)
    updated: ScanHistory = {**history, "sequence": max(history["sequence"], revision),
                           "failures": list(history["failures"]), "starts": dict(history["starts"])}
    if outcome["kind"] == "success":
        if revision >= history["success_revision"]:
            updated["last_success_at"] = float(outcome["at"])
            updated["success_revision"] = revision
    else:
        failure: ScanFailure = {"operation_id": str(outcome["operation_id"]), "revision": revision,
            "failed_at": float(outcome["at"]), "attempts": max(1, min(3, int(outcome["attempts"]))),
            "reason": str(outcome["reason"])[:512], "kind": str(outcome["kind"])}
        records = {f["operation_id"]: f for f in updated["failures"]}
        records[failure["operation_id"]] = failure
        updated["failures"] = sorted(records.values(), key=lambda f: f["revision"])[-HISTORY_LIMIT:]
    if revision >= history["revision"]:
        updated["revision"] = revision
        updated["blocked"] = outcome["kind"] != "success"
        if identity is not None:
            updated["identity"] = identity
    return updated


def write_outcome(cache: Any, path: str, outcome: dict[str, Any]) -> ScanHistory:
    with cache.transact():
        history = read_history(cache, path)
        if history is None:
            raise OSError("Saved scan history could not be read")
        history = apply_outcome(history, outcome)
        if not cache.set((HISTORY_KEY, path), history):
            raise OSError("Scan history write was rejected")
        return history


def history_tooltip(history: ScanHistory, now: float) -> str:
    if not history["failures"]:
        return ""
    lines = ["Automatic basic scans are skipped until a successful manual scan."
             if history["blocked"] else "Previous scan failures; a later scan succeeded."]
    success = metadata_date(history["last_success_at"])
    if success is not None:
        lines.append(f"Last successful basic scan: {datetime.fromtimestamp(success).astimezone():%Y-%m-%d %H:%M:%S %Z}")
    lines.append("Recent basic-scan failures (newest first):")
    for failure in reversed(history["failures"]):
        date = datetime.fromtimestamp(failure["failed_at"]).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        # Scans now make one attempt; older records may count three.
        attempts = f" · {failure['attempts']} attempts" if failure["attempts"] > 1 else ""
        lines.append(f"{date} ({relative_age(now - failure['failed_at'])}){attempts} · {failure['reason']}")
    lines.append("Use Basic scan / Refresh to retry. Load data remains available.")
    return "\n".join(lines)
