# D8/D10 numerics brief (2026-10-20, Claude, Worker)

From the Coordinator, while Tony was asleep: the pure-numbers parts of D8 and D10 of
[the DLD front panel port](../../../roadmaps/dld-front-panel-port.md), on branch
`agent/dld-d8-d10` from `e7d0aba` (`agent/dld-f0a`: `physics.py`, `fits.py`,
`estimates.py`). New modules and tests only: no plot, UI, Settings, store or
`basic_plots.py` changes (other branches own those).

1. **D8 velocities:** TXY → velocity, z up (gravity −|g| ẑ), from a release time (DLD time),
   the fall distance and g of a `ResolvedConstants`; v_z from the exact trajectory, v_x = x/τ,
   v_y = y/τ, no XY rotation ever; recoil units (He* 1083 nm, ħk/m); vectorised,
   read-only-input safe, nan with a count for τ ≤ 0.
2. **Release-time detection** for one cloud: peak finding in the T histogram (shared with
   Transfer fractions only if a pure refactor), a Gaussian fit of the centre ± SE, then
   t_r = t_arrival − t_f; a typed result with notes (comparable peaks "unsure", too few
   events, fit failure), never an exception; a manual t_r passes through.
3. **D10 shot bootstrap:** resample shots with replacement, a statistic over a list of
   per-shot arrays, seeded, default n_boot (propose), cancellation between resamples,
   percentile and SE, a small-sample note. Reuse `estimates.sewm`.

Acceptance: synthetic velocity tests (z-up sign, τ ≤ 0, recoil units); t_r recovered within
SE, notes on two clouds / empty / too few; bootstrap SE within ~10 % of the analytic SE of a
mean over shots, reproducible with a seed, cancellable; strict mypy, pyright,
`git diff --check` clean; full suite clean but for the two root-only failures. Don't edit
AGENTS.md, roadmaps/, .ai/memory/ or .ai/MANUAL_TODO.md.
