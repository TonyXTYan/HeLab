import os
import sys
import tempfile
from pathlib import Path
from typing import Callable

import pytest
from PyQt6.QtCore import QSettings
from helab.utils.constants import *

@pytest.fixture
def cleanup_settings(tmp_path: Path) -> Callable[[], QSettings]:
    """Fresh, file-backed QSettings in the test's tmp dir.

    An ini file under tmp_path (rather than a uniquely named native store)
    keeps tests isolated across xdist workers without leaving a
    ~/Library/Preferences/*.plist behind per test on macOS.
    """
    path = str(tmp_path / "helab_test_settings.ini")
    def _cleanup_settings() -> QSettings:
        return QSettings(path, QSettings.Format.IniFormat)
    return _cleanup_settings

def test_returns_setting_if_valid(cleanup_settings: Callable[[], QSettings], tmp_path: Path) -> None:
    valid_dir = tmp_path / "valid_dir"
    valid_dir.mkdir()
    settings = cleanup_settings()
    settings.setValue("test_key", str(valid_dir))
    candidates = [str(tmp_path / "another_dir")]

    result = get_path_from_setting_or_use_default("test_key", candidates, settings=settings)
    assert result == str(valid_dir)

def test_uses_first_candidate_if_setting_invalid(cleanup_settings: Callable[[], QSettings], tmp_path: Path) -> None:
    invalid_path = str(tmp_path / "does_not_exist")
    valid_candidate = tmp_path / "valid_candidate"
    valid_candidate.mkdir()
    settings = cleanup_settings()
    settings.setValue("test_key", invalid_path)
    candidates = [str(valid_candidate), "/nope/nope"]

    result = get_path_from_setting_or_use_default("test_key", candidates, settings=settings)
    assert result == str(valid_candidate)

def test_uses_first_candidate_if_setting_absent(cleanup_settings: Callable[[], QSettings], tmp_path: Path) -> None:
    valid_candidate = tmp_path / "valid_candidate2"
    valid_candidate.mkdir()
    candidates = [str(valid_candidate)]
    settings = cleanup_settings()

    result = get_path_from_setting_or_use_default("no_such_key", candidates, settings=settings)
    assert result == str(valid_candidate)

def test_returns_empty_if_no_candidates_valid(cleanup_settings: Callable[[], QSettings], tmp_path: Path) -> None:
    settings = cleanup_settings()
    settings.setValue("test_key", "/non/existing")
    candidates = [str(tmp_path / "cand1"), str(tmp_path / "cand2")]

    with pytest.raises(NotADirectoryError):
        _ = get_path_from_setting_or_use_default("test_key", candidates, settings=settings)

def test_setting_with_multiple_valid_candidates(cleanup_settings: Callable[[], QSettings], tmp_path: Path) -> None:
    valid_candidate1 = tmp_path / "valid_candidate1"
    valid_candidate2 = tmp_path / "valid_candidate2"
    valid_candidate1.mkdir()
    valid_candidate2.mkdir()
    settings = cleanup_settings()
    settings.setValue("test_key", str(valid_candidate1))
    candidates = [str(valid_candidate2), str(valid_candidate1)]

    result = get_path_from_setting_or_use_default("test_key", candidates, settings=settings)
    assert result == str(valid_candidate1)

def test_setting_with_no_valid_candidates(cleanup_settings: Callable[[], QSettings], tmp_path: Path) -> None:
    settings = cleanup_settings()
    settings.setValue("test_key", "/non/existing")
    candidates = ["/nope/nope1", "/nope/nope2"]

    with pytest.raises(NotADirectoryError):
        _ = get_path_from_setting_or_use_default("test_key", candidates, settings=settings)

