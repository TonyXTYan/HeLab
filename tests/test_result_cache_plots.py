"""A plot's saved results (result caching R2), through real helpers and the test's own store: a
one-off run is saved, and a plot after a restart (a new runner, new plots) shows it at once
without computing; a changed script or data shows the saved one marked outdated while the run
replaces it; a parameter gives no reuse; Live's reruns and RAM-only folders save nothing; a
result too big for the budget isn't saved and the plot says so; a large one is said once per
save; a cached result counts toward the plot RAM budget."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, List, Optional, cast

import numpy as np
import numpy.typing as npt
import pytest
from PyQt6 import sip
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QDockWidget, QLabel, QMainWindow, QWidget
from pytestqt.qtbot import QtBot

from helab.analysis import result_cache
from helab.analysis.budget import RamBudget
from helab.analysis.dataset_view import DatasetView, build_view
from helab.analysis.parameters import ParameterSpec
from helab.analysis.presets import SavedPlot, ScriptRef
from helab.analysis.result_codec import Declared
from helab.analysis.results import DISK_CACHED, FROM_DISK, AnalysisContext, AnalysisResult
from helab.analysis.runner import AnalysisRunner
from helab.scripts.base import DatasetAnalysis, ScriptMetadata
from helab.utils.cache_store import CacheStore, store_root
from helab.utils.constants import cache_dir
from helab.utils.folder_cache import Dataset, FolderCache, get_folder_cache
from helab.utils.io_service import IOService
from helab.utils.ram_buffers import buffer_of
from helab.views.plots.arrangement import FolderWait
from helab.views.plots.instance import AnalysisInstance
from helab.views.plots.script_tree import TreePanelWidget
from helab.views.plots.workspace import PlotWorkspace

WAIT = 30_000


@dataclass(frozen=True)
class Summed:
    totals: npt.NDArray[np.float64]
    scale: int


class Costly(DatasetAnalysis):
    """A cached analysis: each shot's total, times Scale; counts its computations."""
    version = "1"

    def __init__(self) -> None:
        self.computed = 0
        self.go = threading.Event()
        self.go.set()

    def get_metadata(self) -> ScriptMetadata:
        return self.create_metadata("Costly", "test", "Tests", __file__, "tests.costly", self.version)

    def get_actions(self) -> List[str]:
        return ["Plot"]

    def parameters(self, action_name: str) -> List[ParameterSpec]:
        return [ParameterSpec("scale", "Scale", "int", 1, (1, 10))]

    def cache_supported(self, action_name: str) -> bool:
        return True

    def cache_types(self, action_name: str) -> List[Declared]:
        return [Summed]

    def compute(self, action_name: str, context: AnalysisContext) -> Any:
        assert self.go.wait(10)
        self.computed += 1
        scale = int(context.parameters["scale"])
        return Summed(np.array([array.sum() * scale for array in context.view.shots.values()]), scale)

    def render(self, result: AnalysisResult, parent: Optional[QWidget] = None) -> QWidget:
        data: Summed = result.data
        label = QLabel(f"totals {data.totals.tolist()}", parent)
        label.setObjectName("costly_plot")
        return label


class Plots(PlotWorkspace):
    def __init__(self, window: Window) -> None:
        super().__init__(window, notice=window.notices.append, closing=lambda: window.closing)
        self.window = window

    def current_dataset_view(self) -> DatasetView | None:
        return self.window.view


class Window(QMainWindow):
    def __init__(self, cache: FolderCache, settings: QSettings) -> None:
        super().__init__()
        self.closing = False
        self.view: Optional[DatasetView] = None
        self.notices: list[str] = []
        self.plots = Plots(self)
        self.plots.setup_ram_budget(cache, settings)
        assert self.plots.ram_budget is not None
        self.budget: RamBudget = self.plots.ram_budget


@pytest.fixture(autouse=True)
def reuse_on() -> None:
    """Settings → Cache › Reuse saved analysis results on (off by default since Q27.1). Modules
    that import it from here get it too."""
    from helab.utils.settings_defaults import RESULT_REUSE_SETTING
    from helab.utils.settings_store import app_settings
    settings = app_settings()
    settings.setValue(RESULT_REUSE_SETTING, True)
    settings.sync()


@pytest.fixture
def cache() -> Iterator[FolderCache]:
    """A cache whose helpers run (the local lane), with the test's own store."""
    service = IOService()
    made = get_folder_cache(service)
    made.max_data_bytes = 1 << 40
    yield made
    service.shutdown()


