"""A read-only, immutable snapshot of a loaded dataset: the one input an analysis gets.

A view is built from the ``Dataset`` a tab shows (``FolderExplorer.displayed_dataset``)
without changing the browser. It shares the dataset's arrays, never copied, and copies
only the small records around them, so a later load, check, eviction or selection change
can't alter what an analysis already received.

Each shot is handed out as a non-owning, read-only view of the shared array, and that
array and the buffers behind it are made read-only too (``read_only``), so NumPy refuses
both writes and ``setflags(write=True)``. This guards against accidents, not a security
boundary: scripts are trusted lab code, and ``.base`` still reaches the shared array.

Identity: the source folder, its data-root key when one is known, the loaded
dataset's signature (the helper's hash of the folder's MATLAB TXY fingerprints) and which TXY
it is made of (``source``, Q6.6: "" for the default, MATLAB's with HeLab's filling the shots
MATLAB lacks; ``txy_sources``). Each shot read from HeLab's TXY has its ``origins`` entry
(``helab:<profile hash>``), and results record those of the shots they cover, so data of one
source is never taken for another's. ``revision`` starts at 1
for a loaded dataset and goes up by one each time shots are added to it
(``with_shots``, for Live); results are bound to identity *and* revision (``ViewKey``).
``revise`` makes Live's next dataset of the folder the next revision of its view.

A view may have no shots: Live started before the folder's first shot.

Shot times (``shot_time``): when each shot was taken, from its raw ``d<N>.txt`` file's mtime as
the helper found it (``raw_times``). Without one (the raw file is gone, or the dataset was cached
before shot times were kept) a shot's time is its TXY file's mtime from the fingerprint, which is
when it was converted: such shots are ``fallback_times``, and plots say so. A copied or rewritten
file has a new mtime either way.
"""
from __future__ import annotations

import math
import os
import time
import weakref
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Iterable, Mapping
from urllib.parse import quote

import numpy as np
import numpy.typing as npt

from helab.utils import txy_sources
from helab.utils.file_kinds import raw_times as parse_raw_times

if TYPE_CHECKING:
    from helab.utils.folder_cache import Dataset

Events = npt.NDArray[np.float64]
# (shot, size in bytes, mtime in ns), as the helper fingerprints each TXY file.
Fingerprint = tuple[int, int, int]


@dataclass(frozen=True)
class DataRootRef:
    """The data root (``.helab-root``) a view's folder is under, as known when it was built."""
    uuid: str
    label: str
    folder: str
    key: str  # ``root://<uuid>/<relative>`` for the view's folder


@dataclass(frozen=True)
class ViewIdentity:
    source_path: str
    root_key: str  # "" when no data root is known
    signature: str  # "" when the dataset has none (e.g. a resumed partial load)
    # Which TXY (``txy_sources.identity_source``): "" for the default, else the source's name.
    source: str = ""

    @property
    def name(self) -> str:
        return os.path.basename(self.source_path.rstrip("/\\")) or self.source_path


@dataclass(frozen=True)
class ViewKey:
    """What a result is bound to: the input's identity and its revision."""
    identity: ViewIdentity
    revision: int

    def short(self) -> str:
        return f"{self.identity.name} · rev {self.revision}"


@dataclass(frozen=True)
class Provenance:
    source: str  # the load's source as the helper reported it (e.g. "disk", "memory", "merged")
    loaded_at: float | None  # wall-clock time
    checked_at: float | None  # wall-clock time of the last check against the folder; None: never
    verified: bool  # False: shown from the disk cache, not yet checked against the folder
    unsettled_files: int  # TXY files still being written, left out
    failed_files: int
    problematic: tuple[int, ...]  # shots with unreadable rows (dropped)
    cache_reason: str = ""


