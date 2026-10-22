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
| R-1 | Fixed after Tony's yes (see "Held items" below) | `4468eaf` | First held; the fix proposed: save the folder's pre-listing `st_mtime_ns` as an optional `info["folder_mtime_ns"]` and compare mtimes for equality in both quick checks (`_unchanged_since_cache`, `_unchanged_since_memory`), falling back to today's rule for caches without it. A new optional key in cached datasets' `info` (store format), hence the hold. |
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
| R-11 | Fixed: guards here, excepthook and log file after Tony's yes (below) | `e4d3f2d`, `1efcb87` | The Modified column goes through `_date_text` (blank if the OS can't convert), shared with `_stamp`; Live's re-read warning prints such a time in ns (no test: a log-only path, same guard). Test: `tests/test_row_tooltip.py` (1e20). Not done: `sys.excepthook`. Nothing logs to a file, so a hook alone leaves no trace in the windowed build; installing one also stops PyQt6's abort, so HeLab would go on after an unhandled exception. Question for Tony: keep aborting, or log and go on; and should HeLab write a log file (app folder) so crashes leave a trace? |
| R-12 | Fixed | `fbb072f` | Icon path from the package. Test: `tests/test_helabMainWindow.py` (started from a temp folder). Handoff: `HeLab.spec`'s `datas` lacks `ai-icon.icns`, so the packaged app still logs "Icon file not found" (the bundle has its own icon); add it or drop the check for frozen builds. |
| R-13 | Fixed: placeholders removed after Tony's yes (below) | `aad0ad4`, `c7eb0a3` | Close logged at DEBUG; unused imports gone. Question for Tony: remove "Enable feature X" and "Example Text" (and their `example_checkbox`/`example_text` keys) from Settings → General? |
| R-14 | Fixed | `305f19a` | Dropped the unread fields, constants and ordering operators; `time_load_ram`'s one write. `time_last_updated` defaults to the time the report is made. Test: `tests/test_status_report.py`. |
| R-15 | Done, star imports after the CI floor landed (below); long functions declined | `f410ccb`, `0406507` | `FolderTabWidget.py`: imports by name, dead code and unused methods gone. Left: star imports in `HelabMainWindow.py`/`SettingsDialog.py` (their import blocks are the CI floor's to change now; do after it lands) and the long `_update_folder_summary`/`_load_to_ram_cache` (declined: wording-heavy UI code, no finding in it, a split risks the summary's exact text for little gain). |
| R-16 | Fixed after Tony's yes: through a helper (below) | `c4cf63c` | Question: the manual marker's Save to folder… writes on the GUI thread into any folder the picker returns; say "a local folder" in the dialog and picker title, or send the write through a helper? |
| R-17 | Fixed | `c530e7f` | `run_analysis` catches a failure making the plot (status-bar notice); the constructor calls `live_policy`/`constant_keys` before connecting signals; `start()` shows a settings failure in the dock; `_submit` guards `values()`. Test: `tests/test_analysis_gui.py` (parameters, live_policy, backends). |
| R-18 | Fixed | `324ae2a` | Dropped `GroupData`, `GroupType`, `group_mapping`, `current_group`, `group_changed`; docstrings cut to what the panel does. Kept `ScriptsManager.get_script_metadata` (tests use it). |

Batch checks after `f410ccb`: full suite 2396 passed, 2 skipped, 2 xfailed, **no RERUN**; strict mypy
(helab, tests) and pyright clean.

Lens reviewed `c530e7f..f410ccb`: all accepted, no changes asked.

### Areas 4 and 5 (numerics, DLD and standard scripts; main, release, utils)

| ID | Outcome | Commit | Notes |
|---|---|---|---|
| R-19 | Fixed; Reference spacing after Tony's yes (below) | `f7d06e6`, `e4b1712`, `6fac7df` | The DLD module imports `Orders`, `Detection`, `order_label`, `in_box`, `smooth`, `count_orders`, `unsure`, `chosen_by_search`, `jump` (same default centre) and the detection constants from `orders.py`, and `half_maximum_width`/`refine` from `peaks.py`; its `Fractions` subclasses the shared one to add `masked` (passed by keyword). Kept: its `detect`, `window_half` (ms text), Search T helpers. The follow-up points `tests/test_dld_transfer_fractions.py` at `helab.analysis.orders`: strict mypy refused `tf.Orders`/`tf.jump` (no implicit re-export), which failed `test_typing.py` in the first full run (5 RERUNs of that one test, then failed: a real failure, not flakiness). **For Tony:** should the DLD port also take the Reference spacing (`guided_spacing`), a new setting and a detection change? |
| R-20 | Fixed | `a1b75b2` | joblib's `MAX_DEPTH` import gone; importing constants no longer loads joblib. Handoff: joblib can leave `requirements.txt` (and the lock) if nothing else needs it. |
| R-21 | Fixed | `60a8a99`, `a1b75b2`, `89531cc` | The `DEV_POTENTIAL_DATA_PATHS` comma: the fused entry was `'.../bad' + '' = '.../bad'`, so that path was and is guarded; only the meaningless `''` was swallowed; the value is unchanged. New test: each listed entry is non-empty and refused unless inside the temp folder or checkout. Dead names and imports out of `constants.py` (also checked in the star importers), the QSettings import line and read functions untouched. `main.py`: six probe log lines, star import, unused imports and commented setup_logging gone. `logging_setup.py` removed. `synchronised_dict.py` was removed too, then restored at CoCo's word: Tony decided on 2026-10-21 to keep it, unused, as a vendored MIT thread-safe dict (`.ai/sessions/2026-10-21-claude-ci-robustness/notes.md`, Tony's answers 2). Left: `QDirIterator` (unused, on the QSettings import line). |

