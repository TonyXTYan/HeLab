# D12/D13 correlation numerics brief (2026-10-20, Claude, Worker)

From the Coordinator: the pure-numbers part of D12 (collinear g²) and D13 (back-to-back g²)
of [the DLD front panel port](../../../roadmaps/dld-front-panel-port.md), on branch
`agent/dld-d12-numerics` from `fb47de7` (D8/D10 merged: `velocity.py`, `bootstrap.py`).
New files only (`helab/analysis/correlations.py`, `tests/test_correlations.py`); no plot yet
(a later worker adds it once the units/velocity changes land). Not pushed or merged.

Inputs: per-shot velocity-space events (N×3, m/s, `velocity.VELOCITY_AXES` order) with shot
labels.

1. Pair counting with `scipy.spatial` KD-trees, never O(N²) Python loops: in-shot pairs and
   between-shot pairs (the normalisation) for the 1D cartesian-windowed g²(Δv_i) with
   transverse windows (`corr_1d_cart`), radial g²(|Δv|) (`corr_radial`), and back-to-back
   (v₁ + v₂, with an optional origin; D13). Correct combinatorial factors; document the
   estimator, a sampled between-shot option and its bias.
2. Cancellation (`cancelled`, raising `results.Cancelled`) between shots and inside the pair
   loop; a time budget that stops early and reports partial coverage, never a wrong number.
3. Per-shot reuse for Live: in-shot counts cached by (shot, fingerprint, binning key) in a
   caller's dict; between-shot counts updated incrementally (new shot against all held).
4. Errors: shot bootstrap from the per-shot counts; a Gaussian + 1 fit of the peak
   (amplitude g²(0) − 1, width, ± SE).
5. A typed result (bins, g², SE, pair counts, shots used, notes) with strict-JSON `as_record`.

Acceptance: a simulated thermal source gives g²(0) ≈ 2 within SE, a Poissonian one g² ≈ 1,
simulated BB pairs peak at v₁ + v₂ = 0 (at twice an origin offset without the origin);
cancellation; partial coverage under a budget; incremental = full recompute; 50 shots ×
2000 events in a few seconds; strict mypy, pyright, `git diff --check`; full suite clean
but for the two root-only failures.
