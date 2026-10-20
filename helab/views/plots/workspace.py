"""The plot area (``PlotWorkspace``): the plot docks' main window (``middle_mainwindow``) and its
hint, the open plots (``dock_widgets``), the one Settings panel, the Live feed the plots follow
and the RAM budget with its status-bar button and window, and how a plot's dock shows its result
and its source lines. ``HelabMainWindow`` composes one (``plots``) and places its widgets; plots
(``AnalysisInstance``) and the Scripts panel (``TreePanelWidget``) use it, not the window.

What it needs of the window comes in as callables: the current tab's explorer and all of them,
the status bar's notices, Settings, and whether the window is closing."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Callable, List, Optional

from PyQt6.QtCore import Qt, QSettings, QTimer
from PyQt6.QtWidgets import QDockWidget, QLabel, QMainWindow, QMessageBox, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from helab.analysis.budget import RamBudget
from helab.analysis.budget_core import DIALOG_SHARE, RELEASE_SHARE, WARN_SHARE
from helab.analysis.dataset_view import DatasetView, view_of
from helab.analysis.live_feed import LiveFeed
from helab.analysis.results import AnalysisResult
from helab.utils.colours import AMBER
from helab.utils.constants import read_plot_auto_reload
from helab.utils.folder_cache import FolderCache
from helab.utils.number_format import byte_size
from helab.views.CentralHint import CentralHint
from helab.views.plots.dock import AnalysisDock
from helab.views.plots.settings_panel import PlotSettingsPanel

if TYPE_CHECKING:
    from helab.views.FolderExplorer import FolderExplorer


class PlotWorkspace:
    """The plot area of a main window (``host``, the parent of its docks, panel and windows)."""

    def __init__(self, host: QMainWindow, *,
                 current_explorer: Callable[[], Optional[FolderExplorer]] = lambda: None,
                 explorers: Callable[[], List[FolderExplorer]] = list,
                 notice: Callable[[str], None] = lambda text: None,
                 show_settings: Callable[[], None] = lambda: None,
                 closing: Callable[[], bool] = lambda: False) -> None:
        self.host = host
        self._current_explorer = current_explorer
        self._explorers = explorers
        self._notice = notice
        self._show_settings = show_settings
        self._closing = closing
        self.middle_mainwindow = QMainWindow()
        # Load details are in Folder details; the plot area keeps a short hint.
        self.central_placeholder = CentralHint("Select a data folder to begin")
        self.middle_mainwindow.setCentralWidget(self.central_placeholder)
        self.dock_widgets: List[QDockWidget] = []
        # The newest data of the folder Live watches, for the plots following it.
        self.live_feed = LiveFeed(host)
        # The active plot's settings (the window places it, top right).
        self.panel_right_top_plot_settings = PlotSettingsPanel(parent=host)
        # Shown from 50 % of the RAM budget (loaded folders and plots); opens their sizes. The
        # window places it in its status bar.
        self.ram_button = QToolButton()
        self.ram_button.setAutoRaise(True)
        self.ram_button.hide()
        self.ram_budget: Optional[RamBudget] = None  # From ``setup_ram_budget``.
        self._ram_report: QMessageBox | None = None

    def notice(self, text: str) -> None:
        """A one-time notice in the window's status bar."""
        self._notice(text)

    def detach(self) -> None:
        """The window is closing (after ``close_plots``): the RAM budget and the Settings panel
        stop following the cache and the app."""
        if self.ram_budget is not None:
            self.ram_budget.detach()
        self.panel_right_top_plot_settings.detach()

    def setup_ram_budget(self, cache: FolderCache, settings: QSettings) -> None:
        """Plots count toward the RAM budget: from 50 % the status bar's button (``ram_button``),
        the 75 % window once per crossing, and plots released above 80 % (``RamBudget``)."""
        self.ram_budget = RamBudget(cache, self.panel_right_top_plot_settings, self.host)
        self.ram_budget.auto_reload = read_plot_auto_reload(settings)
        self.ram_budget.changed.connect(self._update_ram_button)
        self.ram_budget.warning.connect(lambda: self.show_ram_report(warn=True))
        self.ram_budget.released.connect(self._plots_released)
        self.ram_button.clicked.connect(lambda: self.show_ram_report())
        self._ram_report = None

    def _update_ram_button(self) -> None:
        """From 50 % of the RAM budget the status bar says how much is in use (amber from 75 %)."""
        budget = self.ram_budget
        assert budget is not None  # Connected by setup_ram_budget.
        usage = budget.usage
        self.ram_button.setVisible(usage.share >= WARN_SHARE)
        if usage.share < WARN_SHARE:
            return
        released = budget.released_count()
        self.ram_button.setText(f"RAM {usage.share:.0%} of budget")
        self.ram_button.setStyleSheet(f"color: {AMBER};" if usage.share >= DIALOG_SHARE else "")
        self.ram_button.setToolTip(
            f"Loaded folders and plots use {byte_size(usage.total)} of the {byte_size(usage.budget)} RAM budget "
            f"(Settings → Cache): folders {byte_size(usage.datasets)}, plots {byte_size(usage.plots)} more.\n"
            f"Above {RELEASE_SHARE:.0%}, plots not viewed lately are released (each keeps a picture and reloads "
            "when shown)." + (f"\n{released} plot{'' if released == 1 else 's'} released now." if released else "")
            + "\nClick for the biggest plots and folders.")

    def _plots_released(self, count: int) -> None:
        self._notice(f"Released {count} plot{'' if count == 1 else 's'} to keep RAM under "
                                f"{RELEASE_SHARE:.0%} of its budget: shown again, each reloads")

    def ram_report_text(self) -> tuple[str, str]:
        """The 75 % window's text: how RAM stands, and the biggest plots and folders."""
        budget = self.ram_budget
        assert budget is not None  # Shown only once setup_ram_budget ran.
        usage = budget.usage
        plots, folders = budget.biggest()
        text = (f"Loaded folders and plots use {byte_size(usage.total)}, {usage.share:.0%} of the RAM budget "
                f"({byte_size(usage.budget)}, Settings → Cache). Above {RELEASE_SHARE:.0%}, HeLab first drops "
                "loaded folders no tab shows, then releases plots not viewed lately: each keeps a picture and "
                "reloads from RAM or the disk cache when shown again. Closing plots or tabs frees RAM too.")
        lines = ["Biggest plots:", *(f"  {label} — {byte_size(size)}" for label, size in plots)] if plots else []
        if folders:
            lines.append("Biggest loaded folders:")
            for path, size, shown in folders:
                name = os.path.basename(path.rstrip(os.sep)) or path
                lines.append(f"  {name} — {byte_size(size)}" + (" (shown in a tab)" if shown else ""))
        return text, "\n".join(lines)

    def show_ram_report(self, warn: bool = False) -> None:
        """The biggest plots and folders: a window that doesn't block (at 75 % once per crossing,
        or from the status bar)."""
        if self._closing():
            return
        text, details = self.ram_report_text()
        box = self._ram_report
        if box is None:
            box = self._ram_report = QMessageBox(self.host)
            box.setWindowModality(Qt.WindowModality.NonModal)
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            settings = box.addButton("Settings…", QMessageBox.ButtonRole.ActionRole)
            if settings is not None:
                settings.clicked.connect(lambda: QTimer.singleShot(0, self._show_settings))
        box.setIcon(QMessageBox.Icon.Warning if warn else QMessageBox.Icon.Information)
        box.setWindowTitle("RAM nearly at its budget" if warn else "RAM in use")
        box.setText(text)
        box.setInformativeText(details)
        box.show()
        box.raise_()

    def close_plots(self) -> None:
        """Close every plot dock as its close button does: each run's job is cancelled, it
        leaves the analysis runner and its result is unpinned (the window is closing; its
        widgets may outlive it, as in tests)."""
        for dock in list(self.dock_widgets):
            dock.close()

    def update_placeholder_visibility(self) -> None:
        """The plot area's hint shows while no plot dock is open, and hides while any is.

        Open docks are those in ``dock_widgets`` (closing removes them), not the visible
        ones: ``addDockWidget`` shows a new dock through a queued event, so the first dock
        isn't visible yet when it is added, and a dock behind another tabbed one isn't
        visible either but is still open."""
        self.central_placeholder.setVisible(not self.dock_widgets)

    def _set_plot_source(self, dock: QDockWidget, explorer: FolderExplorer) -> None:
        """Attach provenance to a plot at creation, before the selection changes."""
        dataset = explorer.displayed_dataset
        content = dock.widget()
        if dataset is None or content is None:
            return
        dock.setProperty("dataSourcePath", dataset.path)
        dock.setProperty("dataSourceSignature", dataset.signature)
        PlotWorkspace._wrap_plot(dock, content)
        PlotWorkspace._update_plot_source_label(dock, explorer)

    def follow_live(self, explorer: FolderExplorer) -> None:
        """Plots follow Live: the data a Live tab shows is published as the newest revision of
        its folder, and a folder no tab checks any more ends (Live off, another tab, or checks
        stopped by an error until Retry): its plots catch up (memory only)."""
        def checking(tab: FolderExplorer) -> bool:
            return tab.live is not None and not tab.live.error and not tab.closed

        session = explorer.live
        dataset = explorer.displayed_dataset
        if session is not None and checking(explorer) and dataset is not None and dataset.path == session.path:
            self.live_feed.publish(dataset, explorer.model.cache.root_of(dataset.path))
        watched = {other.live.path for other in self._explorers() if other.live is not None and checking(other)}
        if explorer.live is not None and checking(explorer):
            watched.add(explorer.live.path)
        for path in self.live_feed.paths() - watched:
            self.live_feed.stop(path)

    def current_dataset_view(self) -> DatasetView | None:
        """An immutable view of the data the current tab shows (memory only), for a new run.
        While Live watches it, that is the revision the plots following it have."""
        current = self._current_explorer()
        if current is None or current.displayed_dataset is None:
            return None
        dataset = current.displayed_dataset
        return view_of(dataset, current.model.cache.root_of(dataset.path))

    def set_plot_result(self, dock: QDockWidget, content: QWidget, result: AnalysisResult,
                        parameters_text: str = "", record_text: str = "", selection_text: str = "") -> None:
        """Show an analysis result in its dock, with two source lines: the input folder and
        revision, which shots (``selection_text``) and the analysis with its version; then the
        settings in short form (``parameters_text``). The full record (every parameter,
        ``record_text``) is in the tooltip."""
        identity = result.input.identity
        dock.setProperty("dataSourcePath", identity.source_path)
        dock.setProperty("dataSourceSignature", result.input_signature or identity.signature)
        dock.setProperty("plotSourceRevision", f"rev {result.input.revision}")
        dock.setProperty("plotSourceDetail", " · ".join(filter(None, (selection_text, result.analysis.short()))))
        dock.setProperty("plotSourceSettings", parameters_text)
        dock.setProperty("plotSourceRecord", result.describe(record_text or parameters_text))
        old = dock.widget()
        if old is None or content.parentWidget() is not old:  # Else updated in place: kept as it is.
            PlotWorkspace._wrap_plot(dock, content)
            if old is not None:
                old.setParent(None)  # out of the dock now, so findChild sees only the new label
                old.deleteLater()
        self.update_plot_source(dock)

    def replace_plot_content(self, dock: QDockWidget, content: QWidget) -> None:
        """Show ``content`` (a released plot's picture) in place of the plot, under the same
        source lines; the plot before it is deleted."""
        old = dock.widget()
        PlotWorkspace._wrap_plot(dock, content)
        if old is not None:
            old.setParent(None)
            old.deleteLater()
        self.update_plot_source(dock)

    def update_plot_source(self, dock: QDockWidget) -> None:
        """A plot's source lines changed (its result, or its Live state): show them now, and
        its settings in short form in its floating window's settings header."""
        PlotWorkspace._update_plot_source_label(dock, self._current_explorer())
        if isinstance(dock, AnalysisDock):
            settings = dock.property("plotSourceSettings")
            dock.settings.toggle.set_text(summary=settings if isinstance(settings, str) else "")

    @staticmethod
    def _wrap_plot(dock: QDockWidget, content: QWidget) -> None:
        """The dock shows its source above the plot: one or two lines (source, then settings),
        never wrapped (a long line is cut at the dock's edge; the tooltip has it all), with no
        vertical padding. Below them, only after a failed run, the error in amber (the plot
        shown is the last one drawn)."""
        wrapper = QWidget(dock)
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(0)
        label = QLabel(wrapper)
        label.setObjectName("plot_data_source")
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(False)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        layout.addWidget(label)
        error = QLabel(wrapper)
        error.setObjectName("plot_error")
        error.setTextFormat(Qt.TextFormat.PlainText)
        error.setStyleSheet(f"color: {AMBER};")
        error.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        error.hide()
        layout.addWidget(error)
        layout.addWidget(content, 1)
        dock.setWidget(wrapper)

    @staticmethod
    def _update_plot_source_label(dock: QDockWidget, explorer: FolderExplorer | None) -> None:
        path = dock.property("dataSourcePath")
        if not isinstance(path, str):
            return
        label = dock.findChild(QLabel, "plot_data_source")
        if label is None:
            return
        node = explorer.model.nodes.get(explorer.selected_path_globally) if explorer is not None else None
        # A names-only listing has no signature; the explorer compares shot lists then. A plot
        # following Live is the folder's data, catching up as its line says.
        current = bool(dock.property("plotFollowing")) or (
            explorer is not None and path == explorer.selected_path_globally and node is not None
            and (not node.signature or dock.property("dataSourceSignature") == node.signature)
            and explorer.folder_opened_path == path)
        prefix = "Data source" if current else "Showing previously loaded data"
        parts = [dock.property(name) for name in ("plotSourceRevision", "plotFollow", "plotSourceDetail")]
        settings = dock.property("plotSourceSettings")
        record = dock.property("plotSourceRecord")
        name = os.path.basename(path.rstrip(os.sep)) or path
        label.setText(" · ".join([f"{prefix}: {name}", *(part for part in parts if isinstance(part, str) and part)])
                      + (f"\n{settings}" if isinstance(settings, str) and settings else ""))
        label.setToolTip(record if isinstance(record, str) and record else path)
        error_label = dock.findChild(QLabel, "plot_error")
        error = dock.property("plotError")
        if error_label is not None:
            text = f"⚠ {error}" if isinstance(error, str) and error else ""
            error_label.setText(text)
            error_label.setToolTip(text)
            error_label.setVisible(bool(text))
