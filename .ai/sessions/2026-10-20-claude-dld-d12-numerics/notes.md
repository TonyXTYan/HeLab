# D12/D13 correlation numerics: notes

Code: `helab/analysis/correlations.py`; tests: `tests/test_correlations.py`. The legacy
`DLD_front_panel` checkout was empty here, so everything is derived from the physics and the
review notes ([core-update.md](../2026-10-20-claude-dld-front-panel-review/core-update.md#correlations-libcorrelations-the-main-new-capability)).
First commit 00b8e26; the Coordinator's review of it (five findings) is answered in
[Review fixes](#review-fixes-second-commit).

## Estimator

    g²(Δ) = [H_in(Δ) / P_in] / [H_between(Δ) / P_between]

- **Ordered pairs** everywhere. Each unordered pair is counted from both of its events, so
  `P_in = Σ_s n_s(n_s − 1)` and `P_between = Σ_{s≠t} n_s n_t = (Σn)² − Σn²`: twice the brief's
  Σ n(n−1)/2 and Σ_{s<t} n_s n_t, a factor that cancels. Gains: the 1D collinear histogram is
  symmetric by construction (tested), all counts are integers (so an incremental update
  equals a full recompute exactly), and BB, CL and radial share one code path.
- **Bin volumes cancel** (window area × width, shell volume): both histograms have them.
- **Why each histogram over its pair total** (as the legacy code): it removes shot-to-shot
  atom-number noise, which would otherwise raise g² at every Δ (by Var_tech/⟨N⟩²). The cost:
  the pair-total normalisation fixes the A-weighted mean of g² at 1, so the bump itself
  divides the *whole curve* by 1 + β, β = ∫(g² − 1)A / ∫A (A the cloud's autocorrelation).
  Derivation: E[H_in] ∝ S ∫ρ₁ρ₁ g² over pairs at Δ and E[P_in] ∝ S ∫∫ρ₁ρ₁ g², while the
  between-shot terms carry no g²; their ratio is g²(Δ)/(1 + β). For a Gaussian peak σ_c in a
  Gaussian cloud σ on each axis, β = (σ_c²/(σ_c² + 2σ²))^{3/2} ≈ (σ_c/(√2σ))³ (5·10⁻³ in the
  tests' simulation, ≪ 10⁻³ for real clouds). The baseline drops to 1/(1 + β) with the peak,
  so the peak over the fitted baseline, (b + A)/b, is free of β; a baseline fixed at 1 isn't
  (it reads 2/(1 + β)·… and, worse, any mismatch of the reference as bunching: below).
- **The reference must match the shots.** If the cloud moves from shot to shot (pointing
  jitter j) or changes size, between-shot pairs are broader than in-shot ones and the ratio
  is a broad bump at 0, (1 + j²/σ²)^{3/2} at its top: 1.06 for j = 0.2σ. The first commit's
  fixed-baseline fit read that as g²(0) = 1.059 ± 0.003 on uncorrelated clouds (Coordinator's
  q3). Now: a free baseline; a note when it is more than 2 SE from 1; no g²(0) when the
  fitted σ is above a third of the reach ("a slope, not a peak"); and `recentre=True`
  (each shot's mean velocity moved to 0 before counting; off by default, in the cache key).
  Re-centring leaves a residual jitter of σ/√n (the mean's own error), negligible for
  hundreds of events, and centres BB about each shot's mean (origin then relative to it).
  **Later (proposed, for Tony): a cloud-matched reference**: pair each shot only with shots
  whose centre and width (per axis, from the events' mean and spread) are within a tolerance
  of its own, the banded mechanism with a different partner rule. It keeps real shot-to-shot
  correlations (unlike re-centring, which also removes a real common-mode motion), at the
  cost of fewer reference pairs; the shot-pair matrix and its partner mask already support
  any partner set.
- **1D window** is a half-width on each transverse component (|Δv_⊥| ≤ w), proposed for
  Tony (the legacy `one_d_window` naming didn't say). A Gaussian peak is diluted by about
  1 − w²/(6σ_c²) per windowed axis (the test uses this).
- **Radial bin centres** are each shell's pair-weighted mean radius for a flat pair density,
  ¾(b⁴ − a⁴)/(b³ − a³), not the edge midpoint (the legacy code's admitted error); they only
  place points now, since the fit averages its model over each shell. `radial_edges(r, bins)`
  gives equal-volume shells, an option beside `linear_edges`.
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
  between-shot pairs with its event first), Q_s (Σ n_s n_t over its partners) and its row of
  the shot-pair matrix (partner → histogram). Adding a shot queries it against the held
  shots' trees once, split by owner, and updates both sides; `remove` subtracts the same
  counts. Held shots' trees are grouped like a binary counter (blocks of 1, 2, 4… shots,
  merged when an equal one follows), so building S shots costs O(N log S) in tree builds.
  A full build is just adds in order, so a budget stop leaves an exact state of the shots
  added, and a later `update` continues it.
- The matrix is kept while S²·bins ≤ `MATRIX_LIMIT` = 8·10⁶ (64 MB; 400 shots × 50 bins).
  Past it the state drops it for good (`matrix_kept` False) and the bootstrap falls back,
  with a note. Proposed, for Tony: a banded matrix (only partner rows) would lift the limit
  for banded runs; not needed yet.
- `spec.key()` covers the binning, mode, axis, window, origin, `recentre` and `events_key`
  (anything upstream that changes the events but not their TXY fingerprints: release time,
  fall distance, masks, unit). Partners aren't in it (they don't change in-shot counts).
- Cancellation: `_check` before each add and per query block, per jackknife shot and per
  replicate refit; an add/remove applies its counts only after all are computed, so a
  cancelled one leaves the state as it was (tested); the bootstrap polls between resamples.
- Time budget: `clock()` read at the start and before each add; the shots not added are
  reported (`shots_used`, `complete`, a note), and g² is exactly those shots' (tested equal
  to a run on them alone). A shot once started is finished (never half counted).

## Errors and the fit

- **Shot bootstrap** (`bootstrap.bootstrap_shots`, seeded, 1000 resamples by default) with
  shot multiplicities c: [c·H_in / c·P_in] / [cᵀBc / Σ_{s≠t partners} c_s c_t n_s n_t], from
  the shot-pair matrix, so the reference is resampled too and a shot's copies never pair
  with each other (B[s, s] = 0). The first commit kept each drawn shot's reference against
  all the others (c·R / c·Q), which carries only about a quarter of the reference's variance
  (Coordinator's finding 3); that is the fallback past `MATRIX_LIMIT`, noted as optimistic
  below ~10 shots. A draw of one shot only has no reference (nan, left out by the bootstrap).
- **Jackknife**: the same matrix gives the exact delete-one-shot jackknife per bin
  (`jackknife_se`, nan without the matrix); it agrees with the bootstrap within 0.6–1.6× per
  bin on the thermal test.
- **Counting SE** g²√(1/H_in + 1/H_between) is kept beside them (`counting_se`) but
  underestimates: pairs sharing an event aren't independent, and bunched pairs come in
  clumps.
- **Fit** (`peak_model(spec, baseline)` with `fits.fit_histogram`, local models not
  registered in `fits.MODELS`): b + A exp(−(x − c)²/2σ²) for 1D (the centre free: BB shifts
  it), centred at 0 radially, **averaged over each bin** with 5 Gauss–Legendre points
  (weighted by r² over radial shells: the pair density of a flat reference), so wide first
  shells of equal-volume bins don't bias the peak (finding 4; tested on a noise-free curve
  over 12 equal-volume shells). Weights: the bootstrap SE floored at a one-count error
  √max(H_in, 1)·(P_between/P_in)/H_between, since a bin with 0 pairs has a bootstrap SE of 0.
  g²(0) = (b + A)/b, b reported as `baseline`; `baseline="fixed"` keeps the legacy 1 + A fit.
  `CorrelationResult.curve(x)` draws the point model; `fit.evaluate(x)` gives bin averages.
- **g²(0)'s SE** is the spread of refits of the first `FIT_RESAMPLES` = 200 bootstrap
  replicates (same weights): neighbouring bins share shots, so the single fit's diagonal
  covariance was ~1.4× too small (finding 2). Without a bootstrap (`n_boot=0`) the
  covariance's SE is used and `g2_zero_method` says it is too small. On the twin-pair test
  source the covariance SE is 2.1× too small, the refit SE matches the scatter (1.11 over 30
  seeds; 0.74 and 1.32 on other sets of 16–40 seeds: the ratio itself is that noisy).
- **When the fit integration lands** (Coordinator, 2026-10-20): `fits.fit_histogram` on the
  integration branch averages over equal-width bins by default (`binned=True`). Merging that
  head, pass `binned=False` here (the model already averages, r²-weighted for shells) or move
  to its `edges=`/weight option once it exists; the equal-width default is wrong for shells.

## Simulations in the tests

- **Thermal (chaotic) source**: per shot a complex Gaussian random field ψ = Σ c_k e^{ik·v},
  512 plane waves, k ~ N(0, 1/(2σ_c²)) per axis, c_k circular Gaussian; events are a Cox
  process with density ∝ envelope × |ψ|² (rejection sampling of Gaussian candidates, bound
  12 on |ψ|²). By Isserlis ⟨|ψ(x)|²|ψ(y)|²⟩ = 1 + |g¹|², |g¹|² = exp(−Δ²/2σ_c²). Finite K adds
  (1 − |g¹|²)/K. So the curve is [1 + 1/K + (1 − 1/K)|g¹|²]/(1 + β + (1 − β)/K): peak 1.986 and
  baseline 0.9948 in absolute terms (σ_c = 0.1, σ = 0.4, K = 512), and **(b + A)/b =
  1 + (1 − 1/K)/(1 + 1/K) = 1.9961**, what the test now expects. (The first notes compared the
  fixed-baseline fit with 1.986, the free-baseline peak: wrong pairing, finding 5.) float32
  phases make it 4× faster (40 shots × ~400 events ≈ 2 s).
- Coordinator's q2 after the fixes (24 seeds, radial, 300 resamples): g²(0) = 2.012 ± 0.0095
  over seeds against 1.9961 (+1.7 SE of the mean), scatter 0.046 against a mean SE of 0.048.
  Per bin, scatter / bootstrap SE is 0.82–1.13. A residual ~0.8 % high is within 2 SE; worth
  a larger run before real data (proposed, for Tony).
- **Pointing jitter** (q3): uncorrelated clouds with 20 % jitter now give no g²(0) (a slope,
  σ_fit ≈ 3.4 against a reach of 0.4) and the note; re-centred they give g² ≈ 1. With 4 and 8
  shots the bin scatter over 30–60 seeds matches the bootstrap SE (0.0405 / 0.0423 and
  0.0268 / 0.0263 in q3; 1.09 and 1.06 for the test's bin average).
- **Uncorrelated (Poisson)**: Gaussian clouds; ≥ 90 % of bins within 3 SE of 1, the weighted
  mean within its error; the peak fit, when it runs, has an amplitude consistent with 0.
- **Back-to-back pairs**: a halo (radius 0.3) of pairs u, −u blurred by 0.01, plus
  uncorrelated halo events. BB peaks at 0 with σ = 0.01√2 (tested); shifted to 2δ when the
  source moves by δ and no origin is given; at 0 again with origin δ. Collinear g² on the same
  events has no peak at 0. The BB amplitude here is only ~1 over the baseline (random halo
  pairs also sum near 0 on a thin shell), so the tests check significance (> 5 SE).
- **Counts against brute force**: in-shot and between-shot histograms, P and Q and every
  shot-pair matrix entry and partner flag, for 1D CL, 1D BB with origin on another axis,
  radial CL, radial BB with equal-volume bins, and banded partners, with a nan row and a
  one-event shot.

## Speed (4 shared cores, loaded by other workers)

- 50 shots × 2000 events, cloud σ = 1 per axis, with a 1000-resample bootstrap, 200 refits
  and the fit: 1D (L = 0.3, w = 0.02) plus radial r ≤ 0.3 together ~5.5 s (2.4·10⁷ radial
  between-shot pairs). The bin-averaged model caches its quadrature grid per x, so a refit
  costs ~5–20 ms. The test allows 20 s each for a loaded machine.
- Cost is the number of pairs within reach: ~N²·f with f the share of pair separations
  inside the bins, plus N log S tree builds. A radial reach comparable to the cloud is the
  slow case (all pairs); real correlation lengths are much shorter than the cloud.

## Review fixes (second commit)

1. HIGH, fixed baseline → fake bunching from pointing jitter: free baseline by default,
   (b + A)/b, baseline note, slope check, `recentre` option, cloud-matched reference
   described above. Test: `test_pointing_jitter_is_not_reported_as_bunching`.
2. MEDIUM, g²(0)'s SE too small: refits of 200 replicates. Test:
   `test_g2_zero_error_matches_its_scatter` (30 seeds, ratio 0.7–1.5).
3. MEDIUM, the bootstrap didn't resample the reference: shot-pair matrix, cᵀBc, exact
   jackknife, fallback note. Tests: `test_bootstrap_resamples_the_reference_with_few_shots`
   (4 and 8 shots), `test_without_the_matrix_the_bootstrap_says_it_is_optimistic`, matrix
   entries in the brute-force test.
4. LOW–MED, bin-averaged model (r²-weighted shells). Test:
   `test_bin_averaged_model_recovers_the_peak_on_wide_shells`.
5. Docstring and notes corrected (1.986 vs 1.9961, bootstrap agreement per bin vs g²(0));
   the thermal tests now expect (b + A)/b within 3 of the honest SEs (radial SE < 0.08, 1D
   < 0.25 with the 1D window widened to 0.25σ_c for statistics) and check the baseline
   against its expected 0.9948.