def test_setting_with_mixed_valid_and_invalid_candidates(cleanup_settings: Callable[[], QSettings], tmp_path: Path) -> None:
    valid_candidate = tmp_path / "valid_candidate"
    valid_candidate.mkdir()
    settings = cleanup_settings()
    settings.setValue("test_key", "/non/existing")
    candidates = ["/nope/nope1", str(valid_candidate), "/nope/nope2"]

    result = get_path_from_setting_or_use_default("test_key", candidates, settings=settings)
    assert result == str(valid_candidate)

@pytest.mark.parametrize("platform, env, expected", [
    ("darwin", {}, ("Library", "Caches", "HeLab", "caches")),
    ("win32", {"LOCALAPPDATA": "LOCAL"}, ("LOCAL", "HeLab", "caches")),
    ("win32", {}, ("AppData", "Local", "HeLab", "caches")),
    ("linux", {"XDG_CACHE_HOME": "XDG"}, ("XDG", "HeLab", "caches")),
    ("linux", {}, (".cache", "HeLab", "caches")),
])
def test_default_app_dir_is_a_persistent_per_user_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str, env: dict[str, str], expected: tuple[str, ...],
) -> None:
    monkeypatch.setattr("sys.platform", platform)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for name in ("LOCALAPPDATA", "XDG_CACHE_HOME"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, str(tmp_path / value))
    assert Path(default_app_dir("caches")) == tmp_path.joinpath(*expected)


def test_missing_default_folder_is_created(cleanup_settings: Callable[[], QSettings], tmp_path: Path) -> None:
    target = tmp_path / "HeLab" / "caches"
    settings = cleanup_settings()
    assert get_path_from_setting_or_use_default("dir_caches", [str(target)], settings, create=True) == str(target)
    assert target.is_dir() and settings.value("dir_caches") == str(target)


@pytest.mark.skipif(sys.platform == "win32", reason="chmod cannot make a Windows folder read-only")
def test_read_only_saved_folder_is_replaced(cleanup_settings: Callable[[], QSettings], tmp_path: Path) -> None:
    # E.g. a cache path saved by an elevated session; it used to crash HeLab at import.
    locked, fallback = tmp_path / "locked", tmp_path / "fallback"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        settings = cleanup_settings()
        settings.setValue("dir_caches", str(locked))
        assert get_path_from_setting_or_use_default("dir_caches", [str(fallback)], settings, create=True) == str(fallback)
    finally:
        locked.chmod(0o700)


def legacy_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str) -> Path:
    system_temp = tmp_path / "system-temp"
    system_temp.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(system_temp))
    folder = system_temp / name
    folder.mkdir()
    (folder / "data_ram_cache").mkdir()
    return folder


def test_legacy_temp_cache_is_moved_to_the_persistent_folder(
    cleanup_settings: Callable[[], QSettings], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    old = legacy_folder(monkeypatch, tmp_path, "helab_caches_wbnee1u8")
    target = tmp_path / "Library" / "Caches" / "HeLab" / "caches"
    settings = cleanup_settings()
    settings.setValue("dir_caches", str(old))
    migrate_legacy_temp_dir("dir_caches", "caches", settings, str(target))
    assert not old.exists() and (target / "data_ram_cache").is_dir()
    assert settings.value("dir_caches") == str(target)


@pytest.mark.parametrize("case", ["user folder", "target exists", "rename fails"])
def test_legacy_move_never_loses_or_overwrites_a_cache(
    cleanup_settings: Callable[[], QSettings], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, case: str,
) -> None:
    old = legacy_folder(monkeypatch, tmp_path, "my_caches" if case == "user folder" else "helab_caches_x")
    target = tmp_path / "HeLab" / "caches"
    if case == "target exists":
        target.mkdir(parents=True)
    if case == "rename fails":
        def fail(*args: object) -> None:
            raise OSError("cross-device link")
        monkeypatch.setattr(os, "rename", fail)
    settings = cleanup_settings()
    settings.setValue("dir_caches", str(old))
    migrate_legacy_temp_dir("dir_caches", "caches", settings, str(target))
    assert (old / "data_ram_cache").is_dir() and settings.value("dir_caches") == str(old)
