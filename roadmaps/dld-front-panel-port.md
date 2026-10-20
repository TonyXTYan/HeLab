# Features from the DLD front panel

Horizon: near and medium term, after the plots v1. Added: 2026-10-20 from a review
of `legacy/DLD_front_panel` (the lab's MATLAB GUI, 2017–2023, branch
`LaserMac-BECMachine-cloudstor`, with its `Core_BEC_Analysis` library). F0,
D1–D10, D12, D14 and D15 were built on 2026-10-20 (see [Built](#built-2026-10-20));
D13's per-shot halo centring is not built, and D11 waits for the TXY converter.
Priority and completion: [overview](_readme.md).
Review, legacy bugs and the detailed specs:
[session notes](../.ai/sessions/2026-10-20-claude-dld-front-panel-review/notes.md).
Branches, merge order and what to check first:
[coordinator register](../.ai/sessions/2026-10-20-claude-dld-coordinator/register.md).

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
  | He* mass | He-4 atomic mass, 4.00260325413 u (proposed) × CODATA u | AME2020; the front panel had 6.6464e-27 kg |
  | ħ, k_B, u | CODATA, read-only | `scipy.constants` |
  | Scattering length (lab) | 7.512 nm | `hebec_constants` (Moal 2006) |
  | Trap frequencies (folder) | 500 Hz radial, 50 Hz axial (stale) | Front panel, 2017 only |
  | Trap axial axis along (folder) | 4 = in the XY plane, between X and Y (proposed; 1 = T, 2 = X, 3 = Y) | New: the trap's long axis is horizontal; the legacy 0.61 rad rotation suggests neither X nor Y. Sets the per-axis bimodal cap and which radius is axial |
  | Detector QE (lab) | 0.1 (proposed) | New: the legacy code has none; the figure usually quoted for He* MCP delay-line detectors. Calibrate it (BEC properties' "QE from R") |
  | Recoil wavelength λ (lab) | 1,083.331 nm, He* 2³S₁ → 2³P₂ (proposed) | NIST ASD, 276.7321865 THz. For ħk/m and 2ħk/m (one Bragg order); confirm the Bragg beams are on this line |
  | Release time t_r, arrival at rest t_a (folder) | Unset: from the data (shown "from the data"). The Release time plot's Use for this folder… saves t_a; plots take t_r = t_a − t_f with their own fall time. t_r can be set by hand | `halo_vel_conv.m` (BEC centre − fall time). The front panel's switch-off of 22.954 s is out of date |
  | Trap origin x₀, y₀ (folder) | Unset: detected (the cloud at rest's mean X, Y), else assumed (0, 0), said in amber | New; saved with t_a by Use for this folder… |
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
  - X and Y are counts / bin width / number of shots, per mm per shot (X and Y
    are in mm). The front panel labels them "m⁻¹/File" but never divides by the
    number of files: a legacy bug.

  In HeLab, smoothing is optional, with a default σ and bins of σ/5. Fits use the
  unsmoothed counts by default, and the smoothed curve only when chosen. This is
  a deliberate difference from the front panel, which fitted the smoothed curve.
- **Axis units:** X and Y in mm. T always in ms, never switching to s, in every
  axis, title, record and T setting, with "," thousands separators and "." for
  decimals whatever the locale: `1,234.5678 ms`. Stored values stay SI (s, m)
  (Tony, 2026-10-20).
- **Fits:** all the old GUI's fit options are ported, switched on and off in the
  plot's settings (on the T/X/Y histograms). Every model is ported and chosen in
  the plot's settings:
  - Gaussian (pure expansion);
  - the exact arrival-time ("Yavin") thermal profile on T;
  - the bimodal TF + Gaussian and TF + arrival-time models. Both TF exponents
    are offered, p = 2 (a full projection, as on the DLD's histograms) and p = 3/2
    (a thin slice), with the caveats in the model choice's tooltip (Tony,
    2026-10-20);
  - the Bose-enhanced g_{5/2} thermal part;
  - the cloud-size-corrected temperature.

  Formulas are taken from the physics, not copied from the MATLAB code (which
  has bugs).
- **Shot times:** the matching raw `d*.txt` file's mtime. The TXY's mtime is when
  it was converted, and a converter catching up gives many shots the same time.
  If the raw file is gone, use the TXY mtime and say so. Raw files are never
  rewritten, so a shot's raw file is stat'ed again only when its TXY fingerprint
  changes (Tony, 2026-10-20).
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

## Built (2026-10-20)

All on `agent/dld-front-panel-port`, one reviewed branch per task (list in the
[register](../.ai/sessions/2026-10-20-claude-dld-coordinator/register.md)). Each session's `handoff.md` and `notes.md`
has the design, derivations, proposals and on-screen checks; the checks are
collected in the [manual to-do](../.ai/MANUAL_TODO.md#dld-front-panel-port-added-2026-10-20).

- **F0** ([f0a](../.ai/sessions/2026-10-20-claude-dld-f0a/handoff.md), [f0b](../.ai/sessions/2026-10-20-claude-dld-f0b/handoff.md),
  [store fixes](../.ai/sessions/2026-10-20-claude-dld-store-fixes/handoff.md)): the constants table
  (`helab/analysis/physics.py`); Settings → Lab parameters; folder constants in the
  store (`folder_constants`, right-click › Folder constants…), inherited by subfolders
  up to the data root; plot overrides (`constant_layers.py`); resolved at submit,
  recorded, and plots marked "constants changed" when a lab or folder value changes.
  `fits.py` (bounded fits ± SE, Poisson likelihood) and `estimates.py`.
- **D1** ([d1](../.ai/sessions/2026-10-20-claude-dld-d1/handoff.md), [decisions](../.ai/sessions/2026-10-20-claude-dld-decisions/handoff.md),
  [physics fixes](../.ai/sessions/2026-10-20-claude-dld-physics-fixes/handoff.md)): a Fits page on the T, X, Y
  histograms, off by default (Gaussian, arrival-time thermal profile, bimodal TF² or
  TF^3/2 + Gaussian), counts or a rate per shot, optional smoothing; ms/mm everywhere
  with grouped digits (`display_units.py`, `plot_axes.GroupedAxis`).
- **D2** ([d2](../.ai/sessions/2026-10-20-claude-dld-d2/handoff.md)): Shot trends (per-shot counts, centre, width and
  temperature, moving mean ± SD, low-count flags, Notify during Live) and the events
  hub (`helab/utils/events.py`) that hooks will attach to.
- **D3** ([d3](../.ai/sessions/2026-10-20-claude-dld-d3/handoff.md)): Density images XY / XT / YT.
- **D4, D14** ([numerics](../.ai/sessions/2026-10-20-claude-dld-d4-d14/handoff.md), [wiring](../.ai/sessions/2026-10-20-claude-dld-d4-wiring/handoff.md)):
  Bose g_5/2 and bimodal TF + Bose fits with a condensate decision, per-axis caps,
  Show BEC properties (N, N0/N, T, Tc, T/Tc, μ, R(0), n0, two QE checks).
- **D5, D6** ([d5-d6](../.ai/sessions/2026-10-20-claude-dld-d5-d6/handoff.md)): Mean X, Y against T with a spectrum;
  T spectrum with a peak list.
- **D7** ([d7](../.ai/sessions/2026-10-20-claude-dld-d7/handoff.md)): shot times from the raw files through the helper,
  the cache (`datasets.raw_times`) and `DatasetView`; the Shot times plot.
- **D8** ([numerics](../.ai/sessions/2026-10-20-claude-dld-d8-d10/handoff.md), [release time](../.ai/sessions/2026-10-20-claude-dld-d8-release/handoff.md),
  [velocity](../.ai/sessions/2026-10-20-claude-dld-d8-velocity/handoff.md)): `velocity.py`, `release.py`, `peaks.py`;
  the Release time plot (Use for this folder… saves t_a and the trap origin) and
  Velocity distributions.
- **D9, D15** ([d9-d15](../.ai/sessions/2026-10-20-claude-dld-d9-d15/handoff.md)): a Mask group on every event plot
  (presets and custom circles) and the placeholder finder (Density images › Find hot
  spots, Copy circles).
- **D10** ([d8-d10](../.ai/sessions/2026-10-20-claude-dld-d8-d10/handoff.md)): `bootstrap.py` (shot bootstrap,
  `shot_means`), used by Release time and the g² errors.
- **D12** ([numerics](../.ai/sessions/2026-10-20-claude-dld-d12-numerics/handoff.md)): `correlations.py` (1D and radial
  g², collinear and back-to-back, in-shot over between-shot pairs, free baseline,
  bootstrap and jackknife errors, `PairCounts` for Live, time budget, cancellation).
  TODO(docs): the Correlations plot (`agent/dld-d12-plot`), once merged.
- Shared: [polish](../.ai/sessions/2026-10-20-claude-dld-polish/handoff.md) (wrapped titles, one amber, in-place updates).

Left to do on what is built:
- D13: per-shot halo centring ("Re-centre each shot" stands in).
- Fits the Decided list names that nothing offers yet: bimodal TF + arrival-time on
  T, a Bose arrival-time profile; the cloud-size-corrected temperature (negligible
  here: 1 + 6·10⁻⁵ at 50 Hz after 0.416 s).
- Velocity axes on the histograms and density images (one helper lifted from
  Velocity distributions into `release.py`, [d8-velocity](../.ai/sessions/2026-10-20-claude-dld-d8-velocity/handoff.md)).
- Shot-bootstrap error bars on the histograms' fits and BEC properties (opt-in,
  `bec.FIT_N_BOOT`) and on Shot trends.
- Folder constants for a tab's top folder (a File menu item, like Place
  .helab-root…), a Folder details section for them, and a drop-down for the coded
  Trap axial axis row.
- Transfer fractions' peak finding onto `peaks.py`, checked by its MATLAB tests.
- Mean position's legends cover the traces at narrow widths (a key line, as Shot
  times has).

## Features

Each feature is a `DatasetAnalysis` (or an option on one) that uses the shared
Shots settings and its own View range, and follows Live. Legacy formulas are
checked before they are ported. Several are wrong in the MATLAB code
(condensate fraction, units, signs): see the
[session notes](../.ai/sessions/2026-10-20-claude-dld-front-panel-review/notes.md#legacy-bugs-a-port-must-not-copy).

| ID | Feature | From |
|---|---|---|
| F0 | Shared base: constants at three levels (Settings → Lab parameters; folder settings in the store by data root; plot overrides, with each value's source shown), resolved when a run starts. Bounded fits returning value ± SE, ± formatting, pooled mean and SD. **Built.** | `dld_front_panel.m`, `hebec_constants`, `string_value_with_unc`, `pooled_mean_and_std` |
| D1 | Fits on the T/X/Y histograms, toggled in the plot's settings, with a selectable thermal model: centre, width, temperature. Units: counts or rate per shot (T in kHz, X/Y per mm), optional smoothing; fits on unsmoothed counts by default. **Built.** | `dld_plot_tof` `fit_thermal`, Yavin model |
| D2 | Shot trends: counts in the View range, fitted or threshold-edge centre/width/T per shot, moving mean ± SD. Low counts flagged; opt-in system notification in Live (below a count, and/or below a fraction of the recent N shots' mean). **Built.** | Read Data's Tot/Avg/SD, autoconverter, `find_dist_cen` |
| D3 | 2D density images XY / XT / YT in PyQtGraph: bins, blur, range compression in the colour map (the data stays linear). **Built.** | `dld_2dplotter_window_a`, `nonlinear_colormap` |
| D4 | Bimodal BEC fits on the histograms: every model selectable, giving N0/N, T, T/Tc, Tc and N. **Built** (TF + arrival-time not yet). | `fit_condensate`, `TC_and_below_tof` |
| D5 | Mean position and width of X/Y against T, with a spectrum. **Built.** | `dld_avg_pos_plots` |
| D6 | Spectrum of the T profile summed over shots, with a peak list (pulse rate, noise, trap frequencies). **Built.** | 1D FFT, `TOF_averaged`, `fft_tx` |
| D7 | Shot times from the raw `d*.txt` files' mtimes (the TXY's when the raw file is gone, said so); per-shot plots against time, gaps between shots. **Built.** | `data_tcreate` |
| D8 | Velocity/momentum axes, z up (release time, fall distance; m/s or recoil units). Release time detected automatically from one cloud's arrival, or set by hand. **Built:** Release time and Velocity distributions plots. | `txy_to_vel`, `halo_vel_conv` |
| D9 | Hot-spot masks per plot: circles that keep or cut, from presets (the earlier detector's, moved to HeLab's unrotated frame; the current detector's from D15). **Built** (the current detector's preset is empty). | `masktxy_2d_circle`, `hotspot_mask` |
| D10 | Error bars by resampling shots (bootstrap), standard error of a weighted mean. **Built**; error bars on fits and trends to do. | `bootstrap_se`, `sewm` |
| D11 | Raw-pulse diagnostics: time sums, corner differences, pulse spacing, ghost counts. Needs HeLab to load raw `d*.txt` files (scripts still do no I/O), so it comes after the TXY converter port. The conversion itself is not in this plan. Not started. | `ghost_counts_analysis`, `pulse_corrs` |
| D12 | g² correlations, collinear: 1D-windowed and radial, in velocity space; in-shot over between-shot pairs, Gaussian fit, shot bootstrap errors. To do when built: a time budget, cancellation inside the pair loop, and per-shot reuse in Live. Numerics **built**; the plot is being finished. | `correlations/calc_any_g2_type`, `corr_1d_cart`, `corr_radial` |
| D13 | Back-to-back correlations for halos (needs per-shot halo centring). Back-to-back pairs built in D12; per-shot halo centring not built. | `correlations` BB modes, `Momentum_Bells_test` |
| D14 | BEC properties beside D4: Tc (ideal, finite-size, interacting), μ, TF radii, peak density, from N and the trap frequencies. **Built.** | `bec_cals/bec_properties` |
| D15 | Hot-spot finder. First a placeholder (bins above a multiple of the summed XY image's median, offered as circles); the real finder is designed later on data from the current detector. Placeholder **built**. | new; feeds D9 |

## Proposed order

1. Built 2026-10-20: F0, then D1, D3 and D7; D2, D9 with the D15 placeholder, D5
   and D6; D4 with D14, D8 and D10; D12's numerics.
2. D12's Correlations plot (being finished), then D13's per-shot halo centring.
3. The left-to-do items under Built, after Tony's on-screen and real-data checks.
4. D11, after the TXY converter port ([Live L4](live-monitoring.md#stages)).

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

Each was built as proposed, so answering means confirming it or asking for a
change. Reasons and measurements are in the linked notes.

Lab values and constants:
1. Borrowed defaults: measure the fall distance (0.848 m for now) and give the
   current trap frequencies (500/50 Hz, stale).
2. Detector QE 0.1, lab level and unconfirmed; calibrate with BEC properties'
   "QE from R" ([d4-d14](../.ai/sessions/2026-10-20-claude-dld-d4-d14/notes.md#constants-choices-for-tony)).
3. Trap axial axis "between X and Y" (code 4); a third trap frequency only if the
   radial trap is anisotropic ([d4-d14](../.ai/sessions/2026-10-20-claude-dld-d4-d14/notes.md#constants-choices-for-tony)).
4. Recoil wavelength 1,083.331 nm (2³S₁ → 2³P₂) with 2ħk/m as one Bragg order:
   confirm the Bragg beams are on this line ([d8-velocity](../.ai/sessions/2026-10-20-claude-dld-d8-velocity/notes.md#proposed-for-tony)).
5. He* mass = He-4 atomic mass, 4.00260325413 u, not the standard atomic weight
   ([f0a](../.ai/sessions/2026-10-20-claude-dld-f0a/notes.md)).
6. A hand-set fall time counts only at the fall distance's layer or a more specific
   one, a disagreement with √(2h/g) over 0.1 % is noted, and velocities then use
   h_eff = ½ g t_f² ([f0a](../.ai/sessions/2026-10-20-claude-dld-f0a/notes.md), [d8-d10](../.ai/sessions/2026-10-20-claude-dld-d8-d10/notes.md)).
7. Open plots when a lab or folder value changes: amber "constants changed (…):
   Rerun to use them"; Rerun or the next Live run uses the new values
   ([f0b](../.ai/sessions/2026-10-20-claude-dld-f0b/notes.md#open-decision-5-proposed-as-suggested)).
8. Folder constants inherit up to the data root; the newest `set_at` wins, so after
   the clock steps back a new choice can lose silently (as for flags); quitting
   waits for flags and constants being written; flags should also wait for a
   verified volume ([f0b](../.ai/sessions/2026-10-20-claude-dld-f0b/notes.md#inheritance-proposed),
   [store fixes](../.ai/sessions/2026-10-20-claude-dld-store-fixes/notes.md#judgement-calls-proposed-for-tony)).
9. "It's a copy…" gives one side a new UUID, which starts without folder constants:
   copy them over? (no proposal; [f0b](../.ai/sessions/2026-10-20-claude-dld-f0b/handoff.md#for-tony)).

Fits and statistics:
10. Poisson maximum likelihood by default (plain √n weights bias widths low)
    ([f0a](../.ai/sessions/2026-10-20-claude-dld-f0a/notes.md#weights-poisson-likelihood-by-default-proposed-for-tony)).
11. Offset ≥ 0 on raw counts (slightly low σ when the true background is 0)
    ([physics fixes](../.ai/sessions/2026-10-20-claude-dld-physics-fixes/handoff.md#for-tony-proposed)).
12. The bimodal R/σ_th cap per axis from μ/k_BT ≤ 2, with a "TF radius at its
    limit" note; offer μ/k_BT max as a setting for deep condensates
    ([d4-d14](../.ai/sessions/2026-10-20-claude-dld-d4-d14/notes.md)).
13. Condensate decision: free-z Bose fit beside the bimodal, Δχ² ≥ 9 (saturated) or
    ≥ 25, plus the plausibility checks; z = 1 fixed in the bimodal's Bose part
    ([d4-d14](../.ai/sessions/2026-10-20-claude-dld-d4-d14/notes.md#review-fixes-physics-review-via-the-coordinator)).
14. BEC properties: the automatic axis choice, the header's contents, explanatory
    notes in the record only, trap rows shown with any bimodal fit
    ([d4-wiring](../.ai/sessions/2026-10-20-claude-dld-d4-wiring/notes.md#proposed-for-tony)).
15. Histograms: fits as an option, off by default; "Only events inside all three
    ranges" off; smoothing σ_T 0.1 ms, σ_XY 0.2 mm; a smoothed-curve fit smooths
    the model too and is refused above a fifth of the range; no launch velocity in
    the arrival-time model ([d1](../.ai/sessions/2026-10-20-claude-dld-d1/notes.md#choices-proposed-for-tony)).
16. Bootstrap: 1000 resamples, seed 0, 68.27 % percentile interval, not BCa
    ([d8-d10](../.ai/sessions/2026-10-20-claude-dld-d8-d10/handoff.md#for-tony-proposed)).
17. Uncertainties written `(416.12 ± 0.12) ms`, or `12.3(12)` CODATA style
    ([f0a](../.ai/sessions/2026-10-20-claude-dld-f0a/handoff.md#for-tony-proposed)).

Release time and velocities:
18. Release time: the arrival-time fit first (Gaussian, then the mean, as noted
    fallbacks), "unsure" at a second peak ≥ 50 %, at least 50 events, wide-cloud
    skew noted not corrected ([d8-d10](../.ai/sessions/2026-10-20-claude-dld-d8-d10/notes.md),
    [physics fixes](../.ai/sessions/2026-10-20-claude-dld-physics-fixes/notes.md)).
19. Release time plot: 100 resamples; Live reruns skip the bootstrap (said); Use for
    this folder… saves t_a and the origin to the plotted folder, Cancel the default
    when unsure; a t_r by hand wins a tie ([d8-release](../.ai/sessions/2026-10-20-claude-dld-d8-release/handoff.md#for-tony-proposed)).
20. Trap origin: unset → detected (robust window about the median) → assumed
    (0, 0) in amber; x₀ without y₀ is no origin
    ([physics fixes](../.ai/sessions/2026-10-20-claude-dld-physics-fixes/handoff.md#for-tony-proposed)).
21. Velocities in TXY column order (v_z, v_x, v_y); Velocity distributions in mm/s by
    default, each histogram over 99 % of its velocities
    ([d8-velocity](../.ai/sessions/2026-10-20-claude-dld-d8-velocity/notes.md#proposed-for-tony)).

Plots:
22. Live waits: 2 s for the histograms (with or without fits), Density images, Mean
    X, Y and T spectrum; 5 s for Release time, Velocity distributions and
    Correlations; the rest every shot. One rule for all? ([polish](../.ai/sessions/2026-10-20-claude-dld-polish/notes.md),
    [d4-wiring](../.ai/sessions/2026-10-20-claude-dld-d4-wiring/notes.md)).
23. Text rule: positions to 9 significant digits and at most 4 decimals, widths to
    4 significant digits; the DLD trigger shown in ms
    ([decisions](../.ai/sessions/2026-10-20-claude-dld-decisions/notes.md)).
24. Density images: one plot with a Projection choice, T across in XT/YT, square
    automatic bins on XY, blur capped at a quarter of the image, the newest shot as
    a contour ([d3](../.ai/sessions/2026-10-20-claude-dld-d3/notes.md)).
25. Spectra: Hann window, power = amplitude², the bins' sinc correction, peaks at
    ≥ 4× the median prominence, automatic bins (~100 events per T bin for D5, ~10
    for D6), gaps filled up to 20 %, SD only
    ([d5-d6](../.ai/sessions/2026-10-20-claude-dld-d5-d6/notes.md#choices-proposed-for-tony)).
26. Shot times: shots without events drawn at 0; caches from before D7 gain times
    only on a listing check ([d7](../.ai/sessions/2026-10-20-claude-dld-d7/notes.md#proposed-for-tony)).
27. Shot trends: threshold edges by default (a Gaussian fit costs ~45 ms per shot);
    the low-count defaults 50 events and 50 % of the last 100 shots, ORed; one window
    N; the box rounded out and kept; only the newest shot notifies, at most once a
    minute per folder; Live errors without a desktop notification
    ([d2](../.ai/sessions/2026-10-20-claude-dld-d2/notes.md#proposed-for-tony)).
28. Masks: unreadable circles fail the run; keep circles ANDed and the lab's
    boundary; preset names; a later "use as this plot's mask" button
    ([d9-d15](../.ai/sessions/2026-10-20-claude-dld-d9-d15/notes.md#rules-choices-proposed-for-tony-where-marked)).
29. The real hot-spot finder (D15), on data from the current detector; the
    placeholder's rule and defaults (σ 1 mm, 0.01 false spots per image, 20 events)
    meanwhile ([d9-d15](../.ai/sessions/2026-10-20-claude-dld-d9-d15/notes.md#d15-placeholder-finder)).
30. g² numerics: free baseline, the 1D window as a half-width per transverse axis,
    banded reference off; a cloud-matched reference later; a larger simulation for
    the ~0.8 % high g²(0) ([d12-numerics](../.ai/sessions/2026-10-20-claude-dld-d12-numerics/notes.md)).
    TODO(docs): the Correlations plot's proposals (kept detection within its SE,
    settings in mm/s, defaults), once `agent/dld-d12-plot` merges.
31. Titles renamed, group names kept ([polish](../.ai/sessions/2026-10-20-claude-dld-polish/notes.md#8-naming-titles-only-keys-unchanged-so-saved-settings-stay-valid)).
32. Hooks: which events and actions, when they are built (a later round); the hub
    (`helab/utils/events.py`) is ready for them.
