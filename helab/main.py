# This Python file uses the following encoding: utf-8
import logging
import tempfile

import coloredlogs

# from helab.utils.loggingSetup import setup_logging
# setup_logging()
coloredlogs.install(
        level=logging.DEBUG,
        # format='%(asctime)s - %(levelname)s - %(message)s'
        fmt='%(asctime)s - %(levelname)s:\t%(message)s',
    )


import platform
import re
import subprocess
import sys
import os

from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication

from helab.resources.icons import StatusIcons, ToolIcons, IconsInitUtil
from helab.utils.constants import *
from helab.utils.caching_setup import *
from helab.views.HelabMainWindow import HelabMainWindow
from helab.utils.threading_setup import *


def _raise_fd_limit(target: int = 10240) -> None:
    # macOS's default launchd/Finder-launch environment caps RLIMIT_NOFILE at 256
    # (vs. a typical interactive shell's much higher ulimit), which HeLab's
    # directory-scanning worker pools can exhaust, aborting Qt's event dispatcher.
    if sys.platform == "win32":
        return
    import resource
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        new_soft = target if hard == resource.RLIM_INFINITY else min(target, hard)
        if new_soft > soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))
            logging.info(f"Raised file-descriptor limit (RLIMIT_NOFILE): {soft} -> {new_soft} (hard={hard})")
    except (ValueError, OSError) as e:
        logging.warning(f"Could not raise RLIMIT_NOFILE: {e}")


def main() -> None:
    # setup_logging()
    _raise_fd_limit()
    logging.debug("this is a debugging message")
    logging.info("this is an informational message")
    logging.warning("this is a warning message")
    logging.error("this is an error message")
    logging.critical("this is a critical message")
    logging.fatal("this is a fatal message")

    logging.info(f"Platform: {sys.platform}, {platform.system()}, {platform.release()}, {platform.version()}, {platform.machine()}, {platform.processor()}")
    logging.info(f"{tempfile.gettempdir() = }")

    logging.info(f"Starting HeLab v{APP_VERSION} ({APP_COMMIT_HASH})")

    # font_db = QFontDatabase()

    logging.debug(cache_status_string())

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # app.setStyleSheet("QWidget { background-color: #fafafa; }")
    if "SF Mono" in QFontDatabase.families():
        helab_mono_font = QFont("SF Mono", 12)
        logging.debug("Using SF Mono helab_mono_font.")
    else:
        helab_mono_font = QFont("Monospace", 12)
        logging.warning("SF Mono helab_mono_font not found. Using Monospace helab_mono_font instead.")
    app.setFont(helab_mono_font)

    IconsInitUtil.initialise_icons()

    main_window = HelabMainWindow()
    main_window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
