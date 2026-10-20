# F0a handoff

Branch `agent/dld-f0a`, from `1231025`. Not pushed or merged. New files only; nothing
existing changed. The worktree's `venv` is an untracked, ignored symlink to the main
checkout's venv, so `pyright` finds the packages.

## Done

- `helab/analysis/physics.py`: the constants table with sources, levels and unconfirmed
  flags; `resolve(lab, folder, plot)` → frozen, hashable `ResolvedConstants` (origins,
  unconfirmed, a note when a hand-set fall time disagrees with √(2h/g), JSON `as_record`
  / validated `from_record`); `fall_time`; σ_v from T and X/Y widths;
  `thermal_temperature`, `temperature_estimate`, each taking the run's constants.
- `helab/analysis/estimates.py`: `Estimate` (strict-JSON record), `format_uncertainty`
  (± and bracket forms, SI prefixes matching pyqtgraph's, ×10ⁿ, rollover, subnormals,
  specials), `pooled_mean_and_std`, `sewm`, `propagate`.
- `helab/analysis/fits.py`: `fit_histogram` → `FitResult` (read-only arrays, strict-JSON
  record); failures as results; a model registry with gates and extras; Gaussian + offset,
  Thomas–Fermi p = 2 and 3/2, bimodal TF + Gaussian (shared centre, R/σ_th capped) with
  component areas. Default weights are the Poisson maximum-likelihood fit (see notes.md;
  the plain √max(n, 1) fit biases widths low and is kept as `"counts"`).
- Tests: `tests/test_physics.py`, `tests/test_fits.py`, `tests/test_uncertainty_format.py`
  (158 tests, about 10 s with `-n 2`).

Design choices, derivations and the items proposed for Tony: [notes.md](notes.md).

## Review fixes (second commit)

The Coordinator's review of `98ea572`, all addressed:

1. Bimodal: R fitted as r = R/σ_th ≤ 2 (physics in notes.md); gated parameters and a note
   when an amplitude is consistent with 0. Tests on a pure thermal cloud and a pure
   condensate.
2. Reweighting that doesn't settle returns its calmest round with a note; the bimodal
   inner Gaussian guess uses count weights or the caller's `sigma`.
3. `pooled_mean_and_std`: a nan SD gives a nan pooled SD; counts must be whole and ≥ 0.
4. and 6. Rollover from the value or the error, in both the SI and the ×10ⁿ paths.
5. A note when count weights get values that aren't whole numbers; the docs say to pass
   `sigma=` for anything else.
7. Exponents and scaling robust for subnormals (`Decimal.scaleb`).
8. `FitResult.as_record`, read-only arrays; `Estimate.as_record` gives None for nan/inf;
   `ResolvedConstants` hashable (`origins` not hashed); `from_record` validates origins and
   values and ignores unknown keys explicitly.
9. The physics conversions require a `ResolvedConstants`.
10. "Fall time and distance disagree" in `ResolvedConstants.notes` and the record; the
    rule's cases listed in notes.md. The rule itself is unchanged.
11. Accurate failure and note texts (bins with counts vs the model's minimum, evaluations
    in the no-convergence text, non-finite vs non-positive errors).
12. No per-call warning filters: one import-time filter for SciPy's `OptimizeWarning`, and
    `np.errstate` (thread-local).
13. He* mass from the He-4 atomic mass, 4.00260325413 u, checked against CODATA's alpha
    particle plus two electrons.

Follow-up (third commit): the bimodal cap became the `max_radius_ratio` option, with the
"TF radius at its limit" note, the cap in `options` / `as_record()`, and a cold-mixture
test (R/σ_th = 3: noted at the default, recovered with the cap at 5).

## Checks

