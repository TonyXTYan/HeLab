import pytest
from collections import OrderedDict

# tests/test_cachingSetup.py

from helab.utils.cachingSetup import (
    load_cache_param,
    fnum,
    cache_status_string,
    CACHE_PARAMS_DEFAULTS,
    CACHE_PARAMS_OVERRIDE,
    caches
)


def test_load_cache_param_existing() -> None:
    params = load_cache_param('status_cache')
    assert isinstance(params, OrderedDict)
    # Check that some defaults or overrides are present
    assert 'statistics' in params
    assert 'size_limit' in params
    # Existing override
    if 'status_cache' in CACHE_PARAMS_OVERRIDE:
        for key in CACHE_PARAMS_OVERRIDE['status_cache'].keys():
            assert params[key] == CACHE_PARAMS_OVERRIDE['status_cache'][key]


def test_load_cache_param_nonexistent() -> None:
    params = load_cache_param('some_unknown_cache')
    assert isinstance(params, OrderedDict)
    # Should still have defaults
    for key in CACHE_PARAMS_DEFAULTS.keys():
        assert key in params


@pytest.mark.parametrize("value,expected", [
    (123,  "   123"),
    (999,  "   999"),
    (1234, "1.234K"),
    (123000, "123.0K"),
    (1234567, "1.235M"),
    (123456789000, "123.5G"),
])
def test_fnum(value: int, expected: str) -> None:
    assert fnum(value) == expected


def test_cache_status_string() -> None:
    status_str = cache_status_string()
    assert "Cache status:" in status_str
    for cache_name in caches.keys():
        assert cache_name in status_str
