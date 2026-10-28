"""Finding HeLab's own TXY for a load or Live check (Q6.6): where ``convert`` put them, current only.

``io_ops.convert`` writes a source folder's ``d_txy_helab_<N>.txy`` and its provenance
``d_txy_helab_<N>.json`` to ``folder_for(base, identity)``: base the cache folder (output ``cache``,
with a data root) or HeLab's temp folder (output ``temp``, or no data root), identity the folder's
``root://`` key or ``path:<absolute path>``; or the TXY beside the raw files (its provenance still
in that folder). A load looks in each of those folders that exists and takes a shot's HeLab TXY only
when its provenance is **current** (``provenance.stale``: the raw file and TXY as recorded, and the
profile the app converts with, ``profile_hash``; "" takes any). A shot the caller already holds from
the same TXY (same size and mtime, ``trusted``) isn't looked up again: TXY are written once.

The folders' mtimes (``folder_state``) let a quick check or a Live check see that nothing was
converted since, as the source folder's own mtime does for MATLAB's TXY (beside ones are in the
source folder's listing).
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any, Mapping

from helab.io_ops.fingerprints import _quick_mtime
from helab.io_ops.infra import _entry_stat

# The app's options in a load's payload (``txy``): ``source`` (txy_sources.SOURCES), ``profile_hash``
# ("": any), ``cache_base`` (the cache folder's parent, as convert's base; "" when the cache is off)
# and ``temps`` (HeLab's temp folder).
PROVENANCE_PATTERN = re.compile(r"^d_txy_helab_(0|[1-9][0-9]*)\.json$", re.ASCII)


@dataclass(frozen=True)
class HelabShot:
    shot: int
    file: str  # Absolute: in HeLab's folder, or beside the raw file.
    size: int
    mtime_ns: int
    profile_hash: str
    profile: dict[str, Any]  # name, version, calibrated
    converted_at: float

    @property
    def fingerprint(self) -> tuple[int, int, int]:
        return self.shot, self.size, self.mtime_ns


def folders(path: str, options: Mapping[str, Any], key: str) -> list[str]:
    """HeLab's folders that may hold this source folder's conversions, in the order looked at."""
    from helab.io_ops.convert import folder_for
    found: list[str] = []
    cache_base, temps = str(options.get("cache_base") or ""), str(options.get("temps") or "")
    by_path = "path:" + os.path.abspath(path)
    for base, identity in ((cache_base, key), (temps, key), (temps, by_path)):
        if base and identity:
            folder = folder_for(base, identity)
            if folder not in found:
                found.append(folder)
    return found


def folder_state(candidates: list[str], listed_at: float) -> list[list[Any]]:
    """``[[folder, mtime_ns]]`` of the folders that exist; mtime None when too close to now to trust
    (``_quick_mtime``): a check that finds the same list knows nothing was converted since."""
    state: list[list[Any]] = []
    for folder in candidates:
        try:
            info = os.stat(folder)  # (HeLab's own folder, not a source folder: not traced as one.)
        except (FileNotFoundError, NotADirectoryError):
            continue
        state.append([folder, _quick_mtime(info, listed_at)])
    return state


def state_unchanged(saved: Any, now: list[list[Any]]) -> bool:
    """A saved ``folder_state`` still holds (and none of its mtimes was too recent to trust)."""
    return isinstance(saved, list) and saved == now and all(entry[1] is not None for entry in now)


def find(path: str, options: Mapping[str, Any], key: str, beside: Mapping[int, os.DirEntry[str]],
         raw: Mapping[int, os.DirEntry[str]], trusted: Mapping[int, tuple[int, int, str]] | None = None,
         ) -> dict[int, HelabShot]:
    """This folder's current HeLab TXY by shot. ``beside``: the source listing's ``d_txy_helab_<N>.txy``
    entries; ``raw``: its ``d<N>.txt`` entries (a shot needs its raw file to be current);
    ``trusted``: shot → (size, mtime, origin) the caller holds."""
    from helab.convert.provenance import Provenance, ProvenanceError, stale
    from helab.utils.txy_sources import HELAB_ORIGIN
    wanted = str(options.get("profile_hash") or "")
    trusted = trusted or {}
    found: dict[int, HelabShot] = {}
    raw_stats: dict[int, tuple[int, int]] = {}

    def raw_stat(shot: int) -> tuple[int, int] | None:
        if shot not in raw_stats:
            entry = raw.get(shot)
            if entry is None:
                return None
            try:
                info = _entry_stat(entry, "helab txy: raw")
            except OSError:
                return None
            raw_stats[shot] = (info.st_size, info.st_mtime_ns)
        return raw_stats[shot]

    beside_stats: dict[int, tuple[str, int, int]] = {}
    for shot, entry in beside.items():
        try:
            info = _entry_stat(entry, "helab txy: beside")
        except OSError:
            continue
        beside_stats[shot] = (entry.path, info.st_size, info.st_mtime_ns)

    for folder in folders(path, options, key):
        records: dict[int, str] = {}
        txy_stats: dict[str, tuple[int, int]] = {}
        try:
            # HeLab's own folder (under the cache or temp folder), not a source folder: plain calls.
            with os.scandir(folder) as directory:
                for entry in directory:
                    if matched := PROVENANCE_PATTERN.fullmatch(entry.name):
                        records[int(matched.group(1))] = entry.path
                    elif entry.name.startswith("d_txy_helab_") and entry.name.endswith(".txy"):
                        try:
                            info = entry.stat()
                        except OSError:
                            continue
                        txy_stats[entry.name] = (info.st_size, info.st_mtime_ns)
        except (FileNotFoundError, NotADirectoryError):
            continue
        for shot, record_path in records.items():
            name = f"d_txy_helab_{shot}.txy"
            here = (os.path.join(folder, name), *txy_stats[name]) if name in txy_stats else None
            there = beside_stats.get(shot)
            held = trusted.get(shot)
            # Held from this very TXY: written once, its record unchanged.
            for candidate in (here, there):
                if (candidate is not None and held is not None and held[:2] == candidate[1:]
                        and held[2].startswith(HELAB_ORIGIN) and shot not in found):
                    found[shot] = HelabShot(shot, candidate[0], candidate[1], candidate[2],
                                            held[2][len(HELAB_ORIGIN):], {}, 0.0)
            if shot in found and not found[shot].profile:
                continue
            try:
                with open(record_path, "rb") as stream:
                    record = Provenance.from_json(stream.read())
            except (OSError, ProvenanceError):
                continue
            location = there if record.output == "beside" else here
            if location is None or record.shot != shot:
                continue
            stats = raw_stat(shot)
            if stats is None:
                continue
            if stale(record, raw_size=stats[0], raw_mtime_ns=stats[1],
                     profile_hash=wanted or record.profile_hash, txy_size=location[1]) is not None:
                continue
            previous = found.get(shot)
            if previous is None or previous.converted_at < record.converted_at:
                found[shot] = HelabShot(shot, location[0], location[1], location[2], record.profile_hash,
                                        {"name": record.profile_name, "version": record.profile_version,
                                         "calibrated": record.profile_calibrated}, record.converted_at)
    return found


def compose(source: str, matlab: Mapping[int, str], helab: Mapping[int, HelabShot],
            held: Mapping[int, str] | None = None) -> dict[int, tuple[str, str]]:
    """Each shot's TXY for ``source``: shot → (file, origin). ``matlab``: MATLAB's TXY by shot;
    ``held``: the origin of shots the caller holds (kept while that TXY is there, ``choose``)."""
    from helab.utils.txy_sources import MATLAB, choose, helab_origin
    chosen: dict[int, tuple[str, str]] = {}
    for shot in sorted(set(matlab) | set(helab)):
        kind = choose(source, shot in matlab, shot in helab, (held or {}).get(shot))
        if kind == MATLAB:
            chosen[shot] = (matlab[shot], "")
        elif kind is not None:
            chosen[shot] = (helab[shot].file, helab_origin(helab[shot].profile_hash))
    return chosen


def record(source: str, origins: Mapping[int, str], helab: Mapping[int, HelabShot],
           known: Mapping[str, Any] | None, options: Mapping[str, Any], state: list[list[Any]]) -> dict[str, Any]:
    """A dataset's ``txy`` metadata: its source, its shots' origins (HeLab's only), the profiles
    they were made with (``known``: those the caller had), the profile asked for and the folders'
    state (for the next quick check)."""
    profiles = {str(key): dict(value) for key, value in (known or {}).items() if isinstance(value, Mapping)}
    for shot in helab.values():
        if shot.profile:
            profiles[shot.profile_hash] = dict(shot.profile)
    used = {origin.split(":", 1)[1] for origin in origins.values()}
    return {"source": source, "origins": {str(shot): origin for shot, origin in sorted(origins.items())},
            "profiles": {key: value for key, value in profiles.items() if key in used},
            "profile_hash": str(options.get("profile_hash") or ""), "folders": state}


def matlab_signature(fingerprint: Any, origins: Mapping[int, str]) -> str:
    """The folder's signature as a scan of it computes it (its settled MATLAB TXY), from a dataset's
    fingerprint: the tab compares the two, so HeLab's TXY in it never make the folder look changed."""
    import hashlib
    import json
    entries = [list(entry) for entry in fingerprint if int(entry[0]) not in origins]
    return hashlib.sha256(json.dumps(entries).encode()).hexdigest()


def origins_from(value: Any) -> dict[int, str]:
    """Origins from a payload's or a dataset's ``{shot: origin}`` (keys may be text, as JSON keeps them)."""
    found: dict[int, str] = {}
    if isinstance(value, Mapping):
        for shot, origin in value.items():
            try:
                found[int(shot)] = str(origin)
            except (TypeError, ValueError):
                continue
    return found


def store_key(store: Any, path: str) -> str:
    """The folder's ``root://`` key as ``convert`` finds it ("" without a store or a data root)."""
    if store is None:
        return ""
    try:
        key = str(store._path_key(path))
    except Exception:  # No data root, an unresolved mount: convert falls back to the path too.
        return ""
    return key if key.startswith("root://") else ""


def default_record(source: str = "matlab") -> dict[str, Any]:
    """The ``txy`` of data made before HeLab's TXY were looked for (MATLAB's alone)."""
    return {"source": source, "origins": {}, "profiles": {}, "profile_hash": "", "folders": []}
