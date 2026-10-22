# Presets and reopened plots, stage 1: handoff (Loom)

Branch `agent/presets-reopen` from `c3d4b50`. Brief: [brief.md](brief.md); notes: [notes.md](notes.md).

## What was built

- **`helab/analysis/presets.py`** (Qt-free, listed in `tests/test_headless_imports.py`): the one
  record format and its validation.
  - `ScriptRef` (analysis id, action, version, file hash, name); `SavedPlot` (script, folder path
    and `root://` key, every parameter as stored, library, Live group, number, title, settings
    section open and width, floating, tab group, front tab, dock name, the script preset its
    values came from); `Arrangement` (plots, folder, root key, Live, the plot area's `saveState`,
    format version). Used for **arrangement presets** and for the **plots to reopen**.
  - `ScriptPreset` / `ScriptPresets` (one record per script and action; unreadable entries kept
    as they were on every rewrite).
  - `check_plot` / `check_values`: unknown key, wrong type, outside limits, a choice that's gone,
    a parameter the record lacks, a library that's gone, a script version that differs. Nothing is
    clamped or replaced: values that fit apply, the others are named (`PlotCheck.summary` one
    line, `details` the tooltip). `preset_note`: a referenced script preset changed or deleted.
- **`helab/views/plots/presets.py`**: storage (`script_presets/<id>/<action>`,
  `arrangement_presets/<name>`, percent-encoded); **`PresetBar`**, the Presets row at the top of
  each plot's settings page (Preset ▾, Apply, Save…, Delete…, and one note line only when there is
  something to say); **`ArrangementPresets`**, the main window's **Presets** menu; **`PresetFolder`**,
  which loads an applied preset's folder and starts its Live under the normal rules.
