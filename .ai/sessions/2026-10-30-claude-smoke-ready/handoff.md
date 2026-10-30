# Handoff: smoke ready (Beacon, Worker; `agent/smoke-ready`, base `9f0b21f`)

Phase A (brief.md items 4, 1, 2 and phase B item 1, the IDs) is done; phase B items 2–5 follow
(brief-phase-b.md). Details and Qt source references: [notes.md](notes.md); first plan:
[plan.md](plan.md).

## Phase A: what changed

- **`helab/utils/accessible.py`** (new; first in `helab/views/`, moved for the review's H2 so the plot
  libraries' and scripts' controls use it without importing views): `identify(widget, id, name="",
  description="")` sets the objectName and the accessible identifier (the same ID), and the name and
  description when given; `identify_action` names a toolbar's button for an action;
  `identify_buttons` gives a button box's or message box's buttons IDs; `id_part` makes a script or
  profile ID safe in an ID.
- **Plots' own controls** (review H2, approved for names/IDs at the line each is made): Plotly's
  "Open in browser" (`plotly_open_in_browser`, `helab/analysis/panes.py`), Matplotlib's toolbar
  (`mpl_<tool>`: `mpl_home`, `mpl_zoom`, …, `helab/analysis/backends.py`), Release time's "Use for
  this folder…" (`release_use_for_folder`) and Density images' "Copy circles"
  (`density_copy_circles`). `AnalysisDock.setWidget` prefixes a drawing's control IDs with the plot's
  number (`plot_<n>.plotly_open_in_browser`), so two plots side by side never share one (Qt's own
  `qt_…` parts keep theirs).
- **Every interactive control in `helab/views/`** has an accessible name and an ID: the toolbars'
  icon-only buttons, status-bar buttons, folder tabs and their close buttons ("Close folder tab:
  <title>", `close_folder_tab_<n>`), each tab's tree and path bar, the summary rows' buttons (the two
  "Review…" now "Review mismatched data" / "Review data root"), the Scripts panel (Group combo,
  Load Scripts…, each run button "Plot <script>" with ID `run_<analysis id>_<action>`), the plot area
  (Settings panel chooser and ✕, each plot's TXY row, preset bar, Rerun, released plot's Reload, the
  floating settings toggle, each plot tab bar and close button "Close plot tab: <title>",
  `close_plot_tab_<plot number>`), every parameter of a plot's settings (pyqtgraph's editors
  `param_<group>.<name>`, named by their title, and their reset buttons `…_reset` "Reset <title>"),
  Settings and its six tabs, every dialog and tool window, and the buttons of message boxes built
  with `QMessageBox(...)`. Labels a runner reads (summary lines, Folder details values
  `details_<row>`, status bar, plot source/status lines, central hint) get IDs only.
- **Debug menu** (`HelabMainWindow`): Run Plot ›, Script Group ›, Show Plot Tab ›, Close Plot Tab ›,
  Settings Tab ›, Save Window Screenshot…, Save Screenshot of Window ›. Filled from memory as they
  show; each calls its control's path (the run button's `click()`, the Group combo's
  `setCurrentIndex`, the Settings panel's `show_plot(raise_dock=True)`, the dock's `close()` as the
  tab ×, `show_settings_dialog(tab=…)`). Unavailable items are disabled with a "(reason)" line
  ("load a folder's data first", "no plots open", "close the open dialog first").
  `SettingsDialog.TAB_TITLES` and `show_tab` (new) back Settings Tab.
- **Screenshot**: `QWidget.grab()` of the HeLab window active when the Debug menu opened (on macOS
  the menu bar leaves the front window active: a floating plot or tool window; on Windows/Linux
  opening the menu activates the main window, so Save Screenshot of Window › lists every visible
  HeLab window by title). PNG to a path picked in a save dialog that starts in the temp folder's
  `screenshots/` (`helab-<window>-<time>.png`); a status-bar notice names the file.
- **Tests**: `tests/test_accessible_names.py` (the walk, its self-test, and the class guard);
  `tests/test_debug_runner_menu.py` (each Debug item and the screenshot).

## The test, and how to add a window (for testing.md)

