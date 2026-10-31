# QF8 handoff (Rivet → CoCo)

The "Now" items are done, one commit each on Ground's `dev/v0.0.8`. Details are in [notes.md](notes.md).

| Item | Commit | Files |
|---|---|---|
| convert-1 `--watch --again` | f592519 | `convert_cli.py`, `test_convert_helab.py` (+ this brief) |
| app-1 Reset and the TXY converter tab | 2f8b2f1 | `ConverterTab.py`, `SettingsDialog.py`, `HelabMainWindow.py`, `test_helabMainWindow.py` |
| app-2 split widths | c4e5b25, a0c630c (after CI) | `HelabMainWindow.py`, `test_main_split.py` |
| A39.3 one running HeLab | 0335768 | `main.py`, `cache_locks.py` (the lock only), `test_one_running.py` |
| A39.1 archive check on PR builds | c201c01 | `ci-build.yml`, `release_draft.py`, `test_release_recovery.py` |

- No floor's paths were touched. `HelabMainWindow.py`, `SettingsDialog.py` and `ConverterTab.py` are on
  no floor's list.
- "Later" (convert-2, A39.4) is not started: it waits for I/O Fixes to land.
- Suite before the push: 8529 passed, 672 skipped, no RERUN. The five type checks all pass. CI results
  are below.

## What only served several instances at once (A39.3: listed, not removed)

With one app per computer, the only other process sharing the app folder and store is `helab convert`
(Q~2).

- **cache-3** (area review): pending saves have no owner, so one window could ask about another running
  HeLab's save.
  - Now the only other owner would be `helab convert`, which holds no pending saves.
  - `FolderCache.restore_pending`'s "from an earlier session" now holds. The store-v4 owner field the
    review proposed isn't needed for this.
- **plots-2**: two HeLabs overwrote each other's `OPEN_PLOTS_SETTING` ("plots open at quit"), and the
  second start reopened the first's plots.
  - The race is gone with one app. `PlotReopen.record`/`restore`/`quit` need no change.
- **`cache_locks.lock_for_move`'s "Another HeLab is running (N windows)."**
  - Only `helab convert` processes can be counted now, so "windows" is wrong.
  - Proposed wording: "A HeLab converter (helab convert) is running (N). Stop it before moving the cache."
    It is user-visible text, so it is Tony's call.
- **These stay, because `helab convert` still runs beside the app:**
  - `instances/<pid>.lock` and `other_instances`: the cache move refuses while a converter runs, and the
    log tidy keeps its log;
  - `startup`'s wait for another process's cache move;
  - `convert_cli._start_cache`.
- **Could go:** "Another HeLab may have changed them" in `PresetsInspector.py:207` and
  `views/plots/presets.py:267, :613`, before `read_presets()`.
  - `helab convert` writes no presets, so these re-reads now only cover a store changed outside HeLab.
  - They are cheap, so I'd keep them and drop the comment's reason.
