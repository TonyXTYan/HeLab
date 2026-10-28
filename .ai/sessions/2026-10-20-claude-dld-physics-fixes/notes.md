# DLD physics fixes: measurements and choices

Probes are in the session scratchpad (`pf/p_offset.py`, `pf/p_nll.py`, `pf/p_hist.py`) and the
physics reviewer's `rv-phys-probes/` (`p1_poisson.py`, `p2_skew.py`), run against this branch.

## 1. Release time from the arrival-time profile (`release.py`)

`_arrival` now fits `fits.arrival_time_model(velocity.effective_fall_distance(C), C.g)` first,
on the same window as before (±1.5 FWHM of the tallest peak, short of halfway to another,
8 bins per FWHM, ≥ 15). Its centre T₀ is the arrival of v = 0 by construction, so
t_r = T₀ − t_f has no skew bias. With h_eff = ½ g t_f² for a hand-set fall time, the model's
own t_f equals the run's, so the centre and the subtraction agree.

Chain: arrival-time fit → Gaussian fit (noted "the arrival-time fit failed (…): a Gaussian's
centre is used instead", plus the skew note when σ_t²/t_f > SE) → mean of the events near
the peak (noted). Always the arrival-time fit first, not only for wide clouds: on every
existing release test (BECs at σ_v 3 mm/s, 50-event clouds, coarse grids, background) it
converged, and for a narrow cloud it is the Gaussian to first order in σ_t/t_f.

`p2_skew.py`, 1.5 µK (σ_t 5.70 ms), 200 000 events, 20 seeds:

| | bias of t_r | SD | mean SE |
|---|---|---|---|
| before (Gaussian) | +32.9 µs | 13.7 µs | 12.8 µs |
| now (arrival-time) | −3.6 µs | 13.7 µs | 12.8 µs |

−3.6 µs is 0.28 of one fit's SE and 1.2 SE of the 20-seed mean (3.1 µs): no bias left
within the probe's resolution. Test: `test_a_wide_cloud_is_fitted_with_the_arrival_time_profile`
(other seeds: mean within 1 SE and within 3 SE/√20). The fallback is tested by making the
arrival-time fit fail (`test_a_failed_arrival_fit_falls_back_to_a_gaussian_with_the_skew_note`).

Assumed by the model (fits.py's comment): a point source, no mean vertical velocity (a launch
velocity is absorbed in T₀, as it was in the Gaussian centre), the run's h and g.

## 2. Offset ≥ 0 for raw counts (`fits.py`)

The bounds callables get only (x, y), so they can't tell raw counts from `sigma=` data. The
floor is therefore in `fit_histogram`, right after the bounds are read: with `sigma is None`
and `weights` "poisson" or "counts", a parameter named `offset` gets lower bound
max(model's, 0). Models' own bounds (lines ~465, ~515, and the bimodal's) stay −top, which
`sigma=` / rates and `weights="none"` keep. An offset at that 0 floor isn't listed in the
"at its bound" note (it is the common, legitimate answer when there is no background).
Lines touched in `fits.py`: the module docstring's weights bullet, an `OFFSET` constant, the
floor (6 lines after `fit_model.bounds`), one condition in `at_bound`. Not touched: the
bounds functions, TF/cap comments.

`p1_poisson.py` (150 events, 80 bins over ±8σ, 200 seeds): offsets < 0 117 → 0; σ mean 0.9862
→ 0.9848 (true Poisson NLL 0.9864); σ pull −0.285 → −0.306.

**The cost, measured (`p_offset.py`, `p_nll.py`):** when the true offset is 0, a floored
offset comes out slightly positive (0.03 counts/bin at 500 events, 0.1 at 5000) and takes the
tails from the Gaussian, so σ's mean pull goes from −0.17 to −0.31 (500 events, ±4σ, 40
bins) and from +0.03 to −0.16 (5000). The exact Poisson likelihood with offset ≥ 0 gives the
same (pulls −0.42 vs −0.43 IRLS, −0.154 vs −0.153, 100 seeds), so this is the constraint's own
effect, not the reweighting's. Coverage within 2 SE stayed 0.95–0.97. Two existing assertions
moved with it:
- `tests/test_fits.py::test_gaussian_recovers_centre_and_width_within_their_errors`: the
  mean-pull tolerance 0.3 → 0.4 (σ −0.305 at 500 events), with a comment;
- `tests/test_fits.py::test_bounds_and_poor_models_are_noted`: flat counts of 100 now end with
  the offset at its upper bound (top = 100, the data's own level) instead of σ; the
  assertion accepts any "at its bound:" note;
- `tests/test_histogram_fits.py::test_fits_use_the_unsmoothed_counts_by_default` (not a file
  this branch owns; one line): the raw-counts fit (floored) and the smoothed fit (`sigma=`,
  not floored) now differ by 0.66 SE in width; tolerance 0.5 → 0.75 SE, with a comment.

**Proposed, for Tony:** (a) keep the floor (an impossible negative mean count, and the exact
likelihood agrees) and accept the small low bias of σ when there is no background, or (b)
floor only when the fit's offset would make the model negative inside the window (the same
thing in practice). Also (c): smoothed counts are still counts, so `profiles.fit_smoothed`
(`sigma=`) could floor too, which would bring back the 0.5 SE agreement; that is in
`profiles.py`, another worker's file, so not done here.

## 3. XY origin (`release.py`, `velocity.py`)

- `detect_release_time(…, positions=None)`: positions (n, 2) beside the times (filtered with
  them). The origin is the mean X and Y of the events within `ORIGIN_SIGMAS` = 2 σ_t of the
  fitted arrival (and inside the fit window), finite X and Y only, ± s/√n (within run).
  `ReleaseTime.origin` (two `Estimate`s, nan without positions), `origin_events`,
  `origin_found`, and `"origin"` in `as_record`.
- `bootstrap_release_time`: a shot may be (n, ≥ 3) TXY events; when every shot is, the
  statistic is (t_r, x₀, y₀) and the origin gets the shot-bootstrap SE too (a trap that moves
  0.2 mm per shot: SE 36 and 54 µm in X and Y vs 9 µm within run, in the test; expected ≈ 46 µm). Times-only shots work as before.
- `txy_to_velocity(…, origin=(0.0, 0.0))`: v_x = (x − x₀)/τ; a non-finite origin raises
  `ValueError` (like a bad shape). `Velocities.origin` records it. The module docstring says
  the trap is assumed above X = Y = 0 unless an origin is given, and what that costs
  (back-to-back pairs sum to ≈ 2x₀/t_f).
- `release.velocity_origin(release, manual=None)` → ((x₀, y₀), "manual" | "detected" |
  "assumed"): the manual override first, else the detected origin, else (0, 0).

Tests: `test_back_to_back_pairs_need_the_xy_origin` (sums 0 to 1e-12 with the origin;
x₀(1/τ₁ + 1/τ₂) exactly without, ≈ 2x₀/t_f), `test_the_xy_origin_is_detected_from_the_rest_cloud`
(with a Bragg order at +0.1 m/s from the same trap, ignored; SE ≈ σ_xy/√n),
`test_the_shot_bootstrap_covers_the_trap_s_shot_to_shot_drift`.

**Proposed, for Tony:** the mean (not a median or a 2D Gaussian fit) of events within 2 σ_t;
a flat background in that slice pulls it towards the background's centre (the detector
middle), by its share of the slice. A per-folder "trap position" setting would be the manual
override's home (`velocity_origin(manual=…)`).

## 4. `bootstrap.shot_means`

`shot_means(per_shot, weights=None)` → `ShotMeans(value, se, shots)`: `estimates.sewm` per
element over shots with a finite value and weight > 0. For D5 (mean X per T bin: each shot's
mean per bin, weighted by its events there) the value is the pooled mean of all events in the
bin and the SE includes the shot-to-shot spread, with no resampling. Tested against the shot
bootstrap of the pooled ratio (agrees within 15 % after √((n−1)/n)). For D2, per-shot numbers
with equal weights give mean ± s/√n.

## 5. Docstrings

"within run (events independent)" on the release SE (module docstring, `ErrorKind`, the
`error` field, `detect_release_time`, the origin's SE, the no-bootstrap note), each pointing
to `bootstrap_release_time`. `peaks.py` needed no change.

## Re-review of 986db18 (second commit)

The Coordinator's re-review kept the floor (lower MSE than a free offset; fixing the offset
at 0 biases σ by 2–3.5 SE once there is any background, so never by default:
`rv-phys-probes/p7_offset.py`) and asked for four changes.

1. **Floor flag.** `fit_histogram(…, nonnegative_offset=None)`: None = raw counts with count
   weights (as before), True/False to ask for or refuse it. `profiles.fit_smoothed` passes
   True (smoothed counts are counts), so the smoothed and raw fits agree again:
   `test_fits_use_the_unsmoothed_counts_by_default` is back to 0.5 SE. Test:
   `test_the_offset_floor_can_be_asked_for_or_refused`.
2. **Bin means.** `fit_histogram(…, binned=True)` averages the model over each bin with
   Simpson's rule (`fits.bin_means`, the bin's two ends and centre; `fits.bin_bounds` puts
   edges halfway between centres, before bins are left out, the outer ones mirrored).
   Simpson for every model rather than a Gaussian CDF: one code path, exact for cubics, and
   its error for a Gaussian in bins of σ is ~10⁻³ of the peak (against ~4 % for the centre
   value). The fitted bins, χ² and the Poisson reweighting all use the bin means; `curve` and
   `evaluate` stay the model itself, for drawing. `binned=False` is for point samples (two
   `test_fits.py` tests of exact function values pass it) and for `fit_smoothed`, whose
   `smoothed_model` now bins before smoothing on its own bins (S·f̄), and whose sandwich
   covariance and refit variances use the same bin means (`bin_means(model.function, …)`),
   so prediction, Jacobian and variance agree. Measured, 60 seeds of 50 000 events in bins
   of σ/5 (σ pull from the events' own standard deviation, which removes the seeds' own
   scatter: that alone was −0.30 for seeds 0–59): centre values +0.5, bin means within 0.15
   (test `test_the_model_is_averaged_over_each_bin`, 40 seeds; bins of σ: centre values 4 %
   wide, bin means right). Coarse bins (σ/2.5 arrival-time, R/5 Thomas–Fermi) still recover
   their parameters (`test_coarse_bins_keep_…`). The release-time probe is unchanged
   (−3.3 µs, SE 12.8 µs).
