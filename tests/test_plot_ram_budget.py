"""Plots count toward the RAM budget (helab/analysis/budget.py): the counter (datasets held plus
what plots hold beyond them, shared arrays once), the thresholds (50 % status bar, 75 % window
once per crossing, release above 80 %), the release order and exemptions, the released plot's
picture, and reloading it from RAM or the disk cache only, by its shots' fingerprints."""
from __future__ import annotations

import gc
import threading
import time
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, List, Optional, cast

import numpy as np
import numpy.typing as npt
import pytest
from PyQt6 import sip
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QDockWidget, QLabel, QMainWindow, QMessageBox, QTabWidget, QToolButton, QWidget
from pytestqt.qtbot import QtBot

from helab.analysis.budget import (PLOT_AUTO_RELOAD_SETTING, RamBudget, buffer_of, buffers, hollow, read_auto_reload,
                                   restore, shots_list)
from helab.analysis.dataset_view import DatasetView, read_only, view_of
from helab.analysis.follow import LiveFeed
from helab.analysis.panes import PlotlyPane
from helab.analysis.parameter_tree import parameter_of
from helab.analysis.parameters import ParameterSpec
from helab.analysis.results import AnalysisContext, AnalysisResult, RamResults
from helab.analysis.runner import AnalysisRunner
from helab.models.ScriptTreeSelector import AnalysisInstance, PlotSettingsPanel, ReleasedPlot, TreePanelWidget
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.scripts.standard import scatter_3d
from helab.utils.dash_server import dash_server
from helab.utils.folder_cache import Dataset, FolderCache, get_folder_cache
from helab.utils.io_service import IOService
from helab.views.CacheTab import CacheTab
from helab.views.CentralHint import CentralHint
from helab.views.HelabMainWindow import HelabMainWindow

ROWS = 1000  # events per shot: 24 kB a shot
SHOT_BYTES = ROWS * 3 * 8


def folder(name: str) -> str:
    return FolderCache.key(f"/data/root/{name}")


def dataset(name: str, shots: range | list[int], *,
            prints: Optional[dict[int, tuple[int, int, int]]] = None) -> Dataset:
    """A loaded folder: ``ROWS`` events a shot, fixed fingerprints (or ``prints``)."""
    numbers = list(shots)
    data = {shot: np.full((ROWS, 3), float(shot)) for shot in numbers}
    fingerprint = [list((prints or {}).get(shot, (shot, 100 + shot, 1_000 + shot))) for shot in numbers]
    return Dataset(folder(name), f"sig-{name}-{len(numbers)}", data,
                   {"fingerprint": fingerprint, "bytes": sum(array.nbytes for array in data.values()),
                    "loaded_at": time.time()}, 0)


@dataclass(frozen=True)
class Copied:
    events: npt.NDArray[np.float64]  # A copy of the view's events: the result's own arrays
    shots: tuple[int, ...]


class Copy(DatasetAnalysis):
    """A result as big as its input (a copy of its events); runs wait for ``go``."""

    def __init__(self) -> None:
        self.go = threading.Event()
        self.go.set()

    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata("Copy", "test", "Tests", __file__, "tests.copy", "1")

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [ParameterSpec("scale", "Scale", "int", 1, (1, 10))]

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        assert self.go.wait(10)
        return Copied(context.view.events().copy(), tuple(context.view.shots))

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: Copied = result.data
        label = QLabel(f"shots {list(data.shots)} · scale {result.parameters['scale']}", parent)
        label.setObjectName("copied_plot")
        label.setStyleSheet("background: #3060c0; color: white;")
        return label


class Window(HelabMainWindow):
    """The main window's plot area, Settings panel, Live feed and RAM budget, with no tabs."""

    def __init__(self, cache: FolderCache, settings: QSettings) -> None:
        QMainWindow.__init__(self)
        self._closing = False
        self.middle_mainwindow = QMainWindow()
        self.middle_mainwindow.resize(800, 600)
        self.central_placeholder = CentralHint("Select a data folder to begin")
        self.middle_mainwindow.setCentralWidget(self.central_placeholder)
        self.dock_widgets: List[QDockWidget] = []
        self.tab_widget = QTabWidget()  # type: ignore[assignment]
        self.panel_right_top_plot_settings = PlotSettingsPanel(self)
        self.live_feed = LiveFeed(self)
        self.ram_button = QToolButton()
        self.view: Optional[DatasetView] = None
        self.notices: list[str] = []
        self.setup_ram_budget(cache, settings)

    def current_dataset_view(self) -> DatasetView | None:
        return self.view

    def show_status_notice(self, text: str, seconds: float = 10.0) -> None:
        self.notices.append(text)

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        QMainWindow.closeEvent(self, a0)


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> Iterator[AnalysisRunner]:
    made = AnalysisRunner()
    monkeypatch.setattr("helab.models.ScriptTreeSelector.get_analysis_runner", lambda: made)
    yield made
    made.stop()


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch) -> Iterator[FolderCache]:
    """A cache whose helpers never run: requests stay in ``service.pending``."""
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    made = get_folder_cache(service)
    made.max_data_bytes = 1 << 40  # Nothing released while a test sets up.
    yield made
    service.shutdown()


