# Review: Floating plot settings

Reviewer: Claude (Opus 5.5), fresh, read-only. Branch `agent/floating-plot-settings`, base 9f6ee5a, head 0c734ec (3 commits). I reviewed `git diff 9f6ee5a...HEAD`, the brief, the handoff, the notes and the screenshots, and ran an offscreen probe of my own (described below).

## Verdict

**No blocker. Ready to land.** All of Tony's four decisions are built as he described them. The hardening rules hold, every check passes, and the branch touches only the brief's paths. I found one latent low-severity issue (1) and two nits.

## Findings (most severe first)

1. **Low, latent: `AnalysisDock.setWidget` hides the old plot even when the new widget has taken it in.** `helab/models/ScriptTreeSelector.py:222-230`.
   - Qt's own `QDockWidget.setWidget` doesn't hide it in this case. When the old widget is reparented into the new one, Qt's layout drops it on `ChildRemoved`, so there is no "old" widget left to hide. The override keeps `_body` and calls `old.hide()`, so the plot inside the new wrapper stays hidden.
   - **Which path does it:** `HelabMainWindow._set_plot_source` (`helab/views/HelabMainWindow.py:917-922`, `_wrap_plot(dock, dock.widget())`). On an `AnalysisDock` it would leave the plot blank under its source line. The probe confirms this: `old body re-wrapped is hidden: True`.
   - **Why it doesn't matter today:** `_set_plot_source` has no production caller. Its only caller is `tests/test_folder_summary.py:332`, which uses a plain `QDockWidget`.
   - **Fix (one line):** hide `old` only while it is still ours, e.g. `if old.parentWidget() is self._body_holder: old.hide()`. A 3-line test would cover it.
   - Not blocking, but cheap to fix before landing.
2. **Nit: three blank lines before the new Live test.** `tests/test_live_plots.py:785-787`, before `test_a_floating_plot_runs_and_follows_with_its_settings_in_its_window` (PEP 8 wants two).
3. **Nit: the handoff says "Not pushed yet".** The branch has been pushed since; that line is now stale.

## Checks against the brief

1. **Moving the page (reparenting)**
   - Unapplied edits survive float → dock → float. Rerun works from the window and after re-docking.
   - The Live group (Follow Live off pins the plot), the source line and the catch-up all work while floating mid-run. `test_live_plots.py::test_a_floating_plot_runs_and_follows…` covers this.
   - Closing a floating plot mid-run through `close_plots` cancels the run, unpins its result and deletes the dock and page.
   - My probe:
     - Focus and typed text in the page while it is still in the main panel, then floating it: the text is kept, the note shows, and the closed section hides the page.
     - A floating dock deleted without being closed (its window went): the page is deleted with it, and the panel falls back to the remaining plot.
     - Closing in the order `LinkedAnalysisInstance.close` uses (page `deleteLater`, `removeDockWidget`, dock `deleteLater`, `remove_plot`): nothing left over.
   - Re-docking into a tab group: `test_redocking_into_its_tab_group` checks that it returns to the group and that `DockTabCloser` still closes the right plot. That test passes.
   - Many floating plots: `test_many_floating_plots_each_hold_their_own_page` passes.
2. **Hardening rules**
   - A floating plot still counts as shown. Activating its window shows it; the probe confirmed that floating a non-shown plot activates its window and shows it, as before.
   - A hidden floating plot falls back to a visible one (tested).
   - `close_plots` and closing the main window are unchanged and close floating plots too.
   - The chooser raises a floating plot.
   - `_focus_changed` now maps focus inside a floating page to its dock (the page's ancestor is now the dock), which is correct.
   - No event filter or `event()` override was added.
3. **Widening and narrowing**
   - `_widen` clamps a wider window to the screen's available width and moves it left when needed (tested). Narrowing isn't clamped, which is correct.
   - The splitter width is remembered per plot: in the probe it survived close/open and dock/re-float (350 px remembered, 350 px restored).
   - Opening the section in a 120 px window grew it to 449 px; the plot kept its minimum. Fine.
   - No leaks: after close, the dock, `frame`, `FloatingSettings`, `SettingsToggle` and the page are all deleted (probe). All of them are children of the dock, and the connections end with it.
4. **`widget()` / `setWidget()` still mean the plot.** I checked every call site: `_set_plot_source`, `set_plot_result` (it unparents the old wrapper before `findChild`, so no stale label is found), the `_show_content` fallback, `setup_dock_widget`, and both tests. `findChild("plot_data_source" / "plot_error")` can't match anything in the settings page, because no other code uses those names. Only finding 1 diverges from Qt's behaviour.
5. **The page moving during a drag (the worker's open question)**
   - Functionally harmless. The page goes to the window and back with its state intact, and the panel shows the note meanwhile.
   - Visible side effect: if that plot's section was left open, the drag window takes the section's width from the plot (or grows to the frame's minimum).
   - Deferring the move until the mouse is released would need an event filter or polling, which the hardening rules avoid. My recommendation: keep it as is and let Tony judge it on screen (checklist item 7 covers drags indirectly).
6. **Ownership:** the branch changes only `helab/models/ScriptTreeSelector.py`, `helab/views/HelabMainWindow.py` (plot-dock code only), the three plot test files and the session folder. Nothing in `io_helper`, `io_service`, `folder_cache` or `FolderExplorer`, and `parameter_tree.py` is unchanged.

The proposed AGENTS.md text and the removal of the duplicated "One Settings panel…" sentence are both right. I agree with the handoff's open question on **Show plot window**: opening the section on that click seems natural, but it's Tony's call.

## Reruns (floor root, venv and floor-env)

| Check | Result |
|---|---|
| `pytest -n 6 --reruns 5 --reruns-delay 1 -rR --basetemp=.ai/temp/pytest-review` | 1152 passed, 2 skipped, 2 xfailed in 48 s, **no RERUN** |
| `mypy helab/ --strict`, `mypy tests --strict` | clean |
| the same with `--platform win32` | clean |
| `pyright helab tests` | 0 errors |
| `pyright --pythonplatform Windows helab tests` | 0 errors |
| `git diff --check 9f6ee5a..HEAD` | clean |

Probe script (offscreen): `/private/tmp/claude-501/-Users-tonyyan-GitHub--maestri-floors-HeLab--agentfloating-plot-settings--maestri-roles-48acbf34-5a62-4718-ba82-c2ca0dd11786/c091775a-5ea2-4af1-9f6b-f3af55075a91/scratchpad/probe.py`.
