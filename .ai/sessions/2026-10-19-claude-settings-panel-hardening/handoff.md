# Handoff: Settings panel hardening

Branch `agent/settings-panel-hardening`, base 486cf56, seven commits (one per brief item),
not pushed. Details, measurements and probes: [notes.md](notes.md).

## What changed

| # | Commit | Change |
|---|---|---|
| 1 | 9495b56 | The Settings panel follows `QApplication.focusChanged`, `focusWindowChanged` and `tabifiedDockWidgetActivated` instead of an app-wide Python event filter (+0.35 µs of Python on every event, one more filter per panel ever made). Plot docks take click focus. Native slots end with the panel; `detach()` ends them, called from `HelabMainWindow.closeEvent`. Focus Qt moves because the focused widget was hidden shows nothing. A dock deleted unclosed (window teardown) now ends its `AnalysisInstance` (now a `QObject`; was left connected to the app-wide runner with its result pinned) and the panel drops its page. |
| 2 | 904b559 | Test only: 20 plots (five floating), chooser order and titles, separate pages and edits, fallback order, nothing left after closing (widgets deleted, instances collected, results unpinned). |
| 3 | 79f504b | `TreePanelWidget.tab_target` defines where a new plot goes (below). The new dock is shown right after `addDockWidget`: Qt shows it later otherwise, and won't tab another plot with a hidden dock, so plots opened in quick succession sat side by side. |
| 4 | 43fe9dc | `DockTabCloser` matches a tab to its dock by identity (Qt keeps the dock's address as tab data), not by title; its event filter on the plot area became dock signals. |
| 5 | a854f9f | The RHI surface is made only on macOS's own windows (`cocoa`), never offscreen or on Windows/Linux; `QtQuickWidgets` is imported only there. |
| 6 | 718d963 | Offscreen tests of every activation source. Fix: showing a plot by its tab, window or the chooser moves focus left in another plot to the shown plot, so a click back in that plot shows it again (the focus approach otherwise missed it). |
| 7 | a345e56 | `UnitSpinBox` parses strictly (fixes "5 m" → 5 s, "5 abc" → 5 as, "95,5" → 9 %, "4.5" → 4 in whole-number boxes) and clamps to the limits (below). |

No visual change, so no screenshots.

## Decisions

- **Typed numbers beyond a setting's limits are set to the nearest limit** when the edit
  ends (Enter or leaving the box), e.g. 150 in a 0–100 % box becomes 100 %. Before, the box
  went back to its old value. The box still outlines red while the typed number is out of
  range. Approved by Maestro; `tests/test_analysis.py` changed in one assertion ("20" in
  Point size → "10 px", "Above the limit: set to 10 px.").
- **What a typed number means** (plot settings): a bare number is in the unit and SI prefix
  shown ("5" in "4 ms" is 5 ms, "1e-3" there is 1 µs); a prefix without the unit applies
  ("5 m" → 5 ms, "5 u" → 5 µs); with the unit it is as written ("5 s"). The decimal mark is
  "." or the locale's comma; a comma is invalid where it isn't the decimal mark. A fraction
  in a whole-number box, letters, inf and empty input are invalid (value comes back).
- **Where a new plot goes:** tabbed with the plot whose settings show if it is docked, else
  with the newest docked plot. Floating plots are never the target (Qt would place the new
  one in the floating plot's old slot, next to an unrelated plot). A plot hidden on its own
  (unticked in the plot area's right-click menu) is never the target; one hidden inside a
  tab group stands for that group. With none docked (none open, or all floating or
  hidden), the new plot docks on its own, never floating.
- **Activation without per-event Python:** a click anywhere in a plot works because plot
  docks take click focus and Qt walks up to them; floating windows through
  `focusWindowChanged`; tabs through the tab signal. Re-activating the main window shows
  the plot that had focus in it.
- Tab close buttons rely on Qt storing the dock as tab data (Qt 5/6 internal behaviour); a
  test guards it, and if Qt ever changes it the × closes nothing rather than a wrong plot.

## Checks

- `pytest -n 6 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`: 1072 passed, 2 skipped, 2 xfailed, no RERUN, twice (33 s, 31 s).
- `mypy helab/ --strict`, `mypy tests --strict`, `mypy tests --strict --platform win32`: clean.
- `pyright helab tests`, `pyright tests --pythonplatform Windows`: 0 errors.
- `git diff --check 486cf56 HEAD`: clean.
- Once, early on, `pytest tests/test_analysis_gui.py tests/test_script_system.py -x` after a
  failing assertion ended in a Fatal Python error during teardown. It never came back (6
  loops, deliberate failures with open and floating plots, the full suite).

## Tony's on-screen checklist

Replaces the MANUAL_TODO item "Settings panel follows the active plot". On the Mac, then a
lab PC (Windows):

1. Three plots open, tabbed. Clicking a tab, clicking inside a plot (counts, a histogram,
   the 3D scatter's web view), on a plot's title strip, and Tab-ing into a plot each show
   that plot's settings.
2. The 3D scatter: a click in the web view switches the settings to it (on the lab PC too,
   even with the black pane). If it doesn't, tell me which machine.
3. Float a plot: clicking its window (title bar or inside), Cmd-` / Alt-Tab to it, and back
   to the main window: the settings follow (back in the main window: the plot clicked last
   there).
4. Plots side by side (drag one out of the tab group and dock it beside): click A, click
   B's tab, then click A again: A's settings come back.
5. The chooser raises the plot it names (a floating one comes to the front); unapplied
   edits survive switching; ✕ and a tab's × close the right plot; closing the shown plot
   shows the one shown before it.
6. Open a plot while all others float: it docks in the plot area on its own; the next one
   joins it as a tab. Open two plots quickly (double-click a Run button): they are tabbed.
7. Drag a tab out to float it and dock it back onto another plot: the new tab group has ×
   buttons.
8. Typing in plot settings: "5" in a box showing ms, "5 m", "5 k", "-5", an empty box,
   "abc", and a number beyond the limits (red outline while typing, then the nearest limit
   on Enter). On a lab PC, check what the boxes show as decimal mark and that typing it works.
9. The RHI fix: opening the first 3D scatter doesn't close and reopen the window on the Mac
   (unchanged item in MANUAL_TODO; the lab-PC question stays open).

## Proposed doc changes (for the Coordinator)

- **AGENTS.md, Script system** (the Settings panel sentence): "One Settings panel (top right,
  `PlotSettingsPanel`) shows the active plot's settings: the plot last clicked, focused or
  brought to the front among tabbed docks, floating ones included. It follows Qt's focus,
  active-window and tab signals (no event filter; plot docks take click focus); showing a
  plot moves focus left in another plot to it. Its chooser names the plot and raises
  another, each plot's page keeps its edits, and closing a plot shows the last one shown
  before it. A new plot is tabbed with the shown plot if docked, else the newest docked one
  (never a floating or lone hidden one; none: it docks alone; `TreePanelWidget.tab_target`).
  Tab × buttons find their dock by identity (`DockTabCloser`). Typed numbers in settings
  (`UnitSpinBox`): a bare number is in the unit shown, a prefix alone applies, "." or the
  locale's comma, and beyond the limits the nearest limit."
- **AGENTS.md, Visualization or UI**: the RHI surface note: "made only on macOS's own
  windows (`HelabMainWindow.needs_rhi_surface`: cocoa), never offscreen."
- **roadmaps/_readme.md**, the Settings panel line: hardening done (event filter replaced,
  many plots, tab rule, tab close by identity, activation sources, typed numbers); left
  open: real-screen checks (MANUAL_TODO) and a pin to keep one plot's settings.
- **.ai/MANUAL_TODO.md**: replace "Settings panel follows the active plot" with the
  checklist above (items 1–8); keep the RHI item as it is.
- **.ai/memory/results/analysis-plots.md** (or a new results file): typed numbers clamp to
  the limits (Maestro-approved 2026-10-19), and the new-plot tab rule.
