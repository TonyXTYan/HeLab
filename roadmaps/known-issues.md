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
- [ ] With a server clock more than 2 s off ours, a change in the same mtime step right after a
  listing (FAT and some shares keep 2 s) isn't seen by the quick check until the folder's next
  change (the next shot) or a Retry / Refresh (R-1's residual, agreed with the reviewer)
  (2026-10-22).

## Tests and CI

- [ ] `test_plot_settings_panel.py::test_activation_sources` reran once on macOS CI; it didn't
  fail in 60 local runs under load (2026-10-21). The Windows rerun was the web-view crash
  (fixed, below); the macOS rerun (`f9faefd`) was a teardown failure, cause unknown, and 160 local
  runs passed. CI now prints rerun reasons: read them at its next rerun (2026-10-22).

## Fixed

Landed in `dev/v0.0.6` from the Codebase Review floor's follow-up (merge `855bdaf`, 2026-10-22):

- [x] A server clock more than `SETTLE_SECONDS` (5 s) ahead of this PC's holds every new shot back
  as still being written for the whole skew (R-22). Tony kept the rule (a file with a future mtime
  is still being written); beyond 2 s ahead, helpers now send `clock_skew` and HeLab says the
  computers' clocks are out of sync, once per share or volume per session (`ClockSkewWarning`),
  and Live stops like an error stop (`cdc255f`, `bf05b59`).
- [x] Two HeLabs shared `<app folder>/logs/helab.log` and lost records at rollover; each now writes
  `helab-<pid>.log` (R-11, `752c638`). Nothing deletes old sessions' files yet.
- [x] The packaged app and wheels lacked `ai-icon.icns` ("Icon file not found") (R-12, `4c9f2a8`,
  `be12b7d`).
- [x] joblib stayed in the requirements with no importer (R-20, `ccce741`).

Landed in `dev/v0.0.6` from the Codebase Review floor (merge `0ee6ca2`, 2026-10-22); the
commits are on `agent/codebase-review` ([handoff](../.ai/sessions/2026-10-22-claude-codebase-review/handoff.md)):

- [x] The quick check of cached or RAM-held data compared the share's clock with this PC's, so a
  share whose clock is behind hid new shots until Retry / Refresh; it now compares the folder's
  own mtime from its last listing (`info["folder_mtime_ns"]`) (R-1, `4468eaf`).
- [x] A Live save's data dump ran under the no-progress timer, so a large dataset on a slow disk
  timed out before its helper started (R-2, `265f35e`).
- [x] The frozen build's response reader could miss a helper's last lines (R-3, `6299fdd`).
- [x] Roots-table reads raised raw SQLite errors and failed a listing (R-4, `af632a3`).
- [x] A store that couldn't be opened was reported as "Mount information is unavailable"; it now
  says "Disk cache could not be opened: …" once (R-5, `2447a66`).
- [x] A pending root location stayed pending after its duplicate was forgotten (R-6, `d586f9d`).
- [x] A status check or details scan finding a folder's signature changed cancelled its running
  load, Live check and cached read ("Cancelled — Retry", Live halted) (R-7, `2559c77`).
- [x] A crashing helper left no cause in the log; its stderr's last 2 KB are logged now (R-8,
  `34bcb78`).
- [x] An unhandled exception (in a slot or a model's `data()`) ended HeLab, with no log file for
  the packaged app; source timestamps were unguarded (R-11, `e4d3f2d`, `1efcb87`).
- [x] The window icon was looked up from the launch folder (R-12, `fbb072f`; the packaged app's
  copy is open, above).
- [x] The manual marker's Save to folder… wrote on the GUI thread (R-16, `c4cf63c`).
- [x] A script hook that raised when its plot opened ended HeLab (R-17, `c530e7f`).
- [x] `tests/test_settings_defaults.py` failed 3 tests run in one process after
  `test_settingsDialog.py`: QtWebEngineWidgets must be imported before the QApplication
  (`22ee3fb`).

Landed in `dev/v0.0.6` from the CI Robustness floor (merges `51c0ee2`, `23e922f`, 2026-10-22);
the commits are on `agent/ci-robustness-2` ([handoff](../.ai/sessions/2026-10-22-claude-ci-robustness-2/handoff.md)):

- [x] `test_live_plots.py::…[Matplotlib-TransferFractions]` worker crash: a QWebEngineView left
  to `deleteLater()` was deleted in a later test or at exit. Fixed in that file by `e492409`
  (no crash in 33 CI jobs since, 9 before); every test is protected now: deferred deletes after
  each test, also when teardown raises, and a test leaving a web view fails (`f9d4a88`, `2fc4dee`,
  `5e696aa`).
- [x] `test_cache_tab.py::test_saves_restored_from_the_store_ask_with_its_numbers` after the
  io-trace test: one store per worker; now a store per test (`c21d5b8`).
- [x] Main-window tests and the default data path: patched in conftest since `d2833f1`; now a
  test guards it (`c21d5b8`).
- [x] `test_window_resize.py::test_label_keeps_painting_after_resize`: a paint still pending for
  the last tick came first (`ebdc33f`).
- [x] `test_dash_server.py::test_stop_frees_the_port`: TIME_WAIT after the server closed
  connections, and a probe without SO_REUSEADDR; it uses a port of its own (`45e5b14`).
- [x] `test_gui_responsiveness.py::test_output_close_failure_cannot_leave_dead_helper_in_active_queue`:
  the log came after the exit it waited for (`c472031`; shown with a delayed call, not on RSPE).

Landed in `dev/v0.0.6` with TonyXTYan/HeLab#7 (squash `17f7bcb`, 2026-10-21); the commits named
are on its branch, `agent/ci-robustness`, unless said
([notes](../.ai/sessions/2026-10-21-claude-ci-robustness/notes.md)):

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
