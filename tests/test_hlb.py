"""HeLab's binary container (``helab.utils.hlb``, caching v2 stage 1): arrays round trip in Blosc chunks
with no pickle, and every kind of damage, a cut or a newer format is an error, never data."""
from __future__ import annotations

import json
import struct
import zlib
from typing import Any, Callable

import numpy as np
import pytest

from helab.utils import hlb


def sample() -> dict[str, np.ndarray[Any, Any]]:
    rng = np.random.default_rng(7)
    return {"channel": rng.integers(0, 8, 1000).astype("|i1"),
            "time": np.cumsum(rng.integers(0, 50, 1000)).astype("<i8"),
            "hits": rng.normal(size=(300, 3)).astype("<f8"),
            "flags": np.array([1, 0, 255], dtype="|u1"),
            "none": np.empty(0, dtype="<f8"), "grid": np.zeros((0, 3), dtype="<f8")}


START = len(hlb.MAGIC) + 8  # (The magic, then the header's length and CRC32.)


def header_of(data: bytes) -> dict[str, Any]:
    (length,) = struct.unpack_from("<I", data, len(hlb.MAGIC))
    found = json.loads(data[START:START + length])
    assert isinstance(found, dict)
    return found


def with_header(data: bytes, change: Callable[[dict[str, Any]], None]) -> bytes:
    """``data`` with its header changed and its CRC made again (the chunks' offsets still point at the
    same bytes), so the reader's later checks are what refuse it."""
    (length,) = struct.unpack_from("<I", data, len(hlb.MAGIC))
    header = header_of(data)
    change(header)
    text = json.dumps(header).encode()
    return data[:len(hlb.MAGIC)] + struct.pack("<II", len(text), zlib.crc32(text)) + text + data[START + length:]


def test_arrays_round_trip_with_their_dtypes_shapes_and_header() -> None:
    arrays = sample()
    data = hlb.pack(arrays, kind="raw", meta={"encoding": "x", "n": 3}, maker={"maker": "m1", "record": {"a": 1}})
    assert data.startswith(hlb.MAGIC) and b"pickle" not in data
    header, back = hlb.unpack(data)
    assert header["format"] == hlb.FORMAT and header["kind"] == "raw" and header["meta"] == {"encoding": "x", "n": 3}
    assert header["maker"] == {"maker": "m1", "record": {"a": 1}}
    assert list(back) == list(arrays)
    for name, array in arrays.items():
        assert back[name].dtype == array.dtype and back[name].shape == array.shape
        assert np.array_equal(back[name], array) and back[name].flags.writeable
    entry = header["arrays"][1]
    assert entry["dtype"] == "<i8" and entry["codec"] == {"name": "blosc", "cname": "zstd", "clevel": 9,
                                                           "shuffle": "byte", "typesize": 8}


