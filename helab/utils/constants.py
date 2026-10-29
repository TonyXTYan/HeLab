import os
import sys
import tempfile
import logging
from typing import TYPE_CHECKING, List
from helab._version import __version__
from helab.build_info import get_build_info

from typing import Optional

from PyQt6.QtCore import QSettings, QDir
from helab.utils.settings_store import app_settings
# Settings' keys (re-exported: they were defined here) and defaults: helab/utils/settings_defaults.py.
from helab.utils.settings_defaults import (
    AUTO_SCAN_VISIBLE_SETTING as AUTO_SCAN_VISIBLE_SETTING,
    CHECK_LEVEL_SETTING as CHECK_LEVEL_SETTING,
    CONVERT_BACKEND_SETTING as CONVERT_BACKEND_SETTING,
    CONVERT_OUTPUT_SETTING as CONVERT_OUTPUT_SETTING,
    CONVERT_PROFILE_SETTING as CONVERT_PROFILE_SETTING,
    DIR_CACHES_SETTING as DIR_CACHES_SETTING,
    DIR_TEMPS_SETTING as DIR_TEMPS_SETTING,
    DISK_BUDGET_SETTING as DISK_BUDGET_SETTING,
    LIVE_AUTOSAVE_SETTING as LIVE_AUTOSAVE_SETTING,
    LIVE_INTERVAL_SETTING as LIVE_INTERVAL_SETTING,
    LOAD_MODE_SETTING as LOAD_MODE_SETTING,
    PLOT_AUTO_RELOAD_SETTING as PLOT_AUTO_RELOAD_SETTING,
    RAM_BUDGET_SETTING as RAM_BUDGET_SETTING,
    SIMULTANEOUS_IO_SETTING as SIMULTANEOUS_IO_SETTING,
    TXY_SOURCE_SETTING as TXY_SOURCE_SETTING,
    CONVERT_OUTPUTS, LOG_KEEP_SETTING, read_setting, setting_default)
if TYPE_CHECKING:
    from helab.convert.profile import DetectorProfile
# from PyQt6.QtGui import QFontDatabase, QFont

# try:
#     helab_mono_font = QFont("SF Mono", 12)
# except:
#     helab_mono_font = QFont("Monospace", 12)

TOOLBAR_STYLESHEET_LR = """
    QToolBar {
        spacing: 5px;
        padding: 2px;
    }
    """

QDOCKWIDGET_STYLESHEET = """
    QDockWidget {
        background: #f0f0f0;  /* Light gray background */
        border: 0px solid #cccccc;  /* Light gray border */
    }
    QDockWidget::title {
        background: #e0e0e0;  /* Slightly darker gray for the title */
        padding: 2px;
    }
    QDockWidget::close-button, QDockWidget::float-button {
        border: none;
        background: transparent;
    }
    QDockWidget::close-button:hover, QDockWidget::float-button:hover {
        background: #d0d0d0;  /* Darker gray when hovered */
    }
    QDockWidget:hover {
        border: 1px solid #000000;  /* Black border when hovered */
    }
    """
QSPLITTER_STYLESHEET = """
    QSplitter::handle {
        background: #d8d8d8;  /* Light gray background for the handle */
    }
    QSplitter::handle:horizontal {
        width: 4px;
    }
    QSplitter::handle:vertical {
        height: 4px;
    }
    QSplitter::handle:hover {
        background: #000000;  /* Darker gray when hovered */
    }
"""


APP_BUILD_INFO = get_build_info()


def get_version() -> str:
    """Return the package version, independent of the launch directory."""
    return __version__

def get_git_commit_hash() -> str:
    """Return the embedded build commit, or this package's checkout commit."""
    return APP_BUILD_INFO.short_commit

APP_VERSION = get_version()
APP_COMMIT_HASH = get_git_commit_hash()


