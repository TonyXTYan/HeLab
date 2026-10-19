# D1 handoff

Branch `agent/dld-d1`, from `e7d0aba` (`agent/dld-f0a`). Not pushed or merged. The
worktree's `venv` is an untracked, ignored symlink to the main checkout's venv. Three commits:
`05e5401` (D1), `679657f` and the third (review fixes).

## Done

- **Arrival-time ("Yavin") model** in `helab/analysis/fits.py`: derived from the physics
  (notes.md), `arrival_time_model(h, g)`, registered as `"arrival_time"`; `FitModel.fixed`
  records the built-in constants in `FitResult.as_record()["fixed"]`.
- **`helab/analysis/profiles.py`** (new): display units (X/Y mm, T ms below a 1 s range else
  s), rate per shot (T kHz per shot, X/Y per mm per shot), Gaussian smoothing as a sparse
  operator (`Smoothing`: σ/5 bins, at most 5 000, reflected edges, total kept), `fit_axis` →
  `AxisFit` (centre, σ, σ_v, T ± SE, curve, notes, record), `fit_smoothed` (smoothed-curve fits
  with the smoothing in the model and sandwich SEs), `constants_text`.
- **"T, X, Y histograms" v4** (`basic_plots.py`): Units, Only events inside all three ranges,
  Smoothing (σ T / σ X,Y), a **Fits** tab (Fit T/X/Y, a model each, Fit to, Constants: fall
  distance and fall time overrides). Fits off by default. Fit curves in black, numbers in each
  axis's title, notes and failures in amber, constants with origins in the header.
- **Record:** `Histograms.record()` (each `AxisFit.as_record` with its `FitResult.as_record`,
  the `ResolvedConstants.as_record`, and `record_lines`) is the result's new
  `AnalysisResult.found`, set by the runner from `DatasetAnalysis.result_found` (default `{}`:
  other plots unchanged). It survives a release; the dock's tooltip shows its `record_lines`
  ("Fit T: …", "Constants: …") through `DatasetAnalysis.result_record`.
- **Hooks:** `AnalysisContext.constants` (lab and folder layers for F0b, empty now),
  `DatasetAnalysis.result_found` / `result_record`.
- Tests: `tests/test_histogram_fits.py` (25 tests), one GUI test in `tests/test_analysis_gui.py`
  (record lines in the dock tooltip). Deliberate updates: `txy_histograms` version 3 → 4 in
  `test_analysis_gui.py` and `test_live_plots.py`; `arrival_time` in `test_fits.py`'s registry.

Not changed: the View-range manual bounds (shared with the 3D scatter via
`selection.range_specs`; they keep s / m with SI prefixes, which already show mm and ms).
No `update()` for the histograms (they redraw, as before); the scatter's in-place update is
untouched and its tests pass.

## Review fixes (second commit)

1. **Smoothed-curve fits** (should-fix 1–3): the smoothing is now in the model (S f(θ) fitted
   to S n), with model-based variances Σ Sᵢⱼ² μⱼ and the sandwich covariance through
   S diag(μ) Sᵀ. The quadrature correction is gone; the parameters, a bimodal R included, are the
   unsmoothed profile's. Over 40 fixed seeds scatter/SE is 0.84 (the raw fit's 0.83); at about
   one count per bin the width's mean pull is −0.36 (tested: 0.7–1.4 and |pull| < 0.5). The
   review suggested fitting the *raw* counts against S f(θ); that would fit the profile narrowed
   by the smoothing (E[n] is f, not S f), so the smoothing goes on the model where the data are
   smoothed (notes.md). A σ_s above a fifth of the range is refused with a note (SEs got
   unreliable beyond). Option renamed "smoothed curve (model smoothed too)"; titles read
   "Gaussian ⊗ smoothing: …"; the drawn curve is the smoothed model on the bins.
2. **Record wired** (4): `AnalysisResult.found`, above.
3. **Fall time** (5): the Fall time tip says the arrival-time model uses h and g only
   (√(2h/g)); a hand-set fall time is X/Y's, and a disagreement is already noted.
4. **Tests** (7): fit curves in rate mode and with Log Y (≤ 0 left out), T in s over a range
   ≥ 1 s, the too-wide smoothing case now asserts the failure, a smoothing near the cloud's
   width still recovers it, the operator's columns sum to 1, `found` survives a release.
