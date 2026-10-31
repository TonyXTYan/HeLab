"""cache-1 (area review): when the data root known at a folder changes identity or goes, what the old
root's store said about the folders it held (Don't cache, Don't auto-load, the converter's
``write_beside``) no longer applies in RAM, as for its constants; this session's flag writes still
running are kept, and so are the flags of folders inside a nested root below."""
from __future__ import annotations

import os
from typing import Any

import pytest

from helab.utils.folder_cache import FolderCache
from helab.utils.io_service import IORequest, IOService

A, B = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
ROOT = os.path.join(os.sep, "data", "root")
RUN, INNER = os.path.join(ROOT, "run"), os.path.join(ROOT, "inner")


def frozen(monkeypatch: pytest.MonkeyPatch) -> tuple[IOService, FolderCache]:
    service = IOService()
    service.timer.stop()
    monkeypatch.setattr(service, "_dispatch", lambda: None)
    return service, FolderCache(service)


def flagged(cache: FolderCache, path: str) -> None:
    cache.remember_prefs(path, {"no_cache": True, "no_auto_load": True, "set_at": 10.0})
    cache._remember_convert_prefs(path, {"write_beside": True, "set_at": 11.0})


@pytest.mark.parametrize("change", ["new uuid", "marker removed", "another root found"])
def test_a_roots_change_of_identity_drops_the_old_roots_flags(monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    service, cache = frozen(monkeypatch)
    try:
        cache._root_seen(ROOT, A, "old")
        cache._root_seen(INNER, B, "inner")  # (A nested root: its folders' flags are its own.)
        flagged(cache, RUN)
        flagged(cache, INNER)
        changed: list[str] = []
        cache.folderPrefsChanged.connect(changed.append)
        event: dict[str, Any]
        if change == "new uuid":
            event = {"kind": "root_changed", "path": ROOT, "location": "vol://test/data/root", "uuid": B,
                     "label": "replacement"}
        elif change == "marker removed":
            event = {"kind": "root_changed", "path": ROOT, "location": "vol://test/data/root",
                     "reason": "marker removed"}
        else:
            event = {"kind": "root_found", "path": ROOT, "location": "vol://other/data/root", "uuid": B,
                     "label": "other"}
        service.resultReady.emit(IORequest("probe", 0, ROOT, "list", {}, 60), event)
        assert cache.folder_prefs(RUN) == {"no_cache": False, "no_auto_load": False}
        assert not cache.write_beside(RUN) and RUN in changed
        assert cache.folder_prefs(INNER) == {"no_cache": True, "no_auto_load": True} and cache.write_beside(INNER)
        # A listing under the new identity finding none now stands (it used to fill in only unknown folders).
        cache.remember_prefs(RUN, {}, known=False)
        assert cache.folder_prefs(RUN) == {"no_cache": False, "no_auto_load": False}
    finally:
        service.shutdown()


def test_a_flag_write_still_running_survives_the_roots_change(monkeypatch: pytest.MonkeyPatch) -> None:
    service, cache = frozen(monkeypatch)
    try:
        cache._root_seen(ROOT, A, "old")
        cache.remember_prefs(RUN, {"no_cache": False, "no_auto_load": True, "set_at": 50.0}, confirmed=False)
        cache._pref_writes["job"] = (RUN, 50.0, "tab")  # (This session's choice, being saved.)
        service.resultReady.emit(IORequest("probe", 0, ROOT, "list", {}, 60), {
            "kind": "root_changed", "path": ROOT, "location": "vol://test/data/root", "reason": "marker removed"})
        assert cache.folder_prefs(RUN) == {"no_cache": False, "no_auto_load": True}
    finally:
        service.shutdown()