@pytest.fixture
def window(qtbot: QtBot, runner: AnalysisRunner, cache: FolderCache, tmp_path: Path) -> Iterator[Window]:
    made = Window(cache, QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(made)
    made.middle_mainwindow.show()
    yield made
    made.close_plots()
    made.ram_budget.detach()
    if not sip.isdeleted(made.middle_mainwindow):
        made.middle_mainwindow.close()
        made.middle_mainwindow.deleteLater()


def open_plot(window: Window, qtbot: QtBot, data: Dataset | DatasetView, script: Optional[DatasetAnalysis] = None,
              *, wait: bool = True) -> AnalysisInstance:
    """A plot of ``data`` (the test keeps no view of it), drawn unless ``wait`` is off."""
    window.view = data if isinstance(data, DatasetView) else view_of(data)
    panel = TreePanelWidget(window)
    qtbot.addWidget(panel)
    script = script or Copy()
    instance = panel.run_analysis(script.get_metadata(), script, "Plot")
    window.view = None
    assert isinstance(instance, AnalysisInstance)
    if wait:
        qtbot.waitUntil(lambda: instance.shown is not None and not instance.job_id, timeout=10_000)
    return instance


def dock_of(instance: AnalysisInstance) -> QDockWidget:
    return cast(QDockWidget, instance.dock_widget)


def error_line(instance: AnalysisInstance) -> str:
    label = dock_of(instance).findChild(QLabel, "plot_error")
    assert label is not None
    return label.text()


def hold(cache: FolderCache, entry: Dataset) -> Dataset:
    cache.datasets[(entry.path, entry.signature, entry.epoch)] = entry
    return entry


def drawn(instance: AnalysisInstance) -> bool:
    content = dock_of(instance).findChild(QLabel, "copied_plot")
    return instance.released is None and content is not None and not instance.job_id


# The counter


def test_an_array_and_its_views_are_one_buffer() -> None:
    base = np.zeros((10, 3))
    view = read_only(base)
    assert buffer_of(view) == buffer_of(base) == (id(base), base.nbytes)
    assert buffer_of(base[2:5]) == buffer_of(base)
    raw = bytearray(240)
    framed = np.frombuffer(raw, dtype=np.float64)
    assert buffer_of(framed) == (id(raw), 240)
    assert buffers([base, view, base[:1]]) == {id(base): base.nbytes}


def test_shared_arrays_are_counted_once(window: Window, cache: FolderCache, qtbot: QtBot) -> None:
    """A plot of a dataset still held adds only its result; two plots of it count their shots
    once; once the dataset is dropped, the plots' shots count (once) as theirs."""
    entry = hold(cache, dataset("run_a", range(1, 5)))
    shots = 4 * SHOT_BYTES
    first = open_plot(window, qtbot, entry)
    assert cache.memory_usage()[1] == shots
    assert cache.plot_bytes() == shots  # Its result: a copy of the events, its own.
    second = open_plot(window, qtbot, entry)
    assert cache.plot_bytes() == 2 * shots  # Two results; the view's shots are the dataset's.
    window.ram_budget.check()
    assert window.ram_budget.usage.total == 3 * shots
    del cache.datasets[(entry.path, entry.signature, 0)]
    assert cache.memory_usage()[1] == 0
    assert cache.plot_bytes() == 3 * shots  # The shots once, though both plots hold them.
    first.close()
    second.close()
    assert cache.plot_bytes() == 0


def test_eviction_keeps_a_dataset_whose_arrays_plots_hold(window: Window, cache: FolderCache, qtbot: QtBot) -> None:
    """Dropping a dataset whose shots a plot holds anyway would free nothing: others go first."""
    plotted = hold(cache, dataset("plotted", range(1, 5)))
    open_plot(window, qtbot, plotted)
    other = hold(cache, dataset("other", range(1, 3)))
    cache.datasets.move_to_end((plotted.path, plotted.signature, 0), last=False)  # Least recently used.
    dropped = cache.evict_to(cache.memory_usage()[1] + cache.plot_bytes() - 1)
    assert dropped == [other] and cache.holds(plotted)


# Thresholds


def test_thresholds_status_bar_window_once_per_crossing(window: Window, cache: FolderCache, qtbot: QtBot) -> None:
    budget = window.ram_budget
    warnings: list[None] = []
    budget.warning.connect(lambda: warnings.append(None))
    shown = hold(cache, dataset("shown", range(1, 41)))  # 960 kB, shown in a tab: never dropped
    cache.retain("tab", shown)
    cache.max_data_bytes = 4 * 40 * SHOT_BYTES  # 25 %
    budget.check()
    assert budget.usage.share == pytest.approx(0.25) and window.ram_button.isHidden() and not warnings
    cache.max_data_bytes = int(40 * SHOT_BYTES / 0.55)
    budget.check()
    assert not window.ram_button.isHidden() and window.ram_button.text() == "RAM 55% of budget"
    assert not warnings and "plots" in window.ram_button.toolTip()
    cache.max_data_bytes = int(40 * SHOT_BYTES / 0.76)
    budget.check()
    assert len(warnings) == 1
    box = window._ram_report
    assert isinstance(box, QMessageBox) and box.isVisible() and not box.isModal()
    assert "76%" in box.text() and "Biggest loaded folders:" in box.informativeText()
    assert "  shown — " in box.informativeText() and "(shown in a tab)" in box.informativeText()
    box.hide()
    cache.max_data_bytes = int(40 * SHOT_BYTES / 0.79)
    budget.check()
    assert len(warnings) == 1  # Still over 75 %: once per crossing.
    cache.max_data_bytes = int(40 * SHOT_BYTES / 0.6)
    budget.check()
    cache.max_data_bytes = int(40 * SHOT_BYTES / 0.77)
    budget.check()
    assert len(warnings) == 2  # Crossed again.
    # Over 80 % with nothing to release (a dataset shown in a tab): nothing happens.
    cache.max_data_bytes = 40 * SHOT_BYTES
    budget.check()
    assert budget.usage.share == pytest.approx(1.0) and cache.holds(shown) and not window.notices


# Release order and exemptions


def test_release_order_and_exemptions(window: Window, cache: FolderCache, runner: AnalysisRunner,
                                      qtbot: QtBot) -> None:
    """Above 80 %: datasets no tab shows go first, then plots least recently viewed first, until
    under 80 %. Never the shown plot, a running one or one following Live; none is closed."""
    budget = window.ram_budget
    plots = {name: open_plot(window, qtbot, dataset(name, range(1, 3))) for name in ("d", "e", "a")}
    blocked = Copy()
    plots["b"] = open_plot(window, qtbot, dataset("b", range(1, 3)), blocked)
    plots["c"] = open_plot(window, qtbot, window.live_feed.publish(dataset("c", range(1, 3))))
    assert plots["c"].following()
    blocked.go.clear()
    plots["b"].run()  # Running from now on.
    qtbot.waitUntil(lambda: bool(plots["b"].job_id) and runner.running() == 1, timeout=5_000)
    unshown = hold(cache, dataset("x", range(1, 3)))
    panel = window.panel_right_top_plot_settings
    for name in ("d", "e", "b", "c", "a"):  # d least recently viewed; a shown.
        panel.show_plot(dock_of(plots[name]))
    assert panel.current_plot() is dock_of(plots["a"])
    budget.check()
    plot_bytes = 4 * SHOT_BYTES  # Each plot: its 2 shots and their copy.
    total = 2 * SHOT_BYTES + 5 * plot_bytes
    assert budget.usage.total == total
    # 80 % of the budget: under it once x, d and e go (not before), with room for their pictures.
    cache.max_data_bytes = int((total - 2 * SHOT_BYTES - 2 * plot_bytes + 30_000) / 0.8)
    budget.check()
    assert not cache.holds(unshown)
    released = {name for name, instance in plots.items() if instance.released is not None}
    assert released == {"d", "e"}
    assert budget.usage.total <= 0.8 * cache.max_data_bytes
    assert window.notices[-1].startswith("Released 2 plots")
    assert all(not instance.is_closed for instance in plots.values()) and len(window.dock_widgets) == 5
    # More pressure: still never a, b or c.
    cache.max_data_bytes = 1
    budget.check()
    assert {name for name, instance in plots.items() if instance.released is not None} == {"d", "e"}
    blocked.go.set()
    window.live_feed.stop(plots["c"].path)
    qtbot.waitUntil(lambda: not plots["b"].job_id, timeout=10_000)
    budget.check()  # b ran, c no longer follows Live: both may go now; a is still shown.
    assert {name for name, instance in plots.items() if instance.released is not None} == {"b", "c", "d", "e"}
    assert plots["a"].released is None


def test_datasets_go_first_again_after_each_release(window: Window, cache: FolderCache, qtbot: QtBot) -> None:
    """The reviewer's probe: dataset A (no tab shows it) is kept while plot P_A holds its arrays;
    once P_A is released, A goes before the next plot, P_B, does."""
    held = hold(cache, dataset("a", range(1, 5)))  # 4 shots
    plot_a = open_plot(window, qtbot, held)  # Its own result: 4 shots
    plot_b = open_plot(window, qtbot, dataset("b", range(1, 3)))  # 2 shots and their copy
    plot_c = open_plot(window, qtbot, dataset("c", range(1, 2)))  # Shown
    panel = window.panel_right_top_plot_settings
    for instance in (plot_a, plot_b, plot_c):
        panel.show_plot(dock_of(instance))
    window.ram_budget.check()
    assert window.ram_budget.usage.total == 14 * SHOT_BYTES
    cache.max_data_bytes = int(9 * SHOT_BYTES / 0.8)
    window.ram_budget.check()
    assert plot_a.released is not None and not cache.holds(held) and plot_b.released is None
    assert window.ram_budget.usage.total <= 9 * SHOT_BYTES


def test_the_least_recently_viewed_plot_goes_first(window: Window, cache: FolderCache, qtbot: QtBot) -> None:
    first, second, third = (open_plot(window, qtbot, dataset(name, range(1, 3))) for name in ("p1", "p2", "p3"))
    panel = window.panel_right_top_plot_settings
    for instance in (second, first, third):
        panel.show_plot(dock_of(instance))
    window.ram_budget.check()
    total = window.ram_budget.usage.total
    cache.max_data_bytes = int((total - 1) / 0.8)  # Over by a byte: one plot goes.
    window.ram_budget.check()
    assert second.released is not None and first.released is None and third.released is None


# The released plot


class Tiny(Copy):
    """A result of a few bytes: a plot of a loaded folder holds almost nothing of its own."""

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        return Copied(np.zeros(1), tuple(context.view.shots))


def test_older_results_count_and_go_with_a_release_or_close(
        window: Window, cache: FolderCache, runner: AnalysisRunner, qtbot: QtBot) -> None:
    """RamResults keeps a plot's older (unpinned) results: they count as the plot's RAM, and
    releasing or closing the plot drops them."""
    entry = hold(cache, dataset("results", range(1, 3)))  # The view's shots are the folder's.
    plots = [open_plot(window, qtbot, entry) for _ in range(2)]
    jobs: list[list[str]] = []
    for instance in plots:
        first = cast(AnalysisResult, instance.shown).job_id
        instance.run()
        qtbot.waitUntil(lambda: not instance.job_id, timeout=10_000)
        second = cast(AnalysisResult, instance.shown).job_id
        jobs.append([first, second])
        older = runner.results.peek(first)
        assert older is not None and older.data is not None  # Unpinned, still kept.
        assert sum(instance.ram_buffers().values()) == 3 * 2 * SHOT_BYTES  # Its view and both copies.
    open_plot(window, qtbot, dataset("other", range(1, 2)))
    assert cache.plot_bytes() >= 2 * 2 * 2 * SHOT_BYTES
    assert plots[0].release()
    assert all(runner.results.peek(job) is None for job in jobs[0])
    plots[1].close()
    assert all(runner.results.peek(job) is None for job in jobs[1])


def test_a_release_must_free_more_than_its_picture_costs(window: Window, cache: FolderCache, qtbot: QtBot) -> None:
    """A plot whose data is a loaded folder's (its own result: 8 bytes) would cost more as a
    picture than releasing it frees: it stays, and its picture's cost is remembered, so later
    checks don't take its picture again. Released pictures count in the budget."""
    shown = hold(cache, dataset("loaded", range(1, 5)))
    cache.retain("tab", shown)
    tiny = open_plot(window, qtbot, shown, Tiny())
    big = open_plot(window, qtbot, dataset("big", range(1, 5)))
    open_plot(window, qtbot, dataset("other", range(1, 2)))  # Shown
    panel = window.panel_right_top_plot_settings
    panel.show_plot(dock_of(big))
    panel.show_plot(dock_of(tiny))
    panel.show_plot(window.dock_widgets[-1])
    budget = window.ram_budget
    cache.max_data_bytes = 1
    budget.check()
    assert tiny.released is None and tiny.picture_cost() > 8
    assert big.released is not None
    picture = big.released.ram_buffers()
    assert picture and set(picture) <= set(budget.ram_buffers())
    assert cache.plot_bytes() >= sum(picture.values())
    assert not tiny.release(8) and tiny.released is None


def test_a_released_plot_keeps_a_picture_and_frees_its_data(window: Window, cache: FolderCache,
                                                            runner: AnalysisRunner, qtbot: QtBot) -> None:
    entry = dataset("freed", range(1, 4))
    array = weakref.ref(entry.data[2])
    instance = open_plot(window, qtbot, entry)
    del entry
    open_plot(window, qtbot, dataset("other", range(1, 2)))  # Shown now.
    job = cast(AnalysisResult, instance.shown).job_id
    assert runner.results.get(job) is not None and instance.ram_buffers()
    assert instance.release()
    released = instance.released
    assert isinstance(released, ReleasedPlot)
    picture = released.picture.picture
    assert picture.png.startswith(b"\x89PNG") and picture.size.width() > 50 and not picture.pixmap().isNull()
    assert instance.ram_buffers() == released.ram_buffers() == {id(picture.png): len(picture.png)}
    assert instance.picture_cost() == len(picture.png)
    assert released.reload_button.isEnabled() and "Released to free RAM" in released.state.text()
    assert dock_of(instance).findChild(QLabel, "copied_plot") is None or sip.isdeleted(
        dock_of(instance).findChild(QLabel, "copied_plot"))
    assert runner.results.get(job) is None
    shown = cast(AnalysisResult, instance.shown)
    assert shown.data is None and shown.coverage.shots == (1, 2, 3) and shown.parameters["scale"] == 1
    assert instance.view.shot_numbers == (1, 2, 3) and instance.view.event_count == 0
    assert instance.view.fingerprints[2] == (2, 102, 1002)
    source = dock_of(instance).findChild(QLabel, "plot_data_source")
    assert source is not None and ": freed · rev 1" in source.text()
    qtbot.wait(10)
    gc.collect()
    assert array() is None  # The shots are gone from RAM.
    assert not instance.release()  # Once.


def test_the_scatter_keeps_a_snapshot_of_its_last_frame(window: Window, qtbot: QtBot) -> None:
    instance = open_plot(window, qtbot, dataset("scatter", range(1, 3)), scatter_3d.Scatter3D())
    open_plot(window, qtbot, dataset("other", range(1, 2)))
    pane = dock_of(instance).findChild(PlotlyPane)
    assert pane is not None
    plot_id = pane.plot_id
    assert instance.release()
    assert isinstance(instance.released, ReleasedPlot) and instance.released.picture.picture.png
    qtbot.waitUntil(lambda: dash_server.snapshot(plot_id) is None, timeout=10_000)  # Its page's data freed.


# Reloading


def test_auto_reload_when_shown_again_on_and_off(window: Window, cache: FolderCache, qtbot: QtBot,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("helab.models.ScriptTreeSelector.store_options", lambda: {})
    entry = hold(cache, dataset("again", range(1, 4)))
    instance = open_plot(window, qtbot, entry)
    other = open_plot(window, qtbot, dataset("other", range(1, 2)))
    panel = window.panel_right_top_plot_settings
    window.ram_budget.auto_reload = False
    assert instance.release()
    panel.show_plot(dock_of(instance))
    qtbot.wait(50)
    assert instance.released is not None and not instance.job_id  # Off: only Reload draws it.
    panel.show_plot(dock_of(other))
    window.ram_budget.auto_reload = True
    panel.show_plot(dock_of(instance))
    qtbot.waitUntil(lambda: drawn(instance), timeout=10_000)
    assert cast(AnalysisResult, instance.shown).coverage.shots == (1, 2, 3) and error_line(instance) == ""
    assert instance.status_label.text() == ""
    # The manual Reload button always works.
    panel.show_plot(dock_of(other))
    window.ram_budget.auto_reload = False
    assert instance.release()
    released = instance.released
    assert released is not None
    released.reload_button.click()
    qtbot.waitUntil(lambda: drawn(instance), timeout=10_000)


def test_auto_reload_tries_once_until_the_folder_changes(
        window: Window, cache: FolderCache, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    """A plot whose data is nowhere: its first show asks the disk cache once; clicks in it and
    later shows don't ask again until the folder's data or disk cache changes. Reload always asks."""
    monkeypatch.setattr("helab.models.ScriptTreeSelector.store_options", lambda: {"directory": "store"})
    instance = open_plot(window, qtbot, dataset("nowhere", range(1, 3)))
    other = open_plot(window, qtbot, dataset("other", range(1, 2)))
    assert instance.release()
    panel = window.panel_right_top_plot_settings
    asked: list[str] = []
    real_submit = cache.submit

    def submit(owner: str, generation: int, path: str, operation: str, *args: Any, **kwargs: Any) -> bool:
        asked.append(operation)
        return real_submit(owner, generation, path, operation, *args, **kwargs)
    monkeypatch.setattr(cache, "submit", submit)

    def answer_nothing() -> None:
        request = next(iter(cache.jobs[("cached", instance.path)].subscribers.values()))
        cache.resultReady.emit(request, {"kind": "error", "message": "No cached data for this folder"})

    panel.show_plot(dock_of(instance))
    assert asked == ["cached"]
    answer_nothing()
    panel.show_plot(dock_of(instance))  # A click in the plot already shown: no new show.
    panel.show_plot(dock_of(other))
    panel.show_plot(dock_of(instance))
    assert asked == ["cached"]  # Shown again, nothing changed: not asked again.
    cache.diskCacheChanged.emit(instance.path)  # Its disk cache changed: worth a try.
    panel.show_plot(dock_of(other))
    panel.show_plot(dock_of(instance))
    assert asked == ["cached", "cached"]
    answer_nothing()
    cast(ReleasedPlot, instance.released).reload_button.click()  # Reload always asks.
    assert asked == ["cached", "cached", "cached"]


def test_a_plot_just_reloaded_goes_after_the_others(window: Window, cache: FolderCache, qtbot: QtBot,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """Two plots under a tight budget don't keep releasing and reloading each other while a third
    could go: the one a reload drew just now is released last."""
    monkeypatch.setattr("helab.models.ScriptTreeSelector.store_options", lambda: {})
    entry = hold(cache, dataset("reloaded", range(1, 3)))
    cache.retain("tab", entry)
    reloaded = open_plot(window, qtbot, entry)
    older = open_plot(window, qtbot, dataset("older", range(1, 3)))
    shown = open_plot(window, qtbot, dataset("shown", range(1, 2)))
    panel = window.panel_right_top_plot_settings
    assert reloaded.release()
    panel.show_plot(dock_of(reloaded))  # Reloads (auto reload).
    qtbot.waitUntil(lambda: drawn(reloaded), timeout=10_000)
    panel.show_plot(dock_of(older))
    panel.show_plot(dock_of(shown))  # Least recently viewed: reloaded, then older.
    assert reloaded.recently_reloaded() and not older.recently_reloaded()
    window.ram_budget.check()
    cache.max_data_bytes = int((window.ram_budget.usage.total - 1) / 0.8)
    window.ram_budget.check()
    assert older.released is not None and reloaded.released is None
    reloaded.reloaded_at -= 60  # Later, it goes in its turn.
    assert not reloaded.recently_reloaded()


def test_auto_reload_setting_saved_and_read(qtbot: QtBot, cache: FolderCache, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    assert read_auto_reload(settings) is True  # On by default.
    tab = CacheTab(cache, settings)
    qtbot.addWidget(tab)
    assert tab.plot_auto_reload.isChecked()
    tab.plot_auto_reload.setChecked(False)
    tab.save(settings)
    settings.sync()
    again = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    assert read_auto_reload(again) is False and again.contains(PLOT_AUTO_RELOAD_SETTING)


def test_a_reload_leaves_out_and_names_changed_and_missing_shots(
        window: Window, cache: FolderCache, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("helab.models.ScriptTreeSelector.store_options", lambda: {})  # RAM only
    entry = hold(cache, dataset("changed", range(1, 6)))
    instance = open_plot(window, qtbot, entry)
    open_plot(window, qtbot, dataset("other", range(1, 2)))
    assert instance.release()
    del cache.datasets[(entry.path, entry.signature, 0)]
    # The folder loaded again: shot 2 rewritten (another fingerprint), shot 4 gone.
    again = hold(cache, dataset("changed", [1, 2, 3, 5], prints={2: (2, 999, 1_002)}))
    cast(ReleasedPlot, instance.released).reload_button.click()
    qtbot.waitUntil(lambda: drawn(instance), timeout=10_000)
    shown = cast(AnalysisResult, instance.shown)
    assert shown.coverage.shots == (1, 3, 5)
    assert error_line(instance) == ("⚠ Reloaded from RAM without 2 of its 5 shots: "
                                    "shot 2 changed since; shot 4 missing")
    view = instance.view
    assert view.shot_numbers == (1, 3, 5) and view.fingerprints[5] == (5, 105, 1_005)
    assert view.shots[3].base is not None and buffer_of(view.shots[3]) == buffer_of(again.data[3])
    instance.run()  # A run of its own clears the note.
    qtbot.waitUntil(lambda: not instance.job_id, timeout=10_000)
    assert error_line(instance) == ""


def test_a_reload_reads_only_the_disk_cache_never_the_folder(
        window: Window, cache: FolderCache, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("helab.models.ScriptTreeSelector.store_options", lambda: {"directory": "store", "budget": 1})
    entry = dataset("disk", range(1, 4))
    instance = open_plot(window, qtbot, entry)
    open_plot(window, qtbot, dataset("other", range(1, 2)))
    assert instance.release()
    service = cache.service
    before = set(map(id, service.pending))
    cast(ReleasedPlot, instance.released).reload_button.click()
    asked = [request for request in service.pending if id(request) not in before]
    assert [(request.operation, request.path) for request in asked] == [("cached", entry.path)]
    assert asked[0].payload["cache"] == {"directory": "store", "budget": 1}
    released = cast(ReleasedPlot, instance.released)
    assert "reading the disk cache" in released.state.text() and not released.reload_button.isEnabled()
    job = cache.jobs[("cached", entry.path)]
    request = next(iter(job.subscribers.values()))
    cache.resultReady.emit(request, {"kind": "progress"})
    assert instance.released is not None
    cache.resultReady.emit(request, {"kind": "loaded", "dataset": dataset("disk", range(1, 4))})
    qtbot.waitUntil(lambda: drawn(instance), timeout=10_000)
    assert cast(AnalysisResult, instance.shown).coverage.shots == (1, 2, 3) and error_line(instance) == ""
    assert all(request.operation == "cached" for request in service.pending if id(request) not in before)


def test_a_disk_reload_ending_during_a_live_run_leaves_that_run(
        window: Window, cache: FolderCache, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    """Live started on the folder while a released plot read the disk cache: its revision's run
    draws the plot; the read, ending first, doesn't replace that run."""
    monkeypatch.setattr("helab.models.ScriptTreeSelector.store_options", lambda: {"directory": "store"})
    script = Copy()
    instance = open_plot(window, qtbot, dataset("live", range(1, 3)), script)
    open_plot(window, qtbot, dataset("other", range(1, 2)))
    assert instance.release()
    cast(ReleasedPlot, instance.released).reload_button.click()
    request = next(iter(cache.jobs[("cached", instance.path)].subscribers.values()))
    script.go.clear()
    window.live_feed.publish(dataset("live", range(1, 5)))  # Live: a revision with 4 shots
    live_job = instance.job_id
    assert live_job
    cache.resultReady.emit(request, {"kind": "loaded", "dataset": dataset("live", range(1, 3))})
    assert instance.job_id == live_job
    script.go.set()
    qtbot.waitUntil(lambda: drawn(instance), timeout=10_000)
    assert cast(AnalysisResult, instance.shown).job_id == live_job
    assert instance.view.shot_numbers == (1, 2, 3, 4) and error_line(instance) == ""


def test_with_no_data_anywhere_the_plot_says_so_and_keeps_its_picture(
        window: Window, cache: FolderCache, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    instance = open_plot(window, qtbot, dataset("nowhere", range(1, 3)))
    open_plot(window, qtbot, dataset("other", range(1, 2)))
    assert instance.release()
    picture = cast(ReleasedPlot, instance.released)
    # The disk cache off: nothing to ask.
    monkeypatch.setattr("helab.models.ScriptTreeSelector.store_options", lambda: {})
    picture.reload_button.click()
    assert instance.released is picture and not instance.job_id
    assert "can't reload: its data isn't in RAM or in the disk cache" in picture.state.text()
    assert picture.reload_button.isEnabled()
    # The disk cache on, but it has nothing for the folder.
    monkeypatch.setattr("helab.models.ScriptTreeSelector.store_options", lambda: {"directory": "store"})
    picture.reload_button.click()
    request = next(iter(cache.jobs[("cached", instance.path)].subscribers.values()))
    cache.resultReady.emit(request, {"kind": "error", "message": "No cached data for this folder"})
    assert instance.released is picture and not instance.job_id
    assert picture.state.text().endswith("the disk cache couldn't give it (No cached data for this folder)")
    # Data of the folder that has none of its shots as they were.
    hold(cache, dataset("nowhere", range(1, 3), prints={1: (1, 0, 0), 2: (2, 0, 0)}))
    monkeypatch.setattr("helab.models.ScriptTreeSelector.store_options", lambda: {})
    picture.reload_button.click()
    assert instance.released is picture and "none of its 2 shots" in picture.state.text()


class Fails(Copy):
    fail = False

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        if self.fail:
            raise RuntimeError("boom")
        return super().compute(action_name, context)


@pytest.mark.parametrize("ending", ["failed", "cancelled"])
def test_a_reload_that_draws_nothing_keeps_no_data(window: Window, cache: FolderCache, runner: AnalysisRunner,
                                                    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
                                                    ending: str) -> None:
    """The reviewer's probe: a reload whose run fails (or is cancelled) leaves the plot released,
    holding nothing (its picture aside), so nothing is counted that can't be freed."""
    monkeypatch.setattr("helab.models.ScriptTreeSelector.store_options", lambda: {})
    entry = hold(cache, dataset("f", range(1, 4)))
    script = Fails()
    instance = open_plot(window, qtbot, entry, script)
    open_plot(window, qtbot, dataset("other", range(1, 2)))
    assert instance.release()
    released = instance.released
    assert released is not None
    script.fail = ending == "failed"
    if ending == "cancelled":
        script.go.clear()
    released.reload_button.click()
    assert instance.job_id
    if ending == "cancelled":
        runner.cancel(instance.job_id)
        script.go.set()
    qtbot.waitUntil(lambda: not instance.job_id, timeout=10_000)
    del cache.datasets[(entry.path, entry.signature, 0)]
    assert instance.released is released and instance.view.event_count == 0
    assert instance.ram_buffers() == released.ram_buffers()  # Its picture only.
    assert released.reload_button.isEnabled()
    if ending == "failed":
        assert "boom" in error_line(instance)


class LastTwo(Copy):
    """Draws only the view's last two shots (its coverage), as a "last N shots" selection does."""

    def covered_shots(self, action_name: str, values: Any, view: DatasetView) -> List[int]:
        return sorted(view.shots)[-2:]

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        shots = sorted(context.view.shots)[-2:]
        return Copied(context.view.events(shots).copy(), tuple(shots))


def test_a_reload_takes_exactly_the_shots_the_plot_drew(
        window: Window, cache: FolderCache, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    """Shot 5 of the two drawn (4, 5) is gone: Reload draws shot 4 alone, never shot 3, which the
    plot never drew, and names shot 5. Rerun with the settings shown takes the view's shots."""
    monkeypatch.setattr("helab.models.ScriptTreeSelector.store_options", lambda: {})
    entry = hold(cache, dataset("exact", range(1, 6)))
    reloaded = open_plot(window, qtbot, entry, LastTwo())
    rerun = open_plot(window, qtbot, entry, LastTwo())
    assert cast(AnalysisResult, reloaded.shown).coverage.shots == (4, 5)
    open_plot(window, qtbot, dataset("other", range(1, 2)))
    assert reloaded.release() and rerun.release()
    del cache.datasets[(entry.path, entry.signature, 0)]
    hold(cache, dataset("exact", range(1, 5)))
    cast(ReleasedPlot, reloaded.released).reload_button.click()
    qtbot.waitUntil(lambda: drawn(reloaded), timeout=10_000)
    assert cast(AnalysisResult, reloaded.shown).coverage.shots == (4,) and reloaded.view.shot_numbers == (4,)
    assert error_line(reloaded) == "⚠ Reloaded from RAM without 1 of its 2 shots: shot 5 missing"
    rerun.run()
    qtbot.waitUntil(lambda: drawn(rerun), timeout=10_000)
    assert rerun.view.shot_numbers == (1, 2, 3, 4) and cast(AnalysisResult, rerun.shown).coverage.shots == (3, 4)
    assert error_line(rerun) == "⚠ Reloaded from RAM without 1 of its 5 shots: shot 5 missing"


def test_rerun_on_a_released_plot_reloads_with_the_settings_shown(
        window: Window, cache: FolderCache, qtbot: QtBot) -> None:
    hold(cache, dataset("rerun", range(1, 3)))
    instance = open_plot(window, qtbot, cache.datasets[(folder("rerun"), "sig-rerun-2", 0)])
    open_plot(window, qtbot, dataset("other", range(1, 2)))
    assert instance.release()
    assert instance.parameter_root is not None
    parameter_of(instance.parameter_root, Copy().parameters("Plot")[0]).setValue(3)
    instance.run()
    qtbot.waitUntil(lambda: drawn(instance), timeout=10_000)
    assert cast(AnalysisResult, instance.shown).parameters["scale"] == 3


# Pieces


def test_hollow_and_restore_keep_exactly_the_shots_by_fingerprint() -> None:
    entry = dataset("pieces", range(1, 5))
    view = view_of(entry)
    empty = hollow(view)
    assert empty.identity == view.identity and empty.revision == view.revision
    assert empty.shot_numbers == (1, 2, 3, 4) and empty.event_count == 0 and empty.fingerprints == view.fingerprints
    newer = dataset("pieces", [1, 2, 4, 5], prints={4: (4, 1, 1)})
    restored = restore(empty, newer)
    assert restored.kept == (1, 2) and restored.changed == (4,) and restored.missing == (3,)
    assert restored.view.shot_numbers == (1, 2) and 5 not in restored.view.shots
    assert restored.asked == 4
    only = restore(empty, newer, [2, 3, 9])  # Exactly these (9 isn't the view's): never 1 or 4.
    assert only.kept == (2,) and only.missing == (3,) and only.changed == () and only.view.shot_numbers == (2,)
    assert shots_list([3]) == "3" and shots_list([3, 7]) == "3 and 7"
    assert shots_list(list(range(1, 10))) == "1, 2, 3, 4, 5, 6 and 3 more"


def test_ram_results_released_forgets_the_data() -> None:
    results = RamResults()
    entry = dataset("results", range(1, 2))
    context = AnalysisContext("a1", "Plot", view_of(entry), {"scale": 1}, Copy().get_metadata().identity())
    result = AnalysisResult.of(context, "completed", Copied(np.ones(3), (1,)))
    results.add(result)
    results.pin("a1")
    stub = results.released(result)
    assert stub.data is None and stub.job_id == "a1" and stub.coverage == result.coverage
    assert results.get("a1") is None and len(results) == 0
