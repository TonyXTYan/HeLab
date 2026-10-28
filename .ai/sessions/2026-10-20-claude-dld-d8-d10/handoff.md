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
  `manual_release_time(t_r, constants)`, and `bootstrap_release_time(shots, constants, …)` with the shot-bootstrap SE, → `ReleaseTime` (value ± SE, source, fall time,
  arrival, σ_t, failure, notes incl. "unsure", peaks, the fit, strict-JSON `as_record`).
- `helab/analysis/bootstrap.py` (D10): `bootstrap_shots(shots, statistic, n_boot=1000,
  seed=0, confidence=0.6827, cancelled=None)` → `BootstrapResult` (value, SE, percentile
  interval, replicates, undefined counts, notes, failure, `estimate()`, `as_record`); scalar or
  1D statistics; raises `Cancelled`.
- Tests: `tests/test_velocity.py` (velocities, peaks, release time; 25 tests) and
  `tests/test_bootstrap.py` (8 tests), about 5 s with `-n 2`.

Derivations (signs), measured skew bias and choices: [notes.md](notes.md).

## Review fixes (second commit)

The Coordinator's review of `559b47a`, all addressed (details in notes.md):

1. Few events: bins hold max(10 %, 40) events and `MIN_BINS` yields to 8 events per bin, so
   50–150-event clouds are found (20/20; were 0–20/20); a histogram too sparse for a peak
   fails as "too few events". Tests at 50, 80, 150 and below the limit.
2. A hand-set fall time: velocities use h_eff = ½ g t_f² (`effective_fall_distance`, recorded
   in `Velocities.fall_distance` with `fall_distance_from_time`), so the reference cloud is at
   rest (was +8.9 mm/s). Test.
3. The release time's SE is within-run only (`error` "within run", docstring and record);
   `bootstrap_release_time` gives the shot-bootstrap SE (`error` "shot bootstrap", the fit's
   kept as `within_run_se`). Test with 50 µs shot jitter.
4. Bootstrap: no error is a failure (all undefined, defined on < 2 resamples, undefined on all
   shots), per element in `failures` / `usable`; a plain nan from an array statistic fills its
   shape. Tests.
5–9. `invalid` counts every row that isn't `valid` (nan X/Y too); `Velocities` copies its
   array; named units "m/s", "ħk", "2ħk"; `arrival_time`'s cancellation-free form for v_z < 0;
   coarse-grid times get whole-step bins.
Also found while fixing: peaks refining to the same place are merged (background alone made
a zero-width fit window), a "no cloud stands out" unsure note, and the smoothing kept its
length for short histograms.

## Checks (first commit)

- New tests (first commit): 21 passed (`-n 2 --reruns 5 --reruns-delay 1`), no reruns.
- `mypy helab tests --strict` (the venv's): clean, 159 files. `pyright helab tests`: 0 errors.
- `git diff --check`: clean.
- Full suite (`python -m pytest -n 2 --reruns 5 --reruns-delay 1`, the venv's `bin` first on
  `PATH`): `2 failed, 1457 passed, 7 skipped, 2 xfailed, 12 rerun in 210.02s`. The 2 failures
  are the known root-only ones (`test_constants.py::test_read_only_saved_folder_is_replaced`,
  `test_cache_mover.py::test_recovery_isnt_usable_after_a_failed_settings_write`); 10 of the
  reruns are theirs; the other 2 reruns were of tests that then passed (the run was
  `-q`, so they aren't named; none are in the new files, which ran with no reruns).

## Checks (second commit)

- New tests: 33 passed (`-n 2 --reruns 5 --reruns-delay 1`), no reruns.
- `mypy helab tests --strict` (the venv's): clean, 157 files. `pyright helab tests`: 0 errors.
- `git diff --check`: clean.
- The reviewer's probes (`probe.py`, `jitter.py`) rerun: detection 20/20 at n = 50…400, the
  hand-set fall time's reference cloud at −5 µm/s, `invalid` 1 for a nan X, the undefined
  bootstrap cases `ok` False, a plain nan from an array statistic accepted, rounded times in
  24 bins.
- Full suite (`python -m pytest -n 2 --reruns 5 --reruns-delay 1 -rR`):
  `2 failed, 1468 passed, 7 skipped, 2 xfailed, 10 rerun in 180.25s`. The 2 failures are the
  known root-only ones, and all 10 reruns are theirs (5 each): no other test needed a rerun.

## For Tony (proposed)

1. Velocity columns in TXY order, (v_z, v_x, v_y).
2. `RECOIL_WAVELENGTH` (1083.331 nm, 2³S₁ → 2³P₂) as a lab-level, unconfirmed row in
   `physics.CONSTANTS`; plot units m/s, ħk/m and 2ħk/m (one Bragg order).
3. Release time: tallest peak, "unsure" at ≥ 50 % of its height or under 3× the median
   bin, `MIN_EVENTS` 50, a Gaussian fit within 1.5 FWHM with a mean fallback; the fall
   time's error left out of the SE (it's systematic); the shot-bootstrap SE
   (`bootstrap_release_time`, n_boot 200) as the one D8 shows.
4b. A hand-set fall time sets the velocities' h to ½ g t_f².
4. Skew of wide clouds: note only (current), or correct by −σ_t²/(2 t_f).
5. Bootstrap: n_boot 1000, seed 0, a 68.27 % interval, a note below 5 shots, percentile (not
   BCa), not `scipy.stats.bootstrap`.
6. Transfer fractions' peak finding moves to `peaks.py` later, as a refactor checked by its
   MATLAB-comparison tests.

## How plots should use these

- **D8 axes.** When a run starts, resolve the constants (F0b), then the release time:
  `manual_release_time` if set by hand, else `bootstrap_release_time(per-shot T columns,
  constants, *search T*, cancelled=context.cancelled)`: its SE includes the shot-to-shot
  jitter, which `detect_release_time`'s own (fit) SE leaves out (2.1 vs 9.8 µs in the review's
  probe). Use plain `detect_release_time` on the summed T only where no error is shown (a
  quick Live preview). Show `error` beside the value. Put `release.as_record()` and the constants' record
  in the result; show `failure` or `notes` (the "unsure" one in amber) on the dock line, and
  the release time with `value.text(unit="s")`. Then `txy_to_velocity(events, release.value.value,
  constants)` per shot or for the selection, and divide by `recoil_velocity(constants)` for
  recoil units. A T histogram can keep T bins and relabel the axis with `vertical_velocity`
  (monotonic), or bin v_z directly; the unit picker uses `VelocityUnit` ("m/s", "ħk", "2ħk")
  with `unit_velocity` / `Velocities.in_unit`; a v_z window maps back to T with `arrival_time` (so the
  T-sorted `searchsorted` window still works). Say how many events had no velocity
  (`invalid`). Never rotate XY.
- **Per-shot release time** (the legacy `halo_vel_conv` centres each shot): call
  `detect_release_time` per shot; with few events per shot, the run's value is steadier.
- **D2 / D4 error bars.** Give `bootstrap_shots` the chosen shots (each shot's events, or
  each shot's counts per window) and a statistic that recomputes the plotted number from a
  list of shots: transfer fractions per order (sum per-order counts over the drawn shots,
  divide by their total: a 1D statistic), or a fit parameter (histogram the drawn shots'
  events, `fit_histogram`, return the parameter or nan when `not fit.ok`). Pass
  `context.cancelled`. Draw ±`se` where `usable`; show `failure` / `failures[i]` where not
  and `notes` (few shots, undefined resamples). Record
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
