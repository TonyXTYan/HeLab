"""The converter on HeLab's test data (the private Hugging Face dataset ``TonyXTYan/HeLab-TestData``,
tag ``TESTDATA_TAG``): every era's raw files give MATLAB's archived TXY byte for byte with
``matlab-2019``, and ``reference/matlab-2023``'s with ``matlab-2023-lab-edit``, by numpy and by cython
where it's built.

The data is the ``testdata`` submodule when checked out (``git submodule update --init --checkout
testdata``, with access to the dataset), or ``HELAB_TESTDATA``, a download of that tag (``hf download
TonyXTYan/HeLab-TestData --type dataset --revision v1 --local-dir <folder>``; CI downloads it with a
read-only token), which wins. Without either these tests skip, unless ``HELAB_REQUIRE_TESTDATA=1`` (CI,
where the token is there), which fails them instead. They only read the files, checked against the set's
manifest first.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from helab.convert.pipeline import convert_raw
from helab.convert.profile import MATLAB_2019, MATLAB_2023_LAB_EDIT, DetectorProfile
from helab.convert.reconstruct import NoRowsError, get_backend

TESTDATA_TAG = "v1"  # the dataset's tag CI downloads (.github/workflows/ci-test.yml)
BACKENDS = ["numpy", "cython"]

# Archived TXY that aren't the 2019 converter's output for their raw file as it is now, each with
# why (the sample set's own are proved in dev/txy/reference_exceptions.py). A listed shot must still
# differ, so a changed file or converter shows here.
FAULTS = {
    ("eras/2022-07-old-plates-he3he4", 2): "re-converted 2023-02-08 by a MATLAB variant with a 2 us x1 dead time",
    ("eras/2022-07-old-plates-he3he4", 3): "re-converted 2023-02-08 by a MATLAB variant with a 2 us x1 dead time",
    ("nested/tight-trap/20260722-tight-trap-1000Hzsampling", 183):
        "the archived TXY lost bytes: line 465 holds 4 values, and 7 hits are missing",
}


SUBMODULE = Path(__file__).resolve().parent.parent / "testdata"


def find_testdata() -> Path | None:
    """The test data's folder: ``HELAB_TESTDATA``, else the checked-out submodule; None (and the tests
    skip) without either, unless ``HELAB_REQUIRE_TESTDATA`` makes that an error."""
    folder = os.environ.get("HELAB_TESTDATA", "")
    if folder:
        return Path(folder)
    if (SUBMODULE / "manifest.json").is_file():
        return SUBMODULE
    if os.environ.get("HELAB_REQUIRE_TESTDATA") == "1":
        raise RuntimeError("HELAB_REQUIRE_TESTDATA=1 but there's no test data (HELAB_TESTDATA, or the testdata "
                           "submodule)")
    return None


DATA = find_testdata()
needs_data = pytest.mark.skipif(DATA is None,
                                reason="no test data: the testdata submodule or HELAB_TESTDATA (this file's docstring)")


def pairs(base: Path) -> list[tuple[str, int]]:
    """(folder below ``base``, shot) of every raw file with MATLAB's TXY beside it."""
    found = []
    for txy in sorted(base.rglob("d_txy_forc*.txt")):
        shot = int(txy.name[len("d_txy_forc"):-len(".txt")])
        if (txy.parent / f"d{shot}.txt").is_file():
            found.append((txy.parent.relative_to(base).as_posix(), shot))
    return found


def converted(raw: Path, profile: DetectorProfile, backend: str) -> bytes:
    """The shot's TXY as MATLAB's wrapper leaves it: empty for no hits."""
    if (why := get_backend(backend).unavailable(None)) is not None:
        pytest.skip(f"{backend}: {why}")
    try:
        return convert_raw(raw.read_bytes(), profile, backend) or b""
    except NoRowsError:
        return b""


@needs_data
def test_the_data_matches_its_manifest() -> None:
    assert DATA is not None
    manifest = json.loads((DATA / "manifest.json").read_text())
    for name, sha256 in manifest["sha256"].items():
        path = DATA / name if name.startswith("reference/") else DATA / "data" / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sha256, name
    listed = set(manifest["sha256"])
    on_disk = {path.relative_to(DATA / "data").as_posix() for path in (DATA / "data").rglob("*") if path.is_file()}
    assert on_disk <= listed


@needs_data
@pytest.mark.parametrize("backend", BACKENDS)
def test_matlab_2019_gives_every_era_byte_for_byte(backend: str) -> None:
    assert DATA is not None
    base = DATA / "data"
    found = pairs(base)
    assert len(found) == 56  # 9 eras (5 shots each, 10 of the ghost counts) and the nested folder's 6
    wrong = []
    for folder, shot in found:
        same = converted(base / folder / f"d{shot}.txt", MATLAB_2019, backend) == \
            (base / folder / f"d_txy_forc{shot}.txt").read_bytes()
        if same == ((folder, shot) in FAULTS):
            wrong.append(f"{folder} {shot}: " + (f"listed ({FAULTS[(folder, shot)]}) but identical" if same
                                                  else "differs"))
    assert not wrong, "\n".join(wrong)


@needs_data
@pytest.mark.parametrize("backend", BACKENDS)
def test_matlab_2023_lab_edit_gives_its_reference_byte_for_byte(backend: str) -> None:
    assert DATA is not None
    base = DATA / "reference" / "matlab-2023"
    found = pairs(base)
    assert len(found) == 32
    wrong = [f"{folder} {shot}" for folder, shot in found
             if converted(base / folder / f"d{shot}.txt", MATLAB_2023_LAB_EDIT, backend)
             != (base / folder / f"d_txy_forc{shot}.txt").read_bytes()]
    assert not wrong, "differ: " + ", ".join(wrong)
