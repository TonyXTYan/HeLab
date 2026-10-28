"""The ``cython`` converter backend gives the reference's output byte for byte
(``helab.convert.backends.cython``, kernel ``native/cython/_kernel.pyx``).

The tests that run the kernel skip, with the reason, when it isn't built (``python
native/cython/build.py``); the rest check that HeLab works without it. Synthetic data and
``tests_sample_data/`` only, never the sample set.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import ModuleType

import numpy as np
import pytest

import helab.convert.backends.cython as cython_backend
from helab.convert.backends.cython import cut_points, reconstruct_cython, search_offsets
from helab.convert.backends.reference import offsets, reconstruct_reference
from helab.convert.pipeline import convert_raw
from helab.convert.profile import MATLAB_2019, MATLAB_2023_LAB_EDIT, BUILTIN_PROFILES, DetectorProfile
from helab.convert.raw import RawPulses, parse_raw
from helab.convert.reconstruct import BackendError, NoRowsError, backends, get_backend, reconstruct
from helab.convert.txy import format_txy

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "data" / "convert" / "cases"
VARIANTS = {"2019": "matlab-2019", "2023": "matlab-2023-lab-edit"}
THREADS = (1, 2, 3, 8, 64)

WHY_NOT = cython_backend.unavailable(None)
needs_kernel = pytest.mark.skipif(WHY_NOT is not None, reason=f"cython backend unavailable: {WHY_NOT}")


def case_names() -> list[str]:
    return sorted(path.name for path in CASES.iterdir() if path.is_dir())


def converted(data: bytes, profile: DetectorProfile, backend: str) -> tuple[str, bytes | None]:
    try:
        ours = convert_raw(data, profile, backend)
    except NoRowsError:
        return "error", None
    return ("nofile" if ours is None else "file"), ours


def txy_or_error(pulses: RawPulses, profile: DetectorProfile, threads: int | None = None) -> bytes | str:
    try:
        hits = reconstruct_reference(pulses, profile) if threads is None else reconstruct_cython(pulses, profile,
                                                                                                 threads)
    except NoRowsError:
        return "error"
    return format_txy(hits)


def sorted_times(pulses: RawPulses, profile: DetectorProfile) -> np.ndarray:
    module = cython_backend.kernel()
    assert module is not None
    _, times = module.prepare(pulses.channels, pulses.times, profile.subtract_time_zero, np.empty(0), np.empty(0))
    assert isinstance(times, np.ndarray)
    return times


# Registration and running without the kernel.

def test_the_backend_is_registered_and_releases_the_gil() -> None:
    backend = get_backend("cython")
    assert "cython" in backends() and backend.releases_gil
    assert backend.unavailable is cython_backend.unavailable


def test_without_the_kernel_it_says_why_and_helab_goes_on(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing() -> ModuleType:
        raise ImportError("No module named 'helab.convert.backends.cython._kernel'")

    monkeypatch.setattr(cython_backend, "_import_kernel", missing)
    cython_backend._reset()
    try:
        why = cython_backend.unavailable(MATLAB_2019)
        assert why is not None and "isn't built" in why and "native/cython/build.py" in why
        assert "cython" in backends()
        with pytest.raises(BackendError, match="isn't built"):
            reconstruct(parse_raw(b"5,100\r\n"), MATLAB_2019, "cython")
        # The reference still runs.
        assert convert_raw(b"5,100\r\n", MATLAB_2019) is None
    finally:
        cython_backend._reset()


@needs_kernel
def test_a_kernel_older_than_its_source_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    newer = tmp_path / "_kernel.pyx"
    newer.write_text("# changed since the build\n")
    monkeypatch.setattr(cython_backend, "_SOURCE", newer)
    cython_backend._reset()
    try:
        why = cython_backend.unavailable(None)
        assert why is not None and "older than" in why
    finally:
        cython_backend._reset()
    assert cython_backend._SOURCE == newer and cython_backend.unavailable(None) is not None
    monkeypatch.undo()
    cython_backend._reset()
    assert cython_backend.unavailable(None) is None


@needs_kernel
def test_threads_making_the_first_call_together_all_get_the_kernel(monkeypatch: pytest.MonkeyPatch) -> None:
    # The harness's thread pool starts every worker on its first shot at once.
    started = threading.Barrier(8)
    real = cython_backend._import_kernel

    def slow() -> ModuleType:
        time.sleep(0.05)
        return real()

    def first_use() -> tuple[bool, str | None]:
        started.wait()
        return cython_backend.kernel() is not None, cython_backend.unavailable(MATLAB_2019)

    monkeypatch.setattr(cython_backend, "_import_kernel", slow)
    cython_backend._reset()
    try:
        with ThreadPoolExecutor(8) as pool:
            assert list(pool.map(lambda _: first_use(), range(8))) == [(True, None)] * 8
    finally:
        cython_backend._reset()


@needs_kernel
def test_a_channel_that_isnt_exactly_a_double_is_refused() -> None:
    assert cython_backend.unavailable(MATLAB_2019) is None
    assert cython_backend.unavailable(MATLAB_2019.replace(channel_y2=2 ** 53 + 1)) is not None
    assert cython_backend.unavailable(MATLAB_2019.replace(channel_y2=10 ** 400)) is not None


def test_the_backend_imports_no_qt_or_plotting_library() -> None:
    # As tests/test_headless_imports.py does for the PURE modules (helab.convert is Qt-free).
    script = ("import importlib, json, sys; importlib.import_module('helab.convert.backends.cython'); "
              "print(json.dumps(sorted(m for m in ('PyQt6', 'pyqtgraph', 'matplotlib', 'dash', 'plotly', "
              "'helab.utils.constants') if m in sys.modules)))")
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120,
                          env=dict(os.environ), cwd=ROOT)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout.splitlines()[-1]) == []


# The parts in Python.

def test_the_search_offsets_are_the_references_cut_where_they_leave_the_rows() -> None:
    for depth in (0, 1, 2, 7, 36, 101):
        assert search_offsets(depth, 10 ** 6).tolist() == offsets(depth)
        for rows in (0, 1, 2, 5, 40):
            cut = search_offsets(depth, rows).tolist()
            assert cut == offsets(depth)[:len(cut)]
            assert all(abs(offset) > rows for offset in offsets(depth)[len(cut):])
    assert search_offsets(-3, 10).tolist() == []


def test_cuts_are_only_at_gaps_longer_than_the_window() -> None:
    nan = float("nan")
    times = np.array([0, 10, 3210, 3211, 6412, 6412, 20000, 20001, nan, nan], dtype=np.float64)
    assert cut_points(times, 3200.0, 1) == []
    every = cut_points(times, 3200.0, 100)
    # 3210 − 10 = 3200 isn't more than the window; no cut beside the NaN rows.
    assert every == [4, 6]
    assert all(times[k] - times[k - 1] > 3200.0 for k in every)
    assert cut_points(times, 3200.0, 2) == [6]
    assert cut_points(np.array([0.0, 1.0, 2.0]), 3200.0, 4) == []
    assert cut_points(np.empty(0), 3200.0, 4) == []


@needs_kernel
def test_the_kernels_sort_is_matlabs_stable_nan_last_order() -> None:
    # prepare carries each row's channel along, so channels 0, 1, 2, … give the order back.
    # NumPy's stable argsort is the reference's sort_order (NaN last, ties and ±0 in file order).
    module = cython_backend.kernel()
    assert module is not None
    rng = np.random.default_rng(7)
    for n in (0, 1, 2, 31, 32, 33, 64, 65, 100, 1000, 5000):
        nearly = np.arange(n, dtype=np.float64) + rng.integers(-40, 40, size=n)
        if n:
            nearly[rng.integers(0, n, size=1 + n // 500)] = rng.integers(-10 ** 6, 10 ** 6)  # far outliers
        ties = rng.integers(0, 5, size=n).astype(np.float64)
        signed = rng.choice(np.array([0.0, -0.0, 1.0, np.nan, -np.inf, np.inf]), size=n)
        for times in (nearly, ties, signed, nearly[::-1].copy(), np.sort(nearly)):
            order = np.arange(n, dtype=np.float64)
            channels, sorted_ = module.prepare(order, times, False, np.empty(0), np.empty(0))
            expected = np.argsort(times, kind="stable")
            assert channels.tolist() == expected.tolist(), n
            assert sorted_.tobytes() == times[expected].tobytes()


# Byte for byte: the cases, the lab pairs, the quirks.

@needs_kernel
@pytest.mark.parametrize("variant", sorted(VARIANTS))
@pytest.mark.parametrize("case", case_names())
def test_each_case_matches_the_reference_and_matlab(case: str, variant: str) -> None:
    folder = CASES / case
    data = (folder / "d1.txt").read_bytes()
    profile = BUILTIN_PROFILES[VARIANTS[variant]]
    expected = json.loads((folder / f"matlab-{variant}.json").read_text())["status"]
    reference_path = folder / f"expected-{variant}.txt"
    matlab = reference_path.read_bytes() if reference_path.exists() else None
    assert converted(data, profile, "cython") == (expected, matlab)
    pulses = parse_raw(data)
    for changed in (profile, profile.replace(matlab_overflow_row=not profile.matlab_overflow_row)):
        reference = txy_or_error(pulses, changed)
        for threads in THREADS:
            assert txy_or_error(pulses, changed, threads) == reference, (changed.name, threads)


@needs_kernel
@pytest.mark.parametrize("case", ["phantom_after_hit", "phantom_lone_pair", "phantom_multi", "phantom_multi_cut",
                                  "phantom_none", "dead_time_x1"])
def test_a_split_shot_equals_the_whole_on_the_phantom_and_dead_time_cases(case: str) -> None:
    pulses = parse_raw((CASES / case / "d1.txt").read_bytes())
    for profile in BUILTIN_PROFILES.values():
        whole = txy_or_error(pulses, profile, 1)
        assert whole == txy_or_error(pulses, profile)
        # Every possible cut at once, then each single cut.
        every = cut_points(sorted_times(pulses, profile), profile.search_window, len(pulses))
        assert every, "the case has no gap to cut at"
        for pieces in range(2, len(every) + 2):
            assert txy_or_error(pulses, profile, pieces) == whole


def sample_pairs() -> list[Path]:
    return [raw for raw in sorted((ROOT / "tests_sample_data").rglob("d[0-9]*.txt"))
            if raw.with_name(f"d_txy_forc{raw.stem[1:]}.txt").exists() and raw.parent.name != "bad_txy"]


@needs_kernel
@pytest.mark.parametrize("raw", sample_pairs(), ids=lambda path: f"{path.parent.name}/{path.name}")
def test_the_lab_converters_files_are_reproduced(raw: Path) -> None:
    reference = raw.with_name(f"d_txy_forc{raw.stem[1:]}.txt").read_bytes()
    assert convert_raw(raw.read_bytes(), MATLAB_2019, "cython") == reference
    pulses = parse_raw(raw.read_bytes())
    assert len(cut_points(sorted_times(pulses, MATLAB_2019), MATLAB_2019.search_window, 16)) > 0
    for threads in (4, 16):
        assert format_txy(reconstruct_cython(pulses, MATLAB_2019, threads)) == reference
    assert txy_or_error(pulses, MATLAB_2023_LAB_EDIT, 8) == txy_or_error(pulses, MATLAB_2023_LAB_EDIT)


def pulses_of(rows: list[tuple[float, float]]) -> RawPulses:
    values = np.array(rows, dtype=np.float64).reshape(-1, 2)
    return RawPulses(channels=np.ascontiguousarray(values[:, 0]), times=np.ascontiguousarray(values[:, 1]))


def hit(t0: float, u: float = 300, v: float = -200) -> list[tuple[float, float]]:
    return [(0, t0 + u), (1, t0 - u), (2, t0 + v), (3, t0 - v)]


@needs_kernel
def test_the_phantom_row_carries_over_pieces_with_no_x_pair() -> None:
    # Three hits, a lone x pair, then a lone y1 20,000 bins on: 15 rows, floor(15/4) = 3 rows
    # preallocated, so the lone pair's row 4 is grown and survives as T = 0. Its report comes
    # from the fourth piece and must pass the fifth, which has no x1.
    profile = MATLAB_2019.replace(skip_first_sorted_row=False)
    pulses = pulses_of([*hit(10000), *hit(30000), *hit(50000), (0, 70300), (1, 69700), (2, 90000)])
    whole = reconstruct_reference(pulses, profile)
    assert whole.shape == (4, 3) and [row[0] == 0.0 and row[2] == 0.0 for row in whole.tolist()].count(True) == 1
    assert cut_points(sorted_times(pulses, profile), profile.search_window, len(pulses)) == [4, 8, 12, 14]
    for threads in (*range(1, 7), len(pulses)):
        assert reconstruct_cython(pulses, profile, threads).tobytes() == whole.tobytes()
    # A hit after the lone pair clears it: no phantom.
    later = pulses_of([*hit(10000), *hit(30000), (0, 50300), (1, 49700), *hit(70000)])
    assert reconstruct_reference(later, profile).shape == (3, 3)
    for threads in range(1, 6):
        assert reconstruct_cython(later, profile, threads).tobytes() == reconstruct_reference(later, profile).tobytes()


@needs_kernel
def test_no_rows_is_matlabs_error_and_the_signs_of_zero_are_kept() -> None:
    empty = pulses_of([])
    with pytest.raises(NoRowsError):
        reconstruct_cython(empty, MATLAB_2019)
    assert reconstruct_cython(empty, MATLAB_2019.replace(subtract_time_zero=False)).shape == (0, 3)
    assert reconstruct_cython(pulses_of([(5, 100)]), MATLAB_2019).shape == (0, 3)
    # A negative v⊥y makes the phantom row's Y −0.0 (the reference's arithmetic, "-0" in the TXY).
    profile = MATLAB_2019.replace(v_perp_y=-5.2632e5)
    pulses = pulses_of([(5, 1000), (0, 10000), (1, 10400)])
    reference = format_txy(reconstruct_reference(pulses, profile))
    assert b"-0" in reference
    assert format_txy(reconstruct_cython(pulses, profile)) == reference


def random_shot(rng: np.random.Generator) -> RawPulses:
    """Hits, partial hits and noise in clusters; gaps short and long; some rows NaN or equal. A
    quarter are clean (whole hits only, then a lone x pair), which reaches the phantom row."""
    rows: list[tuple[float, float]] = [(float(rng.choice([5, 0, 2])), 1000.0)]
    clean = rng.random() < 0.25
    t = 2000.0
    for _ in range(int(rng.integers(1, 40))):
        t += float(rng.choice([rng.integers(0, 3000), rng.integers(3000, 3400), rng.integers(3400, 60000)]))
        kind = 0.0 if clean else rng.random()
        if kind < 0.55:
            rows += hit(t, float(rng.integers(-1500, 1500)), float(rng.integers(-1500, 1500)))
        elif kind < 0.75:
            rows += hit(t)[:int(rng.integers(1, 4))]
        else:
            rows += [(float(rng.integers(0, 6)), t + float(rng.integers(-3500, 3500)))
                     for _ in range(int(rng.integers(1, 8)))]
        if not clean and rng.random() < 0.15:
            rows.append((float(rng.integers(0, 4)), rows[-1][1]))
    if clean or rng.random() < 0.3:
        rows += [(0, t + 100000), (1, t + 100400)]  # a lone pair at the end
    if not clean and rng.random() < 0.2:
        rows.insert(int(rng.integers(1, len(rows))), (float(rng.integers(0, 4)), float("nan")))
    order = np.arange(len(rows))
    if rng.random() < 0.5:
        swaps = rng.integers(1, len(rows), size=len(rows) // 5)
        order[swaps], order[swaps - 1] = order[swaps - 1], order[swaps].copy()
    return pulses_of([rows[k] for k in order])


FUZZ_PROFILES = {
    "2019": MATLAB_2019,
    "2023": MATLAB_2023_LAB_EDIT,
    "2019-no-overflow": MATLAB_2019.replace(matlab_overflow_row=False),
    "2019-no-skip-no-t0": MATLAB_2019.replace(skip_first_sorted_row=False, subtract_time_zero=False),
    "2019-shallow": MATLAB_2019.replace(search_depth=3, search_window=1500.0),
    "2019-deep-raw": MATLAB_2019.replace(search_depth=200, position_formula="raw"),
    "2023-all-dead": MATLAB_2023_LAB_EDIT.replace(dead_time_x2=0.1e-6, dead_time_y1=0.05e-6, dead_time_y2=1e-6),
}


def fuzz_shots(seed: int) -> list[RawPulses]:
    rng = np.random.default_rng(seed)
    return [random_shot(rng) for _ in range(5)]


@needs_kernel
@pytest.mark.parametrize("seed", range(40))
def test_random_shots_match_the_reference_whole_and_split(seed: int) -> None:
    for pulses in fuzz_shots(seed):
        for name, profile in FUZZ_PROFILES.items():
            reference = txy_or_error(pulses, profile)
            for threads in (1, 2, 5, 1000):
                assert txy_or_error(pulses, profile, threads) == reference, (seed, name, threads)


@needs_kernel
def test_the_random_shots_reach_the_phantom_row_and_many_pieces() -> None:
    # The fuzz above is only worth having if it covers these.
    phantoms = split = 0
    for pulses in (shot for seed in range(40) for shot in fuzz_shots(seed)):
        with_phantom = reconstruct_reference(pulses, MATLAB_2019).shape[0]
        phantoms += with_phantom > reconstruct_reference(pulses, MATLAB_2019.replace(matlab_overflow_row=False)).shape[0]
        split += len(cut_points(sorted_times(pulses, MATLAB_2019), MATLAB_2019.search_window, 1000)) >= 3
    assert phantoms >= 5 and split >= 100, (phantoms, split)
