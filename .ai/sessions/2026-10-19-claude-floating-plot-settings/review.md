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

## Recheck at b93fbe5

Range 0c734ec..b93fbe5 (pushed; local HEAD matches): 20224c8 (Show plot window opens the section), cbc617d (`DragEnd`), e55945a (my `setWidget` finding, plus the blank line), b93fbe5 (handoff and notes for round 2). The worker committed review.md in b93fbe5, so this section shows up as an uncommitted change to a tracked file.

### Verdict

**No blocker. Ready to land.** All three round-1 findings are fixed. Below are one doc nit and one note.

### Checks

1. **`setWidget` fix** (`ScriptTreeSelector.py:222-235`). The old plot is hidden only while it is still in `_body_holder`. A widget that wraps it keeps it shown. `test_a_plot_wrapped_in_place_stays_shown` covers both branches.
2. **Show plot window** (`raise_current`). It opens a closed section only when the shown plot's page is in its window. A second click leaves an open section as it is. The chooser still only raises the window. Tested.
3. **`DragEnd`: the filter is always removed.** It is installed only with `dock.installEventFilter(self)`, on a plot dock whose `topLevelChanged` or `dockLocationChanged` fired while a mouse button was down. There is no app-wide filter; `grep installEventFilter` in the module finds that one call only. My probe (`scratchpad/probe2.py`, offscreen, with a counting `eventFilter` and `mouse_held` controlled) checked each exit:
   - **Release:** the filter sees no more events afterwards, and the page moves once.
   - **Closed mid-drag** (the `LinkedAnalysisInstance.close` order): `remove_plot` calls `stop`. The waiting list is empty, the filter sees nothing more, and the dock is deleted.
   - **Deleted unclosed mid-drag:** `_forget_deleted` → `remove_plot` → `stop`. The waiting list is empty, and `removeEventFilter` is skipped on the deleted dock.
   - **Main window closes mid-drag:** `close_plots` → `remove_plot` → `stop`. If the panel goes first, `DragEnd` is its child and is deleted. Qt holds event filters as `QPointer`s, so the dock's later events are safe (probe: no crash).
   - **Can it leak or stay installed?** `_waiting` holds only open plots, and every way a plot ends passes through `remove_plot`. While a drag waits, the cost is one Python call per event on that one dock.
4. **The 0 ms coalescing can't place on a deleted or closed dock.**
   - `_place_moved` skips deleted docks.
   - `remove_plot` drops the dock from `_unplaced`.
   - `_place` returns for a dock with no page.
   - Probe: a dock deleted between the release and the timer gives no crash and leaves `_unplaced` empty.
   - A float and re-dock within one pass is resolved once, from the final state.
5. **The two changed existing tests are legitimate.** I checked both in scratch worktrees at 0c734ec and b93fbe5 (since removed).
   - **Twenty plots, fallback now plot 16:** at 0c734ec, adding one event-loop pass after floating gives the same 16. In offscreen, each floating window activates as it comes up, so plot 16 (the last one floated) enters `_recent`. The expected value changed only because the test now waits for the pages to move. The fallback rule itself is unchanged.
   - **Show plot window re-showing plot 2:** after the main window is reactivated, 0c734ec left focus outside any plot (plot 2 stayed shown). b93fbe5 restores focus into plot 1, so plot 1 shows. The reason is that the page now reaches the floating window a pass later, which changes where focus lands. Both outcomes follow the hardening rule "focus moved into a plot shows it". The test's added `show_plot(two)` sets up what it means to test (the button) and doesn't hide a regression. On screen: clicking back into the main window may now show the plot that last had focus there. That is consistent with the rule.

### Nit and note

- **Doc nit:** the `DragEnd` docstring, notes.md and the handoff all list a **mouse move** as ending a wait after a release the dock never saw. A plain move with no button down never reaches a `QDockWidget` without mouse tracking: Qt's `notify` passes it to the parent instead (probe: a synthetic `MouseMove` didn't reach the filter). In practice the wait ends on Enter, Leave, `NonClientAreaMouseMove`/`Release` or a release on the dock. That still covers the Windows native title-bar case: moving off the title bar into the window, or leaving it, ends the wait. The behaviour is fine; only the wording overstates it.
- **Note:** the AGENTS.md wording the handoff proposes correctly names the one exception to "no event filter" (`DragEnd`, on that dock, during the drag). The panel's docstring now says the same. Its long line (`ScriptTreeSelector.py:1148`, 148 characters) could wrap like its neighbours.

### Reruns (floor root, venv and floor-env, at b93fbe5)

| Check | Result |
|---|---|
| `pytest -n 6 --reruns 5 --reruns-delay 1 -rR --basetemp=.ai/temp/pytest-review` | 1156 passed, 2 skipped, 2 xfailed in 38 s, **no RERUN** |
| `mypy --strict` helab and tests, default and `--platform win32` | clean |
| `pyright helab tests`, default and `--pythonplatform Windows` | 0 errors |
| `git diff --check 9f6ee5a..HEAD` | clean |
