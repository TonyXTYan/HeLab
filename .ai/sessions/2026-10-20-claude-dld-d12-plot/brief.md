# D12/D13 Correlations plot: brief (from the Coordinator)

Worker on branch `agent/dld-d12-plot` (base `7ff350b`). A previous worker was interrupted by a
container restart; its uncommitted work (the plot, its tests, the registration) was recovered and
committed as WIP, then finished.

A "Correlations" plot (D12 g², D13 back-to-back) using `helab/analysis/correlations.py`; read
`.ai/sessions/2026-10-20-claude-dld-d12-numerics/handoff.md` + `notes.md` and
`.ai/sessions/2026-10-20-claude-dld-d8-release/handoff.md` (derive t_r = arrival − t_f from the
plot's own constants via `release.layer_release_time`; origin via `layer_origin`, else detected
cheaply in the run, else assumed with a note; never reuse another plot's t_r).

1. Modes: 1D windowed g²(Δv along an axis), radial g²(|Δv|), back-to-back g²(v1+v2) about the
   origin (optional per-shot re-centring, noted).
2. Inputs: shared Shots, own View range in TXY, Mask group (`helab/analysis/masks.py`), velocities
   via `velocity.py` with the run's constants, units mm/s or recoil (`velocity.RECOIL_WAVELENGTH`).
3. Settings: bins/range, window half-widths, banded partners, n_boot, time budget; Live: per-shot
   reuse via one `PairCounts` per plot (dropped in `plot_closed`), cache key including release
   time, origin, mask, view range, units; cancellation; Live policy appropriate to cost (and
   `AnalysisContext.live` to skip the costly bootstrap on Live reruns, as the Release time plot does).
4. Plot g² ± SE, the 1 + Gaussian fit with baseline b, g²(0) = (b + A)/b ± SE or "no peak: g² near
   0 is X ± Y", notes (baseline ≠ 1, slope, rough SE, budget hit), pair counts; records in found;
   wrapped titles (plot_text), AMBER; ms/mm conventions.

Acceptance: simulated thermal source → g²(0) ≈ 2 within SE; uncorrelated → near-zero ≈ 1, no peak;
back-to-back pairs → peak at 0 with the origin; Live adds a shot without recounting old ones; cache
invalidated on release-time/mask change; budget note; cancellation; plot_closed drops state;
registration in shared tests. mypy --strict, pyright, git diff --check clean; full suite clean but
the two root-only failures.

Others in parallel: D4 wiring (basic_plots.py), D8 part 2 velocity plot. Keep to the new plot file,
its registration and the shared test lists.
