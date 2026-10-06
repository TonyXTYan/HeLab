import os
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