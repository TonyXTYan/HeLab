import os
import re
import subprocess
import sys
import tempfile
import logging
from typing import List
import hashlib

from PyQt6.QtCore import QSettings
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
    with open('setup.py', 'r', encoding='utf-8') as f:
        content = f.read()
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

CURRENT_WORKING_DIRECTORY = os.getcwd()

TEMPFILE_PREFIX = tempfile.gettempdir()

DIR_TEMPS_CANDIDATES = [
    tempfile.mkdtemp(prefix='helab_temps'),
    os.path.join(CURRENT_WORKING_DIRECTORY, 'helab_temps'),
    os.path.join(TEMPFILE_PREFIX, 'helab_temps'),
]

DIR_CACHES_CANDIDATES = [
    tempfile.mkdtemp(prefix='helab_caches'),
    os.path.join(CURRENT_WORKING_DIRECTORY, 'helab_caches'),
    os.path.join(TEMPFILE_PREFIX, 'helab_caches'),
]

# logging.debug(f"{DIR_TEMPS_CANDIDATES = }")
# logging.debug(f"{DIR_CACHES_CANDIDATES = }")

INDICATOR_DOTS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

def get_path_from_setting_or_use_default(key: str, candidates: List[str]) -> str:
    """
    Retrieve a setting value by key or replace it with a default from candidates if not found or invalid.
    This function attempts to retrieve a setting value associated with the given key from QSettings.
    If the retrieved value is a valid path, it is returned. Otherwise, a warning is logged, and the
    function searches through the provided candidates list for an existing path to use as the new value.
    The new value is then saved in QSettings and returned.
    :param key: The key to look up in the settings.
    :type key: str
    :param candidates: A list of candidate paths to use as default if the setting is not found or invalid.
    :type candidates: List[str]
    :return: The valid setting value or a default from the candidates.
    :rtype: str    
    """
    settings = QSettings("ANU", "HeLab")
    value = settings.value(key, type=str)
    if value and isinstance(value, str):
        if os.path.exists(value):
            return str(value)
        else: 
            logging.warning(f"Setting {key} with path {value} does not exist. Replacing with default.")
        # settings.setValue(key, value)  # Save the used value
    else:
        logging.warning(f"Setting {key} not found. Replacing with default.")
    new_value = next((path for path in candidates if os.path.exists(path)), '')
    settings.setValue(key, new_value)  # Save the replaced value
    return new_value


DIR_TEMPS = get_path_from_setting_or_use_default("dir_temps", DIR_TEMPS_CANDIDATES)
DIR_CACHES = get_path_from_setting_or_use_default("dir_caches", DIR_CACHES_CANDIDATES)


# DIR_TEMPS = os.path.join(CURRENT_WORKING_DIRECTORY, 'helab_temps')
# DIR_CACHES = os.path.join(CURRENT_WORKING_DIRECTORY, 'helab_caches')
# DIR_TEMP = "/tmp/cache"

OS_DIR_CACHE_TTL = 60*60 # seconds

# MAX_DEPTH_INT = int(sys.maxsize)>>10
MAX_DEPTH_INT = 1<<15

DEV_POTENTIAL_DATA_PATHS = [
    '/Volumes/tonyNVME Gold/dld output',
    '/Users/tonyyan/.cache/2024_Momentum_Bells_V2 - 20241200',
    # '/Users/tonyyan/Library/CloudStorage/OneDrive-AustralianNationalUniversity/SharePoint - Testing MS Teams/2024_Momentum_Bells_V2 - 20241200',
    # Don't use OneDrive it's shit (cause file system hangs)
    os.path.join(CURRENT_WORKING_DIRECTORY,'tests_sample_data'),
    CURRENT_WORKING_DIRECTORY,
    '/Users/tonyyan/Documents/_ANU/_He_BEC_Group/HeLab',
    'C:\\Users\\XinTong\\Documents',
    'O:\\',
    '/Users/tonyyan/Documents/_ANU/_He_BEC_Group/HeLab/tests_sample_data/good',
    '/Users/tonyyan/Documents/_ANU/_He_BEC_Group/HeLab/tests_sample_data/bad'
    '',
]

DEFAULT_DATA_PATH = next((path for path in DEV_POTENTIAL_DATA_PATHS if os.path.exists(path)), '')


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