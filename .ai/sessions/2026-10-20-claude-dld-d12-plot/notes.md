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
  bootstrap (`LIVE_NOTE`, `reuse.bootstrap_skipped`): the bars and fit weights are then the
  delete-one-shot jackknife's (`correlate(..., errors="jackknife")`, new in the numerics; the
  default stays "counting"), pair counting only when the shot-pair matrix was dropped
  (`LIVE_COUNTING_NOTE`). Deliberate runs and the catch-up when Live stops keep the bootstrap.
- t_r and origin: `release.run_velocity_source(constants, detect)` (added at the merge of dbc79bf)
  is the one rule the Velocity distributions and Correlations plots share; each passes its own
  `detect()` (Correlations: the steady detection; Velocity distributions: its kept one on Live).
- Back-to-back with a detected t_r: `BB_DETECTED_NOTE` (the tallest T peak may be a Bragg-kicked
  cloud, v_z off by its velocity; set t_r from a rest-cloud run, or re-centre), not shown when
  shots are re-centred (proposed, for Tony).
- Defaults (proposed, for Tony; per Pairs mode since the review): collinear 1D v_z, ±3 mm/s,
  60 bins, window ±0.3 mm/s (a thermal cloud's σ_c ≈ ħ/(2mσ₀) is ~0.55 mm/s radially, 0.055 mm/s
  axially at 1 µK; the XY resolution ~0.24 mm/s; ±2 mm/s kept only ~0.31 of the bump per windowed
  axis); back-to-back ±20 mm/s, 40 bins, ±2 mm/s (`bb_range`, `bb_bins`, `bb_window`). Free
  baseline, 200 resamples, time budget 30 s, all-shots reference (K = 10 when banded). The window
  shows for 1D only: a local `_ModeSpec` (ParameterSpec with a second condition).
- Drawing: g² ± SE points, the fitted curve (point model) and its baseline (dashed), a dotted 1,
  and below the in-shot pairs per bin beside the between-shot pairs scaled by P_in/P_between.
  Title lines (WrapLabel): input · shots · events · kind; g²(0) over baseline · σ in the plot's
  unit (or "no peak: g² near 0 is …"); t_r (where from) · origin; pair counts · held/counted ·
  seconds; then warnings and notes in amber.

## Numerics changes (review round)

- g²(0)'s refits (bootstrap replicates, delete-one curves) start from the fit's parameters
  (`_warm`) with at most `REFIT_EVALUATIONS` = 1000 evaluations: with the narrower collinear
  defaults, sparse noisy curves took ~600 evaluations per refit from scratch, ~100 s a run; now
  ~4 s. test_correlations (35) still passes, calibration tests included.
- `_near_zero`'s divide warning is silenced (a replicate with none of the bins: nan, dropped).

## Open / proposed, for Tony

1. The per-mode defaults and the scales in the tooltips.
2. The BB detected-t_r note is skipped when shots are re-centred.
3. D13's per-shot halo centring isn't built: "Re-centre each shot" stands in (each shot's robust
   centre to 0; BB's v₀ then relative to it).
4. Radial/BB on real halos: the origin detection on a halo is "unsure" (no cloud at rest); set the
   origin for the folder from a BEC run (Release time plot → Use for this folder…).
