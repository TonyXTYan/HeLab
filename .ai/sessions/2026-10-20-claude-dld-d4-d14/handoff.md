# D4/D14 handoff (2026-10-20, Claude, Worker)

Branch `agent/dld-d4-d14` (from `6ed1ec9`), one commit; not pushed or merged. Details and
derivations: [notes.md](notes.md).

## API

```python
from helab.analysis import bec
from helab.analysis.fits import condensate_fraction, component_areas, polylog
from helab.analysis.profiles import (BOSE, BOSE_SLICE, BIMODAL_BOSE, BIMODAL_BOSE_SLICE, BIMODALS, BOSES,
                                     fit_axis)

fitted = fit_axis(axis, edges, counts, choice, constants, smoothing, max_radius_ratio=None)  # per-axis cap
condensate_fraction(fitted.fit)            # Estimate N0/N (nan for non-bimodal or failed fits)
props = bec.from_fit(fitted.fit, axis, constants, bin_width=float(np.mean(np.diff(edges))), shots=n_shots)
props.tc, props.t_over_tc, props.fraction, props.chemical_potential, props.radii, props.peak_density
props.notes                                # tuple[str, ...]: show them
props.from_radius                          # RadiusCheck | None: R(t_f), R(0), μ and N0 from R, implied QE
props.as_record()                          # strict JSON for the result's record
bec.axis_caps(constants, mu_over_kt=2.0)   # {"T": …, "X": …, "Y": …}
```

`from_fit` works for every model with areas and a `sigma` (Gaussian, Bose, bimodals; the
arrival-time model too, its σ is σ_v/g): a thermal-only fit gives N0 = 0, Tc, T/Tc and notes.
Numbers are per shot (the histogram's events / shots / QE).

## Wiring into the histograms plot (`basic_plots.py`, the next step)

1. **Caps:** `fit_axis` now defaults to `max_radius_ratio=None`, the per-axis cap from the
   constants (`profiles.axis_cap`), so today's calls already use it. A plot setting "μ/k_B T at
   most" (default 2) can pass `bec.axis_caps(constants, mu)[axis]`.
   **Condensate check:** the TF + Bose choices fit the free-z Bose profile too and fall back to it
   with "no condensate (z = …)" in `AxisFit.notes` (`fits.choose_condensate`; rule in notes.md,
   "Review fixes" and "Re-review fixes"). Show that note on the fit line ("no condensate",
   "possible condensate … not reported: why" or "condensate: …"). **Pass `shots=`** (the shots the
   histogram sums) so the μ/k_BT check runs. Slice models carry `fits.SLICE_NOTE`.
   **D2 (per-shot fits) should make the condensate decision per shot:** summed shots with jittered
   widths aren't one profile, and at millions of events the summed-shot decision often ends at
   "possible condensate". Smoothed N0/N SEs look ~4.6× too small (notes.md): don't show them yet.
2. **Constants:** add `"trap_radial", "trap_axial", "trap_axial_axis", "detector_qe",
   "scattering_length", "hbar"` to `CONSTANT_KEYS` (so a change marks the plot) and the folder
   ones (`trap_radial`, `trap_axial`, `trap_axial_axis`) to the plot's `constants_specs` when a
   bimodal or BEC readout is on. Bump the script version.
3. **Model tips:** the model choice's tip already ends with `profiles.TF_EXPONENT_TIP`, which now
   covers the Bose models, pairing and the cap. Its first sentence in `basic_plots.py` ("the
   condensate fraction is the BEC fit's, later") should drop "later" and mention the Bose models.
4. **Fit line:** `AxisFit.text()` now adds `N0/N …` for bimodals and `z …` for Bose fits; nothing
   else to do for it.
5. **"BEC properties" readout** (an option beside each bimodal fit, or one line under the plot
   for a chosen axis; proposed: one per fitted axis, in the fit's tooltip, with the T axis's in
   the dock line):
   - `N 7.0(2)×10⁵ · N0/N 0.43(1) · T 0.60(2) µK · Tc 1.00(1) µK · T/Tc 0.60(2) · μ 220(5) nK · R(0) 9.7(2) µm`
     (μ as μ/k_B in nK; radii in µm; n0 in cm⁻³ is customary: n0 × 10⁻⁶).
   - Show `props.notes` (amber for "unconfirmed" ones) and, when `from_radius` has an
     `implied_qe`, "QE from R: 0.09(2)": the quickest check of the QE and the trap frequencies.
   - Compute in `compute` (worker thread): `from_fit` solves one ODE (~6 ms) per call.
   - Record `props.as_record()` beside the fit's record.
6. **Errors:** the SEs are the fit's (Poisson) only. A shot bootstrap (`bootstrap.bootstrap_shots`)
   of the whole fit + `from_fit` is the fuller error; use `bec.FIT_N_BOOT = 200` resamples (each
   refits: ~0.1–0.3 s per bimodal fit, so 20–60 s, opt-in and cancellable).

## For the Settings / polish worker

- `physics.Constant` has `maximum` and `choices`. `LabParametersTab.constant_editor` bounds by
  `maximum` and shows a coded row as a whole-number spin box; a drop-down with the labels
  (`constant.choices`, `constant.label(value)`) would be clearer in Lab parameters and Folder
  constants. `constant_layers.value_text` already shows the label ("between X and Y").
- New rows: `detector_qe` (lab; listed in Lab parameters, editable, no unit) and
  `trap_axial_axis` (folder; listed in Folder constants).

## Validation

- New: `tests/test_bose_fits.py`, `tests/test_bec.py`; updated: `tests/test_physics.py`,
  `tests/test_lab_parameters.py` (row lists).
- `mypy --strict helab tests`, `pyright helab tests`: 0 errors. `git diff --check`: clean.
- Full suite before the review fixes (`-n 2 --reruns 5 --reruns-delay 1 -rR`): `2 failed, 1780 passed, 7 skipped, 2 xfailed, 2 warnings, 10 rerun in 227.82s`. The two failures are the root-only ones (`test_constants.py::test_read_only_saved_folder_is_replaced`, `test_cache_mover.py::test_recovery_isnt_usable_after_a_failed_settings_write`), and all 10 reruns are theirs (5 each): no other test needed a rerun.
