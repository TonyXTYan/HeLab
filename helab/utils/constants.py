import os
import re
import subprocess
import sys

from joblib.externals.loky.process_executor import MAX_DEPTH

# TOOLBAR_STYLESHEET_LR = """
# QToolBar {
#     background: none;
#     border: none;
#     spacing: 5px;
# }
# """

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


# Function to extract version from setup.py
def get_version() -> str:
    with open('setup.py', 'r', encoding='utf-8') as f:
        content = f.read()
        match = re.search(r'version\s*=\s*[\'"]([^\'"]+)[\'"]', content)
        if match:
            return match.group(1)
    return '0.0.0'  # Default version if not found

def get_git_commit_hash() -> str:
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
DIR_TEMPS = os.path.join(CURRENT_WORKING_DIRECTORY, 'helab_temps')

DIR_CACHES = os.path.join(CURRENT_WORKING_DIRECTORY, 'helab_caches')

DIR_TEMP = "/tmp/cache"

OS_DIR_CACHE_TTL = 60*60 # seconds

# MAX_DEPTH_INT = int(sys.maxsize)>>10
MAX_DEPTH_INT = 1<<15

DEV_POTENTIAL_DATA_PATHS = [
    '/Volumes/tonyNVME Gold/dld output',
    '/Users/tonyyan/.cache/2024_Momentum_Bells_V2 - 20241200',
    # '/Users/tonyyan/Library/CloudStorage/OneDrive-AustralianNationalUniversity/SharePoint - Testing MS Teams/2024_Momentum_Bells_V2 - 20241200',
    # Don't use OneDrive it's shit (cause file system hangs)
    os.getcwd(),
    '/Users/tonyyan/Documents/_ANU/_He_BEC_Group/HeLab',
    'C:\\Users\\XinTong\\Documents',
    'O:\\',
    '/Users/tonyyan/Documents/_ANU/_He_BEC_Group/HeLab/tests_sample_data/good',
    '/Users/tonyyan/Documents/_ANU/_He_BEC_Group/HeLab/tests_sample_data/bad'
    '',
]


DEV_PATH_TO_MATLAB = "/Applications/MATLAB_R2024b.app"
DEV_PATH_TO_TDC_AUTO_CONVERT_M = "/Users/tonyyan/Documents/_ANU/_He_BEC_Group/tdc_autoconverter/tdc_auto_convert.m"
DEV_PATH_TO_TDC_CONVERT_FILELIST_M = "/Users/tonyyan/Documents/_ANU/_He_BEC_Group/tdc_autoconverter/tdc_convert_filelist.m"