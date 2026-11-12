# Known issues

Bugs, gaps and flaky tests, open and recently fixed. Moved here from the
[roadmap overview](_readme.md) on 2026-10-21 (Tony). Features and their priorities stay in
the overview; manual checks stay in [.ai/MANUAL_TODO.md](../.ai/MANUAL_TODO.md).

How to use it:

- Add an item with the date found (YYYY-MM-DD), where it shows (OS, CI or a lab PC) and
  what is known of its cause. Link evidence in `.ai/sessions/`.
- A test that needed a `RERUN` is an item until its cause is found. "Flaky" is not a cause.
- When an item is fixed, tick it, add the commit and move it to **Fixed**. Drop fixed
  items at the next release's tidy-up.

## App

- [ ] **HeLab froze overnight on the TDC PC (2026-11-09, 00:47, Live idle, the PC unattended) until force
  quit**: `GUI stalled for 5.68s` was the log's last line, with no repeat 30 s later and no stacks in
  `console-19092.txt` (last written 2026-11-06). Most likely (inferred, not reproduced) the watchdog's
  `faulthandler` dump went into the console tee's pipe while its pump was stuck writing to the PowerShell
  console (why, with nobody at the PC, is unknown); the pipe full, the dump waited holding the GIL and every
  thread stopped. Fixed so it can't recur (stacks to the log through a regular file; the tee never waits
  on its terminal), but **the first 5.68 s's cause is unknown**: the next stall's stacks will be in the log.
  The GUI threads audit (block 73, merged `0930096`; GT-23) lists candidates: the mount table read every 10 s while a
  raw-only share folder is shown (GT-7 (b), A73.2); a held console-file write (GT-3, fixed: the tee writes its
  file from a thread, and the watchdog's lines reach the log within 1 s); `low_hits_threshold` (A73.4); a display
  or monitor power change re-laying-out every window (speculative). M73.3 checks the next one.
  The same logs showed Python's own console output (the log at DEBUG) lost on a Windows console once the tee
  started (fixed with it), and a false stall dump at every start (the watchdog armed before the event loop ran;
  fixed: 60 s before its first beat). Earlier stalls there (2026-11-06, 2.6 s and 3.5 s) came as Live loaded a
  new shot, the GUI thread in `explorer_live.low_hits_threshold` (a settings read every 80 ms animation tick).

- [ ] **The RAM budget box clips its text** (Settings → Cache): Qt's `QAbstractSpinBox.sizeHint`
  measures at most 18 characters, and "16.0 GiB (1/8 of 128 GiB)" is 25 (it was 23 as "17.2 GB (1/8
  of 137 GB)", clipped too; widths 131 and 135 px offscreen). A `sizeHint` override on
  `RamBudgetSpinBox` measuring the longest of its texts would fix it (byte units floor, block 32).

- [ ] **Lab data: a corrupted MATLAB TXY** in
  `dld_output_cheerypicked/20260722-tight-trap-1000Hzsampling/d_txy_forc183.txt` (two programs
  wrote it at once), and July 2026 TXY from the 2023 lab edit beside AutoConvert's (Q25.3). HeLab's
  own conversion is unaffected; reconvert those shots from raw. The test data's copy (nested
  `20260722-tight-trap-1000Hzsampling`, shot 183) lost bytes too (line 465 holds 4 values; 7 hits are
  missing): `tests/test_convert_testdata.py` lists it in `FAULTS` as an archive fault, which must still
  differ (Side's `ffe346c`). A fault in MATLAB's archive, not HeLab.
- [ ] **A user script that blocks only in HeLab's own process can still freeze HeLab once**: one that acts on
  the GUI's `QApplication` or widgets, deadlocks against the GUI thread's import lock, or changed between its test
  import and the import. Script folders import on the GUI thread, and the remembered folders load at every start.
  Since Q49.3 (b) (`fdd895c`, Follow-ups, landed `72ab47a`), each folder is first test-imported in a separate
  process, which skips a folder that hangs (`input()`, a network call, a long loop at module level) or crashes at
  import. A share is never loaded at start, and the loading marker (`<app folder>/scripts-loading.json`) makes
  the next start skip the folders with an amber line and Reload, so a start that works always follows. A slow
  cloud folder the mount table calls local (iCloud, Dropbox or OneDrive placeholders) is still loaded, now with
  the test import first, so a placeholder that stalls the import meets its 10 s limit (Prismo's M3, Live
  Scripts, 2026-11-03).

- [ ] **A cached dataset over ~2.1 GB can't be saved.** `pack_dataset` (`helab/utils/cache_store.py:459`)
  compresses a whole folder in one Blosc call, and python-blosc 1.11.4 caps a call at 2,147,483,631
  bytes (store-v4 design note, 2026-10-29). Store-v4's chunked `.hlb` files fix it in caching v2's stage
  2; store-v4's `datasets` keep the limit through stage 1 (Q42.3; Caching v2's A~2). Until then a folder
  that large stays RAM only (check what the save reports). Stage 2 (landed `1cd586c`) ends it in store-v4:
  loads and Live save append-only TXY segments, never a dataset; store-v3, the default while the switch is
  off (Q45.11), keeps the limit.
- [ ] **Dataset files are pickles** (`DATASET_FORMAT = "blosc-pickle-1"`, `pickle.loads` in
  `unpack_dataset`, `cache_store.py:466-473`), unlike saved results (NumPy + JSON). A cache folder
  someone else can write to could run code in HeLab's helpers. Store-v4's pickle-free `.hlb`
  containers fix it (design note, 2026-10-29): since stage 2 (`1cd586c`) store-v4 writes no dataset, though
  it still reads stage 1's `datasets` rows and store-v3's under Keep to seed layers (Q45.4, Q45.5).

- [ ] The tab's startup default-folder resolve (`QTimer.singleShot(0)` in `FolderExplorer.__init__`)
  can run after an early `open_to_path` (a preset applied, or a path typed, before the event loop
  turns) and move the tab to the default folder; online, a preset then says "Live not started: another
  folder was selected". C-30's "treat the startup resolve as the tab settling" wasn't done. A small
  guard in `_resolve_default` (skip it once the tab has navigated) would do (Quick Fixes 4, A~1;
  behaviour users see, so not changed there).
- [ ] Folders with over 100,000 entries record a scan failure.
- [ ] Helpers' private folders go to the system temp folder (`tempfile.mkdtemp` in `IOService`),
  not HeLab's temp folder (`DIR_TEMPS`, Settings → General). Since converter stage 4 the temp
  folder is used: HeLab's converted TXY when the output is `temp` or the folder has no data root
  (`folder_cache.py`, `convert_cli.py`), and numba's cache (Q18.1), so the setting stays; moving
  helper folders into it is what's left (2026-10-15; updated 2026-10-29).
