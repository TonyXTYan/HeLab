"""The Qt-free parts of the RAM budget (helab/analysis/budget.py, whose notes say how it
works): its shares, what a view's shots use in RAM (``view_buffers``), a released plot's
hollow view and its restoring from a dataset (``hollow``, ``restore``), and what the budget
needs of plots and the Settings panel (``Plot``, ``Panel``) and measures (``Usage``)."""
from __future__ import annotations

import dataclasses
import weakref
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Iterable, Optional, Protocol, Sequence

import numpy as np

from helab.analysis.dataset_view import DatasetView, Events, fingerprints_of, read_only
from helab.utils import txy_sources
from helab.utils.ram_buffers import Buffers, buffers

if TYPE_CHECKING:
    from helab.utils.folder_cache import Dataset

WARN_SHARE = 0.50  # the status bar says so
DIALOG_SHARE = 0.75  # a window lists the biggest plots and folders, once per crossing
REARM_SHARE = 0.70  # ...and again only after usage has dropped below this
RELEASE_SHARE = 0.80  # plots are released, least recently viewed first, until under it
# A plot a reload drew in the last this many seconds goes after the others (no ping-pong).
RELOAD_GRACE = 10.0

_view_buffers: weakref.WeakKeyDictionary[DatasetView, Buffers] = weakref.WeakKeyDictionary()


def view_buffers(view: DatasetView) -> Buffers:
    """The memory a view's shots use (a view never changes: measured once)."""
    known = _view_buffers.get(view)
    if known is None:
        known = _view_buffers[view] = buffers(view.shots.values())
    return known


# A released plot's view keeps its shot numbers with no events: one shared, empty array.
_NO_EVENTS = read_only(np.empty((0, 3)))


def hollow(view: DatasetView) -> DatasetView:
    """``view`` without its data: the same identity, revision, shot numbers and fingerprints,
    each shot with no events. What a released plot keeps to reload exactly its shots."""
    return dataclasses.replace(view, shots=MappingProxyType({shot: _NO_EVENTS for shot in view.shots}))


@dataclass(frozen=True)
class Restored:
    """A released plot's view filled again from a dataset (``restore``)."""
    view: DatasetView
    kept: tuple[int, ...]  # shots whose fingerprints match
    changed: tuple[int, ...]  # shots the dataset has with other fingerprints (left out)
    missing: tuple[int, ...]  # shots the dataset lacks

    @property
    def asked(self) -> int:
        return len(self.kept) + len(self.changed) + len(self.missing)


def restore(view: DatasetView, dataset: Dataset, shots: Optional[Iterable[int]] = None) -> Restored:
    """``view`` (a released plot's hollow view) with each of its ``shots`` (default: all of
    them) that ``dataset`` holds with the same fingerprint, and no other shot. Shots with another
    fingerprint (rewritten since) and shots ``dataset`` lacks are left out and named."""
    prints = fingerprints_of(dataset.metadata)
    origins = txy_sources.origins_of(dataset.metadata)
    if not txy_sources.same_choice(txy_sources.metadata_choice(dataset.metadata), view.txy_choice):
        origins = {shot: "another source" for shot in view.shots}  # (Another choice's data is never its.)
    wanted = view.shots if shots is None else sorted(set(shots) & set(view.shots))
    kept: dict[int, Events] = {}
    changed: list[int] = []
    missing: list[int] = []
    for shot in wanted:
        array = dataset.data.get(shot)
        if array is None:
            missing.append(shot)
        elif prints.get(shot) != view.fingerprints.get(shot) or origins.get(shot, "") != view.origins.get(shot, ""):
            changed.append(shot)
        else:
            kept[shot] = read_only(array)
    restored = dataclasses.replace(
        view, shots=MappingProxyType(kept),
        fingerprints=MappingProxyType({shot: view.fingerprints[shot] for shot in kept if shot in view.fingerprints}))
    return Restored(restored, tuple(kept), tuple(changed), tuple(missing))


def shots_list(shots: Sequence[int], limit: int = 6) -> str:
    """``3, 7 and 12``; ``3, 7, 12, 15, 16, 20 and 4 more``."""
    named = [str(shot) for shot in shots[:limit]]
    rest = len(shots) - len(named)
    if rest:
        return f"{', '.join(named)} and {rest:,} more"
    return named[0] if len(named) == 1 else f"{', '.join(named[:-1])} and {named[-1]}"


class Plot(Protocol):
    """What the budget needs of a plot (``AnalysisInstance``)."""

    @property
    def dock_widget(self) -> Any: ...

    def ram_buffers(self) -> Buffers: ...

    def releasable(self) -> bool: ...

    def release(self, frees: Optional[int] = None) -> bool: ...

    def picture_cost(self) -> int: ...

    def recently_reloaded(self) -> bool: ...

    def ram_label(self) -> str: ...

    @property
    def is_released(self) -> bool: ...


class Panel(Protocol):
    """What the budget needs of the Settings panel (``PlotSettingsPanel``)."""

    def current_plot(self) -> Any: ...

    def recent(self) -> list[Any]: ...


@dataclass(frozen=True)
class Usage:
    datasets: int = 0  # loaded folders' data, as FolderCache counts it
    plots: int = 0  # what plots hold beyond it
    budget: int = 0

    @property
    def total(self) -> int:
        return self.datasets + self.plots

    @property
    def share(self) -> float:
        return self.total / self.budget if self.budget > 0 else 0.0
