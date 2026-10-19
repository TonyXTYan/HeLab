# F0a notes: design choices and derivations

Items marked **proposed, for Tony** are my choices made while he was away; each is easy to
change.

## Files

- `helab/analysis/physics.py`: the table (`CONSTANTS`, `TABLE`), `resolve`,
  `ResolvedConstants`, `DEFAULTS`, `fall_time`, the σ_v and temperature conversions.
- `helab/analysis/estimates.py`: `Estimate` (value, SE), `format_uncertainty`,
  `si_prefix`, `pooled_mean_and_std`, `sewm`, `propagate` (delta method).
- `helab/analysis/fits.py`: `fit_histogram`, `FitResult`, `FitModel` and the registry
  (`MODELS`, `register`), the Gaussian, Thomas–Fermi and bimodal models and their areas.
- Tests: `tests/test_physics.py`, `tests/test_fits.py`, `tests/test_uncertainty_format.py`.

All three modules are Qt-free and do no I/O, like `stats.py` and `selection.py`.
`estimates.py` holds the formatting, the pooled statistics and `sewm` (my call: they are
all "values with errors"; `fits.py` depends on it, not the other way).

## Constants (physics.py)

- **Table rows** carry key, title, unit, value, source text, `level` ("lab" or "folder"),
  `unconfirmed`, `shown_only` (DLD trigger and acquisition) and `codata`. The fall time's
  value is nan, meaning derived.
- **Trap frequencies are in the table** (500 / 50 Hz, unconfirmed, folder level), though
  the brief didn't list them: the roadmap's defaults table has them and D4/D14 need them.
  The release time is not: the roadmap makes it come from the data (D8), with a manual
  alternative that F0b/D8 can add as a folder row.
- **CODATA rows (ħ, k_B, u) are level "lab" with `codata=True`.** The roadmap says every
  constant can be set by hand; F0b may still choose not to offer ħ and k_B. *Proposed, for
  Tony:* show them read-only.
- **He* mass:** the He-4 atomic mass, 4.00260325413 u (AME2020) × CODATA u =
  6.64648e-27 kg. The brief's 4.002602 is helium's standard atomic weight, a different
  number (2e-7 relative). A test checks it against CODATA's alpha-particle mass plus two
  electrons.
- **Layers:** `resolve(lab=…, folder=…, plot=…)` applies the defaults, then each layer
  (more specific wins), and records each value's origin ("default", "lab", "folder",
  "plot" or "derived"). Unknown keys and values that aren't finite and positive raise
  `ValueError`: F0b validates input, and a run should never get that far with bad values.
- **Fall time rule** *(proposed, for Tony)*: derived √(2h/g) from the effective distance
  and g, unless a layer at least as specific as the one that set the distance (or g) sets
  a fall time. So a folder's new fall distance is never silently paired with a lab-wide
  fall time; a fall time set in the same folder (or a plot) wins.
- **Unconfirmed** in a resolved set: keys still at an unconfirmed default, and the derived
  fall time while its distance is (`ResolvedConstants.unconfirmed`). A value set at any
  layer counts as the user's word.
- **Fall time rule, every case** *(for Tony to confirm)*:
  - nothing set: derived from the distance and g in use;
  - a fall time set at a layer at least as specific as the most specific layer that set the
    distance or g: kept as set;
  - otherwise derived again. So a plot's g override discards a folder's hand-set fall time,
    and a folder's distance discards a lab-wide fall time;
  - a kept fall time more than 0.1 % from √(2h/g) is noted in `ResolvedConstants.notes`
    and the record ("fall time and distance disagree…"): e.g. a lab-wide 0.417 s beside the
    default 0.848 m (0.4161 s).
- **Record:** `as_record()` gives `{"values", "origins", "unconfirmed", "notes"}` with JSON
  values only. `from_record` needs every table key with a finite value and a known origin
  (`ValueError` otherwise), ignores keys the table doesn't have (a newer version's), and
  recomputes `unconfirmed` and `notes`. `ResolvedConstants` hashes by its values
  (`origins` is compared, not hashed).