- [ ] SMB audit leftovers (2026-10-20): a Windows-suited "seen twice" interval
  (Windows caches attributes 10 s); details scans for visible rows only; icons kept
  across Refresh; the startup "database is locked" on a fresh store (also seen as a warning, "Clean up
  disk cache failed … database is locked", in the full suite's output: a test's private store-v3, Caching
  v2 checkpoint 3; not a failure or a RERUN); refuse a
  network or synced temp folder at startup, as the cache folder is.
- [ ] With the default of one background lane, folder details and status checks
  (including manual ones) wait for the selected load. As planned; revisit if
  it feels slow.
- [ ] When a tab's shown data is dropped while it is shown (a folder status check finds
  the folder mismatched, or its cache is cleared), the tab keeps its arrays and later
  plots on screen; a load finding missing shots clears them (Tony, 2026-10-14). Since
  plotting, a plot whose data differs from the tab's (its shots, their files and origins:
  `DatasetView.held` / `held_of`, plots-1; by shot numbers for a plot with its own TXY choice) says
  "Showing previously loaded data" (`_update_plot_source_label`); not checked: a cache clear (which
  keeps the tab's dataset, so the label stays) and the tab's own arrays (2026-10-28).
- [ ] Live's line counts shots waiting with reason `cleared` (A19.2: Clear converted TXY ran during that
  conversion) as stuck until the next check, and their tooltip ends "A waiting file is checked again only
  when it changes", which is wrong for `cleared`: the next check converts them. Transient (one check
  interval). Fix: leave `cleared` out of `stuck()` in `explorer_live.py`, with its own line or none; not
  adding it to `CONVERT_SETTLING`, which would list them as being written (Caching v2 stage 0, Assay's
  S0-2, 2026-10-31).
- [ ] On Windows the Dash server can bind 127.0.0.1:8050 beside a dual-stack `[::]:8050` listener (an IPv4
  wildcard probe and a `[::]` V6ONLY probe both bind); whether that program then loses its 127.0.0.1
  connections is unverified. `test_dash_server.py`'s ipv6 case is skipped on Windows (CI 41160242383,
  41161383176). IPv4 wildcard listeners are found on every OS (`DashServer._listened_on_all`, plots-4).
  Needs a Windows machine: try `SO_EXCLUSIVEADDRUSE` on HeLab's socket, checking it still gets its port
  back after a restart (TIME_WAIT) (Plot Identity, 2026-10-31).
- [ ] With a server clock more than 2 s off ours, a change in the same mtime step right after a
  listing (FAT and some shares keep 2 s) isn't seen by the quick check until the folder's next
  change (the next shot) or a Retry / Refresh (R-1's residual, agreed with the reviewer)
  (2026-10-22).
- [ ] An identity probe (`cache_admin identity`) waits its turn in the local lane (2 processes).
  Behind long local work it starts late, and only its no-progress timeout is capped, so quitting
  waits that long (Quit now skips it) (Result Cache R2, 2026-10-23).
- [ ] Mixed versions: an older HeLab's Clear all and root clear don't remove saved listings or
  bump `gen_listings`, and its re-key leaves them at the old key; the next listing re-saves them,
  so harmless (cache-only, 2026-10-26).
- [ ] Windows cache moves on a venv install (unsure, not seen): a venv's `python.exe` is a
  redirector that runs the real interpreter as a child; killing it (`_reap`) ends the child only
  through its job object, so the child may hold files a moment after `wait()` returns, and a move's
  rename could hit WinError 32 now and then (lab PCs, CI). The move's verify and recovery catch it,
  but the user sees a failed move. Frozen builds don't have this (Codebase Review 2, 2026-10-26).

- [ ] From the computer-use smoke pass on Tony's Mac (built app at `41a6a7d`, 2026-10-28;
  [results](../.ai/sessions/2026-10-28-claude-smoke-mac/results.md)):
  - HeLab exited without a crash report while loading 20260727-RingBEC (1,007 TXY, 22.5 M
    rows) from the share, at about 14:04–14:06 (pid 79750). Its log is on that Mac,
    `~/Library/Caches/HeLab/logs/helab-79750.log` (last line "Disk cache cleanup" at 14:04:22);
    the retry loaded fine. Cause unknown.
  - Release time took 932.8 s on that folder (35 s on a 519-shot folder), and the process
    reached ~7.3 GB RSS with Velocity distributions running beside it. It needs progress or an
    ETA, or a cap on the bootstrap for big folders.
  - File › Quit sometimes left the process running, so two instances ran at once. It was seen
    when the click landed before the menu opened; cause still unknown (perhaps a click that quit
    nothing, after which the runner started a second HeLab). Since Smoke ready (`4ad8ac5`) a HeLab
    whose windows have closed ends within 1 s (`quit_watch`), and the quit window shows what quitting
    waits for; a click that quits nothing isn't covered. The quit watch could itself wait on logging's lock
    before its exit: fixed in `531d35e` (GT-2, merged `0930096`: it logs from a thread, at most 1 s, and
    `crash_file.exit_after` ends a hung teardown).
  - Saving an arrangement preset kept plot 19's unsaved Log Y. Possibly intended; Tony to judge.

## Tests and CI

