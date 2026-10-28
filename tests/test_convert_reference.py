"""The reference port reproduces MATLAB's converter byte for byte (``helab.convert.backends.reference``).

``tests/data/convert/cases/<case>/``: synthetic raw files made by the cross-checker, with MATLAB
R2025b's own output for both variants (``expected-2019.txt``, ``expected-2023.txt``) and the
outcome (``matlab-<variant>.json``: ``file``, ``nofile`` or ``error``); the table is in its
README. ``tests_sample_data/``: raw files with the TXY the lab's 2019 converter wrote.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from helab.convert.backends.reference import MatchStats, offsets, reconstruct_reference, sort_order, uniquetol_keep
from helab.convert.check import check_txy
from helab.convert.pipeline import convert_raw
from helab.convert.profile import MATLAB_2019, builtin_profile
from helab.convert.raw import parse_raw
from helab.convert.reconstruct import (Backend, BackendError, NoRowsError, available_backends, backends, get_backend,
                                       reconstruct, register_backend)

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "data" / "convert" / "cases"
VARIANTS = {"2019": "matlab-2019", "2023": "matlab-2023-lab-edit"}


def case_names() -> list[str]:
    return sorted(path.name for path in CASES.iterdir() if path.is_dir())


def outcome(data: bytes, profile_name: str) -> tuple[str, bytes | None]:
    try:
        ours = convert_raw(data, builtin_profile(profile_name))
    except NoRowsError:
        return "error", None
    return ("nofile" if ours is None else "file"), ours


def test_the_cases_are_there_with_crlf_kept() -> None:
    assert len(case_names()) >= 39
    # .gitattributes '* -text': a checkout with autocrlf mustn't rewrite them.
    assert (CASES / "basic" / "d1.txt").read_bytes().count(b"\r\n") > 0
    assert b"\r" not in (CASES / "basic" / "expected-2019.txt").read_bytes()


@pytest.mark.parametrize("variant", sorted(VARIANTS))
@pytest.mark.parametrize("case", case_names())
def test_each_case_matches_matlab(case: str, variant: str) -> None:
    folder = CASES / case
    expected = json.loads((folder / f"matlab-{variant}.json").read_text())["status"]
    status, ours = outcome((folder / "d1.txt").read_bytes(), VARIANTS[variant])
    assert status == expected
    reference_path = folder / f"expected-{variant}.txt"
    reference = reference_path.read_bytes() if reference_path.exists() else None
    result = check_txy(ours, reference)
    assert result.identical, result.describe()


def sample_pairs() -> list[Path]:
    return [raw for raw in sorted((ROOT / "tests_sample_data").rglob("d[0-9]*.txt"))
            if raw.with_name(f"d_txy_forc{raw.stem[1:]}.txt").exists() and raw.parent.name != "bad_txy"]


@pytest.mark.parametrize("raw", sample_pairs(), ids=lambda path: f"{path.parent.name}/{path.name}")
def test_the_lab_converters_files_are_reproduced(raw: Path) -> None:
    reference = raw.with_name(f"d_txy_forc{raw.stem[1:]}.txt").read_bytes()
    result = check_txy(convert_raw(raw.read_bytes(), MATLAB_2019), reference)
    assert result.identical, result.describe()


def test_there_are_lab_pairs_to_reproduce() -> None:
    assert len(sample_pairs()) >= 15


def test_the_lab_pairs_are_checked_out_byte_for_byte() -> None:
    # tests_sample_data/.gitattributes '* -text': Windows autocrlf mustn't add CRs to the TXY.
    assert (ROOT / "tests_sample_data" / ".gitattributes").read_text().split() == ["*", "-text"]
    txy = sorted((ROOT / "tests_sample_data").rglob("d_txy_forc*.txt"))
    assert txy and all(b"\r" not in path.read_bytes() for path in txy)


def test_the_search_order_is_minus_one_plus_one_and_so_on() -> None:
    assert offsets(6) == [-1, 1, -2, 2, -3, 3]
    assert offsets(36)[-2:] == [-18, 18]


def test_sorting_is_stable_with_nan_last() -> None:
    nan = float("nan")
    assert sort_order([3.0, nan, 1.0, 3.0, -0.0, 0.0, nan]) == [4, 5, 2, 0, 3, 1, 6]


def test_uniquetol_keeps_the_first_of_each_group_not_chained() -> None:
    # Measured with MATLAB R2025b (builder's notes); values sorted as the port passes them.
    assert uniquetol_keep([0, 15000, 25000, 39000, 40001, 60001], 20000) == [True, False, True, False, False, True]
    assert uniquetol_keep([0, 10000, 20000, 30000, 40000, 50000], 20000) == [True, False, False, True, False, False]
    assert uniquetol_keep([0, 20000, 20000.0000001], 20000) == [True, False, True]
    assert uniquetol_keep([5, 5, 5, 20005, 20006], 20000) == [True, False, False, False, True]
    nan = float("nan")
    assert uniquetol_keep([0, 5, nan, nan], 20000) == [True, False, True, True]
    assert uniquetol_keep([], 20000) == []


def hit_rows(*hits: tuple[float, float, float, float, float]) -> bytes:
    """Trigger, then each hit's x1, x2, y1, y2 times."""
    lines = ["5,1000"]
    for t0, x1, x2, y1, y2 in hits:
        lines += [f"0,{t0 + x1:.0f}", f"1,{t0 + x2:.0f}", f"2,{t0 + y1:.0f}", f"3,{t0 + y2:.0f}"]
    return ("\r\n".join(lines) + "\r\n").encode()


