import logging
import os
from concurrent.futures import ThreadPoolExecutor, Future
# from logging import FATAL
from types import SimpleNamespace
from typing import Iterator, List, Any, cast, Callable, Dict

# import aiofiles

from helab.utils.cachingSetup import os_isdir_cache, os_listdir_cache, os_scandir_cache
from helab.utils.constants import OS_DIR_CACHE_TTL




def os_listdir(path: str, invalidate_cache:bool=False) -> List[str]:
    """
    List directory contents with optional cache invalidation.
    :param path: Directory path.
    :param invalidate_cache: Invalidate cache if True.
    :return: List of directory entry names.
    """

    if invalidate_cache:
        os_listdir_cache.pop(_os_listdir.__cache_key__(path))
    return _os_listdir(path)    # type: ignore[no-any-return]

@os_listdir_cache.memoize(expire=OS_DIR_CACHE_TTL)  # type: ignore[misc]
def _os_listdir(path: str) -> List[str]:
    with os.scandir(path) as entries:
        return [entry.name for entry in entries]
    # aiofiles.os.listdir(path)

def os_listdir_filtered(path: str, invalidate_cache:bool=False) -> List[str]:
    """
    List directory contents with optional cache invalidation.
    :param path: Directory path.
    :param invalidate_cache: Invalidate cache if True.
    :return: List of directory entries.
    """
    if invalidate_cache:
        os_listdir_cache.pop(_os_listdir_filtered.__cache_key__(path))
    return _os_listdir_filtered(path) # type: ignore[no-any-return]


@os_listdir_cache.memoize(expire=OS_DIR_CACHE_TTL)  # type: ignore[misc]
def _os_listdir_filtered(path: str) -> List[str]:
    return [
        entry for entry in os_listdir(path)
        if not entry.endswith('.txt')
           # and entry.startswith('')
           and entry not in ['cache', 'out', 'output', '.DS_Store']
    ]


def os_listdirdir(path: str, invalidate_cache:bool=False) -> List[str]:
    if invalidate_cache:
        os_listdir_cache.pop(_os_listdirdir.__cache_key__(path))
    return _os_listdirdir(path) # type: ignore[no-any-return]

@os_listdir_cache.memoize(expire=OS_DIR_CACHE_TTL)  # type: ignore[misc]
def _os_listdirdir(path: str) -> List[str]:
    # return [
    #     entry for entry in os_listdir(path)
    #     if os_isdir(os.path.join(path, entry))
    # ]
    with os.scandir(path) as entries:
        return [
            entry.name for entry in entries
            if entry.is_dir()
        ]


@os_scandir_cache.memoize(expire=OS_DIR_CACHE_TTL)  # type: ignore[misc]
def _os_scandir_dic(path: str) -> List[Dict[str, Any]]:
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

def os_scandir_dic(path: str, invalidate_cache:bool=False) -> List[Dict[str, Any]]:
    """
    Scan a directory and return a list of dictionaries with file information.
    Optionally invalidate the cache before scanning.
    :param path: Directory path.
    :param invalidate_cache: Invalidate cache if True.
    :return: List of dictionaries with file information.
    """
    
    if invalidate_cache:
        os_scandir_cache.pop(_os_scandir_dic.__cache_key__(path))
    return _os_scandir_dic(path) # type: ignore[no-any-return]

@os_scandir_cache.memoize(expire=OS_DIR_CACHE_TTL)  # type: ignore[misc]
def _os_scandir_sns(path: str) -> List[SimpleNamespace]:
    return [
        SimpleNamespace(
            name=entry.name,
            path=entry.path,
            is_dir=entry.is_dir(),
            is_file=entry.is_file(),
            is_symlink=entry.is_symlink(),
            stat=SimpleNamespace(
                st_mode=entry.stat().st_mode,
                st_ino=entry.stat().st_ino,
                st_dev=entry.stat().st_dev,
                st_nlink=entry.stat().st_nlink,
                st_uid=entry.stat().st_uid,
                st_gid=entry.stat().st_gid,
                st_size=entry.stat().st_size,
                st_atime=entry.stat().st_atime,
                st_mtime=entry.stat().st_mtime,
                st_ctime=entry.stat().st_ctime,
            ),
        )
        for entry in os.scandir(path)
    ]

def os_scandir_sns(path: str, invalidate_cache:bool=False) -> List[SimpleNamespace]:
    if invalidate_cache:
        os_scandir_cache.pop(_os_scandir_sns.__cache_key__(path))
    return _os_scandir_sns(path) # type: ignore[no-any-return]


@os_isdir_cache.memoize(expire=OS_DIR_CACHE_TTL)    # type: ignore[misc]
def _os_isdir(path: str) -> bool:
    return os.path.isdir(path)

def os_isdir(path: str, invalidate_cache:bool=False) -> bool:
    """
    Check if a path is a directory, with optional cache invalidation.
    :param path: Directory path.
    :param invalidate_cache: Invalidate cache if True.
    :return: True if directory, False otherwise.
    """

    if invalidate_cache:
        os_isdir_cache.pop(_os_isdir.__cache_key__(path))
    return _os_isdir(path) # type: ignore[no-any-return]


