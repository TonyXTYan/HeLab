# Handoff: Floating plot settings

Branch `agent/floating-plot-settings`, base 9f6ee5a. Not pushed yet (push when Maestro
says). Design, measurements and checks: [notes.md](notes.md). Brief: [brief.md](brief.md).

## What changed

| Commit | Change |
|---|---|
| 04d82b9 | A floating plot's settings page (the same editors, with unapplied edits, Rerun and the Live group) moves into a collapsible section right of the plot in its window, and back to the Settings panel when it docks again. The section starts closed as a slim strip; open, a one-line header above the page and a draggable splitter. Opening widens the floating window by the section's width (kept on its screen), so the plot keeps its size; closing narrows it. Open/closed and width are kept per plot for the session. While the shown plot floats, the panel says "Settings are in this plot's window" with **Show plot window**. Tests. |
| d648b62 | The strip's focus frame shows only for keyboard focus (a floating window focuses it as it activates); tidier layouts; typing fixes in the new tests. Screenshots re-rendered. |

Files: `helab/models/ScriptTreeSelector.py` (`SettingsToggle`, `FloatingSettings`,
`AnalysisDock` frame, `PlotSettingsPanel._place` and the note),
`helab/views/HelabMainWindow.py` (`update_plot_source` sets the header's settings summary),
tests in `tests/test_plot_settings_panel.py`, `tests/test_live_plots.py` and
`tests/test_analysis_gui.py` (two assertions updated: a floating plot's page is now in its
window, and the panel's stack holds the hint and the note). `parameter_tree.py` needed no
change.

## Tony's decisions, as built

1. Settings move with a floated plot: `topLevelChanged` moves the page; the plot itself
   never changes parent.
2. Collapsed by default; ▸/▾, the plot's name (the chooser's title, e.g. "T, X, Y
   histograms (1) · run_042 · rev 1") and its settings summary (the dock's second source
   line). Open/closed remembered per plot for the session.
3. Right of the plot with a splitter; width remembered per plot. Closed: a strip
   (`▸` upright, text running down) that opens on click (or Space).
4. The main panel shows the note and a button raising the window; docked plots as before.

The hardening rules hold: a floating plot still counts as shown; hidden or closed falls
back to a visible plot (tested with a floating plot hidden); closing the main window
closes plots, floating ones included (tested while running); the chooser raises a floating
plot; `DockTabCloser` keeps close buttons after re-docking into a tab group; no event filter.

## Screenshots (offscreen)

- [floating-collapsed.png](screenshots/floating-collapsed.png): floating, section closed.
- [floating-expanded.png](screenshots/floating-expanded.png): opened (window widened by 279 px).
- [main-panel-settings-away.png](screenshots/main-panel-settings-away.png): the main panel's note.
- [main-panel-docked-again.png](screenshots/main-panel-docked-again.png): docked again, the page is back.

Re-render: `QT_QPA_PLATFORM=offscreen python .ai/sessions/2026-10-19-claude-floating-plot-settings/render_floating_settings.py`
(with `.ai/local/floor-env.sh` sourced).

## Checks

Full suite 1152 passed, 2 skipped, 2 xfailed, **no RERUN** (an earlier run, before a typing
fix in the new tests, had 10 reruns whose names weren't listed). The three plot test
files five times without `--reruns`: all passed. `mypy --strict` on helab and tests, default
and `--platform win32`; pyright on helab and tests, default and `--pythonplatform Windows`;
`git diff --check`: all clean. Not run on Windows itself (Maestro runs the suite on RSPE).

## On-screen checklist for Tony (Mac and a lab PC)

1. Run a plot, float it (double-click its title or drag it out). The main Settings panel
   shows "Settings are in this plot's window" and **Show plot window**; the floating window
   has a slim strip on its right, `▸` at the top and the plot's name and settings running
   down. Is the strip readable, and is it clear it can be clicked?
2. Click the strip. The window grows to the right by about 300 px and the plot keeps its
   size; the header reads "▾ name · settings". Change a setting without Rerun, close the
   section (the window shrinks back), open it again: the edit is still there.
3. Drag the splitter between plot and settings. Close and reopen the section: same width.
   Dock the plot, float it again: open/closed state and width as you left them.
4. Float a plot near the screen's right edge and open its settings: the window stays on
   screen (moves left, or the plot gives up room).
5. Dock the plot again (double-click its title): its page is back in the main panel with
   your edits; Rerun works there.
6. With a plot following Live, float it while it runs, use Follow Live and Rerun in its
   window, dock it, float it, close it while it runs. Nothing should hang or be left over.
7. Three plots tabbed: float the middle one, dock it again: it returns to the tab group,
   and the tabs' × buttons still close the right plots.
8. Several floating plots: click each window; the chooser names it and the panel shows the
   note; the chooser and **Show plot window** bring the right window forward.
9. Minimise a floating plot that is the shown plot: the panel switches to a visible plot.
10. Windows lab PC: floating windows there have Qt's own title bars; check the growth on
    open/close and the strip's look at the PC's scaling. Keyboard: Tab to the strip shows
    a highlight frame and Space opens it; clicking it shows no frame.

## Open questions

- **Show plot window** raises the window but doesn't open a closed section. Should it also
  open it (the user clicked it to reach the settings)? One line to change.
- Dragging a docked plot to another dock position floats it for the drag, so its page goes
  to the window and back during the drag (the panel shows the note meanwhile). Harmless,
  but visible.
- The floating window grows only on the click; floating a plot with its section open
  (floated before) takes the section's width from the plot, as Qt restores the window's
  earlier floating size.

## Proposed doc changes (for the Coordinator)

AGENTS.md › Script system, after "One Settings panel (top right, `PlotSettingsPanel`) shows
the active plot's settings: …":

> A floating plot's page moves into its window (`AnalysisDock.settings`, right of the plot,
> the same editors: edits and Rerun go with it) and back when it docks again; while the
> shown plot floats, the panel says "Settings are in this plot's window" with Show plot
> window. The section starts closed as a strip (▸, the plot's name and settings summary);
> open, its splitter sets its width; opening and closing widen and narrow the window so the
> plot keeps its size; open/closed and width last the session per plot. `AnalysisDock`'s
> `widget()`/`setWidget()` are the plot, inside a splitter frame.

Also: that paragraph currently says "One Settings panel (top right, `PlotSettingsPanel`)
shows the active plot's settings…" twice (the second ends "closing a plot shows the last
one shown before it"); the second copy can go.

`.ai/memory/results/analysis-plots.md` (or a new settled-decisions file): Tony's four
decisions of 2026-10-19 above, with the "Settings are in this plot's window" wording.
