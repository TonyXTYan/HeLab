# D1 notes: fits on the T/X/Y histograms

## What was built

- `helab/analysis/fits.py`: the arrival-time thermal model (`arrival_time`,
  `arrival_time_model(h, g)`, registered as `"arrival_time"` with the default constants) and
  `FitModel.fixed` (constants built into a model, recorded as `"fixed"` in
  `FitResult.as_record()`).
- `helab/analysis/profiles.py` (new, no Qt): display units, rate factor, smoothing (kernel,
  area-keeping convolution, propagated errors, σ/5 bins with a cap), `fit_axis` → `AxisFit`
  (centre, width, σ_v, T ± SE, curve, notes, `as_record`), `constants_text`.
- `helab/scripts/standard/basic_plots.py`: "T, X, Y histograms" v4 with Units, "Only events
  inside all three ranges", Smoothing, and a **Fits** settings tab (Fit T/X/Y with a model
  each, Fit to, Constants: fall distance and fall time overrides).
- Hooks: `AnalysisContext.constants` (lab and folder layers, empty until F0b) and
  `DatasetAnalysis.result_record` (lines a run adds to the dock's record; ScriptTreeSelector
  appends them after the parameters).

## Derivation: the arrival-time ("Yavin") profile

z up, detector a distance h below the trap (z = 0 at the detector), release at t = 0:

    z(t) = h + v t − ½ g t²   →   arrival at  t(v) = (v + √(v² + 2gh)) / g,
    inversely                       v(t) = g t / 2 − h / t,   dv/dt = g/2 + h/t² > 0.

v(t) is monotonic over t > 0 (−∞ → +∞), so each arrival time has one velocity. The
detector counts atoms crossing z = 0, so with Maxwell–Boltzmann p(v) ∝ exp(−v²/2σ_v²),
σ_v² = k_B T/m:

    p(t) = p(v(t)) · |dv/dt|.

The Jacobian is the difference from a Gaussian: early (fast-downward) atoms are bunched, late
ones stretched, a longer late tail. At v = 0, t = t_f = √(2h/g) and dv/dt = g. In DLD time T,
t = T − T₀ + t_f (T₀: arrival of v = 0). Fitted as

    A · (g/2 + h/t²)/g · exp(−v(t)²/2(g s)²) + offset   (t > 0; else the offset),

with s = σ_v/g, so the parameters and roles are the Gaussian's (amplitude, centre, σ, offset),
T = m (g s)²/k_B the same conversion, and the area A s √(2π) (∫p(v)dv/g) the same. For
s ≪ t_f it is the Gaussian of width s (tested).

Assumptions (in the code comment): point source (σ_z0 adds ≈ σ_z0/(g t_f): 2.5 µs for 10 µm,
vs ~5 ms at 1 µK); no mean vertical velocity (a launch velocity v₀ moves T₀ by ≈ v₀/g and is
indistinguishable from it, so T₀ absorbs it; it is *not* the release time unless v₀ = 0); every
atom reaches the detector (a hot cloud wider than the plate loses fast transverse atoms: that
shows up in X/Y, and evenly in T only if the clipping doesn't correlate with v_z, which it
doesn't for independent Maxwell–Boltzmann axes); h and g are the run's constants.

Checked: on 25 synthetic seeds at 1 µK and 20 µK the arrival fit's T pulls have mean |·| < 0.5
and ≥ 80 % within 2 SE; at 50 µK the Gaussian's T is biased low (mean pull ≈ −1.3 at 20 000
events) and the arrival profile's isn't (≈ +0.1). At 20 µK the Gaussian is −0.6 SE low.

## Temperatures

From F0a, unchanged: σ_v = g σ (T axis; for the arrival model σ is s = σ_v/g exactly), σ_v =
σ / t_f (X/Y), T = m σ_v²/k_B, SE(T) = 2 T SE(σ)/σ. Ideal gas, pure expansion; the initial cloud
size is neglected (D4/"cloud-size-corrected temperature" is later). Bimodal: from the thermal σ.
Synthetic X/Y: x = v_x t with t the atom's own arrival time, not t_f; the difference is second
order (tested: recovered within SE).

## Rates and units

- Rate = counts / (bin width in ms or mm) / shots: T in kHz per shot, X and Y per mm per shot.
  The roadmap's Decided section says X/Y "per m per shot"; the Coordinator asked for per mm to
  match the mm axes. **Proposed, for Tony:** per mm (a value 1000× smaller than per m; the label
  says "per mm per shot"). One constant (`RATE_SCALE`) to change if he prefers per m.
