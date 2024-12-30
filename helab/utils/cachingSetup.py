import hashlib
import json
import logging
from collections import OrderedDict
from typing import Dict, Any

import psutil
from diskcache import FanoutCache
from copy import deepcopy
from PyQt6.QtCore import QSettings

from helab.utils.constants import DIR_CACHES
from helab.utils.loggingSetup import setup_logging

# logging.basicConfig(level=logging.DEBUG)

# setup_logging()

logging.debug("cachingSetup.py: Loading")
# logging.debug(f"Page Size {psutil.virtual_memory().get}")

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
    ("sqlite_journal_mode", "memory"),
    ("size_limit", 2**30),          # 1GB
    ("sqlite_mmap_size", 2**27),    # 128MB
    ("sqlite_cache_size", 2**15),   # 32,768 pages (~128MB)
    ("disk_min_file_size", 2**16),  # 64KB
    ("shards", 32),
])

CACHE_PARAMS_OVERRIDE: Dict[str, Dict[str, Any]] = {
    "status_cache": {
        "size_limit": 1<<30<<1, # 2GB
    },
    "hasChildren_cache": {
    },
    "os_listdir_cache": {
    },
    "os_scandir_cache": {
    },
    "os_isdir_cache": {
    },
    "data_ram_cache": {
        "size_limit": 1<<30<<3, # 8GB,
        "sqlite_mmap_size": 1<<30<<2, # 4GB
        "sqlite_cache_size": 1<<18, # 1-4GB (256K pages)
        "disk_min_file_size": 1<<20, # 1MB
        "tag_index": True,
    },
}


# CACHE_PARAMS_OVERRIDE = OrderedDict([
#     ("status_cache", {
#         "size_limit": 2**31, # 2GB
#     }),
#     ("hasChildren_cache", {
#     }),
#     ("os_listdir_cache", {
#     }),
#     ("os_scandir_cache", {
#     }),
#     ("os_isdir_cache", {
#     }),
# ])

# def load_cache_params(cache_name: str) -> dict:
#     # Load final merged params from QSettings:
#     # 1) Start with DEFAULT_CACHE_PARAMS
#     # 2) Apply any local OVERRIDES
#     # 3) Apply user overrides from QSettings
#
#     settings = QSettings("ANU", "HeLab")
#     base_params = deepcopy(CACHE_PARAMS_DEFAULTS)
#
#     # Merge in local overrides
#     override_params = CACHE_PARAMS_OVERRIDE.get(cache_name, {})
#     for k, v in override_params.items():
#         base_params[k] = v
#
#     # Now override from user’s QSettings
#     group_key = f"cache_params/{cache_name}"
#     for param_key, default_val in base_params.items():
#         setting_path = f"{group_key}/{param_key}"
#         # we check type to ensure we read from QSettings with correct type
#         if isinstance(default_val, bool):
#             val = settings.value(setting_path, default_val, type=bool)
#         elif isinstance(default_val, int):
#             val = settings.value(setting_path, default_val, type=int)
#         elif isinstance(default_val, str):
#             val = settings.value(setting_path, default_val, type=str)
#         else:
#             val = settings.value(setting_path, default_val)
#             logging.warning(f"load_cache_params: Unknown type for {param_key = }, {type(default_val) = }")
#         base_params[param_key] = val
#
#     return base_params
#
# def build_all_caches() -> OrderedDict[str, FanoutCache]:
#     # Build and return an OrderedDict of all caches, one entry per cache_name.
#     cache_dict = OrderedDict()
#     for cache_name in CACHE_PARAMS_OVERRIDE.keys():
#         params = load_cache_params(cache_name)
#         cache_path = f"{DIR_CACHES}/{cache_name}"
#         logging.debug(f"build_all_caches: {cache_name = }, {cache_path = }, {params = }")
#         cache_dict[cache_name] = FanoutCache(cache_path, **params)
#     return cache_dict