3. **Robust origin.** `_origin` keeps, within the T slice, an XY window of ±3 robust σ
   (1.4826 MAD) about the median, found twice (the second about what the first kept), then
   takes the mean ± s/√n. Chosen over Gaussian + offset fits of the X and Y histograms: no
   fit to fail on few events, and it also drops a second cloud (a horizontal Bragg order),
   which an offset would not absorb. The background's share is estimated from a frame
   around the window (out to twice its half-widths: three times its area), recorded as
   `origin_background` ("background" in the record) and noted above 5 %. Tests: 200 000
   uniform background events, a 30 % order 20 mm away, and both, over 3 seeds: origin within
   3 SE (a plain mean of the slice was pulled > 3 mm by the order), share < 5 %; a background
   nearly as dense as the cloud inside the window is noted. `velocity_origin` returns
   "detected (unsure)" for an unsure release. The module docstring says a cloud inside the
   window (less than ~3σ away) or a background as dense as the cloud still pulls the mean.
4. **`shot_means` notes** elements with 2 to `MIN_SHOTS` − 1 shots ("the SE over shots is
   rough there").

## Reviewer follow-up (after the merge 157686b)

1. `fit_histogram(edges=…)`: the bins' exact bounds (len(centres) + 1, in the centres'
   order), used whenever given; the default halfway edges are documented as right for
   equal-width bins of counts only. `binned` may be a weight function w(x): each bin gets
   ∫w·f / ∫w (radial shells: r²). The quadrature is now three-point Gauss–Legendre instead of
   Simpson (same three evaluations per bin, exact to degree 5): on r²-weighted shells of σ/3
   Simpson was off by up to 1.3·10⁻³ and moved σ by 0.19 %, Gauss–Legendre by 1.5·10⁻⁶.
   The reviewer's `r2.py` unequal-bin densities: σ 1.043 with halfway edges, 1.0000 (±2·10⁻⁴
   in the test) with `edges=`; radial shells recover σ = 1 within 10⁻⁴ with w = r².
2. Origin background share: nan with a note when the window covers more than half the T
   slice's XY bounding box (a clean cloud, or a background that fills the slice, which then
   pulls the origin: the note says so) or the frame reaches past the slice's events. The
   reviewer's "keeps most of the slice" read as events failed with a real but sparse
   background (480 background events beside 19 000: window keeps 97 %, yet the estimate is
   fine), so it is read as XY extent. Median/MAD clipping breaks down once the background
   is more than about half the slice's events (the window then spans it all); that case now
   says so instead of reporting a share.
3. `FitResult.curve` is documented as the model at points, not bin-averaged.
