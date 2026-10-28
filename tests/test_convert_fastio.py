"""The fast text paths equal the general ones (``helab.convert.fastio``).

``parse_strict`` must accept exactly the files ``raw._STRICT_CRLF``/``_STRICT_LF`` describe and
read them as the general reader (``raw._parse_textscan``) does: every case and probe in
``tests/data/convert/``, ``tests_sample_data/`` and random near-strict bytes. ``format_txy`` must
give ``txy.format_txy_by_value``'s bytes.
"""
from __future__ import annotations

import math
from pathlib import Path
import random

import numpy as np
import pytest

from helab.convert import fastio, raw
from helab.convert.profile import MATLAB_2019, MATLAB_2023_LAB_EDIT, DetectorProfile
from helab.convert.raw import RawPulses, parse_raw
from helab.convert.reconstruct import NoRowsError, reconstruct
from helab.convert.txy import format_txy, format_txy_by_value

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data" / "convert"


def inputs() -> list[Path]:
    return (sorted((DATA / "cases").glob("*/d1.txt")) + sorted((DATA / "textscan").glob("*/*.txt"))
            + sorted((ROOT / "tests_sample_data").rglob("d[0-9]*.txt")))


def strict(data: bytes) -> bool:
    return bool(raw._STRICT_CRLF.fullmatch(data) or raw._STRICT_LF.fullmatch(data))


def same_as_general(data: bytes) -> None:
    fast = fastio.parse_strict(data)
    # Strict files are all read, unless a field is too long for int64 (the general reader then).
    too_long = any(len(field) > 16 for field in data.replace(b"\r\n", b",").replace(b"\n", b",").split(b","))
    assert (fast is not None) == (strict(data) and not too_long), data[:60]
    if fast is not None:
        general = raw._parse_textscan(data)
        assert fast[0].dtype == fast[1].dtype == np.float64
        np.testing.assert_array_equal(fast[0], general.channels)
        np.testing.assert_array_equal(fast[1], general.times)


def test_there_are_strict_and_other_inputs() -> None:
    files = [path.read_bytes() for path in inputs()]
    assert len(files) > 1000
    assert sum(map(strict, files)) > 30 and sum(not strict(data) for data in files) > 1000


@pytest.mark.parametrize("path", inputs(), ids=lambda path: f"{path.parent.name}/{path.name}")
def test_every_case_and_probe_reads_as_the_general_reader(path: Path) -> None:
    same_as_general(path.read_bytes())


def test_random_near_strict_files_read_as_the_general_reader() -> None:
    rng = random.Random(7)
    alphabet = [b"0", b"1", b"9", b",", b"\r\n", b"\n", b"\r", b" ", b"-", b".", b"e"]
    for _ in range(3000):
        ending = rng.choice([b"\r\n", b"\n"])
        lines = [b"%d,%d" % (rng.choice([rng.randrange(8), rng.randrange(10 ** rng.randrange(1, 18))]), rng.randrange(10 ** rng.randrange(1, 18))) + ending
                 for _ in range(rng.randrange(0, 6))]
        data = bytearray(b"".join(lines))
        for _ in range(rng.choice([0, 0, 1, 2])):
            at = rng.randrange(len(data) + 1)
            if rng.random() < 0.5 and data:
                del data[min(at, len(data) - 1)]
            else:
                data[at:at] = rng.choice(alphabet)
        same_as_general(bytes(data))


def test_long_fields_take_the_general_reader() -> None:
    data = b"5,1\r\n0,09007199254740993\r\n1,123456789012345678901\r\n"
    assert strict(data) and fastio.parse_strict(data) is None
    assert parse_raw(data).times.tolist() == [1.0, 9007199254740992.0, 1.2345678901234568e20]
    sixteen = b"5,9999999999999999\n12,0000000000000001\n"
    parsed = fastio.parse_strict(sixteen)
    assert parsed is not None and parsed[0].tolist() == [5.0, 12.0] and parsed[1].tolist() == [1e16, 1.0]


def test_strict_files_go_through_the_fast_path(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(data: bytes) -> RawPulses:
        raise AssertionError("the general reader was used")
    monkeypatch.setattr(raw, "_parse_textscan", refuse)
    assert len(parse_raw(b"5,1\r\n0,2\r\n")) == 2 and len(parse_raw(b"")) == 0


SPECIAL = [0.0, -0.0, 1.0, -1.0, 0.5, 1e-5, 1.25e-7, 123456785.0, 12345678.5, 0.123456785, 99999999.5, 1e16,
           -1e-300, 5e-324, 1.7976931348623157e308, math.nan, -math.nan, math.inf, -math.inf, 2.5e-11, 1.0e-4,
           0.000123456789, 9.9999999e-5, 3.4e38]


def test_special_values_format_as_value_by_value() -> None:
    hits = np.array(SPECIAL + SPECIAL[:3], dtype=np.float64).reshape(-1, 3)
    assert format_txy(hits) == format_txy_by_value(hits)
    assert format_txy(np.array([[math.nan, math.inf, -math.inf]])) == b"NaN,Inf,-Inf\n"
    assert format_txy(np.array([[-0.0, 0.0, 1e-5]])) == b"-0,0,1e-05\n"


def test_random_values_and_block_edges_format_as_value_by_value(monkeypatch: pytest.MonkeyPatch) -> None:
    rng = np.random.default_rng(3)
    hits = np.concatenate([rng.uniform(-0.05, 0.05, (500, 3)), rng.uniform(0, 3, (500, 3)),
                           rng.normal(0, 1, (500, 3)) * 10.0 ** rng.integers(-320, 300, (500, 3))])
    hits[rng.integers(0, hits.shape[0], 20), rng.integers(0, 3, 20)] = math.nan
    monkeypatch.setattr(fastio, "_BLOCK", 7)
    assert format_txy(hits) == format_txy_by_value(hits)
    assert format_txy(hits[:7]) == format_txy_by_value(hits[:7])
    assert format_txy(np.empty((0, 3))) == b""


@pytest.mark.parametrize("profile", [MATLAB_2019, MATLAB_2023_LAB_EDIT], ids=lambda p: p.name)
def test_every_cases_hits_format_as_value_by_value(profile: DetectorProfile) -> None:
    for path in sorted((DATA / "cases").glob("*/d1.txt")):
        try:
            hits = reconstruct(parse_raw(path.read_bytes()), profile)
        except NoRowsError:
            continue
        assert format_txy(hits) == format_txy_by_value(hits), path
