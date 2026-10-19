# Notes: Settings panel hardening

Floor "Settings panel hardening", branch `agent/settings-panel-hardening`, base 486cf56.

## 1. App-wide event filter

Measured (`.ai/temp/filter_cost.py`, offscreen, M-series Mac, PyQt 6.11): a synthetic
MouseMove `sendEvent` costs 0.17 µs without the panel and 0.51–0.53 µs with its app-wide
filter installed (+0.35 µs per event). Cheap in absolute terms, but it is a Python call (GIL
acquire, `isinstance`, a tuple test) on **every** event of every object in the app: mouse
moves, hover, paint, timers, posted I/O deliveries. Every panel ever made added one more
(the test `Window` made an unparented panel per test, never deleted: N filters by the end
of a run), and the filter needed a `getattr(self, "_pages")` guard for interpreter teardown.

Replaced with Qt signals that fire only on change:
- `QApplication.focusChanged(old, now)`: a click or keyboard focus inside a plot. Each plot
  dock now has `ClickFocus`; Qt's click-to-focus walks up from the clicked widget to the
  first click-focusable ancestor, so a click on a label, the dock title or a NoFocus plot
  focuses the dock (pyqtgraph's PlotWidget is StrongFocus itself; QWebEngineView forwards
  focus to its render widget child).
- `QGuiApplication.focusWindowChanged(window)`: a floating plot's window activated, matched
  by `dock.windowHandle() is window`.
- `tabifiedDockWidgetActivated` (as before).
All are `@pyqtSlot`s, so they are native Qt connections that end when the panel is
deleted; `detach()` ends them at once and `HelabMainWindow.closeEvent` calls it.

Focus that moves only because the focused widget was hidden (its dock went behind another
tab on screen, or closed) is ignored (`old` not visible): Qt moves focus to the next
tab-focusable widget, possibly in a third plot, which would otherwise show that plot and
spoil the fallback order.

Lifetime fixes found on the way:
- A dock deleted without a close event (window teardown; tests deleting the plot area) left
  its `AnalysisInstance` connected to the app-wide `AnalysisRunner.finished` forever (and its
  result pinned). The instance is now a `QObject`; `dock.destroyed` → its `close` slot.
  PyQt quirk: a plain Python callable connected to `destroyed` never ran (PyQt's own slot
  proxy for that dock disconnects itself first, on the same signal), so it must be a
  decorated slot of a QObject receiver. `TreePanelWidget` forgets an instance on its
  `ended` signal instead of a lambda on `closed`.
- The panel drops pages of docks deleted unclosed (`_forget_deleted`, a slot on `destroyed`).
- The test `Window` now parents its panel and deletes its plot area at teardown.

Unexplained: once, the first run of `tests/test_analysis_gui.py tests/test_script_system.py
-x` after a failing assertion ended in a Fatal Python error at teardown (stack showed only
threads). Not reproduced in 6 loops nor with deliberate failures with open/floating plots.

## 2. Many plots

`test_twenty_plots_tabbed_and_floating`: 20 plots opened at once (no waiting for docks to
show), five floating. The chooser lists them in opening order with unique titles
("Blocking (n) · run · rev 1"; the id is a per-panel counter, never reused). Each plot's
page keeps its own values and its own current settings tab across chooser switches.
Closing falls back to the most recently shown plot still open (floating or not), then to
the newest never shown; closing a plot that isn't shown leaves the shown one. Once all are
closed: no docks, pages or plot widgets survive (`sip.isdeleted`), the panel is back to
the hint with an empty chooser, `dock_widgets` and `_analysis_instances` are empty, every
`AnalysisInstance` is garbage-collected (weakrefs dead after `gc.collect()`) and none of
their results stays pinned. Results stay in the RAM results store (R1) until its budget
drops them, by design. No code change was needed beyond item 1's.
