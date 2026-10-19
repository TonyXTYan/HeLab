"""Running analyses from the Scripts panel on a tab's loaded data: the input stays bound to
the view it started with, and the plot dock shows its source, revision and record."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Iterator, List, Optional

import numpy as np
import pytest
from pytestqt.qtbot import QtBot
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QDockWidget, QLabel, QMainWindow, QTabWidget, QWidget

from helab.analysis.panes import PlotlyPane
from helab.analysis.parameters import ParameterSpec
from helab.analysis.results import AnalysisContext, AnalysisResult
from helab.io_helper import list_folder, scan
from helab.models.ScriptTreeSelector import AnalysisInstance, ParamTreeTabWidget, TreePanelWidget
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.utils.dash_server import dash_server
from helab.utils.folder_cache import FolderCache
from helab.utils.io_service import IORequest, IOService
from helab.views.CentralHint import CentralHint
from helab.views.FolderExplorer import FolderExplorer
from helab.views.HelabMainWindow import HelabMainWindow


@pytest.fixture
def browser(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FolderExplorer]:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    monkeypatch.setattr("helab.models.SnapshotFileSystemModel.get_io_service", lambda: service)
    explorer = FolderExplorer(str(tmp_path), str(tmp_path), str(tmp_path), [0, 4, 5])
    qtbot.addWidget(explorer)
    qtbot.waitUntil(lambda: ("list", str(tmp_path)) in explorer.model.cache.jobs)
    yield explorer
    explorer.close_cleanup()
    service.shutdown()


def request_for(cache: FolderCache, path: str, operation: str) -> IORequest:
    job = cache.jobs[(operation, path)]
    return next(request for request in cache.service.pending if request.owner == job.owner)


def browse(explorer: FolderExplorer, qtbot: QtBot, path: str) -> None:
    """Replay a real listing (and its details scan) of ``path`` into the queued requests."""
    cache = explorer.model.cache
    for operation in ("list", "details"):
        if (operation, path) not in cache.jobs:
            continue
        request = request_for(cache, path, operation)
        events: list[dict[str, Any]] = []
        (list_folder if operation == "list" else scan)(path, events.append, None)
        for event in events + [{"kind": "done"}]:
            cache.service.resultReady.emit(request, event)
        cache.service.pending.remove(request)
        qtbot.waitUntil(lambda: not cache.has_request(explorer.model.owner, operation, path))


def load(explorer: FolderExplorer, qtbot: QtBot, path: Path, shots: dict[int, int]) -> None:
    """Select ``path`` and complete a load of ``shots`` (shot → rows) as a helper would."""
    explorer.tree.setCurrentIndex(explorer.model.path_index(str(path)))
    browse(explorer, qtbot, str(path))
    explorer.load_to_ram_cache(str(path), dwell=False)
    cache = explorer.model.cache
    request = request_for(cache, str(path), "load")
    for shot, rows in shots.items():
        cache.service.resultReady.emit(request, {"kind": "shot", "shot": shot,
                                                 "array": np.full((rows, 3), float(shot))})
    cache.service.resultReady.emit(request, {
        "kind": "loaded", "signature": explorer.model.nodes[str(path)].signature, "files": len(shots),
        "rows": sum(shots.values()), "bytes": 24 * sum(shots.values()), "problematic": [], "failed_files": 0,
        "source": "files"})
    cache.service.pending.remove(request)
    qtbot.waitUntil(lambda: explorer.displayed_dataset is not None and explorer.displayed_dataset.path == str(path))


def folder(root: Path, name: str, shots: int) -> Path:
    path = root / name
    path.mkdir()
    for shot in range(1, shots + 1):
        (path / f"d_txy_forc{shot}.txt").write_text("1,2,3\n")
    return path


class Window(HelabMainWindow):
    """The main window's plot-dock parts only, around one tab."""

    def __init__(self, explorer: FolderExplorer) -> None:
        QMainWindow.__init__(self)
        self.middle_mainwindow = QMainWindow()
        self.central_placeholder = CentralHint("Select a data folder to begin")
        self.middle_mainwindow.setCentralWidget(self.central_placeholder)
        self.dock_widgets: List[QDockWidget] = []
        self.tab_widget = QTabWidget()  # type: ignore[assignment]
        self.tab_widget.addTab(explorer, "tab")
        self.panel_right_top_params_tab_widget = ParamTreeTabWidget()
        self.notices: list[str] = []

    def show_status_notice(self, text: str, seconds: float = 10.0) -> None:
        self.notices.append(text)

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        QMainWindow.closeEvent(self, a0)


