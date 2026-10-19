# Handoff: Floating plot settings

Branch `agent/floating-plot-settings`, base 9f6ee5a, pushed to origin (TonyXTYan/HeLab).
Round 1 ended at 0c734ec, which a fresh Claude reviewer reviewed ([review.md](review.md):
no blocker). Round 2 added Tony's two answers and the review fixes. Design, measurements and
checks: [notes.md](notes.md). Brief: [brief.md](brief.md).

## What changed

| Commit | Change |
|---|---|
| 04d82b9 | A floating plot's settings page (the same editors, with unapplied edits, Rerun and the Live group) moves into a collapsible section right of the plot in its window, and back to the Settings panel when it docks again. The section starts closed as a slim strip; open, a one-line header above the page and a draggable splitter. Opening widens the floating window by the section's width (kept on its screen), so the plot keeps its size; closing narrows it. Open/closed and width are kept per plot for the session. While the shown plot floats, the panel says "Settings are in this plot's window" with **Show plot window**. Tests. |
| d648b62 | The strip's focus frame shows only for keyboard focus (a floating window focuses it as it activates); tidier layouts; typing fixes in the new tests. Screenshots re-rendered. |
| 0c734ec | Notes and this handoff (reviewed). |
| 20224c8 | Tony: **Show plot window** also opens a closed section (remembered as open), as a click on the strip does. The chooser still only raises the window. |
| cbc617d | Tony: a dragged plot's page moves only when the drag ends: once if the plot ends up floating, not at all if it is docked again. How: see [Drag end](#drag-end). |
| e55945a | Review fixes: `AnalysisDock.setWidget` no longer hides the old plot when the new widget has taken it in (`_set_plot_source`'s `_wrap_plot(dock, dock.widget())`), with a test that fails without the fix; a blank line; review.md. |

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

## Drag end

Maestro's rules: no app-wide filter, no polling. When `topLevelChanged` or
`dockLocationChanged` fires with a mouse button down (one `QGuiApplication.mouseButtons()`
check per signal), the panel's `DragEnd` installs an **event filter on that dock only**.
It ends the wait at the first mouse event the dock gets with no button down: the release,
or a move, hover, enter or leave after a release it didn't see. Then it removes the filter,
and the page is placed on the next pass of the event loop. With no button down
(`setFloating`, the chooser), the page is placed on the next pass too. Between drags,
nothing filters. Qt's own dock drag delivers its release to the dock (the drag grabs the
mouse), which a real offscreen drag in the tests confirms.

Windows caveat, not checked: dragging a floating dock by a native title bar runs the OS's
move loop. If Qt doesn't see that release there, the page moves at the dock's next mouse
event (the pointer leaving or moving over it). It never stays stuck while the pointer
moves over the plot.

## Screenshots (offscreen)

- [floating-collapsed.png](screenshots/floating-collapsed.png): floating, section closed.
- [floating-expanded.png](screenshots/floating-expanded.png): opened (window widened by 279 px).
- [main-panel-settings-away.png](screenshots/main-panel-settings-away.png): the main panel's note.
- [main-panel-docked-again.png](screenshots/main-panel-docked-again.png): docked again, the page is back.

Re-render: `QT_QPA_PLATFORM=offscreen python .ai/sessions/2026-10-19-claude-floating-plot-settings/render_floating_settings.py`
(with `.ai/local/floor-env.sh` sourced).

## Checks

Round 2 (at e55945a): full suite 1156 passed, 2 skipped, 2 xfailed, **no RERUN**
(`-rR`). The three plot test files three times without `--reruns`: all passed. Round 1:
1152 passed, no RERUN (an earlier round-1 run, before a typing fix in the new tests, had
10 reruns whose names weren't listed). `mypy --strict` on helab and tests, default
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
   note; the chooser and **Show plot window** bring the right window forward, and **Show
   plot window** also opens a closed settings section.
9. Drag a docked plot out and, without letting go, back into the plot area: the main
   panel keeps showing its settings throughout (no "Settings are in this plot's window"
   flash). Drag one out and let go: its settings move into its window once. Drag a floating
   plot back into the area: its settings come back at the drop. On Windows, also drag a
   floating plot by its title bar onto the area and check the settings come back.
10. Minimise a floating plot that is the shown plot: the panel switches to a visible plot.
11. Windows lab PC: floating windows there have Qt's own title bars; check the growth on
    open/close and the strip's look at the PC's scaling. Keyboard: Tab to the strip shows
    a highlight frame and Space opens it; clicking it shows no frame.

## Open questions

- Answered by Tony (2026-10-20): Show plot window opens the section (20224c8); a dragged
  plot's page moves only when the drag ends (cbc617d).
- Still as built: the floating window grows only on the click; floating a plot with its
  section open (floated before) takes the section's width from the plot, as Qt restores the
  window's earlier floating size.

## Proposed doc changes (for the Coordinator)

AGENTS.md › Script system, after "One Settings panel (top right, `PlotSettingsPanel`) shows
the active plot's settings: …":

> A floating plot's page moves into its window (`AnalysisDock.settings`, right of the plot,
> the same editors: edits and Rerun go with it) and back when it docks again; while the
> shown plot floats, the panel says "Settings are in this plot's window" with Show plot
> window, which raises it with its settings open. A plot being dragged keeps its page until
> it is let go (`DragEnd`: a filter on that dock only, during the drag). The section starts
> closed as a strip (▸, the plot's name and settings summary); open, its splitter sets its
> width; opening and closing widen and narrow the window so the
> plot keeps its size; open/closed and width last the session per plot. `AnalysisDock`'s
> `widget()`/`setWidget()` are the plot, inside a splitter frame.

Also: that paragraph currently says "One Settings panel (top right, `PlotSettingsPanel`)
shows the active plot's settings…" twice (the second ends "closing a plot shows the last
one shown before it"); the second copy can go.

`.ai/memory/results/analysis-plots.md` (or a new settled-decisions file): Tony's four
decisions of 2026-10-19 above, with the "Settings are in this plot's window" wording.
