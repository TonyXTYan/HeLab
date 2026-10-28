"""TXY text exactly as MATLAB's ``dlmwrite(file, hits, 'precision', 8)`` writes it.

Each value is C's ``%.8g`` (two-digit exponents at least, ``-0`` kept), except that MATLAB spells
the non-finite ones ``NaN``, ``Inf`` and ``-Inf``; values are joined by ``,`` and every row ends
with ``\\n``, the last included, on every platform. No rows give an empty file (measured with
MATLAB R2025b; ``dld_raw_to_txy_counts`` writes no file at all for an empty result, the 2023
``dld_raw_to_txy`` an empty one).

``write_txy`` writes to a new temporary name in the target's folder, created with mode ``0o666``
so the kernel applies the umask, as for any plain new file (MATLAB's ``fopen`` too; ``mkstemp``'s
own is owner-only), flushes it to disk, then renames it into place and syncs the folder, so a
reader never sees half a file and a crash leaves the old one or the new one.

Qt-free; standard library and NumPy only.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import secrets

import numpy as np
import numpy.typing as npt

Hits = npt.NDArray[np.float64]
COLUMNS = 3
_NON_FINITE = {math.inf: "Inf", -math.inf: "-Inf"}
_CREATE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)


def format_value(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return _NON_FINITE[value]
    return "%.8g" % value


def format_txy(hits: Hits) -> bytes:
    if hits.ndim != 2 or (hits.size and hits.shape[1] != COLUMNS):
        raise ValueError(f"TXY hits are an (n, {COLUMNS}) array, not {hits.shape}")
    lines = [",".join(format_value(value) for value in row) + "\n" for row in hits.tolist()]
    return "".join(lines).encode("ascii")


def write_txy(path: str | os.PathLike[str], hits: Hits) -> None:
    write_atomic(path, format_txy(hits))


def write_atomic(path: str | os.PathLike[str], data: bytes) -> None:
    target = Path(path)
    for _ in range(100):
        temporary = target.with_name(f".{target.name}.{secrets.token_hex(8)}.partial")
        try:
            descriptor = os.open(temporary, _CREATE, 0o666)
            break
        except FileExistsError:
            continue
    else:
        raise FileExistsError(f"No free temporary name beside {target}")
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    _fsync_folder(target.parent)


def _fsync_folder(folder: Path) -> None:
    """Make the rename durable where the platform allows (not on Windows)."""
    if os.name == "nt":
        return
    try:
        descriptor = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
