# D8 part 2 handoff: Velocity distributions

Branch `agent/dld-d8-velocity`, from `7ff350b`. Not pushed or merged. Design and the choices
proposed for Tony: [notes.md](notes.md). Brief: [brief.md](brief.md).

## Done

See notes.md "What was built". Validation: `mypy helab/ --strict`, `mypy tests --strict`,
`pyright helab tests` clean; `git diff --check` clean; the full-suite line is in the final commit
message.

## Offering velocity axes on the histograms and density plots later

The conversion is one call once t_r and the origin are known, so other plots can offer a
"Velocity axes" choice without new physics:

1. Add `OWN_KEYS` of this plot (fall_distance, fall_time, g, release_time, arrival_time, trap_x,
   trap_y, recoil_wavelength) to the plot's `constants_specs`/`constant_keys`, so a folder's
   "Use for this folder" marks it.
2. In `compute`, reuse this plot's resolution order: `layer_release_time` → else
   `detect_release_time` (said in amber) → `velocity_origin(detection, layer_origin(...))`. Worth
   lifting `VelocityDistributions.compute`'s block (lines "t_r: the layers'…" to the `replace(...)`
   with the origin) into a helper in `helab/analysis/release.py`, e.g.
   `resolve_release(events, constants, search) -> (release, source, how, detection, origin, origin_how)`,
   along with `release_source_text`, `release_line`, `origin_line` and `ASSUMED_NOTE`/`DETECTED_NOTE`.
3. Convert with `velocity.txy_to_velocity` and bin the `valid` rows; the histograms
   (`basic_plots`) then label `v_z`/`v_x`/`v_y` with `unit_factor` and keep their own
   selection/crop. The View range stays in TXY (the crop runs before conversion), so velocity-space
   bounds would be a new setting.
4. Density images: v_x–v_y is a linear rescale of X–Y only per arrival time, so it must bin
   converted velocities (as `_density` here), not rescale the XY image.
5. D12/D13 (correlations, halos) take the same velocities; the shared helper in 2 is what they need.
