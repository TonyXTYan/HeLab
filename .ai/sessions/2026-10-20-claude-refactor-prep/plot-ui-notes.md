# Plot-UI track notes (2026-10-20)

Branch `agent/refactor-plot-ui` from `agent/refactor-prep` (`9cf8782`), worktree
`/home/user/wt/plot-ui`. Slices B → C → E; this note covers **slice B** so far.

## Slice B: `helab/models/ScriptTreeSelector.py` → `helab/views/plots/`

A pure move: every class and function body is unchanged (checked by comparing the
non-blank lines of the five new modules' bodies with the old file's lines 50–2055:
identical, 1772 lines). Class and function names are unchanged. The old module is
deleted, with no shim.

| Module | Holds | Imports from the package |
|---|---|---|
| `helab/views/plots/__init__.py` | docstring only | — |
| `dock.py` | `address_of`, `WIDGET_SIZE_MAX`, `SettingsToggle`, `FloatingSettings`, `AnalysisDock`, `DockTabCloser` | — |
| `pictures.py` | `Picture`, `snapshot`, `PlotPicture`, `ReleasedPlot` | — |
| `instance.py` | `LinkedAnalysisInstance`, `AnalysisInstance` | `dock`, `pictures` |
| `script_tree.py` | `GroupType`, `GroupData`, `TreePanelWidget` (incl. the bundled `standard.MODULES`/`dld.MODULES` registration, `run_analysis`, `_add_dock`, `tab_target`) | `dock`, `instance` |
| `settings_panel.py` | `mouse_held`, `DragEnd`, `PlotSettingsPanel` | `dock` |

The graph is acyclic as proposed, so no adjustment was needed. `HelabMainWindow`
appears only under `TYPE_CHECKING` (in `instance` and `script_tree`), as before.
Each module's imports were pruned to what it uses (`ruff --select F`); the old
file's unused imports (`numpy`, `QFileDialog` etc. where unused, the
`FolderExplorer` TYPE_CHECKING import, `Union`, `no_type_check`) went with it.

