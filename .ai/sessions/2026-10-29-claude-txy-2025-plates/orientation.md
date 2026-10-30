# Is the July 2026 image change exactly 180°?

**PROVISIONAL** (Claude, 2026-10-29). Tony asked: "the rotation might not be exactly 180deg?", and
for a full 360° scan to confirm. It follows [investigation.md](investigation.md) §1 and §2.5. The
script is `scripts/orientation.py`, the numbers are in `out/orientation.json` and the figure is
`figures/orientation_scan.png`.

**Evidence covers:** June 2026 background-window hits (4 runs, 2026-06-19…27, 648 shots,
87,796 hits, converted from raw) against the October 2026 collisions run (2026-10-09/10, 866 TXY,
117,072 hits) and the July RingBEC run (2026-07-27, 100 of 1,007 TXY, 10,346 hits). X is still
being transferred.

## Answer

The change is **180° to within ~0.3°**: δ = **0.0 ± 0.3°**, so δ is consistent with 0. Details:
- **No mirror and no other angle.** Over a full turn, 180° is the only good match.
- **Offset:** about (0.1, −0.4) mm.
- **Scale:** no change, 1.00 ± 0.01.

Together with the reflection fingerprints, this points to a **pure cable swap**: x1↔x2 and y1↔y2
relabelled, giving exactly X→−X and Y→−Y. Neither a physical rotation of the detector nor a mirror
fits.

## The model and the two methods

Later position = s · R(θ) · M · June position + offset. M is either the identity or a mirror
(x → −x), and θ = 180° + δ for the fine fit.

**(a) Hot spots.** Background-subtracted centroids within r < 3 mm, with a 4–7 mm ring as
background; uncertainties from a bootstrap.

| Spot | June (mm) | October collisions (mm) | July RingBEC (mm) |
|---|---|---|---|
| H1 | (15.833, 1.217) ± (0.009, 0.006) | (−15.878, −1.572) ± (0.006, 0.004) | (−15.875, −1.596) ± 0.015 |
| H2 | (32.256, 1.084) ± 0.008 | (−32.435, −1.416) ± (0.025, 0.023) | weak (33 counts) |
| H3 | (8.83, −1.82) ± 0.07 | (−8.85, 1.80), poorly defined | (−8.85, 2.00) ± (0.7, 0.35) |

Fit to the October run:
- **Rotation + offset:** δ = −0.08 ± 0.24°, offset (−0.06, −0.38) mm; χ² = 22 for 3 dof.
- **Rotation + offset + scale:** δ = **−0.08 ± 0.09°**, offset (0.09, −0.37) mm, scale
  1.008 ± 0.002, χ² ≈ 0.
- **Caveat:** in practice H1 and H2 set the fit; H3 is weak, and it is a burst-ghost location
  ([channel7.md](channel7.md)). Two points fix four parameters exactly, so the scale's error is
  optimistic.

The RingBEC fit is weak (δ = 1.3 ± 2.0°).

**(b) Correlation of background images.**
- **Images:** smoothed 0.25 mm images within r < 34 mm. At each θ the June image is transformed,
  and the offset (|offset| ≤ 1.5 mm) that best matches the later image is chosen.
- **Why the offset is limited:** a free ±4 mm offset let the brightest spot alone match many angles.
- **Two variants,** so that no single spot decides: counts clipped at 3× the median, and H1/H2
  masked in both images.
- **Scans:** a full turn in 1° steps for rotation and for mirror-then-rotation; refinement at 0.05°
  around the top local maxima; δ from a parabola over ±0.6°, with its spread over half-samples.

| Later run, variant | Best rotation | r there | Best other rotation | Best mirror (angle, r) | δ (deg) | Scale |
|---|---|---|---|---|---|---|
| October, clipped | 180.0° | **0.771** | 0.14 (235°) | 215.5°, 0.39 | **+0.001 ± 0.03** | 0.995 |
| October, H1/H2 masked | 179.7° | **0.751** | 0.24 (333°) | 161.4°, 0.24 | **−0.28 ± 0.05** | 0.995 |
| RingBEC, clipped | 179.85° | 0.537 | 0.14 (207°) | 223.4°, 0.25 | −0.22 ± 0.23 | 0.993 |
| RingBEC, H1/H2 masked | 181.55° | 0.253 | 0.13 (175°) | 228.7°, 0.09 | (+1.2 ± 0.4; offset at the search edge: unreliable) | 0.992 |

- **Only 180° matches.** Every curve has a single strong peak at 180° (`orientation_scan.png`).
  90° and 270° give r ≈ 0, mirrors at most 0.39, and no other rotation exceeds 0.25.
- **The masked and clipped δ differ by 0.28°,** more than their statistical errors. The masked
  image leans on the weak structure, including burst-ghost spots, whose apparent positions depend
  on cable delays that changed with the re-cabling.
- **Combined:** the hot-spot fit gives −0.08 ± 0.09° and the October images +0.00 and −0.28, so
  **δ = 0.0 ± 0.3°** (systematic). A rotation of the detector would have to be smaller than about
  0.4° to hide here.
- **Offset:** (0.1 ± 0.15, −0.35 ± 0.15) mm (images: −0.25, −0.25 on the 0.25 mm grid). That is
  ~0.7 ns of extra delay between the ends of an axis: the size expected from swapped or replaced
  cables. The x−y time-sum difference also moved from 121 to 103 bins at that time
  ([investigation.md](investigation.md) §2.1).
- **Scale:** 1.008 ± 0.002 from the two spots, 0.995 from the images, so **1.00 ± 0.01**. No
  significant change.

## Swap or physical rotation? The reflection fingerprints

Each delay-line end has its own reflection delay, the second pulse ~170–196 ns after the first:

| | ch0 | ch1 | ch2 | ch3 |
|---|---|---|---|---|
| June 2026, and the 2022 plates | 173.7 | 195.4 | 169.9 | 189.8 |
| July 2026 | 196.6 | 174.3 | 187.3 | 171.1 |
| September 2026 (sampled from X) | swapped, as in July | | | |

- **Why this means a swap.** The delays belong to the signal path up to the reflection point:
  the anode end and its cable. A physical rotation of the detector that keeps every cable on its
  TDC input leaves each delay on its channel. Here the delays moved between channels, pairwise
  (ch0↔ch1, ch2↔ch3), so **the channel ↔ delay-line-end mapping changed: a swap of cables
  (or connections) somewhere between the anode and the TDC inputs**.
- **The burst signature agrees.** The bursts' first pulse is on the same physical end in both
  periods: ch0 in June, ch1 in July ([channel7.md](channel7.md)).
- **A swap alone gives exactly 180°.** It relabels channels, so X → −X and Y → −Y exactly, and
  converting July raw files with the corner channels swapped in the profile gives exactly the June
  orientation (`out/swapped_map_check.json`).
- **So δ ≈ 0 says the detector was not also rotated.** Within ~0.3°, nothing physically turned.
- **Caveat:** the fingerprints can't show *where* the swap is (anode feedthrough, amplifier, CFD
  or TDC panel). The ~0.4 mm offset and the 19-bin time-sum change suggest the signal paths' cables
  changed too.

**What would settle it in the lab:** look at, or photograph, the corner cabling from the
feedthrough to the TDC and compare it with a June photo or notes, if any. Or pulse one anode end
(or touch it with a probe) and see which TDC channel fires.
