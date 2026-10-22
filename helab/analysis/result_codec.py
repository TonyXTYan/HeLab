"""A result's data as NumPy arrays and a JSON tree, and back, without running code from the
file (result caching R2): no pickle. The default contract of ``DatasetAnalysis.cache_pack`` and
``cache_unpack``.

``encode`` walks what ``compute`` returned: JSON scalars, non-finite floats, strings, lists,
tuples, dicts (any encodable keys), sets, read-only mappings, enums and NumPy arrays and scalars,
and instances of the dataclasses the script declares (``DatasetAnalysis.cache_types``), and objects a
declared ``Reducer`` saves by their data and rebuilds with HeLab's own code (a fit model, whose
functions can't be saved: ``helab.analysis.result_types.FIT_MODEL``). Arrays go
to ``arrays`` by name; everything else stays in the tree, tagged where JSON would lose its type.
``decode`` rebuilds only those types: a dataclass or enum named in a file but not declared is an
error (``CodecError``), never an import. ``pack`` writes both into one ``.npz`` (the tree as UTF-8
bytes in ``__tree__``) and ``unpack`` reads it with ``allow_pickle=False``, refusing object arrays.

Qt-free; NumPy only.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
import enum
import io
import json
import math
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Union

import numpy as np
import numpy.typing as npt

FORMAT = "npz-json-1"
TREE = "__tree__"
Arrays = dict[str, npt.NDArray[Any]]


class CodecError(ValueError):
    """The data can't be saved this way, or a saved file isn't such data."""


@dataclass(frozen=True)
class Reducer:
    """Saves instances of ``cls`` (and its subclasses) as ``reduce(obj)``, a value ``encode`` can
    save, and rebuilds them with ``rebuild(value)``: for objects holding what a file can't (functions),
    which HeLab's code knows how to make again from their data. ``name`` is what the file records."""
    name: str
    cls: type
    reduce: Callable[[Any], Any]
    rebuild: Callable[[Any], Any]


Declared = Union[type, Reducer]


