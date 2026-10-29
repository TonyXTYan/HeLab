"""Finding HeLab's own TXY for a load or Live check (Q6.6): where ``convert`` put them, current only.

``io_ops.convert`` writes a source folder's ``d_txy_helab_<tag>_<N>.txt`` (Q18.4: ``<tag>`` the profile's,
``profile.file_tag``) to ``folder_for(base, identity)`` and its provenance row to the base's
``converted-txy/index.sqlite`` (``provenance.TxyIndex``): base the cache folder (output ``cache``, with a
data root) or HeLab's temp folder (output ``temp``, no data root, or a Don't cache folder), identity the
folder's ``root://`` key or ``path:<absolute path>``; or the TXY beside the raw files (its row, if this
computer made it, in that index). A load asks for one profile, by its
tag and hash (``profile_tag``, ``profile_hash``; "" takes any in HeLab's folders), and takes a shot's
HeLab TXY only when it is **current**: in HeLab's folders by its provenance (``provenance.stale``: the
raw file and TXY as recorded, the profile's hash), beside the raw files by its name's tag and its date
(``provenance.beside_stale``: newer than the raw file), as any computer can tell. A shot the caller
already holds from the same TXY (same size and mtime, ``trusted``) isn't looked up again: TXY are
written once. A load that takes a TXY from a folder marks it used in the index (``LAST_USED_STEP``).
Untagged files of HeLab before Q18.4 (``d_txy_helab_<N>.txy``) are never taken.

The folders' mtimes (``folder_state``) let a quick check or a Live check see that nothing was
converted since, as the source folder's own mtime does for MATLAB's TXY (beside ones are in the
source folder's listing).
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any, Mapping

from helab.io_ops.events import ConvertedSummaryField, ConvertedUsageField
from helab.io_ops.fingerprints import _quick_mtime
from helab.io_ops.infra import _entry_stat

# A folder's ``last_used`` in the index is moved on by a load at most this often (seconds).
LAST_USED_STEP = 3600.0

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
    from helab.convert import provenance
    from helab.convert.provenance import beside_stale, parse_txy_name, stale, txy_name
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
        """Held from this very TXY (written once): taken without reading its row."""
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
        here_stats: dict[tuple[str, int], tuple[str, int, int]] = {}
        try:
            # HeLab's own folder (under the cache or temp folder), not a source folder: plain calls.
            with os.scandir(folder) as directory:
                for entry in directory:
                    parsed = parse_txy_name(entry.name)
                    if parsed is None or wanted_tag and parsed[0] != wanted_tag or only is not None and parsed[1] not in only:
                        continue
                    try:
                        info = entry.stat()
                    except OSError:
                        continue
                    here_stats[parsed] = (entry.path, info.st_size, info.st_mtime_ns)
        except (FileNotFoundError, NotADirectoryError):
            continue
        # Held ones first: their rows aren't read (none at all when every TXY here is held).
        look = sorted(tagged for tagged, here in here_stats.items()
                      if not (tagged[1] not in found and held_here(tagged[1], here)))
        look = [tagged for tagged in look if not (tagged[1] in found and not found[tagged[1]].profile)]
        if not look:
            continue
        root, name = os.path.dirname(folder), os.path.basename(folder)
        records = provenance.read_shots(root, name, tag=wanted_tag, shots={shot for _, shot in look})
        took = False
        for tag, shot in look:
            if shot in found and not found[shot].profile:
                continue
            record = records.get((tag, shot))
            # (Beside ones were judged by their date above; their rows only name them.)
            if record is None or record.output == "beside" or record.txy_name != txy_name(tag, shot):
                continue
            stats = raw_stat(shot)
            if stats is None:
                continue
            here = here_stats[(tag, shot)]
            if stale(record, raw_size=stats[0], raw_mtime_ns=stats[1],
                     profile_hash=wanted or record.profile_hash, txy=here[1:]) is not None:
                continue
            previous = found.get(shot)
            if previous is None or previous.converted_at < record.converted_at:
                found[shot] = HelabShot(shot, here[0], here[1], here[2], record.profile_hash,
                                        {"name": record.profile_name, "version": record.profile_version,
                                         "calibrated": record.profile_calibrated}, record.converted_at)
                took = True
        if took:
            _mark_used(root, name)
    return found


def _mark_used(root: str, name: str) -> None:
    """Move the folder's ``last_used`` on (at most every ``LAST_USED_STEP``); a load never fails for it."""
    import sqlite3
    import time
    from helab.convert.provenance import open_index
    index = open_index(root, write=False)
    if index is None:
        return
    try:
        index.touch(name, time.time(), LAST_USED_STEP)
    except sqlite3.Error:
        pass
    finally:
        index.close()


