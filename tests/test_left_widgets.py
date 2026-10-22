"""Widgets a test leaves are deleted at its teardown (``conftest.delete_left_widgets``): a web view
deleted later, by another test's event loop or at exit, crashed Qt on CI."""
from __future__ import annotations

import pytest
from PyQt6 import sip
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication

from conftest import delete_left_widgets


def test_a_web_view_deleted_later_goes_at_teardown(qapp: QApplication) -> None:
    view = QWebEngineView()
    view.deleteLater()
    delete_left_widgets("this test")
    assert sip.isdeleted(view)


def test_a_web_view_left_alive_fails_its_test_and_goes(qapp: QApplication) -> None:
    view = QWebEngineView()
    with pytest.raises(pytest.fail.Exception, match="this test left 1 web view"):
        delete_left_widgets("this test")
    assert sip.isdeleted(view)
    delete_left_widgets("the next test")  # Nothing left for it.
