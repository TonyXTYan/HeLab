"""Detector profiles: the built-ins, JSON and the content hash (``helab.convert.profile``)."""
from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from helab.convert.pipeline import convert_raw
from helab.convert.profile import (BUILTIN_PROFILES, DEFAULT_PROFILE, DESCRIPTIVE, MATLAB_2019, MATLAB_2023_LAB_EDIT,
                                   NEUTRAL, UNUSED_BY_OUTPUT, USER_TAG_DIGITS, DetectorProfile, ProfileError,
                                   builtin_profile, file_tag)
from helab.convert.reconstruct import NoRowsError

CASES = Path(__file__).resolve().parents[1] / "tests" / "data" / "convert" / "cases"


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
    assert changed == {"name", "notes", "tag", "dead_time_x1", "time_sum_t_x", "time_sum_t_y", "position_formula",
                       "write_empty_txy"}
    assert MATLAB_2023_LAB_EDIT.dead_time_x1 / MATLAB_2023_LAB_EDIT.bin_time == 20000.0
    assert sorted(BUILTIN_PROFILES) == ["matlab-2019", "matlab-2023-lab-edit", "plates-2017", "plates-2022",
                                        "plates-2025"]


def test_json_round_trips_and_refuses_unknown_or_missing_fields() -> None:
    for profile in BUILTIN_PROFILES.values():
        assert DetectorProfile.from_json(profile.to_json()) == profile
    data = json.loads(MATLAB_2019.to_json())
    with pytest.raises(ProfileError, match="Unknown"):
        DetectorProfile.from_dict({**data, "centre": 0})
    with pytest.raises(ProfileError, match="Missing"):
        DetectorProfile.from_dict({k: v for k, v in data.items() if k != "search_depth"})
    for schema in (99, 0, None, "1", True):
        with pytest.raises(ProfileError, match="schema"):
            DetectorProfile.from_dict({**data, "schema": schema})
    with pytest.raises(ProfileError):
        DetectorProfile.from_json("[1]")
    with pytest.raises(ProfileError):
        DetectorProfile.from_json("{")


def test_the_content_hash_is_stable_and_covers_only_what_changes_the_output() -> None:
    # Pinned: a change here changes every HeLab TXY's provenance, so it must be on purpose.
    assert MATLAB_2019.content_hash() == "fbaf472897b0745fd5eca1249862e37ab43dc553adcf0dc6122648dfdfd414d0"
    assert MATLAB_2023_LAB_EDIT.content_hash() == "a228f236d31749608e9853d7f69954d47174cb08d7d2f1adaea40a364739183e"
    # The MCP and trigger channels don't change the output (yet): not in the hash.
    assert MATLAB_2019.replace(channel_mcp=7, channel_trigger=4).content_hash() == MATLAB_2019.content_hash()
    assert MATLAB_2019.replace(name="copy", version=2, notes="x", calibrated=True).content_hash() == \
        MATLAB_2019.content_hash()
    assert MATLAB_2019.replace(search_depth=40).content_hash() != MATLAB_2019.content_hash()
    # 3200 and 3200.0 are one profile.
    assert MATLAB_2019.replace(search_window=3200).content_hash() == MATLAB_2019.content_hash()


def test_a_field_at_its_neutral_default_is_optional_and_out_of_the_hash() -> None:
    assert set(NEUTRAL) == {"dead_time_x1", "dead_time_x2", "dead_time_y1", "dead_time_y2", "x2_handling", "y_handling",
                            "tag"}
    data = json.loads(MATLAB_2019.to_json())
    assert DetectorProfile.from_dict({k: v for k, v in data.items() if k not in NEUTRAL}) == MATLAB_2019.replace(tag="")
    # A field added later at its neutral value leaves the hash as it was: here, the hash with
    # dead_time_y2 present equals the canonical hash of the other fields alone.
    others = {k: v for k, v in data.items()
              if k not in (*DESCRIPTIVE, *UNUSED_BY_OUTPUT, *NEUTRAL, "schema")}
    text = json.dumps(others, sort_keys=True, separators=(",", ":"))
    assert MATLAB_2019.content_hash() == hashlib.sha256(text.encode()).hexdigest()
    assert MATLAB_2019.replace(dead_time_y2=1e-6).content_hash() != MATLAB_2019.content_hash()


def _perturbed(name: str, value: Any) -> Any:
    if isinstance(value, bool):
        return not value
    if name.startswith("channel_"):
        return 7  # a channel none of the cases uses
    if isinstance(value, int):
        return value - 7
    if isinstance(value, float):
        return value * 1.5 + 1e-6 if name.startswith(("dead_time", "bin_time", "v_perp")) else value * 0.6 + 1
    options = {"position_formula": ("centred", "raw")}.get(name, ())
    return next((option for option in options if option != value), None)


