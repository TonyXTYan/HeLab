# Quick Fixes 4: notes (Mender, Opus 5.5, 2026-10-29)

Branch `agent/quick-fixes-4` from `b08627a`. Four CI-flaky tests from `roadmaps/known-issues.md`
(Tests and CI). No converter paths touched.

| Job | Test | Commit | Kind |
|---|---|---|---|
| 1 | `test_preset_folder_live.py::test_offline_a_folder_never_listed_is_named_as_such` | `beff3de` | app (small) + test |
| 2 | `test_folder_summary.py::test_scan_metadata_survives_restart_without_reading_txy_contents` | `291c83a` | test |
| 3 | `test_io_trace.py::test_tracing_changes_no_event_and_no_source_call` | `b295815` | test |
| 4 | `test_helabMainWindow.py::test_the_view_menu_has_no_thread_status_item_and_its_setting_is_retired` (caused by `test_window_icon_is_found_from_any_launch_folder`) | `0d10713` | test |

## Job 1: offline preset of a never-listed folder

**Cause.** The test passed only by timing. Offline, `ArrangementPresets.apply` opens the folder
(`FolderExplorer.open_to_path` sets `selected_path_globally` to it), and `PresetFolder.check` named
it (C-29) only in the `selected_path_globally != self.folder` branch. What moved the selection was the
tab's startup default-folder resolve: `FolderExplorer.__init__` submits it on a
`QTimer.singleShot(0)`; when that ran after the apply, it was submitted at the new generation and its
answer called `open_to_path(<default>)`. When the resolve had answered already (or was cancelled by
the apply's `setRootPath`), the selection stayed on the folder, its offline listing answered with
`offline_unlisted` and no report, and `check` went on waiting "until the tab's listing answers", which
had answered. No notice; the test's 30 s wait timed out. In the app (a settled tab) the C-29 notice
never showed. Codebase Review 2's C-29 premise ("`open_to_path` of a folder with no saved listing
leaves the selection on its parent") was the startup resolve; their C-30 note says as much.

**Evidence.** CI rerun reasons: `pytestqt.exceptions.TimeoutError: waitUntil timed out in 30000
milliseconds`, `tests/test_preset_folder_live.py:82` (runs 40713926667, 40722925594 jobs 122938617220
and 122938617543, 40740875291). Instrumenting `check` locally showed every passing run's notice came
from `_io_event` → `resolve` → `open_to_path`. Waiting for the tab to settle before the apply made it
fail every time (5 s timeout).

**Fix.** `helab/views/plots/presets.py`, `PresetFolder.check`: working offline, when the folder's node
has `offline_unlisted` and nothing cached or shown to load, it says the C-29 notice and finishes
(`_unlisted_offline`, also used by the old branch). The test is parametrized: `tab_settled` (waits for
the tab's startup work, as the online test does) and `at_once` (the old form; the resolve may move the
selection either side of the apply, the notice is the same).

**Checks.** The file: 3 passed. Six rounds of `test_preset_folder_live`, `test_offline_browsing`,
`test_live`, `test_presets_window` under `-n 8` (82 tests each): all passed. mypy `--strict` clean.

**Known-issues line:** remove (fixed, `beff3de`): "offline, `PresetFolder.check` waited for a listing
that had answered `offline_unlisted`; the test passed only when the tab's startup default-folder
resolve moved the selection after the apply."

**Follow-up A~1.** The startup resolve (`singleShot(0)` in `FolderExplorer.__init__`) can still run
after an early `open_to_path` (a preset applied, or a path typed, before the event loop turns) and move
the tab to the default folder. Online, a preset then says "Live not started: another folder was
selected". C-30's "treat the startup resolve as the tab settling" wasn't done. A small guard in
`_resolve_default` (skip it once the tab has navigated) would do; behaviour users see, so not done
here.

## Job 2: process-wide `os.scandir` patch

**Cause.** The test patches `os.scandir` process-wide to record the scan's listings and expects exactly
`[source]`. `IOService.release` removes a finished helper's output folder with `shutil.rmtree` on a
daemon thread (`HeLab-artifact-cleanup`), and `rmtree` lists by file descriptor (`os.scandir(<fd>)` on
macOS and Linux). A release from an earlier test on the same worker, running during the patch, added
the int.

**Evidence.** macOS CI run 40722845197, job 122938251377: `assert ['/private/va...0/source', 41] ==
['/private/va...s_re0/source']`, line 725. `shutil.rmtree` under a recording `os.scandir` records
`[3, 4, 5]`. With a plugin churning `rmtree` on another thread during the test, the old test fails
(`[15, 17, 18, 14, 16, 17, ...] == ['.../source']`), the new one passes.

**Fix.** Test only: both patches (the recorder and the later "Volume unavailable" failure) act only on
the test's own thread; other threads' calls go through. The scan runs on the calling thread (no pools
in `scanning`, `infra`, `stores`).

**Checks.** 40 runs under the `rmtree` churn and 3 runs of the file under `-n 8`: all passed. mypy
`--strict` clean.

**Known-issues line:** remove (fixed, `291c83a`): "another thread's `shutil.rmtree` (from
`IOService.release`) inside the test's process-wide `os.scandir` patch; the patch now records only the
test's thread."

