"""Settings → TXY converter (the profile manager, Q6.11), Settings → Cache's converted-TXY row and its
Clear (Q12.3), and a plot's TXY source row (Q6.6, Q6.10). Synthetic files under ``tmp_path`` only."""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
import sqlite3
import time
from typing import Any

import numpy as np
import pytest
from PyQt6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from helab.analysis.dataset_view import build_view
from helab.convert.profile import BUILTIN_PROFILES, MATLAB_2019, DetectorProfile
from helab.convert.user_profiles import ProfileLibrary
from helab.convert import provenance
from helab.io_ops import helab_txy
from helab.io_ops.admin import cache_admin
from helab.utils import constants
from helab.utils.folder_cache import Dataset, store_options
from helab.utils.number_format import byte_size
from helab.views.CacheTab import CacheTab
from helab.views.ConverterTab import ConverterTab, ProfileEditor
from helab.views.plots.txy_source import TxySourceRow, folder_day, plate_note
from helab.utils.folder_cache import FolderCache
from helab.utils.io_service import IOService
from helab.views.plots.instance import AnalysisInstance
from test_constant_layers import FallTime
from test_folder_flags import admin, frozen

# A folder as FolderCache keys it (``FolderCache.key``: on Windows with a drive letter).
RUN = os.path.abspath("/data/run")


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
        # Tabs and Live read helab-priority until set otherwise (Q18.2).
        assert tab.source_combo.currentData() == "helab-priority" and cache.tab_source() == "helab-priority"
        tab.source_combo.setCurrentIndex(tab.source_combo.findData("matlab-priority"))
        tab.save(ini)
        assert constants.read_txy_source(ini) == "matlab-priority" and cache.tab_source() == "matlab-priority"
        assert cache.with_txy(str(tmp_path), {})["txy"]["source"] == "matlab-priority"
        ini.setValue(constants.TXY_SOURCE_SETTING, "matlab")  # (A name before Q18.2.)
        assert constants.read_txy_source(ini) == "matlab-priority"
        ini.setValue(constants.TXY_SOURCE_SETTING, "both")
        assert constants.read_txy_source(ini) == "helab-priority"
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


def indexed(folder: Path, shot: int, used: float = 1.0, output: str = "cache") -> None:
    """The index's row for the folder's TXY of ``shot`` (``output`` beside: a TXY beside the raw files)."""
    name = provenance.txy_name("m19v1", shot)
    info = (folder / name).stat() if output != "beside" else os.stat(folder.parent)
    record = provenance.Provenance(
        shot=shot, raw_name=f"d{shot}.txt", raw_size=1, raw_mtime_ns=1, raw_sha256="", profile_name="matlab-2019",
        profile_version=1, profile_hash="h", profile_tag="m19v1", profile_calibrated=False, backend="numpy",
        output=output, txy_name=name, txy_size=info.st_size, txy_mtime_ns=info.st_mtime_ns, txy_sha256="", hits=1,
        converted_at=used, helab_version="0", read_seconds=0.0, parse_seconds=0.0, reconstruct_seconds=0.0,
        format_seconds=0.0, write_seconds=0.0)
    with provenance.open_index(str(folder.parent), write=True) as index:
        index.record(folder.name, "", "/data/" + folder.name, record, used)


