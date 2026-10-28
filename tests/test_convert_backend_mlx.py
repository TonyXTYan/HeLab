"""The ``mlx`` backend gives the reference's output byte for byte (``helab.convert.backends.mlx_gpu``).

The GPU tests skip where MLX can't run (not Apple Silicon, or the package missing); the rest
run everywhere: the same pipeline with the first-choice search on the CPU
(``reconstruct_mlx(..., gpu=False)``) checks the integer conversion, the greedy pass and the
output, which are shared. Synthetic data and ``tests_sample_data/`` only.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from helab.convert.backends import mlx_gpu
from helab.convert.backends.reference import reconstruct_reference, uniquetol_keep
from helab.convert.check import check_txy
from helab.convert.pipeline import convert_raw
from helab.convert.profile import MATLAB_2019, MATLAB_2023_LAB_EDIT, DetectorProfile, builtin_profile
from helab.convert.raw import RawPulses, parse_raw
from helab.convert.reconstruct import _MODULES, NoRowsError, backends, get_backend, reconstruct
from helab.convert.txy import format_txy

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "data" / "convert" / "cases"
VARIANTS = {"2019": "matlab-2019", "2023": "matlab-2023-lab-edit"}
REASON = mlx_gpu._unavailable(None)
needs_gpu = pytest.mark.skipif(REASON is not None, reason=f"mlx backend unavailable: {REASON}")


def case_names() -> list[str]:
    return sorted(path.name for path in CASES.iterdir() if path.is_dir())


def txy_or_error(pulses: RawPulses, profile: DetectorProfile, gpu: bool | None) -> bytes:
    """The TXY bytes from the reference (``gpu`` None) or the mlx pipeline, or b"error"."""
    try:
        if gpu is None:
            return format_txy(reconstruct_reference(pulses, profile))
        return format_txy(mlx_gpu.reconstruct_mlx(pulses, profile, gpu=gpu))
    except NoRowsError:
        return b"error"


def test_mlx_is_registered_by_name_for_spawned_workers() -> None:
    assert _MODULES["mlx"] == "helab.convert.backends.mlx_gpu"
    assert "mlx" in backends()
    assert get_backend("mlx").name == "mlx"


def test_importing_the_backend_imports_neither_mlx_nor_qt() -> None:
    script = ("import json, sys, helab.convert.backends.mlx_gpu, helab.convert.reconstruct as r; r.backends(); "
              "print(json.dumps([m for m in ('mlx', 'PyQt6', 'helab.utils.constants') if m in sys.modules]))")
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120,
                          env=dict(os.environ), cwd=ROOT)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout.splitlines()[-1]) == []


def test_off_apple_silicon_or_without_mlx_it_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    mlx_gpu._platform_unavailable.cache_clear()
    try:
        monkeypatch.setattr("sys.platform", "linux")
        reason = mlx_gpu._unavailable(MATLAB_2019)
        assert reason is not None and "Apple Silicon" in reason
        mlx_gpu._platform_unavailable.cache_clear()
        monkeypatch.setattr("sys.platform", "darwin")
        monkeypatch.setattr("platform.machine", lambda: "arm64")
        monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
        reason = mlx_gpu._unavailable(None)
        assert reason is not None and "isn't installed" in reason
    finally:
        mlx_gpu._platform_unavailable.cache_clear()


def test_a_profile_it_cant_run_is_refused() -> None:
    if REASON is not None:
        pytest.skip(f"mlx backend unavailable: {REASON}")
    assert mlx_gpu._unavailable(MATLAB_2019) is None
    assert mlx_gpu._unavailable(MATLAB_2023_LAB_EDIT) is None


@pytest.mark.parametrize("gpu", [pytest.param(True, marks=needs_gpu), False], ids=["gpu", "cpu"])
@pytest.mark.parametrize("variant", sorted(VARIANTS))
@pytest.mark.parametrize("case", case_names())
def test_each_case_matches_matlab_and_the_reference(case: str, variant: str, gpu: bool) -> None:
    folder = CASES / case
    profile = builtin_profile(VARIANTS[variant])
    pulses = parse_raw((folder / "d1.txt").read_bytes())
    ours = txy_or_error(pulses, profile, gpu)
    assert ours == txy_or_error(pulses, profile, None)
    expected = json.loads((folder / f"matlab-{variant}.json").read_text())["status"]
    if expected == "error":
        assert ours == b"error"
        return
    if not gpu:
        return
    result = convert_raw((folder / "d1.txt").read_bytes(), profile, "mlx")
    reference_path = folder / f"expected-{variant}.txt"
    check = check_txy(result, reference_path.read_bytes() if reference_path.exists() else None)
    assert check.identical, check.describe()


def sample_pairs() -> list[Path]:
    return [raw for raw in sorted((ROOT / "tests_sample_data").rglob("d[0-9]*.txt"))
            if raw.with_name(f"d_txy_forc{raw.stem[1:]}.txt").exists() and raw.parent.name != "bad_txy"]


@needs_gpu
@pytest.mark.parametrize("raw", sample_pairs(), ids=lambda path: f"{path.parent.name}/{path.name}")
def test_the_lab_converters_files_are_reproduced(raw: Path) -> None:
    reference = raw.with_name(f"d_txy_forc{raw.stem[1:]}.txt").read_bytes()
    result = check_txy(convert_raw(raw.read_bytes(), MATLAB_2019, "mlx"), reference)
    assert result.identical, result.describe()


# Fuzz: dense, overlapping hits with ringing, so that x1 rows compete for the same x2 and y
# pulses and the greedy pass has to recompute (and cascade).

def fuzz_pulses(seed: int, rows: int = 320) -> RawPulses:
    rng = np.random.default_rng(seed)
    channels: list[float] = [5.0]
    times: list[float] = [float(rng.integers(0, 10 ** 10))]
    base = times[0] + float(rng.integers(-5000, 5000))
    while len(times) < rows:
        base += float(rng.integers(0, 2500))
        u, v, e = (int(rng.integers(-1500, 1500)), int(rng.integers(-1500, 1500)), int(rng.integers(-600, 600)))
        group = [(0, base + 1600 + u), (1, base + 1600 - u), (2, base + 1600 + v + e), (3, base + 1600 - v)]
        for channel, time in list(group):
            if rng.random() < 0.25:                           # ringing: a second pulse nearby
                group.append((channel, time + float(rng.integers(1, 400))))
        if rng.random() < 0.3:
            group.append((int(rng.choice([4, 6, 7])), base + float(rng.integers(0, 3200))))
        keep = [item for item in group if rng.random() > 0.08]  # lost pulses
        for channel, time in keep:
            channels.append(float(channel))
            times.append(time)
    order = np.arange(len(times))
    swaps = rng.integers(0, len(times) - 1, size=len(times) // 10)  # a few out of order in the file
    order[swaps], order[swaps + 1] = order[swaps + 1], order[swaps].copy()
    return RawPulses(channels=np.array(channels)[order], times=np.array(times)[order])


FUZZ_PROFILES = {
    "2019": MATLAB_2019,
    "2023": MATLAB_2023_LAB_EDIT,
    "fractional-limits": MATLAB_2019.replace(search_window=3200.5, match_time_sum_x=3000.25, match_tolerance_y=150.5,
                                             xy_sum_tolerance=399.5, search_depth=11),
    "no-quirks": MATLAB_2019.replace(skip_first_sorted_row=False, subtract_time_zero=False, matlab_overflow_row=False,
                                     position_formula="raw"),
    "all-dead-times": MATLAB_2019.replace(dead_time_x1=2e-6, dead_time_x2=1e-6, dead_time_y1=3e-7, dead_time_y2=1e-8),
    "tiny-window": MATLAB_2019.replace(search_window=500.0, search_depth=4),
}


@pytest.mark.parametrize("name", sorted(FUZZ_PROFILES))
def test_dense_contested_streams_match_the_reference(name: str) -> None:
    profile = FUZZ_PROFILES[name]
    contested = changed = 0
    gpu = mlx_gpu._unavailable(profile) is None
    for seed in range(40):
        pulses = fuzz_pulses(seed)
        reference = txy_or_error(pulses, profile, None)
        assert txy_or_error(pulses, profile, False) == reference, f"cpu, seed {seed}"
        prep = mlx_gpu.prepare(pulses, profile)
        assert prep is not None
        first = mlx_gpu.first_choices_numpy(prep)
        if gpu:
            assert txy_or_error(pulses, profile, True) == reference, f"gpu, seed {seed}"
            assert_same_choices(mlx_gpu.first_choices_mlx(prep), first)
        final = mlx_gpu.resolve(prep, first)
        contested += int(np.count_nonzero(final.x2 != first.x2) + np.count_nonzero(final.y1 != first.y1))
        changed += int(np.count_nonzero((final.x2 != first.x2) | (final.y1 != first.y1) | (final.y2 != first.y2)))
    if name in ("2019", "fractional-limits", "no-quirks"):
        assert changed > 0, "the fuzz should make the greedy pass change some first choices"


def assert_same_choices(a: mlx_gpu.Choices, b: mlx_gpu.Choices) -> None:
    for column in ("x2", "y1", "y2"):
        np.testing.assert_array_equal(getattr(a, column), getattr(b, column), err_msg=column)


def with_rows(pulses: RawPulses, extra: list[tuple[float, float]], at: int) -> RawPulses:
    channels = list(pulses.channels)
    times = list(pulses.times)
    for k, (channel, time) in enumerate(extra):
        channels.insert(at + k, channel)
        times.insert(at + k, time)
    return RawPulses(channels=np.array(channels), times=np.array(times))


@pytest.mark.parametrize("gpu", [pytest.param(True, marks=needs_gpu), False], ids=["gpu", "cpu"])
@pytest.mark.parametrize("odd", ["nan", "inf", "-inf", "fraction", "huge"])
def test_odd_times_match_the_reference(odd: str, gpu: bool) -> None:
    """NaN and infinite times never match (code 0); a time with a fraction or past 2^50 sends
    the shot to the reference."""
    value = {"nan": np.nan, "inf": np.inf, "-inf": -np.inf, "fraction": 0.5, "huge": 2.0 ** 51}[odd]
    for seed in range(6):
        pulses = fuzz_pulses(100 + seed, rows=120)
        extra = [(0.0, float(pulses.times[5]) + value), (2.0, value), (1.0, float(pulses.times[9]) + 3)]
        for at in (0, 7, len(pulses.times)):
            odd_pulses = with_rows(pulses, extra, at)
            for profile in (MATLAB_2019, MATLAB_2023_LAB_EDIT):
                assert txy_or_error(odd_pulses, profile, gpu) == txy_or_error(odd_pulses, profile, None), (seed, at)


def test_a_fraction_or_a_huge_time_goes_to_the_reference_and_odd_rows_dont() -> None:
    pulses = fuzz_pulses(7, rows=60)
    for value, prepared in ((np.nan, True), (np.inf, True), (0.5, False), (2.0 ** 51, False)):
        odd = with_rows(pulses, [(1.0, float(pulses.times[3]) + value)], 4)
        assert (mlx_gpu.prepare(odd, MATLAB_2019) is not None) is prepared, value
    # Only corner rows count: a fractional time on another channel changes nothing.
    other = with_rows(pulses, [(7.0, float(pulses.times[3]) + 0.5)], 4)
    assert mlx_gpu.prepare(other, MATLAB_2019) is not None
    wide = MATLAB_2019.replace(search_window=float(mlx_gpu.WINDOW_LIMIT))
    assert mlx_gpu.prepare(pulses, wide) is None
    assert txy_or_error(pulses, wide, False) == txy_or_error(pulses, wide, None)


def test_empty_and_tiny_files_match_the_reference() -> None:
    nothing = RawPulses(channels=np.array([]), times=np.array([]))
    assert txy_or_error(nothing, MATLAB_2019, False) == b"error"
    no_zero = MATLAB_2019.replace(subtract_time_zero=False)
    assert txy_or_error(nothing, no_zero, False) == txy_or_error(nothing, no_zero, None) == b""
    for rows in ([(5.0, 10.0)], [(0.0, 10.0)], [(5.0, 1.0), (0.0, 10.0), (1.0, 20.0)]):
        pulses = RawPulses(channels=np.array([r[0] for r in rows]), times=np.array([r[1] for r in rows]))
        for profile in (MATLAB_2019, MATLAB_2023_LAB_EDIT, no_zero):
            assert txy_or_error(pulses, profile, False) == txy_or_error(pulses, profile, None)


def test_a_search_depth_of_one_matches_the_reference() -> None:
    profile = MATLAB_2019.replace(search_depth=1)
    pulses = fuzz_pulses(3, rows=80)
    assert txy_or_error(pulses, profile, False) == txy_or_error(pulses, profile, None)
    if mlx_gpu._unavailable(profile) is None:
        assert txy_or_error(pulses, profile, True) == txy_or_error(pulses, profile, None)


def test_the_integer_dead_time_cut_is_uniquetols() -> None:
    rng = np.random.default_rng(1)
    for _ in range(200):
        values = np.sort(rng.integers(0, 200_000, size=int(rng.integers(0, 60)))).astype(np.int64)
        tolerance = int(rng.integers(0, 30_000))
        ours = mlx_gpu._dead_time_keep(values, tolerance).tolist()
        assert ours == uniquetol_keep([float(v) for v in values], float(tolerance))


def test_integer_limits_are_the_float_tests() -> None:
    limits = mlx_gpu.limits_of(MATLAB_2019.replace(search_window=3200.5, match_time_sum_x=3000.0,
                                                   match_tolerance_x=0.25, xy_sum_tolerance=0.0))
    assert limits.window == 3200        # not |d| > 3200.5
    assert limits.x2 == 3000            # |d| < 3000.25
    assert limits.xy == -1              # |d| < 0: never
    assert mlx_gpu.limits_of(MATLAB_2019) == mlx_gpu.Limits(window=3200, x2=3399, y=3399, xy=399)
    huge = mlx_gpu.limits_of(MATLAB_2019.replace(xy_sum_tolerance=1e300))
    assert huge.xy == 4 * mlx_gpu.CLAMP


@needs_gpu
def test_threads_give_the_same_bytes() -> None:
    """MLX is called from several threads at once (the timing harness's thread mode)."""
    shots = [fuzz_pulses(seed, rows=2000) for seed in range(12)]
    expected = [format_txy(reconstruct(p, MATLAB_2019, "mlx")) for p in shots]
    with ThreadPoolExecutor(4) as pool:
        got: list[Any] = list(pool.map(lambda p: format_txy(reconstruct(p, MATLAB_2019, "mlx")), shots * 2))
    assert got == expected * 2


def _ints(values: list[int]) -> npt.NDArray[np.int64]:
    return np.array(values, dtype=np.int64)


def test_a_contested_x2_is_recomputed_in_order() -> None:
    """Two x1 share one x2 candidate: the first takes it with its y pair, so the second falls
    back to its next x2 (here with a y pair of its own), as MATLAB's marks make it."""
    # trigger; x1 a, x1 b, shared x2, b's other x2, y pairs for each.
    rows = [(5, 0), (0, 10000), (0, 10100), (1, 13000), (2, 11500), (3, 11700), (1, 13300), (2, 11600),
            (3, 11850)]
    pulses = RawPulses(channels=np.array([float(c) for c, _ in rows]), times=np.array([float(t) for _, t in rows]))
    reference = txy_or_error(pulses, MATLAB_2019, None)
    assert reference.count(b"\n") == 2
    assert txy_or_error(pulses, MATLAB_2019, False) == reference
    prep = mlx_gpu.prepare(pulses, MATLAB_2019)
    assert prep is not None
    first = mlx_gpu.first_choices_numpy(prep)
    final = mlx_gpu.resolve(prep, first)
    assert final.x2.tolist() != first.x2.tolist() or final.y1.tolist() != first.y1.tolist()
    np.testing.assert_array_equal(prep.x1_rows, _ints([1, 2]))
