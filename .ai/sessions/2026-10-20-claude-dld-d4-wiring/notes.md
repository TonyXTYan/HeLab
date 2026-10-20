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
  shown run used: a lab QE change doesn't mark a Gaussian-only plot.

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
- **Reuse key keeps every constant.** `AnalysisResult.reuse_key()["constants"]` is the full
  `constants_record`, which `ResolvedConstants.from_record` must read back
  (`test_constant_layers.py::test_the_result_records_the_constants_it_ran_with`), so a Gaussian-only
  run's key still holds the QE even though its plot isn't marked when the QE changes. Narrowing it
  to `constant_keys` (and reading back with defaults for the rest) is a choice for R2/R3, when
  reuse is first used; tried here and reverted to keep that invariant. The key carries constants
  only when a fit is on (`run_constants` None otherwise), as the brief asks.