5. **Nits** (8): "Fit to" shows while Smooth is on; `ParameterSpec.when` takes a single
   condition, so it can't also wait for a fit to be on (the tip says it applies to every fit).
   The blank lines are removed.

## Second review fixes (third commit)

1. **Gating on honest SEs:** `fit_histogram` takes a `covariance_of` hook; `fit_smoothed` passes
   its sandwich, so the SEs, the "consistent with 0" gating and notes, the undetermined check
   and the extras (bimodal R) all read it. Reviewer's probe: thermal-only condensate gated in
   28/30 seeds (was 4/30; unsmoothed 28/30). Test on 10 fixed seeds.
2. **Cost:** refits start from the last fit only, at most 3 after the first: a smoothed bimodal
   axis 0.65 → 0.25 s (0.29 s at 5 000 bins). Live policy kept (notes.md).
3. **Runner:** a failing `result_found` is logged and gives `found = {}`; the run completes.
   Test in `tests/test_analysis.py`.
4. **`found`** documented as read-only at the top level only.
5. **Smoothed model** applies S only on its own bin centres (count and positions); tested.

## Remaining / not D1

- D4: N0/N, Tc, TF + arrival-time bimodal, TF^{3/2} for slices, the R/σ_th cap as a setting.
- **F0b:** fill `AnalysisContext.constants` when a run starts, and put the layers (or the
  resolved constants) into `AnalysisResult.reuse_key` (R2/R3): they decide the result but are
  not parameters, so today's key would wrongly match a run with other lab/folder values.
- Release time from T₀ − t_f (separate detection, per the roadmap).

## Checks

Third commit: targeted (`test_histogram_fits`, `test_fits`, `test_analysis`,
`test_analysis_gui`, `test_live_plots`, `-n 2 --reruns 5 --reruns-delay 1`): 173 passed, no
reruns. `mypy helab tests --strict`: no issues (153 files); `pyright helab tests` (venv): 0
errors; `git diff --check`: clean.

Second commit:
- Targeted (`test_histogram_fits`, `test_fits`, `test_analysis`, `test_analysis_gui`,
  `test_live_plots`, `-n 2 --reruns 5 --reruns-delay 1`): 170 passed, no reruns.
- `mypy helab tests --strict`: no issues (153 files). `pyright helab tests` (the venv's): 0
  errors. `git diff --check`: clean.
- Full suite not rerun (changes are in `profiles.py`, `basic_plots.py`, `results.py`,
  `runner.py`, `base.py` and their tests, all in the targeted set).

First commit (`05e5401`):
- Full suite (`python -m pytest -n 2 --reruns 5 --reruns-delay 1`, venv's `bin` first on
  `PATH`): `2 failed, 1457 passed, 7 skipped, 2 xfailed, 10 rerun in 220.52s`. The 2 failures
  are the known root-only ones (`test_constants.py::test_read_only_saved_folder_is_replaced`,
  `test_cache_mover.py::test_recovery_isnt_usable_after_a_failed_settings_write`); the 10
  reruns are their own 5 each. No other test needed a rerun.
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
   smoothed curve: titles say "⊗ smoothing", numbers close to the unsmoothed fit's, with
   similar SEs.
6. Constants: set a fall distance; the header says "(this plot)"; hover the dock source for
   the "Fit …" and "Constants: …" lines with "unconfirmed" flags.
7. A failing fit (Bins 2): amber "… fit failed: too few bins …", no crash. Live with fits on:
   reruns keep up.

## Proposed for Tony

See notes.md, "Choices proposed for Tony" (placement, per-mm rates, box off, smoothing
defaults, ms/s rule, smoothed-curve fits, no launch velocity, bimodal p = 2).

## Proposed doc changes (not made)

- **AGENTS.md, Script system:** after the F0a sentence: "The T, X, Y histograms (v4) show X/Y
  in mm and T in ms or s, as counts or a rate per shot, optionally smoothed, and fit each axis
  on its Fits tab (Gaussian, the arrival-time thermal profile on T, bimodal TF² + Gaussian;
  `helab/analysis/profiles.py`) for centre, σ and temperature ± SE; a run's lab and folder
  constants come in `AnalysisContext.constants`, and what a run found (`result_found`) is the
  result's `found`, shown in the dock's record."
- **roadmaps/dld-front-panel-port.md:** mark D1 built; in Decided → Histogram units, "per mm
  per shot" for X/Y if Tony agrees, and "fits of the smoothed curve smooth the model too";
  record the arrival-time model's assumptions (point source, no launch velocity).
