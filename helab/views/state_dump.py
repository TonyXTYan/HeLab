"""Debug › Dump State…: what the main window shows, as JSON a test runner reads instead of a
screenshot (roadmaps/smoke-automation.md, item 3's read half). Memory only: widgets' texts and the
tabs' and plots' state in RAM, never a folder, the disk cache or a helper.

Its shape (``SCHEMA``) is the one the ``--smoke`` control channel (v0.0.8) is to return for its
state query, so a runner reads either the same way. Each field names what the user sees, and the
controls' IDs (helab/utils/accessible.py) where a runner would look for them."""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from PyQt6 import sip
from PyQt6.QtWidgets import QLabel, QWidget

from helab.utils.constants import APP_COMMIT_HASH, APP_VERSION
from helab.utils.folder_cache import get_folder_cache
from helab.utils.io_service import get_io_service
from helab.views.FolderExplorer import FolderExplorer
from helab.views.plots.dock import AnalysisDock
from helab.views.plots.instance import AnalysisInstance

if TYPE_CHECKING:
    from helab.views.HelabMainWindow import HelabMainWindow

SCHEMA = "helab.state/1"


def text_of(widget: Optional[QWidget]) -> dict[str, Any]:
    """A label's text and tooltip as shown (hidden: ``shown`` false, its text as last set)."""
    if not isinstance(widget, QLabel) or sip.isdeleted(widget):
        return {"text": "", "tooltip": "", "shown": False}
    return {"text": widget.text(), "tooltip": widget.toolTip(), "shown": widget.isVisible()}


def folder_tab(window: HelabMainWindow, index: int, explorer: FolderExplorer) -> dict[str, Any]:
    live = explorer.live
    return {
        "id": explorer.objectName(),  # folder_tab_<n>, as its close button's ID ends.
        "title": window.tab_widget.tabText(index),
        "current": explorer is window.tab_widget.currentWidget(),
        "view_path": explorer.view_path,
        "selected_path": explorer.selected_path_globally,
        "path_bar": explorer.path_edit.text(),
        # The folder summary's lines (summary_selected, summary_counts, summary_cache, summary_freshness).
        "summary": {"selected": text_of(explorer.selected_folder_label),
                    "counts": text_of(explorer.folder_summary_label),
                    "cache": text_of(explorer.folder_cache_label),
                    "freshness": text_of(explorer.folder_freshness_label)},
        "summary_buttons": [button.objectName() for button in explorer.summary_buttons if not button.isHidden()],
        "loading": explorer.loading,
        "load_path": explorer.load_path if explorer.loading else "",
        "load_progress": explorer.load_progress if explorer.loading else None,
        "load_error": explorer.load_error,
        "shown_data": explorer.displayed_dataset.path if explorer.displayed_dataset is not None else "",
        "live": None if live is None else {
            "path": live.path, "on": live.on, "error": live.error, "shots": len(live.shots), "new": live.new,
            "checks": live.checks},
    }


def plot(window: HelabMainWindow, instance: AnalysisInstance) -> dict[str, Any]:
    dock = instance.dock_widget
    shown = isinstance(dock, AnalysisDock) and dock is window.plots.panel_right_top_plot_settings.current_plot()
    return {
        "id": instance.instance_id,  # As its tab's close button's ID ends (close_plot_tab_<id>).
        "title": dock.windowTitle() if dock is not None else "",
        "script": instance.metadata.identity().analysis_id,
        "action": instance.action,
        "name": instance.name,
        "path": instance.path,
        "shown_in_settings": shown,
        "floating": bool(dock is not None and dock.isFloating()),
        "visible": bool(dock is not None and dock.isVisible()),
        "released": instance.is_released,
        "running": bool(instance.job_id),
        "following_live": instance.following(),
        "source": text_of(dock.findChild(QLabel, "plot_data_source") if dock is not None else None),
        "status": text_of(instance.status_label),
        "error": text_of(dock.findChild(QLabel, "plot_error") if dock is not None else None),
    }


def dump_state(window: HelabMainWindow) -> dict[str, Any]:
    """The window's state now (``SCHEMA``), from memory only."""
    explorers = [(index, widget) for index in range(window.tab_widget.count())
                 if isinstance(widget := window.tab_widget.widget(index), FolderExplorer)]
    instances = window.panel_right_bottom_script_selector.instances()
    geometry = window.geometry()
    return {
        "schema": SCHEMA,
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "monotonic": time.monotonic(),
        "pid": os.getpid(),
        "version": APP_VERSION,
        "commit": APP_COMMIT_HASH,
        "window": {"title": window.windowTitle(), "geometry": [geometry.x(), geometry.y(),
                                                              geometry.width(), geometry.height()],
                   "offline": get_folder_cache(get_io_service()).offline,
                   "closing": window._closing},
        "status_bar": {"activity": text_of(window.status_bar_message_left),
                       "resources": text_of(window.status_bar_message_right),
                       "buttons": [button.objectName() for button in (
                           window.mismatch_button, window.roots_button, window.offline_button, window.plots.ram_button)
                           if not button.isHidden()]},
        "folder_details": {key: text_of(value) for key, value in window.folder_details.values.items()},
        "central_hint": text_of(window.plots.central_placeholder.hint),
        "folder_tabs": [folder_tab(window, index, explorer) for index, explorer in explorers],
        "script_group": window.panel_right_bottom_script_selector.group_selector.currentText(),
        "plot_count": len(instances),
        "plots": [plot(window, instance) for instance in instances],
    }
