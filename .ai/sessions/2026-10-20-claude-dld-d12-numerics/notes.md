# D12/D13 correlation numerics: notes

Code: `helab/analysis/correlations.py`; tests: `tests/test_correlations.py`. The legacy
`DLD_front_panel` checkout was empty here, so everything is derived from the physics and the
review notes ([core-update.md](../2026-10-20-claude-dld-front-panel-review/core-update.md#correlations-libcorrelations-the-main-new-capability)).

## Estimator

    g²(Δ) = [H_in(Δ) / P_in] / [H_between(Δ) / P_between]

- **Ordered pairs** everywhere. Each unordered pair is counted from both of its events, so
  `P_in = Σ_s n_s(n_s − 1)` and `P_between = Σ_{s≠t} n_s n_t = (Σn)² − Σn²`: twice the brief's
  Σ n(n−1)/2 and Σ_{s<t} n_s n_t, a factor that cancels. Gains: the 1D collinear histogram is
  symmetric by construction (tested), all counts are integers (so an incremental update
  equals a full recompute exactly), and BB, CL and radial share one code path.
- **Bin volumes cancel** (window area × width, shell volume): both histograms have them.
- **Why each histogram over its pair total** (as the legacy code): it removes shot-to-shot
  atom-number noise, which would otherwise raise g² at every Δ (by Var_tech/⟨N⟩²). The cost
  is that the pair-total normalisation fixes the A-weighted mean of g² at 1, so the bump
  itself pulls g² down by β = ∫(g² − 1)A / ∫A (A the cloud's autocorrelation). Derivation:
  E[H_in] ∝ S ∫ρ₁ρ₁ g² over pairs at Δ and E[P_in] ∝ S ∫∫ρ₁ρ₁ g², while the between-shot
  terms carry no g²; their ratio is g²(Δ)/(1 + β). For a Gaussian peak σ_c in a Gaussian
  cloud σ on each axis, β = (σ_c²/(σ_c² + 2σ²))^{3/2} ≈ (σ_c/(√2σ))³: the "1/number of modes"
  of a thermal source; 5·10⁻³ in the tests' simulation, ≪ 10⁻³ for real clouds. Not
  corrected; it's in the module docstring. Proposed, for Tony: leave it (the same bias as
  the old code), or offer normalising by shot counts instead (H_in/S over H_between/S(S−1):
  unbiased for g² but carrying technical number noise).
- **1D window** is a half-width on each transverse component (|Δv_⊥| ≤ w), proposed for
  Tony (the legacy `one_d_window` naming didn't say). A Gaussian peak is diluted by about
  1 − w²/(6σ_c²) per windowed axis (the test uses this).
- **Radial bin centres** are each shell's pair-weighted mean radius for a flat pair density,
  ¾(b⁴ − a⁴)/(b³ − a³), not the edge midpoint (the legacy code's admitted error).
  `radial_edges(r, bins)` gives equal-volume shells, an option beside `linear_edges`.
- **Bins** are [e_k, e_{k+1}), the last closed (`np.histogram`'s rule).

### Back-to-back (D13)

Δ = v₁ + v₂ − 2·origin. Searched as |v₁ − (2·origin − v₂)| (the tree holds the reflected
events); the in-shot search excludes an event paired with itself (it would sit at
2(v − origin)). Without an origin the events must be centred: a source moving at δ puts the
peak at 2δ (tested), and the result says so in a note.

### Banded between-shot reference (the "sampled subset", optional)

`partners=K` pairs each shot only with the K shots before and after it (in the order added)
for the between-shot histogram; P_between sums n_s n_t over the same pairs. Cost ~2KS shot
pairs instead of S². Unbiased when shots are interchangeable; under a slow drift through a
run it is *less* biased than all pairs (neighbours share conditions), but noisier (fewer
reference pairs; with ~K/S of them the reference noise grows by ~√(S/2K)). Deterministic, so
a Live update equals a recompute (tested). Proposed, for Tony: off by default; worth it for
runs of hundreds of shots (see Speed). Rejected alternative: random shot pairs (not
reproducible, and Live-unfriendly).

## Implementation

- Pairs: `scipy.spatial.KDTree.sparse_distance_matrix` (p = ∞ on axes scaled so the 1D
  slab |Δ_axis| ≤ L, |Δ_⊥| ≤ w becomes a cube of half-width w; p = 2 radially), radius
  widened by 10⁻⁹, then each pair's separation is recomputed from the raw events and
  filtered exactly. The separations are symmetric in floating point (−(a − b) is b − a,
  a + b is b + a), so a pair is binned the same from either side. Query points go in blocks of
  2048 (bounded memory; cancellation polled per block). `KDTree` is SciPy's thin subclass of
  `cKDTree` (pyright can't see `cKDTree` in SciPy's stubs).
- `count_neighbors` was measured and rejected: with 30 radii it took 11 s for 10⁵ points,
  ~4× slower than enumerating the same pairs.
- `PairCounts` (the Live state) holds per shot: the events, its in-shot histogram (`InShot`,
  also put in the caller's cache under `(shot, fingerprint, spec.key())`), R_s (ordered
  between-shot pairs with its event first) and Q_s (Σ n_s n_t over its partners). Adding a
  shot queries it against the held shots' trees once and updates R/Q on both sides;
  `remove` subtracts the same counts. Held shots' trees are grouped like a binary counter
  (blocks of 1, 2, 4… shots, merged when an equal one follows), so building S shots costs
  O(N log S) in tree builds. A full build is just adds in order, so a budget stop leaves an
  exact state of the shots added, and a later `update` continues it.
- `spec.key()` covers the binning, mode, axis, window, origin and `events_key` (anything
  upstream that changes the events but not their TXY fingerprints: release time, fall
  distance, masks, unit). Partners aren't in it (they don't change in-shot counts).
- Cancellation: `_check` before each add and per query block; an add/remove applies its
  counts only after all are computed, so a cancelled one leaves the state as it was
  (tested); the bootstrap polls between resamples.
- Time budget: `clock()` read at the start and before each add; the shots not added are
  reported (`shots_used`, `complete`, a note), and g² is exactly those shots' (tested equal
  to a run on them alone). A budget smaller than one shot's work still finishes that shot
  once started (a shot is never half counted).

## Errors and the fit

- **Shot bootstrap** (`bootstrap.bootstrap_shots`, seeded, 1000 resamples by default) of
  [Σ_draw H_in / Σ_draw P_in] / [Σ_draw R / Σ_draw Q]. No pairs are recounted. A drawn shot's
  R_s stays its count against all the other held shots (never against copies of itself in
  the draw), so the replicates carry each shot's numerator and its share of the reference.
  It slightly underestimates the reference's own noise (the reference has ~S× more pairs
  than the numerator, so this is second order). Across 8 simulation seeds the radial g²(0)
  scatter (0.034) matched the bootstrap SE (0.031).
- **Counting SE** g²√(1/H_in + 1/H_between) is kept beside it (`counting_se`) but
  underestimates: pairs sharing an event aren't independent, and bunched pairs come in
  clumps.
- **Fit**: `fits.fit_histogram` with local models (not registered in `fits.MODELS`, to stay
  out of others' files): `G2_GAUSSIAN` 1 + A exp(−(x − c)²/2σ²) for 1D (the centre free:
  BB shifts it), `G2_GAUSSIAN_CENTRED` 1 + A exp(−r²/2σ²) for radial. Weights: the bootstrap
  SE floored at a one-count error √max(H_in, 1)·(P_between/P_in)/H_between, since a bin with
  0 pairs has a bootstrap SE of 0. g²(0) = 1 + A ± SE(A). The baseline is fixed at 1, as the
  legacy 2-parameter fit (the normalisation puts it there); proposed for Tony: a free
  baseline option if real data shows a slope.
- A noise-free curve fitted this way returns its g²(0) to 0.1 % (checked by hand).

## Simulations in the tests

- **Thermal (chaotic) source**: per shot a complex Gaussian random field ψ = Σ c_k e^{ik·v},
  512 plane waves, k ~ N(0, 1/(2σ_c²)) per axis, c_k circular Gaussian; events are a Cox
  process with density ∝ envelope × |ψ|² (rejection sampling of Gaussian candidates, bound
  12 on |ψ|²). By Isserlis ⟨|ψ(x)|²|ψ(y)|²⟩ = 1 + |g¹|², |g¹|² = exp(−Δ²/2σ_c²). Finite K adds
  (1 − |g¹|²)/K. Expected g²(0) = 2/(1 + β + (1 − β)/K) = 1.986 (σ_c = 0.1, σ = 0.4, K = 512).
  float32 phases make it 4× faster (40 shots × ~400 events ≈ 2 s).
- Seeds 0–7 (40 shots each): radial g²(0) pulls against 1.986 were +1.2, +0.8, +0.8, +3.1,
  +0.2, +0.8, +1.9, 0.0 (SE ≈ 0.032); 1D (w = 0.15σ_c) −1.8, +0.6, +0.1, −1.7, −2.6, −0.3,
  −0.8, +2.5 (SE ≈ 0.09). Pooling 320 shots: 2.004 ± 0.012 against 1.986 (+1.5 SE), with bin
  residuals mostly +1 SE: a radial excess of ≲ 1 %, within the statistics but worth a larger
  check before real data (proposed, for Tony). The test uses seed 1 and checks within 3 SE of
  the expectation and within 0.15 of 2.
- **Uncorrelated (Poisson)**: Gaussian clouds; ≥ 90 % of bins within 3 SE of 1, the weighted
  mean within its error.
- **Back-to-back pairs**: a halo (radius 0.3) of pairs u, −u blurred by 0.01, plus
  uncorrelated halo events. BB peaks at 0 with σ = 0.01√2 (tested); shifted to 2δ when the
  source moves by δ and no origin is given; at 0 again with origin δ. Collinear g² on the same
  events has no peak at 0. The BB amplitude here is only ~2: random halo pairs also sum near
  0 on a thin shell, so the tests check significance (> 10 SE) rather than a value.
- **Counts against brute force**: in-shot and between-shot histograms, P and Q, for 1D CL,
  1D BB with origin on another axis, radial CL, radial BB with equal-volume bins, and banded
  partners, with a nan row and a one-event shot.

## Speed (4 shared cores, loaded by other workers)

- 50 shots × 2000 events, cloud σ = 1 per axis, with a 1000-resample bootstrap and the fit:
  1D (L = 0.3, w = 0.02): ~1.4 s; radial r ≤ 0.3: ~3.5 s (2.4·10⁷ between-shot pairs);
  radial banded (K = 5): ~1 s. The test allows 20 s for a loaded machine.
- Cost is the number of pairs within reach: ~N²·f with f the share of pair separations
  inside the bins, plus N log S tree builds. A radial reach comparable to the cloud is the
  slow case (all pairs); real correlation lengths are much shorter than the cloud.
