import logging
import sys

from PyQt6.QtCharts import QPieSeries, QChart, QChartView
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout
from pympler import muppy, summary
import psutil

class MemoryUsageWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('Memory Usage Breakdown')
        self.series = QPieSeries()
        self.update_memory_usage()
        chart = QChart()
        chart.addSeries(self.series)
        chart.setTitle('Memory Usage by Object Type')
        chart_view = QChartView(chart)

        layout = QVBoxLayout()
        layout.addWidget(chart_view)
        self.setLayout(layout)

        # logging.debug(f"{psutil}")


    def update_memory_usage(self) -> None:
        # Retrieve all objects tracked by the garbage collector
        all_objects = muppy.get_objects()
        # Summarize the memory usage by object type
        summary_info = summary.summarize(all_objects)                           # type: ignore[no-untyped-call]
        # Clear the previous data in the series
        self.series.clear()
        # Add data to the series for the top object types
        for item in summary_info[:10]:  # Display top 10 object types
            obj_type = item[0]
            mem_usage = item[2] / (1024 ** 2)  # Convert bytes to megabytes
            self.series.append(f'{obj_type}: {mem_usage:.2f} MB', mem_usage)