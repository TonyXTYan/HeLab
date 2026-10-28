"""The rust backend: the reference's matching compiled from Rust (``native/rust/``, PyO3), byte for
byte the same output.

The compiled module ``helab_convert_rs`` is imported on first use; without it the backend stays
registered and ``unavailable`` says why, so HeLab and the tests run without it. Build it into a
venv with ``maturin develop --release`` in ``native/rust/``. It copies its inputs and releases the
GIL while it works (``releases_gil``), so threads converting different shots run in parallel.

``reconstruct_rust(pulses, profile, threads=…)`` also splits one shot: the sorted rows are cut
only between two finite times more than ``search_window`` apart, and the pieces are matched on
Rust threads; ``native/rust/src/reconstruct.rs`` says why that can't change the output (the
phantom row and the 36-row search included). ``parse_strict`` and ``format_txy`` are a Rust raw
parser and TXY formatter, timed beside the shared Python/NumPy I/O for the report only.

Qt-free; standard library and NumPy only (the compiled module needs NumPy too).
"""
from __future__ import annotations

import importlib
from typing import Protocol, cast

import numpy as np
import numpy.typing as npt

from helab.convert.profile import POSITION_FORMULAS, DetectorProfile
from helab.convert.raw import RawPulses
from helab.convert.reconstruct import Backend, Hits, NoRowsError, register_backend

MODULE = "helab_convert_rs"
Floats = npt.NDArray[np.float64]


class Native(Protocol):
    """The compiled module's functions (``native/rust/src/lib.rs``)."""
    __version__: str

    def reconstruct(self, channels: Floats, times: Floats, channel_corners: tuple[float, float, float, float],
                    subtract_time_zero: bool, skip_first_sorted_row: bool,
                    dead_time_bins: tuple[float | None, float | None, float | None, float | None],
                    search_depth: int, search_window: float, x_limit: float, y_limit: float, xy_limit: float,
                    time_sum_t: tuple[float, float], bin_time: float, v_perp: tuple[float, float], centred: bool,
                    matlab_overflow_row: bool, threads: int = 1, piece_rows: int = 0) -> tuple[Hits, int]: ...

    def cut_points(self, times: Floats, window: float, piece_rows: int) -> list[int]: ...

    def parse_strict(self, data: bytes) -> tuple[Floats, Floats] | None: ...

    def format_txy(self, hits: Floats) -> bytes: ...


_native: Native | None = None
_missing: str | None = None


def _import_native() -> Native:
    return cast(Native, importlib.import_module(MODULE))


def native() -> Native | None:
    """The compiled module, or None when it isn't installed (``missing_reason`` says why)."""
    global _native, _missing
    if _native is None and _missing is None:
        try:
            _native = _import_native()
        except ImportError as error:
            _missing = f"{MODULE} isn't installed ({error}); build it with `maturin develop --release` in native/rust"
    return _native


def missing_reason() -> str | None:
    native()
    return _missing


def unavailable(profile: DetectorProfile | None) -> str | None:
    reason = missing_reason()
    if reason is not None or profile is None:
        return reason
    if profile.x2_handling != "matlab" or profile.y_handling != "matlab":
        return "only 'matlab' candidate handling"
    if profile.position_formula not in POSITION_FORMULAS:
        return f"unknown position formula {profile.position_formula!r}"
    return None


def _dead_time_bins(dead_time: float, profile: DetectorProfile) -> float | None:
    return dead_time / profile.bin_time if dead_time > 0 else None


def reconstruct_rust(pulses: RawPulses, profile: DetectorProfile, threads: int = 1,
                     piece_rows: int = 0) -> tuple[Hits, int]:
    """The hits and the number of pieces the shot was matched in. ``threads`` > 1 matches pieces
    on that many Rust threads (about four pieces each unless ``piece_rows`` is given);
    ``piece_rows`` alone cuts at the first allowed gap every that many rows (1: every one)."""
    module = native()
    if module is None:
        raise RuntimeError(_missing)
    if len(pulses) == 0 and profile.subtract_time_zero:
        raise NoRowsError("The raw file has no rows (MATLAB fails at t_zero, L62)")
    p = profile
    return module.reconstruct(
        np.ascontiguousarray(pulses.channels, dtype=np.float64), np.ascontiguousarray(pulses.times, dtype=np.float64),
        (float(p.channel_x1), float(p.channel_x2), float(p.channel_y1), float(p.channel_y2)),
        p.subtract_time_zero, p.skip_first_sorted_row,
        (_dead_time_bins(p.dead_time_x1, p), _dead_time_bins(p.dead_time_x2, p),
         _dead_time_bins(p.dead_time_y1, p), _dead_time_bins(p.dead_time_y2, p)),
        p.search_depth, p.search_window,
        p.match_time_sum_x + p.match_tolerance_x,                            # T_sum_tol_throw (L440)
        p.match_time_sum_y + p.match_tolerance_y,                            # T_sum_tol_keep (L441)
        p.xy_sum_tolerance, (p.time_sum_t_x, p.time_sum_t_y), p.bin_time, (p.v_perp_x, p.v_perp_y),
        p.position_formula == "centred", p.matlab_overflow_row, threads, piece_rows)


def _run(pulses: RawPulses, profile: DetectorProfile) -> Hits:
    return reconstruct_rust(pulses, profile)[0]


register_backend(Backend(
    name="rust",
    run=_run,
    unavailable=unavailable,
    releases_gil=True,
    description="The reference's matching in Rust (PyO3); releases the GIL; can split one shot on threads.",
))
