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
- **He* mass:** 4.002602 u × CODATA u = 6.64648e-27 kg (the brief's number; the He-4
  atomic mass is 4.00260325 u, a 2e-7 relative difference, far below any fit's error).
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
- **Record:** `as_record()` gives `{"values", "origins", "unconfirmed"}` with JSON values
  only; `from_record` reads it back (tested through `json.dumps`).

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
- **Failures are results**, with nan estimates: "no data to fit", "no counts to fit",
  "too few bins to fit: N for P parameters", "all counts in one bin: no width to fit",
  "the fit did not converge", "the fit could not run: …", and "not determined by the data:
  <parameter> (no usable SE)". The last one matters: SciPy's pseudo-inverse covariance gives
  a parameter the data don't constrain a variance of exactly **0**, not inf, which would
  read as an exact value; any variance that isn't finite and positive is a failure.
- **Notes on a fit that worked:** non-finite bins left out; a parameter at its bound (its
  SE isn't reliable); reduced χ² above 3.
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
variances use the mean of the last two parameter sets, which damps it.

Coverage after (fraction within 2 SE, mean pull, pull SD; 300 seeds):

| Case | centre | σ / R |
|---|---|---|
| Gaussian, 500 events, 40 bins | 0.96, 0.07, 0.97 | 0.96, −0.06, 0.98 |
| Gaussian, 5000 events | 0.95, 0.02, 1.01 | 0.94, 0.09, 1.01 |
| Gaussian, 50,000 events | 0.95, −0.08, 1.04 | 0.94, 0.13, 1.08 |
| TF p = 2, 5000 events | 0.95, 0.02, 0.99 | 0.94, 0.13, 1.05 |
| Bimodal, 20,000 events, 100 bins (100 seeds) | 0.96 | R 0.89 (pull +0.54), σ_th 0.94 |

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
  10⁻³…10⁵ get `×10ⁿ`: `(6.64650 ± 0.00020)×10⁻²⁷ kg`. A value that rounds to 1000 of a
  prefix moves up one (`0.9999996 s` → `(1.00000 ± 0.00010) s`).
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
  size ≤ ddof add only their mean's spread (their SD is nan).
- `sewm(values, weights)` → `Estimate` of the weighted mean, Cochran (1977) as Gatz & Smith
  (1995): SE² = n/((n − 1)(Σw)²) · Σ w² (x − x̄_w)². I showed the review's expanded form
  equals Gatz & Smith's three-term bracket (it is Σ (wᵢxᵢ − w̄x̄_w − x̄_w(wᵢ − w̄))²); the test
  checks both, and s/√n for equal weights.
- `propagate(f, values, covariance)`: first-order SE by central differences, used by
  `FitResult.derived`.