def test_the_helper_measures_and_clears_converted_txy(tmp_path: Path) -> None:
    root = str(tmp_path / "converted-txy")
    # Indexed TXY, and the records of the builds before the index (Q26.2: measured and cleared, never read).
    one = converted_folder(root, "a" * 24, {"d_txy_helab_m19v1_1.txt": b"x" * 10, "d_txy_helab_m19v1_1.json": b"{}",
                                             "folder.json": b"{}", "notes.txt": b"theirs"})
    indexed(one, 1, used=100.0)
    beside = converted_folder(root, "b" * 24, {"d_txy_helab_m19v1_2.json": b"{}", "folder.json": b"{}"})
    indexed(beside, 2, used=200.0, output="beside")
    # A TXY the index doesn't know (an index lost or set aside): measured by its file, cleared too.
    gone = converted_folder(root, "c" * 24, {"d_txy_helab_m19v1_3.txt": b"y" * 5, "d_txy_helab_m19v1_3.json": b"{}",
                                              "folder.json": b"{}"})
    # An old build's leftover temporary folder.json: HeLab's too (so its folder can go); look-alikes stay.
    leftover = converted_folder(root, "d" * 24, {".folder.json.0123456789abcdef.partial": b"half",
                                                  "folder.json": b"{}"})
    (gone / ".folder.json.0123456789abcdeF.partial").write_bytes(b"theirs")
    os.symlink(one / "d_txy_helab_m19v1_1.txt", gone / "d_txy_helab_m19v1_9.txt")
    aside = Path(root) / "index-damaged-20261029T120000Z-0123abcd.sqlite"
    aside.write_bytes(b"damaged")
    (Path(root) / "index-notes.sqlite").write_bytes(b"theirs")
    index_bytes = os.path.getsize(Path(root) / provenance.INDEX_NAME)
    assert helab_txy.converted_usage(root) == {
        "files": 2, "bytes": 10 + 2 + 2 + 2 + 2 + 5 + 2 + 2 + 4 + 2 + 7 + index_bytes, "folders": 4, "last_used": 200.0,
        "newer": 0, "clearable": 7, "clearable_bytes": 10 + 2 + 5 + 2 + 4 + 2 + 7}  # (What Clear removes, below.)
    assert helab_txy.converted_usage(str(tmp_path / "none")) == {
        "files": 0, "bytes": 0, "folders": 0, "last_used": None, "newer": 0, "clearable": 0, "clearable_bytes": 0}
    assert helab_txy.clear_converted(root) == {"files": 2, "bytes": 10 + 2 + 5 + 2 + 4 + 2 + 7}
    # Left: the index (Clear keeps it), the beside TXY's old record and folder.json: nothing more to clear.
    after = helab_txy.converted_usage(root)
    assert (after["files"], after["clearable"], after["clearable_bytes"]) == (0, 0, 0) and after["bytes"] > 0
    assert not leftover.exists()
    assert sorted(os.listdir(one)) == ["folder.json", "notes.txt"]  # Another's file stays, so its folder too.
    assert sorted(os.listdir(beside)) == ["d_txy_helab_m19v1_2.json", "folder.json"]  # A beside TXY's record stays.
    assert sorted(os.listdir(gone)) == [".folder.json.0123456789abcdeF.partial", "d_txy_helab_m19v1_9.txt",
                                        "folder.json"]  # A link is never followed or removed; a look-alike stays.
    assert sorted(os.listdir(root)) == ["a" * 24, "b" * 24, "c" * 24, "index-notes.sqlite", provenance.INDEX_NAME]
    # The removed TXY's row and its folder's row go; the beside TXY's row and folder stay.
    with provenance.open_index(root, write=False) as index:  # type: ignore[union-attr]
        assert [row[0] for row in index.folders()] == ["b" * 24]
        assert list(index.shots("b" * 24)) == [("m19v1", 2)] and index.shots("a" * 24) == {}