- **`helab/views/plots/arrangement.py`**: `capture` (open plots → arrangement), `open_arrangement`
  (in tab groups, floating, then `restoreState`), **`FolderWait`** (a reopened plot's data: RAM,
  else one local `cached` read, else `FolderCache.datasetChanged` from a tab's load) and
  **`PlotReopen`** (records on plot open/close and at quit, restores at start).
- Hooks: `AnalysisInstance` (`start(saved, wait)`, `apply_saved`, `saved_plot`, `waiting`,
  **`run_reopened`: the one place a reopened plot decides to run**, the R2 seam), `TreePanelWidget`
  (`find_script`, `reopen_plot`, `place_dock`, `instances`, `plotsChanged`), `HelabMainWindow`
  (Presets menu, `plot_reopen.restore` 30 ms after start, `plot_reopen.quit()` before the plots
  close), Settings → General checkbox, four rows in `settings_defaults.py` (kept together).

## Decisions taken (Tony to confirm where marked)

1. **Script presets hold the library, not the Live group.** The library is how the plot is drawn,
   part of "the plot I want"; when a plot reruns during Live is about watching a folder, not about
   the analysis. Arrangements and reopen hold both.
2. **Arrangements store each plot's values, plus the name and date of the script preset last
   applied to it, as provenance only.** Stored values make an arrangement self-contained and
   reproducible (a later edit of a script preset can't silently change what a saved arrangement
   opens). Applying says "preset “p” changed since: this arrangement's values are used" (or
   "deleted since") on that plot's note line. *Tony: confirm, or prefer "follow the named preset".*
3. **Applying an arrangement replaces the open plots, after asking** (Apply / Cancel, Cancel
   default). A preset is a whole one-folder arrangement; adding beside would mix folders against
   the one-folder rule and double-open plots. *Tony: confirm.*
4. **Saving** takes the current tab's folder (its data shown, else its selection), whether Live
   watches it, and the open plots **of that folder**; plots of other folders are left out and the
   name prompt says how many.
5. **Applying** opens the folder in the current tab as typing its path does (`open_to_path`: the
   folder becomes the tab's top folder), then loads it with `load_to_ram_cache(explicit=True)` (a
   deliberate selection: cache first, large-folder question, Don't auto-load ignored) **once it's
   known to hold data** (cached, in RAM, or listed with TXY files); a folder listed with none isn't
   loaded (that load fails "No converted TXY files"). Live starts only when `live_unavailable` is
   empty after the load ends (`start_live`), else one notice says why (the load error if there is
   one); it gives up if the tab selects another folder.
6. **A folder that can't be listed** is named once ("Preset “X”: run can't be opened now (…): its
   plots wait for its data"); **its plots still open** and wait, as a remounted drive then brings
   their data through the tab.
7. **Reopen**: plots keep their numbers ("Counts per shot (3)"), numbering continues after them.
   Plots that can't reopen (script not loaded, record unreadable) are named once in one notice and
   **dropped from the record** at the next recording. *Tony: or keep them for a later session
   (e.g. until their Load Scripts… folder is loaded)?*
8. **Reopened plots never read their folder**: RAM, else one automatic `cached` read (local lane,
   not priority, so the startup tab's own read goes first; `allow_large: False`, so a large folder
   says "too large to read back automatically: select it to load"), else wait for a tab's load.
   A folder recorded under one data root whose data now has another isn't used automatically
   ("is now another data root's folder: select it, then Rerun"); the plot's Rerun while waiting
   looks again deliberately and takes it.
9. **Recording**: on plot open, plot close and quit (not on every edit), so a crash loses edits
   since the last open/close. Recorded even with reopening off (cheap; turning it on later
   reopens the last session).
10. **Reset all settings** clears presets and the reopen list (as briefed) and its confirmation now
    says so. My view: presets are the user's work rather than preferences; *Tony may prefer
    Reset to keep them* (a one-line change: save and restore the two prefixes around `clear()`).
11. **Dock geometry**: `saveState`/`restoreState` on the plot area, docks named `helab-plot-<n>` by
    their place in the record. Tested offscreen: tab groups, which tab is in front, a separate dock
    area, floating flag, settings width. Floating window positions and sizes are left to Qt's
    restore: *check on screen* (below).

## Proposed wording (Tony to decide)

- Menu **Presets**: "Save Folder and Plots as Preset…", then each preset by name (tooltip "Open
  run with its 3 plots, and Live"), "Delete Preset ▸"; unreadable ones "⚠ name (can't be read)",
  disabled, reason in the tooltip; "No presets saved".
- Settings → General: **"Reopen plots at start"**, tooltip "When HeLab starts, the plots open when
  it last quit open again with their settings and places. Each runs again on its folder's data in
  RAM or the disk cache, never reading the folder itself: without cached data it waits until a
  tab loads the folder."
- Plot lines: "Waiting for run's data: select it to load"; "Reading run's data from the disk
  cache…"; title "Counts per shot (3) · run · waiting for its data".
- Notes: "Reopened · ⚠ 2 settings at the script's defaults: Bins, Mode · saved with v1, now v2";
  "Preset “fast” applied · ⚠ 1 setting left as they were: Bins".
- Notices: "Not reopened: Gone (its script isn't loaded (Load Scripts… its folder, then open it
  again))"; "Preset “X”: Live on for run" / "Live not started: …"; "Saved preset “X”: run, 3 plots, Live".

## Shared files: what changed outside new modules

- `instance.py` (Cellar's run path untouched): `start`, `_open_settings`, `close` (mine), plus a
  4-line hook at the top of `run()` (a waiting plot looks for its data instead), `_title` and the
  input line in `_show_follow` (say "waiting for its data" instead of "rev 0"). `run_reopened`
  calls `_submit` unchanged.
- `script_tree.py`: `_add_dock` takes an optional `tab_with` (default as before) and emits
  `plotsChanged`; `_forget_instance` emits it.
- `FolderExplorer`: **no change**; uses `open_to_path`, `load_to_ram_cache(dwell=False,
  explicit=True)`, `live_unavailable`, `start_live` and its signals.
- `settings_defaults.py`: rows `reopen_plots_at_start`, `open_plots`, prefixes `script_presets/`,
  `arrangement_presets/` (together, after `log_files_keep` / `lab_constants/`).

## What Tony should check on screen

1. Settings page Presets row: fits the narrow panel? Save / Apply / Delete; a second plot of the
   same script lists the preset at once.
2. Presets menu: save with plots in two tab groups and one floating; Apply after closing some;
   positions and sizes of the floating window, docked splits and which tab is in front.
3. Quit with plots open, restart: plots back in place, "waiting" until the folder is selected (or
   running at once when its data is cached); the startup tab's own selection unchanged.
4. A Live preset on a folder with data: Live starts only after the data shows; on a large folder
   the large-folder question comes first.
5. A preset of an unmounted folder: one notice, plots waiting; mount it and select it: they run.
6. Reset all settings' new wording.

## Proposed doc edits (for the Coordinator)

**AGENTS.md, Script system** (after "Results stay in RAM (`RamResults`, R1 …)"), add:
> Presets (`roadmaps/presets-and-workspaces.md`, stage 1): a plot's settings page has a Presets row
> (`helab/views/plots/presets.py`, `PresetBar`): script presets saved per analysis id and action,
> shared by its plots, holding every parameter and the library (not the Live group). The
> **Presets** menu saves one folder's arrangement (the folder, Live, its plots with their settings,
> library, Live group and places; `ArrangementPresets`) and applies it: the open plots close after
> asking, the tab opens the folder as typing its path would and loads it deliberately once it's
> known to hold data, the plots open in place waiting for its data, and Live starts once the data
> shows (`PresetFolder`, under `start_live`'s rules) or says why. The plots open at quit reopen at
> start (Settings → General, "Reopen plots at start", default on; `helab/views/plots/arrangement.py`,
> `PlotReopen`): recorded on plot open, close and quit, each running on its folder's data from RAM
> or one local `cached` read only (`FolderWait`), else waiting for a tab's load;
> `AnalysisInstance.run_reopened` is the one place a reopened plot decides to run. Records and
> validation are Qt-free (`helab/analysis/presets.py`: one `Arrangement` format for both,
> `check_plot` names every saved value that doesn't fit: unknown key, type, limit, removed choice,
> missing parameter, library, version; never clamped or replaced).

**AGENTS.md, Settings persistence**, after the `lab_constants/` sentence:
> Presets are JSON records with a format version under `script_presets/<id>/<action>` and
> `arrangement_presets/<name>` (percent-encoded), the plots to reopen under `open_plots`; Reset all
> settings clears them too.

**roadmaps/presets-and-workspaces.md**: add a "Stage 1 (done 2026-10-22, `agent/presets-reopen`)"
section summarising the above, and move to Open decisions: references vs stored values (2),
replace vs add beside (3), keeping unreopenable plots (7), Reset keeping presets (10); "Startup
restoration and automatic-run behavior" is answered by the setting and decision 8.

**roadmaps/_readme.md** line 171: "- [ ] Save analysis presets and reopen analysis workspaces" →
mark stage 1 done (script and one-folder arrangement presets, reopen at start) with the branch, the
full workspace file left open.

**.ai/MANUAL_TODO.md**: add an item with the six on-screen checks above, linking this handoff.

## Validation

- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest` (local, macOS): 2531 passed, 2 skipped, 2 xfailed, **no RERUN**.
- `mypy helab --strict`, `mypy tests --strict`, `pyright helab tests`: clean.
- New tests: `tests/test_presets_record.py` (29), `tests/test_presets_plots.py` (25),
  `tests/test_presets_window.py` (3, the real main window: record at quit and reopen; menu; a Live
  preset in a real tab on an empty folder starts Live only after the listing).

## CI (run 39745015514 on `a74fd07`, all required jobs green)

- ubuntu py3.13 Tests: 2529 passed, 4 skipped, 2 xfailed, no RERUN. macOS py3.13 Tests: 2531 passed,
  2 skipped, 2 xfailed, no RERUN. Builds green on all three.
- **Windows py3.13 Tests: 2511 passed, 18 skipped, 2 xfailed, 3 RERUN**, all
  `tests/test_cache_first.py::test_a_folder_changed_within_its_mtime_tick_is_listed[cached]`
  (`tests\test_cache_first.py:841: assert 1792656510000000000 is None`, the same each time): already
  listed in `roadmaps/known-issues.md` (line 47); untouched by this branch (no I/O or cache code
  changed). This section is committed locally after the push (not pushed, to save a CI run).

## Follow-up 1 (Tony, 2026-10-22): done locally in `3fff973`, not pushed

1. **Changed from a preset**: after Apply or Save in a plot's settings page, each setting that
   differs from that preset (as applied, memory only; the library included, the Live group not)
   has a small dot (the palette's highlight colour, not amber: it isn't a warning) beside its
   name, tooltip "Changed from preset “p”, which has 20". The Presets row (same row) shows
   **"Save N changes ▾"**: **Save to preset “p”** (asks first: "Replace the settings of preset “p”
   of Counts per shot with these? …") or **Save as new preset…**. No marks when no preset was
   applied this session (a reopened plot's provenance name isn't compared: its values may differ
   from the preset by design); deleting the preset, here or from another plot, clears them.
   Settings the preset holds a value for that didn't fit aren't marked (its note named them).
2. **Replace or Add** replaces decision 3: "“p” opens run with its 3 plots. Replace the 2 open
   plots, or Add the preset's beside them?" (Replace / Add / Cancel, Cancel default). Add keeps the
   open plots where they are, opens the preset's in their own tab groups numbered after them, and
   doesn't apply the saved dock layout (restoring it would move the open plots).
3. **Keep or Drop** replaces decision 7: one non-modal question per start for all plots that
   couldn't reopen: "2 plots open last time couldn't reopen: Gone (its script isn't loaded …); … Keep
   them for a later start (for example once the scripts are loaded), or drop them?" (**Keep for
   later**, default, / **Drop**). Until answered (closed, or HeLab quits) they're kept. Kept plots
   stay in the record after the open plots, each in a tab group of its own, and reopen at a start
   where their script is loaded. A plot whose record can't be read at all is only named.
4. **Storage**: waiting for CoCo's word (presets stay in QSettings for now; decision 10 then
   changes to Reset leaving presets alone).

Tests added: change marks (and clearing them), Replace/Add, Keep/Drop and a kept plot reopening
once its script is loaded. Full suite 2535 passed, no RERUN; strict mypy and pyright clean.
