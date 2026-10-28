# Second look: branch `LaserMac-BECMachine-cloudstor`

Tony moved the `legacy/DLD_front_panel` submodule to branch
`LaserMac-BECMachine-cloudstor` (`6c7352c`). This adds 19 commits after the `10ae8ea`
reviewed in [notes.md](notes.md):
- 2019-10 to 2020-06: Bryce Henson and Kieran Thomas;
- 2023-08-29: Tony's "sync changes, finally".

The nested `lib/Core_BEC_Analysis` goes from `b8907f5` to `9e833a1` (107 commits).
Its nested library submodules were already submodules before; they are only
bumped here. The Core changes are in [core-update.md](core-update.md).

## Submodule update (2026-10-20)

`git submodule update --init --recursive --force` in `legacy/DLD_front_panel`
checked out `Core_BEC_Analysis` at `9e833a1`. It stopped at three nested pins
that are on no upstream:

| Path | Pinned | Where it is | Done |
|---|---|---|---|
| `lib/bootstrap_error` | `73501cc` | Only `HeBECANU/bootstrap_error`, branch `LaserMac-BECMachine-cloudstor-DLD_front_panel_submodule_folder-` (`.gitmodules` points at `brycehenson/`) | Fetched from HeBECANU, checked out `73501cc` |
| `bin/export_fig` | `5d19203` | Nowhere public (no HeBECANU or TonyXTYan fork) | Left at upstream `b1a7288` (v3.0~13) |
| `bin/MBeautifier` | `dea7508` | Nowhere public | Left at upstream `cff447f` (v1.4.0) |

**Two notes:**
- **`MBeautifier` and `ciecam02` index state:** before the update, their indexes showed every file as a staged deletion. This was probably left over from the old in-tree copies. The update and a `reset --hard` restored them; nothing local was lost (the working trees were empty).
- **Fixing it for good:** the missing commits were made locally in 2023 and never pushed. To fix the pins, push them from the machine that has them (LaserMac?), or repin them to upstream commits. Both tools are irrelevant to porting: export_fig exports figures, MBeautifier formats code.

**Remaining state:**
- `git status` in HeLab shows `legacy/DLD_front_panel` as modified, since the gitlink is now `6c7352c`. HeLab's `.gitmodules` still says `branch = main`; it should say `LaserMac-BECMachine-cloudstor` if that branch stays.
- Inside `Core_BEC_Analysis`, the two tool submodules show as modified because they are not at their pins.

## Changes in the front panel itself (`10ae8ea..6c7352c`)

### `dld_front_panel.m`
- **Path setup:** `set_up_project_path` (Core) replaces `addpath(genpath(...))`.
- **New lab constants:**
  - `handles.switchoff = 22.954` s: the trap switch-off time in the sequence.
  - `handles.dldtrig = 20.3` s: the DLD trigger time.

  So T = 0 on the detector is 2.654 s before the trap switches off. The expected arrival centre is `switchoff + falltime − dldtrig` = 3.07 s. **Correction to D1/D8:** the release time (`out_time` for `txy_to_vel`) is `switchoff − dldtrig`, a lab setting.
- **Rotation default:** the XY rotation's default changed from **0.61 to 0.93 rad**. This fits the roadmap's note that a new detector was installed after MATLAB's 0.61. Rotation stays out of HeLab (Tony, 2026-10-20), but the hot spot near the XY box's edge in transfer fractions may come from it.
- **Low-file threshold:** disabled (`< 0 % 1000`).
- **Hot spot removal** (2019-11-20 / 2020-06): a "hotspot" checkbox runs `hotspot_mask(data)` (Core `txy_tools`) on the per-shot cells before concatenating them. This is D9's hot-spot cut; the algorithm is in [core-update.md](core-update.md).

### `lib/dld_plot_tof.m` (Kieran Thomas, 2019-11)
**Fixed since the first review:**
- X/Y axes are now ×1e3 (mm).
- The FFT uses the T histogram's raw counts (`fft_tx`, padding 10, Hamming).
- `vdet = 1` on spatial axes, since the data is in metres.
- Labels use `string_value_with_unc`.

**A new thermal model on the time axis** (the "Yavin" exact arrival-time form):

`f(x) = A·exp(−(((x² − μ²)/x)²)/(2σ²))·(1 + μ²/x²)`

