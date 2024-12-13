# This Python file uses the following encoding: utf-8
import logging
import re
import subprocess
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication

from helab.resources.icons import StatusIcons, ToolIcons, IconsInitUtil
from helab.utils.loggingSetup import setup_logging
from helab.views.helabMainWindow import MainWindow, APP_VERSION, APP_COMMIT_HASH

if __name__ == "__main__":

    setup_logging()
    logging.debug("this is a debugging message")
    logging.info("this is an informational message")
    logging.warning("this is a warning message")
    logging.error("this is an error message")
    logging.critical("this is a critical message")

    logging.info(f"Starting HeLab v{APP_VERSION} ({APP_COMMIT_HASH})")

    # font_db = QFontDatabase()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # app.setStyleSheet("QWidget { background-color: #fafafa; }")
    if "SF Mono" in QFontDatabase.families():
        font = QFont("SF Mono", 12)
        logging.debug("Using SF Mono font.")
    else:
        font = QFont("Monospace", 12)
        logging.warning("SF Mono font not found. Using Monospace font instead.")
    app.setFont(font)

    IconsInitUtil.initialise_icons()

    main_window = MainWindow()
    main_window.show()

    sys.exit(app.exec())
