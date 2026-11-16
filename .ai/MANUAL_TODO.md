# HeLab Manual To-do

The ongoing list of work requiring manual action, including native UI checks,
real-volume testing and release validation. Product features belong in the
[roadmap overview](../roadmaps/_readme.md), known issues in [known-issues.md](../roadmaps/known-issues.md).

Keep items concise and tick them when completed. Record detailed results, tested
commit, OS/build and reproductions in `.ai/sessions/`, linked from the item.
New confirmed bugs go in `roadmaps/known-issues.md`, new features in `roadmaps/_readme.md`, with a link to the evidence.

The v0.0.5a checks below were added on 2026-10-08 and remain pending.

Decisions only Tony can make are in [DECISIONS_TODO](DECISIONS_TODO.md), and work agents
may do without asking in [AI_TODO](AI_TODO.md). Items here have `M` IDs ([ID_BLOCKS](ID_BLOCKS.md)): the
smoke pass is M1.1–M1.10 (M1.9 added 2026-10-29, Q24.3; M1.10 the same day, block 27), and older items get IDs as they're touched. Items below the smoke pass that it doesn't
cover are lab validation, and don't gate a release (Tony, 2026-10-28: Q1.1).

## Release smoke pass

**v0.0.7a1 (released 2026-10-31, TonyXTYan/HeLab#10):** the Mac pass ran in part on `6dec236` by
computer use with the [runbook](sessions/2026-10-30-claude-smoke-handoff/runbook.md)
([results](sessions/2026-10-30-claude-smoke-final-mac/results.md)): M1.1, M1.2-1 and M1.2-3, M1.6-1,
M1.6-2 and M1.6-4 passed; M1.7's 13 DLD plots all drew (the physics is Tony's to review); M1.4-1 is to
review. Its one bug, the plot settings table's Value column off the right edge in a narrow panel, was
fixed before the release (`42a82b0`). Tony released without waiting for the rest (2026-10-31), and
0.0.8a1 (2026-11-04, TonyXTYan/HeLab#11) shipped without them too, so these are still open for v0.0.9:
- on a Mac: M1.4-2 to M1.4-4, M1.5, M1.6-3, M1.8, M1.9 and M36.1–M36.4; by hand, the plot/settings
  splitter drags and two newly floated plots opening offset (Q33.3). M1.3 (nothing acquiring) and M1.10
  were skipped;
- the lab PC pass (M1.1–M1.10 on Windows), with M1.3, Live during an acquisition.

These checks gate a release (Tony, 2026-10-28: Q1.1; amended for v0.0.6a1 by Q6.1, and for v0.0.7a1 on 2026-10-31, above). Run the pass once
on a Mac and once on a lab PC (Windows), on the release candidate. Steps marked **Lab PC**
matter most there. Each machine takes about 45 min, and step 3 needs a run acquiring.

The Assistant takes Tony through it in Chat, one step at a time. Tony answers "ok" or says
what he saw. Results go to a session file per machine
(`sessions/<date>-<tool>-smoke-<machine>/results.md`: the machine, OS, commit, trace folder
and each step's result), and problems go to [known-issues](../roadmaps/known-issues.md).
Afterwards, an agent ticks the items below that the pass covered
(A1.8, [AI_TODO](AI_TODO.md)).

A small model can drive most of it through computer use, with Tony reviewing the screenshots:
see the [runbook](sessions/2026-10-30-claude-smoke-handoff/runbook.md) (Q5.1; the first one,
[plan](sessions/2026-10-28-claude-smoke-automation/plan.md)). Its dry run on the
Mac (A5.1, 2026-10-28, Sonnet 5.5) is in
[results](sessions/2026-10-28-claude-smoke-mac/results.md).

**Setup:**
- A checkout of the release candidate, with its venv: `source venv/bin/activate` (Windows
  `venv\Scripts\activate`), then `helab`.
- The share mounted: `/Volumes/dld_output`, or the mapped drive.
- Optional: turn on Help › Record I/O trace (this session) for the whole pass, so an agent
  can summarise the share traffic afterwards.

### M1.1 Start-up
- **Do:** About HeLab (the HeLab menu on macOS, Help on Windows).
- **Expect:** the release's version (`helab/_version.py`), the commit you checked out, the branch.
  Settings → Cache shows the inventory. A first start on this machine starts an empty `store-v4` (from
  0.0.8); where an older HeLab's `store-v3` is in the cache folder, "An older disk cache" asks once (Keep,
  Ignore or Clear…, Q44.1).

### M1.2 Browse and cache first
- **Do:** browse the share two levels into a data root (a folder with a `.helab-root` at or
  above it). Select a run folder and let it load. Select another folder, then go back to the
  first one.
- **Expect:** the data shows at once on return. For a cached folder: "loaded (cached)", then
  "Checking for changes…", then checked. Folder details shows ⚓ and the marker, or "RAM only"
  without one. The tree's badges and the ANCHOR badge are on root folders.
- **Do:** quit and start again, then select the same folder.
- **Expect:** data from the disk cache at once, then the check. Counts agree with before.
- **Lab PC:** the same, and note how long selecting a cached folder takes.

### M1.3 Live during a run (needs an acquisition)
- **Do:** select the run folder being written. Open Counts per shot, a T histogram and the
  3D scatter. Turn Live on.
- **Expect:** new shots within a few seconds of their last write. A shot being written
  shows "still being written". Plots show `rev N · following Live` (the scatter at most
  every 5 s). The tree and path bar are locked; switching tabs turns Live off.
- **Do:** after 10 new shots, check line 3 and the cache line. Then turn Live off.
- **Expect:** "saving 10 shots", then the cache line updates. Live off saves once more.
- **Do:** with Live on, quit (Cmd+Q / File › Quit).
- **Expect:** the quit window names the folder and closes by itself. At the next start the
  shots come from the cache.
- **Lab PC:** the same; the GUI stays responsive with the plots open.

### M1.4 Presets and reopened plots
- **Do:** open two plots of one script. In one, change a setting and save a preset from its
  Presets row. In the other plot, the preset is listed at once. Apply it, then change one
  setting.
- **Expect:** a dot by the changed setting, and "Save 1 change ▾".
- **Do:** Presets menu › save an arrangement with plots in two tab groups and one floating.
  Close some plots, then apply it with Replace, and again with Add.
- **Expect:** Replace restores the places (the floating window's place and size, the front
  tab). Add opens its plots beside the open ones.
- **Do:** quit with plots open and start again.
- **Expect:** the plots come back in place, waiting until their folder is selected (or
  running at once if it's cached). The startup tab's own selection is unchanged.

### M1.5 Saved analysis results
- **Do:** turn on Settings → Cache › Reuse saved analysis results (off by default since Q27.1); on a
  folder below a `.helab-root`, open a DLD port Correlations plot (radial), or
  Release time. Wait for it to draw, and look at the source line's tooltip.
- **Expect:** the record ends "saved in the disk cache". The folder's row gets the grey
  REPORT badge, and Folder details says "Cached analysis: 1 result, <size>".
- **Do:** quit, start, load the folder and open the same plot.
- **Expect:** it draws at once, "from disk cache, computed …".
- **Do:** Settings → Data roots › Clear cached analysis… on that root.
- **Expect:** it asks first; afterwards the badge goes, and the cached data stays.

### M1.6 Work Offline
- **Do:** File › Work Offline.
- **Expect:** the check mark and "Offline · cached data only" in the status bar. Refresh,
  Check folder status and Live are greyed, with the reason.
- **Do:** browse the tree, select the folder loaded in step 2 and open a plot on it.
- **Expect:** counts and icons from saved listings; "not checked (offline)"; the plot runs.
  A folder never loaded says "Data not kept (offline)…". Nothing spins.
- **Do (if practical):** unmount the share, quit, start again (HeLab starts offline), and
  repeat the browse.
- **Do:** the status-bar button › Yes (Work Online).
- **Expect:** every tab relists, the selection is checked, the controls come back.

### M1.7 DLD plots on real data (a quick look)
- **Do:** on a BEC or thermal run, open each DLD Front Panel Port plot in a narrow (~560 px)
  dock: T, X, Y histograms (turn on a fit), Density images, Mean X, Y, T spectrum, Shot
  times, Shot trends, Release time, Velocity distributions, Correlations, Transfer
  fractions.
- **Expect:** every plot paints (the lab PC too: PyQtGraph, no QtWebEngine). T axes read like
  `20,450` (not `2.045e+04`) and X/Y are in mm. Titles wrap with nothing clipped, warnings are
  amber, and "ħk/m" shows ħ (not h). Zoom stays through Live reruns.
- **Note anything that looks physically wrong.** The detailed physics checks are after the
  release (MANUAL_TODO, "On real data").

### M1.8 Plot settings panel and floating plots
- **Do:** three plots tabbed. Click each tab, click inside each plot (including the 3D
  scatter's web view), then float one plot and click between it and the main window.
- **Expect:** the Settings panel follows the plot clicked. A floating plot's settings
  open on its right; docking it again brings the page back with its edits.
- **Do:** in a T box, type `20,450.5`, `20.45 s` and `abc`.
- **Expect:** the first two are read; `abc` stays red.
- **Lab PC:** the 3D scatter's first open: does the main window close and reopen
  (Q1.7, [DECISIONS_TODO](DECISIONS_TODO.md#q17-windows-3d-scatter-window-flicker))? If the pane is black, Open in
  browser works.

### M1.9 Live convert and plot update (Q24.3, Tony 2026-10-29)
- **Do:** make a scratch folder with a data root (Place .helab-root here…), copy three raw
  `d<N>.txt` from `~/HeLab-samples/txy-v1/2024-11-rt-low-occupancy/` into it (raw files only, no
  TXY), open it, start Live, turn on Auto-convert, and open Shot trends and a density image. Then
  copy three more raw files in, one every ~10 s.
- **Expect:** each shot converts once written (the Live line counts them; no damaged or no-hit
  warning for these shots), the plots update with every new shot, and the data's source reads
  HeLab (`m19v1`). Turning Live on collapses the left panel. Nothing is written into the folder
  unless Write beside is on.

### M1.10 Two versions on one Mac (Tony 2026-10-29, block 27)
- **Do:** with the released 0.0.6a1 build and a source build of v0.0.7 on one Mac (one settings
  store, one cache folder), open a cached folder in v0.0.7, quit, open it in 0.0.6a1, quit, and
  open it in v0.0.7 again; change a setting in each.
- **Expect:** neither version loses or rewrites the other's cache (both use store-v3's layout 3,
  so 0.0.6a1 opens it writable: check it leaves v0.0.7's `convert_prefs` rows and HeLab's
  `converted-txy/` alone; only a higher layout opens read-only), settings each version doesn't know are left alone, and nothing
  asks to clear the cache or replace a `.helab-root`.

## Live timing, in the lab (added 2026-10-30, block 33)

- [ ] **M33.1** Once the lab acquires again: on a Live run with auto-convert, measure the delay from
  each shot's last write (its mtime) to its TXY and the plot update (the log's `MILESTONE
  convert_done` / `plot_done` once Runner Tools lands), for a few dozen shots; then choose the Live
  interval and settle time defaults (Q33.7; now 3 and 5 s, so ~5–8 s).
- [ ] **M36.4 The settle time setting on a live run** (block 36; with M33.1): Settings › General, set
  "Read files unmodified for" to 10 s and watch Live on a run being written: shots appear ~10 s after
  their file stops changing.

## UI polish (added 2026-10-30, block 36)

- [ ] **M36.1 The main split on a real screen** (Mac and a lab PC): open two plots: folders 380, settings
  ~330, plots the rest; drag the splitters, quit, relaunch: the widths come back; Live on still collapses
  the folder panel. On the lab PC (Segoe UI 9 pt) nothing in the settings panel is cut at 320 px; drag it to
  its least (250 px) and note what is cut (Q36.3); at a large display scale the Scripts row's button may be.
- [ ] **M36.2 Floating plots** (Mac): float two plots from their title's float button: they open 800×600 a
  step apart; a double-click on a title does the same; the Dock button docks each. With one floating and
  the main window active, the panel names the docked plot and its title's Float floats that one. Pick the
  floating plot from the Settings panel's chooser and check the panel ends on it (the popup's close gives
  focus back to the main window first; offscreen tests can't show which wins).
- [ ] **M36.3 A path too long on Windows** (a lab PC without long paths): a user profile converting beside
  raw files in a deep folder shows "Path too long for Windows …" in the Live line's tooltip; or check
  `LongPathsEnabled` there and note it.

## Beside conversion on the lab share (added 2026-10-31, block 38)

- [ ] **M38.1 Can the lab share add a file without replacing one?** (Tony, on the Mac with the lab share
  mounted; Q38.1): in a scratch folder on the share (never a data folder), run the probe in Quick Fixes 7's
  [notes](sessions/2026-10-31-claude-quick-fixes-7/notes.md) §1 (`python3 -I probe.py <scratch folder>`).
  It reports whether `os.link` works and whether `renamex_np(RENAME_EXCL)` refuses an existing name and
  renames onto a new one, then leaves files `a`, `b`, `c` to delete. If neither works, beside conversion
  on the share from macOS shows Q38.1's warning (decided 2026-11-02; built on the Converter UX floor, landed
  `ed7bcf9`: Retry, or write to HeLab's cache or temp folder instead) rather than failing with the reason
  (`c194f37`); M48.2 checks that question.
  Windows PCs are unaffected (`os.rename` refuses an existing name itself).

## I/O fixes, Plot identity, Caching v2, Quick Fixes 8 (added 2026-10-31, blocks 40–43)

- [ ] **M40.1 Live switching to HeLab's TXY, in the lab** (A39.2; with Live and auto-convert on under
  HeLab priority and MATLAB's converter also running): shots first read from MATLAB's TXY switch to
  HeLab's within two checks of their conversion; no "changed after it was read" note appears on the Live
  line; the log has one INFO line per switched shot.
- [ ] **M41.1 The Dash port beside another program** (Tony, Mac): with another program listening on
  `0.0.0.0:8050` (e.g. a Dash app run with `host="0.0.0.0"`), open a 3D scatter in HeLab: its Open in
  browser URL is on another port, and the other program still answers `http://127.0.0.1:8050`.
- [ ] **M41.2 A profile change while a plot follows Live** (Tony, real data): a raw-only folder with
  auto-convert and a plot following; switch Settings › TXY converter to another profile: the plot reruns at
  once on the new profile's data, and Velocity distributions' title doesn't say "kept from rev N" on that
  run.
- [ ] **M42.1 Time the raw layer's codec on a lab PC** (Q42.2): `dev/txy/check_samples.py --via-layer`
  (in memory, read only) on a copy of the sample set; zstd 9 measured 16 MB/s of raw text per M4 Max
  thread (an estimated 4–5 MB/s on the Sandy Bridge PCs). Too slow for a folder's background fill: zstd 5.
- [ ] **M43.1 Split widths from a wider screen** (app-2; a laptop or lab PC): start HeLab with a split
  saved on a wide monitor, or quit at 1500,600 and start with `--geometry 1600x900+0+0`: the plots get
  at least 240 px and both panels look usable (Q43.3); quitting without dragging keeps the wide widths.
- [ ] **M43.2 One running HeLab** (A39.3; the packaged app on macOS, `open -n HeLab.app` or the binary
  from a terminal, and on Windows): the second start shows "HeLab is already running…" and quits; after
  quitting the first, or killing it, a new start opens normally.

## Caching v2 checkpoint 3 (added 2026-10-31, block 44)

- [ ] **M44.1 Caching v2's dialogs on screen** (switch on, test settings and a temp cache folder only:
  `floor-env.sh`): see the store-v3 question once ("An older disk cache", Q44.1), each Settings › Cache row
  (Raw pulses, Older cache (store-v3)) and its buttons, Make room's text with raw pulses and only copies,
  and Folder details' amber line after overwriting a raw file in a temp folder.
- [ ] **M44.2 Cache export into MATLAB**: run `helab cache export d1.hlb --to mat` on a layer from the
  sample set's via-layer run (or a temp store) and the format page's MATLAB lines
  ([`docs/hlb-format.md`](../docs/hlb-format.md): `load`, `jsondecode(s.header)`).

## Caching v2 stage 2 (added 2026-11-02, block 47)

- [ ] **M47.1 Stage 2's controls on screen** (switch on, test settings and a temp cache folder only:
  `floor-env.sh`): Settings › Cache's TXY data row (shots, folders, size, tags, only copies) and its Clear…,
  the Cache policy combo, Clear all and the purge naming TXY data and raw pulses, and lowering the budget
  below usage asking from its plan; Make room naming TXY layers by group; right-click "TXY for this folder…"
  and "Cache policy for this folder…" (disabled without a data root), and Folder details' TXY line naming
  them (Q47.3: wording kept as built). Since block 50 also: the purge rows per kind (TXY data, HeLab's cached
  raw pulses) and "Everything not used, checked or shown in the last N days" with its question (A47.4);
  setting a folder to "TXY only" offering to remove HeLab's cached raw pulses, "Your d files aren't touched"
  (Q50.9); "N converted when loaded" in the row tooltip and Folder details, and "converted from raw" in a
  plot's TXY line (Q50.7, Q50.8).
- [ ] **M47.2 A load from the raw layer on the lab share** (S3-2's cost note): time a large shot's load from
  the raw layer against reading its HeLab TXY text over the share. Locally the raw step costs more (0.48 s
  against 0.004 s for a 3.25 MB shot on an M4); its gain should be on a slow share and offline. Also
  (Q51.1, Tony 2026-11-03): after a folder load on the share, the background raw fill lists the folder once
  more (Folder details' activity, or the I/O trace in the log); note whether it slows browsing or the next
  load. If it does, Q51.1 (c) follows.

**Q50.18's checks** (Tony 2026-11-02, about 15 minutes; asked for before the v0.0.8 PR, still open after 0.0.8a1
shipped with store-v4 on, 2026-11-04; run them on 0.0.8a1, since v0.0.9 drops the store-v3 question M44.1 looks
at and its Older cache row offers only Clear…; with the run sheet's isolated folders,
`.ai/sessions/2026-10-31-claude-caching-v2/`): M44.1 and M47.1 on screen, then M47.2 (with Q51.1's extra listing)
and M42.1 on a lab PC with the switch on (one Live session).

## Converter UX (added 2026-11-03, block 48)

- [ ] **M48.1 TXY and shares on the lab share** (with M38.1): turn on beside for a folder there (the share's
  warning), Live with auto-convert (the question once), `helab convert --output beside` (the prompt), and
  Folder details' offer on a share folder without TXY (convert to HeLab's cache; the folder then loads).
- [ ] **M48.2 Q38.1's question** on a share without hard links (a FAT USB stick shared, or the lab's SMB if
  M38.1 says so): in Live and in `helab convert`, each choice (Retry, cache, temp, Not now / quit).
- [ ] **M48.3 A raw file with a garbage line during Live**: the Live line, Folder details and the tooltip
  name the read stopped early (Q48.1's wording).

## Live Scripts (added 2026-11-03, block 49)

- [ ] **M49.1 Auto-reload with real editors** (VS Code, PyCharm, vim's rename-on-save) on macOS and Windows:
  one reload per save, plots rerun, nothing reloads while auto-reload is off. On Windows, check that a
  watched script folder can still be renamed or deleted in Explorer while auto-reload is on
  (`QFileSystemWatcher` may hold directory handles).
- [ ] **M49.2 A lab session**: a Live plot of a user script, edited mid-run with a typo, then fixed: the plot
  keeps following on the old code with the amber line, then takes the fixed code.

## TXY priority lists (added 2026-11-03, block 55)

- [ ] **M55.1 The TXY list editor in its three places**: Settings › TXY converter's Edit…; right-click › TXY for
  this folder… ("As Settings"); a plot's TXY button ("As the folder's tab"). Check ticking, dragging and Move up /
  Move down, the summary, and OK off with nothing ticked.
- [ ] **M55.2 Convert this folder…** (right-click, and File › Convert "<folder>"…): pick m23v1, then each
  destination (HeLab's cache, its temp folder, beside the raw files). On a share, beside asks first. Folder
  details' row shows the progress "with m23v1".
- [ ] **M55.3 Live's offer**: Live in a folder whose list is "m23v1 only" with Auto-convert on m19v1: the line's
  "not read here: convert with m23v1?" and the menu item; taking it converts with m23v1.
- [ ] **M55.4 A real folder under `m23v1 › m19v1 › External`** with External, m19v1 and m23v1 TXY: the shots'
  origins in a plot's record, and Folder details' "· N fallback" when the list misses some shots. Also the
  timing on a large folder (A55.3).

## Documentation (added 2026-11-03, block 56)

- [ ] **M56.1 Read the manual's first pages** (`mkdocs serve`, with `requirements-docs.lock` installed): install, data root, Live,
  converting TXY, writing a script, command line, settings, cache. Their labels and numbers were checked against
  the code; the wording, the order and what is left out are yours.
- [ ] **M56.2 Turn on GitHub Pages** on TonyXTYan/HeLab (Settings › Pages › Deploy from a branch: `gh-pages`, `/`)
  once the first published release's Docs site run has made the branch; the same on HeBECANU/HeLab when releases
  are made there. TonyXTYan/HeLab: Pages served `gh-pages` before the v0.0.8 PR, and publishing 0.0.8a1 deployed
  the first version (docs-site run 41749646827, 2026-11-04); left: HeBECANU/HeLab.
- [ ] **M56.3 Help › User manual in a release build**: on a networked computer (the site's version page opens in
  the browser), offline or on a lab PC (the bundled copy opens, and its search works), and from a source run (the
  GitHub page).

## v0.0.8 follow-ups (added 2026-11-03, block 58)

- [ ] **M58.1 The try-import on Windows** (a lab PC): Load Scripts… of a folder, Reload, and a script with
  `input()` at import. The panel shows "Reload (checking)", then the folder's "didn't load" line; no console
  window flashes, and HeLab stays responsive.
- [ ] **M58.2 The bundled manual offline**: Help › User manual with the network off, on a packaged build. The
  bundled copy opens and its search finds results.
- [ ] **M58.3 The site after the first published pre-release**: the site's root shows "No stable release yet",
  linking to `pre-release/`, and the version menu lists the pre-release. On 0.0.8a1 (2026-11-04) the root said
  "No stable release yet"; Tony chose to reword it (A59.2 (b)), so check the root again once that lands. Landed
  `20dd672` (Quick Fixes 10): the root shows "Latest: <version> (alpha)" only after the next published
  pre-release's Docs site run; a stable v0.0.9 makes the root `latest` instead, and the page isn't seen.

## Quick Fixes 10 (added 2026-11-04, block 60)

- [ ] **M60.1 Settings › TXY converter's profiles list on a real screen** (macOS and Windows; A56.4, `0dc4f90`,
  `6722408`): the list's columns (Profile, Version, TXY tag, Kind, Notes, Hash) aligned and nothing cut; a user
  profile's 33-character tag widens its column, and a narrow window scrolls sideways; a built-in's description
  wraps above "Plates in since…", "Content hash…" and "TXY files…". Checked only offscreen at 720×640.
- [ ] **M60.2 v0.0.9's draft release notes** (A59.1, the job's first real run), before publishing: the tag linked,
  GitHub's generated notes, one "Full Changelog" line comparing `v0.0.8a1...v0.0.9`, the Workflow Run link on
  `github.com` (not `api.github.com`), the build list and the asset manifest; no `::warning::` in the release job's
  log about the releases, the history or GitHub's notes.

## Activity window (added 2026-11-04, block 63)

- [ ] **M63.1 The Activity window on a real screen** (macOS and Windows; `5af4a89`): open it from Window › Activity
  and from a click on the status bar; follow a load, a Live session with auto-convert, a Folder details conversion
  and a plot run; Cancel a load, Retry a failed listing, Stop Live, and Pause and Resume background I/O during a
  background scan ("paused by you" on the status bar meanwhile); check that its size is remembered and History marks
  failures.
- [ ] **M63.2 Pause background I/O on a share** (the lab PC, or any slow share): pause while a background load reads
  it, and confirm that it pauses and resumes, and that quitting while paused quits normally.


## Basic plots v2 (added 2026-11-05, block 66)

- [ ] **M66.1 Basic Plots v2 on a real screen and with Live** (`559baa5`): the tree (v2 open, v1 closed), New on a
  second Plot, Shot time on a real run with gaps (and a folder converted later, for the amber triangles), the
  XY/XT/YT options (blur, rate per shot, colour scales, include outside), and Plot info and the one-line dock with long
  folder names and its outdated / ⚠ marks. **On the lab's Windows PC**, open the Scripts group menu at a narrow panel:
  every entry in full.

## Folder info (added 2026-11-05, block 67)

- [ ] **M67.1 Folder info on a real screen** (`03f801e`): a real folder with cached data, saved results, a TXY list and
  constants; a folder with only copies (a raw file moved away, then Retry / Refresh: the mark and "last looked", then
  moved back); a RAM-only folder (Place .helab-root here…); the detail pane on a long results list; the window's height
  on the laptop screen; ⌘I with the folder panel hidden; Live on the folder (This session following each shot, a read
  after each save and on stop). The three Clears on a copy of a real folder: sizes against Settings › Cache's, the
  only-copy paragraph, "Removed …" and the read again, another folder's cache untouched. On macOS and Windows: open and
  close the detail pane several times (it stays put); reopen after moving the main window to the laptop (it fits);
  minimise during Live and restore after a save; on an external monitor, make it taller than the laptop's screen,
  minimise, restore and reopen with ⌘I (its height kept); close it from the title bar and reopen (size kept, and
  minimising still follows Live); and Cmd+H then back (A67.6).
- [ ] **M67.2 Folder info on Windows** (the lab PC): Ctrl+I, the title lines' buttons with Windows' wider fonts, and the
  detail pane on a 1366-pixel-wide screen.

## App updates (added 2026-11-06, block 68)

- [ ] **M68.1 A real update from source** (`ba22460`) on this Mac **and** a lab PC (Windows), each in both modes: a
  branch with a newer green commit (Update and restart → back on the new commit, the status bar's "updated"), then
  Help › Restore previous version (the old commit, and the old venv if the lock changed); and a release-to-release
  update on a checkout at a tag. On Windows watch the updater wait for helpers, the venv rename and the relaunch with no
  console. Never over SSH.
- [ ] **M68.2 The startup check on a lab PC's network**: Help › Check for Updates… names the reason when it can't
  reach GitHub, and startup stays quiet.
- [ ] **M68.3 Windows' locks and consoles** (Sentry's AU-7, AU-8): update while another uv venv's Python with numpy runs
  (e.g. a second checkout's `python -c "import numpy, time; time.sleep(600)"`): the update goes ahead and isn't held by
  that venv's DLLs; and no console window opens during the update (git, uv, the venv check).

## Floating plots as windows (added 2026-11-09, block 69)

- [ ] **M69.1 A floating plot is an ordinary window** (`AnalysisDock.WINDOW_FLAGS`), on this Mac **and** a lab PC
  (Windows): float a plot (its title's float button, a double-click, a drag): it has minimise and maximise
  buttons, minimises (macOS: to the Dock), goes behind the main window when that is clicked, and stays shown
  while HeLab is in the background. Then: does dragging its own title bar onto the plot area still dock it?
  (Offscreen tests can't show it; if not, the Dock button does, and that is to be said in the manual.) A
  restart puts it back floating as a window. While it's minimised, the Settings panel shows another plot.

## Console and stall stacks on Windows (added 2026-11-09, block 70)

- [ ] **M70.1 The TDC PC's console after `96df3ed`** (the overnight hang's fix; known-issues): on the TDC PC,
  `git pull` and start HeLab from PowerShell (`venv\Scripts\helab`). The log's lines keep showing in the
  PowerShell window after "Logging to …" (before the fix nothing did), and they are in
  `logs\console-<pid>.txt` too; text such as "›" and "…" shows as itself, not `â€º`. No "GUI stalled" at the
  start, however slow (only an INFO "GUI event loop's first beat …s"). Then click into the PowerShell window
  to start a selection and leave it for a minute: HeLab stays responsive (its log goes on); press Esc and the
  console catches up. If HeLab ever stalls again, its thread stacks are in `helab-<pid>.log` after
  "GUI stall's thread stacks:": send them over.

## The 2D histograms' memory warning and the console's UTF-8 (added 2026-11-10, block 72)

- [ ] **M72.1 The memory warning** (Q72.1): in the XY, XT, YT histograms with the RAM budget at its default, raise
  X, Y and T bins until the amber line above **Rerun with these settings** appears ("⚠ Estimated memory … of the
  RAM budget …") as you type, before any run. **Undo** puts the bins back and the line goes; set them again,
  press Rerun, then **Cancel**: the run stops. Leave it running: the plot draws and its title says the same; the
  log has one warning per change. With Show › rate per shot and only XY on, switching Show between counts and rate
  per shot moves XY's colour bar between right and left (RV-3).
- [ ] **M72.2 A Windows console's UTF-8** (RV-5): on a lab PC, start HeLab from PowerShell or cmd and make a long
  log line with "σ", "→" or "·" (e.g. a blur note at DEBUG): the console shows them, and keeps printing.

## Live stall (added 2026-11-12, block 74)

- [ ] **M74.1 Live with auto-convert on the TDC PC**: after the next long session, the log has no "Live: no check
  started for" warning (if one appears, the backstop fired: send the log), and fewer GUI stalls than the 70 of
  2026-11-11.
- [ ] **M74.2 An unreadable raw file in Live** (any machine): lock one (Windows: open it exclusively; macOS:
  `chmod 000`). Within about 25 s it shows as unconvertible, "Couldn't be read for 20 s: …", later shots go on,
  and after unlocking it converts on Live off and on.

## Review fixes at 09ca79b (added 2026-11-17, block 75)

- [ ] **M75.1 Laserlock on the real DG1022 and WS8** (N1–N3; nothing ran on an instrument): Release while locked
  with the wavemeter fast (the output must not move after it); each write no bigger than Max step; Find stable range
  with the beam blocked during the hold (it must return, unlocked).
- [ ] **M75.2 An update that rebuilds the venv, on Windows and macOS** (R2): start HeLab and `helab convert` by hand
  during the build; each says HeLab is being updated and stops, and the update finishes and starts HeLab.

## The GUI thread audit (added 2026-11-10, block 73)

- [ ] **M73.1 A dead mapped drive at start** (GT-7, Windows lab PC): with a mapped drive whose server is off,
  start HeLab (expect no wait now), then select a raw-only folder: does the GUI stall, and for how long (A73.2)?
- [ ] **M73.2 Dialogs beside a dead drive** (GT-9, Q73.4, Windows lab PC): with the same drive, Settings › General
  › Browse… (now Qt's own dialog, in the home folder) and Open in File Manager on a folder of it: HeLab stays
  responsive even if Explorer hangs.
- [ ] **M73.3 After a long Live session on the TDC PC** (GT-1, GT-3): no burst of "timed out" helper retries after
  a box was left open; any "GUI stalled" line reaches the log file with its stacks (for the 5.68 s stall).
- [ ] **M73.4 Draw at** (Q73.1): in the XY, XT, YT histograms with bins over 2,048 a side, Image › Draw at: screen
  resolution looks the same at screen size as every bin, zoomed in shows the block means, the plane's title says
  how it is drawn; every bin draws as before. Also Plotly (over 1,000) and Matplotlib.

## Post-2025 plates, in the lab (added 2026-10-29, block 25)

- [ ] **M25.2 TDC input 7:** what is connected, is it enabled, at what threshold, and did anything
  move there in 2025 (Q25.2)?
- [ ] **M25.5 The bursts (Q25.5):** a scope on input 7 and the x1-end amplifier together; a ~10 min
  run with the MCP HV off (bursts gone: the detector or its HV; still there: outside pickup), then
  a few HV settings; inspect the x1 end's feedthrough, cable and amplifier.
- [ ] **M25.4 A calibration run for the 2025 plates:** a free-space halo with ≥100 halo atoms per
  shot, raw files kept, ideally with the MCP pick-off on channel 4 (absolute time sums).

## TXY converter (added 2026-10-29)

- [ ] **M10.1 Count MATLAB's half-written reads on X** (Tony or the Assistant: a listing pass on
  X). Converter stage 1 found one (2019-halos d3667: its TXY is 0.25 s younger than its raw file
  and lacks the shot's end). Others would show as a TXY modified within a few seconds of its raw
  file. Worth knowing before stage 5 compares HeLab with MATLAB on every shot.

- [ ] **M11.1 Time the converter on the lab PCs** (Tony, at each PC, not over SSH: an elevated SSH
  session has poisoned HeLab's cache settings on the Main PC before): numpy and cython, the two
  shipped backends (Q11.2; cython from the CI build), with
  `sessions/2026-10-29-claude-txy-bench/bench.py --mode serial` and `processes-warm` at x2 and x4 on
  a copy of the sample set. Shows whether one core there keeps up with gigabit (Q6.9). Optional:
  repeat the Mac's x12/x16 rows with Safari closed.

- [ ] **M12.1 The converter on the lab share** (Tony, at the acquisition PC): run `helab convert
  --watch <a copy of a run folder> --output temp` while files arrive (or copy them in one by one),
  and check that no shot is read early (mtime granularity; Windows file sharing: a raw file open for
  writing may fail to read, `read_failed`, retried next check). Also check the source's clock against
  this PC's: the partial cleanup and `--once` trust the source's mtimes (a clock over an hour behind
  could make another computer's beside write look old).

- [ ] **M14.1 TXY sources in a plot** (synthetic or a lab copy): open a folder converted by HeLab,
  open a T histogram, switch its TXY between the four choices, check the source line and that Live
  keeps each plot on its own source.
- [ ] **M14.2 A user profile end to end**: Settings → TXY converter, duplicate plates-2022, edit a time
  sum, set it as the conversion profile, Save; convert a folder; check the provenance names it and the
  plots load those TXY (not the old ones).
- [ ] **M15.1 Live auto-convert at the acquisition PC**: Live + Auto-convert on a copy of a run folder
  while raw files arrive: each shot converts once written, the Live line counts them, a truncated file
  waits with its reason, a near-empty shot notifies once; start-at-launch with the folder listed and
  with it unplugged (one notification).
- [ ] **M15.2 The Auto-convert button on Windows and macOS** (its menu arrow, the checked look, the
  menu's texts).

- [ ] **M16.1 The compiled backend on the Sandy Bridge lab PC**: the CI Windows build's `HeLab.exe
  convert --watch <copy of a run> --once --backend cython` loads and converts (no AVX2: cython builds
  with `/O2 /fp:precise`). Supersedes M11.2. (Rust no longer ships, Q11.2.)
- [ ] **M16.2 macOS signing and Gatekeeper** accept the cython `_kernel` extension in a release
  `HeLab.app` (the only compiled converter file that ships since `134e2ec`; rust, mlx and llvmlite
  don't).

- [ ] **M23.1 TXY sources and profiles in the app**: Settings → TXY converter shows "Tabs and Live
  read"; a plot's TXY row has the source and profile combos; HeLab only + plates-2022 loads its own
  data and the source line says `TXY: HeLab only (p22v1)`.
- [ ] **M23.2 The launch folder**: set one, restart: only its tab opens, Live and auto-convert start,
  the left panel collapses; Live off brings it back. In a real HeLab session (it covers the old M18.1, Q15.1).
- [ ] **M23.3 Damaged raw files on the acquisition PC**: a deliberately truncated raw file is reported
  damaged after ~20 s with one notification; later shots convert.

- [ ] **M35.1 HeLab-dev's window in a computer-use screenshot** (block 35): `python dev/dev_app.py
  --env-file .ai/local/floor-env.sh`, `open .ai/local/HeLab-dev.app`, then a computer-use screenshot
  targeting `au.edu.anu.he-bec-lab.dev` shows the main window; also the menu bar's app name (Qt may
  say "Python" or "HeLab").
- [ ] **M34.1 Accessibility on Windows** (block 34; a lab PC): Accessibility Insights or `inspect.exe`
  on HeLab: the toolbar's Live shows AutomationId `live` and Name "Live", a script's Plot button
  `run_helab.counts_per_shot_Plot` / "Plot Counts per shot", a plot tab's close button
  `close_plot_tab_1`; Debug › Run Plot runs a plot.
- [ ] **M34.2 Screenshots on a lab PC**: Debug › Save Window Screenshot… with a PyQtGraph plot and a 3D
  scatter open: what each pane looks like in the PNG.
- [ ] **M34.3 The runner's view on the Mac** (the built `.app`): `app_ax_find` finds "Folder path" and
  `run_…` by AXIdentifier; the Group combo's AXTitle is its current group (expected) and its
  AXIdentifier `script_group`; `app_menu` reaches Debug › Run Plot › … with its items filled (an item
  pressed without the menu opening may be stale and then does nothing); whether a menu item's
  objectName reaches accessibility.
- [ ] **M34.4 `--geometry` and Dump State on the Mac**: `helab --geometry 1600x928+0+39` opens the
  window there (content 1600×928, the frame's top-left at 0,39); Debug › Dump State… writes a JSON
  naming the open folder and plot tabs.
- [ ] **M32.1 Byte units on Windows** (Q26.1, block 32; a lab PC or a CI build): Settings → Cache
  shows "8.0 GiB" for a fresh setting, and an existing 8 GB setting shows "7.5 GiB" and stays
  8 000 000 000 after Save; Folder details' rate reads MiB/s; the status bar's RAM reads GiB.

- [ ] **M30.1 The converted-TXY index in Settings › Cache** (block 30): on a machine with old-build
  `d_txy_helab_*.json` / `folder.json` in `converted-txy/`, open Settings › Cache: the row counts
  them, its tooltip has Cache folder and Temp folder lines, Clear removes them; then convert a folder
  with Live on and see "last used just now".
- [ ] **M30.2 Don't cache and the command line** (Q30.2): mark a folder Don't cache and convert it
  (Live auto-convert or Settings › TXY converter): its TXY go under the temp folder's
  `converted-txy/` and still load as HeLab's. Then `helab convert --watch <it> --once --output cache`:
  the warning and `[y/N]`; Enter → temp, `y` → cache; piped (`< /dev/null`) → temp;
  `--output cache-forced` → cache, no question.
- [ ] **M30.3 Last uses written at quit** (Q30.3): load a converted folder's TXY twice within the hour,
  quit with nothing else saving: the quit window shows briefly and closes by itself; at the next start
  Settings › Cache shows the second load's time. Work more than 10 minutes after the second load,
  then quit: no quit window (the background write already recorded it). Wording, Tony's to change: header "Recording when
  converted TXY were last used before HeLab quits:" (with other saves: "Saving 1 folder to the disk
  cache and recording when converted TXY were last used before HeLab quits:"); entry "Converted TXY
  last used — recording when HeLab's converted TXY were last used". The window shows on quits within 10
  minutes of a load that skipped its mark.

## Data roots (v0.0.5a1, added 2026-10-18)

Native checks of the data-roots stages D1–D4 ([plan](sessions/2026-10-16-claude-data-roots/plan.md)).
Use disposable folders or shares where possible; never place a `.helab-root` on
real experiment data without deciding where its top should be.

- [ ] Place .helab-root here… from macOS on an SMB share: the marker is hidden in
  Windows Explorer on the lab PCs (`UF_HIDDEN`), and from Windows it gets the
  hidden attribute. The folder's cache works after the relisting.
- [ ] A read-only share (or write-protected USB disk): the manual dialog's Copy and
  Save to folder… (writes `.helab-root`, hidden; ⌘⇧. shows it in Finder) give the
  exact file; moved into place by hand, Retry / Refresh finds it.
- [ ] The placement checks: a share's subfolder offers "Place at <top>", Return
  cancels, a nested root and a home folder warn.
- [ ] Windows, a tab at a mapped drive's top (e.g. `Z:\`), nothing selected:
  File › Place .helab-root in “Z:\”… writes `Z:\.helab-root`; with a subfolder
  selected the item names it instead. A tab at `C:\` gets the system-folder
  warning with Cancel as default.
- [ ] One folder through two mounts (e.g. `C/.../dld_output` and the separate
  `dld_output` share): "Same folder or a copy?" opens once; Same folder shares
  one cache; Later reopens at the next sighting; Remind me next session stays
  quiet; "⚓ N to confirm" reopens it.
- [ ] A copied folder or cloned USB disk: It's a copy… keeping either side; the
  other gets a new marker and an empty cache; the original keeps its data.
- [ ] Two same-named USB disks used in turn at `/Volumes/USB`: each keeps its own
  cache; at startup a restored tab on the second disk doesn't show the first
  disk's cached data.
- [ ] The macOS startup disk: a marker in `~/data` works through the firmlinked
  `/Users` path; Windows `C:\` refuses, a data folder works.
- [ ] Folder details shows ⚓ with the marker in use, or RAM only; the tree's ANCHOR
  badge; greyed disk-cache menu items on RAM-only folders; Settings → Data roots
  lists and forgets locations.
- [ ] Settings → Data roots, a mounted row: Show in Finder (macOS) and Show in
  File Explorer (Windows) open the folder with the hidden `.helab-root`
  selected (visible after Cmd+Shift+. / View › Show › Hidden items); Copy path
  gives the file's path. Delete .helab-root… removes it (on Windows too, with
  its hidden attribute), and the folder turns RAM only in Folder details; on a
  read-only share it names the file instead.
- [ ] Settings → Data roots › Clear cached data… on a root with cached folders:
  the confirmation names the label and size; afterwards those folders show
  no cached data (a load reads the source), another root's folders keep
  theirs, and Don't cache / Don't auto-load flags stay.
- [ ] A location answered Later (one folder through two mounts): its folder and
  subfolders show the amber warning triangle beside their status icons, the
  row tooltip names the other location, the selected folder's summary says
  "RAM only · this .helab-root is also at another location" with Review…,
  and Settings → Data roots' Review… opens the window (usable while Settings
  stays open); after Same folder they all go.
- [ ] The TDC converter and the lab MATLAB scripts ignore `.helab-root`.
- [ ] Before using this build: `store-v3` starts empty. On each lab PC, move the old
  `store-v2` folder to the Trash when upgrading (Tony, 2026-10-28: Q1.5).

- [ ] In the full app on `/Volumes/dld_output`, exercise cache-first display,
  two-step browse and names-only Refresh. Confirm reselecting a RAM-held folder
  shows data immediately; decide whether the older "keep the previous signature"
  concern is resolved.
- [ ] Restart the app and confirm disk-cache reuse, unchecked cached display,
  subsequent verification and data/count agreement.
- [ ] Observe new shots during writing: unsettled files are excluded, counted
  honestly and included on a later explicit check/load after settling. Live
  (L1/L2): see below.
- [ ] Live on `/Volumes/dld_output` during an acquisition: turn Live on for the run
  folder. New shots appear within a few seconds of their last write (5 s settling
  + a check later); a shot being written shows as "still being written"; the
  tree's counts follow; nothing else in that tab can be selected; switching tabs
  turns Live off.
- [ ] Note the line 3 tooltip's "The last check took … ms" for one stat and for a
  listing of a large folder over SMB; a new shot is found within a minute even if
  the SMB client reports the folder's mtime late.
- [ ] After 10 new shots, line 3 says "saving 10 shots", then the cache line
  updates; at 80 % of the disk budget the Save update question appears and
  auto-saves wait for it.
- [ ] Unmount the share during Live: amber "Live stopped: Folder not found — is its
  drive connected?", data kept; Retry after remounting resumes; Live off saves.
- [ ] Quit (File › Quit and Cmd+Q) during Live and during a large folder's
  background save: the window names the folders and closes by itself; Quit now
  quits at once; next launch the saved shots come from the cache.
- [ ] Lab PCs (Windows): the same Live checks; a check's cost on the lab share.
- [ ] Plots following Live (L3), Mac then a lab PC, from
  `.ai/sessions/2026-10-19-claude-live-l3/handoff.md` (Tony's on-screen checklist):
  1. During a run, open Counts per shot, histograms, Transfer fractions and the 3D
     scatter, then Live on: new shots appear within seconds (scatter at most every
     5 s); `rev N · following Live`, `updating to rev N · K new shots waiting`.
  2. Policy: Rerun every 5 new shots; Wait after a run = 10 s.
  3. Untick Follow Live: `pinned (Follow Live off) · K newer shots`; tick again: it
     catches up.
  4. An empty run folder: Live on says `waiting for the first shot`, plots say "No
     shots yet", then follow from the first shot.
  5. Transfer fractions: auto orders re-found as shots come; manual keeps them.
  6. Live off (or tab switch) with shots held back: one catch-up rerun, then stays.
  7. Scatter camera stays across reruns, in the dock and Open in browser; a closed
     plot's browser tab says so; on a lab PC the 1 s polls cost nothing noticeable.
  8. Highlight the newest shot (scatter, histograms): red, moves with each new shot;
     histograms read its real counts on the red right axis, also with Log Y.
  9. Live on a folder with subfolders: only its own new TXY files are added.
- [ ] Trace the real share: Help › Record I/O trace (this session), use HeLab as when
  the SMB traffic was seen (tree open, browse, load, Live during acquisition), quit,
  then summarise the recording with
  `.ai/sessions/2026-10-19-claude-smb-io-audit/trace_summary.py <recording folder>
  --under /Volumes/dld_output --minutes`; expect no roots_verify bursts, ~0 ops/min
  idle. On a lab PC too.
- [ ] Plot settings (Plots v1 polish): change Shots, View range and Points in a
  plot's settings and press Rerun with these settings; the plot and its
  two-line source follow. Manual bounds' spin boxes step sensibly when scrolled.
  The centre hint disappears when the first plot opens and returns when all
  close. Scatter point size and opacity in the dock and via Open in browser.
- [ ] Opening the first 3D scatter no longer closes and reopens the main window on
  the Mac (hidden QQuickWidget, `HelabMainWindow._start_with_rhi_surface`). On the
  lab PCs (Windows), check whether it happens there and whether the same fix is
  safe on GPUs that can't paint QtWebEngine before enabling it (M1.8; the question is
  [Q1.7](DECISIONS_TODO.md#q17-windows-3d-scatter-window-flicker)).
- [ ] Transfer fractions on real data: order 0 and the spacing match the T
  histogram's peaks (the windows shaded below); manual mode starts from them and
  edits apply on Rerun; the XY box keeps the hot spot out; compare with
  `monitor_momentum.m` on the same shots. Steps in
  `.ai/sessions/2026-10-19-claude-transfer-fractions-hardening/handoff.md` (unsure
  note, Search T ends, clipped windows, typed centre kept during a Live rerun).
- [ ] Settings panel on screen (Mac, then a lab PC), from
  `.ai/sessions/2026-10-19-claude-settings-panel-hardening/handoff.md`:
  1. Three plots, tabbed: clicking a tab, inside a plot (counts, a histogram, the
     3D scatter's web view), its title strip, and Tab-ing in each show its settings.
  2. A click in the 3D scatter's web view switches to it (lab PC too, black pane).
  3. A floating plot: clicking its window, Cmd-` / Alt-Tab to it and back: the
     settings follow.
  4. Side by side: click A, B's tab, A again: A's settings. Untick the shown plot
     in the plot area's menu: a visible plot's settings; float the shown plot:
     its settings stay.
  5. The chooser raises its plot; unapplied edits survive; ✕ and a tab's × close
     the right plot; closing the shown plot shows the one before.
  6. All others floating: a new plot docks alone, the next tabs with it; two
     plots opened quickly are tabbed.
  7. Drag a tab out and dock it onto another plot: the group has × buttons.
  8. Typing: "5" in an ms box, "5 m", "5 k", "-5", empty, "abc", beyond the
     limits (red while typing, nearest limit on Enter); on a lab PC, the decimal
     mark shown and typed.
- [ ] Floating plot settings (Mac, then a lab PC), from
  `.ai/sessions/2026-10-19-claude-floating-plot-settings/handoff.md` (11 steps): the
  strip is readable and clickable; opening widens the window, the plot keeps its size,
  edits survive close/open; splitter width and open state kept across dock/float; stays
  on screen at the right edge; docking returns the page with edits; float/dock/close
  while following Live; tab groups and × buttons; several floating plots with the chooser
  and Show plot window (opens a closed section); dragging out and back moves nothing,
  letting go moves the page once (Windows: drag by the title bar too); minimising the
  shown plot falls back; Windows title bars, scaling, Tab + Space on the strip.
- [ ] Plot RAM budget (Mac, then a lab PC), from
  `.ai/sessions/2026-10-20-claude-plot-ram-budget/handoff.md` (8 steps; set the RAM
  budget low): status bar from 50 %; the 75 % window once per crossing; past 80 %
  plots behind other tabs released as pictures with Reload (shown, running, Live
  plots stay); a released 3D scatter's picture (and one never on screen: blank?);
  reload on show (and the setting off); no reload when neither RAM nor the cache has
  the data, no source access (I/O trace); changed or missing shots named; Activity
  Monitor shows RAM going down.
- [ ] Plots on screen: the 3D scatter in the dock (QtWebEngine) and via Open in
  browser, on the Mac and a lab PC (black pane: the browser path must work);
  counts and histograms; closing and tabbing docks; the Dash page says "Plot not
  found" after closing.
- [ ] Plots on real lab folders: are the crop bounds and histogram ranges sensible
  (99 % of all events vs the cloud)? Time for a large folder (~2.75 s per 5 M
  events for the crop); navigation stays responsive meanwhile.
- [ ] On a disposable fixture, interrupt an original TXY write, then complete or
  repair it. Verify an explicit check/load detects the recovery and replaces any
  partial result. Record the actual required action; toolbar Refresh only
  relists names. Do not modify real experiment files for this check.
- [ ] Switch and close tabs during shared listings/checks/loads; remaining tabs
  retain their subscriptions, data and truthful progress.
- [ ] Cancel and retry during active I/O; verify responsiveness, retained usable
  data and no replacement attempt starting alongside a still-stopping helper.
- [ ] Disconnect/unmount the source volume during I/O using a disposable source
  where practical; verify responsive navigation, cancellation, usable cached
  data and clear failure/retry state. Reconnect and retry.

- [ ] Load a large folder on `/Volumes/dld_output` and judge the Folder details
  time-left estimate (settles within a few seconds, stays steady, excludes
  paused time) and the short status bar. Added 2026-10-09.

- [ ] Restart the native GUI with `/Volumes/dld_output` mounted: after one
  completed check has saved share-keyed records, saved status icons and
  blocked-scan badges should remain across a remount, changed folder mtimes
  should show an amber clock, and automatic visible scanning should not recheck
  those saved statuses ([investigation](sessions/2026-10-15-codex-status-remount/notes.md)).
- [ ] Remount two disposable SMB shares in opposite orders on a test volume and
  restart the native GUI: each share should retain only its own status, scan
  history, preferences and datasets. After the cache clear, each share's first
  visit should build its own saved records.
  Also remount while HeLab stays open: when the saved records can be read,
  toolbar Refresh should replace the shown branches' saved badges and mark RAM
  data unchecked; restart still refreshes paths outside those branches and
  other tabs' loaded data.
- [ ] On a Windows lab PC, verify a mixed-case mapped folder and its UNC spelling
  resolve to the same cache record and that Clear, Make room and pending-save
  dialogs return the folder's original path spelling. With a disconnected mapped
  drive, time mount lookup and print `_windows_mounts()` with the drive both
  connected and disconnected (Explorer red X). Confirm WNetGetConnectionW gives
  the share name or fails safely, browsing does not block or record a scan
  failure, and repeated cache warnings do not flood the tab line or tooltip.
  On a disposable NFS/AFP/WebDAV mount, confirm one short Disk cache off line
  with the mount type and full tooltip detail, while browsing still works.

## Presets and reopened plots (added 2026-10-23)

From `.ai/sessions/2026-10-22-claude-presets-reopen/handoff.md` ("What Tony should check on
screen"):

- [ ] A plot's Presets row fits the narrow Settings panel; Save / Apply / Delete; a second plot of
  the same script lists the preset at once. After Apply, change a setting: its dot and
  "Save N changes ▾" (Save to preset / Save as new).
- [ ] Presets menu: save with plots in two tab groups and one floating; Apply after closing some
  (Replace, then Add): the floating window's place and size, docked splits and the front tab.
- [ ] Quit with plots open, restart: plots back in place, waiting until the folder is selected
  (or running at once when its data is cached); the startup tab's own selection unchanged. With a
  script not loaded: the Keep for later / Drop question.
- [ ] A Live preset on a folder with data: Live starts only after the data shows; on a large
  folder the large-folder question comes first. A preset of an unmounted folder: one notice,
  plots waiting; mount and select it: they run.
- [ ] Reset all settings' wording (presets kept); Settings → Cache › Presets…: the listing and
  each verdict, Rename, Duplicate, Delete.
- [ ] With Live on a folder whose cached data turns out not to match it: stop Live → Review… /
  Load as it is now → start Live again: the mismatch clears with the new data and Live runs on
  it, never the old shots.

## Work Offline (cache-only browsing, added 2026-10-26)

From `.ai/sessions/2026-10-26-claude-cache-only/handoff.md` ("On-screen checks"), on the Mac and
on a lab PC:

- [ ] Online, browse a data root two levels down and load a folder. File › Work Offline: the check
  mark and the status-bar "Offline · cached data only"; Refresh and Check folder status greyed
  with the reason; Live greyed ("Live is off while working offline").
- [ ] The tree: counts and status icons; a folder never expanded online has no arrow ("Not listed
  while online"); tooltips end "Offline: showing saved results from …"; icons stay generic.
- [ ] Select the loaded folder: data at once, "not checked (offline)", third line "Offline · cached
  data only · listed …". A folder never loaded: "Data not kept (offline)…" and "No cached data
  (offline)"; nothing spins.
- [ ] A plot on the loaded folder runs; a saved Correlations or Release time result shows from the
  disk cache.
- [ ] Right-click: Retry / Refresh, Check folder status, Open in File Manager, Place .helab-root
  here… greyed with the reason; Folder constants… and Clear loaded data cache work. Settings →
  Data roots: Show in Finder and Delete .helab-root… greyed, Clear cached data… works; Settings →
  Cache: the Folder listings row counts folders, Clear… asks first.
- [ ] Quit and start: HeLab starts offline at the last data root.
- [ ] **Real volume:** unmount the lab share, restart offline and repeat the tree, selection and
  plot checks; the paths are the share's usual `/Volumes/…` (Windows: the mapped drive) paths.
- [ ] Status-bar button › Yes (Work Online): every tab relists, the selection is checked
  ("Checking for changes…"), the controls come back, the setting is off at the next start.
- [ ] The log: one INFO "Work Offline on: cached data only", then one "Working offline: no …" line
  per refused operation kind.

## Saved analysis results (result cache R2, added 2026-10-23)

From `.ai/sessions/2026-10-22-claude-result-cache-r2/handoff.md` ("What Tony should check on
screen"), on the Mac and on a lab PC:

- [ ] A Correlations plot (radial) on a folder below a `.helab-root`: after it draws, its record
  (source line tooltip) ends "saved in the disk cache". Quit, start, load the folder, open
  Correlations again: it draws at once, "from disk cache, computed …".
- [ ] Change a setting and Rerun: computes; change it back and Rerun: shown at once.
- [ ] Edit the script file (a comment) or bump its version, reopen the plot: the old result shows
  with the amber "outdated (script file changed): rerunning" line until the run ends.
- [ ] Settings → Cache: the Cached analysis row (count, size); Clear… asks first; Clear all says
  cached analysis stays. Settings → Data roots: Clear cached analysis… (button and right-click)
  asks first and leaves the Cached column's data; Clear cached data… leaves the saved results.
- [ ] Release time with the default 1,000-replicate bootstrap: the second open is instant.
- [ ] A folder without a `.helab-root`: plots work as before, nothing saved (RAM only).
- [ ] After a plot saves, its folder's row shows the grey REPORT badge after the data cache's; the
  row tooltip and Folder details' cache line say "Cached analysis: 1 result, <size>". Reuse saved
  analysis results off: the badge and lines go; on: back. Clear cached analysis…: they go.
- [ ] With a small budget, Make room for a result removes the least recently shown other results;
  a plot that recomputes one of those right after saves its newer copy (or asks its own Make
  room), never refused.
- [ ] While HeLab runs, move the cache folder's `store-v3` aside by hand. Open a Correlations
  plot: it computes, and nothing claims "saved in disk cache" until the new store has answered.
  Presets show "Reading saved presets…" or their names again, never an old store's.
- [ ] On a lab PC, the lookup's helper start (Windows, ~0.1–0.5 s) still beats the runs.

## DLD front panel port (added 2026-10-20)

Built and tested offscreen only, on `agent/dld-front-panel-port`
([plan](../roadmaps/dld-front-panel-port.md#built-2026-10-20)). Each session's
`handoff.md` in `.ai/sessions/2026-10-20-claude-dld-<id>/` has the step-by-step
on-screen list; the items below gather them. Record results in `.ai/sessions/`.

**On macOS (look and behaviour):**
- [ ] Settings → Lab parameters: units in ms/mm/nm, sources, amber "unconfirmed",
  CODATA read-only, Restore; change g, Save, reopen, restart: kept; Reset all
  settings clears it ([f0b](sessions/2026-10-20-claude-dld-f0b/handoff.md#on-screen-checklist-for-tony)).
- [ ] Right-click › Folder constants…: "this folder", "inherited from …", "derived,
  √(2h/g)", "from the data"; a subfolder inherits; values survive a restart; a folder
  without `.helab-root` says "RAM only · kept for this session only"; Save waits
  while a row set here has no value; a hand-set fall time far from √(2h/g) gets the
  amber note ([f0b](sessions/2026-10-20-claude-dld-f0b/handoff.md#on-screen-checklist-for-tony),
  [d8-release](sessions/2026-10-20-claude-dld-d8-release/handoff.md#on-screen-checklist-for-tony)).
- [ ] A plot with constants: change a lab value → amber "constants changed … Rerun
  to use them" only on plots that use it (a Gaussian-only histogram ignores the QE;
  a bimodal one doesn't); Rerun or the next Live shot clears it
  ([decisions](sessions/2026-10-20-claude-dld-decisions/handoff.md#on-screen-checklist),
  [d4-wiring](sessions/2026-10-20-claude-dld-d4-wiring/handoff.md)).
- [ ] ms/mm everywhere: T axes like `20,450` (no `2.045e+04`), fit titles
  `(20,916.12 ± 0.12) ms`, the 3D scatter's axes and hover; typing `20,450.5`,
  `20450.5` and `20.45 s` in a T box; `20,5` refused, also on a German-locale PC
  ([decisions](sessions/2026-10-20-claude-dld-decisions/handoff.md#on-screen-checklist)).
- [ ] Every new plot in a 560 px dock: titles wrap, nothing clipped, warnings amber;
  zoom kept through Live reruns (histograms, density images, mean position,
  T spectrum, shot times, trends, velocity distributions)
  ([polish](sessions/2026-10-20-claude-dld-polish/handoff.md)).
- [ ] Density images: projections, blur, rate per shot, sqrt/log/power reaching the
  faintest bins with the bar in real values, a manual T window, the newest shot's
  contour ([d3](sessions/2026-10-20-claude-dld-d3/handoff.md#on-screen-for-tony-macos)).
- [ ] Masks: the Mask group on each event plot, the 2020 preset drawn dashed on XY,
  custom circles counting only when the edit ends, a bad circle failing the run with
  the last plot kept; Find hot spots → Copy circles → paste into another plot
  ([d9-d15](sessions/2026-10-20-claude-dld-d9-d15/handoff.md#on-screen-checklist-native-ui)).
- [ ] Shot trends: panels zoom together, shot-time axis, amber low shots; Notify
  during Live gives one system notification for a low shot (block the beam), none
  more within a minute, none outside Live; the tray/menu-bar icon is
  [Q1.8](DECISIONS_TODO.md#q18-the-tray--menu-bar-icon-for-notifications) ([d2](sessions/2026-10-20-claude-dld-d2/handoff.md#on-screen-checklist-tony)).
- [ ] The ħ glyph ("ħk/m", "2ħk/m") in the native fonts on macOS and Windows: the
  offscreen renders drew "h" ([d8-velocity](sessions/2026-10-20-claude-dld-d8-velocity/notes.md#review-round-coordinator-on-04d69bf)).

**On a lab PC:**
- [ ] Every new plot paints on the Lab Side PC (PyQtGraph, no QtWebEngine): T, X, Y
  histograms with fits and BEC properties, Density images, Mean X, Y, T spectrum,
  Shot times, Shot trends, Release time, Velocity distributions, Correlations.
- [ ] Live with heavy plots open (bimodal fits, Release time, Velocity distributions)
  keeps up on a real run: reruns 2–5 s apart, the GUI responsive.

**On the lab share (SMB timing, D7):**
- [ ] Help › Record I/O trace on an uncached load: one `load: shot time` per raw file
  of a shot read; none on a reload from the cache or an unchanged Live check; one
  `live: shot time` per new shot; `syscall: false` on Windows. Time the first load of
  a ~10k-shot uncached folder with and without D7 (one extra stat per shot)
  ([d7](sessions/2026-10-20-claude-dld-d7/handoff.md#for-tony-real-volume-smb-checks)).
- [ ] Shot times match the `d<N>.txt` mtimes in Finder/Explorer, not the TXY
  conversion times; a folder without raw files shows amber triangles and the count;
  a folder cached before D7 is amber until Refresh ([d7](sessions/2026-10-20-claude-dld-d7/handoff.md#for-tony-on-screen-checks)).

**On real data (physics):**
- [ ] Temperatures on a real thermal cloud and a BEC: Gaussian vs arrival-time on T
  (agree cold, arrival a little higher hot); smoothed-curve fits close to the
  unsmoothed ([d1](sessions/2026-10-20-claude-dld-d1/handoff.md#on-screen-checklist-for-tony)).
- [ ] Bimodal TF² + Bose on a condensate: `N0/N`; on a thermal folder "no
  condensate (z = …)"; a borderline one "possible condensate, not reported"; BEC
  properties' numbers sensible, and do "QE from R" and "QE from thermal" agree with
  the lab's QE ([d4-wiring](sessions/2026-10-20-claude-dld-d4-wiring/handoff.md)).
- [ ] Density images' XY orientation against the old front panel's 2D Plot
  (`legacy/DLD_front_panel`) ([d3](sessions/2026-10-20-claude-dld-d3/handoff.md#on-screen-for-tony-macos)).
- [ ] Mean X, Y and T spectrum: do the listed peaks match the pulse rate and the
  50 Hz harmonics; is the noise floor's rise towards Nyquist acceptable; a large
  folder's 16,384-bin profile ([d5-d6](sessions/2026-10-20-claude-dld-d5-d6/handoff.md#on-screen-checks-for-tony)).
- [ ] Release time on a BEC folder: value, origin and notes; Use for this folder…
  then Folder constants… shows t_a and the origin; Velocity distributions has the
  cloud at rest at v = 0 and σ_v giving the expected T. Measure the fall distance
  from a cloud released at rest ([d8-release](sessions/2026-10-20-claude-dld-d8-release/handoff.md#on-screen-checklist-for-tony),
  [d8-velocity](sessions/2026-10-20-claude-dld-d8-velocity/notes.md)).
- [ ] Calibrate the detector QE (0.1 proposed) and confirm the trap frequencies and
  the trap's axial axis (BEC properties' QE checks).
- [ ] Hot spots on the current detector: Find hot spots on a flat field or an
  atom-free T window, and a real run without hot spots (none offered); the circles
  become the "current detector" preset ([d9-d15](sessions/2026-10-20-claude-dld-d9-d15/handoff.md#on-screen-checklist-native-ui)).
- [ ] g² on real data (Correlations): a thermal cloud just above T_c (radial g²(0)
  near 2, less with detector resolution and the window; σ against ħ/(m·σ_x)); a BEC
  (≈ 1); a halo back-to-back along each axis with re-centring (the peak at 0 and its
  width; set the folder's origin from a BEC run, since a halo's is "unsure"); speed on
  a few hundred shots (try neighbouring shots if all-pairs is slow); are the per-mode
  defaults right ([d12-plot](../.ai/sessions/2026-10-20-claude-dld-d12-plot/handoff.md#real-data-checks-proposed)).
- [ ] Correlations on screen: the title lines, points with bars, red fit and dashed
  baseline, pairs panel, in a 560 px dock; ħk units; Live reruns ≥ 5 s with
  "N shots held, 1 counted" and jackknife bars, one bootstrap rerun when Live stops;
  a 1 s time budget stopping and Rerun continuing
  ([d12-plot](../.ai/sessions/2026-10-20-claude-dld-d12-plot/handoff.md#on-screen-checklist-for-tony)).

## v0.0.5a: cache rebuild (native checks, added 2026-10-11)

Built in S6–S10 of the [cache plan](../roadmaps/cache-storage-and-settings.md#sessions) and
tested offscreen only. Check on native macOS (and once on a Windows lab PC):

- [ ] Settings → Cache: the inventory appears, Clear by kind and Clear all ask first and the
  tab refreshes; both purges show estimates; lowering the disk budget below use asks and
  trims; the RAM budget spin box shows "16.0 GB (1/8 of 128 GB)"-style values.
- [ ] The disk cache dialogs with a small disk budget: the 80% warning (Open purge settings
  opens the Cache tab at Remove old entries; Ignore this time), Make room / Don't cache this
  folder now, Save update / Don't cache this update now; one at a time, never behind Settings.
- [ ] Large-folder warning on `/Volumes/dld_output` with a low RAM budget: the amber summary
  line, Load anyway… dialog (tick box enables Load anyway), No auto-load, Folder details and
  the status bar; a folder over 30% of RAM is refused.
- [ ] Cache move: Change… to a folder on the same disk (instant), then to another disk
  (progress, Cancel during the copy keeps the source), a refused target (network, synced or
  non-empty) with Show in Finder; quit during a copy and confirm the next start finishes or
  undoes it. Start a second HeLab during a move: it waits.
- [ ] Folder flags: right-click toggles, row badges and tooltips, "Auto-load off for this
  folder · Load", the Remove its cached data question, and the Folder preferences row.

## v0.0.5a: native UI and packaged application

- [ ] On native macOS (and a Windows lab PC), start a large manual recursive basic
  scan, resize once and repeatedly, and confirm painting, progress and Cancel work
  before scans finish ([resize fix](sessions/2026-10-11-codex-resize-during-scan/notes.md#implementation)). Added 2026-10-11.
- [ ] Build the PyInstaller app and confirm the right-pointing SVG triangle
  renders (including Qt's SVG icon plugin), helper operations run and native
  folder/volume icons appear.
- [ ] On native macOS, check triangle hover, click, keyboard opening, Escape,
  delayed dismissal, pointer reentry and the accepted hover-then-click
  close/reopen flicker. Check the independent main-icon check/cancel target.
- [ ] Run the folder-browser smoke checks on a Windows lab PC, including native
  popup behavior, cached data, source loading and packaged helper execution.

## v0.0.5a: release evidence

- [ ] Versioning (added 2026-10-12): on native macOS and Windows, launch the packaged
  app from outside the checkout; Help → About must match its version, commit and
  UTC build stamp. On the first release PR, verify PRs only check/build, the new
  main version gets an explicit tag on the squash commit plus a draft, alpha/final
  pre-release flags agree, publishing is manual, and tag pushes do not release twice
  ([implementation](sessions/2026-10-12-codex-app-versioning/notes.md)).
- [ ] Release recovery (added 2026-10-12): in a disposable test release, fail after
  tag creation and after a partial upload; rerun all jobs, then try a later same-version
  main push. Confirm tagged-SHA rebuild/tests, preservation of completed uploads,
  correct asset stamps/digests and refusal to change a moved tag/published release.
  Check PR stamps show the source branch and merge ref plus the actual merge SHA.

- [ ] Release repos (added 2026-10-13; the
  [proposal](../roadmaps/app-updates.md#release-repos-proposed-2026-10-13-tony-to-confirm) was
  confirmed 2026-10-28, Q1.4): stop pushing dev branches to `HeBECANU`. For the first lab-ready
  version, fast-forward `HeBECANU` `main` to the released `TonyXTYan` commit
  (`git push HeBECANU <sha>:main`; no squash or rebase there), check the draft
  appears there with the same tag commit and assets, then publish it.
- [ ] Self-update prerequisites (added 2026-10-13), before the first updater ships:
  ask ANU IT whether managed lab PCs allow self-replacing/unsigned programs;
  test reaching `api.github.com` from each lab PC; decide where the signing key
  is backed up and who can release after Tony leaves
  ([risks](../roadmaps/app-updates.md#risks)).
- [ ] Cached-data check (added 2026-10-13): on `/Volumes/dld_output`, time selecting a
  cached folder at each Settings → General → Check of cached data level; move an older
  folder into a cached folder's path and confirm the mismatched-folders window (rows, button
  tooltips, status-bar "⚠ N mismatched") for the shown folder, a background load and a
  folder status check; with two or more moved folders confirm loads and scans pause with the
  banner, then Resume / Cancel all, and from 8 Skip; return to a folder after adding a TXY
  and confirm the new shot loads. Added 2026-10-14: hold ↓ across cached folders with
  auto-load on (Finish mode) and confirm nothing loads until you stop, then the last
  folder loads within 1 s; a single click on an idle app loads at once; Review… on a
  mismatched folder opens the list on it.
- [ ] macOS release zip (added 2026-10-13): download the macOS CI artifact, check
  `HeLab-macos.zip` is ~300 MB and holds only `HeLab.app`, unzip it in Finder and
  open the app (right-click › Open for the ad-hoc signature)
  ([build size step 1](../roadmaps/build-size.md#steps-cheapest-first)).
- [ ] Observe hover-menu tests in CI: real timers have approximately 200 ms of
  slack and may flake on slow machines. If a failure is reproducible, add a
  concrete test-reliability item to `roadmaps/known-issues.md` with logs (A1.6).

## Plane projections (added 2026-11-10, block 71)

- [ ] **M71.1 Plane projections on a real halo** (`roadmaps/plane-projections.md`): open a halo folder whose
  arrival is saved (Release time plot › Use for this folder…), then Basic Plots › v2 › Plane projections. The 3D
  view turns with the mouse and shows the XY, XT and YT planes through the halo, and the three histograms below
  match the XY, XT, YT histograms plot's shapes (in mm/s). Turn on Plane 4 and set a thickness of a few mm/s: its
  histogram is the halo's ring, and changing α, θ and ψ moves the plane in 3D. Switch to Matplotlib (Drawing ›
  Library): the same, unturned. With Live on, a new shot keeps the 3D camera where you left it.
