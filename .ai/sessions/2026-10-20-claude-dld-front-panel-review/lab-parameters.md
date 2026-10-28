# Borrowed default lab parameters: where each comes from

Tony asked (2026-10-20) for the defaults of Settings → Lab parameters, borrowed
from the old repos, to be investigated and noted here. Every value below is
**unconfirmed**: the detector, trap and timing have changed since this code was
written, so the hardware may not match it.

## The three legacy repos

| Repo | Commit | Notes |
|---|---|---|
| `legacy/DLD_front_panel` (`LaserMac-BECMachine-cloudstor`) | `6c7352c` | Front panel values: 2017–2019, synced 2023 |
| Its `lib/Core_BEC_Analysis` | `9e833a1` | `hebec_constants.m`: 2019, synced 2023 |
| `legacy/Momentum_Bells_test` (`OneDrive-Yogesh`) | `fdfcb6b` | The lab's current analysis code; last commit by Yogesh Sridhar, **2026-09-28** |
| `legacy/tdc_autoconverter` | `e4f8812` | 2019 |

Momentum_Bells_test is the newest. Its monitors (`monitor_momentum.m`,
`monitor_mag.m`, `lib/monitor_halos.m`) set their own constants after calling
`hebec_constants`. Its own Core_BEC_Analysis isn't checked out here; it came from
the MATLAB path.

## Parameters

### Fall distance and fall time

| Value | Where | Since | Notes |
|---|---|---|---|
| **0.852925545 m** | `monitor_momentum.m:55` | 2020-07-21 (`4fe788a`) | Still there in the 2026-09-28 sync |
| | `monitor_mag.m:49`, `bec_interference.m:49` | 2020–2021 | |
| | `lib/monitor_halos.m` | 2019-11-15 (`fdc64d7`) | Until 2024 |
| 0.848 m | `lib/monitor_halos.m:47` | **2024-06-05** (`d34fcf2`, Yogesh, "stash 2") | 0.8529 commented out beside it. The same commit changed the rotation to 0.93, the DLD trigger to 20.5 s and the arrival windows to about 2.12–2.16 s |
| | `dld_front_panel.m:108` | 2017 | "848mm" |
| 0.8587 m | Core `hebec_constants.m:42` | 2019-11-07 (`8b4fa77`, Kieran Thomas) | No comment. Matches the 0.418707 s fall time in `lib/halo_vel_conv_legacy.m:33` (2019-12) |
| **0.417 s** | `monitor_momentum.m:39`, `monitor_mag.m:32`, `bec_interference.m:31`, `lib/halo_func.m:91`, `main.m:249` and other halo scripts | Fall time; every current script uses it | |
| 0.416 s | `dld_front_panel.m:109` | 2017 | |

**Consistency** at g = 9.796: √(2h/g) gives
- 0.4173 s for 0.8529 m: matches 0.417 s;
- 0.4161 s for 0.848 m: matches the front panel's 0.416 s;
- 0.4187 s for 0.8587 m.

So 0.8529 m and 0.417 s go together, and 0.848 m and 0.416 s go together.
monitor_halos' 2024 change pairs 0.848 m with the 0.417 s used everywhere else.

**Tony's choice (2026-10-20): 0.848 m for now.** The fall time is derived from it: √(2h/g) = 0.4161 s, editable. I had proposed 0.852925545 m with 0.417 s (superseded). These are the only pair that agree,
and they are still in the monitor synced on 2026-09-28. **Open:** why did
monitor_halos go back to 0.848 m in 2024? Ask Yogesh. Ideally, measure the
distance: fit the arrival time of a BEC released at rest, with a known release
time.

### g

| Value | Where | Notes |
|---|---|---|
| **9.7960207 − 78e-8 m/s²** (= 9.79602 m/s²) | Core `hebec_constants.m:32` | Canberra; the comment (36) cites the GGMplus model at (−35.2831, 149.1126). This is the ANU, height-corrected |
| 9.7961 m/s² | `dld_front_panel.m:112` | Cites Rec1969_034 |
| 9.8, 9.81 | `Heconst.m`, the `txy_to_vel` test, `centre_BEC_COM` | Rough values |

