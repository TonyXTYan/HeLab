import os
import random
import re
import subprocess
import sys
import tempfile
import logging
from typing import List
import hashlib

from typing import Optional

from PyQt6.QtCore import QSettings, QDir, QDirIterator
# from PyQt6.QtGui import QFontDatabase, QFont

from joblib.externals.loky.process_executor import MAX_DEPTH

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


def get_version() -> str:
    """
    Retrieve the version number from the setup.py file.

    This function reads the setup.py file located in the current directory,
    searches for the version string defined in the file, and returns it.

    :return: The version string in the format x.y.z. If the version string
             is not found, it returns '0.0.0' as the default version.
    :rtype: str
    """
    dirs_to_try = ['setup.py', '../setup.py', '../../setup.py']  # Add more paths as needed
    content = None

    for path in dirs_to_try:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
                break
        except FileNotFoundError:
            continue

    if content:
        match = re.search(r'version\s*=\s*[\'"]([^\'"]+)[\'"]', content)
        if match:
            return match.group(1)
    return '0.0.0'  # Default version if not found

def get_git_commit_hash() -> str:
    """
    Retrieve the current Git commit hash.

    This function attempts to obtain the current Git commit hash of the repository
    in which the script is located. It returns the first 6 characters of the commit
    hash in uppercase. If the commit hash cannot be determined, it returns 'unknown'.

    :return: The first 6 characters of the Git commit hash in uppercase, or 'unknown' if not found.
    :rtype: str

    :raises subprocess.CalledProcessError: If the Git command fails.
    :raises FileNotFoundError: If Git is not installed or not found in the system path.
    :raises Exception: For any other exceptions that may occur.
    """
    try:
        commit_hash = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'],
            stderr=subprocess.STDOUT
        ).decode('utf-8').strip()
        return commit_hash[:6].upper()  # Return only the first 6 characters
    except Exception:
        return 'unknown'

APP_VERSION = get_version()
APP_COMMIT_HASH = get_git_commit_hash()


QSETTINGS_ORG_NAME = "ANU_HE_BEC_GROUP"
QSETTINGS_APP_NAME = "HeLab"

# What happens to a folder's load when another folder is selected.
LOAD_MODE_SETTING = "load_on_select_mode"
LOAD_MODE_LABELS = {"cancel": "Cancel the current load",
                    "finish": "Finish the current load in the background",
                    "queue": "Queue folders kept selected for 3 s"}
DEFAULT_LOAD_MODE = "finish"

SIMULTANEOUS_IO_SETTING = "simultaneous_folder_io_operations"
AUTO_SCAN_VISIBLE_SETTING = "auto_basic_scan_visible_folders"
DEFAULT_SIMULTANEOUS_IO = 1
MAX_SIMULTANEOUS_IO = 32


def read_io_concurrency(settings: QSettings) -> int:
    """Use a safe default for missing or malformed saved limits."""
    try:
        # Independent legacy limits do not imply an intended shared limit.
        value = int(settings.value(SIMULTANEOUS_IO_SETTING, DEFAULT_SIMULTANEOUS_IO))
    except (TypeError, ValueError, OverflowError):
        return 1
    return max(1, min(MAX_SIMULTANEOUS_IO, value))


def read_load_mode(settings: QSettings) -> str:
    mode = settings.value(LOAD_MODE_SETTING, DEFAULT_LOAD_MODE, type=str)
    return mode if mode in LOAD_MODE_LABELS else DEFAULT_LOAD_MODE



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

TEMPFILE_PREFIX = tempfile.gettempdir()


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

INDICATOR_DOTS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
INDICATOR_DOTS_ALL = "⠃⠅⠆⠇⠉⠊⠋⠌⠍⠎⠏⠑⠒⠓⠔⠕⠖⠗⠘⠙⠚⠛⠜⠝⠞⠟⠡⠢⠣⠤⠥⠦⠧⠨⠩⠪⠫⠬⠭⠮⠯⠰⠱⠲⠳⠴⠵⠶⠷⠸⠹⠺⠻⠼⠽⠾⠿"
def INDICATOR_DOT_RANDOM(n: int = 1) -> str:
    if not (1 <= n <= len(INDICATOR_DOTS)):
        raise ValueError(f"n must be between 1 and {len(INDICATOR_DOTS)}, inclusive.")
    return ''.join(random.sample(INDICATOR_DOTS, n))


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
                                         *, create: bool = False) -> str:
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
        settings = QSettings(QSETTINGS_ORG_NAME, QSETTINGS_APP_NAME)
    value = settings.value(key, type=str)
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
    settings.setValue(key, new_value)  # Save the replaced value
    return new_value


# QSettings persists dir_temps/dir_caches across processes and reuses
# whatever path was saved last time, so concurrent processes (e.g. pytest-xdist
# workers) that each expect a private cache dir would otherwise all resolve to
# the same on-disk FanoutCache and race each other's .clear()/writes. These
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
        settings = QSettings(QSETTINGS_ORG_NAME, QSETTINGS_APP_NAME)
    value = settings.value(key, type=str)
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