@dataclass(frozen=True, eq=False)
class DatasetView:
    identity: ViewIdentity
    revision: int
    shots: Mapping[int, Events]  # shot number → read-only (n, 3) T/X/Y array, ascending
    fingerprints: Mapping[int, Fingerprint]
    provenance: Provenance
    data_root: DataRootRef | None = None
    added_shots: tuple[int, ...] = ()  # the shots this revision added to the previous one
    created_at: float = field(default_factory=time.time)
    # The signature of the loaded dataset this revision is ("": the identity's, revision 1's).
    dataset_signature: str = ""
    # shot number → its raw d<N>.txt file's mtime (ns), where the helper found one.
    raw_times: Mapping[int, int] = field(default_factory=lambda: MappingProxyType({}))
    # shot number → its origin, for shots read from HeLab's TXY (``helab:<profile hash>``); MATLAB's aren't listed.
    origins: Mapping[int, str] = field(default_factory=lambda: MappingProxyType({}))
    # profile hash → {name, version, calibrated} of the HeLab TXY in it.
    txy_profiles: Mapping[str, Mapping[str, Any]] = field(default_factory=lambda: MappingProxyType({}))

    def txy_text(self) -> str:
        """Which TXY this revision is made of, for a plot's record (``txy_sources.describe``)."""
        source = self.identity.source or txy_sources.DEFAULT_SOURCE
        return txy_sources.describe(source, self.origins, self.txy_profiles, len(self.shots))

    @property
    def key(self) -> ViewKey:
        return ViewKey(self.identity, self.revision)

    @property
    def signature(self) -> str:
        """The loaded dataset's signature at this revision (Live's revisions have their own)."""
        return self.dataset_signature or self.identity.signature

    @property
    def shot_numbers(self) -> tuple[int, ...]:
        return tuple(self.shots)

    @property
    def event_count(self) -> int:
        return sum(len(array) for array in self.shots.values())

    def shot_time(self, shot: int) -> float | None:
        """When ``shot`` was taken (s since the epoch): its raw file's mtime, else its TXY file's
        (a fallback, ``fallback_times``); None if the view has neither."""
        if shot in self.raw_times:
            return self.raw_times[shot] / 1e9
        fingerprint = self.fingerprints.get(shot)
        return fingerprint[2] / 1e9 if fingerprint is not None else None

    def shot_times(self, shots: Iterable[int] | None = None) -> dict[int, float]:
        """``shot_time`` of the chosen shots (default: all) that have one, by shot."""
        times = {int(shot): self.shot_time(int(shot)) for shot in (self.shots if shots is None else shots)}
        return {shot: value for shot, value in sorted(times.items()) if value is not None}

    def fallback_times(self, shots: Iterable[int] | None = None) -> tuple[int, ...]:
        """The chosen shots (default: all) whose time is their TXY file's, not their raw file's."""
        return tuple(sorted(int(shot) for shot in (self.shots if shots is None else shots)
                            if shot not in self.raw_times and shot in self.fingerprints))

    def events(self, shots: Iterable[int] | None = None) -> Events:
        """All events of the chosen shots (default: all) as one new (n, 3) array."""
        chosen = [txy(self.shots[shot]) for shot in (self.shots if shots is None else shots)]
        return np.concatenate(chosen) if chosen else np.empty((0, 3))

    def with_shots(self, added: Mapping[int, Events],
                   fingerprints: Mapping[int, Fingerprint] | None = None, *,
                   provenance: Provenance | None = None, signature: str = "",
                   raw_times: Mapping[int, int] | None = None, origins: Mapping[int, str] | None = None,
                   txy_profiles: Mapping[str, Mapping[str, Any]] | None = None) -> DatasetView:
        """The next revision: this view plus ``added`` (new or replaced shots), same identity.
        The added arrays become shared, read-only data, as ``build_view``'s are. ``provenance``
        and ``signature``: the newer load's (default: this view's provenance, no signature).
        ``raw_times``: shot times known now; this view's are kept for shots not in ``added`` (a
        replaced shot has only the time given for it). ``origins``: the added shots' that came from
        HeLab's TXY (an added shot not in it is MATLAB's)."""
        shots = {**self.shots, **{int(shot): read_only(array) for shot, array in added.items()}}
        kinds = {**{shot: origin for shot, origin in self.origins.items() if shot not in added},
                 **{int(shot): origin for shot, origin in (origins or {}).items() if int(shot) in added}}
        prints = {**self.fingerprints, **(fingerprints or {})}
        times = {**{shot: value for shot, value in self.raw_times.items() if shot not in added},
                 **(raw_times or {})}
        return DatasetView(self.identity, self.revision + 1, _frozen(dict(sorted(shots.items()))),
                           MappingProxyType(dict(prints)), provenance or self.provenance, self.data_root,
                           tuple(sorted(int(shot) for shot in added)), dataset_signature=signature,
                           raw_times=MappingProxyType({shot: times[shot] for shot in shots if shot in times}),
                           origins=MappingProxyType({shot: kinds[shot] for shot in shots if shot in kinds}),
                           txy_profiles=MappingProxyType({**self.txy_profiles, **(txy_profiles or {})}))


