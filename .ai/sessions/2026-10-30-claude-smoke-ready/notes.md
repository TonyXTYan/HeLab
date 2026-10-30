# Notes: smoke ready (Beacon, 2026-10-30)

## Qt's accessible name and ID, as Qt 6.11 computes them

PyQt6 6.11 does not bind `QAccessible` (only `QAccessibilityHints`), so the test can't call
`QAccessible.queryAccessibleInterface(w).text(Name)`. Read from Qt 6.11.0's own source
(`qtbase/src/widgets/accessible/{qaccessiblewidget,simplewidgets,complexwidgets}.cpp`, fetched into
`.ai/temp/qtsrc/`):

- `QAccessibleWidget::text(Name)`: `accessibleName()`, else a window's title, else `buddyString`:
  the text of a sibling `QLabel` whose `buddy()` is the widget (a `QFormLayout` row label is one), or
  the parent `QGroupBox`'s title; "&" stripped.
- `QAccessibleButton::text(Name)`: `accessibleName()`, else the button's text.
- A tab (`QAccessibleTabButton`): `accessibleTabName`, else its text. The tab bar itself: the current
  tab's.
- `QAccessibleComboBox::text(Name)`: on non-Unix the widget rule; on Unix (Linux, and macOS is
  Q_OS_UNIX too) it falls through to the current text. The test doesn't count the current text: it
  changes with the choice.
- Description: `accessibleDescription()`, else the tooltip.
- `QTabBar` close buttons have no name at all (only a "Close Tab" tooltip); its scroll arrows are
  named ("Scroll Left/Right"); a dock's Float and Close buttons are named by `qdockwidget.cpp`.

`effective_name` in the test mirrors these, conservatively.

**IDs.** `QWidget::accessibleIdentifier` exists since Qt 6.9 (PyQt6 6.11 binds it).
`QAccessibleBridgeUtils::accessibleId` (`src/gui/accessible/qaccessiblebridgeutils.cpp`) returns it,
or, when empty, the dotted path of every accessible ancestor's objectName (class name where empty).
Both platform bridges use that function: macOS `accessibilityIdentifier`
(`qcocoaaccessibilityelement.mm`) → AXIdentifier; Windows `UIA_AutomationIdPropertyId`
(`qwindowsuiamainprovider.cpp`) → AutomationId. So HeLab sets both, the same text
(`helab/utils/accessible.py`, `identify`), and the OS sees exactly the ID. Not checked live yet on
either OS (M~ in the handoff).

## IDs: what is unique

Unique among the controls a window **shows** at once. Each plot's settings page has the same
controls (one page shown at a time in the Settings panel's stack); each folder tab has its own path
bar and tree (one tab shown). Those share an ID (`folder_path`, `param_Shots.first_shot`), so a
runner finds "the path bar" without knowing the tab's number. Per-item controls that show side by
side get the item's ID: run buttons `run_<analysis id>_<action>`, plot tab close buttons
`close_plot_tab_<plot number>`, folder tab close buttons `close_folder_tab_<n>` (n: the order the
tab was opened this session). Qt hides a hidden widget from macOS/Windows accessibility, so the
repeats never meet.

## Decisions taken (mine, reversible)

- Read-only labels a runner reads (summary lines, Folder details values, status bar, plot source
  and status lines, central hint) get IDs but no name: Qt names a label by its text, and a set name
  would hide the text.
- `CacheTab` and `SettingsDialog` name their controls in one `_identify` method instead of per
  line, to keep the merge with TXY Index (which edits CacheTab's converted row) to one hunk.
- Plain `QMessageBox.question/warning/information/about` calls and `QInputDialog.getText` (static
  helpers, no handle before they show) keep Qt's own buttons, named by their text, without IDs.
  Message boxes built with `QMessageBox(...)` and custom buttons get IDs (`identify_buttons`).
  Alerts that only get Qt's default OK at show time (DataRootsTab `_alert`, FolderExplorer's marker
  error, RootDuplicatesWindow's error) keep Qt's OK without an ID.

## Follow-up (2026-10-30, after landing): the SIGSEGV in test_every_script_and_each_library

Sable (UI Polish) saw `test_accessible_names.py::test_every_script_and_each_library` crash its xdist
worker with SIGSEGV. Investigated on `agent/smoke-ready` after merging dev/v0.0.7 at 43cb202 (local
merge 97e1dd7, not pushed).

- **Reproduced:** `pytest tests/test_accessible_names.py tests/test_presets_plots.py
  tests/test_debug_runner_menu.py -n 4 --reruns 2` crashes gw0 in that test **7 of 7** runs (4, then
  3 as the control). (With `test_presets_window.py` instead: 0 of 4.) macOS crash reports
  (`python3.13-2026-10-30-1534*.ips`): SIGSEGV, main thread, `QDockWidget` deleted (DeferredDelete) →
  `deleteChildren` four levels down → `sipQWidget::~sipQWidget` → `QObject::destroyed` →
  `PyQtSlotProxy::unislot` → `PyQtSlot::call` → `_PyEval_EvalFrameDefault`; faulthandler: the main
  thread's Python frame is `<invalid frame>`.
- **The connection:** `helab/analysis/panes.py:32`, `PlotlyPane.__init__`:
  `self.destroyed.connect(lambda *_: server.remove_plot(plot_id))`, a Python callable (through a
  PyQt slot proxy) on the pane's own `destroyed`; the only plain-callable `destroyed` connection on a
  widget inside a plot dock.
- **Fix, tested (working tree only, reverted):** `weakref.finalize(self, server.remove_plot,
  self.plot_id)` instead of the lambda: **0 of 6** runs crashed (control 3 of 3 crashed right after,
  same session). The figure still leaves the server, once the plot's Python object goes (checked:
  present while the closed plot's instance is still referenced, gone after it's dropped); before, it
  left at the C++ deletion. Alternative keeping that timing (not tested): a long-lived QObject with a
  bound `pyqtSlot` on `destroyed`, mapping the pane's address to its plot ID (a plain Qt connection,
  no Python proxy, as the tab-× fix).
- **An isolated loop** (a QWidget subclass with the same lambda, deleted with its parent 3 × 3000
  times, with GC and allocator churn) never crashed, so the precise PyQt mechanism isn't shown; the
  evidence is the 7/7 vs 0/6 swap.
- **Real use:** the same path runs whenever a Plotly plot's dock is deleted: closing a tabbed or
  floating Plotly plot (its tab's ×, Close plot, Debug › Close Plot Tab, the dock's ×), and quitting
  with Plotly plots open. 75 open-and-close cycles of a Plotly plot in one real main window didn't
  crash, so it needs a particular memory history; in the app it would be a rare quit without a
  traceback when a Plotly plot closes.
- **The same family:** `helab/views/PresetsInspector.py:136`, `label.destroyed.connect(gone)` (a
  closure on a Python-made QLabel's `destroyed`, Settings › Cache's Presets line); not seen to crash.
- **Tests proposed:** (1) the cleanup: open a Plotly plot, close it, drop it: its figure is gone from
  `dash_server` (pins the behaviour the lambda existed for); (2) the rule as a guard (with A~3's AST
  scan): no `.destroyed.connect(` to a lambda or a plain function anywhere in `helab/`; (3) the 3-file
  order above as a manual check (it reproduces 7/7 on this Mac, not CI-able as a unit test).
