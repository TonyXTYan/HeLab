# Quick fixes, batch 2: notes (Ferrule, 2026-10-26)

Brief: [brief.md](brief.md). Branch `agent/quick-fixes-2`, base `0840acb`.

## Job 1: `cache_move.verify` didn't check saved results' files

- **Cause:** `verify(cache_dir, store_id)` (`helab/utils/cache_move.py`) read
  `SELECT file, bytes FROM datasets UNION ALL SELECT file, bytes FROM pending_saves` and checked
  each file under `datasets/`. Saved results (R2) name their files `results/<uuid>.npz` in the
  `results` and `pending_results` tables; neither was read, so a copy missing or truncating one
  passed verification.
- **Fix:** also read `(file, bytes)` from `results` and `pending_results` when the store has
  them (a read-only store from before result caching may not: `sqlite_master` check, as
  `cache_store._has_table` does), and resolve `results/<name>` under the store root, like
  `CacheStore._store_file`. The messages stay the same ("a data file is missing from the copy
  (results/….npz)", "a copied data file has the wrong size (…)").
- **Test:** `tests/test_cache_move.py::test_a_copy_with_a_damaged_result_file_fails_verification`
  (a saved or a waiting result; its copied file removed or truncated): 4 cases, all fail without
  the change, pass with it.
- **Checks:** full suite `-n 4 --reruns 5 --reruns-delay 1`: 4311 passed, 2 skipped, 2 xfailed,
  no RERUN; mypy --strict helab and tests, pyright helab tests: clean.
- **Commit:** `9d90156`.
- **Proposed known-issues line** (move to fixed): `- [x] cache_move.verify didn't check saved
  results' files (results, pending_results): a copy missing or truncating one passed (9d90156).`

## Job 2: `roots_verify` was missing from `io_helper.CACHE_ONLY`

- **Cause:** `IOService.CACHE_OPERATIONS` lists `roots_verify`; `io_helper.CACHE_ONLY` didn't, so
  a `roots_verify` without `cache` reached `verify_known_roots(request["cache"], …)` and failed
  with `KeyError: 'cache'` instead of "The disk cache is off for this session". `FolderCache`
  always sends the cache (`_verify_roots` returns early without `store_options()`), so it
  couldn't happen today.
- **Other differences:** after the fix, `CACHE_ONLY` has two operations `CACHE_OPERATIONS`
  doesn't: `root_reassign` and `root_remove`. That's right: the helper needs the cache for
  them, and the app counts them as opening it through their payload (`IOService.uses_cache`:
  `operation in CACHE_OPERATIONS or payload.get("cache")`), so a cache move still holds them.
  No other dispatched operation reads `request["cache"]` outside `CACHE_ONLY`.
- **Fix:** add `roots_verify` to `CACHE_ONLY` (comment names the app's list and the test).
- **Tests** (`tests/test_helper_dispatch.py`):
  `test_the_helpers_cache_only_operations_are_the_apps_cache_operations` (subset, and the extras
  are exactly the two marker writes) and
  `test_an_operation_sent_without_the_cache_is_refused_or_runs_without_it` (every route with a
  `cache`, sent without it: the clear refusal, or the handler runs). Both fail for
  `roots_verify` without the fix.
- **Commit:** `778641a`.
- **Proposed known-issues line** (move to fixed): `- [x] roots_verify was missing from
  io_helper.CACHE_ONLY (a vague KeyError without a cache); a test keeps it in step with
  IOService.CACHE_OPERATIONS (778641a).`

## Job 3: a gone data root's saved-result counts stayed in RAM

- **Cause:** a root that goes or changes UUID while HeLab runs reaches `FolderCache` in three
  places, all calling `_root_constants_gone` (folder constants) before `data_roots` changes:
  `_root_seen` (another UUID at the folder), `_root_gone` (`root_changed` without a UUID:
  forgotten, marker removed or invalid) and `root_changed` at a folder this session hadn't seen
  as a root. None touched `result_counts`, so "Cached analysis: N results" stayed until a
  listing measured the folder again. (The flags aren't dropped there either; `removed(affected,
  KINDS)` covers dataset kinds only, not results.)
- **Fix:** `_root_results_gone(path)`, called beside `_root_constants_gone` at those three
  places: deletes the counts of the folders the root held (not those inside a nested root
  below) and emits `resultCountsChanged`. The "held by this root" test is now one method,
  `_root_holds`, shared by both. Small change, one file; the Cache Only floor touches
  `folder_cache.py` too (four small hunks: two call sites in `_root_seen`/`_root_gone`, one in
  the `root_changed` branch, the methods after `_root_constants_gone`).
- **Not changed:** a measurement already in flight from before the root went is still taken
  when it arrives. For a forgotten root it is still true (results stay under the UUID, and the
  marker is found again by the next listing); for a replaced root the listing that reports
  `root_changed` sends the new store's counts after it.
- **Test:** `tests/test_result_cache_badge.py::test_a_root_that_goes_drops_the_counts_of_the_folders_it_held`
  (forgotten, replaced, unseen; a nested root's counts kept; the next measurement taken): fails
  without the change.
- **Commit:** `28fbc18`.
- **Proposed known-issues line** (move to fixed): `- [x] A folder whose data root was forgotten
  or replaced while HeLab ran kept its saved-result count in RAM (28fbc18).`

Checks for jobs 2 and 3 (one run with both): full suite `-n 4 --reruns 5 --reruns-delay 1`:
4334 passed, 2 skipped, 2 xfailed, no RERUN; mypy --strict helab and tests, pyright: clean.

## Job 4: status-message audit, load labels for `merged` / `updated`

Audit only: no wording changed (Tony decides). Original findings:
[review](../2026-10-08-codex-status-message-review/review.md) item 4 and the activity-line table.
The phase labels it named ("Reading new TXY files into disk cache", "Reading new TXY files",
"Ready · Loaded from … + new TXY files" on the activity line) are gone: the tab line now says
Loading / Checking / Paused with the file and counts, whatever the source. What's left that
depends on the source is `LOAD_ORIGINS` (`helab/views/FolderExplorer.py:38`), shown as the cache
line's tooltip "Loaded from <origin>" (`_update_cache_summary`) and as Folder details'
**Source** row (`FolderDetailsPanel._data_rows`).

**What the helper does** (`helab/io_ops/loading.py`, `load`; source chosen at the
`load_source` event: `"updated" if in_memory else "disk" if cached else "merged" if reused else
"files"`), now pinned by `tests/test_load_sources.py`:

- `merged`: the cache's dataset is unpacked; shots whose TXY file is unchanged are reused from it,
  **new and modified** files are read. It can read **none**: Load as it is now after a shot went
  (`allow_missing`) gives `read` 0, `removed` 1.
- `updated`: some shots are held in the tab's RAM (`memory`); the others come from the disk cache
  when it holds them unchanged (`reused_disk`), and new and modified files are read. It can read
  **none**: a full listing check of data the tab holds with nothing changed (`cached` True,
  `read` 0). Live's checks also report `updated` (`io_ops/live.py`: new shots, and shots read
  again, `modified_loaded`).
- Both send `loaded` first, then (when the folder may be cached) write the disk cache:
  `cache_saved`, then `disk_cached`. An `updated` load whose memory shots the cache lacks reads
  those files again after `loaded`, for the save ("cache save: read").
- Both announce **every** file (`file_started` / `file_finished`), the reused ones too.

**Mismatches** (wording now → proposed; for Tony):

1. `merged` origin: "disk cache + new TXY files" (tooltip "Loaded from disk cache + new TXY
   files", Folder details Source). Omits modified files, and claims new files when none were
   read. Proposed, from `load_counts` (already sent): "disk cache + N TXY files read" (tooltip
   detail lists new / modified, as `load_count_details` already does); with `read` 0: "disk
   cache" (and "· N files removed" from the counts).
2. `updated` origin: "memory + new TXY files". Omits shots from the disk cache (`reused_disk`)
   and modified files, and claims new files when none were read. Proposed, from the counts:
   "memory" + " + disk cache" when `reused_disk` + " + N TXY files read" when `read`; with
   nothing read, "memory". The same text fits Live's results.
3. The file being read (Folder details State "Loading · <file>", the I/O tooltip's file via
   `FolderCache.load_note`) names reused files too, since the helper sends `file_started` for
   every file. In a large merged/updated load with few changes the names run through files that
   aren't read. Proposed (not wording; a helper change): send `file_started` only for files read,
   or keep it and show the name only for those (the shot events say which). Counts are fine:
   "N of M files checked · K loaded" counts reused shots as loaded, i.e. in the dataset, and
   Source's tooltip gives the breakdown.
4. Minor: the tooltip's `cache_reason` "Reused N shots from memory, M shots from disk cache; read
   K new or changed TXY files" counts K before reading: files then found still being written or
   unreadable are included, and K can be 0 ("read 0 new or changed TXY files"). Proposed: "K new
   or changed TXY files to read" (or drop the clause when 0).
5. Minor, maybe intended: the cache line says "Cached data found" rather than "loaded" for a
   merged or updated load that read anything, though most shots came from the cache
   (`reused` in `_update_cache_summary` is true only when nothing was read). Ask Tony
   whether "loaded" should mean "used at all".

**Matches** (no change): the disk cache writing after `loaded`: the cache line says "Updating
cache…" / "Creating cache…" while `disk_cache_saving`, the I/O tooltip labels the job "Save data
cache" (`IOService.label`, `finishing`) and names the files the save reads again, then "Cache
updated / created <age>"; the tab line drops the load at `loaded`. `disk` and `files` origins are
right.

- **Tests:** `tests/test_load_sources.py` (5): merged reads new + modified and saves after
  `loaded`; merged reading nothing; updated reusing memory and the cache; updated re-reading
  memory-only shots after `loaded` for the save; updated reading nothing. They pin behaviour,
  not wording. Commit: `8de9ea6`. Checks: full suite -n 4: 4339 passed, 2 skipped, 2 xfailed, no
  RERUN; mypy --strict helab and tests, pyright: clean.
- **Proposed `_readme.md` line:** keep the item open with "audit done: five label proposals
  for Tony (.ai/sessions/2026-10-26-claude-quick-fixes-2/notes.md#job-4)", or close it and add
  the proposals as one new item once Tony picks wording.

## Job 5: the remaining CI reruns

**Counts** (every CI CD run since 2026-10-23: `dev/v0.0.6`, `agent/windows-store-test`,
`agent/result-cache-r2`, `agent/quick-fixes`, the dependabot PR; 36 test jobs' logs read with
`gh api …/jobs/<id>/logs`):

- `test_live_plots.py::test_a_following_scatter_updates_its_page_in_place`: 2 reruns, both
  Ubuntu py3.13, both at teardown (PASSED, then RERUN 5 s later):
  - run 39880474971 (dev/v0.0.6, 2026-10-23), job 120176473708: "TEARDOWN ERROR: Exceptions
    caught in Qt event loop: TypeError: 'NoneType' object is not callable" (no traceback).
  - run 40265137480 (dev/v0.0.6, 2026-10-26, the latest), job 121385821413: "TEARDOWN ERROR:
    Exceptions caught in Qt event loop: … contextlib.py, line 162, in __exit__
    self.gen.throw(value) TypeError: exceptions must be classes or instances deriving from
    BaseException, not QMessageLogContext". (`where_qt_raised` added no note: this one has a
    traceback.)
- `test_plot_settings_panel.py::test_activation_sources`: no reruns.

**Cause.** The second reason gives it away: something called a context manager's `__exit__` with
`(QtMsgType, QMessageLogContext, str)`, the arguments of a Qt message handler. PyQt6 keeps one
Python handler in a static (`qtcore_PyMessageHandler`, `PyQt6/bindings/QtCore/qlogging.sip`);
Qt calls its C++ wrapper from whichever thread logs, which then takes the GIL and calls the
static. pytest-qt installs a fresh bound method (`_QtMessageCapture._handle_with_context`) at each
test's setup and, at the end of the call phase (`pytest_runtest_makereport`, `when == "call"`),
`_stop()` installs `None`, which frees that bound method (only PyQt held it). A thread that
entered Qt's handler just before the swap and waited for the GIL then calls `None` ("'NoneType'
object is not callable"), or, if it had already read the pointer, the freed bound method's
memory, which a new bound method (a `contextmanager`'s `__exit__`, made in teardown) had reused
("not QMessageLogContext"). Either way the error goes to `sys.excepthook` during teardown, where
pytest-qt reports it. On macOS every Qt message these tests log comes from the main thread
(`repro/qtmsgthreads.py`, a throwaway plugin: 207 messages, all MainThread); on Linux the
offscreen QtWebEngine evidently logs from another thread as the plot closes (not confirmed which
thread or message: Docker isn't running on this Mac, and starting it wasn't mine to do).

**Reproduced** (`repro/handler_race.py`: a Python thread logging through `QMessageLogger` while
the main thread swaps handlers as pytest-qt does, with Python work between the swaps):
"TypeError: 'NoneType' object is not callable", rarely (2 in 11.7k swaps; 1 per 30 s run in a
tighter loop, 4 runs). With every handler kept alive and a function installed instead of `None`
(`repro/handler_race_kept.py`): 0 in about 160k swaps.

**Fix** (CoCo chose option A of three, 2026-10-26): `pytest.ini` `addopts = --no-qt-log`, with
a comment giving the reason. pytest-qt then never installs a Python message handler, so no test
can hit the race. Nothing relies on its capture: no `qtlog` fixture, `qt_log_level_fail`,
`qt_log_ignore` or `no_qt_log` in `tests/`, `helab/`, CI or config, and nothing in `helab/`
installs a handler. Qt messages now go to Qt's default handler (stderr), which pytest captures:
a throwaway failing test that logs a Qt warning shows it under "Captured stderr call" (checked,
not committed). The other options: (B) mark only this test `no_qt_log` (another web-view test
could still race); (C) patch pytest-qt's capture in conftest to keep handlers alive.
`tests/conftest.py`'s `where_qt_raised` docstring cites this rerun as its example; it stays
useful for other Qt errors from C and is left alone.

- **Proposed AGENTS.md Testing line:** "pytest-qt's Qt log capture is off (`--no-qt-log`,
  `pytest.ini`): its per-test swap of Qt's message handler raced with QtWebEngine logging from
  another thread (Ubuntu teardown errors); Qt messages show in captured stderr."
- **Proposed known-issues line** (move to fixed): `- [x] test_live_plots.py's scatter test
  reran at teardown on Ubuntu ("'NoneType' object is not callable", then "… not
  QMessageLogContext"): pytest-qt's per-test message-handler swap raced with a Qt message from
  another thread; Qt log capture off (--no-qt-log) (cd2b0c3).` For `test_activation_sources`,
  append: "No rerun in the 36 test jobs since 2026-10-23 (Quick Fixes 2). Its macOS teardown
  failure (`f9faefd`) may have been the same message-handler race, which `--no-qt-log` removes
  (cd2b0c3)." Keep it open until it has gone a while longer.
- **Commit:** `cd2b0c3`.
- **Checks:** full suite `-n 4 --reruns 5 --reruns-delay 1`: 4339 passed, 2 skipped, 2 xfailed,
  no RERUN; `tests/test_live_plots.py` 10 times under `-n 4`: 131 passed each, no RERUN; mypy
  --strict helab and tests, pyright: clean.

## Job 6: load labels, proposals 1-4 of job 4 (Tony agreed, 2026-10-26)

- **Origin:** `load_origin(source, load_counts)` (`helab/views/FolderExplorer.py`) replaces the
  `merged` / `updated` entries of `LOAD_ORIGINS`, used by the cache line's tooltip and Folder
  details' Source row: merged "disk cache + N TXY files read" or "disk cache"; updated "memory"
  [+ " + disk cache"] [+ " + N TXY files read"]. N is `load_counts["read"]` (files the load set
  out to read, including any then found still being written or unreadable).
- **File being read:** `io_ops/loading.py` sends `file_started` / `file_finished` only for files it
  reads (not for shots in memory or reused from the cache); the save's re-reads and Live already
  did. What read those events: `IOService` (current file, per-file 15/20/30 s timeouts, and "while
  a file is read only file events count as progress"), `FolderCache` (`job.current_file` for the
  I/O tooltip, attempts), `FolderExplorer` and `explorer_live` (the file name). Progress counts,
  `LoadClock`'s estimate and rate come from `progress` events and are unchanged; reused shots
  are covered by the 60 s no-progress timeout through their progress and shot events.
- **Cache reason:** "Reused N shots from memory, M shots from disk cache; K new or changed TXY
  files to read" (singular "file" for 1), the clause dropped when K is 0.
- **Kept:** "Cached data found" (proposal 5).
- **Tests:** `test_load_sources.py` (origins and reasons per case, announced files),
  `test_gui_responsiveness.py::test_load_progress_counts_cached_files_and_reports_unreadable_files`
  (announced files per source: files 1, 2; disk none; memory 2), `test_folder_cache.py` (two
  reasons).
- **Commit:** `93fb3dd`.
- **Checks:** full suite `-n 4 --reruns 5 --reruns-delay 1`: 4339 passed, 2 skipped, 2 xfailed, no
  RERUN; mypy --strict helab and tests, pyright: clean.
- **Proposed `_readme.md` change:** close "Finish the status-message audit" (done: `8de9ea6`,
  `93fb3dd`).