def test_an_ambiguous_x2_keeps_the_first_and_isnt_retried() -> None:
    # x1 at 10000; x2 candidates at row −1 (wrong, sums don't match y) and +1 (right).
    data = b"5,1000\r\n1,9000\r\n0,10000\r\n1,10400\r\n2,10100\r\n3,10300\r\n"
    stats = MatchStats()
    hits = reconstruct_reference(parse_raw(data), MATLAB_2019, stats)
    # The x2 before x1 is kept, the y sum check fails, and the right x2 is never tried.
    assert stats.x2_ambiguous == 1 and stats.y_missing == 1 and stats.x2_retry_would_match == 1
    assert hits.shape == (0, 3)


def test_a_lone_x_pair_past_the_preallocated_rows_is_a_phantom_hit() -> None:
    # floor(3/4) = 0 rows preallocated: the x pair grows a zero row, whose T = 0 survives.
    hits = reconstruct_reference(parse_raw(b"5,1000\r\n0,10000\r\n1,10400\r\n"), MATLAB_2019)
    tx = 0.5 * (9000 + 9400 - 3200)
    assert hits.tolist() == [[0.0, ((9000 - tx) - (9400 - tx)) * 5.2632e5 * 25e-12, 0.0]]
    assert reconstruct_reference(parse_raw(b"5,1000\r\n0,10000\r\n1,10400\r\n"),
                                 MATLAB_2019.replace(matlab_overflow_row=False)).shape == (0, 3)


def test_hits_come_out_sorted_by_t_with_matlabs_arithmetic() -> None:
    data = hit_rows((90000, 500, -500, 300, -300), (20000, -700, 700, 200, -200))
    hits = reconstruct_reference(parse_raw(data), MATLAB_2019)
    assert hits.shape == (2, 3)
    x1, x2, y1, y2 = 20000 - 700 - 1000.0, 20000 + 700 - 1000.0, 20000 + 200 - 1000.0, 20000 - 200 - 1000.0
    tx, ty = 0.5 * (x1 + x2 - 3200), 0.5 * (y1 + y2 - 3200)
    assert hits[0].tolist() == [(tx + ty) / 2 * 25e-12, ((x1 - tx) - (x2 - tx)) * 5.2632e5 * 25e-12,
                                ((y1 - ty) - (y2 - ty)) * 5.2632e5 * 25e-12]
    assert hits[1, 0] > hits[0, 0]


def test_no_rows_is_matlabs_error_and_a_lone_trigger_no_hits() -> None:
    with pytest.raises(NoRowsError):
        reconstruct_reference(parse_raw(b""), MATLAB_2019)
    assert reconstruct_reference(parse_raw(b""), MATLAB_2019.replace(subtract_time_zero=False)).shape == (0, 3)
    assert reconstruct_reference(parse_raw(b"5,100\r\n"), MATLAB_2019).shape == (0, 3)
    assert convert_raw(b"5,100\r\n", MATLAB_2019) is None
    assert convert_raw(b"5,100\r\n", builtin_profile("matlab-2023-lab-edit")) == b""


def test_the_reference_backend_is_registered_and_available() -> None:
    assert "reference" in backends() and "reference" in available_backends(MATLAB_2019)
    data = hit_rows((20000, 0, 1000, 500, 1500))
    assert np.array_equal(reconstruct(parse_raw(data), MATLAB_2019),
                          reconstruct_reference(parse_raw(data), MATLAB_2019))
    with pytest.raises(BackendError):
        get_backend("no-such-backend")


def test_a_backend_that_cant_run_is_refused() -> None:
    backend = Backend(name="test-unavailable", run=lambda pulses, profile: np.zeros((0, 3)),
                      unavailable=lambda profile: "not installed")
    register_backend(backend)
    register_backend(backend)  # the same one again is fine
    assert "test-unavailable" not in available_backends()
    with pytest.raises(BackendError, match="not installed"):
        reconstruct(parse_raw(b"5,1\r\n"), MATLAB_2019, "test-unavailable")
    with pytest.raises(BackendError, match="already"):
        register_backend(Backend(name="test-unavailable", run=backend.run, unavailable=lambda profile: None))
