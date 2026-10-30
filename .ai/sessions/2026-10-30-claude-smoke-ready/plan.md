# Plan: smoke ready (Beacon, Worker, 2026-10-30)

## Windows and dialogs covered (each opened by the test)

- **Main window** (`HelabMainWindow`): left/right toolbars (icon-only actions: New Tab, Up, Refresh,
  Check folder status + its scope arrow, Cancel loading, Live, Settings, panel toggles), folder tabs
  (`FolderTabWidget`, its tab bar and corner buttons), each tab's `FolderExplorer` (path bar, tree,
  summary rows' Cancel/Retry/Deselect/… buttons), Folder details (`FolderDetailsPanel`), status-bar
  buttons (mismatched, roots, offline, RAM), Scripts panel (`TreePanelWidget`: Group combo, Load
  Scripts…, each script's run buttons), the plot area with plots open on a synthetic loaded folder
  (docks, tab bars and their close ×, the Settings panel with its pages, preset bar, TXY row,
  `CentralHint`), a released plot (`ReleasedPlot`'s Reload) and a floating plot (`FloatingSettings`,
  `SettingsToggle`).
- **Settings** (`SettingsDialog`) and every tab: General, Lab parameters (`LabParametersTab`), TXY
  converter (`ConverterTab`), Scripts, Cache (`CacheTab`, `RamBudgetSpinBox`), Data roots
  (`DataRootsTab`).
- **Dialogs and tool windows:** `ProfileEditor`, `PresetsInspector`, `FolderConstantsDialog`,
  `MissingShotsWindow`, `RootDuplicatesWindow`, `CopyRootDialog`, `ManualMarkerDialog`, `PlaceRootBox`,
  `LargeFolderDialog`, `QuitSaveDialog`, `DebugIconsWindow`, `MemoryUsageWindow`.
- Plain `QMessageBox`/`QInputDialog` calls (text buttons, Qt names them) are listed as reasoned skips,
  not opened one by one.

## How the test finds unnamed controls

`tests/test_accessible_names.py`. For each window: `findChildren(QWidget)`, keep the ones visible
within the window (`isVisibleTo`) of the interactive classes — `QAbstractButton`, `QComboBox`,
`QLineEdit`, `QAbstractSpinBox`, `QAbstractSlider` (not a scroll area's own scroll bars), `QTabBar`
(and each tab's text), `QAbstractItemView` — skipping Qt's own sub-widgets (a spin box's or combo's
line edit, a combo's popup view). Enabled or not. Each one's effective name is
`QAccessible.queryAccessibleInterface(w).text(QAccessible.Text.Name)`; the test fails listing every
empty one with its class, object path and tooltip.

**Guard:** the test imports every module under `helab/views/`, lists every `QWidget` subclass defined
there, and requires each to be in `COVERED` (the case that opens it, which asserts an instance was
actually walked) or `SKIPPED` (with a reason). A new window, dialog or widget class fails until it is
added to one. No `QWebEngineView` left alive (the plots used are PyQtGraph/Matplotlib, and the
module's teardown closes plots); settings from `app_settings()`; synthetic TXY folders in `tmp_path`.

## Debug menu items (existing Debug menu, filled on `aboutToShow`, memory only)

- **Run plot ›** the current group's scripts and their actions ("Plot Release time"), calling the run
  button's own callback; disabled with "(load a folder's data first)" when nothing is loaded.
- **Script group ›** each group, checkable, setting the Group combo (`setCurrentText`, so the same
  `_on_group_changed` path runs).
- **Plot tabs ›** "Show <title>" (raises the dock, as a tab click does) and "Close <title>" (the dock's
  `close()`, as the tab's × does) per open plot; disabled "(no plots open)".
- **Settings tab ›** each Settings tab by name: `show_settings_dialog(tab=…)` opens Settings on it.
- **Save window screenshot…** (below).

## Screenshot

`QWidget.grab()` of the target window to a PNG chosen in a save dialog (default name
`helab-<window>-<time>.png` in the app's temp folder's `screenshots/`; HeLab never proposes a source
folder). Target: the HeLab window active when the Debug menu opened (on macOS the front window, a
floating plot or a non-modal tool window), else the main window; plus **Screenshot of ›** each visible
HeLab window by title, so a floating plot can be picked on Windows/Linux where opening the menu
activates the main window. QtWebEngine (Plotly) panes and any GL view come out blank: listed in the
handoff with a `Q~`/`A~` follow-up, no workaround here. A path without a dialog: proposed as `Q~`.