def load_cache_param(cache_name: str) -> OrderedDict[str, Any]:
    settings = QSettings("ANU", "HeLab")
    base_params = deepcopy(CACHE_PARAMS_DEFAULTS)

    for key, val in CACHE_PARAMS_OVERRIDE.get(cache_name, {}).items():
        base_params[key] = val

    logging.debug(f"load_cache_param: hardcode {cache_name = }, base_params = {json.dumps(base_params)}")
    for key, val in base_params.items():
        setting_path = f"cache_params/{cache_name}/{key}"
        # logging.debug(f"load_cache_param: {setting_path} = {settings.value(setting_path, val)}")
        # if isinstance(val, bool):
        #     base_params[key] = settings.value(setting_path, val, type=bool)
        # elif isinstance(val, int):
        #     base_params[key] = settings.value(setting_path, val, type=int)
        # elif isinstance(val, str):
        #     base_params[key] = settings.value(setting_path, val, type=str)
        # else:
        #     base_params[key] = settings.value(setting_path, val)
        #     logging.warning(f"load_cache_param: Unknown type for {key = }, {type(val) = }")
        base_params[key] = settings.value(setting_path, val)

    logging.debug(f"load_cache_param: loaded   {cache_name = } ,base_params = {json.dumps(base_params)}")
    return base_params


# status_cache = FanoutCache(DIR_CACHES + '/status_cache', **diskcache_params)
# hasChildren_cache = FanoutCache(DIR_CACHES + '/hasChildren_cache', **diskcache_params)
# os_listdir_cache = FanoutCache(DIR_CACHES + '/os_listdir_cache', **diskcache_params)
# os_scandir_cache = FanoutCache(DIR_CACHES + '/os_scandir_cache', **diskcache_params)
# os_isdir_cache   = FanoutCache(DIR_CACHES + '/os_isdir_cache', **diskcache_params)

status_cache      = FanoutCache(DIR_CACHES + '/status_cache',      **load_cache_param('status_cache'))
hasChildren_cache = FanoutCache(DIR_CACHES + '/hasChildren_cache', **load_cache_param('hasChildren_cache'))
os_listdir_cache  = FanoutCache(DIR_CACHES + '/os_listdir_cache',  **load_cache_param('os_listdir_cache'))
os_scandir_cache  = FanoutCache(DIR_CACHES + '/os_scandir_cache',  **load_cache_param('os_scandir_cache'))
os_isdir_cache    = FanoutCache(DIR_CACHES + '/os_isdir_cache',    **load_cache_param('os_isdir_cache'))
data_ram_cache    = FanoutCache(DIR_CACHES + '/data_ram_cache',    **load_cache_param('data_ram_cache'))

caches = OrderedDict([
    ('status_cache', status_cache),
    ('hasChildren_cache', hasChildren_cache),
    ('os_scandir_cache', os_scandir_cache),
    ('os_listdir_cache', os_listdir_cache),
    ('os_isdir_cache', os_isdir_cache),
    ('data_ram_cache', data_ram_cache),
])

# caches = build_all_caches()
#
# status_cache = caches['status_cache']
# hasChildren_cache = caches['hasChildren_cache']
# os_listdir_cache = caches['os_listdir_cache']
# os_scandir_cache = caches['os_scandir_cache']
# os_isdir_cache = caches['os_isdir_cache']



def fnum(num: int) -> str:
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
    cache_str = "Cache status:\n"
    max_len_cache_name = max(len(cache_name) for cache_name in caches.keys())
    for cache_name, cache in caches.items():
        hits, miss = cache.stats()
        size = cache.volume()
        spacer = " "*(max_len_cache_name-len(cache_name))
        cache_str += f"  {cache_name}: {spacer}hits = {fnum(hits)}, miss = {fnum(miss)}, size = {fnum(size)}B\n"
    return cache_str




# def custom_key_function(func, *args, **kwargs):
#     # Create a unique string representation of the function and its arguments
#     key_string = f"{func.__module__}.{func.__name__}:{args}:{kwargs}"
#     # Hash the string using SHA-256
#     # print(f"custom_key_function: {key_string = }, hash = {hashlib.sha256(key_string.encode()).hexdigest()}")
#     return hashlib.sha256(key_string.encode()).hexdigest()