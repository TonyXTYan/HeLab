# D8 part 2 brief: Velocity distributions plot

Worker brief from the DLD Coordinator, 2026-10-20. Branch `agent/dld-d8-velocity` from `7ff350b`
(D8 part 1 merged). A first worker was interrupted by a container restart; a second recovered its
uncommitted work (commit `719b834`) and finished it.

1. Convert the chosen shots' events (shared Shots, own View range in TXY, Mask group) to velocities
   with the run's constants: t_r from `release.layer_release_time`, else detected in the same run
   (`release.detect_release_time`, no bootstrap, said in the line); origin from `layer_origin`, else
   detected, else assumed (0, 0) with a note. Never reuse another plot's t_r.
2. v_z, v_x, v_y histograms (optional 2D v_x–v_y / v_x–v_z density) in m/s, mm/s or recoil units
   (ħk/m, 2ħk/m); z up; optional Gaussian fit per axis with σ_v ± SE and T = mσ_v²/k_B.
3. Constants (h, g, t_f, arrival/release, trap origin, recoil wavelength: a lab-level unconfirmed
   row `recoil_wavelength`, 1083.331 nm) via `constants_specs`/`constant_keys`; records with the t_r
   used and its source; sensible Live policy; wrapped titles, AMBER; in-place update.

Acceptance: a cloud released at rest maps to v ≈ 0 with the folder's arrival, a launch velocity
maps right; recoil unit; origin offset; detected vs folder t_r sources in the record; masks reduce
counts; empty cases; units text; registration in the shared tests; mypy --strict, pyright,
`git diff --check` clean; full suite clean except the two root-only failures.
