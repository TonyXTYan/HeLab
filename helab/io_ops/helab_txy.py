"""Finding HeLab's own TXY for a load or Live check (Q6.6): where ``convert`` put them, current only.

``io_ops.convert`` writes a source folder's ``d_txy_helab_<tag>_<N>.txt`` (Q18.4: ``<tag>`` the profile's,
``profile.file_tag``) and its provenance ``d_txy_helab_<tag>_<N>.json`` to ``folder_for(base, identity)``:
base the cache folder (output ``cache``, with a data root) or HeLab's temp folder (output ``temp``, or no
data root), identity the folder's ``root://`` key or ``path:<absolute path>``; or the TXY beside the raw
files (its provenance, if this computer made it, in that folder). A load asks for one profile, by its
tag and hash (``profile_tag``, ``profile_hash``; "" takes any in HeLab's folders), and takes a shot's
HeLab TXY only when it is **current**: in HeLab's folders by its provenance (``provenance.stale``: the
raw file and TXY as recorded, the profile's hash), beside the raw files by its name's tag and its date
(``provenance.beside_stale``: newer than the raw file), as any computer can tell. A shot the caller
already holds from the same TXY (same size and mtime, ``trusted``) isn't looked up again: TXY are
written once. Untagged files of HeLab before Q18.4 (``d_txy_helab_<N>.txy``) are never taken.

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
# and ``profile_tag`` (the profile asked for; "": any, in HeLab's folders only), ``profile`` (its name,
# version and calibrated, for TXY beside the raw files that have no record here), ``cache_base`` (the
# cache folder's parent, as convert's base; "" when the cache is off) and ``temps`` (HeLab's temp folder).


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


def beside_wanted(name: str, options: Mapping[str, Any]) -> bool:
    """A source listing's ``d_txy_helab_<tag>_<N>.txt`` is of the profile asked for (its tag): only those
    are kept as the listing's beside entries, one per shot."""
    from helab.convert.provenance import parse_txy_name
    parsed = parse_txy_name(name)
    return parsed is not None and parsed[0] == str(options.get("profile_tag") or "")


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
         only: set[int] | None = None) -> dict[int, HelabShot]:
    """This folder's current HeLab TXY by shot. ``beside``: the source listing's TXY of the profile asked
    for (``beside_wanted``); ``raw``: its ``d<N>.txt`` entries (a shot needs its raw file to be current);
    ``trusted``: shot → (size, mtime, origin) the caller holds: the same TXY of the profile asked for (its
    record isn't read again: a TXY and its record are written once, and raw files are never rewritten,
    Tony 2026-10-20); ``only``: the shots the source could take from HeLab (``could_take``; None: all),
    so a check reads no record of a shot MATLAB's TXY wins."""
    from helab.convert.provenance import PROVENANCE_PATTERN, Provenance, ProvenanceError, beside_stale, stale, txy_name
    from helab.utils.txy_sources import HELAB_ORIGIN
    wanted = str(options.get("profile_hash") or "")
    wanted_tag = str(options.get("profile_tag") or "")
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
        if only is not None and shot not in only:
            continue
        try:
            info = _entry_stat(entry, "helab txy: beside")
        except OSError:
            continue
        beside_stats[shot] = (entry.path, info.st_size, info.st_mtime_ns)

    def held_here(shot: int, candidate: tuple[str, int, int] | None) -> bool:
        """Held from this very TXY (written once): taken without reading its record."""
        held = trusted.get(shot)
        if (candidate is None or held is None or held[:2] != candidate[1:] or not held[2].startswith(HELAB_ORIGIN)
                or wanted and held[2] != HELAB_ORIGIN + wanted):
            return False
        found[shot] = HelabShot(shot, candidate[0], candidate[1], candidate[2], held[2][len(HELAB_ORIGIN):], {}, 0.0)
        return True

    # Beside the raw files: the profile's tag in the name, current while newer than the raw file.
    if wanted_tag and wanted:
        for shot, there in beside_stats.items():
            if held_here(shot, there):
                continue
            stats = raw_stat(shot)
            if stats is None or beside_stale(stats[1], there[2]) is not None:
                continue
            profile = options.get("profile")
            found[shot] = HelabShot(shot, there[0], there[1], there[2], wanted,
                                    dict(profile) if isinstance(profile, Mapping) else {"name": wanted_tag},
                                    there[2] / 1e9)

    for folder in folders(path, options, key):
        records: dict[int, list[tuple[str, str]]] = {}
        txy_stats: dict[str, tuple[int, int]] = {}
        try:
            # HeLab's own folder (under the cache or temp folder), not a source folder: plain calls.
            with os.scandir(folder) as directory:
                for entry in directory:
                    if matched := PROVENANCE_PATTERN.fullmatch(entry.name):
                        if not wanted_tag or matched["tag"] == wanted_tag:
                            records.setdefault(int(matched["shot"]), []).append((matched["tag"], entry.path))
                    elif entry.name.startswith("d_txy_helab_") and entry.name.endswith(".txt"):
                        try:
                            info = entry.stat()
                        except OSError:
                            continue
                        txy_stats[entry.name] = (info.st_size, info.st_mtime_ns)
        except (FileNotFoundError, NotADirectoryError):
            continue
        for shot, tagged in records.items():
            if only is not None and shot not in only:
                continue
            for tag, record_path in tagged:
                name = txy_name(tag, shot)
                here = (os.path.join(folder, name), *txy_stats[name]) if name in txy_stats else None
                if shot not in found and held_here(shot, here):
                    continue
                if shot in found and not found[shot].profile:
                    continue
                try:
                    with open(record_path, "rb") as stream:
                        record = Provenance.from_json(stream.read())
                except (OSError, ProvenanceError):
                    continue
                # (Beside ones were judged by their date above; their records only name them.)
                if here is None or record.output == "beside" or record.shot != shot or record.profile_tag != tag:
                    continue
                stats = raw_stat(shot)
                if stats is None:
                    continue
                if stale(record, raw_size=stats[0], raw_mtime_ns=stats[1],
                         profile_hash=wanted or record.profile_hash, txy_size=here[1]) is not None:
                    continue
                previous = found.get(shot)
                if previous is None or previous.converted_at < record.converted_at:
                    found[shot] = HelabShot(shot, here[0], here[1], here[2], record.profile_hash,
                                            {"name": record.profile_name, "version": record.profile_version,
                                             "calibrated": record.profile_calibrated}, record.converted_at)
    return found


