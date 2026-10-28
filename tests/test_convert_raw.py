"""Raw DLD files are read as MATLAB's textscan reads them (``helab.convert.raw``).

The expected rows were measured with MATLAB R2025b on these exact bytes (builder's notes,
``.ai/sessions/2026-10-29-claude-txy-reference/notes.md``).
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from helab.convert.raw import RawPulses, parse_raw, read_raw

N = math.nan
ROOT = Path(__file__).resolve().parents[1]

TEXTSCAN = [
    (b"", []),
    (b"\r\n", []),
    (b"5,100\r\n", [(5, 100)]),
    (b"5,100\r\n0,200\r\n1,300", [(5, 100), (0, 200), (1, 300)]),
    (b"5,100\r\n0,200\r\n1,", [(5, 100), (0, 200), (1, N)]),
    (b"5,100\r\n0,200\r\n1", [(5, 100), (0, 200), (1, N)]),
    (b"5,100\r\n0,200\r\n1,3", [(5, 100), (0, 200), (1, 3)]),
    (b"5,100\r\n\r\n0,200\r\n1,300\r\n", [(5, 100), (0, 200), (1, 300)]),
    (b"5,100\r\n0,200\r\n\r\n\r\n", [(5, 100), (0, 200)]),
    (b"\r\n5,100\r\n0,200\r\n", [(5, 100), (0, 200)]),
    (b"5,100\n0,200\n1,300\n", [(5, 100), (0, 200), (1, 300)]),
    (b"5,100\r0,200\r1,300\r", [(5, 100), (0, 200), (1, 300)]),
    (b"5,100\r0,200\r\n", [(5, 100), (0, 200)]),
    (b"5,100\r\n0,200\r", [(5, 100), (0, 200)]),
    (b"5, 100\r\n 0,200 \r\n1 ,300\r\n", [(5, 100), (0, 200), (1, 300)]),
    (b"5,\t100\t\r\n0\t,200\r\n", [(5, 100), (0, 200)]),
    (b"5,100\r\n0,abc\r\n1,300\r\n", [(5, 100), (0, N)]),
    (b"5,100\r\n0,200\r\nabc,300\r\n1,400\r\n", [(5, 100), (0, 200)]),
    (b"5,100\r\n0,12abc\r\n1,300\r\n", [(5, 100), (0, 12)]),
    (b"5,100\r\n0,1 2\r\n1,300\r\n", [(5, 100), (0, 1), (2, N), (1, 300)]),
    (b"5,100,7\r\n0,200\r\n1,300\r\n", [(5, 100), (7, N), (0, 200), (1, 300)]),
    (b"5,100,\r\n0,200\r\n", [(5, 100), (0, 200)]),
    (b"5,,100\r\n0,200\r\n", [(5, N), (100, N), (0, 200)]),
    (b"5,100\r\n,200\r\n1,300\r\n", [(5, 100), (N, 200), (1, 300)]),
    (b"5,Inf\r\n0,-inf\r\n1,nan\r\n2,NaN\r\n", [(5, math.inf), (0, -math.inf), (1, N), (2, N)]),
    (b"+5,.5\r\n5.,1e3\r\n1,1E3\r\n2,1d3\r\n3,1e+3\r\n", [(5, 0.5), (5, 1000), (1, 1000), (2, 1000), (3, 1000)]),
    (b"5,100\r\n0,1e\r\n1,300\r\n", [(5, 100), (0, 1)]),
    (b"5,0x10\r\n1,300\r\n", [(5, 0)]),
    (b"5,100\r\n0,-\r\n1,300\r\n", [(5, 100), (0, N)]),
    (b"5,100\r\n0,.\r\n1,300\r\n", [(5, 100), (0, N)]),
    (b"5,100\r\n0,200\x00\x00\x00", [(5, 100), (0, 200)]),
    (b"05,000100\r\n", [(5, 100)]),
    (b"\xef\xbb\xbf5,100\r\n0,200\r\n", []),
    (b"5,1.5e3\r\n0,200.25\r\n", [(5, 1500), (0, 200.25)]),
    (b"5,-100\r\n0,-2\r\n", [(5, -100), (0, -2)]),
    (b"5,123456789012345678\r\n0,9007199254740993\r\n", [(5, 1.2345678901234568e17), (0, 9007199254740992.0)]),
    # The first line's ending decides which endings count (Lens's F1; MATLAB R2025b).
    (b"1,10\n2,20\r\n3,30\n", [(1, 10), (2, 20)]),
    (b"1,10\r2,20\r\n3,30\r", [(1, 10), (2, 20)]),
    (b"1,10\r\n2,20\r3,30\n", [(1, 10), (2, 20), (3, 30)]),
    (b"1,10\n2,20\n3,30\r", [(1, 10), (2, 20), (3, 30)]),
    (b"\n1,10\r\n2,20\r\n", [(1, 10), (2, 20)]),
    (b"1,10\n\r2,20\r3,30\n4,40\n", [(1, 10)]),
    (b"1,10\r\r\n2,20\n3,30\r4,40\r", [(1, 10), (2, 20), (3, 30), (4, 40)]),
    (b"1,10\r \r\n2,20\n3,30\r", [(1, 10)]),
    (b"1,10\r\r2,20\n3,30\r", [(1, 10), (2, 20)]),
    (b"1,10\r\n\n2,20\r3,30\n", [(1, 10), (2, 20), (3, 30)]),
]


def rows(pulses: RawPulses) -> list[tuple[float, float]]:
    return list(zip(pulses.channels.tolist(), pulses.times.tolist()))


def same(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> bool:
    return len(a) == len(b) and all(
        (x == y or (math.isnan(x) and math.isnan(y))) for pair_a, pair_b in zip(a, b) for x, y in zip(pair_a, pair_b))


@pytest.mark.parametrize(("data", "expected"), TEXTSCAN, ids=[repr(case[0][:24]) for case in TEXTSCAN])
def test_raw_files_read_as_textscan_does(data: bytes, expected: list[tuple[float, float]]) -> None:
    got = rows(parse_raw(data))
    assert same(got, [(float(a), float(b)) for a, b in expected]), got


PROBES = ROOT / "tests" / "data" / "convert" / "textscan"


def probe_files() -> list[tuple[str, str]]:
    return [(folder.name, line) for folder in sorted(PROBES.iterdir()) if folder.is_dir()
            for line in (folder / "matlab.txt").read_text().splitlines()]


def test_the_cross_checkers_probes_are_there() -> None:
    assert len(probe_files()) >= 449


@pytest.mark.parametrize(("folder", "line"), probe_files(), ids=lambda value: value.split(" ")[0])
def test_the_cross_checkers_probes_read_as_matlab_does(folder: str, line: str) -> None:
    # probes/README.md: each matlab.txt line is the input's name, MATLAB's row count, its values.
    name, count, *values = line.split()
    got = rows(parse_raw((PROBES / folder / f"{name}.txt").read_bytes()))
    expected = [(float(values[k]), float(values[k + 1])) for k in range(0, len(values), 2)]
    assert len(got) == int(count) and same(got, expected), got


def test_mixed_line_endings_skip_the_fast_path() -> None:
    from helab.convert import raw
    mixed = b"1,10\n2,20\r\n3,30\n"
    assert not raw._STRICT_CRLF.fullmatch(mixed) and not raw._STRICT_LF.fullmatch(mixed)
    assert len(parse_raw(mixed)) == 2


def test_the_fast_path_and_the_general_reader_agree() -> None:
    from helab.convert import raw
    data = b"5,21405148161\r\n5,12672176\r\n0,21405378461\r\n1,21405378456\r\n9,9007199254740993\r\n"
    fast = raw._parse_strict(data)
    general = raw._parse_textscan(data)
    assert rows(fast) == rows(general)
    lf = data.replace(b"\r\n", b"\n")
    assert rows(raw._parse_strict(lf)) == rows(raw._parse_textscan(lf)) == rows(fast)


def test_pulses_are_float64_arrays_in_file_order(tmp_path: Path) -> None:
    path = tmp_path / "d1.txt"
    path.write_bytes(b"5,300\r\n0,100\r\n1,200\r\n")
    pulses = read_raw(path)
    assert pulses.channels.dtype == np.float64 and pulses.times.dtype == np.float64
    assert rows(pulses) == [(5.0, 300.0), (0.0, 100.0), (1.0, 200.0)]
    assert len(pulses) == 3
    with pytest.raises(ValueError):
        RawPulses(np.zeros(2), np.zeros(3))