- **The conversions take the run's `ResolvedConstants`** (required), never the defaults, so
  a plot can't show a temperature from constants its result didn't record.

### Temperature from widths (pure expansion, ideal gas)

With z up and the detector h below the trap, z(t) = h + v_z t − ½ g t². At rest an atom
arrives at t_f = √(2h/g) moving at −g t_f. A small upward v_z has moved it v_z t_f by then,
so it arrives later by δt = v_z t_f / (g t_f) = v_z / g: **σ_v = g σ_t**. (An initial height
spread σ_z0 adds σ_z0 / (g t_f), neglected; that is the cloud-size correction D1 lists.)
Transversally x = v_x t_f: **σ_v = σ_x / t_f**. Each axis: **k_B T = m σ_v²**. Tested on
exact arrival times of atoms with Gaussian v_z (the sign: faster upward atoms arrive later).
`temperature_estimate` carries the SE: SE(T) = 2 m |σ_v| SE(σ_v) / k_B. He* at 1 µK has
σ_v = 4.56 cm/s.

## Fits (fits.py)

- **API:** `fit_histogram(centres, counts, model="gaussian", weights=…, sigma=…)` →
  `FitResult` with `estimates` (name → `Estimate`), `covariance`, `curve` at the centres,
  `evaluate(x)` for a fine curve, `chi2`, `dof`, `reduced_chi2`, `failure` ("" when it
  worked), `notes` (warnings) and `derived(f)` for a number computed from the parameters
  with its SE (delta method).
- **Input:** raw counts, or anything else with its errors as `sigma=` (rates, smoothed
  counts). Count weights on values that aren't whole numbers give a note.
- **Failures are results**, with nan estimates: "no data to fit", "no counts to fit",
  "too few bins to fit: N for P parameters", "all counts in one bin: no width to fit",
  "counts in only N bins: too few to fit this model (it needs M)" (3 for the one-part
  models, 4 for bimodal), "the fit did not converge in N evaluations", "the fit could not
  run: …", and "not determined by the data: <parameter> (no usable SE)". The last one
  matters: SciPy's pseudo-inverse covariance gives a parameter the data don't constrain a
  variance of exactly **0**, not inf, which would read as an exact value; any variance that
  isn't finite and positive is a failure, unless the parameter is gated (below).
- **Notes on a fit that worked:** bins left out (a non-finite centre or count; an error
  that isn't finite and > 0, each said separately); counts that aren't whole numbers; a
  part's amplitude consistent with 0; a parameter at its bound (its SE isn't reliable);
  the Poisson weights not settling; reduced χ² above 3.
- **Gates:** a parameter that only shapes one part names that part's amplitude
  (`ModelParameter.gates`). When the amplitude is within 2 SE of 0 (or at 0 with no SE),
  the note says "<amplitude> consistent with 0 (within 2 SE): <parameters> not determined",
  those SEs are nan, and the fit isn't failed for them.
- **Extras:** numbers computed from the parameters and reported in `estimates` with a
  delta-method SE (`FitModel.extras`; the bimodal R).
- **Record:** `FitResult.as_record()` is strict JSON (nan → None), without the curve.
  The result's arrays are read-only.
