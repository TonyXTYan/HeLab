"""Settings → TXY converter (the profile manager, Q6.11), Settings → Cache's converted-TXY row and its
Clear (Q12.3), and a plot's TXY source row (Q6.6, Q6.10). Synthetic files under ``tmp_path`` only."""
from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any

import numpy as np
import pytest
from PyQt6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from helab.analysis.dataset_view import build_view
from helab.convert.profile import BUILTIN_PROFILES, MATLAB_2019, DetectorProfile
from helab.convert.user_profiles import ProfileLibrary
from helab.io_ops import helab_txy
from helab.io_ops.admin import cache_admin
from helab.utils import constants
from helab.utils.folder_cache import Dataset, store_options
from helab.views.CacheTab import CacheTab
from helab.views.ConverterTab import ConverterTab, ProfileEditor
from helab.views.plots.txy_source import TxySourceRow, folder_day, plate_note
from helab.utils.folder_cache import FolderCache
from helab.utils.io_service import IOService
from helab.views.plots.instance import AnalysisInstance
from test_constant_layers import FallTime
from test_folder_flags import admin, frozen


def settings(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


def tab_for(qtbot: QtBot, tmp_path: Path, cache: Any = None, ini: QSettings | None = None) -> ConverterTab:
    tab = ConverterTab(cache, ini or settings(tmp_path), folder=str(tmp_path / "profiles"))
    qtbot.addWidget(tab)
    tab.say = lambda text: pytest.fail(f"unexpected message: {text}")  # type: ignore[method-assign]
    return tab


def select(tab: ConverterTab, name: str) -> None:
    for row in range(tab.list.count()):
        item = tab.list.item(row)
        if item is not None and item.data(0x0100) == name:
            tab.list.setCurrentItem(item)
            return
    raise AssertionError(f"{name} not listed")


def test_the_builtins_are_listed_read_only(qtbot: QtBot, tmp_path: Path) -> None:
    tab = tab_for(qtbot, tmp_path)
    labels = [tab.list.item(row).text() for row in range(tab.list.count())]  # type: ignore[union-attr]
    assert [label.split(" ")[0] for label in labels] == list(BUILTIN_PROFILES)
    assert "uncalibrated" in labels[-1] and "default" in labels[0]
    select(tab, "plates-2022")
    assert not tab.edit_button.isEnabled() and not tab.delete_button.isEnabled()
    assert tab.duplicate_button.isEnabled() and "Plates in since 2022-11-03" in tab.details.text()
    assert tab.profile_combo.currentData() == "matlab-2019" and tab.backend_combo.currentData() == "numpy"
    assert tab.output_combo.currentData() == "cache"


def test_duplicate_edit_export_import_and_delete(qtbot: QtBot, tmp_path: Path) -> None:
    tab = tab_for(qtbot, tmp_path)
    names = iter(["mine", "imported"])
    tab.ask_name = lambda title, suggestion: next(names)  # type: ignore[method-assign]
    select(tab, "plates-2022")
    tab.duplicate_selected()
    library = ProfileLibrary(str(tmp_path / "profiles"))
    mine = library.find("mine")
    assert mine is not None and mine.notes.startswith("Copied from plates-2022") and tab.selected() == "mine"
    assert tab.edit_button.isEnabled() and tab.delete_button.isEnabled()
    tab.edit = lambda profile: profile.replace(time_sum_t_x=3367.0, version=2)  # type: ignore[method-assign]
    tab.edit_selected()
    assert library.find("mine") == mine.replace(time_sum_t_x=3367.0, version=2)
    exported = tmp_path / "out.json"
    tab.export_selected(str(exported))
    assert DetectorProfile.from_json(exported.read_text()).time_sum_t_x == 3367.0
    tab.import_file(str(exported))  # Its name is taken: asked for another.
    assert library.find("imported") is not None
    asked: list[str] = []

    def decline(title: str, text: str, verb: str) -> bool:
        asked.append(text)
        return False
    tab.confirm = decline  # type: ignore[method-assign]
    select(tab, "mine")
    tab.delete_selected()
    assert library.find("mine") is not None and "mine.json" in asked[0]  # Declined: kept.
    tab.confirm = lambda title, text, verb: True  # type: ignore[method-assign]
    tab.delete_selected()
    assert library.find("mine") is None


def test_saving_picks_the_profile_backend_and_output(qtbot: QtBot, tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    service, cache = frozen(monkeypatch)
    try:
        ini = settings(tmp_path)
        ProfileLibrary(str(tmp_path / "profiles")).save(MATLAB_2019.replace(name="mine", search_depth=40))
        tab = tab_for(qtbot, tmp_path, cache, ini)
        tab.profile_combo.setCurrentIndex(tab.profile_combo.findData("mine"))
        tab.backend_combo.setCurrentIndex(tab.backend_combo.findData("rust"))
        tab.output_combo.setCurrentIndex(tab.output_combo.findData("temp"))
        tab.save(ini)
        assert ini.value(constants.CONVERT_PROFILE_SETTING) == "mine"
        assert ini.value(constants.CONVERT_BACKEND_SETTING) == "rust"
        assert constants.read_convert_output(ini) == "temp"
        # Loads now want HeLab's TXY made with that profile's output.
        assert cache.convert_profile().search_depth == 40
        assert cache.with_txy(str(tmp_path), {})["txy"]["profile_hash"] == cache.convert_profile().content_hash()
        # A saved profile that's gone: shown as not found, saved as the default.
        ini.setValue(constants.CONVERT_PROFILE_SETTING, "deleted")
        gone = tab_for(qtbot, tmp_path, None, ini)
        assert "not found" in gone.profile_combo.currentText()
        gone.save(ini)
        assert ini.value(constants.CONVERT_PROFILE_SETTING) == "matlab-2019"
    finally:
        service.shutdown()


def test_unreadable_files_are_named(qtbot: QtBot, tmp_path: Path) -> None:
    folder = tmp_path / "profiles"
    folder.mkdir()
    (folder / "broken.json").write_text("{")
    tab = tab_for(qtbot, tmp_path)
    texts = [tab.list.item(row).text() for row in range(tab.list.count())]  # type: ignore[union-attr]
    assert any(text.startswith("⚠ broken.json") for text in texts)


def test_the_editor_validates_shows_the_hash_and_bumps_the_version(qtbot: QtBot) -> None:
    editor = ProfileEditor(MATLAB_2019.replace(name="mine"))
    qtbot.addWidget(editor)
    save = editor.buttons.button(editor.buttons.StandardButton.Save)
    assert save is not None and save.isEnabled() and "same output" in editor.hash_label.text()
    line = editor.editors["time_sum_t_x"]
    line.setText("3367")  # type: ignore[attr-defined]
    assert "saved as v2" in editor.hash_label.text()
    line.setText("abc")  # type: ignore[attr-defined]
    assert not save.isEnabled() and "must be a number" in editor.problem.text()
    line.setText("-1")  # type: ignore[attr-defined]
    assert not save.isEnabled() and "zero or positive" in editor.problem.text()
    line.setText("3367")  # type: ignore[attr-defined]
    editor.editors["notes"].setText("halo fit")  # type: ignore[attr-defined]
    editor.accept_profile()
    assert editor.result_profile is not None
    assert (editor.result_profile.version, editor.result_profile.time_sum_t_x, editor.result_profile.notes) == (
        2, 3367.0, "halo fit")


# Settings → Cache: HeLab's converted TXY.


def converted_folder(root: str, name: str, files: dict[str, bytes]) -> Path:
    folder = Path(root) / name
    folder.mkdir(parents=True)
    for file, data in files.items():
        (folder / file).write_bytes(data)
    return folder


def test_the_helper_measures_and_clears_converted_txy(tmp_path: Path) -> None:
    root = str(tmp_path / "converted-txy")
    one = converted_folder(root, "a" * 24, {"d_txy_helab_1.txy": b"x" * 10, "d_txy_helab_1.json": b"{}",
                                             "folder.json": b"{}", "notes.txt": b"theirs"})
    beside = converted_folder(root, "b" * 24, {"d_txy_helab_2.json": b"{}", "folder.json": b"{}"})
    gone = converted_folder(root, "c" * 24, {"d_txy_helab_3.txy": b"y" * 5, "d_txy_helab_3.json": b"{}",
                                              "folder.json": b"{}"})
    os.symlink(one / "d_txy_helab_1.txy", gone / "d_txy_helab_9.txy")
    assert helab_txy.converted_usage(root) == {"files": 2, "bytes": 10 + 2 + 2 + 2 + 2 + 5 + 2 + 2, "folders": 3}
    assert helab_txy.clear_converted(root) == {"files": 2, "bytes": 10 + 2 + 5 + 2}
    assert sorted(os.listdir(one)) == ["folder.json", "notes.txt"]  # Another's file stays, so its folder too.
    assert sorted(os.listdir(beside)) == ["d_txy_helab_2.json", "folder.json"]  # A beside TXY's record stays.
    assert sorted(os.listdir(gone)) == ["d_txy_helab_9.txy", "folder.json"]  # A link is never followed or removed.


def test_the_cache_tab_shows_and_clears_converted_txy(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
                                                      tmp_path: Path) -> None:
    service, cache = frozen(monkeypatch)
    try:
        root = helab_txy.converted_root(store_options()["directory"])
        converted_folder(root, "a" * 24, {"d_txy_helab_1.txy": b"x" * 1500, "d_txy_helab_1.json": b"{}"})
        tab = CacheTab(cache, settings(tmp_path))
        qtbot.addWidget(tab)
        asked: list[str] = []

        def accept(title: str, text: str, verb: str) -> bool:
            asked.append(text)
            return True
        tab.confirm = accept
        events: list[Any] = []
        cache_admin(store_options(), "inventory", events.append)
        request = admin(service, "inventory")
        for event in (events[0], {"kind": "done"}):
            service.resultReady.emit(request, event)
        service.pending.remove(request)
        assert tab.converted_label.text() == "1 file · 1.5 kB" and tab.converted_button.isEnabled()
        tab.clear_converted()
        assert "Removes 1 TXY file HeLab converted" in asked[0]
        assert admin(service, "clear_converted_txy").payload["params"] == {}
        tab.detach()
        cleared: list[Any] = []
        cache_admin(store_options(), "clear_converted_txy", cleared.append)
        assert cleared[0] == {"kind": "removed", "kinds": ["converted_txy"], "paths": None, "datasets": 0,
                              "bytes": 1502}
        assert helab_txy.converted_usage(root)["files"] == 0
    finally:
        service.shutdown()


# A plot's TXY source row.


def view_dated(day: str, origins: dict[str, str] | None = None) -> Any:
    when = int(time.mktime(time.strptime(day + " 12:00", "%Y-%m-%d %H:%M")) * 1e9)
    metadata = {"fingerprint": [[1, 10, when]], "raw_times": [[1, when]],
                "txy": {"source": "matlab", "origins": origins or {}}}
    return build_view(Dataset("/data/run", "sig", {1: np.zeros((1, 3))}, metadata, 0))


def test_the_row_suggests_a_plate_profile_without_applying_it(qtbot: QtBot) -> None:
    picked: list[str] = []
    row = TxySourceRow("matlab", picked.append)
    qtbot.addWidget(row)
    view = view_dated("2023-02-04")
    assert folder_day(view) == "2023-02-04"
    assert plate_note(view, "matlab-2019") == "plates-2022 suggested for this folder's date (2023-02-04)"
    assert plate_note(view, "plates-2022") == "" and plate_note(view_dated("2016-01-01"), "matlab-2019") == ""
    row.show_profile(view, "matlab-2019")
    assert row.note.text() == ("HeLab converts with matlab-2019 · plates-2022 suggested for this folder's date "
                               "(2023-02-04)")
    assert "it is not applied" in row.note.toolTip()
    row.combo.setCurrentIndex(row.combo.findData("helab-only"))
    assert picked == ["helab-only"] and row.source() == "helab-only"
    row.set_source("matlab")  # (Set by the plot: not a choice.)
    assert picked == ["helab-only"]


# A plot switching its TXY source (``AnalysisInstance.set_txy_source``).


def test_a_plot_loads_its_own_source_and_goes_back_to_the_tabs(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    cache = FolderCache(service)
    try:
        path = "/data/run"
        tab_data = Dataset(path, "sig", {1: np.zeros((1, 3))},
                           {"fingerprint": [[1, 10, 100]], "txy": {"source": "matlab", "origins": {}}}, 0)
        cache.datasets[cache.dataset_key(tab_data)] = tab_data
        instance = AnalysisInstance(FallTime().get_metadata(), FallTime(), "Plot", build_view(tab_data), "1", None,
                                    cache=cache)
        ran: list[Any] = []
        monkeypatch.setattr(instance, "_submit", lambda view, *args, **kwargs: ran.append(view))
        instance.set_txy_source("helab-only")
        [request] = [r for r in service.pending if r.operation == "load"]
        assert request.payload["txy"]["source"] == "helab-only" and request.payload["no_cache"] is True
        assert instance.follow_text() == "TXY: HeLab only (loading…)"
        helab = Dataset(path, "sig", {1: np.ones((1, 3)), 2: np.ones((1, 3))},
                        {"fingerprint": [[1, 11, 101], [2, 12, 102]],
                         "txy": {"source": "helab-only", "origins": {"1": "helab:h", "2": "helab:h"}}}, 0)
        instance._source_owner = ""  # (The load answered.)
        instance._source_loaded(helab)
        assert ran[-1].identity.source == "helab-only" and sorted(ran[-1].shots) == [1, 2]
        # Live's next: a revision of the plot's own source, offered as it follows.
        newer = Dataset(path, "sig", {**helab.data, 3: np.ones((1, 3))},
                        {"fingerprint": [[1, 11, 101], [2, 12, 102], [3, 13, 103]],
                         "txy": {"source": "helab-only", "origins": {"1": "helab:h", "2": "helab:h", "3": "helab:h"}}},
                        0)
        instance.follow.start(ran[-1])
        instance.follow.end(time.monotonic())
        instance._source_loaded(newer)
        assert instance.follow.latest.revision == 2 and instance.follow.latest.added_shots == (3,)
        # A dataset of another source (asked for before a change) is ignored; back to the tab's data.
        instance.set_txy_source("matlab")
        assert ran[-1].identity.source == "" and ran[-1].shots.keys() == {1}
        instance.close()
    finally:
        service.shutdown()
