# F0b brief (from the Coordinator)

Worker task on `agent/dld-f0b`, from `agent/dld-f0a` at `e7d0aba` (which added
`helab/analysis/physics.py`: the constants table, `resolve(lab, folder, plot)` →
`ResolvedConstants` with origins and `as_record`).

F0b: constants at three levels, resolved when a run starts
(roadmaps/dld-front-panel-port.md, Decided: "Constants at three levels", "Defaults borrowed").

1. **Lab parameters**: a Settings tab listing physics.py's lab-level rows; each editable
   value with its unit, source, an "unconfirmed" marker and Restore default; stored in
   QSettings; CODATA values read-only.
2. **Folder settings**: per folder, keyed by data root like the folder flags (`folder_prefs`),
   only in HeLab's store, written only by helpers under the existing rules, coming with
   listings; RAM-only folders keep them for the session and say so. Additive store change
   only (agent/dld-d7 adds `datasets.raw_times`). Decide inheritance (proposed: nearest folder
   at or above). Right-click › Folder constants… dialog with each value's effective source.
3. **Plot overrides**: a reusable "Constants" parameter group (helpers in helab/analysis)
   that D1 adopts; each value can be overridden; the plot shows each value's source. Don't
   edit basic_plots.py; add a demo/test usage.
4. **Resolved at run start**: the run's AnalysisContext gets the ResolvedConstants resolved on
   the GUI thread; recorded in the result; Live reruns resolve again.
5. **Open decision 5**: open plots are marked "constants changed: Rerun to use them" when a
   lab or folder value changes, and use the new values on Rerun or the next Live update.

Handoff in this folder: notes.md (design, store change, proposals), handoff.md.