class Blocking(DatasetAnalysis):
    def __init__(self) -> None:
        self.release = threading.Event()
        self.entered = threading.Event()
        self.renders = 0

    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata("Blocking", "test", "Tests", __file__, "tests.blocking", "3")

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [ParameterSpec("scale", "Scale", "int", 1, (1, 10))]

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        self.entered.set()
        assert self.release.wait(10)
        return context.view.event_count * int(context.parameters["scale"])

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        self.renders += 1
        return QLabel(f"events {result.data}", parent)


@pytest.fixture
def window(qtbot: QtBot, browser: FolderExplorer) -> Iterator[Window]:
    made = Window(browser)
    qtbot.addWidget(made)
    yield made


def source_label(dock: QDockWidget) -> QLabel:
    label = dock.findChild(QLabel, "plot_data_source")
    assert label is not None
    return label


def test_selection_change_mid_run_keeps_the_input(
        window: Window, browser: FolderExplorer, qtbot: QtBot, tmp_path: Path) -> None:
    first, second = folder(tmp_path, "run_A", 2), folder(tmp_path, "run_B", 1)
    browse(browser, qtbot, str(tmp_path))
    load(browser, qtbot, first, {1: 3, 2: 4})
    panel = TreePanelWidget(window)
    qtbot.addWidget(panel)
    script = Blocking()
    instance = panel.run_analysis(script.get_metadata(), script, "Plot")
    assert isinstance(instance, AnalysisInstance) and instance.dock_widget is not None
    assert instance.view.identity.source_path == str(first)
    assert script.entered.wait(5)
    # While it runs, the tab moves on to another folder and shows its data.
    load(browser, qtbot, second, {1: 5})
    dataset = browser.displayed_dataset
    assert dataset is not None and dataset.path == str(second)
    script.release.set()
    qtbot.waitUntil(lambda: instance.result is not None, timeout=10_000)
    result = instance.result
    assert result is not None and result.state == "completed"
    assert result.input.identity.source_path == str(first) and result.input.revision == 1
    assert result.data == 7  # run_A's events, not run_B's
    label = source_label(instance.dock_widget)
    window._update_plot_source_label(instance.dock_widget, browser)
    assert label.text() == "Showing previously loaded data: run_A · rev 1 · tests.blocking v3 · Scale 1"
    assert "Input: " + str(first) in label.toolTip() and "kept in RAM only" in label.toolTip()
    # A new run takes the data shown now.
    view = window.current_dataset_view()
    assert view is not None and view.identity.source_path == str(second)


def test_rerun_uses_the_same_input_and_close_cleans_up(
        window: Window, browser: FolderExplorer, qtbot: QtBot, tmp_path: Path) -> None:
    run = folder(tmp_path, "run_C", 1)
    browse(browser, qtbot, str(tmp_path))
    load(browser, qtbot, run, {1: 2})
    panel = TreePanelWidget(window)
    qtbot.addWidget(panel)
    script = Blocking()
    script.release.set()
    instance = panel.run_analysis(script.get_metadata(), script, "Plot")
    assert instance is not None and instance.dock_widget is not None and instance.parameter_root is not None
    qtbot.waitUntil(lambda: instance.result is not None, timeout=10_000)
    first = instance.result
    assert first is not None and first.data == 2
    assert window.panel_right_top_params_tab_widget.indexOf(instance.param_tab) >= 0
    label = source_label(instance.dock_widget)
    assert label.text() == "Data source: run_C · rev 1 · tests.blocking v3 · Scale 1"
    instance.parameter_root.child("scale").setValue(4)
    instance.rerun_button.click()
    qtbot.waitUntil(lambda: instance.result is not first, timeout=10_000)
    assert instance.result is not None and instance.result.data == 8
    assert instance.result.input == first.input
    assert source_label(instance.dock_widget).text().endswith("Scale 4")
    runner = instance.runner
    assert runner.results.get(instance.result.job_id) is not None
    instance.dock_widget.close()
    assert instance.is_closed and instance.instance_id not in panel._analysis_instances
    assert window.panel_right_top_params_tab_widget.indexOf(instance.param_tab) < 0


