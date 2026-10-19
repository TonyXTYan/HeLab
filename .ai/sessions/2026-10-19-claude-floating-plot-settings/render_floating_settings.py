"""Offscreen renders of a floating plot's settings section, for the handoff. Run from the
floor's root with the floor's environment (``source .ai/local/floor-env.sh``: HeLab's cache,
temp and app folders point at the floor's own), e.g.

    QT_QPA_PLATFORM=offscreen python .ai/sessions/2026-10-19-claude-floating-plot-settings/render_floating_settings.py

It prints the window's and the section's widths at each step: opening the section widens the
window by its width, so the plot keeps its size.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional

for name in ("HELAB_DIR_CACHES_OVERRIDE", "HELAB_DIR_TEMPS_OVERRIDE", "HELAB_APP_DIR_OVERRIDE"):
    if not os.environ.get(name):
        sys.exit(f"{name} is not set: source .ai/local/floor-env.sh first")

import numpy as np
from PyQt6 import QtWebEngineWidgets  # noqa: F401  (before the QApplication)
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QDockWidget, QMainWindow, QTabWidget, QWidget

from helab.analysis.dataset_view import DatasetView, view_of
from helab.analysis.follow import LiveFeed
from helab.models.ScriptTreeSelector import AnalysisDock, AnalysisInstance, PlotSettingsPanel, TreePanelWidget
from helab.scripts.base import DatasetAnalysis
from helab.scripts.standard.basic_plots import TxyHistograms
from helab.utils.folder_cache import Dataset
from helab.views.CentralHint import CentralHint
from helab.views.HelabMainWindow import HelabMainWindow

OUT = Path(__file__).parent / "screenshots"
PATH = "/Volumes/dld_output/2026-10-19/run_042"


def cloud(last: int) -> Dataset:
    rng = np.random.default_rng(7)
    data = {shot: np.column_stack([rng.normal(0.4205, 0.0012, 2000), rng.normal(0, 0.004, 2000),
                                   rng.normal(0, 0.004, 2000)]) for shot in range(1, last + 1)}
    return Dataset(PATH, f"cloud-{last}", data, {
        "fingerprint": [[shot, 10_000 + shot, 1_000 + shot] for shot in data], "source": "updated",
        "loaded_at": time.time()}, 0)


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
        time.sleep(0.01)


def plot(window: Window, script: DatasetAnalysis) -> AnalysisInstance:
    panel = TreePanelWidget(window)
    instance = panel.run_analysis(script.get_metadata(), script, "Plot")
    assert isinstance(instance, AnalysisInstance)
    window._panels = getattr(window, "_panels", []) + [panel]  # Kept alive with the window.
    return instance


def save(widget: QWidget, name: str) -> None:
    OUT.mkdir(exist_ok=True)
    widget.grab().save(str(OUT / name))
    print("wrote", OUT / name)


def sizes(label: str, dock: AnalysisDock) -> None:
    print(f"{label}: window {dock.width()} · plot {dock.frame.sizes()[0]} · settings {dock.settings.width()}"
          f" (open {dock.settings.is_open})")


def main() -> None:
    app = QApplication(sys.argv)
    window = Window()
    area = window.middle_mainwindow
    area.resize(900, 520)
    area.show()
    window.view = view_of(cloud(30))
    instance = plot(window, TxyHistograms())
    wait(app, lambda: instance.shown is not None)
    dock = instance.dock_widget
    assert isinstance(dock, AnalysisDock)
    settings = window.panel_right_top_plot_settings
    settings.resize(380, 520)
    settings.show()

    dock.setFloating(True)
    dock.resize(460, 480)
    dock.show()
    wait(app, lambda: dock.settings.isVisible())
    sizes("floating, closed", dock)
    save(dock, "floating-collapsed.png")
    save(settings, "main-panel-settings-away.png")

    dock.settings.toggle.click()
    wait(app, lambda: dock.settings.is_open)
    sizes("open", dock)
    save(dock, "floating-expanded.png")

    dock.frame.setSizes([dock.frame.sizes()[0] - 80, dock.frame.sizes()[1] + 80])
    dock.frame.splitterMoved.emit(dock.frame.sizes()[0], 1)  # As a drag of the handle would.
    wait(app, lambda: True)
    sizes("dragged 80 px wider", dock)
    dock.settings.toggle.click()
    wait(app, lambda: not dock.settings.is_open)
    sizes("closed again", dock)
    dock.settings.toggle.click()
    wait(app, lambda: dock.settings.is_open)
    sizes("open again (remembered width)", dock)

    dock.setFloating(False)
    wait(app, lambda: not dock.settings.isVisible())
    save(settings, "main-panel-docked-again.png")
    window.close_plots()


if __name__ == "__main__":
    main()
