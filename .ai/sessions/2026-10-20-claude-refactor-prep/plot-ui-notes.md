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
