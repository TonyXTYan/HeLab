# CI robustness 2: notes (2026-10-22)

Branch `agent/ci-robustness-2` from `fc0f50d`, floor "CI Robustness". Worker: Claude (Opus 5.5).

## CI evidence

I downloaded the Tests job logs of 32 runs (96 jobs: `dev/v0.0.6` since 2026-10-20, `agent/dld-front-panel-port`,
`agent/refactor-*`, `agent/ci-robustness`, `agent/post-merge-docs`), using
`gh api repos/TonyXTYan/HeLab/actions/jobs/<id>/logs`. `gh run view --log` returns nothing for runs with
skipped jobs. I grepped them for `RERUN`, `Fatal Python error`, `fatal exception` and `crashed`.

**Timing lesson.** pytest-rerunfailures sleeps `--reruns-delay` (5 s on CI) *before* it logs `RERUN`
(`pytest_rerunfailures.py:1300-1305`). So the gap between a test's start line and its RERUN line is
5 s plus how long the test ran. Read naively, the window-resize reruns looked like 5 s timeouts. They
were failures within about 0.5 s. A teardown failure shows as `PASSED` (the call phase) followed by
`RERUN` 5 s later. A crashed worker's test shows `RERUN` on one worker with no delay and its rerun on
another.

CI's `-rR` names rerun tests but not why they failed, so there were no tracebacks. Commit `315273d`
adds a `rerun reasons` section (the `E` lines and the failing `file.py:N` line).

## Per item

### A1: Matplotlib-TransferFractions segfault
- CI: 9 crashed jobs, all on 2026-10-20 runs before `e492409` ("Delete live-plot test windows at
  teardown", which landed in dev with #6). None in the 33 jobs since (dev, agent/dld after
  `e492409`, refactor branches, ci-robustness, post-merge-docs). The main thread's frame was
  `<invalid frame>`, and Qt printed "Release of profile requested but WebEnginePage still not deleted".
- Cause: pytest-qt (`_close_widgets`) and the fixtures only `deleteLater()` widgets, so the deletion
  happens in a later test's event loop or at exit. A QWebEngineView outliving its test that way
  crashes Qt.
- Local reproduction (macOS): a copy of `test_live_plots.py` without e492409's three
  `sendPostedEvents` lines, `-k following_plot_keeps_following`, 6 runs at once: 4 of 6 segfaulted
  and the others printed the WebEngine warning. With the conftest hook (below): 0 of 6, with no
  warning. The current file alone: 0 of 3.
- Probe: after every test of the full suite (2372 tests), I counted live QWebEngineViews: none.
- Fix `f9d4a88`: conftest's `pytest_runtest_teardown` wrapper sends DeferredDelete after every test.
  A web view still alive after that fails the test. Tested in `tests/test_left_widgets.py`.

### A2: cache-tab test after the io-trace test
- Reproduced every time: `pytest test_io_trace.py::test_a_live_save_keeps_dont_cache_and_the_budget
  test_cache_tab.py::test_saves_restored_from_the_store_ask_with_its_numbers` (one process) fails
  with "Not enough room in the disk cache for run…" instead of "a changed: save the update…".
- Cause: each worker shared one store, and the Live save's pending save was restored by the later
  test's inventory.
- Fix `c21d5b8`: the `private_store` fixture gives each test a fresh store under the basetemp
  (`set_cache_dir`, the helpers' `HELAB_DIR_CACHES_OVERRIDE`, `constants._dir_caches_override`).
  With it, `temporary_data_root`'s cleanup that forgot roots and `default_budget_is_newest` were
  removed. The full suite's time didn't change (about 35 s with `-n 8` here).

### A3: default data path
- conftest has patched `FolderTabWidget.DEFAULT_DATA_PATH` / `DEV_POTENTIAL_DATA_PATHS` to an
  empty temp folder since `d2833f1` (2026-10-20), so the known issue was already fixed in code.
  What was missing was a test that it can't leak.
- `tests/test_test_isolation.py`: a real `HelabMainWindow`'s tabs start in `START_FOLDER`. Only
  `constants`, `FolderTabWidget` and `io_ops.infra` read the default paths (an AST scan), so a new
  reader would be caught. I checked the test fails with the patch removed:
  `'/Volumes/dld_output' == '/var/folders/…'`.

### A4: window resize painting
- CI: 12 reruns (macOS, Ubuntu), all at 98–99 %, each right after `test_versioning.py` on its worker.
  The sibling label test on another worker passed at the same moment. After subtracting the rerun
  delay, every failure came within about 0–0.6 s of the start.
- Things I tried first: 3 full CI-command runs (`--cov`, `--timeout-method=thread`, -n 4, 12 burners):
  clean. Per-test probes over the whole suite of threads, top-level widgets, running analysis jobs
  and first-paint latency: nothing accumulates, and first paint after any test is ≤ 0.25 s.
  `taskpolicy -b` starved the processes completely (0 % CPU), so it was useless.
- Cause: after the resize the test waited for *any* paint, then asserted a new timer tick. A tick
  whose timer fired in `qWait(250)`'s last pass has its paint still pending (offscreen's dispatcher
  sends posted events before it activates timers). That paint came first, with no new tick, so the
  assert failed. The recursive-scan tests in the same file check paint and beats in one
  `waitUntil` and never flaked.
