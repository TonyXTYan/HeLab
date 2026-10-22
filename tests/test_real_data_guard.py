"""Tests never touch real data: under pytest, the I/O helper refuses source paths on mounted volumes and
shares, in cloud storage or in the developers' data folders, before touching them (tests/conftest.py,
``io_ops.infra._guard``). The paths here don't exist: a refusal is all that can happen to them."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from helab.io_ops import infra
from helab.utils.constants import DEV_POTENTIAL_DATA_PATHS

ON_WINDOWS = sys.platform == "win32"
MOUNTED = ["\\\\no-such-server\\share\\run_1"] if ON_WINDOWS else [
    "/Volumes/helab-no-such-share/run_1", "/mnt/helab-no-such-disk", "/net/no-such-server/data",
    "/media/helab-no-such-disk/run_1", os.path.expanduser("~/Library/CloudStorage/helab-no-such-drive/run_1")]


def taken_notes() -> list[str]:
    """The paths refused so far, which are then cleared (else the test fails, as it should for
    paths a test didn't mean to ask for)."""
    refused: list[str] = []
    for note in Path(os.environ["HELAB_TEST_SOURCE_GUARD"]).glob("*.txt"):
        refused += note.read_text(encoding="utf-8").splitlines()
        note.unlink()
    return refused


@pytest.mark.parametrize("path", MOUNTED)
def test_mounted_volumes_and_shares_are_refused_untouched(path: str) -> None:
    for touch in (lambda: infra._stat(path, "test"), lambda: infra._lstat(path, "test"),
                  lambda: infra._isdir(path, "test"), lambda: infra._scandir(path, "test"),
                  lambda: infra._read_txy_file(os.path.join(path, "d_1.txt"), "test"),
                  lambda: infra._read_marker(path, "test")):
        with pytest.raises(infra.SourceRefused):
            touch()
    assert set(taken_notes()) == {path, os.path.join(path, "d_1.txt")}


def test_the_developers_data_folders_are_refused() -> None:
    _, denied, _ = infra._guard_rules()
    data = [path for path in DEV_POTENTIAL_DATA_PATHS if path and infra._normal(path) in denied]
    assert data, "the data folders outside this checkout and the temp folder"
    for path in data:
        with pytest.raises(infra.SourceRefused):
            infra._guard(os.path.join(path, "run_1"))
    assert len(taken_notes()) == len(data)


@pytest.mark.parametrize("path", DEV_POTENTIAL_DATA_PATHS, ids=[str(i) for i in range(len(DEV_POTENTIAL_DATA_PATHS))])
def test_each_listed_data_folder_is_a_path_and_guarded(path: str) -> None:
    """Every entry of the developers' data folders is a path of its own (a missing comma would fuse
    two), and a folder inside it is refused, unless it is in the temp folder or this checkout."""
    assert path
    allowed, _, _ = infra._guard_rules()
    if any(infra._within(infra._normal(path), folder) for folder in allowed):
        return
    with pytest.raises(infra.SourceRefused):
        infra._guard(os.path.join(path, "run_1"))
    assert taken_notes() == [os.path.join(path, "run_1")]


def test_test_folders_and_the_way_to_them_are_allowed(tmp_path: Path) -> None:
    checkout = Path(__file__).resolve().parents[1]
    for path in (tmp_path, tmp_path / "run_1", checkout / "tests_sample_data", Path(tmp_path.anchor)):
        infra._guard(str(path))
    if not ON_WINDOWS:
        infra._guard("/Volumes")  # The list of mounts, not one of them
    assert infra._isdir(str(tmp_path), "test") and not taken_notes()


def test_a_helper_refuses_a_request_on_a_share_before_any_work() -> None:
    path = MOUNTED[0]
    for operation in ("list", "load", "root_create"):
        request = {"operation": operation, "path": path, "output": "", "cache": None}
        done = subprocess.run([sys.executable, "-m", "helab.io_helper"], input=json.dumps(request) + "\n",
                              capture_output=True, text=True, timeout=60, env=os.environ.copy())
        events = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
        assert events and events[-1]["kind"] == "error", done.stdout + done.stderr
        assert "Tests never touch real data" in events[-1]["message"]
    assert set(taken_notes()) == {path}
