# Smoke pass hand-over: v0.0.7 (M1.1–M1.10) on another machine

Written 2026-10-30 by Side (the Assistant on Ground) at Tony's request in Chat. It is meant to be
handed to whoever runs the release smoke pass on another computer, a person or a computer-use
model, and needs nothing else from this repository to start. It supersedes the
[2026-10-28 runbook](../2026-10-28-claude-smoke-automation/plan.md) for v0.0.7: the steps are
those of [MANUAL_TODO, Release smoke pass](../../MANUAL_TODO.md#release-smoke-pass) (which wins
if the two differ), plus the runner tools of the Smoke ready and Runner Tools floors.

**Before those floors land** (check `git log` for "Smoke ready" and "Runner Tools"), the Debug
menu items, `--geometry`, Dump State, the milestone log lines and `dev/dev_app.py` below don't
exist yet: use the "older route" given beside each.

## 1. Who does what

- **Runner:** a person, or a model with computer use on the machine under test (Sonnet 5.5, or
  Haiku 5.5 if it reads the screen reliably). It judges each check only by the text here.
- **Supervisor:** Tony (or the Assistant in Chat). Fills in the config (§3), answers the runner's
  stop questions, and reviews `REVIEW` and `FAIL` results.
- **Output:** a folder `.ai/sessions/<date>-<tool>-smoke-<machine>/` with `results.md` (§7) and
  `shots/`. Send it back as in §8.

## 2. Setting up the machine (once)

Python 3.13 through uv, as in the README's "Setup (any machine)":

```bash
git clone https://github.com/TonyXTYan/HeLab.git && cd HeLab
git checkout <CANDIDATE>          # the release candidate the supervisor names (§3)
uv python install 3.13
uv venv --seed --python 3.13 venv && source venv/bin/activate   # Windows: venv\Scripts\activate
uv pip install -r requirements.lock -e .
```

Starting HeLab for the pass:

- **macOS, driven by computer use:** a source run has no bundle ID, so the tools can't target it.
  Build the stub once: `python dev/dev_app.py`, then start with
  `open .ai/local/HeLab-dev.app --args --geometry 1600x928+0+39`. It shows as "HeLab-dev",
  bundle ID `au.edu.anu.he-bec-lab.dev`, so a released HeLab running beside it never answers for
  it. Quit it before opening it again (`open` on a running app drops the new arguments; `open -n`
  makes a second copy with the same ID). *Older route:* build `dist/HeLab.app`
  (`pyinstaller HeLab.spec --clean -y`, several minutes) and `open -n dist/HeLab.app`.
- **macOS or Windows, by hand:** `helab --geometry 1600x928+0+39` (Windows
  `venv\Scripts\helab.exe …`). Without the floors, leave out `--geometry`.

Data:

- The lab share mounted (`/Volumes/dld_output`, or the mapped drive on a lab PC).
- **For M1.9:** a scratch folder on the local disk (not the share), e.g. `~/helab-smoke-live/`.
  Raw files to copy into it during the step come from the test data's `data/live/raw-20/` (20
  consecutive raw shots, ~7 MB) if Tony has given you the test-data set, or else from
  `~/HeLab-samples/txy-v1/2024-11-rt-low-occupancy/` (raw `d*.txt` only), or else from any run
  folder on the share (copy *from* it; never write into the share).

## 3. Config (the supervisor fills this in)

```text
MACHINE         = <name>, <macOS or Windows version>
CANDIDATE       = <branch or commit; About HeLab must show its version and commit>
VERSION         = <what About should show: 0.0.7a1 on the PR branch; dev/v0.0.7 still says 0.0.6a1>
START_COMMAND   = <from §2>
SHARE_PATH      = <e.g. /Volumes/dld_output or Z:\>
DATA_ROOT       = <a folder at or below a .helab-root on the share>
CACHED_FOLDER   = <a run folder below DATA_ROOT, under ~2 GB of TXY>
OTHER_FOLDER    = <another run folder below DATA_ROOT>
PHYSICS_FOLDER  = <a BEC or thermal run of about 500 shots or fewer, for M1.7>
RAM_ONLY_FOLDER = <a folder with no .helab-root above it, or "none">
ACQUIRING       = <the folder being written now, or "no">
LIVE_SCRATCH    = <the local scratch folder for M1.9>
OLD_BUILD       = <macOS only, M1.10: the released 0.0.6a1 HeLab.app, or "none">
RECORD_TRACE    = <yes | no>  (Help › Record I/O trace for the whole run)
```

