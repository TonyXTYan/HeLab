"""A shot cut into pieces converts as the whole shot does (``helab.convert.split``).

Pieces are forced small (``min_rows=1``: a cut at every safe gap), for both backends that ship
with stage 2's NumPy floor, on every case (the ``phantom_*`` and ``dead_time_x1`` ones among them)
and ``tests_sample_data/``, serially and on thread and process pools.
"""
from __future__ import annotations

from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor
import math
from pathlib import Path

import numpy as np
import pytest

from helab.convert.profile import MATLAB_2019, MATLAB_2023_LAB_EDIT, DetectorProfile
from helab.convert.raw import RawPulses, parse_raw
from helab.convert.reconstruct import NoRowsError, reconstruct
from helab.convert.split import cut_threshold, plan_cuts, reconstruct_split, sorted_rows
from helab.convert.txy import format_txy

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "data" / "convert" / "cases"
PROFILES = [MATLAB_2019, MATLAB_2023_LAB_EDIT]
BACKENDS = ["reference", "numpy"]


def whole_and_split(pulses: RawPulses, profile: DetectorProfile, backend: str, executor: Executor | None = None,
                    min_rows: int = 1) -> tuple[bytes | None, bytes | None]:
    try:
        whole = format_txy(reconstruct(pulses, profile, backend))
    except NoRowsError:
        whole = None
    try:
        split = format_txy(reconstruct_split(pulses, profile, backend, executor=executor, min_rows=min_rows))
    except NoRowsError:
        split = None
    return whole, split


def case_names() -> list[str]:
    return sorted(path.name for path in CASES.iterdir() if path.is_dir())


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.name)
@pytest.mark.parametrize("case", case_names())
def test_each_case_split_equals_the_whole(case: str, profile: DetectorProfile, backend: str) -> None:
    pulses = parse_raw((CASES / case / "d1.txt").read_bytes())
    whole, split = whole_and_split(pulses, profile, backend)
    assert whole == split


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.name)
@pytest.mark.parametrize("case", ["phantom_after_hit", "phantom_lone_pair", "phantom_multi", "phantom_multi_cut",
                                  "phantom_none", "dead_time_x1"])
def test_the_phantom_and_dead_time_cases_are_cut(case: str, profile: DetectorProfile) -> None:
    pulses = parse_raw((CASES / case / "d1.txt").read_bytes())
    assert plan_cuts(sorted_rows(pulses, profile)[1], profile, None, 1)


def test_the_phantom_row_comes_from_the_tail_after_the_last_hit() -> None:
    # Pulses 10 µs apart groups, so each group is its own piece. Trigger, two hits, a lone x
    # pair: N = 11, floor(N/4) = 2 rows for 2 hits, so the pair goes into a row MATLAB grew with
    # zeros: the phantom row (T = 0), which the split makes from the tail (the second hit's
    # piece onwards). With a second pair (N = 13, 3 rows) or a pair before the last hit, none.
    def rows(*groups: tuple[float, ...]) -> RawPulses:
        values = [(5.0, 0.0)] + [(float(channel), time) for group in groups for channel, time in enumerate(group)]
        array = np.array(values)
        return RawPulses(np.ascontiguousarray(array[:, 0]), np.ascontiguousarray(array[:, 1]))

    def hit(t0: float) -> tuple[float, ...]:
        return t0 + 1000.0, t0 + 2200.0, t0 + 1500.0, t0 + 1700.0

    def pair(t0: float) -> tuple[float, ...]:
        return t0 + 1000.0, t0 + 1900.0

    phantom = rows(hit(4e5), hit(8e5), pair(1.2e6))
    assert format_txy(reconstruct(phantom, MATLAB_2019)).startswith(b"0,")
    for pulses in (phantom, rows(hit(4e5), hit(8e5), pair(1.2e6), pair(1.6e6)), rows(hit(4e5), pair(8e5), hit(1.2e6)),
                   rows(pair(4e5)), rows(pair(4e5), pair(8e5))):
        assert len(plan_cuts(sorted_rows(pulses, MATLAB_2019)[1], MATLAB_2019, None, 1)) >= 1
        for profile in PROFILES:
            whole, split = whole_and_split(pulses, profile, "numpy")
            assert whole == split


def sample_raws() -> list[Path]:
    return sorted((ROOT / "tests_sample_data").rglob("d[0-9]*.txt"))


@pytest.mark.parametrize("raw", sample_raws(), ids=lambda path: f"{path.parent.name}/{path.name}")
def test_the_lab_files_split_equal_the_whole(raw: Path) -> None:
    pulses = parse_raw(raw.read_bytes())
    for profile in PROFILES:
        whole, split = whole_and_split(pulses, profile, "numpy", min_rows=20)
        assert whole == split


@pytest.mark.parametrize("pool", [ThreadPoolExecutor, ProcessPoolExecutor])
def test_pieces_run_on_a_pool(pool: type[Executor]) -> None:
    pulses = parse_raw(max(sample_raws(), key=lambda path: path.stat().st_size).read_bytes())
    with pool(2) as executor:  # type: ignore[call-arg]
        for profile in PROFILES:
            whole, split = whole_and_split(pulses, profile, "numpy", executor, min_rows=1000)
            assert whole == split
    assert len(plan_cuts(sorted_rows(pulses, MATLAB_2019)[1], MATLAB_2019, None, 1000)) > 1


def test_cuts_go_only_in_gaps_wider_than_the_window_and_dead_times() -> None:
    t = np.array([0.0, 3200.0, 6401.0, 6402.0, 30000.0, 51000.0, math.nan, math.nan])
    assert plan_cuts(t, MATLAB_2019, None, 1) == [2, 4, 5]
    assert cut_threshold(MATLAB_2023_LAB_EDIT) == pytest.approx(20000.0)
    assert plan_cuts(t, MATLAB_2023_LAB_EDIT, None, 1) == [4, 5]
    # min_rows and the piece count: no piece shorter than min_rows, about len/pieces long.
    assert plan_cuts(t, MATLAB_2019, None, 3) == [4]
    assert plan_cuts(t, MATLAB_2019, 2, 1) == [4]
    assert plan_cuts(np.array([0.0, 1.0]), MATLAB_2019, 4, 1) == []


def test_a_file_without_rows_is_still_an_error() -> None:
    with pytest.raises(NoRowsError):
        reconstruct_split(RawPulses(np.empty(0), np.empty(0)), MATLAB_2019, "numpy", min_rows=1)
