# Provisional UI pass on dev/v0.0.7 (f986257), 2026-10-30

Runner: Claude Sonnet 5.5 via computer use, on Tony's Mac. A short pass (about 20 min) to catch early
bugs while other work is in progress; not the M1 smoke pass. Build: `dist/HeLab.app` rebuilt from the
branch (About: HeLab 0.0.6a1, dev/v0.0.7, source state clean). Data: `/Volumes/dld_output`, folder
`20260625_Ramsey_weak_trap` (519 shots). The runner floors (Debug menu items, `--geometry`,
`dev/dev_app.py`) are not on this branch, so the older route was used.

## Worked (no bug seen)
- Start-up on the share root; About; File menu; Settings (General, Cache tabs open and Cancel closes).
- Open a folder by typing its path: cached load in about 3 s, "Cached data loaded", Folder details ⚓.
- Counts per shot, T, X, Y histograms, 3D scatter draw. Bins 50 + Log Y then "Rerun with these
  settings" redraws ("50 bins (set) · log Y").
- Work Offline on and off ("Offline · cached data only"); going online re-checks the folder.
- File › Quit ends the process within seconds; on relaunch the three plots come back
  ("Showing previously loaded data").
- Both logs (`helab-54699.log`, `helab-88259.log`) have no error, exception or traceback lines.

## Observations (for Tony to judge; none looks like a crash or data bug)
1. **Return does not commit a typed parameter value**; Tab does. The v0.0.7 hand-over runbook says
   Return should now commit and close the editor, so that change has probably not landed yet.
2. **Tabbing out of a value opens the next row's editor** (Bins → Log Y showed an empty wide editor
   box until the next click). Same cause as 1.
3. **Folder details contradicts itself while offline:** State "Loaded from cache · not checked yet"
   beside "Loaded 13:18:15 · 2m ago · checked, unchanged" (summary line says "not checked (offline)").
4. **Plot pane is very narrow by default** (about 240 px next to a 700 px settings panel) once a plot
   is open; tab titles clip ("Counts p…") and the 3D scatter's header line is cut off. A drag on the
   plot/settings splitter did nothing in this session (possibly the automation, not HeLab).
5. **Debug menu still has placeholder items** ("Debug - 6", "Draw a line in debug console",
   "Debug - validate tab status") and none of the runner items from the hand-over runbook.
6. Settings › General shows the label "DIR_TEMPS:" (the constant's name) where the Cache folder row
   below it reads as prose.
7. Settings › Cache: "Cached analysis 2 results" after the 2026-10-28 dry run cleared 3 for DATA_ROOT;
   plausible (new results since), not checked.

## Tool notes (not HeLab bugs)
- A first Return in the path bar after setting its text through accessibility did nothing; a
  keystroke-driven edit then Return worked. Typing into the settings table needs full-screen control.

## Not covered
Presets and arrangements, floating plots, Live, Place .helab-root, RAM-only folders, the other
tabs of Settings, heavy folders, M1.9 and M1.10.

## Second round (presets, floating plots, quit/restore)
Worked: Save… preset dialog opens; OK with an empty name closes it and saves nothing (no message).
Presets menu lists the 2026-10-28 `smoke-arrangement` from the dry run. Floating a plot works; quitting
with two floating plots exits cleanly and both come back floating after the restart. Log clean.

8. **Floating windows open exactly over the main plot area and on top of each other:** the first
   floated at 264x859 (the docked pane's size) at the same x/y as the docked pane; a second plot
   floated at the identical place, so one hides the other. After a restart they come back there too.
9. **No obvious way back to docked:** with background clicks, the main window's Float button toggled
   the selected plot's float state (it floated a second plot by accident), double-clicking the
   floating title did nothing, and the floating window's vertical title strip only collapses its
   settings. A person should check double-click on the dock title (dry run: it floated).
10. **Settings panel after floating:** "Settings are in this plot's window" with a "Show plot window"
    button; fine, but the Float button in the panel's title then floats whichever plot the panel
    names, not the one just floated.

Not covered: Live, Place .helab-root, arrangement Replace/Add, heavy folders. Full-screen control was
asked for a second time and timed out, so the floating-window drag/dock checks need a person.
