# D8/D10 numerics handoff

Branch `agent/dld-d8-d10`, from `e7d0aba` (`agent/dld-f0a`). Not pushed or merged. New files
only; nothing existing changed. The worktree's `venv` is an untracked, ignored symlink to the
main checkout's venv, for pyright.

## Done

- `helab/analysis/velocity.py` (D8): `txy_to_velocity(events, release_time, constants)` →
  `Velocities` (read-only (n, 3) values in TXY order (v_z, v_x, v_y), `invalid` count, nan for
  τ ≤ 0 or non-finite T, `in_recoils`); `vertical_velocity` (a T axis as v_z) and its inverse
  `arrival_time`; `recoil_velocity(constants, wavelength)` with `RECOIL_WAVELENGTH`
  1083.331 nm (unconfirmed). z up: v_z = ½ g τ − h/τ.
- `helab/analysis/peaks.py`: `find_time_peaks(times, lower, upper)` → `PeakSearch` (peaks
  tallest first, the histogram), Transfer fractions' method written on its own (not
  extracted: see notes.md).
- `helab/analysis/release.py` (D8): `detect_release_time(times, constants, lower, upper)` and
  `manual_release_time(t_r, constants)` → `ReleaseTime` (value ± SE, source, fall time,
  arrival, σ_t, failure, notes incl. "unsure", peaks, the fit, strict-JSON `as_record`).
- `helab/analysis/bootstrap.py` (D10): `bootstrap_shots(shots, statistic, n_boot=1000,
  seed=0, confidence=0.6827, cancelled=None)` → `BootstrapResult` (value, SE, percentile
  interval, replicates, undefined counts, notes, failure, `estimate()`, `as_record`); scalar or
  1D statistics; raises `Cancelled`.
- Tests: `tests/test_velocity.py` (velocities, peaks, release time; 15 tests) and
  `tests/test_bootstrap.py` (6 tests), about 4 s with `-n 2`.

Derivations (signs), measured skew bias and choices: [notes.md](notes.md).

## Checks

- New tests: 21 passed (`-n 2 --reruns 5 --reruns-delay 1`), no reruns.
- `mypy helab tests --strict` (the venv's): clean, 159 files. `pyright helab tests`: 0 errors.
- `git diff --check`: clean.
- Full suite (`python -m pytest -n 2 --reruns 5 --reruns-delay 1`, the venv's `bin` first on
  `PATH`): `2 failed, 1457 passed, 7 skipped, 2 xfailed, 12 rerun in 210.02s`. The 2 failures
  are the known root-only ones (`test_constants.py::test_read_only_saved_folder_is_replaced`,
  `test_cache_mover.py::test_recovery_isnt_usable_after_a_failed_settings_write`); 10 of the
  reruns are theirs; the other 2 reruns were of tests that then passed (the run was
  `-q`, so they aren't named; none are in the new files, which ran with no reruns).

## For Tony (proposed)

1. Velocity columns in TXY order, (v_z, v_x, v_y).
2. `RECOIL_WAVELENGTH` (1083.331 nm, 2³S₁ → 2³P₂) as a lab-level, unconfirmed row in
   `physics.CONSTANTS`; plot units m/s, ħk/m and 2ħk/m (one Bragg order).
3. Release time: tallest peak, "unsure" at ≥ 50 % of its height, `MIN_EVENTS` 50, a Gaussian
   fit within 1.5 FWHM with a mean fallback; the fall time's error left out of the SE (it's
   systematic).
4. Skew of wide clouds: note only (current), or correct by −σ_t²/(2 t_f).
5. Bootstrap: n_boot 1000, seed 0, a 68.27 % interval, a note below 5 shots, percentile (not
   BCa), not `scipy.stats.bootstrap`.
6. Transfer fractions' peak finding moves to `peaks.py` later, as a refactor checked by its
   MATLAB-comparison tests.

## How plots should use these

- **D8 axes.** When a run starts, resolve the constants (F0b), then the release time:
  `manual_release_time` if set by hand, else `detect_release_time(view's T column over the
  chosen shots, constants, *search T*)`. Put `release.as_record()` and the constants' record
  in the result; show `failure` or `notes` (the "unsure" one in amber) on the dock line, and
  the release time with `value.text(unit="s")`. Then `txy_to_velocity(events, release.value.value,
  constants)` per shot or for the selection, and divide by `recoil_velocity(constants)` for
  recoil units. A T histogram can keep T bins and relabel the axis with `vertical_velocity`
  (monotonic), or bin v_z directly; a v_z window maps back to T with `arrival_time` (so the
  T-sorted `searchsorted` window still works). Say how many events had no velocity
  (`invalid`). Never rotate XY.
- **Per-shot release time** (the legacy `halo_vel_conv` centres each shot): call
  `detect_release_time` per shot; with few events per shot, the run's value is steadier.
- **D2 / D4 error bars.** Give `bootstrap_shots` the chosen shots (each shot's events, or
  each shot's counts per window) and a statistic that recomputes the plotted number from a
  list of shots: transfer fractions per order (sum per-order counts over the drawn shots,
  divide by their total: a 1D statistic), or a fit parameter (histogram the drawn shots'
  events, `fit_histogram`, return the parameter or nan when `not fit.ok`). Pass
  `context.cancelled`. Draw ±`se`; show `notes` (few shots, undefined resamples). Record
  `as_record()` (n_boot and seed included). For a count-weighted mean of per-shot values,
  `estimates.sewm` needs no resampling. A fit per resample costs n_boot fits: consider 200
  for D4 or a time budget, and reuse per-shot histograms (sum the drawn shots' counts) rather
  than re-binning events.

## Proposed doc changes (not made: AGENTS.md and roadmaps/ are Tony's)

- **AGENTS.md, Script system**, after F0a's proposed sentence: "D8/D10 numbers:
  `velocity.py` (TXY → velocity at release, z up, v_z = ½ g τ − h/τ, TXY column order, no
  XY rotation; recoil units), `release.py` (the release time from one cloud's arrival, or
  by hand; results with notes, never exceptions; peaks from `peaks.py`) and `bootstrap.py`
  (`bootstrap_shots`: seeded shot resampling, cancellable)."
- **roadmaps/dld-front-panel-port.md:** in Decided → Velocities, add "v_z = ½ g τ − h/τ, the
  velocity at release; TXY column order" and the recoil wavelength; under D8/D10 mark the
  numeric halves built; record the bootstrap defaults if Tony agrees.
