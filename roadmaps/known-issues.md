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
- [ ] Beside conversion fails on a file system with neither hard links nor a no-replace rename:
  `txy.write_atomic` refuses rather than risk replacing a file, and the run stops with the reason (Quick
  Fixes 7, `c194f37`; Q38.1; M38.1 for the lab share).

- [ ] **A cached dataset over ~2.1 GB can't be saved.** `pack_dataset` (`helab/utils/cache_store.py:459`)
  compresses a whole folder in one Blosc call, and python-blosc 1.11.4 caps a call at 2,147,483,631
  bytes (store-v4 design note, 2026-10-29). Store-v4's chunked `.hlb` files fix it; until then a
  folder that large stays RAM only (check what the save reports).
- [ ] **Dataset files are pickles** (`DATASET_FORMAT = "blosc-pickle-1"`, `pickle.loads` in
  `unpack_dataset`, `cache_store.py:466-473`), unlike saved results (NumPy + JSON). A cache folder
  someone else can write to could run code in HeLab's helpers. Store-v4's pickle-free `.hlb`
  containers fix it (design note, 2026-10-29).

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
  across Refresh; the startup "database is locked" on a fresh store; refuse a
  network or synced temp folder at startup, as the cache folder is.
- [ ] With the default of one background lane, folder details and status checks
  (including manual ones) wait for the selected load. As planned; revisit if
  it feels slow.
- [ ] When a tab's shown data is dropped while it is shown (a folder status check finds
  the folder mismatched, or its cache is cleared), the tab keeps its arrays and later
  plots on screen; a load finding missing shots clears them (Tony, 2026-10-14). Since
  plotting, a plot whose folder signature no longer matches says "Showing previously loaded
  data" (`_update_plot_source_label`); not checked: a cache clear, which keeps the signature,
  and the tab's own arrays (2026-10-28).
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

- [ ] `test_live_plots.py::test_each_plot_keeps_its_scripts_minimum_size[Scatter3D]` reran once on
  Windows CI (run 40808815122, `agent/txy-followups` `ec1338a`, group 1/2), no reason in the log (a
  worker crash?); passed on retry. Also a macOS local worker crash (gw2, `agent/txy-index` `0f69731`,
  2026-10-30). Likely the QtWebEngine crash below.
- [ ] **QtWebEngine crashes xdist workers** (the Plotly and Scatter3D entries here):
  `test_accessible_names.py::test_every_script_and_each_library` crashed its worker once in a local
  full run (2026-10-30, `agent/smoke-ready`), passed on rerun; macOS's crash report gives the
  mechanism the other entries lacked: **SIGTRAP (EXC_BREAKPOINT) on a QtWebEngineCore thread** (a
  Chromium check failing, frames all in QtWebEngineCore under an NSRunLoop source), not Python or
  HeLab's code. That test now closes each web-view plot once walked (at most one renderer open).
  A second mechanism, now fixed (below): a SIGSEGV on the main thread when a Plotly plot's dock was
  deleted; some of these worker crashes may have been it. Watch whether they recur after `c104502`.
  They do: `test_accessible_names.py` crashed its worker on Ground CI 41100591971 (Windows Tests 1/2, job
  124217404251, gw0, `371751d`), PR CI 41095142656 attempt 1 (macOS Tests 1/2, `8ccc0be`) and PR CI
  41104589243 (macOS Tests 1/2, job 124231159424, `92c532b`); each passed on rerun (2026-10-31).
- [ ] `test_accessible_names.py::test_every_script_and_each_library`: "Controls without an accessible
  name: Basic plots v1 › Plot T, X, Y histograms: QTabBar < QMainWindow < QSplitter < HelabMainWindow: no
  ID", Windows CI 41086378298 (Tests 1/2, job 124168617741, gw0, `dev/v0.0.7` `9de3e19`, 2026-10-31);
  passed on rerun. Not a worker crash: likely a dock tab bar Qt makes when docks tabify, walked before
  `identify` names it. Cause not found.
- [ ] `test_gui_responsiveness.py::test_timeout_retry_releases_dead_helper_slot_while_artifact_reader_is_blocked[2]`:
  `waitUntil timed out in 3000 milliseconds` at line 292 (the `finally`'s wait for the killed fake
  helpers to exit after `service.shutdown()`), on Windows CI run 40803552596 (`agent/txy-ship`) and
  once locally on macOS; passed on retry. Again on Windows: Ground CI 40861772277 (`9f0b21f`) and
  `agent/txy-index` CI 40874212130; Ground CI 40988453930 (`c492242`, Windows Tests 1/2) and 41000437956 (`43cb202`);
  the `[1]` case on Windows, `agent/ui-polish` CI 41005221588 (same line). A candidate: 3 s under load.