def test_a_clear_leaves_a_newer_helabs_index_alone(tmp_path: Path) -> None:
    """An older HeLab's Clear never sets aside or removes a newer HeLab's index (its beside rows are the
    only account of those TXY), live or set aside by a conversion: not counted as ours, said as ``newer``.
    It removes the TXY it was asked to, and damaged set-aside indexes."""
    root = str(tmp_path / "converted-txy")
    folder = converted_folder(root, "a" * 24, {"d_txy_helab_m19v1_1.txt": b"x" * 10})
    indexed(folder, 1)
    index = Path(root) / provenance.INDEX_NAME
    with contextlib.closing(sqlite3.connect(index)) as conn:
        conn.execute(f"PRAGMA user_version = {provenance.SCHEMA + 1}")
        conn.commit()
    newer_aside = Path(root) / "index-newer-20261029T120000Z-0123abcd.sqlite"
    newer_aside.write_bytes(b"newer")
    damaged = Path(root) / "index-damaged-20261029T120000Z-89abcdef.sqlite"
    damaged.write_bytes(b"damaged")
    before = index.read_bytes()
    usage = helab_txy.converted_usage(root)
    assert usage["newer"] == len(before) + 5 and usage["bytes"] == 10 + 7 and usage["files"] == 1
    assert (usage["clearable"], usage["clearable_bytes"]) == (2, 10 + 7)
    assert helab_txy.clear_converted(root) == {"files": 1, "bytes": 10 + 7}
    assert index.read_bytes() == before and newer_aside.exists() and not damaged.exists()
    assert sorted(os.listdir(root)) == [newer_aside.name, provenance.INDEX_NAME]
    assert helab_txy.converted_usage(root) == {"files": 0, "bytes": 0, "folders": 0, "last_used": None,
                                               "newer": len(before) + 5, "clearable": 0, "clearable_bytes": 0}


def test_a_clear_that_removed_rows_gives_their_space_back(tmp_path: Path) -> None:
    """Review Low-6: SQLite reuses a removed row's space but never shrinks the file by itself, so a Clear
    that removed rows ends with a VACUUM: the index is small again."""
    root = str(tmp_path / "converted-txy")
    folder = converted_folder(root, "a" * 24, {provenance.txy_name("m19v1", shot): b"x" for shot in range(400)})
    with provenance.open_index(root, write=True) as index:
        for shot in range(400):
            info = (folder / provenance.txy_name("m19v1", shot)).stat()
            index.record(folder.name, "", "/data/run", provenance.Provenance(
                shot=shot, raw_name=f"d{shot}.txt", raw_size=1, raw_mtime_ns=1, raw_sha256="r" * 64,
                profile_name="matlab-2019", profile_version=1, profile_hash="h" * 64, profile_tag="m19v1",
                profile_calibrated=False, backend="numpy", output="cache", txy_name=provenance.txy_name("m19v1", shot),
                txy_size=info.st_size, txy_mtime_ns=info.st_mtime_ns, txy_sha256="t" * 64, hits=1, converted_at=1.0,
                helab_version="0", read_seconds=0.0, parse_seconds=0.0, reconstruct_seconds=0.0, format_seconds=0.0,
                write_seconds=0.0), 1.0)
    index_file = Path(root) / provenance.INDEX_NAME
    full = index_file.stat().st_size
    assert full > 100_000
    assert helab_txy.clear_converted(root)["files"] == 400
    assert index_file.stat().st_size < full / 4 and sorted(os.listdir(root)) == [provenance.INDEX_NAME]
    assert provenance.read_shots(root, folder.name) == {}


def test_the_clear_question_names_records_when_no_txy_is_left(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
                                                              tmp_path: Path) -> None:
    """Review Nit-6: with only old records or a damaged index to clear, the question doesn't say "0 TXY files"."""
    service, cache = frozen(monkeypatch)
    try:
        tab = CacheTab(cache, settings(tmp_path))
        qtbot.addWidget(tab)
        asked: list[str] = []

        def decline(title: str, text: str, verb: str) -> bool:
            asked.append(text)
            return False
        tab.confirm = decline
        for files, clearable_bytes in ((0, 40_000), (3, 1500)):
            tab.inventory = {"converted_txy": {"files": files, "bytes": 99_000, "clearable": 2,
                                               "clearable_bytes": clearable_bytes}}
            tab.clear_converted()
        assert asked[0].startswith(f"Removes what is left of HeLab's converted TXY: old records and damaged indexes "
                                   f"({byte_size(40_000)}), from the cache and temp folders")
        assert "0 TXY files" not in asked[0]
        assert asked[1].startswith(f"Removes 3 TXY files HeLab converted, with their records ({byte_size(1500)})")
        tab.detach()
    finally:
        service.shutdown()


