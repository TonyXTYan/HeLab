# main_app.py
import logging
import coloredlogs
coloredlogs.install(
        level=logging.DEBUG,
        # format='%(asctime)s - %(levelname)s - %(message)s'
        fmt='%(asctime)s - %(levelname)s:\t%(message)s',
    )
import sys
from typing import Dict

from PyQt6.QtGui import QFontDatabase, QFont
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QDockWidget,
    QWidget, QVBoxLayout
)
from PyQt6.QtCore import Qt
import pyqtgraph as pg
from helab.scripts.pg_simple_densities import *
import numpy as np
import numpy.typing as npt

from helab.utils.cachingSetup import data_ram_cache
from helab.workers.loadFolderToRamWorker import LoadFolderToRamWorker


class MainWindow(QMainWindow):
    def __init__(self, data: Dict[int, npt.NDArray[np.float64]]) -> None:
        super().__init__()
        self.setWindowTitle("Density Plots in DockWidget")

        # Create the plot widget using the reusable function
        win = make_three_density_plots(data, nbins=300)
        # win = make_three_density_plots_with_drag(data, nbins=300)

        # Create a dock widget and set the container as its content
        dock = QDockWidget("Density Plots", self)
        dock.setWidget(win)

        # Add dock widget to the main window
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    # Optionally set a central widget if needed.


if __name__ == "__main__":
    # Set global configuration for background
    pg.setConfigOption('background', None)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    if "SF Mono" in QFontDatabase.families():
        helab_mono_font = QFont("SF Mono", 12)
        logging.debug("Using SF Mono helab_mono_font.")
    else:
        helab_mono_font = QFont("Monospace", 12)
        logging.warning("SF Mono helab_mono_font not found. Using Monospace helab_mono_font instead.")
    app.setFont(helab_mono_font)


    # Sample data creation
    rng = np.random.default_rng(0)
    # data = {
    #     0: rng.normal(loc=(0, 5, 10), scale=(1, 3, 2), size=(200, 3)),
    #     1: rng.normal(loc=(5, 2, 20), scale=(2, 5, 5), size=(300, 3)),
    #     2: rng.normal(loc=(10, 0, -10), scale=(3, 10, 3), size=(150, 3))
    # }
    data = LoadFolderToRamWorker.default_algorithm_decompress(data_ram_cache[list(data_ram_cache)[0]])

    mainWin = MainWindow(data)
    mainWin.resize(1200, 800)
    mainWin.show()
    sys.exit(app.exec())
