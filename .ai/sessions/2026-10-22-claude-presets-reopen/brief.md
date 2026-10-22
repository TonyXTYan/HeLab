# Presets and reopened plots, stage 1 (Worker brief)

Floor "Presets Reopen", branch `agent/presets-reopen` from `c3d4b50` (`dev/v0.0.6`, 2026-10-22).
Session folder: `.ai/sessions/2026-10-22-claude-presets-reopen/` (this brief is `brief.md`; write
`notes.md` and `handoff.md` here). Approved by Tony (Chat, 2026-10-22). A parallel floor, "Result
Cache" (`agent/result-cache-r2`), works on disk-cached results; see Overlap.

Start by reading `AGENTS.md` (Script system, Settings persistence, DLD analyses' Hooks),
`roadmaps/agent-workflow.md`, `roadmaps/presets-and-workspaces.md` and the behaviour notes it
links (`.ai/sessions/2026-10-14-codex-planning-for-future/analysis-behaviour.md`), then
`helab/views/plots/` (`instance.py`, `script_tree.py`, `workspace.py`, `settings_panel.py`),
`helab/analysis/parameters.py`, `helab/analysis/parameter_tree.py`, `helab/utils/settings_defaults.py`
and `helab/utils/settings_store.py`.

## Objective

The first stage of [presets and workspaces](../../../roadmaps/presets-and-workspaces.md), about a
day or two of work:

> **Scope (Tony, Chat, 2026-10-22, corrected the same day):** two kinds of preset, both in
> scope: **per-script parameter presets** (1a) and **arrangement presets for one folder** (1b).
> Reopen at start (2) stays as briefed and shares the arrangement record. The arrangement is
> close to the roadmap's workspace stage but for one folder: no multiple folders, pinned results
> or run history.

### 1a. Named parameter presets per script

- In a plot's settings page: **save** the current settings under a name, **apply** a saved one,
  **delete** one (asks first). Presets belong to the script (`analysis_id`, and the action when a
  script has several), shared by every plot of it, saved across restarts.
- A preset holds every parameter's effective value as stored, plus the format version and the
  script identity it was saved from; whether the drawing library and the Live group go in:
  decide and say why (default: library yes, Live group no).
- Validated against the installed script's `ParameterSpec`s on apply and on load, by the same
  rules as 1b below (each incompatible value named, never silently replaced or clamped), except
  that applying to an open plot leaves its incompatible settings at their current values.
- Applying a preset is an edit like any other: it reruns only as an edit would.

### 1b. Named arrangement presets (one folder)

- A preset holds: **the folder to load**, **whether to use Live**, **which plots to open**, the
  plots' **placement** (dock layout: docked, tabbed together or floating) and **each plot's
  parameters** (plus its drawing library and Live group, as reopen records them). Saved under a
  name, across restarts; **save** the current arrangement, **apply** one, **delete** one (asks
  first). Put the menu where it fits (e.g. a main-window menu); propose wording in the handoff.
- **Applying** selects the folder in the current tab through the normal path (a deliberate
  selection: the normal load rules, cache first, large-folder questions and all apply), opens the
  plots in their placement with their parameters, and, with Live on, starts Live under the normal
  Live rules: only once the folder's data is shown (`FolderExplorer.start_live`'s conditions);
  if Live can't start, say why, never force it. What happens to plots already open when a preset
  is applied (replace after asking, or add beside them): pick one, say why in the handoff.
  A folder that isn't there (unmounted, moved) is named; decide whether the plots still open.
- A preset records the format version and, per plot, the script identity it was saved from (id,
  action, version, file hash) and every parameter's effective value as stored (SI units,
  `ParameterSpec`'s own storage); Shots, View range, Mask and the plot's own Constants group
  values are parameters like the others.
- **Validation against the installed script's `ParameterSpec`s** on apply (and on load): unknown
  keys, wrong types, values outside limits, a choice that no longer exists, a parameter the
  script now has that the preset lacks, a script that isn't loaded. Each incompatible value is
  **named** to the user and never silently replaced or clamped: compatible values apply, the
  others take the script's defaults, and the plot says which (one line, details in the tooltip,
  `feedback_ui_vertical_space`). A plot saved by another script version still opens under the
  same rules, and says so. A corrupt preset store is a clear recoverable state (named, ignored,
  never a crash).