- Reproduction: making that pending paint certain (one tick right after the resize), the old logic
  failed 19/20 and 20/20, the new 0/40.
- Fix `ebdc33f`: `TickPaints` records the tick each paint shows, and the test waits for a paint of
  a newer tick, twice. It still fails (2 s timeout) when updates are disabled on resize and never
  restored. Under 8 burners: 240/240.

### A5: Dash port
- Cause: when the server closes a connection first, its side stays in TIME_WAIT for about 60 s. A
  plain `bind` (no SO_REUSEADDR) is refused then, although `DashServer._bind` (SO_REUSEADDR off
  Windows) would get the port. `test_serves_added_plot`, run just before, makes such connections
  on 8050. On macOS urllib usually closes first, so the TIME_WAIT is client-side and it passes.
  On Linux the server closes first, which explains the reruns "even alone" on Ubuntu.
- Shown on macOS with a raw client that waits for the server to close: plain bind `[Errno 48]`,
  SO_REUSEADDR bind ok. The old probe failed 5/5, the new check 0/5.
- Fix `45e5b14`: the test uses a free port of its own, makes a server-closed connection, stops,
  and a second `DashServer` must get the same port. It fails if `stop()` leaves the server
  listening (`assert 49786 == 49784`). 8 loops × 15 runs: 120/120.
- Not done: tests other than this one still prefer 8050 and fall back by design. A conftest patch
  of `DashServer.HOST_PORT = 0` would keep suites off 8050 entirely, but it imports Dash in every
  worker; I left it.

### A6
- `test_activation_sources`: the Windows CI rerun was A1's crash (gw4 "Windows fatal exception:
  access violation" during it, run 39377080659, before `e492409`). The macOS rerun (run
  39531406589, `f9faefd`) was a **teardown** failure: the call passed at 08.92 and RERUN came at
  13.93. There's no traceback, and 160 file runs under 8 burners passed. **Open**: the next CI
  rerun's `rerun reasons` will say what fails. My guess is pytest-qt's teardown capture of an
  exception raised in a Qt slot while the plot area (with a web view and a floating dock) is deleted.
- `test_output_close_failure_cannot_leave_dead_helper_in_active_queue`: no RSPE output survives.
  Race found by reading the code: `IOService._run` sends `exit`, then closes the output and logs
  "Could not close I/O helper output". The test asserted the log right after waiting for both
  scans, and the second scan can finish first. With the close delayed 0.3 s: old 5/5 fail, new 0/5.
  Fix `c472031` waits for the log in the same condition, 10 s. Likely the RSPE cause; not confirmed
  there.

## B1: pytest.ini
- Before: with a copy of helab first on `PYTHONPATH`, `helab.__file__` was the copy (the console
  script puts `venv/bin` first, and conftest's prepend adds `tests/`, not the root).
- `pytest.ini` with `pythonpath = .` (`50fa36b`); checked from the root, from `tests/` and with
  `python -m pytest`.
- Nothing else reads it: coverage reads `.coveragerc`, `setup.cfg`, `tox.ini` and `pyproject.toml`;
  `HeLab.spec` and `setup.py` don't read it; CI's commands are unchanged.
- Bare `pytest` still collects `side_projects/rga_visualiser/test_*.py` (as before).

## B2: settings defaults
- `helab/utils/settings_defaults.py` (`0f4df65`); details in the handoff.
- Found: PyQt6 `QSettings.value(k, 8 << 30, type=int)` → 0 (a 32-bit int), saved or default. Never
  hit, because HeLab reads the budget untyped. `read_setting(typed=True)` now refuses number rows.

## Floor observations
- This floor's copied `__pycache__` folders held Ground's paths: a traceback showed
  `../../../HeLab/tests/test_cache_tab.py`. I deleted them (outside `venv/` and `legacy/`). The venv
  itself was the floor's own (editable install → the floor).
- `cov.syspath.txt` at the repo root is tracked in Git. It looks like a stray debug file.

## Stress totals (local, macOS M-series, 16 cores)
- Fixed files together (`test_live_plots`, `test_cache_tab`, `test_io_trace`, `test_window_resize`,
  `test_dash_server`, `test_plot_settings_panel`, `test_gui_responsiveness`, `test_test_isolation`,
  `test_left_widgets`, `test_settings_defaults`): 10 runs × `-n 8`, `--reruns 0`, 8 CPU burners:
  2890/2890 passed, no crash.
- Full suite `-n 4 --reruns 5 --reruns-delay 1` (with `test_typing`): 2394 passed, 2 skipped,
  2 xfailed, **no RERUN**.
