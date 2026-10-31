"""Caching v2's raw layer (``helab.convert.raw_layer``, stage 1): a raw file's layer, packed as a
``.hlb`` and read back, gives the same TXY as the file, byte for byte, for every available backend
and the split path; the right encoding is chosen; and the done-writing checks answer from its facts
as they do from the bytes. Inputs: every converter case, every textscan probe, ``tests_sample_data/``
and a seeded fuzz set (synthetic or checked in: tests never touch real data)."""
from __future__ import annotations

import builtins
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import random
import threading
from typing import Any

import numpy as np
import pytest

from helab.convert import raw, raw_layer
from helab.convert.check import convert_via_layer
from helab.convert.pipeline import convert_raw
from helab.convert.profile import MATLAB_2019, MATLAB_2023_LAB_EDIT, DetectorProfile
from helab.convert.raw import RawPulses, parse_raw
from helab.convert.reconstruct import _MODULES, NoRowsError, get_backend, reconstruct
from helab.convert.split import reconstruct_split
from helab.convert.txy import format_txy
from helab.utils import hlb

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "data" / "convert" / "cases"
TEXTSCAN = ROOT / "tests" / "data" / "convert" / "textscan"
PROFILES = [MATLAB_2019, MATLAB_2023_LAB_EDIT]


def through_hlb(data: bytes) -> tuple[raw_layer.RawLayer, RawPulses]:
    """The file's layer as the store would keep it: encoded, packed, read back, decoded."""
    layer, header = raw_layer.from_hlb(raw_layer.to_hlb(raw_layer.encode(data), maker={"maker": "t"},
                                                        meta={"name": "d1.txt"}))
    assert header["kind"] == "raw" and header["meta"]["name"] == "d1.txt" and header["maker"] == {"maker": "t"}
    assert header["meta"]["parser"] == raw_layer.RAW_PARSER_VERSION
    return layer, raw_layer.decode(layer)


def same_rows(layer: raw_layer.RawLayer, ours: RawPulses, theirs: RawPulses) -> None:
    """What every backend reads of the pulses is the same: ``times[0]`` and the stably sorted rows (the
    float encoding: the very arrays, file order and NaN included)."""
    assert len(ours) == len(theirs) == layer.facts.rows
    if layer.encoding == raw_layer.FLOAT:
        assert np.array_equal(ours.channels, theirs.channels, equal_nan=True)
        assert np.array_equal(ours.times, theirs.times, equal_nan=True)
        return
    if not len(theirs):
        return
    assert ours.times[0] == theirs.times[0] and ours.channels[0] == theirs.channels[0]
    a, b = np.argsort(ours.times, kind="stable"), np.argsort(theirs.times, kind="stable")
    assert np.array_equal(ours.times[a], theirs.times[b]) and np.array_equal(ours.channels[a], theirs.channels[b])


def txy(pulses: RawPulses, profile: DetectorProfile, backend: str) -> bytes | None:
    try:
        return format_txy(reconstruct(pulses, profile, backend))
    except NoRowsError:
        return None


def backends(profile: DetectorProfile) -> list[str]:
    """Every backend that can run here with ``profile`` (the compiled ones only where built)."""
    names = []
    for name in _MODULES:
        try:
            if get_backend(name).unavailable(profile) is None:
                names.append(name)
        except Exception:  # (A backend that can't even load here: not available.)
            continue
    return names


def same_txy(data: bytes, *, every_backend: bool = True, split: bool = True) -> None:
    file_pulses = parse_raw(data)
    layer, layer_pulses = through_hlb(data)
    same_rows(layer, layer_pulses, file_pulses)
    for profile in PROFILES:
        for backend in backends(profile) if every_backend else ["numpy"]:
            assert txy(layer_pulses, profile, backend) == txy(file_pulses, profile, backend), (profile.name, backend)
        if split and len(file_pulses):
            with ThreadPoolExecutor(2) as pool:
                ours = format_txy(reconstruct_split(layer_pulses, profile, "numpy", executor=pool, min_rows=1))
            assert ours == txy(file_pulses, profile, "numpy")


def same_checks(data: bytes) -> None:
    facts = raw_layer.encode(data).facts
    triggers = {0, 1, 2, 5, 9, 200, *((facts.first_channel,) if facts.first_channel is not None else ())}
    for trigger in triggers:
        assert raw_layer.not_done(facts, trigger) == raw.not_done(data, trigger)


# Every converter case, the lab's sample files, every textscan probe.

def case_names() -> list[str]:
    return sorted(path.name for path in CASES.iterdir() if path.is_dir())


@pytest.mark.parametrize("case", case_names())
def test_each_cases_layer_converts_as_its_file(case: str) -> None:
    data = (CASES / case / "d1.txt").read_bytes()
    same_txy(data)
    same_checks(data)
    assert convert_or_none(data, MATLAB_2019, via_layer=True) == convert_or_none(data, MATLAB_2019)


