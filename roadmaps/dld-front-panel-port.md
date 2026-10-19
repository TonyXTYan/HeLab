# Features from the DLD front panel

Horizon: near and medium term, after the plots v1. Added: 2026-10-20 from a review
of `legacy/DLD_front_panel` (the lab's MATLAB GUI, 2017–2023, branch
`LaserMac-BECMachine-cloudstor`, with its `Core_BEC_Analysis` library). Planning
only: nothing is built yet. Priority and completion: [overview](_readme.md).
Review, legacy bugs and the detailed specs:
[session notes](../.ai/sessions/2026-10-20-claude-dld-front-panel-review/notes.md).

## What HeLab already covers

HeLab is already ahead of the old GUI in these areas:

| Old GUI | HeLab |
|---|---|
| Read Data (a path prefix plus a file count) | Browsing, caching, shot selection |
| Monitor Run (each new shot replaced the view) | Live |
| `wait_till_written` | Settle rules |
| Point Cloud | 3D scatter |
| `function_cache` | Result caching |

The old GUI's XY rotation (0.61 rad; 0.93 rad on the newest branch) is left out,
by Tony's decision (2026-10-20). Ask him before using it anywhere.

## Decided (Tony, 2026-10-20)

- **Legacy hardware parameters are not taken as given.** The detector, trap and
  timing have changed since the MATLAB code was written. Every hard-coded value
  in it is a starting point to confirm, not a default:
  - tsums, v_perp and the dead time;
  - trap frequencies, switch-off and trigger times;
  - hot spots and rotation.
