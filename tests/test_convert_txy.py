"""TXY text is written as MATLAB's dlmwrite precision 8 writes it (``helab.convert.txy``)."""
from __future__ import annotations

import math
import os
from pathlib import Path
import stat

import numpy as np
import pytest

from helab.convert.txy import format_txy, format_txy_by_value, write_atomic, write_txy


def test_values_format_as_dlmwrite_precision_8() -> None:
    # Measured with MATLAB R2025b: dlmwrite('w.txt', M, 'precision', 8).
    hits = np.array([[-0.0, 0.0, math.nan], [math.inf, -math.inf, 1e-5], [123456789, 0.1, 1e21],
                     [1e-300, 5e-324, -277.01834], [0.5, 1.25e-5, 99999999.5], [2.0 ** 53, -1e-7, 1e16]])
    assert format_txy(hits) == (
        b"-0,0,NaN\nInf,-Inf,1e-05\n1.2345679e+08,0.1,1e+21\n1e-300,4.9406565e-324,-277.01834\n"
        b"0.5,1.25e-05,1e+08\n9.0071993e+15,-1e-07,1e+16\n")


def test_no_hits_give_an_empty_file(tmp_path: Path) -> None:
    assert format_txy(np.zeros((0, 3))) == b""
    write_txy(tmp_path / "d_txy_helab_1.txy", np.zeros((0, 3)))
    assert (tmp_path / "d_txy_helab_1.txy").read_bytes() == b""


def test_hits_must_be_three_columns() -> None:
    with pytest.raises(ValueError):
        format_txy(np.zeros((2, 2)))
    with pytest.raises(ValueError):
        format_txy(np.zeros(3))


@pytest.mark.parametrize("rows", [0, 1, 255, 256, 3000])
def test_hits_must_be_float64_at_every_size(rows: int) -> None:
    hits = np.random.default_rng(rows).uniform(-1, 1, (rows, 3))
    for wrong in (hits.astype(np.float32), (hits * 1000).astype(np.int64), hits.ravel()):
        with pytest.raises(ValueError):
            format_txy(wrong)
    # Any layout of float64 is fine: Fortran order and strided views give the same bytes.
    expected = format_txy_by_value(hits)
    assert format_txy(hits) == expected
    assert format_txy(np.asfortranarray(hits)) == expected
    doubled = np.repeat(hits, 2, axis=1)  # columns 0, 0, 1, 1, 2, 2
    assert format_txy(doubled[:, ::2]) == expected
    padded = np.zeros((2 * rows, 3))
    padded[::2] = hits
    assert format_txy(padded[::2]) == expected


def test_the_write_is_atomic_and_leaves_no_temporary(tmp_path: Path) -> None:
    tmp_path = tmp_path / "out"  # conftest's tmp_path holds a .helab-root
    tmp_path.mkdir()
    target = tmp_path / "d_txy_helab_1.txy"
    target.write_bytes(b"old")
    write_txy(target, np.array([[0.001, 0.002, -0.003]]))
    assert target.read_bytes() == b"0.001,0.002,-0.003\n"
    assert [path.name for path in tmp_path.iterdir()] == [target.name]


def test_a_failed_write_keeps_the_old_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path = tmp_path / "out"  # conftest's tmp_path holds a .helab-root
    tmp_path.mkdir()
    target = tmp_path / "d_txy_helab_1.txy"
    target.write_bytes(b"old")

    def fail(source: str, destination: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("helab.convert.txy.os.replace", fail)
    with pytest.raises(OSError):
        write_atomic(target, b"new")
    assert target.read_bytes() == b"old"
    assert [path.name for path in tmp_path.iterdir()] == [target.name]


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_a_written_txy_gets_a_plain_files_mode(tmp_path: Path) -> None:
    target = tmp_path / "d_txy_helab_1.txy"
    write_txy(target, np.array([[0.001, 0.002, -0.003]]))
    umask = os.umask(0o022)  # the only way to read it; restored at once
    os.umask(umask)
    assert stat.S_IMODE(target.stat().st_mode) == 0o666 & ~umask