def test_a_clear_keeps_the_row_of_a_txy_written_again_meanwhile(tmp_path: Path) -> None:
    """Rows go only for the very files removed (name, size, mtime): one a conversion wrote since stays."""
    root = str(tmp_path / "converted-txy")
    folder = converted_folder(root, "a" * 24, {"d_txy_helab_m19v1_1.txt": b"x" * 10})
    indexed(folder, 1)
    with provenance.open_index(root, write=True) as index:
        index.forget_removed(folder.name, [("d_txy_helab_m19v1_1.txt", 10, 1)])  # (Another file of that name.)
        assert list(index.shots(folder.name)) == [("m19v1", 1)]


def test_the_cache_tab_shows_and_clears_converted_txy(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
                                                      tmp_path: Path) -> None:
    service, cache = frozen(monkeypatch)
    try:
        root = helab_txy.converted_root(store_options()["directory"])
        converted_folder(root, "a" * 24, {"d_txy_helab_m19v1_1.txt": b"x" * 1500, "d_txy_helab_m19v1_1.json": b"{}"})
        # The temp folder's too (Q27.5): a Don't cache folder's, or one without a data root.
        temp = converted_folder(os.path.join(constants.DIR_TEMPS, "converted-txy"), "b" * 24,
                                {"d_txy_helab_m19v1_2.txt": b"y" * 498})
        indexed(temp, 2, used=time.time() - 7200)
        temp_bytes = 498 + os.path.getsize(temp.parent / provenance.INDEX_NAME)
        tab = CacheTab(cache, settings(tmp_path))
        qtbot.addWidget(tab)
        asked: list[str] = []

        def accept(title: str, text: str, verb: str) -> bool:
            asked.append(text)
            return True
        tab.confirm = accept
        events: list[Any] = []
        request = admin(service, "inventory")
        # (FolderCache sends the temp folder with every inventory and Clear of them: the helper never reads constants.)
        assert request.payload["params"] == {"temps": constants.DIR_TEMPS}
        cache_admin(store_options(), "inventory", events.append, **request.payload["params"])
        for event in (events[0], {"kind": "done"}):
            service.resultReady.emit(request, event)
        service.pending.remove(request)
        assert tab.converted_label.text() == f"2 files · {byte_size(1502 + temp_bytes)} · last used 2h ago"
        assert tab.converted_button.isEnabled()
        assert tab.converted_label.toolTip().endswith(
            f"Cache folder: 1 file in 1 folder · {byte_size(1502)}\n"
            f"Temp folder: 1 file in 1 folder · {byte_size(temp_bytes)} · last used 2h ago")
        tab.clear_converted()
        assert "Removes 2 TXY files HeLab converted" in asked[0] and "from the cache and temp folders" in asked[0]
        clear = admin(service, "clear_converted_txy")
        assert clear.payload["params"] == {"temps": constants.DIR_TEMPS}
        tab.detach()
        cleared: list[Any] = []
        cache_admin(store_options(), "clear_converted_txy", cleared.append, **clear.payload["params"])
        assert cleared[0] == {"kind": "removed", "kinds": ["converted_txy"], "paths": None, "datasets": 0,
                              "bytes": 1502 + 498}
        assert helab_txy.converted_usage(root)["files"] == 0 and helab_txy.converted_usage(str(temp.parent))["files"] == 0
        # Nit-4: what is left is the temp folder's index, which Clear keeps: shown, but nothing to clear.
        events.clear()
        cache_admin(store_options(), "inventory", events.append, **request.payload["params"])
        tab._job = ""  # (The Clear's job is done: the tab is writable again, as Clear all shows.)
        tab.inventory = events[0]["inventory"]
        tab._update()
        assert tab.clear_all_button.isEnabled()
        index_bytes = os.path.getsize(temp.parent / provenance.INDEX_NAME)
        assert tab.converted_label.text() == f"0 files · {byte_size(index_bytes)}"  # (No folder left to be used.)
        assert not tab.converted_button.isEnabled()
        assert "keeps the index" in tab.converted_label.toolTip()
    finally:
        service.shutdown()


