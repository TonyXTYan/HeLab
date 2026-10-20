# Refactor handoff (2026-10-20, overnight run)

This was an unsupervised run on the defaults Tony chose
([readiness](readiness.md#tonys-answers-2026-10-20)). Nothing is merged into
`dev/v0.0.6` and no PR is open. All branches are pushed to `TonyXTYan/HeLab`.

Each slice went through the same steps before its push:
- the full suite, with strict mypy and pyright, ran on the slice;
- a separate reviewer subagent read the diff (most compared every moved
  definition by AST with the original);
- the slice was pushed only after the review's findings were fixed.

Behaviour is meant to be unchanged throughout: the same wording, timing,
settings keys, cache format and helper protocol.

## How to land

**Recommended:** review and land **`agent/refactor-integration`**. It holds all
five branches, merged in order:

1. `agent/refactor-prep`
2. `agent/refactor-basic-plots`
3. `agent/refactor-io`
4. `agent/refactor-plot-ui`
5. `agent/refactor-explorer`

It also holds the conflict resolutions and one cross-track fix (below).
It passed the full suite with no reruns. It forks from `dev/v0.0.6` at `e908430`,
so it merges into `dev/v0.0.6` without conflicts unless `dev/v0.0.6` has moved
since.

Landing the branches one by one also works. Land `agent/refactor-prep` first.
After that, expect these conflicts, all resolved in the integration branch:
- **`AGENTS.md`:** each track updated the paragraphs about the code it moved.
- **`tests/test_live_plots.py`, `tests/test_analysis_gui.py`,
  `tests/test_shot_trends.py`:** import lines.
- **`FolderExplorer.py` / `HelabMainWindow.py`:** import lines, plus the moved
  Live block.
- **`tests/test_headless_imports.py`:** a basic-plots + plot-ui pair also needs
  `orders` listed as pure and `overlay` as Qt (the cross-track fix).

## Branches

| Branch | Slices | Commits (oldest first) | Notes |
|---|---|---|---|
| `agent/refactor-prep` | readiness survey; root skips; A; lock | `97986eb` `913605a` `812baa8` `70402ce` `2f4e7d3` `9cf8782` `1429d43` + this handoff | [readiness](readiness.md), [brief](brief-common.md) |
| `agent/refactor-basic-plots` | D | `07738f1` `ea968ae` `5f4f7be` `bc88e77` | `basic-plots-notes.md` on that branch |
| `agent/refactor-io` | F, G | `a05d135` `a7029f1` `8ae9173` `22a2c93` | `io-notes.md` on that branch |
| `agent/refactor-plot-ui` | B, C, E | `49b197c` `31358e1` `01b3dc9` `c296d28` `ddc1c07` `a00b3e2` | `plot-ui-notes.md` on that branch |
| `agent/refactor-explorer` | H (Live part only) | `b511129` `b031ada` `fafec61` | `explorer-notes.md` on that branch |
| `agent/refactor-integration` | all of the above | merges + `orders`/`overlay` classification | this file |

## What changed

- **Prep:**
  - Root-only permission tests skip under root (cloud containers).
  - New guards:
    - `tests/test_helper_imports.py`: browsing in the helper imports no numpy,
      pandas, Blosc or Qt.
    - `tests/test_bundled_analyses.py`: every bundled analysis has a unique
      `analysis_id` and a `version`.
  - Dead code removed from `HelabMainWindow`.
  - **`requirements.lock`** (a universal lock for Python 3.13, 85 packages) is
    what CI's 3.13 jobs, the README, AGENTS.md and the Maestri setup install.
    The compatibility jobs stay unpinned.
  - `setup.py` lists the real runtime dependencies.
  - `requirements-pip.txt` is deleted.
- **D, Basic plots:**
  - Transfer fractions' order detection is now `helab/analysis/orders.py` (pure).
  - The newest-shot overlay helpers are now `helab/analysis/overlay.py`.
  - No Basic plots script imports another script any more.
  - DLD is untouched.
  - 240 random runs give field-for-field identical `Fractions` before and after.
- **F, I/O:** `helab/io_helper.py` went from 3209 lines to 141. It is now the
  process entry and dispatcher over **`helab/io_ops/`**, 15 modules by family:
  - `infra` holds all helper state, the trace and the test seams.
  - Names that tests patch are called as `module.name`.
  - The coordinator built the app with PyInstaller on Linux. All 15 modules are
    bundled, and the frozen helper listed, scanned and loaded TXY shots.
- **G, I/O:** `helab/io_ops/events.py` is a TypedDict contract for the
  helper's 66 event kinds, and mypy checks every send.
  `tests/test_helper_events.py` checks both sides: the kinds the helper sends,
  and the kinds the GUI matches against.
- **B, plot UI:** `helab/models/ScriptTreeSelector.py` became
  **`helab/views/plots/`**: `dock`, `pictures`, `instance`
  (`AnalysisInstance`), `script_tree` (`TreePanelWidget`) and
  `settings_panel`. `helab/models/__init__` no longer loads the whole plot UI.
- **C, plot UI:** a Qt-free analysis core:
  - `LiveFeed` moved to `live_feed.py`, so `follow.py` and
    `scripts/base.py` no longer load Qt.
  - `budget_core.py` holds the pure parts of the RAM budget.
  - `runner_core.AnalysisQueue` sits under the Qt `AnalysisRunner` adapter.
  - `tests/test_headless_imports.py` lists every `helab/analysis` module as
    pure or Qt.
- **E, plot UI:**
  - **`app_settings()`** (`helab/utils/settings_store.py`) is the only way
    helab opens the native settings. Tests get a private ini through
    `HELAB_TEST_SETTINGS_FILE`, which fixes the known issue that window tests
    read the developer's settings.
  - **`PlotWorkspace`** (`helab/views/plots/workspace.py`, the window's
    `plots`) owns the plot area. `AnalysisInstance` takes it instead of
    reaching into the window with `getattr`.
  - The test windows are plain `QMainWindow`s with a real workspace.
- **H-lite, explorer:**
  - Live moved to a **`LiveController`** (`helab/views/explorer_live.py`, the
    tab's `live_control`). The tab keeps thin delegates (`start_live`,
    `stop_live`, `live`, …).
  - The load-state dataclass was **left alone by decision**. About 550
    accesses would be renamed with no behaviour moved, and it would collide
    with E. Moving the load logic behind a controller later is the better step.

`HelabMainWindow` went from 1733 lines to 1486, and `FolderExplorer` from 2867
to 2378. `FolderCache` is unchanged (slice H was skipped beyond Live).

## Review findings worth knowing

- **Fixed:**
  - **C:** the runner and its core referenced each other, so an idle runner was
    freed only by the cyclic GC, possibly on another thread. Fixed in
    `c296d28`, with tests that fail on the old commit.
  - **F:** the import guard covered only browsing. It now covers the whole
    helper.
  - **Docs:** several notes and comments still named moved code.
- **Integration:** `orders` and `overlay` were unclassified in the headless
  import test. Each branch passed alone, but the merged tree failed until both
  were listed. Fixed on `agent/refactor-integration`.
- **Left as is (low):**
  - The Settings panel is created slightly earlier (no observable effect).
  - `AnalysisQueue` built directly would silently drop a callback that is a
    bound method of a temporary object. Only `AnalysisRunner` builds one today.
  - Three typing casts in `io_ops` trust shapes mypy can't check.
    `MoveCheckFields` must be kept in step with `cache_move.check_target`.
  - The AST checks in the new tests have known blind spots (aliased imports,
    kinds compared through named sets).
  - The `LiveController` asserts its tab is alive. That can't fail while Qt
    owns the tab.

## Validation

Local runs were on Linux, 4 cores, at `-n 2` to `-n 4` with
`--reruns 5 --reruns-delay 1`.

- **Every slice:** the full suite passed, with no reruns except the two
  listed below.
- **Integration tree** (all five branches): **2201 passed, 9 skipped,
  2 xfailed, no reruns**. Strict mypy and pyright run inside the suite.
- **Frozen app (Linux PyInstaller build of `agent/refactor-integration`):**
  - Every new module is in the bundle (`io_ops.*`, `views.plots.*`,
    `explorer_live`, `explorer_text`, `settings_store`, and the new
    `analysis` modules).
  - The GUI started offscreen with a private profile, loaded both script
    groups, ran for 25 s and closed its tabs cleanly when stopped. Its only
    ERROR line is `main.py`'s demo `logging.error("this is an error
    message")`, which predates this work.
  - The frozen helper loaded 3 TXY shots through to `loaded` and `done`.
- **Reruns seen:**
  - `test_dash_server.py::test_stop_frees_the_port` once, during C, while three
    suites ran at once and competed for port 8050.
  - One unnamed rerun in a reviewer's targeted run on E; four later runs of the
    same files were clean.

**CI (GitHub, macOS/Windows/Ubuntu):** none of the failures comes from the
refactor. The failing runs included commits that change only notes:
- `test_live.py::test_quitting_straight_after_a_save_waits_for_another_tabs_load_waits_for_the_save`
  (Windows): "Disk cache unavailable" right after quitting. It failed on
  `1429d43` (notes only) and `49b197c`.
- `test_cache_mover.py::test_a_lock_is_exclusive_and_released_when_its_process_ends`
  (Windows): the file lock is still held after its process was killed. It
  failed on `a05d135` and needed reruns on other runs.
- `test_two_step_browse.py::test_refresh_cancels_only_automatic_subscriptions_and_suppresses_new_checks`
  (macOS): already in Known issues. It failed on `812baa8` (notes only).
- One macOS Tests job (`22a2c93`) was **cancelled by the 15-minute job
  limit**. Its tests had passed, but on a slow runner the suite plus the serial
  coverage rerun took about 13.5 minutes, leaving almost no margin.

The latest commits' CI runs may still be going. Check the Actions tab.

## Proposals (not done)

**Roadmap and doc updates:**
- `roadmaps/refactoring.md`: record milestone 2's slices A–G and H-lite as
  done, and the remaining H (the load logic behind a controller; `FolderCache`
  stores; splitting `_on_event` last).
- `roadmaps/_readme.md` Known issues:
  - tick "window tests read native QSettings" (fixed by E1);
  - add the two Windows CI flakes above;
  - add the macOS job-time margin.
- `roadmaps/agent-workflow.md`: "One settings factory" done
  (`app_settings()`). A profile can later make it honour
  `HELAB_SETTINGS_OVERRIDE`. Also say that a branch changing dependencies
  edits `requirements.txt` **and** refreshes `requirements.lock`.

**CI:**
- Raise the macOS Tests job's `timeout-minutes` (15) or drop its serial
  coverage rerun.
- Root-cause the two Windows flakes (the lock release after a kill; the store
  open right after quitting).

**Behaviour changes, each for Tony to decide:**
- Call `AnalysisRunner.stop()` on quit.
- Typed widget classes in Basic plots instead of `hasattr` widget attributes.
- `DecadeLogAxis` → `GroupedAxis` (labels differ at 10⁹ events per bin and up).
- Move transfer fractions onto `peaks.find_time_peaks` (would change the
  numbers; recheck the MATLAB comparison).
- Type the GUI side of the helper events: `resultReady` as
  `HelperEvent | GuiEvent`, narrowed per handler.

**Tidy-ups:**
- `.ai/memory/results/*-pc-caveats.md` still say `-r requirements.txt` for
  lab PCs. Switch them to `requirements.lock` when those machines next update.
- Old session render scripts
  (`.ai/sessions/2026-10-19-claude-live-l3/render_live_plots.py`,
  `…floating-plot-settings/render_floating_settings.py`) import moved names.
  They are history and were broken before this run too.

## Manual checks (proposed for `.ai/MANUAL_TODO.md`)

Native and real-volume checks can't be done from the cloud container:
- **macOS app from the integration branch:** browse `/Volumes/dld_output`,
  load a run, use cache first, Live with plots following, and quit while saving.
- **Windows lab PC:** the same, plus the packaged app's helper. CI builds it,
  but no frozen helper has been run on Windows.
- **Plot UI on screen:**
  - floating plot settings;
  - the Settings panel following the active plot;
  - RAM budget release and reload;
  - closing the window with plots open.
- **Settings:** native settings still read and save as before (Settings
  dialog, budgets, check level, Lab parameters).
