# Brief: DLD physics fixes (Worker)

From the Coordinator, after the physics review of `agent/dld-d8-d10` (merged as `fb47de7`).
Branch `agent/dld-physics-fixes` from `fb47de7`; not pushed or merged.

Owned: `helab/analysis/release.py`, `velocity.py`, `bootstrap.py`, `peaks.py`, and in
`fits.py` only the offset bounds. Tests in `tests/test_velocity.py`, `tests/test_bootstrap.py`,
`tests/test_fits.py` (append).

1. Release time: wide clouds bias the Gaussian centre (+32.9 µs at 1.5 µK, SE 12.8 µs).
   Refit the arrival peak with `fits.arrival_time_model(effective_fall_distance(C), C.g)`,
   whose centre is the v = 0 arrival; the Gaussian + skew note only as a fallback.
   Test: 1.5 µK, 20 seeds, bias within ~1 SE of 0.
2. Fits: with Poisson count weights on raw counts, the offset's lower bound is 0 (negative
   offsets made the model negative in the tails in 117/200 sparse fits); −top stays for
   `sigma=` / rates. Test.
3. Velocities: an XY origin (x₀, y₀) detected from the rest cloud (its XY centre ± SE) in
   `release.py`, recorded in the result; `txy_to_velocity(origin=…)` (default (0, 0), saying
   the trap is then assumed above X = Y = 0), a manual override. Test with back-to-back pairs.
4. Bootstrap: a convenience for the SE over shots of a per-shot-mean statistic, if natural
   (D5 will use it).
5. Docstrings: "within run (events independent)" for SEs that ignore shot jitter; point to
   `bootstrap_release_time`.

Acceptance: those tests; `mypy --strict helab tests`, `pyright helab tests`,
`git diff --check` clean; full suite clean except the two root-only failures.
