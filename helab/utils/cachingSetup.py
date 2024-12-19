import diskcache

from helab.utils.constants import DIR_CACHES


# https://github.com/grantjenks/python-diskcache/blob/master/diskcache/core.py
diskcache_params = {
    'statistics': True,
    'size_limit': 2**30, # 1GB
    'eviction_policy': 'least-recently-stored',
    'sqlite_mmap_size': 2**27,   # 128MB
    'disk_min_file_size': 2**16, # 64KB
}

os_listdir_cache = diskcache.FanoutCache(DIR_CACHES + '/os_listdir_cache', **diskcache_params)
os_scandir_cache = diskcache.FanoutCache(DIR_CACHES + '/os_scandir_cache', **diskcache_params)
os_isdir_cache   = diskcache.FanoutCache(DIR_CACHES + '/os_isdir_cache', **diskcache_params)


status_cache = diskcache.FanoutCache(DIR_CACHES + '/status_cache', **diskcache_params)
hasChildren_cache = diskcache.FanoutCache(DIR_CACHES + '/hasChildren_cache', **diskcache_params)


def cache_status_stirng() -> str:
    cache_str = "Cache status:\n"
    # cache_str += f"  tab_widget.status_cache:      {len(self.tab_widget.status_cache)} items\n"
    # cache_str += f"  tab_widget.hasChildren_cache: {len(self.tab_widget.hasChildren_cache)} items\n"
    status_cache_stats = status_cache.stats()
    hasChildren_cache_stats = hasChildren_cache.stats()
    os_listdir_cache_stats = os_listdir_cache.stats()
    os_scandir_cache_stats = os_scandir_cache.stats()
    os_isdir_cache_stats = os_isdir_cache.stats()
    status_cache_sizes = status_cache.volume() / 1000 / 1000  # MB
    hasChildren_cache_sizes = hasChildren_cache.volume() / 1000 / 1000  # MB
    os_listdir_cache_sizes = os_listdir_cache.volume() / 1000 / 1000  # MB
    os_scandir_cache_sizes = os_scandir_cache.volume() / 1000 / 1000  # MB
    os_isdir_cache_sizes = os_isdir_cache.volume() / 1000 / 1000  # MB
    cache_str += f"  status_cache:      hits = {status_cache_stats[0]:<6}, miss = {status_cache_stats[1]:<6}, size = {status_cache_sizes:<6.2f} MB\n"
    cache_str += f"  hasChildren_cache: hits = {hasChildren_cache_stats[0]:<6}, miss = {hasChildren_cache_stats[1]:<6}, size = {hasChildren_cache_sizes:<6.2f} MB\n"
    cache_str += f"  os_listdir_cache:  hits = {os_listdir_cache_stats[0]:<6}, miss = {os_listdir_cache_stats[1]:<6}, size = {os_listdir_cache_sizes:<6.2f} MB\n"
    cache_str += f"  os_scandir_cache:  hits = {os_scandir_cache_stats[0]:<6}, miss = {os_scandir_cache_stats[1]:<6}, size = {os_scandir_cache_sizes:<6.2f} MB\n"
    cache_str += f"  os_isdir_cache:    hits = {os_isdir_cache_stats[0]:<6}, miss = {os_isdir_cache_stats[1]:<6}, size = {os_isdir_cache_sizes:<6.2f} MB\n"
    return cache_str