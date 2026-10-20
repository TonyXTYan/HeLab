# D8 part 2 notes: Velocity distributions

## What was built

- `helab/scripts/standard/velocity_distributions.py`, the **Velocity distributions** plot
  (`helab.velocity_distributions` v1, group "Basic plots v1", registered in `standard.MODULES`).
  - Events: Shots → Mask (D9, `masks.mask_from`) → View range (auto-crop keep % or a manual T/X/Y
    box, as the density images; a manual T window picks one cloud or Bragg order).
  - t_r: `release.layer_release_time` (t_r by hand, or saved arrival t_a − *this run's* t_f), else
    `release.detect_release_time` on the run's events within Search T (one detection, SE "within
    run", no bootstrap), said in amber. The origin: `layer_origin`, else the same detection's,
    else (0, 0) assumed, said in amber (with a v_x ≈ x₀/t_f spurious offset, tested).
  - Velocities from `velocity.txy_to_velocity` (z up). Events arriving before t_r (or not finite)
    are counted and noted, never drawn.
  - Histograms v_z, v_x, v_y (Freedman–Diaconis or set bins), a dashed line at v = 0, optional
    Gaussian + offset fits (`fits.fit_histogram`): centre, σ_v ± SE, T = m σ_v²/k_B
    (`physics.temperature_estimate`). Optional 2D density v_x–v_y (square bins, aspect locked) or
    v_x–v_z, reusing the density images' bins, colour scales and colour bar.
  - Units: mm/s (default), m/s, ħk/m, 2ħk/m; the title says "1 2ħk/m = 184 mm/s"; the record adds λ.
  - Record (`found`): t_r value/SE, source ("lab"/"folder"/"plot"/"detected") and from
    ("release_time"/"arrival_time"/"data"), the detection, origin (x, y, how, source), unit factor,
    fits with σ_v and T, every note, and the constants (`describe_constants`, every key).
  - Live: `LivePolicy(min_delay=1.0)` (conversion + at most one detection, under a second on
    500k events); `update` draws in place unless the fit or density mode changes.
- `helab/analysis/physics.py`: lab-level, unconfirmed row `recoil_wavelength` = c / 276.7321865 THz
  (1,083.331 nm), `ResolvedConstants.recoil_wavelength`.
- `helab/analysis/constant_layers.py`: `KEY_PREFIX`/`fixed_prefix(key)` so the wavelength is shown
  and typed in nm (Lab parameters tab, plot settings, `value_text`).
- `helab/analysis/velocity.py`: the recoil unit reads the run's `constants.recoil_wavelength` by
  default; `RECOIL_WAVELENGTH` now mirrors the table row.
- Tests: `tests/test_velocity_distributions.py` (12) plus the shared lists (registration, coverage
  and reuse key, empty cases, ms/mm settings, wrapped titles, physics and lab-parameter row sets).

## Proposed, for Tony

1. `recoil_wavelength` 1,083.331 nm (He* 2³S₁ → 2³P₂) as a lab-level row, **unconfirmed** until
   Tony confirms the Bragg beams are on this line; 2ħk/m is taken as one Bragg order
   (counter-propagating beams).
2. Default unit mm/s (a µK cloud's σ_v is tens of mm/s); m/s, ħk/m and 2ħk/m offered.
3. T = m σ_v²/k_B neglects the cloud's initial size (pure expansion), said in the fit's tooltip.
4. With no t_r anywhere the plot detects one per run (no bootstrap) rather than refusing; the
   Release time plot remains the place to measure it properly and save the folder's arrival.
5. An origin set in one of x₀/y₀ only is no origin (part 1's rule): detection, else assumed.
6. Live `min_delay` 1 s (cheaper than the Release time plot's 5 s: no bootstrap).
7. The record's origin `source` is `trap_x`'s layer; a mixed layering of x₀ and y₀ shows only x₀'s.
