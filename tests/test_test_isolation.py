"""Tests run apart from the developer's data and from each other (tests/conftest.py): they test
this checkout's helab, new tabs start in an empty temp folder, never the default data path
(``/Volumes/dld_output`` when it is mounted), and each test's disk cache is a store of its own."""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

import helab
from conftest import START_FOLDER
from helab.utils import constants
from helab.utils.cache_store import CacheStore, store_root
from helab.utils.folder_cache import store_options
from helab.views.FolderExplorer import FolderExplorer
from helab.views.HelabMainWindow import HelabMainWindow

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATHS = {"DEFAULT_DATA_PATH", "DEV_POTENTIAL_DATA_PATHS"}
# The modules that may read the default data paths: conftest patches FolderTabWidget's names, and
# io_ops.infra reads them only to refuse them under pytest.
READERS = {"helab/utils/constants.py", "helab/views/FolderTabWidget.py", "helab/io_ops/infra.py"}


def test_helab_is_this_checkouts() -> None:
    """pytest.ini's ``pythonpath`` puts this checkout first, so pytest never tests another
    checkout's helab: a floor's venv copied from Ground has Ground's editable install."""
    assert Path(helab.__file__).resolve() == ROOT / "helab" / "__init__.py"


def test_pytest_imports_the_checkout_it_runs_in_before_any_other(tmp_path: Path) -> None:
    other = tmp_path / "other-checkout" / "helab"
    other.mkdir(parents=True)
    (other / "__init__.py").write_text("", encoding="utf-8")
    test = tmp_path / "test_which.py"  # (Outside tests/: no conftest, so it imports quickly.)
    test.write_text("import helab\n\ndef test_which():\n    print('helab at', helab.__file__)\n",
                    encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(other.parent)}
    done = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "no:xdist",
                           "-s", "-q", "--rootdir", str(ROOT), "-c", str(ROOT / "pytest.ini"), str(test)],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"helab at {ROOT / 'helab' / '__init__.py'}" in done.stdout, done.stdout


def test_only_patched_modules_read_the_default_data_paths() -> None:
    """A new reader of the default data paths would slip past conftest's patch."""
    readers = set()
    for file in (ROOT / "helab").rglob("*.py"):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        names |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                  for alias in node.names}
        if names & DEFAULT_PATHS:
            readers.add(file.relative_to(ROOT).as_posix())
    assert readers == READERS


def test_a_main_windows_tabs_start_in_the_test_folder(qtbot: QtBot) -> None:
    window = HelabMainWindow()
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.tab_widget.count() == 1)  # (Its first tab comes from a timer.)
    window.add_new_folder_explorer_tab()
    explorers = [window.tab_widget.widget(index) for index in range(window.tab_widget.count())]
    assert len(explorers) == 2
    data = [os.path.normcase(path) for path in constants.DEV_POTENTIAL_DATA_PATHS if path]
    for explorer in explorers:
        assert isinstance(explorer, FolderExplorer)
        for path in (explorer.target_path, explorer.view_path, explorer.selected_path_globally):
            assert os.path.normcase(path) == os.path.normcase(os.path.abspath(START_FOLDER))
            assert os.path.normcase(path) not in data
    window.close()


def test_each_test_has_a_store_of_its_own(private_store: str, tmp_path_factory: pytest.TempPathFactory) -> None:
    """Made for this test: nothing an earlier test of this worker saved (a pending save, a budget,
    roots) is there. conftest seeds only this test's data root."""
    assert constants.cache_dir() == private_store == os.environ["HELAB_DIR_CACHES_OVERRIDE"]
    assert Path(private_store).is_relative_to(tmp_path_factory.getbasetemp())
    assert store_options()["directory"] == store_root(private_store)
    with CacheStore(store_root(private_store), root_mode=True) as store:
        assert len(store.root_locations()) == 1
        assert store.inventory()["pending"] == []
