# D8/D10 numerics: derivations and choices

## Velocities, z up (`helab/analysis/velocity.py`)

Frame: trap at the origin, z up, gravity −g ẑ with g = |g| > 0, the detector the plane
z = −h (h the fall distance, below the trap). Released at DLD time t_r with velocity
(v_x, v_y, v_z):

    z(τ) = v_z τ − ½ g τ²,  x(τ) = v_x τ,  y(τ) = v_y τ,  τ = t − t_r.

Arriving at z = −h at time t:  −h = v_z τ − ½ g τ²  ⇒  **v_z = ½ g τ − h/τ**
(the brief's h = −v_z τ + g τ²/2, the same equation). v_x = x/τ, v_y = y/τ.

Sign checks (all in `tests/test_velocity.py`, on exact trajectories):
- at rest: τ = √(2h/g) = t_f, v_z = ½ g t_f − h/t_f = (g t_f² − 2h)/(2 t_f) = 0;
- thrown up (v_z > 0) it arrives later than t_f, thrown down earlier: dv_z/dτ = ½ g + h/τ²
  > 0, so v_z is a monotonic relabelling of T for t > t_r;
- near t_f: v_z ≈ g (τ − t_f) (dv_z/dτ at t_f = ½ g + h/t_f² = g), physics.py's σ_v = g σ_t;
- the inverse, for a velocity window's T bounds: τ = (v_z + √(v_z² + 2gh))/g (`arrival_time`).

This is the surviving top-level Core `txy_to_vel.m` sign, −h/t_f + ½|g|t_f, as the review's
Decided section says. The Core folder copy's opposite sign is z down; not ported.

These are velocities **at release**. X and Y are taken from the point under the trap (the
detector's own axes and origin, no rotation). If the trap isn't over the detector centre,
v_x and v_y get an offset x₀/τ: a later choice (a "trap position on the detector" folder
setting), not needed for D8's axes.

τ ≤ 0 (an event before the release) or a non-finite T: nan, counted in `invalid`.

Columns keep the TXY order, (v_z, v_x, v_y), so axis index 0 is T or v_z in either view
(**proposed, for Tony**; the alternative is (v_x, v_y, v_z)).

### Recoil units

v_rec = ħk/m = h/(λ m) with λ the He* 2³S₁ → 2³P₂ vacuum wavelength, from its frequency
276.732 186 5 THz: λ = 1083.331 nm, v_rec = 9.20 cm/s. `RECOIL_WAVELENGTH` lives in
`velocity.py` for now, flagged unconfirmed. **Proposed, for Tony:** add it to
`physics.CONSTANTS` as a lab-level row ("Recoil wavelength", m, unconfirmed: which beams set
the unit), so it's recorded with the run like the rest. A Bragg order is 2ħk for
counter-propagating beams, so first-order Bragg peaks are at ±2 v_rec in these units; the plot
could offer "ħk" and "2ħk" as unit choices.

## Release time (`helab/analysis/release.py`, `helab/analysis/peaks.py`)

t_r = t_arrival − t_f, t_arrival the centre of one cloud released at rest (BEC, order 0).

**Peak finding** (`peaks.find_time_peaks`): the same method as Transfer fractions'
`detect` (bins half the shortest T interval holding 10 % of the events, 50…20 000 bins,
narrowing to the densest 99 % past the cap, Gaussian smoothing σ 1.5 bins,
`find_peaks` with prominence max(2 % of the tallest, 4 events/bin), FWHM on the nearer side,
position refined to the mean of events within one FWHM). Written as its own module, **not**
extracted from `transfer_fractions.py`: that plot's `detect` interleaves the binning with
its order/spacing logic, so extracting only the shared part would change its code on a
branch that doesn't own plots. Two differences: peaks in the first/last bin count (the
smoothed histogram is zero-padded before `find_peaks`), and each peak records its events
within ±FWHM/2. **Proposed, for Tony:** Transfer fractions switches to `peaks.py` later (a
refactor with its MATLAB-comparison tests as the check) — the only part they may share.

**Centre:** a Gaussian + offset fit (`fit_histogram`, Poisson likelihood) to the events
within 1.5 FWHM of the tallest peak (≈ ±3.5 σ), and short of halfway to any other peak,
8 bins per FWHM (≥ 15). When the fit fails or its centre leaves the window, the mean of
those events ± s/√n is used, noted. The arrival-time ("Yavin") model doesn't exist on this
base; when D1 registers it, it can replace the Gaussian here for thermal clouds.

**Notes and failures** (never exceptions):
- failure: no fall time, no events, fewer than `MIN_EVENTS` = 50 (proposed), no peak (e.g.
  all times equal);
- "unsure": another peak at least 50 % of the tallest's smoothed height (proposed; Transfer
  fractions uses 50 % of order 0's events). The tallest is still used; a Search T
  (`lower`/`upper`) chooses another cloud;
- the Gaussian fit's own notes, prefixed "fit:";
- the skew note, below.

**SE:** the arrival's only. The fall time is taken as exact; its error is systematic and
the same for every shot: δt_r = −δt_f = −δh/(g t_f) = −0.245 s/m · δh (−1.2 ms between the
0.848 and 0.8529 m candidates). The result records `fall_time`, and with the run's
`ResolvedConstants` record the origin of h. Since velocities depend on t_r only through
τ, and t_r was set by t_f, a wrong h cancels at τ ≈ t_f (v_z = 0 there whatever h is) but
not elsewhere.

**Skew.** τ(v_z) = (v_z + √(v_z² + 2gh))/g ≈ t_f + u + u²/(2 t_f), u = v_z/g, so a cloud
of rms T width σ_t has its mean arrival σ_t²/(2 t_f) late and its mode about σ_t²/t_f early.
Measured: a 1.5 µK cloud (σ_v 5 cm/s, σ_t 5.1 ms, 200 000 events) gave t_r 33 µs late
(σ_t²/(2t_f) = 31.6 µs; the SE was 11 µs). A BEC (σ_t 0.3 ms) is off by 0.1 µs. The result
notes when σ_t²/t_f exceeds the SE. **Proposed, for Tony:** either keep the note only
(current), or subtract σ_t²/(2 t_f) from the fitted centre (it matched the measured bias to
5 % here, but assumes a symmetric velocity distribution and a fit centre near the mean).

## Shot bootstrap (`helab/analysis/bootstrap.py`)

`bootstrap_shots(shots, statistic, n_boot, seed, confidence, cancelled)`: draws n shots with
replacement n_boot times; SE = std(replicates, ddof 1), interval = the (1 ∓ c)/2 percentiles.
The statistic takes a list of per-shot items (arrays, or anything) and returns a number or a
1D array (transfer fractions per order); nan for undefined resamples, which are counted per
element, left out and noted above 5 %.

Choices, **proposed for Tony**:
- `n_boot` 1000 (the SE's own error ≈ 1/√(2·1000) ≈ 2 %; 200 is enough for the SE alone,
  ~2000 for 95 % intervals). A fit-per-resample statistic costs n_boot fits: D4 may want 200
  or a time budget.
- `seed` 0 by default (recorded): the same data gives the same error bars, so Live reruns
  don't jitter. `None` gives fresh entropy, recorded as None.
- `confidence` 0.6827 (±1σ), so the percentile interval and the SE bar agree for normal
  replicates; 0.95 for reported intervals.
- A note below 5 shots (`MIN_SHOTS`): with n shots the bootstrap SE is √((n−1)/n) of the
  usual one and there are only C(2n−1, n) distinct draws (10 for n = 3). Fewer than 2 shots:
  a failure (value kept, SE nan).
- Percentile intervals, not BCa: BCa needs a jackknife (n more statistic calls) and is
  unstable for few shots; `scipy.stats.bootstrap` (the review's suggestion) resamples
  observations of arrays of equal length and has no cancellation, so it isn't used.
- Cancellation raises `results.Cancelled` (as `stats.auto_crop` does), polled before the
  first evaluation and before each resample.

Test: 60 shots with a 2 ms shot-to-shot spread; bootstrap SE of the mean of shot means
within 10 % of `sewm`'s s/√n (equal weights), and the 68 % interval ≈ ±1 SE.