# A plot's TXY source row.


def view_dated(day: str, origins: dict[str, str] | None = None) -> Any:
    when = int(time.mktime(time.strptime(day + " 12:00", "%Y-%m-%d %H:%M")) * 1e9)
    metadata = {"fingerprint": [[1, 10, when]], "raw_times": [[1, when]],
                "txy": {"source": "matlab", "origins": origins or {}}}
    return build_view(Dataset(RUN, "sig", {1: np.zeros((1, 3))}, metadata, 0))


def test_the_row_suggests_a_plate_profile_without_applying_it(qtbot: QtBot) -> None:
    picked: list[tuple[str, str]] = []
    row = TxySourceRow("", lambda source, profile: picked.append((source, profile)))
    qtbot.addWidget(row)
    view = view_dated("2023-02-04")
    assert folder_day(view) == "2023-02-04"
    assert plate_note(view, "matlab-2019") == "plates-2022 suggested for this folder's date (2023-02-04)"
    assert plate_note(view, "plates-2022") == "" and plate_note(view_dated("2016-01-01"), "matlab-2019") == ""
    row.show_profile(view, "matlab-2019")
    assert row.note.text() == ("HeLab converts with matlab-2019 · plates-2022 suggested for this folder's date "
                               "(2023-02-04)")
    assert "it is not applied" in row.note.toolTip()
    assert row.source() == "" and row.combo.currentText() == "As the folder's tab"
    row.combo.setCurrentIndex(row.combo.findData("helab-only"))
    assert picked == [("helab-only", "")] and row.source() == "helab-only"
    # The profile whose HeLab TXY are read, by its tag (Q18.2).
    assert row.profile_combo.findText("plates-2022 (p22v1)") >= 0
    row.profile_combo.setCurrentIndex(row.profile_combo.findData("plates-2022"))
    assert picked[-1] == ("helab-only", "plates-2022") and row.profile() == "plates-2022"
    row.set_source("matlab-priority", "")  # (Set by the plot: not a choice.)
    assert len(picked) == 2 and row.profile() == "" and row.profile_combo.isEnabled()
    row.combo.setCurrentIndex(row.combo.findData("matlab-only"))
    assert not row.profile_combo.isEnabled()  # (MATLAB's alone: no profile.)


# A plot switching its TXY source (``AnalysisInstance.set_txy_source``).


def test_a_plot_loads_its_own_source_and_goes_back_to_the_tabs(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    cache = FolderCache(service)
    try:
        path = RUN
        tab_data = Dataset(path, "sig", {1: np.zeros((1, 3))},
                           {"fingerprint": [[1, 10, 100]],
                            "txy": {"source": "helab-priority", "origins": {}, "profile_tag": "m19v1", "tab": True}},
                           0)
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
                         "txy": {"source": "helab-only", "origins": {"1": "helab:h", "2": "helab:h"},
                                 "profile_tag": "m19v1"}}, 0)
        instance._source_owner = ""  # (The load answered.)
        instance._source_loaded(helab)
        assert ran[-1].identity.source == "helab-only" and sorted(ran[-1].shots) == [1, 2]
        # Live's next: a revision of the plot's own source, offered as it follows.
        newer = Dataset(path, "sig", {**helab.data, 3: np.ones((1, 3))},
                        {"fingerprint": [[1, 11, 101], [2, 12, 102], [3, 13, 103]],
                         "txy": {"source": "helab-only", "origins": {"1": "helab:h", "2": "helab:h", "3": "helab:h"},
                                 "profile_tag": "m19v1"}},
                        0)
        instance.follow.start(ran[-1])
        instance.follow.end(time.monotonic())
        instance._source_loaded(newer)
        assert instance.follow.latest.revision == 2 and instance.follow.latest.added_shots == (3,)
        # Another profile's (Q18.2): its own load, by its tag; a dataset of the choice before is ignored.
        instance.set_txy_source("helab-only", "matlab-2023-lab-edit")
        request = [r for r in service.pending if r.operation == "load"][-1]
        assert request.payload["txy"]["profile_tag"] == "m23v1" and instance.txy_choice() == "helab-only@m23v1"
        assert request.payload["txy"]["profile"]["name"] == "matlab-2023-lab-edit"
        assert instance.follow_text().startswith("TXY: HeLab only (m23v1) (loading…)")
        instance._source_owner = ""
        before = len(ran)
        instance._source_loaded(newer)
        assert len(ran) == before
        # Back to the tab's data, also after Settings changed the tabs' source (Avocet's review): until the
        # folder loads again, the data the tab shows is still the tab's.
        cache.set_tab_source("matlab-priority")
        instance.set_txy_source("")
        assert instance.on_tab_choice() and ran[-1].identity.source == "" and ran[-1].shots.keys() == {1}
        instance.close()
    finally:
        service.shutdown()


