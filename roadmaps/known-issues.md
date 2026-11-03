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
    waits for; a click that quits nothing isn't covered.
  - Saving an arrangement preset kept plot 19's unsaved Log Y. Possibly intended; Tony to judge.

## Tests and CI

- [ ] **The PR-only compatibility jobs (Python 3.11, 3.12, 3.14) fail** (soft; HeLab requires 3.13). PR #11's CI
  41648018025 (`f0bb9f9`), as on v0.0.7's PR (41104589243): 3.14's every job fails installing pygame (no 3.14
  wheel: "SDL.h file not found"); 3.11 and 3.12 Tests fail widely, mostly `test_cache_move` (116), `test_store_v4`
  (77), `test_typing` (33), `test_store_v3_question` (15). New since v0.0.7: 3.11's Converter backends fail 3
  (`test_convert_helab`'s cache-move and WAL tests). Not looked into; the required 3.13 jobs were green with no
  RERUN.
- [x] `test_script_probe.py::test_without_the_offscreen_plugin_the_probe_runs_without_an_application` reran once
  on Ubuntu, Ground CI 41640562938 (Tests 2/3, job 125932836198, `72ab47a`, the Follow-ups landing): it expected the
  probe to crash, but the folder read "didn't load: its import didn't finish within 2 s", so under CI load the probe
  hadn't started within the test's 2 s limit; passed on rerun. Being fixed on the Follow-ups floor (a limit the
  probe's start-up can't race). Fixed: `1920a67` (the tests wait 60 s; only rounds meant to hang get 2 s).
- [ ] `test_quit_confirms.py::test_quitting_with_nothing_to_save_closes_within_a_second` reran once on Windows,
  Ground CI 41578243240 (Tests 2/3, job 125726739543, `dcc02d8`, 2026-11-03): `assert (673.46 - 672.26) < 1.0`,
  quitting took 1.2 s; passed on rerun. The first Ground run with store-v4 on by default (the switch-on landed
  `92f9d1a`); "Disk cache inventory: Cancelled" was logged just after. Unchecked whether store-v4's quit path
  (the inventory, `raw_fill`) adds the time or the runner was busy. Again on Windows, Ground CI 41597667363
  (Tests 2/3, job 125788785096, `413b2a0`, 2026-11-03): reran twice, `assert (674.56 - 671.49) < 1.0`, quitting
  took 3.07 s; passed on the second rerun.
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
- [ ] `test_accessible_names.py::test_every_script_and_each_library`: "Controls without an accessible
  name: Basic plots v1 › Plot T, X, Y histograms: QTabBar < QMainWindow < QSplitter < HelabMainWindow: no
  ID", Windows CI 41086378298 (Tests 1/2, job 124168617741, gw0, `dev/v0.0.7` `9de3e19`, 2026-10-31);
  passed on rerun. Not a worker crash: likely a dock tab bar Qt makes when docks tabify, walked before
  `identify` names it. Again: `agent/caching-v2` CI 41465454700 (`ee4df2b`, Windows Tests 1/2, job
  125345114056), passed on retry. **Cause** (Vault, 2026-11-03, from that log): a plot dock area's tab bar gets
  its ID in `PlotWorkspace.fit` (`dock.py`, `identify_tabs`), which a debounced timer (`_fit_soon`) runs, and the
  walk ran before the timer fired ("GUI stalled for 2.30s" in that test the same second). `dock.py` is
  unchanged since 0.0.7a1. Fix: name the tab bar when docks tabify, or let the walk run pending fits first.
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
  `agent/caching-v2` CI 41386150963 (`df17761`, Ubuntu Tests 2/2, job 125087377900), passed on retry. A
  crash, not an assertion (a native fault in a GUI test?); cause unknown.
- [ ] `test_test_isolation.py::test_pytest_imports_the_checkout_it_runs_in_before_any_other`: a
  collection error in pathlib `lstat` on Windows CI (run 40754482305, `agent/txy-packaging` `7d2bff9`),
  passed on retry. Again on Windows Tests (2/2): `agent/byte-units` CI 40989130996 (job
  123847075029) and `agent/smoke-ready` CI 40990082872 (job 123850152612), both passed on retry; Ground
  CI 41072414259 (job 124119750861, `2960680`); `agent/caching-v2` CI 41375836115 (`84ccaeb`, job
  125055805809) and CI 41379212072 (`6b0f998`, job 125066159186); `agent/v4-switch-on` CI 41490797588
  (`d3b4931`, 2026-11-03); `agent/txy-priority` CI 41587970080 (Windows Tests 1/3, job 125757887948,
  `bf3fb85`, 2026-11-03).
- [ ] `test_gui_responsiveness.py::test_stalled_process_keeps_heartbeat_and_shutdown_responsive`:
  `assert 0.2199… < 0.2` (line 228) on macOS CI (run 40764414177), passed on retry.
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
- [ ] `test_result_lifecycle.py::test_save_x_eviction_of_the_same_key_before_its_transaction_saves_the_newer_copy`:
  `waitUntil` timed out (30 s) at line 71, in the same local run as the entry above (load ~37); passed on
  retry and 5 of 5 alone. Cause not looked into.
- [ ] `test_live_plots.py::test_a_floating_plot_runs_and_follows_with_its_settings_in_its_window`
  reran once on macOS CI (run 40260284152): `'completed' == 'cancelled'`. Cause unknown
  ([audit](../.ai/sessions/2026-10-28-claude-v0.0.6-checks/audit.md) #23, 2026-10-28). Again in a local full
  run on Ground (Quick Fixes 8, 2026-11-01, Rivet's handoff). Again on Ubuntu: Ground CI 41567847672 (Tests 1/3,
  job 125693660872, `5878bd2`, 2026-11-03), the same `'completed' == 'cancelled'`, passed on rerun.
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

Tony (2026-10-22): note these, no fixes for now; raise them again only if they keep
happening. Counted over the last 12 CI runs from `gh api repos/TonyXTYan/HeLab/actions/jobs/<id>/logs`
(whose Windows logs include the test output; `gh run view --log` can return nothing). The Quick
Fixes floor (2026-10-23) fixed four (dropped from Fixed at the v0.0.6a1 tidy-up). A "worker
crashed" on CI with no traceback is usually CI's 120 s timeout, whose stacks
`faulthandler_timeout` now prints.

## Fixed

- [x] **A runner whose /tmp is a mount of its own failed the result-cache, lifecycle and offline
  tests.** Ground CI 41587336570 (`a51176f`, Ubuntu Tests 3/3, job 125755838908) and 41570883747 (`b1a16d3`,
  Ubuntu Tests 1/3, job 125703300662), both on ubuntu-26.04 image 20261018.50.1: the tests' folders under
  `/tmp` weren't on a trusted mount, so cached reads waited for a volume check the tests' own FolderCaches never
  run ("its volume wasn't verified within 120 s"), on every rerun. Not store-v4 and not test order (Rivet).
  Fixed: conftest names the temp folder's and `--basetemp`'s mounts in `HELAB_TEST_FIXED_MOUNT`, which
  `data_roots.fixed_mount` trusts only when set (`ee4bbdf`, `21e614a`; landed `ab0b306`). Repro: `TMPDIR` on a
  mounted disk image; without the fix 63 failed and 20 errors.
Landed in `dev/v0.0.8` (`dev/v0.0.7`'s were dropped at the v0.0.7a1 tidy-up; their release-notes
lines are in TonyXTYan/HeLab#10):

- [x] **A user script with `from __future__ import annotations` and a `@dataclass` failed to load**
  (`AttributeError` from `dataclasses._is_type`; found writing the manual, 2026-11-03):
  `ScriptsManager._load_script_file` ran the module without registering it in `sys.modules`. **Fixed** (`c8d400c`,
  Docs floor, landed `b0e3aac`): the module is in `sys.modules` as `helab.scripts.dynamic.<file name>` only while
  its file runs (`scripts_manager._importing`), then whatever held the name is put back; `test_script_modules.py`.
- [x] `helab cache --help` printed a person's name: `helab/cache_cli.py` built argparse's description from its
  docstring. Public CLI output. **Fixed** (`0ab9c87`, Docs floor, landed `b0e3aac`): an explicit `DESCRIPTION`;
  `tests/test_cli_help.py` keeps the user commands' help free of names and item IDs.
- [x] **A shot held from a fallback External stopped Live** (found by the TXY Priority floor's tests for review
  TP-3, 2026-11-03): under a list such as `m23v1 › m19v1`, a shot Live held from External (the fallback) that an
  entry of the list then had made `live_check` and `save_held` stop with "changed". **Fixed** (`8f250df`, landed
  `9bf99ff`): Live reads such a shot again, as A39.2's switch does (External feeding the mismatch rule meanwhile),
  and `save_held` composes with `reclaim=False`; tests of `live_check` and `save_held` under the list fail without
  the fix.
- [x] `test_converter_tab.py::test_the_cache_tab_shows_and_clears_converted_txy` failed all 6 tries in two `-n 4`
  runs on the TXY Priority floor (2026-11-03); it passed alone. **Cause:** it counted converted TXY in the xdist
  worker's temp folder (conftest's `DIR_TEMPS`, one per session), so any test that converted to "temp" earlier on
  the same worker (`test_explorer_convert`'s `[temp]` case, the floor's `test_convert_folder`) left files there,
  and each retry then hit `FileExistsError` on its own folder; reproduced in one process with either test first.
  **Fixed** (`f944a5a`, landed `9bf99ff`): each of those tests has its own temp folder. CI 41590741400: no RERUN.

- [x] **Plotly worker deaths** in `test_plot_backends.py::test_2d_plots_draw_with_every_library`'s Plotly cases
  (`[values0-Plotly-CountsPerShot]`, `[values0-Plotly-TxyHistograms]`, `[values1-…]`, `[values2-…]`): an xdist worker
  crashed or aborted ("Fatal Python error: Aborted"), each passing on retry. Seen on Windows CI 40803552596;
  `agent/byte-units` CI 40865344851 (job 123418722344, gw3); Ground CI 41084197666 (job 124161029996, `dd540cd`) and
  PR CI 41095142656 (`8ccc0be`); `agent/plot-identity` CI 41158691080 (job 124411181934, gw1); `agent/caching-v2` CI
  41389534725 (macOS, job 125097691928, gw8); and, once three test groups put the crash order on gw1 of group 2/3,
  CI 41481668334 (macOS 2/3), 41484513530 (Ubuntu 2/3 and macOS 2/3), 41488725971 (macOS 2/3), 41489860538
  (Ubuntu 2/3) and 41490372206 (Windows 1/3). **Cause** (Quick Fixes 9): four test files made the worker's
  `QApplication` with an empty argument list (`test_memroyUsageWindow.py`'s session fixture, `test_icons_pt.py`'s
  autouse fixture, `test_icons_ut.py` and `test_main_ut.py`'s `setUpClass`); when one ran as the worker's first Qt
  test, QtWebEngine's first web view ended the process (a qFatal, "Argument list is empty, the program name is not
  passed to QCoreApplication", SIGABRT under `WebContentsAdapter` from `PlotlyPane.__init__`). A replay of gw1's
  order aborted 5 of 5; a bisect by file left `test_memroyUsageWindow.py` then the Plotly case. **Fixed**
  (`b0eb914`): those fixtures take `qapp` or `conftest.qt_application()`, a subprocess script passes
  `sys.argv[:1]`; `tests/test_qt_application.py` guards it (no `Q*Application()` or `([])` in `helab/` or
  `tests/`) and replays the crash order. CI 41493818761: no RERUN, and gw1 survived the old order. Not this cause:
  the SIGTRAP and the Matplotlib case (open above).
- [x] `test_live_plots.py::test_transfer_fractions_highlight_follows_lives_newest_shot`: worker gw2 died ("Fatal
  Python error: Segmentation fault") on `agent/caching-v2` CI 41471378031 (`76e0f91`, Ubuntu Tests 2/2, job
  125365677960, `[PyQtGraph]`), and locally on macOS (`[Matplotlib]`, 2026-11-03); each passed on retry. **Cause**
  (Lumen, `823589a`): the tests make a Scripts panel with no Qt parent, which becomes cyclic garbage once `plot()`
  returns; Live Scripts' amber start note was a style sheet, so polishing the panel ran Python
  (`ElidedLabel.changeEvent`), and a garbage collection there freed the half-polished panel (SIGSEGV in
  `QWidgetPrivate::updateIsOpaque`). Not the library switch (the crash came before it), and users can't hit it (the
  app's panel is Qt-owned; a replaced plot widget stays Qt's until its `deleteLater`). **Fixed** (`823589a`): the
  note is amber by its palette; a nested pytest forcing collections in the polish (SIGSEGV before), a
  no-Python-in-polish test and a library-switch guard test. The test rule: [testing](../.ai/architecture/testing.md)
  (A52.1 for the other test sites).
- [x] `test_presets_plots.py::test_an_arrangement_preset_round_trips_every_bundled_script` hung on a modal "Preset
  can't be read" until killed at 100 s, on `agent/v4-switch-on` CI 41484277419 (Ubuntu Tests 2/3, job
  125410633098). **Cause** (Lumen): a preset saved while an identity probe is out is held as owed and written when
  the probe answers; the test's simulated restart shut the helpers down before that write, so the re-read lacked
  the preset. A real quit waits for it. **Fixed** (`566eed6`): the restart waits for an owed write
  (`restart_presets` asserts `not presets_saving()`); `presets.warning_box` is a seam, and conftest's autouse
  `no_modal_warnings` fails any test that would wait on that modal instead of hanging (Prismo's L1).
- [x] `test_explorer_convert.py::test_auto_convert_beside_on_a_share_once_confirmed_or_turned_off[off]`: the share
  question didn't appear within 5 s (line 114), on `agent/v4-switch-on` CI 41482722171 (macOS Tests 1/2, job
  125405134241) and once in the plot-library-crash floor's local full run (its A~1); passed on rerun. **Cause**
  (Ember): on a slow runner Live's next tick queued a conversion (beside False, the flag not yet known) before the
  test set the folder's beside flag, and nothing ran it, so auto-convert stayed "requested"; the same race gave
  `…asks_retry_or_hellabs_folders[retry]` a stale payload. The app is right both ways. **Fixed** in the tests
  (`beside_flag_in_live`, merged `f1194df`): the old tests failed 4 of 13 loaded rounds, the new ones 1,200 of 1,200
  passed.
- [x] `test_convert_helab.py::test_two_writers_side_by_side_lose_nothing`: `IndexUnavailable … database is locked …
  SQLITE_BUSY` on Windows, Ground CI 41476107464 (Tests 2/2, job 125382190899, twice), then `[a writer missing its
  window]` at shot 0 after 0.04 s on CI 41483647539 (Tests 3/3), and failing after 5 reruns in Converter backends on
  `agent/converter-ux` CI 41489860538 and `agent/preset-modal-hang` CI 41500431969 attempt 1 (branches without the
  second fix). **Cause:** the test's writer processes open the index per shot, and on a slow runner one missed its
  window past `BUSY_SECONDS`, which the app takes as harmless (the conversion is tried again later). **Fixed** in
  the test (Quick Fixes 9): writers try such a shot again (`324ad79`, 4 times), then until `RETRY_SECONDS` (30 s),
  as a conversion is retried for as long as it takes (`28d8973`); a 1 ms repro case kept (the old writer fails it 7
  of 10).
- [x] `test_release_recovery.py::test_detached_pr_stamp_records_source_branch_and_merge_ref_without_replacing_commit`:
  `assert 'unknown' == 'detached'` at :337 on Windows CI 41481668334 (Tests 3/3) and 41490372206 (Tests 3/3).
  **Cause:** `build_info._git` gives each git call 2 s, and `git status --porcelain` on the test's fresh
  `--no-checkout` clone (it refreshes the whole index) took longer on a slow runner, so `checkout_build_info`
  returned an all-"unknown" stamp. **Fixed** in the test (`a599ac6`, Quick Fixes 9's option (b)): one untimed `git
  status` first; the app keeps 2 s per git call. Option (a), a longer timeout where it can't slow the app's start
  (the build's stamp), only if a real build ever stamps "unknown".
- [x] `test_live_convert.py::test_a_conversion_refused_offline_stops_auto_convert_and_says_so`: "Live stopped:
  Cancelled" where "auto-convert stopped: not while working offline" was expected (line 575), `agent/caching-v2` CI
  41472779247 (`1cffaba`, macOS Tests 2/2, job 125370535914); passed on retry. **Cause:** Live checks every 20 ms
  there; a check its tick asked for while the test was offline was refused, and its "cancelled" halted Live
  first. **Fixed** in the test (`d03c0c6`, Quick Fixes 9): Live's next check is queued before going offline
  (`next_request`); the repro case kept.
- [x] `test_live_scripts.py::test_a_reload_waits_for_a_run_of_its_scripts_on_the_worker_thread`: `in_flight()`
  empty at :206, Ground CI 41463943327 (Ubuntu Tests 1/2, job 125340069131); passed on retry. **Cause:** the test
  waited for `runner.in_flight()`, which counts a job from when it is queued; on a busy runner the reload cancelled
  the still-queued job, which then ended uncomputed. The app is right (a cancelled run that never started
  shouldn't hold a reload). **Fixed** in the tests (merged `f534ede`): it and
  `test_removing_the_folder_a_reload_waits_for_ends_the_wait` wait for the script's `STARTED` event; 200 runs under
  load with no RERUN.
- [x] **Windows test jobs near their limit:** Ground CI 41460607344's Windows Tests 2/2 took 24 min 40 s (usually
  10–13; no single test, the longest gap 18 s: a slow runner), and Ground CI 41476107464's Windows groups 20.3 and
  21.1 min of pytest, against a stop line of about 25 and the job's 30. **Fixed** (Quick Fixes 9): three test
  groups per OS (`9787e35`; Windows about 9–11 min a group since), with `--session-timeout` (`457debc`) and the
  junit.xml artifact (`5324a7f`) so a job cut short keeps its reasons.

- [x] **A quit test leaves its `GUIWatchdog` running** (a log line, never a failure): `HelabMainWindow.closeEvent`
  stops the watchdog only on its full path; it returns early when a close waits for saves (`_wait_for_saves`
  opens `QuitSaveDialog`) or a quit dialog is open, and `qtbot.addWidget`'s close at teardown doesn't stop it
  either. The worker, idle at the end of its run, then logs `ERROR:root:GUI stalled for 62.74s; capturing
  thread stacks` (`gui_watchdog.py:40`). Seen in a local full run on `agent/caching-v2` (2026-11-02; the
  faulthandler dump showed the main thread idle in execnet beside a live `GUIWatchdog` thread) and 4 times on
  `agent/caching-v2` CI 41393351958 (`28d5844`: Windows Tests 1/2 twice, Windows 2/2 and Ubuntu 2/2 once).
  Likely `tests/test_quit_confirms.py` or `tests/test_txy_last_used_quit.py` (not pinned: neither reproduces
  alone). Fix: A47.3 (finish or cancel the dialog in those tests, or stop the watchdog when the window is
  destroyed). Vault's handoff, step 3.
  **Fixed** (`36b2224`, A47.3, Quick Fixes 9): `_watch` ends once its QObject is deleted, so a window deleted
  without its full close takes the thread with it (`tests/test_gui_watchdog.py`). The "GUI stalled" lines still
  seen on Windows CI were then named (`1bc8020`: the line names its window and, under pytest, the test that made
  it and the test running now): in CI 41449699791 and 41455114540 every line's window was made in the test running
  then (the accessible-names walk, up to 27.8 s; the Debug runner's tests; a preset Live test), so these are tests
  blocking the GUI thread with their own window, not a leak; lines that seemed to fire during converter tests were
  another worker's output interleaved in the log ([testing](../.ai/architecture/testing.md)).
- [x] `test_io_service_run.py::test_a_helper_still_starting_when_helab_quits_is_stopped` (A40.1's guard test):
  `TimeoutExpired` after 10 s at :162, `agent/caching-v2` CI 41451159277 (Windows Tests 2/2, job 125296521261);
  passed on rerun. Its `Popen` fake took any `HeLab-*` thread, so another IOService's helper start meanwhile
  entered it and could be `started[0]`, which the test never kills (`this_tests` wouldn't help: that thread starts
  after the patch). **Fixed** (`d480a82`, Quick Fixes 9): the fake takes only this request's start, known by its
  stderr file in the request's folder (`IOService.before_start`); the repro case kept. CI 41455114540: no RERUN.
- [x] `test_io_trace.py::test_the_gui_process_never_touches_source_folders`: `waitUntil timed out in 20000
  milliseconds` at :259, inside `wait_idle` (not the invariant's assertion, which comes after), on Windows CI
  41456480233 (`agent/caching-v2` `2247b69`, Tests 2/2, job 125314458602) and 41457940413 (`agent/converter-ux`
  `baf7a1c`, Tests 2/2, job 125319510384; the first attempt 34 s, the rerun 8 s); each passed on rerun. Neither
  branch reaches it (the test runs with store-v3 and builds no Folder details panel); the test takes 9–18.5 s on
  Windows runners (3.4 s locally), near its 20 s wait. **Fixed** (`ee4994b`, Quick Fixes 9): its five helper waits
  share `HELPERS_MS` = 60 s; other tests' `wait_idle` keep 20 s; the assertions are unchanged.
- [x] Beside conversion failed on a file system with neither hard links nor a no-replace rename:
  `txy.write_atomic` refuses rather than risk replacing a file, and the run stopped with the reason (Quick
  Fixes 7, `c194f37`; Q38.1). **Fixed** as Tony decided (Converter UX, landed `ed7bcf9`): the helper sends
  `beside_refused`, and the app and `helab convert` ask Retry, or write to HeLab's cache or temp folder
  instead, never silently. The lab share itself is M38.1 and M48.2.

- [x] `test_typing.py::test_pyright_helab` and `test_accessible_names.py::test_every_script_and_each_library`
  passed pytest-timeout's 120 s on a slow macOS runner: `agent/caching-v2` CI 41389534725 (`93a938b`, macOS
  Tests 1/2, job 125097691928) killed the pyright test's worker 5 times ("node down: Not properly
  terminated") and the walk's once ("Timeout (0:01:40)!"); each passed on rerun. Their normal times sit near
  the limit (pyright 40–97 s, the walk 27–99 s across OSes; 115–142 s and 123 s on that runner).
  **Fixed** (Quick Fixes 9): their own `pytest.mark.timeout(300)`, each with a guard test: `test_typing.py`
  (`e8a28a1`), the walk (`5f52068`); CI 41392473183 and 41394539355 green with no RERUN.
- [x] `test_folder_icons.py::test_native_icon_delivery_is_shared_and_rendering_stays_memory_only`:
  "Painting an icon performed I/O or submitted work" raised on another thread (pytestqt "Failed to
  process thread exception"), Ground CI 41164525298 (Windows Tests 1/2, job 124429158185, gw0,
  `82c9db3`); passed on rerun. It patches `os.stat` and `os.scandir` for the whole process, so likely
  another thread in the worker stat'ed meanwhile (the trap above). Fix: check only the GUI thread's calls
  (Quick Fixes 8, 2026-10-31).
  **Fixed** (`eccb23c`, Quick Fixes 9): the I/O fakes raise only on the GUI thread; the repro case kept.
- [x] `test_io_service_run.py::test_writing_held_data_out_counts_as_progress`: `assert (2 == 1)` at
  line 40 (two progress marks, 0.7 ms and 1.4 ms, where one is expected), Windows CI 40863356565
  (job 123411955603, `agent/txy-index`); passed on retry. Again: `agent/runner-tools` CI 40989399407
  (Windows); Ground CI 41084197666 (Windows Tests 2/2, job 124161029996, two marks 0.96 ms and 1.5 ms);
  Ground CI 41158349537 (Quick Fixes 8, Windows Tests 2/2, job 124410096333, twice); `agent/caching-v2`
  CI 41164715526 (Windows Tests 2/2, job 124429733436, marks 1.4 ms and 5.2 ms); Ground CI 41182171527
  (`23ab189`, Windows Tests 2/2, job 124481666642); `agent/caching-v2` CI 41186805673 (`9abdb58`, Windows
  Tests 2/2, job 124495315262, twice, marks 0.72/1.36 ms and 0.73/1.36 ms). A Windows timing flake;
  IOService untouched by those branches. Tony, 2026-10-31: a Quick Fixer hunts its cause.
  **Fixed** (`3bafef1`, Quick Fixes 8): not two progress marks. The test's fake replaced `subprocess.Popen`
  for the whole process, so another thread's helper start (left over from an earlier test) was counted;
  the test now counts only its own thread's calls (the repro kept as a second case). `IOService._run`
  unchanged. Ground CI 41202772809 (`110033d`): no RERUN.
- [x] **0.0.7a1 got no tag and no draft** (2026-10-31): `main`'s "Tag tested main commit and create draft
  release" (run 41110274554, job 124257980580) stopped in `release_draft --validate-only` with a
  `JSONDecodeError`. Every entry ending in `/helab/_build_info.json` was read as JSON, and in the macOS
  zip `Contents/Frameworks/helab/_build_info.json` is now a symlink (`zip -y` stores its target's path):
  the shipped cython kernel makes PyInstaller keep `Frameworks/helab/` a folder and link its data files
  to `Contents/Resources/`. The packaged stamp was right (0.0.7a1, `e03c32a`, clean). PR CI never runs
  this step. Fixed on `dev/v0.0.8`: a linked stamp is followed and must lead to another stamp
  (`tests/test_release_recovery.py`; the old check fails and the new one passes on that run's macOS
  zip). Tony chose no hotfix to `main` (2026-10-31): v0.0.8's release is the first with zips. Running
  `release_draft --validate-only` on PR builds would have shown it before the merge: since `c201c01`
  every 3.13 build checks its own archive (`release_draft --check`, A39.1).
- [x] `test_raw_fill.py::test_encoding_a_large_raw_file_keeps_heartbeats_going` (new with C3-1): failed
  after 5 RERUNs on macOS CI 41186805673 (`agent/caching-v2` `9abdb58`, Tests 1/2), 2–4 heartbeats where it
  asked for ≥ 5. The test counted heartbeats in a fixed 0.3 s window at a 0.02 s interval, and a loaded
  runner's ticker thread got fewer turns; the code was fine. Fixed in the test (`375562e`, landed
  `c2d0ece`): the slow encode lasts until three heartbeats have come, with a 10 s deadline; 25 of 25 runs
  under a 12-process CPU load with reruns off, and it fails without C3-1's ticker. CI 41188263711: no
  RERUN.
- [x] `test_cache_switch.py` left three `sqlite3.Connection`s unclosed (`ResourceWarning: unclosed
  database`; found by the TXY Index floor on `9f0b21f`). Fixed on `agent/caching-v2` (`46f481f`, landed
  `ad86bd3`): the leaks were the tests' own `with sqlite3.connect(...)` blocks (29 in 11 files; sqlite3's
  context manager commits but never closes), not the store's error paths; tests now use
  `contextlib.closing`.
- [x] `test_live_convert.py::test_a_converted_shot_asks_for_lives_next_check`: `'' == 'check'` at :231,
  macOS CI 41158349537 (Tests 2/2, gw3; passed on rerun). A race in the test: when two ticks in a row are
  late, a check queued with a conversion is answered by `cycle` without running it, so the test reached
  :230 with a conversion queued and no check out yet. Fixed in the test (`8145ff1`, IO Fixes, landed
  `471966b`): it waits for the conversion and a check, with `live_interval` 0.02 and 0 (0 reproduced it
  3/3).
- [x] `test_cache_mover.py::test_startup_waits_out_a_move_then_recovers_and_registers`: `[True, True,
  True] == [True]` at :198, CI 41162160704 (IO Fixes `623ce20`, Windows Tests 1/2); passed on rerun.
  Windows frees a killed helper's `move.lock` a little later, so `startup` found it held and waited again.
  Fixed: the test's `wait()` also waits until the move lock is free (`e8e7ebc`).
- [x] `test_one_running.py::test_the_running_lock_is_held_by_one_process_and_freed_when_it_ends`:
  `None is not None` at :50, Ground CI 41160032390 (Windows Tests 1/2, job 124415375251). It waited on
  `take_running`'s tuple, always truthy, so never waited out Windows' late release of a killed process's
  lock. Fixed: it waits on the lock itself (`f128623`).
- [x] `test_main_split.py`'s window test (`[1300]`) failed on Windows (CI 41161048586, 41161254527): its
  window's splitter width depended on the worker's history (without `IconsInitUtil.initialise_icons()` the
  side toolbars show their text, and whichever earlier test set the icons up decided it). Fixed: the test
  checks the panels against `fitted()` for the splitter it got (`279fc8b`), the file sets the icons up for
  every test (`04a667a`), after the `QApplication` (`1f86ca2`: icons made first aborted six workers on CI
  41164525298). Other window tests: A43.1.