- [ ] **`test_crash_file.py::test_a_held_up_file_write_never_holds_a_log_line`** reran once (macOS CI
  43134544536, Tests (2/3), `agent/live-stall`; that branch doesn't touch the tee): `assert 1572 == 2000`
  lines in `console-held.txt` (line 392). The child waits for the tee's queue to empty, then 0.2 s, then
  `stop()`, which waits only 2 s for the file's writer: an empty queue doesn't mean the last chunks are written.
  Fix candidate: wait for the writer to finish (a flushed count or a join), not `qsize()`. Added by GT-3 (block 73).
- [ ] **`tests/test_basic_plots_v2_hist2d.py` prints "RuntimeError: wrapped C/C++ object of type FigureCanvasQTAgg
  has been deleted"** (2026-11-09, macOS, local; the tests pass, no RERUN). Matplotlib's queued `_draw_idle`
  fires after qtbot deleted a `MatplotlibPane` that `update` had just redrawn
  (`test_every_library_draws_and_updates_in_place`'s Matplotlib cases). It predates the XY, XT, YT merge (the
  three-plot version prints it too). Likely fix: cancel the canvas's pending idle draw when the pane closes, or
  process events before the test ends.

- [ ] **The PR-only compatibility jobs (Python 3.11, 3.12, 3.14) fail** (soft; HeLab requires 3.13). PR #11's CI
  41648018025 (`f0bb9f9`), as on v0.0.7's PR (41104589243): 3.14's every job fails installing pygame (no 3.14
  wheel: "SDL.h file not found"); 3.11 and 3.12 Tests fail widely, mostly `test_cache_move` (116), `test_store_v4`
  (77), `test_typing` (33), `test_store_v3_question` (15). New since v0.0.7: 3.11's Converter backends fail 3
  (`test_convert_helab`'s cache-move and WAL tests). Not looked into; the required 3.13 jobs were green with no
  RERUN.
- [ ] `test_quit_confirms.py::test_quitting_with_nothing_to_save_closes_within_a_second` reran once on Windows,
  Ground CI 41578243240 (Tests 2/3, job 125726739543, `dcc02d8`, 2026-11-03): `assert (673.46 - 672.26) < 1.0`,
  quitting took 1.2 s; passed on rerun. The first Ground run with store-v4 on by default (the switch-on landed
  `92f9d1a`); "Disk cache inventory: Cancelled" was logged just after. Unchecked whether store-v4's quit path
  (the inventory, `raw_fill`) adds the time or the runner was busy. Again on Windows, Ground CI 41597667363
  (Tests 2/3, job 125788785096, `413b2a0`, 2026-11-03): reran twice, `assert (674.56 - 671.49) < 1.0`, quitting
  took 3.07 s; passed on the second rerun. Again on Windows, Ground CI 41750756742 (Tests 2/3, job 126315040588,
  `25f3ae6`, dev/v0.0.9's first run, 2026-11-04): `assert (911.83 - 910.77) < 1.0`, quitting took 1.06 s;
  passed on rerun. Again on Windows, `agent/quick-fixes-10` CI 41762330085 (Tests 2/3, job 126352703916, `feb9985`,
  2026-11-04): `assert (692.18 - 691.02) < 1.0`, quitting took 1.15 s; passed on rerun. All four on Windows Tests
  2/3 since store-v4 went on.
  Again on Windows: Ground CI 42031225750 (Tests 2/3, job 127257995304, `90d8d9b`, 2026-11-06), passed on rerun.
- [ ] `test_quit_confirms.py::test_the_watch_ends_a_process_left_running_with_its_exit_code` reran once on Windows,
  Ground CI 42621021439 (Tests 2/3, job 129172975176, `0de469b`, 2026-11-09): `assert [] == [3]` at line 37, the
  quit watch (`quit_watch.exit_soon`, grace 0.05 s) hadn't called its exit within the test's 5 s `join`; passed on
  rerun. First sighting. The bug review of `f844c0f..0de469b` (RV-7) found it slow, not blocked: the worker's
  own thread dump shows the watch inside `still_running()`'s `traceback.format_stack` (its "still running"
  warning came 8 s after the test started), and no console-tee thread alive; conftest turns the tee off in test
  processes, and the tests that start one do it in child processes. Fixed in `bfe4009` (`join(30)`; merged
  `fc58b51`): close once a few Windows CI runs pass without it.
- [ ] `test_updates_updater.py::test_a_moved_tag_is_refused` passed the 100 s `faulthandler_timeout` in a local full
  run on Ground (`fc58b51`, `-n 12`, 2026-11-10): "Timeout (0:01:40)!" with the test in `subprocess`'s
  `_execute_child`, starting `git` (`_git`, line 79, from `detach_at_tag`); it then passed, no RERUN. A `git` start
  that took over 100 s under load; first sighting, cause unchecked.
- [ ] `test_updates_launch.py::test_a_helab_the_updater_started_shows_that_updates_outcome_on_this_start` reran once
  on Windows, `review/v0.0.9-0de469b` CI 42757504516 (Tests 3/3, job 129635247309, `58abfdb`, 2026-11-10):
  `waitUntil timed out in 15000 milliseconds` at line 234 (the "updated to …" notice); passed on rerun. First
  sighting; that branch doesn't touch App updates. Cause unchecked.
- [ ] `test_presets_window.py::test_a_live_off_preset_turns_live_off_in_a_real_tab` reran once on Ubuntu, Ground
  CI 41597667363 (Tests 3/3, job 125788785411, `413b2a0`, 2026-11-03): `waitUntil timed out in 30000 milliseconds`;
  passed on rerun. That job ran runner image ubuntu-26.04 20261021.618. Cause unchecked.
- [ ] `test_txy_sources.py::test_a_load_whose_last_used_mark_times_out_still_returns_its_shots` reran once on
  Windows CI 41561765280 (Tests 3/3, job 125673863803, `agent/v4-switch-on` `23134c0`, 2026-11-03):
  `assert took < 5.0` failed at 5.52 s (the load with the converted-TXY index held by another writer, which must
  not wait out the index's 10 s busy timeout); passed on rerun. **Not timing slack:** dev/v0.0.8's own CI at
  `9f92daf` (run 41490153371, job 125430855984, switch off) reran it at 10.408 s, the index's 10 s busy timeout
  rather than the 200 ms wait the test pins (found by Vault, 2026-11-03; that run's RERUN wasn't recorded at the
  time). So on Windows some open of the converted-TXY index during a load isn't bounded by the 200 ms wait, and a
  load can stall ~10 s while a conversion holds the index: `helab_txy`/`provenance`, not caching v2's code.
- [ ] `test_convert_helab.py::test_watch_converts_new_shots_and_stops_on_ctrl_c` reran once on macOS CI
  41561765280 (Converter backends, job 125673863875, `23134c0`): `helab convert --watch` ended with -2 (killed
  by the SIGINT) instead of 0 ("Stopped"); passed on rerun. The SIGINT reached the process when Python's default
  handler wasn't the converter's (before it was set, or after it was reset); unchecked. Vault: the loop catches
  `KeyboardInterrupt` around `convert_folder` and the sleep, nothing in helab resets SIGINT, 15/15 local passes,
  none in dev's last 8 runs; the watcher's cache options carry `store_v4`, so the switch-on can reach it. Again
  on Ubuntu CI 41622979011 (Converter backends, `agent/followups` `fdd895c`, "rerun reasons": `AssertionError:
  assert -2 == 0` from `wait(20)`), passed on rerun; that branch changed only `--output`'s parsing. Next
  step: put the watcher's stderr in the assertion message.
  Again on Ubuntu CI, `agent/folder-info` 41998150471 (Tests 3/3, job 127146449450, `4dd31db`, 2026-11-05), passed on
  rerun.
  Again on Ubuntu: Ground CI 42031225750 (Tests 3/3, job 127257995388, `90d8d9b`).
  Again on macOS: Ground CI 42486811905 (Converter backends, job 128750416374, `61f5832`, 2026-11-08), `assert -2 ==
  0` from `wait(20)`; passed on rerun.
- [ ] `test_live_plots.py::test_each_plot_keeps_its_scripts_minimum_size[Scatter3D]` reran once on
  Windows CI (run 40808815122, `agent/txy-followups` `ec1338a`, group 1/2), no reason in the log (a
  worker crash?); passed on retry. Also a macOS local worker crash (gw2, `agent/txy-index` `0f69731`,
  2026-10-30). Likely the QtWebEngine crash below. Again: gw2 on `agent/plot-library-crash` CI 41483861898
  (`34e6452`, Windows Tests 1/2, job 125409160738; no faulthandler output, a native crash), passed on retry.
  Possibly the empty-argument `QApplication` of the Plotly deaths (Fixed below, `b0eb914`; its 3D scatter is a
  Plotly web view); unchecked: if it recurs on a branch with `b0eb914`, it isn't, and its worker's file order
  is the next thing to read (Quick Fixes 9).
- [ ] **QtWebEngine crashes xdist workers** (the Plotly and Scatter3D entries here):
  `test_accessible_names.py::test_every_script_and_each_library` crashed its worker once in a local
  full run (2026-10-30, `agent/smoke-ready`), passed on rerun; macOS's crash report gives the
  mechanism the other entries lacked: **SIGTRAP (EXC_BREAKPOINT) on a QtWebEngineCore thread** (a
  Chromium check failing, frames all in QtWebEngineCore under an NSRunLoop source), not Python or
  HeLab's code. That test now closes each web-view plot once walked (at most one renderer open).
  A second mechanism, now fixed (below): a SIGSEGV on the main thread when a Plotly plot's dock was
  deleted; some of these worker crashes may have been it. A third, fixed too (below, `b0eb914`): a
  `QApplication` made with no program name, which made QtWebEngine end the process at the first web view.
  Watch whether they recur after `c104502`.
  They do: `test_accessible_names.py` crashed its worker on Ground CI 41100591971 (Windows Tests 1/2, job
  124217404251, gw0, `371751d`), PR CI 41095142656 attempt 1 (macOS Tests 1/2, `8ccc0be`) and PR CI
  41104589243 (macOS Tests 1/2, job 124231159424, `92c532b`); each passed on rerun (2026-10-31). Those
  `test_accessible_names` deaths are not the empty-argument cause: no such fixture ran on those workers before
  them (Quick Fixes 9), so the SIGTRAP stays open. (The `[values2-Plotly-TxyHistograms]` abort once listed here
  was that cause: Fixed below.)
- [ ] `test_raw_fill.py::test_files_not_settled_wait_and_a_fill_yields` reran once on Windows, Ground CI 42765698387
  (Tests 1/3, job 129661620867, `70df9e6`, 2026-11-10): `assert (4, 0) == (3, 1)` at line 118, the shot written
  with the current time saved instead of waiting; passed on rerun. First sighting. Likely the runner: the test
  writes `d4.txt` with `mtime=time.time()` and expects it unsettled under a 5 s settle time, so a fill that
  starts over 5 s later finds it settled. Unchecked; a fix would date it in the future or patch the clock.
- [ ] `test_gui_responsiveness.py::test_timeout_retry_releases_dead_helper_slot_while_artifact_reader_is_blocked[2]`:
  `waitUntil timed out in 3000 milliseconds` at line 292 (the `finally`'s wait for the killed fake
  helpers to exit after `service.shutdown()`), on Windows CI run 40803552596 (`agent/txy-ship`) and
  once locally on macOS; passed on retry. Again on Windows: Ground CI 40861772277 (`9f0b21f`) and
  `agent/txy-index` CI 40874212130; Ground CI 40988453930 (`c492242`, Windows Tests 1/2) and 41000437956 (`43cb202`);
  the `[1]` case on Windows, `agent/ui-polish` CI 41005221588 (same line); `[2]` on Ground CI 41164525298
  (`82c9db3`, Windows Tests 1/2, job 124429158185); `[1]` on Ground CI 41374704252 (`0406a1d`, Windows
  Tests 2/2, job 125052359778); `[1]` on `agent/caching-v2` CI 41375836115 (`84ccaeb`, Windows Tests 2/2,
  job 125055805809); `[1]` on Ground CI 41443833629 (`a0bc26d`, Windows Tests 2/2, job 125272121356);
  `[1]` on `agent/caching-v2` CI 41446828628 (`4c7199d`, Windows Tests 2/2, job 125282060253) and CI
  41459782803 (`fa7884f`, Windows Tests 1/2, job 125325725282). A candidate: 3 s under load. Quick Fixes 9's
  guess (not checked): an earlier test's helper start entering this test's process-wide `Popen` fake, which
  A46.1 (`6fa8cd9`, `this_tests`) would stop; all three sightings above ran without A46.1, so keep it open
  until CI runs with it say. None in Quick Fixes 9's Ground runs since A46.1 (CI 41455114540 to 41493818761, all
  job logs read).
- [ ] `test_plot_backends.py::test_2d_plots_draw_with_every_library[values1-Matplotlib-CountsPerShot]`: worker
  gw1 crashed on `agent/txy-index` CI 40883472651 (job 123480992297); passed on retry. Split from the Plotly
  cases' entry (Fixed below): no web view here, so not their cause. Cause not found.
- [ ] `test_root_discovery.py::test_volume_check_alone_refreshes_hints_without_visiting_markers`:
  xdist worker gw2 crashed on macOS CI 40866574094 attempt 1 (job 123422851726, `agent/txy-index`
  `9691873`; `INTERNALERROR> AssertionError: (…, <WorkerController gw2>)`, exit code 3, no RERUN);
  attempt 2 passed; it also reran on macOS in CI 40879735789 (job 123467827712). The test patches
  `os.lstat` for the whole process; an unraisable reached pytest's hook, whose `tracemalloc_message`
  ran coverage's `canonical_filename` → `os.path.realpath` → the patched `lstat` → `Failed` inside the
  hook. Fix: patch the name the code under test calls (`data_roots`' or `infra`'s), or `gc.collect()`
  before patching. The collected object may have been one of the tests' leaked connections (fixed,
  `46f481f`, below); the patch-the-name fix still stands.
  Again on macOS: `agent/app-updates` CI 42026547431 (Tests 1/3, job 127242189697, `235859d`, 2026-11-05), setup and
  teardown, "visited a source folder" from its process-wide `os.lstat` patch; passed on rerun.
- [ ] `test_folder_cache.py::test_scan_reports_cached_children_without_loading_or_probing_them`: reran
  once on Windows CI 40894080358 (job 123518429856, `agent/txy-index` `1b71c37`): `assert scanned ==
  [str(root)]` at line 1155, with a `helab_io_…` temp folder first. Its process-wide `os.scandir` patch
  caught `IOService.release`'s `shutil.rmtree` on the "HeLab-artifact-cleanup" daemon thread
  (`io_service.py:963`), the same trap as the fixed `test_folder_summary` entry below. Fix: record
  only the test thread's calls (`threading.get_ident()`) or paths under `tmp_path`.
- [ ] `test_folder_summary.py::test_cached_scan_age_and_failed_refresh_retain_counts` fails across
  midnight UTC: 3 RERUNs on Windows CI 40975825607 (job 123803535756, `agent/txy-index` `c6277f0`):
  `assert '2026-10-29' in 'Last successful status scan: 2026-10-30 00:00:19 …'` at line 286. It takes
  the expected date from a timestamp ~35 s before the scan the tooltip shows. Fix: the date of the time
  the tooltip shows, or a frozen clock.
- [ ] `test_folder_summary.py::test_visible_scans_follow_scrolling_without_prefetching_offscreen_folders`:
  `all(...)` False at line 868 over the pending scan requests, once in a local `-n 12` full run
  (2026-10-31, Ground `dev/v0.0.7` `01ce35f`, Quick Fixes 7 round 6); passed on rerun. Cause not found.
- [ ] `test_presets_window.py::test_applying_a_live_preset_in_a_real_tab_starts_live_once_listed`:
  `waitUntil timed out in 30000 milliseconds` at line 104, Windows Tests (1/2), PR CI 41087162687 (job
  124171347360, `b836b56`, 2026-10-31); passed on rerun. Cause not found.
- [ ] `test_root_gui.py::test_the_gui_never_writes_the_saved_file_itself`: xdist worker gw0 crashed
  once on macOS CI (run 40790093719, `agent/quick-fixes-5` `ed0635c`, job 123172940859, 2026-10-29);
  passed on its rerun. Again: gw2 on Ground CI 41161254527 (Windows Tests 2/2, job 124419124616,
  `f128623`; "node down: Not properly terminated", a stack at line 449), passed on gw4. Again: gw3 on
  `agent/caching-v2` CI 41386150963 (`df17761`, Ubuntu Tests 2/2, job 125087377900), passed on retry. Again on
  `agent/activity-window` CI 41810647028 (`de386d2`, macOS Tests 1/3, job 126508807739), passed on retry; its
  faulthandler stack shows a likely cause: `ManualMarkerDialog._result`'s modal `QMessageBox.warning`
  (`DataRootDialogs.py:235`), shown for the cancelled marker save during the test's `service.shutdown()`. Fix
  proposed by the Activity Window floor: close the dialog before the shutdown in the test, or show the warning
  without a modal loop (`open()`), as the converter's questions do.
- [ ] `test_test_isolation.py::test_pytest_imports_the_checkout_it_runs_in_before_any_other`: a
  collection error in pathlib `lstat` on Windows CI (run 40754482305, `agent/txy-packaging` `7d2bff9`),
  passed on retry. Again on Windows Tests (2/2): `agent/byte-units` CI 40989130996 (job
  123847075029) and `agent/smoke-ready` CI 40990082872 (job 123850152612), both passed on retry; Ground
  CI 41072414259 (job 124119750861, `2960680`); `agent/caching-v2` CI 41375836115 (`84ccaeb`, job
  125055805809) and CI 41379212072 (`6b0f998`, job 125066159186); `agent/v4-switch-on` CI 41490797588
  (`d3b4931`, 2026-11-03); `agent/txy-priority` CI 41587970080 (Windows Tests 1/3, job 125757887948,
  `bf3fb85`, 2026-11-03); Ground CI 41660788301 (Windows Tests 1/3, job 126003261482, `3ab75b2`,
  2026-11-03); Ground CI 41752079691 (Windows Tests 1/3, job 126319407975, `ec308ac`, 2026-11-04).
  Again: Ground CI 42581846388 (Windows Tests 1/3, job 129042255589, `5570c94`, 2026-11-09), the same collection
  error in pathlib `lstat`.
- [ ] `test_io_lanes.py::test_tab_switch_moves_work_to_background_and_requeued_load_reuses_ram_shots`:
  `KeyError: 'memory'` at line 262 (the requeued load's payload had no RAM shots), macOS Tests (3/3) on
  Ground CI 41660788301 (job 126003261256, `3ab75b2`, 2026-11-03); passed on rerun. Likely cause, not
  confirmed: the test puts three messages and calls `IOService._tick()` once, and a tick stops after
  8 ms, so on a slow runner the `shot` message can still be queued when the tab switches. Probable fix:
  tick until `service.messages` is empty.
- [ ] `test_gui_responsiveness.py::test_stalled_process_keeps_heartbeat_and_shutdown_responsive`:
  `assert 0.2199… < 0.2` (line 228) on macOS CI (run 40764414177), passed on retry.
- [ ] `test_gui_responsiveness.py::test_real_helper_loads_data_and_refresh_replaces_changed_data`: Windows CI
  41758844145 (`agent/quick-fixes-10` `be2f0e5`, Tests 3/3, job 126341477058, 2026-11-04), one RERUN, passed on
  rerun. The `waitUntil` (15 s) at line 788 timed out once, with real helper processes. That job took 12 min 43 s;
  the other Windows groups took about 7–10 min, so a slow runner is likely. The branch didn't touch the test's
  path. Cause not yet found.
- [ ] Tests that `chdir` while helpers can start: a helper inherits the working folder, which its
  `helab.utils.constants` lists as a developer's data folder (`DEV_POTENTIAL_DATA_PATHS`), so the source
  guard refuses it outside the temp folder and the checkout. `test_window_icon_is_found_from_any_launch_folder`
  now leaves `tmp_path` right after building the window (Quick Fixes 4), which narrows the window but
  doesn't close it. Fix: A13.1.
- [ ] A test that closes a real main window leaves the app-wide IOService closed in
  `io_service._service`, its retired requests never forgotten (timer stopped), until the next
  `get_io_service()` replaces it; and a live app-wide service (and its FolderCache) lasts the
  worker's run, so its timers and helpers can work against later tests' private stores. Tests
  should start each with a fresh or quiesced app-wide service, but a closed one must not simply be
  reset: wait for its old helpers' exits first (`cache_busy()`), or their store may still be open
  (found by `agent/quick-fixes-3`, Feeler's review, 2026-10-27).
- [ ] macOS CI on `dev/v0.0.7` (run 40679555921, job 122786573479, `7b82c9d`, 2026-10-28) was
  cancelled at ~20 min (earlier macOS jobs took 5–6 min):
  `test_correlations.py::test_fifty_shots_of_two_thousand_events_take_seconds` reran 5× then
  failed; `test_folder_summary.py::test_disk_cache_summary_tracks_shared_save_completion[cache_saved]`
  reran 3× (cause found and fixed by Quick Fixes 5, below in Fixed); `test_correlations_plot.py::test_back_to_back_pairs_peak_at_zero_with_the_trap_origin`
  and `test_analysis_gui.py::test_another_library_draws_the_plot_again_without_a_rerun` reran once
  each. Four "Timeout (0:01:40)!" dumps (one in `test_g2_zero_error_matches_its_scatter`) and
  crashed workers gw0 and gw1. The same tree (`e75a105`) passed every job in run 40679110506
  minutes earlier, so a slow runner with timing-sensitive, compute-heavy tests is likely; cause
  not found.
- [ ] **matplotlib's font cache build passes the 100 s `faulthandler_timeout`** on a fresh CI runner,
  killing the xdist worker ("node down: Not properly terminated", then "worker crashed"; it passes on
  rerun, the cache built). Windows: Ground CI 41031678338 (`da76ced`, Tests 1/2, job 123982721538, gw0),
  `test_accessible_names.py::test_every_script_and_each_library` at line 375 switching Counts per shot to
  Matplotlib: the main thread in `font_manager._load_fontmanager` → `addfont` (the first `matplotlib.figure`
  import, from `backends.mpl_figure`), GUI stalls logged at 24, 54 and 84 s. macOS: the `agent/txy-packaging`
  entry below (`_get_macos_fonts`). So that test's worker crashes are not all QtWebEngine's or the fixed
  Plotly SIGSEGV. Candidate fix: build the font cache before the tests (a CI step importing
  `matplotlib.font_manager`, or once in conftest at session start).
- [ ] macOS CI on `agent/txy-packaging` (run 40765484151, `e2f3e14`, 2026-10-28): the test job was
  cancelled at its 20-min limit on both attempts, so neither printed its summary or rerun reasons
  (job logs read 2026-10-29 with `gh api …/actions/jobs/<id>/logs`). Attempt 1 (job 123091397883):
  `test_analysis_gui.py::test_another_library_draws_the_plot_again_without_a_rerun` reran after
  its worker gw0 crashed ("node down: Not properly terminated"), following a 100 s faulthandler
  dump with the test at line 581 inside matplotlib's font cache build
  (`font_manager._get_macos_fonts`); `test_convert_helab.py::test_heartbeats_while_computing_stop_after_the_budget`
  reran once. Attempt 2 (job 123103873970): the same font-cache dump in the same test, which then
  passed; `test_convert_helab.py::test_a_hung_backend_stops_sending_heartbeats` reran twice;
  `test_correlations.py::test_g2_zero_error_matches_its_scatter` reran after worker gw3 crashed;
  `test_live_plots.py::test_a_following_correlations_plot_counts_only_new_shots_and_skips_its_bootstrap`
  reran 5× and then **failed** (reason lost). The two heartbeat tests' cause was found and fixed
  later (Quick Fixes 5, Fixed below); the packaging floor then moved the compiled backends to
  their own job, after which macOS tests took 4–11 min again. The other three: cause not found.
  For `test_another_library…`, also in the 2026-10-28 run below, a slow runner building
  matplotlib's font cache is likely.
- [ ] `test_live_testdata.py::test_convert_watch_converts_a_run_as_it_arrives`: the watcher stopped converting,
  pytest-timeout's "Timeout (0:01:40)" dump showing the test in `wait_for` (line 240) waiting for `helab convert
  --watch` to convert a shot, then the worker died ("node down: Not properly terminated"), on Windows CI
  41459782803 (`agent/caching-v2` `fa7884f`, Tests 1/2, job 125325725282); passed on retry. It takes 6–10 s in
  every other run read that night (15 runs on three OSes); caching v2's stage 3 can't reach it (the watcher runs
  `convert_cli` and `io_ops/convert.py` in store-v3, which import nothing stage 3 changed). Cause not found: the
  watcher's log isn't kept when the worker is killed. Next step: fail `wait_for` with the watcher's log before
  pytest-timeout (Vault's handoff, 2026-11-03).
- [ ] `test_left_widgets.py::test_a_teardown_that_raises_still_deletes_the_web_views`: line 80's `assert "3
  passed, 2 errors"` failed because the inner run printed `.E.E.E` (its third test, `test_after_it`, also errored
  at teardown), on Ubuntu CI 41459782803 (`agent/caching-v2` `fa7884f`, Tests 2/2, job 125325725389); passed on
  retry; the rerun reasons cut the rest of its output. The inner run is PyQt6 QtWebEngine views and the test
  conftest only, no HeLab I/O. Likely the QtWebEngine teardown flakiness of the "QtWebEngine crashes xdist
  workers" entry; not pinned (Vault's handoff, 2026-11-03).
- [ ] `test_dash_server.py::test_stop_frees_the_port`: `assert 56278 == 56276`, once in a local full run on the
  Live Scripts floor (2026-11-03, other floors' suites running on the same Mac); passed on rerun. `free_port()`
  picks a port and the server binds it later, so another process can take it in between and the server falls
  back to the next free port (earlier sessions saw it too: 2026-10-20, -21, -22). Fix: bind and hand the open
  socket over, or retry with a new port when `start()` returns another (Live Scripts' A~6).
- [ ] **Ubuntu CI 41468043383 attempt 1** (`agent/live-scripts` `74b79b3`, Tests 1/2, job 125354149828, cancelled at
  its 20-min limit, 2026-11-03): `test_cache_admin.py::test_failed_listing_history_write_keeps_the_listing_guard`
  failed 6 times on gw0 from 15:08:18 (about 5 s an attempt, 0.4 s normally), then gw1 from 15:08:52 failed every
  test left to it 6 times at about 35 s an attempt, each its `WAIT = 30_000` for a save that never completed
  (`test_result_cache_badge`'s save test; `test_result_cache_plots`' outdated `[script]`/`[data]`,
  `ends_unshown[cancelled]`, `live_reruns_are_never_saved`), until the cancel: 43 RERUN lines, no reason, no
  summary. Attempt 2 green; the guard test alone 15 of 15, and both workers' orders replayed in one process pass;
  no disk, memory or file-limit message. It looks like that runner's helper subprocesses getting nothing done
  from 15:08; not proven (Lumen's A~7, Quick Fixes 9's hunt). A run cut short now keeps its reasons: live
  `RERUN REASON` lines (`1ca5baa`), `--session-timeout` (`457debc`) and the junit.xml artifact (`5324a7f`).
- [ ] `test_cache_first.py::test_a_server_clock_ahead_of_ours_keeps_the_quick_check[cached]`: the test's in-process
  load sat in SQLite's `COMMIT` (`cache_store.transaction`, under `start_dataset_job`, `loading.py:289`) for over
  100 s, faulthandler's dump at 100 s, then the worker killed at `--timeout=120` (reported "(???)", a dead worker),
  on Ground CI 41476107464 (`f534ede`, Windows Tests 1/2, job 125382190106); passed on retry. The store is the
  test's own and SQLite's busy timeout is 30 s, so a file-system stall on the runner or a long wait behind another
  process is likely; not reproduced (Quick Fixes 9).
- [ ] `test_live_testdata.py::test_a_run_replayed_into_live_is_converted_once_per_shot_as_matlab_did`:
  pytest-timeout's "Timeout (0:01:40)", then "node down", on `agent/caching-v2` CI 41476804254 (`6b00cb0`, Windows
  Tests 2/2, job 125384496288); passed on retry. The dump: the test's own `run_convert` → `convert_folder` →
  `finish` → `write_atomic` → `pin` → `provenance.record` → `_write` → `_patient` → `_transaction`, waiting at
  `BEGIN IMMEDIATE` (`provenance.py:346`) on the converted-TXY index's lock. Each `_patient` waits at most
  `BUSY_SECONDS` (10 s), so another connection to that test's own index held it for most of 100 s. The switch was
  off and neither `provenance.py` nor `io_ops/convert.py` had changed on that branch; not pinned (Vault's handoff,
  2026-11-03).
- [ ] `test_live_io.py::test_a_live_check_pauses_background_work_only_while_it_reads`: `waitUntil` timed out
  (10 s) at line 136, once in a local full run under a load average of ~37 (Ground, Quick Fixes 9, 2026-11-02,
  before `e8a28a1`); passed on retry and 5 of 5 alone. Cause not looked into. Again on Windows CI, same line:
  `agent/docs-a54-1` 41587185042 (Tests 2/3, job 125755380835, `9631294`) and Ground 41595342227 (`dc86412`),
  both passed on rerun (2026-11-03).
  Again on Windows CI, `agent/folder-info` 42001112700 (Tests 2/3, job 127156351562, `9da2bee`, 2026-11-05),
  line 125.
- [ ] `test_live_convert.py::test_a_conversion_refused_offline_stops_auto_convert_and_says_so` (both cases): macOS CI
  on `agent/quick-fixes-10`, 41758844145 (`be2f0e5`, Tests 1/3, job 126341476955, `[as it comes]`) and 41770471113 (`1ab4864`, Tests 2/3,
  job 126378820117, `[a Live check comes due while offline]`), one RERUN each, passed on rerun. The `waitUntil` (5 s)
  at line 626, for the conversion's "not while working offline" error after `_convert_tick` while offline, timed
  out. It predates the branch: it reproduced once on the base `bd349ec` under overload (1 of 15 passes, `-n 4`
  against 32 CPU burners on 16 cores, `--reruns 0`), and the code path (`_convert_tick` → `FolderCache.convert` →
  `submit` → IOService's offline refusal → `_convert_event`) is unchanged by the branch; none of 147 macOS Tests
  jobs in 43 other recent runs (2026-11-03 to 04) reran it. In the base failure's teardown a pending "Volume
  verification" job and a "Disk cache convert_prefs" read were cancelled: check whether the conversion waits
  behind them while offline instead of being refused at once (Rivet's hypothesis, unconfirmed). Cause not yet
  found (Quick Fixes 10's handoff).
  Again on `agent/activity-window` CI 41818074716 (`a2f040f`, macOS Tests 2/3, job 126533965855, `[a Live check comes due
  while offline]`), passed on rerun. The branch's AW-5 change (`384f93f`) to `_convert_event`'s offline branch sets
  `convert.error`, which line 626 waits for, before `_convert_stopped`, and the offline answer still comes from
  `FolderCache.submit`'s single-shot path; the Reviewer ran it 12 times under 16 CPU burners with `--reruns 0`,
  all passing.
  Again on macOS: Ground CI 42031225750 (Tests 1/3, job 127257995260, `90d8d9b`, the `[as it comes]` case).
- [ ] `test_load_queue.py::test_an_automatic_load_waits_for_the_selection_to_settle_only_while_loads_are_busy`:
  one RERUN on `agent/activity-window` CI 41794579242 (`a141e60`, Ubuntu Tests 1/3, job 126455595537):
  `assert explorer.settling` at line 674, right after a third folder is selected while the second's load is busy;
  passed on rerun. The test drives `FolderExplorer` only, with real settle timers (`SETTLE_MAX` 1.0), so the wait
  probably ended before the assertion on a slow runner. Cause not confirmed.
- [ ] `test_gui_responsiveness.py::test_rendering_never_reads_filesystem_or_disk_cache`: two RERUNs in one local
  run on `agent/activity-window` (`d4593c8`, teardown and then its rerun's setup): `AssertionError: GUI rendering
  performed I/O` raised in a thread (pytest-qt's "Failed to process unraisable/thread exception"); not reproduced
  in 3 more runs. Probably a thread another test left behind (a helper's artifact cleanup, `shutil.rmtree`),
  started during the test and counted by `this_tests` as its own. Fix proposed: count only threads the test's
  own service starts.
- [ ] `test_result_lifecycle.py::test_save_x_eviction_of_the_same_key_before_its_transaction_saves_the_newer_copy`:
  `waitUntil` timed out (30 s) at line 71, in the same local run as the entry above (load ~37); passed on
  retry and 5 of 5 alone. Cause not looked into.
  The sibling `test_lookup_x_eviction_of_another_result_shows_it_from_disk` timed out the same way (30 s at line 71, the
  `saved_plot` helper) in Tally's review run on `agent/folder-info` (`f57629c`, 2026-11-05, a slow run: 4m13s against
  2m38s), and passed on rerun.
- [ ] `test_live_plots.py::test_a_floating_plot_runs_and_follows_with_its_settings_in_its_window`
  reran once on macOS CI (run 40260284152): `'completed' == 'cancelled'`. Cause unknown
  ([audit](../.ai/sessions/2026-10-28-claude-v0.0.6-checks/audit.md) #23, 2026-10-28). Again in a local full
  run on Ground (Quick Fixes 8, 2026-11-01, Rivet's handoff). Again on Ubuntu: Ground CI 41567847672 (Tests 1/3,
  job 125693660872, `5878bd2`, 2026-11-03), the same `'completed' == 'cancelled'`, passed on rerun. Again on macOS:
  `review/v0.0.9-0de469b` CI 42757504516 (Tests 1/3, job 129635247356, `58abfdb`, 2026-11-10), passed on rerun (that
  branch made `AnalysisInstance.job_id` a property whose setter only enables the memory row's Cancel).
- [ ] `test_analysis_gui.py::test_scatter_from_the_panel` (a Dash/web-view plot) reran in local
  full runs on 2026-10-20 (`dld-d7` and `refactor-prep` handoffs); it passed on retry and alone.
  Cause unknown (audit #16, 2026-10-28).
- [ ] `test_plot_settings_panel.py::test_activation_sources` reran once on macOS CI; it didn't
  fail in 60 local runs under load (2026-10-21). The Windows rerun was the web-view crash
  (fixed); the macOS rerun (`f9faefd`) was a teardown failure, cause unknown, and 160 local
  runs passed. CI now prints rerun reasons: read them at its next rerun (2026-10-22). No rerun
  in the 23 CI runs to 2026-10-23; a frameless Qt exception there now names where the event
  loop ran (`e326fdf`).
  No rerun in the 36 test jobs since 2026-10-23 (Quick Fixes 2). Its macOS teardown failure
  (`f9faefd`) may have been the same message-handler race as the scatter test's, which
  `--no-qt-log` removes (`cd2b0c3`); keep it open a while longer.
- [ ] **`test_share_detection` patches `os.path.realpath` process-wide**: a leftover `IOService` request then fails
  `Path.resolve()` in the helper launch ("Clean up disk cache failed … share_of stat'ed a source path"), a warning
  only, seen in Mendy's local runs for LR-15 (2026-11-05). Not a RERUN yet; the patch should be scoped to the call it
  tests.
- [ ] **`test_convert_helab.py::test_a_killed_helpers_workers_exit`** (`AssertionError: the pool started`): under `-n 8`
  the converting helper's pool workers weren't yet visible to `psutil` when its first `shot_converted` arrived; 2 reruns
  in Ledger's local run on `agent/folder-info` (`4dd31db`, 2026-11-05), 1 in its final run, and 2 under load ~500 in
  Relay's on `agent/app-updates`; passed on rerun, unrelated to both branches. Likely fix: wait briefly (bounded) for
  the children before asserting, or have the helper report its pool's pids.
- [ ] **The updater on Windows, not yet seen on a lab PC** (Sentry's AU-7, AU-8; `ba22460`): whether a DLL uv
  hard-linked into HeLab's venv and loaded by another venv's Python is told apart (built: each Python's modules by
  path, a test on Windows CI), and whether git or uv flash console windows during an update (built:
  `CREATE_NO_WINDOW`). Until M68.3.

Tony (2026-10-22): note these, no fixes for now; raise them again only if they keep
happening. Counted over the last 12 CI runs from `gh api repos/TonyXTYan/HeLab/actions/jobs/<id>/logs`
(whose Windows logs include the test output; `gh run view --log` can return nothing). The Quick
Fixes floor (2026-10-23) fixed four (dropped from Fixed at the v0.0.6a1 tidy-up). A "worker
crashed" on CI with no traceback is usually CI's 120 s timeout, whose stacks
`faulthandler_timeout` now prints.

## Fixed

Landed in `dev/v0.0.9` (`dev/v0.0.8`'s were dropped at the v0.0.8a1 tidy-up; their release-notes lines are in
TonyXTYan/HeLab#11):

- [x] **Live stopped picking up shots after a conversion** (the lab PC, 2026-11-11, twice: no check or
  conversion for 2 h and 1.5 h until Live off and on). A Live check answering `live_unchanged` stayed in
  `FolderCache.jobs` until its `done`, so a check asked for in between was joined to it and never ran. Fixed in
  `997e4e5` with a backstop (`0a90050`) and the unreadable-file rule (`c24bd5d`; block 74, merged `e6603ab`); M74.1.
- [x] **Stale `index.lock` in checkouts** (2026-11-12): `build_info._git`'s `git status`, run by every process
  importing `helab.utils.constants`, refreshed the index under its lock, and its 2 s timeout's kill under load
  left an empty `index.lock` that stopped the next commit (floors and Ground). Fixed in `8e882fa`
  (`GIT_OPTIONAL_LOCKS=0`; merged `e6603ab`); the per-process git calls remain (A74.3).
- [x] `test_convert_helab.py::test_a_raw_file_unreadable_for_20_s_is_unconvertible_and_holds_nothing_up`
  reran once (Windows CI 43150068338, Tests (2/3), the lab copy's run of `58304e7`): it asked for
  "Couldn't be read for 25 s:" and got 26 s, the clock going on during a slow run (the app was right).
  Fixed 2026-11-12: the test accepts 25–29 s.
- [x] `test_accessible_names.py::test_every_script_and_each_library`: "Basic plots › Plot T, X, Y histograms:
  QTabBar < QMainWindow < QSplitter < HelabMainWindow: no ID" (Windows CI 41086378298, 41465454700, Ground CI
  42765698387). Cause: the walk ran before the debounced dock fit that names the tab bar, late behind a stall in
  that same fit. Fixed in `762d56c` (GUI threads audit, GT-10: `DockTabCloser.fit` maps the area's docks once, and
  the walk runs pending fits first; merged `0930096`).
- [x] **Auto-load pause state carried across tests** (test isolation; Ground CI 41981742368 and `agent/folder-info`
  42001112700, RERUNs of `test_text_length.py`'s long-name test): `test_result_lifecycle`, `test_result_cache_plots` and
  `test_result_cache_review` patch a tiny disk budget and left the app-wide `FolderCache` paused (ten such tests in a
  suite trace); the next window test's `update_auto_load_pause()` on the real budget then showed "Disk cache below 80% —
  automatic loading resumed" in front of its status bar, eliding the Live phrase's end, and auto loads stayed paused in
  between. Fixed in `626ca02`: conftest's autouse `no_carried_disk_pause` clears the cache's usage and pause state
  before each test without emitting; `tests/test_carried_disk_pause.py` runs two tests in order and fails without it.
- [x] **An elided label raised in Qt's event loop as it was deleted** (LR-3's T3, `73098fa`): `ElidedLabel.event`'s
  override was also called for events Qt sends while deleting the label, where `super().event()` raised "wrapped
  C/C++ object of type ElidedLabel has been deleted". Seen as a RERUN of
  `test_result_cache_plots.py::test_the_source_line_marks_reuse` on Windows, Ground CI 41981742368 (Tests 1/3, job
  127093226656, `e638a22`). Fixed in `98a23af`: the override is gone and the app's tooltip filter (`TooltipWrap`)
  shows an elided label's full text. **LR-3's Windows summary line** (CI 41976935066, 41977069786, 41979494346:
  `test_folder_summary.py`'s fixed height and `test_text_length.py`'s sizes failing on every rerun): the Live line
  was measured before its layout sized it, and the tests used macOS sizes; fixed in `fc81f78`, `e638a22`,
  `c713f4c` (CI's offscreen Windows font needs 259 px where macOS needs 157).
- [x] **Folder details' conversion said nothing of a raw file whose read stopped early** (A58.2): only Live's
  auto-convert named it and notified. Folder details' Convert row now names it (one by name, several counted, the
  detail in its tooltip) and each file notifies once per session whichever conversion read it, through the shared
  `explorer_convert.note_read_stop` and `read_stops_text` (`6b22d8d`, Quick Fixes 10, landed `20dd672`). The row
  isn't amber for it yet (A60.1).
- [x] **The release job's notes linked the API's URL for the Workflow Run** (`github.event.repository.url`; v0.0.8a1's
  draft, run 41746737106), with no tag link and no comparison: `release_draft.release_body` now writes them, the
  run link from `github.server_url` (A59.1; `ca0bd61`, `be2f0e5`, `9e06bcb`, Quick Fixes 10, landed `20dd672`).