- **Threads:** fits run in the analysis worker, so nothing changes warning filters per
  call (`warnings.catch_warnings` isn't thread-safe). `fits.py` sets one filter at import
  for SciPy's `OptimizeWarning` (the covariance checks report that case), and wraps each
  solve in `np.errstate` (thread-local) for trial-step overflows.
- **Scaling:** x and the counts are mapped to order one before fitting, each parameter by
  its role (position, width, height, shape); the covariance is mapped back. A T profile at
  0.416 s with σ = 0.1 ms fits as well as one at 0.
- **Multiple starts:** a model may return several starting points; the converged one with
  the lowest χ² is kept. The bimodal model starts from a Gaussian fit split three ways.

### Weights: Poisson likelihood by default *(proposed, for Tony)*

The brief asked for √max(n, 1) weights. Alone, they bias widths low (Neyman's χ²): at 500
events in 40 bins the Gaussian σ came out about one SE low on average (mean pull −1.07,
82 % within 2 SE; at 5000 events −0.55). So the default `"poisson"` fits with √max(n, 1)
first, then refits with each bin's variance from the model, max(μ, 0.1), until no
parameter moves more than 0.01 SE (at most 10 rounds). The fixed point solves
Σ (n − μ)/μ · ∂μ/∂θ = 0, the Poisson likelihood's own score equations, so it is the
Poisson maximum-likelihood fit, and the last covariance is the inverse Fisher information.
The plain iteration oscillated (mostly the offset, through the near-empty tails); the
variances use the mean of the last two parameter sets, which damps it. When 10 rounds
still don't settle (a model that doesn't describe the data: a Gaussian on a flat-topped
cloud moves about 0.7 SE per round), the result is the round that moved least, with a note
"the Poisson weights did not settle in 10 rounds (… up to N SE per round)". The bimodal
model's inner Gaussian guess uses count weights, or the caller's `sigma`.

Coverage after (fraction within 2 SE, mean pull, pull SD; 300 seeds):

| Case | centre | σ / R |
|---|---|---|
| Gaussian, 500 events, 40 bins | 0.96, 0.07, 0.97 | 0.96, −0.06, 0.98 |
| Gaussian, 5000 events | 0.95, 0.02, 1.01 | 0.94, 0.09, 1.01 |
| Gaussian, 50,000 events | 0.95, −0.08, 1.04 | 0.94, 0.13, 1.08 |
| TF p = 2, 5000 events | 0.95, 0.02, 0.99 | 0.94, 0.13, 1.05 |
| Bimodal, 20,000 events, 100 bins (100 seeds; before the R/σ bound) | 0.96 | R 0.89 (pull +0.54), σ_th 0.94 |

The bimodal R's +0.5 SE bias is from coarse bins (R spanned 12 bins; the model is
evaluated at bin centres, not integrated over bins); the test uses 200 bins. *Possible
later refinement:* integrate the model over each bin. `"counts"` keeps the plain
√max(n, 1) fit (cheaper, biased), `"none"` fits unweighted with the covariance scaled by
the residuals, and `sigma=` takes given errors.

Cost: a Gaussian fit takes about 15–20 ms here (a few `curve_fit` rounds), a bimodal one
about 170 ms. Fine for D1 (three histograms per run, Live every few seconds); D2's per-shot
fits may want `"counts"`, or a direct Poisson likelihood minimiser later.

### Models from the physics

- **Gaussian + offset:** A exp(−(x − μ)²/2σ²) + c. Area A σ √(2π).
- **Thomas–Fermi projection:** A (1 − (x − x₀)²/R²)₊^p + c, fixed p, registered for
  p = 2 (`thomas_fermi_2`) and p = 3/2 (`thomas_fermi_1_5`). Area
  A R √π Γ(p + 1)/Γ(p + 3/2) (16/15 A R at p = 2, 3π/8 A R at p = 3/2), checked by
  quadrature. The moment guess uses Var = R²/(2p + 3).
- **Bimodal:** A_c (1 − u²)₊^p + A_t exp(−(x − x₀)²/2σ²) + c, one centre
  (`bimodal_tf2_gaussian`, `bimodal_tf1_5_gaussian`). `areas` gives both parts, so N0/N
  is `result.derived(…)` with its SE (tested: recovers 0.4 within 2 SE in ≥ 9 of 12 seeds).