## Job 3: traced and untraced events differ

**Cause.** Not tracing. A load (`io_ops/loading.py`, the per-file loop) and a Live check
(`io_ops/live.py`) send a file's progress event only 0.1 s after the last one (`time.monotonic()`;
the last file's always). On a slow runner the traced load took over 0.1 s between two files and sent
one more progress event. The event list depended on wall-clock time.

**Evidence.** Windows CI run 40725480099, job 122947593152: "At index 2 diff" (index 2 is the load;
its first item, the `scan_summary` event, is what the truncated summary showed). Splitting the two
lists from the log: the traced list has an extra `{'kind': 'progress', 'progress': 0.666…,
'checked_files': 2, …}`. Locally, giving only the traced run a clock in 0.11 s steps reproduced it.

**Fix.** Test only: `loading` and `live` read a clock that moves 1 s per reading (from 1000, above the
throttle's initial `last_progress = 0.0`, as a real clock is), so both runs send every progress event
and are compared whole.

**Checks.** The file: 29 passed. 20 runs alone, and 3 runs with `test_folder_summary` and `test_live`
under `-n 8` (121 tests): all passed. mypy `--strict` clean.

**Known-issues line:** remove (fixed, `b295815`): "load and Live progress events are sent at most every
0.1 s; a slow traced run sent one more. The test gives both runs a stepped clock."

## Job 4: the window-icon test's working folder reaches the next test

**Cause.** `test_window_icon_is_found_from_any_launch_folder` `chdir`'d to `tmp_path` for the whole
test. The window checks the store's data roots (`roots_verify`, `FolderCache._verify_markers`) in a
helper; helpers are started without a `cwd`, so they inherit the test's. The helper's
`helab.utils.constants` puts its working folder (`OS_WORKING_DIRECTORY`, `QDir_WORKING_DIRECTORY`) in
`DEV_POTENTIAL_DATA_PATHS`, so under the source guard `tmp_path` became a developer's data folder
unless it is in the system temp or the checkout (`infra._guard_rules`). Each test's store has
`tmp_path` as a data root (`temporary_data_root`), so `roots_verify` visits it, is refused, and notes
it; the helper started during the test's teardown, so the note failed the next test on the worker.

**Evidence.** Rerun reason on the numba floor: "Tests never touch real data, but this test's I/O asked
for: [.../popen-gw2/test_window_icon_is_found_from0]"; Codebase Review 2's notes saw the same with a
basetemp outside the checkout. Locally with `--basetemp` under `$HELAB_DIR_TEMPS_OVERRIDE`: a window
built in `tmp_path` and left 3 s logs "Verify data roots failed: … [Errno 13] Tests never touch real
data: '…/test_a0'"; the old test followed by a test that runs the event loop for 7 s fails that test
3/3.

**Fix.** Test only: the test is in `tmp_path` only while `HelabMainWindow()` is built (where it looks
for its icon) and goes back at once; helpers start from the launch folder.

**Checks.** The same pair with the new test passes 3/3; `test_helabMainWindow.py` under `-n 4` with
the outside basetemp passed 10/10. mypy `--strict` clean.

**Known-issues line:** remove (fixed, `0d10713`): "a helper inherits the test's working folder, which
its constants list as a developer's data folder; the window-icon test now leaves `tmp_path` right after
building the window."

**Follow-up A~2.** Any test that `chdir`s while helpers can start has the same trap with an outside
basetemp. Options: start helpers with an explicit `cwd`, or leave `OS_WORKING_DIRECTORY` /
`QDir_WORKING_DIRECTORY` out of the guard's denied list when `SOURCE_GUARD` is set. A grep found no
other test that `chdir`s with a window open; not changed here.

## Extra: the trace seam test and a path with spaces (`c81fe6f`)

Found by the outside-basetemp full run, not in the brief.
`test_io_trace.py::test_off_unless_the_test_seam_names_a_folder` split the helper's
`"<trace file> <pid>"` line on whitespace and failed "too many values to unpack (expected 2)" (line
111, 5 reruns then failed) because this floor's temps folder is `…/floors/Quick Fixes 4/temps`. CI's
temp paths have no spaces, so CI never saw it. Fix: `rsplit(maxsplit=1)`. The file passes with both
basetemps (29 each).

**Known-issues line:** none needed (found and fixed here); or, for the record: "a test split a path
on whitespace; floors' temp folders hold spaces."

## Checks before the report

At `0d10713` (jobs 1–4), on this Mac (16 cores), `-n 4 --reruns 5 --reruns-delay 1`:

- `--basetemp=.ai/temp/pytest` (inside the checkout): **7986 passed, 669 skipped, no RERUN**.
- `--basetemp` under `$HELAB_DIR_TEMPS_OVERRIDE` (outside): 1 failed (the extra above), 7985 passed,
  669 skipped, 5 reruns, all of that one test: "ValueError: too many values to unpack (expected 2)",
  `tests/test_io_trace.py:111`.

At `c81fe6f` (with the extra): the outside run **7986 passed, 669 skipped, no RERUN**.

`mypy helab/ --strict` (182 files), `mypy tests --strict` (151 files), `pyright helab tests`
(0 errors): clean.

Stress loops per job are in each job's Checks above.
