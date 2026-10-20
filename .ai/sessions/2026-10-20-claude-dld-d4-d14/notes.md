# D4/D14 numerics: notes (2026-10-20, Claude, Worker)

Branch `agent/dld-d4-d14` from `6ed1ec9`. Brief: [brief.md](brief.md). Wiring: [handoff.md](handoff.md).
Judgement calls are marked **proposed, for Tony**.

## What was built

- `helab/analysis/fits.py`
  - `polylog(order, x)`: Li_s(x) for real 0 ≤ x ≤ 1, s > 1, no mpmath.
  - `bose_thermal`, `bose_area`, `bose_model(order)`: registered `bose_g2_5` (g_5/2) and `bose_g2`
    (g_2), parameters amplitude, centre, σ, fugacity z ∈ [0, 1], offset.
  - `bimodal_model(power, bose=order)`: registered `bimodal_tf2_g2_5` (TF² + g_5/2) and
    `bimodal_tf1_5_g2` (TF^3/2 + g_2), z fixed at 1 (recorded in the model's `fixed`), the same
    parameter names as the Gaussian bimodals (so `fit_axis`, `text()`, the cap and the gating
    work unchanged). Areas keyed `thomas_fermi` and `bose`.
  - `condensate_fraction(fit)`: N0/N ± SE by the delta method on the fit's parameter covariance
    (`FitResult.derived`), so the areas' correlation counts. `component_areas(fit)`: each part's
    area ± SE.
  - Fugacity at 1 or 0 gets a physics note ("saturated, at or below Tc: try a bimodal fit" /
    "the Boltzmann limit"), not "at its bound".
- `helab/analysis/bec.py` (new): `Trap`, `axis_roles`, `scaling_factors` (Castin–Dum ODE),
  `cigar_scaling` (first-order analytic), `radius_ratio_cap`, `axis_caps`, `detector_length`,
  `release_radius`, `bec_properties` (N, N0, T, covariance → `BecProperties`), `from_fit`
  (a histogram fit → properties, with its covariance), `radius_check` / `RadiusCheck`
  (R(t) → R(0) → μ and N0 without the QE → implied QE). `FIT_N_BOOT = 200`.
- `helab/analysis/physics.py`: rows `detector_qe` (lab, 0.1, unconfirmed, at most 1) and
  `trap_axial_axis` (folder, coded 1 = T, 2 = X, 3 = Y, 4 = between X and Y; default 4,
  unconfirmed). `Constant` gains `maximum` and `choices` (`allows`, `label`); `resolve`,
  `from_record` and `constant_layers.clean_layer` enforce them.
- `helab/analysis/constant_layers.py`: symbols, coded rows shown by label (`value_text`), a coded
  row's plot override is an int spec with its codes in the tip; the QE's override is ≤ 1.
- `helab/views/LabParametersTab.py`: `constant_editor` bounds a row at its maximum, and a coded
  row is a whole-number spin box (a drop-down is proposed, for the polish worker / Tony).
- `helab/analysis/profiles.py`: the four new choices in `T_MODELS`/`XY_MODELS`, `MODEL_KEYS`,
  `BIMODALS` (and `BOSES`); `TF_EXPONENT_TIP` (shown on every model choice already) extended with
  the Bose models, pairing, the bias, the cap's axis dependence; `AxisFit.text()` adds N0/N for
  bimodals and z for Bose fits; `fit_axis(max_radius_ratio=None)` takes the axis's physical cap
  (the default stays 2, so nothing changes until the wiring passes None).

## Derivations

**Bose thermal profile.** Ideal Bose gas in a harmonic trap, after a long ballistic expansion:
n(r) ∝ g_{3/2}(z e^{−Σxᵢ²/2σᵢ²}) with σᵢ = √(k_B T/m) t (√(t² + 1/ωᵢ²) exactly). Writing g_{3/2}
as Σ_k z^k e^{−k r²/2σ²}/k^{3/2} and integrating each Gaussian over one other axis multiplies the
k-th term by σ√(2π/k), raising the order by 1/2. So a full projection (both other axes) is g_{5/2},
a thin slice (one axis) g_2. Parametrised as A g_ν(z e^{−u²/2})/g_ν(z) + offset (A = the peak above
the offset), its area is A√(2π)σ g_{ν+1/2}(z)/g_ν(z). Pairing: ν = 5/2 with TF p = 2, ν = 2 with
p = 3/2 (the same axes integrated). z → 0 is the Gaussian, and σ gives T exactly as the Gaussian's σ.

Smoothness for fitting: g_{5/2}(e^{−α}) = ζ(5/2) − ζ(3/2)α + (4/3)√π α^{3/2} + …, so with α = u²/2
the profile is C² at the centre even at z = 1; g_2 has an α ln α term (C¹). Both are fine for a
least-squares fit; g_{3/2} (a cusp) would not be, and isn't needed.

**Polylog.** For x ≤ e^{−1}: the series, 60 terms (the tail is below e^{−60}). For x > e^{−1},
μ = ln x ∈ (−1, 0]: the expansion about 1, Li_s(e^μ) = Γ(1−s)(−μ)^{s−1} + Σ ζ(s−k)μ^k/k! (s not
whole), and for s = n the k = n−1 term replaced by μ^{n−1}/(n−1)! (H_{n−1} − ln(−μ)); 30 terms,
converging as (|μ|/2π)^k. SciPy's `zeta` takes the negative arguments. Checked against
π²/6, π²/12 − ln²2/2, Li_3(1/2) = 7ζ(3)/8 − π² ln2/12 + ln³2/6, ζ(3), ζ(5/2), and a
200 000-term direct series at 0.05…0.999 on both sides of the split (2e-13 relative).

**Bimodal + Bose.** Below Tc the thermal cloud is saturated, so z = 1 is fixed (the standard
choice; with interactions the thermal cloud sees μ > 0 and the mean field, which an ideal-gas
z = 1 profile neglects: **proposed, for Tony**: fixed z = 1, not fitted, as fitting z beside a
condensate is degenerate).

**Gaussian bias, measured** (noise-free expected counts over ±5σ, 200 bins; scratch script):
a Gaussian fitted to a g_5/2 cloud gives T low by 2 % (z = 0.3), 5 % (0.6), 8.5 % (0.9),
10 % (0.97) and 10.5 % (z = 1). As the thermal part of a bimodal fit on a Bose cloud the Gaussian
overstates N0/N: 0.177 for a true 0.1, 0.365 for 0.3, 0.640 for 0.6, with R 9 %, 3 %, 1 % low. The
Bose bimodal recovers both exactly (to 1e-7) on the same counts.

**Cap on R/σ_th.** R_i(t) = λ_i(t) R_i(0) = λ_i √(2μ/mω_i²); σ_i(t) = √(k_BT/mω_i²) √(1 + ω_i²t²).
So R/σ = √(2μ/k_BT) λ_i(t)/√(1 + ω_i²t²), computed with the solved λ at t = t_f
(`radius_ratio_cap`). Long-time limits: cigar radial √(2μ/k_BT) (λ_⊥ → τ); isotropic
√(2/3)·√(2μ/k_BT) = √(4μ/3k_BT) (energy conservation: λ̇ → √(2/3)ω); cigar axial
(π/2)ε√(2μ/k_BT) (λ_z → (π/2)ε²τ). At the table's 500/50 Hz and t_f = 0.416 s the radial cap is
1.989 at μ/k_BT = 2 (ε² corrections), the axial 0.313. A detector axis at an angle in the plane of
a radial and the axial axis sees R = √(R_⊥² sin²θ + R_z² cos²θ) ≤ R_⊥ (an ellipsoid's projection),
with σ isotropic after a long fall, so "between" takes the radial cap: the cap is an upper bound.
Default μ/k_BT = 2 (`DEFAULT_MU_OVER_KT`) keeps today's cap of 2 on a radial axis; deep condensates
need more (**proposed, for Tony**: expose μ/k_BT max as the plot setting rather than the ratio).

**Castin–Dum.** λ̈_i = ω_i²/(λ_i λ_xλ_yλ_z), solved with DOP853 (rtol 1e-10) in τ = ω_max t (about
6 ms per solve). The cigar approximation (Castin & Dum 1996) agrees to 0.1 % (λ_⊥) and
0.3 % (λ_z) at ε = 0.01; at the table's ε = 0.1 λ_⊥ is 0.6 % and λ_z 5 % off after the fall, so the
code always uses the solved λ.

**D14.** Tc0 = (N/ζ(3))^{1/3} ħω̄/k_B = 0.9405 ħω̄N^{1/3}/k_B; finite size −ζ(2)/(2ζ(3)^{2/3}) =
−0.7275 (ω_arith/ω̄)N^{−1/3} (Grossmann & Holthaus 1995; Dalfovo et al., RMP 1999);
interaction −1.326 (a/a_ho)N^{1/6} (Giorgini, Pitaevskii & Stringari 1996); Tc = Tc0(1 + both).
μ = ½ħω̄(15N0 a/a_ho)^{2/5}, R_i = √(2μ/mω_i²), n0 = μm/(4πħ²a), a_ho = √(ħ/mω̄),
ω̄ = (ω_⊥²ω_z)^{1/3}. Hand check at N = 10⁶, N0 = 3·10⁵, (500, 500, 50) Hz, a = 7.512 nm:
ω̄ = 2π·232.1 Hz, a_ho = 3.30 µm, Tc0 = 1.048 µK, shifts −1.10 % and −3.02 %, Tc = 1.004 µK,
μ/k_B = 224 nK, R_⊥ = 9.7 µm, R_z = 97 µm, n0 = 1.96·10¹⁹ m⁻³ (all in `tests/test_bec.py`).

**From a fit.** N, N0 per shot = area / bin width / shots / QE; T = m(σ_v)²/k_B with σ_v = gσ (T)
or σ/t_f (X, Y), as `fit_axis`. Their 3 × 3 covariance is J C Jᵀ from the fit's covariance C, so
N/N0 correlation is kept; then every property by `propagate` on (N, N0, T). The QE, trap
frequencies, a and m carry no SE (noted). A fit's R on T becomes a length g t_f R; R(0) = R(t_f)/λ.
From R(0): μ_R = ½mω_i²R(0)², N0_R = (a_ho/15a)(2μ_R/ħω̄)^{5/2}, implied QE = counts/N0_R (its SE
treats the counted N0 and R as independent: rough; N0 ∝ R⁵ makes it R-sensitive).

## Constants (choices for Tony)

- **Detector QE: 0.1, lab level, unconfirmed (proposed, for Tony).** Neither the legacy repos
  (the submodules aren't checked out here, and the review notes found no QE anywhere: only Core's
  `attenuate_counts` simulates lower QE) nor `lab-parameters.md` give a value. 10 % is the figure
  usually quoted for He* MCP delay-line detectors; I did not have a citable lab measurement. The
  `RadiusCheck.implied_qe` is offered as a calibration route (a condensate's TF radius gives N0
  without the QE).
- **Trap axial axis: folder level, coded, default 4 = "between X and Y" (proposed, for Tony).**
  The magnetic trap's long axis is horizontal (so T, vertical, is radial: confident but marked
  unconfirmed with the row), and the old GUI's 0.61 rad XY rotation suggests the trap's axes are
  rotated from the detector's, so neither X nor Y is axial in HeLab's unrotated frame. With 4, X and
  Y take the radial (largest, so safe) cap, and no R(0) is given from X or Y. Codes rather than a
  text row because the table holds positive floats; the editors show whole numbers. A drop-down in
  Lab parameters / Folder constants is proposed.
- **No third trap frequency.** The table's trap is cylindrical; `Trap(omegas)` and
  `scaling_factors` take three, so a third row (`trap_radial_2`) is a small later addition if the
  trap is measurably anisotropic radially.

## Validation

- `tests/test_bose_fits.py` (12 tests, 16 cases): polylog values and series agreement; Bose area = the
  profile's integral; g_5/2 fits recover T and z within 3 SE at z = 0.6 and 0.97 where the
  Gaussian's T is > 8 SE low; g_2 on a slice; fugacity end notes; bimodal TF² + g_5/2 recovers
  N0/N, R, σ at N0/N = 0.15 and 0.5 where the Gaussian bimodal overstates N0/N by > 3 SE; the
  delta-method SE of N0/N matches the spread over 24 clouds (ratio in 0.6–1.5); the slice pair;
  no-condensate and failed fits; the offered models and their tip; `fit_axis(max_radius_ratio=None)`
  with X axial (cap 0.31) vs Y radial (2.0).
- `tests/test_bec.py` (13 tests): coefficients; hand-computed D14 values; limits (isotropic,
  a → 0, Tc ∝ N^{1/3}, μ ∝ N0^{2/5}, (1 − N0/N)^{1/3}); SE propagation; edge-case notes (no atoms,
  no condensate, N0 > N, no T, TF regime, large shifts, a condensate above Tc, unconfirmed trap);
  Castin–Dum vs the cigar approximation and the isotropic asymptote; R(0) round trip; axis roles
  and caps; the new rows' validation, labels, plot overrides and records; end to end, a synthetic
  3·10⁵-atom condensate on 4·10⁵ thermal atoms at 0.6 µK, QE 0.1, 20 shots: `from_fit` recovers
  N, N0, T, N0/N, R(0), N0 from R and the implied QE within 3 SE.
- Existing fits/profiles/physics/constants/lab-parameters tests pass unchanged except the two
  table-listing tests, updated for the new rows.
- mypy --strict helab tests, pyright helab tests: clean. `git diff --check`: clean.
- Full suite: see [handoff.md](handoff.md).

## Left for later

- Bimodal TF + arrival-time (Yavin) thermal on T, and a Bose arrival-time profile (the g_5/2
  model on T is the Gaussian-in-time approximation, like the Gaussian model).
- The cloud-size-corrected temperature (roadmap fit option): `√(1 + 1/ω²t²)` is 1 + 6·10⁻⁵ at
  50 Hz after 0.416 s, so negligible here; offer it only if short TOFs come up.
- Interacting thermal cloud (Hartree–Fock) profiles: not offered.
- Detector saturation correction for N0: only a note.

## Review fixes (physics review, via the Coordinator)

1. **Bimodal z = 1 invented condensates above Tc** (z 0.3 → N0/N 0.15, σ +7 %). `fits.fit_condensate`
   / `choose_condensate` now always fit the free-z Bose profile beside the bimodal; `fit_axis` does
   this for both TF + Bose choices and reports the free-z fit with "no condensate (z = …)" unless a
   condensate is clearly there. **Rule (proposed, for Tony):** Δχ² = χ²(free z) − χ²(bimodal) ≥ 9
   when the free-z fit saturates (z ≥ 0.999), or ≥ 25 when it doesn't. The review asked for
   "z ≥ 0.999 AND better"; the z condition alone rejects strong condensates (2/3 of the peak: free z
   0.44 ± 0.20 following the condensate with a narrow σ, while the bimodal is better by Δχ² ≈ 150),
   hence the 25 branch. χ² is Pearson with the model's variance (both fits are Poisson ML), so Δχ²
   is the likelihood ratio to second order; one extra free parameter; the models aren't nested, so
   9/25 are conventions (3σ/5σ for 1 dof). Measured (scratch p3.py, 15 thermal clouds per z, 5
   mixtures per fraction, 120 bins ±5σ): no false condensates at z = 0.3, 0.7, 0.95, 1.0 from
   4·10⁵ and 4·10⁶ events; one at z = 1 (at Tc) from 2·10⁴ events. Mixtures of 5, 30, 70 % found
   5/5 with N0/N within 0.005 from 4·10⁵ events; from 2·10⁴, 30 and 70 % found 5/5, 5 % in 2/5.
   Smoothed-curve fits use diagonal χ², which overstates Δχ²: their decision is looser (noted in
   fits.py).
2. **Slice fits** (`FitModel.slice`: TF^3/2, g_2) now note `SLICE_NOTE` in every fit;
   `bec.from_fit` gives only T and R(0) for them (N, N0, N0/N, Tc, μ, n0, both implied QEs nan);
   `AxisFit.text()` labels the fraction "N0/N (slice)".
3. **`fit_axis(max_radius_ratio=None)` is now the default** (`profiles.axis_cap`, falling back to
   `MAX_RADIUS_RATIO` for another axis or constants that give no cap), so the plot uses the per-axis
   caps without changes. At the defaults the caps are 1.989 (no existing test changed).
4. `cigar_scaling` docstring: orientation only (λ_z 5 % off at ε = 0.1); the code uses the ODE.
5. Notes/tooltips: z = 1 ignores the condensate's mean-field depletion of the thermal centre; T from
   many shots includes centre jitter and reads high (a `from_fit` note; per-shot fits avoid it);
   second QE check `BecProperties.implied_qe_thermal` = QE · (counted thermal)/ζ(3)(k_BT/ħω̄)³
   (R-independent, with a condensate only; σ⁶-sensitive through T³) beside `saturated_thermal`;
   QE scalings in the QE note (N, N0 ∝ 1/QE, Tc ∝ QE^−1/3, μ and n0 ∝ QE^−2/5, R ∝ QE^−1/5).
