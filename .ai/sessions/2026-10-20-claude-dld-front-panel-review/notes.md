# DLD front panel review (2026-10-20, Claude)

Tony asked for a review of the `legacy/DLD_front_panel` submodule and a plan of
features to bring into HeLab. The short plan is in
[roadmaps/dld-front-panel-port.md](../../../roadmaps/dld-front-panel-port.md).
Details are here:

- **This file:** the GUI, the map from MATLAB features to HeLab, the detailed feature specs and the open decisions.
- [lib-scripts.md](lib-scripts.md): file by file, the GUI's own `lib/*.m` (the plots, fits and monitor helpers).
- [core-library.md](core-library.md): `lib/Core_BEC_Analysis` (import, raw → TXY reconstruction, FFT, bootstrap, masks, velocity).
- **Second look**, after Tony moved the submodule to branch `LaserMac-BECMachine-cloudstor` (2026-10-20):
  - [branch-update.md](branch-update.md): the submodule update and the front panel's changes (hot-spot mask, Yavin TOF fit, ghost-count diagnostics).
  - [core-update.md](core-update.md): Core's changes (g² correlations, BEC calculators, the 2023 converter edits).

  Where these differ from the sections below, **the second look wins**.

**How the review was done:**
- I read `dld_front_panel.m` and `pics/gui.png` myself.
- Two subagents (medium effort) read `lib/` and `Core_BEC_Analysis`.
- I spot-checked their main claims against the source:
  - `dld_plot_tof.m:11` multiplies by 1e-3, and lines 405–406 are the wrong condensate integrals.
  - `dld_avg_pos_plots.m:18` halves the bin count.
  - The two `txy_to_vel.m` copies disagree in sign, at line 41 of each.
- No code changed.

## The repo

- **Repo:** `HeBECANU/DLD_front_panel` at `10ae8ea` (last commit 2019-10-04). Its nested `Core_BEC_Analysis` is at `b8907f5` (2019-07-08).
- **Authors:** Bryce Henson, Jacob Ross, Roman Khakimov and Rob Dall.
- **Built with:** MATLAB GUIDE (`dld_front_panel.fig` + `.m`, 1407 lines).
- **Contents:** about 180 `.m` files. Most are vendored File Exchange code under `Core_BEC_Analysis/bin`.

## GUI walkthrough (`dld_front_panel.m`)

The screenshot (`pics/gui.png`) shows the defaults:

- **Read Data** (`pushbutton1_Callback`, `importdata` at 195–336).
  - **Inputs:** a path prefix (`…\dld_output\d`), the first file number and the number of files (1 and 10).
  - **Per file:**
    - With "Use TXY" on, it converts raw → `_txy_forc` when the TXY file is missing or older than the raw file (`dld_raw_to_txy`), then reads it.
    - It rotates XY by `rot_angle` (0.61 rad).
    - Files under 1000 hits count as "low files".
  - **Display:** Tot / Avg / SD of hits per file.
  - **Afterwards:** it auto-presses 1D Plot and 2D Plot (`auto_press_*` flags at 114–117).
  - **Stopping:** a Stop Import toggle on the same button.
- **Windowing** (`windowdata`, 1152–1174).
  - **The box:** x and y min/max in mm (±30), with a separate t window for the 1D view (0.4–0.5 s) and the 2D view (0.4–0.5 s).
  - **Counters:** "TOF window counts" and "2D window counts".
- **1D Plot** (`dld_plot_tof`).
  - **Profiles:** T (kHz/file), X and Y (m⁻¹/file), as Gaussian-smoothed histograms.
  - **Settings:** time bin 0.0001 and spatial bins 401.
  - **Options:** Fit (thermal Gaussian → T), Bimodal (TF + Gaussian → N0/N, T/Tc, Tc, N), FFT, log FFT and Hold zoom.
- **2D Plot** (`dld_2dplotter_window_a`): XY, XT and YT density images.
  - **Settings:** 201 bins, blur in bins, "Range comp." (counts^0.5), and viridis.
