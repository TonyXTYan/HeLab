"""The NumPy backend gives the reference's output byte for byte (``helab.convert.backends.numpy_backend``).

The synthetic cases (``tests/data/convert/cases/``, with MATLAB's own output), ``tests_sample_data/``
and seeded random files dense enough that matches compete for pulses (the exact pass) and leave
phantom rows. Never the sample set (``compare_backends.py`` in the session folder does that).
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import json
import math
import multiprocessing
import os
from pathlib import Path
import random
import subprocess
import sys
from typing import Any

import pytest

np = pytest.importorskip("numpy", reason="the numpy backend needs NumPy")

from helab.convert.backends import numpy_backend  # noqa: E402
from helab.convert.backends.reference import uniquetol_keep  # noqa: E402
from helab.convert.check import check_txy  # noqa: E402
from helab.convert.pipeline import convert_raw  # noqa: E402
from helab.convert.profile import MATLAB_2019, MATLAB_2023_LAB_EDIT, DetectorProfile, builtin_profile  # noqa: E402
from helab.convert.raw import RawPulses, parse_raw  # noqa: E402
from helab.convert.reconstruct import NoRowsError, available_backends, get_backend, reconstruct  # noqa: E402
from helab.convert.split import reconstruct_split  # noqa: E402
from helab.convert.txy import format_txy  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "data" / "convert" / "cases"
VARIANTS = {"2019": "matlab-2019", "2023": "matlab-2023-lab-edit"}


def case_names() -> list[str]:
    return sorted(path.name for path in CASES.iterdir() if path.is_dir())


def converted(pulses: RawPulses, profile: DetectorProfile, backend: str) -> bytes | None:
    try:
        return format_txy(reconstruct(pulses, profile, backend))
    except NoRowsError:
        return None


def test_the_backend_is_registered_and_available() -> None:
    assert "numpy" in available_backends() and "numpy" in available_backends(MATLAB_2023_LAB_EDIT)
    assert get_backend("numpy").run is numpy_backend.reconstruct_numpy


def _convert_basic(profile_name: str) -> bytes | None:
    return convert_raw((CASES / "basic" / "d1.txt").read_bytes(), builtin_profile(profile_name), "numpy")


def test_a_spawned_worker_finds_the_backend() -> None:
    # A spawned process imports only what reconstruct._MODULES names.
    with ProcessPoolExecutor(1, mp_context=multiprocessing.get_context("spawn")) as pool:
        assert pool.submit(_convert_basic, "matlab-2019").result() == (CASES / "basic" / "expected-2019.txt").read_bytes()


@pytest.mark.parametrize("variant", sorted(VARIANTS))
@pytest.mark.parametrize("case", case_names())
def test_each_case_matches_matlab(case: str, variant: str) -> None:
    folder = CASES / case
    expected = json.loads((folder / f"matlab-{variant}.json").read_text())["status"]
    data = (folder / "d1.txt").read_bytes()
    try:
        ours = convert_raw(data, builtin_profile(VARIANTS[variant]), "numpy")
        status = "nofile" if ours is None else "file"
    except NoRowsError:
        ours, status = None, "error"
    assert status == expected
    reference_path = folder / f"expected-{variant}.txt"
    result = check_txy(ours, reference_path.read_bytes() if reference_path.exists() else None)
    assert result.identical, result.describe()


def sample_raws() -> list[Path]:
    return sorted((ROOT / "tests_sample_data").rglob("d[0-9]*.txt"))


@pytest.mark.parametrize("raw", sample_raws(), ids=lambda path: f"{path.parent.name}/{path.name}")
@pytest.mark.parametrize("profile", [MATLAB_2019, MATLAB_2023_LAB_EDIT], ids=lambda p: p.name)
def test_the_lab_files_convert_as_the_reference_does(raw: Path, profile: DetectorProfile) -> None:
    pulses = parse_raw(raw.read_bytes())
    assert converted(pulses, profile, "numpy") == converted(pulses, profile, "reference")


def test_no_rows_is_an_error_unless_time_zero_is_off() -> None:
    empty = RawPulses(np.empty(0), np.empty(0))
    with pytest.raises(NoRowsError):
        reconstruct(empty, MATLAB_2019, "numpy")
    assert reconstruct(empty, MATLAB_2019.replace(subtract_time_zero=False), "numpy").shape == (0, 3)


def test_uniquetol_matches_the_reference() -> None:
    nan, inf = math.nan, math.inf
    rng = random.Random(5)
    lists: list[list[float]] = [[0, 15000, 25000, 39000, 40001, 60001], [0, 10000, 20000, 30000, 40000, 50000],
             [0, 20000, 20000.0000001], [5, 5, 5, 20005, 20006], [0, 5, nan, nan], [], [3.0], [nan],
             [-inf, -inf, 0, 1, inf, inf, nan], [-inf, 5], [1e308, 1.7e308], [0.1 * k for k in range(50)]]
    lists += [sorted(rng.choice([rng.uniform(0, 1e5), float(rng.randrange(0, 60000, 500))]) for _ in range(200))
              for _ in range(30)]
    for values in lists:
        for tol in (0.0, 0.1, 20000.0, 0.5e-6 / 25e-12, 1e300, inf):
            got = numpy_backend.uniquetol_keep(np.array(values, dtype=np.float64), tol).tolist()
            assert got == uniquetol_keep([float(v) for v in values], tol), (values, tol)


def random_pulses(rng: random.Random) -> RawPulses:
    """A trigger, then hits (some missing a pulse or with a wrong y sum), lone x pairs and noise,
    shuffled; dense enough that x1s compete for pulses."""
    spread = rng.choice([2000.0, 2e4, 1e5, 1e7])
    rows: list[tuple[float, float]] = [(5.0, 1000.0)]
    for _ in range(rng.choice([0, 1, 3, 20, 200])):
        t0, x, y = rng.uniform(0, spread), rng.uniform(-1500, 1500), rng.uniform(-1500, 1500)
        for channel, time in ((0, t0 + 1600 + x), (1, t0 + 1600 - x), (2, t0 + 1600 + y + rng.choice([0, 0, 300])),
                              (3, t0 + 1600 - y)):
            if rng.random() < 0.95:
                rows.append((float(channel), float(round(time))))
    for _ in range(rng.choice([0, 1, 2])):
        t0, x = rng.uniform(0, spread), rng.uniform(-1500, 1500)
        rows += [(0.0, float(round(t0 + 1600 + x))), (1.0, float(round(t0 + 1600 - x)))]
    for _ in range(rng.choice([0, 0, 5, 50])):
        rows.append((float(rng.choice([0, 1, 2, 3, 4, 6])), float(round(rng.uniform(0, spread)))))
    rest = rows[1:]
    rng.shuffle(rest)
    rows = rows[:1] + rest
    if rng.random() < 0.1:
        rows.append((0.0, math.nan))
    values = np.array(rows, dtype=np.float64).reshape(-1, 2)
    return RawPulses(np.ascontiguousarray(values[:, 0]), np.ascontiguousarray(values[:, 1]))


def random_profile(rng: random.Random) -> DetectorProfile:
    profile = rng.choice([MATLAB_2019, MATLAB_2023_LAB_EDIT])
    changes: dict[str, object] = {}
    if rng.random() < 0.3:
        changes["search_depth"] = rng.choice([1, 2, 5, 50])
    if rng.random() < 0.2:
        changes["skip_first_sorted_row"] = False
    if rng.random() < 0.2:
        changes["subtract_time_zero"] = False
    if rng.random() < 0.2:
        changes["matlab_overflow_row"] = False
    if rng.random() < 0.3:
        changes[rng.choice(["dead_time_x1", "dead_time_x2", "dead_time_y1", "dead_time_y2"])] = rng.choice(
            [1e-9, 25e-9, 0.5e-6])
    if rng.random() < 0.2:
        changes["search_window"] = rng.choice([100.0, 5000.0])
    if rng.random() < 0.2:
        changes["xy_sum_tolerance"] = rng.choice([50.0, 4000.0])
    return profile.replace(**changes) if changes else profile


def test_random_dense_files_convert_as_the_reference_does(monkeypatch: pytest.MonkeyPatch) -> None:
    searched: list[int] = []
    phantoms: list[int] = []
    search_one, hits = numpy_backend._search_one, numpy_backend._hits

    def counting_search(*args: Any) -> tuple[int, int, int]:
        searched.append(1)
        return search_one(*args)

    def counting_hits(*args: Any) -> Any:
        out = hits(*args)
        if int((args[4] == numpy_backend.HIT).sum()) < out.shape[0]:  # args[4]: the outcomes
            phantoms.append(1)
        return out

    monkeypatch.setattr(numpy_backend, "_search_one", counting_search)
    monkeypatch.setattr(numpy_backend, "_hits", counting_hits)
    rng = random.Random(2026_10_29)
    for k in range(150):
        pulses, profile = random_pulses(rng), random_profile(rng)
        assert converted(pulses, profile, "numpy") == converted(pulses, profile, "reference"), (k, profile)
    # The exact pass ran (x1s competed for pulses) and phantom rows were made.
    assert len(searched) > 50 and phantoms


def test_small_chunks_change_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    pulses = parse_raw((CASES / "used_pulses" / "d1.txt").read_bytes())
    whole = converted(pulses, MATLAB_2019, "numpy")
    monkeypatch.setattr(numpy_backend, "CHUNK", 1)
    assert converted(pulses, MATLAB_2019, "numpy") == whole == converted(pulses, MATLAB_2019, "reference")


@pytest.mark.parametrize("backend", ["reference", "numpy"])
def test_random_files_split_equal_the_whole(backend: str) -> None:
    rng = random.Random(29)
    for k in range(60 if backend == "reference" else 150):
        pulses, profile = random_pulses(rng), random_profile(rng)
        split = reconstruct_split(pulses, profile, backend, min_rows=rng.choice([1, 3, 20])) if len(pulses) else None
        assert (None if split is None else format_txy(split)) == converted(pulses, profile, backend), (k, profile)


FIRST_USE = """
import sys, threading
from pathlib import Path
from helab.convert.pipeline import convert_raw
from helab.convert.profile import MATLAB_2019
from helab.convert.reconstruct import _BACKENDS
assert "numpy" not in _BACKENDS and "helab.convert.backends.numpy_backend" not in sys.modules
data = Path(sys.argv[1]).read_bytes()
barrier = threading.Barrier(32)
results, errors = [], []
def run():
    try:
        barrier.wait()
        results.append(convert_raw(data, MATLAB_2019, "numpy"))
    except BaseException as error:
        errors.append(repr(error))
threads = [threading.Thread(target=run) for _ in range(32)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
assert not errors, errors
assert len(results) == 32 and len(set(results)) == 1, len(set(results))
sys.stdout.buffer.write(results[0])
"""


def test_many_threads_using_the_backend_first_at_once_agree() -> None:
    # The backend is imported on first use (reconstruct._MODULES); 32 threads racing to it in a
    # fresh process must all get it, registered once, and the same bytes.
    done = subprocess.run([sys.executable, "-c", FIRST_USE, str(CASES / "basic" / "d1.txt")], capture_output=True,
                          timeout=120, env=dict(os.environ), cwd=ROOT)
    assert done.returncode == 0, done.stderr.decode()
    assert done.stdout == (CASES / "basic" / "expected-2019.txt").read_bytes()
