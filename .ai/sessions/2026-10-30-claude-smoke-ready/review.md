# Review: smoke ready, phase A (Wren, Reviewer; `agent/smoke-ready`, 9f0b21f..94ed478)

Reviewed the diff itself (`git diff 9f0b21f...94ed478`), not the handoff's account of it. Phase B
commits after 94ed478 are out of scope.

## Checks run

- **Full suite** on 94ed478, in a detached worktree of that commit (so Beacon's phase B edits on the
  floor don't mix in), `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`:
  **8200 passed, 669 skipped, no RERUN** (the same as the handoff). (A first try from a `git archive`
  copy had 3 failures and 15 reruns, all from `test_versioning`/`test_release_recovery` needing
  `.git`: my setup, not the branch.)
- `mypy helab/ --strict`, `--platform win32`, `mypy tests --strict`: clean (192, 192, 161 files).
  `pyright helab tests`, `pyright --pythonplatform Windows helab tests`: 0 errors.
- **CI run 40978424279** (head 94ed478): completed, success, every job green. Tests jobs:
  macOS (1/2) 123812163730 4089 passed, 322 skipped, **1 rerun**; macOS (2/2) 123812163733 4111 passed;
  Ubuntu (1/2) 123812163884 4086 passed, 324 skipped, **1 rerun**; Ubuntu (2/2) 123812163905 4111 passed;
  Windows (1/2) 123812163773 4076 passed, 333 skipped, **1 rerun**; Windows (2/2) 123812163931 4095
  passed; Converter backends 123812163744 / 123812163861 / 123812163779 clean. The three reruns: H1.
- A probe (scratch, not committed): the main window on a synthetic folder with **every script of
  every group** open (16 plots), then the test's own `unnamed()` on every visible top-level window;
  and a `MatplotlibPane` on its own. Results in H2.

## High

**H1. CI: the same test reran on all three OSes, after the new test ran on that worker.**
`tests/test_analysis_gui.py::test_plots_close_from_their_tab_and_the_settings_panel`, Tests (1/2) on
macOS, Ubuntu and Windows (jobs above), each the same reason:

```
E       assert (False)
E        +  where False = <helab.views.plots.instance.AnalysisInstance object at …>.is_closed
tests/test_analysis_gui.py:359: AssertionError
```

It fails on its first attempt and passes on the rerun. Each time it ran on `gw0` right after 9 tests of
`tests/test_accessible_names.py` (Settings, 7 dialogs, the self-test) and `tests/test_analysis.py`. In
the 30 Tests jobs of the 5 latest CI runs of other branches (40977894008, 40977028554, 40975825607,
40898587803, 40894080358) it never reran, and it isn't in known-issues. The test closes a plot through
its tab's `tabCloseRequested`, the path this commit changed in `DockTabCloser`
(`helab/views/plots/dock.py:299` `windowTitleChanged` → `schedule_fit`; `:316` `tabMoved` →
`schedule_fit`; `:310-325` `identify_tabs` on every fit). I couldn't reproduce it locally: the exact `gw0` order
replayed 3× in one process and 2× with `-n 1 --cov=helab --timeout=120 --timeout-method=thread`, and the
test 48× in parallel, all passed. The landing rule needs every RERUN explained or in known-issues;
3 of 3 OSes points at an order dependency or a regression from this commit. Find the cause (e.g.
log, in that test, every `QTabBar` under `middle_mainwindow` with its count, `tabsClosable`, the
`helabClosable` property and `dock_at` for each index at the failure), fix it, or add it to
known-issues with what's known.

**H2. The walk doesn't reach controls that plots draw, and four of them fail its own rule today.**
The main-window case opens two PyQtGraph scripts only (`Counts per shot`, `T, X, Y histograms`), and
`widget_classes()` guards `helab/views` only, so widget classes in `helab/analysis` and `helab/scripts`
(`PlotlyPane`, `MatplotlibPane`, `ReleasePlot`, the density images' widget, `UnitSpinBox` in other
places) are outside the guard. With every script open, the walk reports:

- `helab/scripts/dld/release_time.py:383` "Use for this folder…" (`QPushButton < ReleasePlot`): no ID.
- `helab/analysis/panes.py:40` "Open in browser" (`QPushButton < PlotlyPane`), twice (two Plotly
  plots: 3D scatter, Correlations): no ID. One fixed ID would also repeat when two Plotly plots are
  shown side by side in the plot area (same window), so it needs the plot's number.
- `helab/analysis/backends.py:97` `MatplotlibPane`'s `NavigationToolbar2QT`: 8 `QToolButton`s (Home,
  Back, Forward, Pan, Zoom, Subplots, Customize, Save): no ID. Any plot whose Library is set to
  Matplotlib has them. (Named by Qt from their text; the ID is what's missing.)
- Probably `helab/scripts/dld/density_images.py:422` "Copy circles" too (not shown on synthetic data).

Brief item 1 ("every interactive control … each script's …"), item 2 ("with synthetic data where a
control only appears with a folder or a plot") and phase B item 1 (an ID on every control the test
walks). These files are outside the owned paths, so this needs CoCo: either approve names/IDs there, or
give them IDs from the view side after render (e.g. in `instance.py`, `plot_<n>_…`). Either way the test
should open each script once (all groups) and one plot per Library, and the guard should cover widget
classes in `helab/analysis` and `helab/scripts` (or say in `SKIPPED` why not).

**H3. On macOS (and Linux) Qt names a combo box by its current text, not its accessible name.**
`QAccessibleComboBox::text(Name)` (`.ai/temp/qtsrc/complexwidgets.cpp:416`, `#ifndef Q_OS_UNIX`) uses
the widget rule only on Windows; on Q_OS_UNIX, which includes macOS (notes.md says so), Name is the
Value: the current choice. The Cocoa bridge gives Name as AXTitle (`cocoa.mm:571`) and the description
as AXDescription (`cocoa.mm:707`). So on the Mac, where `app_ax_find` searches by title, the Group combo
is titled by its current group, the Preset combo by the preset, and so on. Smoke-automation item 4 names
the Group combo explicitly ("so `app_ax_find` finds them by title"); that isn't met on macOS, and can't
be from PyQt6 (no `QAccessible` binding to override the interface). What's wrong today is the account:

- handoff, runbook proposal: "`app_ax_find` by name ('Folder path', …, 'Preset', 'Apply preset',
  'TXY source')": "Preset" and "TXY source" are combos; on macOS a runner finds combos by AXIdentifier
  (`script_group`, `preset_combo`, `txy_source`, `txy_profile`, `plot_chooser`, the Settings combos), or
  uses Debug › Script Group. Say so, and add it to M~3 (check AXTitle of `script_group` on the Mac).