def could_take(source: str, raw: Mapping[int, Any], matlab: Mapping[int, Any],
               held: Mapping[int, str] | None = None) -> set[int] | None:
    """The shots ``source`` could take from HeLab's TXY, for ``find``'s ``only``: by default those MATLAB's
    lack, and those held from HeLab's (kept while there); every shot for the other sources (None)."""
    from helab.utils.txy_sources import MATLAB
    if source != MATLAB:
        return None
    return (set(raw) - set(matlab)) | set(held or {})


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
            # Profiles of one output share a hash (matlab-2019 and the plates today): every name is kept.
            entry = profiles.setdefault(shot.profile_hash, dict(shot.profile))
            text = f"{shot.profile.get('name', '?')} v{shot.profile.get('version', '?')}"
            names = [str(name) for name in entry.get("names") or [f"{entry.get('name', '?')} v{entry.get('version', '?')}"]]
            entry["names"] = sorted({*names, text})
    used = {origin.split(":", 1)[1] for origin in origins.values()}
    return {"source": source, "origins": {str(shot): origin for shot, origin in sorted(origins.items())},
            "profiles": {key: value for key, value in profiles.items() if key in used},
            "profile_hash": str(options.get("profile_hash") or ""),
            "profile_tag": str(options.get("profile_tag") or ""), "folders": state,
            # The root key HeLab's folders were found by (FolderCache sends it back when it knows no root).
            "key": str(options.get("key") or "")}


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


# HeLab's TXY under the cache folder (Settings → Cache): outside the disk budget, and removed only when
# the user asks (Q12.3): ``converted_usage`` measures them, ``clear_converted`` removes them.

