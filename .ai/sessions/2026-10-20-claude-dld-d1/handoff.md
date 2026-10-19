# D1 handoff

Branch `agent/dld-d1`, from `e7d0aba` (`agent/dld-f0a`). Not pushed or merged. The
worktree's `venv` is an untracked, ignored symlink to the main checkout's venv.

## Done

- **Arrival-time ("Yavin") model** in `helab/analysis/fits.py`: derived from the physics
  (notes.md), `arrival_time_model(h, g)`, registered as `"arrival_time"`; `FitModel.fixed`
  records the built-in constants in `FitResult.as_record()["fixed"]`.
- **`helab/analysis/profiles.py`** (new): display units (X/Y mm, T ms below a 1 s range else
  s), rate per shot (T kHz per shot, X/Y per mm per shot), Gaussian smoothing (σ/5 bins, at
  most 5 000, total kept, propagated errors), `fit_axis` → `AxisFit` (centre, σ, σ_v, T ± SE,
  curve, notes, record), `constants_text`.
- **"T, X, Y histograms" v4** (`basic_plots.py`): Units, Only events inside all three ranges,
  Smoothing (σ T / σ X,Y), a **Fits** tab (Fit T/X/Y, a model each, Fit to, Constants: fall
  distance and fall time overrides). Fits off by default. Fit curves in black, numbers in each
  axis's title, notes and failures in amber, constants with origins in the header. The dock's
  record gets "Fit T: …" and "Constants: …" lines; `Histograms.record()` holds the JSON
  (`AxisFit.as_record`, `FitResult.as_record`, `ResolvedConstants.as_record`).
- **Hooks:** `AnalysisContext.constants` (lab and folder layers for F0b, empty now) and
  `DatasetAnalysis.result_record` (record lines; `ScriptTreeSelector` appends them).
- Tests: `tests/test_histogram_fits.py` (21 tests: arrival profile's area/skew/limit,
  registry and record, T recovery within SE with the arrival model at 1 and 20 µK, Gaussian
  bias at 50 µK vs arrival, Gaussian T recovery on T/X/Y, constants in the conversions,
  bimodal thermal T, units, rate scaling, smoothing area and bins, fits unsmoothed by default
  and the smoothed-curve correction, the box, drawing/titles/record, the F0b layers, empty /
  one-bin / too-few-bins notes, cancellation, the Fits tab); one GUI test in
  `tests/test_analysis_gui.py` (record lines in the dock tooltip).
- Deliberate test updates: `txy_histograms` version 3 → 4 in `test_analysis_gui.py` and
  `test_live_plots.py`; `arrival_time` added to `test_fits.py`'s registry test.

Not changed: the View-range manual bounds (shared with the 3D scatter via
`selection.range_specs`; they keep s / m with SI prefixes, which already show mm and ms).
No `update()` for the histograms (they redraw, as before); the scatter's in-place update is
untouched and its tests pass.

## Remaining / not D1

- D4: N0/N, Tc, TF + arrival-time bimodal, TF^{3/2} for slices, the R/σ_th cap as a setting.
- F0b: fill `AnalysisContext.constants` when a run starts; put the resolved constants into
  the reuse key (R2/R3).
- Release time from T₀ − t_f (separate detection, per the roadmap).

## Checks

- Full suite (`python -m pytest -n 2 --reruns 5 --reruns-delay 1`, venv's `bin` first on
  `PATH`): `2 failed, 1457 passed, 7 skipped, 2 xfailed, 10 rerun in 220.52s`. The 2 failures
  are the known root-only ones (`test_constants.py::test_read_only_saved_folder_is_replaced`,
  `test_cache_mover.py::test_recovery_isnt_usable_after_a_failed_settings_write`); the 10
  reruns are their own 5 each. No other test needed a rerun.

- `mypy helab tests --strict`: no issues (153 files). `pyright helab tests`: 0 errors.
- `git diff --check`: clean.
- Targeted (`test_histogram_fits`, `test_analysis`, `test_analysis_gui`, `test_live_plots`,
  `test_fits`, `test_physics`, `test_plot_settings_panel`, `-n 2 --reruns 5`): 213 passed,
  1 skipped, no reruns (before the Fits-tab test was added; it passed on its own).
- Timing at 300 000 events: 56 ms without fits, 85 ms with three Gaussians, 215 ms with three
  bimodal fits: the default Live policy (every shot) stays.

## On-screen checklist for Tony

1. Load a folder with a thermal cloud; open T, X, Y histograms: unchanged except X/Y in mm
   and T in ms (or s for a range over 1 s).
2. Fits tab: Fit T, X, Y on. Black curves over the bars; each title's second line reads
   centre, σ and T ± SE. Do the temperatures look right for a known cloud?
3. T model → Arrival-time thermal: T should agree with the Gaussian for a cold cloud and be a
   little higher for a hot one; centre is the arrival of v = 0.
4. Units → rate per shot: y labels "Rate (kHz per shot)" / "Rate (per mm per shot)"; fitted
   numbers unchanged.
5. Smooth on: faint bars with a darker curve; widened-bins note in amber for wide ranges. Fit to
   smoothed curve: σ is noted as corrected.
6. Constants: set a fall distance; the header says "(this plot)"; hover the dock source for
   the "Fit …" and "Constants: …" lines with "unconfirmed" flags.
7. A failing fit (Bins 2): amber "… fit failed: too few bins …", no crash. Live with fits on:
   reruns keep up.

## Proposed for Tony

See notes.md, "Choices proposed for Tony" (placement, per-mm rates, box off, smoothing
defaults, ms/s rule, smoothed-width correction, no launch velocity, bimodal p = 2).

## Proposed doc changes (not made)

- **AGENTS.md, Script system:** after the F0a sentence: "The T, X, Y histograms (v4) show X/Y
  in mm and T in ms or s, as counts or a rate per shot, optionally smoothed, and fit each axis
  on its Fits tab (Gaussian, the arrival-time thermal profile on T, bimodal TF² + Gaussian;
  `helab/analysis/profiles.py`) for centre, σ and temperature ± SE; a run's lab and folder
  constants come in `AnalysisContext.constants`, and `DatasetAnalysis.result_record` adds
  lines to the dock's record."
- **roadmaps/dld-front-panel-port.md:** mark D1 built; in Decided → Histogram units, "per mm
  per shot" for X/Y if Tony agrees; record the arrival-time model's assumptions (point source,
  no launch velocity).
