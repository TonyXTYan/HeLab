# Automating the release smoke pass (M1.1–M1.8) with computer use

Written 2026-10-28 by Side (Claude, the Assistant on Ground), at Tony's request in Chat. ID
block 5 ([ID_BLOCKS](../../ID_BLOCKS.md)). The steps themselves are in
[MANUAL_TODO, Release smoke pass](../../MANUAL_TODO.md#release-smoke-pass). This note is the
runbook for having a small model (e.g. Claude Haiku 5.5) drive them on another machine through
computer use, with Tony reviewing the results instead of clicking through.

## The idea

- **Runner:** a small, cheap model with desktop control, on the machine under test, for example
  the Claude desktop app's computer use (the `computer-use` skill), or Claude Code with a
  computer-use tool. It works one screenshot, one action at a time, and judges each check only
  against the text in this runbook.
- **Supervisor:** Tony, or the Assistant on Ground. The supervisor fills in the config, starts
  the run, answers the runner's stop questions, and reviews `REVIEW` and `FAIL` results with
  their screenshots.
- **Output:** a session folder `sessions/<date>-<tool>-smoke-<machine>/` with `results.md`
  (template below) and `shots/`. The Assistant then carries the results into the docs (A1.8),
  and failures into known-issues.

The runner decides only what it can see: a label, a menu item, a status line, a dialog. Taste
and physics ("is this temperature sensible", "does the layout look right") are marked `REVIEW`
with a screenshot for Tony. They are never passed or failed by the runner.

## What can be automated

| Step | Automation | Needs a human for |
|---|---|---|
| M1.1 Start-up | full | nothing |
| M1.2 Browse and cache first | full | nothing (the folders are named in the config) |
| M1.3 Live during a run | only while a run is acquiring | confirming a run is acquiring; otherwise `SKIP` |
| M1.4 Presets and reopened plots | full | judging floating-window placement (`REVIEW`) |
| M1.5 Saved analysis results | full | nothing |
| M1.6 Work Offline | full, except unmounting | unmounting the share (optional part; `SKIP` by default) |
| M1.7 DLD plots on real data | screenshots only | every plot's look and physics (`REVIEW`) |
| M1.8 Settings panel, floating plots | full | the lab-PC window-flicker question Q1.7 (`REVIEW`) |

So about 5 of the 8 steps pass or fail on their own, and the rest come back as screenshots to
look over. M1.3 is the one that needs timing (a run acquiring).

## Safety rules for the runner (in its prompt, verbatim)

1. Work only inside the HeLab window, plus the dialogs HeLab opens. Don't open Finder or File
   Explorer, a terminal, a browser (except a page HeLab's "Open in browser" opens) or any other
   app.
2. **Never change the data share.** Don't use: Place .helab-root…, Delete .helab-root…, Save to
   folder…, It's a copy…, Load as it is now, or any file operation.
3. Change only the settings this runbook names. Never use: Clear all, Remove old entries, Change…
   (moving the cache), Reset all settings, Forget, Clear cached data… (datasets).
4. The only clearing allowed is **Clear cached analysis…**, on the data root named in the config
   (M1.5).
5. When a dialog or message appears that this runbook doesn't describe, **stop**: take a
   screenshot and ask the supervisor. Never click through an unknown dialog.
6. Never type credentials or answer a system permission prompt. Ask the supervisor.
7. If an action doesn't give what the runbook expects, take a screenshot and try once more at
   most. Then mark the check `FAIL`, with what you saw, and go on to the next check.
8. Quit HeLab only where a step says so, with File › Quit or Cmd+Q / Alt+F4, never by force.

## Config (the supervisor fills this in before a run)

```text
MACHINE        = <name>, <macOS or Windows version>
HELAB_COMMIT   = <git log -1 --format=%h on that machine>
START_COMMAND  = <macOS: open -n <checkout>/dist/HeLab.app (the built app: a source run has no
                  bundle ID and can't be driven, and quit any other HeLab first, since they
                  share the bundle ID); Windows: C:\...\venv\Scripts\helab.exe>
SHARE_PATH     = <e.g. /Volumes/dld_output  or  Z:\>
DATA_ROOT      = <a folder at or below a .helab-root, e.g. /Volumes/dld_output/2026>
CACHED_FOLDER  = <a run folder below DATA_ROOT, moderate size (< 2 GB of TXY)>
OTHER_FOLDER   = <another run folder below DATA_ROOT>
PHYSICS_FOLDER = <a BEC or thermal run, for M1.7; about 500 shots or fewer: a 1,007-shot
                  folder (22.5 M rows) took 7 min to load and 15.5 min for Release time>
RAM_ONLY_FOLDER= <a folder with no .helab-root above it, or "none">
ACQUIRING      = <yes: the folder being written now | no>
RECORD_TRACE   = <yes | no>  (Help › Record I/O trace for the whole run)
```

## Runbook

Each check is **Do** (the actions), **See** (the text or state that passes) and **Shot** (the
screenshot to save, as `shots/M1.x-<n>.png`). The verdict is `PASS`, `FAIL` (with what was seen
instead), `SKIP` (with the reason) or `REVIEW` (the screenshot is for Tony).

### M1.1 Start-up
1. **Do:** run START_COMMAND and wait until the main window shows (up to 60 s). **See:** a window
   titled HeLab with a folder tree on the left. **Shot:** M1.1-1.
2. **Do:** if RECORD_TRACE is yes: Help › Record I/O trace (this session). **See:** a status-bar
   note that the trace is recording.
3. **Do:** About HeLab, in the HeLab menu on macOS (Help on Windows). **See:** the version
   `0.0.5a1` (or the release version once it's bumped) and a commit starting with HELAB_COMMIT.
   **Shot:** M1.1-3. Close the dialog. (HeLab reopens the last session: folder and plots.)
4. **Do:** the Settings button (left toolbar) › the Cache tab. **See:** an inventory with rows
   and sizes, not an error. **Shot:** M1.1-4. Close Settings without changing anything.

### M1.2 Browse and cache first
1. **Do:** type DATA_ROOT into the path bar and press Enter. Expand the tree down to
   CACHED_FOLDER and select it. **See:** within 60 s the summary under the path bar shows shot
   counts, and Folder details shows ⚓ (a data root). **Shot:** M1.2-1.
2. **Do:** wait until the load finishes (Folder details: State idle or loaded). Select
   OTHER_FOLDER, then select CACHED_FOLDER again. **See:** the data shows at once (no progress
   bar first). **Shot:** M1.2-2.
3. **Do:** quit HeLab (File › Quit), start it again and select CACHED_FOLDER. **See:** first
   "loaded (cached)" or "Checking for changes…", then the same counts as in step 1. **Shot:**
   M1.2-3a while checking, M1.2-3b after.
4. **Do:** if RAM_ONLY_FOLDER isn't "none", select it. **See:** Folder details says "RAM only".
   **Shot:** M1.2-4.

### M1.3 Live during a run
If ACQUIRING is no: `SKIP` ("no run acquiring") and go to M1.4.
1. **Do:** select ACQUIRING's folder. In the Scripts panel on the right, open Counts per shot
   from the group "Basic plots v1". Then press Live on the toolbar. **See:** the summary's third
   line starts "Live", and the tree and path bar are greyed. **Shot:** M1.3-1.
2. **Do:** wait 2 minutes. **See:** the shot count has grown, and the plot's source line shows
   `following Live`. **Shot:** M1.3-2.
3. **Do:** keep waiting until about 10 new shots have arrived (up to 10 minutes). **See:** the
   third line says "saving 10 shots" at some point, or the cache line's time updates. **Shot:**
   M1.3-3.
4. **Do:** press Live again (off). **See:** the third line no longer says Live, and the tree is
   usable. **Shot:** M1.3-4.

### M1.4 Presets and reopened plots
1. **Do:** select CACHED_FOLDER. Open the T histogram from "DLD Front Panel Port" twice. In the
   first plot's settings (the Settings panel at top right), change one number, e.g. its bins
   to 50 (Tab commits a value; Return alone doesn't). Then press the panel's **Save…** button
   and name it `smoke`. **See:** the second plot's Preset row lists `smoke`. **Shot:** M1.4-1.
2. **Do:** in the second plot, apply `smoke` (Apply button), then change one setting (e.g. tick
   Log Y). **See:** a blue dot by that setting and a button "Save 1 change ▾". **Shot:** M1.4-2.
3. **Do:** Presets menu › Save Folder and Plots as Preset…, named `smoke-arrangement`. Close one
   plot (the "x" on its dock title bar; the tab's "x" icon may not respond). Then Presets menu ›
   `smoke-arrangement` (an item, not a submenu), and choose **Replace** in the dialog
   (Replace / Cancel / Add). **See:** both plots are back. **Shot:** M1.4-3 (`REVIEW`: is the
   placement right?).
4. **Do:** quit HeLab with the plots open, then start it again. **See:** the plots come back,
   waiting for or showing CACHED_FOLDER's data. **Shot:** M1.4-4.

### M1.5 Saved analysis results
1. **Do:** with CACHED_FOLDER selected, open Release time from "DLD Front Panel Port", and wait
   until it draws (up to 3 minutes). Hover over the plot's source line. **See:** the tooltip
   ends "saved in the disk cache". **Shot:** M1.5-1.
2. **Do:** quit and start HeLab, select CACHED_FOLDER and open Release time again. **See:** it
   draws within a few seconds, and its source line says "from disk cache". **Shot:** M1.5-2.
3. **Ask the supervisor first:** this clears every saved analysis result under DATA_ROOT,
   including the machine's own from earlier work. **Do:** Settings › Data roots, select
   DATA_ROOT's row (not another root), then Clear cached analysis… and confirm. **See:** a
   confirmation dialog first ("Clears N saved results…"); afterwards the row's Cached column
   still shows data. **Shot:** M1.5-3. Close Settings with Cancel.

### M1.6 Work Offline
1. **Do:** File › Work Offline. **See:** "Offline · cached data only" in the status bar, and
   Live greyed. **Shot:** M1.6-1.
2. **Do:** select CACHED_FOLDER and open Counts per shot. **See:** the data shows, with "not
   checked (offline)", and the plot draws. **Shot:** M1.6-2.
3. **Do:** select OTHER_FOLDER's parent and expand a subfolder you haven't opened before.
   **See:** either saved counts, or "Not listed while online" / "Data not kept (offline)". No
   spinner keeps going. **Shot:** M1.6-3.
4. **Do:** click the status-bar "Offline · cached data only" › Yes. **See:** "Offline" goes, and
   the selection shows "Checking for changes…". **Shot:** M1.6-4.
5. Unmounting the share and restarting offline: `SKIP` unless the supervisor does the unmount.

### M1.7 DLD plots on real data
1. **Do:** select PHYSICS_FOLDER. From "DLD Front Panel Port", open each plot in turn: T, X, Y
   histograms, Density images, Mean X, Y, T spectrum, Shot times, Shot trends, Release time,
   Velocity distributions, Correlations, Transfer fractions. Wait for each to draw (up to 3
   minutes; Release time and Velocity distributions may take longer on a big folder, so allow
   up to 20 minutes and start the next plot only after the previous one has drawn). **See:**
   every plot draws, with no "failed" line (amber notes are fine; copy them into the results).
   **Shot:** M1.7-<plot> for each (`REVIEW`: ms/mm axis labels, wrapped titles, ħ, physics).
2. **Do:** close the plots.

### M1.8 Settings panel and floating plots
1. **Do:** open three plots (any). Click each plot's tab in turn. **See:** the Settings panel's
   title names the plot clicked each time. **Shot:** M1.8-1.
2. **Do:** double-click one plot's title to float it. Click inside the floating window, then
   inside the main window's plot. **See:** the panel follows the click, and the floating window
   has its own settings on its right. **Shot:** M1.8-2.
3. **Do:** in a T box of the DLD port's settings, type `20,450.5` and press Enter, then
   `20.45 s`, then `abc`. **See:** the first two are accepted, and `abc` stays red. **Shot:**
   M1.8-3.
4. **On Windows:** open the 3D scatter for the first time this session. Note whether the main
   window closes and reopens, and whether the plot pane is black. **Shot:** M1.8-4 (`REVIEW`, Q1.7).
5. **Do:** File › Quit. If RECORD_TRACE was yes, note Help › Show I/O trace folder's path first.

## results.md template

```markdown
# Smoke pass on <MACHINE>, <date>

Runner: <model> via <computer-use tool>. Supervisor: <name>. Config: <paste the config>.

| Check | Verdict | Seen / note | Shot |
|---|---|---|---|
| M1.1-1 | PASS | | shots/M1.1-1.png |
| … | | | |

Stops (unknown dialogs, questions asked): …
Trace folder: …
```

## Guidance for a small model

- One action, then a fresh screenshot. Don't plan several clicks ahead from an old screenshot.
- Match text literally. "Checking for changes…" is not the same as "Check failed". If unsure,
  mark `REVIEW`.
- Menus: open one, take a screenshot, then click the item.
- Waiting: take a screenshot every 10–20 s up to the stated limit. Don't click while waiting.
- Keep `results.md` updated after each check, so an interrupted run keeps what it found.
- Budget about 45–60 minutes per machine. M1.3 depends on the run.
- Dropdowns (the script Group, preset popups): click an empty part of the script list, press
  shift+Tab twice to focus the Group combo, then Down. Don't open the popup: while it is open
  every click and key fails until a person clicks.
- Quit: after File › Quit, check the process has gone before starting HeLab again; two instances
  share one bundle ID. Cmd+Q needs the system-keys grant.
- Screenshots: the background tools can't save files yet (see
  [roadmap](../../../roadmaps/smoke-automation.md)); quote the seen text in `results.md`.

## Before the first real run

1. A dry run on Tony's Mac, with a larger model watching, to fix wording in the runbook where
   the screen differs (A5.1). First pass done 2026-10-28: results in
   [smoke-mac/results.md](../2026-10-28-claude-smoke-mac/results.md); what blocked unsupervised
   driving, ten build suggestions and the runbook fixes in
   [smoke-mac/computer-use-notes.md](../2026-10-28-claude-smoke-mac/computer-use-notes.md).
2. On a lab PC: check the computer-use tool can see and control a Qt window there (a scaled
   display, the black QtWebEngine pane), and that the small model reads Qt's text reliably at
   that resolution.
3. Decide which model runs it: Haiku 5.5 for cost, or Sonnet 5.5 if Haiku misreads the screen
   in the dry run (Q5.1).