- `tests/test_accessible_names.py` module docstring: "though Qt on Linux names a combo by its current
  text" → "on macOS and Linux"; and say the test checks the Windows name for combos.
- The proposed `app-runtime-and-ui.md` paragraph should carry the same caveat.

## Low

**L1. Stale Debug items when an item is pressed without its menu opening.** The submenus are filled at
construction and refilled only on `aboutToShow` (`HelabMainWindow.py:583-590`). If a runner presses an
item through accessibility without the menu opening (what M~3 asks to check), the item may hold a
deleted object: Run Plot's actions hold run buttons that `tree_widget.clear()` deletes when the group
changes (`HelabMainWindow.py:625` → `b.click()` on a deleted button), Show/Close Plot Tab hold docks
`deleteLater`'d on close (`:653`, `:663`), and Save Window Screenshot… uses the target from the last
`aboutToShow` (`:594`, `:679-688`). With `app_log`'s excepthook this logs a `RuntimeError` and does
nothing rather than crashing. A `sip.isdeleted` guard in the lambdas would make it a no-op; M~3 should
note the risk.

**L2. Inline dialogs aren't walked and the skip list doesn't say so.** plan.md promised plain
`QMessageBox`/`QInputDialog` calls "listed as reasoned skips"; `SKIPPED` is empty and the guard can't see
them (they aren't classes). Inline dialogs with more than text buttons: `QInputDialog` in
`HelabMainWindow`, `CacheMover`'s `QProgressDialog` (`CacheMover.py:258`). notes.md explains the choice;
put it in the test's docstring and the testing.md proposal so a reader of the test knows what's out.

**L3. A plot parameter's editor is hidden until its row is selected.** pyqtgraph 0.14's
`WidgetParameterItem` hides the editor of number, text and list parameters until the row is selected
(`parametertree/parameterTypes/basetypes.py:25`, `hideWidget = True`); Qt hides hidden widgets from
accessibility, so a runner can't find `param_<group>.<name>` until it selects the row in the
`plot_settings` tree. The runbook proposal should say so (it bears on phase B's Return/Tab bug too).

## Nits

- **N1.** `plot_tabs_<n>` (`dock.py:310`, `:322`) numbers bars in `findChildren` order; Qt retires bars
  with `deleteLater` and makes new ones as docks move (`qmainwindowlayout.cpp`, `unuseTabBar`), so a
  bar's number can change within a session. The close buttons' IDs (from `plot_id`) are fine; the
  fallback `f"{number}_{index}"` (`dock.py:325`) changes with tab moves (no non-`AnalysisDock` docks today).
- **N2.** The self-test doesn't cover "no ID" or a tab without a name; one line each.
- **N3.** The screenshot creates `screenshots/` in the temp folder and writes the PNG on the GUI thread
  (`HelabMainWindow.py:709-717`). The temp folder can be set in Settings, and the I/O trace checks it
  through a helper (`trace_check`, `:742`). Fine for a debug item; say so if it stays.

## Checked, no finding

- **IDs** are set where the control is made, from what it is (analysis ID, plot number, folder tab's
  open order, parameter key, profile field name, constant key, button role), never from text; the
  screenshot's file name is the only title-derived string. Folder tab close buttons keep their ID after
  an earlier tab is closed (probe: `close_folder_tab_2` stays on "run"). With 16 plots open no ID
  repeats among a window's shown controls.
- **The name rules** in `effective_name` match Qt 6.11 (`qaccessiblewidget.cpp:317-335`,
  `simplewidgets.cpp:122-125`, tabs, line edits' placeholder only as Description) and are conservative,
  except combos (H3). The self-test fails on an icon-only button, an unlabelled spin box, a repeated
  shown ID and a mismatched identifier, and not on a buddy-labelled box or a hidden repeat.
- **Debug items** call their control's path: Run Plot clicks the run button (→ `run_analysis`), Script
  Group `setCurrentIndex` (→ `currentTextChanged` → `_on_group_changed`, the only connection), Show Plot
  Tab `show_plot(raise_dock=True)` (the chooser's `activated` path), Close Plot Tab `dock.close()`
  (`DockTabCloser.close_tab`'s), Settings Tab `show_settings_dialog(tab=…)` (same guard, then
  `show_tab`). Menus are filled from memory (`current_dataset_view`, the tree, `instances()`); nothing
  reads source folders or the store.
- **Screenshot target:** the active window at the Debug menu's `aboutToShow`, else the main window;
  deleted or hidden targets fall back; `grab()` renders the widget, so the save dialog isn't in it.
- **Call sites:** besides names/IDs, only the Debug menu, `show_settings_dialog(tab=)`,
  `SettingsDialog.TAB_TITLES`/`show_tab`, `AnalysisDock.plot_id`, and the `DockTabCloser` refits (H1).
  Dock objectNames (used by arrangements and `saveState`) are untouched; Qt's dock layout doesn't use tab
  bars' objectNames.
- **Tests:** settings via `app_settings()`, synthetic folders in `tmp_path`, only PyQtGraph plots (no
  `QWebEngineView` made by the tests; the main window is closed through `_closing`).
