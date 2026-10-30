"""Q23.6: a user profile's tag is ``u`` and 32 hex digits of its content hash (8 before), so every name pattern
takes a 33-character tag; built-in tags are unchanged. TXY of tonight's ``u`` + 8 builds are another tag's:
ignored for the profile, converted again, never deleted. A path the OS refuses for its length (Windows' 260
characters without long paths) is said plainly, per shot."""
from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import Any

import pytest

from helab.convert import provenance, txy
from helab.convert.profile import BUILTIN_PROFILES, MATLAB_2019, NAME_TAG, file_tag
from helab.io_ops import convert, helab_txy
from helab.io_ops.convert import WINDOWS_MAX_PATH, path_too_long
from helab.utils import file_kinds
from test_convert_helab import of, raw_bytes, request_for, run, source, summary, write_raw  # noqa: F401

MINE = MATLAB_2019.replace(name="mine")  # A user profile: tagged by its hash.
TAG = file_tag(MINE)
OLD_TAG = TAG[:9]  # As tonight's builds named it: u and 8 hex digits.


def test_a_user_tag_is_u_and_32_hex_digits_and_built_in_tags_stay() -> None:
    assert len(TAG) == 33 and TAG == "u" + MINE.content_hash()[:32]
    assert {file_tag(profile) for profile in BUILTIN_PROFILES.values()} == {"m19v1", "m23v1", "p17v1", "p22v1", "p25t1"}


def test_every_name_pattern_takes_a_33_character_tag_and_no_longer() -> None:
    name = provenance.txy_name(TAG, 12)
    assert name == f"d_txy_helab_{TAG}_12.txt" and len(name) == 50 + len("12")  # (55 for shot 99999.)
    assert file_kinds.match(name) == (file_kinds.HELAB_TXY, 12)
    assert provenance.parse_txy_name(name) == (TAG, 12)
    assert helab_txy._OWN_FILE.match(name)
    too_long = f"d_txy_helab_{TAG}0_12.txt"  # A 34-character tag.
    assert file_kinds.match(too_long) is None and provenance.parse_txy_name(too_long) is None
    assert not helab_txy._OWN_FILE.match(too_long)
    # Tonight's builds' names are still HeLab's TXY (another tag), counted and cleared with HeLab's own.
    old = provenance.txy_name(OLD_TAG, 12)
    assert file_kinds.match(old) == (file_kinds.HELAB_TXY, 12) and helab_txy._OWN_FILE.match(old)
    # One tag pattern everywhere (spelled out where its module can't import the profile's).
    for pattern in (file_kinds.HELAB_TXY.pattern.pattern, provenance._NAME, provenance.BARE_NAME,
                    helab_txy._OWN_FILE.pattern):
        assert NAME_TAG in pattern


def test_the_temporary_names_of_a_user_profiles_txy_are_housekeepings() -> None:
    target = provenance.txy_name(TAG, 3)
    temporary = txy.partial_name(target, "0123456789abcdef")
    assert len(temporary) == len(target) + 26  # (81 for shot 99999.)
    assert convert.partial().fullmatch(temporary) and convert.own_partial().fullmatch(temporary)
    assert helab_txy._OWN_FILE.match(temporary)
    assert not convert.partial().fullmatch(txy.partial_name(f"d_txy_helab_{TAG}0_3.txt", "0123456789abcdef"))


def test_tonights_u8_txy_is_another_tags_converted_again_and_kept(source: Path, tmp_path: Path) -> None:
    write_raw(source, 1, raw_bytes(10_000))
    old = source / provenance.txy_name(OLD_TAG, 1)
    old.write_bytes(b"made by an earlier build\n")
    events = run(source, request_for(source, tmp_path, profile=MINE.to_dict(), beside=True, beside_confirmed=True))
    [converted] = of(events, "shot_converted")
    assert converted["txy"] == str(source / provenance.txy_name(TAG, 1))
    assert old.read_bytes() == b"made by an earlier build\n"  # Never deleted or replaced.
    assert {path.name for path in source.iterdir()} == {"d1.txt", old.name, provenance.txy_name(TAG, 1)}


@pytest.mark.parametrize("error, platform, said", [
    (OSError(errno.ENAMETOOLONG, "File name too long"), "darwin", "this computer"),
    (OSError(errno.ENAMETOOLONG, "File name too long"), "win32", "this computer"),
    (FileNotFoundError(errno.ENOENT, "No such file"), "win32", "Windows"),
    (FileNotFoundError(errno.ENOENT, "No such file"), "linux", None),
    (PermissionError(errno.EACCES, "Denied"), "win32", None),
    (ValueError("not an OS error"), "win32", None),
], ids=["ENAMETOOLONG", "ENAMETOOLONG on Windows", "Windows: not found, long", "elsewhere: not found",
        "denied", "not an OS error"])
