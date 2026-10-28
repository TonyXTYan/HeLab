"""Folders that start Live and auto-convert when HeLab launches (TXY converter stage 4, Q9.6).

The user sets a folder from the Live line's Auto-convert menu ("Start Live and auto-convert here
when HeLab launches"); the list is a setting (``live_launch_folders``, a JSON list of paths), so it
is known before any folder is listed and works for folders without a ``.helab-root``.

At launch (``start``, from the main window once its first tab is open) each folder opens in a tab
of its own and is set to auto-convert this session (``FolderCache.auto_convert``). Live follows
the current tab, so it starts in one only: the first folder's tab, opened last so it is current;
the others' tab tooltips say so. That folder loads as a deliberate selection (cache first) when it
holds data, and Live turns on once its data shows, or once its listing finds no shots yet, under
the normal rules (``FolderExplorer.start_live``), never forced (``LaunchFolder``). A folder that is
missing or can't be listed now raises one system notification (``events.notify``) and is left as
it is: no retry. Working offline nothing starts, and a notification says so.

Never under pytest unless a test asks (``start(..., in_tests=True)``): tests own their settings."""
from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Callable

from PyQt6 import sip
from PyQt6.QtCore import QObject

from helab.utils import events
from helab.utils.folder_cache import FolderCache, get_folder_cache
from helab.utils.io_service import get_io_service
from helab.utils.settings_defaults import LIVE_LAUNCH_FOLDERS_SETTING, read_setting
from helab.utils.settings_store import app_settings

if TYPE_CHECKING:
    from helab.views.FolderExplorer import FolderExplorer
    from helab.views.HelabMainWindow import HelabMainWindow

LIVE_LAUNCH = "live_launch"  # The events' ``source``: a folder set to start Live at launch.


def launch_folders() -> list[str]:
    """The folders set to start Live and auto-convert at launch, in the order they were set."""
    saved = read_setting(app_settings(), LIVE_LAUNCH_FOLDERS_SETTING)
    try:
        value = json.loads(saved) if isinstance(saved, str) and saved else []
    except ValueError:
        logging.warning("The folders to start Live at launch couldn't be read (%r): none started", saved)
        return []
    folders: list[str] = []
    for path in value if isinstance(value, list) else ():
        if isinstance(path, str) and path.strip() and FolderCache.key(path) not in folders:
            folders.append(FolderCache.key(path))
    return folders


def starts_at_launch(path: str) -> bool:
    return FolderCache.key(path) in launch_folders()


def set_starts_at_launch(path: str, on: bool) -> None:
    """Add a folder to the launch list (at its end), or take it off."""
    folders = [folder for folder in launch_folders() if folder != FolderCache.key(path)]
    if on:
        folders.append(FolderCache.key(path))
    settings = app_settings()
    if folders:
        settings.setValue(LIVE_LAUNCH_FOLDERS_SETTING, json.dumps(folders))
    else:
        settings.remove(LIVE_LAUNCH_FOLDERS_SETTING)
    logging.info("Start Live and auto-convert at launch %s: %s", "on" if on else "off", path)


def _name(path: str) -> str:
    return os.path.basename(path.rstrip(os.sep)) or path


def _notify(message: str, folder: str) -> None:
    """A system notification (once per folder per session)."""
    events.notify(events.LIVE_ERROR, message, title="HeLab: Live at launch", key=(LIVE_LAUNCH, folder),
                  desktop=True, path=folder, source=LIVE_LAUNCH)


def start(window: HelabMainWindow, *, in_tests: bool = False) -> list[LaunchFolder]:
    """Open the launch folders (a tab each) and start Live with auto-convert in the first; what
    watches that folder until Live is on (empty when nothing starts)."""
    if "PYTEST_CURRENT_TEST" in os.environ and not in_tests:
        return []
    folders = launch_folders()
    if not folders or window._closing:
        return []
    cache = get_folder_cache(get_io_service())
    if cache.offline:
        names = ", ".join(_name(folder) for folder in folders)
        message = (f"Working offline: Live and auto-convert not started for {names} (set to start when HeLab "
                   "launches). Turn off File › Work Offline, then turn Live on in its tab.")
        events.notify(events.LIVE_ERROR, message, title="HeLab: Live at launch", desktop=True, source=LIVE_LAUNCH)
        window.show_status_notice(message)
        return []
    cache.auto_convert.update(folders)
    first = folders[0]
    for folder in (*folders[1:], first):
        window.add_new_folder_explorer_tab(target_path=folder)
        index = window.tab_widget.currentIndex()
        if folder != first:
            window.tab_widget.setTabToolTip(index, (
                f"{folder}\nSet to start Live and auto-convert when HeLab launches. Live follows the current tab, "
                f"so it started in {_name(first)}'s tab only: turn Live on here to watch this folder instead."))
    from helab.views.FolderExplorer import FolderExplorer
    explorer = window.tab_widget.currentWidget()
    if not isinstance(explorer, FolderExplorer):
        return []
    logging.info("Live at launch: %s%s", first, f" (also opened: {', '.join(folders[1:])})" if folders[1:] else "")
    return [LaunchFolder(explorer, first, window.show_status_notice)]


