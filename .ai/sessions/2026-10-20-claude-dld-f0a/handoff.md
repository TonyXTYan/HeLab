# F0a handoff

Branch `agent/dld-f0a`, from `1231025`. Not pushed or merged. New files only; nothing
existing changed. The worktree's `venv` is an untracked, ignored symlink to the main
checkout's venv, so `pyright` finds the packages.

## Done

- `helab/analysis/physics.py`: the constants table with sources, levels and unconfirmed
  flags; `resolve(lab, folder, plot)` → frozen `ResolvedConstants` (origins, unconfirmed,
  JSON `as_record` / `from_record`); `fall_time`; σ_v from T and X/Y widths;
  `thermal_temperature`, `temperature_estimate`.
- `helab/analysis/estimates.py`: `Estimate`, `format_uncertainty` (± and bracket forms,
  SI prefixes matching pyqtgraph's, ×10ⁿ, specials), `pooled_mean_and_std`, `sewm`,
  `propagate`.
- `helab/analysis/fits.py`: `fit_histogram` → `FitResult`; failures as results; a model
  registry; Gaussian + offset, Thomas–Fermi p = 2 and 3/2, bimodal TF + Gaussian (shared
  centre) with component areas. Default weights are the Poisson maximum-likelihood fit
  (see notes.md; the plain √max(n, 1) fit biases widths low and is kept as `"counts"`).
- Tests: `tests/test_physics.py`, `tests/test_fits.py`, `tests/test_uncertainty_format.py`
  (141 tests, about 10 s with `-n 2`).

Design choices, derivations and the items proposed for Tony: [notes.md](notes.md).

## Checks

- `mypy helab --strict`, `mypy tests --strict`, `pyright helab tests`: clean.
- `git diff --check`: clean.
- New tests: 141 passed (`-n 2 --reruns 5 --reruns-delay 1`), no reruns in the final runs.
- Full suite (`python -m pytest -n 2 --reruns 5 --reruns-delay 1`, venv not activated):
  `6 failed, 1414 passed, 7 skipped, 2 xfailed, 31 rerun in 208.30s`.
  - The 2 known root-only failures (`test_constants.py::test_read_only_saved_folder_is_replaced`,
    `test_cache_mover.py::test_recovery_isnt_usable_after_a_failed_settings_write`).
  - The 4 mypy tests in `test_typing.py`: they call bare `mypy`, which on this machine is
    `/root/.local/bin/mypy` without NumPy, so existing files (`dataset_view.py`) fail as
    well. Rerun with the venv's `bin` first on `PATH`: `test_typing.py` 6 passed, 4 rerun
    (mypy runs in two workers at once).
  - Other reruns: `test_window_resize.py::test_label_keeps_painting_after_resize[repeated]`
    once; the rest were the failing tests' own reruns.

## For Tony (proposed)

1. **TF exponent:** p = 2 on every DLD histogram axis (T, X and Y), not 3/2 for X/Y as the
   review notes say; 3/2 is for a slice through one other axis. Correct the review's D4
   and legacy-bug 2 wording if he agrees.
2. **Poisson likelihood weights by default** instead of plain √max(n, 1).
3. **Fall time rule:** a hand-set fall time wins only at the fall distance's level or a more
   specific one; otherwise it's derived again.
4. ħ, k_B and u shown read-only in Lab parameters (they're in the table as lab level with
   `codata=True`).
5. Parentheses around the ± form with a unit, `(416.12 ± 0.12) ms`; bracket form
   `12.3(12)`, CODATA style.

## Proposed doc changes (not made: AGENTS.md and roadmaps/ are Tony's)

- **AGENTS.md, Script system:** one sentence after the transfer fractions paragraph:
  "Shared numbers for the DLD port: `helab/analysis/physics.py` (the constants table;
  `resolve` layers lab, folder and plot values into a `ResolvedConstants` that a run
  records), `fits.py` (`fit_histogram`: bounded histogram fits, Poisson likelihood by
  default, failures as results; register models in `MODELS`) and `estimates.py`
  (`Estimate`, `format_uncertainty`, `pooled_mean_and_std`, `sewm`)."
- **roadmaps/dld-front-panel-port.md:** mark F0's numeric half built (the overview's
  checklist in `_readme.md`, if F0 is split there), and in Decided → Fits add "Fits are
  Poisson maximum-likelihood by default" and "the TF exponent is 2 for full histograms,
  3/2 for a slice", if Tony agrees.

## For F0b (constants UI and store)

- Build the Settings → Lab parameters rows from `physics.CONSTANTS`: title, unit, default,
  source as the tooltip, an "unconfirmed" mark, `level` deciding lab tab vs folder
  settings, `shown_only` rows not used in formulas, the fall time shown as derived
  (`Constant.derived`) with a "set by hand" option.
- Store each layer as a plain `{key: float}` mapping and call
  `resolve(lab=…, folder=…, plot=…)` when a run starts (on the GUI side, before compute);
  validate input first, since `resolve` raises `ValueError` on unknown keys and
  non-positive or non-finite values.
- Put `ResolvedConstants.as_record()` in the run's effective parameters or record, and
  show `origins[key]` beside each value ("lab", "folder", "this plot", "derived",
  "default").

## For D1 / D4

- D1: histogram with `stats.histogram`, then `fit_histogram(bin_centres(h.edges), h.counts,
  "gaussian")`; on T, `temperature_estimate(Estimate(g·σ_t, g·SE))` (σ_v from
  `sigma_v_from_arrival_width`); on X/Y, σ_v = σ_x / t_f. Show `failure` or `notes` on the
  plot, values with `Estimate.text(unit=…)`, and draw `result.evaluate(fine_x)`.
- D1 registers the arrival-time ("Yavin") profile as another `FitModel` (parameters with
  roles, `guesses`, `bounds`, `areas`).
- D4: `bimodal_tf2_gaussian`, with N0/N as
  `result.derived(lambda p: tf / (tf + gauss))` from `model.areas(p)`. Add the g_{5/2}
  thermal part as a model. Consider integrating the model over bins when they are coarse
  compared with R (notes.md).
