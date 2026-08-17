from typing import Any

import pytest
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication

from helab.views.MemoryUsageWindow import MemoryUsageWindow
from unittest.mock import MagicMock

# test_memoryUsageWindow.py

@pytest.fixture(scope="session")
def app() -> Any:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    yield app
    try:
        app.quit()
    except Exception:
        pass

@patch('helab.views.MemoryUsageWindow.muppy.get_objects')
@patch('helab.views.MemoryUsageWindow.summary.summarize')
def test_memory_usage_window_initialization(mock_summarize: MagicMock, mock_get_objects: MagicMock, app: Any) -> None:
    mock_get_objects.return_value = ['object1', 'object2', 'object3']
    mock_summarize.return_value = [
        ('type1', 0, 1048576),
        ('type2', 0, 524288),
        ('type3', 0, 262144)
    ]
    window = MemoryUsageWindow()
    assert window.series.count() == 3
    # assert window.series.at(0).value() == 1.0
    # assert window.series.at(1).value() == 0.5
    # assert window.series.at(2).value() == 0.25
    assert window.series.slices()[0].value() == 1.0
    assert window.series.slices()[1].value() == 0.5
    assert window.series.slices()[2].value() == 0.25

@patch('helab.views.MemoryUsageWindow.muppy.get_objects')
@patch('helab.views.MemoryUsageWindow.summary.summarize')
def test_update_memory_usage_less_than_ten(mock_summarize: MagicMock, mock_get_objects: MagicMock, app: Any) -> None:
    mock_get_objects.return_value = ['object1', 'object2']
    mock_summarize.return_value = [
        ('type1', 0, 1048576),
        ('type2', 0, 524288)
    ]
    window = MemoryUsageWindow()
    assert window.series.count() == 2

@patch('helab.views.MemoryUsageWindow.muppy.get_objects')
@patch('helab.views.MemoryUsageWindow.summary.summarize')
def test_update_memory_usage_no_objects(mock_summarize: MagicMock, mock_get_objects: MagicMock, app: Any) -> None:
    mock_get_objects.return_value = []
    mock_summarize.return_value = []
    window = MemoryUsageWindow()
    assert window.series.count() == 0

@patch('helab.views.MemoryUsageWindow.muppy.get_objects')
@patch('helab.views.MemoryUsageWindow.summary.summarize')
def test_update_memory_usage_top_ten(mock_summarize: MagicMock, mock_get_objects: MagicMock, app: Any) -> None:
    mock_get_objects.return_value = ['object'] * 20
    mock_summarize.return_value = [
        (f'type{i}', 0, 1000000) for i in range(15)
    ]
    window = MemoryUsageWindow()
    assert window.series.count() == 10