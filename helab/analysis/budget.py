"""Plots count toward the RAM budget (Settings → Cache), beside the folders' data held in RAM.

The counter is the datasets ``FolderCache`` holds (as it counts them) plus each open plot's
own data: its dataset view's shot arrays and its result's arrays. Arrays are counted by the
memory they use (``buffer_of``: an array and every view of it are one), so a plot of a
dataset still held adds only what it holds beyond it, and two plots of one folder count
their shared shots once.

Shares of the budget (Tony, 2026-10-19/20): from 50 % the status bar says so; at 75 % a
window lists the biggest plots and folders, once per crossing; above 80 % plots are
released, least recently viewed first, until usage is back under 80 %. The datasets no tab
shows go first (``FolderCache.evict_to``); plots only if that isn't enough. The shown plot,
a running plot and one following Live are never released, and no plot is closed.

A released plot keeps a picture of itself (no longer interactive) with a Reload button, and
frees its view and result. It reloads from RAM (the folder's dataset still held) or the
local disk cache, never from its folder, by its shots' fingerprints (``restore``), when it is
shown again (``auto_reload``, a setting, on by default) or on Reload.
"""
from __future__ import annotations

import dataclasses
import logging
import weakref
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Iterable, Iterator, Mapping, Optional, Protocol, Sequence

import numpy as np
from PyQt6.QtCore import QObject, QSettings, QTimer, pyqtSignal

from helab.analysis.dataset_view import DatasetView, Events, read_only

if TYPE_CHECKING:
    from helab.utils.folder_cache import Dataset, FolderCache

WARN_SHARE = 0.50  # the status bar says so
DIALOG_SHARE = 0.75  # a window lists the biggest plots and folders, once per crossing
RELEASE_SHARE = 0.80  # plots are released, least recently viewed first, until under it

# Settings → Cache: a released plot reloads when it is shown again (on by default).
PLOT_AUTO_RELOAD_SETTING = "plot_auto_reload"

# The memory a set of arrays uses: an identifier of each buffer → its size in bytes.
Buffers = dict[int, int]


def read_auto_reload(settings: QSettings) -> bool:
    value = settings.value(PLOT_AUTO_RELOAD_SETTING, True)
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off", "")
    return bool(value)


def buffer_of(array: np.ndarray[Any, Any]) -> tuple[int, int]:
    """The memory ``array`` uses, as (identifier, bytes): the array at the bottom of its
    ``.base`` chain, or the buffer it was made from (``np.frombuffer``)."""
    while isinstance(array.base, np.ndarray):
        array = array.base
    owner = array.base
    if owner is None:
        return id(array), int(array.nbytes)
    while isinstance(owner, memoryview) and owner.obj is not None:
        owner = owner.obj  # The object whose memory it is (``np.frombuffer`` keeps a memoryview of it).
    try:
        size = memoryview(owner).nbytes
    except TypeError:
        size = int(array.nbytes)
    return id(owner), int(size)


def buffers(arrays: Iterable[np.ndarray[Any, Any]]) -> Buffers:
    """The memory ``arrays`` use (empty ones use none)."""
    return dict(item for item in map(buffer_of, arrays) if item[1])


def arrays_in(value: Any, depth: int = 0) -> Iterator[np.ndarray[Any, Any]]:
    """The NumPy arrays in a result's data: in dataclasses, tuples, lists, sets and mappings,
    a few levels down."""
    if isinstance(value, np.ndarray):
        if value.dtype != object:
            yield value
        return
    if depth > 6 or value is None or isinstance(value, (str, bytes, int, float, complex, bool)):
        return
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for item in dataclasses.fields(value):
            yield from arrays_in(getattr(value, item.name, None), depth + 1)
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from arrays_in(item, depth + 1)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from arrays_in(item, depth + 1)


_view_buffers: weakref.WeakKeyDictionary[DatasetView, Buffers] = weakref.WeakKeyDictionary()
_dataset_buffers: weakref.WeakKeyDictionary[Dataset, tuple[int, Buffers]] = weakref.WeakKeyDictionary()


def view_buffers(view: DatasetView) -> Buffers:
    """The memory a view's shots use (a view never changes: measured once)."""
    known = _view_buffers.get(view)
    if known is None:
        known = _view_buffers[view] = buffers(view.shots.values())
    return known


def dataset_buffers(dataset: Dataset) -> Buffers:
    """The memory a held dataset's shots use (measured again if its shots change)."""
    known = _dataset_buffers.get(dataset)
    if known is None or known[0] != len(dataset.data):
        known = _dataset_buffers[dataset] = (len(dataset.data), buffers(dataset.data.values()))
    return known[1]


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

    def lost(self, shots: Iterable[int]) -> tuple[tuple[int, ...], tuple[int, ...]]:
        """Of ``shots`` (those the plot drew), the changed and the missing ones."""
        chosen = set(shots)
        return (tuple(shot for shot in self.changed if shot in chosen),
                tuple(shot for shot in self.missing if shot in chosen))


def fingerprints_of(dataset: Dataset) -> dict[int, tuple[int, int, int]]:
    prints: dict[int, tuple[int, int, int]] = {}
    for entry in dataset.metadata.get("fingerprint") or ():
        if len(entry) >= 3:
            prints[int(entry[0])] = (int(entry[0]), int(entry[1]), int(entry[2]))
    return prints


