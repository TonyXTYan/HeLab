# D4/D14 wiring brief (2026-10-20, Claude, Worker)

From the Coordinator: wire D4/D14 (Bose fits, condensate decision, `bec.from_fit`) into
"T, X, Y histograms" (`helab/scripts/standard/basic_plots.py`), per
[the D4/D14 handoff](../2026-10-20-claude-dld-d4-d14/handoff.md):

1. Bimodal choices per axis with the condensate decision (`shots=`, per-axis caps): titles show
   "N0/N 0.304 ± 0.004", "no condensate (z = 0.37)", or amber "possible condensate … not
   reported: why"; slice models "N0/N (slice)".
2. "Show BEC properties" (off by default, Fits page) from a chosen fit via `bec.from_fit`; compact
   wrapped block in the title, full set in the record (found `record_lines` + JSON); unconfirmed
   constants amber; slice fits only T and R(0).
3. The trap's constants (QE, trap frequencies, axial axis, scattering length, ħ) in
   `CONSTANT_KEYS` / `constants_specs` only when a bimodal fit or BEC properties is on.
4. Bump the version; measure the cost on ~300k events and set the Live `min_delay`.

Branch `agent/dld-d4-wiring` from `7fa394f`; at the end merge `7ff350b` (D8 part 1). A first
worker was interrupted by a container restart; a second recovered its uncommitted work.
