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
  - `ScriptPreset` / `ScriptPresets` (one stored record per preset since Follow-up 2; one that
    can't be read is named and left as it is).
  - `check_plot` / `check_values`: unknown key, wrong type, outside limits, a choice that's gone,
    a parameter the record lacks, a library that's gone, a script version that differs. Nothing is
    clamped or replaced: values that fit apply, the others are named (`PlotCheck.summary` one
    line, `details` the tooltip). `preset_note`: a referenced script preset changed or deleted.
- **`helab/views/plots/presets.py`**: storage (since Follow-up 2 the disk cache store's `presets`
  table through FolderCache, below); **`PresetBar`**, the Presets row at the top of
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
10. **Reset all settings** clears the reopen list and keeps presets (Follow-up 2: presets are in the
    disk cache store now); its confirmation says so.
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
- `settings_defaults.py`: rows `reopen_plots_at_start`, `open_plots` (together, after
  `log_files_keep`); the preset prefixes went with Follow-up 2.
- Follow-up 2 (store, admin, events, FolderCache, CacheTab): see its section below.

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
6. Reset all settings' new wording (presets kept).
7. (Flint, round 6) With Live on a folder whose cached data turns out not to match it: stop Live →
   Review… / Load as it is now → start Live again: the mismatch clears with the new data and Live
   runs on it, never the old shots.

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
> The plots to reopen are an arrangement record under `open_plots` (Reset all settings clears it);
> presets are in the disk cache store (Caching), not QSettings.

(And the Caching paragraph's addition: see Follow-up 2 below.)

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

## Review fixes (Flint on `a74fd07`): `29add99`, not pushed

1. P1 mismatched folder: `FolderWait` uses no RAM (tab pins included) or cached data while the folder
   is in `FolderCache.mismatched`, deliberate Rerun included; line "run's cached data doesn't match
   the folder: Review… it, or select it to load it as it is now"; looks again on `mismatchesChanged`.
2. P2 unverified cached read: asked again once on `volumesVerified` (a plain miss isn't).
3. P2 Live-off preset on the folder already shown: Apply stops Live ("Preset “X”: Live off for run").
4. P2 bad `dock_state`: `parse` drops it (`Arrangement.layout_error`), plots open in their tab groups,
   reopen and apply name it; restore decodes defensively.

Each has a regression test (5 tests fail on the unfixed code). Full suite 2541 passed, no RERUN;
strict mypy and pyright clean.

## Review fixes, round 2 (Flint on `ffc2d4e`): see the commit after `ffc2d4e`, not pushed

1. P1: the datasets held when a wait sees its folder mismatched stay unusable to it (weak refs);
   `mismatchesChanged` (emitted before the new load's dataset is published) only records them;
   a cached read landing while mismatched is refused. Tests drive a real `allow_missing` load
   through `FolderCache`'s events with the old pin held.
2. P2: change marks compare only values `check_value` accepts (no `coerce` on rejected values).
3. P2: the Keep/Drop box is shown with `show()`, non-modal (tested on the real box).

4 new tests fail on `ffc2d4e`; full suite 2544 passed, no RERUN; strict mypy and pyright clean.

## Review fixes, round 3 (Flint on `0098d8d`): the commit after `0098d8d`, not pushed

- **One rule** for a reopened or preset plot's data, on every path: only what `FolderCache` itself
  keeps as the folder's current data (`current_dataset`, else `latest_dataset`; a cached read's
  result only if `holds` it; none while `mismatched`), never a tab's pin alone. No per-wait history.
- **`helab/utils/folder_cache.py` (outside my owned paths, a one-condition guard, no new API):** a
  `cached` read that lands while its folder is mismatched is cancelled, not stored, so `_mismatch`'s
  "nothing shows it again until a load completes" holds for tabs too (a tab's cached read racing
  a check that finds shots gone no longer shows the old data). The Result Cache floor, which also
  edits `folder_cache.py`, merges after: the change is in the `loaded` branch's cancel condition.
- Tests drive real helper events (load, `shots_missing`, list, invalidate, cached, `evict_to`) with a
  tab's old pin held and a waiter made after each drop (mismatch → load → evicted; folder changed;
  cleared), a cached read racing a mismatch, and an arrangement applied over a pinned old dataset.
  Full suite 2549 passed, no RERUN; strict mypy and pyright clean.

## Review fix, round 4 (Flint on `222bcdb`): the commit after `222bcdb`, not pushed

**`helab/utils/folder_cache.py`, for the Result Cache merge (replaces round 3's condition):**
`_mismatch` cancels the folder's in-flight `cached` job and marks its requests being delivered
cancelled (as `_invalidate_data` does), so a read started before a mismatch never lands after it,
even once a replacement load has cleared the mismatch. Round 3's `job.path in self.mismatched`
condition in the `loaded` branch is removed (redundant: every caller that starts a cached read
refuses while mismatched). The two changes in that file are these lines in `_mismatch` only.
Recovery is unchanged (Load as it is now, the tab's own loads, cached reads asked after the
folder matched again). Tests: `tests/test_presets_mismatch_tab.py` (Flint's order with a real
`FolderExplorer`, ending with a post-resolution cached read that is taken) and the same order at
`FolderCache` level in `tests/test_presets_plots.py`; both fail on `222bcdb`. Full suite 2551
passed, no RERUN; strict mypy and pyright clean.

## Review fix, round 5 (Flint on `760a69f`): the commit after `760a69f`, not pushed

**`helab/utils/folder_cache.py`, net diff vs `c3d4b50` (for the Result Cache merge): 14 lines added
in `_mismatch`, one line (`self._matched(job.path)`) moved in the `loaded` branch.** Replaces the
round-3 and round-4 changes.
- `_mismatch` fences all of the folder's earlier work: it moves the folder's epoch (every load,
  memory check, Live check, held save and cached read from before is cancelled when it reports, by
  the existing epoch check), raises `_base_floor` (nothing held from before is a later load's base)
  and cancels queued RAM answers of loads and cached reads (subscribers hear `cancelled`). Not a
  clear: the record, window and Review / Retry stay; no disk flags change.
- `_matched` runs only for an accepted load, after the epoch / signature / base checks.
- Side effects, as intended or acceptable: a tab load or Live check of that folder in flight at the
  mismatch ends `cancelled` (the tab says "Cancelled — Retry"; Live stops with Retry, as on any
  error); a load that finished just before and is still writing its disk cache has its badge events
  ignored (its `_finishing_epochs` no longer match), so the cache badge waits for the next check.
- **For `roadmaps/known-issues.md` (pre-existing, fixed here):** work started before a mismatch
  could clear it and bring the old data back (ordinary load, memory check, Live check, held save,
  a check beside a cached read, a queued RAM answer); `tests/test_mismatch_fence.py`'s ordinary-load
  test fails on `c3d4b50` (`mismatched` emptied by the old load's `loaded`), all 6 family tests fail
  on `c3d4b50` and `760a69f`.

Full suite 2560 passed, no RERUN; strict mypy and pyright clean.


## Round 6 (Flint on `2c7c2dc`: review complete, nothing above P3): the commit after `2c7c2dc`, not pushed

- `live_unchanged` is fenced by the same epoch check as `loaded`: a Live check from before a
  mismatch that finds nothing new also ends `cancelled` (Live stops with Retry) instead of scheduling
  another check, so "a Live check in flight at the mismatch ends cancelled" (round 5) is exact. Test:
  the real Live helper (`io_ops.live.live_check`) on an unchanged temp folder, its events fed to the
  Live job after a status check's mismatch (`tests/test_mismatch_fence.py`; fails without the gate).
- **`folder_cache.py` net diff vs `c3d4b50` now:** 18 lines added (14 in `_mismatch`, 4 for the
  `live_unchanged` gate in the load/cached event branch), one line (`self._matched(job.path)`) moved
  in the `loaded` branch.
- **Later cleanup (note only):** stop Live → Review… recovery needs a Qt event-loop turn between
  the two actions (the tab's model updates in between; called on one stack, the first call finds no
  replacement). Not a blocker; a later test/API cleanup could make the order explicit.
- **For `roadmaps/known-issues.md`: six mismatch races, pre-existing, fixed in `b66bba6`** (each
  fails on `c3d4b50`, tests in `tests/test_mismatch_fence.py`): work started before a folder was found
  mismatched could clear the mismatch and bring the old data back: (1) an ordinary load, (2) a
  memory check, (3) a Live check, (4) a held (Live) save, (5) a check beside a cached read (cleared
  it and then failed, leaving no data and no warning), (6) a RAM answer still queued (handed the
  old data to a tab). Plus the cached-read race of rounds 3–4, fixed by the same fence.

Full suite 2561 passed, no RERUN; strict mypy and pyright clean.

## Follow-up 2 (Tony, 2026-10-22: presets in the cache store, an inspector): `0dd9e02` and the commit after, not pushed (full suite 2575 passed, 2 skipped, 2 xfailed, no RERUN; strict mypy and pyright clean)

**Storage** (`helab/utils/cache_store.py`, the presets table and its `_migrate` step only):
- Table `presets (kind, scope, name, record, set_at)`, primary key (kind, scope, name). `kind` is
  "script" (`scope` = percent-encoded analysis id `/` action) or "arrangement" (`scope` "").
  `record` is the preset's JSON, or NULL once deleted. The row stays with its `set_at`, so an older
  write (another HeLab, a late request) can't bring the preset back; a later write can.
- `write_presets(rows)` is one transaction: each row is written unless a later `set_at` is saved,
  and it returns what is saved now. `read_presets()` returns every row, deleted ones too. A
  read-only store without the table reads as none and is never changed.
- `_migrate` gained a third check (`presets`), run under the same write lock. `SCHEMA` has the
  table too.
- Keyed by no folder, so `rekey_subtree`, `remove`/Clear all, purges, `trim`, `clear_root` and
  `clear_prefs` never touch it.
- **For Cellar's merge:** `SCHEMA` gains one `CREATE TABLE`, and `_migrate`'s `missing()` gains a
  third element. Each is a few lines next to `folder_constants`.

**Action and event** (`helab/io_ops/admin.py`, `events.py`):
- `cache_admin` "presets" (local lane): writes `params["rows"]` (if any), then reads every row.
  With nothing to write it only reads, so a read-only store still answers.
- It sends `PresetsEvent` `{"kind": "presets", "saved", "rows" | "error"}` (`PresetRowFields`).
- **For Cellar:** one `elif` in `cache_admin`, one name in `ADMIN_ACTIONS`, two TypedDicts, one
  `HelperEvent` member and one `KINDS` name.

**FolderCache** (`helab/utils/folder_cache.py`, the presets section, the `_on_admin_event` hooks and
the `quit_saves` entry):
- `presets` is the RAM copy, (kind, scope, name) → {record, set_at}, deleted rows included; the
  newest `set_at` wins.
- **What I chose for reads:** a helper reads presets at startup (`ArrangementPresets.__init__`),
  and when the Presets menu, a plot's settings page or the presets window opens. One read runs at
  a time; a read asked meanwhile runs once after it. Every write job also reads everything back,
  so the menu and the plots' Presets rows update when the answer comes (`presetsChanged`).
- `set_presets(rows)`: the user's change shows at once, and one helper writes it, so a rename is
  atomic. Its `set_at` is past what this HeLab shows, even when another HeLab's clock is ahead.
  The call returns "" or why the change is RAM only.
- **RAM only** while the disk cache is off or its saved folder is refused (`presets_session_only`;
  nothing is read or written then). The next read writes those rows once the store is there, e.g.
  after a cache move clears the refusal.
- **A store that can't be read** is named (`presets_note()`: "⚠ Saved presets can't be read: …").
  RAM keeps what it knew, and changes stay "couldn't be saved (…)" until the next read succeeds.
  It is never "no presets". Before the first answer, the note says "Reading saved presets…".
- `quit_saves` lists **"Presets"** (`PRESETS_SAVING`) while a preset write is in flight.
- **`helab/views/QuitSaveDialog.py`** (added to my owned paths by CoCo; Cellar hasn't touched it):
  that entry reads "Presets — saving", and the heading counts only folders ("Saving presets to the
  disk cache before HeLab quits:", or "Saving 2 folders and presets …"). The commit after
  `9a338fd`; test `test_the_quit_window_names_presets_being_saved`.
- Refused while quitting (`QUITTING`), like constants.

**Views:**
- `helab/views/plots/presets.py`: the storage functions now go through `preset_store()` (the app's
  FolderCache). The QSettings functions and `PresetSignals` are gone, and `ScriptPresets` is built
  from one record per preset (`from_records`).
- Saving a preset under another name no longer asks to "replace unreadable presets": nothing but
  the named preset is written. Notes and notices add "(RAM only…)" when that applies.
- `preset_note` is skipped until the store's presets are known.
- **Folder by `root://` key:** applying still selects the saved path. When that path can't be
  opened, the notice also names where its data root is seen this session, if anywhere
  (`folder_now`: "its data root is seen at another place now: <path>").

**Inspector** (`helab/views/PresetsInspector.py`, new; the hook in `CacheTab.py` is 16 lines):
- Settings → Cache has a "Presets" row with its counts and the note, and **Presets…**, which opens
  the window (one at a time, non-modal).
- The window lists script presets by script, then arrangement presets. Columns: Name (with
  "(RAM only)"), Saved with (vN, or "folder, N plots"), Installed script ("✓ fits the installed
  script", "⚠ N settings wouldn't apply · saved with v0, now v1", "⚠ its script isn't loaded…",
  "⚠ can't be read: …"), Saved (date).
- The details pane shows each value by its setting's title, the library, each problem named
  (`check_plot`, the same check as applying), and each plot of an arrangement with its own
  verdict.
- **Rename…** and **Duplicate…** ask only when they would replace another preset. **Delete…**
  asks first.
- The installed scripts come from the main window's Scripts panel (`set_script_finder`, held
  weakly). Without them, a preset says "not checked: the installed scripts aren't known here".
- **Editing values in the inspector is not built, by proposal:** pyqtgraph's parameter editors
  belong to a plot's settings tree (`AnalysisInstance`, Live group, library), and reusing them
  outside a plot isn't clean. Apply → change → **Save to preset “X”** already edits a preset. A
  later option is an "Edit in a plot" button that opens a plot of the script with the preset
  applied.
- A rename leaves an arrangement that names the old preset saying "preset “old” deleted since"
  (its own values still apply).

**Reopen at start** stays in QSettings (`open_plots`; Reset all settings clears it). The preset
rows left `settings_defaults.py`; nothing was released, so old keys get no migration.

**Tests:**
- `tests/test_presets_store.py` (new, 13), at three levels:
  - The store: newest wins; a delete beats an older write and a later write beats the delete; a
    failed transaction writes nothing; scopes kept apart; Clear all, purges, trim, `clear_root`,
    `clear_prefs` and a re-key leave presets; an older store gains the table; a read-only store
    without it reads as none and is left as it was.
  - The helper's action.
  - FolderCache through real helpers: save, restart, read back, delete, restart; another HeLab's
    later choice wins and shows; an older write can't undo a delete; a refused cache folder keeps
    presets in RAM, then saves them once usable (read back after a restart); disk cache off; an
    unreadable store is named, keeps what was known and saves on the next good read;
    `quit_saves` waits ("Presets"); Clear all plus Reset all settings leave presets (read back
    after a restart).
- `tests/test_presets_plots.py`:
  - The round-trip tests now really restart (the app's IOService ends; a new FolderCache reads
    the store).
  - New: a script preset is there after a restart.
  - New inspector tests: the listing with versions and verdicts, a value outside its limits, an
    unreadable preset, a missing script in an arrangement; Rename, Duplicate and Delete with their
    questions, read back after a restart; the Cache tab's counts and Presets….
- Each preset test module resets the app FolderCache's preset RAM (an autouse `fresh_presets`)
  and waits for its preset helpers: that cache lasts a worker's run. *Proposed for later:* move
  this into `tests/conftest.py`'s `default_constants`, which isn't my file.

**Proposed doc edit, AGENTS.md Caching paragraph** (after the folder constants sentences):
> Presets (`helab/views/plots/presets.py`) are the store's `presets` table: one row per script or
> arrangement preset (kind, scope, name, JSON record or NULL once deleted, `set_at`), written only
> by helpers (`cache_admin presets`, local lane: writes, then reads every row), the newest `set_at`
> winning each row in the store's transaction; a delete keeps its row so an older write can't
> bring the preset back. Nothing else removes them (not Clear all, purges, making room, a root's
> Clear cached data… or Reset all settings). FolderCache keeps them in RAM (`presets`), read at
> startup and when the Presets menu, a plot's settings page or Settings → Cache › Presets…
> (`helab/views/PresetsInspector.py`) opens; RAM only while the disk cache is off or its folder
> refused (saved by the next read once it's there); a store that can't be read is named
> (`presets_note`), never "no presets"; `quit_saves` waits for their writes.

## Review fixes, round 7 (Flint on `5923fe7..9a338fd`): the commit after `65ff7e1`, not pushed

1. **(P1) Saving before the first read could replace a stored preset unasked.**
   - Changes made before the store's names are known (`presets_read`, which is set by a successful
     answer) are kept in `_presets_unknown`, marked `PRESETS_WAIT_READ`, and not written. A read
     carries no rows until then.
   - When the first successful answer lands, any of those names that the store holds with a record
     keeps the stored preset, and `presets_conflicts` says so once (`PRESET_FOUND`, "… save again
     to replace it"). The plot's Presets row shows it, and an arrangement shows it as a notice. The
     rest are written then.
   - If that read fails, they say "not saved: the saved presets can't be read (…)" and wait for the
     next successful read. An unknown or unreadable list of names never authorizes a replace.
   - `quit_saves` waits for changes waiting for a read in flight.
   - A save then says "Saved preset “p” (saved once the saved presets are read)".
2. **(P2) An older read snapshot could remove a just-written preset.**
   - **The rule now:** within one store, a row never goes away (a delete keeps its row), so no read
     answer, however old, removes anything from RAM. Newest `set_at` merges the rest.
   - Only an answer from another store (`store_id`, now sent as the event's `store`; a store
     deleted and recreated by hand) drops what the previous store said, keeping this session's
     unsaved changes.
   - This is ordering by store identity rather than by the store's write count: write counts
     would only matter if rows could vanish within a store, and they can't.
   - The submission-time rule is gone, and `_preset_jobs` now holds only each job's rows.
3. **(P2) Empty claimed before a successful read.**
   - "No presets saved" appears in the menu, and "(none saved)" in the inspector, only once
     `presets_known()` is true: a successful read, or RAM only, where there is no store.
   - Before that, the menu shows only the note ("Reading saved presets…" or "⚠ Saved presets
     can't be read: …"), the inspector shows "(none known yet)", and Settings → Cache's line says
     "… known · <note>". The plot row's "No presets of X yet" tooltip is gated the same way.

Tests:
- `tests/test_presets_store.py`, four new:
  - A save before the first read, with real helpers: no write before the names are known, the
    stored "p" is kept and said, "q" is written, and saving again then writes it.
  - Unreadable names first: the change waits and is checked once the store is readable.
  - The older snapshot after a write, through frozen helpers, in Flint's order; and another
    store's answer.
  - Empty claimed only after a read: the inspector and the Cache tab's line, before, after a
    failed read, and after a successful one.
- `tests/test_presets_plots.py`, three new:
  - A plot's Save… before the first read: no question; the stored one kept and said; asks once the
    name is known.
  - The menu's Save Folder and Plots as Preset… before the first read: the stored one kept, with a
    notice.
  - The menu's "No presets saved" only after a successful read.
- **All seven fail on `65ff7e1`** (run in a scratch worktree with only the new names added). The
  snapshot test fails with the preset pruned from RAM.
- The plot tests' fixture now starts each test with the store read, as after startup.

Checks: full suite 2583 passed, 2 skipped, 2 xfailed, **no RERUN**; mypy --strict (helab, tests)
and pyright clean.

## Review fixes, round 8 (Flint on `9a338fd..393d2af`, round 7 accepted): the commit after `393d2af`, not pushed

Both findings concern a store recreated while HeLab runs (deleted by hand, made again at the same
path, so it has a new `store_id`).

- **Every presets answer now names its store** (`store`), the error answer too.
- **FolderCache checks the store first.**
  - An answer from a **retired** store (one replaced since: `_presets_retired`) changes nothing.
    It acknowledges no save, merges no row and doesn't make that store current. The rows its job
    wrote are written again, to the current store, so `quit_saves` keeps waiting for them.
  - On a **store change**, every row the previous store said goes, whatever its `set_at`: `set_at`
    isn't comparable across unrelated stores. This session's unsaved changes stay (and are written
    to the new store). Only then are the new store's rows merged. Pending conflict notes from the
    old store go too.
- Tests, in `tests/test_presets_store.py`, all three failing on `393d2af`:
  - `test_a_late_answer_from_the_retired_store_acknowledges_nothing`: frozen helpers, Flint's
    order.
  - `test_a_recreated_stores_rows_replace_the_old_stores_whatever_their_times`: A's p at set_at
    100 against B's at 10; an unsaved change carried to B.
  - `test_a_store_recreated_at_the_same_folder_is_read_as_itself`: real helpers, the store
    deleted and recreated at the same path.
- `review-findings.md` (CoCo's and Flint's rounds 7 and 8) is committed with this, so the floor is
  clean.

Checks: full suite 2586 passed, 2 skipped, 2 xfailed, **no RERUN**; mypy --strict (helab, tests)
and pyright clean.

## Review fixes, round 9 (Flint on `393d2af..3ba07eb`, round 8 accepted): the commit after `3ba07eb`, not pushed

Rounds 7–9 were all edge cases of one piece of bookkeeping: which preset changes are still
unsaved. Each round patched one answer order. This round replaces the patches with one rule that
holds whatever order helpers answer in. The rule is written above the presets section of
`helab/utils/folder_cache.py`, and is this:

1. **RAM follows one store, the current one** (`_presets_store`).
   - An answer from a store replaced since (`_presets_retired`) changes nothing.
   - An answer from another store makes it current, **as at a fresh start**:
     - everything the last store said goes, whatever its times;
     - the new store's names are unknown (`presets_read` False) until it sends its rows, so an
       error from it leaves them unknown;
     - this session's unsaved changes stay, and are checked against the new store's names like
       any change made before a first read (a name it holds is kept: `PRESET_FOUND`).
2. **A change is written only once the current store's names are known, and only to that store.**
   - Every write names its store (`store` in the job's params).
   - A helper that opens another store (one recreated since) writes nothing there. It only reads
     that store and answers with its rows and id (`helab/io_ops/admin.py`).
   - Until the names are known, a change waits (`PRESETS_WAIT_READ`).
3. **A change is cleared only by the current store.** That is, the current store holds that
   change (its row with the change's `set_at`) or a later choice of that preset, whichever job's
   answer says so.
   - Each job records the exact changes it carries (`_preset_jobs`: key → `set_at`).
   - Nothing defers any more to "another job writes it too" (`_preset_writing` is gone).
4. **When a job ends**, take each change it carried that is still unsaved and that no other job
   carries:
   - if the job's answer came from a replaced store, the change is written again to the current
     store, or waits for that store's names;
   - otherwise its save failed, and the change says why ("couldn't be saved (…)") until the next
     read tries again.

So a change shown as being saved always has a job in flight that will settle it. `presets_saving`
(and so `quit_saves`) also requires a preset job in flight, as a backstop.

Flint's two findings under this rule:

- **(1)** Interleaved retired/current replies. B's answer settles p by itself; A's answer is
  ignored; at A's end p is no longer A's change. Nothing is left waiting, and quitting doesn't
  hang.
- **(2)** On A→B, `presets_read` is reset. B's failed read shows "⚠ Saved presets can't be read",
  the inspector and menu say "(none known yet)", and a change waits for B's names
  (`PRESETS_WAIT_READ`, only a read asked) instead of being written.

One behaviour changed beyond the findings: a write meant for A that finds B no longer lands in
B. Under the old code it could replace a preset in B whose name this session had never seen,
which is the round-7 P1 over again.

Tests, in `tests/test_presets_store.py`:

- `test_rows_meant_for_another_store_are_never_written`: the helper's action, with a real store.
  It is given another store's id, and no id.
- `test_interleaved_answers_from_the_retired_and_the_current_store_leave_nothing_waiting`:
  Flint's order, run with frozen helpers whose stores are simulated (`Stores`).
- `test_every_order_of_the_three_writes_answers_settles_every_change`: all 90 interleavings of
  the three write jobs (to A, and two to B). Every job's presets event comes before its end. Each
  step checks that nothing is shown as saving without a job in flight. At the end every change is
  settled and B holds the newest.
- `test_a_retired_stores_answer_after_its_change_was_superseded_writes_nothing_again`.
- `test_a_write_meant_for_the_old_store_that_finds_a_new_one_writes_nothing_there`: B's p is kept,
  with the conflict said, and q is written.
- `test_a_replacement_stores_failed_read_leaves_its_names_unknown`: Flint's (2), down to the
  inspector's lines and the quit window.

Six tests fail on `3ba07eb`. Flint's order fails there with p stuck as "being written"; the
others fail on the old code's ordering or because writes didn't name a store. Two existing
helper-action tests now pass the store's id.

Proposed AGENTS.md addition, under Caching (for the Coordinator), after the folder constants
sentence: "Presets (`presets` table) follow the same rule, and one more for a store recreated
while HeLab runs (new `store_id`): RAM follows the current store; another store's answer is a
fresh start (names unknown until it sends rows; unsaved changes kept and checked against them); a
write names its store and a helper finding another writes nothing; a change is cleared only by the
current store holding it or a later choice; a change left unsaved when its job ends is written
again if a replaced store answered it, else said not saved (`FolderCache` presets section)."

## Review fix, round 10 (Flint on `3ba07eb..4fc315b`, the round-9 rule held): the commit after `4fc315b`, not pushed

**Finding.** A change p is saved before the store's names are known. A second read is asked
while the first is still running (`_presets_again`). HeLab starts quitting, and the first read
fails. p was then marked "not saved" and `quitSavesChanged` fired while `quit_saves()` was
briefly empty, so `QuitSaveDialog` accepted the quit. Only after that did the job's end queue the
read that had been asked again. Quitting could therefore stop that retry and lose p.

**Fix.** It follows from the round-9 rule: a job's continuation is queued before its end is
announced.

- `_preset_job_ended` queues the read asked again (`_presets_again`) before it emits
  `quitSavesChanged` or `presetsChanged`.
- `_names_unread` no longer marks changes "not saved" while such a read is already asked for.
  They stay `PRESETS_WAIT_READ` and wait for that read, so they count as being saved. This covers
  the earlier error notification from the failed answer (`_on_presets`), as well as a job that
  fails outright.

**Test.** `test_quitting_waits_for_a_read_asked_again_after_the_first_one_fails`, in
`tests/test_presets_store.py`, uses the real `QuitSaveDialog` after `cancel_for_quit`. It runs
twice: once with the first read's answer an error, once with the job itself failing. In both,
every `quitSavesChanged` shows `["Presets"]`, the window stays open, the retry is queued, and p is
saved before the window accepts. Both variants fail on `4fc315b`, where the window saw `[]`.

## Review fix, round 11 (Flint on `4fc315b..3bb153a`): the commit after `3bb153a`, not pushed

**Finding.** Another job's failure could still tell quit that nothing was left while B's read
retry was running. Round 10's guard checked only `_presets_again`, which is false once the retry
is queued. So an older write ending with a helper error, or answering with B's read error, marked
p "not saved" and told quit `[]`.

**Fix: the decision is made in one place.** A change still owed (being written `""`, or waiting
for the names `PRESETS_WAIT_READ`) is said not saved only in `_presets_settle`. That runs only
once no preset job is in flight and no read is asked for.

- Until then, failures are only noted:
  - a job's failure, for the changes it carried (`_presets_failed`);
  - a failed read of names not yet known (`_presets_unread`);
  - a full queue, the same way.
- The owed change keeps its state while they are noted.
- `_names_unread`, the per-path guard, is gone.
- When the last job ends, each owed change gets its noted reason, or "not saved: the saved
  presets can't be read (…)".

**Quit's answer.** `presets_saving` (and so `quit_saves`) lists Presets while a change is owed
and a preset job is in flight or a read is asked for. Since owed changes leave that state only in
`_presets_settle`, no notification can show quit an empty list while work that would save one
remains.

**One deviation from CoCo's wording, for Tony and CoCo to confirm.** CoCo asked for Presets to be
listed whenever any preset job is in flight, owed change or not. I tried exactly that first.
Closing the main window during the startup read (or after opening the Presets menu) then showed
"Saving presets…" with nothing to save, and in tests the main window's close was deferred
(`test_presets_window` failed and the preset tests hung). The added "a change is owed" condition
keeps the structural guarantee: an owed change can't stop being owed while work remains, so
quitting never ends while a change is still owed and work is left that would save it.

**Tests,** in `tests/test_presets_store.py`:

- `test_another_jobs_failure_never_tells_quit_nothing_is_left_while_bs_read_runs`: Flint's two
  orders, with the real `QuitSaveDialog` after `cancel_for_quit`. The window waits, every
  notification shows `["Presets"]`, and B's read then saves p.
- `test_quit_waits_exactly_while_work_that_would_save_a_change_remains`: every way w1 can end
  (helper error, B read error, the retired store's answer, B's rows) against every way r2 can end
  (B's rows, B read error, helper error), in every order of their events, 53 cases. At every
  step, the quit window lists Presets exactly while p is owed and a job or requested read
  remains, and p is never owed with neither. At the end, p is saved to B if any answer read B, and
  otherwise is said not saved.
- `test_a_replacement_stores_failed_read_leaves_its_names_unknown` (round 9) is adjusted: q now
  stays undecided while A's job runs, and is said not saved once it ends.

These fail on `3bb153a`: both of Flint's orders, the enumeration, and the adjusted round-9 test.
