# Codebase review: Mend's notes

Worker: Mend (Claude Opus 5.5). Branch `agent/codebase-review` from `fc0f50d`.

## Baseline (2026-10-22, before any change)

From the floor root with `floor-env.sh`:

- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`: 2378 passed, 2 skipped,
  2 xfailed in 128 s; **no RERUN**. Two warnings, both pyqtgraph's NumPy 2.5 deprecation
  (`arr.shape = (3, 3)` in `pyqtgraph/functions.py`, from `test_t_spectrum.py`).
- `mypy helab/ --strict`: no issues (150 files). `mypy tests --strict`: no issues (104 files).
- `pyright helab tests`: 0 errors, 0 warnings.

## Findings

Each of Lens's findings (`findings.md`) as fixed (commit), declined (why) or needs Tony. Every
correctness fix has a test that fails without it and passes with it (checked by reverting the
`helab/` change and rerunning the test).

### Area 1 (I/O helpers, IOService, store, FolderCache, roots)

| ID | Outcome | Commit | Notes |
|---|---|---|---|
| R-1 | **Needs Tony** (held by CoCo, 2026-10-22) | — | Fix proposed: save the folder's pre-listing `st_mtime_ns` as an optional `info["folder_mtime_ns"]` and compare mtimes for equality in both quick checks (`_unchanged_since_cache`, `_unchanged_since_memory`), falling back to today's rule for caches without it. A new optional key in cached datasets' `info` (store format), hence the hold. |
| R-2 | Fixed | `265f35e` | Each array written to the helper's folder resets `last_activity` (no event, so no wording change). Test: `tests/test_io_service_run.py`. Handoff note: every Live autosave rewrites the whole held dataset to temp and the helper reads it back (by design). |
| R-3 | Fixed | `6299fdd` | After `poll()` says the helper exited, the reader reads the file to its end. Test: `tests/test_io_service_run.py`. |
| R-4 | Fixed | `af632a3` | `root_at`/`other_root_locations` raise `StoreError`; `list_folder` treats an unreadable table as "may have a row" (`_may_have_root`) and `_discover_root` also catches a root write's raw `sqlite3.Error`. Tests: `tests/test_root_marker_errors.py` (3). |
| R-5 | Fixed | `2447a66` | The store's own `StoreError`s pass through `_cache_store` unchanged; an `OSError` making its folder is `OPEN_FAILED`; "Mount information is unavailable" stays for the mount and resolver steps. The existing expectation at `test_cache_store_open.py:124` (a genuine mount error) is still right and unchanged. New test (needs `no_auto_data_root`: conftest's seeding opens the store first). |
| R-6 | Fixed | `d586f9d` | Decision: confirmed if the location is already confirmed with this UUID, else pending iff another confirmed location has it. Test: `tests/test_root_duplicates.py`. Handoff: a pending location whose other locations were all forgotten is now confirmed by its next listing (no question asked), with the UUID's cached data. |
| R-7 | Fixed (confirmed first) | `2559c77` | The test showed the tab's load cancelled ("Cancelled — Retry") when another tab's status check found a new signature. A signature change now only drops the folder's datasets (`_folder_changed`); `_invalidate_data` stays for Clear. Test: `tests/test_folder_cache.py`. |
| R-8 | Fixed | `34bcb78` | stderr goes to `stderr.txt` in the helper's folder; on an incomplete exit its last 2 KB are logged at WARNING. The error event's message is unchanged (no wording change). Test: `tests/test_io_service_run.py`. |
| R-9 | Fixed | `6ddec21` | `_entry_stat(..., follow_symlinks=False)`, traced as `lstat` with `syscall`, so `tests/test_io_trace.py` (other floor's) is unchanged. Test: `tests/test_two_step_browse.py`. |
| R-10 | Partly done | `f684720` | Lifted `_on_root_event`, `_on_verification_event`, `_on_finishing_event` out of `_on_event` unchanged. Declined: the scan and load blocks (they reassign `kind`/`event` for the shared tail, so a split needs a return protocol harder to follow than the blocks) and `_load`'s cache-read block (nine locals and an early stop through `stop_if_missing`). |

Batch checks after R-2..R-10 (`f684720`): full suite 2390 passed, 2 skipped, 2 xfailed, **no RERUN**
(twice, the second run covering R-10); strict mypy (helab, tests) and pyright clean. Lens reviewed
`265f35e..f684720`: no changes asked.

### Areas 2 and 3 (models, views, analysis core, plots)

| ID | Outcome | Commit | Notes |
|---|---|---|---|
| R-11 | Fixed (guards); **excepthook needs Tony** | `e4d3f2d` | The Modified column goes through `_date_text` (blank if the OS can't convert), shared with `_stamp`; Live's re-read warning prints such a time in ns (no test: a log-only path, same guard). Test: `tests/test_row_tooltip.py` (1e20). Not done: `sys.excepthook`. Nothing logs to a file, so a hook alone leaves no trace in the windowed build; installing one also stops PyQt6's abort, so HeLab would go on after an unhandled exception. Question for Tony: keep aborting, or log and go on; and should HeLab write a log file (app folder) so crashes leave a trace? |
| R-12 | Fixed | `fbb072f` | Icon path from the package. Test: `tests/test_helabMainWindow.py` (started from a temp folder). Handoff: `HeLab.spec`'s `datas` lacks `ai-icon.icns`, so the packaged app still logs "Icon file not found" (the bundle has its own icon); add it or drop the check for frozen builds. |
| R-13 | Part fixed; **controls need Tony** | `aad0ad4` | Close logged at DEBUG; unused imports gone. Question for Tony: remove "Enable feature X" and "Example Text" (and their `example_checkbox`/`example_text` keys) from Settings → General? |
| R-14 | Fixed | `305f19a` | Dropped the unread fields, constants and ordering operators; `time_load_ram`'s one write. `time_last_updated` defaults to the time the report is made. Test: `tests/test_status_report.py`. |
| R-15 | Part done | `f410ccb` | `FolderTabWidget.py`: imports by name, dead code and unused methods gone. Left: star imports in `HelabMainWindow.py`/`SettingsDialog.py` (their import blocks are the CI floor's to change now; do after it lands) and the long `_update_folder_summary`/`_load_to_ram_cache` (declined: wording-heavy UI code, no finding in it, a split risks the summary's exact text for little gain). |
| R-16 | **Needs Tony** (note only) | — | Question: the manual marker's Save to folder… writes on the GUI thread into any folder the picker returns; say "a local folder" in the dialog and picker title, or send the write through a helper? |
| R-17 | Fixed | `c530e7f` | `run_analysis` catches a failure making the plot (status-bar notice); the constructor calls `live_policy`/`constant_keys` before connecting signals; `start()` shows a settings failure in the dock; `_submit` guards `values()`. Test: `tests/test_analysis_gui.py` (parameters, live_policy, backends). |
| R-18 | Fixed | `324ae2a` | Dropped `GroupData`, `GroupType`, `group_mapping`, `current_group`, `group_changed`; docstrings cut to what the panel does. Kept `ScriptsManager.get_script_metadata` (tests use it). |

Batch checks after `f410ccb`: full suite 2396 passed, 2 skipped, 2 xfailed, **no RERUN**; strict mypy
(helab, tests) and pyright clean.