- The initial centre is `switchoff + falltime − dldtrig`.
- For x near μ, `(x² − μ²)/x ≈ 2(x − μ)`, so σ is about 2σ_t. That is why T now has a factor `0.25`: `T = ¼·(σ/t_f)²·m/k_B`.

**Bugs:**
- `fit_thermal` applies the 0.25 to **every** axis, including X/Y, where the plain Gaussian is still used. So the X/Y temperatures are now 4× too low.
- In `yav_parab` (the bimodal model on the time axis) the fall time is hard-coded as `tf = 0.416`, and x is offset by the centre `b(2)` there but not in `therm_fun1d`. The two thermal forms are not the same function.
- **Still wrong:** the condensate fraction. `countsTF = A/(4R)` and `countsGauss = B/(√(2π)σ)` are unchanged; the attempts to fix them are commented out. The TF exponent is still 3/2.
- Debug prints were left in (no semicolons).

The physics to keep is the exact arrival-time thermal profile. It is better than a Gaussian at long expansion times. D1 should offer it on the T axis, with the release time from the lab settings, after checking it against a simulation.

### `lib/dld_2dplotter_window_a.m`
Range compression is now a **nonlinear colour map** (`nonlinear_colormap(viridis, 'power', γ)`, Core). The counts are no longer transformed, so the colour bar shows true density. **D3 should do the same:** compress the colour scale (pyqtgraph `ColorMap` with power-spaced stops) and keep the data linear.

### New: `lib/ghost_counts_analysis.m` (391 lines, script)
A detector diagnostic on **raw** files.
- **Reconstruction:** it reruns the 4-corner reconstruction inline (here the MCP channel is 4, not 7). It records which raw pulses formed each hit (`dld_pulses_used`).
- **Splitting hits:** by the corner difference `x2 − x1 < −5 ns`, which picks out the suspected ghost counts (a line in X).
- **Histograms:** the time differences between ghost and real hits' pulses on each channel (up to 10 µs), and within each group.
- **What it shows:** whether ghosts are ringing or reflections arriving a fixed delay after a real pulse.
- **Problems:** hard-coded `Y:\…\dld_output\d29.txt`; `clear all`.

### New: `lib/pulse_corrs.m` (161 lines, script)
Runs on the workspace that `ghost_counts_analysis` leaves. It histograms:
- `X2−X1` and `Y2−Y1` raw pulse differences (±0.3 µs), which give the position spectra in ns;
- each channel's pulse-to-pulse intervals (up to 5.5 µs), which show ringing and dead time;
- time sums `x1+x2−2·mcp` and `y1+y2−2·mcp` for ghost vs real hits.

The `xdiff_hist*.png` and `ydiff_hist_ns.png` in the root are its output.

### Other files
- **Moved to `old/`:** the dead `TC_and_below_*`, `tof_gauss_*`, `guassfun_*`, `TOF_averaged`, `positiveFFT`, `power_spec`, `procFFT`, `plot_pancake` and `fit_2d_gaussian` (the first review had found them dead).
- **`dld_front_panel.fig`** moved to the root.
- **`Untitled2.m`:** a 4-column table of numbers 2902–2925, apparently shot numbers grouped by 4 for a scan. Not code.
- **Pictures:** `BEC_DFG*.fig`, `TimeFit/XFit/YFit.fig` and `.jpg`, `atom_laser.png`, `Barchart.png`: figures from Kieran's fits.

## What this changes in the plan

- **D1:** add the exact arrival-time thermal model on T. It needs the release time = `switchoff − dldtrig` as a lab setting (22.954 − 20.3 = 2.654 s on that machine). The temperature factor depends on the model; test it on simulated data. Don't copy the 0.25 onto X/Y.
- **D3:** compress the colour map, not the data.
- **D8:** the release time comes from the same settings.
- **D9:** `hotspot_mask` is the algorithm to port (see [core-update.md](core-update.md)).
- **D11 (new sub-item): raw-pulse diagnostics**, from `ghost_counts_analysis` and `pulse_corrs`:
  - time-sum and corner-difference histograms;
  - each channel's pulse spacing;
  - which pulses formed each hit.

  The converter port should keep which pulses formed each hit, so these come almost free.
- **Rotation:** the new default of 0.93 rad is worth telling Tony, alongside the edge hot spot. The decision stays his.
