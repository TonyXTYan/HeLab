"""The numba backend gives the reference's output byte for byte (``helab.convert.backends.numba_backend``).

The same cases as ``test_convert_reference.py`` (MATLAB's own output), every profile field
perturbed, random pulse streams, and one shot cut into pieces (serially, on threads and with
``prange``) against the whole. Skipped, with the reason, where numba can't be imported; the test
that HeLab works without numba runs everywhere.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import dataclasses
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Iterator

import numpy as np
import numpy.typing as npt
import pytest

from helab.convert.backends.numba_backend import (Within, import_problem, piece_bounds, reconstruct_numba,
                                                  reconstruct_numba_pieces)
from helab.convert.check import check_txy
from helab.convert.pipeline import convert_raw
from helab.convert.profile import DESCRIPTIVE, MATLAB_2019, DetectorProfile, builtin_profile
from helab.convert.raw import RawPulses, parse_raw
from helab.convert.reconstruct import NoRowsError, available_backends, get_backend, reconstruct

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "data" / "convert" / "cases"
VARIANTS = {"2019": "matlab-2019", "2023": "matlab-2023-lab-edit"}
PROBLEM = import_problem()
needs_numba = pytest.mark.skipif(PROBLEM is not None, reason=f"the numba backend can't run here: {PROBLEM}")


def case_names() -> list[str]:
    return sorted(path.name for path in CASES.iterdir() if path.is_dir())


def outcome(data: bytes, profile: DetectorProfile, backend: str) -> bytes | str | None:
    try:
        return convert_raw(data, profile, backend)
    except NoRowsError:
        return "error"


def test_helab_works_without_numba() -> None:
    # numba blocked: the backend is listed, says why it can't run, and the reference still converts.
    script = """
import sys
sys.modules["numba"] = None
from helab.convert.profile import MATLAB_2019
from helab.convert.raw import parse_raw
from helab.convert.reconstruct import BackendError, available_backends, backends, get_backend, reconstruct
assert "numba" in backends() and "numba" not in available_backends(MATLAB_2019)
reason = get_backend("numba").unavailable(MATLAB_2019)
assert reason and "numba" in reason, reason
try:
    reconstruct(parse_raw(b"5,1\\r\\n"), MATLAB_2019, "numba")
except BackendError as error:
    assert "can't run" in str(error)
else:
    raise AssertionError("ran without numba")
assert reconstruct(parse_raw(b"5,1\\r\\n"), MATLAB_2019).shape == (0, 3)
print("ok")
"""
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120,
                          env=dict(os.environ), cwd=ROOT)
    assert done.returncode == 0 and done.stdout.strip() == "ok", done.stderr


def test_registering_the_backend_imports_no_numba_or_heavy_module() -> None:
    script = """
import json, sys
from helab.convert.reconstruct import backends
backends()
print(json.dumps(sorted(name for name in ("numba", "llvmlite", "PyQt6", "matplotlib", "helab.utils.constants")
                        if name in sys.modules)))