def read_only(array: Events) -> Events:
    """A non-owning, read-only view of ``array`` (never a copy). ``array`` and every array
    behind it (its ``.base`` chain, e.g. the buffer ``np.load`` reads a shot into) are made
    read-only too, as shared shot data is by convention, so neither the view nor ``array``
    can be made writable again; only a deliberate ``setflags`` on the owning base can."""
    chain: Any = array
    while isinstance(chain, np.ndarray):
        if chain.flags.writeable:
            chain.setflags(write=False)
        chain = chain.base
    view = array.view()
    view.setflags(write=False)
    return view


def txy(array: Events) -> Events:
    """A shot's T/X/Y columns as (n, 3); an empty or malformed array gives no events."""
    if array.ndim == 2 and array.shape[1] >= 3:
        return array[:, :3]
    return np.empty((0, 3))


def _frozen(shots: dict[int, Events]) -> Mapping[int, Events]:
    return MappingProxyType(shots)


def root_key(folder: str, identifier: str, path: str) -> str:
    """``root://<uuid>/<relative>``, exactly as the store keys folders below a data root: each part
    of the relative path percent-quoted (``cache_paths``: ``run 1`` is ``run%201``; codebase review
    2, C-15). Records saved before used the raw parts, so a folder whose name needs quoting doesn't
    match its old arrangement or reopen record (Tony, 2026-10-26: no backward compatibility)."""
    relative = os.path.relpath(path, folder).replace(os.sep, "/")
    if relative == ".":
        return f"root://{identifier}"
    return f"root://{identifier}/" + "/".join(quote(part, safe="") for part in relative.split("/"))


def _wall_time(monotonic: Any) -> float | None:
    """FolderCache stamps checks with ``time.monotonic()``; a view keeps wall-clock times."""
    if not isinstance(monotonic, (int, float)) or not math.isfinite(monotonic):
        return None
    return time.time() - (time.monotonic() - float(monotonic))


def fingerprints_of(metadata: Mapping[str, Any]) -> dict[int, Fingerprint]:
    """Each shot's (shot, size, mtime) from a load's ``fingerprint`` list."""
    prints: dict[int, Fingerprint] = {}
    for entry in metadata.get("fingerprint") or ():
        if len(entry) >= 3:
            prints[int(entry[0])] = (int(entry[0]), int(entry[1]), int(entry[2]))
    return prints


def _provenance(metadata: Mapping[str, Any]) -> Provenance:
    loaded = metadata.get("loaded_at")
    return Provenance(
        source=str(metadata.get("source", "")),
        loaded_at=float(loaded) if isinstance(loaded, (int, float)) else None,
        checked_at=_wall_time(metadata.get("checked_at")),
        verified=bool(metadata.get("verified", True)),
        unsettled_files=int(metadata.get("unsettled_files", 0) or 0),
        failed_files=int(metadata.get("failed_files", 0) or 0),
        problematic=tuple(sorted(int(shot) for shot in metadata.get("problematic", ()) or ())),
        cache_reason=str(metadata.get("cache_reason", "") or ""))