- [ ] `test_plot_backends.py::test_2d_plots_draw_with_every_library[values0-Plotly-CountsPerShot]`: an
  xdist worker crashed on Windows CI run 40803552596; passed on retry (no traceback; look for a
  faulthandler dump). Again: the Plotly case on `agent/byte-units` CI 40865344851 (job 123418722344,
  gw3), and `[values1-Matplotlib-CountsPerShot]` on `agent/txy-index` CI 40883472651 (job
  123480992297, gw1). The Plotly case again on Windows Tests 2/2: Ground CI 41084197666 (job
  124161029996, `dd540cd`) and PR CI 41095142656 (`8ccc0be`).
- [ ] `test_io_service_run.py::test_writing_held_data_out_counts_as_progress`: `assert (2 == 1)` at
  line 40 (two progress marks, 0.7 ms and 1.4 ms, where one is expected), Windows CI 40863356565
  (job 123411955603, `agent/txy-index`); passed on retry. Again: `agent/runner-tools` CI 40989399407
  (Windows); Ground CI 41084197666 (Windows Tests 2/2, job 124161029996, two marks 0.96 ms and 1.5 ms).
  A Windows timing flake; IOService untouched.
- [ ] `test_root_discovery.py::test_volume_check_alone_refreshes_hints_without_visiting_markers`:
  xdist worker gw2 crashed on macOS CI 40866574094 attempt 1 (job 123422851726, `agent/txy-index`
  `9691873`; `INTERNALERROR> AssertionError: (…, <WorkerController gw2>)`, exit code 3, no RERUN);
  attempt 2 passed; it also reran on macOS in CI 40879735789 (job 123467827712). The test patches
  `os.lstat` for the whole process; an unraisable reached pytest's hook, whose `tracemalloc_message`
  ran coverage's `canonical_filename` → `os.path.realpath` → the patched `lstat` → `Failed` inside the
  hook. Fix: patch the name the code under test calls (`data_roots`' or `infra`'s), or `gc.collect()`
  before patching. The collected object may be one of `test_cache_switch.py`'s leaked connections
  (next).
- [ ] `test_cache_switch.py` leaves three `sqlite3.Connection`s unclosed (`ResourceWarning:
  unclosed database` with `-W always::ResourceWarning`): two in
  `test_load_that_cannot_read_the_cache_leaves_its_flag_unknown`, one in
  `test_newer_store_is_read_but_never_written` (the store's error paths). They surface when the GC
  collects them, in whatever test runs then. Found by the TXY Index floor on `9f0b21f`.
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
  passed on its rerun. A crash, not an assertion (a native fault in a GUI test?); cause unknown.
- [ ] `test_test_isolation.py::test_pytest_imports_the_checkout_it_runs_in_before_any_other`: a
  collection error in pathlib `lstat` on Windows CI (run 40754482305, `agent/txy-packaging` `7d2bff9`),
  passed on retry. Again on Windows Tests (2/2): `agent/byte-units` CI 40989130996 (job
  123847075029) and `agent/smoke-ready` CI 40990082872 (job 123850152612), both passed on retry; Ground
  CI 41072414259 (job 124119750861, `2960680`).
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
- [ ] `test_live_plots.py::test_a_floating_plot_runs_and_follows_with_its_settings_in_its_window`
  reran once on macOS CI (run 40260284152): `'completed' == 'cancelled'`. Cause unknown
  ([audit](../.ai/sessions/2026-10-28-claude-v0.0.6-checks/audit.md) #23, 2026-10-28).
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

Landed in `dev/v0.0.8` (`dev/v0.0.7`'s were dropped at the v0.0.7a1 tidy-up; their release-notes
lines are in TonyXTYan/HeLab#10):

- [x] **0.0.7a1 got no tag and no draft** (2026-10-31): `main`'s "Tag tested main commit and create draft
  release" (run 41110274554, job 124257980580) stopped in `release_draft --validate-only` with a
  `JSONDecodeError`. Every entry ending in `/helab/_build_info.json` was read as JSON, and in the macOS
  zip `Contents/Frameworks/helab/_build_info.json` is now a symlink (`zip -y` stores its target's path):
  the shipped cython kernel makes PyInstaller keep `Frameworks/helab/` a folder and link its data files
  to `Contents/Resources/`. The packaged stamp was right (0.0.7a1, `e03c32a`, clean). PR CI never runs
  this step. Fixed on `dev/v0.0.8`: a linked stamp is followed and must lead to another stamp
  (`tests/test_release_recovery.py`; the old check fails and the new one passes on that run's macOS
  zip). Tony chose no hotfix to `main` (2026-10-31): v0.0.8's release is the first with zips. Running
  `release_draft --validate-only` on PR builds would have shown it before the merge (A39.1).
