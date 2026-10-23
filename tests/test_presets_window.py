"""The main window's part in presets and reopening: the open plots are recorded at quit (before
they close) and come back at the next start; the Presets menu lists the saved arrangements."""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from PyQt6 import QtWebEngineWidgets  # noqa: F401  (before any QApplication: the main window)
from pytestqt.qtbot import QtBot

from helab.analysis.presets import Arrangement, SavedPlot, ScriptRef, parse
from helab.utils.folder_cache import FolderCache, get_folder_cache
from helab.utils.io_service import get_io_service
from helab.utils.settings_defaults import OPEN_PLOTS_SETTING, read_setting
from helab.utils.settings_store import app_settings
from helab.views.plots.arrangement import FolderWait
from helab.views.plots.instance import AnalysisInstance
from helab.views.plots.presets import preset_store, write_arrangement

PATH = "/helab-test-nowhere/run"  # Never read: reopened plots don't touch their folder.


@pytest.fixture(autouse=True)
def fresh_presets(qtbot: QtBot) -> Iterator[None]:
    """The app's FolderCache lasts the worker's run: each test starts with no presets known, and
    its preset helpers end with it (their store is the test's own)."""
    store = preset_store()
    store.presets.clear()
    store.presets_unsaved.clear()
    store.presets_conflicts.clear()
    store._presets_unknown.clear()
    store.presets_read, store.presets_error, store._store = False, "", ""
    yield
    qtbot.waitUntil(lambda: store.service.closed or not store._preset_jobs, timeout=30_000)


def test_plots_open_at_quit_reopen_at_the_next_start(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.views.HelabMainWindow import HelabMainWindow
    monkeypatch.setattr("helab.views.plots.arrangement.store_options", lambda: {})
    window = HelabMainWindow()
    qtbot.addWidget(window)
    scripts = window.panel_right_bottom_script_selector
    cache = get_folder_cache(get_io_service())
    ref = ScriptRef("helab.counts_per_shot", "Plot", "", "", "Counts per shot")
    made = scripts.reopen_plot(SavedPlot(ref, PATH), FolderWait(cache, PATH))
    assert isinstance(made, AnalysisInstance) and made.waiting()
    window.close()
    assert made.is_closed
    [saved] = parse(read_setting(app_settings(), OPEN_PLOTS_SETTING)).plots
    assert saved.script.analysis_id == "helab.counts_per_shot" and saved.path == PATH

    again = HelabMainWindow()
    qtbot.addWidget(again)
    qtbot.waitUntil(lambda: bool(again.panel_right_bottom_script_selector.instances()), timeout=10_000)
    [instance] = again.panel_right_bottom_script_selector.instances()
    assert instance.path == PATH and instance.waiting() and instance.metadata.analysis_id == "helab.counts_per_shot"
    again.close()


def test_the_presets_menu_lists_saved_arrangements(qtbot: QtBot) -> None:
    from helab.views.HelabMainWindow import HelabMainWindow
    write_arrangement("Morning run", Arrangement((), PATH, live=True))
    window = HelabMainWindow()
    qtbot.addWidget(window)
    store = preset_store()
    qtbot.waitUntil(lambda: store.presets_read and not store._preset_jobs, timeout=30_000)
    window.arrangement_presets.fill_menu(window.menu_presets)
    texts = [action.text() for action in window.menu_presets.actions() if not action.isSeparator()]
    assert texts[:2] == ["Save Folder and Plots as Preset…", "Morning run"]
    assert window.menu_presets.title() == "Presets"
    window.close()


def test_applying_a_live_preset_in_a_real_tab_starts_live_once_listed(
        qtbot: QtBot, tmp_path: Path) -> None:
    """A folder with no shots yet (this temp folder): the tab opens it as typing its path would,
    and Live starts once the tab's listing shows it has no TXY files, not before."""
    from helab.views.FolderExplorer import FolderExplorer
    from helab.views.HelabMainWindow import HelabMainWindow
    run = tmp_path / "run"
    run.mkdir()
    folder = FolderCache.key(str(run))
    write_arrangement("Watch run", Arrangement((), folder, live=True))
    window = HelabMainWindow()
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: isinstance(window.tab_widget.currentWidget(), FolderExplorer), timeout=10_000)
    explorer = window.tab_widget.currentWidget()
    assert isinstance(explorer, FolderExplorer)
    window.arrangement_presets.apply("Watch run")
    assert explorer.selected_path_globally == folder and explorer.view_path == folder
    assert explorer.live is None  # Not before the folder is listed.
    qtbot.waitUntil(lambda: explorer.live is not None, timeout=30_000)
    assert explorer.live is not None and explorer.live.path == folder
    window.close()


def test_a_live_off_preset_turns_live_off_in_a_real_tab(qtbot: QtBot, tmp_path: Path) -> None:
    """Flint's probe: a Live preset of an empty folder, then one with Live off for the same folder."""
    from helab.views.FolderExplorer import FolderExplorer
    from helab.views.HelabMainWindow import HelabMainWindow
    run = tmp_path / "run"
    run.mkdir()
    folder = FolderCache.key(str(run))
    write_arrangement("on", Arrangement((), folder, live=True))
    write_arrangement("off", Arrangement((), folder, live=False))
    window = HelabMainWindow()
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: isinstance(window.tab_widget.currentWidget(), FolderExplorer), timeout=10_000)
    explorer = window.tab_widget.currentWidget()
    assert isinstance(explorer, FolderExplorer)
    window.arrangement_presets.apply("on")
    qtbot.waitUntil(lambda: explorer.live is not None, timeout=30_000)
    window.arrangement_presets.apply("off")
    assert explorer.live is None
    window.close()
