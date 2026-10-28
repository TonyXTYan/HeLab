"""Detector profiles for the profile manager: the plate built-ins and their JSON files (A10.3), the
plate swap suggestion (Q6.10), the user's profile files (Q6.11) and the settings that pick one."""
from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings

from helab.convert.profile import (BUILTIN_PROFILES, DESCRIPTIVE, MATLAB_2019, PLATE_SWAPS, UNCALIBRATED,
                                   DetectorProfile, ProfileError, builtin_files, suggested_plates)
from helab.convert.user_profiles import ProfileLibrary, check_name, duplicate


def test_the_packaged_json_files_load_equal_to_the_definitions() -> None:
    assert builtin_files() == dict(BUILTIN_PROFILES)


def test_the_plate_profiles_start_as_matlab_2019() -> None:
    for name in ("plates-2017", "plates-2022", "plates-2025"):
        profile = BUILTIN_PROFILES[name]
        changed = {field.name for field in dataclasses.fields(DetectorProfile)
                   if getattr(profile, field.name) != getattr(MATLAB_2019, field.name)}
        assert changed <= set(DESCRIPTIVE)
        # Same output, so the same content hash: their TXY are current for each other.
        assert profile.content_hash() == MATLAB_2019.content_hash()
    assert UNCALIBRATED == {"plates-2025"} and "Uncalibrated" in BUILTIN_PROFILES["plates-2025"].notes
    assert [name for _, name in PLATE_SWAPS] == ["plates-2017", "plates-2022", "plates-2025"]


@pytest.mark.parametrize(("day", "expected"), [
    ("2017-03-16", None), ("2017-03-17", "plates-2017"), ("2022-08-22", "plates-2017"),
    ("2022-11-03", "plates-2022"), ("2025-06-17", "plates-2022"), ("2025-06-18", "plates-2025"),
    ("2026-10-29", "plates-2025"), ("", None), ("2025/06/18", None), ("yesterday", None)])
def test_plate_swaps_suggest_a_profile_for_a_day(day: str, expected: str | None) -> None:
    assert suggested_plates(day) == expected


@pytest.mark.parametrize("name", ["", " lead", "trail ", "trail.", "a/b", "a\\b", "é", "x" * 65, "nul", "COM1.v2",
                                  "matlab-2019", "MATLAB-2019", "Plates-2025"])
def test_unusable_names_are_refused(name: str) -> None:
    assert check_name(name) is not None


@pytest.mark.parametrize("name", ["mine", "Tony test 2", "plates-2022.halo_fit", "a", "x" * 64])
def test_usable_names(name: str) -> None:
    assert check_name(name) is None


def test_save_scan_find_and_delete(tmp_path: Path) -> None:
    library = ProfileLibrary(str(tmp_path / "profiles"))
    assert library.scan() == ([], [])
    mine = duplicate(BUILTIN_PROFILES["plates-2022"], "mine").replace(time_sum_t_x=3367.0)
    assert mine.version == 1 and mine.notes.startswith("Copied from plates-2022 v1")
    path = library.save(mine)
    assert path == str(tmp_path / "profiles" / "mine.json")
    assert DetectorProfile.from_json(Path(path).read_text()) == mine
    assert library.find("mine") == mine and library.find("matlab-2019") is MATLAB_2019
    assert library.find("nobody") is None
    with pytest.raises(ProfileError, match="exists"):
        library.save(mine.replace(notes="again"))
    with pytest.raises(ProfileError, match="exists"):
        library.save(mine.replace(name="MINE"))  # (Case-insensitive file systems.)
    library.save(mine.replace(version=2), replace=True)
    assert library.find("mine") == mine.replace(version=2)
    assert not [name for name in os.listdir(tmp_path / "profiles") if name.endswith(".partial")]
    with pytest.raises(ProfileError, match="built in"):
        library.delete("matlab-2019")
    library.delete("mine")
    assert library.find("mine") is None


def test_a_bad_or_misnamed_file_is_listed_as_unreadable(tmp_path: Path) -> None:
    folder = tmp_path / "profiles"
    folder.mkdir()
    (folder / "broken.json").write_text("{")
    (folder / "renamed.json").write_text(MATLAB_2019.replace(name="original").to_json())
    (folder / "builtin.json").write_text(MATLAB_2019.to_json())
    (folder / "ignored.txt").write_text("x")
    data = json.loads(MATLAB_2019.replace(name="future").to_json())
    (folder / "future.json").write_text(json.dumps({**data, "schema": 99}))
    found, bad = ProfileLibrary(str(folder)).scan()
    assert found == []
    reasons = {Path(entry.file).name: entry.reason for entry in bad}
    assert set(reasons) == {"broken.json", "renamed.json", "builtin.json", "future.json"}
    assert "named 'original'" in reasons["renamed.json"] and "built-in" in reasons["builtin.json"]
    assert "schema" in reasons["future.json"]


def test_import_and_export_round_trip(tmp_path: Path) -> None:
    library = ProfileLibrary(str(tmp_path / "profiles"))
    exported = tmp_path / "out.json"
    library.export(BUILTIN_PROFILES["matlab-2023-lab-edit"], str(exported))
    assert library.read_file(str(exported)) == BUILTIN_PROFILES["matlab-2023-lab-edit"]
    (tmp_path / "bad.json").write_text('{"schema": 1}')
    with pytest.raises(ProfileError, match="Missing"):
        library.read_file(str(tmp_path / "bad.json"))
    with pytest.raises(ProfileError, match="Can't read"):
        library.read_file(str(tmp_path / "absent.json"))


def test_free_names(tmp_path: Path) -> None:
    library = ProfileLibrary(str(tmp_path / "profiles"))
    assert library.free_name("matlab-2019") == "matlab-2019-2"
    library.save(MATLAB_2019.replace(name="copy"))
    assert library.free_name("copy") == "copy-2"
    assert check_name(library.free_name("../evil")) is None
    assert check_name(library.free_name("nul")) is None


def test_the_settings_pick_the_profile_and_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from helab.utils import constants
    monkeypatch.setattr(constants, "profiles_folder", lambda: str(tmp_path / "profiles"))
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    assert constants.read_convert_profile(settings) is MATLAB_2019
    assert constants.read_convert_backend(settings) == "numpy"
    settings.setValue(constants.CONVERT_PROFILE_SETTING, "plates-2025")
    settings.setValue(constants.CONVERT_BACKEND_SETTING, "rust")
    assert constants.read_convert_profile(settings).name == "plates-2025"
    assert constants.read_convert_backend(settings) == "rust"
    ProfileLibrary(str(tmp_path / "profiles")).save(MATLAB_2019.replace(name="mine", search_depth=40))
    settings.setValue(constants.CONVERT_PROFILE_SETTING, "mine")
    settings.setValue(constants.CONVERT_BACKEND_SETTING, "gpu-magic")
    assert constants.read_convert_profile(settings).search_depth == 40
    assert constants.read_convert_backend(settings) == "numpy"
    settings.setValue(constants.CONVERT_PROFILE_SETTING, "deleted")
    assert constants.read_convert_profile(settings) is MATLAB_2019
