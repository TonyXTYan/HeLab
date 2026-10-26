"""Sextant's seam probe 2 (not for the repo): a folder seen online with Live, then Work Offline and
an arrangement preset with a plot and Live for it."""
from __future__ import annotations
from pathlib import Path
import pytest
from PyQt6 import QtWebEngineWidgets  # noqa: F401
from pytestqt.qtbot import QtBot
from helab.analysis.presets import Arrangement, SavedPlot, ScriptRef
from helab.utils.folder_cache import FolderCache, get_folder_cache
from helab.utils.io_service import IORequest, IOService, get_io_service
from helab.views.explorer_live import OFFLINE_LIVE
from helab.views.plots.presets import write_arrangement
from test_live import write_shot
from test_presets_window import quit_window
from test_offline_browsing import SOURCE


def test_seam_preset_for_a_folder_seen_online_applied_offline(qtbot: QtBot, tmp_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.views.FolderExplorer import FolderExplorer
    from helab.views.HelabMainWindow import HelabMainWindow
    run = tmp_path / "run"
    run.mkdir()
    for shot in (1, 2, 3):
        write_shot(run, shot)
    folder = FolderCache.key(str(run))
    ref = ScriptRef("helab.counts_per_shot", "Plot", "", "", "Counts per shot")
    write_arrangement("on", Arrangement((), folder, live=True))
    write_arrangement("p", Arrangement((SavedPlot(ref, folder),), folder, live=True))
    started: list[IORequest] = []
    real_start = IOService._start

    def start(service: IOService, request: IORequest, lane: str) -> None:
        real_start(service, request, lane)
        if request in service.active and service.offline:
            assert not (request.operation in SOURCE and not IOService.finishes_offline(request)), (
                f"Source operation started offline: {request.operation} {request.path}")
            started.append(request)
    monkeypatch.setattr(IOService, "_start", start)
    window = HelabMainWindow()
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: isinstance(window.tab_widget.currentWidget(), FolderExplorer), timeout=10_000)
    explorer = window.tab_widget.currentWidget()
    assert isinstance(explorer, FolderExplorer)
    cache = get_folder_cache(get_io_service())
    notices: list[str] = []
    monkeypatch.setattr(window.plots, "notice", notices.append)
    root = explorer.model.root
    qtbot.waitUntil(lambda: explorer.model.root is not None and explorer.model.root.loaded
                    and not explorer.model.cache.service.pending and not explorer.model.cache.service.active,
                    timeout=30_000)
    print("STARTUP SELECTED:", explorer.selected_path_globally)
    window.arrangement_presets.apply("on")
    qtbot.waitUntil(lambda: explorer.live is not None or any("Live" in n for n in notices), timeout=30_000)
    print("ONLINE STATE: live", explorer.live is not None, "opened", explorer.folder_opened_path == folder,
          "data", explorer.folder_opened_data is not None, "selected", explorer.selected_path_globally == folder,
          "load_error", repr(explorer.load_error), "unavailable", repr(explorer.live_unavailable(folder)))
    print("ONLINE NOTICES:", notices)
    window.set_work_offline(True)
    assert cache.offline and explorer.live is None
    notices.clear()
    window.arrangement_presets.apply("p")
    scripts = window.panel_right_bottom_script_selector
    qtbot.waitUntil(lambda: bool(scripts.instances()), timeout=10_000)
    [instance] = scripts.instances()
    qtbot.waitUntil(lambda: instance.shown is not None and not instance.job_id, timeout=30_000)
    qtbot.waitUntil(lambda: any("Live" in n for n in notices), timeout=30_000)
    print("OFFLINE NOTICES:", notices)
    print("STARTED OFFLINE:", sorted({r.operation for r in started}))
    print("SHOTS SHOWN:", instance.shown.coverage.shots, "SOURCE:", instance.shown.source)
    assert explorer.live is None
    assert any(OFFLINE_LIVE in n for n in notices), notices
    assert {r.operation for r in started} <= IOService.OFFLINE_OPERATIONS
    quit_window(qtbot, window)
