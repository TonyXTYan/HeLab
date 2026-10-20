# D12/D13 Correlations plot: notes

Code: `helab/scripts/standard/correlations_plot.py` (registered last in `standard.MODULES`);
tests: `tests/test_correlations_plot.py` (14), plus the shared lists in `tests/test_plot_text.py`,
`tests/test_live_plots.py` (coverage, empty reasons, a Live-follow test) and
`tests/test_display_units.py`. Numerics are `helab/analysis/correlations.py` unchanged.

## Recovery

The interrupted worker left the plot, its tests and the registration uncommitted; committed as
WIP (3ffe2a3) first. Three tests failed then:
- The v₀ settings were named `bb_z`/`bb_x`/`bb_y` (from `name[2:]` of `v_z`); the tests and the
  settings line used `bb_vz`…: renamed to `bb_vz`, `bb_vx`, `bb_vy`.
- `json.dumps(result.found)`: `found` is a mappingproxy in `AnalysisResult`; the test now dumps
  `dict(result.found)` (the values were JSON already).
- The BB test expected an "assumed" origin with only t_r set, but the plot (as briefed) detects the
  origin in the run then. The test now checks the detected origin (unsure on a halo, warned; the
  peak still at 0 within 3 SE) and gets "assumed" from a failed detection, with the trap above
  Y = 0 so the 0.5 mm/s window on v_y keeps the pairs (with y₀ = −0.4 mm the v_y sums are off by
  −1.9 mm/s, outside the window: no peak at all). The moving-source case moved the source by
  20 mm/s, which put the peak at 40 mm/s, outside the ±5 mm/s range: now 1.5 mm/s (peak at 3).

## Design (what the plot does)

- Events: chosen shots → mask (D9) → own view range in TXY (auto-crop kept from this plot's
  previous box while the new one fits well inside it: `steady_box`, `trends.KEEP_SLACK`, so Live's
  shots don't restart the count) → velocities (`txy_to_velocity`) with this run's constants.
- t_r: `layer_release_time` (by hand, or saved arrival − this run's t_f), else one
  `detect_release_time` on the chosen masked events in Release search T (within-run SE, noted).
  Origin: `layer_origin`, else that detection's, else assumed (0, 0) in amber. The detection runs
  whenever t_r or the origin is unset (cheap: one histogram fit, no bootstrap).
- **Proposed, for Tony: a detection within its SE of the plot's previous one is kept** ("detected,
  kept"), so Live's held pair counts stay valid; otherwise every new shot would nudge t_r and
  restart the count. Keyed by the constants, the search range and the mask.
- Spec `events_key` (JSON): t_r, effective h, g, the origin, the mask's circles, the view-range
  box. Units are not in it: **settings are in mm/s whatever the drawing unit** (proposed, for
  Tony), so switching mm/s ↔ ħk ↔ 2ħk only redraws (tested: identical counts).
- Live: one `_PlotState` per plot owner (module-level dict, lock), holding the folder, the
  `PairCounts`, the in-shot cache (kept across spec changes, filtered by `spec.key()`), the box and
  the detection. `plot_closed` drops it and remembers the owner (up to 4096) so a late run of a
  closed plot keeps nothing. Another folder starts anew.
- Live policy `min_delay=5 s` (proposed, for Tony). Live reruns (`context.live`) skip the shot
  bootstrap (`LIVE_NOTE`, `reuse.bootstrap_skipped`): the bars are then pair counting's (too small)
  and g²(0)'s error the jackknife refits'. Deliberate runs and the catch-up when Live stops keep it.
- Defaults (proposed, for Tony): 1D v_z, range ±20 mm/s, 40 bins, window ±2 mm/s, free baseline,
  200 resamples, time budget 30 s, all-shots reference (K = 10 when banded).
- Drawing: g² ± SE points, the fitted curve (point model) and its baseline (dashed), a dotted 1,
  and below the in-shot pairs per bin beside the between-shot pairs scaled by P_in/P_between.
  Title lines (WrapLabel): input · shots · events · kind; g²(0) over baseline · σ in the plot's
  unit (or "no peak: g² near 0 is …"); t_r (where from) · origin; pair counts · held/counted ·
  seconds; then warnings and notes in amber.

## Open / proposed, for Tony

1. Per-bin errors on a Live rerun are pair counting's (underestimates). The numerics already have
   the exact jackknife per bin (`jackknife_se`) for free; using it as `se` when there is no
   bootstrap would be more honest (a change in `correlations.py`, outside this task).
2. `correlations._near_zero` raises a RuntimeWarning ("invalid value encountered in divide",
   line ~878) on a budget-stopped run with few shots (bootstrap rows all nan); harmless (nan
   results), worth an `np.errstate` in the numerics.
3. D13's per-shot halo centring isn't built: "Re-centre each shot" stands in (each shot's robust
   centre to 0; BB's v₀ then relative to it).
4. Radial/BB on real halos: the origin detection on a halo is "unsure" (no cloud at rest); set the
   origin for the folder from a BEC run (Release time plot → Use for this folder…).