- An arrangement may **reference per-script presets** (by name) or **just store each plot's
  values**: propose which (or both, e.g. stored values plus the name they came from) and why,
  including what happens when a referenced preset was changed or deleted since.
- One record format for arrangements and for reopen-at-start (the last arrangement), and one
  validation shared with per-script presets, in a Qt-free
  module (e.g. `helab/analysis/presets.py`, listed in `tests/test_headless_imports.py`) for the
  record and its validation, so the later workspace file can build on it.

### 2. Plots reopen at start

- When HeLab quits (and when a plot opens or closes, so a crash loses little), record the open
  plots: script id/action/version, the folder (source path and its `root://` key if known),
  parameters, library, Live group settings, title, settings section open/closed, and their
  order and tab grouping. At the next start they come back with those settings and **rerun on
  their folder's data from RAM or a local `cached` read only**, as a released plot's reload does
  today (`AnalysisInstance.reload`, `_read_disk_cache`). A reopened plot never asks for source
  I/O itself: with no cached data (or a RAM-only folder), it waits with a one-line note ("Waiting
  for <folder>'s data: select it to load") and runs when that folder's data arrives through a tab's
  normal load. The startup tab's own selection and loads stay exactly as now.
- The same validation as presets applies to the saved settings (script changed, missing script,
  e.g. a Load Scripts… folder not loaded at start): a plot that can't reopen is named once in a
  notice, never a crash, never blocking the GUI; nothing claims a stale or absent result is current.
- Dock geometry: restore order and tab grouping; floating positions and exact sizes only if
  `saveState`/`restoreState` (or similar) does it cleanly, otherwise propose in the handoff.
- A setting to turn reopening off (Settings → General, default on): propose the wording; it is
  the policy the roadmap's "restoring a layout does not implicitly run expensive analysis unless
  the user has chosen that policy" asks for. Expensive plots (Correlations, bootstraps) rerun on
  reopen like any rerun: no special casing, but they must not hold the startup.
- Reopen wording (the setting, the notices) is still open: propose it in the handoff.
- Storage: through `app_settings()`/`read_setting`, every key or prefix in
  `helab/utils/settings_defaults.py` (as `lab_constants/` is), `tests/test_settings_defaults.py`
  passing; JSON values with a format version. Reset all settings clears presets and the reopen
  list (say if that's wrong). Tests use their own ini as conftest gives them.

Not in scope: several folders, pinned
result panels, run history, the full workspace file, per-folder parameter overrides, showing disk-cached results on reopen (the Result Cache
floor's R2 will let a reopened plot show a cached result on an exact `reuse_key` match; leave a
clean seam for it: one place where a reopened plot decides to run).

## Overlap with the Result Cache floor

Both floors touch the plot dock. Split:

- **Yours**: `helab/views/plots/script_tree.py`, `settings_panel.py`, `dock.py`; `workspace.py`
  except the result/source-line functions (`set_plot_result`, `update_plot_source`, `_wrap_plot`,
  `_update_plot_source_label`); in `instance.py`, construction, `start`, `_open_settings`,
  `values`, `backend`, `live_values`, `close` and new code for presets/reopen.
- **Theirs**: in `instance.py`, the run path (`_submit`, `_finished`, `reload` and its helpers
  `_in_ram`, `_read_disk_cache`, `_end_disk_read`, `_reload_event`, `_reload_from`,
  `_reload_failed`); the workspace functions above. You may *call* `reload`/`_submit`; if you
  must change one, keep it minimal and name it in the handoff.
- Prefer new modules (`helab/views/plots/presets.py`, `helab/analysis/presets.py`, a reopen
  module) and small hooks in the shared files. `settings_defaults.py`: both floors append rows;
  keep yours together. Whichever lands second syncs.

## Owned paths

The files above that are yours; new modules under `helab/views/plots/` and `helab/analysis/`;
`helab/analysis/parameter_tree.py` (settings-page controls); `helab/views/HelabMainWindow.py`
(start/quit hooks and the presets menu); calls into `FolderExplorer` (select a folder,
`start_live`) with at most a small public hook there, named in the handoff; `helab/views/SettingsDialog.py` (the reopen setting only);
`helab/utils/settings_defaults.py` (new rows); new test files under `tests/` and minimal edits
to existing plot tests. Don't touch: `helab/scripts/` (scripts' contract stays as it is),
`helab/io_ops/`, `helab/utils/cache_store.py`, `helab/utils/folder_cache.py`, `helab/analysis/results.py`,
`runner*.py`, `CacheTab.py`, `roadmaps/`, `AGENTS.md`, `.ai/MANUAL_TODO.md`, `.ai/memory/`,
`requirements*`.

## Checks

From the floor root, after `source venv/bin/activate && source .ai/local/floor-env.sh`:
`pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest` (report every RERUN with
its reason), `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests`. Tests to add:
per-script preset round-trip for every bundled script (save, restart, apply gives the same
effective values); arrangement round-trip (save, restart, apply gives the same folder, Live choice, plots,
placement and effective values for every bundled script), Live applied only once the data is
shown, each incompatibility named (unknown key, type, limit, removed choice, missing
parameter, missing script, missing folder), corrupt store; reopen round-trip with the folder in RAM, in the disk cache and in
neither (no source request submitted: assert on the IOService requests), a missing script, Live
group and library restored. Don't launch the HeLab GUI (QSettings isn't isolated on floors yet).