**Default: 9.79602 m/s².** The differences are 1e-5 relative, below any fit's error.

### He* mass, ħ, k_B

- `hebec_constants`: `mhe = 1.66e-27·4.002`, about 0.05% off. The front panel: 6.6464e-27 kg.
- **Default:** CODATA through `scipy.constants`: m(⁴He) = 4.002602 u = 6.6465e-27 kg. The metastable state's extra mass (about 20 eV/c²) is negligible.

### Scattering length

| Value | Where | Notes |
|---|---|---|
| **7.512 nm** | Core `hebec_constants.m:26` | Moal et al., PRL 96, 023203 (2006). Set in commit `2614f65`, 2019-09, "correcting scattering length"; 15 nm is commented out above it |
| | `TC_and_below_tof_b` | |
| 15 nm | Core before 2019-09 | |

**Default: 7.512 nm.** That is the measured value for spin-polarised He* (m = +1).

### Trap frequencies

- **Only source:** the front panel, 2017: `trapfreqrad = 500`, `trapfreqaxial = 50` Hz (`dld_front_panel.m:110-111`). Nothing in Momentum_Bells_test or Core sets them, and `basic_quadratic_trap.m` is a simulation.
- **Default: 500 Hz radial, 50 Hz axial, clearly flagged stale.** Only D4/D14 (Tc, N, μ) use them.
- **Ask Tony** for current values: they depend on the trap's bias and gradient, and the sequence has changed.

### Release time (DLD trigger, trap switch-off)

| Parameter | Value | Where | Since |
|---|---|---|---|
| DLD trigger | 20.3 s | `dld_front_panel.m:117` (2019-11); `monitor_momentum.m` 2020–2023; `bec_interference.m:34` | |
| | **20.5 s** | `monitor_momentum.m:42` | 2023-09-12 (`cf7f597`, Tony at the BEC machine) |
| | | `monitor_mag.m:35`, `lib/monitor_halos.m:33` | |
| DLD acquisition | 4 → 2.3 → 1.4 → 1.1 → 3 → **2 s** | `monitor_momentum.m:43` | Last set 2026-09-28. A shot whose last count is earlier than this is flagged incomplete (line 132) |
| Trap switch-off | 22.954 s | `dld_front_panel.m:116` | 2019-11. With trigger 20.3 s and fall 0.416 s, atoms arrive at about 3.07 s after the trigger |
| | 0 | `lib/monitor_halos.m:59` | Unused |

**Where atoms arrive now.** Arrival windows (T after the DLD trigger) in `lib/fraction_calc.m`:
- 2026-09-28: **2.08–2.18 s** (lines 15, 27);
- 2024: 2.11–2.18 s;
- older `main.m` / `data_vs_phase.m`: 3.75–4 s.

So the front panel's switch-off is out of date. Release is now about 2.12 − 0.417 ≈ **1.7 s after the trigger**, which is about 22.2 s in the sequence if the trigger is at 20.5 s.

**How the current code does it.** It never uses an absolute release time. `lib/halo_vel_conv.m:36-53` (2023-08) centres each shot on its BEC (`find_dist_cen`) and converts with `out_time = −tf`. In other words, the release is that shot's BEC arrival minus the fall time.

