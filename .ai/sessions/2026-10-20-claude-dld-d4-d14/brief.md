# D4/D14 numerics brief (2026-10-20, Claude, Worker)

From the Coordinator: the numerics of D4 (bimodal BEC fits) and D14 (BEC properties) of
[the DLD front panel port](../../../roadmaps/dld-front-panel-port.md), on branch
`agent/dld-d4-d14` from `6ed1ec9` (`agent/dld-front-panel-port` with the merged DLD work,
the physics fixes and Tony's ms/mm decisions). Numerics and the fit options' plumbing in
`profiles.py` only; not `basic_plots.py` rendering (the polish worker), not the trends plot
(D2) nor `correlations.py` (D12). A later step wires D4 into the histograms plot.

Deliverables, with the physics reviewer's guidance:

1. `fits.py`: g_5/2 and g_2 thermal models (fugacity 0 < z ≤ 1, robust polylogs), bimodal
   TF² + g_5/2 and TF^3/2 + g_2 with a shared centre, a per-axis R/σ_th cap API, an N0/N helper
   with its SE by the delta method from the areas' covariance.
2. `helab/analysis/bec.py` (new): Tc0 = 0.94 ħω̄N^{1/3}/k_B, finite-size −0.73 (ω_arith/ω̄)N^{−1/3},
   interaction −1.33 (a/a_ho)N^{1/6}, μ = ½ħω̄(15 N0 a/a_ho)^{2/5}, R_i, n0, a_ho, ω̄ = (ω_⊥²ω_z)^{1/3};
   T/Tc and N0/N; Castin–Dum λ_i(t) (ODE, and the cigar approximations tested against it); R(0)
   from R(t); ± SE (`estimates.propagate`); a typed result with notes.
3. `physics.py`: rows for the detector QE (lab, unconfirmed) and the trap-axis mapping (folder,
   unconfirmed); a third trap frequency if useful.
4. `profiles.py`: the new models in T_MODELS/XY_MODELS with tooltips (pairing, the cap's axis
   dependence, windowing).
5. Tests on synthetic Bose clouds, mixtures, hand-computed D14 values and limits, Castin–Dum
   vs ODE, polylog accuracy, edge-case notes. Bootstrap: recommend n_boot ≈ 200.

Acceptance: strict mypy and pyright on helab and tests, `git diff --check` clean, the full
suite clean except the two root-only failures. Commit; don't push or merge.
