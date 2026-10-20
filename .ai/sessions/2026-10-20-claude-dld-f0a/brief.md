# F0a brief (2026-10-20, Claude, Worker)

From the Coordinator, while Tony was asleep: build the pure-numbers half of F0 of
[the DLD front panel port](../../../roadmaps/dld-front-panel-port.md), on branch
`agent/dld-f0a` from `1231025` (`agent/dld-front-panel-port`). No UI, no I/O, no settings:
the three-level constants UI and store are F0b's.

1. `helab/analysis/physics.py`: one constants table (CODATA ħ, k_B, u; He* mass from
   4.002602 u; g = 9.79602 m/s²; scattering length 7.512 nm; fall distance 0.848 m; fall
   time √(2h/g) unless given; DLD trigger 20.5 s and acquisition 2 s, shown only), each
   with key, title, unit, value, source, unconfirmed flag and intended level (lab/folder);
   a frozen, JSON-serialisable resolved-constants object; `thermal_temperature`, σ_v from
   a T width (g σ_t) and from an X/Y width (σ_x / t_f).
2. `helab/analysis/fits.py`: bounded `curve_fit` wrappers for 1D histograms, moment
   guesses, value ± SE, model curve, reduced χ², failure reasons as results, a model
   registry; Gaussian + offset, and if time allows TF^p and bimodal TF + Gaussian.
3. `format_uncertainty(value, se, style="pm"|"paren")`, with SI units consistent with
   HeLab's unit formatting.
4. `pooled_mean_and_std` and `sewm`.

Acceptance: synthetic recoveries within ~2 SE across seeds, edge-case notes, formatting
cases, pooled stats against NumPy, the constants and 0.848 m → 0.4161 s; strict mypy,
pyright and `git diff --check` clean; only new files.
