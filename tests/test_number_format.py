import pytest

from helab.utils.number_format import fnum


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


@pytest.mark.parametrize("value,expected", [
    (850, "850 B"),
    (999, "999 B"),
    (1000, "1.0 kB"),
    (706_000_000, "706 MB"),
    (1_200_000_000, "1.2 GB"),
    (8 * 10**9, "8.0 GB"),
    (8 << 30, "8.6 GB"),  # (An old saved 8 GiB budget.)
])
def test_byte_size_is_si(value: int, expected: str) -> None:
    """Tony (2026-10-26, C-14): sizes in SI units, powers of 1000, as the rates."""
    from helab.utils.number_format import byte_size
    assert byte_size(value) == expected


@pytest.mark.parametrize("seconds,expected", [
    (42.9, "42 s"), (725, "12 min 5 s"), (4512, "1 h 15 min"), (2 * 86400 + 5 * 3600, "2 d 5 h")])
def test_duration_has_an_hour_unit(seconds: float, expected: str) -> None:
    """Tony (2026-10-26, C-14): ``duration`` gains an hour unit (it said "75 min 12 s")."""
    from helab.utils.time_format import duration
    assert duration(seconds) == expected
