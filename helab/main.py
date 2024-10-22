# This Python file uses the following encoding: utf-8
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from helab.resources.icons import StatusIcons
from helab.utils.loggingSetup import setup_logging
from helab.views.heliumMainWindow import MainWindow


if __name__ == "__main__":

    setup_logging()

    font = QFont("SF Mono")

    app = QApplication(sys.argv)
    app.setFont(font)

    StatusIcons.initialise_icons()  # This need to be after QGUIApplication creation

    main_window = MainWindow()
    main_window.show()

    sys.exit(app.exec())
