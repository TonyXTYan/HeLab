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
  own conversion is unaffected; reconvert those shots from raw.

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
    when the click landed before the menu opened; cause unknown.
  - In the plot settings panel, Return doesn't commit a typed value (the editor stays open);
    Tab does.
  - A plot tab's "x" didn't respond to computer-use clicks (the dock title's "x" did). It may
    be only an accessibility gap.
  - Saving an arrangement preset kept plot 19's unsaved Log Y. Possibly intended; Tony to judge.

## Tests and CI

- [ ] `test_live_plots.py::test_each_plot_keeps_its_scripts_minimum_size[Scatter3D]` reran once on
  Windows CI (run 40808815122, `agent/txy-followups` `ec1338a`, group 1/2), no reason in the log (a
  worker crash?); passed on retry.
- [ ] `test_gui_responsiveness.py::test_timeout_retry_releases_dead_helper_slot_while_artifact_reader_is_blocked[2]`:
  `waitUntil timed out in 3000 milliseconds` at line 292 (the `finally`'s wait for the killed fake
  helpers to exit after `service.shutdown()`), on Windows CI run 40803552596 (`agent/txy-ship`) and
  once locally on macOS; passed on retry. Again on Windows: Ground CI 40861772277 (`9f0b21f`) and
  `agent/txy-index` CI 40874212130; Ground CI 40988453930 (`c492242`, Windows Tests 1/2). A candidate: 3 s
  under load.
- [ ] `test_plot_backends.py::test_2d_plots_draw_with_every_library[values0-Plotly-CountsPerShot]`: an
  xdist worker crashed on Windows CI run 40803552596; passed on retry (no traceback; look for a
  faulthandler dump). Again: the Plotly case on `agent/byte-units` CI 40865344851 (job 123418722344,
  gw3), and `[values1-Matplotlib-CountsPerShot]` on `agent/txy-index` CI 40883472651 (job
  123480992297, gw1).
- [ ] `test_io_service_run.py::test_writing_held_data_out_counts_as_progress`: `assert (2 == 1)` at
  line 40 (two progress marks, 0.7 ms and 1.4 ms, where one is expected), Windows CI 40863356565
  (job 123411955603, `agent/txy-index`); passed on retry. A Windows timing flake; IOService untouched.
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
- [ ] `test_root_gui.py::test_the_gui_never_writes_the_saved_file_itself`: xdist worker gw0 crashed
  once on macOS CI (run 40790093719, `agent/quick-fixes-5` `ed0635c`, job 123172940859, 2026-10-29);
  passed on its rerun. A crash, not an assertion (a native fault in a GUI test?); cause unknown.
- [ ] `test_test_isolation.py::test_pytest_imports_the_checkout_it_runs_in_before_any_other`: a
  collection error in pathlib `lstat` on Windows CI (run 40754482305, `agent/txy-packaging` `7d2bff9`),
  passed on retry. Again on Windows Tests (2/2): `agent/byte-units` CI 40989130996 (job
  123847075029) and `agent/smoke-ready` CI 40990082872 (job 123850152612), both passed on retry.
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

Landed in `dev/v0.0.7`:

- [x] `test_convert_helab.py::test_two_writers_side_by_side_lose_nothing` starved on Windows
  (`IndexUnavailable … database is locked … SQLITE_BUSY` after 10.75 s; one RERUN in CI 40977028554,
  `0b00fdc`, Windows Converter backends; earlier, with a rollback journal, CI 40879735789). SQLite's
  write lock isn't fair, and the test's two processes wrote 150 rows each back to back, opening the
  index per row, so WAL's `-wal` was rebuilt on each open too; a conversion opens it once per run and
  spends a shot's work between rows. Fixed on `agent/txy-index` (landed `460360b`): WAL, then the
  writers pause 5 ms per row (a lost row still fails it). If it reruns again: a blocking OS lock
  around each write transaction (A30.3 notes the related connection reuse).

- [x] CI's Windows test job hit its 30-min limit at 99% (run 40790912863, `02cda86`): the six
  `tests/test_typing.py` tests ran last, serially on one xdist worker (a 2-4 min tail on every OS).
  Fixed by Quick Fixes 6 (merged `977120e`): a conftest collection hook starts them first, one per
  worker, and each mypy test has its own cache folder, since mypy runs sharing one SQLite cache
  crash ("database is locked"). Windows' tail went from 174 s to 19 s (run 40797275638); the job
  still takes ~23-24 of its 30 min (Q16.2: two pytest groups per OS, A17.2).

- [x] Quick Fixes 5 (2026-10-29, merged `931f9f8`; `.ai/sessions/2026-10-29-claude-quick-fixes-5/notes.md`;
  Reviewer Sandpiper reproduced each cause):
  - `test_folder_summary.py::test_disk_cache_summary_tracks_shared_save_completion[cache_saved]`
    (macOS CI reruns since 2026-10-26): the test waited only for the second tab's dataset, which
    shows from RAM a zero-timer before the shared listing's replay brings the row's folder date; a
    slow loop pass let the wait return between them. The test now waits for the date too; the app's
    label corrects itself one timer later.
  - `test_convert_helab.py::test_watch_converts_new_shots_and_stops_on_ctrl_c` failed every attempt
    in suites started as a background job (`pytest … &`): the shell ignores SIGINT for those, the
    convert child inherited it and Python then installs no Ctrl-C handler. The fixture now starts
    the child with SIGINT handled; other tests that send SIGINT to a child need the same. The CLI is
    unchanged (from a terminal, Ctrl-C works).
  - `test_convert_helab.py::test_a_hung_backend_stops_sending_heartbeats` and
    `::test_heartbeats_while_computing_stop_after_the_budget` (macOS CI reruns): the tests used a
    0.02 s interval and ~0.1 s real-time budgets, so a ticker thread woken late sent nothing; the
    ticker itself is fine (1 s interval, ≥ 60 s budget). The tests now use a clock only they move.
  - `test_convert_helab.py::test_a_killed_helpers_workers_exit` (one Ubuntu rerun): a kill during a
    provenance or `folder.json` write left a JSON `.partial` that HeLab's own-folder cleanup didn't
    match; the cleanup now covers them (A12.4) and the test accepts exactly those names.

- [x] Four CI-flaky tests, fixed by Quick Fixes 4 (2026-10-29, merged `e9c5bfa`;
  `.ai/sessions/2026-10-29-claude-quick-fixes-4/notes.md`; Reviewer Plover reproduced three causes on
  the base code):
  - `test_preset_folder_live.py::test_offline_a_folder_never_listed_is_named_as_such` (4 CI reruns):
    offline, `PresetFolder.check` waited for a listing that had already answered `offline_unlisted`;
    the test passed only when the tab's startup resolve moved the selection after the apply. Fixed in
    the app (`helab/views/plots/presets.py`: the C-29 notice, then finish), so the notice now shows in
    a settled tab too.
  - `test_helabMainWindow.py` (the view-menu test after the window-icon test): a helper inherited the
    test's working folder, which the source guard denies outside temp and the checkout; the icon test
    now leaves `tmp_path` right after building the window (the trap itself: Tests and CI, above).
  - `test_folder_summary.py::test_scan_metadata_survives_restart_without_reading_txy_contents`: its
    process-wide `os.scandir` patch caught `IOService.release`'s `shutil.rmtree` on a daemon thread;
    the patches now act only on the test's own thread.
  - `test_io_trace.py::test_tracing_changes_no_event_and_no_source_call`: loads and Live checks send a
    file's progress event only 0.1 s after the last, so a slow traced run sent one more; the test now
    gives both runs a clock moving 1 s per reading.
  - Also `test_io_trace.py::test_off_unless_the_test_seam_names_a_folder` failed with a temps path
    containing spaces (split on whitespace; now `rsplit(maxsplit=1)`).

- [x] The release job left v0.0.6a1's draft with no assets (run 40675311830 on `main`, "Tag
  tested main commit and create draft release": "Draft was replaced, removed or published;
  refusing to modify it"). GitHub lists a draft under `untagged-<hash>`, so the lookup by tag
  missed it; v0.0.5a1's draft is empty the same way. The lookup also matches the draft's name
  now (`d36a20e`, not yet on `main`). The v0.0.6a1 draft is still empty (2026-10-28).
