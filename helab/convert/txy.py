"""TXY text exactly as MATLAB's ``dlmwrite(file, hits, 'precision', 8)`` writes it.

Each value is C's ``%.8g`` (two-digit exponents at least, ``-0`` kept), except that MATLAB spells
the non-finite ones ``NaN``, ``Inf`` and ``-Inf``; values are joined by ``,`` and every row ends
with ``\\n``, the last included, on every platform. No rows give an empty file (measured with
MATLAB R2025b; ``dld_raw_to_txy_counts`` writes no file at all for an empty result, the 2023
``dld_raw_to_txy`` an empty one).

``write_txy`` writes to a new temporary name in the target's folder, created with mode ``0o666``
so the kernel applies the umask, as for any plain new file (MATLAB's ``fopen`` too; ``mkstemp``'s
own is owner-only), flushes it to disk, then renames it into place and syncs the folder, so a
reader never sees half a file and a crash leaves the old one or the new one. ``replace=False``
never replaces a file already at the target (``FileExistsError``; the temporary one is removed):
HeLab's writes beside raw files never touch an existing TXY: a hard link, else the OS's rename that
refuses an existing name (macOS ``renamex_np``, Linux ``renameat2``; Windows' ``os.rename`` refuses one
anyway), else no write at all (``OSError`` ``ENOTSUP``). ``before_rename`` is called with the
temporary file's ``os.stat`` once it is written and closed, before the rename (which keeps its size
and mtime): HeLab records which file it is writing in its index first; an exception there removes
the temporary file and is raised.

Qt-free; standard library and NumPy only.
"""
from __future__ import annotations

import ctypes
import errno
import functools
import math
import os
from pathlib import Path
import re
import secrets
import sys
from typing import Callable

import numpy as np
import numpy.typing as npt

from helab.convert import fastio

Hits = npt.NDArray[np.float64]
COLUMNS = 3
_NON_FINITE = {math.inf: "Inf", -math.inf: "-Inf"}
_CREATE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
_TOKEN_BYTES = 8
PLATFORM = sys.platform  # (Read at call time: tests try other platforms' rules.)
_RENAME_EXCL = 0x4  # macOS <stdio.h>
_RENAME_NOREPLACE = 0x1  # Linux <linux/fs.h>
_AT_FDCWD = -100
# What renamex_np / renameat2 answer where the file system (or the kernel) can't refuse a name.
_UNSUPPORTED = frozenset({errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP})


def partial_name(name: str, token: str) -> str:
    """The temporary name ``write_atomic`` writes ``name`` under first (``token``: 16 hex digits)."""
    return f".{name}.{token}.partial"


def partial_pattern(name_pattern: str) -> re.Pattern[str]:
    """The temporary names ``write_atomic`` makes for targets matching ``name_pattern`` (a regex
    without anchors), and nothing else: what a writer's leftovers can be matched by."""
    return re.compile(rf"^\.(?:{name_pattern})\.[0-9a-f]{{{2 * _TOKEN_BYTES}}}\.partial$", re.ASCII)


def format_value(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return _NON_FINITE[value]
    return "%.8g" % value


def format_txy(hits: Hits) -> bytes:
    """Hits are a 2-D float64 array (any memory layout); anything else is refused, at every
    size (the fast formatter reads the values' bit patterns)."""
    if not isinstance(hits, np.ndarray) or hits.dtype != np.float64:
        raise ValueError(f"TXY hits are a float64 array, not {getattr(hits, 'dtype', type(hits).__name__)}")
    if hits.ndim != 2 or (hits.size and hits.shape[1] != COLUMNS):
        raise ValueError(f"TXY hits are an (n, {COLUMNS}) array, not {hits.shape}")
    if not hits.size:
        return b""
    return fastio.format_txy(hits)


def format_txy_by_value(hits: Hits) -> bytes:
    """``format_txy`` value by value through ``format_value``: the general path the fast one is
    tested against."""
    lines = [",".join(format_value(value) for value in row) + "\n" for row in hits.tolist()]
    return "".join(lines).encode("ascii")


def write_txy(path: str | os.PathLike[str], hits: Hits) -> None:
    write_atomic(path, format_txy(hits))


def write_atomic(path: str | os.PathLike[str], data: bytes, *, replace: bool = True,
                 before_rename: Callable[[os.stat_result], None] | None = None,
                 after_rename: Callable[[], None] | None = None) -> None:
    # ``after_rename`` runs right after the rename, before the folder's fsync (a converter lets go of
    # the index lock it held across the rename alone, A19.2). Should it raise, the file is in place
    # and stays; the error is raised and the folder isn't fsynced.
    target = Path(path)
    for _ in range(100):
        temporary = target.with_name(partial_name(target.name, secrets.token_hex(_TOKEN_BYTES)))
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
        if before_rename is not None:
            before_rename(os.stat(temporary))
        if replace:
            os.replace(temporary, target)
        else:
            _rename_new(temporary, target)
        if after_rename is not None:
            after_rename()
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    _fsync_folder(target.parent)


def _rename_new(temporary: Path, target: Path) -> None:
    """Rename ``temporary`` to ``target`` only if nothing is there: a hard link fails on an existing
    name atomically, then the temporary name goes. Where links aren't supported (some shares,
    FAT), Windows' rename, which refuses an existing file, or elsewhere ``_rename_exclusive``: never a
    check then a rename, which would replace a file written in between."""
    try:
        os.link(temporary, target)
    except FileExistsError:
        raise
    except OSError:
        if PLATFORM == "win32":
            os.rename(temporary, target)
        else:
            _rename_exclusive(temporary, target)
        return
    os.unlink(temporary)


def _rename_exclusive(temporary: Path, target: Path) -> None:
    """The OS's atomic rename that refuses an existing name; where neither it nor a hard link works,
    the write is refused (``ENOTSUP``) rather than risk replacing a file."""
    rename = _exclusive_rename(PLATFORM)
    if rename is None:
        raise _cannot_refuse(target, "this system has no rename that refuses an existing name")
    if rename(os.fsencode(temporary), os.fsencode(target)) == 0:
        return
    code = ctypes.get_errno()
    if code == errno.EEXIST:
        raise FileExistsError(code, "A file is already there", str(target))
    if code in _UNSUPPORTED:
        raise _cannot_refuse(target, os.strerror(code))
    raise OSError(code, os.strerror(code), str(temporary), None, str(target))


def _cannot_refuse(target: Path, reason: str) -> OSError:
    return OSError(errno.ENOTSUP, f"Not written: this folder's file system can't add a file without risking "
                                  f"replacing one already there (no hard links, and {reason})", str(target))


@functools.cache
def _exclusive_rename(platform: str) -> Callable[[bytes, bytes], int] | None:
    """``(old, new) -> 0 or -1`` (errno in ``ctypes.get_errno``): macOS ``renamex_np(RENAME_EXCL)``,
    Linux ``renameat2(RENAME_NOREPLACE)`` (glibc 2.28+); None where the C library has neither."""
    if platform not in ("darwin", "linux"):
        return None
    try:
        libc = ctypes.CDLL(None, use_errno=True)
    except (OSError, TypeError):
        return None
    if platform == "darwin":
        renamex = getattr(libc, "renamex_np", None)
        if renamex is None:
            return None
        renamex.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex.restype = ctypes.c_int
        return lambda old, new: int(renamex(old, new, _RENAME_EXCL))
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        return None
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    return lambda old, new: int(renameat2(_AT_FDCWD, old, _AT_FDCWD, new, _RENAME_NOREPLACE))


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
