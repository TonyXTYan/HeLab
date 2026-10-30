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
(`helab/views/accessible.py`, `identify`), and the OS sees exactly the ID. Not checked live yet on
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
