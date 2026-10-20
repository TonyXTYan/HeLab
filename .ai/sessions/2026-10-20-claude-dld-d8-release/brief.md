# D8 part 1 brief: release time and trap origin

Worker brief from the DLD Coordinator, 2026-10-20. Branch `agent/dld-d8-release` from `52386ec`
(agent/dld-front-panel-port with the merged DLD work).

1. `physics.py`: a folder-level `release_time` row (s, no fixed default: "from the data") and
   `trap_x`, `trap_y` origin rows (folder level, mm, unset → detected or assumed 0); design how a
   row without a default resolves, record the origin as "detected" vs folder/plot, and keep
   `resolve()`, records, `clean_layer` and the editors (Lab parameters tab, Folder constants
   dialog) working.
2. A new "Release time" plot (group "Basic plots v1"): `release.detect_release_time` (arrival-time
   model first) with `bootstrap_release_time` for the honest error (n_boot proposed ~200,
   cancellable); the T histogram near the arrival with the fitted model and the arrival/release
   markers (ms, grouped ticks), the XY image or X/Y histograms around the origin with the robust
   window, and the text line (release ± SE, arrival, t_f with h, origin ± SE, background), notes.
   "Use for this folder" writes release_time and trap_x/trap_y through
   `FolderCache.set_folder_constants` (GUI thread, explicit user action, confirmation); never
   automatically.
3. Records: `found` with the full release record; `constant_keys` for h, g, t_f; a Live policy
   with a few seconds' `min_delay`; wrapped titles, AMBER.

Others at work: D4/D14 (fits, bec, physics rows, profiles, LabParametersTab), D9/D15 (selection
masks, density images). So: a new plot file, rows appended to `physics.py`, registration; no
existing plot touched.

Acceptance: synthetic single cloud recovers t_r and the origin within SE; the bootstrap error
reflects shot jitter; "Use for this folder" writes only on confirmation (mock FolderCache);
optional rows resolve as detected when unset; editors show unset rows; registration in the shared
tests; ms/mm formatting; mypy --strict, pyright, `git diff --check` clean; full suite clean but the
two root-only failures.
