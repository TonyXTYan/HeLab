# DLD_front_panel `lib/*.m`, file by file

From a subagent's read of every `.m` directly in `legacy/DLD_front_panel/lib/`
(not `Core_BEC_Analysis`). Usage was checked by grepping each name across the
repo. Paths are relative to `legacy/DLD_front_panel/`. Overview and plan:
[notes.md](notes.md).

## Used by the GUI

### `dld_plot_tof.m` (476 lines): the 1D Plot button (`dld_front_panel.m:367`)

**What it plots:** up to three stacked panels, plus optional fits and an FFT column.
- **T panel:** count rate in kHz/file, from a Gaussian-smoothed histogram (`smooth_hist`, σ = bin width) divided by the number of files (32–40).
- **X and Y panels:** linear count density in m⁻¹/file (52–88).

**`fit_thermal` (225–319).** Fits `amp·exp(-(x-mu)²/(2σ²))` with `fitnlm` and no offset. Starting values come from the weighted mean and RMS width.
- On the time axis the width becomes a distance: σ_x = σ_t·g·t_fall.
- `T = (σ_x/t_fall)²·m/k_B`, labelled "no interactions".
- Uncertainty: 2T·SE_σ/σ.
- The plot shows a 1σ prediction band and the centre, width and T as text.

**`fit_condensate` (322–426)** fits the bimodal model `bimod` (428–442).
- **Model:** a TF part `A·max(0,1-((x-x0)/R)²)^(3/2)` plus a Gaussian `B·exp(-(x-x0)²/2σ²)` with the same centre. The thermal fit seeds it, with R starting at σ/10.
- **It reports:**
  - N0/N;
  - T/Tc = (1-N0/N)^(1/3);
  - T from the Gaussian width;
  - Tc = T/(T/Tc);
  - N_est = (k_B·Tc/(0.94·ħ·ω̄))³ with ω̄ = 2π·(500·500·50)^(1/3), hard-coded.

**Inputs:** windowed TXY, `files_imported`, the windows, `time_binsize` and `oned_spatial_binw_h`. Checkboxes: oned_time/X/Y, oned_fit, fit_bimod, FFT, FFT_log, zoom. It also reads `handles.grav`, `falltime`, `masshe`, `boltzconst`, `hbar` and `trapfreq*`.

**Bugs:**
- **FFT:** it uses undefined `t_centers`, `T1d_counts`, `X1d_counts`, `X_bin_width` and `Y1d_counts` (113, 136–139, 176–179). Its X/Y FFTs use the time sampling rate.
- **Bin width:** `T_bin_width = field·1e-3` (11), but the field is labelled "Time bins (s)".
- **X/Y axes:** plotted as `centers*1e-3` (56, 76) but labelled mm.
- **`fit_condensate` spatial factor:** `vdet = 1/1000` (384) with the data in metres, so the spatial T is off by 10⁶.
- **Condensate areas:** `countsTF = A/(4R)` and `countsGauss = B/(√(2π)σ)` (405–406) divide instead of multiply. So N0/N and T/Tc are wrong.
- **TF exponent:** 3/2 is used for the T profile. Integrated over x and y, it should be 2 (`TC_and_below_*` uses 2).
- **Fitting:** unbounded fits (`abs()` inside the model) and `UseParallel`.
- **Clean-up:** an empty block (96–98) and a mis-encoded ± (422).

### `dld_2dplotter_window_a.m` (213 lines): the 2D Plot button (`dld_front_panel.m:888`)

**What it plots:** XY (m⁻²), XT and YT (m⁻¹s⁻¹) density images.
- `hist3` with `linspace(min,max,bins)` edges, divided by the bin area (52–142).
- An even bin count is forced odd (46–49).
- Options: range compression `counts.^0.5` (`dyn_range_pow`, 19), an `imgaussfilt` blur in bins, and viridis.

**Pictures:** `pics/2d_hist.png` shows a pulsed atom laser. `phased_noise*.png`, `sceptre_1.png`, `eye_of_sauron.png`, `SAL_profile*.png` and the `*_ramp.png` files are the same views on other runs.

**Bugs:**
- **2D Gaussian fit block (161–210):** undefined `radius_fit_guess_num`, `bins_per_pixel`, `binned_output` and `figure_number`. The caller uses an undefined `pixel_size_x`, so ticking the fit box crashes.
- **Bin area:** it divides by `bins` where there are `bins-1` bins.
- **"LogScale":** it is really a square root.
- **Blur:** a blur over bins/2 silently becomes 0.

### `dld_avg_pos_plots.m` (114 lines): the Avg Pos button (`dld_front_panel.m:1331`)

**What it plots:** the mean and SD of X and Y (mm) in each T bin, against T, in four panels (22–58). Optionally a one-sided amplitude spectrum of each, with a Hamming window and the first point dropped to hide DC, and a log option (88–115).

**Use:** beam position drift and width breathing over a pulse, and oscillation frequencies (sloshing, trap, noise).

**Bugs:**
- **Bins:** `T_bin_num = round(N/2)+1` (18) gives about 2× wider bins than asked.
- **Bin width units:** they disagree with `dld_plot_tof`.
- **Labels:** the X FFT is labelled "Yavg" (64).
- **Odd length:** `P2(1:L/2+1)` fails when L is odd.
- **Empty bins:** they make the spectrum NaN.
- **Code:** it grows arrays inside the loop; `tmin/tmax` are unused.

### `wait_till_written.m` (+ `is_early.m`): Monitor Run (`dld_front_panel.m:751`)

- **What it does:** busy-waits until the file's mtime is `wait_for_mod` s old (1 s raw, 4 s TXY), using locale-dependent `datenum(dir.date)`.
- **`is_early.m`:** the standalone file has a syntax error (`function = …`) and undefined variables. MATLAB uses the working subfunction inside `wait_till_written.m`.

