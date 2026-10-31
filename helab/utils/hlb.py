"""HeLab's binary container (``.hlb``, caching v2): named NumPy arrays in Blosc chunks, with a JSON
header, and no pickle anywhere.

Layout (stage 1 design addendum §5)::

    offset 0   MAGIC   8 bytes  b"\\x89HLB\\r\\n\\x1a\\n" (PNG-style: a text-mode copy or a cut file fails it)
    offset 8   length  <u4      the header's bytes (at most MAX_HEADER)
    offset 12  crc32   <u4      zlib's CRC32 of the header's bytes
    offset 16  header  JSON, UTF-8
    then       chunks  each array's Blosc chunks, back to back, to the end of the file

The header is ``{"format", "kind", "maker", "meta", "arrays": [{"name", "dtype", "shape", "codec",
"chunks": [{"offset", "length", "size", "crc32"}]}]}``: ``offset`` from the end of the header,
``length`` the compressed bytes, ``size`` the uncompressed ones, ``crc32`` (zlib's) of the compressed
bytes (Blosc 1 keeps no checksum). Each chunk holds at most ``CHUNK_BYTES`` (64 MiB) of the array,
cut at element boundaries, so python-blosc's 2 GB limit on one call never applies.

**Format rule** (Q27.2): unknown header fields are ignored (an additive change keeps ``FORMAT``); a
file of a newer ``format``, or an unknown dtype or codec, is refused (``HlbError``), never rewritten.
Only the dtypes in ``DTYPES`` are read, with their byte order spelled out.

Reading checks everything before trusting it: the magic, the header's length, CRC and shape, each
array's dtype, shape and chunk sizes, that the chunks tile the body exactly (in order, no gap, no
overlap, nothing after the last), and every chunk's CRC and decompressed size. A file
that fails any check is an error, never "nothing saved" (AGENTS.md's read rule).

Bytes only: the store writes the file (a temporary name, fsync, rename). Qt-free; standard
library, NumPy and blosc.
"""
from __future__ import annotations

import json
import math
import struct
import zlib
from typing import Any, Mapping

import numpy as np
import numpy.typing as npt

MAGIC = b"\x89HLB\r\n\x1a\n"
FORMAT = 1
MAX_HEADER = 16 * 1024 * 1024
CHUNK_BYTES = 64 * 1024 * 1024
# The dtypes a file may hold, by their explicit spelling (byte order included).
DTYPES: dict[str, np.dtype[Any]] = {name: np.dtype(name) for name in ("|i1", "|u1", "<i8", "<f8")}
CNAME = "zstd"
CLEVEL = 9
_LENGTH = struct.Struct("<II")  # (The header's length and CRC32.)
_START = len(MAGIC) + _LENGTH.size


class HlbError(ValueError):
    """The bytes aren't a container this HeLab can read (damaged, cut, or of a newer format)."""


def _blosc() -> Any:
    import blosc  # (Imported on first use, as the store does.)
    return blosc