## 4. Safety rules for the runner (verbatim in its prompt)

1. Work only in HeLab's windows and the dialogs it opens. Don't open Finder or File Explorer, a
   terminal, a browser (except a page HeLab's "Open in browser" opens) or any other app, except
   where a step says to copy files into LIVE_SCRATCH.
2. **Never change the data share.** Don't use, on the share: Place .helab-root…, Delete
   .helab-root…, Save to folder…, It's a copy…, Write beside, or any file operation.
3. Change only the settings this runbook names. Never use: Clear all, Remove old entries,
   Change… (moving the cache), Reset all settings, Forget, Clear cached data… (datasets).
4. The only clearing allowed is **Clear cached analysis…** on DATA_ROOT (M1.5), after asking.
5. A dialog or message this runbook doesn't describe: **stop**, take a screenshot, ask the
   supervisor. Never click through an unknown dialog.
6. Never type credentials or answer a system permission prompt; ask the supervisor.
7. An action that doesn't give what's expected: screenshot, try once more at most, then `FAIL`
   with what you saw, and go on.
8. Quit HeLab only where a step says so, with File › Quit (Cmd+Q / Alt+F4), never by force. Then
   make sure the process has gone before starting it again.

## 5. How to drive it

- **Menus over popups.** Use the Debug menu instead of clicking combos, popups or tab icons:
  - Debug › Script Group › <group> (not the Group combo's popup, which jams the accessibility
    tree until a person clicks);
  - Debug › Run Plot › <plot>; Debug › Show Plot Tab › / Close Plot Tab › <title> (a plot tab's ×
    isn't reachable by accessibility);
  - Debug › Settings Tab › <tab>;
  - Debug › Save Window Screenshot… for every `Shot:` (type the path `shots/M1.x-n.png`), or Save
    Screenshot of Window › for a floating plot;
  - Debug › Dump State… after a check whose `See:` is text: it saves the summary lines, Folder
    details, status bar and each plot's source line as JSON. Quote the field in `results.md`.

  *Older route:* the Group combo by keyboard (click an empty part of the script list, shift+Tab
  twice, Down); close plots with the × on the dock's title bar; quote seen text instead of saving
  shots.
- **Controls have names.** Every button, box and field has an accessible name and a stable ID, so
  find controls by name rather than by pixel.
- **Waiting.** Don't poll screenshots. HeLab's log (Help › Show log folder; the newest
  `helab-<pid>.log`) gets one line when a long step ends:
  `MILESTONE load_done folder=… shots=… source=cache|folder|check|save …`,
  `MILESTONE plot_done script=… plot=… state=ok|failed|cancelled …`,
  `MILESTONE convert_done folder=… by=live|cli converted=… …`. Wait for the line, then take one
  screenshot. *Older route:* a screenshot every 10–20 s up to the step's limit, no clicks.
- **One action, then a fresh screenshot.** Match text literally ("Checking for changes…" is not
  "Check failed"); unsure means `REVIEW`.
- **Plot settings:** Return now commits a typed value and closes the editor (older route: Tab).
- Keep `results.md` updated after each check. Budget 45–60 minutes per machine, plus M1.3's
  acquisition and M1.10.

Each check below is **Do**, **See** (what passes) and **Shot** (`shots/M1.x-n.png`). Verdicts:
`PASS`, `FAIL` (with what was seen), `SKIP` (with the reason) or `REVIEW` (for Tony).

## 6. The checks

### M1.1 Start-up
1. **Do:** START_COMMAND; wait for the main window (up to 60 s). **See:** a HeLab window with a
   folder tree on the left. **Shot:** M1.1-1.
2. **Do:** if RECORD_TRACE: Help › Record I/O trace. **See:** a status-bar note that it records.
3. **Do:** About HeLab (the HeLab menu on macOS, Help on Windows). **See:** VERSION, and a commit
   starting with CANDIDATE's. **Shot:** M1.1-3. Close it.
4. **Do:** Debug › Settings Tab › Cache (older: the Settings button › Cache). **See:** an
   inventory with rows and sizes, not an error. A first start on this machine shows an empty
   store. **Shot:** M1.1-4. Close Settings without changing anything.

### M1.2 Browse and cache first
1. **Do:** type DATA_ROOT in the path bar, Enter; expand down to CACHED_FOLDER and select it.
   **See:** shot counts in the summary within 60 s; Folder details shows ⚓. **Shot:** M1.2-1.
2. **Do:** wait for `load_done` for that folder; select OTHER_FOLDER, then CACHED_FOLDER again.
   **See:** the data shows at once. **Shot:** M1.2-2.
3. **Do:** File › Quit, start again, select CACHED_FOLDER. **See:** "loaded (cached)" or
   "Checking for changes…" first, then the same counts. **Shot:** M1.2-3a, M1.2-3b.
4. **Do:** if RAM_ONLY_FOLDER isn't "none", select it. **See:** "RAM only" in Folder details.
   **Shot:** M1.2-4. **Lab PC:** note how long selecting a cached folder takes.

### M1.3 Live during a run
If ACQUIRING is "no": `SKIP` ("no run acquiring").
1. **Do:** select ACQUIRING. Run Counts per shot ("Basic plots v1"), a T histogram and the 3D
   scatter. Press Live. **See:** the summary's third line starts "Live"; tree and path bar
   locked. **Shot:** M1.3-1.
2. **Do:** wait 2 minutes. **See:** the count grows; plots show `following Live`. A shot being
   written shows "still being written". **Shot:** M1.3-2.
3. **Do:** wait for about 10 new shots (up to 10 min). **See:** "saving 10 shots", then the cache
   line's time updates. **Shot:** M1.3-3.
4. **Do:** with Live on, File › Quit. **See:** the quit window lists what it is saving and
   closes by itself; at the next start the shots come from the cache. **Shot:** M1.3-4.

### M1.4 Presets and reopened plots
1. **Do:** select CACHED_FOLDER. Run the T histogram ("DLD Front Panel Port") twice. In the first,
   set bins to 50 (Return), then the panel's **Save…** as `smoke`. **See:** the second plot's
   Preset row lists `smoke`. **Shot:** M1.4-1.
2. **Do:** in the second plot, Apply `smoke`, then tick Log Y. **See:** a dot by Log Y and
   "Save 1 change ▾". **Shot:** M1.4-2.
3. **Do:** float one plot (double-click its title). Presets › Save Folder and Plots as Preset…,
   `smoke-arrangement`. Close a plot, then Presets › `smoke-arrangement` › **Replace**; then again
   with **Add**. **See:** Replace restores both plots in place (the floating one's place and size);
   Add opens them beside the open ones. **Shot:** M1.4-3 (`REVIEW`: placement).
4. **Do:** quit with plots open; start again. **See:** the plots come back, waiting for or showing
   CACHED_FOLDER. **Shot:** M1.4-4.

### M1.5 Saved analysis results
1. **Do:** Settings › Cache › tick **Reuse saved analysis results** (off by default), OK. With
   CACHED_FOLDER selected, run Release time ("DLD Front Panel Port"); wait for `plot_done` (up to
   3 min). Hover the plot's source line. **See:** the tooltip ends "saved in the disk cache"; the
   folder gets the grey REPORT badge; Folder details says "Cached analysis: 1 result". **Shot:**
   M1.5-1.
2. **Do:** quit, start, select CACHED_FOLDER, run Release time. **See:** it draws within seconds,
   "from disk cache". **Shot:** M1.5-2.
3. **Ask the supervisor first.** **Do:** Settings › Data roots, DATA_ROOT's row, Clear cached
   analysis…, confirm. **See:** it asks first ("Clears N saved results…"); afterwards the badge
   goes and the Cached column still shows data. **Shot:** M1.5-3. Then untick Reuse saved
   analysis results again.

### M1.6 Work Offline
1. **Do:** File › Work Offline. **See:** "Offline · cached data only" in the status bar; Refresh,
   Check folder status and Live greyed. **Shot:** M1.6-1.
2. **Do:** select CACHED_FOLDER, run Counts per shot. **See:** data with "not checked (offline)";
   the plot draws. **Shot:** M1.6-2.
3. **Do:** expand a subfolder not opened before. **See:** saved counts, or "Not listed while
   online" / "Data not kept (offline)"; nothing keeps spinning. **Shot:** M1.6-3.
4. **Do:** the status-bar button › Yes. **See:** "Offline" goes; the selection is checked again.
   **Shot:** M1.6-4. Unmounting the share: `SKIP` unless the supervisor does it.

### M1.7 DLD plots on real data (for Tony's eye)
1. **Do:** select PHYSICS_FOLDER. Run each "DLD Front Panel Port" plot in turn, each after the
   previous `plot_done`: T, X, Y histograms (with a fit), Density images, Mean X, Y, T spectrum,
   Shot times, Shot trends, Release time, Velocity distributions (up to 20 min on big folders),
   Correlations, Transfer fractions. **See:** every plot draws with no "failed" line (copy amber
   notes). **Shot:** M1.7-<plot> each (`REVIEW`: T like `20,450`, X/Y in mm, titles not clipped,
   ħ shown, physics). Close the plots.

### M1.8 Plot settings panel and floating plots
1. **Do:** three plots tabbed; show each tab in turn and click inside each plot (the 3D scatter's
   web view too). **See:** the Settings panel follows the plot. **Shot:** M1.8-1.
2. **Do:** float one; click between it and the main window. **See:** the floating plot's settings
   open on its right; docking it again keeps its edits. **Shot:** M1.8-2.
3. **Do:** in a T box type `20,450.5`, Return; `20.45 s`, Return; `abc`, Return. **See:** the
   first two are taken; `abc` stays red. **Shot:** M1.8-3.
4. **Lab PC:** the 3D scatter's first open this session: does the main window close and reopen,
   and is the pane black (then Open in browser)? **Shot:** M1.8-4 (`REVIEW`, Q1.7).

### M1.9 Live convert and plot update
1. **Do:** copy three raw `d<N>.txt` (no TXY) into LIVE_SCRATCH. In HeLab, open LIVE_SCRATCH and
   right-click › Place .helab-root here… (this is the local scratch folder, never the share).
   Start Live, turn on Auto-convert, run Shot trends and a density image. **See:** the left panel
   collapses; the three shots convert (the Live line counts them; `convert_done … by=live`); no
   damaged or no-hit warning. **Shot:** M1.9-1.
2. **Do:** copy three more raw files in, one every ~10 s. **See:** each converts once written;
   the plots update with each; the data's source reads HeLab (`m19v1`); no file appears in
   LIVE_SCRATCH except the raw ones and `.helab-root` (Write beside is off). **Shot:** M1.9-2.
3. **Do:** Live off. **See:** the save and the tree usable again. **Shot:** M1.9-3.

### M1.10 Two versions on one Mac (macOS only)
If OLD_BUILD is "none" or this is a lab PC: `SKIP`.
1. **Do:** open CACHED_FOLDER in the candidate, change one setting, quit. Open OLD_BUILD (0.0.6a1),
   open the same folder, change a setting, quit. Open the candidate again. **See:** neither
   version loses or rewrites the other's cache; no question about clearing the cache or replacing
   a `.helab-root`; settings each version doesn't know are left alone; Settings › Cache in the
   candidate still lists its converted TXY. **Shot:** M1.10-1 (each start).

## 7. results.md template

```markdown
# Smoke pass on <MACHINE>, <date>

Runner: <person or model> via <tool>. Supervisor: <name>. Config: <paste §3>.

| Check | Verdict | Seen / note | Shot |
|---|---|---|---|
| M1.1-1 | PASS | | shots/M1.1-1.png |
| … | | | |

Stops (unknown dialogs, questions asked): …
RERUNs, crashes, hangs (with the log file's name): …
Trace folder (if RECORD_TRACE): …
```

## 8. Sending the results back

- Commit the session folder on a new branch `smoke/<date>-<machine>` from CANDIDATE and push it to
  `TonyXTYan/HeLab` (a new branch only; never push to `dev/*` or `main`). Or zip the folder and
  send it to Tony.
- Leave out anything private: no account names, no passwords, nothing from a dialog you weren't
  asked to read. Screenshots of HeLab with the share's folder names are fine.
- Attach the log file (`helab-<pid>.log`) for any crash, hang or `FAIL`.
- The Assistant then carries the results into the docs and failures into known-issues (A1.8).
