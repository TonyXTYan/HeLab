import json
import logging
from collections import OrderedDict
from typing import Dict, Any, Optional

import psutil
from diskcache import FanoutCache
from copy import deepcopy
from PyQt6.QtCore import QSettings

from helab.utils.constants import *


logging.debug("caching_setup.py: Loading")

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
    # Off: with statistics on, every read is a write transaction that can time out
    # and silently answer "nothing saved".
    ("statistics", False),
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

def load_cache_param(cache_name: str, settings: QSettings | None = None) -> OrderedDict[str, Any]:
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
    if settings is None:
        settings = QSettings(QSETTINGS_ORG_NAME, QSETTINGS_APP_NAME)
    base_params = deepcopy(CACHE_PARAMS_DEFAULTS)

    for key, val in CACHE_PARAMS_OVERRIDE.get(cache_name, {}).items():
        base_params[key] = val

    logging.debug(f"load_cache_param: hardcode {cache_name = }, base_params = {json.dumps(base_params)}")
    for key, val in base_params.items():
        setting_path = f"cache_params/{cache_name}/{key}"
        base_params[key] = settings.value(setting_path, val)
    # Never from saved settings, which may still hold the old default.
    base_params["statistics"] = False

    logging.debug(f"load_cache_param: loaded   {cache_name = } ,base_params = {json.dumps(base_params)}")
    return base_params


# Read only by Settings' old Cache tab, until S7 rebuilds it (roadmaps/cache-storage-and-settings.md).
data_ram_cache = FanoutCache(DIR_CACHES + '/data_ram_cache', **load_cache_param('data_ram_cache'))

caches = OrderedDict([
    ('data_ram_cache', data_ram_cache),
])