def _outputs(profile: DetectorProfile) -> list[bytes | str | None]:
    out: list[bytes | str | None] = []
    for case in sorted(path for path in CASES.iterdir() if path.is_dir()):
        data = (case / "d1.txt").read_bytes()
        # Times with a fraction too, so position_formula's rounding shows.
        for raw in (data, data.replace(b"\r\n", b".3\r\n")):
            try:
                out.append(convert_raw(raw, profile))
            except NoRowsError:
                out.append("error")
    return out


@pytest.mark.parametrize("name", [field.name for field in dataclasses.fields(DetectorProfile)
                                  if field.name not in DESCRIPTIVE])
def test_every_field_that_changes_the_output_is_in_the_hash(name: str) -> None:
    # Side's check: perturb each field; either the hash changes or no case's output does.
    changed = _perturbed(name, getattr(MATLAB_2019, name))
    if changed is None:
        pytest.skip(f"{name} has one allowed value")
    profile = MATLAB_2019.replace(**{name: changed})
    if profile.content_hash() == MATLAB_2019.content_hash():
        assert _outputs(profile) == _outputs(MATLAB_2019), f"{name} changes the output but not the hash"
    else:
        assert name not in UNUSED_BY_OUTPUT


@pytest.mark.parametrize("changes", [
    {"bin_time": 0}, {"search_depth": 0}, {"dead_time_x1": -1e-6}, {"x2_handling": "retry"},
    {"position_formula": "rotated"}, {"search_window": "3200"}, {"search_depth": 36.0}, {"calibrated": 1},
    {"name": ""}, {"notes": 3}, {"v_perp_x": float("nan")}, {"bin_time": float("inf")},
    {"search_window": -1}, {"match_tolerance_y": -200}, {"xy_sum_tolerance": -1}, {"time_sum_t_x": -3200},
    {"channel_x2": 0}, {"channel_y2": 2},
    {"tag": "M19v1"}, {"tag": "m"}, {"tag": "1abc"}, {"tag": "m19_v1"}, {"tag": "abcdefghijklmnopq"}, {"tag": 1},
    {"tag": "u0123abcd"},
])
def test_invalid_values_are_refused(changes: dict[str, object]) -> None:
    with pytest.raises(ProfileError):
        MATLAB_2019.replace(**changes)


def test_unknown_builtin_is_refused() -> None:
    with pytest.raises(ProfileError):
        builtin_profile("plates-2030")


def test_a_builtins_tag_never_changes() -> None:
    """Q18.4: HeLab's TXY are named by their profile's tag, frozen once used (a file named with one
    stands for that profile on every computer). A new built-in adds its line here; none ever changes."""
    assert {name: profile.tag for name, profile in BUILTIN_PROFILES.items()} == {
        "matlab-2019": "m19v1", "matlab-2023-lab-edit": "m23v1", "plates-2017": "p17v1", "plates-2022": "p22v1",
        "plates-2025": "p25t1"}
    assert {name: file_tag(profile) for name, profile in BUILTIN_PROFILES.items()} == {
        name: profile.tag for name, profile in BUILTIN_PROFILES.items()}
    assert len({profile.tag for profile in BUILTIN_PROFILES.values()}) == len(BUILTIN_PROFILES)


def test_any_other_profile_is_tagged_by_its_hash() -> None:
    edited = MATLAB_2019.replace(search_depth=40)
    assert file_tag(edited) == "u" + edited.content_hash()[:USER_TAG_DIGITS]
    assert USER_TAG_DIGITS == 32 and len(file_tag(edited)) == 33  # (Q23.6; 8 before.)
    # A copy under another name, or a file claiming a built-in's tag, never writes under it.
    assert file_tag(MATLAB_2019.replace(name="mine")) == "u" + MATLAB_2019.content_hash()[:USER_TAG_DIGITS]
    assert file_tag(MATLAB_2019.replace(name="mine", tag="m19v1")) == "u" + MATLAB_2019.content_hash()[:USER_TAG_DIGITS]
    assert file_tag(MATLAB_2019.replace(tag="p22v1")) == "u" + MATLAB_2019.content_hash()[:USER_TAG_DIGITS]
    assert file_tag(MATLAB_2019.replace(tag="")) == "u" + MATLAB_2019.content_hash()[:USER_TAG_DIGITS]
    # The tag is descriptive: out of the hash, and optional in JSON (a user profile has none).
    assert MATLAB_2019.replace(tag="").content_hash() == MATLAB_2019.content_hash()
    data = MATLAB_2019.to_dict()
    del data["tag"]
    assert DetectorProfile.from_dict(data) == MATLAB_2019.replace(tag="")