"""
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120,
                          env=dict(os.environ), cwd=ROOT)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout.splitlines()[-1]) == []


@needs_numba
def test_the_backend_is_available_and_releases_the_gil() -> None:
    backend = get_backend("numba")
    assert backend.releases_gil and "numba" in available_backends(MATLAB_2019)
    assert backend.unavailable(builtin_profile("matlab-2023-lab-edit")) is None


@needs_numba
@pytest.mark.parametrize("variant", sorted(VARIANTS))
@pytest.mark.parametrize("case", case_names())
def test_each_case_matches_matlab(case: str, variant: str) -> None:
    folder = CASES / case
    expected = json.loads((folder / f"matlab-{variant}.json").read_text())["status"]
    ours = outcome((folder / "d1.txt").read_bytes(), builtin_profile(VARIANTS[variant]), "numba")
    assert ("error" if ours == "error" else "nofile" if ours is None else "file") == expected
    reference_path = folder / f"expected-{variant}.txt"
    reference = reference_path.read_bytes() if reference_path.exists() else None
    result = check_txy(ours if isinstance(ours, bytes) else None, reference)
    assert result.identical, result.describe()


def sample_pairs() -> list[Path]:
    return [raw for raw in sorted((ROOT / "tests_sample_data").rglob("d[0-9]*.txt"))
            if raw.with_name(f"d_txy_forc{raw.stem[1:]}.txt").exists() and raw.parent.name != "bad_txy"]


@needs_numba
@pytest.mark.parametrize("raw", sample_pairs(), ids=lambda path: f"{path.parent.name}/{path.name}")
def test_the_lab_converters_files_are_reproduced(raw: Path) -> None:
    reference = raw.with_name(f"d_txy_forc{raw.stem[1:]}.txt").read_bytes()
    result = check_txy(convert_raw(raw.read_bytes(), MATLAB_2019, "numba"), reference)
    assert result.identical, result.describe()


def _perturbed(name: str, value: object) -> object:
    # As test_convert_profile's perturbation, plus a narrow window so more pieces are cut.
    if isinstance(value, bool):
        return not value
    if name.startswith("channel_"):
        return 7
    if isinstance(value, int):
        return value - 7
    if isinstance(value, float):
        return value * 1.5 + 1e-6 if name.startswith(("dead_time", "bin_time", "v_perp")) else value * 0.6 + 1
    options = {"position_formula": ("centred", "raw")}.get(name, ())
    return next((option for option in options if option != value), None)


def _case_inputs() -> Iterator[bytes]:
    for case in case_names():
        data = (CASES / case / "d1.txt").read_bytes()
        # Times with a fraction too, so position_formula's rounding shows.
        yield data
        yield data.replace(b"\r\n", b".3\r\n")


@needs_numba
@pytest.mark.parametrize("name", [field.name for field in dataclasses.fields(DetectorProfile)
                                  if field.name not in DESCRIPTIVE] + ["v_perp_negative"])  # signed zeros
@pytest.mark.parametrize("base", sorted(VARIANTS.values()))
def test_every_profile_field_is_followed(name: str, base: str) -> None:
    profile = builtin_profile(base)
    if name == "v_perp_negative":
        profile = profile.replace(v_perp_x=-profile.v_perp_x, v_perp_y=-profile.v_perp_y)
    else:
        changed = _perturbed(name, getattr(profile, name))
        if changed is None:
            pytest.skip(f"{name} has one allowed value")
        profile = profile.replace(**{name: changed})
    for data in _case_inputs():
        assert outcome(data, profile, "numba") == outcome(data, profile, "reference")


def random_pulses(rng: np.random.Generator, hits: int, noise: int) -> RawPulses:
    """Hits made of four corners near each other (some with a partner missing or doubled), noise
    on every channel, clusters with gaps between them, a few NaN, Inf and repeated times."""
    rows: list[tuple[float, float]] = [(5.0, float(rng.integers(0, 2000)))]
    t = 1000.0
    for _ in range(hits):
        t += float(rng.choice([rng.integers(0, 3000), rng.integers(3000, 40000)]))
        x = float(rng.integers(-1800, 1800))
        y = float(rng.integers(-1800, 1800))
        corners = [(0.0, t - x / 2), (1.0, t + x / 2), (2.0, t - y / 2), (3.0, t + y / 2)]
        for channel, time in corners:
            if rng.random() < 0.1:
                continue
            rows.append((channel, time + 1600 + float(rng.integers(-150, 150))))
            if rng.random() < 0.08:
                rows.append((channel, time + 1600 + float(rng.integers(-1500, 1500))))
    for _ in range(noise):
        rows.append((float(rng.integers(0, 8)), float(rng.uniform(0, t + 5000)) // 1))
    order = rng.permutation(len(rows))
    channels = np.array([rows[k][0] for k in order], dtype=np.float64)
    times = np.array([rows[k][1] for k in order], dtype=np.float64)
    if len(times) > 3:
        times[0] = rows[0][1]
        channels[0] = 5.0
    specials = [np.nan, np.inf, -np.inf, -0.0, 0.0]
    for _ in range(int(rng.integers(0, 4))):
        times[int(rng.integers(0, len(times)))] = float(rng.choice(specials))
    for _ in range(int(rng.integers(0, 3))):
        channels[int(rng.integers(0, len(channels)))] = np.nan
    for _ in range(int(rng.integers(0, 6))):
        a, b = rng.integers(0, len(times), 2)
        times[a] = times[b]
    return RawPulses(channels, times)


def _same(a: npt.NDArray[np.float64], b: npt.NDArray[np.float64]) -> bool:
    # Bit for bit (signed zeros and NaN payloads included), and the same shape.
    return a.shape == b.shape and a.tobytes() == b.tobytes()


@needs_numba
@pytest.mark.parametrize("seed", range(40))
def test_random_pulse_streams_match_the_reference_whole_and_in_pieces(seed: int) -> None:
    rng = np.random.default_rng(seed)
    pulses = random_pulses(rng, hits=int(rng.integers(0, 300)), noise=int(rng.integers(0, 200)))
    for profile in (MATLAB_2019, builtin_profile("matlab-2023-lab-edit"),
                    MATLAB_2019.replace(search_depth=8, search_window=900.0, matlab_overflow_row=bool(seed % 2)),
                    MATLAB_2019.replace(skip_first_sorted_row=False, subtract_time_zero=bool(seed % 3))):
        reference = reconstruct(pulses, profile, "reference")
        assert _same(reconstruct(pulses, profile, "numba"), reference)
        for pieces in (2, 7, 50):
            assert _same(reconstruct_numba_pieces(pulses, profile, pieces, "serial"), reference)
        assert _same(reconstruct_numba_pieces(pulses, profile, 7, "prange"), reference)


@needs_numba
@pytest.mark.parametrize("within", ["serial", "threads", "prange"])
@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_a_shot_cut_into_pieces_equals_the_whole(variant: str, within: Within) -> None:
    profile = builtin_profile(VARIANTS[variant])
    cut = set()
    with ThreadPoolExecutor(4) as pool:
        for case in case_names():
            pulses = parse_raw((CASES / case / "d1.txt").read_bytes())
            try:
                whole = reconstruct(pulses, profile, "reference")
            except NoRowsError:
                continue
            for pieces in (2, 3, 5, 1000):
                assert _same(reconstruct_numba_pieces(pulses, profile, pieces, within, pool), whole), (case, pieces)
                if piece_bounds(pulses, profile, pieces).shape[0] > 2:
                    cut.add(case)
    # A10.2: the phantom cases and the dead-time case are really split.
    assert {"phantom_after_hit", "phantom_multi", "phantom_multi_cut", "phantom_none", "dead_time_x1"} <= cut


@needs_numba
def test_pieces_are_cut_only_at_gaps_longer_than_the_window() -> None:
    times = np.array([0, 10, 3210, 3211, 6411, 6412, np.nan, np.inf], dtype=np.float64)
    pulses = RawPulses(np.zeros(len(times)), times)
    profile = MATLAB_2019.replace(subtract_time_zero=False)
    # 3210 − 10 = 3200 is not more than the window, nor 6411 − 3211; Inf and NaN (sorted last) are
    # never cut at.
    assert piece_bounds(pulses, profile, 8).tolist() == [0, 8]
    times[2] = 3211.0
    assert piece_bounds(pulses, profile, 8).tolist() == [0, 2, 8]
    assert piece_bounds(pulses, profile, 1).tolist() == [0, 8]


@needs_numba
def test_threads_converting_different_shots_agree_with_serial() -> None:
    inputs = [parse_raw(path.read_bytes()) for path in sample_pairs()]
    serial = [reconstruct_numba(pulses, MATLAB_2019) for pulses in inputs]
    with ThreadPoolExecutor(4) as pool:
        threaded = list(pool.map(lambda pulses: reconstruct_numba(pulses, MATLAB_2019), inputs * 3))
    assert all(_same(a, b) for a, b in zip(serial * 3, threaded))


@needs_numba
def test_no_rows_is_matlabs_error_and_a_lone_trigger_no_hits() -> None:
    with pytest.raises(NoRowsError):
        reconstruct(parse_raw(b""), MATLAB_2019, "numba")
    with pytest.raises(NoRowsError):
        reconstruct_numba_pieces(parse_raw(b""), MATLAB_2019, 4)
    assert reconstruct(parse_raw(b""), MATLAB_2019.replace(subtract_time_zero=False), "numba").shape == (0, 3)
    assert reconstruct(parse_raw(b"5,100\r\n"), MATLAB_2019, "numba").shape == (0, 3)
    assert convert_raw(b"5,100\r\n", builtin_profile("matlab-2023-lab-edit"), "numba") == b""