- Fits always run on counts (Poisson weights); the drawn curve is scaled by the same factor as
  the bars, so the rate setting never changes a fitted number.
- "The box and T window applied first": every histogram already counts only events inside its
  own range. The new **Only events inside all three ranges** also drops events outside the other
  two axes' ranges (X/Y from T's window). **Proposed:** off by default (the plot's counts don't
  change for existing users); Tony may prefer it on, at least whenever a fit is on. With
  auto-crop, each axis's range is its own shortest 99 % range (cheap), not the 3D scatter's
  `crop_box` heuristic.
- Axes: X and Y in mm; T in ms when its range spans under 1 s, else s (`T_SECONDS_FROM`).
  Data and fits stay in s and m; only drawing scales.
- **View range bounds unchanged:** `selection.range_specs`/`BOUNDS` are shared with the 3D
  scatter, so the manual bounds keep their s / m units with SI prefixes (the spin boxes already
  show and accept mm and ms). The dock's `range_brief` already writes them with prefixes.

## Smoothing

- σ per axis: **proposed defaults** T 0.1 ms (the front panel's 0.0001 "time bin", read as
  seconds), X/Y 0.2 mm. Bins of σ/5 (`bin_factor` 5), at most 5 000 (`SMOOTH_MAX_BINS`); beyond,
  the bins widen and the title says so in amber (the kernel stays σ wide).
- Convolution with a normalised Gaussian cut at ±4σ, edges reflected (`np.pad` symmetric): what
  spreads past an edge folds back in, so the total is kept exactly (tested, including a kernel
  wider than the histogram).
- Fits default to the unsmoothed counts.
- **Fit to: smoothed curve (model smoothed too)**, after the review of `05e5401`. The first
  version fitted s = S n as independent bins with observed errors and took the smoothing out in
  quadrature: its SEs were ~4× too small (bins share counts), and observed-count weights biased
  low-count fits. Now (`profiles.fit_smoothed`):
  - S is the smoothing as a sparse matrix (`Smoothing`; the same reflected-edge map that smooths
    what is drawn). The model is smoothed with it: s is fitted with S f(θ), so θ are the
    unsmoothed profile's parameters (no quadrature step; a bimodal R is deconvolved too).
  - Weights: Var(sᵢ) = Σⱼ Sᵢⱼ² μⱼ with μ = f(θ) (model-based, refitted until θ settles; the first
    round uses the observed counts), floored at 0.1 count per raw bin.
  - Covariance: the sandwich (JᵀWJ)⁻¹ JᵀW · S diag(μ) Sᵀ · WJ (JᵀWJ)⁻¹, J the smoothed model's
    derivatives: the estimator's real spread, counting the correlation.
  - Checked over 40 seeds: scatter/SE 0.84 (5 000 events) and 0.83 (600 events over 600 bins),
    as the raw fit's 0.83/0.77; width pull −0.36 at about one count per bin. The test uses fixed
    seeds: ratio in 0.7–1.4, mean pull within ±0.5, at 5 000 events/200 bins and 300/600.
  - Smoothing wider than a fifth of the histogram's range is refused for this fit (a failure
    note: "too wide for this range … fit the unsmoothed counts"): folded back at the edges many
    times, the SEs came out 2× too large at half the range.
  - Why not "fit the raw counts against S f(θ)", as the review suggested: E[n] is the profile
    f itself, so that would fit f = S⁻¹(profile), the profile narrowed by the smoothing. The
    smoothed data's expectation is S f, so the smoothing goes on the model when the data are
    smoothed. Statistically the smoothed curve holds no more than the raw counts (its SEs come
    out about the same), so the option is for comparison with the front panel.
  - Drawn: the smoothed model on the bins, over the smoothed curve; the title says
    "Gaussian ⊗ smoothing: …".
  - Second review (`679657f`): the sandwich replaced the SEs only after `fit_histogram` had
    gated with its weights-only SEs, so a thermal-only cloud's condensate was "consistent with
    0" in 4/30 seeds (unsmoothed 28/30) and R showed at the cap with an SE. Now
    `fit_histogram(…, covariance_of=…)` takes the covariance from the caller before anything
    reads it (SEs, gating and notes, undetermined check, extras); the probe gives 28/30, as
    unsmoothed. Tested on 10 fixed seeds (≥ 8 gated, within 1 of the unsmoothed count).
  - Cost: refits start from the last fit only (not the bimodal model's four starts and its
    Gaussian seed fit), at most 3 after the first. A smoothed bimodal axis went from 0.65 s to
    0.25 s (2 400 bins; 0.29 s at 5 000), a smoothed Gaussian ~0.07 s; widths and SEs unchanged.
    The Live policy stays "every shot": `live_policy` is per action, not per setting, and three
    smoothed bimodal axes (< 1 s) are well under a shot's interval. **Proposed:** a per-setting
    policy if Live ever runs faster.
  - The smoothed model applies S only on its own bins (same count and positions within 10⁻⁶ of
    a bin); anywhere else it is the unsmoothed model. If `fit_histogram` left bins out, the
    covariance hook returns nan and the fit fails as undetermined rather than misapplying S.