Third commit: the three test files 158 passed, no reruns; `mypy helab tests --strict` and
`pyright helab tests` (the venv's) clean; `git diff --check` clean.

Second commit:
- `mypy helab tests --strict` and `pyright helab tests` (the venv's): clean.
- `git diff --check`: clean.
- The three test files: 157 passed (`-n 2 --reruns 5 --reruns-delay 1`), no reruns.
- `tests/test_typing.py` with the venv's `bin` first on `PATH`: 6 passed, no reruns.
- Not rerun: the full suite (only the three new modules changed since the first run).

First commit (`98ea572`), full suite (`python -m pytest -n 2 --reruns 5 --reruns-delay 1`,
venv not activated): `6 failed, 1414 passed, 7 skipped, 2 xfailed, 31 rerun in 208.30s`.
- The 2 known root-only failures (`test_constants.py::test_read_only_saved_folder_is_replaced`,
  `test_cache_mover.py::test_recovery_isnt_usable_after_a_failed_settings_write`).
- The 4 mypy tests in `test_typing.py`: they call bare `mypy`, which on this machine is
  `/root/.local/bin/mypy` without NumPy, so existing files (`dataset_view.py`) fail as
  well. With the venv's `bin` first on `PATH`: 6 passed, 4 rerun (mypy in two workers).
- Other reruns: `test_window_resize.py::test_label_keeps_painting_after_resize[repeated]`
  once; the rest were the failing tests' own reruns.

## For Tony (proposed)

1. **TF exponent:** p = 2 on every DLD histogram axis (T, X and Y), not 3/2 for X/Y as the
   review notes say; 3/2 is for a slice through one other axis. Correct the review's D4
   and legacy-bug 2 wording if he agrees.
2. **Poisson likelihood weights by default** instead of plain √max(n, 1).
3. **Bimodal R/σ_th cap, default to choose.** `max_radius_ratio` (default 2, μ ≤ 2 k_B T)
   stops the fit inventing a condensate on a thermal cloud or a thermal spike inside a
   condensate, but clamps cold, deep condensates (T ≈ 0.1–0.3 Tc: ratio 2.5–4.5). Those
   get a "TF radius at its limit" note, and the cap is in the record. Choose the default:
   2 (proposed, as a D4 plot setting), or higher (e.g. 4) with the note kept.
4. **Fall time rule** (cases in notes.md): a hand-set fall time wins only at the fall
   distance's (and g's) level or a more specific one; otherwise it's derived again. A kept
   one that disagrees with √(2h/g) by more than 0.1 % is noted.
5. ħ, k_B and u shown read-only in Lab parameters (they're in the table as lab level with
   `codata=True`).
6. Parentheses around the ± form with a unit, `(416.12 ± 0.12) ms`; bracket form
   `12.3(12)`, CODATA style.

## Proposed doc changes (not made: AGENTS.md and roadmaps/ are Tony's)

- **AGENTS.md, Script system:** one sentence after the transfer fractions paragraph:
  "Shared numbers for the DLD port: `helab/analysis/physics.py` (the constants table;
  `resolve` layers lab, folder and plot values into a `ResolvedConstants` that a run
  records and passes to every conversion), `fits.py` (`fit_histogram`: bounded histogram
  fits, Poisson likelihood by default, failures as results; register models in `MODELS`)
  and `estimates.py` (`Estimate`, `format_uncertainty`, `pooled_mean_and_std`, `sewm`)."
- **roadmaps/dld-front-panel-port.md:** mark F0's numeric half built (the overview's
  checklist in `_readme.md`, if F0 is split there), and in Decided → Fits add "Fits are
  Poisson maximum-likelihood by default", "the TF exponent is 2 for full histograms, 3/2
  for a slice" and "bimodal R/σ_th ≤ 2", if Tony agrees.

## For F0b (constants UI and store)

- Build the Settings → Lab parameters rows from `physics.CONSTANTS`: title, unit, default,
  source as the tooltip, an "unconfirmed" mark, `level` deciding lab tab vs folder
  settings, `shown_only` rows not used in formulas, the fall time shown as derived
  (`Constant.derived`) with a "set by hand" option.
- Store each layer as a plain `{key: float}` mapping and call
  `resolve(lab=…, folder=…, plot=…)` when a run starts (on the GUI side, before compute);
  validate input first, since `resolve` raises `ValueError` on unknown keys and
  non-positive or non-finite values.
- Put `ResolvedConstants.as_record()` in the run's effective parameters or record, show
  `origins[key]` beside each value ("lab", "folder", "this plot", "derived", "default"),
  and show `notes` (the fall-time disagreement) in the settings and the plot's line.

## For D1 / D4

- D1: histogram with `stats.histogram`, then `fit_histogram(bin_centres(h.edges), h.counts,
  "gaussian")` (raw counts; pass `sigma=` for rates or smoothed counts). On T,
  `temperature_estimate(Estimate(g·σ_t, g·SE), constants)` (σ_v from
  `sigma_v_from_arrival_width(σ_t, constants)`); on X/Y,
  `sigma_v_from_transverse_width(σ_x, constants)`. Show `failure` or `notes` on the plot,
  values with `Estimate.text(unit=…)`, draw `result.evaluate(fine_x)`, record
  `result.as_record()`.
- D1 registers the arrival-time ("Yavin") profile as another `FitModel`: parameters with
  roles (and gates if it has parts), `guesses(x, y, errors)`, `bounds(x, y)`, `areas`.
- D4: `bimodal_tf2_gaussian`; R is `result["radius"]` (an extra), N0/N
  `result.derived(…)` from `model.areas(p)`. Read "consistent with 0" notes as "no
  condensate" or "no thermal part". Offer `max_radius_ratio` as a plot setting and show
  the "TF radius at its limit" note. Add the g_{5/2} thermal part as a model. Consider
  integrating the model over bins when they are coarse compared with R (notes.md).
