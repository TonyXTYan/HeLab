# DLD physics fixes handoff

Branch `agent/dld-physics-fixes` from `fb47de7`. Not pushed or merged. Brief: [brief.md](brief.md);
measurements and choices: [notes.md](notes.md).

## Done

1. **Release time** (`helab/analysis/release.py`): the arrival peak is fitted with
   `fits.arrival_time_model(effective_fall_distance(C), C.g)` (centre = v = 0 arrival);
   Gaussian (+ skew note) then mean as fallbacks, each noted. 1.5 µK, 20 seeds: bias
   +32.9 → −3.6 µs (SE 12.8 µs).
2. **Offset ≥ 0** (`helab/analysis/fits.py`): with count weights on raw counts (no `sigma=`,
   weights "poisson"/"counts") the `offset` parameter's lower bound is 0; an offset at that
   floor isn't noted as "at its bound". The models' bounds functions are unchanged (−top),
   since they can't see the weights: the floor is in `fit_histogram` (docstring bullet,
   `OFFSET`, 6 lines after reading the bounds, one `at_bound` condition). Sparse probe: 117/200
   negative offsets → 0.
3. **XY origin**: `detect_release_time(…, positions=)` gives `ReleaseTime.origin` (rest cloud's
   mean X, Y within 2 σ_t ± SE, `origin_events`, in the record); `bootstrap_release_time` takes
   TXY shots and bootstraps the origin too; `txy_to_velocity(…, origin=(0, 0))` with
   `Velocities.origin`; `release.velocity_origin(release, manual)` → (origin, "manual" |
   "detected" | "assumed"). Docstrings say (0, 0) assumes the trap is above X = Y = 0.
4. **`bootstrap.shot_means(per_shot, weights)`** → `ShotMeans`: per-element `sewm` over
   shots, for D5's mean X per T bin (and D2's per-shot numbers).
5. **Docstrings**: "within run (events independent)" with pointers to `bootstrap_release_time`.

Tests added: `tests/test_velocity.py` (arrival-time fit over 20 seeds, Gaussian fallback,
back-to-back pairs with/without origin, origin detection and `velocity_origin`, the origin's
shot bootstrap); `tests/test_bootstrap.py` (`shot_means` vs the bootstrap); `tests/test_fits.py`
(offset floor, given errors keep −top, background still found).

Existing tests changed because of the floor (see notes.md, item 2): `test_fits.py` Gaussian
pull tolerance 0.3 → 0.4 and the flat-counts bound note; `test_histogram_fits.py` (not an owned
file, one tolerance line) smoothed-vs-raw width 0.5 → 0.75 SE. The skew-note test became the
arrival-time test plus a fallback test.

## Re-review fixes (second commit)

1. `fit_histogram(nonnegative_offset=None|True|False)`; `profiles.fit_smoothed` passes True.
   `test_histogram_fits` smoothed-vs-raw tolerance back to 0.5 SE.
2. `fit_histogram(binned=True)`: the model averaged over each bin (Simpson,
   `fits.bin_means` / `fits.bin_bounds`); `fit_smoothed` bins inside `smoothed_model` and
   uses the bin means for its sandwich and variances (`binned=False` there). 50k events in
   bins of σ/5: σ pull +0.5 → within 0.15.
3. Robust XY origin: ±3 robust σ window about the median, twice; `origin_background`
   recorded and noted > 5 %; `velocity_origin` "detected (unsure)".
4. `ShotMeans.notes` below `MIN_SHOTS` shots.
Details: notes.md, "Re-review of 986db18". `profiles.py` lines touched: the import, the
`smoothed_model` docstring and function (bin means on its bins), and in `fit_smoothed` the
bin bounds, two `bin_means` means and the `fit_histogram` flags.

## Checks

- `mypy helab tests --strict`: no issues, 176 files. `pyright helab tests`: 0 errors.
  `git diff --check`: clean.
- Targeted (`-n 2 --reruns 5 --reruns-delay 1`): velocity/bootstrap/fits/histogram fits all
  pass, no reruns.
- Full suite (`python -m pytest -n 4 --reruns 5 --reruns-delay 1 -rR`):
  `2 failed, 1656 passed, 7 skipped, 2 xfailed, 2 warnings, 10 rerun in 161.41s`. The 2
  failures are the known root-only ones (`test_constants.py::test_read_only_saved_folder_is_replaced`,
  `test_cache_mover.py::test_recovery_isnt_usable_after_a_failed_settings_write`), and all
  10 reruns are theirs (5 each).

## For Tony (proposed)

1. The offset floor biases σ slightly low when the true background is 0 (mean pull −0.17 →
   −0.31 at 500 events, +0.03 → −0.16 at 5000; the exact constrained Poisson likelihood gives
   the same). Keep it (proposed), or keep −top.
2. ~~Floor the smoothed fit's offset too~~: done in the second commit.
3. XY origin as the mean within 2 σ_t (background pulls it slightly); a per-folder "trap
   position" setting as the manual override's home.
4. Always fit the arrival-time profile first (not only for wide clouds).

## Checks (second commit)

- Targeted (velocity, bootstrap, fits, histogram fits; `-n 2 --reruns 5 --reruns-delay 1`):
  96 passed, no reruns. `mypy helab tests --strict`: clean, 176 files. `pyright helab tests`:
  0 errors. The diff check: clean.
- Full suite (`-n 4 --reruns 5 --reruns-delay 1 -rR`): `2 failed, 1664 passed, 7 skipped,
  2 xfailed, 2 warnings, 10 rerun in 108.37s`: the two known root-only failures, and all 10
  reruns are theirs.
