from pathlib import Path

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


@pytest.mark.parametrize("platform", ["darwin", "linux"])
@pytest.mark.parametrize("value,expected", [
    (850, "850 B"),
    (999, "999 B"),
    (1000, "1.0 kB"),
    (706_000_000, "706 MB"),
    (1_200_000_000, "1.2 GB"),
    (8 * 10**9, "8.0 GB"),
    (8 << 30, "8.6 GB"),  # (8 GiB, Windows' default budget.)
    (2 * 10**15, "2000 TB"),
])
def test_disk_sizes_are_si_on_macos_and_linux(platform: str, value: int, expected: str) -> None:
    """Q26.1: sizes on disk in SI units (powers of 1000) on macOS and Linux, as the rates."""
    from helab.utils.number_format import byte_size
    assert byte_size(value, "disk", platform=platform) == expected


@pytest.mark.parametrize("value,expected", [
    (850, "850 B"),
    (999, "999 B"),
    (1000, "1.0 KiB"),  # (Past 999.5 the next unit, as in SI: three digits at most.)
    (1024, "1.0 KiB"),
    (706 << 20, "706 MiB"),
    (1_200_000_000, "1.1 GiB"),
    (8 * 10**9, "7.5 GiB"),  # (8 GB, macOS's and Linux's default budget.)
    (8 << 30, "8.0 GiB"),
    (100 << 30, "100 GiB"),
    (2 << 50, "2048 TiB"),
])
def test_disk_sizes_are_binary_on_windows_and_ram_everywhere(value: int, expected: str) -> None:
    """Q26.1: powers of 1024 labelled KiB/MiB/GiB ("so it's clear") for sizes on disk on Windows,
    and for RAM on every OS."""
    from helab.utils.number_format import byte_size
    assert byte_size(value, "disk", platform="win32") == expected
    for platform in ("darwin", "linux", "win32", None):
        assert byte_size(value, "ram", platform=platform) == expected


def test_units_follow_the_platform_helab_runs_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """``sys.platform`` unless HELAB_UNITS_PLATFORM_OVERRIDE names another; the tests pin macOS's
    (conftest), and a call without ``platform`` takes ``PLATFORM``."""
    import sys
    from helab.utils import number_format
    from helab.utils.number_format import UNITS_PLATFORM_OVERRIDE, byte_size, byte_unit, units_platform
    assert units_platform({}) == sys.platform
    assert units_platform({UNITS_PLATFORM_OVERRIDE: "win32"}) == "win32"
    assert units_platform({UNITS_PLATFORM_OVERRIDE: ""}) == sys.platform
    assert number_format.PLATFORM == "darwin" and byte_size(8 << 30, "disk") == "8.6 GB"
    monkeypatch.setattr(number_format, "PLATFORM", "win32")
    assert byte_size(8 << 30, "disk") == "8.0 GiB" and byte_unit(3, "disk") == (1 << 30, "GiB")
    assert byte_unit(2, "disk", "linux") == (10**6, "MB") and byte_unit(3, "ram", "darwin") == (1 << 30, "GiB")


@pytest.mark.parametrize("seconds,expected", [
    (42.9, "42 s"), (725, "12 min 5 s"), (4512, "1 h 15 min"), (2 * 86400 + 5 * 3600, "2 d 5 h")])
def test_duration_has_an_hour_unit(seconds: float, expected: str) -> None:
    """Tony (2026-10-26, C-14): ``duration`` gains an hour unit (it said "75 min 12 s")."""
    from helab.utils.time_format import duration
    assert duration(seconds) == expected


# Run in a fresh interpreter: the disk budget's default and minimum, and the log sizes, are set when
# helab is imported, so patching ``number_format.PLATFORM`` can't reach them.
IMPORT_TIME_UNITS = """
import json, sys
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
from helab.utils import app_log, constants, number_format
from helab.utils.settings_defaults import DISK_BUDGET_SETTING, setting_default
from helab.views.CacheTab import CacheTab
app = QApplication([])
settings = QSettings(sys.argv[1], QSettings.Format.IniFormat)
settings.setValue(DISK_BUDGET_SETTING, 10**9)  # 1 GB: the old minimum, under Windows' 1 GiB.
read = constants.read_disk_budget(settings)
tab = CacheTab(None, settings)
shown = (tab.disk_budget.minimum(), tab.disk_budget.suffix(), tab.disk_budget.value())
applied = tab.apply_budget()
tab.save(settings)
print(json.dumps({"platform": number_format.PLATFORM, "min": constants.MIN_DISK_BUDGET,
                  "default": constants.DEFAULT_DISK_BUDGET, "row": setting_default(DISK_BUDGET_SETTING),
                  "min_ram": constants.MIN_RAM_BUDGET, "read": read, "shown": shown, "applied": applied,
                  "saved": int(settings.value(DISK_BUDGET_SETTING)), "mb": [app_log.MB, app_log.MB_UNIT]}))
"""


@pytest.mark.parametrize("override", ["win32", "darwin", None])
def test_units_set_at_import_follow_the_platform(override: str | None, tmp_path: Path) -> None:
    """Q26.1 in a fresh interpreter, with Windows' units (override ``win32``), macOS's, and this OS's
    own (no override: ``sys.platform``, so Windows CI runs Windows' units here). Windows: 8 GiB by
    default, at least 1 GiB, logs in MiB; a stored 1 GB reads as 1 GiB and the next Save writes it
    (the minimum, Q26.1 (c)). RAM's minimum is 1 GiB everywhere."""
    import json
    import os
    import subprocess
    import sys
    from helab.utils.number_format import UNITS_PLATFORM_OVERRIDE
    env = dict(os.environ)  # (conftest's private folders and offscreen Qt.)
    env.pop(UNITS_PLATFORM_OVERRIDE, None)
    if override is not None:
        env[UNITS_PLATFORM_OVERRIDE] = override
    done = subprocess.run([sys.executable, "-c", IMPORT_TIME_UNITS, str(tmp_path / "settings.ini")], env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    found = json.loads(done.stdout.strip().splitlines()[-1])
    platform = override or sys.platform
    assert found["platform"] == platform and found["min_ram"] == 1 << 30
    if platform == "win32":
        assert found["min"] == 1 << 30 and found["default"] == found["row"] == 8 << 30
        assert found["read"] == 1 << 30 and found["shown"] == [1.0, " GiB", 1.0]
        assert found["applied"] is True and found["saved"] == 1 << 30  # (Rewritten to the minimum.)
        assert found["mb"] == [1 << 20, "MiB"]
    else:
        assert found["min"] == 10**9 and found["default"] == found["row"] == 8 * 10**9
        assert found["read"] == 10**9 and found["shown"] == [1.0, " GB", 1.0]
        assert found["applied"] is True and found["saved"] == 10**9  # (Kept: the minimum here.)
        assert found["mb"] == [10**6, "MB"]