def build_view(dataset: Dataset, root: tuple[str, str, str] | None = None) -> DatasetView:
    """A new view of ``dataset`` at revision 1. ``root`` is ``FolderCache.root_of``'s
    (folder, uuid, label), used when the load itself didn't report a data root."""
    metadata = dict(dataset.metadata)  # FolderCache may later change a few flags in place
    reported = metadata.get("data_root")
    data_root = None
    if isinstance(reported, dict) and reported.get("uuid") and reported.get("path"):
        folder, identifier, label = str(reported["path"]), str(reported["uuid"]), str(reported.get("label", ""))
        data_root = DataRootRef(identifier, label, folder, root_key(folder, identifier, dataset.path))
    elif root is not None:
        folder, identifier, label = root
        data_root = DataRootRef(identifier, label, folder, root_key(folder, identifier, dataset.path))
    shots = {int(shot): read_only(array) for shot, array in sorted(dataset.data.items())}
    identity = ViewIdentity(dataset.path, data_root.key if data_root else "", dataset.signature,
                            txy_sources.identity_source(txy_sources.source_of(metadata)))
    times = parse_raw_times(metadata.get("raw_times"))
    origins = txy_sources.origins_of(metadata)
    return DatasetView(identity, 1, _frozen(shots), MappingProxyType(fingerprints_of(metadata)),
                       _provenance(metadata), data_root,
                       raw_times=MappingProxyType({shot: times[shot] for shot in shots if shot in times}),
                       origins=MappingProxyType({shot: origins[shot] for shot in shots if shot in origins}),
                       txy_profiles=MappingProxyType(txy_sources.profiles_of(metadata)))


# One view per Dataset object, so repeated runs on the same shown data share one input.
_views: weakref.WeakKeyDictionary[Dataset, DatasetView] = weakref.WeakKeyDictionary()


def view_of(dataset: Dataset, root: tuple[str, str, str] | None = None) -> DatasetView:
    """The view of this dataset object (made once; see ``build_view``)."""
    view = _views.get(dataset)
    if view is None:
        view = _views[dataset] = build_view(dataset, root)
    return view


def revise(view: DatasetView, dataset: Dataset, root: tuple[str, str, str] | None = None) -> DatasetView:
    """``dataset``, a newer load of ``view``'s folder (Live's next), as a view: the next revision
    of ``view`` with the shots it adds or replaces (by fingerprint) or the shot times it finds, or
    ``view`` itself when it adds neither. A dataset of another folder, or one without some of ``view``'s shots, is no
    revision of it: its own view (``view_of``). From then on ``view_of(dataset)`` is this view,
    so a new run on the data shown starts from the same revision as the plots following it."""
    known = _views.get(dataset)
    if known is not None:
        return known
    data = {int(shot): array for shot, array in dataset.data.items()}
    source = txy_sources.identity_source(txy_sources.source_of(dataset.metadata))
    if dataset.path != view.identity.source_path or not set(view.shots) <= set(data) or source != view.identity.source:
        return view_of(dataset, root)
    prints = fingerprints_of(dataset.metadata)
    origins = txy_sources.origins_of(dataset.metadata)
    # A shot now from the other kind of TXY (or another profile's) is replaced too.
    added = {shot: array for shot, array in data.items()
             if shot not in view.shots or prints.get(shot, view.fingerprints.get(shot)) != view.fingerprints.get(shot)
             or origins.get(shot, "") != view.origins.get(shot, "")}
    times = parse_raw_times(dataset.metadata.get("raw_times"))
    # A check that only found times for shots already shown (an older cache's) is a revision too,
    # so plots following Live stop showing them as fallbacks.
    filled = any(times.get(shot) != view.raw_times.get(shot) for shot in view.shots if shot in times)
    revised = view if not added and not filled else view.with_shots(
        added, {shot: prints[shot] for shot in added if shot in prints},
        provenance=_provenance(dict(dataset.metadata)), signature=dataset.signature, raw_times=times,
        origins=origins, txy_profiles=txy_sources.profiles_of(dataset.metadata))
    _views[dataset] = revised
    return revised