def convert_or_none(data: bytes, profile: DetectorProfile, via_layer: bool = False) -> bytes | None:
    """``convert_raw`` (or ``convert_via_layer``, which raises alike), None for a file with no rows."""
    try:
        return (convert_via_layer if via_layer else convert_raw)(data, profile)
    except NoRowsError:
        return None


@pytest.mark.parametrize("raw_file", sorted((ROOT / "tests_sample_data").rglob("d[0-9]*.txt")),
                         ids=lambda path: f"{path.parent.name}/{path.name}")
def test_the_lab_sample_files_layers_convert_as_the_files(raw_file: Path) -> None:
    data = raw_file.read_bytes()
    assert raw_layer.encode(data).encoding == raw_layer.COMPACT  # (The TDC's own files: the compact path.)
    same_txy(data, every_backend=False, split=False)
    same_checks(data)


@pytest.mark.parametrize("folder", sorted(path.name for path in TEXTSCAN.iterdir() if path.is_dir()))
def test_every_textscan_probes_layer_reads_as_the_file(folder: str) -> None:
    inputs = [path for path in sorted((TEXTSCAN / folder).iterdir())
              if path.is_file() and path.name not in ("list.txt", "matlab.txt")]
    assert inputs
    for path in inputs:
        data = path.read_bytes()
        layer, pulses = through_hlb(data)
        same_rows(layer, pulses, parse_raw(data))
        assert layer.encoding == (raw_layer.COMPACT if strict(data) else raw_layer.FLOAT) or big(data), path.name
        same_checks(data)


def strict(data: bytes) -> bool:
    from helab.convert import fastio
    return fastio.parse_strict(data) is not None


def big(data: bytes) -> bool:
    """A strict file the compact encoding still refuses (a channel over 127, a time from 2^62)."""
    pulses = parse_raw(data)
    return bool(len(pulses)) and (float(pulses.channels.max()) > 127 or float(pulses.times.max()) >= 2.0 ** 62)


# A seeded fuzz set.

def lines(rows: list[tuple[Any, Any]], ending: str = "\r\n") -> bytes:
    return "".join(f"{channel},{time}{ending}" for channel, time in rows).encode()


def fuzz() -> list[tuple[str, bytes, str]]:
    """(name, bytes, the encoding expected)."""
    rng = random.Random(20261031)
    cases: list[tuple[str, bytes, str]] = []
    for n in range(40):
        size = rng.randrange(1, 600)
        start = rng.randrange(0, 10 ** 12)
        times = [start + rng.randrange(0, 4000) for _ in range(size)]
        if n % 4 == 0:
            times = [start + rng.randrange(0, 5) for _ in range(size)]  # (Many ties.)
        if n % 5 == 1:
            times[0] = max(times) + 7  # (Row 0 not the earliest.)
        if n % 5 == 2 and size > 2:
            times[0] = times[1] = times[2]  # (Row 0 tied.)
        rows = [(5 if i == 0 else rng.choice((1, 2, 3, 4, 5, 6, 7, 8)), time) for i, time in enumerate(times)]
        cases.append((f"strict{n}", lines(rows, "\r\n" if n % 2 else "\n"), raw_layer.COMPACT))
    near = 2 ** 53
    cases += [
        ("2^53 - 1", lines([(5, near - 1), (1, near - 2), (2, 3)]), raw_layer.COMPACT),
        ("2^53 + 1", lines([(5, near + 1), (1, near), (2, near + 3)]), raw_layer.COMPACT),  # (Rounded as floats.)
        ("16 digits", lines([(5, 9_999_999_999_999_999), (1, 1)]), raw_layer.COMPACT),
        ("17 digits", lines([(5, 10 ** 16), (1, 1)]), raw_layer.FLOAT),  # (Past the strict path.)
        ("2^62", lines([(5, 2 ** 62), (1, 1)]), raw_layer.FLOAT),
        ("channel 128", lines([(5, 10), (128, 20)]), raw_layer.FLOAT),
        ("channel 127", lines([(5, 10), (127, 20)]), raw_layer.COMPACT),
        ("NaN row", b"5,10\r\n1,\r\n2,30\r\n", raw_layer.FLOAT),
        ("NaN first", b",10\r\n1,5\r\n", raw_layer.FLOAT),
        ("CR only", b"5,10\r1,20\r2,15\r", raw_layer.FLOAT),
        ("mixed endings", b"5,10\r\n1,20\n2,15\r\n", raw_layer.FLOAT),
        ("no final newline", b"5,10\r\n1,20", raw_layer.FLOAT),
        ("decimals and signs", b"5,10.5\r\n1,-3\r\n2,1e3\r\n", raw_layer.FLOAT),
        ("empty", b"", raw_layer.COMPACT),
        ("blank only", b"\r\n\r\n", raw_layer.FLOAT),
        ("trigger only", b"5,100\r\n", raw_layer.COMPACT),
        ("leading newlines", b"\n\n5,10\n1,20\n", raw_layer.FLOAT),
    ]
    return cases


