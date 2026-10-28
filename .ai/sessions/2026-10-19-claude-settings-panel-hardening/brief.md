# Brief: Settings panel hardening

Floor "Settings panel hardening", branch agent/settings-panel-hardening, base 486cf56 (dev/v0.0.6). Rules: your role, AGENTS.md (Script system, UI, Visualization) and roadmaps/agent-workflow.md (Quick features).

## Background

Tony's Assistant built a quick feature on Ground, and you harden it:
- **32f32a7**: `PlotSettingsPanel` replaced the per-plot settings tabs. One top-right panel shows the active plot's settings: last clicked, focused, tab-activated or floating-window-activated, through an app-wide event filter plus `tabifiedDockWidgetActivated`. A chooser names the plot and raises it. Pages keep their edits, and closing a plot falls back to the plot shown before. `ParameterSpec.page` gives multi-tab settings. `UnitSpinBox` (helab_float/helab_int) accepts numbers without their unit.
- **486cf56**: × close buttons on tabbed plot docks (`DockTabCloser`), a ✕ beside the chooser (`PlotSettingsPanel.close_current`), and a macOS fix: a hidden QQuickWidget in `HelabMainWindow._start_with_rhi_surface` stops the window closing and reopening when the first 3D scatter opens.

Read the roadmap lines marked "hardening pending" and the related MANUAL_TODO items.

## Harden

1. **The app-wide event filter.** Measure its cost per event: it should be cheap, and must not run Python work on every mouse move. Check its lifetime: installed once, removed on window close, no leak across main windows or tests, and no stale references to closed docks.
2. **Many plots,** e.g. 20 open, tabbed and floating. The chooser, the fallback order on close, and memory once they're closed. Each plot's pages and edits stay separate.
3. **`_add_dock`** only tabs a new dock next to a visible one. Define the rule with hidden, floating, closed and all-floating docks, and test each case.
4. **`DockTabCloser`** matches tabs to docks by window title (unique as "Name (id)" today). Make it match by dock identity, or prove titles can't collide (renames, two plots of the same analysis) and test that.
5. **The RHI fix** is macOS only. Check it is a no-op elsewhere and can't break offscreen tests. The lab-PC check stays in MANUAL_TODO for Tony.
6. **Activation sources.** Test each one offscreen as far as Qt allows: a click in a pyqtgraph view, a click in a QtWebEngine view (focus may never reach Qt), tab activation, a floating window, keyboard focus. Write down what offscreen tests can't show, for Tony's on-screen checklist.
7. **UnitSpinBox edge cases:** a bare number with each SI prefix shown, negative values, empty input, locale decimal commas (lab PCs are Windows), and clamping.

**Not in scope:** a "pin" to keep one plot's settings (a new feature; Tony decides later).

## Ownership

You own:
- `helab/models/ScriptTreeSelector.py`
- the plot-dock, settings-panel and RHI code in `helab/views/HelabMainWindow.py`
- `helab/analysis/parameters.py` and `parameter_tree.py`
- `tests/test_analysis_gui.py`, `tests/test_script_system.py`, new test files for this work
- your session folder

Don't touch `io_helper`, `io_service`, `folder_cache`, `FolderExplorer` or `SnapshotFileSystemModel`: an SMB I/O audit floor may start there. Ask me for anything else.

## Checks and handoff

- The full suite: `pytest -n 6 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest` (run `mkdir -p .ai/temp` once).
- `mypy --strict` helab and tests, also `--platform win32` on tests.
- pyright helab tests, also `pyright tests --pythonplatform Windows`.
- `git diff --check`.
- Report every RERUN by name.
- Offscreen renders of any visual change go in `screenshots/`.
- Commit each item separately. Don't push until I say so.
- When done, write handoff.md: what changed, decisions, Tony's on-screen checklist, proposed doc changes. Then run `maestri floor status "..." --state review` and report with `maestri ask "Maestro" "<summary>"`.