Batch checks after `e4b1712`: full suite (`--basetemp=.ai/temp/pytest-review`) 2408 passed, 2 skipped,
2 xfailed, **no RERUN**; strict mypy (helab 148 files, tests 106) and pyright clean.

### Held items, after Tony's answers (2026-10-22, through CoCo)

Tony said yes to all five held items, each done in full on this branch with a test that fails
before and passes after, its own commit and Lens's review. R-13 and R-15 waited until CoCo landed
the CI Robustness floor in dev/v0.0.6 (`51c0ee2`), merged here as `4ca1f9f` (a merge: the branch
was pushed; no conflicts; merged tree 2443 passed, no RERUN, mypy/pyright clean).

| ID | Commit | What was done | Test (fails before) |
|---|---|---|---|
| R-1 | `4468eaf` | A load stats the folder before listing (the summary's stat, moved: one "folder mtime" trace stat) and keeps `st_mtime_ns` as the dataset's optional `info["folder_mtime_ns"]` (`_write_dataset`; `confirm_dataset` refreshes it unless the row's listing is newer) and in `loaded`, which `memory_check` carries. Both quick checks need it equal (`fingerprints._mtime_unchanged`). Within `RACY_SECONDS` (2 s; `min(2, SETTLE_SECONDS)`, so none in tests) of the listing it is None: the next check lists. Older caches keep the old rule. A Live save records None (one listing after it). | `tests/test_cache_first.py`: server clock 1 h behind, 1 h ahead, a FAT 2 s step; cached and RAM-held (6 failed before) |
| R-11 | `1efcb87` | `helab/utils/app_log.py`: `<app folder>/logs/helab.log` (INFO up, 2 MB × 4 older files); `sys.excepthook` logs with the traceback and carries on, status-bar note "Unexpected error, logged: <type>: <message>" on the GUI thread; `threading.excepthook` logs; one log per (type, file, line) a minute, repeats counted. | `tests/test_app_log.py` (6; only tmp folders) |
| R-16 | `c4cf63c` | Helper op `marker_save` (`io_ops.markers.save_marker_copy`), foreground like `root_create`; the dialog submits it, asks Replace after the save ended; refused/error warnings. | `tests/test_root_gui.py` (incl. a real helper while the GUI process may not open the file), `tests/test_helper_dispatch.py` |
| R-13 | `c7eb0a3` | "Enable feature X" / "Example Text", their rows and constants removed; the keys in `RETIRED` (removed on save); the 10 px spacer before "When selecting another folder:" removed. | `tests/test_settingsDialog.py` |
| R-15 | `0406507` | `HelabMainWindow.py`, `SettingsDialog.py` import by name; `QDirIterator` gone. | `tests/test_explicit_imports.py` (no star import in helab/ outside `legacy_plotly`) |
| R-19 | `6fac7df` | The DLD Transfer fractions uses `orders.detect` (guided) and drops its own; Orders › Reference spacing (15 ms, in ms, Auto); version 2 → 3. | `tests/test_dld_transfer_fractions.py`: a bump between the orders (2 of 4 seeds failed before), the reference setting |

Also `22ee3fb`: `tests/test_settings_defaults.py` imports QtWebEngineWidgets at the top. Lens found
that file, run in one process after test_settingsDialog.py and test_constants.py, failed 3 tests
(QtWebEngineWidgets after a QApplication); it predated this branch (same at `4ca1f9f`).

Lens's new finding R-22 (low, Needs Tony, no code change): `_settled` treats a file with a future
mtime as young, so a server clock more than 5 s ahead holds new shots as still being written.

Full checks after each item: no RERUN in any full run, except two runs before the R-16 commit
(`test_typing.py::test_mypy_helab_tests_strict` and
`test_helper_dispatch.py::test_the_routing_table_covers_every_handler_and_named_operation`, each
rerun 5 times and failed: real failures from my test's `markers.os` patch and the routing table
lacking `marker_save`, fixed before the commit). Final: see the handoff.
