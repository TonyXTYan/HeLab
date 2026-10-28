"""One raw file's bytes to its TXY bytes, as MATLAB's wrapper produces them.

``convert_raw`` reads, reconstructs and formats; it returns None when no TXY is written (no hits
and the profile's ``write_empty_txy`` off, as ``dld_raw_to_txy_counts`` does) and raises
``NoRowsError`` for a file with no rows (MATLAB fails). The timing harness (``timing``) runs the
same steps with a clock around each.

Qt-free; standard library and NumPy only.
"""
from __future__ import annotations

from helab.convert.profile import DetectorProfile
from helab.convert.raw import parse_raw
from helab.convert.reconstruct import DEFAULT_BACKEND, reconstruct
from helab.convert.txy import format_txy


def convert_raw(data: bytes, profile: DetectorProfile, backend: str = DEFAULT_BACKEND) -> bytes | None:
    hits = reconstruct(parse_raw(data), profile, backend)
    if hits.shape[0] == 0 and not profile.write_empty_txy:
        return None
    return format_txy(hits)
