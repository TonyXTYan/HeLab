"""F0b folder constants: a folder's own values (fall distance and time, trap frequencies), kept
only in HeLab's store by data root, written only by helpers (newest choice wins), never removed by
Clear all, purges or a root's Clear; they come with listings (with the folders above), and a
folder's subfolders inherit them up to its data root. RAM-only folders keep them for the session."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from helab.io_helper import cache_admin, list_folder
from helab.utils.cache_store import KINDS, CacheStore
from helab.utils.folder_cache import FolderCache, store_options
from helab.utils.io_service import IORequest, IOService
from helab.views.FolderConstantsDialog import FolderConstantsDialog

A, B = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


# The store

def test_constants_are_saved_per_folder_newest_choice_wins_and_survive_clears(tmp_path: Path) -> None:
    root = str(tmp_path / "store")
    with CacheStore(root) as store:
        assert store.set_constants(f"root://{A}/run", {"fall_distance": 0.85}, 10.0) == {
            "values": {"fall_distance": 0.85}, "set_at": 10.0}
        # An older choice (another HeLab, a request arriving late) doesn't overwrite a newer one.
        assert store.set_constants(f"root://{A}/run", {"fall_distance": 0.9}, 5.0)["values"] == {"fall_distance": 0.85}
        # Only finite numbers are kept (which constants exist is the app's business).
        store.set_constants(f"root://{A}/other", {"trap_axial": 40, "x": "text", "y": float("nan"), "z": True}, 11.0)
        store.set_prefs(f"root://{A}/run", True, False, 12.0)
        store.remove(KINDS)  # Clear all.
        store.purge_records(time.time() + 1, include_failures=True)
        store.purge_datasets(time.time() + 1)
        store.clear_root(A)  # Settings › Data roots › Clear cached data…
        store.clear_prefs(13.0)  # The Cache tab's Forget folder choices: flags only.
    with CacheStore(root) as store:  # A restart.
        read = store.read_constants([f"root://{A}/run", f"root://{A}/other", f"root://{A}/run/sub", f"root://{A}"])
        assert read[f"root://{A}/run"].value == {"values": {"fall_distance": 0.85}, "set_at": 10.0}
        assert read[f"root://{A}/other"].value == {"values": {"trap_axial": 40.0}, "set_at": 11.0}
        assert read[f"root://{A}/run/sub"].missing and read[f"root://{A}"].missing  # The store doesn't inherit.
        # Restoring every value keeps the row and its time: an older choice can't bring them back.
        assert store.set_constants(f"root://{A}/run", {}, 20.0) == {"values": {}, "set_at": 20.0}
        assert store.set_constants(f"root://{A}/run", {"fall_distance": 0.9}, 15.0)["values"] == {}


def test_a_nested_roots_rekey_moves_constants_newest_wins(tmp_path: Path) -> None:
    with CacheStore(str(tmp_path / "store")) as store:
        store.set_constants(f"root://{A}/inner/run", {"trap_radial": 400.0}, 10.0)
        store.set_constants(f"root://{A}/inner/old", {"trap_radial": 300.0}, 10.0)
        store.set_constants(f"root://{B}/old", {"trap_radial": 350.0}, 20.0)  # Newer, already there.
        store.rekey_subtree(f"root://{A}/inner", f"root://{B}")
        read = store.read_constants([f"root://{B}/run", f"root://{B}/old", f"root://{A}/inner/run"])
        assert read[f"root://{B}/run"].value == {"values": {"trap_radial": 400.0}, "set_at": 10.0}
        assert read[f"root://{B}/old"].value == {"values": {"trap_radial": 350.0}, "set_at": 20.0}
        assert read[f"root://{A}/inner/run"].missing


def test_unkeyed_paths_are_left_out_only_when_asked(tmp_path: Path) -> None:
    def key(path: str) -> str:
        if not path.startswith("/data"):
            raise ValueError("no data root")
        return path
    with CacheStore(str(tmp_path / "store"), path_key=key) as store:
        store.set_constants("/data/run", {"g": 9.8}, 1.0)
        read = store.read_constants(["/data/run", "/data", "/"], keyed_only=True)
        assert set(read) == {"/data/run", "/data"} and read["/data"].missing
        with pytest.raises(ValueError):
            store.read_constants(["/"])


# Helpers: written only by them, and sent with listings

def test_listings_send_each_subfolders_constants_and_the_folders_above(tmp_path: Path) -> None:
    parent = tmp_path / "data"
    child = parent / "run1"
    (child / "deep").mkdir(parents=True)
    options: dict[str, Any] = {"directory": str(tmp_path / "caches" / "store-v3")}
    list_folder(str(parent), lambda event: None, options)  # Listed first (finds the data root), as in the app.
    events: list[dict[str, Any]] = []
    cache_admin(options, "constants", events.append, path=str(child), values={"fall_distance": 0.85}, set_at=10.0)
    cache_admin(options, "constants", events.append, path=str(tmp_path), values={"trap_axial": 45.0}, set_at=11.0)
    assert events[0] == {"kind": "folder_constants", "folders": {str(child): {"values": {"fall_distance": 0.85},
                                                                              "set_at": 10.0}}}
    listed: list[dict[str, Any]] = []
    list_folder(str(parent), listed.append, options)
    entry = next(e for event in listed if event["kind"] == "entries" for e in event["entries"]
                 if e["path"] == str(child))
    assert entry["constants"] == {"values": {"fall_distance": 0.85}, "set_at": 10.0}
    # Each folder above it with a key that sets some (to the data root here); not the listed folder
    # itself, which sets none, nor a subfolder setting none (no key: none set, with saved_read).
    sent = next(event for event in listed if event["kind"] == "folder_constants")["folders"]
    assert str(parent) not in sent and sent[str(tmp_path)]["values"] == {"trap_axial": 45.0}
    assert all("constants" not in e and e["saved_read"] for event in listed if event["kind"] == "entries"
               for e in event["entries"] if e["path"] != str(child))
    assert str(tmp_path.parent) not in sent  # Above the data root: no key, left out.
    listed.clear()
    list_folder(str(child / "deep"), listed.append, options)
    sent = next(event for event in listed if event["kind"] == "folder_constants")["folders"]
    assert sent[str(child)]["values"] == {"fall_distance": 0.85}
    # Clear all, a purge and the root's Clear keep them.
    uuid = json.loads((tmp_path / ".helab-root").read_text())["uuid"]
    for action, params in (("clear", {}), ("purge", {"cutoff": time.time() + 1, "what": "records",
                                                      "include_failures": True}), ("clear_root", {"uuid": uuid})):
        cache_admin(options, action, lambda event: None, **params)
    listed.clear()
    list_folder(str(parent), listed.append, options)
    entry = next(e for event in listed if event["kind"] == "entries" for e in event["entries"]
                 if e["path"] == str(child))
    assert entry["constants"]["values"] == {"fall_distance": 0.85}


@pytest.mark.no_auto_data_root
def test_a_folder_without_a_data_root_is_answered_session_only(tmp_path: Path) -> None:
    options: dict[str, Any] = {"directory": str(tmp_path / "caches" / "store-v3")}
    events: list[dict[str, Any]] = []
    cache_admin(options, "constants", events.append, path=str(tmp_path), values={"fall_distance": 0.85}, set_at=1.0)
    assert events[0] == {"kind": "folder_constants", "folders": {},
                         "session_only": {str(tmp_path): "no .helab-root found here or above"}}


# FolderCache: memory, inheritance, saving through helpers

def frozen(monkeypatch: pytest.MonkeyPatch) -> tuple[IOService, FolderCache]:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    return service, FolderCache(service)


def admin(service: IOService, action: str) -> IORequest:
    return next(r for r in reversed(service.pending) if r.operation == "cache_admin" and r.payload["action"] == action)


def answer(service: IOService, request: IORequest, *events: dict[str, Any]) -> None:
    for event in events:
        service.resultReady.emit(request, event)
    service.pending.remove(request)


ROOT, RUN, SHOT = os.path.join(os.sep, "data", "root"), os.path.join(os.sep, "data", "root", "run"), \
    os.path.join(os.sep, "data", "root", "run", "a")


def test_subfolders_inherit_the_nearest_folders_values_up_to_the_data_root(monkeypatch: pytest.MonkeyPatch) -> None:
    service, cache = frozen(monkeypatch)
    try:
        cache.data_roots[ROOT] = (A, "root")
        changed: list[str] = []
        cache.constantsChanged.connect(changed.append)
        top = os.path.dirname(ROOT)
        cache.remember_constants(top, {"values": {"trap_axial": 1.0}, "set_at": 1.0})  # Above the root.
        cache.remember_constants(ROOT, {"values": {"trap_axial": 45.0, "fall_distance": 0.85}, "set_at": 1.0})
        cache.remember_constants(RUN, {"values": {"fall_distance": 0.86, "bad": 1.0}, "set_at": 2.0})
        assert changed == [top, ROOT, RUN] and cache.folder_constants(RUN) == {"fall_distance": 0.86}
        assert cache.inherited_constants(SHOT) == {"fall_distance": (0.86, RUN), "trap_axial": (45.0, ROOT)}
        assert cache.effective_folder_constants(SHOT) == {"fall_distance": 0.86, "trap_axial": 45.0}
        # A fall time set above the folder setting the distance isn't paired with it: derived instead.
        cache.remember_constants(ROOT, {"values": {"trap_axial": 45.0, "fall_distance": 0.85, "fall_time": 0.417},
                                        "set_at": 3.0})
        assert "fall_time" not in cache.effective_folder_constants(SHOT)
        assert cache.effective_folder_constants(ROOT)["fall_time"] == 0.417
        # Without a known data root, inheritance goes to the top.
        assert cache.inherited_constants(os.path.join(top, "elsewhere"))["trap_axial"] == (1.0, top)
        # A listing's "none saved" doesn't erase what this session knows; an older record loses.
        cache.remember_constants(RUN, {}, known=False)
        cache.remember_constants(RUN, {"values": {"fall_distance": 0.5}, "set_at": 1.5})
        assert cache.folder_constants(RUN) == {"fall_distance": 0.86}
    finally:
        service.shutdown()


def test_saving_goes_through_a_helper_and_a_failure_shows_the_saved_values_again(
        monkeypatch: pytest.MonkeyPatch) -> None:
    service, cache = frozen(monkeypatch)
    try:
        assert store_options()
        cache.data_roots[ROOT] = (A, "root")
        cache.remember_constants(RUN, {"values": {"fall_distance": 0.85}, "set_at": 1.0})
        failures: list[tuple[str, str, str]] = []
        cache.folderConstantsFailed.connect(lambda *args: failures.append(args))
        assert cache.set_folder_constants(RUN, {"fall_distance": 0.9, "trap_axial": 0.0}, owner="tab")
        assert cache.folder_constants(RUN) == {"fall_distance": 0.9}  # Shown at once; 0 isn't a value.
        request = admin(service, "constants")
        assert request.payload["params"]["path"] == RUN and request.payload["params"]["values"] == {"fall_distance": 0.9}
        set_at = request.payload["params"]["set_at"]
        answer(service, request, {"kind": "folder_constants", "folders": {RUN: {"values": {"fall_distance": 0.9},
                                                                                "set_at": set_at}}},
               {"kind": "done"})
        assert cache.folder_constants(RUN) == {"fall_distance": 0.9} and not failures
        # Another choice fails: the store's last answer shows again, and the tab hears why.
        cache.set_folder_constants(RUN, {}, owner="tab")
        assert cache.folder_constants(RUN) == {}
        answer(service, admin(service, "constants"), {"kind": "error", "message": "disk full"})
        assert cache.folder_constants(RUN) == {"fall_distance": 0.9}
        assert failures == [(RUN, "disk full", "tab")]
    finally:
        service.shutdown()


def test_ram_only_folders_keep_their_constants_for_the_session(monkeypatch: pytest.MonkeyPatch) -> None:
    service, cache = frozen(monkeypatch)
    try:
        cache._remember_unrooted(RUN, "no .helab-root found here or above")
        assert cache.constants_session_only(RUN) == "no .helab-root found here or above"
        assert cache.set_folder_constants(RUN, {"fall_distance": 0.9})
        assert not any(r.operation == "cache_admin" for r in service.pending)  # Nothing to save it in.
        cache.remember_constants(RUN, {}, known=False)  # A listing: none saved there.
        assert cache.folder_constants(RUN) == {"fall_distance": 0.9}
        # A helper that finds no root when saving: kept, and said so.
        cache.set_folder_constants(SHOT, {"trap_axial": 40.0})
        request = admin(service, "constants")
        answer(service, request, {"kind": "folder_constants", "folders": {},
                                  "session_only": {SHOT: "no .helab-root found here or above"}}, {"kind": "done"})
        assert cache.folder_constants(SHOT) == {"trap_axial": 40.0}
        assert cache.constants_session_only(SHOT) == "no .helab-root found here or above"
    finally:
        service.shutdown()


def test_listing_events_fill_in_constants(monkeypatch: pytest.MonkeyPatch) -> None:
    service, cache = frozen(monkeypatch)
    try:
        cache.data_roots[ROOT] = (A, "root")
        assert cache.submit("tab", 0, RUN, "list", {"cache": store_options()})
        request = next(r for r in service.pending if r.operation == "list")
        service.resultReady.emit(request, {"kind": "folder_constants", "folders": {
            ROOT: {"values": {"trap_axial": 45.0}, "set_at": 1.0}, RUN: {}}})
        service.resultReady.emit(request, {"kind": "entries", "entries": [
            {"path": SHOT, "modified": None, "constants": {"values": {"fall_distance": 0.8}, "set_at": 2.0}}]})
        assert cache.effective_folder_constants(SHOT) == {"fall_distance": 0.8, "trap_axial": 45.0}
        assert cache.folder_constants(RUN) == {}
    finally:
        service.shutdown()


# The dialog

def test_the_dialog_shows_each_values_source_and_saves_what_the_folder_sets(
        qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    service, cache = frozen(monkeypatch)
    try:
        cache.data_roots[ROOT] = (A, "root")
        cache.remember_constants(ROOT, {"values": {"trap_axial": 45.0}, "set_at": 1.0})
        cache.remember_constants(RUN, {"values": {"fall_distance": 0.9}, "set_at": 1.0})
        cache.set_lab_constants({"g": 9.8})
        dialog = FolderConstantsDialog(RUN, cache)
        qtbot.addWidget(dialog)
        assert dialog.source_text("fall_distance") == "this folder"
        assert dialog.source_text("trap_axial") == "inherited from root"
        assert dialog.source_text("fall_time") == "derived, √(2h/g)"
        assert dialog.sources["trap_radial"].text().startswith("default · ")  # And unconfirmed.
        assert dialog.editors["fall_time"].value() == pytest.approx((2 * 0.9 / 9.8) ** 0.5)
        assert not dialog.editors["trap_axial"].isEnabled() and dialog.editors["trap_axial"].value() == 45.0
        assert not dialog.session_label.isVisibleTo(dialog)
        # Setting the fall time by hand far from √(2h/g) is noted.
        dialog.set_here["fall_time"].setChecked(True)
        dialog.editors["fall_time"].setValue(0.5)
        assert dialog.source_text("fall_time") == "this folder" and "disagree" in dialog.notes_label.text()
        dialog.restore("fall_distance")  # Back to the default distance (the fall time stays set).
        assert dialog.values() == {"fall_time": 0.5} and dialog.editors["fall_distance"].value() == 0.848
        dialog.save()
        request = admin(service, "constants")
        assert request.payload["params"]["values"] == {"fall_time": 0.5}
    finally:
        service.shutdown()


def test_session_only_values_are_saved_once_the_folder_has_a_data_root(monkeypatch: pytest.MonkeyPatch) -> None:
    service, cache = frozen(monkeypatch)
    try:
        # A helper found no root when saving (proposed: the values wait in RAM, then are saved).
        cache.set_folder_constants(RUN, {"trap_axial": 40.0})
        request = admin(service, "constants")
        answer(service, request, {"kind": "folder_constants", "folders": {},
                                  "session_only": {RUN: "no .helab-root found here or above"}}, {"kind": "done"})
        assert cache.constants_session_only(RUN) and not any(r.operation == "cache_admin" for r in service.pending)
        changed: list[str] = []
        cache.constantsChanged.connect(changed.append)
        cache._root_seen(RUN, A, "run")  # Place .helab-root here: a listing reports the root.
        assert cache.constants_session_only(RUN) == "" and changed == [RUN]
        saved = admin(service, "constants")
        assert saved.payload["params"]["path"] == RUN and saved.payload["params"]["values"] == {"trap_axial": 40.0}
        answer(service, saved, {"kind": "folder_constants", "folders": {RUN: {
            "values": {"trap_axial": 40.0}, "set_at": saved.payload["params"]["set_at"]}}}, {"kind": "done"})
        # Later choices are saved at once.
        cache.set_folder_constants(RUN, {"trap_axial": 41.0})
        assert admin(service, "constants").payload["params"]["values"] == {"trap_axial": 41.0}
    finally:
        service.shutdown()


def test_values_set_while_a_folder_had_no_root_are_saved_when_it_gets_one(monkeypatch: pytest.MonkeyPatch) -> None:
    service, cache = frozen(monkeypatch)
    try:
        cache._remember_unrooted(SHOT, "no .helab-root found here or above")
        cache.set_folder_constants(SHOT, {"fall_distance": 0.9})
        cache.dataRootsChanged.emit(os.path.join(os.sep, "elsewhere"))  # Another root: still none here.
        assert cache.constants_session_only(SHOT) and not any(r.operation == "cache_admin" for r in service.pending)
        cache._root_seen(ROOT, A, "root")  # Found above it.
        assert cache.no_root(SHOT) is None and cache.constants_session_only(SHOT) == ""
        assert admin(service, "constants").payload["params"] == {
            "path": SHOT, "values": {"fall_distance": 0.9},
            "set_at": cache.folder_constant_records[SHOT]["set_at"], "verified_volumes": []}
        # A pending duplicate root, then answered: saved then.
        cache.root_duplicates["smb://x/y"] = {"path": RUN, "uuid": B, "answer": ""}
        cache.set_folder_constants(RUN, {"trap_radial": 400.0})
        assert all(r.payload["params"]["path"] != RUN for r in service.pending if r.operation == "cache_admin")
        cache._duplicate_settled("smb://x/y")
        assert admin(service, "constants").payload["params"]["path"] == RUN
    finally:
        service.shutdown()


def test_a_failed_automatic_save_keeps_the_values_in_ram_and_tries_again(
        monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    service, cache = frozen(monkeypatch)
    try:
        cache._remember_unrooted(RUN, "no .helab-root found here or above")
        cache.set_folder_constants(RUN, {"trap_axial": 40.0})
        failures: list[tuple[str, str, str]] = []
        cache.folderConstantsFailed.connect(lambda *args: failures.append(args))
        cache._root_seen(RUN, A, "run")
        answer(service, admin(service, "constants"), {"kind": "error", "message": "database is locked"})
        assert cache.folder_constants(RUN) == {"trap_axial": 40.0} and failures == []  # No tab asked.
        assert cache.constants_session_only(RUN) == "couldn't be saved (database is locked)"
        assert "Folder constants of" in caplog.text and "database is locked" in caplog.text
        cache.volumesVerified.emit()  # The next root change tries again.
        retry = admin(service, "constants")
        assert retry.payload["params"]["values"] == {"trap_axial": 40.0}
        assert cache.constants_session_only(RUN) == ""
    finally:
        service.shutdown()


def test_no_automatic_save_starts_while_quitting(monkeypatch: pytest.MonkeyPatch) -> None:
    service, cache = frozen(monkeypatch)
    try:
        cache._remember_unrooted(RUN, "no .helab-root found here or above")
        cache.set_folder_constants(RUN, {"trap_axial": 40.0})
        cache.quitting = True
        cache._root_seen(RUN, A, "run")
        assert not any(r.operation == "cache_admin" for r in service.pending)
        assert cache.folder_constants(RUN) == {"trap_axial": 40.0}
    finally:
        service.shutdown()


def test_an_unsupported_mount_answer_stays_through_root_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    service, cache = frozen(monkeypatch)
    try:
        cache.set_folder_constants(RUN, {"trap_axial": 40.0})
        request = admin(service, "constants")
        answer(service, request, {"kind": "folder_constants", "folders": {},
                                  "session_only": {RUN: "NFS mounts aren't supported"}}, {"kind": "done"})
        changed: list[str] = []
        cache.constantsChanged.connect(changed.append)
        for _ in range(2):
            cache.volumesVerified.emit()
            cache.rootDuplicatesChanged.emit()
        cache._root_seen(ROOT, A, "root")
        assert cache.constants_session_only(RUN) == "NFS mounts aren't supported"
        assert not any(r.operation == "cache_admin" for r in service.pending) and RUN not in changed
    finally:
        service.shutdown()


def test_a_nested_root_moves_the_inheritance_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    service, cache = frozen(monkeypatch)
    try:
        cache.data_roots[ROOT] = (A, "root")
        cache.remember_constants(ROOT, {"values": {"trap_axial": 45.0}, "set_at": 1.0})
        assert cache.effective_folder_constants(SHOT) == {"trap_axial": 45.0}
        changed: list[str] = []
        cache.constantsChanged.connect(changed.append)
        cache._root_seen(RUN, B, "run")  # A nested .helab-root found at run.
        assert changed == [RUN] and cache.effective_folder_constants(SHOT) == {}
    finally:
        service.shutdown()


def test_the_dialog_says_when_values_last_only_this_session(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    service, cache = frozen(monkeypatch)
    try:
        cache._remember_unrooted(RUN, "no .helab-root found here or above")
        dialog = FolderConstantsDialog(RUN, cache)
        qtbot.addWidget(dialog)
        assert dialog.session_label.text() == ("RAM only · kept for this session only: "
                                               "no .helab-root found here or above")
        assert dialog.session_label.isVisibleTo(dialog)
    finally:
        service.shutdown()
