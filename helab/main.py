# This Python file uses the following encoding: utf-8
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from helab.resources.icons import StatusIcons, ToolIcons, IconsInitUtil
from helab.utils.loggingSetup import setup_logging
from helab.views.helabMainWindow import MainWindow


if __name__ == "__main__":

    setup_logging()

    font = QFont("SF Mono")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(font)


    IconsInitUtil.initialise_icons()

    main_window = MainWindow()
    main_window.show()

    sys.exit(app.exec())
