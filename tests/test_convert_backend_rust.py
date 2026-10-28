"""The rust backend (``helab.convert.backends.rust``, ``native/rust/``) gives the reference's output
byte for byte, whole and split within a shot, and HeLab runs without it.

Tests that need the compiled module ``helab_convert_rs`` skip without it (build it with
``maturin develop --release`` in ``native/rust/``); the ones about its absence always run.
Synthetic data and ``tests_sample_data/`` only.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import random

import numpy as np
import pytest

from helab.convert.backends import rust
from helab.convert.backends.reference import reconstruct_reference
from helab.convert.check import check_txy
from helab.convert.pipeline import convert_raw
from helab.convert.profile import MATLAB_2019, MATLAB_2023_LAB_EDIT, DetectorProfile, builtin_profile
from helab.convert.raw import RawPulses, parse_raw
from helab.convert.reconstruct import BackendError, NoRowsError, available_backends, get_backend, reconstruct
from helab.convert.txy import format_txy

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "data" / "convert" / "cases"
VARIANTS = {"2019": "matlab-2019", "2023": "matlab-2023-lab-edit"}
PROFILES = (MATLAB_2019, MATLAB_2023_LAB_EDIT)
# (threads, piece_rows): whole; cut at every gap allowed, on one and on several threads; the
# automatic pieces on several threads.
SPLITS = ((1, 0), (1, 1), (3, 1), (4, 0))

needs_rust = pytest.mark.skipif(rust.native() is None, reason=f"{rust.MODULE} isn't installed (native/rust)")


def case_names() -> list[str]:
    return sorted(path.name for path in CASES.iterdir() if path.is_dir())


def same_hits(ours: np.ndarray, reference: np.ndarray) -> bool:
    """Bit for bit (−0 included) and the same TXY text."""
    return (ours.shape == reference.shape and ours.dtype == reference.dtype and ours.tobytes() == reference.tobytes()
            and format_txy(ours) == format_txy(reference))


def test_the_backend_is_registered_and_releases_the_gil() -> None:
    backend = get_backend("rust")
    assert backend.releases_gil and backend.name == "rust"


def test_without_the_compiled_module_the_backend_says_why_and_wont_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse() -> rust.Native:
        raise ImportError(f"No module named {rust.MODULE!r}")

    monkeypatch.setattr(rust, "_native", None)
    monkeypatch.setattr(rust, "_missing", None)
    monkeypatch.setattr(rust, "_import_native", refuse)
    reason = get_backend("rust").unavailable(MATLAB_2019)
    assert reason is not None and rust.MODULE in reason
    assert "rust" not in available_backends(MATLAB_2019)
    assert "reference" in available_backends(MATLAB_2019)
    with pytest.raises(BackendError, match="can't run"):
        reconstruct(parse_raw(b"5,1000\r\n"), MATLAB_2019, "rust")


@needs_rust
def test_it_refuses_candidate_handling_it_doesnt_have() -> None:
    # Only "matlab" exists today and a profile refuses anything else, so force one.
    other = MATLAB_2019.replace()
    object.__setattr__(other, "x2_handling", "retry")
    assert rust.unavailable(other) is not None
    assert rust.unavailable(MATLAB_2019) is None


@needs_rust
@pytest.mark.parametrize("variant", sorted(VARIANTS))
@pytest.mark.parametrize("case", case_names())
def test_each_case_matches_matlab(case: str, variant: str) -> None:
    folder = CASES / case
    expected = json.loads((folder / f"matlab-{variant}.json").read_text())["status"]
    try:
        ours = convert_raw((folder / "d1.txt").read_bytes(), builtin_profile(VARIANTS[variant]), "rust")
        status = "nofile" if ours is None else "file"
    except NoRowsError:
        status, ours = "error", None
    assert status == expected
    reference_path = folder / f"expected-{variant}.txt"
    result = check_txy(ours, reference_path.read_bytes() if reference_path.exists() else None)
    assert result.identical, result.describe()


@needs_rust
@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.name)
@pytest.mark.parametrize("case", case_names())
def test_each_case_split_within_the_shot_equals_the_reference(case: str, profile: DetectorProfile) -> None:
    # Among them the phantom_* and dead_time_x1 cases (A10.2): every split gives the same bits.
    pulses = parse_raw((CASES / case / "d1.txt").read_bytes())
    if len(pulses) == 0:
        for threads, piece_rows in SPLITS:
            with pytest.raises(NoRowsError):
                rust.reconstruct_rust(pulses, profile, threads, piece_rows)
        return
    reference = reconstruct_reference(pulses, profile)
    for threads, piece_rows in SPLITS:
        ours, _ = rust.reconstruct_rust(pulses, profile, threads, piece_rows)
        assert same_hits(ours, reference), (threads, piece_rows)


@needs_rust
@pytest.mark.parametrize("case", ["phantom_after_hit", "phantom_multi", "phantom_multi_cut", "dead_time_x1"])
def test_the_phantom_and_dead_time_cases_are_really_split(case: str) -> None:
    pulses = parse_raw((CASES / case / "d1.txt").read_bytes())
    for profile in PROFILES:
        _, pieces = rust.reconstruct_rust(pulses, profile, 1, 1)
        assert pieces >= 3


def sample_pairs() -> list[Path]:
    return [raw for raw in sorted((ROOT / "tests_sample_data").rglob("d[0-9]*.txt"))
            if raw.with_name(f"d_txy_forc{raw.stem[1:]}.txt").exists() and raw.parent.name != "bad_txy"]


@needs_rust
@pytest.mark.parametrize("raw", sample_pairs(), ids=lambda path: f"{path.parent.name}/{path.name}")
def test_the_lab_converters_files_are_reproduced(raw: Path) -> None:
    reference = raw.with_name(f"d_txy_forc{raw.stem[1:]}.txt").read_bytes()
    pulses = parse_raw(raw.read_bytes())
    for threads, piece_rows in SPLITS:
        hits, _ = rust.reconstruct_rust(pulses, MATLAB_2019, threads, piece_rows)
        result = check_txy(format_txy(hits) if hits.shape[0] else None, reference)
        assert result.identical, (threads, piece_rows, result.describe())


def random_shot(rng: random.Random, events: int, dense: bool) -> RawPulses:
    """A trigger, then events (hits, lone x pairs, lone x1, two x2, noise, equal times) at gaps
    below, at and above the search window and the 2023 dead time, in nearly time order, with the
    odd NaN and fractional time. ``dense``: only hits and one lone x pair, so the phantom row's
    floor(N/4) is met."""
    rows: list[tuple[float, float]] = [(5.0, 1000.0 + rng.randrange(1000))]
    t = rows[0][1]
    kinds = ("hit",) if dense else ("hit", "hit", "pair", "x1", "two_x2", "noise", "equal")
    pair_at = rng.choice((events, events - 1, rng.randrange(events + 1)))
    for event in range(events + 1):
        t += rng.choice((rng.uniform(0, 3000), 3200.0, 3201.0, rng.uniform(3201, 25000), rng.uniform(20000, 60000)))
        t = float(round(t)) if rng.random() < 0.97 else t
        kind = "pair" if dense and event == pair_at else "skip" if event == events else rng.choice(kinds)
        x1, x2 = t + rng.randrange(1500), t + rng.randrange(1500)
        y1 = t + rng.randrange(1500)
        y2 = x1 + x2 - y1 + (rng.randrange(-300, 300) if dense else rng.randrange(-600, 600))
        if kind == "hit":
            rows += [(0.0, x1), (1.0, x2), (2.0, y1), (3.0, y2)]
        elif kind == "pair":
            rows += [(0.0, x1), (1.0, x2)]
        elif kind == "x1":
            rows += [(0.0, x1)]
        elif kind == "two_x2":
            rows += [(1.0, x2 - 900), (0.0, x1), (1.0, x2), (2.0, y1), (3.0, y2)]
        elif kind == "noise":
            rows += [(float(rng.randrange(6)), t + rng.randrange(3000)) for _ in range(rng.randrange(1, 6))]
        elif kind == "equal":
            rows += [(0.0, t), (1.0, t), (2.0, t), (3.0, t), (0.0, t), (1.0, t)]
    for k in range(1, len(rows) - 1):  # nearly in time order, as the TDC writes
        if rng.random() < 0.1:
            rows[k], rows[k + 1] = rows[k + 1], rows[k]
    if rng.random() < 0.05:
        k = rng.randrange(1, len(rows))
        rows[k] = (rows[k][0], math.nan)
    if rng.random() < 0.05:
        rows.insert(0, rows.pop(rng.randrange(len(rows))))  # t_zero not the trigger
    values = np.array(rows, dtype=np.float64)
    return RawPulses(channels=np.ascontiguousarray(values[:, 0]), times=np.ascontiguousarray(values[:, 1]))


@needs_rust
@pytest.mark.parametrize("seed", range(8))
def test_random_shots_split_any_way_equal_the_reference(seed: int) -> None:
    rng = random.Random(seed)
    phantoms = split = 0
    for shot in range(40):
        dense = shot % 2 == 0
        pulses = random_shot(rng, rng.randrange(1, 16) if dense else rng.randrange(1, 120), dense)
        for profile in PROFILES:
            reference = reconstruct_reference(pulses, profile)
            phantoms += int(bool(np.any((reference[:, 0] == 0) & (reference[:, 2] == 0))))
            for threads, piece_rows in SPLITS + ((2, 3), (8, 1)):
                ours, pieces = rust.reconstruct_rust(pulses, profile, threads, piece_rows)
                split += pieces > 1
                assert same_hits(ours, reference), (seed, shot, profile.name, threads, piece_rows)
    assert phantoms and split


@needs_rust
def test_a_phantom_row_from_an_earlier_piece_survives_a_later_piece_without_attempts() -> None:
    # No trigger: each hit's y1 comes first, so skipping the first sorted row costs nothing. Three
    # hits, a lone x pair, then one MCP pulse far away: N = 15, floor(N/4) = 3 = R, so row R + 1
    # (the pair's) is a grown row and survives as the phantom, though the last piece is the MCP's.
    lines = []
    for t0 in (10000, 20000, 30000):
        lines += [f"2,{t0}", f"0,{t0 + 500}", f"1,{t0 + 600}", f"3,{t0 + 1100}"]
    lines += ["0,40000", "1,40300", "4,90000"]
    pulses = parse_raw(("\r\n".join(lines) + "\r\n").encode())
    reference = reconstruct_reference(pulses, MATLAB_2019)
    assert reference.shape == (4, 3) and np.sum((reference[:, 0] == 0) & (reference[:, 2] == 0)) == 1
    for threads, piece_rows in SPLITS:
        ours, pieces = rust.reconstruct_rust(pulses, MATLAB_2019, threads, piece_rows)
        assert same_hits(ours, reference), (threads, piece_rows)
    assert rust.reconstruct_rust(pulses, MATLAB_2019, 1, 1)[1] == 5


@needs_rust
def test_the_cut_goes_only_between_finite_times_more_than_the_window_apart() -> None:
    native = rust.native()
    assert native is not None
    # Sorted, as the matching sees them: gaps of exactly the window, more, and next to Inf and NaN.
    times = np.array([0, 3200, 6401, 6402, 6402, 9603, 20000, math.inf, math.nan, math.nan], dtype=np.float64)
    assert native.cut_points(times, 3200.0, 1) == [0, 2, 5, 6, 10]
    assert native.cut_points(times, 3200.0, 0) == [0, 10]
    assert native.cut_points(times, 3200.0, 4) == [0, 5, 10]


@needs_rust
def test_threads_converting_shots_at_once_give_the_reference() -> None:
    rng = random.Random(99)
    shots = [random_shot(rng, 400, dense=False) for _ in range(12)]
    expected = [reconstruct_reference(shot, MATLAB_2019) for shot in shots]
    with ThreadPoolExecutor(6) as pool:
        got = list(pool.map(lambda shot: reconstruct(shot, MATLAB_2019, "rust"), shots))
    assert all(same_hits(ours, reference) for ours, reference in zip(got, expected))


@needs_rust
def test_no_rows_is_matlabs_error_unless_time_zero_is_off() -> None:
    empty = parse_raw(b"")
    with pytest.raises(NoRowsError):
        reconstruct(empty, MATLAB_2019, "rust")
    assert reconstruct(empty, MATLAB_2019.replace(subtract_time_zero=False), "rust").shape == (0, 3)


@needs_rust
def test_the_rust_raw_parser_reads_strict_files_as_parse_raw_and_refuses_others() -> None:
    native = rust.native()
    assert native is not None
    for path in sorted(CASES.glob("*/d1.txt")) + sample_pairs():
        data = path.read_bytes()
        expected = parse_raw(data)
        got = native.parse_strict(data)
        if got is not None:
            assert got[0].tobytes() == expected.channels.tobytes() and got[1].tobytes() == expected.times.tobytes()
    assert native.parse_strict(b"0,1\r\n5,99999999999999999999\r\n") is None  # 20 digits: Python's
    big = b"0,9007199254740993\n"  # 2^53 + 1 rounds to even, as float(int) does
    strict = native.parse_strict(big)
    assert strict is not None and strict[1].tolist() == parse_raw(big).times.tolist()
    assert native.parse_strict(b"0,1\r\n0,2\n") is None and native.parse_strict(b"0,1") is None


@needs_rust
def test_the_rust_formatter_writes_what_format_txy_writes() -> None:
    native = rust.native()
    assert native is not None
    rng = np.random.default_rng(5)
    special = [0.0, -0.0, math.nan, math.inf, -math.inf, 0.125, 123456785.0, 123456795.0, 1e-5, 9.99999995e-5,
               0.0001, 99999999.5, 12345678.5, 5e-324, 1.7976931348623157e308, -2.5e-12, 1e16, 1e-300]
    values = np.concatenate([np.array(special), rng.normal(0, 1e-3, 3000), rng.normal(0, 1, 3000),
                             10.0 ** rng.uniform(-12, 12, 3000) * rng.choice([-1, 1], 3000),
                             np.round(rng.uniform(-1e9, 1e9, 3000)) / 2.0 ** rng.integers(0, 30, 3000)])
    values = np.concatenate([values, np.zeros((-len(values)) % 3)])
    hits = values.reshape(-1, 3)
    assert native.format_txy(np.ascontiguousarray(hits.ravel())) == format_txy(hits)