`tests/test_accessible_names.py` opens each window and dialog (the real main window with a
synthetic TXY folder loaded, two PyQtGraph plots tabbed, one released and one floating; the main
window again with **every script of every group** run once (both run buttons) and Counts per shot in
each Library; Settings at each tab and the profile editor; eleven dialogs and tool windows and
Correlations' drawing on a cache whose helpers never run; six message boxes HeLab builds, caught as
they open), walks every control of the interactive classes (`QAbstractButton`, `QComboBox`, `QLineEdit`,
`QAbstractSpinBox`, `QAbstractSlider`, `QTabBar` and each tab, `QAbstractItemView`, editable
`QTextEdit`/`QPlainTextEdit`; less a control's own parts, listed in `part_of_another`) and fails
listing each without a name or ID, whose accessible identifier isn't its ID, or whose ID repeats
among the controls its window shows. Hidden controls are checked for a name and ID too. PyQt6
doesn't bind `QAccessible`, so `effective_name` follows Qt 6.11's rules (notes.md).
`test_every_widget_class_is_walked_or_skipped_with_a_reason` imports every module of `helab/views`,
`helab/analysis` and `helab/scripts` (less `legacy_plotly`) and fails on a `QWidget` subclass that no
case opens (`covers(...)` on a case, `DIALOGS`) and that `SKIPPED` doesn't list with a reason (none
today). Not classes, so out of the guard's sight: `INLINE_SKIPPED` lists, with why, the dialogs Qt
builds itself (`QMessageBox.question` and its kin, `QInputDialog.getText/getInt`, whose field Qt
names by its label, `QFileDialog`) and HeLab's boxes built from live state no case opens. Combo boxes:
the test checks the name Qt gives on Windows; on macOS and Linux Qt names a combo by its current
choice (see the runbook line below). **A new window or dialog:** add a builder to `DIALOGS` (or a
case with `@covers`), with synthetic data if its controls need a folder or a plot; a new message box
built where it asks: an entry in `ASKS`.

## Phase B items 5 and 6: Quit that confirms, and the quit window's list

