# Brief: Floating plot settings

Floor "Floating plot settings", branch agent/floating-plot-settings, base 9f6ee5a (dev/v0.0.6, after Live L3). Worker: Claude Code, Opus 5.5 high, Worker role. Review: a fresh Claude reviewer (Codex is low on usage). Rules: your role, AGENTS.md › Script system (Settings panel) and roadmaps/agent-workflow.md.

## Tony's decisions (2026-10-19)

1. **Settings move with a floated plot.** When a plot dock floats, its settings page (the same editors, not a copy) moves into that plot's window. When it's docked again, the page goes back to the main Settings panel. Unapplied edits and Rerun stay with the page.
2. **Collapsed by default.** In the floating window the settings sit in a collapsible section: a header with ▸/▾, the plot's name and its settings summary. It starts collapsed. Each plot remembers its open/closed state for the session.
3. **To the right of the plot,** like the main window, with a **draggable splitter**. Remember the splitter width per plot for the session. Collapsed, the section is a slim strip that expands on click.
4. **The main panel:** while the shown plot is floating, it says "Settings are in this plot's window", with a button that raises that window. Docked plots behave as now.

## Watch for

- Focus and activation rules from Settings panel hardening:
  - a floating plot still counts as shown
  - hidden or closed falls back to a visible plot
  - closing the main window closes plots
- Moving the page must not break those rules, `DockTabCloser`, the chooser, or L3's Follow Live controls and the source line.
- Float, re-dock and close while the plot is running or following Live. Many floating plots. Re-docking into a tab group.
- Windows matters: Maestro runs the suite on RSPE. Tony checks the look on the Mac and a lab PC.

## Ownership

- You own:
  - `helab/models/ScriptTreeSelector.py` (PlotSettingsPanel)
  - the plot-dock code in `helab/views/HelabMainWindow.py`
  - `helab/analysis/parameter_tree.py`
  - tests for those
  - your session folder
- Don't touch `io_helper`, `io_service`, `folder_cache` or `FolderExplorer`, which belong to the SMB audit.

## Checks and handoff

- The usual full checks:
  - the suite with `--reruns`
  - `mypy --strict`, including `--platform win32`
  - pyright, including Windows
  - `git diff --check`
- Offscreen renders of the floating window, collapsed and expanded, go in `screenshots/`.
- `handoff.md` holds an on-screen checklist for Tony.
- Commit freely; push when Maestro says.