- **Bimodal constraint** *(proposed, for Tony)*: R is fitted as the ratio r = R/σ_th in
  [0.02, 2] (parameter `ratio`; R is reported as the extra `radius`). Unconstrained, the
  review found the fit inventing a condensate on a purely thermal cloud (20,000 events,
  20 seeds: always "ok", N0/N 0.013–0.148, R/σ 2–4: a TF wider than the Gaussian), and on
  a pure condensate the thermal part became a narrow spike inside the TF. Why 2: after a
  time of flight t both widths grow with t, σ_th = √(k_B T/m)·t and R = √(2μ/m)·t, so
  R/σ_th = √(2μ/k_B T), which is 2 at μ = 2 k_B T; colder clouds than that have too few
  thermal atoms to fit the Gaussian part anyway. The gates: `ratio` by both amplitudes,
  `sigma` by the thermal one, `radius` by the condensate one.

  After (200 bins, 20,000 events): pure thermal, 8 seeds: N0/N 0.001–0.16, 6 with
  "Condensate amplitude consistent with 0", and the others at 1.7 and 2.6 SE (one with R/σ
  at its bound of 2, noted). Pure condensate, 8 seeds: N0/N ≥ 0.9999, every one with
  "Thermal amplitude consistent with 0", R within 1 % of the truth. The 40 % mixture: N0/N
  0.39–0.41 ± 0.005. Tested: pure thermal N0/N < 0.2 and noted or under 2 SE in ≥ 6 of 8
  seeds; pure condensate noted in every seed with N0/N > 0.95.
- **The cap is a fit option**, `fit_histogram(…, max_radius_ratio=2.0)`, recorded in the
  result's `options` and `as_record()["options"]`. The default 2 (μ ≤ 2 k_B T) is valid
  near Tc down to roughly 0.4 Tc. Cold, deep condensates (T ≈ 0.1–0.3 Tc) often have
  μ/k_B T of 3–10, a ratio of 2.5–4.5 (the Coordinator's point), and would be clamped.
  So a fit ending within 1 % of the cap says "TF radius at its limit (R = c·σ_th): the
  cloud may be colder than the limit allows; raise it or treat T and N0/N as bounds"
  (instead of the generic "at its bound"). A fourth start at r = 3 (clipped to the cap)
  lets a raised cap reach cold clouds. Tested on a cold mixture with R/σ_th = 3 (12,000
  TF + 8,000 thermal events): the default gives the note in every seed (R clamped about
  5 % low); a cap of 5 recovers r = 2.98–3.09 and R within 2.5 % in 6 of 6 seeds. A
  higher cap brings back some of the ambiguity on thermal clouds, so **the default is
  Tony's to choose** *(for Tony)*: 2 (safe for clouds near Tc, notes on cold ones), or a
  higher default such as 4 with the note kept, or the cap as a D4 plot setting
  (proposed: a D4 setting defaulting to 2).

**The TF exponent of a DLD histogram is 2 on every axis** *(for Tony, a correction to the
review notes)*. The 3D TF density n ∝ (1 − Σ xᵢ²/Rᵢ²)₊ keeps its shape through the
expansion (Castin–Dum scaling). Integrating it over one other axis gives power 3/2, over
two gives power 2. The DLD records every atom in 3D, so a T, X or Y histogram of all
events integrates over both other axes: p = 2 for all three. The review notes (D4, legacy
bug 2) say "2 for T profiles and 3/2 for X/Y"; 3/2 applies only to a profile through a
narrow slice of one other axis (an X histogram of a thin T window) or a cut of a 2D image.
D4 should default to p = 2 and offer 3/2. Both are registered.

**Not built:** the arrival-time ("Yavin") thermal profile and the Bose-enhanced g_{5/2}
part (D1/D4 register them), the cloud-size-corrected temperature, and fitting the
smoothed curve (D1).

## Formatting (estimates.py)

`legacy/DLD_front_panel` isn't checked out in this worktree, so `format_uncertainty` is
built from the review's description of Core's `string_value_with_unc`
(`50.12±0.15` / `8.5479(10)`):

- The error is rounded to `digits` (2) significant digits, the value to the same place:
  `50.12 ± 0.15`, `8.5479(10)`, `0.10 ± 0.10` (0.0996 rounding up keeps two digits).
- Bracket form: the error in the value's last digits, CODATA style, so `12.3(12)` (not
  `12.3(1.2)`) and `1234(56)`; an error left of the point is written as it is,
  `12300(1200)`.