RUNNERS: list[AnalysisRunner] = []


@pytest.fixture(autouse=True)
def stop_runners() -> Iterator[None]:
    yield
    while RUNNERS:
        RUNNERS.pop().stop()


def make_window(qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Window:
    runner = AnalysisRunner()
    RUNNERS.append(runner)
    monkeypatch.setattr("helab.views.plots.instance.get_analysis_runner", lambda: runner)
    window = Window(cache, QSettings(str(tmp_path / f"settings-{time.monotonic_ns()}.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.plots.middle_mainwindow.show()
    return window


def close(window: Window) -> None:
    window.plots.close_plots()
    window.budget.detach()
    if not sip.isdeleted(window.plots.middle_mainwindow):
        window.plots.middle_mainwindow.close()
        window.plots.middle_mainwindow.deleteLater()


def folder_view(tmp_path: Path, name: str = "run", *, changed: int | None = None) -> DatasetView:
    folder = tmp_path / "data" / name
    folder.mkdir(parents=True, exist_ok=True)
    data = {shot: np.full((10, 3), float(shot)) for shot in (1, 2, 3)}
    prints = [[shot, 100 + shot + (1 if shot == changed else 0), 1_000 + shot] for shot in data]
    return build_view(Dataset(FolderCache.key(str(folder)), f"sig-{name}-{changed}", data,
                              {"fingerprint": prints, "source": "files", "loaded_at": time.time()}, 0))


def open_plot(window: Window, qtbot: QtBot, view: DatasetView, script: DatasetAnalysis) -> AnalysisInstance:
    window.view = view
    panel = TreePanelWidget(window.plots)
    qtbot.addWidget(panel)
    instance = panel.run_analysis(script.get_metadata(), script, "Plot")
    window.view = None
    assert isinstance(instance, AnalysisInstance)
    return instance


def settled(instance: AnalysisInstance) -> bool:
    return instance.shown is not None and not instance.job_id


def saved(instance: AnalysisInstance) -> bool:
    return settled(instance) and cast(AnalysisResult, instance.shown).policy == DISK_CACHED


def label(instance: AnalysisInstance, name: str) -> str:
    dock = cast(QDockWidget, instance.dock_widget)
    found = dock.findChild(QLabel, name)
    assert found is not None
    return found.text() + "\n" + found.toolTip()


def results_saved() -> int:
    with CacheStore(store_root(cache_dir())) as store:
        return int(store._conn.execute("SELECT COUNT(*) FROM results").fetchone()[0])


def test_a_saved_result_is_shown_after_a_restart_without_computing(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = Costly()
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    first = open_plot(window, qtbot, folder_view(tmp_path), script)
    qtbot.waitUntil(lambda: saved(first), timeout=WAIT)
    assert script.computed == 1 and results_saved() == 1
    assert "saved in the disk cache" in label(first, "plot_data_source")
    close(window)
    # A restart: a new runner (no results in RAM), new plots, the same disk cache.
    again = Costly()
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    second = open_plot(window, qtbot, folder_view(tmp_path), again)
    qtbot.waitUntil(lambda: settled(second), timeout=WAIT)
    shown = cast(AnalysisResult, second.shown)
    assert again.computed == 0 and shown.source == FROM_DISK and not shown.outdated
    assert np.array_equal(shown.data.totals, [30.0, 60.0, 90.0])
    text = label(second, "plot_data_source")
    assert "from disk cache, computed" in text and "From disk cache, computed" in text
    assert label(second, "plot_error").strip() == ""
    # It counts toward the plot RAM budget like any result.
    assert buffer_of(shown.data.totals)[0] in second.ram_buffers()
    # A parameter changed: no reuse (and nothing outdated: other settings), computed and saved.
    root = second.parameter_root
    assert root is not None
    root.child("scale").setValue(2)
    second.run()
    qtbot.waitUntil(lambda: saved(second) and again.computed == 1, timeout=WAIT)
    assert cast(AnalysisResult, second.shown).source != FROM_DISK and results_saved() == 2
    close(window)


def test_a_reopened_plot_shows_its_exact_saved_result_without_computing(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A plot reopened at start (or from an arrangement preset) runs as the user's first run does
    once its folder's data is found (``run_reopened``): it looks in the disk cache first."""
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    first = open_plot(window, qtbot, folder_view(tmp_path), Costly())
    qtbot.waitUntil(lambda: saved(first), timeout=WAIT)
    close(window)
    # A restart: the plot reopens from its record and waits for its folder's data.
    script = Costly()
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    panel = TreePanelWidget(window.plots)
    qtbot.addWidget(panel)
    metadata = script.get_metadata()
    monkeypatch.setattr(panel, "find_script", lambda ref: (metadata, script))
    view = folder_view(tmp_path)
    wait = FolderWait(cache, view.identity.source_path)
    monkeypatch.setattr(wait, "look", lambda deliberate=False: None)  # (Found below, as RAM or a cached read finds it.)
    instance = panel.reopen_plot(SavedPlot(ScriptRef.of(metadata.identity(), "Plot", metadata.name),
                                           view.identity.source_path, values={"scale": 1}), wait)
    assert isinstance(instance, AnalysisInstance) and instance.waiting()
    wait.found.emit(view)
    qtbot.waitUntil(lambda: settled(instance), timeout=WAIT)
    shown = cast(AnalysisResult, instance.shown)
    assert script.computed == 0 and shown.source == FROM_DISK and not shown.outdated
    assert np.array_equal(shown.data.totals, [30.0, 60.0, 90.0]) and results_saved() == 1
    close(window)


@pytest.mark.parametrize("change", ["script", "data"])
def test_a_changed_script_or_data_shows_the_saved_result_outdated_until_the_run_ends(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    first = open_plot(window, qtbot, folder_view(tmp_path), Costly())
    qtbot.waitUntil(lambda: saved(first), timeout=WAIT)
    script = Costly()
    if change == "script":
        script.version = "2"
    script.go.clear()  # The run waits, so the outdated one shows meanwhile.
    view = folder_view(tmp_path, changed=2 if change == "data" else None)
    second = open_plot(window, qtbot, view, script)
    qtbot.waitUntil(lambda: second.shown is not None, timeout=WAIT)
    shown = cast(AnalysisResult, second.shown)
    assert shown.source == FROM_DISK and shown.outdated and second.job_id
    reason = "script version 1 → 2" if change == "script" else "data changed (1 shot changed)"
    assert reason in label(second, "plot_error") and "outdated" in label(second, "plot_error")
    assert "saved result of" in label(second, "plot_data_source")
    script.go.set()
    qtbot.waitUntil(lambda: saved(second), timeout=WAIT)
    assert cast(AnalysisResult, second.shown).source != FROM_DISK and label(second, "plot_error").strip() == ""
    assert script.computed == 1
    close(window)


def test_live_reruns_are_never_saved(qtbot: QtBot, cache: FolderCache, tmp_path: Path,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []
    submit = cache.service.submit

    def record(owner: str, generation: int, path: str, operation: str, *args: Any, **kwargs: Any) -> bool:
        asked.append(operation)
        return submit(owner, generation, path, operation, *args, **kwargs)
    monkeypatch.setattr(cache.service, "submit", record)
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    script = Costly()
    view = folder_view(tmp_path)
    instance = open_plot(window, qtbot, view, script)
    qtbot.waitUntil(lambda: saved(instance), timeout=WAIT)
    asked.clear()
    revision = view.with_shots({4: np.full((10, 3), 4.0)}, {4: (4, 104, 1_004)})
    window.plots.live_feed.revised.emit(revision)
    qtbot.waitUntil(lambda: script.computed == 2 and settled(instance), timeout=WAIT)
    assert "result_find" not in asked and "result_save" not in asked and results_saved() == 1
    close(window)


@pytest.mark.no_auto_data_root
def test_a_folder_without_a_data_root_keeps_results_in_ram(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    script = Costly()
    instance = open_plot(window, qtbot, folder_view(tmp_path), script)
    qtbot.waitUntil(lambda: settled(instance), timeout=WAIT)
    assert cast(AnalysisResult, instance.shown).policy != DISK_CACHED and script.computed == 1
    qtbot.wait(300)  # (Nothing more arrives.)
    assert results_saved() == 0
    close(window)


@pytest.mark.parametrize("answer", ["Make room", "Discard"])
def test_a_result_over_the_budget_asks_make_room_or_discard(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: str) -> None:
    """Tony, 2026-10-22: a result that doesn't fit waits, and the disk cache asks (CacheDialogs, with
    the dataset saves' questions): Make room saves it (other saved results make room, never cached
    data), Discard drops it; the plot says which."""
    from helab.utils import folder_cache
    from helab.views.CacheDialogs import CacheDialogs
    monkeypatch.setattr(folder_cache, "_disk_budget", 1)
    monkeypatch.setattr(folder_cache, "_disk_budget_set_at", time.time())
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    dialogs = CacheDialogs(cache, window, lambda: None)
    instance = open_plot(window, qtbot, folder_view(tmp_path), Costly())
    qtbot.waitUntil(lambda: dialogs.dialog is not None, timeout=WAIT)
    assert "not saved yet: the disk cache is full (Make room or Discard)" in instance.status_label.text()
    box = dialogs.dialog
    assert box is not None
    assert box.text().startswith("Not enough room in the disk cache to save Costly's result for run (")
    assert "Cached data isn't touched" in box.informativeText() or "isn't enough" in box.informativeText()
    [entry] = cache.pending_results.values()
    assert entry["label"] == "Costly" and results_saved() == 0
    if answer == "Make room":
        # The user raised the budget meanwhile: Make room saves it without removing anything.
        monkeypatch.setattr(folder_cache, "_disk_budget", 8 << 30)
        monkeypatch.setattr(folder_cache, "_disk_budget_set_at", time.time())
        dialogs._answer(entry["pending_id"], dialogs._asking[1], "adopt_result", make_room=False)
        dialogs._close()
        qtbot.waitUntil(lambda: saved(instance), timeout=WAIT)
        assert results_saved() == 1
    else:
        button = next(b for b in box.buttons() if b.text() == "Discard")
        button.click()
        qtbot.waitUntil(lambda: "discarded" in instance.status_label.text(), timeout=WAIT)
        assert results_saved() == 0
    qtbot.waitUntil(lambda: not cache.pending_results, timeout=WAIT)
    dialogs.detach()
    close(window)


def test_a_large_saved_result_is_said_once_per_save(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(result_cache, "LARGE_RESULT_BYTES", 10)
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    instance = open_plot(window, qtbot, folder_view(tmp_path), Costly())
    qtbot.waitUntil(lambda: saved(instance), timeout=WAIT)
    notes = [note for note in window.notices if "in the disk cache" in note]
    assert len(notes) == 1 and notes[0].startswith("Saved Costly (run) in the disk cache: ")
    root = instance.parameter_root
    assert root is not None
    root.child("scale").setValue(3)
    instance.run()
    qtbot.waitUntil(lambda: len([n for n in window.notices if "in the disk cache" in n]) == 2, timeout=WAIT)
    close(window)


def test_clear_cached_analysis_leaves_the_plot_but_its_record_says_ram_only(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    instance = open_plot(window, qtbot, folder_view(tmp_path), Costly())
    qtbot.waitUntil(lambda: saved(instance), timeout=WAIT)
    assert cache.cache_admin("clear_results")
    qtbot.waitUntil(lambda: cast(AnalysisResult, instance.shown).policy != DISK_CACHED, timeout=WAIT)
    assert "kept in RAM only" in label(instance, "plot_data_source") and results_saved() == 0
    assert cast(QDockWidget, instance.dock_widget).findChild(QLabel, "costly_plot") is not None
    close(window)


def test_the_gui_never_opens_the_store_and_helpers_touch_no_source_folder(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Saving and finding results run in local-lane helpers only: in this process the store can't be
    opened, and the helpers' I/O trace (every source-folder operation) records none."""
    trace = tmp_path / "trace"
    trace.mkdir()
    monkeypatch.setenv("HELAB_TEST_IO_TRACE", str(trace))

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the GUI process opened the disk cache")
    monkeypatch.setattr(CacheStore, "__init__", refuse)
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    first = open_plot(window, qtbot, folder_view(tmp_path), Costly())
    qtbot.waitUntil(lambda: saved(first), timeout=WAIT)
    script = Costly()
    second = open_plot(window, qtbot, folder_view(tmp_path), script)
    qtbot.waitUntil(lambda: settled(second), timeout=WAIT)
    assert cast(AnalysisResult, second.shown).source == FROM_DISK and script.computed == 0
    close(window)
    import json
    lines = [json.loads(line) for file in trace.glob("*.jsonl") for line in file.read_text().splitlines() if line]
    # The helpers' own bookkeeping and the mount table (for the folder's key), as every cached read's.
    assert lines and {line["op"] for line in lines} <= {"request", "request_end", "mounts"}


def test_saved_results_count_in_the_usage_the_80_percent_pause_sees(
        qtbot: QtBot, cache: FolderCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.utils import folder_cache
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    instance = open_plot(window, qtbot, folder_view(tmp_path), Costly())
    qtbot.waitUntil(lambda: saved(instance), timeout=WAIT)
    with CacheStore(store_root(cache_dir())) as store:
        with store.transaction(write=False):
            results = store._results_live()
        assert cache.disk_usage == store.usage() and results > 0
    # With a budget the results alone fill past 80 %, automatic loads of uncached folders pause.
    monkeypatch.setattr(folder_cache, "_disk_budget", int(results / 0.81) + int(cache.disk_usage or 0) - results)
    cache.update_auto_load_pause()
    assert cache.auto_load_paused
    close(window)


def source_line(instance: AnalysisInstance) -> str:
    dock = cast(QDockWidget, instance.dock_widget)
    found = dock.findChild(QLabel, "plot_data_source")
    assert found is not None
    return found.text()


class Quick(Costly):
    """The same analysis, not saved (as the quick plots)."""

    def cache_supported(self, action_name: str) -> bool:
        return False


def test_the_source_line_marks_reuse(qtbot: QtBot, cache: FolderCache, tmp_path: Path,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    script = Costly()
    script.go.clear()
    instance = open_plot(window, qtbot, folder_view(tmp_path), script)
    qtbot.waitUntil(lambda: bool(instance.job_id), timeout=WAIT)
    assert cast(QDockWidget, instance.dock_widget).property("plotReuse") is True
    script.go.set()
    qtbot.waitUntil(lambda: saved(instance), timeout=WAIT)
    assert "saved in disk cache" in source_line(instance)
    again = open_plot(window, qtbot, folder_view(tmp_path, "other"), Costly())
    qtbot.waitUntil(lambda: saved(again), timeout=WAIT)
    quick = open_plot(window, qtbot, folder_view(tmp_path, "third"), Quick())
    qtbot.waitUntil(lambda: settled(quick), timeout=WAIT)
    line = source_line(quick)
    assert "disk cache" not in line and "reuse" not in line
    close(window)


def test_with_reuse_off_plots_neither_look_up_nor_save(qtbot: QtBot, cache: FolderCache, tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.utils.settings_defaults import RESULT_REUSE_SETTING
    from helab.utils.settings_store import app_settings
    window = make_window(qtbot, cache, tmp_path, monkeypatch)
    first = open_plot(window, qtbot, folder_view(tmp_path), Costly())
    qtbot.waitUntil(lambda: saved(first), timeout=WAIT)
    first.close()
    settings = app_settings()
    settings.setValue(RESULT_REUSE_SETTING, False)
    settings.sync()
    asked: list[str] = []
    submit = cache.service.submit

    def record(owner: str, generation: int, path: str, operation: str, *args: Any, **kwargs: Any) -> bool:
        asked.append(operation)
        return submit(owner, generation, path, operation, *args, **kwargs)
    monkeypatch.setattr(cache.service, "submit", record)
    script = Costly()
    second = open_plot(window, qtbot, folder_view(tmp_path), script)
    qtbot.waitUntil(lambda: settled(second), timeout=WAIT)
    assert script.computed == 1 and cast(AnalysisResult, second.shown).source != FROM_DISK
    assert "result_find" not in asked and "result_save" not in asked
    assert "disk cache" not in source_line(second) and results_saved() == 1
    close(window)


def test_the_cache_tab_saves_the_reuse_setting(qtbot: QtBot, cache: FolderCache, tmp_path: Path) -> None:
    from helab.utils.settings_defaults import RESULT_REUSE_SETTING, read_setting
    from helab.views.CacheTab import CacheTab
    settings = QSettings(str(tmp_path / "cache-tab.ini"), QSettings.Format.IniFormat)
    tab = CacheTab(cache, settings)
    qtbot.addWidget(tab)
    assert not tab.result_reuse.isChecked()  # Off by default (Q27.1).
    tab.result_reuse.setChecked(True)
    tab.save(settings)
    assert read_setting(settings, RESULT_REUSE_SETTING, typed=True) is True
    tab.result_reuse.setChecked(False)
    tab.save(settings)
    assert read_setting(settings, RESULT_REUSE_SETTING, typed=True) is False
    tab.detach()