_dir_temps_override = os.environ.get("HELAB_DIR_TEMPS_OVERRIDE")
_dir_caches_override = os.environ.get("HELAB_DIR_CACHES_OVERRIDE")

if _dir_temps_override:
    os.makedirs(_dir_temps_override, exist_ok=True)
    DIR_TEMPS = _dir_temps_override
else:
    migrate_legacy_temp_dir("dir_temps", "temps")
    DIR_TEMPS = get_path_from_setting_or_use_default("dir_temps", DIR_TEMPS_CANDIDATES, create=True)

if _dir_caches_override:
    os.makedirs(_dir_caches_override, exist_ok=True)
    DIR_CACHES = _dir_caches_override
else:
    migrate_legacy_temp_dir("dir_caches", "caches")
    DIR_CACHES = get_path_from_setting_or_use_default("dir_caches", DIR_CACHES_CANDIDATES, create=True)


# DIR_TEMPS = os.path.join(CURRENT_WORKING_DIRECTORY, 'helab_temps')
# DIR_CACHES = os.path.join(CURRENT_WORKING_DIRECTORY, 'helab_caches')
# DIR_TEMP = "/tmp/cache"

OS_DIR_CACHE_TTL = 60*60 # seconds

# MAX_DEPTH_INT = int(sys.maxsize)>>10
MAX_DEPTH_INT = 1<<15

DEV_POTENTIAL_DATA_PATHS = [
    '/Volumes/dld_output',
    '/Volumes/tonyNVME Gold/dld output',
    '/Users/tonyyan/.cache/2024_Momentum_Bells_V2 - 20241200',
    # '/Users/tonyyan/Library/CloudStorage/OneDrive-AustralianNationalUniversity/SharePoint - Testing MS Teams/2024_Momentum_Bells_V2 - 20241200',
    # Don't use OneDrive it's shit (cause file system hangs)
    os.path.join(OS_WORKING_DIRECTORY,'tests_sample_data'),
    str(QDir_WORKING_DIRECTORY.filePath("tests_sample_data")),
    str(QDir_WORKING_DIRECTORY),
    OS_WORKING_DIRECTORY,
    '/Users/tonyyan/Documents/_ANU/_He_BEC_Group/HeLab',
    'C:\\Users\\XinTong\\Documents',
    'O:\\',
    '/Users/tonyyan/Documents/_ANU/_He_BEC_Group/HeLab/tests_sample_data/good',
    '/Users/tonyyan/Documents/_ANU/_He_BEC_Group/HeLab/tests_sample_data/bad'
    '',
]

# This is a display hint; availability is resolved by an isolated I/O helper
# after the window is shown. Never stat a remote mount at module import.
DEFAULT_DATA_PATH = DEV_POTENTIAL_DATA_PATHS[0]


DEV_PATH_TO_MATLAB = "/Applications/MATLAB_R2024b.app"
DEV_PATH_TO_TDC_AUTOCONVERTER_GIT_FOLDER = "/Users/tonyyan/Documents/_ANU/_He_BEC_Group/tdc_autoconverter"
DEV_PATH_TO_TDC_AUTO_CONVERT_M = "/Users/tonyyan/Documents/_ANU/_He_BEC_Group/tdc_autoconverter/tdc_auto_convert.m"
DEV_PATH_TO_TDC_CONVERT_FILELIST_M = "/Users/tonyyan/Documents/_ANU/_He_BEC_Group/tdc_autoconverter/tdc_convert_filelist.m"


BASE62_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

def base62_encode(number: int) -> str:
    if number == 0:
        return BASE62_ALPHABET[0]
    
    base62 = []
    while number:
        number, remainder = divmod(number, 62)
        base62.append(BASE62_ALPHABET[remainder])
    
    return ''.join(reversed(base62))

def base62_decode(base62: str) -> int:
    number = 0
    for char in base62:
        number = number * 62 + BASE62_ALPHABET.index(char)
    return number


def hash_int(path: str) -> int:
    # return int(hashlib.sha256(path.encode()).hexdigest(), 16)
    hash_bytes = hashlib.sha256(path.encode()).digest()
    return int.from_bytes(hash_bytes, 'big')

def hash_bit(path: str) -> str:
    return bin(hash_int(path))[2:]

def hash_bit_to_int(code: str) -> int:
    return int(code, 2)

def hash_str(path: str) -> str:
    # return hashlib.sha256(path.encode()).hexdigest()
    
    # hash_bytes = hashlib.sha256(path.encode()).digest()
    # return base64.b64encode(hash_bytes).decode('utf-8').replace('/', '_').replace('+', '-')
    
    hash_bytes = hashlib.sha256(path.encode()).digest()
    hash_int = int.from_bytes(hash_bytes, 'big')
    return base62_encode(hash_int)

def hash_str_to_int(code: str) -> int:
    return base62_decode(code)


def assert_warn(condition: bool, message: str) -> None:
    if not condition:
        logging.warning(message)



