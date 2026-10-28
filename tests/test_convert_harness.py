"""The converter's harness: the sample manifest, the byte checker and the timing harness.

Never the real sample set: each test writes its own manifest and files.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from helab.convert.check import check_txy
from helab.convert.profile import MATLAB_2019, builtin_profile
from helab.convert.samples import SampleError, load_manifest, read_verified, select_shots
from helab.convert.timing import Parallelism, ShotJob, summarise, time_shot, time_shots

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "tests" / "data" / "convert" / "cases" / "basic"


def make_samples(folder: Path, shots: int = 5) -> Path:
    raw = (CASE / "d1.txt").read_bytes()
    txy = (CASE / "expected-2019.txt").read_bytes()
    entries = []
    (folder / "set-a").mkdir(parents=True)
    for shot in range(1, shots + 1):
        (folder / "set-a" / f"d{shot}.txt").write_bytes(raw)
        (folder / "set-a" / f"d_txy_forc{shot}.txt").write_bytes(txy)
        entries.append({"shot": shot, "raw_sha256": hashlib.sha256(raw).hexdigest(),
                        "txy_sha256": hashlib.sha256(txy).hexdigest(), "raw_bytes": len(raw)})
    manifest = {"source_share": "none", "sets": {"set-a": {"source": "synthetic", "shots_in_source": shots,
                                                          "shots": entries}}}
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return folder


def test_the_manifest_gives_shots_split_into_held_in_and_held_out(tmp_path: Path) -> None:
    sets = load_manifest(make_samples(tmp_path / "samples"))
    assert [s.name for s in sets] == ["set-a"]
    assert [shot.shot for shot in select_shots(sets, "even")] == [1, 3, 5]
    assert [shot.shot for shot in select_shots(sets, "odd")] == [2, 4]
    assert len(select_shots(sets, "all")) == 5 and select_shots(sets, "all", ["other"]) == []
    shot = sets[0].shots[1]
    assert shot.label == "set-a/d2" and shot.raw_path.name == "d2.txt" and shot.txy_path.name == "d_txy_forc2.txt"
    assert read_verified(shot.raw_path, shot.raw_sha256) == (CASE / "d1.txt").read_bytes()


def test_a_file_that_isnt_the_manifests_is_refused(tmp_path: Path) -> None:
    shot = load_manifest(make_samples(tmp_path / "samples"))[0].shots[0]
    shot.raw_path.write_bytes(b"5,1\r\n")
    with pytest.raises(SampleError, match="SHA-256"):
        read_verified(shot.raw_path, shot.raw_sha256)
    with pytest.raises(SampleError):
        load_manifest(tmp_path / "nowhere")
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "manifest.json").write_text('{"sets": {"x": {}}}')
    with pytest.raises(SampleError):
        load_manifest(tmp_path / "bad")


def test_the_checker_names_the_first_differing_line_and_the_hit_counts() -> None:
    assert check_txy(b"1,2,3\n4,5,6\n", b"1,2,3\n4,5,6\n").identical
    result = check_txy(b"1,2,3\n4,5,6\n7,8,9\n", b"1,2,3\n4,5,7\n")
    assert (result.identical, result.line, result.ours_line, result.reference_line) == (False, 2, "4,5,6", "4,5,7")
    assert (result.ours_hits, result.reference_hits) == (3, 2)
    assert "line 2" in result.describe()
    longer = check_txy(b"1,2,3\n4,5,6\n", b"1,2,3\n")
    assert (longer.line, longer.ours_line, longer.reference_line) == (2, "4,5,6", "")
    no_newline = check_txy(b"1,2,3\n", b"1,2,3")
    assert not no_newline.identical and no_newline.reference_hits == 1
    assert check_txy(None, None).identical
    missing = check_txy(b"", None)
    assert not missing.identical and missing.describe() == "differs: ours 0 hits, reference no file"


@pytest.mark.parametrize("parallelism", [Parallelism.SERIAL, Parallelism.THREADS, Parallelism.PROCESSES])
def test_timing_runs_each_stage_and_writes_the_txy(tmp_path: Path, parallelism: Parallelism) -> None:
    out = tmp_path / "out"
    out.mkdir()
    jobs = [ShotJob(f"basic/{k}", CASE / "d1.txt", out / f"d_txy_helab_{k}.txy") for k in range(3)]
    timings = time_shots(jobs, MATLAB_2019, parallelism=parallelism, workers=2)
    assert [timing.label for timing in timings] == [job.label for job in jobs]
    for job, timing in zip(jobs, timings):
        assert job.txy_path.read_bytes() == (CASE / "expected-2019.txt").read_bytes()
        assert timing.hits == 5 and timing.raw_bytes == (CASE / "d1.txt").stat().st_size
        assert min(timing.read, timing.reconstruct, timing.write) >= 0 and timing.total > 0
    summary = summarise(timings, wall=1.0)
    assert (summary.shots, summary.hits, summary.raw_bytes) == (3, 15, 3 * timings[0].raw_bytes)
    assert summary.mb_per_s(1.0) == summary.raw_bytes / 1e6


def test_timing_follows_matlab_for_empty_files_and_results(tmp_path: Path) -> None:
    empty = tmp_path / "d1.txt"
    empty.write_bytes(b"")
    trigger = tmp_path / "d2.txt"
    trigger.write_bytes(b"5,100\r\n")
    out = tmp_path / "out"
    out.mkdir()
    failed = time_shot(ShotJob("empty", empty, out / "a.txy"), MATLAB_2019)
    assert failed.hits is None and not (out / "a.txy").exists()
    assert time_shot(ShotJob("trigger", trigger, out / "b.txy"), MATLAB_2019).hits == 0
    assert not (out / "b.txy").exists()
    time_shot(ShotJob("trigger", trigger, out / "c.txy"), builtin_profile("matlab-2023-lab-edit"))
    assert (out / "c.txy").read_bytes() == b""
    with pytest.raises(NotImplementedError):
        time_shots([ShotJob("x", trigger, out / "d.txy")], MATLAB_2019, parallelism=Parallelism.WITHIN_SHOT)