- **Constants at three levels; every one can be set by hand.**
  1. **Lab parameters** (Settings, app-wide), for values that normally never
     change: g, the He* mass, the scattering length, the detector.
  2. **Folder settings**, per experiment or folder, for values that can change
     from folder to folder: the fall distance and time, the release time, the
     trap frequencies and the like.
     - They are kept in HeLab's own store, keyed by the folder's data root (like
       the Don't cache flags), never as a file next to the data.
  3. **Plot overrides.** A plot uses the lab and folder values by default and can
     override any of them in its own settings. Each plot shows where each value
     comes from (lab, folder or this plot).

  Compute does no I/O, so a run resolves the effective values when it starts.
  They go in with the run's parameters and are recorded in the result.
- **Defaults are borrowed from the legacy repos for now**, marked unconfirmed:

  | Parameter | Default | Source |
  |---|---|---|
  | Fall distance | **0.848 m** (Tony, 2026-10-20) | `Momentum_Bells_test/lib/monitor_halos.m` (Yogesh, 2024-06) and the front panel. `monitor_momentum.m` still has 0.852925545 m |
  | Fall time | √(2h/g) = 0.4161 s, derived from the distance unless set by hand | The legacy scripts' 0.417 s went with 0.8529 m |
  | g | 9.79602 m/s² | Canberra (`hebec_constants`) |
  | He* mass, ħ, k_B | CODATA | `scipy.constants` |
  | Scattering length | 7.512 nm | `hebec_constants` (Moal 2006) |
  | Trap frequencies | 500 Hz radial, 50 Hz axial (stale) | Front panel, 2017 only |
  | Release time | From the data: one cloud's arrival − fall time (see below); manual alternative | `halo_vel_conv.m` (BEC centre − fall time). The front panel's switch-off of 22.954 s is out of date |
  | DLD trigger, acquisition | 20.5 s, 2 s (shown only, and used to flag incomplete shots) | `monitor_momentum.m`, 2023–2026 |

  Sources, dates and consistency checks:
  [lab-parameters.md](../.ai/sessions/2026-10-20-claude-dld-front-panel-review/lab-parameters.md).

- **Fall distance candidates.** The value had no source in the code: 0.8587 m
  was chosen, then reopened the same day. The candidates in
  the legacy code are:
  - 0.848 m: the front panel, and `Momentum_Bells_test/lib/monitor_halos.m`
    (touched 2024);
  - 0.8587 m: Core `hebec_constants`, an uncommented line (2019). It matches
    the 0.418707 s fall time in `halo_vel_conv_legacy.m`;
  - 0.852925545 m: `Momentum_Bells_test/monitor_momentum.m` (2020) and
    `bec_interference.m` (2021), the newest use.

  Best measured from the data: the arrival time of atoms released at rest.
- **Velocities: z up, as on Earth.** Atoms fall towards −z, and gravity is −|g| ẑ.
- **Release-time detection:** not every run has orders 0, ±1, ±2, so the release
  time gets its own automatic detection, for a single cloud of atoms (one
  cloud's arrival in T). It stays separate from Transfer fractions' order
  detection, which Tony will describe later. The two could share the peak
  finding in the T histogram, but nothing else.
- **Histogram units:** counts, or a rate per shot, chosen in the plot's
  settings. The rate follows the front panel's method (`lib/dld_plot_tof.m`,
  Core `smooth_hist.m`) with its bug fixed:
  - the box and T window are applied first;
  - the front panel's "bin size" is a Gaussian smoothing σ, with bins of σ/5
    (`bin_factor` 5), and the counts are smoothed with that Gaussian;
  - T is counts / bin width / number of shots, in kHz per shot (the front
    panel's "kHz/File");
  - X and Y are counts / bin width / number of shots, per m per shot. The front
    panel labels them "m⁻¹/File" but never divides by the number of files: a
    legacy bug.

  In HeLab, smoothing is optional, with a default σ and bins of σ/5. Fits use the
  unsmoothed counts by default, and the smoothed curve only when chosen. This is
  a deliberate difference from the front panel, which fitted the smoothed curve.
- **Axis units:** X and Y in mm. T in ms or s, chosen automatically from its
  range.
- **Fits:** all the old GUI's fit options are ported, switched on and off in the
  plot's settings (on the T/X/Y histograms). Every model is ported and chosen in
  the plot's settings:
  - Gaussian (pure expansion);
  - the exact arrival-time ("Yavin") thermal profile on T;
  - the bimodal TF + Gaussian and TF + arrival-time models, with the TF exponent
    for each projection;
  - the Bose-enhanced g_{5/2} thermal part;
  - the cloud-size-corrected temperature.

  Formulas are taken from the physics, not copied from the MATLAB code (which
  has bugs).
- **Shot times:** the matching raw `d*.txt` file's mtime. The TXY's mtime is when
  it was converted, and a converter catching up gives many shots the same time.
  If the raw file is gone, use the TXY mtime and say so.
- **View range:** every plot keeps its own, defaulting to the current
  auto-crop. There is no region shared per tab.
- **Low counts:** an opt-in system notification during Live, with two checkboxes
  (either or both):
  - fewer than an absolute count (proposed: 50, the current monitor's `num_lim`);
  - below a fraction of the mean of the last N shots. N defaults to 100 (Tony);
    the fraction is proposed at 50 %.
- **Raw → TXY conversion is not in this plan.** It belongs to the TXY converter
  port (`tdc_autoconverter`, [Live L4](live-monitoring.md#stages), the "TXY
  converter" item in the [overview](_readme.md)): one converter, writing to a
  temporary name and renaming. The legacy code's two reconstruction variants
  (2019, and 2023 with an x1 dead time and separate tsums) and the check that
  existing `_txy_forc` files are reproduced are noted there.
- **Hooks:** a note for code compatibility only; nothing is built for them in this
  round. Code that raises such events (a low-count shot, Live errors) should
  send them through one place, so hooks (sounds, scripts, remote notices) can
  attach later.
- **Hot spots:**
  - Port the earlier detector's presets as they are, moved into HeLab's
    unrotated frame.
  - The current detector gets its own preset.
  - The real hot-spot finder (D15) is designed later. The first version is the
    simplest placeholder: sum the XY image over the chosen shots and flag bins
    above a multiple of the image's median. It offers them as circles to review.

## Features

Each feature is a `DatasetAnalysis` (or an option on one) that uses the shared
Shots settings and its own View range, and follows Live. Legacy formulas are
checked before they are ported. Several are wrong in the MATLAB code
(condensate fraction, units, signs): see the
[session notes](../.ai/sessions/2026-10-20-claude-dld-front-panel-review/notes.md#legacy-bugs-a-port-must-not-copy).

| ID | Feature | From |
|---|---|---|
| F0 | Shared base: constants at three levels (Settings → Lab parameters; folder settings in the store by data root; plot overrides, with each value's source shown), resolved when a run starts. Bounded fits returning value ± SE, ± formatting, pooled mean and SD | `dld_front_panel.m`, `hebec_constants`, `string_value_with_unc`, `pooled_mean_and_std` |
| D1 | Fits on the T/X/Y histograms, toggled in the plot's settings, with a selectable thermal model: centre, width, temperature. Units: counts or rate per shot (T in kHz, X/Y per m), optional smoothing; fits on unsmoothed counts by default | `dld_plot_tof` `fit_thermal`, Yavin model |
| D2 | Shot trends: counts in the View range, fitted or threshold-edge centre/width/T per shot, moving mean ± SD. Low counts flagged; opt-in system notification in Live (below a count, and/or below a fraction of the recent N shots' mean) | Read Data's Tot/Avg/SD, autoconverter, `find_dist_cen` |
| D3 | 2D density images XY / XT / YT in PyQtGraph: bins, blur, range compression in the colour map (the data stays linear) | `dld_2dplotter_window_a`, `nonlinear_colormap` |
| D4 | Bimodal BEC fits on the histograms: every model selectable, giving N0/N, T, T/Tc, Tc and N | `fit_condensate`, `TC_and_below_tof` |
| D5 | Mean position and width of X/Y against T, with a spectrum | `dld_avg_pos_plots` |
| D6 | Spectrum of the T profile summed over shots, with a peak list (pulse rate, noise, trap frequencies) | 1D FFT, `TOF_averaged`, `fft_tx` |
| D7 | Shot times from the raw `d*.txt` files' mtimes (the TXY's when the raw file is gone, said so); per-shot plots against time, gaps between shots | `data_tcreate` |
| D8 | Velocity/momentum axes, z up (release time, fall distance; m/s or recoil units). Release time detected automatically from one cloud's arrival, or set by hand | `txy_to_vel`, `halo_vel_conv` |
| D9 | Hot-spot masks per plot: circles that keep or cut, from presets (the earlier detector's, moved to HeLab's unrotated frame; the current detector's from D15) | `masktxy_2d_circle`, `hotspot_mask` |
| D10 | Error bars by resampling shots (bootstrap), standard error of a weighted mean | `bootstrap_se`, `sewm` |
| D11 | Raw-pulse diagnostics: time sums, corner differences, pulse spacing, ghost counts. Needs HeLab to load raw `d*.txt` files (scripts still do no I/O), so it comes after the TXY converter port. The conversion itself is not in this plan | `ghost_counts_analysis`, `pulse_corrs` |
| D12 | g² correlations, collinear: 1D-windowed and radial, in velocity space; in-shot over between-shot pairs, Gaussian fit, shot bootstrap errors. To do when built: a time budget, cancellation inside the pair loop, and per-shot reuse in Live | `correlations/calc_any_g2_type`, `corr_1d_cart`, `corr_radial` |
| D13 | Back-to-back correlations for halos (needs per-shot halo centring) | `correlations` BB modes, `Momentum_Bells_test` |
| D14 | BEC properties beside D4: Tc (ideal, finite-size, interacting), μ, TF radii, peak density, from N and the trap frequencies | `bec_cals/bec_properties` |
| D15 | Hot-spot finder. First a placeholder (bins above a multiple of the summed XY image's median, offered as circles); the real finder is designed later on data from the current detector | new; feeds D9 |

## Proposed order

1. F0, then D1, D3 and D7. These are independent; one floor each.
2. D2, D9 with the D15 placeholder, D5 and D6.
3. D4 with D14, D8 and D10.
4. D12, then D13 (they need D8, D9 and D10).
5. D11, after the TXY converter port ([Live L4](live-monitoring.md#stages)).

## Acceptance

- Each fit or derived number is checked on synthetic data with known values,
  then on real lab data with Tony, before it is called a result
  ([specialist analyses](reproducible-workflows.md#specialist-analyses)).
- Empty shots, empty windows and failed fits give a note on the plot, never a
  crash. The old GUI's `bug1.txt` crash came from an empty window.
- Results record the constants and lab settings they used, including per-plot
  overrides.
- D12 recovers g²(0) = 2 on a simulated thermal source and the expected peak on
  simulated pairs.

## Open decisions

1. Confirm the borrowed defaults on the current setup: measure the fall
   distance when possible (0.848 m for now), and give the current trap frequencies.
2. The low-count defaults: 50 counts and 50 % (proposed).
3. The real hot-spot finder (thresholds, shots, T windows without atoms), on
   data from the current detector.
4. Hooks: which events and actions, when they are built (a later round).
5. What open plots do when a lab or folder value changes. Suggested: mark them
   changed, and rerun on Rerun or the next Live update.
