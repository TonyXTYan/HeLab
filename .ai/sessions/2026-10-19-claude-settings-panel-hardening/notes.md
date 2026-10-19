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

## 3. Where a new plot goes (`_add_dock`)

Old rule: tab with the newest *visible* open dock. Problems found:
- In a shown area `addDockWidget` hides the new dock and shows it through a queued call
  (`QLayout::addChildWidget`), and `tabifyDockWidget` never groups with a hidden dock. So
  plots opened before the event loop ran (two quick clicks, or a script opening several)
  sat side by side; offscreen, even with the tab target fixed, 20 plots opened at once
  formed no group at all. Now the new dock is shown right after `addDockWidget`.
- A visible *floating* dock could be the target; Qt then puts the new plot in that dock's
  old docked place, i.e. tabbed beside some unrelated plot (probe: E landed with D1).
- Offscreen, docks behind a tab report `isVisible()` True; on macOS (per the old
  docstring) False. The rule shouldn't depend on it.

New rule (`TreePanelWidget.tab_target`): tab with the plot whose settings show, if it is
docked in the area, else the newest docked plot. Docked = in the area, not floating, and
not hidden on its own (a dock unticked in the area's context menu is hidden; one hidden in
a tab group still stands for the group, and Qt adds the new plot to that group). Visibility
is ignored. None → the new plot docks on its own (no plot open, all floating, or all
hidden). Closed plots are not open (removed from `dock_widgets` and the area); deleted ones
are skipped. Tests: `test_tab_target_rule` (each case), 20 plots at once form one group,
`test_a_new_plot_docks_alone_when_all_others_float`.

Also fixed: `receivers()` in the panel tests now flushes deferred deletes first (a panel
from an earlier test awaiting deletion skewed the baseline when run after test_analysis_gui).

## 4. DockTabCloser

Titles were unique only by convention ("Name (id)", the id a per-panel counter); two
TreePanelWidgets, a future rename or a dock title set elsewhere could collide, and the old
lookup also skipped floating docks by title. Now `dock_at(bar, index)` matches the tab's
data: Qt's dock tab bars (`QDockAreaLayoutInfo::updateTabBar`) store each tab's dock widget
address as tab data (Qt 5 and 6; checked on 6.11). `test_tab_close_buttons_match_docks_by_identity`
guards that behaviour (if Qt stops storing it, the test fails rather than closing a wrong
plot; `dock_at` returns None then and nothing closes). Three docks with the same title close
the right one; a renamed plot still closes by its tab.

Its event filter on the plot area went too: it called Python for every event of the
`middle_mainwindow` (QMainWindow tracks hover for its separators, so mouse moves over the
plot area too). Fitting now follows each plot dock's `dockLocationChanged`,
`topLevelChanged` and `visibilityChanged` (one coalescing 0 ms timer), and `fit()`
activates the area's layout first so Qt has made its tab bars.
`test_tab_bars_made_later_get_close_buttons`: bars Qt makes after re-docking a floated plot
or showing a hidden one get close buttons.

`sip.unwrapinstance` is typed `-> None` in PyQt6's stub: `address_of` casts it.

## 5. The RHI surface

`_start_with_rhi_surface` made a hidden `QQuickWidget` whenever `sys.platform == "darwin"`,
offscreen tests included (macOS CI and local runs made one in every `HelabMainWindow`), and
`PyQt6.QtQuickWidgets` was imported at module level on every OS. Now
`HelabMainWindow.needs_rhi_surface(system, qpa)` is true only for darwin with Qt's
`cocoa` platform: Windows, Linux (xcb, wayland), `minimal` and `offscreen` make nothing, so
offscreen tests on any OS never create a Quick scene graph. QtQuickWidgets is imported
inside the branch (PyInstaller still sees the import statically). Tests: the platform
table; an offscreen `HelabMainWindow` has no `QQuickWidget` child; on macOS (forced on) the
surface is a hidden child that stays hidden when the window shows. The window-recreation
effect itself can't be seen offscreen: Tony's checklist keeps the Mac check and the
lab-PC question (MANUAL_TODO).

## 6. Activation sources

Tested offscreen (`test_activation_sources`, `test_a_click_back_in_the_focused_plot`):
- Click in a pyqtgraph `PlotWidget` viewport: the PlotWidget is StrongFocus and takes focus.
- Click in content that takes no focus (a QLabel): the dock (ClickFocus) takes it.
- Click on the dock's title strip: the dock takes it.
- Click in a `QWebEngineView`: its render widget (the view's focus proxy, made once the page
  renders) takes focus; offscreen it renders `setHtml` content.
