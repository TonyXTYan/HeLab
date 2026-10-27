# Quick fixes, batch 3 — notes (Shim, 2026-10-27)

Branch `agent/quick-fixes-3`, base `450b6ec`. Brief: [brief.md](brief.md).

## Job: `test_store_identity.py::test_a_store_in_the_folder_whatever_its_age_ends_quit` times out at `-n 12`

### Cause

`store_free()` (`tests/conftest.py`) never became true, because the **app-wide IOService was
shut down and still counted as busy**:

- Any test that closes a real `HelabMainWindow` shuts the app-wide service down
  (`HelabMainWindow.closeEvent` → `get_io_service().shutdown()`; also `test_presets_plots.py`'s
  restart, `test_gui_responsiveness.py`, conftest's `no_quitting_cache`).
- `shutdown()` cancels what is running (the window's startup presets read and cache sweep, both
  `cache_admin`): `_retire` moves them to `retired` and starts the reaper, which kills, waits and
  sets `request.exited` within milliseconds. But `shutdown()` also stops the timer, so `_tick`
  never runs `_forget`, and the requests stay in `retired` for good.
- `io_service._service` keeps the closed service until something calls `get_io_service()` again
  (only then is a new one made).
- `cache_busy()` counted every retired request that uses the cache, **exited or not**. So every
  later `store_free()` on that worker was False until some test happened to call
  `get_io_service()`, and a test waiting for it timed out on every attempt (all 6 in Ground's run).
- Whether the identity test ran in such a window depends on how xdist spreads the tests over
  workers: `-n 12` hit it in 2 of 3 Ground runs, `-n 4` (floor runs, CI) didn't.

It wasn't the other suspects: the app-wide service wasn't busy with another test's live work, and
helpers' exits *were* confirmed (`exited` set); only the slot bookkeeping, which a closed service
never updates, still held them.

### Evidence

- Diagnostics added to the test (temporary): at the timeout, `presets_read=True jobs={}`, the
  test's own service `busy=False`, the app-wide service `busy=True` with one request:
  `retired cache_admin presets lane=local uses_cache=True age=30.0 poll=-9 exited=True
  cancelled=True reason='cancelled'` — so the third part of the wait was the false one, held by a
  helper killed (−9) and reaped 30 s earlier.
- Deterministic repro (temporary scratch test, not committed): make the app-wide service read
  presets, shut it down while the helper runs, wait for `exited`; then
  `test_a_store_in_the_folder_whatever_its_age_ends_quit` fails in 30 s every time. With the fix,
  both pass in 0.5 s.
- A full run at `-n 12 --reruns 0 -p no:randomly` with a temporary teardown probe ("app-wide
  service closed and `cache_busy()`"): **1,112 tests** ran in that state, the windows starting at
  tests that close a main window (`test_analysis_gui.py::test_closing_the_main_window_ends_its_plots`,
  `test_helabMainWindow.py`, `test_plot_settings_panel.py`, `test_settings_defaults.py`,
  `test_test_isolation.py`, …); every stuck request was `exited=True`
  (`('cache_admin', 'presets', True), ('cache_admin', 'sweep', True)`). `test_store_identity.py`'s
  other tests ran inside such a window on one worker in that run; the target test didn't, and
  passed.

### Fix (`12338a3`)

- `helab/utils/io_service.py`, `IOService.cache_busy()`: counts a request only while
  `request.exited` isn't set (set by `_reap` after `process.wait()`, or by `_run` when no process
  started). A helper still running or not yet reaped still counts, so `store_free` keeps
  `5607182`'s rule (no store deleted before every helper's exit is confirmed). It can't promise
  more than that rule did: on a Windows venv install the process waited for can be the
  `python.exe` redirector, whose interpreter child may hold store files a moment after the parent
  exits (already listed in known-issues, "Windows cache moves on a venv install"; Feeler's review,
  P2). In the app, the
  cache mover's wait (`CacheMover._start_when_stopped`) may go on up to one timer tick sooner, once
  the process has been waited for; slots are still freed only by `_forget`, unchanged.
- `tests/test_cache_mover.py::test_a_closed_service_is_free_once_its_helpers_have_exited`: a shut
  down service whose helper exited is free (fails before the fix).
- `tests/test_result_cache_quit.py::test_a_store_is_free_only_once_the_app_wide_services_helpers_have_exited`
  now holds back the exit confirmation itself (`_reap`) instead of `_forget`, which no longer
  decides "free".
- Other `store_free` users (`test_presets_store.py:524`, `test_result_cache_quit.py:151/193`) had
  the same exposure; the one fix covers them.

Alternatives not taken: clearing the closed service from `store_free` (would drop the Windows
protection for a closed service's still-running helpers), or making `get_io_service` / a fixture
replace a closed service (hides the wrong answer `cache_busy()` gives rather than fixing it, and
would forget helpers still running against the store).

### Checks

At `12338a3`, macOS, `--basetemp=.ai/temp/pytest`:
- Full suite `-n 12 --reruns 5 --reruns-delay 1`, three times: 4465 passed, 2 skipped each
  (94 s, 64 s, 71 s), **no RERUN**.
- Full suite `-n 4 --reruns 5 --reruns-delay 1`: 4465 passed, 2 skipped (108 s), **no RERUN**.
- `tests/test_store_identity.py` alone, 10 times (`-p no:xdist`): 1576 passed each.
- `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests`: clean.
- The new `test_cache_mover.py` test fails at `450b6ec` (closed service still `cache_busy()`).

### Proposed `roadmaps/known-issues.md` line (move to Fixed)

- [x] `test_store_identity.py::test_a_store_in_the_folder_whatever_its_age_ends_quit` timed out
  on every attempt at `-n 12` (2026-10-26): a test closing a real main window shuts down the
  app-wide IOService, whose stopped timer never frees its retired helpers' slots, and
  `cache_busy()` counted them though their exit was confirmed, so `store_free()` stayed False for
  the rest of that worker's run. `cache_busy()` now goes by the reaper's `exited` flag
  (`agent/quick-fixes-3` `12338a3`, 2026-10-27).

### Proposed follow-up line (open, Tests and CI; Feeler's review, P3; not fixed here)

- [ ] A test that closes a real main window leaves the app-wide IOService closed in
  `io_service._service`, its retired requests never forgotten (timer stopped), until the next
  `get_io_service()` replaces it; and a live app-wide service (and its FolderCache) lasts the
  worker's run, so its timers and helpers can work against later tests' private stores. Tests
  should start each with a fresh or quiesced app-wide service, but a closed one must not simply be
  reset: wait for its old helpers' exits first (`cache_busy()`), or their store may still be open
  (found by `agent/quick-fixes-3`, 2026-10-27).