def test_path_too_long_names_the_oss_refusal(error: BaseException, platform: str, said: str | None) -> None:
    long = "C:\\" + "d" * (WINDOWS_MAX_PATH + 10)
    message = path_too_long(error, long, platform)
    if said is None:
        assert message is None
    else:
        assert message is not None and message.startswith(f"Path too long for {said}") and long in message
        assert f"{len(long):,} characters" in message


@pytest.mark.parametrize("winerror, length, too_long", [(206, 100, True), (3, WINDOWS_MAX_PATH, True),
                                                        (3, WINDOWS_MAX_PATH - 1, False), (5, 400, False)])
def test_windows_errors_206_and_3_on_a_long_path(winerror: int, length: int, too_long: bool) -> None:
    error = OSError(errno.EINVAL, "Windows' error")  # (Not a FileNotFoundError: the Windows error decides.)
    error.winerror = winerror  # type: ignore[attr-defined]  # (Set by Python on Windows only.)
    path = "C:\\" + "d" * (length - 3)
    assert (path_too_long(error, path, "win32") is not None) is too_long
    short = FileNotFoundError(errno.ENOENT, "No such file")  # A short path not found is just that.
    assert path_too_long(short, "C:\\run\\d_txy_helab_m19v1_1.txt", "win32") is None


def test_the_temporary_name_in_the_error_is_the_length_said(tmp_path: Path) -> None:
    target = "C:\\" + "d" * 240
    temporary = Path(target + ".0123456789abcdef.partial")
    error = FileNotFoundError(errno.ENOENT, "No such file", temporary)  # os.open(Path) gives the Path.
    message = path_too_long(error, target, "win32")
    assert message is not None and f"{len(str(temporary)):,} characters" in message


def test_a_write_refused_for_its_length_is_that_shots_message(source: Path, tmp_path: Path,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """On every OS, with the write patched to fail as the OS would: each shot is refused with the message (a
    per-shot ``shot_unconvertible``, which the Live line and ``helab convert`` show), and the run goes on."""
    for shot in (1, 2):
        write_raw(source, shot, raw_bytes(10_000))

    def refused(path: str | os.PathLike[str], data: bytes, **kwargs: Any) -> None:
        raise OSError(errno.ENAMETOOLONG, "File name too long", str(path))

    monkeypatch.setattr(txy, "write_atomic", refused)
    events = run(source, request_for(source, tmp_path, profile=MINE.to_dict(), beside=True, beside_confirmed=True))
    refusals = of(events, "shot_unconvertible")
    assert [event["shot"] for event in refusals] == [1, 2] and of(events, "shot_converted") == []
    target = str(source / provenance.txy_name(TAG, 1))
    assert refusals[0]["reason"] == "failed" and refusals[0]["message"] == path_too_long(
        OSError(errno.ENAMETOOLONG, "File name too long", target), target)
    assert len(summary(events)["unconvertible"]) == 2 and of(events, "error") == []


def test_a_folder_refused_for_its_length_fails_the_conversion_saying_so(source: Path, tmp_path: Path,
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    write_raw(source, 1, raw_bytes(10_000))
    made = os.makedirs

    def refused(path: str, *args: Any, **kwargs: Any) -> None:
        if convert.FOLDER_NAME in str(path):
            raise OSError(errno.ENAMETOOLONG, "File name too long", path)
        made(path, *args, **kwargs)

    monkeypatch.setattr(os, "makedirs", refused)  # (Any other folder is made as usual.)
    with pytest.raises(OSError, match="^Path too long for this computer"):
        run(source, request_for(source, tmp_path, profile=MINE.to_dict()))


def test_a_deep_folder_converts_or_says_its_path_is_too_long(tmp_path: Path) -> None:
    """A real conversion beside raw files in a folder whose TXY path passes Windows' 260 characters (its
    temporary name more still): it converts where the OS allows it (macOS, Linux, Windows with long paths
    turned on, as on GitHub's runners) and is refused with exactly that message where it doesn't."""
    folder = tmp_path / "deep"  # (A folder of its own, however long the temp folder already is.)
    while len(str(folder)) < 230:  # (Below Windows' 248 for a folder, so the test can make it anywhere.)
        folder = folder / ("d" * min(40, 236 - len(str(folder))))
    folder.mkdir(parents=True)
    write_raw(folder, 1, raw_bytes(10_000))
    target = str(folder / provenance.txy_name(TAG, 1))
    assert len(target) >= WINDOWS_MAX_PATH
    events = run(folder, request_for(folder, tmp_path, profile=MINE.to_dict(), beside=True, beside_confirmed=True))
    converted, refused = of(events, "shot_converted"), of(events, "shot_unconvertible")
    if converted:
        assert converted[0]["txy"] == target and os.path.isfile(target) and not refused
    else:
        [refusal] = refused
        assert refusal["message"].startswith("Path too long for ") and target in refusal["message"] or (
            refusal["message"].startswith("Path too long for ") and ".partial" in refusal["message"])
