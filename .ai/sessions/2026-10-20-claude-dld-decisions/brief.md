# DLD decisions: brief (Worker, 2026-10-20)

Branch `agent/dld-decisions` from `fb47de7` (agent/dld-front-panel-port with all seven DLD
branches merged). Coordinator: the DLD coordinator session
([register](../2026-10-20-claude-dld-coordinator/register.md)).

Implement Tony's decisions of 2026-10-20:

1. Every time axis in ms (never s), thousands grouped "," and "." whatever the locale
   (`1,234.5678 ms`), tick labels too (an `AxisItem` with `tickStrings`); one module for display
   units (`helab/analysis/display_units.py`), duplicates deleted; View-range T bounds shown in ms,
   stored in SI. Frequencies stay Hz/kHz; durations that aren't axis positions stay as they are.
2. X and Y in mm everywhere they're displayed.
3. TF exponent: offer p = 2 and p = 3/2 on the bimodal fits, with the caveats in the tooltip.
4. D1 adopts F0b's constants API (`constants_specs`, `constant_keys`), constants once in the record.
5. Shot times (D7): keep the rule, say why (raw `d*` files are never rewritten), and make sure no
   raw file is re-stat'ed while its TXY fingerprint is unchanged.

Folded in mid-task from the coordinator: the integration-seam review (A–E: D1's full constants fix
with `run_constants` → `None` without fits, raising dock hooks, D5/D6 record in `found`, one
`si_text`, `SpectrumPeak`, `record_text` limited to the analysis's keys), the physics review (TF
tooltip wording, `max_radius_ratio` through `fit_axis`, the R/σ cap comment, D1's arrival-time
model on the effective fall distance) and the tests review (constants fixture, a transposition
test for the density images, the ms/s tests).

Not to edit: AGENTS.md, roadmaps/, .ai/memory/, .ai/MANUAL_TODO.md (text proposed in handoff.md);
release.py, velocity.py and fits.py's offset bounds (another worker).