- **Point Cloud** (`plot_3d`, 911–955).
  - **Display:** a 3D scatter, capped at 200,000 points by random sampling. The title says what fraction is shown.
  - **Auto Rotate:** a timer runs a 200-frame camera path at 20 fps (`make_rot_timer`).
- **Avg Pos** (`dld_avg_pos_plots`): mean and SD of X and Y in each T bin, with an optional spectrum.
- **Monitor Run** (`monitor_files`, 633–844). It is a busy loop:
  - **Detecting files:** every 0.1–0.2 s it diffs `dir()` names and dates against the previous listing.
  - **Choosing files:** it keeps raw `d*.txt` files, or `_txy_forc` files when "Monitor TXY" is on.
  - **Waiting for the write:** `wait_till_written`, with a 1 s age for raw files and 4 s for TXY.
  - **Raw format check:** first line `5,…`, at most 15 chars per line, one comma.
  - **Reading:** it sets the GUI's file number to the new shot and presses Read Data with one file. So each new shot **replaces** the shown data; it doesn't accumulate.
  - **Size threshold:** files under `Low_Count_Size` MiB are skipped.
- **Constants** (105–112):
  - fall distance 0.848 m and fall time 0.416 s
  - trap frequencies 500 Hz radial and 50 Hz axial
  - g = 9.7961 (Canberra)
  - k_B, ħ, and m_He = 6.6464e-27 kg

  `hebec_constants` (Core) holds a second set, and `lib/Heconst.m` a third, cruder one (g = 9.8, m = 4/6e23/1000).
- **Known bugs** in its own header: an occasional monitor runtime bug, no-count windows, "idiot proof min max values".
  - `bug1.txt` is a crash in `windowdata` when a file had zero counts. The data was empty, not N×3, and the 1D plot ran anyway.

## Legacy features compared with HeLab

