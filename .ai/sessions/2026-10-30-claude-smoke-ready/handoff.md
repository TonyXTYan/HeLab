# Handoff: smoke ready (Beacon, Worker; `agent/smoke-ready`, base `9f0b21f`)

Phase A (brief.md items 4, 1, 2 and phase B item 1, the IDs) is done; phase B items 2–5 follow
(brief-phase-b.md). Details and Qt source references: [notes.md](notes.md); first plan:
[plan.md](plan.md).

## Phase A: what changed

- **`helab/views/accessible.py`** (new): `identify(widget, id, name="", description="")` sets the
  objectName and the accessible identifier (the same ID), and the name and description when given;
  `identify_action` names a toolbar's button for an action; `identify_buttons` gives a button box's or
  message box's buttons IDs; `id_part` makes a script or profile ID safe in an ID.
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
synthetic TXY folder loaded, two PyQtGraph plots tabbed, one released and one floating; Settings at
each tab and the profile editor; eleven dialogs and tool windows on a cache whose helpers never
run), walks every control of the interactive classes (`QAbstractButton`, `QComboBox`, `QLineEdit`,
`QAbstractSpinBox`, `QAbstractSlider`, `QTabBar` and each tab, `QAbstractItemView`, editable
`QTextEdit`/`QPlainTextEdit`; less a control's own parts, listed in `part_of_another`) and fails
listing each without a name or ID, whose accessible identifier isn't its ID, or whose ID repeats
among the controls its window shows. Hidden controls are checked for a name and ID too. PyQt6
doesn't bind `QAccessible`, so `effective_name` follows Qt 6.11's rules (notes.md).
`test_every_widget_class_in_views_is_walked_or_skipped_with_a_reason` imports every module of
`helab/views/` and fails on a `QWidget` subclass that no case opens (`covers(...)` on a case,
`DIALOGS`) and that `SKIPPED` doesn't list with a reason (none today). **A new window or dialog:**
add a builder to `DIALOGS` (or a case with `@covers`), with synthetic data if its controls need a
folder or a plot.

## Checks

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
  (`helab/views/accessible.py`, `identify`; test-enforced: `tests/test_accessible_names.py`)."
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
  "Preset", "Apply preset", "TXY source") or by AXIdentifier (`folder_path`, `live`, `run_…`).

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
  AXIdentifier, and `app_menu` reaches Debug › Run Plot › … with its items filled (Qt fills them on
  the menu's opening; check that the accessibility route opens it the same way).
- **Q~2** IDs of a folder tab's own controls are the same in every tab (`folder_path`, `folder_tree`;
  only the shown tab's are on screen), while the tab bar's close buttons carry the tab's number. Keep
  it so (a runner needn't know the tab's number), or prefix every tab's controls?