def could_take(source: str, raw: Mapping[int, Any], matlab: Mapping[int, Any],
               held: Mapping[int, str] | None = None) -> set[int] | None:
    """The shots ``source`` could take from HeLab's TXY, for ``find``'s ``only``: with MATLAB priority those
    MATLAB's lack, and those held from HeLab's (kept while there); every shot for the other sources (None)."""
    from helab.utils.txy_sources import MATLAB_PRIORITY
    from helab.utils.txy_sources import normal_source
    if normal_source(source) != MATLAB_PRIORITY:
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


def default_record(source: str = "") -> dict[str, Any]:
    """The ``txy`` of data made before HeLab's TXY were looked for (MATLAB's alone): its source "" (none
    named), which every source but HeLab only reads alike (``loading._helab_unchanged``)."""
    return {"source": source, "origins": {}, "profiles": {}, "profile_hash": "", "folders": []}


# HeLab's TXY under the cache and temp folders (Settings → Cache, Q27.5): outside the disk budget, and
# removed only when the user asks (Q12.3): ``converted_usage`` measures them, ``clear_converted`` removes
# them, each base through its index.

# HeLab's own files in a folder there: the TXY of the tagged names, the untagged ones before Q18.4, and the
# per-shot records and ``folder.json`` of the builds before the index (none read any more, but HeLab's:
# measured and cleared with the rest), and their leftover temporaries (``io_ops.convert.own_partial``'s).
_OWN_FILE = re.compile(r"^(?:d_txy_helab_(?:[a-z][a-z0-9]{1,15}_)?(?:0|[1-9][0-9]*)\.(?:txt|txy|json)"
                       r"|\.d_txy_helab_(?:[a-z][a-z0-9]{1,15}_)?(?:0|[1-9][0-9]*)\.(?:txt|txy|json)\.[0-9a-f]{16}"
                       r"\.partial|folder\.json|\.folder\.json\.[0-9a-f]{16}\.partial)$", re.ASCII)
_TXY_SUFFIXES = (".txt", ".txy")
_FOLDER_RECORD = "folder.json"


def converted_root(cache_directory: str) -> str:
    """``<cache folder>/converted-txy`` for the store at ``cache_directory`` (convert's base)."""
    from helab.io_ops.convert import FOLDER_NAME
    return os.path.join(os.path.dirname(os.path.abspath(cache_directory)), FOLDER_NAME)


def converted_roots(cache_directory: str, temps: str) -> dict[str, str]:
    """Each base's ``converted-txy``: ``cache`` (the store's), and ``temp`` (HeLab's temp folder) if given."""
    from helab.io_ops.convert import FOLDER_NAME
    roots = {"cache": converted_root(cache_directory)}
    if temps and os.path.normcase(os.path.abspath(os.path.join(temps, FOLDER_NAME))) != os.path.normcase(roots["cache"]):
        roots["temp"] = os.path.abspath(os.path.join(temps, FOLDER_NAME))
    return roots


def _index_files(root: str) -> tuple[list[os.DirEntry[str]], list[os.DirEntry[str]]]:
    """The index (and its journal) and indexes set aside (``provenance.SET_ASIDE_PATTERN``), regular
    files: (this HeLab's or damaged ones, a newer HeLab's). A newer HeLab's index, live or set aside, is
    never ours to clear (nor counted as ours)."""
    from helab.convert.provenance import INDEX_NAME, SCHEMA, SET_ASIDE_PATTERN, index_schema
    live_newer = (index_schema(root) or 0) > SCHEMA
    ours: list[os.DirEntry[str]] = []
    newer: list[os.DirEntry[str]] = []
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                if not entry.is_file(follow_symlinks=False):
                    continue
                if entry.name in (INDEX_NAME, INDEX_NAME + "-journal"):
                    (newer if live_newer else ours).append(entry)
                elif SET_ASIDE_PATTERN.fullmatch(entry.name):
                    (newer if entry.name.startswith("index-newer-") else ours).append(entry)
    except OSError:
        pass
    return ours, newer


def _size(entry: os.DirEntry[str]) -> int:
    try:
        return entry.stat(follow_symlinks=False).st_size
    except OSError:
        return 0


