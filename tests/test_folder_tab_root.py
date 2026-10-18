# tests/test_folder_tab_root.py
import ntpath
import os
import posixpath

import pytest

from helab.views.FolderTabWidget import root_on_target_drive


@pytest.mark.parametrize("target, expected", [
    ("Y:\\", "Y:\\"),                                   # mapped network drive (Open Drives menu)
    ("Y:\\data\\run1", "Y:\\"),
    ("y:\\data", "y:\\"),
    ("\\\\server\\share\\data", "\\\\server\\share\\"),  # UNC share
    ("C:\\Users\\helium", "C:/"),                       # same drive keeps the default root
    ("c:\\Users", "C:/"),
])
def test_windows_target_on_other_drive_roots_there(target: str, expected: str) -> None:
    assert root_on_target_drive("C:/", target, ntpath) == expected


def test_posix_root_is_unchanged() -> None:
    assert root_on_target_drive("/", "/Volumes/data/run1", posixpath) == "/"


def test_root_shares_target_drive_so_validation_passes() -> None:
    root = root_on_target_drive("C:/", "Y:\\data\\run1", ntpath)
    assert ntpath.commonpath([root, "Y:\\data\\run1"]) == ntpath.abspath(root)


def test_default_path_module_is_os_path() -> None:
    assert root_on_target_drive(os.sep, os.path.join(os.sep, "data")) == os.sep
