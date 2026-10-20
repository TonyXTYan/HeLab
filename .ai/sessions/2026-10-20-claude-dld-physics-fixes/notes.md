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
