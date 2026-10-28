"""Plots count toward the RAM budget (Settings → Cache), beside the folders' data held in RAM.

The counter is the datasets ``FolderCache`` holds (as it counts them) plus each open plot's
own data: its dataset view's shot arrays and its result's arrays. Arrays are counted by the
memory they use (``buffer_of``: an array and every view of it are one), so a plot of a
dataset still held adds only what it holds beyond it, and two plots of one folder count
their shared shots once.

Shares of the budget (Tony, 2026-10-19/20): from 50 % the status bar says so; at 75 % a
window lists the biggest plots and folders, once per crossing (again only after RAM in use
drops below 70 %); above 80 % plots are released, least recently viewed first, until usage
is back under 80 %. The datasets no tab shows go first (``FolderCache.evict_to``); plots
only if that isn't enough. The shown plot, a running plot and one following Live are never
released, and no plot is closed.

A released plot keeps a picture of itself (no longer interactive) with a Reload button, and
frees its view and result. It reloads from RAM (the folder's dataset still held) or the
local disk cache, never from its folder, by its shots' fingerprints (``restore``), when it is
shown again (``auto_reload``, a setting, on by default) or on Reload.

The Qt-free parts (the shares, ``view_buffers``, ``hollow``, ``restore``, ``Usage``) are in
helab/analysis/budget_core.py.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional, Sequence

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from helab.analysis.budget_core import DIALOG_SHARE, REARM_SHARE, RELEASE_SHARE, Panel, Plot, Usage
from helab.utils.ram_buffers import Buffers

if TYPE_CHECKING:
    from helab.utils.folder_cache import FolderCache


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
        """The plots that may be released, first to go first: those a reload drew in the last
        ``RELOAD_GRACE`` seconds last (so two plots under a tight budget don't keep releasing and
        reloading each other while a third could go), those not on screen before those on
        screen, then least recently viewed (shown in the Settings panel) first."""
        recent = self.panel.recent() if self.panel is not None else []
        shown = self.panel.current_plot() if self.panel is not None else None

        def key(plot: Plot) -> tuple[bool, bool, int]:
            dock = plot.dock_widget
            visible = bool(dock is not None and dock.isVisible())
            return plot.recently_reloaded(), visible, recent.index(dock) if dock in recent else -1

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
            # First, only plots that free more than their picture with every other plot staying;
            # then, if still over, plots sharing buffers with candidates later in the order.
            for alone in (True, False):
                staying = [plot for plot in self.plots if plot not in candidates]
                for plot in candidates:
                    if usage.total <= limit:
                        break
                    if plot.is_released:
                        continue
                    others = [other for other in self.plots if other is not plot] if alone else staying
                    frees = self.frees(plot, others)
                    if frees > plot.picture_cost() and plot.release(frees):
                        released += 1
                        # A dataset only this plot's arrays kept may go now: datasets first, again.
                        self.cache.evict_to(limit)
                        usage = self.measure()
                    else:
                        staying.append(plot)  # Its picture would cost more than it frees.
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
        elif usage.share < REARM_SHARE:
            self._warned = False  # Hovering between 70 and 75 % doesn't open it again.
        if usage != before or released:
            self.changed.emit()

    def frees(self, plot: Plot, staying: Sequence[Plot]) -> int:
        """What releasing ``plot`` makes freeable: its buffers that neither a dataset shown in a
        tab nor a plot that stays (``staying``) holds. A dataset no tab shows goes once no plot
        holds it (``evict_to`` after each release). ``check`` first counts every other plot as
        staying, so a plot isn't released for shots another plot keeps anyway; then only the
        shown, running, Live and skipped ones, so plots sharing shots go one after another."""
        kept = set(self.cache.shown_buffers())
        for other in staying:
            kept.update(other.ram_buffers())
        return sum(size for key, size in plot.ram_buffers().items() if key not in kept)

    def biggest(self, count: int = 5) -> tuple[list[tuple[str, int]], list[tuple[str, int, bool]]]:
        """For the 75 % window: the biggest plots (label, bytes of their data) and folders
        (path, bytes, shown in a tab), largest first."""
        plots = sorted(((plot.ram_label(), sum(plot.ram_buffers().values())) for plot in self.plots),
                       key=lambda item: -item[1])
        folders = sorted(self.cache.held_sizes(), key=lambda item: -item[1])
        return [item for item in plots if item[1] > 0][:count], folders[:count]

    def released_count(self) -> int:
        return sum(1 for plot in self.plots if plot.is_released)
