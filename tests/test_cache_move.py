"""Roadmap S9: moving the disk cache folder, and recovering a move a crash interrupted.

Every crash case ends with one valid store and the setting pointing at it."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Any, Callable

import pytest

from helab.utils import cache_move
from helab.utils.cache_move import COPY, RENAME, MoveCancelled, MoveError
from helab.utils.cache_store import CacheStore, DatasetRecord, store_root

RECORD: DatasetRecord = {"ram_bytes": 1, "rows": 1, "shots": 1, "fingerprint": [], "problematic": [], "info": {}}


class Crash(Exception):
    pass


def make_cache(folder: Path, datasets: int = 3) -> str:
    """A cache folder holding a store with a few datasets; returns its store id."""
    with CacheStore(store_root(str(folder))) as store:
        for index in range(datasets):
            path = f"/data/run{index}"
            store.save_dataset(path, store.write_dataset_file(os.urandom(5000 + index)), RECORD,
                               store.start_dataset_job(path))
        return store.store_id


class Setting:
    """The ``dir_caches`` setting; ``fail`` makes saving it fail (sync/status error)."""

    def __init__(self, value: str) -> None:
        self.value, self.fail = value, False

    def read(self) -> str:
        return self.value

    def write(self, value: str) -> bool:
        if self.fail:
            return False
        self.value = value
        return True


def crash_at(point: str) -> Callable[[str], None]:
    def crash(reached: str) -> None:
        if reached == point:
            raise Crash(point)
    return crash


def no_progress(done: int, total: int) -> None:
    pass


def never() -> bool:
    return False


@pytest.fixture
def folders(tmp_path: Path) -> tuple[str, str, str, str]:
    """(app folder, source cache folder, target folder, store id)."""
    app, source, target = tmp_path / "app", tmp_path / "caches", tmp_path / "moved" / "caches"
    return str(app), str(source), str(target), make_cache(source)


def force(method: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache_move, "same_disk", lambda source, target: method == RENAME)


def run(app: str, source: str, target: str, setting: Setting, crash: Callable[[str], None]) -> None:
    """The whole move as the app runs it: check, record, move, cutover, cleanup."""
    checked = cache_move.check_target(source, target)
    assert not checked["problem"]
    record = cache_move.start(source, target, app, checked["method"])
    record = cache_move.move(record, app, no_progress, never, crash)
    updated = cache_move.cutover(app, record, setting.write, crash)
    assert updated is not None
    assert cache_move.cleanup(app, updated, crash) == []


def assert_one_store(app: str, source: str, target: str, setting: Setting, store_id: str) -> None:
    valid = [path for path in (source, target) if cache_move.valid_at(path, store_id)]
    assert valid == [setting.value], (valid, setting.value)
    assert cache_move.read_record(app) is None


@pytest.mark.parametrize("method", [RENAME, COPY])
def test_a_move_ends_with_one_store_and_the_setting_pointing_at_it(
    folders: tuple[str, str, str, str], method: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, target, store_id = folders
    force(method, monkeypatch)
    setting = Setting(source)
    run(app, source, target, setting, lambda point: None)
    assert setting.value == target and not os.path.exists(source)
    assert_one_store(app, source, target, setting, store_id)
    with CacheStore(store_root(target)) as store:
        assert store.read_dataset("/data/run2").value is not None


MOVE_POINTS = {RENAME: ["started", "rename", "renamed", "setting", "setting_updated"],
               COPY: ["started", "partial", "copy", "copied", "verify", "verified", "setting", "setting_updated",
                      "partial-delete", "cleanup", "old_deleted"]}


@pytest.mark.parametrize("method, point", [(method, point) for method, points in MOVE_POINTS.items()
                                           for point in points])
def test_a_crash_at_any_step_is_recovered_at_the_next_start(
    folders: tuple[str, str, str, str], method: str, point: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, target, store_id = folders
    force(method, monkeypatch)
    setting = Setting(source)
    crash = crash_at(point)
    if point == "partial":
        # Part of the files copied, then the crash.
        copied: list[int] = []

        def progress(done: int, total: int) -> None:
            copied.append(done)
            if len(copied) == 2:
                raise Crash("partial")
        record = cache_move.start(source, target, app, COPY)
        with pytest.raises(Crash):
            cache_move.move(record, app, progress, never)
    elif point == "partial-delete":
        # The cutover happened; the old folder was partly deleted, then the crash.
        record = cache_move.start(source, target, app, COPY)
        record = cache_move.move(record, app, no_progress, never)
        updated = cache_move.cutover(app, record, setting.write)
        assert updated is not None
        os.remove(os.path.join(store_root(source), "records.sqlite"))
    else:
        with pytest.raises(Crash):
            run(app, source, target, setting, crash)
    message = cache_move.recover(app, setting.read, setting.write)
    assert message or point == "old_deleted"
    assert_one_store(app, source, target, setting, store_id)
    # Recovering again changes nothing.
    assert cache_move.recover(app, setting.read, setting.write) == ""


@pytest.mark.parametrize("point", ["recover-setting", "recover-recorded", "cleanup"])
def test_a_crash_during_recovery_is_recovered_the_same_way(
    folders: tuple[str, str, str, str], point: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, target, store_id = folders
    force(COPY, monkeypatch)
    setting = Setting(source)
    record = cache_move.start(source, target, app, COPY)
    cache_move.move(record, app, no_progress, never)  # Verified, then the crash before the cutover.
    with pytest.raises(Crash):
        cache_move.recover(app, setting.read, setting.write, crash_at(point))
    cache_move.recover(app, setting.read, setting.write)
    assert setting.value == target
    assert_one_store(app, source, target, setting, store_id)


def test_the_old_folder_is_deleted_only_after_the_cutover(
    folders: tuple[str, str, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, target, store_id = folders
    force(COPY, monkeypatch)
    record = cache_move.move(cache_move.start(source, target, app, COPY), app, no_progress, never)
    assert record["step"] == "verified"
    cache_move.cleanup(app, record)  # Too early: nothing is deleted, and the record stays.
    assert cache_move.valid_at(source, store_id) and cache_move.read_record(app) == record


def test_an_unverified_copy_is_undone_even_when_it_finished(
    folders: tuple[str, str, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, target, store_id = folders
    force(COPY, monkeypatch)
    setting = Setting(source)
    with pytest.raises(Crash):
        run(app, source, target, setting, crash_at("copied"))
    assert cache_move.valid_at(target, store_id)  # Complete, but never verified...
    assert "undone" in cache_move.recover(app, setting.read, setting.write)
    assert setting.value == source and not os.path.exists(target)  # ...so it is redone next time.


def test_a_corrupt_copy_fails_verification_and_the_source_stays(
    folders: tuple[str, str, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, target, store_id = folders
    force(COPY, monkeypatch)
    copy_tree = cache_move._copy_tree

    def damaged(*args: Any) -> None:
        copy_tree(*args)
        datasets = os.path.join(store_root(args[1]), "datasets")  # The copy (made in a staging folder).
        victim = os.path.join(datasets, sorted(os.listdir(datasets))[0])
        with open(victim, "r+b") as file:
            file.truncate(10)
    monkeypatch.setattr(cache_move, "_copy_tree", damaged)
    record = cache_move.start(source, target, app, COPY)
    with pytest.raises(MoveError, match="failed verification: a copied data file has the wrong size"):
        cache_move.move(record, app, no_progress, never)
    assert cache_move.abort(app, cache_move.read_record(app) or record) == []
    assert not os.path.exists(target) and cache_move.valid_at(source, store_id)
    assert cache_move.read_record(app) is None


@pytest.mark.parametrize("table", ["results", "pending_results"])
@pytest.mark.parametrize("damage", ["missing", "size"])
def test_a_copy_with_a_damaged_result_file_fails_verification(
    folders: tuple[str, str, str, str], table: str, damage: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, target, store_id = folders
    force(COPY, monkeypatch)
    path = "root://aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/run"
    with CacheStore(store_root(source)) as store:
        file = store.write_result_file(os.urandom(5000))
        saved = store.save_result(path, "k1", "f1", {}, file, store.start_result_job(path), analysis_id="a",
                                  action="Plot", computed_at=1.0, budget=0 if table == "pending_results" else None)
        assert saved.saved == (table == "results") and bool(saved.pending_id) == (table == "pending_results")
    assert cache_move.verify(source, store_id) == ""
    copy_tree = cache_move._copy_tree

    def damaged(*args: Any) -> None:
        copy_tree(*args)
        victim = os.path.join(store_root(args[1]), *file.split("/"))  # The copy's result file.
        if damage == "missing":
            os.remove(victim)
        else:
            with open(victim, "r+b") as handle:
                handle.truncate(10)
    monkeypatch.setattr(cache_move, "_copy_tree", damaged)
    record = cache_move.start(source, target, app, COPY)
    problem = "a data file is missing from the copy" if damage == "missing" else "a copied data file has the wrong size"
    with pytest.raises(MoveError, match=f"failed verification: {problem} \\({file}\\)"):
        cache_move.move(record, app, no_progress, never)
    assert cache_move.abort(app, cache_move.read_record(app) or record) == []
    assert not os.path.exists(target) and cache_move.valid_at(source, store_id)


def test_files_put_in_the_target_after_the_check_are_never_deleted(
    folders: tuple[str, str, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, target, store_id = folders
    force(COPY, monkeypatch)
    os.makedirs(target)
    assert not cache_move.check_target(source, target)["problem"]  # Empty when checked...
    copy_tree = cache_move._copy_tree

    def meanwhile(*args: Any) -> None:
        copy_tree(*args)
        Path(target, "mine.txt").write_text("the user's")  # ...then the user puts a file there.
    monkeypatch.setattr(cache_move, "_copy_tree", meanwhile)
    record = cache_move.start(source, target, app, COPY)
    with pytest.raises(MoveError, match="isn't empty anymore"):
        cache_move.move(record, app, no_progress, never)
    assert cache_move.abort(app, cache_move.read_record(app) or record) == []
    assert os.listdir(target) == ["mine.txt"] and not os.path.exists(cache_move.staging_path(target))
    assert cache_move.valid_at(source, store_id) and cache_move.read_record(app) is None
    # A target that isn't empty when the move starts is refused before anything happens.
    with pytest.raises(MoveError, match="isn't empty anymore"):
        cache_move.start(source, target, app, COPY)


def test_only_this_moves_marked_copy_is_ever_deleted(
    folders: tuple[str, str, str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    app, source, target, store_id = folders
    force(COPY, monkeypatch)
    # A folder already where the staging folder goes isn't HeLab's: refused, and kept.
    staging = cache_move.staging_path(target)
    os.makedirs(staging)
    Path(staging, "mine.txt").write_text("x")
    record = cache_move.start(source, target, app, COPY)
    with pytest.raises(MoveError, match="in the way"):
        cache_move.move(record, app, no_progress, never)
    assert cache_move.abort(app, record) == [] and os.listdir(staging) == ["mine.txt"]
    shutil.rmtree(staging)
    # A user's own copy of the cache (same store id, no marker) is never taken for this move's.
    shutil.copytree(source, target)
    assert cache_move.valid_at(target, store_id)
    cache_move.write_record(app, {**record, "step": "copied"})
    assert cache_move.abort(app, {**record, "step": "copied"}) == []
    assert cache_move.valid_at(target, store_id) and cache_move.valid_at(source, store_id)


def test_recovery_never_trusts_a_folder_now_somewhere_unsafe(
    folders: tuple[str, str, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, target, store_id = folders
    force(COPY, monkeypatch)
    setting = Setting(source)
    cache_move.move(cache_move.start(source, target, app, COPY), app, no_progress, never)  # Verified.
    # Meanwhile the target became a link into a synced folder.
    monkeypatch.setattr(cache_move, "cache_location_problem",
                        lambda path: "in a synced folder (Dropbox)" if path == target else "")
    assert "kept using" in cache_move.recover(app, setting.read, setting.write)
    assert setting.value == source and cache_move.valid_at(source, store_id)  # The safe source survives.


def test_a_move_never_overwrites_an_unfinished_ones_record(folders: tuple[str, str, str, str]) -> None:
    app, source, target, store_id = folders
    pending = {"from": "/old", "to": source, "method": COPY, "step": "setting_updated", "store_id": store_id,
               "id": "earlier"}
    cache_move.write_record(app, pending)
    with pytest.raises(MoveError, match="earlier cache move hasn't finished"):
        cache_move.start(source, target, app, RENAME)
    assert cache_move.read_record(app) == pending


def test_renaming_back_counts_even_if_its_record_cant_be_deleted(
    folders: tuple[str, str, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, target, store_id = folders
    force(RENAME, monkeypatch)
    record = cache_move.move(cache_move.start(source, target, app, RENAME), app, no_progress, never)

    def denied(app_dir: str) -> None:
        raise PermissionError("denied")
    monkeypatch.setattr(cache_move, "delete_record", denied)
    assert cache_move.undo_rename(app, record)
    assert cache_move.valid_at(source, store_id) and not os.path.exists(target)


def test_an_abort_after_the_rename_renames_it_back(
    folders: tuple[str, str, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, target, store_id = folders
    force(RENAME, monkeypatch)
    setting = Setting(source)
    record = cache_move.start(source, target, app, RENAME)
    with pytest.raises(Crash):
        cache_move.move(record, app, no_progress, never, crash_at("rename"))  # Renamed, not yet recorded.
    assert cache_move.abort(app, record) == []
    assert_one_store(app, source, target, setting, store_id)


def test_cancel_during_the_copy_keeps_the_source(
    folders: tuple[str, str, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, target, store_id = folders
    force(COPY, monkeypatch)
    calls: list[bool] = []

    def cancelled() -> bool:
        calls.append(True)
        return len(calls) > 2
    record = cache_move.start(source, target, app, COPY)
    with pytest.raises(MoveCancelled):
        cache_move.move(record, app, no_progress, cancelled)
    assert cache_move.abort(app, record) == []
    assert not os.path.exists(target) and cache_move.valid_at(source, store_id)


def test_a_settings_write_that_fails_is_before_the_cutover(
    folders: tuple[str, str, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, target, store_id = folders
    # Copy: the copy is discarded and the source stays.
    force(COPY, monkeypatch)
    setting = Setting(source)
    setting.fail = True
    record = cache_move.move(cache_move.start(source, target, app, COPY), app, no_progress, never)
    assert cache_move.cutover(app, record, setting.write) is None
    assert cache_move.read_record(app) == record  # Not recorded as updated.
    # Verified: only an abort that knows the cutover failed discards it.
    assert cache_move.abort(app, record, before_cutover=True) == []
    assert setting.value == source and not os.path.exists(target)
    assert_one_store(app, source, target, setting, store_id)


def test_a_rename_whose_setting_fails_is_renamed_back_or_repaired_next_start(
    folders: tuple[str, str, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, target, store_id = folders
    force(RENAME, monkeypatch)
    setting = Setting(source)
    setting.fail = True
    record = cache_move.move(cache_move.start(source, target, app, RENAME), app, no_progress, never)
    assert cache_move.cutover(app, record, setting.write) is None
    # Renamed back: as if nothing happened.
    assert cache_move.undo_rename(app, record)
    assert_one_store(app, source, target, setting, store_id)
    # Renaming back fails too: the destination is used, and the next start fixes the setting.
    record = cache_move.move(cache_move.start(source, target, app, RENAME), app, no_progress, never)
    def busy(a: str, b: str) -> None:
        raise OSError("busy")
    monkeypatch.setattr(os, "rename", busy)
    assert not cache_move.undo_rename(app, record)
    monkeypatch.undo()
    setting.fail = False
    assert "finished" in cache_move.recover(app, setting.read, setting.write)
    assert setting.value == target
    assert_one_store(app, source, target, setting, store_id)


def test_a_settings_write_failing_during_recovery_keeps_the_record(
    folders: tuple[str, str, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, target, store_id = folders
    force(COPY, monkeypatch)
    setting = Setting(source)
    cache_move.move(cache_move.start(source, target, app, COPY), app, no_progress, never)
    setting.fail = True
    assert "tries again" in cache_move.recover(app, setting.read, setting.write)
    assert cache_move.read_record(app) is not None and cache_move.valid_at(source, store_id)
    setting.fail = False
    cache_move.recover(app, setting.read, setting.write)
    assert_one_store(app, source, target, setting, store_id)


def test_a_finished_move_whose_copy_is_now_unreadable_is_reported_not_forgotten(
    folders: tuple[str, str, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, target, store_id = folders
    force(COPY, monkeypatch)
    setting = Setting(source)
    with pytest.raises(Crash):
        run(app, source, target, setting, crash_at("old_deleted"))
    os.remove(os.path.join(store_root(target), "records.sqlite"))  # The new cache is damaged.
    assert "unreadable" in cache_move.recover(app, setting.read, setting.write)
    # Nothing valid is left: the record is kept for the log, set aside so it doesn't hold up the cache.
    assert cache_move.read_record(app) is None
    assert any(name.startswith("cache-move.failed-") for name in os.listdir(app))


def test_an_unreadable_copy_with_a_good_source_keeps_the_record_until_the_setting_is_saved(
    folders: tuple[str, str, str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, target, store_id = folders
    force(COPY, monkeypatch)
    setting = Setting(source)
    with pytest.raises(Crash):
        run(app, source, target, setting, crash_at("setting_updated"))  # Cut over; the old folder not deleted yet.
    os.remove(os.path.join(store_root(target), "records.sqlite"))  # The copy is now unreadable.
    setting.fail = True
    assert "tries again" in cache_move.recover(app, setting.read, setting.write)
    assert cache_move.read_record(app) is not None  # Not set aside: the source is fine.
    setting.fail = False
    cache_move.recover(app, setting.read, setting.write)
    assert setting.value == source and cache_move.read_record(app) is None


def test_the_cache_is_usable_after_recovery_only_where_the_store_is(folders: tuple[str, str, str, str]) -> None:
    app, source, target, store_id = folders
    assert cache_move.usable_after_recovery(app, source)  # No move left.
    cache_move.write_record(app, {"from": source, "to": target, "method": COPY, "step": "started",
                                  "store_id": store_id, "id": "m"})
    assert cache_move.usable_after_recovery(app, source)  # The setting names the store.
    assert not cache_move.usable_after_recovery(app, target)  # It doesn't: don't open a new one there.


def test_a_cache_folder_holding_the_app_folder_isnt_moved(folders: tuple[str, str, str, str]) -> None:
    app, source, target, store_id = folders
    inside = os.path.join(source, "app")
    problem = cache_move.check_target(source, target, inside)["problem"]
    assert problem.startswith("The cache folder contains HeLab's own folder")
    assert not cache_move.check_target(source, target, app)["problem"]


def test_the_target_is_checked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "caches"
    make_cache(source)
    assert cache_move.check_target(str(source), str(source / "inside"))["problem"] == (
        "The new folder can't be inside the current cache folder.")
    full = tmp_path / "full"
    full.mkdir()
    (full / "x").write_text("x")
    assert "isn't empty" in cache_move.check_target(str(source), str(full))["problem"]
    synced = tmp_path / "Dropbox" / "caches"
    assert "in a synced folder (Dropbox)" in cache_move.check_target(str(source), str(synced))["problem"]
    monkeypatch.setattr(cache_move, "cache_location_problem", lambda path: "on a network drive (smbfs)")
    assert "on a network drive (smbfs)" in cache_move.check_target(str(source), str(tmp_path / "net"))["problem"]
    monkeypatch.undo()
    fine = cache_move.check_target(str(source), str(tmp_path / "new" / "caches"))
    assert fine["problem"] == "" and fine["method"] == RENAME and fine["bytes"] > 15_000
    force(COPY, monkeypatch)
    monkeypatch.setattr(cache_move.shutil, "disk_usage", lambda path: shutil._ntuple_diskusage(1, 1, 100))  # type: ignore[attr-defined]
    assert cache_move.check_target(str(source), str(tmp_path / "new2"))["problem"].startswith("Not enough space on ")
