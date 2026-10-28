# Brief: Live monitoring L1 + L2

Coordinator: Maestro (ground). Floor: "Live L1", branch `agent/live-l1`,
base: `dev/v0.0.6` at the commit that adds this brief. Rules:
`AGENTS.md`, `roadmaps/agent-workflow.md`.

## Objective

Stages L1 and L2 of [live monitoring](../../../roadmaps/live-monitoring.md#stages),
following its "Dataset-cache writes while monitoring" and "Live scope and
polling" sections (Tony's decisions, 2026-10-19).

- Enable the toolbar **Live** action (`HelabMainWindow.action_tab_live`, now a
  disabled placeholder) for the current tab's selected folder when it holds
  loaded data (decide and note what it does otherwise).
- While Live is on: the tab's folder explorer is greyed out (tree, path bar,
  navigation); the summary's "Live updates off" line becomes a live state line
  (last check, new shots, still being written, next check).
- Polling: a check of the folder runs a cooldown after the previous check
  finished (default 3 s, a setting in Settings → General). Reuse the
  incremental load (`memory` fingerprints → `memory_shots`, source `updated`);
  files still being written stay excluded and counted as today. Prefer one
  cheap test (e.g. the folder's mtime, as the cached `unchanged` path does)
  before a listing, and measure what a check costs.
- New shots stay in RAM; no per-shot disk write. **L2**: auto-save every N
  unsaved shots (default 10, Settings → Cache), saves never overlap. Save also
  when Live stops (Live off, tab switch, tab close). Auto-saves obey the
  budget, Don't cache and the pending-save questions like any load's save.
- **Switching tabs turns Live off**; Live is never restored at startup.
- **Quit** saves unsaved shots first, with a window naming what it saves and
  **Quit now**; a save with no progress for the usual timeout stops itself.
  The same quit save covers an ordinary finished load's background save
  (`disk_cache_pending`), fixing the known issue in `roadmaps/_readme.md`.
- Errors (source gone, check failed): Live stops polling and keeps the data,
  with a clear line and Retry; no unbounded retries.

## Points to look at, and say what you chose

- A check every 3 s runs in the **foreground** lane, so background work pauses
  around each one (`IOService._apply_pauses`, 0.5 s resume). Measure; if it
  starves background work, propose a rule (e.g. a Live check that finds
  nothing new doesn't hold the background).
- Which events the plots get: the shown dataset is replaced as today when new
  shots merge (`displayed_dataset`). Plots following Live is L3 (later, with
  the dataset view from the other floor): don't build plot updates here.

## Ownership

- Owns: `helab/views/FolderExplorer.py`, `helab/utils/folder_cache.py`,
  `helab/utils/io_service.py`, `helab/io_helper.py` (only if needed), the Live
  action, `closeEvent` / quit flow in `helab/views/HelabMainWindow.py`, the
  two settings (`helab/views/SettingsDialog.py`, `CacheTab.py`), a new
  `helab/views/QuitSaveDialog.py` (or similar), tests for all of these.
- Don't touch: `helab/scripts/`, `helab/models/ScriptTreeSelector.py`, the plot
  dock code in `HelabMainWindow` (`_set_plot_source`, `_update_plot_source_label`),
  any new dataset-view module: the "Dataset view + plots" floor owns those.
  If you must change something there, ask the coordinator first.
- Docs: write only this session folder. Put proposed changes to `AGENTS.md`,
  `roadmaps/`, `.ai/memory/` and `.ai/MANUAL_TODO.md` in `handoff.md`.

## Checks

- Floor setup: `python -c "import helab; print(helab.__file__)"` must print a
  path inside this floor, and `source .ai/local/floor-env.sh` before running
  the app or scripts (private cache/app folders). Never launch the app against
  Tony's real cache or settings without that file sourced; native QSettings are
  not isolated yet, so prefer offscreen scripts with a tmp `QSettings` file.
- Tests with fake folders where files arrive during Live (settle time via
  `HELAB_SETTLE_SECONDS`), tab switch, quit save and Quit now, error stop.
- `pytest -n 6 --reruns 5 --reruns-delay 1` (another floor runs too), report
  any RERUN; `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests`.
- Optional real-volume run on `/Volumes/dld_output` is Tony's (MANUAL_TODO
  "observe new shots during writing"); note what he should check.

## Handoff

Commit as you go (subject + body with what, why, validation; end with the
Co-Authored-By line from AGENTS.md conventions). When done: `handoff.md` here
(what changed, decisions taken, open questions, proposed doc changes, manual
checks), push (the only push: commit locally at will, push once at the end to save CI runs) `agent/live-l1` once, `maestri floor status "…" --state review`,
and tell the coordinator.
