"""Widgets a test leaves are deleted at its teardown (``conftest.delete_left_widgets``): a web view
deleted later, by another test's event loop or at exit, crashed Qt on CI."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from PyQt6 import sip
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication

from conftest import delete_left_widgets

ROOT = Path(__file__).resolve().parents[1]


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


BROKEN_TEARDOWN = '''
import pytest
from PyQt6 import sip
from PyQt6.QtWebEngineWidgets import QWebEngineView

views = []


@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("this fixture's teardown broke")


@pytest.mark.parametrize("left", ["deleted later", "alive"])
def test_leaves_a_web_view(qapp, broken_teardown, left):
    views.append(QWebEngineView())
    if left == "deleted later":
        views[-1].deleteLater()


def test_after_it(qapp):
    assert len(views) == 2 and all(sip.isdeleted(view) for view in views)
'''


def test_a_teardown_that_raises_still_deletes_the_web_views(tmp_path: Path) -> None:
    """The cleanup runs after the teardown even when a fixture's teardown (or pytest-qt's) raises,
    and the test fails with that error, not with the views it left. Through pytest's own hook
    calls, in a run of its own with this conftest as its plugin."""
    test = tmp_path / "test_broken_teardown.py"  # (Outside tests/, so conftest comes only by -p.)
    test.write_text(BROKEN_TEARDOWN, encoding="utf-8")
    # Its own rootdir, so its node IDs are "test_broken_teardown.py::…" wherever the basetemp is (one
    # outside the checkout, as on CI, gave "../../…/HeLab::test_after_it" under the checkout's).
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "tests")])}
    done = subprocess.run([sys.executable, "-m", "pytest", "-p", "conftest", "-p", "no:cacheprovider",
                           "-p", "no:xdist", "-p", "no:rerunfailures", "-q", "-rA", str(test)],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    out = done.stdout + done.stderr
    assert "PASSED test_broken_teardown.py::test_after_it" in out, out
    assert out.count("RuntimeError: this fixture's teardown broke") >= 2, out
    assert "ERROR test_broken_teardown.py::test_leaves_a_web_view[deleted later]" in out, out
    assert "ERROR test_broken_teardown.py::test_leaves_a_web_view[alive]" in out, out
    assert "left 1 web view" not in out, out  # (The original failure is kept.)
    assert "3 passed, 2 errors" in out, out
