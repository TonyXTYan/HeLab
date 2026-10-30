# UI polish: working notes (Worker, 2026-10-30)

## RERUNs seen
- Partial run (accessible names + presets, -n 4), after the Q33.3/Q33.4 change:
  `test_accessible_names.py::test_every_script_and_each_library` "worker 'gw0' crashed", passed on
  rerun; the known QtWebEngine worker crash (known-issues: "QtWebEngine crashes xdist workers").
  Alone 3x and the same set 2x more: no crash.
- The crash recurred (2 of ~5 runs of accessible names + presets + debug runner menu, -n 4). The macOS
  crash reports (~/Library/Logs/DiagnosticReports/python3.13-2026-10-30-15*.ips) are **SIGSEGV**, not
  the known SIGTRAP: main thread, `QDockWidget` deleted (DeferredDelete) → children deleted →
  `QObject::destroyed` → `PyQtSlotProxy::unislot` → a Python slot → segfault in
  `_PyEval_EvalFrameDefault`. A Python callable (proxy: a lambda or plain function, not a bound
  QObject slot) connected to a destroyed signal of a widget inside a plot dock: the likely one is
  `helab/analysis/panes.py:32` (`PlotlyPane`: `self.destroyed.connect(lambda *_: server.remove_plot(plot_id))`).
  **The base commit 43cb202 crashes the same way** (a temporary worktree, the same three files 4x:
  3 crashes, same SIGSEGV stack in the newest report), so it is not this floor's. Not an owned path:
  proposed as a follow-up in the handoff.
