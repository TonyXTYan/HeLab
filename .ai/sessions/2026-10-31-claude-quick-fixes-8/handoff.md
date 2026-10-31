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