Only `script_tree` loads QtWebEngine (through `helab.scripts`, with Dash and Matplotlib).
`instance`, `dock`, `settings_panel` and `pictures` import none of it (correction after
review: an earlier version of this note said `instance` pulled it in through `backends`;
`backends` doesn't import `panes`). So an entry point or test that imports only those
modules and then creates the QApplication would load QtWebEngine too late if it later
imports the scripts; the app is fine because `main.py` imports `HelabMainWindow`, which
imports `QWebEngineView`, before the QApplication exists.

### Patch targets moved

- `helab.models.ScriptTreeSelector.store_options` ×11, `.get_analysis_runner` ×4,
  `.get_folder_cache` ×1 → `helab.views.plots.instance.*` (where `AnalysisInstance`
  looks them up). `monkeypatch.setattr` with a string raises if the attribute is
  missing, so a wrong target would have failed loudly.
- `.mouse_held` ×1 → `helab.views.plots.settings_panel.mouse_held`.
- No `patch.object(<module>, …)` or module aliases of the old file existed.

### Imports updated

`helab/views/HelabMainWindow.py` and nine test files (`test_analysis_gui`,
`test_constant_layers`, `test_dld_transfer_fractions`, `test_live_plots`,
`test_plot_ram_budget`, `test_plot_settings_panel`, `test_script_system`,
`test_shot_trends`, `test_transfer_fractions`). `helab/models/__init__.py`
re-exported `TreePanelWidget` and `PlotSettingsPanel`; it is now empty, and
`test_script_system` imports them from their modules.

### Decision: `helab/models/__init__.py` no longer loads the plot UI

That re-export meant importing *any* `helab.models.*` module (e.g.
`SnapshotFileSystemModel`, which `FolderExplorer` uses) imported the whole plot
UI, the bundled scripts and QtWebEngine. With it gone, `FolderExplorer` and the
model are lighter. The app is unaffected: `main.py` imports `HelabMainWindow`
(which imports `QWebEngineView` itself, and the plot package) before the
`QApplication` exists.

The one consequence in tests: 15 test files no longer load QtWebEngine at
collection (checked by importing every test module alone, base vs now). Only
`tests/test_folder_details_io.py` then imported `HelabMainWindow` lazily inside a
test, after the `QApplication` existed, so run alone it failed with
"QtWebEngineWidgets must be imported … before a QCoreApplication instance is
created" (in the full suite another module had loaded it first). Its
`HelabMainWindow` import moved to module level with a comment. No other of the 15
files imports the main window, scripts or `helab.analysis` lazily.

### Docs

- `AGENTS.md` Script system: "The right-hand panel (`ScriptTreeSelector`)" now
  names `TreePanelWidget`, `helab/views/plots/script_tree.py` and the package's
  modules.
- `roadmaps/analysis-workflow.md`: the same reference.
- `roadmaps/refactoring.md` names no moved file; unchanged.
- Left as history: `.ai/sessions/*` notes and render scripts
  (`2026-10-19-claude-live-l3/render_live_plots.py`,
  `2026-10-19-claude-floating-plot-settings/render_floating_settings.py` still
  import the old module), and `docs/.ai-generated/script_system_review.md` (an old
  generated review, unchanged since v0.0.4a).

### Validation

- Targeted (`-n 2 --reruns 2`): the nine plot test files, 359 passed, 1 skipped;
  `tests/test_folder_details_io.py` alone, 5 passed.
- `python -m mypy helab --strict` (124 files), `python -m mypy tests --strict`
  (94 files), `pyright helab tests`: clean.
- Full suite (`-n 2 --reruns 5 --reruns-delay 1 -rR`): **2183 passed, 9 skipped,
  2 xfailed in 6 min 16 s, no RERUN.**

### Open points for later slices

- `HelabMainWindow` still reaches the plot package only through `dock`,
  `script_tree` and `settings_panel`; slice E's `PlotWorkspace` will own those.
- `AnalysisInstance`'s duck-typed `getattr(main_window, …)` calls are unchanged.

## Slice C: a Qt-free analysis core

Behaviour-preserving; class and function bodies moved unchanged except where noted.

| From | To | Notes |
|---|---|---|
| `follow.LiveFeed` | `helab/analysis/live_feed.py` | With its Qt, `revise`/`view_of` and `events` imports. `follow.py` keeps `LivePolicy`, `Follow`, the specs and texts, and imports no Qt (nor `events`). |
| `budget.py`: `WARN_SHARE`, `DIALOG_SHARE`, `REARM_SHARE`, `RELEASE_SHARE`, `RELOAD_GRACE`, `view_buffers` (and its weak cache), `hollow` (`_NO_EVENTS`), `Restored`, `restore`, `shots_list`, the `Plot`/`Panel` protocols, `Usage` | `helab/analysis/budget_core.py` | A clean cut: everything above `RamBudget` was pure. `budget.py` keeps `RamBudget` and imports the shares, protocols and `Usage` from the core. |
| `AnalysisRunner`'s queue, worker thread, job ids, contexts, cancellation, `stop` | `helab/analysis/runner_core.py`, `AnalysisQueue` | Same code; the two `emit`s became calls to `on_started(job_id)` / `on_finished(result)` callbacks given at construction. |

**Runner delivery is unchanged.** `AnalysisRunner(QObject)` keeps `started`/`finished`,
`results`, `submit`/`cancel`/`running`/`stop` and `get_analysis_runner()`; it builds
`self.core = AnalysisQueue(results, self._started, self._finished)`, whose callbacks emit the
signals. They are called on the worker thread at exactly the points the old `emit`s were, so
Qt queues them to GUI-thread receivers as before. The worker thread's target is now the core's
bound method, and the core holds the runner's bound methods, so the runner stays alive while
its worker runs, as before. `AnalysisRunner.results` is the core's `RamResults` object.

The one private access in tests (`runner._thread`, `test_analysis.py`) is now
`runner.core._thread`. No test patched a name in `follow`, `budget` or `runner` by string;
`LiveFeed._latest` and `RamResults._pinned` accesses are on instances and unchanged.

Imports updated: `HelabMainWindow` (`LiveFeed`; `RamBudget` plus the shares from
`budget_core`), `CacheTab` (`RELEASE_SHARE`), `helab/views/plots/instance.py`, and tests
`test_live_plots`, `test_shot_trends`, `test_plot_ram_budget`, `test_constant_layers`.
The scripts' `from helab.analysis.follow import LivePolicy` stays valid (DLD scripts untouched).

### The guard: `tests/test_headless_imports.py`

- In a fresh subprocess (environment copied, cwd the repo root), imports `helab.scripts.base`,
  `helab.utils.ram_buffers` and 26 `helab.analysis` modules (all science modules, `follow`,
  `budget_core`, `runner_core`) and asserts none of PyQt6, pyqtgraph, matplotlib, dash, plotly
  or `helab.utils.constants` is in `sys.modules`. No pure module needed `constants`.
- A second test makes every `helab/analysis/` module listed as pure or Qt (`backends`,
  `budget`, `empty`, `live_feed`, `panes`, `parameter_tree`, `plot_axes`, `plot_text`,
  `runner`), so a new module has to be classified. My addition beyond the brief.
- Proven: adding `import PyQt6.QtCore` to `follow.py` failed it (`['PyQt6'] == []`); an
  unlisted `helab/analysis/probe_new.py` failed the listing test. Both reverted.
- scipy is still imported by the core (physics, fits…); not Qt, so allowed.

### Docs

`AGENTS.md`: `LiveFeed`'s module; `budget_core.py` beside `budget.py`; the runner sentence
names `AnalysisQueue` in `runner_core.py` and the new guard. Docstrings of `follow`, `budget`,
`runner` point to the new modules; `ram_buffers`' docstring names `budget_core`.
`roadmaps/refactoring.md` names none of these; unchanged.

### Validation

- Targeted (`-n 2 --reruns 2`): 11 files (analysis, plots, budget, Live, shot trends,
  release time, Cache tab, script system, headless imports): 355 passed, 1 skipped.
- Strict mypy `helab` (127 files) and `tests` (95 files), `pyright helab tests`: clean.
- Full suite (`-n 2 --reruns 5 --reruns-delay 1 -rR`): **2185 passed, 9 skipped, 2 xfailed,
  1 rerun in 6 min 24 s.** The rerun: `tests/test_dash_server.py::test_stop_frees_the_port`
  (port 8050; other workers' suites run at the same time). Unrelated to the moves; the file
  alone passed 3 times out of 3.

### Left / proposals

- `RamBudget` and `AnalysisRunner` are still Qt; a headless runner uses `AnalysisQueue`
  directly. `helab/analysis/empty.py` imports Qt for one widget; drawing modules stay Qt.
- Pre-existing lint (not touched): unused `RamBudget` import in `test_plot_ram_budget.py`,
  unused `IORequest`/`PLOTLY` and ruff F821 on a lambda reading `widget` before `del widget` in
  `test_live_plots.py`.

## Slice E1: one settings factory

- New `helab/utils/settings_store.py`: `app_settings()` and the org/app names
  (`QSETTINGS_ORG_NAME`, `QSETTINGS_APP_NAME`, moved from `constants.py`, where nothing
  else used them). QtCore only and nothing of HeLab's, because `constants.py` imports it and
  reads settings while it is imported. Not in `constants.py`, to stay import-light.
- All nine native constructions go through it: `main.py` (1), `constants.py` (2: the
  defaults of `get_path_from_setting_or_use_default` and `migrate_legacy_temp_dir`),
  `HelabMainWindow.py` (5), `SettingsDialog.py` (1). Production is identical: a new
  `QSettings(org, app)` per call, as before (native format, user scope).
- `cache_setting.open_settings` (helpers reopening the store from `settings_spec`) is left
  alone: it reopens whatever store the app named, ini or native.
- **Seam:** `HELAB_TEST_SETTINGS_FILE=<file.ini>` makes `app_settings()` open that ini. An env
  var, read per call, like the repo's other `HELAB_TEST_*` seams. `tests/conftest.py`'s
  autouse `private_settings` sets one per test, in a `tmp_path_factory` folder apart from
  `tmp_path` (tests list `tmp_path`). The profiles plan (`roadmaps/agent-workflow.md`) names
  `HELAB_SETTINGS_OVERRIDE` for a user-chosen file: that's a feature for later, so the seam
  stays test-only by name.
- **constants' import-time read:** under pytest the `HELAB_DIR_*_OVERRIDE` variables mean it
  never reads settings at import; in the app it now reads through `app_settings()` (native,
  as before). Conftest's order is unchanged.
- `tests/test_load_queue.py`: the three `monkeypatch.setattr("helab.views.HelabMainWindow.QSettings", …)`
  are gone; one test writes its value to `app_settings()` (the test's ini).
- `tests/test_settings_store.py`: an AST check that no `helab/` module but the factory and
  `cache_setting.py` constructs a `QSettings` other than an ini (`QSettings()` included),
  with a sample proving the check catches `QSettings(org, app)` and `QSettings()`; the seam
  gives an ini of the test's own; without it the factory asks for `(org, app)`, checked by
  recording the constructor (no native store is opened in tests).
- AGENTS.md: Settings persistence (the factory, the seam, the known issue now resolved), the
  test-seam list (now "these test seams", since it already named four), and, from the slice B
  review, `helab/views/plots/` in Package layout.

Proposals (not made: roadmap edits are Tony's):
- `roadmaps/_readme.md` known issue "Tests that build a real `HelabMainWindow` read the
  developer's native QSettings…": tick it (done by the factory and the per-test ini).
- `roadmaps/agent-workflow.md`, "One settings factory": mark done (`app_settings()`,
  `tests/test_settings_store.py`); profiles can make `app_settings()` return the profile's
  file (`HELAB_SETTINGS_OVERRIDE`) in that one place.

Validation (E1): tests that build the main window or settings (22 files): 510 passed,
1 skipped; strict mypy `helab`, `tests` and pyright clean.

## Fix after the slice C review: the runner's lifetime

Review finding on `31358e1`: `AnalysisRunner` → `core` → its bound `_started`/`_finished` →
runner made a cycle, so an idle runner was freed only by the cyclic GC (on whatever thread ran
it), no longer by refcount. Fixed in its own commit:

- `AnalysisQueue` holds the callbacks in `_Held`: a bound method by `weakref.WeakMethod`,
  anything else strongly. An idle runner has no cycle again.
- Starting the worker resolves them to strong references and passes them to the thread
  (`Thread(target=self._work, args=callbacks)`, then `_run_jobs`/`_run` take them), so a
  running worker keeps its runner alive exactly as the old `target=self._work` did. A callback
  whose owner is gone when a worker starts is skipped (can't happen: only the runner submits).
- Tests (`test_analysis.py`): an idle runner is freed with the cyclic GC off (it failed on
  `31358e1`); a runner whose job is computing stays alive with no other reference, reports
  the job, and is freed once stopped.
- Also reflowed `follow.py`'s docstring line that slice C made 120 characters.

## Slice E2: `PlotWorkspace` out of `HelabMainWindow`

New `helab/views/plots/workspace.py`, `PlotWorkspace`: a plain class (not a `QObject`), which
the window composes as `self.plots`. It owns:
- `middle_mainwindow`, `central_placeholder`, `dock_widgets`, `live_feed`;
- `panel_right_top_plot_settings`, made here now (the window still places it in the right
  splitter);
- `ram_button`, made here (the window still adds it to its status bar, at the same place
  among the permanent widgets), and `ram_budget` with `setup_ram_budget`,
  `_update_ram_button`, `_plots_released`, `ram_report_text` and `show_ram_report`;
- the presentation methods, moved verbatim: `close_plots`, `update_placeholder_visibility`,
  `_set_plot_source`, `follow_live`, `current_dataset_view`, `set_plot_result`,
  `replace_plot_content`, `update_plot_source`, `_wrap_plot` and `_update_plot_source_label`;
- new: `notice(text)` and `detach()` (the RAM budget's, then the Settings panel's detach, in
  the old order).

**Interface to the window.** Callables passed in: `current_explorer`, `explorers`, `notice`
(`show_status_notice`), `show_settings` (`show_settings_dialog`) and `closing`. Each defaults to
an empty answer, for tests. `host` is the window. Every object it makes keeps the parent it had
before: `LiveFeed`, `PlotSettingsPanel`, `RamBudget`, the RAM window and each `AnalysisDock`
until it is docked are parented to `host`. `HelabMainWindow` gains `current_explorer()`.

**Callers.**
- `AnalysisInstance`/`LinkedAnalysisInstance` take `workspace: Optional[PlotWorkspace]` (was
  `main_window`) and call it typed. Every duck-typed `getattr` is gone (`live_feed`,
  `ram_budget`, `set_plot_result`, `update_plot_source`, `replace_plot_content`,
  `middle_mainwindow`, `update_placeholder_visibility`).
- None-tolerance is kept: with no workspace there is no dock, no feed and no budget, and
  `_show_content`/`_swap_content` fall back to `setWidget` as before.
- The deleted-window check is `sip.isdeleted(workspace.host)`, the same object as before.
- `TreePanelWidget(workspace)` (was `helab_main_window`) uses the typed `current_dataset_view()`
  and `notice()`. The Settings panel never reached the window, so it is unchanged.
- `PlotWorkspace` imports `FolderExplorer` only under TYPE_CHECKING, and `instance` and
  `script_tree` import `PlotWorkspace` only under TYPE_CHECKING, so there is no cycle.

**The window** keeps menus, tabs, the status bar, the quit flow, `central_hint`,
`_update_folder_details` (now reading `plots.dock_widgets`/`central_placeholder`), the
folder-details timer and the desktop-notice sink. `closeEvent` order is unchanged:
`_closing = True`, `plots.close_plots()`, then `plots.detach()` (budget, then panel), then the
rest. Settings applies `plots.ram_budget`.

**No delegating properties** on the window: callers write `window.plots.X`.

**Tests.**
- The five hand-built windows (`test_live_plots`, `test_analysis_gui`, `test_plot_ram_budget`,
  `test_constant_layers`, `test_shot_trends`) are now plain `QMainWindow`s holding a real
  `PlotWorkspace`, no longer `HelabMainWindow` subclasses with a skipped `__init__`. A
  `PlotWorkspace` subclass overrides `current_dataset_view` where a test chooses the data
  (`window.view`).
- `test_plot_ram_budget`'s window keeps the typed `budget` (the set-up `RamBudget`).
- About 230 accesses are now `window.plots.X`, and `TreePanelWidget(window.plots)`.
- `test_script_system`'s mock window is now a `PlotWorkspace(QMainWindow())`.
- `test_folder_summary`/`test_folder_cache` `SimpleNamespace` windows have `plots=…`, and their
  static calls are `PlotWorkspace._set_plot_source/_update_plot_source_label`.
- `test_load_queue`'s partial `CancelTestWindow` gets a `PlotWorkspace` (Settings reads
  `plots.ram_budget`; the old `getattr(self, "ram_budget", None)` was only for such windows).
- One `monkeypatch.setattr(window, "current_dataset_view", …)` on a real window now targets
  `window.plots`.
- Checked: no test module's QtWebEngine import at collection changed (all modules imported
  alone, before and after).

AGENTS.md: the Live paragraph (`PlotWorkspace.follow_live`, its `live_feed`) and the Script
system paragraph (`PlotWorkspace.close_plots`, what the workspace owns, how it reaches the
window).

**Left on the window, noted rather than forced:** `central_hint` (explorer text) and
`_update_folder_details` (Folder details plus the plot hint: it is the window's timer). The
desktop-notice sink stays too.

**Note:** the workspace and its window refer to each other (the `host` attribute and the
callables), a Python cycle. It doesn't matter in the app (one window for the session), and test
windows are deleted by qtbot. The fake windows had cycles of their own through their lambdas.

### Validation (E)

- Targeted (16 files: plots, Live, budget, analysis GUI, scripts, folder summary and cache,
  main window, load queue, resize, central hint, transfer fractions): 513 passed, 2 fixed, then
  47 passed on those two files. Reruns there were the two failures being reproduced, both fixed
  (a `setattr` on the window, the partial window).
- Strict mypy `helab` (129 files) and `tests` (96 files), `pyright helab tests`: clean.
- Full suite (`-n 2 --reruns 5 --reruns-delay 1 -rR`): **2191 passed, 9 skipped, 2 xfailed in
  5 min 49 s, no RERUN.**

## Reviews (coordinator, 2026-10-20)

Separate reviewer subagents read each slice's commits.

- **B (`49b197c`):** no correctness findings. The bodies are identical apart
  from two old comments among the imports. No mutable module state. Every patch
  target is in the module that looks the name up. No cycles. QtWebEngine order
  is fine: 14 test files no longer load it at collection, and they pass alone.
  Two doc fixes, both folded into `01b3dc9`: a wrong note on where QtWebEngine
  is loaded, and Package layout in AGENTS.md.
- **C (`31358e1`):** verbatim. Signal order, thread and exception paths are
  unchanged. One real lifetime regression: a runner↔core reference cycle meant
  an idle runner was freed only by the cyclic GC, possibly on another thread.
  Fixed in `c296d28` (weak callbacks while idle, strong references held by the
  running thread), with tests that fail on `31358e1`.
- **E (`01b3dc9`, `c296d28`, `ddc1c07`):** no high or medium findings. The
  factory opens the same native store and the seam applies only when set.
  The runner fix matches the old lifetime when idle, when running and across a
  stop/restart. The moved workspace methods are identical by AST apart from
  `host` and the callables. Parents, status-bar placement and closeEvent order
  are unchanged, and no test assertion was weakened. Low notes, left as they
  are:
  - The Settings panel is created slightly earlier (in `_setup_middle_area`),
    with no observable effect.
  - The RAM budget's slots are bound to the workspace, so their lifetime
    follows `RamBudget`, a window child.
  - `AnalysisQueue` built directly with a bound method of a temporary object
    would drop that callback silently. Only `AnalysisRunner` builds one today.
  - The AST settings test misses aliased imports and `functools.partial`.

  The reviewer's first targeted run showed one unnamed RERUN; four later runs
  of the same files were clean.
