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

- [ ] Folders with over 100,000 entries record a scan failure.
- [ ] The temp folder (`DIR_TEMPS`, Settings → General) is created and can be
  changed, but nothing uses it: helpers' private folders go to the system temp
  dir (`tempfile.mkdtemp` in `IOService`). Remove the setting, or move helper
  folders into it (2026-10-15).
- [ ] SMB audit leftovers (2026-10-20): a Windows-suited "seen twice" interval
  (Windows caches attributes 10 s); details scans for visible rows only; icons kept
  across Refresh; the startup "database is locked" on a fresh store; refuse a
  network or synced temp folder at startup, as the cache folder is.
- [ ] With the default of one background lane, folder details and status checks
  (including manual ones) wait for the selected load. As planned; revisit if
  it feels slow.
- [ ] When a tab's shown data is dropped while it is shown (a folder status check finds
  the folder mismatched, or its cache is cleared), the tab keeps its arrays and later
  plots on screen; a load finding missing shots clears them. Clear the analysis view
  or mark it stale, once plotting exists (Tony, 2026-10-14).
- [ ] `roots_verify` is missing from `io_helper.CACHE_ONLY`, though `IOService.CACHE_OPERATIONS`
  lists it: sent without a cache it would fail with a vague `KeyError`. `FolderCache` always
  sends one, so it can't happen today (2026-10-21).

## Tests and CI

- [ ] `test_gui_responsiveness.py::test_output_close_failure_cannot_leave_dead_helper_in_active_queue`
  needed one rerun on the RSPE Windows PC on three branches (2026-10-19).
- [ ] `tests/test_cache_tab.py::test_saves_restored_from_the_store_ask_with_its_numbers`
  fails when `tests/test_io_trace.py::test_a_live_save_keeps_dont_cache_and_the_budget`
  ran earlier on the same xdist worker: a pending save left in the shared test
  store ([register](../.ai/sessions/2026-10-20-claude-dld-coordinator/register.md)) (2026-10-20).
- [ ] Main-window tests resolve the default data path, which is
  `/Volumes/dld_output` when it is mounted: tests should never touch the real
  volume (2026-10-19).
- [ ] `test_window_resize.py::test_label_keeps_painting_after_resize[repeated]` and `[single]`
  rerun on macOS and Ubuntu CI: 12 jobs on `dev/v0.0.6`, 3 on agent branches
  ([CI survey](../.ai/sessions/2026-10-21-claude-ci-robustness/notes.md)) (2026-10-21).
- [ ] `test_live_plots.py::…[Matplotlib-TransferFractions]` crashed an xdist worker (a
  segfault) 7 times on `dev/v0.0.6` CI, macOS and Windows, never on the agent branches
  (2026-10-21).
- [ ] `test_plot_settings_panel.py::test_activation_sources` reran once on macOS CI; it didn't
  fail in 60 local runs under load (2026-10-21).
- [ ] `test_dash_server.py::test_stop_frees_the_port` reruns: when suites run at once on one
  machine (port 8050 contention), and 3 times in one Ubuntu CI job on its own (`c127469`), so
  contention isn't the whole cause; the port may not be free at once after the server stops
  (2026-10-21).

## Fixed

On `agent/ci-robustness` unless said (2026-10-21,
[notes](../.ai/sessions/2026-10-21-claude-ci-robustness/notes.md)):

- [x] A known `.helab-root` that turned invalid was forgotten in the store but not reported,
  so tabs kept the old root for the session; it now sends `root_changed` like a removed one
  (`7b0f95b`).
- [x] The store warning said "Disk cache could not be opened" twice (`95f2309`).
- [x] Windows: opening the store while another process closed it failed with SQLite's
  "disk I/O error" (the cause of `test_live.py`'s quitting-test flake, 12 of 16 agent Windows
  jobs); retried briefly now (`ab83c0c`). Watch CI to confirm it stays gone.
- [x] TXY files with four numbers a row loaded with their columns shifted (`60015d0`, `f03ef83`).
- [x] Load Scripts…: scripts listed again on reload, abstract base classes blocking a file,
  `SystemExit` at import (`38ecff8`, `f03ef83`).
- [x] `test_folder_cache.py::test_two_tabs_share_snapshot_arrays_and_default_resolution`
  (RSPE Windows PC, macOS CI): it checked the second tab's tree before its replays arrived
  (`2069c3c`).
- [x] `test_two_step_browse::test_refresh_cancels_only_automatic_subscriptions_and_suppresses_new_checks`
  and `…test_refresh_requests_details_for_new_subfolders_after_it_finishes` (macOS CI): they
  looked before Refresh's posted re-requests ran (`0550e28`).
- [x] `test_cache_mover.py`'s lock tests (Windows): a killed process's lock is freed a little
  later on Windows; the tests wait for it (`ff4d91e`).
- [x] macOS CI jobs ran the suite twice and hit the 15-minute limit; one run with coverage now,
  20-minute limit (`f9faefd`).
- [x] Tests that build a real `HelabMainWindow` read the developer's native QSettings; the
  settings factory gives tests a private ini (`01b3dc9`, `agent/refactor-plot-ui`).
- [x] Quitting cancelled cache writes still running in the background (a finished
  load's `disk_cache_pending` save), so the next check redid them. Fixed by the
  quit window (`QuitSaveDialog`, with Quit now) in Live L1 (2026-10-19).
- [x] Files still being written: settle age only, by Tony's decision (2026-10-20);
  Live re-reads a recently read shot that changes. The converter's temp-name
  rename remains the real fix.
- [x] `tests/test_live_io.py`'s pause test assumed a 3000-file background load
  was still running after setup. Fixed with `HELAB_TEST_READ_GATE`; both Live
  I/O tests now run on Windows too (Plots v1 polish, 2026-10-19).
