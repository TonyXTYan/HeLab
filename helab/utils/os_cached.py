import logging
import os
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Iterator, List, Any, cast, Callable, Dict

from helab.utils.cachingSetup import os_isdir_cache, os_listdir_cache, os_scandir_cache
from helab.utils.constants import OS_DIR_CACHE_TTL

# import cachetools
import diskcache
# import threading
# import asyncio

# from cachetools import TTLCache

# from joblib import Memory
# joblib_memory = Memory(DIR_CACHES, verbose=0)


# from dogpile.cache import make_region
# region = make_region().configure(
#     'dogpile.cache.memory',
#     expiration_time=60,
# )

# # @region.cache_on_arguments()
# def os_listdir(path: str) -> list[str]:
#     return os.listdir(path)
#
# # @region.cache_on_arguments()
# def os_scandir(path: str) -> Iterator[os.DirEntry[Any]]:
#     return os.scandir(path)
#
# # @region.cache_on_arguments()
# def os_isdir(path: str) -> bool:
#     return os.path.isdir(path)



# executor = ThreadPoolExecutor(max_workers=8)

# os_listdir_cache: TTLCache[str, List[str]] = cachetools.TTLCache(maxsize=10*1000, ttl=OS_DIR_CACHE_TTL)
# # os_scandir_cache: TTLCache[str, Iterator[os.DirEntry[Any]]] = cachetools.TTLCache(maxsize=100*1000, ttl=60)
# os_scandir_cache:TTLCache[str, List[os.DirEntry[Any]]] = TTLCache(maxsize=100*1000, ttl=OS_DIR_CACHE_TTL)
# os_isdir_cache: TTLCache[str, bool] = cachetools.TTLCache(maxsize=1000*1000, ttl=OS_DIR_CACHE_TTL)
#
# # os_listdir_lock = threading.Lock()
# # os_scandir_lock = threading.Lock()
# # os_scandir_lock_list = threading.Lock()
# # os_isdir_lock = threading.Lock()
#
# @cachetools.cached(os_listdir_cache, lock=threading.Lock(), info=True)
# def os_listdir(path: str) -> List[str]:
#     return os.listdir(path)
#
# # @cachetools.cached(os_scandir_cache, lock=os_scandir_lock)
# def os_scandir(path: str) -> Iterator[os.DirEntry[Any]]:
#     # return os.scandir(path)
#     return iter(os_scandir_list(path))
#
# @cachetools.cached(os_scandir_cache, lock=threading.Lock(), info=True)
# def os_scandir_list(path: str) -> List[os.DirEntry[Any]]:
#     return list(os.scandir(path))
#
# @cachetools.cached(os_isdir_cache, lock=threading.Lock(), info=True)
# def os_isdir(path: str) -> bool:
#     return os.path.isdir(path)
#
# # Wrapper functions to run the cached functions in a separate thread
# def os_listdir_async(path: str) -> Future[List[str]]:
#     return executor.submit(os_listdir, path)
#
# # async def os_scandir_async(path: str) -> Future:
# #     loop = asyncio.get_event_loop()
# #     return await loop.run_in_executor(executor, os_scandir, path)
# #     # return executor.submit(os_scandir, path)'
#
# def os_scandir_async(path: str) -> Future[Iterator[os.DirEntry[Any]]]:
#     return executor.submit(os_scandir, path)
#     # return executor.submit(os_scandir, path)'
#
# def os_isdir_async(path: str) -> Future[bool]:
#     return executor.submit(os_isdir, path)



# @cachetools.cached(os_listdir_cache)
# def os_listdir(path: str) -> list[str]:
#     with os_listdir_lock:
#         return os.listdir(path)
#
# @cachetools.cached(os_scandir_cache)
# def os_scandir(path: str) -> Iterator[os.DirEntry[Any]]:
#     with os_scandir_lock:
#         return os.scandir(path)
#
# @cachetools.cached(os_isdir_cache)
# def os_isdir(path: str) -> bool:
#     with os_isdir_lock:
#         return os.path.isdir(path)



# @joblib_memory.cache
# # @cachetools.cached(os_listdir_cache)
# def os_listdir(path: str) -> list[str]:
#     with os_listdir_lock:
#         return os.listdir(path)
#
# @joblib_memory.cache
# # @cachetools.cached(os_scandir_cache)
# def os_scandir(path: str) -> Iterator[os.DirEntry[Any]]:
#     with os_scandir_lock:
#         return os.scandir(path)
#
# @joblib_memory.cache
# # @cachetools.cached(os_isdir_cache)
# def os_isdir(path: str) -> bool:
#     with os_isdir_lock:
#         return os.path.isdir(path)



@os_listdir_cache.memoize(expire=OS_DIR_CACHE_TTL)  # type: ignore[misc]
def os_listdir(path: str) -> List[str]:
    return os.listdir(path)

# os_listdir = cast(Callable[[str], List[str]], os_listdir)

# @os_scandir_cache.memoize(expire=OS_DIR_CACHE_TTL)
# def os_scandir(path: str) -> Iterator[os.DirEntry[Any]]:
#     return os.scandir(path)

@os_scandir_cache.memoize(expire=OS_DIR_CACHE_TTL)  # type: ignore[misc]
def os_scandir(path: str) -> List[Dict[str, Any]]:
    return [
        {
            'name': entry.name,
            'path': entry.path,
            'is_dir': entry.is_dir(),
            'is_file': entry.is_file(),
            'is_symlink': entry.is_symlink(),
            'stat': {
                'st_mode': entry.stat().st_mode,
                'st_ino': entry.stat().st_ino,
                'st_dev': entry.stat().st_dev,
                'st_nlink': entry.stat().st_nlink,
                'st_uid': entry.stat().st_uid,
                'st_gid': entry.stat().st_gid,
                'st_size': entry.stat().st_size,
                'st_atime': entry.stat().st_atime,
                'st_mtime': entry.stat().st_mtime,
                'st_ctime': entry.stat().st_ctime,
            },
        }
        for entry in os.scandir(path)
    ]


@os_isdir_cache.memoize(expire=OS_DIR_CACHE_TTL)    # type: ignore[misc]
def os_isdir(path: str) -> bool:
    return os.path.isdir(path)




# def os_listdir(path: str) -> List[str]:
#     if path in os_listdir_cache:
#         return os_listdir_cache[path]
#     else:
#         result = os.listdir(path)
#         os_listdir_cache[path] = result
#         return result
#
# def os_scandir(path: str) -> Iterator[os.DirEntry[Any]]:
#     logging.debug(f"os_scandir: {path}, {path in os_scandir_cache}")
#     if path in os_scandir_cache:
#         return iter(os_scandir_cache[path])
#     else:
#         result = os.scandir(path)
#         os_scandir_cache[path] = list(result)
#         return result
#
# def os_isdir(path: str) -> bool:
#     if path in os_isdir_cache:
#         return os_isdir_cache[path]
#     else:
#         result = os.path.isdir(path)
#         os_isdir_cache[path] = result
#         return result