Merged `origin/dev/v0.0.7` at c492242 (TXY Index) first: one conflict, `QuitSaveDialog`'s imports
(both kept); its CacheTab changes (the converted row's texts and tooltip) bring no new control.

- **The quit window lists every operation** (`FolderCache.quit_entries()`, the approved sibling of
  `quit_saves()`, which still returns the folders as strings and is derived from it): a typed
  `QuitSave(kind, path, state, started)` per operation. Kinds `QUIT_*`: Live's new shots, a load's save
  (`its data`), a folder's flags, its constants, a plot's result, Make room for one, presets, the
  converted TXY's last uses (`TXY_LAST_USED`), and a conversion still running. States: reading,
  writing, waiting (for the folder's previous save, or for the saved presets), held (for the store's
  identity check: `_probe_held`, the brief's "held writes"), converting. Starts from what the cache
  already keeps (`SharedJob.created`, `_finishing_created`, `_started`, `_result_ops`, the flush's
  start) plus two hooks: `_deferred_since` (when a save began waiting) and `_finishing_live` (whether
  a finishing write is Live's). `quit_save_started(entry)` now gives any entry's earliest start.
  `QuitSaveDialog` shows one line each, `<folder> — <kind>, <state> · <m:ss>`, updated in place every
  250 ms from memory, and closes by itself when none is left; Quit now as before.
  - **One new wait:** a conversion still running (auto-convert's `convert` job) is now waited for;
    before, quitting killed it with the helpers. It writes each TXY under a temporary name, so Quit
    now loses only the shot in progress. Tony may prefer it listed but not waited for: **Q~4**.
- **Quit that confirms** (`helab/views/quit_watch.py`, called from `main.py` once `app.exec()`
  returns): the process ends within `GRACE` (1 s) of its event loop ending; if Python's teardown still
  runs then (a non-daemon thread, an exit handler, a stuck pipe), it logs every thread's stack and ends
  with the same exit code (`os._exit`). Before the loop ends, nothing changed: with nothing to save
  the window closes at once (a test: under 1 s); with saves pending the quit window shows why,
  closing itself when they end or on Quit now. **The flush's grace fits before it:** the last uses'
  flush is a quit save like the others (shown in the window, `MARK_FLUSH_TIMEOUT` 5 s without progress,
  Quit now skips it), so the 1 s watch only starts after the window has closed. The known issue "File ›
  Quit sometimes left the process running": its cause isn't known (a click landing before the menu
  opened may have quit nothing, and the runner then started a second HeLab); whichever it was, a HeLab
  whose windows have closed can no longer stay running more than a second, and a runner confirms the
  quit by the process exiting (or reads Dump State's `window.closing` while the quit window waits).
- **Tests**: `tests/test_quit_confirms.py`: the watch (in-process, and a real process with a
  60 s non-daemon thread ending with its exit code in under the grace), quitting with nothing to save
  in under a second, every kind as an entry with its state and start, the window's lines and closing by
  itself, Quit now. Four existing tests' expected lines updated to the new format (`test_live.py`,
  `test_result_cache_quit.py`, `test_presets_store.py`, `test_txy_last_used_quit.py`).
- **Docs proposals:** `live.md`'s quit paragraph: "Quitting waits for every operation
  `FolderCache.quit_entries` lists (Live's new shots, a load's save, flags, constants, a result or Make
  room, presets, last uses, a running conversion); the quit window shows each with its folder, state and
  run time and closes when they end; Quit now skips them; the process then ends within 1 s
  (`quit_watch`)." The dialog's docstring is updated in the code. An AGENTS.md line is not needed.

## Review fixes (Wren, review.md)

- **H1** (the rerun on all three OSes): **a real bug since 0.0.6a1, fixed.** `DockTabCloser`
  connected each dock tab bar's `tabCloseRequested` to a lambda capturing the bar (9c477c2). Qt makes
  those bars (`QMainWindowLayout`; HeLab finds them with `findChildren`), so sip keeps no reference to
  their Python wrappers; wrapper and lambda form a cycle, and the first full `gc.collect()` after the
  bar is fitted clears it: the Qt connection stays but calls nothing (Wren reproduced it in
  isolation; my CI-order instrumentation showed the emit never reaching `close_tab` while a direct
  call worked). So **a plot tab's × went dead soon after its tab bar was made**, for mouse clicks
  too: that is known-issues' "A plot tab's x didn't respond to computer-use clicks" (pointer clicks;
  the dock title's ×, Qt's own button, has no lambda). The order dependency in CI was only when a
  collection fell between the fit and the test's emit. Fixed by a bound `pyqtSlot(int)` reading the
  bar from `sender()` (a plain Qt connection, no Python proxy); the comment at the connection names
  the mechanism. `test_a_plot_tabs_close_button_closes_that_plot_when_clicked` now drops its
  reference to the bar and collects before the click: it fails with the old lambda (checked) and
  passes now. CI's group 1/2 command ran clean three times locally, and CI 40984390827 had no RERUN.
  - **Release notes:** "A plot tab's × works again: it stopped responding soon after the tabs
    appeared (0.0.6a1–0.0.7a1)."
  - **Proposed rule** (app-runtime-and-ui.md, and a line in AGENTS.md under UI): never connect a
    lambda (or `functools.partial`) that captures the sender when Qt made the sender (found with
    `findChildren`, `tabBar()`, `widgetForAction`, …); use a bound slot and `sender()`.
  - **A~3** A test guard from Wren's AST scan: fail on `X.<signal>.connect(lambda …)` whose lambda
    refers to `X` where `X` comes from `findChildren`/`findChild`/`tabBar()`/`widgetForAction`. Cheap
    for the direct form (Wren's scan finds 14 such connections, all safe today); it would miss a
    sender reached through another name, so it backs the rule rather than replaces it.
- **H2**: done as above (approved files), the test runs every script and each Library, the guard
  covers `helab/analysis` and `helab/scripts`.
- **H3**: docs: the test's docstring (macOS and Linux), the runbook line on combos, M~3.
- **L1**: Debug items do nothing when their run button, plot or window is gone (`sip.isdeleted`).
- **L2**: six message boxes walked (`ASKS`), the rest in `INLINE_SKIPPED` with reasons; docstring fixed.
- **L3**: the runbook line on parameter editors.
- **N1**: a plot tab bar's ID is `plot_tabs_<its first tab's plot number>`: Qt makes and retires
  bars as plots are tabbed (`unuseTabBar` deletes them), so no ID can stay with a bar; the close
  buttons' IDs (each plot's number) are the stable ones. No fallback ID for docks that aren't plots
  (there are none; the walk would flag one).
- **N2**: the self-test covers a control with no ID and a tab without a name.
- **Re-review** (Wren, R1, R2, nits): H1's cause and A~2 rewritten as above, the connection's comment
  names the mechanism; the × test collects before its click (R2); Matplotlib's private `_actions`
  read with a default, so a rename only loses the IDs; `--geometry` followed by another option keeps
  that option for Qt instead of taking it as the value (a test).
- **N3**: the screenshot (and Dump State) write stays on the GUI thread: one folder in HeLab's temp
  folder and one small file the user picked, as Settings' profile export does (a comment says so).

## Checks

- After the review fixes (on top of phase B 2–4): full suite (`-n 4 --reruns 5 --reruns-delay 1`)
  8222 passed, 669 skipped, no RERUN; CI's group 1/2 command locally 4099 passed, 322 skipped, no
  RERUN (three times since the H1 fix); the five type checks clean.
- Phase A, as committed (94ed478):
- Full suite twice (`-n 4 --reruns 5 --reruns-delay 1`): basetemp `.ai/temp/pytest` 8200 passed,
  669 skipped, **no RERUN**; basetemp outside the checkout (a path with a space, in the scratchpad)
  8200 passed, 669 skipped, no RERUN. (An earlier run had 6 failures with 30 reruns, all mine:
  `tests/test_load_queue.py`'s `CancelTestWindow` has no Scripts panel; fixed before these runs.)
- `mypy helab/ --strict`, `--platform win32`, `mypy tests --strict`, `pyright helab tests`,
  `pyright --pythonplatform Windows helab tests`: clean.
- GUI on this Mac (cocoa, floor-env.sh sourced, a synthetic folder in a temp dir): grabs of a
  PyQtGraph, a Matplotlib, a Plotly (QtWebEngine) and the 3D scatter (Plotly) plot all came out as
  drawn, and the main window's grab shows its docks.

## Proposed doc changes (for the Coordinator)

- **AGENTS.md**, under UI: "Every interactive control has an accessible name and a stable ID
  (`helab/utils/accessible.py`, `identify`; test-enforced: `tests/test_accessible_names.py`)."
- **app-runtime-and-ui.md**, a paragraph "Accessible names, IDs and the runner's Debug items": the
  `identify` helpers and the ID rules (unique among a window's shown controls; per-item IDs from the
  script's analysis ID, the plot's number, the folder tab's number; never from text); Qt 6.11 maps the
  accessible identifier to AXIdentifier (macOS) and AutomationId (Windows); the Debug items above and
  what each calls; the screenshot's target rule and folder.
- **testing.md**: the paragraph "The test, and how to add a window" above.
- **smoke-automation.md**: items 1, 2 and 4 done (this floor); item 5 answered: the existing Debug
  menu (Q5.2.5); item 3 still v0.0.8.
- **Runbook** (`.ai/sessions/2026-10-28-claude-smoke-automation/plan.md`), what a runner uses now
  instead of pixels: Debug › Script Group › <group> instead of the Group combo's popup; Debug › Run
  Plot › Plot <script>; Debug › Show/Close Plot Tab › <title> instead of the tab and its ×; Debug ›
  Settings Tab › <tab>; Debug › Save Window Screenshot… for each `Shot:` (type the path in the save
  panel); `app_ax_find` by name ("Folder path", "Check folder status", "Live", "Cancel loading",
  "Apply preset", "Rerun with these settings") or by AXIdentifier (`folder_path`, `live`, `run_…`).
  **Combo boxes by AXIdentifier only** (`script_group`, `preset_combo`, `txy_source`, `txy_profile`,
  `plot_chooser`, the Settings combos such as `load_mode`): on macOS Qt titles a combo by its current
  choice, not its name (`QAccessibleComboBox`, `Q_OS_UNIX`); or Debug › Script Group for the group.
  **A plot parameter's editor shows only while its row is selected** (pyqtgraph hides it, and Qt
  hides hidden widgets from accessibility): select the row in `plot_settings` first, then
  `param_<group>.<name>` is there; Return now takes the value and closes it, Escape cancels.
  The same caveat goes into the `app-runtime-and-ui.md` paragraph above.

## Phase B items 2–4

- **Debug › Dump State…** (`helab/views/state_dump.py`, `HelabMainWindow.dump_state`): JSON of what the
  window shows, from memory only (a test makes `IOService.submit` fail during it): `schema`
  (`helab.state/1`), time, pid, version, the window (title, geometry, offline), the status bar
  (activity, resources, buttons shown by ID), Folder details (each row `details_<key>`: text,
  tooltip, shown), the plot area's hint, each folder tab (its ID `folder_tab_<n>`, title, paths, the
  four summary lines, summary buttons shown, load state and error, data shown, Live: path, on, error,
  shots, new, checks), the script group, and each plot (its number, title, script ID, action, path,
  shown in Settings, floating, released, running, following Live, its source, status and error
  lines). Saved like a screenshot (temp folder's `screenshots/`, or a picked path). **The shape is
  meant as the `--smoke` channel's state answer (v0.0.8)**: the channel can return `dump_state()`
  as it is, and its fields name controls by the phase A IDs.
- **`--geometry WxH+X+Y`** (`helab/main.py`; `HelabMainWindow.take_geometry`, `apply_geometry`): the
  window's content size and its frame's top-left, this run only (HeLab saves no window geometry, so
  nothing changes later); `--geometry=…` too; signed X/Y for screens left or above; a malformed value
  is logged and ignored; taken out of argv before Qt sees it (Qt reads `-geometry` itself on Linux);
  never below the window's minimum size (1000×600).
- **Return in a plot's settings** (approved change in `helab/analysis/parameter_tree.py`): Return
  always committed the value (pyqtgraph's spin box), but left the row's editor open, which looked as
  if nothing was taken. Now Return or Enter closes the editor after the box takes the value (the row
  deselects and shows its value; a click opens it again); an invalid entry then Return gives the
  value back, as Tab does; **Escape now cancels for real**: it puts the value back and closes the
  editor (before, the typed text stayed and was taken when focus left). Numbers (`UnitNumberItem`) and
  choices (a new `ChoiceItem`, type `helab_list`); multi-line text keeps Return as a newline and
  Ctrl+Enter to commit. In the main window, Escape is also Cancel Loading's shortcut while a load
  runs (unchanged). Tests: `tests/test_parameter_return.py`, including that the plot's next run gets
  the value.
- **Plot tab ×**: it went dead after a garbage collection (fixed, review H1); an accessibility press
  can't reach it (A~2).

## For Tony, follow-ups and manual checks

- **Q~1** Screenshot without a dialog: a runner would rather not drive a save panel. Proposed:
  Debug › Save Window Screenshot to Temp Folder, writing `screenshots/helab-<window>-<time>.png` at
  once and naming it in the status bar (later the `--smoke` channel's `shot <name>`).
- **A~1** On the lab PCs QtWebEngine panes paint black on screen (results/lab-pc-qtwebengine-black-render),
  so their grab is black too; the plot's HTML export covers them. No workaround here. The 3D
  scatter's OpenGL view (`opengl_view`, used where QtWebEngine can't paint) wasn't grabbed on this
  Mac: check on a lab PC with M~2.
- **M~1** On Windows (a lab PC): Accessibility Insights or `inspect.exe` on HeLab: the toolbar's Live
  shows AutomationId `live` and Name "Live", a script's Plot button `run_helab.counts_per_shot_Plot`
  / "Plot Counts per shot", a plot tab's close button `close_plot_tab_1`; and Debug › Run Plot runs a
  plot.
- **M~2** On a lab PC: Debug › Save Window Screenshot… with a PyQtGraph plot and a 3D scatter open:
  what each pane looks like in the PNG.
- **M~3** On the Mac with the built `.app`: `app_ax_find` finds "Folder path" and `run_…` by
  AXIdentifier; the Group combo's AXTitle is its current group (expected, H3) and AXIdentifier
  `script_group`; `app_menu` reaches Debug › Run Plot › … with its items filled (Qt fills them on
  the menu's opening; check that the accessibility route opens it the same way: an item pressed
  without the menu opening may be stale, and then does nothing rather than act on a closed plot).
- **A~2** (for known-issues): close "A plot tab's x didn't respond to computer-use clicks" with
  its cause: the × went dead after a garbage collection (the lambda above), fixed on this floor.
  Separately, as a note for runners rather than a bug: an accessibility *press* can't reach a tab's ×,
  because Qt's tab bar never exposes its close buttons (`QAccessibleTabBar`, qtbase
  `complexwidgets.cpp`, lists only the tabs, role PageTab with one action, press, which selects the
  tab, and the two scroll arrows); PyQt6 can't add them. Runner routes: Debug › Close Plot Tab ›
  <title>, the Settings panel's "Close plot" (`close_plot`), or the dock title bar's × ("Close"). The
  same holds for folder tabs' ×. No cheap way to expose it: a tab's context menu wouldn't help, as a
  PageTab offers no ShowMenu action; only Qt itself could list the close buttons.
- **Q~3** A Debug › Close Folder Tab › <title> item (as for plots), for a runner closing folder tabs?
- **M~4** On the Mac: `helab --geometry 1600x928+0+39` opens the window there (content 1600×928, the
  frame's top-left at 0,39); Debug › Dump State… writes a JSON naming the open folder and plot tabs.
- **Q~4** A conversion running at quit: wait for it in the quit window (as built: its shot finishes;
  Quit now skips), or list it and let quitting end it as before?
- **Q~2** IDs of a folder tab's own controls are the same in every tab (`folder_path`, `folder_tree`;
  only the shown tab's are on screen), while the tab bar's close buttons carry the tab's number. Keep
  it so (a runner needn't know the tab's number), or prefix every tab's controls?