## Handoff

Commit as you go on `agent/presets-reopen` (subject + body with validation). Keep
`maestri floor status` current (start, milestones, `--state blocked` when you need Tony,
`--state review` when ready). When done: `handoff.md` with what was built, the decisions you took
(and those left for Tony: reopen and menu wording, defaults, what applying does to open plots,
references vs stored values), what Tony should check on screen,
proposed edits to `AGENTS.md` (Script system / Settings persistence), `roadmaps/presets-and-workspaces.md`,
`roadmaps/_readme.md` and `.ai/MANUAL_TODO.md`; push the branch once to `TonyXTYan/HeLab`, watch
its CI (`gh run watch`) and report every RERUN by test and OS. Then `--state review` and
`maestri ask "CoCo" "<handoff summary>"`. Ask CoCo (`maestri ask "CoCo" …`) when blocked or unsure
of scope.

## Follow-up 1 (Tony, Chat, 2026-10-22, after the handoff)

A Codex Reviewer (Flint) is reviewing `a74fd07` on this floor at the same time, in its own detached
worktree under `.ai/temp/review-presets` (don't touch it). Its findings come to you through CoCo;
fold them in with these changes. Commit as you go; **don't push until CoCo says the review findings
are in too** (one more push for both).

1. **Changed from a preset:** when a plot's values differ from the script preset last applied to
   it, show an indication **next to each changed value** in the settings page (memory only, from
   the applied preset's values; the tooltip gives the preset's value) and a button offering
   **Save to preset "<name>"** (overwrite, asks first) or **Save as new preset…**. Keep it to one
   row (`feedback_ui_vertical_space`); no indication when no preset was applied.
2. **Applying an arrangement asks Replace or Add** (Add opens the preset's plots beside the open
   ones, numbered after them; Cancel default). Replaces decision 3.
3. **A plot that can't reopen: ask the user** Drop or Keep (Keep leaves it in the record for a
   later session, e.g. until its Load Scripts… folder is loaded; one question for all such plots
   at a start, not one per plot). Replaces decision 7.
4. **Preset storage separate from QSettings** ("maybe something similar to the folder status
   storage?"): CoCo is confirming the design with Tony; start with 1–3 and **wait for CoCo's word
   on storage before moving it**. Reset all settings will then leave presets alone (decision 10).

Decisions 2 (arrangements store values with provenance), 1, 4–6, 8, 9, 11 and the wording: Tony is
fine with them.
