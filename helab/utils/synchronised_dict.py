# https://github.com/B3W/Synchronized-Dict/tree/master
# https://github.com/B3W/Synchronized-Dict/blob/master/synchronized_dict.py
# MIT License
#
# Copyright (c) 2019 Weston Berg
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


# Modified by: Tony Yan (assisted ChatGPT-4o)

import collections.abc
import threading
from typing import Any, Iterator, Optional, Type, TypeVar

KT = TypeVar("KT")  # Key type
VT = TypeVar("VT")  # Value type


class SynchronisedDict(collections.abc.MutableMapping[KT, VT]):
    """
    Class representing a simple, synchronized dictionary.
    """
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._map: dict[KT, VT] = {}  # Structure for storing data
        self._lock = threading.RLock()  # Access lock
        self.update(*args, **kwargs)

    @classmethod
    def fromkeys(cls: Type["SynchronisedDict[KT, VT]"],
                 iterable: Iterator[KT],
                 value: Optional[VT] = None) -> "SynchronisedDict[KT, VT]":
        sync_dict = cls()
        sync_dict._map = dict.fromkeys(iterable, value)  # type: ignore
        return sync_dict

    def __getitem__(self, key: KT) -> VT:
        with self._lock:
            return self._map[key]

    def __setitem__(self, key: KT, value: VT) -> None:
        with self._lock:
            self._map[key] = value

    def __delitem__(self, key: KT) -> None:
        with self._lock:
            del self._map[key]

    def __iter__(self) -> Iterator[KT]:
        with self._lock:
            return iter(self._map)

    def __len__(self) -> int:
        with self._lock:
            return len(self._map)

    def __str__(self) -> str:
        with self._lock:
            return str(self._map)

    def update(self, *args: Any, **kwargs: Any) -> None:
        with self._lock:
            self._map.update(*args, **kwargs)