- Keyboard focus moved into a plot's widget (Tab reason).
- Tab activation via the dock tab bar (needs the bar laid out: a bar Qt has made but not
  yet shown ignores `setCurrentIndex`).
- A floating plot's window activated (`focusWindowChanged`).
- The main window activated again: Qt restores its focus widget, so the plot that had focus
  there shows again.

Gap found and fixed: with focus approach alone, if plot B was shown by its tab, its window
or the chooser while focus stayed in plot A's widget, a click back in that widget changed
no focus, so A's settings didn't come back (the old event filter saw the press). Now when
a plot is shown while focus sits in another plot, focus moves to the shown plot's dock
(not when focus is elsewhere, e.g. the chooser keeps it). The test fails without the fix.

What offscreen tests can't show (Tony's on-screen checklist):
- Real clicks through macOS (cocoa) and Windows: click-to-focus is applied only to
  spontaneous events; QTest marks its clicks spontaneous, but the window system decides
  activation. Check a first click into an inactive window (another app in front).
- QtWebEngine on screen: whether a click in the 3D scatter reaches Qt's render widget as a
  focus change on macOS and on the lab PCs (black-pane PCs: the click still lands on the
  widget, nothing paints). If a click in the scatter doesn't switch the settings, report it:
  the fallback is to make the scatter's container ClickFocus-only and steal focus.
- Floating windows: activation by clicking the floating title bar, by Cmd-` / Alt-Tab and
  by Mission Control; `focusWindowChanged` should fire for each.
- Background tabs: which dock Qt focuses when the focused plot goes behind a tab, on
  screen (offscreen never hides background tabs: they stay "visible" there).
- Dragging a plot's tab out to float it and back in, and docking a floating plot onto
  another to make a tab group: the panel and tab × buttons follow.
- Keyboard: Tab/Shift-Tab into a plot's controls shows its settings; on macOS full keyboard
  access setting changes which widgets take Tab focus.

## 7. UnitSpinBox

Probed with real typed input + Enter (`.ai/temp/spin_probe.py`). Wrong before (Ground's
version, which appended the shown unit to bare text and used pyqtgraph's loose regex):
- "5 m", "5 u", "5 k" in a box showing "4 ms" → **5 s** (the prefix was lost).
- "5 abc" → **5 as** (pyqtgraph's regex takes "a" as atto and the rest as a suffix).
- "95,5" in a % box (English locale) → **9 %**; "95.5" in a German locale → 9 %.
- "4.5" in a whole-number box → 4 (truncated).
- Out of range ("150" in 0–100 %) → back to the old value (kept as it was).

Now `UnitSpinBox.parse` reads strictly: number (one decimal mark, exponent allowed), then an
optional SI prefix (`u` = µ), then optionally the unit. Bare number → shown unit and prefix
(exponent included: "1e-3" in "4 ms" is 1 µs); prefix without unit → that prefix; with unit
→ as written. Decimal mark: "." always, "," only where it is the locale's decimal point
(the box never shows thousands separators, so "1.000" is 1 even in German). Whole-number
boxes take integral values only ("4.0" yes, "4.5" no). Empty, letters, inf/nan, prefixes in
a box without SI prefixes ("95 k" in %) are invalid: red outline while typing, value back
when the edit ends. Beyond the limits: red outline while typing, and the edit's end sets
the nearest limit (`fixup` → `setValue` clamps), as `ParameterSpec.coerce` and the arrows
do. Maestro approved the clamping and the one assertion change in `tests/test_analysis.py`
("20" in Point size → "10 px", comment "Above the limit: set to 10 px.").
`suffixPower` is passed to `siApply` (pyqtgraph's own parser ignores it, so "4 mm²" would
mis-parse there; unused by today's specs).

`tests/test_unit_spin_box.py` (63 cases): each SI prefix shown (µ, m, none, k; s and m
units, zero and negative values), with/without unit, invalid input, percent with limits,
whole numbers, German decimal comma (`setLocale`, no system change), the red outline, and
values reaching the parameter through the settings tree. The file imports
QtWebEngineWidgets first: run alone, nothing else imports it before the app starts.
