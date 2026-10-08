# Remaining folder status-message fixes

Implemented Tony's approved remaining status-message fixes after pulling
`886847e` with `git pull --ff-only`. The in-progress edits were temporarily
stashed and reapplied without conflicts; the Windows identity fix is preserved.

- Load progress counts files checked separately from files successfully loaded,
  unreadable files, and files that changed while being read. Helpers supply
  explicit checked counts; cached partial datasets retain unreadable counts.
- Folder counts and the central placeholder share queued/running/paused scan
  wording. Running metadata scans retain
  `Scanning: checking file counts and status…`; names-only listings identify
  folder entries. Background details remain app-wide activity, as before.
- Verification heartbeats update the message after file progress starts.
- Per-file retries name their scope and put the filename in the tooltip. The
  retry label clears on completion, and tabs joining shared loads receive the
  current verification/retry state as well as progress.
- Manual listing retries distinguish queued from running; the central loading
  title explicitly identifies a paused load.

Basic scan naming was discussed but not changed: Quick scan implies speed on
slow volumes; Check folder status was suggested as a clearer alternative.
Live updates remain deferred; no cache freshness policy changes were made.

Validation on Python 3.13.15:

- `venv/bin/pytest -q tests/test_folder_cache.py tests/test_folder_summary.py
  tests/test_load_queue.py tests/test_gui_responsiveness.py
  tests/test_cache_first.py tests/test_io_lanes.py tests/test_two_step_browse.py
  --basetemp=.ai/temp/pytest-status-regressions-final`: 175 passed, one existing
  logging.warn deprecation warning.
- `venv/bin/mypy helab/ tests --strict`: no issues in 88 source files.
- `venv/bin/pyright helab tests`: zero errors or warnings.
- `git diff --check`: clean.

Changes are uncommitted. Validation uses isolated test settings/caches and
controlled helper events with real Qt widgets; no live lab-volume run was made.

## Follow-up: folder status naming and toolbar placement

Tony chose **Check folder status**, then clarified that the control belongs in
the toolbar rather than beside the folder path. The existing Rescan toolbar
position now provides an icon-only split button; its arrow retains Folders in
view, Current folder, Recursive depth, and All subfolders. The primary icon
checks folders in view and becomes Cancel check during the current tab's check.
Switching tabs updates that state; cancelling keeps other tabs' subscriptions.
Refresh retains the existing relisting operation.

Removed both the inline status-check button and the duplicate inline Up button.
The path field is the only widget in the top row; toolbar Up keeps its existing
navigation and enabled-state logic. Related menus, settings, scan history,
freshness tooltips, queue labels, and console messages use the new terminology.
Internal identifiers and persisted settings/cache keys are unchanged.

Follow-up validation:

- Relevant regression suites (the seven above plus scan history, folder icons,
  settings dialog, and folder tab roots): **217 passed, 1 skipped**, one existing
  logging.warn deprecation warning.
- Strict mypy and Pyright across helab/tests: clean.
- A Qt toolbar interaction test covers scope selection, primary-icon checking,
  cancellation with shared work, tab switching, and toolbar Up navigation.
- Offscreen Fusion preview visually inspected at 480 px window width: path
  field 424 px wide, status icon/dropdown visible, three summary lines intact.
  Preview and isolated harness are in `.ai/temp/folder-status-toolbar.png` and
  `.ai/temp/folder_status_toolbar_preview.py`; the harness stubs Dash startup.
- `git diff --check`: clean. No commit performed.

### Vertical toolbar dropdown follow-up

Moved the status-check menu arrow below its icon, between neighboring toolbar
icons, using Qt's menu subcontrol so its mouse target still opens the scope menu.
The button no longer widens the toolbar. Both idle and cancel tooltips now use
short lines, including instructions for the icon and lower arrow.

- `tests/test_load_queue.py`: **20 passed**; the toolbar test verifies compact
  width, the bottom arrow's geometry and menu click, scope/cancel behavior,
  tab switching and Up navigation.
- Strict mypy and Pyright across helab/tests: clean.
- Updated offscreen Fusion preview inspected at 480 px: path field 440 px wide.
- `git diff --check`: clean. No commit performed.

### Larger right-pointing scope triangle

Tony requested the lower arrow point right and be roughly twice as large for
standard-density displays. It now uses a 10 × 14 logical-pixel SVG, replacing
the native down-arrow (which ignored the requested glyph size). The lower menu
hit area is 16 px tall, and the toolbar/path widths are unchanged. Multiline
tooltips and primary-icon check/cancel behavior are retained.