def restore(view: DatasetView, dataset: Dataset) -> Restored:
    """``view`` (a released plot's hollow view) with each of its shots that ``dataset`` holds
    with the same fingerprint: exactly the plot's shots. Shots with another fingerprint
    (rewritten since) and shots ``dataset`` lacks are left out and named."""
    prints = fingerprints_of(dataset)
    kept: dict[int, Events] = {}
    changed: list[int] = []
    missing: list[int] = []
    for shot in view.shots:
        array = dataset.data.get(shot)
        if array is None:
            missing.append(shot)
        elif prints.get(shot) != view.fingerprints.get(shot):
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


class RamBudget(QObject):
    """Counts the plots against ``FolderCache``'s RAM budget and keeps them within 80 % of it
    (see the module's notes). Checks run a pass of the event loop after a dataset is added or
    dropped (``FolderCache.datasetChanged``), a plot's data changes (``schedule``) or the budget
    changes (``check``)."""

    changed = pyqtSignal()  # the usage or its level changed: the status bar
    warning = pyqtSignal()  # usage crossed 75 %: the window lists the biggest plots and folders
    released = pyqtSignal(int)  # plots released by one check

    def __init__(self, cache: FolderCache, panel: Optional[Panel] = None, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.cache = cache
        self.panel = panel
        self.plots: list[Plot] = []
        self.auto_reload = True
        self.usage = Usage(budget=cache.max_data_bytes)
        self._warned = False
        self._check_soon = QTimer(self)
        self._check_soon.setSingleShot(True)
        self._check_soon.setInterval(0)
        self._check_soon.timeout.connect(self.check)
        cache.ram_users.add(self)
        cache.datasetChanged.connect(self.schedule)

    def detach(self) -> None:
        """Stop counting (the window is closing)."""
        self._check_soon.stop()
        self.cache.ram_users.discard(self)
        try:
            self.cache.datasetChanged.disconnect(self.schedule)
        except TypeError:
            pass

    def add(self, plot: Plot) -> None:
        if plot not in self.plots:
            self.plots.append(plot)
        self.schedule()

    def remove(self, plot: Plot) -> None:
        if plot in self.plots:
            self.plots.remove(plot)
        self.schedule()

    def schedule(self, *_: Any) -> None:
        self._check_soon.start()

    def ram_buffers(self) -> Buffers:
        """The memory the open plots' data uses (``FolderCache`` counts what datasets don't)."""
        merged: Buffers = {}
        for plot in self.plots:
            merged.update(plot.ram_buffers())
        return merged

    def measure(self) -> Usage:
        _, datasets, _ = self.cache.memory_usage()
        return Usage(datasets, self.cache.plot_bytes(), self.cache.max_data_bytes)

    def order(self) -> list[Plot]:
        """The plots that may be released, first to go first: those not on screen before those
        on screen, then least recently viewed (shown in the Settings panel) first."""
        recent = self.panel.recent() if self.panel is not None else []
        shown = self.panel.current_plot() if self.panel is not None else None

        def key(plot: Plot) -> tuple[bool, int]:
            dock = plot.dock_widget
            visible = bool(dock is not None and dock.isVisible())
            return visible, recent.index(dock) if dock in recent else -1

        return sorted((plot for plot in self.plots if plot.dock_widget is not shown and plot.releasable()), key=key)

    def check(self) -> None:
        """Measure; above 80 %, drop the datasets no tab shows, then release plots, until under
        it; then say how it stands (status bar, the 75 % window once per crossing)."""
        self._check_soon.stop()
        usage = self.measure()
        released = 0
        limit = int(RELEASE_SHARE * usage.budget)
        if usage.budget > 0 and usage.total > limit and (candidates := self.order()):
            self.cache.evict_to(limit)
            usage = self.measure()
            datasets = self.cache.held_buffers()
            for plot in candidates:
                if usage.total <= limit:
                    break
                frees = self.frees(plot, datasets)
                if frees <= plot.picture_cost():
                    continue  # Its data is mostly a loaded folder's: its picture would cost more.
                if plot.release(frees):
                    released += 1
                    # A dataset only this plot's arrays kept may go now: datasets first, again.
                    self.cache.evict_to(limit)
                    usage = self.measure()
                    datasets = self.cache.held_buffers()
            if released:
                logging.info("RAM budget: released %d plot%s, now %.0f%% of %d bytes", released,
                             "" if released == 1 else "s", usage.share * 100, usage.budget)
        before, self.usage = self.usage, usage
        if released:
            self.released.emit(released)
        if usage.share >= DIALOG_SHARE:
            if not self._warned:
                self._warned = True
                self.warning.emit()
        else:
            self._warned = False
        if usage != before or released:
            self.changed.emit()

    def frees(self, plot: Plot, datasets: Buffers) -> int:
        """What releasing ``plot`` frees: its buffers no held dataset and no other plot has."""
        others: set[int] = set()
        for other in self.plots:
            if other is not plot:
                others.update(other.ram_buffers())
        return sum(size for key, size in plot.ram_buffers().items() if key not in datasets and key not in others)

    def biggest(self, count: int = 5) -> tuple[list[tuple[str, int]], list[tuple[str, int, bool]]]:
        """For the 75 % window: the biggest plots (label, bytes of their data) and folders
        (path, bytes, shown in a tab), largest first."""
        plots = sorted(((plot.ram_label(), sum(plot.ram_buffers().values())) for plot in self.plots),
                       key=lambda item: -item[1])
        folders = sorted(self.cache.held_sizes(), key=lambda item: -item[1])
        return [item for item in plots if item[1] > 0][:count], folders[:count]

    def released_count(self) -> int:
        return sum(1 for plot in self.plots if plot.is_released)