# What happens to a folder's load when another folder is selected.
LOAD_MODE_LABELS = {"cancel": "Cancel the current load",
                    "finish": "Finish the current load in the background",
                    "queue": "Queue folders kept selected for 3 s"}
DEFAULT_LOAD_MODE: str = setting_default(LOAD_MODE_SETTING)

# How much the quick check of a folder's cached data (folder not modified since it was
# cached) also checks of its TXY files' sizes and times; Full lists the folder every time.
CHECK_LEVEL_LABELS = {"swift": "Swift: the last file",
                      "fast": "Fast: the first and last files",
                      "medium": "Medium: first, last and at least 3 random files (1%)",
                      "high": "High: first, last and at least 10 random files (3%)",
                      "full": "Full: every file (lists the folder)"}
DEFAULT_CHECK_LEVEL: str = setting_default(CHECK_LEVEL_SETTING)

DEFAULT_SIMULTANEOUS_IO: int = setting_default(SIMULTANEOUS_IO_SETTING)
MAX_SIMULTANEOUS_IO = 32


# The disk cache budget in bytes (Settings → Cache from S7). It counts live data only.
DEFAULT_DISK_BUDGET: int = setting_default(DISK_BUDGET_SETTING)
MIN_DISK_BUDGET = 10**9  # 1 GB: budgets are SI, as every size HeLab shows (Tony, 2026-10-26)


def read_disk_budget(settings: QSettings) -> int:
    """The saved disk cache budget, or the default for a missing or malformed value."""
    try:
        value = int(read_setting(settings, DISK_BUDGET_SETTING))
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_DISK_BUDGET
    return max(MIN_DISK_BUDGET, value)


# The RAM budget for loaded folders not shown in a tab, saved as steps of 1/128 of the
# computer's RAM so it still makes sense after a RAM upgrade.
RAM_STEPS = 128
DEFAULT_RAM_STEPS: int = setting_default(RAM_BUDGET_SETTING)
MAX_RAM_STEPS = 64
MIN_RAM_BUDGET = 10**9  # 1 GB (SI, as the disk budget)


def total_ram() -> int:
    import psutil
    return int(psutil.virtual_memory().total)