class LaunchFolder(QObject):
    """A launch folder's tab until Live is on (as an arrangement preset's ``PresetFolder``): it
    loads as a deliberate selection once known to hold data, and Live turns on once the data
    shows or the listing finds no shots yet. A folder that can't be listed (missing, unmounted)
    or where Live can't start is notified once; selecting another folder or closing the tab ends it."""

    def __init__(self, explorer: FolderExplorer, folder: str, notice: Callable[[str], None]) -> None:
        super().__init__(explorer)
        self.explorer, self.folder, self._notice = explorer, folder, notice
        self.done = False
        self.load_asked = False
        self.data_expected = False
        self._signals = [explorer.dataLoaded, explorer.loadStateChanged, explorer.liveChanged,
                         explorer.model.activityChanged]
        for signal in self._signals:
            signal.connect(self.check)
        self.check()

    def check(self, *_: object) -> None:
        if self.done:
            return
        explorer = self.explorer
        if sip.isdeleted(explorer) or explorer.closed:
            self.finish()
            return
        name = _name(self.folder)
        if explorer.selected_path_globally != self.folder:
            self._notice(f"Live at launch not started for {name}: another folder was selected")
            self.finish()
            return
        node = explorer.model.nodes.get(self.folder)
        if node is not None and node.error:
            _notify(f"Live and auto-convert not started for {name}: it can't be opened now "
                    f"({node.error.removesuffix(' — Retry')}). {self.folder}", self.folder)
            self.finish()
            return
        if not self.load_asked:
            listed = node is not None and node.report is not None
            if self._shown() or explorer.model.cache.disk_cached(self.folder) or (
                    node is not None and listed and node.txy_count > 0):
                self.load_asked = self.data_expected = True
                explorer.load_to_ram_cache(self.folder, dwell=False, explicit=True)
                if self.done:
                    return  # (A load answered at once, and this ran again meanwhile.)
            elif listed:
                self.load_asked = True  # No TXY files: Live starts before the first shot.
            else:
                return  # Until the tab's listing answers.
        if self._busy():
            return
        if explorer.live is not None:
            self.finish()  # Turned on already (by the user).
            return
        reason = explorer.live_unavailable(self.folder)
        # Done before Live starts: starting shows its data, whose signals would start it again here.
        self.done = True
        if not reason and explorer.start_live():
            self._notice(f"Live and auto-convert on for {name} (set to start when HeLab launches)")
        else:
            why = explorer.load_error.removesuffix(" — Retry") if explorer.load_error else reason
            _notify(f"Live and auto-convert not started for {name}: {why or 'Live could not start'}. "
                    f"{self.folder}", self.folder)
        self._disconnect()

    def _shown(self) -> bool:
        explorer = self.explorer
        return explorer.folder_opened_path == self.folder and explorer.folder_opened_data is not None

    def _busy(self) -> bool:
        """Its load (or the wait before it) still runs, so its data may yet show (as ``PresetFolder._busy``)."""
        explorer = self.explorer
        if (explorer.loading and explorer.load_path == self.folder) or explorer.load_waiting or explorer.settling:
            return True
        return (self.data_expected and not self._shown() and not explorer.load_error
                and explorer.large_state(self.folder) is None)

    def finish(self) -> None:
        if self.done:
            return
        self.done = True
        self._disconnect()

    def _disconnect(self) -> None:
        for signal in self._signals:
            try:
                signal.disconnect(self.check)
            except (TypeError, RuntimeError):
                pass
        self.deleteLater()