def test_arrays_are_cut_into_chunks_at_element_boundaries() -> None:
    times = np.arange(10_001, dtype="<i8") * 3
    data = hlb.pack({"time": times}, kind="raw", chunk_bytes=1000)  # (996 bytes: 124 elements a chunk.)
    chunks = header_of(data)["arrays"][0]["chunks"]
    assert len(chunks) == -(-times.nbytes // 992) and all(chunk["size"] % 8 == 0 for chunk in chunks)
    assert sum(chunk["size"] for chunk in chunks) == times.nbytes
    assert np.array_equal(hlb.unpack(data)[1]["time"], times)
    # Deltas taken over the whole array before cutting: a sum across chunk boundaries is the array again.
    deltas = np.diff(times, prepend=0)
    assert np.array_equal(np.cumsum(hlb.unpack(hlb.pack({"d": deltas}, kind="raw", chunk_bytes=64))[1]["d"]), times)


def test_unknown_header_fields_are_ignored() -> None:
    data = with_header(hlb.pack(sample(), kind="raw"), lambda header: header.update(later={"x": 1}))
    assert np.array_equal(hlb.unpack(data)[1]["hits"], sample()["hits"])


def test_a_dtype_outside_the_allowed_set_is_never_written() -> None:
    with pytest.raises(hlb.HlbError, match="can't be stored"):
        hlb.pack({"x": np.zeros(3, dtype=np.float32)}, kind="raw")
    with pytest.raises(hlb.HlbError, match="can't be stored"):
        hlb.pack({"x": np.zeros(3, dtype=">i8")}, kind="raw")
    with pytest.raises(hlb.HlbError, match="can't be stored"):
        hlb.pack({"x": np.array(["a"], dtype=object)}, kind="raw")


def damaged() -> list[tuple[str, Callable[[bytes], bytes], str]]:
    def flip(data: bytes, at: int) -> bytes:
        return data[:at] + bytes([data[at] ^ 0xFF]) + data[at + 1:]

    def change(key: str, value: Any, index: int = 0) -> Callable[[bytes], bytes]:
        return lambda data: with_header(data, lambda header: header["arrays"][index].__setitem__(key, value))

    def chunk(key: str, value: int) -> Callable[[bytes], bytes]:
        return lambda data: with_header(data, lambda header: header["arrays"][0]["chunks"][0].__setitem__(key, value))
    return [
        ("magic", lambda data: b"\x89HLC" + data[4:], "first bytes"),
        ("text mode copy", lambda data: data.replace(b"\r\n", b"\n", 1), "first bytes"),
        ("empty", lambda data: b"", "first bytes"),
        ("cut header", lambda data: data[:20], "cut or too long"),
        ("huge header", lambda data: data[:8] + struct.pack("<I", hlb.MAX_HEADER + 1) + data[12:], "cut or too long"),
        ("header flipped", lambda data: flip(data, START + 3), "header is damaged"),
        ("header crc", lambda data: data[:12] + struct.pack("<I", 1) + data[16:], "header is damaged"),
        ("header not JSON", lambda data: data[:8] + struct.pack("<II", 1, zlib.crc32(b"}")) + b"}", "unreadable"),
        ("newer format", lambda data: with_header(data, lambda header: header.update(format=hlb.FORMAT + 1)),
         "newer HeLab"),
        ("no format", lambda data: with_header(data, lambda header: header.pop("format")), "no format"),
        ("no arrays", lambda data: with_header(data, lambda header: header.update(arrays={})), "no arrays"),
        ("meta not an object", lambda data: with_header(data, lambda header: header.update(meta=[1])), "meta"),
        ("unknown dtype", change("dtype", "<f4"), "isn't one this HeLab reads"),
        ("big-endian", change("dtype", ">i8", 1), "isn't one this HeLab reads"),
        ("unknown codec", change("codec", {"name": "lzma"}), "codec"),
        ("bad shape", change("shape", [-1]), "shape"),
        ("wrong shape", change("shape", [999]), "don't hold"),
        ("duplicate", lambda data: with_header(data, lambda header: header["arrays"][1].update(
            name=header["arrays"][0]["name"])), "listed twice"),
        ("chunk outside", chunk("offset", 10 ** 9), "don't fill the file"),
        ("negative offset", chunk("offset", -5), "don't fill the file"),
        ("gap", chunk("offset", 1), "don't fill the file"),
        ("overlap", lambda data: with_header(data, lambda header: header["arrays"][1]["chunks"][0].__setitem__(
            "offset", 0)), "don't fill the file"),
        ("trailing bytes", lambda data: data + b"\0", "after the last chunk"),
        ("crc", chunk("crc32", 1), "checksum"),
        ("size", chunk("size", 7), "don't hold"),
        ("flipped data", lambda data: flip(data, len(data) - 3), "checksum"),
        ("truncated", lambda data: data[:-10], "after the last chunk, or is cut"),
    ]


@pytest.mark.parametrize("name, spoil, message", damaged(), ids=[case[0] for case in damaged()])
def test_damage_or_a_newer_format_is_an_error_never_data(name: str, spoil: Callable[[bytes], bytes],
                                                         message: str) -> None:
    data = hlb.pack({"channel": sample()["channel"], "time": sample()["time"]}, kind="raw")
    with pytest.raises(hlb.HlbError, match=message):
        hlb.unpack(spoil(data))


def test_a_header_change_that_stays_valid_json_is_an_error() -> None:
    """C2-2 (Assay): the header has its own CRC, so a flipped digit in the facts isn't read as data."""
    from helab.convert import raw_layer
    data = raw_layer.to_hlb(raw_layer.encode(b"5,10\r\n1,20\r\n"))
    assert b'"first_channel":5' in data
    with pytest.raises(hlb.HlbError, match="header is damaged"):
        raw_layer.from_hlb(data.replace(b'"first_channel":5', b'"first_channel":7'))


def test_bytes_after_the_last_chunk_are_an_error() -> None:
    data = hlb.pack({"time": np.arange(10, dtype="<i8")}, kind="raw")
    with pytest.raises(hlb.HlbError, match="after the last chunk|don't fill"):
        hlb.unpack(data + b"junk")
