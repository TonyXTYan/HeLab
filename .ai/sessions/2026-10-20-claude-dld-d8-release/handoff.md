# D8 part 1 handoff: release time and trap origin

Branch `agent/dld-d8-release`, from `52386ec`. Not pushed or merged. Design and the choices
proposed for Tony: [notes.md](notes.md). Brief: [brief.md](brief.md).

## Done

- `helab/analysis/physics.py`: optional rows (`Constant.optional`, `signed`, `accepts`;
  `physics.OPTIONAL`), new folder rows `release_time`, `trap_x`, `trap_y`; unset → nan with origin
  "detected" (`ResolvedConstants.is_set`); records with None, older records read; nan-safe
  `__eq__`/`__hash__`.
- `helab/analysis/constant_layers.py`: signed limits, `FROM_THE_DATA`, `value_and_origin`, nan-safe
  `changed_keys`, `clean_layer` by `Constant.accepts`, symbols t_r, x₀, y₀.
- `helab/analysis/release.py` (additive): drawing fields on `ReleaseTime` (`fit_window`,
  `origin_half`, `origin_window`), `layer_release_time`, `layer_origin`.
- `helab/scripts/standard/release_time.py`: the **Release time** plot with **Use for this
  folder…**; registered in `standard.MODULES`.
- Views (minimal): `FolderConstantsDialog` (from the data source, nan-safe editors, signed
  bounds via `constant_editor`), `LabParametersTab.constant_editor` (signed bounds),
  `ScriptTreeSelector` (constant titles via `value_and_origin`).
- Tests: `tests/test_release_time_plot.py` (11); shared lists in `test_analysis.py`,
  `test_live_plots.py`, `test_plot_text.py`, `test_display_units.py`; `test_physics.py`'s table set.

## How D8 part 2 (velocity axes) and D12/D13 should read them

1. Declare the keys: `constants_specs(("fall_distance", "fall_time", "g", "release_time", "trap_x",
   "trap_y"))` (or `constant_keys` + `run_constants`), so a plot can also set t_r or the origin for
   itself, and is marked when "Use for this folder" changes them.
2. In `compute`, from `context.resolved_constants`:
   ```python
   given = release.layer_release_time(constants)          # None: no layer sets t_r
   found = given or release.bootstrap_release_time(per_shot_txy, constants, lower, upper,
                                                   cancelled=context.cancelled)
   origin, how = release.velocity_origin(found, manual=release.layer_origin(constants))
   velocities = velocity.txy_to_velocity(events, found.value.value, constants, origin=origin)
   ```
   Record where each came from: t_r `constants.origins["release_time"]` ("folder", "plot", …) or
   "detected" (and `found.error`); the origin's `how` ("manual" from a layer, "detected",
   "detected (unsure)" or "assumed"). Say "assumed (0, 0)" beside the velocities in amber.
3. A layer that sets only one of `trap_x`/`trap_y` is no origin (`layer_origin` → None): the
   detected or assumed one is used. Show `value_and_origin(constants, key)` in titles ("from the
   data" when unset).
4. A detection there costs a bootstrap (seconds; notes.md): prefer the folder's values, and when
   unset consider `detect_release_time` without the bootstrap for a quick preview, saying the SE is
   within run.
5. D12/D13 (correlations, halos) use the same velocities; they need nothing else.

## Expected merge conflicts

- **D4/D14** (`physics.py` new rows, `LabParametersTab`): both append rows to `CONSTANTS` and fields
  to `ResolvedConstants` (keep both, any order: the assert checks the field set matches `TABLE`),
  and maybe `SYMBOLS` in `constant_layers.py` and `test_physics.py`'s folder-row set. In
  `LabParametersTab.constant_editor` keep `bounds=list(limits(constant.key))`. If D4 adds a row that
  can be zero or negative, give it `signed=True`.
- **D9/D15**: no shared file except the shared test lists (add both plots).

## For Tony (proposed)

1. Unset optional rows resolve with origin "detected", shown "from the data".
2. Plot bootstrap default 100 resamples (measured costs in notes.md), Live `min_delay` 5 s.
3. "Use for this folder" writes to the plotted folder, merged with what it sets, Cancel default
   when unsure; the plot always detects and doesn't draw the folder's value.
4. Folder dialog editors of unset rows start at 0.

## On-screen checklist for Tony

1. Open the Release time plot on a BEC folder: the three panels, the title line in ms/mm,
   notes in amber; zoom keeps on a Live rerun (5 s apart).
2. Use for this folder…: the question lists values and "now"; Cancel writes nothing; Save shows
   "Set for this folder"; right-click › Folder constants… shows them as "this folder".
3. Folder constants… on another folder: Release time "from the data (Release time plot)", trap
   origin editors accept negative mm.

## Checks

- `mypy helab --strict`, `mypy tests --strict`, `pyright helab tests`: clean. `git diff --check`: clean.
- New tests: 11 passed, no reruns. `tests/test_script_system.py`'s bundled-plot list gained the plot
  (it failed in the first full run, before that).
- Full suite (`-n 2 --reruns 5 --reruns-delay 1 -rR`): **2 failed, 1861 passed, 7 skipped,
  2 xfailed, 14 rerun in 278 s**. Failed (5 reruns each): only the two known root-only tests.
  Other reruns, which then passed: `test_dash_server.py::test_stop_frees_the_port` (3) and
  `test_window_resize.py::test_label_keeps_painting_after_resize[repeated]` (1), neither touched here.
