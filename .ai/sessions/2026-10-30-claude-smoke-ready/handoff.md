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

## Review fixes (Wren, review.md)

- **H1** (the rerun on all three OSes): reproduced locally with CI's exact command
  (`pytest -n 4 --test-group 1/2 -rR --cov=helab … --timeout=120 --timeout-method=thread`: 1 RERUN of
  `test_plots_close_from_their_tab_and_the_settings_panel` on gw0, 4 runs of 4); replaying gw0's
  order alone, even under xdist, never failed. Instrumented at the failure: one tab bar, 3 tabs,
  closable, marked by `DockTabCloser`, `dock_at` finding every dock; the test's
  `tabCloseRequested.emit` never reached `close_tab`, while calling `close_tab` directly closed the
  plot. So the **lambda connected to `tabCloseRequested`** (`lambda index, bar=bar: self.close_tab(bar,
  index)`) stopped delivering; nothing in HeLab disconnects it, and in isolation it survives
  `gc.collect()`, so the PyQt mechanism isn't pinned down. Fixed by connecting a bound
  `pyqtSlot(int)` of the closer (`_tab_close_requested`, the bar from `sender()`): CI's command twice
  since, **no RERUN**. Why this branch: the only changes on that path are the closer's extra refits
  and naming; with the lambda gone the order no longer fails.
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
- **Plot tab ×**: real clicks work (a test); background/accessibility clicks can't, see A~2.

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
- **A~2** (for known-issues, replacing "A plot tab's x didn't respond to computer-use clicks"): Qt's
  tab bar never exposes its tabs' close buttons to accessibility: `QAccessibleTabBar`
  (qtbase `complexwidgets.cpp`) lists only the tabs (role PageTab, its rect the whole tab with its ×,
  one action: press, which selects it) and the two scroll arrows, so a click by accessibility at the ×
  presses the tab, already selected, and nothing happens. PyQt6 has no `QAccessible` bindings, so
  HeLab can't add the button to the tree. Real clicks work (test). Runner routes: Debug › Close Plot
  Tab › <title>, the Settings panel's "Close plot" (ID `close_plot`), or the dock title bar's ×, which
  Qt does expose ("Close"). The same holds for folder tabs' × (Debug has no folder-tab item; File has
  none either). No cheap fix: a tab's context menu wouldn't help, as PageTab offers no ShowMenu action
  to open it by accessibility. Only Qt itself (a `QAccessibleTabBar` that lists the close buttons,
  upstream) would.
- **Q~3** A Debug › Close Folder Tab › <title> item (as for plots), for a runner closing folder tabs?
- **M~4** On the Mac: `helab --geometry 1600x928+0+39` opens the window there (content 1600×928, the
  frame's top-left at 0,39); Debug › Dump State… writes a JSON naming the open folder and plot tabs.
- **Q~2** IDs of a folder tab's own controls are the same in every tab (`folder_path`, `folder_tree`;
  only the shown tab's are on screen), while the tab bar's close buttons carry the tab's number. Keep
  it so (a runner needn't know the tab's number), or prefix every tab's controls?