def test_deleting_the_profile_in_use_falls_back_at_once(qtbot: QtBot, tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    service, cache = frozen(monkeypatch)
    try:
        ini = settings(tmp_path)
        ProfileLibrary(str(tmp_path / "profiles")).save(MATLAB_2019.replace(name="mine", search_depth=40))
        ini.setValue(constants.CONVERT_PROFILE_SETTING, "mine")
        tab = tab_for(qtbot, tmp_path, cache, ini)
        tab.confirm = lambda title, text, verb: True  # type: ignore[method-assign]
        select(tab, "mine")
        tab.delete_selected()
        # Even if Settings is then cancelled, the setting never names the deleted profile.
        assert ini.value(constants.CONVERT_PROFILE_SETTING) == "matlab-2019"
        assert cache.convert_profile() is MATLAB_2019 and tab.profile_combo.currentData() == "matlab-2019"
    finally:
        service.shutdown()


def test_the_plate_note_says_uncalibrated(qtbot: QtBot) -> None:
    assert plate_note(view_dated("2025-07-01"), "matlab-2019") == (
        "plates-2025 (uncalibrated) suggested for this folder's date (2025-07-01)")


def test_reload_of_a_released_plot_on_another_source(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    cache = FolderCache(service)
    try:
        helab = Dataset(RUN, "sig", {1: np.ones((1, 3)), 2: np.ones((1, 3))},
                        {"fingerprint": [[1, 11, 101], [2, 12, 102]],
                         "txy": {"source": "helab-only", "origins": {"1": "helab:h", "2": "helab:h"},
                                 "profile_tag": "m19v1"}}, 0)
        instance = AnalysisInstance(FallTime().get_metadata(), FallTime(), "Plot", build_view(helab), "1", None,
                                    cache=cache)
        ran: list[Any] = []
        monkeypatch.setattr(instance, "_submit", lambda view, *args, **kwargs: ran.append(view))
        states: list[str] = []
        instance.released = SimpleNamespace(set_state=lambda text, busy=False: states.append(text))  # type: ignore[assignment]
        instance.shown = SimpleNamespace(parameters={}, constant_layers={}, input=instance.view.key,  # type: ignore[assignment]
                                         job_id="", coverage=SimpleNamespace(shots=(1, 2)))
        # Shown again (not the user's Reload): its data isn't in RAM, and it doesn't read the folder.
        instance.reload()
        assert not [r for r in service.pending if r.operation == "load"]
        assert "Reload loads it again from the folder" in states[-1]
        # The user's Reload: its source is loaded, then it draws on exactly its shots.
        instance._nowhere = False
        instance.reload(deliberate=True)
        [request] = [r for r in service.pending if r.operation == "load"]
        assert request.payload["txy"]["source"] == "helab-only" and states[-1] == "loading its TXY source…"
        instance._source_owner = ""
        instance._source_loaded(helab)
        assert ran[-1].identity.source == "helab-only" and sorted(ran[-1].shots) == [1, 2]
        instance.released = None
        instance.close()
    finally:
        service.shutdown()
