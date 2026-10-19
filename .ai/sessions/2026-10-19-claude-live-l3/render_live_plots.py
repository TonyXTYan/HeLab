"""Offscreen renders of plots following Live (L3), for the handoff. Run from the floor's root
with the floor's environment (``source .ai/local/floor-env.sh``: HeLab's cache, temp and app
folders point at the floor's own), e.g.

    QT_QPA_PLATFORM=offscreen python .ai/sessions/2026-10-19-claude-live-l3/render_live_plots.py
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, List, Optional

for name in ("HELAB_DIR_CACHES_OVERRIDE", "HELAB_DIR_TEMPS_OVERRIDE", "HELAB_APP_DIR_OVERRIDE"):
    if not os.environ.get(name):
        sys.exit(f"{name} is not set: source .ai/local/floor-env.sh first")

import numpy as np
from PyQt6 import QtWebEngineWidgets  # noqa: F401  (before the QApplication)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QDockWidget, QMainWindow, QTabWidget, QWidget

from helab.analysis.dataset_view import DatasetView
from helab.analysis.follow import LiveFeed
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.models.ScriptTreeSelector import AnalysisInstance, PlotSettingsPanel, TreePanelWidget
from helab.scripts.base import DatasetAnalysis
from helab.scripts.standard.basic_plots import CountsPerShot
from helab.utils.folder_cache import Dataset
from helab.views.CentralHint import CentralHint
from helab.views.HelabMainWindow import HelabMainWindow

OUT = Path(__file__).parent
PATH = "/Volumes/dld_output/2026-10-19/run_042"


def revision(last: int) -> Dataset:
    rng = np.random.default_rng(last)
    data = {shot: rng.normal(size=(int(rng.integers(800, 1200)), 3)) for shot in range(1, last + 1)}
    return Dataset(PATH, f"sig-{last}", data, {
        "fingerprint": [[shot, 10_000 + shot, 1_000 + shot] for shot in data], "source": "updated",
        "loaded_at": time.time()}, 0)


class Gated(CountsPerShot):
    """Counts per shot whose runs wait for ``go``, and fail on the revisions in ``fail``."""

    def __init__(self) -> None:
        self.go = threading.Event()
        self.go.set()
        self.fail: set[int] = set()

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        assert self.go.wait(30)
        if context.view.revision in self.fail:
            raise RuntimeError("index 7 is out of bounds for axis 0 with size 7")
        return super().compute(action_name, context)


class Window(HelabMainWindow):
    def __init__(self) -> None:
        QMainWindow.__init__(self)
        self.middle_mainwindow = QMainWindow()
        self.central_placeholder = CentralHint("Select a data folder to begin")
        self.middle_mainwindow.setCentralWidget(self.central_placeholder)
        self.dock_widgets: List[QDockWidget] = []
        self.tab_widget = QTabWidget()  # type: ignore[assignment]
        self.panel_right_top_plot_settings = PlotSettingsPanel(self)
        self.live_feed = LiveFeed(self)
        self.view: Optional[DatasetView] = None

    def current_dataset_view(self) -> DatasetView | None:
        return self.view

    def show_status_notice(self, text: str, seconds: float = 10.0) -> None:
        pass

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        QMainWindow.closeEvent(self, a0)


def wait(app: QApplication, done: Callable[[], bool], seconds: float = 20.0) -> None:
    end = time.monotonic() + seconds
    while not done():
        if time.monotonic() > end:
            raise TimeoutError
        app.processEvents()
        time.sleep(0.01)
    for _ in range(5):
        app.processEvents()


def plot(window: Window, script: DatasetAnalysis) -> AnalysisInstance:
    panel = TreePanelWidget(window)
    instance = panel.run_analysis(script.get_metadata(), script, "Plot")
    assert isinstance(instance, AnalysisInstance)
    window._panels = getattr(window, "_panels", []) + [panel]  # Kept alive with the window.
    return instance


def save(widget: QWidget, name: str) -> None:
    widget.grab().save(str(OUT / name))
    print("wrote", OUT / name)


def main() -> None:
    app = QApplication(sys.argv)
    window = Window()
    area = window.middle_mainwindow
    area.resize(900, 460)
    area.show()

    # 1. Following, a run in flight, newer shots waiting.
    window.view = window.live_feed.publish(revision(40))
    script = Gated()
    instance = plot(window, script)
    wait(app, lambda: instance.shown is not None)
    script.go.clear()
    window.live_feed.publish(revision(41))
    for last in (42, 43, 44):
        window.live_feed.publish(revision(last))
    wait(app, lambda: instance.follow.waiting() == 3)
    save(instance.dock_widget or area, "following-waiting.png")
    script.go.set()
    wait(app, lambda: instance.shown is not None and instance.shown.input.revision == 5)
    save(instance.dock_widget or area, "following-current.png")

    # 2. A failed rerun keeps the last plot.
    script.fail = {6}
    window.live_feed.publish(revision(45))
    wait(app, lambda: bool(instance.error))
    save(instance.dock_widget or area, "rerun-failed.png")

    # 3. The plot's settings: its Live group, with the script's values as defaults.
    settings = window.panel_right_top_plot_settings
    settings.resize(360, 520)
    settings.show()
    wait(app, lambda: True)
    save(settings, "settings-live-group.png")
    window.close_plots()

    # 4. Live started on an empty folder: no shots yet.
    window.view = window.live_feed.publish(Dataset(PATH.replace("042", "043"), "", {}, {"fingerprint": []}, 0))
    empty = plot(window, CountsPerShot())
    wait(app, lambda: empty.shown is not None)
    save(empty.dock_widget or area, "empty-no-shots-yet.png")
    window.close_plots()


if __name__ == "__main__":
    main()
