"""HeLab's own TXY files and the provenance kept beside them.

HeLab writes a shot's TXY as ``d_txy_helab_<N>.txy`` (Q8.2, Q9.7), byte for byte in MATLAB's
format, so the file carries no header. What made it is a small JSON record per shot,
``d_txy_helab_<N>.json`` (``Provenance``): the raw file's fingerprint (size, mtime, SHA-256), the
profile's name, version and content hash, the backend, and the TXY's size, SHA-256 and hit count.
It is written after the TXY, atomically, always in HeLab's own folder (the cache or the temp
folder), never in a source folder, even when the TXY goes beside the raw files.

One record per shot, not a manifest per folder: each is written once by the conversion that made
its TXY, so two conversions of one folder never rewrite each other's records, and Live adding a
shot every ~30 s writes one small file rather than the whole folder's list again.

``stale`` says why a TXY no longer stands for its raw file and the profile asked for (no record,
the raw file or the TXY changed, another profile hash), so a shot is converted again when a
profile improves. Profiles with one hash convert every file alike, so the backend and the
profile's name and version are recorded but don't make a TXY stale.

Qt-free; standard library only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
import re
from typing import Any

PROVENANCE = "helab-txy-provenance"
VERSION = 1

TXY_PATTERN = re.compile(r"^d_txy_helab_(\d+)\.txy$")


def txy_name(shot: int) -> str:
    return f"d_txy_helab_{shot}.txy"


def provenance_name(shot: int) -> str:
    return f"d_txy_helab_{shot}.json"


# What each field's JSON value may be (a float may be written as an integer).
_TYPES: dict[str, type | tuple[type, ...]] = {"int": int, "float": (int, float), "bool": bool, "str": str}


class ProvenanceError(ValueError):
    """A provenance record that isn't valid JSON of this shape."""


@dataclass(frozen=True, kw_only=True)
class Provenance:
    shot: int
    # The source folder as this conversion saw it, and its data-root key ("" without one).
    source_folder: str
    source_key: str
    raw_name: str
    raw_size: int
    raw_mtime_ns: int
    raw_sha256: str
    profile_name: str
    profile_version: int
    profile_hash: str
    profile_calibrated: bool
    backend: str
    # Where the TXY went: "beside" (next to the raw file), "cache" or "temp"; its file name.
    output: str
    txy_name: str
    txy_size: int
    txy_sha256: str
    hits: int
    converted_at: float
    helab_version: str
    read_seconds: float
    parse_seconds: float
    reconstruct_seconds: float
    format_seconds: float
    write_seconds: float

    def to_json(self) -> str:
        return json.dumps({"helab": PROVENANCE, "version": VERSION, **asdict(self)}, indent=1, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, text: str | bytes) -> Provenance:
        try:
            data = json.loads(text)
        except (ValueError, UnicodeDecodeError) as error:
            raise ProvenanceError(f"Not JSON: {error}") from error
        if not isinstance(data, dict) or data.get("helab") != PROVENANCE:
            raise ProvenanceError("Not a HeLab TXY provenance record")
        if data.get("version") != VERSION:
            raise ProvenanceError(f"Unknown provenance version {data.get('version')!r} (this HeLab reads {VERSION})")
        values: dict[str, Any] = {}
        for field in fields(cls):
            if field.name not in data:
                raise ProvenanceError(f"Missing field {field.name!r}")
            value: Any = data[field.name]
            expected = _TYPES[str(field.type)]
            if isinstance(value, bool) and field.type != "bool" or not isinstance(value, expected):
                raise ProvenanceError(f"{field.name} must be a {field.type}, not {value!r}")
            values[field.name] = float(value) if field.type == "float" and isinstance(value, (int, float)) else value
        return cls(**values)


def stale(record: Provenance | None, *, raw_size: int, raw_mtime_ns: int, profile_hash: str,
          txy_size: int | None) -> str | None:
    """Why a shot's TXY should be made again, or None when it is current: ``txy_size`` is the TXY's
    size now (None: no TXY), the raw values are its file's now."""
    if txy_size is None:
        return "no TXY"
    if record is None:
        return "no provenance record"
    if (record.raw_size, record.raw_mtime_ns) != (raw_size, raw_mtime_ns):
        return "the raw file changed since it was converted"
    if record.txy_size != txy_size:
        return "the TXY changed since it was written"
    if record.profile_hash != profile_hash:
        return f"converted with another profile ({record.profile_name} v{record.profile_version})"
    return None
