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
