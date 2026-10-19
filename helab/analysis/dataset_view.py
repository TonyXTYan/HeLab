"""A read-only, immutable snapshot of a loaded dataset: the one input an analysis gets.

A view is built from the ``Dataset`` a tab shows (``FolderExplorer.displayed_dataset``)
without changing the browser. It shares the dataset's arrays (read-only, never copied)
and copies only the small records around them, so a later load, check, eviction or
selection change can't alter what an analysis already received.

Identity: the source folder, its data-root key when one is known, and the loaded
dataset's signature (the helper's hash of the TXY fingerprints). ``revision`` starts at 1
for a loaded dataset and goes up by one each time shots are added to it
(``with_shots``, for Live); results are bound to identity *and* revision (``ViewKey``).
"""
from __future__ import annotations

import math
import os
import time
import weakref
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Iterable, Mapping

import numpy as np
import numpy.typing as npt

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

    @property
    def key(self) -> ViewKey:
        return ViewKey(self.identity, self.revision)

    @property
    def shot_numbers(self) -> tuple[int, ...]:
        return tuple(self.shots)

    @property
    def event_count(self) -> int:
        return sum(len(array) for array in self.shots.values())

    def events(self, shots: Iterable[int] | None = None) -> Events:
        """All events of the chosen shots (default: all) as one new (n, 3) array."""
        chosen = [txy(self.shots[shot]) for shot in (self.shots if shots is None else shots)]
        return np.concatenate(chosen) if chosen else np.empty((0, 3))

    def with_shots(self, added: Mapping[int, Events],
                   fingerprints: Mapping[int, Fingerprint] | None = None) -> DatasetView:
        """The next revision: this view plus ``added`` (new or replaced shots), same identity."""
        shots = {**self.shots, **{int(shot): read_only(array) for shot, array in added.items()}}
        prints = {**self.fingerprints, **(fingerprints or {})}
        return DatasetView(self.identity, self.revision + 1, _frozen(dict(sorted(shots.items()))),
                           MappingProxyType(dict(prints)), self.provenance, self.data_root,
                           tuple(sorted(int(shot) for shot in added)))


def read_only(array: Events) -> Events:
    """The array itself if already read-only, else a read-only view of it (never a copy)."""
    if not array.flags.writeable:
        return array
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
    """``root://<uuid>/<relative>``, as the store keys folders below a data root."""
    relative = os.path.relpath(path, folder).replace(os.sep, "/")
    return f"root://{identifier}" + ("" if relative == "." else "/" + relative)


def _wall_time(monotonic: Any) -> float | None:
    """FolderCache stamps checks with ``time.monotonic()``; a view keeps wall-clock times."""
    if not isinstance(monotonic, (int, float)) or not math.isfinite(monotonic):
        return None
    return time.time() - (time.monotonic() - float(monotonic))


def _fingerprints(metadata: Mapping[str, Any]) -> dict[int, Fingerprint]:
    prints: dict[int, Fingerprint] = {}
    for entry in metadata.get("fingerprint") or ():
        if len(entry) >= 3:
            prints[int(entry[0])] = (int(entry[0]), int(entry[1]), int(entry[2]))
    return prints


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
    loaded = metadata.get("loaded_at")
    provenance = Provenance(
        source=str(metadata.get("source", "")),
        loaded_at=float(loaded) if isinstance(loaded, (int, float)) else None,
        checked_at=_wall_time(metadata.get("checked_at")),
        verified=bool(metadata.get("verified", True)),
        unsettled_files=int(metadata.get("unsettled_files", 0) or 0),
        failed_files=int(metadata.get("failed_files", 0) or 0),
        problematic=tuple(sorted(int(shot) for shot in metadata.get("problematic", ()) or ())),
        cache_reason=str(metadata.get("cache_reason", "") or ""))
    shots = {int(shot): read_only(array) for shot, array in sorted(dataset.data.items())}
    identity = ViewIdentity(dataset.path, data_root.key if data_root else "", dataset.signature)
    return DatasetView(identity, 1, _frozen(shots), MappingProxyType(_fingerprints(metadata)),
                       provenance, data_root)


# One view per Dataset object, so repeated runs on the same shown data share one input.
_views: weakref.WeakKeyDictionary[Dataset, DatasetView] = weakref.WeakKeyDictionary()


def view_of(dataset: Dataset, root: tuple[str, str, str] | None = None) -> DatasetView:
    """The view of this dataset object (made once; see ``build_view``)."""
    view = _views.get(dataset)
    if view is None:
        view = _views[dataset] = build_view(dataset, root)
    return view
