"""TXY files as the converter writes them, and as interrupted or foreign writes leave them.

A TXY file is rows of three comma-separated numbers (t, x, y). A load reads every settled file
(``helab/io_ops/loading.py``): rows with fewer numbers are dropped and their shot is marked
problematic; a file with longer rows or text can't be read and is counted as failed; either way
the folder's other shots load. A file must never load with its columns shifted.
"""
from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any

import numpy as np
import pandas as pd
import pytest

from helab.io_ops import infra
from helab.io_ops.loading import load

GOOD = b"0.1,0.002,0.003\n0.2,0.004,0.005\n"
GOOD_ROWS = [[0.1, 0.002, 0.003], [0.2, 0.004, 0.005]]


def txy(folder: Path, shot: int, content: bytes) -> str:
    file = folder / f"d_txy_forc{shot}.txt"
    file.write_bytes(content)
    when = time.time() - 60  # Settled.
    os.utime(file, (when, when))
    return str(file)


def rows(filename: str) -> list[list[float]]:
    frame = infra._read_txy_file(filename, "test")
    return [[float(value) for value in row] for row in frame.to_numpy()]


@pytest.mark.parametrize("content", [
    GOOD,
    b"0.1,0.002,0.003\n0.2,0.004,0.005",  # No newline at the end.
    b"0.1,0.002,0.003\r\n0.2,0.004,0.005\r\n",  # Windows line ends.
    b"0.1,0.002,0.003\n\n0.2,0.004,0.005\n",  # A blank line.
    b"\n0.1,0.002,0.003\n0.2,0.004,0.005\n",  # A blank first line.
    b"\xef\xbb\xbf0.1,0.002,0.003\n0.2,0.004,0.005\n",  # A byte-order mark.
    b"0.1, 0.002, 0.003\n0.2, 0.004, 0.005\n",  # Spaces after the commas.
    b"1.0E-01,2.0e-03,3e-3\n2e-1,4.0E-03,5.0e-03\n",  # Exponents.
    b"0.1,0.002,0.003\r0.2,0.004,0.005\r",  # Old Mac line ends.
], ids=["plain", "no final newline", "crlf", "blank line", "blank first line", "bom", "spaces", "exponents",
        "cr"])
def test_the_converters_files_read_the_same(tmp_path: Path, content: bytes) -> None:
    assert rows(txy(tmp_path, 1, content)) == GOOD_ROWS


def test_an_empty_file_is_a_shot_with_no_events(tmp_path: Path) -> None:
    assert rows(txy(tmp_path, 1, b"")) == []


def test_negative_numbers_read_as_they_are(tmp_path: Path) -> None:
    assert rows(txy(tmp_path, 1, b"0.1,-0.002,-0.003\n")) == [[0.1, -0.002, -0.003]]


@pytest.mark.parametrize("content", [
    b"0.1,0.002,0.003,1\n0.2,0.004,0.005,2\n",  # Four numbers a row: pandas would shift them.
    b"0.1,0.002,0.003\n0.2,0.004,0.005,9\n",  # A later row with four.
    b"t,x,y\n0.1,0.002,0.003\n",  # A header.
], ids=["four columns", "a longer row", "header"])
def test_a_file_with_longer_rows_or_text_is_unreadable(tmp_path: Path, content: bytes) -> None:
    with pytest.raises((ValueError, pd.errors.ParserError)):
        infra._read_txy_file(txy(tmp_path, 1, content), "test")


def loaded(folder: Path, tmp_path: Path) -> tuple[dict[int, np.ndarray[Any, Any]], dict[str, Any]]:
    """Load ``folder`` with no disk cache: each shot's events, and the ``loaded`` event."""
    output = tmp_path / f"out-{time.monotonic_ns()}"
    output.mkdir()
    events: list[Any] = []
    load(str(folder), str(output), events.append, {})
    shots = {event["shot"]: np.load(event["artifact"]) for event in events if event["kind"] == "shot"}
    return shots, next(event for event in events if event["kind"] == "loaded")


@pytest.mark.parametrize("content", [
    b"0.1,0.002,0.003,1\n0.2,0.004,0.005,2\n",
    b"0.1,0.002,0.003\n0.2,0.004,0.005,9\n",
    b"t,x,y\n0.1,0.002,0.003\n",
], ids=["four columns", "a longer row", "header"])
def test_an_unreadable_file_fails_alone(tmp_path: Path, content: bytes) -> None:
    folder = tmp_path / "run"
    folder.mkdir()
    txy(folder, 1, GOOD)
    txy(folder, 2, content)
    txy(folder, 3, GOOD)
    shots, done = loaded(folder, tmp_path)
    assert sorted(shots) == [1, 3] and shots[1].tolist() == GOOD_ROWS
    assert done["failed_files"] == 1 and done["problematic"] == [2] and done["total_files"] == 3


@pytest.mark.parametrize("content", [
    GOOD + b"0.3,0.006",  # A last row cut short.
    GOOD + b"\x00\x00\x00\x00",  # Zeros after an interrupted write.
    GOOD + b"0.3,nan,0.007\n",
    b"0.3,0.006\n" + GOOD,  # A short first row.
], ids=["cut short", "zeros", "nan", "short first row"])
def test_rows_that_are_not_three_numbers_are_dropped_and_the_shot_flagged(tmp_path: Path, content: bytes) -> None:
    folder = tmp_path / "run"
    folder.mkdir()
    txy(folder, 1, content)
    txy(folder, 2, GOOD)
    shots, done = loaded(folder, tmp_path)
    assert shots[1].tolist() == GOOD_ROWS and shots[2].tolist() == GOOD_ROWS
    assert done["problematic"] == [1] and done["failed_files"] == 0


@pytest.mark.parametrize("content", [b"0.1,0.002\n0.2,0.004\n", b"\x00\x00\x00\x00"], ids=["two columns", "zeros"])
def test_a_file_with_no_whole_row_is_an_empty_flagged_shot(tmp_path: Path, content: bytes) -> None:
    folder = tmp_path / "run"
    folder.mkdir()
    txy(folder, 1, content)
    txy(folder, 2, GOOD)
    shots, done = loaded(folder, tmp_path)
    assert shots[1].tolist() == [] and done["problematic"] == [1] and done["failed_files"] == 0


def test_a_folder_with_no_readable_file_fails_its_load(tmp_path: Path) -> None:
    folder = tmp_path / "run"
    folder.mkdir()
    txy(folder, 1, b"t,x,y\n")
    with pytest.raises(ValueError, match="No readable TXY files"):
        loaded(folder, tmp_path)