# HeLab's own files there: the TXY and records (and their leftover temporaries) of the tagged names, and
# of the untagged ones before Q18.4 (no longer loaded, but HeLab's: measured and cleared with the rest).
_OWN_FILE = re.compile(r"^(?:d_txy_helab_(?:[a-z][a-z0-9]{1,15}_)?(?:0|[1-9][0-9]*)\.(?:txt|txy|json)"
                       r"|\.d_txy_helab_(?:[a-z][a-z0-9]{1,15}_)?(?:0|[1-9][0-9]*)\.(?:txt|txy|json)\.[0-9a-f]{16}"
                       r"\.partial|folder\.json)$", re.ASCII)
_TXY_SUFFIXES = (".txt", ".txy")


def converted_root(cache_directory: str) -> str:
    """``<cache folder>/converted-txy`` for the store at ``cache_directory`` (convert's base)."""
    from helab.io_ops.convert import FOLDER_NAME
    return os.path.join(os.path.dirname(os.path.abspath(cache_directory)), FOLDER_NAME)


def converted_usage(root: str) -> dict[str, int]:
    """HeLab's TXY files under ``root``: their count and bytes (records included), and the folders."""
    usage = {"files": 0, "bytes": 0, "folders": 0}
    try:
        folders = [entry for entry in os.scandir(root) if entry.is_dir(follow_symlinks=False)]
    except (FileNotFoundError, NotADirectoryError):
        return usage
    for folder in folders:
        usage["folders"] += 1
        try:
            with os.scandir(folder.path) as entries:
                for entry in entries:
                    if entry.is_file(follow_symlinks=False) and _OWN_FILE.fullmatch(entry.name):
                        usage["bytes"] += entry.stat(follow_symlinks=False).st_size
                        usage["files"] += int(entry.name.endswith(_TXY_SUFFIXES))
        except OSError:
            continue
    return usage


def clear_converted(root: str) -> dict[str, int]:
    """Remove HeLab's TXY under ``root`` (the user asked, Settings → Cache): each folder's TXY and their
    records, never a file of another name or a link. The record of a TXY written beside the raw files
    (no TXY of its shot here) stays: the only account of how that TXY was made; a folder left with its
    ``folder.json`` alone goes."""
    removed = {"files": 0, "bytes": 0}
    try:
        folders = [entry.path for entry in os.scandir(root) if entry.is_dir(follow_symlinks=False)]
    except (FileNotFoundError, NotADirectoryError):
        return removed
    for folder in folders:
        try:
            entries = [entry for entry in os.scandir(folder) if entry.is_file(follow_symlinks=False)
                       and _OWN_FILE.fullmatch(entry.name)]
        except OSError:
            continue
        here = {entry.name for entry in entries}
        for entry in entries:
            name = entry.name
            if name == "folder.json":
                continue
            if name.endswith(".json") and not {name[:-len(".json")] + suffix for suffix in _TXY_SUFFIXES} & here:
                continue  # The record of a TXY beside the raw files: kept (its provenance).
            try:
                size = entry.stat(follow_symlinks=False).st_size
                os.unlink(entry.path)
            except OSError:
                continue
            removed["files"] += int(name.endswith(_TXY_SUFFIXES))
            removed["bytes"] += size
        try:
            left = os.listdir(folder)
            if left == ["folder.json"]:
                os.unlink(os.path.join(folder, "folder.json"))
            if not os.listdir(folder):
                os.rmdir(folder)
        except OSError:
            pass
    return removed


def folder_print(fingerprint: Any, origins: Mapping[int, str],
                 matlab_stats: Mapping[int, tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    """The folder's MATLAB TXY as a dataset of it stands for them, for its summary and signature (Live,
    Live's saves): the data's own MATLAB shots as held or read, plus the settled MATLAB TXY of shots it
    holds from HeLab's (a scan counts those). MATLAB TXY of shots not in the data (waiting, young) are
    left out, as a load leaves out young files; a dataset of MATLAB's TXY alone keeps the signature of
    its fingerprint, as before HeLab's TXY were read."""
    from helab.io_ops.fingerprints import _settled
    own = [(int(entry[0]), int(entry[1]), int(entry[2])) for entry in fingerprint if int(entry[0]) not in origins]
    shadowed = _settled([matlab_stats[shot] for shot in sorted(origins) if shot in matlab_stats])
    return sorted(own + shadowed)
