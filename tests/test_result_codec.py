"""A result's data saved without pickle (``helab.analysis.result_codec``): NumPy arrays and a JSON
tree, rebuilt only from the types a script declares; a file holding anything else (an object
array, an undeclared type) is refused, never run."""
from __future__ import annotations

import enum
import io
import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np
import numpy.typing as npt
import pytest

from helab.analysis import result_codec
from helab.analysis.result_codec import CodecError


class Mode(enum.Enum):
    ONE = "one"


@dataclass(frozen=True)
class Inner:
    value: float
    arrays: tuple[npt.NDArray[np.float64], ...] = ()


@dataclass(frozen=True)
class Outer:
    name: str
    inner: Inner | None
    counts: Mapping[int, tuple[int, int]] = field(default_factory=lambda: MappingProxyType({}))
    mode: Mode = Mode.ONE
    total: int = field(default=0, init=False)


TYPES = (Inner, Outer, Mode)


def round_trip(value: Any, types: tuple[type, ...] = TYPES) -> Any:
    tree, arrays = result_codec.encode(value, types)
    return result_codec.decode(*result_codec.unpack(result_codec.pack(tree, arrays)), types)


def test_nested_dataclasses_arrays_and_special_values_round_trip() -> None:
    outer = Outer("x", Inner(math.nan, (np.arange(5.0), np.ones((2, 3)))), MappingProxyType({3: (1, 2)}))
    object.__setattr__(outer, "total", 7)
    back = round_trip({"data": outer, "inf": -math.inf, "set": frozenset({1, 2}), (1, 2): [None, True, 1.5]})
    data = back["data"]
    assert isinstance(data, Outer) and data.name == "x" and data.mode is Mode.ONE and data.total == 7
    assert data.inner is not None and math.isnan(data.inner.value)
    assert np.array_equal(data.inner.arrays[1], np.ones((2, 3))) and not data.inner.arrays[0].flags.writeable
    assert isinstance(data.counts, MappingProxyType) and data.counts[3] == (1, 2)
    assert back["inf"] == -math.inf and back["set"] == frozenset({1, 2}) and back[(1, 2)] == [None, True, 1.5]


def test_numpy_scalars_become_plain_values() -> None:
    back = round_trip([np.float64(1.5), np.int64(3), np.bool_(True)])
    assert back == [1.5, 3, True] and type(back[1]) is int and type(back[2]) is bool


def test_undeclared_types_are_refused_both_ways() -> None:
    with pytest.raises(CodecError, match="isn't declared"):
        result_codec.encode(Inner(1.0), ())
    tree, arrays = result_codec.encode(Inner(1.0), TYPES)
    with pytest.raises(CodecError, match="isn't a declared type"):
        result_codec.decode(tree, arrays, ())
    with pytest.raises(CodecError):
        result_codec.encode(lambda: None)
    with pytest.raises(CodecError, match="object array"):
        result_codec.encode(np.array([object()], dtype=object))


def test_a_file_with_an_object_array_or_another_format_is_refused() -> None:
    buffer = io.BytesIO()
    np.savez(buffer, __tree__=np.frombuffer(b'{"format":"npz-json-1","tree":1}', dtype=np.uint8),
             a0=np.array([{"x": 1}], dtype=object))
    with pytest.raises(CodecError):
        result_codec.unpack(buffer.getvalue())
    with pytest.raises(CodecError):
        result_codec.unpack(b"not a zip")
    other = io.BytesIO()
    np.savez(other, __tree__=np.frombuffer(b'{"format":"other","tree":1}', dtype=np.uint8))
    with pytest.raises(CodecError, match="unknown format"):
        result_codec.unpack(other.getvalue())


def test_a_tree_naming_a_field_the_type_lacks_is_refused() -> None:
    tree = {"$dataclass": result_codec.type_name(Inner), "fields": [["value", 1.0], ["evil", 2]]}
    with pytest.raises(CodecError, match="no field"):
        result_codec.decode(tree, {}, TYPES)
