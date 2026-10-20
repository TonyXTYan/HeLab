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

Only `script_tree` imports `helab.scripts` (both groups, and through them Dash,
Matplotlib and QtWebEngine); `instance` still pulls QtWebEngine in through
`helab.analysis.backends` → `panes`.

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
