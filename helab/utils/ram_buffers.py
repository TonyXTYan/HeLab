"""Counting the RAM arrays use, by the memory behind them: an array and every view of it are
one buffer, so data shared between datasets, views and results counts once (the RAM budget:
``FolderCache._evict``, ``helab.analysis.budget``)."""
from __future__ import annotations

import dataclasses
import weakref
from typing import TYPE_CHECKING, Any, Iterable, Iterator, Mapping

import numpy as np

if TYPE_CHECKING:
    from helab.utils.folder_cache import Dataset

# The memory a set of arrays uses: an identifier of each buffer → its size in bytes.
Buffers = dict[int, int]


def buffer_of(array: np.ndarray[Any, Any]) -> tuple[int, int]:
    """The memory ``array`` uses, as (identifier, bytes): the array at the bottom of its
    ``.base`` chain, or the buffer it was made from (``np.frombuffer``)."""
    while isinstance(array.base, np.ndarray):
        array = array.base
    owner = array.base
    if owner is None:
        return id(array), int(array.nbytes)
    while isinstance(owner, memoryview) and owner.obj is not None:
        owner = owner.obj  # The object whose memory it is (``np.frombuffer`` keeps a memoryview of it).
    try:
        size = memoryview(owner).nbytes
    except TypeError:
        size = int(array.nbytes)
    return id(owner), int(size)


def buffers(arrays: Iterable[np.ndarray[Any, Any]]) -> Buffers:
    """The memory ``arrays`` use (empty ones use none)."""
    return dict(item for item in map(buffer_of, arrays) if item[1])


def arrays_in(value: Any, depth: int = 0) -> Iterator[np.ndarray[Any, Any]]:
    """The NumPy arrays in a result's data: in dataclasses, tuples, lists, sets and mappings,
    a few levels down."""
    if isinstance(value, np.ndarray):
        if value.dtype != object:
            yield value
        return
    if depth > 6 or value is None or isinstance(value, (str, bytes, int, float, complex, bool)):
        return
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for item in dataclasses.fields(value):
            yield from arrays_in(getattr(value, item.name, None), depth + 1)
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from arrays_in(item, depth + 1)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from arrays_in(item, depth + 1)


_dataset_buffers: weakref.WeakKeyDictionary[Dataset, tuple[int, Buffers]] = weakref.WeakKeyDictionary()


def dataset_buffers(dataset: Dataset) -> Buffers:
    """The memory a held dataset's shots use (measured again if its shots change)."""
    known = _dataset_buffers.get(dataset)
    if known is None or known[0] != len(dataset.data):
        known = _dataset_buffers[dataset] = (len(dataset.data), buffers(dataset.data.values()))
    return known[1]
