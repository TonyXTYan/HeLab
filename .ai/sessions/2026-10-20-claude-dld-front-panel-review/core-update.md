# Core_BEC_Analysis `b8907f5` → `9e833a1`

A subagent (medium effort) read the diff; I spot-checked the sign of `txy_to_vel`, the
constants, the tsums and dead time, the "new detector" line, and that `sewm` was
already a submodule.

**Where the work came from:**
- Correlations: Kieran Thomas and Bryce Henson, 2019-11 to 2020-02.
- David Shin's appendix on the combinatorial algorithm (`combinatorial_algorithm_g_function.pdf`).
- Tony's 2023-08-29 sync (`e6f12a6`), which brought in uncommitted edits from the lab machine.

`bootstrap_error` at `73501cc` contains cloud-sync "(conflicted copy 2023-08-29 …)"
files; ignore them. Paths below are relative to `lib/Core_BEC_Analysis/`. The
context is in [branch-update.md](branch-update.md).

## Corrections to the first review

- **Nested libraries:** they were already submodules at `b8907f5` (gitlinks); this branch only bumps them. [core-library.md](core-library.md) described them as in-tree folders.
- **`txy_to_vel`:** only `lib/txy_to_vel/txy_to_vel.m` survives, and it now uses the **z-up** sign:
  `v_z = −h/t_f + ½|g|·t_f` (line 43, with gravity = −|g|).
  - The test is unchanged and z-down, so it now fails.
  - Neither convention is wrong. HeLab must write its convention down and test it on analytic trajectories.
  - The old notes' "the folder copy is right" is out of date.
