"""One raw file's bytes to its TXY bytes, as MATLAB's wrapper produces them, or as HeLab writes its own.

``convert_raw`` reads, reconstructs and formats; it returns None when no TXY is written (no hits
and the profile's ``write_empty_txy`` off, as ``dld_raw_to_txy_counts`` does) and raises
``NoRowsError`` for a file with no rows (MATLAB fails). The timing harness (``timing``) runs the
same steps with a clock around each.

``convert_shot`` is HeLab's own conversion (``io_ops.convert`` and ``helab convert``): the same
steps, timed, and always a TXY: no hits give a 0-byte one, whatever the profile says, so
"converted, empty" differs from "not converted yet" (Q10.3, A10.5). A large shot may be cut into
pieces reconstructed in parallel (``split``; byte for byte the whole shot's output).

Qt-free; standard library and NumPy only.
"""
from __future__ import annotations

from concurrent.futures import Executor
from dataclasses import dataclass
import time

from helab.convert.profile import DetectorProfile
from helab.convert.raw import parse_raw
from helab.convert.reconstruct import DEFAULT_BACKEND, reconstruct
from helab.convert.split import reconstruct_split
from helab.convert.txy import format_txy

# HeLab's backend unless the user picks another: stage 2's recommendation (NumPy works everywhere,
# needs no build and meets the bulk target on one core); the others are optional behind the switch.
APP_BACKEND = "numpy"


def convert_raw(data: bytes, profile: DetectorProfile, backend: str = DEFAULT_BACKEND) -> bytes | None:
    hits = reconstruct(parse_raw(data), profile, backend)
    if hits.shape[0] == 0 and not profile.write_empty_txy:
        return None
    return format_txy(hits)


@dataclass(frozen=True)
class Converted:
    """A shot converted for HeLab: its TXY bytes (empty for no hits), hit count and seconds per step."""
    txy: bytes
    hits: int
    parse_seconds: float
    reconstruct_seconds: float
    format_seconds: float


def convert_shot(data: bytes, profile: DetectorProfile, backend: str = APP_BACKEND, *,
                 executor: Executor | None = None, max_pieces: int | None = None) -> Converted:
    """HeLab's TXY for a raw file's bytes. With an ``executor``, the shot is cut at the gaps the
    match can't cross into at most ``max_pieces`` pieces run there (``split.reconstruct_split``).
    Raises ``NoRowsError`` for a file with no rows and ``BackendError`` when the backend can't run."""
    started = time.perf_counter()
    pulses = parse_raw(data)
    parsed = time.perf_counter()
    if executor is None:
        hits = reconstruct(pulses, profile, backend)
    else:
        hits = reconstruct_split(pulses, profile, backend, executor=executor, max_pieces=max_pieces)
    reconstructed = time.perf_counter()
    txy = format_txy(hits)
    return Converted(txy=txy, hits=int(hits.shape[0]), parse_seconds=parsed - started,
                     reconstruct_seconds=reconstructed - parsed, format_seconds=time.perf_counter() - reconstructed)
