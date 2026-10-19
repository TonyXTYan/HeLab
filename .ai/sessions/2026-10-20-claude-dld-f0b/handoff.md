# F0b handoff

Branch `agent/dld-f0b`, from `e7d0aba` (agent/dld-f0a). Not pushed or merged.
Design and the choices proposed for Tony: [notes.md](notes.md). Brief: [brief.md](brief.md).

## Done

1. **Settings → Lab parameters** (`helab/views/LabParametersTab.py`,
   `helab/utils/lab_parameters.py`): lab-level rows with unit (`UnitSpinBox`), source,
   unconfirmed marker, shown-only marker, Restore default; CODATA read-only; QSettings
   `lab_constants/<key>`; Save / Reset all settings handled; applied to
   `FolderCache.lab_constants` at startup and after Settings.
2. **Folder constants**: store table `folder_constants` (additive), helper-only writes
   (`cache_admin "constants"`, newest `set_at` wins), with listings (entries and the
   folders above), inheritance up to the data root, RAM-only session values;
   right-click › **Folder constants…** (`helab/views/FolderConstantsDialog.py`).
3. **Plot overrides**: `helab/analysis/constant_layers.py` (`constants_specs`,
   `constant_keys`, `plot_overrides`, `resolve_for_run`, `folder_layer`,
   `describe_constants`, `record_text`, `changed_keys`); hooks
   `DatasetAnalysis.constant_keys` / `run_constants`.
4. **Resolved at run start**: `AnalysisContext.constants` (layers, D1's shape) and
   `.resolved_constants`; `AnalysisResult.constant_layers` / `.resolved_constants` /
   `constants_record` (in `reuse_key`, and a Constants line in the record). Live reruns
   and Rerun resolve again; reloads keep the drawn layers.
5. **Open decision 5**: amber "constants changed (…): Rerun to use them" (proposed).

Tests: `tests/test_folder_constants.py` (store, rekey, helpers, listings, clears,
RAM-only, FolderCache, dialog), `tests/test_lab_parameters.py` (tmp ini QSettings, tab,
dialog), `tests/test_constant_layers.py` (helpers, precedence, records, plots in a
window: titles, source line, marking, Rerun, plot override, Live rerun, an analysis with
its own overrides as D1 has). `tests/test_settingsDialog.py`: new tab in the list.
No GUI store access: the GUI only sends `cache_admin` jobs; existing store-access tests pass.

## Remaining

- Release time (manual alternative): no table row yet; for D8 (notes.md).
- A Folder details section for the constants (only the dialog exists).
- Folder constants for a tab's top folder (not a tree row): no menu entry yet (File menu
  like Place .helab-root… would do).
- A Cache-tab row to forget all folders' constants (proposed, if wanted).

## Checks

- `mypy helab --strict`, `mypy tests --strict`, `pyright helab tests` and
  `pyright --pythonplatform Windows helab tests`: clean. `git diff --check`: clean.
- Full suite `-n 2 --reruns 5 --reruns-delay 1`: **2 failed, 1458 passed, 7 skipped,
  2 xfailed, 11 rerun**. Failed: the two known root-only tests. RERUN: those two (5 each)
  and `test_window_resize.py::test_label_keeps_painting_after_resize[repeated]` (once).
  In an earlier targeted run, `test_cache_tab.py::test_saves_restored_from_the_store_ask_with_its_numbers`
  failed 5 reruns once under `-n 2` (it uses the worker's shared store, so it depends on
  what ran before in that worker); it passed alone, in its file pair and in the full suite.

## On-screen checklist for Tony

1. Settings → Lab parameters: rows, units, sources, amber "unconfirmed", CODATA read-only;
   change g, Save, reopen: kept; Restore default; Reset all settings clears it.
2. Right-click a folder › Folder constants…: sources ("this folder", "inherited from …",
   "derived, √(2h/g)", "default · unconfirmed"); Set here + value, Save; a subfolder shows
   "inherited from <folder>"; restart HeLab: values still there.
3. A folder without `.helab-root`: the dialog says "RAM only · kept for this session only".
4. A plot with a Constants group (after D1 adopts it): the choice titles show value and
   source; the source line's "constants: …"; change the lab g → amber "constants changed
   … Rerun to use them"; Rerun clears it; in Live the next shot clears it.
5. A hand-set fall time far from √(2h/g): amber note in the dialog and on the plot.

## How D1 plugs in

D1 (agent/dld-d1, `05e5401`) already reads `context.constants` (`{"lab", "folder"}`)
and resolves itself (`plot_constants`). After the merge it gets the real lab and folder
values with **no change**. To also get the settings titles, the source-line text, the
recorded `resolved_constants` and the "constants changed" marking, either:

- **Minimal**: in `TxyHistograms` override
  `constant_keys(action) -> ("g", "mass", "k_B", "fall_distance", "fall_time")` and
  `run_constants(action, values, layers) -> plot_constants(values, layers)`. Marking,
  source text and the record then work; the "0 = default" overrides stay.
- **Full (recommended)**: replace `FALL_DISTANCE`/`FALL_TIME` with
  `*constants_specs(("fall_distance", "fall_time"), page=<its Fits page>)`, read
  `context.resolved_constants` in `compute` (drop `plot_constants`), and drop the
  constants lines from `result_record` (the record has a Constants line now). Bump its
  version (parameter names change).

## Expected merge conflicts

- **agent/dld-d1**: a trial merge conflicts in two places, both "keep both":
  - `helab/analysis/results.py`, `AnalysisContext`: the `constants` field lines are
    identical (same text); keep F0b's following `resolved_constants` field.
  - `helab/models/ScriptTreeSelector.py`, `_show_content`: keep
    `record = describe(without_constants(specs), …)`, then D1's `result_record` lines,
    then F0b's `resolved_constants` settings lines.
  `helab/scripts/base.py` merged cleanly.
- **agent/dld-d7**: a trial merge (io_helper, cache_store, folder_cache) went through
  with no conflicts; the store change is a new table only.

## Proposed text (not edited: AGENTS.md, roadmaps/, memory)

- **AGENTS.md, Script system** (after the parameters sentence): "Constants come in three
  layers (`helab/analysis/constant_layers.py`): Settings → Lab parameters (QSettings
  `lab_constants/<key>`), folder constants (store `folder_constants`, helper-written,
  newest wins, never cleared by Clear all, purges or a root's Clear; with listings; a
  folder's values apply to its subfolders up to its data root; RAM-only folders keep
  them for the session) and a plot's Constants group (`constants_specs`). A run gets the
  lab and folder layers in `AnalysisContext.constants` and, for an analysis with
  `constant_keys`, `resolved_constants` resolved at submit; results record both. A lab
  or folder change marks open plots "constants changed: Rerun to use them"."
- **AGENTS.md, Caching** (folder flags paragraph): "Folder constants (`folder_constants`,
  right-click › Folder constants…) follow the same rules as the flags."
- **roadmaps/dld-front-panel-port.md**: F0 built (with F0a); Open decision 5 → Decided
  "Open plots are marked when a lab or folder value changes and use it on Rerun or the
  next Live update"; Decided: "A folder's constants apply to its subfolders that don't
  set their own, up to its data root"; Release time row left for D8.
