# D12/D13 Correlations plot: handoff

Branch `agent/dld-d12-plot`, from `7ff350b`. Not pushed or merged. Design, the recovery and the
choices proposed for Tony: [notes.md](notes.md). Brief: [brief.md](brief.md).

## Done

- `helab/scripts/standard/correlations_plot.py`: the **Correlations** plot (`helab.correlations` v1),
  registered last in `standard.MODULES`. Pages: g² (Type 1D/radial, Pairs collinear/back-to-back,
  Axis, Range, Bins, Window, Radial bins equal width/volume, BB source v₀ 0 or set here,
  Re-centre each shot; Reference and fit: all/neighbouring shots, K, baseline free/fixed, bootstrap
  resamples, time budget) and Velocity (Plot in mm/s / ħk / 2ħk, Release search T, the constants
  h, t_f, g, t_r, t_a, x₀, y₀), plus the shared Shots, View range and Mask.
- t_r from the layers (`layer_release_time`), else detected in the run; origin from the layers,
  else detected, else assumed (0, 0) in amber. Never another plot's t_r.
- Live: one `PairCounts` + in-shot cache per plot (`_PlotState`), `events_key` with t_r, h, g, the
  origin, the mask and the view box; `plot_closed` drops it; Live reruns skip the bootstrap
  (`LIVE_NOTE`); policy `min_delay` 5 s; time budget and cancellation continue from the held state.
- Records in `found`: `correlation` (`CorrelationResult.as_record`), `velocity`, `brief`,
  `record_lines`, `constants`, `reuse` (t_r, origin, view range, shots used, bootstrap skipped).
- Tests: `tests/test_correlations_plot.py` (14: thermal g²(0) ≈ 1.996 within 3 SE; uncorrelated no
  peak / g² ≈ 1; BB peak at 0 with the origin, detected, assumed, moving source, v₀, re-centring;
  t_r detection kept within SE; Live adds one shot; release time / mask / origin / view range
  restart the count; budget note and continuation; cancellation; plot_closed; drawing;
  settings line and registration). Shared lists: `test_plot_text.py` (560 px dock),
  `test_live_plots.py` (coverage, empty reasons, a Live-follow test), `test_display_units.py`.

## Review round

Coordinator's review of f75c009, fixed in the merge of dbc79bf (21820a7): Live bars from the
jackknife; per-mode defaults (collinear ±3 mm/s, 60 bins, ±0.3 mm/s; back-to-back ±20 mm/s, 40
bins, ±2 mm/s) with σ_c and resolution in the tooltips; the BB detected-t_r note; mask the BECs
before re-centring halos. Shared `release.run_velocity_source` for both velocity plots. Refits warm
started (~100 s → ~4 s on sparse data). Then the integration head e14843f merged cleanly.

## On-screen checklist for Tony

1. Open Correlations on a BEC folder with the folder's t_a and origin set (Release time plot →
   Use for this folder…): the title's lines (kind; g²(0) over baseline · σ in mm/s; t_r (folder) ·
   origin (manual); pair counts), the g² points with bars, the red fit and dashed baseline, the
   pairs panel below. Fits a 560 px dock.
2. Without the folder's values: "t_r detected in this run" note; on a halo, the amber
   "origin's detection is unsure".
3. Plot in ħk: same counts, axes rescaled, the "unconfirmed" note.
4. Live on: reruns at most every 5 s, "N shots held, 1 counted", the Live-rerun note (jackknife bars);
   Live off: one rerun with the bootstrap.
5. A small time budget (e.g. 1 s) on a large folder: "stopped at the time budget…" and Rerun
   continuing the count.

## Real-data checks (proposed)

- A thermal cloud just above T_c: radial g²(0) near 2 (less with detector resolution and window);
  a BEC: ≈ 1. Compare σ with the expected correlation length ħ/(m·σ_x).
- A halo run: back-to-back 1D along each axis with re-centring; the peak at 0 and its width.
- Speed on a few hundred shots: consider "neighbouring shots" if all-pairs is slow.

## Checks

- `mypy --strict helab tests` (198 files) and `pyright helab tests`: clean. `git diff --check`: clean.
- Targeted: `tests/test_correlations_plot.py` 14 passed; the shared cases 6 passed; the Live test
  passed (`-n 1 --reruns 5 --reruns-delay 1`).
- Review round (merges of dbc79bf and e14843f, the fixes above): full suite **2 failed, 2018
  passed, 7 skipped, 2 xfailed, 10 rerun in 420 s**: only the two known root-only failures (5
  reruns each).
- First round: full suite `-n 2 --reruns 5 --reruns-delay 1 -rR`: **2 failed, 1986 passed, 7 skipped, 2 xfailed,
  11 rerun in 511 s**: the two known root-only failures (5 reruns each) and one rerun of
  `test_folder_summary.py::test_disk_cache_summary_tracks_shared_save_completion[cache_saved]`,
  which passed. (The first full run also caught the registry lists in `test_analysis.py` and
  `test_script_system.py`, now updated.)