- Standard-density offscreen preview visually inspected.
- Toolbar/load-queue tests: **20 passed**. Strict mypy and Pyright: clean.
- Added the SVG to wheel package data and PyInstaller data. A local wheel build
  succeeded and includes `helab/resources/menu-right.svg`.
- `git diff --check`: clean. No commit performed.

### Triangle size and spacing correction from Tony's screenshot

Reduced the right-pointing triangle to 6 × 8 logical pixels. Removed the
permanent native border around its menu area and used explicit main-button
padding so the scan icon and lower arrow have room between them. Hover/press
feedback remains; the lower menu hit area is 20 × 12 px. The button stays within
its neighbors' width. Multiline tooltips and menu/primary click behavior remain.

- Fusion previews inspected at 1× and 2× scaling; the native macOS style's
  offscreen render was also inspected for the custom-painted scan/arrow area.
- `tests/test_load_queue.py`: **20 passed**; warnings were the existing logging
  deprecation and Dash's port 8050 already in use.
- Strict mypy and Pyright: clean; `git diff --check`: clean.

### Independent icon and scope click targets

Tony reported that the icon and triangle no longer felt separately clickable.
Actual primary/arrow mouse clicks passed in the offscreen reproduction, but the
stylesheet highlighted the entire split button on hover. Replaced that native
split subcontrol with two vertically stacked QToolButtons in one toolbar widget:
the upper button holds the existing check/cancel QAction, and the lower button
opens the existing scope menu. Each now has its own mouse target, hover/press
feedback and tooltip. The 6 × 8 px triangle, toolbar width and scope choices are
retained; both buttons follow the QAction's enabled state.

- Regression now uses real mouse clicks for primary start/cancel as well as
  scope popup; checks that icon clicks do not open the menu and both targets
  disable together. All **20 load-queue tests passed**.
- Strict mypy and Pyright: clean; `git diff --check`: clean.
- Updated 2× Fusion preview visually inspected. No commit performed.

### Refresh now updates the folder tree only

Tony clarified that toolbar Refresh should relist folders, rather than recheck
every visible folder. `FolderExplorer.refresh()` now calls a names-only model
refresh of the root and expanded branches represented in the viewport (including
expanded ancestors above the viewport). Collapsed/selected rows are not forced
through scans. Listing submissions use bounded batches and stop after navigation,
cancellation or closure. Visible native icons are refreshed as before.

The `listing_only` request flag prevents detailed scans, checked-status/date
replacement, and status signals that start automatic data loads. Shared snapshot
notifications carry this intent to passive tabs, so their trees update without
new loads or checks. Existing status summaries and datasets remain intact.
Refresh completion also cannot finish an independently running status check.
Automatic scanning of missing statuses still follows its existing opt-in setting.

Updated Refresh's multiline tooltip and removed references to using toolbar
Refresh to recheck status from related tooltips. The existing internal `rescan`
behavior remains available; older dataset-update tests now invoke it explicitly.

Validation: **219 passed, 1 skipped** across the eleven relevant browser/cache/I/O
suites, including real-helper listing events for added/removed folders, preserved
selection/expansion/status/data in two tabs, and a concurrent status check.
Strict mypy and Pyright across helab/tests and `git diff --check` are clean.
Warnings were the existing logging deprecation and Dash port 8050 already in use.
No commit performed.

### Native hover feedback and hover-open scope menu

Tony reported that the custom scan/triangle buttons lacked the other toolbar
buttons' hover effect and requested opening options on triangle hover. Removed
the custom background/border stylesheet and enabled native auto-raise painting
on both buttons. The scope button uses native QStyle painting with only Qt's
additional menu indicator suppressed, retaining the existing 6 × 8 px icon.

A single-shot 200 ms hover timer opens the scope menu to the right of the
triangle. Leaving before the delay, hiding or disabling the button prevents
opening. The menu remains accessible when moving into it; hovering never starts
a scan. Click/keyboard popup and independent primary check/cancel remain intact.
The multiline triangle tooltip now mentions hover and click.

Validation: **22 passed** in hover-menu and load-queue tests; strict mypy (90
files), Pyright and `git diff --check` clean. Fusion offscreen normal and hover
previews inspected, confirming independent native borders/highlights and
unchanged toolbar width. Native macOS appearance was not separately launched.
The same existing logging/Dash-port warnings remain. No commit performed.

