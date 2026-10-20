# D4/D14 wiring notes

## What changed

- `helab/analysis/bec_readout.py` (new): `BecReadout` / `readout()` / `choose()`: one axis's fit
  through `bec.from_fit`, a compact header block (`title_lines`), every number and note for the
  record (`record_lines`, `as_record`, strict JSON) and the unconfirmed constants (`⚠ unconfirmed:
  QE 0.1 (N, N0 ∝ 1/QE), trap 500 Hz / 50 Hz (Tc, μ, R(0), n0)`). A slice fit gives T and R(0) only
  and flags only the trap frequencies (no atom numbers, so the QE doesn't enter).
- `profiles.AxisFit.text()` / `.decision`: "no condensate (z = …)" or "possible condensate, not
  reported (z = …)" on the fit line; the plot's title drops the "condensate:" / "no condensate"
  decision note (its why is in the record) and keeps "possible condensate … not reported: why"
  in amber.
- `basic_plots.py`: `BEC` ("Show BEC properties", off, Fits page) and `BEC_AXIS` ("BEC properties
  from": auto, T, X, Y); fits get `shots=`; constants rows for QE, trap frequencies, axial axis
  and scattering length shown only while `bec_constants_used` (a fitted axis with a bimodal model,
  or BEC properties with any fit); version 7; Live `min_delay` 2 s; a parameter warning when BEC
  properties are on without a fit.
- `ParameterSpec.shown_with` (a callable condition beside `when`, not compared) and
  `apply_visibility` honouring it.
- `DatasetAnalysis.run_constant_keys(action, values)`: the keys a run uses (default: all of
  `constant_keys`). The runner records those on the result, so the reuse key, the header's
  "Fits with …", the dock's "constants:" and the "constants changed" mark name only the keys the
  shown run used: a lab QE change doesn't mark a Gaussian-only plot. If `run_constant_keys`
  raises, the runner logs it and keeps the resolution with every declared key.
- **Reuse key and records** (after the merge with D8, whose `ResolvedConstants.as_record(keys)`
  and `AnalysisResult.constants_record` narrow to `constant_keys`): `reuse_key()["constants"]`
  holds only the run's `run_constant_keys`: no fit, no constants; a Gaussian-only fit
  `fall_distance, fall_time, g, k_B, mass`; a bimodal fit or BEC properties those plus
  `detector_qe, hbar, scattering_length, trap_axial, trap_axial_axis, trap_radial`. The layers
  keep only those keys, and an empty layer is left out. The histograms' `found["constants"]` is
  `as_record(self.constant_keys)`, so it agrees with the result's own record.
  `ResolvedConstants.from_record` reads back only whole records: when R2/R3 first read a reuse
  key's constants back they need a `keys=` variant (defaults or "unknown" for the rest).
- **Hidden settings stay out of the reuse key:** `parameters.unused_parameters(specs, values)`
  (rows whose `when` / `shown_with` doesn't hold) is computed by the runner, carried as
  `AnalysisContext.unused` / `AnalysisResult.unused`, and `reuse_key()["parameters"]` leaves them
  out (e.g. σ X/Y with Smooth off, Y's model with Fit Y off, "BEC properties from" with the
  readout off). `result.parameters` and the record still have every value. AnalysisResult can't
  reach the specs, hence the field.
- The plot's "constants:" line and the "constants changed" mark use `result.constant_keys` as is,
  for any run with resolved constants (no fallback to the plot's declared keys).

## Cost (294k events, 5 shots, whole compute)

Gaussian ×3 0.3 s; one bimodal TF + Bose 2.0 s; three bimodal/fits + BEC 3.3 s; the readout
alone ~2 ms (one ODE). Earlier measurement by the first worker: 0.6 s on a condensate axis, 2.4 s
on a thermal axis (the free-z partner fit). Live `min_delay` 1 s → 2 s (a run is never cancelled;
the worker is shared), like the other heavy plots.

## Proposed, for Tony

- **auto source for BEC properties:** a fit that reports a condensate first, then a full
  projection over a slice, then an axis along a radial trap axis (T unless Trap axial axis says
  otherwise), then T, X, Y order. The setting can name an axis.
- **Header block content:** N, N0, N0/N, T, Tc, Tc0, T/Tc, μ/k_B, R(0) ⊥ and z, n0 (cm⁻³), R(0)
  fitted, QE from R, QE from thermal. The record adds Tc ideal / finite size, T/Tc0 from N0/N,
  μ/k_BT, saturated thermal N, R(t_f), μ and N0 from R, ω̄ and a_ho, and every note.
- **Explanatory notes only in the record** ("N and N0 per shot", "T from …", the QE/thermal
  explanations, the slice note); warnings stay in amber in the header.
- **Trap rows shown with a bimodal fit even without BEC properties**, since the bimodal's cap and
  its condensate check use the trap, QE and scattering length.
- **Live wait 2 s** (Live settings can lower it per plot).
