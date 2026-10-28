# Smoke pass on Tony's Mac (dev build 41a6a7d), 2026-10-28

Runner: Claude Sonnet 5.5 via computer-use `app_*` tools (dry run, A5.1). Supervisor: Tony.
Config: DATA_ROOT=/Volumes/dld_output; CACHED=20260625_Ramsey_weak_trap; OTHER=20260620_Rabi_trial_weak_intrap; PHYSICS=20260727-RingBEC; RAM_ONLY=none; ACQUIRING=no; RECORD_TRACE=no.
Build: dist/HeLab.app from `pyinstaller HeLab.spec --clean -y` (source-run `helab` has no bundle ID and can't be driven).

Screenshots are not saved to `shots/`: the `app_*` tools can't write files and `screencapture -l` fails from the shell. Seen text is quoted instead.

| Check | Verdict | Seen / note |
|---|---|---|
| M1.1-1 | PASS | Window "HeLab — dld_output" with folder tree. App restored last session (share root, 3D scatter + T,X,Y histograms open), not a blank start. |
| M1.1-2 | SKIP | RECORD_TRACE=no |
| M1.1-3 | PASS | About is under the HeLab menu on macOS, not Help. Shows HeLab 0.0.5a1, commit 41a6a7de…, branch dev/v0.0.6, source state clean. |
| M1.1-4 | PASS | Settings › Cache: "558 MB of 8.6 GB budget", rows for cached data, summaries, analysis etc. Closed with Cancel. |
| M1.2-1 | PASS | Typed the folder path directly (leaf folder, nothing to expand). First load: no cached data, 519 TXY, 1:21 from the share; then "519 TXY found · 519 loaded", "Cache created 26s ago", Folder details ⚓ dld_output · /Volumes/dld_output/.helab-root. |
| M1.2-2 | PASS | Switched to OTHER (listing started), back to CACHED: "Loaded", 1,585,096 rows in RAM at once, no progress bar. |
| M1.2-3 | PASS | After File › Quit and relaunch: "Cached data found · Cached 1m ago" with "Preparing…", then "519 TXY found · 519 loaded", source "disk cache", "checked, unchanged", in about 1 s. App reopened on the share root, not on the last folder. |
| M1.2-4 | SKIP | RAM_ONLY_FOLDER=none |
| M1.3 | SKIP | no run acquiring |
| M1.4-1 | PASS | Two T, X, Y histograms (plots 18, 19) on CACHED_FOLDER; Bins 0→50 in plot 18, preset `smoke` saved with the settings row's "Save…" button. Plot 19's Preset row then showed `smoke`. |
| M1.4-2 | PASS | In plot 19: Apply → "Preset "smoke" applied"; ticking Log Y gave a blue dot beside it and a "Save 1 change ▾" button. |
| M1.4-3 | PASS / REVIEW | Presets › Save Folder and Plots as Preset… → `smoke-arrangement` ("2 plots"). Closed plot 19, then Presets › smoke-arrangement opened a Replace / Cancel / Add dialog ("Replace the 3 open plots"); Replace restored two histograms (bins 50, log Y). Placement for Tony to judge. |
| M1.4-4 | PASS | After File › Quit and relaunch both plots returned: "Showing previously loaded data: 20260625_Ramsey_weak_trap". |
| M1.5-1 | PASS | Release time on CACHED_FOLDER drew in about 35 s. Tooltip ends: "Job a3 · completed 13:49:39 in 34.9 s · saved in the disk cache". |
| M1.5-2 | PASS | After quit and relaunch, Plot › Release time drew within seconds; tooltip: "From disk cache, computed 2026-10-28 13:49 in 34.9 s (job a4) · in the disk cache". |
| M1.5-3 | PASS | Settings › Data roots (rows dld_output 572 MB, tonyyan 118 kB): selected dld_output, Clear cached analysis… gave a confirmation ("Clears 3 saved results (107 kB) for data root "dld_output"… cached data, .helab-root and folder flags stay"); Clear; row still 572 MB. Tony approved this step first, since it also removed his earlier results. |
| M1.6-1 | PASS | File › Work Offline: status bar "Offline · cached data only", summary "Offline · cached data only", Live icon greyed. |
| M1.6-2 | PASS | "519 TXY found · 519 loaded (cached)… not checked (offline)"; Counts per shot drew. |
| M1.6-3 | PASS | Share root offline, expanded 20250306_20250312_BEC_ETP_check: row tooltip "Subfolders: not listed while online… Offline: not listed while online". No spinner. |
| M1.6-4 | PASS | Status-bar "Offline" note › "Work online again?" › Yes: Offline gone; summary showed "checked, unchanged" 1 s later (the "Checking for changes…" text was too brief to catch). |
| M1.7 load | PASS | Second attempt: 20260727-RingBEC "1,007 TXY found · 1,007 loaded", 22,494,594 rows, 539.9 MB in RAM (about 6 GB process RSS), took 7:07; "Problems: 1 shot unreadable or with invalid rows". |
| M1.7 T, X, Y histograms | REVIEW | Drew in under 20 s. Axes "T (ms)", "X (mm)", "Y (mm)". |
| M1.7 Mean X, Y against T | REVIEW | Drew in under 25 s; "T (ms)" axis, SD panel below. |
| M1.7 T spectrum | REVIEW | Drew in under 25 s; T profile plus spectrum (Hz), one peak marked. |
| M1.7 Density images | REVIEW | Drew in about 55 s; X (mm) / Y (mm) axes, colour bar. |
| M1.7 Shot times | REVIEW | Drew in under 25 s; amber "1,007 TXY times (no raw file)". |
| M1.7 Shot trends | REVIEW | Drew in under 25 s; amber note "173 low", "ranges found in the data are rounded out". |
| M1.7 Transfer fractions | REVIEW | Drew in under 25 s; amber notes: orders overlap, 2 shots ≤ 50 counts, 18 shots with no events. |
| M1.7 Release time | FAIL (slow) → REVIEW | Drew, but only after 932.8 s (15.5 min; limit 3 min). Tooltip: "Job a13 · completed 14:38:54 in 932.8 s · saved in the disk cache". t_r = 509.6 ± 1.6 ms; amber: arrival-time fit failed, reduced χ² 192. The 519-shot Ramsey folder took 34.9 s for the same plot. |
| M1.7 Velocity distributions | FAIL (slow) → REVIEW | Started while Release time was still running (job a14); drew after more than 4 minutes (finished before the 15.5 min Release time wait ended). Axes v_z/v_x/v_y in mm/s; amber: t_r detected within this run, arrival fit failed, 1,490,888 events before t_r. |
| M1.7 Correlations | REVIEW | Drew within 90 s; "stopped at the time budget: 28 of 1,007 shots used", "no peak: g² near 0 is 0.976 ± 0.025", plus the same arrival-fit warnings. |
| M1.8-1 | PASS | With 8 plots open, clicking the Release time, Velocity distributions and Correlations tabs each set the Settings panel title to that plot ("Release time (32) · 20260727-RingBEC · rev 1", etc.). |
| M1.8-2 | PASS / REVIEW | Double-clicking the Correlations title floated it; the main panel then said "Settings are in this plot's window · Show plot window". After dragging the window clear, the floating plot has its own settings strip on its right, and clicking inside the main Velocity plot moved the panel to "Velocity distributions (33)". The floating window first appeared exactly over the main plot area; placement for Tony to judge. |
| M1.8-3 | PASS | Release time › Search T from: `20,450.5` → "20,450.5 ms"; `20.45 s` → "20,450 ms"; `abc` stayed in the field with a red outline. Reset to default afterwards (nothing re-run). |
| M1.8-4 | SKIP | Windows only |
| M1.8-5 | PASS | File › Quit; process gone within seconds (exit watcher: 14:45:53). Earlier unexplained exit (pid 79750) did not recur. |

Runbook wording fixes so far: About HeLab is in the HeLab menu (macOS); START_COMMAND on macOS must be the built .app; the app reopens the last session.
- Path bar accepts a full path, so the tree needn't be expanded; the app's file listing of the share root starts only after select. The restart reopens the share root, so step 3 needs a re-select of CACHED_FOLDER (as the runbook says).
- Wording: "Presets row › Save as new preset…" is the "Save…" button; arrangement presets are Presets › <name> (not a submenu) with Replace/Cancel/Add dialog.
- Dropdowns/menu buttons (script Group) can't be clicked by the background tools; a full-screen click opened the popup but then every click/key failed ("Could not verify which document this window is editing") until Tony clicked the item himself. Menu-bar menus and plot tabs' close icons: the tab "x" did not respond to clicks, the dock title "x" did.
- Before closing plot 19 the panel showed 'Saved preset "smoke"' for plot 18, with Log Y unchecked there; the saved arrangement kept plot 19's unsaved Log Y. Possibly benign, Tony to judge.
- File menu: Open, Place .helab-root in "<folder>"…, Work Offline, Cancel Loading, Settings…, Quit (never click Place .helab-root).
- Quit: File › Quit sometimes leaves the process running if the click lands before the menu opens (two HeLab instances ran for a while). Check `pgrep` before relaunching. Cmd+Q needs the systemKeyCombos grant.
- Dropdown (Group) trick that works in full-screen mode: click an empty part of the script list, shift+Tab twice to focus the Group combo, press Down. No popup opens.
- M1.5-3 clears the user's own saved results on a machine where the runbook is run for the first time; the runbook should say so.

- M1.7 first attempt: HeLab (pid 79750) exited without a crash report between 14:04:22 and 14:06 while loading 20260727-RingBEC (1,007 files, started ~13:57). Cause unknown (Tony says he didn't quit it). Log: ~/Library/Caches/HeLab/logs/helab-79750.log (last line: Disk cache cleanup 14:04:22). Retrying.
- M1.7 on RingBEC (22.5 M rows) is slow and memory-heavy: Release time 15.5 min, process RSS up to about 7.3 GB with two analyses running at once (the second plot started while the first was still running). Worth a known-issues entry: either a progress indicator/ETA or a cap on the bootstrap for big folders. The runbook's 3 minute limit is too short for this folder; use a smaller PHYSICS_FOLDER (about 500 shots) or allow 20 min.
- Typing into parameter boxes: Return alone didn't commit a value (the editor stayed open); Tab committed it and moved to the next row, so a following double-click on the same row can hit a different row. Reset buttons are the yellow arrows at the right of each row.
- RingBEC is now in the disk cache (Cache created ~14:16), plus saved results from Release time, so a later run starts warm.

## Summary

PASS: M1.1, M1.2 (step 4 skipped), M1.4, M1.5, M1.6 (step 5 skipped), M1.8 (step 4 skipped). SKIP: M1.3 (no run acquiring). REVIEW for Tony: all 10 M1.7 plots listed in the runbook drew (axis labels ms/mm seen on T, X, Y, density, velocity), floating-window placement (M1.4-3, M1.8-2). FAIL (slow): M1.7 Release time (15.5 min) and Velocity distributions on the 22.5 M-row RingBEC folder. Unexplained: one HeLab exit during the first RingBEC load.
Screenshots were not saved to shots/; see [computer-use-notes.md](computer-use-notes.md).