@pytest.mark.parametrize("name, data, encoding", fuzz(), ids=[case[0] for case in fuzz()])
def test_the_fuzz_sets_layers_convert_as_the_files(name: str, data: bytes, encoding: str) -> None:
    assert raw_layer.encode(data).encoding == encoding
    same_txy(data)
    same_checks(data)


def test_the_compact_layer_is_sorted_with_row_0_first_and_smaller() -> None:
    data = lines([(5, 900), (1, 300), (2, 300), (3, 100), (4, 950)])
    layer = raw_layer.encode(data)
    assert layer.encoding == raw_layer.COMPACT
    assert layer.arrays["channel"].tolist() == [5, 3, 1, 2, 4]  # (Row 0, then by time, ties in file order.)
    assert layer.arrays["time"].tolist() == [900, -800, 200, 0, 650]
    assert layer.facts == raw_layer.Facts(rows=5, t_zero=900.0, first_channel=5, blank=False, final_newline=True,
                                          line_endings="crlf", reader="strict")
    rng = random.Random(3)
    big_file = lines([(5, 0)] + [(rng.randrange(1, 9), t * 37 + rng.randrange(0, 30)) for t in range(20_000)])
    assert len(raw_layer.to_hlb(raw_layer.encode(big_file))) < len(big_file) / 4


def test_facts_round_trip_and_bad_ones_are_refused() -> None:
    facts = raw_layer.encode(b"\r\n5,10\r1,2").facts
    assert raw_layer.Facts.from_json(facts.to_json()) == facts and facts.line_endings == "mixed"
    nan = raw_layer.Facts.from_json(raw_layer.encode(b"").facts.to_json())
    assert nan.rows == 0 and np.isnan(nan.t_zero)
    bad: Any
    for bad in (None, [], {"rows": 1}, {**facts.to_json(), "rows": -1}, {**facts.to_json(), "reader": "other"},
                {**facts.to_json(), "blank": 1}, {**facts.to_json(), "t_zero": "x"}):
        with pytest.raises(hlb.HlbError):
            raw_layer.Facts.from_json(bad)


def test_a_layer_whose_arrays_dont_match_is_an_error() -> None:
    packed = raw_layer.to_hlb(raw_layer.encode(lines([(5, 10), (1, 20)])))
    layer, _ = raw_layer.from_hlb(packed)
    short = raw_layer.RawLayer(layer.encoding, {**layer.arrays, "time": layer.arrays["time"][:1]}, layer.facts)
    with pytest.raises(hlb.HlbError, match="wrong type or length"):
        raw_layer.decode(short)
    with pytest.raises(hlb.HlbError, match="isn't one this HeLab reads"):
        raw_layer.decode(raw_layer.RawLayer("i4-1", layer.arrays, layer.facts))
    with pytest.raises(hlb.HlbError, match="Not a raw layer"):
        raw_layer.from_hlb(hlb.pack({"x": np.zeros(1)}, kind="txy"))


def test_via_layer_converts_in_memory_and_writes_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``check_samples.py --via-layer`` (``convert_via_layer``) opens no file: the samples stay read-only.
    Only this test's thread is refused (C2-12): another thread (an earlier test's helper clean-up) opens
    files as usual meanwhile."""
    data = (CASES / "basic" / "d1.txt").read_bytes()
    expected = convert_or_none(data, MATLAB_2019)
    convert_via_layer(data, MATLAB_2019)  # (Backends loaded first.)
    here = threading.get_ident()
    real_open, real_os_open = builtins.open, os.open

    def refused(real: Any) -> Any:
        def guarded(*args: Any, **kwargs: Any) -> Any:
            if threading.get_ident() == here:
                raise AssertionError(f"a file was opened: {args[:1]}")
            return real(*args, **kwargs)
        return guarded
    monkeypatch.setattr(builtins, "open", refused(real_open))
    monkeypatch.setattr(os, "open", refused(real_os_open))
    assert convert_via_layer(data, MATLAB_2019) == expected and expected
    elsewhere: list[BaseException] = []

    def other_thread() -> None:
        try:
            with open(tmp_path / "other.txt", "w", encoding="ascii") as handle:
                handle.write("ok")
        except BaseException as exc:
            elsewhere.append(exc)
    thread = threading.Thread(target=other_thread)
    thread.start()
    thread.join(10)
    assert elsewhere == [] and (tmp_path / "other.txt").exists()
