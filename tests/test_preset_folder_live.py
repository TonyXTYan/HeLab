"""An arrangement preset's folder in a real window (codebase review 2, Sextant's seam probes):
C-30, online, Live waits for the folder's first load to show its data instead of giving up in the
moment before the load is seen; C-29, offline, a folder never listed online is named as such, not
as "another folder was selected"."""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from PyQt6 import QtWebEngineWidgets  # noqa: F401
from pytestqt.qtbot import QtBot

from helab.analysis.presets import Arrangement, SavedPlot, ScriptRef
from helab.utils import folder_cache, io_service
from helab.utils.folder_cache import FolderCache, get_folder_cache
from helab.utils.io_service import get_io_service
from helab.views.plots.presets import write_arrangement
from test_live import write_shot
from test_presets_window import quit_window


@pytest.fixture(autouse=True)
def back_online() -> Iterator[None]:
    """Every test ends online: the app's IOService and FolderCache last the worker's run, and one
    left working offline made the worker's next real-window tests offline (CI, e35df6f)."""
    yield
    service = io_service._service
    if service is not None and service.folder_cache is not None and service.folder_cache.offline:
        service.folder_cache.set_offline(False)
    folder_cache._offline = False


def window_and_tab(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> tuple[object, object, list[str]]:
    from helab.views.FolderExplorer import FolderExplorer
    from helab.views.HelabMainWindow import HelabMainWindow
    window = HelabMainWindow()
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: isinstance(window.tab_widget.currentWidget(), FolderExplorer), timeout=10_000)
    notices: list[str] = []
    monkeypatch.setattr(window.plots, "notice", notices.append)
    return window, window.tab_widget.currentWidget(), notices


def test_live_waits_for_the_folders_first_load_to_show(qtbot: QtBot, tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.views.FolderExplorer import FolderExplorer
    from helab.views.HelabMainWindow import HelabMainWindow
    run = tmp_path / "run"
    run.mkdir()
    for shot in (1, 2, 3):
        write_shot(run, shot)
    folder = FolderCache.key(str(run))
    write_arrangement("on", Arrangement((), folder, live=True))
    window, explorer, notices = window_and_tab(qtbot, monkeypatch)
    assert isinstance(window, HelabMainWindow) and isinstance(explorer, FolderExplorer)
    service = explorer.model.cache.service
    qtbot.waitUntil(lambda: explorer.model.root is not None and explorer.model.root.loaded
                    and not service.pending and not service.active, timeout=30_000)
    window.arrangement_presets.apply("on")
    qtbot.waitUntil(lambda: explorer.live is not None or any("Live" in notice for notice in notices),
                    timeout=30_000)
    assert explorer.live is not None and notices == ["Preset “on”: Live on for run"], notices
    quit_window(qtbot, window)


@pytest.mark.parametrize("settled", [True, False], ids=["tab_settled", "at_once"])
def test_offline_a_folder_never_listed_is_named_as_such(qtbot: QtBot, tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch, settled: bool) -> None:
    """Settled: the tab opens the folder and its offline listing answers that it was never listed
    (it passed only when the tab's startup default folder answered after the apply and moved the
    selection, CI 2026-10-29). At once: that answer may move the selection either side of the
    apply; the notice is the same."""
    from helab.views.FolderExplorer import FolderExplorer
    from helab.views.HelabMainWindow import HelabMainWindow
    run = tmp_path / "run"
    run.mkdir()
    folder = FolderCache.key(str(run))
    ref = ScriptRef("helab.counts_per_shot", "Plot", "", "", "Counts per shot")
    write_arrangement("p", Arrangement((SavedPlot(ref, folder),), folder, live=True))
    window, explorer, notices = window_and_tab(qtbot, monkeypatch)
    assert isinstance(window, HelabMainWindow) and isinstance(explorer, FolderExplorer)
    if settled:
        service = explorer.model.cache.service
        qtbot.waitUntil(lambda: explorer.model.root is not None and explorer.model.root.loaded
                        and not service.pending and not service.active, timeout=30_000)
    window.set_work_offline(True)
    try:
        assert get_folder_cache(get_io_service()).offline
        window.arrangement_presets.apply("p")
        qtbot.waitUntil(lambda: any(notice.startswith("Preset “p”") for notice in notices), timeout=30_000)
        said = [notice for notice in notices if notice.startswith("Preset “p”")]
        assert said == ["Preset “p”: run can't be opened while working offline (not listed while online): "
                        "its plots wait for its data"], notices
        assert explorer.live is None
    finally:
        window.set_work_offline(False)
    quit_window(qtbot, window)