def pack(arrays: Mapping[str, npt.NDArray[Any]], *, kind: str, meta: Mapping[str, Any] | None = None,
         maker: Mapping[str, Any] | None = None, clevel: int = CLEVEL, cname: str = CNAME, shuffle: bool = True,
         chunk_bytes: int = CHUNK_BYTES) -> bytes:
    """The container's bytes for ``arrays`` (each a NumPy array of a dtype in ``DTYPES``, any shape),
    compressed with Blosc (``cname`` at ``clevel``, byte shuffle by the element size unless off)."""
    blosc = _blosc()
    entries: list[dict[str, Any]] = []
    body: list[bytes] = []
    offset = 0
    for name, array in arrays.items():
        dtype = np.dtype(array.dtype)
        spelled = dtype.str
        if spelled not in DTYPES:
            raise HlbError(f"Array {name!r}: dtype {spelled} can't be stored")
        flat = np.ascontiguousarray(array).reshape(-1)
        data = flat.tobytes()
        step = max(dtype.itemsize, chunk_bytes - chunk_bytes % dtype.itemsize)
        chunks: list[dict[str, int]] = []
        for start in range(0, len(data), step) if data else ():
            piece = data[start:start + step]
            packed = blosc.compress(piece, typesize=dtype.itemsize, clevel=clevel,
                                    shuffle=blosc.SHUFFLE if shuffle else blosc.NOSHUFFLE, cname=cname)
            chunks.append({"offset": offset, "length": len(packed), "size": len(piece),
                           "crc32": zlib.crc32(packed)})
            body.append(packed)
            offset += len(packed)
        entries.append({"name": name, "dtype": spelled, "shape": list(array.shape),
                        "codec": {"name": "blosc", "cname": cname, "clevel": clevel,
                                  "shuffle": "byte" if shuffle else "none", "typesize": dtype.itemsize},
                        "chunks": chunks})
    header = json.dumps({"format": FORMAT, "kind": kind, "maker": dict(maker or {}), "meta": dict(meta or {}),
                         "arrays": entries}, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(header) > MAX_HEADER:
        raise HlbError(f"The header is {len(header)} bytes, over {MAX_HEADER}")
    return b"".join((MAGIC, _LENGTH.pack(len(header), zlib.crc32(header)), header, *body))


def read_header(data: bytes) -> dict[str, Any]:
    """The header of a container's bytes, checked (``HlbError`` otherwise)."""
    if len(data) < _START or data[:len(MAGIC)] != MAGIC:
        raise HlbError("Not a HeLab container (its first bytes are wrong)")
    length, crc = _LENGTH.unpack_from(data, len(MAGIC))
    if length > MAX_HEADER or _START + length > len(data):
        raise HlbError("The container's header is cut or too long")
    if zlib.crc32(data[_START:_START + length]) != crc:
        raise HlbError("The container's header is damaged (checksum)")
    try:
        header = json.loads(data[_START:_START + length].decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise HlbError(f"The container's header is unreadable ({exc})") from None
    if not isinstance(header, dict) or not isinstance(header.get("format"), int) or isinstance(header["format"], bool):
        raise HlbError("The container's header has no format")
    if header["format"] > FORMAT:
        raise HlbError(f"Written by a newer HeLab (format {header['format']}; this one reads {FORMAT})")
    if header["format"] < 1 or not isinstance(header.get("arrays"), list):
        raise HlbError("The container's header lists no arrays")
    for key in ("meta", "maker"):
        if not isinstance(header.get(key, {}), dict):
            raise HlbError(f"The container's {key} isn't an object")
    return header


def unpack(data: bytes) -> tuple[dict[str, Any], dict[str, npt.NDArray[Any]]]:
    """A container's header and arrays (new arrays, never views of ``data``), every part checked."""
    blosc = _blosc()
    header = read_header(data)
    length, _ = _LENGTH.unpack_from(data, len(MAGIC))
    base = _START + length
    entries = [_entry(entry) for entry in header["arrays"]]
    # The chunks tile the body exactly: in the order listed, no gap, no overlap, nothing after the last.
    end = 0
    for name, _, _, chunks in entries:
        for chunk in chunks:
            if chunk["offset"] != end or chunk["length"] <= 0:
                raise HlbError(f"Array {name!r}: its chunks don't fill the file in order (a gap or an overlap)")
            end += chunk["length"]
    if base + end != len(data):
        raise HlbError("The container has bytes after the last chunk, or is cut")
    arrays: dict[str, npt.NDArray[Any]] = {}
    for name, dtype, shape, chunks in entries:
        if name in arrays:
            raise HlbError(f"Array {name!r} is listed twice")
        expected = math.prod(shape) * dtype.itemsize
        if sum(chunk["size"] for chunk in chunks) != expected:
            raise HlbError(f"Array {name!r}: its chunks don't hold {expected} bytes")
        pieces: list[bytes] = []
        for chunk in chunks:
            start, end = base + chunk["offset"], base + chunk["offset"] + chunk["length"]
            if chunk["offset"] < 0 or chunk["length"] <= 0 or end > len(data):
                raise HlbError(f"Array {name!r}: a chunk lies outside the file (cut?)")
            packed = data[start:end]
            if zlib.crc32(packed) != chunk["crc32"]:
                raise HlbError(f"Array {name!r}: a chunk is damaged (checksum)")
            try:
                piece = blosc.decompress(packed)
            except Exception as exc:  # (python-blosc raises plain exceptions on damage.)
                raise HlbError(f"Array {name!r}: a chunk can't be decompressed ({exc})") from None
            if len(piece) != chunk["size"]:
                raise HlbError(f"Array {name!r}: a chunk decompressed to the wrong size")
            pieces.append(piece)
        arrays[name] = np.frombuffer(b"".join(pieces), dtype=dtype).reshape(shape).copy()
    return header, arrays


def _entry(entry: Any) -> tuple[str, np.dtype[Any], tuple[int, ...], list[dict[str, int]]]:
    if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
        raise HlbError("An array entry has no name")
    name = entry["name"]
    dtype = DTYPES.get(str(entry.get("dtype")))
    if dtype is None:
        raise HlbError(f"Array {name!r}: dtype {entry.get('dtype')!r} isn't one this HeLab reads")
    codec = entry.get("codec")
    if not isinstance(codec, dict) or codec.get("name") != "blosc":
        raise HlbError(f"Array {name!r}: codec {codec!r} isn't one this HeLab reads")
    shape = entry.get("shape")
    if not isinstance(shape, list) or not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0
                                              for n in shape):
        raise HlbError(f"Array {name!r}: its shape is malformed")
    chunks = entry.get("chunks")
    keys = ("offset", "length", "size", "crc32")
    if not isinstance(chunks, list) or not all(
            isinstance(chunk, dict) and all(isinstance(chunk.get(key), int) and not isinstance(chunk.get(key), bool)
                                            for key in keys) for chunk in chunks):
        raise HlbError(f"Array {name!r}: its chunks are malformed")
    return name, dtype, tuple(shape), [{key: int(chunk[key]) for key in keys} for chunk in chunks]
