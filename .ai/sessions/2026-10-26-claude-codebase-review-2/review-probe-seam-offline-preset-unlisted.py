"""Sextant's seam probe (not for the repo): an arrangement preset with Live applied while working
offline, in a real window."""
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


def test_seam_preset_with_live_applied_offline(qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.views.FolderExplorer import FolderExplorer
    from helab.views.HelabMainWindow import HelabMainWindow
    run = tmp_path / "run"
    run.mkdir()
    folder = FolderCache.key(str(run))
    ref = ScriptRef("helab.counts_per_shot", "Plot", "", "", "Counts per shot")
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
    window.set_work_offline(True)
    assert cache.offline
    window.arrangement_presets.apply("p")
    scripts = window.panel_right_bottom_script_selector
    qtbot.waitUntil(lambda: bool(scripts.instances()), timeout=10_000)
    [instance] = scripts.instances()
    qtbot.waitUntil(lambda: any("Live not started" in n or "Live on" in n for n in notices), timeout=30_000)
    print("NOTICES:", notices)
    print("STARTED OFFLINE:", sorted({r.operation for r in started}))
    print("WAITING:", instance.waiting(), "STATUS:", instance.status_label.text())
    assert explorer.live is None
    print("SELECTED:", explorer.selected_path_globally, "VIEW:", explorer.view_path)
    assert {r.operation for r in started} <= IOService.OFFLINE_OPERATIONS
    quit_window(qtbot, window)
