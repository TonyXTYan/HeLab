"""Read-only diagnosis: reproduce Windows newlines and inspect Qt geometry."""
from pathlib import Path
import sys

import pytest
from PyQt6.QtCore import QPoint

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests"))
import conftest as _test_environment  # Apply the project's private directory and settling overrides first.
from test_cache_first import test_files_still_being_written_are_left_for_the_next_load as _check_progress
from test_large_folder import test_the_check_of_data_already_in_ram_counts_only_what_it_adds as _check_large_folder
from test_hover_menu_button import make_button


@pytest.mark.parametrize("target", ["progress", "large_folder"])
def test_windows_crlf_reproduces_the_ci_assertion(target, monkeypatch, tmp_path):
    original = Path.write_text

    def windows_write(self, data, *args, **kwargs):
        kwargs["newline"] = "\r\n"
        return original(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", windows_write)
    with pytest.raises(AssertionError):
        if target == "progress":
            _check_progress(monkeypatch, tmp_path)
        else:
            _check_large_folder(tmp_path)
    data = (tmp_path / "source" / "d_txy_forc1.txt").read_bytes() if target == "progress" else None
    print(f"{target}: reproduced assertion with CRLF; first shot={data!r}")


def test_report_screen_edge_geometry(qtbot):
    window, button, menu = make_button(qtbot)
    area = button.screen().availableGeometry()
    window.move(area.right() + 1 - window.frameGeometry().width(), area.top() + 100)
    qtbot.wait(100)
    right = button.mapToGlobal(QPoint(button.width(), 0)).x()
    print({"screen": (area.width(), area.height()), "window_width": window.frameGeometry().width(),
           "button_right": right, "screen_right": area.right() + 1,
           "remaining_width": area.right() + 1 - right, "menu_width": menu.sizeHint().width(),
           "overflow": right + menu.sizeHint().width() > area.right() + 1})
