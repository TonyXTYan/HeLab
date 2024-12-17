import os
from typing import Iterator, List, Any

import cachetools
import threading

from cachetools import TTLCache

os_listdir_cache: TTLCache[str, List[str]] = cachetools.TTLCache(maxsize=10*1000, ttl=60*60*24)
os_scandir_cache: TTLCache[str, Iterator[os.DirEntry[Any]]] = cachetools.TTLCache(maxsize=10*1000, ttl=60*60*24)
os_isdir_cache: TTLCache[str, bool] = cachetools.TTLCache(maxsize=1000*1000, ttl=60*60*24)

os_listdir_lock = threading.Lock()
os_scandir_lock = threading.Lock()
os_isdir_lock = threading.Lock()

@cachetools.cached(os_listdir_cache)
def os_listdir(path: str) -> list[str]:
    with os_listdir_lock:
        return os.listdir(path)

@cachetools.cached(os_scandir_cache)
def os_scandir(path: str) -> Iterator[os.DirEntry[Any]]:
    with os_scandir_lock:
        return os.scandir(path)

@cachetools.cached(os_isdir_cache)
def os_isdir(path: str) -> bool:
    with os_isdir_lock:
        return os.path.isdir(path)