# D1 brief (Coordinator, 2026-10-20)

Worker task on branch `agent/dld-d1`, from `e7d0aba` (`agent/dld-f0a`: `physics.py`,
`fits.py`, `estimates.py`). Tony asleep; work autonomously and record choices as proposed.

**D1: fits on the T/X/Y histograms** ([roadmap](../../../roadmaps/dld-front-panel-port.md),
Decided section authoritative), as an option on "T, X, Y histograms", off by default:

1. Histogram units: counts or rate per shot (front panel's method, bug fixed): box/T window
   first; T counts / bin width / shots in kHz per shot; X and Y per mm per shot. Optional
   Gaussian smoothing (σ, bins σ/5); fits on unsmoothed counts unless chosen.
2. Axis units: X, Y in mm; T in ms or s from its range. Check whether the View-range bounds
   are shared before changing them.
3. Fits per axis with a model choice: Gaussian + offset, the exact arrival-time ("Yavin")
   profile on T (derived, registered in `fits.py`, tested), bimodal TF + Gaussian if time
   allows (D4's outputs are not D1's).
4. Temperatures from F0a with a `ResolvedConstants`; per-plot overrides of fall distance and
   fall time only ("Constants" group); constants recorded with origins and unconfirmed flags;
   a hook for F0b's lab and folder levels.
5. Display: fit curves, centre / σ / T ± SE, amber notes, never a crash; compute-side fits
   with cancellation; sensible Live policy.
6. `FitResult.as_record` in the result's record.

Acceptance: synthetic recovery of T within SE (Gaussian on each axis, arrival time on T),
rates and units, smoothing keeps area and fits stay unsmoothed by default, empty / single-bin /
failed fits noted, constants recorded, update-in-place intact, existing tests pass (updated
deliberately), mypy/pyright/`git diff --check` clean. No edits to AGENTS.md, roadmaps/,
.ai/memory/, .ai/MANUAL_TODO.md.