### `fileExists.m`: Read Data (232–239)

A Java `File.exists()` wrapper.

### `sfigure.m`

A silent-figure helper. It duplicates the one in `Core_BEC_Analysis/bin`.

## Dead code (no callers)

### `TC_and_below_{a,b,radial_a}.m` and `TC_and_below_tof_{a,b}.m`

A bimodal TOF fit below Tc ("ONLY GOOD IN TF APPROXIMATION").

**Thermal part:** Bose-enhanced, integrated over 2D:

`A_th·Σ_{n=1}^{nmax} exp(-z²/z0²)^n / n^{5/2} = A·g_{5/2}(e^{-z²/z0²})`

with `z = g·τ·(t+t0)` and `z0² = (2k_B·T/(m·ωr²))·(1+ωr²τ²)`.

**Condensate part:** `A_c·(1-z²/(R_t·v)²)²` for |t| < R_t, with v = g·τ. A background is added.

**Fit:** `fminsearch` on the sum of squared errors (MaxIter 20000), on data normalised to its peak and centred on it. nmax = 200.

**Derived quantities:**
- thermal and condensate fractions;
- `μ = ½·m·ωr²·(R_t·v)²/(1+ωr²τ²)`, divided by 2πħ, so μ is in Hz although the comment says joules;
- `N0 = (2μ/ħω̄)^{5/2}·a_ho/(15a)` with a = 7.512 nm;
- `N_th = 1.202·(k_B·T/ħω̄)³`;
- the scattering length back-solved.

Also `Tv0` from `tof_gauss*`.

**Variants:**
- `_a` calls a `TC_and_below_tof` and a `tof_gauss` that don't exist. It never accumulates its histogram (`d(bin) = binned_time(bin)+1`, 68), and calls `close all`.
- `_radial_a` uses ωa² in `cp` (144), against its own μ (133).
- `TC_and_below_tof_a` and `_b` are byte-identical.

**Throughout:** hard-coded trap frequencies, τ and scattering length; T can go negative.

### `tof_gauss_dld_a.m`, `tof_gauss_b.m` (+ `guassfun_a/b.m`)

The "Yavin et al." TOF-width temperature.
- **Width estimate:** normalise to the peak, then take the full 1/e width from the e⁻¹ crossings.
- **Fit:** `B·exp(-(2(t-t0)/w)²)+bg` with `fminsearch`.
- **Temperature:** `v0 = g·w/2`, `T = m·v0²/(2k_B)`. This is the same physics as `fit_thermal`, since w/2 = √2·σ_t.
- **Assumption:** the TOF spread is pure velocity.
- **Bug:** it indexes past the array if no second crossing is found.
- **Duplicates:** the a/b versions differ only in debug prints and transposes.

### `Heconst.m`

Constants, with problems:
- `Hemass = 4/6e23/1000` = 6.667e-27 kg (the real value is 6.6465e-27).
- Γ = 2π·1.62 MHz and λ = 1083.33 nm.
- `Helife = 1/(Γ·2π)`, which is wrong.
- I_sat = 0.17 and Hemu = 2.8e6.
- g = 9.8, against the front panel's 9.7961.

### `dld_raw_to_txy_parfor.m`

A `parfor` over raw files that writes `_txy_forc` files with 8-digit precision. It is the converter's job.

### `plot_pancake.m`

- **Bugs:** it reads the same file 10 times and calls a missing `dld_read_5channels_reconst_multi_a`.
- **Processing:** it rotates by 0.61 rad and crops to t 0–0.1 s, x −20–0 mm, y ±30 mm.
- **Plots:** a 3D scatter, and a Y–T image (200 µm × 50 µs) built with a per-hit loop.

### `TOF_averaged.m`

- **What it does:** sums the TOF histograms of 50 shots (0.4–0.55 s, 0.1 ms bins), then plots the FFT (`positiveFFT`) and the PSD (`power_spec`, 0–5 kHz) to find trap frequencies.
- **Problems:** hard-coded paths, and missing dependencies.
- **Keep:** the summed-TOF spectrum idea.

### `positiveFFT.m`, `power_spec.m`, `procFFT.m`

- **`positiveFFT`:** `fft/N`, first half, without doubling.
- **`power_spec`:** uses the obsolete `psd()`.
- **`procFFT`:** a PSD plus `findpeaks` above max/3, and saves to `C:\Program Files\MATLAB\R2011b\Pow.mat`.

## `bug1.txt`

"zero counts encountered", then `Index in position 2 exceeds array bounds` in
`windowdata` (`dld_front_panel.m:1169`). A zero-count file left `txy_data` empty,
not N×3, and the 1D plot ran anyway. HeLab's plots must keep handling empty
shots and empty windows, which `analysis/empty.py` does.

## Summary

| File | Status |
|---|---|
| `dld_plot_tof` | Used (1D Plot); FFT broken; bimodal N0/N wrong |
| `dld_2dplotter_window_a` | Used (2D Plot); fit block broken |
| `dld_avg_pos_plots` | Used (Avg Pos) |
| `wait_till_written`, `fileExists`, `sfigure` | Used |
| `fit_2d_gaussian` | Effectively dead (its caller is broken) |
| `TC_and_below_*`, `tof_gauss_*`, `guassfun_*`, `Heconst` | Dead; a/b duplicates |
| `TOF_averaged`, `positiveFFT`, `power_spec`, `procFFT`, `plot_pancake`, `dld_raw_to_txy_parfor` | Dead; hard-coded paths, missing dependencies |
| `is_early.m` | Syntax error, unused |