| Legacy | HeLab now | Gap |
|---|---|---|
| Read N files from a prefix and number | Folder browser, cached and incremental loads, shot selection (all / last N / range / from shot) | None; HeLab is far ahead |
| Monitor Run (each new shot replaces the view) | Live: checks with one stat, accumulates shots, plots follow | None; HeLab is far ahead |
| `wait_till_written`: age 1 s, plus a trailing `\n` (Core) | Settle age 5 s, plus a change-while-read check | Trailing-newline check not used (Tony's choice) |
| Raw → TXY conversion when the TXY is missing or older | Raw files are only counted and classed (`fixable`) | **Missing:** L4 / QC repair |
| XY rotation 0.61 rad | Not applied | Declined by Tony for transfer fractions (2026-10-20); ask before any use |
| Box window (t, x, y) shared by the views | Per-plot View range (auto-crop / manual) | Counts per shot ignore any window; no shared region |
| Circle masks (`masktxy_2d_circle`, Core) | None | **Missing:** hot-spot cut |
| Hits per file, Tot/Avg/SD, files under 1000 hits | Counts per shot plot | No mean ± SD; no low-count flag |
| T/X/Y smoothed histograms in rate units (kHz/file, m⁻¹/file) | T/X/Y histograms in counts, log Y, newest shot | Rate and per-shot normalisation; smoothing |
| Thermal Gaussian fit → T | None | **Missing** |
| Bimodal TF + Gaussian → N0/N, T/Tc, Tc, N | None | **Missing** (legacy math wrong; see below) |
| 2D XY / XT / YT density images | None (3D scatter only) | **Missing** |
| Point cloud, 200k cap, auto-rotate | 3D scatter (Plotly/Dash), 100k labelled sample, camera kept | Auto-rotate not needed |
| Average position and width vs T, with spectrum | None | **Missing** |
| FFT of the T profile (count-rate noise, pulse trains); summed TOF spectrum (`TOF_averaged`) | None | **Missing** |
| `txy_to_vel`: velocity per count (Core) | None (T, X, Y in s and m) | **Missing** |
| `bootstrap_se`, `sewm`, `string_value_with_unc` (Core) | None | Missing; small |
| File time per shot (`data_tcreate`) | mtime in fingerprints only (`DatasetView` fingerprints: shot, size, mtime ns) | Not exposed as a shot time |
| Autoconverter: moving mean ± std of counts, low-count sound | None | Missing; fits Live |
| `function_cache` (arguments MD5 → .mat) | Result caching R1, exact-match rules (R2 planned) | Nothing to take but a "load slower than recompute" hint |

## Legacy bugs a port must not copy

From the subagents' reports, spot-checked where marked ✓:

1. **Condensate fraction:** `dld_plot_tof.m:405–406` divides the amplitudes by the width instead of multiplying ✓. The areas should be:
   - TF `(1-u²)^p`: `A·R·√π·Γ(p+1)/Γ(p+3/2)`. That is `16/15·A·R` for p=2 and `3π/8·A·R` for p=3/2.
   - Gaussian: `B·√(2π)·σ`.

   So the legacy N0/N, T/Tc, Tc and N are wrong.
2. **TF exponent:** the T profile uses 3/2 (`bimod`, line 437). For a 3D TF profile integrated over both transverse axes, the exponent is 2. 3/2 is right for a profile integrated over one axis. `TC_and_below_tof_*` uses 2.
3. **Spatial temperature in `fit_condensate`:** it uses `vdet = 1/1000` while the data is in metres, so T is off by 10⁶.
4. **Bin width units:** `dld_plot_tof` multiplies the "Time bins (s)" field by 1e-3 (line 11 ✓); `dld_avg_pos_plots` doesn't.
5. **Average-position bins:** they come out about 2× wider than asked (`T_bin_num = round(N/2)+1`, line 18 ✓). Odd lengths crash the FFT, and empty bins make it all NaN.
6. **X/Y axes:** plotted as `centers*1e-3` but labelled mm (metres → mm needs ×1e3).
7. **FFT branch of the 1D plot:** it uses undefined variables, and applies a time sampling rate to spatial data.
8. **2D plot:**
   - The 2D Gaussian fit block can't run (undefined variables).
   - The bin area is off by one bin.
   - "Log scale" is really a square root.
9. **`txy_to_vel`:** the two copies have opposite signs for v_z (line 41 of each ✓). *Superseded:* on the new branch only the folder copy survives, now with the z-up sign, and its unchanged test fails ([core-update.md](core-update.md#corrections-to-the-first-review)). HeLab must define its own convention.
10. **Constants:** three inconsistent sets. `Heconst`'s `Helife = 1/(Γ·2π)` is wrong.
11. **Rate units:** `dld_plot_tof` divides T by the number of files ("kHz/File"), but X and Y are only divided by the bin width, though labelled "m⁻¹/File". This holds on the new branch too (checked against the source).
12. **The reconstruction's** `how_many_x == ~1` (Core `dld_read…:513`) means `== 0`. Reproduce or fix it knowingly when porting the converter.

## Feature plan in detail

The IDs match the roadmap document. Every plot is a `DatasetAnalysis` using the
shared Shots and View range settings. It follows Live under its `live_policy`,
says why it has nothing to draw (`helab/analysis/empty.py`) and records coverage.

### Shared foundation (F0)

- **`helab/analysis/physics.py`: one constants table.**
  - m_He = 4.002602 u = 6.6465e-27 kg (the legacy front panel had 6.6464e-27)
  - g = 9.796 m/s² (Canberra; the front panel had 9.7961, Core 9.7960207 − 78e-8)
  - k_B and ħ from `scipy.constants`
  - He* scattering length 7.512 nm (Moal 2006). Core's `hebec_constants` moved from 15 nm to this value in 2019, on the new branch.

  Lab parameters: fall time 0.416 s, fall distance 0.848 m (the front panel; Core now says 0.8587 m, i.e. 0.4187 s: **to confirm**), trap frequencies 500/50 Hz, and release time = trap switch-off − DLD trigger (22.954 − 20.3 s in the new front panel).
  - These change with the setup, so they should be app settings, under a "Lab constants" group with Restore default.
  - They should not live in each plot. Each result records the values it used.
- **`helab/analysis/fits.py`.**
  - `curve_fit` wrappers with bounds and initial guesses from moments, returning value ± SE (from the covariance).
  - A fit failure becomes a plot note, never an exception.
  - Models: Gaussian+offset, TF^p, bimodal with a shared centre, and later g_{5/2}.
- **`format_uncertainty(v, u)`:** `50.12 ± 0.15` or `8.5479(10)`, ported from Core's `string_value_with_unc`. Used in titles and dock lines.

### D1: Gaussian fit and temperature on the T/X/Y histograms

- **Where:** a Fit option (off by default) on "T, X, Y histograms". Alternatively a sibling "TOF fit" plot, if the histogram plot should stay fast; that is to decide.
- **Model:** `A·exp(-(x-μ)²/2σ²) + c`, fitted to the histogram over the View range.
- **Temperature:** the ideal-gas, pure-expansion approximation, which ignores the initial cloud size:
  - T axis: σ_z = g·t_f·σ_t (the arrival speed times the time spread), so σ_v = σ_z/t_f = g·σ_t. This matches the legacy `fit_thermal`.
  - X/Y axes: σ_v = σ_x / t_f.
  - Then `T = m·σ_v²/k_B`.
- **Display:** the fit curve on the histogram, and centre, σ and T each ± SE in the plot's line.
- **Tests:** synthetic Gaussian events at a known T recover T within the SE. Edge cases: empty, a single bin, all events in one bin.

### D2: Per-shot trends

- **What:** a "Shot trends" plot. For each chosen shot it shows:
  - counts in the window;
  - Gaussian centre and σ on T, X and Y;
  - T from D1.

  Each is plotted against shot number, or against shot time once D7 exists.
- **Overlays:** a moving mean ± std band (window N, like the autoconverter's `mov_mean_len`), and the mean ± SD of counts, like the legacy Tot/Avg/SD.
- **Low-count flag:** shots under a threshold are drawn in amber. During Live, an optional status note. (The legacy code beeped; HeLab shouldn't, unless Tony wants a sound.)
- **Speed:** reuses per-shot results across Live revisions where coverage allows (R1).

### D3: 2D density images XY / XT / YT

- **Drawing:** PyQtGraph `ImageItem` from `np.histogram2d`, normalised to density (m⁻², m⁻¹s⁻¹, or counts per shot).
- **Settings:** bins (default 201, or automatic), blur σ in bins (`scipy.ndimage.gaussian_filter`), range compression γ (1 = linear, 0.5 = legacy; also log), colour map viridis, and panels XY/XT/YT.
- **Axes:** mm and ms.
- **Live:** fast enough to follow Live; the newest shot can be highlighted as a contour, or in its own panel.
- **Why:** it complements the 3D scatter where QtWebEngine can't paint (Lab Side PC). PyQtGraph paints there.

### D4: Bimodal BEC fit

- **Model:** TF^p plus a Gaussian with a shared centre. p = 2 for T profiles and 3/2 for X/Y.
  - Bounds: R > 0, amplitudes ≥ 0.
  - Seeded from D1's Gaussian, with R starting at a fraction of σ.
- **Outputs**, all ± SE (bootstrap over shots once D10 exists):
  - N0/N, from the areas given under "Legacy bugs" above;
  - T, from the thermal width;
  - T/Tc = (1 − N0/N)^{1/3};
  - Tc;
  - N = (k_B·Tc / (0.94·ħ·ω̄))³ with ω̄ = 2π·(f_r²·f_a)^{1/3};
  - optionally μ and N0 from the TF radius and the scattering length (`TC_and_below_tof_b`).
- **Later:** a Bose-enhanced thermal part `A·g_{5/2}(exp(-u²))`, as a truncated sum (nmax 200) or `mpmath.polylog`.
- **Validation:** synthetic bimodal data with a known N0/N, plus a check on real BEC data with Tony before claiming results.

### D5: Mean position and width vs T

- **Computation:** for T bins of a set width (exactly that width), the mean and SD of X and Y in mm against T, with empty bins left as gaps.
- **Spectrum (optional):** of each trace, with `rfft`, a Hamming window, DC dropped and a log option.
- **Use:** atom-laser pointing and breathing, and sloshing.

### D6: Spectra of the T profile

- **Computation:** a fine T histogram (rate per shot), summed or averaged over the chosen shots, then an amplitude spectrum.
  - Method: `rfft` with `scipy.signal.get_window`, normalised as Core's `fft_tx` does (sum of the window = length, non-DC bins ×2), and zero padding.
  - Option: a Welch PSD.
- **Peaks:** listed above a threshold (`find_peaks`, minimum spacing) in a table or labels, like `dominant_freq_components` and `procFFT`.
- **Use:** pulse-train rate, mains or noise pickup, and trap frequencies from summed TOFs (`TOF_averaged`).
- **Uneven samples:** use Lomb–Scargle instead of Core's spline resample.

### D7: Shot times

- **Source:** the helper already has each TXY file's mtime in the fingerprints, so `DatasetView` gives a per-shot time from them. That costs no new I/O.
- **Raw file time:** the raw `d*.txt` time is closer to when the shot was taken (Core's `data_tcreate`), but needs one stat per raw file. Decide whether it's worth it.
- **Using it:** an option to plot per-shot plots (counts, D2) against wall-clock time, and gaps between shots (time since the previous one) to show stalls.
- **Caveat:** a copied or rewritten file has a new mtime. Say so in the tooltip.

### D8: Velocity / momentum view

- **Conversion:** `txy_to_vel` as a pure function. Inputs: release time, fall distance and g.
  - `t_f = T − t_release`
  - `v_z = ±(h/t_f − ½·g·t_f)`: the sign depends on whether z points down or up. The legacy copies used both. HeLab picks one, writes it down and tests it on analytic trajectories.
  - `v_x = X/t_f`, `v_y = Y/t_f`
- **Units:** m/s, or recoil velocity units with `v_r = h·f/(c·m)`, or ħk (1083 nm).
- **Where:** an axis option in the histograms, 2D images and scatter, so it isn't a new data format. The cache stays raw TXY.
- **Tests:** a port of `test_txy_to_vel.m` pins the sign.

### D9: Analysis region and masks

- **What:** a named region (a box plus circle masks that keep or cut, like `masktxy_2d_circle`) shared by every plot of a tab. Alternatively, a "Region" settings page that each plot can follow.
- **Counts per shot** then optionally counts inside the region (legacy "TOF window counts").
- **Hot spots:** circle cuts handle detector hot spots. This is relevant to the hot spot near the XY box's edge seen in transfer fractions.
- **Speed:** TXY files are sorted by T, so `np.searchsorted` gives the T window at O(log n) per shot.
- **Rotation:** none, unless Tony decides otherwise.

### D10: Uncertainties

- **Shot bootstrap:** resample shots for error bars on transfer fractions and fitted quantities, using `scipy.stats.bootstrap`. Core's subset-fraction diagnostics (`bootstrap_se`) only if wanted.
- **`sewm`:** the standard error of a weighted mean (Cochran), for count-weighted averages.

### D11: Raw → TXY converter

- **Algorithm:** port the 4-corner reconstruction used in production (`dld_raw_to_txy` calls `dld_read_5channels_reconst_multi_imp(file, 1,0,1,0)`). The full algorithm is in [core-library.md](core-library.md#raw-reconstruction).
  - 25 ps bins, tsum 3200 ± 200, the |x1+x2−y1−y2| < 400 check, unique partners within 36 rows, v_perp 5.2632e5 m/s, normalised to the first (trigger) row.
- **Where it runs:** in a helper (numba or vectorised).
- **Validation:** against existing `_txy_forc` files. Same count, values equal to 8 significant figures (`dlmwrite` precision 8).
- **Writing files:** only on the user's say, as a QC repair (`fixable` folders), or with Live L4 on the acquisition machine. Write to a temporary name and rename.
- **Same file:** `legacy/tdc_autoconverter`'s copy is byte-identical.

## Not worth porting

- XY rotation (declined).
- 3D auto-rotate.
- `wait_till_written` / `is_early`: HeLab's settle rules are stronger.
- `fileExists`.
- `function_cache`: R1/R2 are stricter.
- `fast_search_histogram` / `fast_sorted_mask`: use `np.searchsorted`.
- The `bin/` packages: numpy, scipy and pyqtgraph cover them.
- The `TC_and_below_*` / `tof_gauss_*` / `guassfun_*` a/b duplicates and `plot_pancake`: dead or hard-coded. Take their physics into D1/D4 instead.

## Proposed order

- **Batch 1:** F0 constants + fits, D1 (fit and T), D3 (2D images), D7 (shot times). These are independent, so one floor each could work. D1 and D4 share `fits.py`, so F0 lands first.
- **Batch 2:** D2 (trends), D9 (region and masks), D5/D6 (position and spectra).
- **Batch 3:** D4 (bimodal), D8 (velocity), D10 (bootstrap).
- **D11:** with Live L4 / QC.

## Open decisions (Tony)

1. **Lab constants:** app settings with defaults (fall time 0.416 s, trap 500/50 Hz, g 9.796, release time)? Or per plot? Which fall distance: 0.848 m or 0.8587 m? (Scattering length: 7.512 nm, as the library itself settled.)
2. **Histogram units:** counts (now), counts per shot, or rate per shot (kHz/shot, legacy "per file")? Should display axes be mm and ms?
3. **Fits:** a Fit option on the existing histogram plot, or separate plots?
4. **Temperature model:** pure expansion (legacy `fit_thermal`), or corrected for the initial cloud size `(1+ω²τ²)` (`TC_and_below`)?
5. **Regions:** shared per tab (D9), or each plot keeps its own View range?
6. **Low counts:** a threshold and how to flag it (colour or note; a sound?).
7. **Shot time:** the TXY file's mtime (free), or the raw file's (one stat per raw file)?
8. **Order:** which batch comes first, and whether the converter (D11) waits for L4.

## Tony's decisions (2026-10-20, Maestri orange thread)

> **The plan's [Decided section](../../../roadmaps/dld-front-panel-port.md#decided-tony-2026-10-20) is current.** The rounds below are history and are superseded where they differ. Examples: the fall distance is now 0.848 m, shot times use the raw file's mtime, and histogram rates are per shot.

- **Hardware has changed since the MATLAB code.** No hard-coded front panel or Core parameter is taken as given: tsums, v_perp, dead times, trap frequencies, switch-off/trigger times, hot spots, rotation, fall time. Each becomes a setting whose default is used only once Tony confirms it.
- **Fall distance: reopened.** Tony first chose 0.8587 m, then asked where it came from. I had overstated it as the library's settled value. It is one uncommented line in Core `hebec_constants.m:42` (Kieran Thomas, `8b4fa77`, 2019-11-07). It matches a 0.4187 s fall time (`find_dist_cen.m:33`, and the `0.418707` in `Momentum_Bells_test/lib/halo_vel_conv_legacy.m:33`, 2019-12).
  The other values in the legacy code:
  - 0.848 m: the front panel (`dld_front_panel.m:108`), and `Momentum_Bells_test/lib/monitor_halos.m:47` (touched 2024-06), where 0.852925545 is commented out;
  - 0.852925545 m: `Momentum_Bells_test/monitor_momentum.m:55` (since 2020-07) and `bec_interference.m:49` (2021-07), the newest use. That is a fall time of 0.4173 s at g = 9.796.

  Measure it on the current setup if possible (arrival time of atoms released at rest).
- **Velocities: z up, as on Earth.** Atoms fall towards −z.
  - `v_z = −h/t_f + ½|g|·t_f`. This is the surviving Core copy's sign. Its MATLAB test, which is z-down, isn't ported as is.
  - Check: an atom released at rest arrives at t_f = √(2h/g), and there v_z = −√(gh/2) + √(gh/2) = 0. ✓
  - Test on analytic trajectories.
- **Hot spots:** port the earlier presets (moved into the unrotated frame) as they are. The current detector needs its own preset, from a new **hot-spot finder (D15)**:
  - **Input:** XY counts per shot, preferably in T windows without atoms.
  - **Background:** a smoothed estimate (a median or Gaussian filter of the summed image).
  - **Spot test:** bins whose excess is well above the background noise (> k·√bg) in most shots, at the same place. Hot spots persist across shots; atom clouds move and vary.
  - **Output:** clusters of such bins become circles (centre, radius), with their excess and shot fraction, shown on the XY image to review. Accepted circles are saved as a D9 preset named after the detector.

## Tony's decisions, second round (2026-10-20, Maestri orange thread)

Still planning; nothing is built. They are recorded in the plan's "Decided"
section, which supersedes the D1–D15 details above where they differ:

- **Constants:** every constant can be set by hand. App-wide values go in a new Settings → **Lab parameters** tab. Each plot's settings can override them for that plot.
- **Histogram units:** counts and kHz per file, both selectable.
- **Fits:** port all of the old fit options, toggled in the plot settings on the histograms. This is not a separate plot, which reverses my recommendation.
- **Models:** port every one, selectable: Gaussian, arrival-time, both bimodal forms, Bose-enhanced, and cloud-size-corrected.
- **Shot times:** TXY mtime for now.
- **View range:** each plot keeps its own, defaulting to auto. The per-tab shared region (old D9) is dropped. D9 is now hot-spot masks per plot.
- **Low counts:** an opt-in system notification, built as the first of a general hooks mechanism (H1).
- **Hot-spot finder:** decided later. The plan carries the simplest placeholder: bins above a multiple of the summed XY image's median, offered as circles.

## Tony's decisions, third round (2026-10-20)

- **Defaults:** borrowed from the old repos for now, and marked unconfirmed. The table is in the plan.
  - Fall distance 0.852925545 m and fall time 0.417 s, from `Momentum_Bells_test` (`monitor_momentum.m:55` and `:39`). These are the newest and agree with each other: √(2·0.8529/9.796) = 0.4173 s.
  - Trap frequencies 500/50 Hz, switch-off 22.954 s and DLD trigger 20.3 s, from the front panel.
- **Axes:** X and Y in mm. T in ms or s, chosen automatically.
- **View range:** "auto" is the current auto-crop.
- **Low counts in Live:** two opt-in checkboxes, either or both: below an absolute count, and below a fraction of the mean of the recent N shots.
- **Hooks:** a note for code compatibility only; nothing is built this round. The old H1 item is dropped. Events go through one place so hooks can attach later.

## Borrowed defaults investigated (2026-10-20)

See [lab-parameters.md](lab-parameters.md) for every value's source, date and consistency.

**Corrections to earlier sections:**
- **Release time:** "trap switch-off − DLD trigger" from the front panel is out of date. The current code centres each shot on its BEC and uses arrival − fall time.
- **DLD trigger:** 20.5 s since 2023-09.
- **Fall distance:** monitor_halos changed to 0.848 m in 2024.
- **Rotation:** 0.93 rad since 2023-01, with the new detector plate.

**Low-count alert:** Tony set N = 100 recent shots.

## Review by the Ground assistant, with Tony's decisions (2026-10-20)

The plan's Decided section now records these:
- **Constants at three levels:**
  - Lab parameters in Settings: g, mass, scattering length, detector.
  - Folder settings in the store, keyed by data root: fall distance and time, release time, trap frequencies.
  - Plot overrides, with each value's source shown.

  Values are resolved when a run starts. Open: what open plots do when a value changes.
- **Shot times:** the raw `d*.txt` mtime, falling back to the TXY's and saying so.
- **Release time:** its own detection for a single cloud's arrival. Only the peak finding may be shared with Transfer fractions' order detection.
- **D12:** time budget, cancellation inside the pair loop and per-shot Live reuse are a to-do for when it is built.
- **D11:** the raw → TXY conversion moved to the TXY converter item (L4). D11 is now only the raw-pulse diagnostics, after that port.
- **Histogram rates:** the front panel's method, with its bug fixed (X/Y divided by the number of shots too). Smoothing is optional. Fits use unsmoothed counts by default.
- **Housekeeping:**
  - `.gitmodules` and AGENTS.md now name branch `LaserMac-BECMachine-cloudstor` (about 40 MB checked out).
  - The roadmap entry was fixed: one link, and the decision count corrected.