**Plan:**
- **D8's default release time comes from the data:** each shot's (or the run's) order-0 arrival minus the fall time.
- **Manual setting:** a release time in seconds after the DLD trigger, offered as an alternative.
- **Lab parameters:** keep the DLD trigger (20.5 s) and acquisition (2 s) only for display, and to flag incomplete shots.
- **Do not use 22.954 s.**

### XY rotation (not used in HeLab; Tony 2026-10-20)

| Value | Where | Since |
|---|---|---|
| 0.61 rad | `monitor_momentum.m:21`, still in 2026 | |
| | Core `import_mcp_tdc_data`'s default | |
| | the front panel until 2019 | |
| **0.93 rad** | `monitor_mag.m:14` | 2023-01-31 (`b124521`), "0.93;%0.61" |
| | `lib/monitor_halos.m:12` | 2024-06-05 |
| | the front panel's new default | 2023 sync |

The change lines up with a new detector plate: Dec 2022 data folders are named `…new_plates…`. monitor_momentum still uses 0.61, which may be a leftover. That fits the hot spot near the XY box's edge seen when porting transfer fractions.

### Detector box and hot spots

- **XY window:** ±35 mm in every current Momentum_Bells_test script, commented "tight XY lims to eliminate hot spot from destroying pulse widths". The front panel and Core use ±30 mm. The T window is [0, 4] s.
- **Hot spots:**
  - Core `hotspot_mask.m` has the 2019 list of nine circles and one keep circle of r 38 mm, for the old detector.
  - The 2023 sync adds a "new detector" spot at (3.44, 18.96) mm, r 5.5 mm.
  - All of these are in the rotated frame (0.61 rad for the 2019 list; the new-detector spot's rotation is unknown, probably 0.93).
- **Plan:**
  - Port the 2019 list as the "old detector" preset (inverse-rotated by 0.61 rad).
  - Leave the current detector to D15's finder, as Tony decided. The 2023 spot is a hint, not a preset.

### Detector reconstruction (D11, not lab settings)

| Constant | Value | Where |
|---|---|---|
| Time bin | 25 ps | Core `dld_read_5channels_reconst_multi_imp.m:39` |
| tsum | 3200 bins ± 200 (2019; the autoconverter still uses it) | Same file |
| Separate tsums for T | x 3390, y 3275 (2023 edit, 470–471) | Same file |
| v_perp | 5.2632e5 m/s | Same file |
| x1 dead time | 0.5 µs (2023 edit, 434) | Same file |

These belong to the converter variant, and HeLab won't treat them as lab parameters until D11.

### Low-count alert (D2, Live)

**Decided (Tony, 2026-10-20):** the fraction check compares a shot with the mean of the **last 100 shots** by default.

What the old code did:
- **Shot histories:** `monitor_momentum.m:53` used 100 shots; `monitor_mag` 20; `monitor_halos` 30; the autoconverter's moving mean 30 (`tdc_auto_convert.m:52`).
- **Minimum counts:**
  - `frac_opts.num_lim` 50 in `monitor_momentum.m:81` and 150 in `monitor_mag.m:75`, for the fraction calculation;
  - `opts.num_lim` 2000 atoms in `monitor_halos.m:66`;
  - the autoconverter warned below 700 counts/s (`min_counts_hz`, line 56).

**Proposed defaults** (both off until switched on):
- absolute: **below 50 counts**, the current monitor's `num_lim`;
- fraction: **below 50% of the last 100 shots' mean**. 50% is a guess: no legacy value.

## Defaults table (as in the plan)

| Parameter | Default | Confidence |
|---|---|---|
| Fall distance | 0.848 m | Tony's choice for now (monitor_halos 2024, front panel); measure later |
| Fall time | √(2h/g) = 0.4161 s, derived | Follows the distance; the scripts' 0.417 s went with 0.8529 m |
| g | 9.79602 m/s² | High |
| m_He, ħ, k_B | CODATA | High |
| Scattering length | 7.512 nm | High (published) |
| Trap frequencies | 500 / 50 Hz | Low: 2017 front panel only |
| Release time | From the data: order-0 arrival − fall time; manual alternative | Matches the current code |
| DLD trigger, acquisition | 20.5 s, 2 s | High (2023–2026), for display |
| Low-count alert | Off; < 50 counts and/or < 50% of the last 100 shots' mean | 100 decided; 50 and 50% proposed |