def ram_step_bytes(total: int | None = None) -> int:
    return max(1, (total_ram() if total is None else total) // RAM_STEPS)


def ram_step_range(total: int | None = None) -> tuple[int, int]:
    """The allowed steps: at least max(1 GB, 1 step), at most half of RAM."""
    step = ram_step_bytes(total)
    return min(MAX_RAM_STEPS, max(1, -(-MIN_RAM_BUDGET // step))), MAX_RAM_STEPS


def read_ram_budget_steps(settings: QSettings, total: int | None = None) -> int:
    """The saved RAM budget in steps, or the default, within the allowed range."""
    low, high = ram_step_range(total)
    try:
        value = int(read_setting(settings, RAM_BUDGET_SETTING))
    except (TypeError, ValueError, OverflowError):
        value = DEFAULT_RAM_STEPS
    return max(low, min(high, value))


def read_ram_budget(settings: QSettings, total: int | None = None) -> int:
    """The saved RAM budget in bytes."""
    return read_ram_budget_steps(settings, total) * ram_step_bytes(total)


def read_io_concurrency(settings: QSettings) -> int:
    """Use a safe default for missing or malformed saved limits."""
    try:
        # Independent legacy limits do not imply an intended shared limit.
        value = int(read_setting(settings, SIMULTANEOUS_IO_SETTING))
    except (TypeError, ValueError, OverflowError):
        return 1
    return max(1, min(MAX_SIMULTANEOUS_IO, value))


def read_check_level(settings: QSettings) -> str:
    level = read_setting(settings, CHECK_LEVEL_SETTING, typed=True)
    return level if level in CHECK_LEVEL_LABELS else DEFAULT_CHECK_LEVEL


def read_load_mode(settings: QSettings) -> str:
    mode = read_setting(settings, LOAD_MODE_SETTING, typed=True)
    return mode if mode in LOAD_MODE_LABELS else DEFAULT_LOAD_MODE


# Live (roadmaps/live-monitoring.md): seconds from the end of one check of the watched folder to
# the start of the next (Settings → General), and how many new shots wait in RAM before the
# folder is saved to the disk cache (Settings → Cache).
DEFAULT_LIVE_INTERVAL: float = setting_default(LIVE_INTERVAL_SETTING)
MIN_LIVE_INTERVAL, MAX_LIVE_INTERVAL = 0.5, 600.0
DEFAULT_LIVE_AUTOSAVE: int = setting_default(LIVE_AUTOSAVE_SETTING)
MAX_LIVE_AUTOSAVE = 100_000


def read_live_interval(settings: QSettings) -> float:
    import math
    try:
        value = float(read_setting(settings, LIVE_INTERVAL_SETTING))
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_LIVE_INTERVAL
    return max(MIN_LIVE_INTERVAL, min(MAX_LIVE_INTERVAL, value)) if math.isfinite(value) else DEFAULT_LIVE_INTERVAL


# Log files to keep (Settings → General): every session's, rotated copies counted; at startup the
# oldest beyond it are deleted (``helab.utils.app_log.tidy_logs``).
DEFAULT_LOG_KEEP: int = setting_default(LOG_KEEP_SETTING)
MAX_LOG_KEEP = 100_000


def read_log_keep(settings: QSettings) -> int:
    try:
        value = int(read_setting(settings, LOG_KEEP_SETTING))
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_LOG_KEEP
    return max(1, min(MAX_LOG_KEEP, value))


def read_convert_output(settings: QSettings) -> str:
    """Where HeLab's own TXY go (Q9.3): ``cache`` (the default) or ``temp``; anything else saved
    reads as the default."""
    value = read_setting(settings, CONVERT_OUTPUT_SETTING, typed=True)
    return value if value in CONVERT_OUTPUTS else str(setting_default(CONVERT_OUTPUT_SETTING))


def read_txy_source(settings: QSettings) -> str:
    """Which TXY tabs and Live load (Q18.2, ``helab.utils.txy_sources``): the setting when it names a
    source (an old name too), else ``helab-priority``."""
    from helab.utils.txy_sources import DEFAULT_SOURCE, normal_source
    return normal_source(read_setting(settings, TXY_SOURCE_SETTING, typed=True)) or DEFAULT_SOURCE


def profiles_folder() -> str:
    """The user's detector profiles (``helab.convert.user_profiles``): a folder of the app folder."""
    from helab.convert.user_profiles import FOLDER_NAME
    return os.path.join(app_folder(), FOLDER_NAME)


def read_convert_profile(settings: QSettings) -> "DetectorProfile":
    """The detector profile HeLab's conversions use (Q6.11): the setting's built-in or user profile;
    one that no longer exists or can't be read gives the default, ``matlab-2019`` (logged)."""
    from helab.convert.profile import DEFAULT_PROFILE, builtin_profile
    from helab.convert.user_profiles import ProfileLibrary
    name = str(read_setting(settings, CONVERT_PROFILE_SETTING, typed=True) or "")
    found = ProfileLibrary(profiles_folder()).find(name) if name else None
    if found is None:
        if name and name != DEFAULT_PROFILE:
            logging.warning("Detector profile %r not found: conversions use %s", name, DEFAULT_PROFILE)
        return builtin_profile()
    return found


def read_convert_backend(settings: QSettings) -> str:
    """The converter backend HeLab's conversions use: the setting when it names a known backend
    (whether it can run here is the helper's to say), else ``numpy``."""
    from helab.convert.pipeline import APP_BACKEND
    from helab.convert.reconstruct import _MODULES
    value = str(read_setting(settings, CONVERT_BACKEND_SETTING, typed=True) or "")
    return value if value in _MODULES else APP_BACKEND


def read_live_autosave(settings: QSettings) -> int:
    try:
        value = int(read_setting(settings, LIVE_AUTOSAVE_SETTING))
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_LIVE_AUTOSAVE
    return max(1, min(MAX_LIVE_AUTOSAVE, value))


# Settings → Cache: a plot released to free RAM reloads when it is shown again (on by default;
# helab/analysis/budget.py).


def read_plot_auto_reload(settings: QSettings) -> bool:
    value = read_setting(settings, PLOT_AUTO_RELOAD_SETTING)
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off", "")
    return bool(value)



OS_WORKING_DIRECTORY: str = os.getcwd()
QDir_WORKING_DIRECTORY = QDir.current()
QDir_USER_DIRECTORY = QDir.homePath()
QDir_ROOT_DIRECTORY = QDir.rootPath()
QDir_TEMP_DIRECTORY = QDir.tempPath()

logging.debug(f"{OS_WORKING_DIRECTORY = }")
logging.debug(f"{QDir_WORKING_DIRECTORY = }")
logging.debug(f"{QDir_USER_DIRECTORY = }")
logging.debug(f"{QDir_ROOT_DIRECTORY = }")
logging.debug(f"{QDir_TEMP_DIRECTORY = }")


def default_app_dir(kind: str) -> str:
    """Persistent per-user folder for HeLab's ``"caches"`` or ``"temps"``.

    macOS ``~/Library/Caches/HeLab``, Windows ``%LOCALAPPDATA%\\HeLab``, otherwise
    ``$XDG_CACHE_HOME/HeLab`` (``~/.cache/HeLab``). Unlike the system temp folder,
    the OS does not delete these after a few days without use.
    """
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        base = os.path.join(home, "Library", "Caches")
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")
    return os.path.join(base, "HeLab", kind)


# Created on first use; the last candidate keeps HeLab starting when the
# per-user folder is not writable.
DIR_TEMPS_CANDIDATES = [
    default_app_dir("temps"),
    QDir(QDir_TEMP_DIRECTORY).filePath('helab_temps'),
]

DIR_CACHES_CANDIDATES = [
    default_app_dir("caches"),
    QDir(QDir_TEMP_DIRECTORY).filePath('helab_caches'),
]

# logging.debug(f"{DIR_TEMPS_CANDIDATES = }")
# logging.debug(f"{DIR_CACHES_CANDIDATES = }")

def usable_directory(path: str, *, create: bool = False) -> bool:
    """A directory HeLab can write to, optionally created first.

    Writing a probe file is the reliable test: on Windows ``os.access`` ignores
    ACLs, e.g. a folder an elevated session created and Administrators own.
    """
    try:
        if create:
            os.makedirs(path, exist_ok=True)
        if not os.path.isdir(path):
            return False
        with tempfile.TemporaryFile(dir=path):
            return True
    except OSError:
        return False


def get_path_from_setting_or_use_default(key: str, candidates: List[str], settings: Optional[QSettings] = None,
                                         *, create: bool = False, persist: bool = True) -> str:
    """
    This function attempts to retrieve a setting value using the provided key. If the value is a writable
    directory, it is returned. Otherwise the function returns the first usable candidate (creating it when
    ``create`` is set) and saves it. If no candidate is usable, an error is raised.

    :param settings: Optional QSettings to read/write instead of the app's own (e.g. an
        ini file in a test's tmp dir). Defaults to None.
    :type settings: Optional[QSettings]
    :raises NotADirectoryError: If no valid default path is found in the candidates.
    """

    if settings is None:
        settings = app_settings()
    value = read_setting(settings, key, typed=True)
    if value and isinstance(value, str):
        # A path saved under another account (e.g. an elevated session) may exist but be read-only.
        if usable_directory(value):
            return str(value)
        else:
            logging.warning(f"Setting {key} with path {value} is not a writable folder. Replacing with default.")
    else:
        logging.warning(f"Setting {key} not found. Replacing with default.")
    new_value = next((path for path in candidates if usable_directory(path, create=create)), '')
    if new_value == '':
        logging.error(f"No valid default path found for {key}.")
        raise NotADirectoryError(f"No valid default path found for {key = }, {candidates = }.")
    if persist:
        settings.setValue(key, new_value)  # Save the replaced value
    return new_value


# QSettings persists dir_temps/dir_caches across processes and reuses
# whatever path was saved last time, so concurrent processes (e.g. pytest-xdist
# workers) that each expect a private cache dir would otherwise all resolve to
# the same on-disk cache and race each other's clears and writes. These
# overrides let a test process opt out of the persisted/shared path and force
# its own private directory instead.
def migrate_legacy_temp_dir(key: str, kind: str, settings: Optional[QSettings] = None,
                            target: Optional[str] = None) -> None:
    """Move a folder HeLab once created in the system temp folder to its persistent place.

    Older versions defaulted to ``tempfile.mkdtemp(prefix="helab_<kind>_")``, which the
    OS may delete after a few days without use (losing the data cache and saved scan
    results). Only that pattern is moved; a folder the user chose is left alone. The
    move is a rename, so it is instant on the same volume; if it fails, the old folder
    stays in use and the move is retried next launch.
    """
    if settings is None:
        settings = app_settings()
    value = read_setting(settings, key, typed=True)
    if not value or not isinstance(value, str) or not os.path.isdir(value):
        return
    legacy = (os.path.realpath(os.path.dirname(value)) == os.path.realpath(tempfile.gettempdir())
              and os.path.basename(value).startswith(f"helab_{kind}_"))
    target = target or default_app_dir(kind)
    if not legacy or os.path.exists(target):
        return
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        os.rename(value, target)
    except OSError as exc:
        logging.warning(f"Could not move {key} from {value} to {target}: {exc}")
        return
    settings.setValue(key, target)
    logging.info(f"Moved {key} from {value} to {target}")


def refuse_unsafe_cache_dir(path: str, candidates: List[str]) -> tuple[str, str, bool]:
    """``path``, or for this session a default folder if ``path`` is on a network or synced
    folder, with the reason to tell the user and whether the disk cache can be used.

    With no safe default the disk cache is off for the session, never left on the refused
    folder. The saved setting is left for the user to change.
    """
    from helab.utils.cache_location import cache_location_problem
    problem = cache_location_problem(path)
    if not problem:
        return path, "", True
    fallback = next((candidate for candidate in candidates if not cache_location_problem(candidate)
                     and usable_directory(candidate, create=True)), "")
    if not fallback:
        # Change… can't help here (it moves a cache, and there is none): say what will.
        default = candidates[0] if candidates else default_app_dir("caches")
        reason = (f"The saved cache folder {path} is {problem}, where the cache can't work safely, and no "
                  f"safe default folder is available: HeLab couldn't create {default}. The disk cache is "
                  f"off for this session. Make that folder writable, then restart HeLab; it will use it, "
                  f"and you can move the cache in Settings → General.")
        logging.error(reason)
        return path, reason, False
    reason = (f"The saved cache folder {path} is {problem}, where the cache can't work safely. "
              f"HeLab uses {fallback} for this session; choose another folder in Settings → General.")
    logging.warning(reason)
    return fallback, reason, True


_dir_temps_override = os.environ.get("HELAB_DIR_TEMPS_OVERRIDE")
_dir_caches_override = os.environ.get("HELAB_DIR_CACHES_OVERRIDE")

if _dir_temps_override:
    os.makedirs(_dir_temps_override, exist_ok=True)
    DIR_TEMPS = _dir_temps_override
else:
    migrate_legacy_temp_dir(DIR_TEMPS_SETTING, "temps")
    DIR_TEMPS = get_path_from_setting_or_use_default(DIR_TEMPS_SETTING, DIR_TEMPS_CANDIDATES, create=True)

def resolve_cache_dir(settings: Optional[QSettings] = None, *, persist: bool = False) -> tuple[str, str, bool]:
    """The cache folder to use: the saved one if it is usable and safe, else a default; why the
    saved one isn't used ("" when it is); and whether the disk cache can be used at all.
    ``persist`` saves a default that replaced a missing or unusable setting: only at startup
    while ``cache.lock`` is held (a cache move may be renaming the saved folder right now)."""
    if _dir_caches_override:
        os.makedirs(_dir_caches_override, exist_ok=True)
        return _dir_caches_override, "", True
    path = get_path_from_setting_or_use_default(DIR_CACHES_SETTING, DIR_CACHES_CANDIDATES, settings, create=True,
                                                persist=persist)
    return refuse_unsafe_cache_dir(path, DIR_CACHES_CANDIDATES)


def start_cache_dir(settings: Optional[QSettings] = None, *, usable: bool = True, reason: str = "") -> None:
    """At startup, with ``cache.lock`` held and any move recovered: move a legacy temp cache
    folder, save a replaced setting, and use the cache folder the setting names now. If an
    interrupted move couldn't be resolved (``usable`` False), the disk cache is off for this
    session and nothing is saved: the store may be in a folder the setting doesn't name yet."""
    if not usable:
        set_cache_dir(cache_dir(), reason, False)
        return
    if not _dir_caches_override:
        migrate_legacy_temp_dir(DIR_CACHES_SETTING, "caches", settings)
    set_cache_dir(*resolve_cache_dir(settings, persist=True))
# The cache folder when HeLab started. It can change while HeLab runs (a cache move, or a
# move recovered at startup): read the current one with ``cache_dir()``.
# DIR_CACHES_REFUSED: why the saved cache folder isn't used this session ("" when it is).
# DISK_CACHE_ENABLED: False when it was refused and no safe default exists.
DIR_CACHES, DIR_CACHES_REFUSED, DISK_CACHE_ENABLED = resolve_cache_dir()
_cache_dir_state = [DIR_CACHES, DIR_CACHES_REFUSED, DISK_CACHE_ENABLED]


def cache_dir() -> str:
    """The cache folder in use now. Every cache path is read through this, never ``DIR_CACHES``."""
    return str(_cache_dir_state[0])


def cache_dir_refused() -> str:
    return str(_cache_dir_state[1])


def cache_dir_enabled() -> bool:
    return bool(_cache_dir_state[2])


def set_cache_dir(path: str, refused: str = "", enabled: bool = True) -> None:
    """Switch the cache folder in place (after a move, or a move recovered at startup)."""
    _cache_dir_state[:] = [path, refused, enabled]


def app_folder() -> str:
    """The per-user app folder, outside every cache: the cache-move record and the locks."""
    return os.environ.get("HELAB_APP_DIR_OVERRIDE") or os.path.dirname(default_app_dir("caches"))


# DIR_TEMPS = os.path.join(CURRENT_WORKING_DIRECTORY, 'helab_temps')
# DIR_CACHES = os.path.join(CURRENT_WORKING_DIRECTORY, 'helab_caches')
# DIR_TEMP = "/tmp/cache"

DEV_POTENTIAL_DATA_PATHS = [
    '/Volumes/dld_output',
    os.path.join(OS_WORKING_DIRECTORY,'tests_sample_data'),
    str(QDir_WORKING_DIRECTORY.filePath("tests_sample_data")),
    str(QDir_WORKING_DIRECTORY),
    OS_WORKING_DIRECTORY,
    'O:\\',
]

# This is a display hint; availability is resolved by an isolated I/O helper
# after the window is shown. Never stat a remote mount at module import.
DEFAULT_DATA_PATH = DEV_POTENTIAL_DATA_PATHS[0]


def assert_warn(condition: bool, message: str) -> None:
    if not condition:
        logging.warning(message)