- **`hebec_constants.m`:**
  - `ahe_scat` moved from 15 nm to **7.512 nm** (Moal et al., PRL 96 023203; commit `2614f65`). The comment's unit "m²" is wrong.
  - New `fall_distance = 0.8587` m (42). At g = 9.796, that is a fall time of 0.4187 s, which `find_dist_cen` also quotes.
  - The front panel still says 0.848 m / 0.416 s. **Ask Tony which is current.**
  - `const.grav` is G (Newton's constant), not g.
  - ħ and m_He are still truncated (about 0.05%).
- **`hist_adaptive_method`** (`fast_search_histogram` `a6af668`) now drops the under- and overflow bins by default (`out_of_bounds = 0`). Callers still trim `(2:end-1)`, so `centre_BEC` and `find_dist_cen` are now one bin off. Port what they meant, not the code.
- **`dominant_freq_components`:** peaks are now separated by an absolute 5 Hz (`:43`), not 5/T_span.
- **`smooth_hist`:** without a σ, the default σ is 0.5% of the range, with bins of σ/5.
- **`string_value_with_unc`:**
  - Moved to `command_line_format_tools/`, with name–value arguments (`type`, `separator`, `remove_common_factors`, `power_type`).
  - It keeps two significant figures when unc/10^⌊log unc⌋ ≤ 1.5, else one (94–101).
  - `%u` breaks negative exponents.

## Correlations (`lib/correlations/`): the main new capability

**The physics.** g²(Δ) by pair counting:
- **In-shot pairs** (distinct counts from the same shot) over **between-shot pairs**, each divided by its total pair count. g² goes to 1 far from the peak.
- A thermal source has g²(0) = 2; pair sources (halos) can give g² ≫ 1.
- **Collinear (CL)** histograms r₁ − r₂. **Back-to-back (BB)** histograms r₁ + r₂ (`delta_multiplier = −1`, `corr_1d_cart.m:136-137`), so the coordinates must be centred on the source, in velocity/k space.
- Raw TXY mixes seconds and metres, so this needs D8 first.

### `calc_any_g2_type.m`

**Types:** `1d_cart_cl/bb` (102–210), `radial_cl/bb` (213–318) and `3d_cart_cl/bb` (321–446). The 3D type is really the 1D one run along each axis.

**Input:** a 1×S cell of N×3 arrays (sorted by column 1 for pre-masking), or a 2×S cell for two ports.

**Outputs:**
- in-shot and between-shot densities;
- `norm_g2.g2_amp`;
- `g2peak = max(xg2)`, which is biased upwards;
- an optional `fitnlm` of `A·exp(−Δ²/2σ²)+1`.

**Bugs:**
- `corr_opt.param_num` typo (78–95): the fit is always the 2-parameter model, and setting the option crashes.
- `xg2` is computed only when plotting (157, 267, 387), so turning plots off crashes.
- Two-port chunking: S chunks in 1D, S/100 radially (242).

### `corr_1d_cart.m`

- **Window:** the other two components of Δ are windowed to `one_d_window`. It must be much smaller than the correlation length, or the peak is diluted (4–8).
- **Signs:** ±Δ masks (208–222).
- **Normalisation:** `bins/(window_area·bin_width·pairs)` with N²−N pairs, or N₁N₂ for two ports (294–300).
- **Smoothing:** optional `gaussfilt` (302–306).
- **Memory modes** (96–113):
  - low-mem loops over counts;
  - high-mem builds N²/2×3 Δ arrays (about 1.2 GB at N = 10⁴);
  - auto uses MATLAB's Windows-only `memory`.
- **Pre-masking:** `fast_sorted_mask` on the sorted axis (191–200), a sweep line.
- **`attenuate_counts`** thins counts at random, to simulate lower QE.
- **Bug:** the high-mem path passes "sorted" for unsorted Δ to `hist_adaptive_method` (281–282). The histograms are wrong below 2000 edges, and the path ignores two-port input.

### Other correlation files

- **`corr_radial.m`:** histograms |Δ| over `redges`, ×2 for unordered pairs, divided by the shell volume 4/3·π·(r₂³−r₁³) (155–159, 231–232). Bin centres are edge midpoints; the code admits that's wrong (98). The tests use `sqrt(linspace(rmin², rmax²))` bins.
- **`corr_3d_cart.m`:** unfinished. Its normalisation is broken and `x_centers` is undefined. Nothing calls it.
- **`chunk_data.m`:** the normalisation data. Each shot's counts go to *distinct* chunks via `randperm` (30–37), with `num_chunks ≥ max N` (25–27), so the denominator has no in-shot pairs. The legacy version leaked them. The denominator gets about N·S² pairs against S·N² in the numerator, so it is noisier and is smoothed.
- **`corr_err.m`:**
  - It calls `bootstrap_se(use_frac_size, replace=false)` at fractions 0.25–0.5, 5 × 30.
  - It thins counts rather than resampling shots.
  - The pinned `bootstrap_se` breaks on this path: `est_fun` takes 2 arguments and is called with 3, and `data_smpl` stays the 5-shot warm-up sample (`bootstrap_se.m:124, 130, 165, 172, 185`).
- **`corr_multi_low_mem.m`:** superseded.
- **`jth_neibour/corr_radial_deuar.m`:** "blobbiness". It compares the distance to the j-th nearest neighbour against the uniform-Poisson value `Γ(4/3)/2·((j−½)·6/π)^{1/3}` (161, 183). It is N×N, and its test is broken. In Python this is `cKDTree.query(k=K)`.
- **Test data:**
  - `fake_*_corr.m` clones a fraction of atoms with a Gaussian offset. `mvnrnd(..., diag(w))` treats the widths as variances, so σ_corr is √0.0015 ≈ 0.039, not 0.0015.
  - `generate_thermal_data/` doesn't work; its readme says so.

### A Python port (for D12/D13)

- **In-shot pairs** with `scipy.spatial.cKDTree`:
  - Radial: `np.diff(tree.count_neighbors(tree, edges))` minus self-pairs.
  - BB: count against `cKDTree(-v)` and subtract the self-terms.
  - 1D-cart: scale the axes so the window becomes a cube, then `query_pairs(R, p=np.inf, output_type='ndarray')` and filter. A numba sweep on sorted T also works.
- **Between-shot pairs**, with no chunking or random numbers:
  - H_between = H_all(merged) − ΣH_in;
  - P_between = (ΣN)² − ΣN².
  - If that is too slow, subsample pairs of shots.
- **g²** = (H_in/P_in)/(H_between/P_between); the bin volume cancels.
- **Peak:** fit `A·exp(−Δ²/2σ²)+1`; don't take the maximum.
- **Errors:** shot-level bootstrap or jackknife. Keep the S×bins in-shot array, since it is additive per shot.
- **Live:** cache per-shot histograms by fingerprint. A new shot costs its in-shot term plus the cross terms.
- **Centre drift:** optionally re-centre each shot, since drift inflates the between-shot pairs.
- **Validation:**
  - a Cox process (a Gaussian random complex field, |E|² times an envelope, Poisson-sampled) gives exactly g²(0) = 2;
  - pair cloning gives g² ≈ 1 + 1/occupancy;
  - BB halo pairs.

## `lib/bec_cals/`

**`bec_properties(omega, N, mass, a)`** (Pethick & Smith; the code itself says "do not trust", line 10):
- **Tc:**
  - ideal gas: T_c0 = ħω̄N^{1/3}/(k_B·ζ(3)^{1/3}) (52);
  - finite-size correction: ×(1 − 0.73·ω_m/(ω̄N^{1/3})) (56);
  - interaction shift: −1.33·(a/ā)·N^{1/6}·T_c0, with ā = √(ħ/mω̄) (61–62).
- **μ:** μ = (15^{2/5}/2)·(Na/ā)^{2/5}·ħω̄ (70–72).
- **TF radii:** R_i = √(2μ/mω_i²).
- **Densities:** peak n₀ = μ/U₀ with U₀ = 4πħ²a/m, and the mean N/V_TF.
- **Contact:** 64π²a²n₀/7 per atom (91).
- **Bugs:** the omega check uses `&&`, so it never fires (27).

**Other files:**
- `bec_tc.m` is deprecated.
- `g_bose.m` computes g_{3/2} only, as a series. It returns NaN for z ≥ 0.9999 and can loop forever on vectors. Use `mpmath.polylog`, or a capped numpy series.

## `txy_tools/`

**`hotspot_mask.m`** (2019-11-20) applies a box, then `masktxy_2d_circle`. Defaults:
- **Box:** T [0, ∞), X/Y ±50 mm.
- **Keep:** a circle at (0, 0), r = 38 mm.
- **Cut** (mm), nine circles of r = 2–4 mm:
  - (32, 3.6), (35.6, 5.6), (25.36, −19.8)
  - (13.68, 31.6), (28.4, −13.68), (32.08, −12.24)
  - (28.88, −21.84), (18.8, −28.72), (2.48, −34.8)
- **"New detector"** (2023 sync, line 29–30): a single cut at (3.44, 18.96) mm, r = 5.5 mm.

**Bugs:**
- `isempty(anal_args)` on an undefined variable (9): only the defaults work.
- `num_counts = numel(txy)` is 3× the count (44).

**Frame:** the mask runs after `import_mcp_tdc_data` has rotated XY by 0.61 rad, so its centres are in the rotated frame. For HeLab, which doesn't rotate, inverse-rotate them (α = −0.61):
- x = x′cos α − y′sin α
- y = x′sin α + y′cos α

The circle at the origin doesn't move. The import window was ±30 mm, so circles outside it never mattered.

**Also new:**
- `mask_square.m`: a box, with `invert`.
- `mask_square_num.m`: counts per shot in a box.

## Import and reconstruction

**`import_mcp_tdc_data.m`:**
- **New options:** `force_cache_load` (24–28) and `from_archive` (135).
- **Bad merge:**
  - the done-writing check still runs (169);
  - each file is read twice: masked then rotated (205–210), then rotated then masked (215–224), which overwrites the first result.
- **Net:** the same as before, but slower.

**`dld_read_5channels_reconst_multi_imp.m`** (the 2023 lab-machine edits):
1. **x1 dead time.** `uniquetol(x1, 0.5e-6/bin_time, 'DataScale', 1)` keeps one x1 per 0.5 µs (434). This is a detector-wide 0.5 µs dead time, so counts are lost.
   - Commented variants exist for x2 (0.5 µs), y1 (5 µs) and y2 (3 µs).
   - Confirm the tolerance semantics by running it.
2. **Separate time sums.** `T_sum_x = 3390` and `T_sum_y = 3275` (470–471) set T. That shifts T by about −1.66 ns. The matching still uses 3200 ± 200.
3. **Unchanged:** X/Y. Columns 2–5 now store raw x1, x2, y1, y2, but the differences are the same.
4. **Abandoned:** MCP matching was tried and commented out (channel 4). `dld_pulses_used` is built but not returned (618).

**`legacy/tdc_autoconverter`** (`e4f8812`, 2019-07-07) still has the old version; the two differ by exactly these hunks.

**For D11:** support both variants and find out which one wrote the reference `_txy_forc` files. At 8 significant figures the T shift is invisible, but event counts differ because of the dead time.

## One line each

- **`find_dist_cen.m`:** per shot and axis, the centre and width from the outermost bins above a threshold.
  - Bugs: `centre_OK` is overwritten per axis, and it is one bin off (see above).
  - Its comment gives TOF 0.4187 s.
- **`nonlinear_colormap`:** logistic or power remapping in CIECAM02 J′a′b′. A pyqtgraph LUT is enough for HeLab.
- **`pooled_mean_and_std`:** combines subset means and SDs exactly. Useful for incremental Live statistics.
- **`text_to_window_fun`:** rasterises "He*" as a ghost-imaging window. Ignore.
- **Trivial or not needed:**
  - `num_with_sep`, `vectors/*` (stable atan2 angle), `num_grad_*` / DERIVESTsuite;
  - `stash_opts`, `simple_bec_analysis.m` (tutorial), `scratch/hist_goof.m`;
  - `logical_tools/consecutive_true`, `bin/fwhm`.

## Nested libraries

| Library | Change |
|---|---|
| `matlab_function_cache` | Unchanged |
| `sewm` | Vectorised, same formula |
| `fast_sorted_mask` | README only |
| `fast_search_histogram` | `out_of_bounds` (above) |
| `bootstrap_error` | Vector estimators, log-spaced fractions and `use_frac_size` (broken, above) |