def type_name(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _types(types: Iterable[Declared]) -> dict[str, type]:
    return {type_name(cls): cls for cls in types if isinstance(cls, type)}


def _reducers(types: Iterable[Declared]) -> list[Reducer]:
    return [item for item in types if isinstance(item, Reducer)]


def encode(value: Any, types: Iterable[Declared] = ()) -> tuple[Any, Arrays]:
    """``value`` as a JSON tree and the arrays it names; raises ``CodecError`` for anything else
    (a dataclass or enum not in ``types``, an object array, a callable…)."""
    types = tuple(types)
    allowed, reducers = _types(types), _reducers(types)
    arrays: Arrays = {}

    def walk(item: Any) -> Any:
        if item is None or isinstance(item, (bool, str)):
            return item
        for reducer in reducers:
            if isinstance(item, reducer.cls):
                return {"$reduced": reducer.name, "value": walk(reducer.reduce(item))}
        if isinstance(item, enum.Enum):
            name = type_name(type(item))
            if name not in allowed:
                raise CodecError(f"{name} isn't declared in cache_types")
            return {"$enum": name, "name": item.name}
        if isinstance(item, (int, np.integer)) and not isinstance(item, np.bool_):
            return int(item)
        if isinstance(item, np.bool_):
            return bool(item)
        if isinstance(item, (float, np.floating)):
            number = float(item)
            return number if math.isfinite(number) else {"$float": repr(number)}
        if isinstance(item, np.ndarray):
            if item.dtype.hasobject:
                raise CodecError("an object array can't be saved without pickle")
            name = f"a{len(arrays)}"
            arrays[name] = np.ascontiguousarray(item)
            return {"$array": name}
        if isinstance(item, np.generic):
            raise CodecError(f"NumPy scalar of type {item.dtype} can't be saved")
        if dataclasses.is_dataclass(item) and not isinstance(item, type):
            name = type_name(type(item))
            if name not in allowed:
                raise CodecError(f"{name} isn't declared in cache_types")
            return {"$dataclass": name,
                    "fields": [[field.name, walk(getattr(item, field.name))] for field in dataclasses.fields(item)]}
        if isinstance(item, tuple):
            return {"$tuple": [walk(entry) for entry in item]}
        if isinstance(item, list):
            return [walk(entry) for entry in item]
        if isinstance(item, (set, frozenset)):
            entries = [walk(entry) for entry in item]
            return {"$frozenset" if isinstance(item, frozenset) else "$set": entries}
        if isinstance(item, MappingProxyType):
            return {"$mappingproxy": [[walk(key), walk(entry)] for key, entry in item.items()]}
        if isinstance(item, dict):
            return {"$dict": [[walk(key), walk(entry)] for key, entry in item.items()]}
        raise CodecError(f"{type(item).__name__} can't be saved")

    return walk(value), arrays


def decode(tree: Any, arrays: Mapping[str, npt.NDArray[Any]], types: Iterable[Declared] = ()) -> Any:
    """What ``encode`` gave, rebuilt; only the ``types`` declared, arrays read-only."""
    types = tuple(types)
    allowed = _types(types)
    reducers = {reducer.name: reducer for reducer in _reducers(types)}

    def walk(item: Any) -> Any:
        if item is None or isinstance(item, (bool, int, float, str)):
            return item
        if isinstance(item, list):
            return [walk(entry) for entry in item]
        if not isinstance(item, dict) or len(item) not in (1, 2):
            raise CodecError("not a saved result tree")
        if "$float" in item:
            return float(str(item["$float"]))
        if "$array" in item:
            array = arrays.get(str(item["$array"]))
            if array is None:
                raise CodecError(f"array {item['$array']} is missing")
            array.flags.writeable = False
            return array
        if "$tuple" in item:
            return tuple(walk(entry) for entry in _list(item["$tuple"]))
        if "$set" in item:
            return {walk(entry) for entry in _list(item["$set"])}
        if "$frozenset" in item:
            return frozenset(walk(entry) for entry in _list(item["$frozenset"]))
        if "$dict" in item:
            return {walk(pair[0]): walk(pair[1]) for pair in _pairs(item["$dict"])}
        if "$mappingproxy" in item:
            return MappingProxyType({walk(pair[0]): walk(pair[1]) for pair in _pairs(item["$mappingproxy"])})
        if "$reduced" in item:
            reducer = reducers.get(str(item["$reduced"]))
            if reducer is None:
                raise CodecError(f"{item['$reduced']} isn't a declared type")
            try:
                return reducer.rebuild(walk(item.get("value")))
            except CodecError:
                raise
            except Exception as exc:
                raise CodecError(f"{item['$reduced']} can't be rebuilt: {exc}") from exc
        if "$enum" in item:
            cls = allowed.get(str(item["$enum"]))
            if cls is None or not issubclass(cls, enum.Enum):
                raise CodecError(f"{item['$enum']} isn't a declared type")
            return cls[str(item["name"])]
        if "$dataclass" in item:
            cls = allowed.get(str(item["$dataclass"]))
            if cls is None or not dataclasses.is_dataclass(cls):
                raise CodecError(f"{item['$dataclass']} isn't a declared type")
            values = {str(pair[0]): walk(pair[1]) for pair in _pairs(item["fields"])}
            fields = {field.name: field for field in dataclasses.fields(cls)}
            if set(values) - set(fields):
                raise CodecError(f"{item['$dataclass']} has no field {sorted(set(values) - set(fields))[0]}")
            given = {name: value for name, value in values.items() if fields[name].init}
            try:
                built = cls(**given)
            except TypeError as exc:
                raise CodecError(f"{item['$dataclass']} can't be rebuilt: {exc}") from exc
            for name, value in values.items():
                if not fields[name].init:
                    object.__setattr__(built, name, value)
            return built
        raise CodecError("not a saved result tree")

    return walk(tree)


def _list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise CodecError("not a saved result tree")
    return value


def _pairs(value: Any) -> list[list[Any]]:
    entries = _list(value)
    if not all(isinstance(pair, list) and len(pair) == 2 for pair in entries):
        raise CodecError("not a saved result tree")
    return entries




def pack(tree: Any, arrays: Mapping[str, npt.NDArray[Any]]) -> bytes:
    """One ``.npz`` holding the arrays and the tree (``FORMAT``), zip-compressed."""
    text = json.dumps({"format": FORMAT, "tree": tree}, separators=(",", ":"), allow_nan=False)
    buffer = io.BytesIO()
    files: dict[str, Any] = {TREE: np.frombuffer(text.encode("utf-8"), dtype=np.uint8), **arrays}
    np.savez_compressed(buffer, **files)
    return buffer.getvalue()


def unpack(data: bytes) -> tuple[Any, Arrays]:
    """The tree and arrays of a ``pack``ed file; ``CodecError`` for anything else."""
    try:
        with np.load(io.BytesIO(data), allow_pickle=False) as files:
            arrays: Arrays = {name: files[name] for name in files.files}
    except (ValueError, OSError, EOFError) as exc:  # (``allow_pickle=False`` refuses object arrays.)
        raise CodecError(f"not a saved result file: {exc}") from exc
    text = arrays.pop(TREE, None)
    if text is None or text.dtype != np.uint8:
        raise CodecError("not a saved result file: no tree")
    try:
        document = json.loads(text.tobytes().decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CodecError(f"not a saved result file: {exc}") from exc
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise CodecError("not a saved result file: unknown format")
    return document.get("tree"), arrays


def nbytes(arrays: Mapping[str, npt.NDArray[Any]]) -> int:
    return sum(int(array.nbytes) for array in arrays.values())