- Drawn: faint bars behind a darker smoothed line.

## Fits

- Models: T — Gaussian, Arrival-time thermal, Bimodal TF² + Gaussian; X/Y — Gaussian, Bimodal
  TF² + Gaussian. p = 2 per F0a's derivation (full-histogram projections). TF^{3/2} and the
  TF + arrival-time bimodal are not offered (D4). Bimodal shows centre, thermal σ, R and T; no
  N0/N (D4). The bimodal R/σ_th cap stays at F0a's default 2 (recorded in options).
- **Placement (proposed):** an option on the existing plot, all fits off by default; a Fits
  settings tab holds the toggles, models, Fit to and Constants.
- Display: each axis's title gets a second line, e.g. `Gaussian: centre (−20 ± 360) µm · σ
  (84.39 ± 0.62) mm · T (19.80 ± 0.29) µK`; notes and failures in amber
  (`#b06000`, as Transfer fractions); the curve in black over the bars. The header line names
  the constants with origins and unconfirmed flags; constants notes (fall time disagreeing with
  √(2h/g)) in amber.
- Record: `Histograms.record()` holds each `AxisFit.as_record()` (with `FitResult.as_record()`,
  including `fixed`), with any fit `ResolvedConstants.as_record()`, and `record_lines`. It is
  the result's new `AnalysisResult.found` (JSON): the runner sets it in the worker thread from
  `DatasetAnalysis.result_found(action, data)` (default `{}`, so other plots are unchanged), it
  survives `RamResults.released`, and the base `result_record` shows its `record_lines` in the
  dock's tooltip ("Fit T: …" with reduced χ² and notes, "Constants: …"). Not in `reuse_key`
  (it is output, not input). It is read-only at the top level only (shared inner lists and
  dicts; documented). A `result_found` that raises is logged and gives `found = {}`; the run
  still completes and draws.
- Fall time: the arrival-time model is built from h and g (its fall is √(2h/g)); a hand-set
  fall time is used by X/Y temperatures only. The Fall time tip says so, and the plot already
  notes a disagreeing hand-set fall time. (Kept: building the T model from a hand-set t_f would
  need an h or g that disagrees with the table's.)
- "Fit to" shows while Smooth is on; `ParameterSpec.when` takes one condition, so it can't
  also wait for a fit to be on (the tip says it applies to every fit).
- Live: fits add ~20–30 ms per Gaussian axis, ~50 ms per bimodal axis at 300 000 events
  (whole run 56 ms without fits, 85 ms with three Gaussians, 215 ms with three bimodals). The
  default policy (every shot) stays.
- Cancellation: `context.check()` before each axis and before each fit.

## Constants and the F0b hook

- `AnalysisContext.constants`: `{"lab": {…}, "folder": {…}}`, default empty. F0b fills it when a
  run starts (GUI side, from Settings and the folder's store); the plot adds its fall distance
  and fall time (0 = not set) as the plot layer and calls `physics.resolve`. Nothing else is
  overridable per plot (as briefed).
- Not yet in the result's reuse key: the lab/folder layers are not parameters. When F0b lands,
  put the resolved constants (or the layers) into what `reuse_key` compares (R2/R3).
- The run recomputes the arrival-time model with the run's h and g, so the fit and the
  temperatures use the same numbers; the record shows both.

## Choices proposed for Tony

1. Fits as an option on "T, X, Y histograms", off by default, on a Fits tab.
2. X/Y rate per **mm** per shot (roadmap says per m).
3. "Only events inside all three ranges" off by default.
4. Smoothing defaults σ_T 0.1 ms, σ_XY 0.2 mm, at most 5 000 bins.
5. T in ms below a 1 s range, else s.
6. Fitting the smoothed curve smooths the model too (honest SEs, no correction step), and is
   refused when σ_s exceeds a fifth of the range.
7. The arrival-time model has no free launch velocity (it is degenerate with T₀).
8. Bimodal offered on D1's axes with p = 2 only; D4 adds its outputs.