def test_closing_a_dock_mid_run_delivers_nothing(
        window: Window, browser: FolderExplorer, qtbot: QtBot, tmp_path: Path) -> None:
    run = folder(tmp_path, "run_E", 1)
    browse(browser, qtbot, str(tmp_path))
    load(browser, qtbot, run, {1: 2})
    panel = TreePanelWidget(window)
    qtbot.addWidget(panel)
    script = Blocking()
    instance = panel.run_analysis(script.get_metadata(), script, "Plot")
    assert instance is not None and instance.dock_widget is not None
    job_id = instance.job_id
    ended: list[AnalysisResult] = []
    instance.runner.finished.connect(lambda result: ended.append(result) if result.job_id == job_id else None)
    assert script.entered.wait(5)
    instance.dock_widget.close()
    assert instance.is_closed and instance.instance_id not in panel._analysis_instances
    script.release.set()
    qtbot.waitUntil(lambda: bool(ended), timeout=10_000)
    QApplication.processEvents()
    assert ended[0].state == "cancelled" and ended[0].data is None
    assert script.renders == 0 and instance.result is None
    assert instance.runner.results.get(job_id) is None


def test_centre_hint_hides_while_a_plot_dock_is_open(
        window: Window, browser: FolderExplorer, qtbot: QtBot, tmp_path: Path) -> None:
    """The hint goes as soon as the first dock is added (its show is queued, so visibility
    can't tell) and comes back only when the last open dock closes."""
    run = folder(tmp_path, "run_H", 1)
    browse(browser, qtbot, str(tmp_path))
    load(browser, qtbot, run, {1: 3})
    window.show()
    panel = TreePanelWidget(window)
    qtbot.addWidget(panel)
    script = Blocking()
    metadata = script.get_metadata()
    hint = window.central_placeholder
    assert not hint.isHidden()
    first = panel.run_analysis(metadata, script, "Plot")
    assert first is not None and first.dock_widget is not None
    assert hint.isHidden()
    second = panel.run_analysis(metadata, script, "Plot")
    assert second is not None and second.dock_widget is not None
    script.release.set()
    qtbot.waitUntil(lambda: first.result is not None and second.result is not None, timeout=10_000)
    first.dock_widget.close()
    assert hint.isHidden() and window.dock_widgets == [second.dock_widget]
    second.dock_widget.close()
    assert not hint.isHidden() and not window.dock_widgets


def test_run_without_data_says_so(window: Window, qtbot: QtBot) -> None:
    panel = TreePanelWidget(window)
    qtbot.addWidget(panel)
    script = Blocking()
    assert panel.run_analysis(script.get_metadata(), script, "Plot") is None
    assert window.notices == ["Blocking: load a folder's data first"]


def test_scatter_from_the_panel(window: Window, browser: FolderExplorer, qtbot: QtBot, tmp_path: Path) -> None:
    run = folder(tmp_path, "run_D", 2)
    browse(browser, qtbot, str(tmp_path))
    load(browser, qtbot, run, {1: 30, 2: 40})
    panel = TreePanelWidget(window)
    qtbot.addWidget(panel)
    metadata = next(m for m in panel.script_manager.get_scripts_in_group("Plots") if m.name == "3D scatter")
    script_class = panel.script_manager.get_script(metadata.script_id)
    assert script_class is not None
    script = script_class()
    assert isinstance(script, DatasetAnalysis)
    instance = panel.run_analysis(metadata, script, "Plot")
    assert instance is not None and instance.dock_widget is not None
    qtbot.waitUntil(lambda: instance.result is not None, timeout=10_000)
    pane = instance.dock_widget.findChild(PlotlyPane)
    assert pane is not None and pane.plot_id in dash_server.plots
    assert pane.open_button.text() == "Open in browser"
    assert pane.note.text().startswith("All 70 events in range shown · crop keeps")
    assert pane.note.toolTip().startswith("Showing all 70 events in the range")
    label = source_label(instance.dock_widget)
    assert label.text() == ("Data source: run_D · rev 1 · helab.scatter_3d v2 · Shots all, Range auto-crop, "
                            "Auto-crop: keep 99 %, Point size 1.5 px, Opacity 0.5, Display cap 100,000")
    assert metadata.file_hash[:12] in label.toolTip()
    # The record lists every parameter, those not in use included.
    assert "Parameters: Shots all, Last N 50, From shot 1, To shot (0 = last) 0, Range auto-crop, " \
           "Auto-crop: keep 99 %, T min 0 s, T max 0 s," in label.toolTip()
    plot_id = pane.plot_id
    instance.dock_widget.close()
    qtbot.waitUntil(lambda: plot_id not in dash_server.plots)
    QApplication.processEvents()
