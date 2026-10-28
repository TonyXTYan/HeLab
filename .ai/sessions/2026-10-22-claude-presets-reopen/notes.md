# Presets and reopened plots: working notes (Loom, Claude Opus 5.5)

2026-10-22, floor "Presets Reopen", branch `agent/presets-reopen` from `c3d4b50`.

## Scope changes during the session

1. Brief as written: per-script parameter presets + reopen at start.
2. CoCo relayed Tony (Chat): a preset is a whole arrangement for one folder; per-script dropped.
3. CoCo relayed Tony's correction the same day: both, per-script (1a) and arrangement (1b);
   propose references vs stored values. Built both; see the handoff's decisions.

## Findings while building

- `ScriptsManager` script ids embed the file path; records find a script by its stable
  `analysis_id` (and action) instead (`TreePanelWidget.find_script`).
- `FolderCache` stores both a load's and a cached read's dataset in `datasets` and emits
  `datasetChanged(path)` afterwards: a waiting plot listens to that (no change to folder_cache).
- A `cached` read's outcomes: `loaded` with a `Dataset`, `error` ("No cached data for this
  folder" when none), `too_large`, `cancelled`; the reload code's shape was copied into
  `FolderWait` rather than reusing `_read_disk_cache` (Cellar's), whose event handler only acts
  on released plots.
- Qt (offscreen): the tab behind another in a dock group is neither hidden nor invisible;
  `visibleRegion().isEmpty()` tells it. `QComboBox` with a placeholder picks no item itself.
- A real tab's explicit load of a folder without TXY files fails ("No converted TXY files in this
  folder"), which first stopped a Live preset on an empty folder: the preset now loads its folder
  deliberately only once it's known to hold data (cached, in RAM, or listed with TXY files).
- Docks closed by applying a preset still exist (deleteLater) with recorded names when
  `restoreState` runs: their names are cleared first (test added).

## Validation log

- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`: 2530 passed, 2 skipped,
  2 xfailed, no RERUN (before the dock-name fix; final run in the handoff).
- `mypy helab --strict`, `mypy tests --strict`, `pyright helab tests`: clean.