- **Keep:**
  - `dash_server.py:132`: any free port when HOST_PORT is taken. Any program can hold the port.
  - The `set_at` "later choice" guards in `cache_store.py` and `folder_cache.py` (another HeLab's clock).
    They also order a choice against a running save in the same app.

## Questions for Tony (provisional)

- **Q~1 (app-1) Work Offline and Reset all settings.**
  - Reset clears `work_offline`, but the session stays offline with File › Work Offline checked. After
    Reset then Save, or Reset then Cancel, the next start is online.
  - Options: (a) Reset keeps Work Offline, like the cache folder's location, and the confirmation says
    so; (b) Reset turns Work Offline off at once; (c) leave it as it is.
  - Proposed: (a). Work Offline is a mode the user turns on for a reason (no network), not a preference
    to forget.
- **Q~2 (A39.3) Does `helab convert` count as a running HeLab?**
  - Today a second app refuses to start, but `helab convert --watch` may run beside the app, as before.
    It registers in `instances/` so a cache move waits for it.
  - Proposed: yes, it may run beside the app. It is the lab's headless converter, and the app's own
    auto-convert and the CLI share the store and index safely already.
- **Q~3 (app-2) The plots' least width when saved widths don't fit: 240 px.**
  - 400 px would also narrow Q33.2's default 380/320 in a small window: Windows CI's splitter is 976 px,
    where the default leaves the plots 268 px.
  - Proposed: 240 for now, so the default holds wherever it ran. Raise it only if Tony wants small screens
    to favour the plots over the default panels.

## Manual checks (provisional)

- **M~1 (app-2):** on a laptop or lab PC, start HeLab with a split saved on a wide monitor, or quit at
  1500,600 and start with `--geometry 1600x900+0+0`.
  - The plots get at least 240 px and both panels look usable.
  - Quitting without dragging keeps the wide widths for the monitor.
- **M~2 (A39.3):** start the packaged app twice, on macOS (`open -n HeLab.app`, or the binary from a
  terminal) and on Windows.
  - The second shows "HeLab is already running…" and quits.
  - After quitting the first, or after killing it, a new start opens normally.

## Doc proposals (for CoCo to apply)

- **AGENTS.md**, Codebase rules → I/O and threads (or UI), one line: "One HeLab app per computer:
  `main()` takes `running.lock` in the app folder (`cache_locks.take_running`) before anything opens; a
  second start says so and exits 1 (Q39.1, A39.3). `helab convert` doesn't take it."
- **`.ai/architecture/cache-store.md`** (or wherever `cache_locks` is described): add `running.lock`
  beside `cache.lock`, `move.lock` and `instances/<pid>.lock`. It is held for the process's life and not
  released at quit.
- **`.ai/architecture/converter.md`**, "`helab convert --watch`":
  - `--again` converts each shot once more in `--watch` too: the pass after the recording pass;
  - drop "works with `--once` only", if the review's proposal was applied.
- **`.ai/architecture/app-runtime-and-ui.md`**, the main split (Q33.2):
  - saved widths that don't fit leave the plots `MIN_PLOTS_WIDTH` (400 px), with both panels narrowed
    in proportion;
  - a width the window narrowed isn't saved as the user's;
  - showing a panel again goes through the same fit.
- **`.ai/architecture/settings.md`**: Reset all settings reloads every tab, the TXY converter included.
  The main window re-applies the conversion profile, the tabs' TXY source and result reuse after the
  dialog closes, whether by Save or Cancel.
- **`.ai/architecture/release-and-ci.md`**: each Python 3.13 build checks its own archive
  (`release_draft --check`) against its build commit, without a tag or draft. Recovery builds of an older
  tag are left to the release job.
- **`roadmaps/known-issues.md`**, Fixed:
  - convert-1 (f592519)
  - app-1 (2f8b2f1, except Q~1)
  - app-2 (c4e5b25)
  - 0.0.7a1's macOS linked stamp: now caught on the PR (c201c01)
- **`.ai/AI_TODO.md`**: A39.1 and A39.3 done.

## CI

### Run 41158349537 (`1f0c4fe`): failure, every Tests, Converter and Build job log read

- **windows Tests (1/2)** (job 124410096439): 2 failed, 4239 passed, 10 reruns. Both failures are mine
  (app-2, c4e5b25), and each test failed all 5 of its reruns.
  - `test_main_split.py::test_the_default_split_gives_the_plots_the_room_and_a_plot_keeps_it`:
    `assert (313 == 380)`.
  - `test_main_split.py::test_widths_saved_on_a_wider_screen_leave_the_plots_room_and_stay_saved`:
    `[411, 307, 250]`, `307 >= 392`.
  - Cause and fix: a0c630c, below.
- **windows Tests (2/2)** (124410096333): 4253 passed, **2 RERUN**:
  `test_io_service_run.py::test_writing_held_data_out_counts_as_progress` (`assert (2 == 1)`, at
  `test_io_service_run.py:40`, twice). Already in known-issues (line 133).
- **macos Tests (2/2)** (124410096404): 4271 passed, **1 RERUN**:
  `test_live_convert.py::test_a_converted_shot_asks_for_lives_next_check`
  (`AssertionError: assert ('' == 'check'` at `tests/test_live_convert.py:231`, `session.request` empty
  where "check" was queued with the conversion).
  - Not in known-issues. It is Live code, which this round didn't touch, and it is in the I/O Fixes
    floor's paths (`explorer_live.py`, `io_ops/live.py`).
  - Proposed known-issues line: "`test_live_convert.py::test_a_converted_shot_asks_for_lives_next_check`:
    `session.request` was '' rather than 'check' at :231, the check expected queued with the conversion
    (macOS CI 41158349537, gw3; passed on rerun). Cause not looked into."
- **No RERUN:** ubuntu Tests 1/2 (4255 passed) and 2/2 (4271), macos Tests 1/2 (4258), and all three
  Converter backends jobs (713 / 715 / 715).
- **A39.1 ran on all three builds and passed:** "HeLab-macos.zip / HeLab-windows.zip / HeLab-ubuntu.zip:
  built cleanly from 0.0.7a1 at 1f0c4fe175a9…".

### a0c630c: the app-2 follow-up

- **Default split.** A 400 px floor narrowed the default 380/320 in Windows CI's 976 px splitter.
  `MIN_PLOTS_WIDTH` is now 240, below the 268 px the default leaves there.
- **Floor.** A panel raised to its least width wasn't taken off the other. `HelabMainWindow.fitted` now
  keeps each panel's least width and shares the room above them in proportion.
- **Collapse.** Running the window test at 1300 px here (a 976 px splitter) also showed that collapsing
  the settings panel set the plots to `width - left_panel_width`. That is negative once the folders are
  narrowed, so the folders took the window and that width was saved. The collapse now gives the panel's
  width to the plots and leaves the folders as shown.
- **Tests.** Seven `fitted` cases, CI's 976 px among them, and the window test at 1600 and 1300 px. The
  1300 case fails on c4e5b25.
- **Suite.** 8537 passed, 672 skipped, no RERUN. The five type checks pass.

### Run 41160032390 (`903f2b6`): success, every Tests, Converter and Build job log read

- **windows Tests (1/2)** (job 124415375251): 4243 passed, **1 RERUN**:
  `test_one_running.py::test_the_running_lock_is_held_by_one_process_and_freed_when_it_ends`
  (`assert (None is not None)` at :50, my new test). Cause:
  - it waited with `free_soon(lambda: take_running(app))`, but `take_running` returns a tuple, and
    `(None, "")` is truthy;
  - so it never waited out Windows' late release of a killed process's lock, which is the case
    `free_soon` exists for (POSIX releases at once, so macOS can't show it).
  - Fixed in the local commit below: the test waits on the lock itself and unlocks the override folder's
    lock it took. Passed 5 of 5 here.
- **No RERUN:** windows Tests 2/2 (4259 passed), macos Tests 1/2 (4260) and 2/2 (4277), ubuntu Tests
  1/2 (4257) and 2/2 (4278), and all three Converter backends jobs (715 / 713 / 715).
- **A39.1 again passed on all three builds:** "built cleanly from 0.0.7a1 at 903f2b6158…".
- **Run 1's RERUNs did not recur:** the `test_io_service_run` one (known) and the `test_live_convert` one
  (new, proposed above).
- The test fix and this record were held back at first, then pushed on CoCo's word as f128623.

### Run 41161254527 (`f128623`): failure, every Tests, Converter and Build job log read

- **windows Tests (1/2)** (job 124419124662): 1 failed, 4242 passed, 5 RERUN, all of them
  `test_main_split.py::test_widths_saved_on_a_wider_screen_leave_the_plots_room_and_stay_saved[1300]`
  (gw3): `[165, 232, 271]`, `assert 165 > 271` at :203, on all 6 tries. Conduit saw the same on
  41161048586. Cause, repro and fix: below.
- **windows Tests (2/2)** (124419124616): 4259 passed, **1 RERUN**:
  `test_root_gui.py::test_the_gui_never_writes_the_saved_file_itself`.
  - The gw2 worker crashed in it ("node down: Not properly terminated", a stack at
    `test_root_gui.py:449`), and the test passed on gw4.
  - This is known-issues line 169's crashed worker: another sighting, at CI 41161254527.
- **No RERUN:** windows Converter (713 passed), macos Tests 1/2 (4260) and 2/2 (4277), ubuntu Tests 1/2
  (4257) and 2/2 (4278), and macos and ubuntu Converter (715 / 715).
- **A39.1 passed on all three builds:** "built cleanly from 0.0.7a1 at f12862359c…".

### The cause: the split test's window depended on the worker's history (279fc8b, 04a667a)

- **What varied.** The same `resize(1300, 900)` gave a 976 px splitter on Windows in 41160032390 and
  676 px in 41161254527. The test's tests ran in the same order on their worker both times; the earlier
  files on the worker differed (xdist's scheduling).
- **Why that matters.** Without `IconsInitUtil.initialise_icons()` (`main.py` calls it before the
  window), each side toolbar's buttons show their text, so the toolbars are as wide as "Toggle Folder
  Details" and "Toggle Right Bottom Panel" in the system font.
  - Here: 142 + 173 = 315 px of a 1300 px window.
  - On Windows CI: about 624 px, since 1300 → 676 and 1600 → 976.
  - With the icons: 72 px, so a 1228 px splitter here.
- **Why it varied per run.** The icons are class attributes. Once any test in a worker sets them up
  (`test_load_queue.py:309`, `test_accessible_names.py:484`, three tests in `test_folder_summary.py`),
  they stay set for that worker's later tests, and xdist hands those tests to a different worker each run.
- **Repro (macOS).**
  - f128623's test at a 1000 px window (a 676 px splitter without icons, like Windows' 1300) fails with
    `[172, 232, 273]`, `172 > 273`.
  - With `initialise_icons()` first it passes.
  - Probe: a 1300 px window gives a splitter of 985 without icons and 1228 with them.
- **The app was right.** `fitted(1500, 600, 676)` is (165, 271): both panels sit near their least
  widths (80, 250) and share the 106 px above them. The test's "folders wider than settings" and
  "narrow the folders by 100" were wrong for such a splitter.
- **Fixes.**
  - 279fc8b: the window test checks the panels equal `fitted(1500, 600, splitter width)` and the plots
    keep the floor, naming the splitter, window and toolbar widths on failure; the user widens the
    folders instead; a 1000 px case is added.
  - 04a667a: `test_main_split.py` sets the icons up for every test (autouse), as `main.py` does, so its
    windows no longer depend on the worker; the `fitted` table gains CI's exact 676 px case.
- **Suite.** 8539 passed, 672 skipped, no RERUN. The five type checks pass.
- **Proposed** (A~, not done here): other tests that open a `HelabMainWindow` and depend on its widths
  carry the same hidden dependence. A conftest autouse `initialise_icons()` would remove it everywhere;
  it is outside this brief's files.

### Run 41163140243 (`0a1e799`): success, all 12 job logs read (four fetched again after API drops)

- **No RERUN in any job.** Tests passed: windows 1/2 4246, 2/2 4258; macos 4263, 4276; ubuntu 4259,
  4276. Converter backends 713 / 715 / 715.
- On Windows the fixed tests passed: `test_main_split`'s window test [1600], [1300] and [1000], the
  default split, and `test_one_running`'s lock test.
- **A39.1 passed on all three builds:** "built cleanly from 0.0.7a1 at 0a1e799126…".

### e8e7ebc: test_cache_mover's startup test waits for the move lock itself (CoCo, from IO Fixes' CI)

- **The RERUN.** CI 41162160704 (I/O Fixes), windows Tests 1/2:
  `test_cache_mover.py::test_startup_waits_out_a_move_then_recovers_and_registers`,
  `[True, True, True] == [True]` at :198.
- **Cause.** The same as f128623's. `wait()` killed the helper holding `move.lock` and returned at once.
  Windows frees a killed process's locks a little later, so `startup` found the lock still held and
  called `wait()` again.
- **Fix.** `wait()` now also waits (`free_soon`) until the move lock is free.
- **Repro (macOS, scratch).** A helper that forks a child sharing its locked file, the child living
  0.3 s longer, so the lock is freed late as on Windows:
  - the old test records 3541 waits;
  - with the fix it passes 3 of 3.
- **Checks.** The file's 22 tests pass, three runs. The cause is the one CoCo named, so no known-issues
  line is needed.

### Run 41164525298 (`82c9db3`): failure, every Tests, Converter and Build job log read

- **windows Tests (1/2)** (job 124429158185): 1 failed, 4246 passed, 7 RERUN.
  - **Mine (04a667a):** `test_main_split.py::test_widths_that_dont_fit_are_shared_above_each_panels_least_width[0-600-976-expected5]`,
    5 RERUN and FAILED. Six workers crashed in it (gw3 to gw8, "node down: Not properly terminated").
    - Cause: the autouse `icons` fixture made QIcons before any QApplication existed. gw3 had run only
      converter tests, and this pure test was its first Qt one, so the process aborted. Each replacement
      worker got the same test first and crashed the same way.
    - Repro: that test alone in a fresh process (`-p no:xdist`) exits 134.
    - Fix: 1f86ca2. The fixture takes pytest-qt's `qapp`, and each of the 8 `fitted` cases now passes
      alone.
    - Suite 8539 passed, no RERUN; the five type checks pass.
  - `test_gui_responsiveness.py::test_timeout_retry_releases_dead_helper_slot_while_artifact_reader_is_blocked[2]`:
    1 RERUN, `waitUntil timed out in 3000 milliseconds` at :292. Already in known-issues (line 121).
  - **New:** `test_folder_icons.py::test_native_icon_delivery_is_shared_and_rendering_stays_memory_only`,
    1 RERUN on gw0: "Painting an icon performed I/O or submitted work", then pytestqt "Failed to process
    thread exception".
    - gw0 hadn't run `test_main_split`, so it isn't the icons fixture.
    - The test patches `os.stat` and `os.scandir` process-wide, so likely another thread in the worker
      stat'ed meanwhile.
    - Proposed known-issues line: "`test_folder_icons.py::test_native_icon_delivery_is_shared_and_rendering_stays_memory_only`:
      'Painting an icon performed I/O or submitted work' raised on another thread (pytestqt 'Failed to
      process thread exception'; Windows CI 41164525298, gw0; passed on rerun). It patches os.stat and
      os.scandir for the whole process; a check limited to the GUI thread would tell painting's I/O
      from another thread's."
- **No RERUN:** windows Tests 2/2 (4258), macos 1/2 (4263) and 2/2 (4276), ubuntu 1/2 (4259) and 2/2
  (4277), and all three Converter backends jobs (715 / 713 / 715).
- **A39.1 passed on all three builds:** "built cleanly at 82c9db3b77…".

### Run 41165963510 (`a64013b`, with 1f86ca2): success, all 12 job logs read

- **No RERUN and no crashed worker in any job.**
  - Tests passed: windows 1/2 4246, 2/2 4258; macos 4263, 4276; ubuntu 4260, 4277.
  - Converter backends: 713 / 715 / 715.
- **A39.1 passed on all three builds:** "built cleanly from 0.0.7a1 at a64013be9c…".
- This record is committed locally only (doc-only: no push, so no CI run).
