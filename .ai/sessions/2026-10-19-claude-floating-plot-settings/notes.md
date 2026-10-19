# Notes: Floating plot settings

## Design

- **Where the page goes.** `AnalysisDock` keeps one permanent frame as its Qt widget: a
  horizontal `QSplitter` with the plot (a holder) on the left and `FloatingSettings` on the
  right, hidden while docked. The dock's Python `widget()` / `setWidget()` are overridden to
  mean the plot, so `HelabMainWindow._wrap_plot`, `set_plot_result`, `_set_plot_source`,
  `AnalysisInstance._show_content` and the tests' `dock.setWidget(...)` are unchanged. A
  replaced plot stays a hidden child of the dock until its owner deletes it, as in Qt's own
  `setWidget`. Qt itself never calls `widget()`/`setWidget()` (non-virtual), and
  `findChild` sees through the frame.
- Floating moves only the settings page; the plot never changes parent, so a web view
  (3D scatter) isn't reparented when a plot floats or docks.
- **Who moves it.** `PlotSettingsPanel` connects each `AnalysisDock`'s `topLevelChanged`
  (`_floating_changed` → `_place`): floating, the page leaves the stack
  (`stack.removeWidget`) for `dock.hold_settings(page)`; docked, `settings.release()` and
  back into the stack. If the dock is the shown plot, the stack shows the page or the
  **away note** ("Settings are in this plot's window" + **Show plot window**, which calls
  `show_plot(dock, raise_dock=True)`). `show_plot` picks page or note by whether the page
  is in the stack. `remove_plot` releases the page from a live dock and removes it from the
  stack only if it is there. No event filter or `event()` override was added (the
  hardening test still checks the panel).
- **Section.** `SettingsToggle` (a `QAbstractButton`, checkable: checked = open) paints the
  header: open, one line "▾  name · summary", elided, size policy (Ignored, Fixed); closed,
  a strip as wide as a line, "▸" upright at the top and the text running down (rotated
  90°). Tooltip: "Show/Hide this plot's settings", name, summary. Name = the chooser's title
  (`set_title`: "Counts per shot (1) · run_042 · rev 12"); summary = the dock's
  `plotSourceSettings`, set in `HelabMainWindow.update_plot_source`. Space works (it's a
  button). The focus frame draws only for Tab/Backtab/shortcut focus: activating a floating
  window focuses its first focusable widget, which framed the strip every time.
- **Widths.** Closed: the section is fixed at the strip width and the splitter handle is
  disabled with an arrow cursor. Open: min 160 px, default 300 px, set by dragging the
  handle (`splitterMoved` records `open_width`). `set_settings_open` fixes the section at
  its new width, widens/narrows the floating window by the difference (`_widen`: wider is
  clamped to the screen's available width and moved left if its right edge would leave
  it), then sets the splitter sizes explicitly. Without the explicit `setSizes`, closing
  left stale splitter sizes ([96, 300] with a 21 px strip: a gap where the section was).
  `hold_settings` also sets the sizes, else a section floated again open came back at its
  160 px minimum instead of its width.
- Floating doesn't widen the window (only the click does): Qt restores a dock's earlier
  floating geometry when it floats again, so widening on every float would add up.

## Measurements (offscreen, 800 px screen)

From `render_floating_settings.py`:

```
floating, closed: window 460 · plot 435 · settings 21 (open False)
open: window 739 · plot 435 · settings 300 (open True)
dragged 80 px wider: window 739 · plot 355 · settings 380 (open True)
closed again: window 380 · plot 355 · settings 21 (open False)
open again (remembered width): window 739 · plot 355 · settings 380 (open True)
```

## Checks

- Full suite (`pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest -rR`):
  1152 passed, 2 skipped, 2 xfailed, no RERUN. An earlier full run (before the typing fix
  in the new tests) had 10 reruns, names not listed (`-q` without `-rR`); its only failures
  were the two `test_typing` tests for those typing errors.
- The three plot test files five times in a row without `--reruns`: 101 passed each time.
- `mypy --strict` on helab and tests, default and `--platform win32`: clean.
- `pyright helab tests`, default and `--pythonplatform Windows`: clean.
- `git diff --check`: clean.
