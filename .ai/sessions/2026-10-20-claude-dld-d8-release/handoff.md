# D8 part 1 handoff: release time and trap origin

Branch `agent/dld-d8-release`, from `52386ec`, with the integration head `7fa394f` (D4/D14, D9/D15)
merged in. Not pushed or merged. Design and the choices proposed for Tony: [notes.md](notes.md)
(the review fixes at the end). Brief: [brief.md](brief.md).

## Done

- `helab/analysis/physics.py`: optional rows (`Constant.optional`, `signed`; validity is
  `Constant.allows`, merged with D4's maximum and codes; `physics.OPTIONAL`). New folder rows
  `release_time` and `arrival_time` (s, positive) and `trap_x`, `trap_y` (m, signed). Unset → nan
  with origin "detected" (`ResolvedConstants.is_set`); records with None, older records read;
  nan-safe `__eq__`/`__hash__`; `as_record(keys)`.
- `helab/analysis/constant_layers.py`: `limits(key)` (signed, optional times from 0, the row's
  maximum), `FROM_THE_DATA`, `value_and_origin`, nan-safe `changed_keys`, symbols t_r, t_a, x₀, y₀.
- `helab/analysis/release.py` (additive): drawing fields on `ReleaseTime` (`fit_window`,
  `origin_half`, `origin_window`), `layer_release_time` (t_r by hand, or a saved arrival − the
  consumer's t_f), `layer_origin`.
- `helab/analysis/results.py`, `runner.py`, `models/ScriptTreeSelector.py`: `AnalysisContext.live`
  (a rerun following Live); `constants_record` limited to the analysis's constant keys.
- `helab/scripts/standard/release_time.py`: the **Release time** plot with **Use for this
  folder…** (saves `arrival_time` and the origin); registered in `standard.MODULES`.
- Views: `FolderConstantsDialog` (from the data source; Save waits while a row set here has no
  value), `LabParametersTab.constant_editor` (`limits`), plot settings' constant titles.
- Tests: `tests/test_release_time_plot.py` (15), a Live-rerun test in `test_live_plots.py`, the
  shared lists, `test_physics.py`'s table set, `test_constant_layers.py`'s record (own keys only).

## How D8 part 2 (velocity axes) and D12/D13 should read them

1. Declare the keys: `constants_specs(("fall_distance", "fall_time", "g", "release_time",
   "arrival_time", "trap_x", "trap_y"))` (or `constant_keys` + `run_constants`), so a plot can set
   t_r or the origin for itself and is marked when "Use for this folder" changes them. A plot's own
   t_r or t_a of 0 counts as not set (the layers' is used).
2. In `compute`, from `context.resolved_constants`:
   ```python
   given = release.layer_release_time(constants)   # t_r by hand, or saved t_a − this run's t_f; None: unset
   found = given or release.bootstrap_release_time(per_shot_txy, constants, lower, upper,
                                                   cancelled=context.cancelled)
   origin, how = release.velocity_origin(found, manual=release.layer_origin(constants))
   velocities = velocity.txy_to_velocity(events, found.value.value, constants, origin=origin)
   ```
   **Never store or reuse another plot's t_r**: the folder holds the arrival, and t_r = t_a − t_f
   comes from *this* run's fall time, so the cloud at rest is at v_z = 0 whatever h, g or t_f the
   plot uses. Record where each came from: `constants.origins["arrival_time"]` /
   `["release_time"]` ("folder", "plot", …) or "detected" (with `found.error`), and the origin's
   `how` ("manual" from a layer, "detected", "detected (unsure)", "assumed"); say "assumed (0, 0)"
   beside the velocities in amber. `found.notes` says when t_r came from the saved arrival.
3. A layer that sets only one of `trap_x`/`trap_y` is no origin (`layer_origin` → None).
4. Detecting costs a bootstrap (seconds; notes.md): prefer the folder's values; when unset, on
   `context.live` reruns use `detect_release_time` (one detection, SE "within run", said so), as the
   Release time plot does.
5. D12/D13 (correlations, halos) use the same velocities; they need nothing else.

## For Tony (proposed)

1. Unset optional rows resolve with origin "detected", shown "from the data".
2. Plot bootstrap default 100 resamples; Live reruns skip it (fit SE, said so), deliberate runs and
   the catch-up when Live stops keep it; Live `min_delay` 5 s.
3. "Use for this folder" saves the arrival t_a (not t_r) and the origin to the plotted folder,
   merged with what it sets and dropping its t_r by hand; Cancel is the default when the detection
   is unsure or this run's fall time isn't the folder's. When both a t_r by hand and a t_a are set,
   the more specific layer wins, t_r by hand on a tie.
4. Release and arrival times are positive; 0 in an editor means "no value yet" and Save waits.

## On-screen checklist for Tony

1. Open the Release time plot on a BEC folder: the three panels, the title line in ms/mm, notes in
   amber. Turn Live on: reruns say "(within run)" and "Live rerun: shot bootstrap skipped"; Live off:
   one more run with the bootstrap.
2. Use for this folder…: the question lists t_a and the origin with "now", and the t_r the folder's
   plots will get; change the plot's own h first: the warning and Cancel as the default. Save:
   "Set for this folder"; Folder constants… shows them as "this folder".
3. Folder constants…: Set here on Release time with nothing above: Save is greyed with a note until a
   value is typed; trap origin editors take negative mm.

## Checks

- `mypy --strict helab tests` (196 files), `pyright helab tests`: clean. `git diff --check`: clean.
- Targeted tests after the merge (live plots, release time, constants, physics, folder constants,
  lab parameters, velocity, plot text, analysis, display units, script system, bec, fits) `-n 2
  --reruns 5`: 372 passed, no reruns.
- Full suite `-n 2 --reruns 5 --reruns-delay 1 -rR` after the merge: **2 failed, 1966 passed, 7
  skipped, 2 xfailed, 11 rerun in 209 s**: the two known root-only failures (5 reruns each) and one
  rerun of `test_window_resize.py::test_label_keeps_painting_after_resize[repeated]`, which passed.
