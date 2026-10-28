"""Detector profiles: the built-ins, JSON and the content hash (``helab.convert.profile``)."""
from __future__ import annotations

import dataclasses
import json

import pytest

from helab.convert.profile import (BUILTIN_PROFILES, DEFAULT_PROFILE, MATLAB_2019, MATLAB_2023_LAB_EDIT,
                                   DetectorProfile, ProfileError, builtin_profile)


def test_the_default_is_matlab_2019_with_matlabs_constants() -> None:
    profile = builtin_profile()
    assert DEFAULT_PROFILE == "matlab-2019" and profile is MATLAB_2019
    assert (profile.bin_time, profile.search_depth, profile.search_window) == (25e-12, 36, 3200.0)
    assert profile.match_time_sum_x + profile.match_tolerance_x == 3400.0
    assert profile.xy_sum_tolerance == 400.0 and profile.v_perp_x == profile.v_perp_y == 5.2632e5
    assert (profile.channel_x1, profile.channel_x2, profile.channel_y1, profile.channel_y2) == (0, 1, 2, 3)
    assert profile.position_formula == "centred" and not profile.write_empty_txy and not profile.calibrated


def test_the_2023_lab_edit_differs_only_where_matlab_does() -> None:
    changed = {field.name for field in dataclasses.fields(DetectorProfile)
               if getattr(MATLAB_2019, field.name) != getattr(MATLAB_2023_LAB_EDIT, field.name)}
    assert changed == {"name", "notes", "dead_time_x1", "time_sum_t_x", "time_sum_t_y", "position_formula",
                       "write_empty_txy"}
    assert MATLAB_2023_LAB_EDIT.dead_time_x1 / MATLAB_2023_LAB_EDIT.bin_time == 20000.0
    assert sorted(BUILTIN_PROFILES) == ["matlab-2019", "matlab-2023-lab-edit"]


def test_json_round_trips_and_refuses_unknown_or_missing_fields() -> None:
    for profile in BUILTIN_PROFILES.values():
        assert DetectorProfile.from_json(profile.to_json()) == profile
    data = json.loads(MATLAB_2019.to_json())
    with pytest.raises(ProfileError, match="Unknown"):
        DetectorProfile.from_dict({**data, "centre": 0})
    with pytest.raises(ProfileError, match="Missing"):
        DetectorProfile.from_dict({k: v for k, v in data.items() if k != "search_depth"})
    with pytest.raises(ProfileError, match="schema"):
        DetectorProfile.from_dict({**data, "schema": 99})
    with pytest.raises(ProfileError):
        DetectorProfile.from_json("[1]")
    with pytest.raises(ProfileError):
        DetectorProfile.from_json("{")


def test_the_content_hash_is_stable_and_covers_only_what_changes_the_output() -> None:
    # Pinned: a change here changes every HeLab TXY's provenance, so it must be on purpose.
    assert MATLAB_2019.content_hash() == "231cb2637fdac1e1af20b29263d710fd142646bc76a23d340e9ad18edc277c96"
    assert MATLAB_2023_LAB_EDIT.content_hash() == "e5c91ba87a8257c88a1cde8067508d2139d805e8657d6a07485226e798d671fe"
    assert MATLAB_2019.replace(name="copy", version=2, notes="x", calibrated=True).content_hash() == \
        MATLAB_2019.content_hash()
    assert MATLAB_2019.replace(search_depth=40).content_hash() != MATLAB_2019.content_hash()
    # 3200 and 3200.0 are one profile.
    assert MATLAB_2019.replace(search_window=3200).content_hash() == MATLAB_2019.content_hash()


@pytest.mark.parametrize("changes", [
    {"bin_time": 0}, {"search_depth": 0}, {"dead_time_x1": -1e-6}, {"x2_handling": "retry"},
    {"position_formula": "rotated"}, {"search_window": "3200"}, {"search_depth": 36.0}, {"calibrated": 1},
    {"name": ""}, {"notes": 3},
])
def test_invalid_values_are_refused(changes: dict[str, object]) -> None:
    with pytest.raises(ProfileError):
        MATLAB_2019.replace(**changes)


def test_unknown_builtin_is_refused() -> None:
    with pytest.raises(ProfileError):
        builtin_profile("plates-2025")