- **Units:** with a unit, an SI prefix chosen from the larger of the value and its error:
  `(416.12 ± 0.12) ms`, `416.12(12) ms`, `(0 ± 50) mm`. The ± form takes parentheses with a
  unit (ISO 80000-1; *proposed, for Tony* — drop them if they're too wide for titles).
  `si=False` for units that take no prefix (kg). Without a prefix, numbers outside
  10⁻³…10⁵ get `×10ⁿ`: `(6.64650 ± 0.00020)×10⁻²⁷ kg`.
- **Rollover:** when rounding carries the value or the error up a digit, the next prefix
  or power is used: `0.9999996 s` → `(1.00000 ± 0.00010) s`, `0 ± 0.9996 s` →
  `(0.0 ± 1.0) s`, `9.999e7 ± 1e6` → `(1.000 ± 0.010)×10⁸` (also with an error of 0), and
  `99999.97` → `(1 ± 0)×10⁵`.
- **Robust exponents:** the decimal exponent comes from Python's `e` formatting and the
  scaling from `Decimal.scaleb`, so subnormals work (`5e-324` → `(4.94066 ± 0)×10⁻³²⁴`, no
  ZeroDivisionError; `1e-320` → `×10⁻³²¹`). An error below 10⁻¹⁵ of the value is written to
  2 significant digits on its own (`1 ± 1e−20`), not as 20 decimals.
- `Estimate.as_record()` is strict JSON: a nan or infinite value or error is None.
- **Reused helper:** the spin boxes (`UnitSpinBox`, `ParameterSpec(si=True)`) use
  pyqtgraph's `siScale`. `estimates.py` stays Qt-free, so it has its own `si_prefix`, and
  a test checks it gives pyqtgraph's prefix for 68 values over y…Y (µ is U+00B5 in both).
  Beyond y…Y pyqtgraph writes no prefix or "e27"; `si_prefix` clamps.
  `selection.range_text`'s `SI_PREFIXES` covers only n…1, so it wasn't enough.
- **Specials:** error 0 → the value to 6 significant digits, `1 ± 0` / `1.23457(0)`; nan or
  infinite error → `± nan` / `± ∞`; non-finite value → `nan`, `∞`, `−∞`; a negative error is
  taken as its size; negative numbers use "−" (U+2212), as `range_text` does, and a value
  rounding to zero has no sign.

## Combining estimates

- `pooled_mean_and_std(means, stds, counts, ddof=1)` → (mean, SD, N), equal to NumPy on the
  joined data for ddof 0 and 1 (tested with groups of 0, 1, 2, 5, 40 and 300). Groups of
  size ≤ ddof add only their mean's spread (their SD is nan). Any other group's nan SD
  makes the pooled SD nan: its spread is unknown, not 0 (the first version read it as 0,
  pooled([1, 2], [1, nan], [5, 5]) gave 0.85). Counts must be whole numbers ≥ 0, else
  `ValueError`.
- `sewm(values, weights)` → `Estimate` of the weighted mean, Cochran (1977) as Gatz & Smith
  (1995): SE² = n/((n − 1)(Σw)²) · Σ w² (x − x̄_w)². I showed the review's expanded form
  equals Gatz & Smith's three-term bracket (it is Σ (wᵢxᵢ − w̄x̄_w − x̄_w(wᵢ − w̄))²); the test
  checks both, and s/√n for equal weights.
- `propagate(f, values, covariance)`: first-order SE by central differences, used by
  `FitResult.derived`.
