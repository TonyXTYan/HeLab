"""Compact scan outcomes; cache functions are used only by isolated helpers."""
from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict, cast

from helab.utils.cache_freshness import metadata_date
from helab.utils.cache_store import CacheStore, SaveGuard, StoreError
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
    failures: list[ScanFailure]
    starts: dict[str, int]


HISTORY_LIMIT = 10


def empty_history() -> ScanHistory:
    return {"version": 1, "sequence": 0, "revision": 0, "blocked": False,
            "last_success_at": None, "success_revision": 0,
            "failures": [], "starts": {}}


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
    history = cast(ScanHistory, {**{key: item for key, item in value.items() if key != "identity"},
        "last_success_at": metadata_date(value.get("last_success_at")),
        "starts": dict(starts), "failures": sorted(failures.values(), key=lambda f: f["revision"])[-HISTORY_LIMIT:]})
    if history["blocked"] and not history["failures"]:
        return None
    return history


def _saved(store: CacheStore, path: str) -> ScanHistory | None:
    """The saved history (empty if none), or None if malformed; a read error raises.

    An error must never look like "nothing saved", which would unblock a scan.
    """
    found = store.read_record("histories", path)
    if found.failed:
        raise StoreError(found.error)
    return parse_history(found.value)


def read_history(store: CacheStore | None, path: str) -> ScanHistory | None:
    """For display: the saved history (empty if none), or None if unreadable."""
    return None if store is None else read_histories(store, [path])[path]


def read_histories(store: CacheStore, paths: list[str]) -> dict[str, ScanHistory | None]:
    return {path: None if found.failed else parse_history(found.value)
            for path, found in store.read_records("histories", paths).items()}


class ScanSkipped(Exception):
    """A scan that is not manual found its folder blocked (or, if automatic, its history unreadable)."""

    def __init__(self, history: ScanHistory | None) -> None:
        super().__init__("Folder status check skipped")
        self.history = history


def begin_scan(store: CacheStore, path: str, operation_id: str, revision: int, guard: SaveGuard,
               *, manual: bool = True, automatic: bool = False) -> tuple[ScanHistory, int]:
    with store.transaction():
        # Decided here, under the write lock, from a read that raises on error.
        found = _saved(store, path)
        if not manual and (found["blocked"] if found is not None else automatic):
            raise ScanSkipped(found)
        # A manual or details check repairs malformed metadata; real read errors
        # still propagate.
        history = found or empty_history()
        starts = dict(history["starts"])
        issued = starts.get(operation_id, max(revision, history["sequence"] + 1))
        starts[operation_id] = issued
        starts = dict(list(starts.items())[-64:])
        updated: ScanHistory = {**history, "sequence": max(history["sequence"], issued), "starts": starts}
        store.save_record("histories", path, updated, guard)
        return updated, issued


def apply_outcome(history: ScanHistory, outcome: dict[str, Any]) -> ScanHistory:
    revision = int(outcome["revision"])
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
    return updated


def write_outcome(store: CacheStore, path: str, outcome: dict[str, Any], guard: SaveGuard) -> ScanHistory:
    with store.transaction():
        # A read error raises: an empty history would overwrite the saved failures.
        history = _saved(store, path)
        if history is None:
            raise StoreError("Saved scan history could not be read")
        history = apply_outcome(history, outcome)
        store.save_record("histories", path, history, guard)
        return history


def history_tooltip(history: ScanHistory, now: float) -> str:
    if not history["failures"]:
        return ""
    lines = ["Automatic folder status checks are skipped until a successful manual scan."
             if history["blocked"] else "Previous scan failures; a later scan succeeded."]
    success = metadata_date(history["last_success_at"])
    if success is not None:
        lines.append(f"Last successful folder status check: {datetime.fromtimestamp(success).astimezone():%Y-%m-%d %H:%M:%S %Z}")
    lines.append("Recent folder-status-check failures (newest first):")
    for failure in reversed(history["failures"]):
        date = datetime.fromtimestamp(failure["failed_at"]).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        # Scans now make one attempt; older records may count three.
        attempts = f" · {failure['attempts']} attempts" if failure["attempts"] > 1 else ""
        lines.append(f"{date} ({relative_age(now - failure['failed_at'])}){attempts} · {failure['reason']}")
    lines.append("Use Check folder status to retry. Load data remains available.")
    return "\n".join(lines)