### One-second dismissal after leaving the triangle and menu

Tony chose a one-second dismissal delay. The scope button now observes menu
pointer events and starts a single-shot 1000 ms timer when the cursor is outside
both the triangle and menu. Returning to either cancels the timer; leaving again
starts a full new delay. Outside mouse movement does not keep extending the
deadline. Closing/selecting the menu stops its timers. Global cursor geometry
avoids relying on the underlying button's hover flag while the popup grabs input.

Regression checks cover staying inside the menu, delayed dismissal, returning
to the triangle or menu, and a fresh delay after the next leave. Hover/menu and
load-queue suites passed **25 tests**. Strict mypy/Pyright and diff checks are
clean. No commit performed.

The hover-menu test module preloads QtWebEngine before QApplication so the
existing shared worker-cleanup fixture also works in standalone runs (five
hover-menu tests passed standalone). Dismissal begins on pointer movement/leave,
so opening the menu with the keyboard does not itself start a closing timer.

### Dismissal delay shortened to 0.5 s

Tony asked for a 0.5 s dismissal instead of one second. The dismiss timer is now
500 ms; the hover-to-open delay stays 200 ms. Hover-menu tests were retimed
(300 ms checks before dismissal, `test_menu_dismisses_after_half_second_outside`)
and all five pass. No commit performed.

### Review follow-up: details after Refresh; popups to the right

Review found that Refresh cancelled this tab's browse-step-2 `details` scans
(they are non-manual) and never requested them again, so dates, signatures and
identities stayed blank until the folder was reselected; new subfolders found by
Refresh had no dates. Now `cancel_automatic_scans` returns what it cancelled;
cancelled details, details deferred while refreshing, and folders where the
refresh listing found new subfolders are requested once the refresh finishes.
The request is deferred one event-loop turn so the finishing listing still owns
its tree and prunes removed folders first. Stop/navigation/close drop the set.

Click, Space and accessible `showMenu()` popups of the scope triangle now open
to its right like hover (Qt placed them below); at the screen's right edge the
menu opens to the left. Tony accepts the close/reopen flicker on hover-then-click
and needs click/keyboard to keep working for agents without a mouse.

Validation: 221 passed, 1 skipped across the ten browser/cache/I/O/hover suites
(new tests fail without the fix); strict mypy (90 files), Pyright and
`git diff --check` clean. No commit performed.

### Review follow-up: row stuck on "queued" after a cache clear + Refresh

A scan/details request made while its folder's cache clear runs is parked and,
after the clear, replaced by a new request; the parked one never gets a terminal
event. If Refresh then cancelled the replacement, the model handed the row back
to the parked request, leaving it "queued" until the folder was listed again.
The refresh-cancel fallback now ignores (and forgets) requests FolderCache no
longer tracks. Regression test reproduced the stuck state before the fix.
Validation: 222 passed, 1 skipped; strict mypy, Pyright, `git diff --check` clean.
No commit performed.

### Review follow-up: rows idle while work is still running

Two cases left a row `idle` (no spinner) while this tab's work on the folder ran:
a tab joining another tab's already-started listing/check (it receives `started`,
not `queued`, so it never took the row), and Refresh's listing finishing while a
status check of the same folder was still running (the row was not handed back).
A first `started` now gives a late joiner the row; it records no names (it missed
earlier ones) so it cannot prune children. When the row's request finishes, the
newest of this tab's other active requests takes the row (`_release_row`, shared
with the Refresh-cancel fallback); details take it as `idle`, being background.
Non-owners still record names, so a request handed the row prunes correctly.
Both regression tests failed before the fix. Validation: 224 passed, 1 skipped;
strict mypy (90 files), Pyright and `git diff --check` clean. No commit performed.

### Known issue #3 recorded, not fixed; roadmap set up

While a tab refreshes it ignores other tabs' finished results (off-screen rows
stay stale until relisted). Not fixed by design: replaying after Refresh can
trigger source I/O once the result is older than 10 s; the proper fix is the
no-I/O in-memory path planned with cache-only browsing. Two strict `xfail`
tests (`SHARED_RESULTS_DURING_REFRESH` in `tests/test_two_step_browse.py`)
record the expected behaviour; controls without Refresh pass. New root
`ROADMAP.md` gathers open work (README TODO list and MEMORY.md TODO moved there;
AGENTS.md points to it). Validation: 224 passed, 1 skipped, 2 xfailed; strict
mypy, Pyright and `git diff --check` clean. No commit performed.
