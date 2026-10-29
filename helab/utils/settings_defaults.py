"""Every ``QSettings`` key HeLab reads, with its type, default and what it is: the one place a
setting's default is written (``roadmaps/agent-workflow.md``, "Hard-coded defaults").

Reads go through ``read_setting``, which passes the table's default, so a key missing from the
table can't be read (``KeyError``) and no read has a default of its own
(``tests/test_settings_defaults.py`` checks the code and the reads a real window makes). A
reader still checks the value it gets (a malformed or out-of-range saved value is replaced by
the default there, e.g. ``constants.read_disk_budget``).

Standard library and QtCore only: ``helab.utils.constants`` and the I/O helpers import it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import QSettings


@dataclass(frozen=True)
class Setting:
    key: str
    type: type  # What a typed read converts the saved value to (``read_setting(..., typed=True)``).
    default: Any  # The value when nothing is saved: the same type, or None for "unset".
    description: str


DIR_TEMPS_SETTING = "dir_temps"
DIR_CACHES_SETTING = "dir_caches"
LOAD_MODE_SETTING = "load_on_select_mode"
CHECK_LEVEL_SETTING = "cached_data_check_level"
SIMULTANEOUS_IO_SETTING = "simultaneous_folder_io_operations"
AUTO_SCAN_VISIBLE_SETTING = "auto_basic_scan_visible_folders"
DISK_BUDGET_SETTING = "disk_cache_budget"
RAM_BUDGET_SETTING = "ram_budget_steps"
LIVE_INTERVAL_SETTING = "live_check_interval_seconds"
LIVE_AUTOSAVE_SETTING = "live_autosave_shots"
PLOT_AUTO_RELOAD_SETTING = "plot_auto_reload"
RESULT_REUSE_SETTING = "result_reuse"
# File › Work Offline (cache-only browsing): remembered across restarts (Tony, 2026-10-26: D2).
WORK_OFFLINE_SETTING = "work_offline"
LOG_KEEP_SETTING = "log_files_keep"
# Where HeLab's own TXY go (Q9.3): HeLab's temp folder or its disk cache folder; writing them beside
# the raw files is a per-folder flag (Q9.7, the store's ``convert_prefs.write_beside``), not this.
CONVERT_OUTPUT_SETTING = "converted_txy_output"
CONVERT_OUTPUTS = ("cache", "temp")
# Which detector profile and backend HeLab's conversions use (Settings → TXY converter; Q6.11). The
# profile is a built-in's name or a user profile's (``helab.convert.user_profiles``).
CONVERT_PROFILE_SETTING = "convert_profile"
CONVERT_BACKEND_SETTING = "convert_backend"
# Live auto-convert (TXY converter stage 4): the folder that starts Live and auto-convert when HeLab
# launches (Q9.6, Q18.3: one; helab/views/live_launch.py), and the hits below which a converted shot notifies (Q9.4).
LIVE_LAUNCH_FOLDER_SETTING = "live_launch_folder"
LIVE_LAUNCH_FOLDERS_SETTING = "live_launch_folders"  # (Before Q18.3: a list; its first becomes the folder.)
CONVERT_LOW_HITS_SETTING = "convert_low_hits"
TXY_SOURCE_SETTING = "txy_source"
# The plots that reopen at start (helab/views/plots/arrangement.py; presets are in the disk cache store).
REOPEN_PLOTS_SETTING = "reopen_plots_at_start"
OPEN_PLOTS_SETTING = "open_plots"

SETTINGS: tuple[Setting, ...] = (
    Setting(DIR_TEMPS_SETTING, str, "",
            "Folder for temporary files (Settings → General). Unset: the first writable of the default "
            "folders (constants.DIR_TEMPS_CANDIDATES), saved at startup."),
    Setting(DIR_CACHES_SETTING, str, "",
            "The disk cache's folder, changed only by moving the cache (Settings → General → Change…). "
            "Unset: the first writable default folder (constants.DIR_CACHES_CANDIDATES), saved at startup."),
    Setting(LOAD_MODE_SETTING, str, "finish",
            "What selecting another folder does to a running load: cancel, finish (in the background) "
            "or queue (folders kept selected for 3 s) (Settings → General, Folder I/O menu)."),
    Setting(CHECK_LEVEL_SETTING, str, "medium",
            "How many cached TXY files the quick check of an unmodified folder stats: swift, fast, "
            "medium, high or full (lists the folder) (Settings → General)."),
    Setting(SIMULTANEOUS_IO_SETTING, int, 1,
            "Simultaneous background I/O operations, 1 to 32 (Settings → General)."),
    Setting(AUTO_SCAN_VISIBLE_SETTING, bool, False,
            "Check the status of visible folders without saved results automatically "
            "(Settings → General, View menu)."),
    Setting(DISK_BUDGET_SETTING, int, 8 * 10**9,
            "The disk cache budget in bytes (SI: 8 GB), at least 1 GB; live data only (Settings → Cache)."),
    Setting(RAM_BUDGET_SETTING, int, 16,
            "The RAM budget in steps of 1/128 of the computer's RAM, at least max(1 GB, 1 step), at "
            "most 64 (Settings → Cache)."),
    Setting(LIVE_INTERVAL_SETTING, float, 3.0,
            "Seconds from the end of one Live check to the start of the next, 0.5 to 600 "
            "(Settings → General)."),
    Setting(LIVE_AUTOSAVE_SETTING, int, 10,
            "New Live shots held in RAM before the folder is saved to the disk cache, 1 to 100,000 "
            "(Settings → Cache)."),
    Setting(PLOT_AUTO_RELOAD_SETTING, bool, True,
            "A plot released to free RAM reloads when it is shown again (Settings → Cache)."),
    Setting(RESULT_REUSE_SETTING, bool, True,
            "Plots that support it (Correlations, Release time) show their result saved in the disk cache "
            "for the same data, script and settings instead of computing it again, and save new ones; off: "
            "neither (Settings → Cache)."),
    Setting(WORK_OFFLINE_SETTING, bool, False,
            "File › Work Offline: browse and analyse cached data only, reading no source folder and no "
            "server, until turned off (also at the next start)."),
    Setting(LOG_KEEP_SETTING, int, 300,
            "Log files to keep, every session's helab-<pid>.log files and their rotated copies counted; "
            "at startup the oldest beyond it are deleted, never a running HeLab's, 1 to 100,000 "
            "(Settings → General)."),
    Setting(CONVERT_OUTPUT_SETTING, str, "cache",
            "Where HeLab's own TXY files (d_txy_helab_<tag>_<N>.txt) go: cache (the disk cache's folder, keyed by "
            "the folder's data root; a folder without one goes to temp) or temp (HeLab's temp folder). "
            "Folders set to write them beside the raw files do that instead."),
    Setting(CONVERT_PROFILE_SETTING, str, "matlab-2019",
            "The detector profile HeLab's conversions use (Settings → TXY converter): a built-in's name or a user "
            "profile's; one that no longer exists reads as matlab-2019. HeLab's TXY of another profile aren't "
            "loaded until converted again."),
    Setting(CONVERT_BACKEND_SETTING, str, "numpy",
            "The converter backend HeLab's conversions use (Settings → TXY converter): numpy (always there), or an "
            "optional compiled one; a conversion with a backend that can't run says why."),
    Setting(LIVE_LAUNCH_FOLDER_SETTING, str, "",
            "The folder that opens, alone, and starts Live with auto-convert when HeLab launches (the Live line's "
            "Auto-convert menu; one folder, Q18.3): its path. Unset: none, and HeLab opens its usual first tab."),
    Setting(LIVE_LAUNCH_FOLDERS_SETTING, str, "",
            "Before Q18.3: the launch folders as a JSON list of paths. Read once when the single folder isn't set: "
            "its first becomes that folder, and this key is removed."),
    Setting(TXY_SOURCE_SETTING, str, "helab-priority",
            "Which TXY tabs and Live load (Settings → TXY converter, Q18.2): helab-priority (HeLab's of the "
            "conversion profile where they exist, MATLAB's for the rest), matlab-priority, helab-only or "
            "matlab-only; anything else reads as helab-priority. A plot may choose another in its settings."),
    Setting(CONVERT_LOW_HITS_SETTING, int, 100,
            "Live auto-convert: a converted shot with fewer hits than this raises a system notification, once "
            "per shot (the Auto-convert menu); 0: never."),
    # The plots that reopen at start (keep these rows together).
    Setting(REOPEN_PLOTS_SETTING, bool, True,
            "Reopen the plots open when HeLab last quit; each reruns on its folder's data in RAM or the disk "
            "cache, never reading the folder itself (Settings → General)."),
    Setting(OPEN_PLOTS_SETTING, str, "",
            "The plots open when HeLab last quit (or last opened or closed a plot), with their settings and "
            "places: an arrangement record (helab.analysis.presets, JSON). Unset: none."),
)

# Keys under a prefix: Settings → Lab parameters saves only the lab constants the user set,
# ``lab_constants/<key>`` in SI units (``helab.utils.lab_parameters``); unset, the constants
# table's default applies (``helab.analysis.physics.CONSTANTS``).
PREFIXES: tuple[Setting, ...] = (
    Setting("lab_constants/", float, None,
            "A lab constant the user set (Settings → Lab parameters), in SI units; unset: "
            "helab.analysis.physics.CONSTANTS's default."),
)

# Keys older HeLabs saved, now only removed when settings are saved (the example_* pair: Settings →
# General's placeholders, removed by Tony's decision, 2026-10-22).
RETIRED = ("simultaneous_folder_scans", "simultaneous_folder_loads", "example_checkbox", "example_text",
           "view_toggle_thread_status")  # (View › Toggle Thread Status Auto Pop-up: did nothing; Tony, 2026-10-26.)

_BY_KEY = {setting.key: setting for setting in SETTINGS}


def setting(key: str) -> Setting:
    """The table's row for ``key`` (a prefix row for ``lab_constants/<key>``); KeyError if none."""
    found = _BY_KEY.get(key)
    if found is not None:
        return found
    for prefix in PREFIXES:
        if key.startswith(prefix.key) and len(key) > len(prefix.key):
            return prefix
    raise KeyError(f"{key!r} is not in HeLab's settings table (helab/utils/settings_defaults.py)")


def setting_default(key: str) -> Any:
    return setting(key).default


def read_setting(settings: QSettings, key: str, *, typed: bool = False) -> Any:
    """``key``'s saved value, else the table's default; ``typed`` converts it to the row's type
    (as ``QSettings.value(..., type=...)`` does), otherwise it comes as saved. Only bool and str
    rows read typed: PyQt's ``type=int`` is a 32-bit int, so 8 GB (saved or the default) reads
    as 0; numbers are read as saved and converted by their reader."""
    row = setting(key)
    if typed:
        if row.type not in (bool, str):
            raise ValueError(f"{key!r} is a {row.type.__name__}: read it untyped and convert it")
        return settings.value(key, row.default, type=row.type)
    return settings.value(key, row.default)
