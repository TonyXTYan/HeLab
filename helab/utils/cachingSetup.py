import hashlib
import json
import logging
from collections import OrderedDict
from typing import Dict, Any, Optional

import psutil
from diskcache import FanoutCache
from copy import deepcopy
from PyQt6.QtCore import QSettings

from helab.utils.constants import *
from helab.utils.loggingSetup import setup_logging


logging.debug("cachingSetup.py: Loading")

# Default cache parameters from diskcache
# https://github.com/grantjenks/python-diskcache/blob/master/diskcache/core.py
# diskcache_params = {
#     'statistics': True,
#     'size_limit': 2**30, # 1GB
#     'eviction_policy': 'least-recently-stored',
#     'sqlite_mmap_size': 2**27,   # 128MB
#     'disk_min_file_size': 2**16, # 64KB
# }


CACHE_PARAMS_DEFAULTS: OrderedDict[str, Any] = OrderedDict([
    ("statistics", True),
    ("eviction_policy", "least-recently-stored"),
    # ("sqlite_journal_mode", "memory"),
    ("sqlite_journal_mode", "wal"),
    ("size_limit", 1<<30),          # 1GB
    ("sqlite_mmap_size", 1<<20<<7), # 128MB
    ("sqlite_cache_size", 1<<10<<5),# 32,768 pages (~128MB)
    ("disk_min_file_size", 1<<20),  # 1MB
    # ("shards", 32),
    ("shards", 16),
    ("timeout", 0.200), # diskcache default is 0.010 seconds,
    ("sqlite_busy_timeout", 10), # seconds?
    ("cache_compression", True),
])
"""
The default cache parameters for all caches.
"""

CACHE_PARAMS_OVERRIDE: Dict[str, Dict[str, Any]] = {
    "status_cache": {
        "size_limit": 1<<30<<1, # 2GB
        #TODO increase RAM ?
    },
    "os_file_system_cache": {
    },
    "data_ram_cache": {
        "size_limit": 1<<30<<3, # 8GB,
        "sqlite_mmap_size": 1<<30<<0, # 1GB
        "sqlite_cache_size": 1<<10<<8, #  256K pages (~1GB)
        "disk_min_file_size": 1<<20<<3, # 8MB
        "tag_index": True,
    },
}
"""
The default cache parameters for each cache type.
"""

def load_cache_param(cache_name: str) -> OrderedDict[str, Any]:
    """
    Load the cache parameters from the settings.

    This function retrieves cache parameters for a given cache name. It first
    loads the default cache parameters and then overrides them with any
    specific parameters defined for the given cache name. Finally, it updates
    the parameters with values stored in the QSettings.

    :param cache_name: The name of the cache for which parameters are to be loaded.
    :type cache_name: str
    :return: An OrderedDict containing the cache parameters.
    :rtype: OrderedDict[str, Any]
    """
    settings = QSettings(QSETTINGS_ORG_NAME, QSETTINGS_APP_NAME)
    base_params = deepcopy(CACHE_PARAMS_DEFAULTS)

    for key, val in CACHE_PARAMS_OVERRIDE.get(cache_name, {}).items():
        base_params[key] = val

    logging.debug(f"load_cache_param: hardcode {cache_name = }, base_params = {json.dumps(base_params)}")
    for key, val in base_params.items():
        setting_path = f"cache_params/{cache_name}/{key}"
        base_params[key] = settings.value(setting_path, val)

    logging.debug(f"load_cache_param: loaded   {cache_name = } ,base_params = {json.dumps(base_params)}")
    return base_params


status_cache         = FanoutCache(DIR_CACHES + '/status_cache',      **load_cache_param('status_cache'))
os_file_system_cache = FanoutCache(DIR_CACHES + '/os_file_system_cache', **load_cache_param('os_file_system_cache'))
data_ram_cache       = FanoutCache(DIR_CACHES + '/data_ram_cache',    **load_cache_param('data_ram_cache'))

caches = OrderedDict([
    ('status_cache', status_cache),
    ('os_file_system_cache', os_file_system_cache),
    ('data_ram_cache', data_ram_cache),
])


def fnum(num: Optional[int]) -> str:
    """
    Format a number with a suffix for thousands, millions, etc.
    :param num: The number to format
    :return:    The formatted number

    e.g.

    - `fnum(123)`  -> `'   123'`
    - `fnum(1234)` -> `'1.234K'`
    - `fnum(123000)`  -> `'123.0K'`
    - `fnum(1234567)` -> `'1.235M'`
    - `fnum(123456789000)` -> `'123.5G'`
    """
    if num is None: return "NA"
    suffixes = ['K', 'M', 'G', 'T', 'P', 'E']
    for i, suffix in reversed(list(enumerate(suffixes, 1))):
        divisor = 1000 ** i
        if num >= divisor:
            val = num / divisor
            decimals = 3 if val < 10 else 2 if val < 100 else 1
            formatted = f"{val:.{decimals}f}{suffix}"
            return formatted.rjust(6)[-6:]
    return f"{num}".rjust(6)[-6:]


def cache_status_string() -> str:
    """
    Create a string with the status of all caches
    :return: The cache status string
    """
    cache_str = "Cache status:\n"
    max_len_cache_name = max(len(cache_name) for cache_name in caches.keys())
    for cache_name, cache in caches.items():
        hits, miss = cache.stats()
        size = cache.volume()
        spacer = " "*(max_len_cache_name-len(cache_name))
        cache_str += f"  {cache_name}: {spacer}hits = {fnum(hits)}, miss = {fnum(miss)}, size = {fnum(size)}B\n"
    return cache_str

def close_all_caches() -> None:
    """
    Close all caches
    """
    for cache in caches.values():
        cache.close()

# def custom_key_function(func, *args, **kwargs):
#     # Create a unique string representation of the function and its arguments
#     key_string = f"{func.__module__}.{func.__name__}:{args}:{kwargs}"
#     # Hash the string using SHA-256
#     # print(f"custom_key_function: {key_string = }, hash = {hashlib.sha256(key_string.encode()).hexdigest()}")
#     return hashlib.sha256(key_string.encode()).hexdigest()