def converted_usage(root: str) -> ConvertedUsageField:
    """HeLab's TXY under ``root`` (a base's ``converted-txy``): their count and bytes (the index and old
    builds' records included), the folders holding them, when one was last used (from the index; None:
    never, or unknown), and ``newer``: the bytes of a newer HeLab's index there, which Clear leaves.
    Each file is measured by its ``stat`` (a row's size may name a file a killed write never renamed in)."""
    import sqlite3
    from helab.convert.provenance import open_index
    usage: ConvertedUsageField = {"files": 0, "bytes": 0, "folders": 0, "last_used": None, "newer": 0}
    last_used: dict[str, float] = {}
    index = open_index(root, write=False)
    if index is not None:
        try:
            last_used = {row[0]: row[4] for row in index.folders()}
        except sqlite3.Error:
            last_used = {}
        finally:
            index.close()
    try:
        folders = [entry for entry in os.scandir(root) if entry.is_dir(follow_symlinks=False)]
    except (FileNotFoundError, NotADirectoryError):
        return usage
    ours, newer = _index_files(root)
    usage["bytes"] += sum(_size(entry) for entry in ours)
    usage["newer"] = sum(_size(entry) for entry in newer)
    newest: float | None = None
    for folder in folders:
        holds = False
        try:
            with os.scandir(folder.path) as entries:
                for entry in entries:
                    if not (entry.is_file(follow_symlinks=False) and _OWN_FILE.fullmatch(entry.name)):
                        continue
                    usage["bytes"] += entry.stat(follow_symlinks=False).st_size
                    usage["files"] += int(entry.name.endswith(_TXY_SUFFIXES))
                    holds = True
        except OSError:
            continue
        if holds:
            usage["folders"] += 1
            used = last_used.get(folder.name)
            if used is not None and (newest is None or used > newest):
                newest = used
    usage["last_used"] = newest
    return usage


def converted_summary(roots: Mapping[str, str]) -> ConvertedSummaryField:
    """``converted_usage`` of each base (``bases``) and their totals: what Settings → Cache shows."""
    bases = {name: converted_usage(root) for name, root in roots.items()}
    used = [base["last_used"] for base in bases.values() if base["last_used"] is not None]
    return {"files": sum(base["files"] for base in bases.values()),
            "bytes": sum(base["bytes"] for base in bases.values()),
            "folders": sum(base["folders"] for base in bases.values()),
            "last_used": max(used) if used else None,
            "newer": sum(base["newer"] for base in bases.values()), "bases": bases}


def clear_converted(root: str) -> dict[str, int]:
    """Remove HeLab's TXY under ``root`` (the user asked, Settings → Cache): each folder's TXY with their
    rows in the index (only rows naming the very file removed), old builds' records and their leftover
    temporaries, damaged indexes set aside, never a file of another name or a link. Rows of TXY written
    beside the raw files stay (the only account of how they were made), and so does the index; an old
    record whose TXY isn't here (beside) stays too, and a folder left with its ``folder.json`` alone
    goes. A newer HeLab's index (``user_version`` above ``SCHEMA``, or set aside as ``index-newer-…``) is
    left as it is, its rows too: not ours to clear."""
    import contextlib
    from helab.convert.provenance import IndexUnavailable, SCHEMA, TXY_PATTERN, TxyIndex, index_schema, open_index
    removed = {"files": 0, "bytes": 0}
    try:
        folders = [entry.path for entry in os.scandir(root) if entry.is_dir(follow_symlinks=False)]
    except (FileNotFoundError, NotADirectoryError):
        return removed
    index: TxyIndex | None = None
    if index_schema(root) == SCHEMA:
        with contextlib.suppress(IndexUnavailable):
            index = open_index(root, write=True)
    try:
        for folder in folders:
            try:
                entries = [entry for entry in os.scandir(folder) if entry.is_file(follow_symlinks=False)
                           and _OWN_FILE.fullmatch(entry.name)]
            except OSError:
                continue
            here = {entry.name for entry in entries}
            gone: list[tuple[str, int, int]] = []
            for entry in entries:
                name = entry.name
                if name == _FOLDER_RECORD:
                    continue
                if name.endswith(".json") and not {name[:-len(".json")] + suffix for suffix in _TXY_SUFFIXES} & here:
                    continue  # An old record of a TXY beside the raw files: kept (its provenance).
                try:
                    info = entry.stat(follow_symlinks=False)
                    os.unlink(entry.path)
                except OSError:
                    continue
                removed["files"] += int(name.endswith(_TXY_SUFFIXES))
                removed["bytes"] += info.st_size
                if TXY_PATTERN.fullmatch(name):
                    gone.append((name, info.st_size, info.st_mtime_ns))
            if index is not None and gone:
                with contextlib.suppress(IndexUnavailable):
                    index.forget_removed(os.path.basename(folder), gone)
            try:
                left = os.listdir(folder)
                if left == [_FOLDER_RECORD]:
                    os.unlink(os.path.join(folder, _FOLDER_RECORD))
                if not os.listdir(folder):
                    os.rmdir(folder)
            except OSError:
                pass
    finally:
        if index is not None:
            index.close()
    from helab.convert.provenance import SET_ASIDE_PATTERN
    for entry in _index_files(root)[0]:
        if SET_ASIDE_PATTERN.fullmatch(entry.name):  # (Damaged ones; never the live index.)
            size = _size(entry)
            try:
                os.unlink(entry.path)
            except OSError:
                continue
            removed["bytes"] += size
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
