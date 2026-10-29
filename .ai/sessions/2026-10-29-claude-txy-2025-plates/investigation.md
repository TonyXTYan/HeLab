> **Provisional** (Tony, 2026-10-29): the data on X is still being transferred, so these findings
> cover only the folders present on 2026-10-29 and are re-checked when the transfer completes.
> Tony confirmed the cable swap and asked to treat it as the detector orientation (Q25.1).

# 2025 MCP plates: channel 7, a provisional calibration, and other findings

**PROVISIONAL. Nothing here is a calibration Tony has approved, and nothing was applied to HeLab.**

**Follow-ups (same day):** [channel7.md](channel7.md) covers what channel 7 is. Its pulses mark the
largest of ~7 Hz detector "bursts", which also make ~16% of background hits as ghosts, including
some of the weak hot spots below. [orientation.md](orientation.md) finds the July change is
180.0 ± 0.3°, a pure cable swap.

Claude, 2026-10-29, at Tony's request: "investigate more about channel 7 and calibration of 2025
plate and anything else at your discretion". This is analysis only. No HeLab source, tests,
profiles or docs were changed, and nothing was written to X. My earlier notes are in
[notes.md](notes.md). The candidate profile is in
[profile-plates-2025.provisional.json](profile-plates-2025.provisional.json). The scripts are in
`scripts/`, numbers in `out/` and figures in `figures/` (list at the end).

## Summary

| # | Finding | Confidence |
|---|---|---|
| 1 | **The corner cables were swapped between 27 Jun and 21 Jul 2026** (x1↔x2 and y1↔y2). Every image from then on (tight trap, RingBEC, QE, collisions) is **rotated 180°** relative to June 2026 and all earlier data. | high |
| 2 | **Channel 7** is a new, random (Poisson) input at ~0.3 Hz in June and ~0.07 Hz in July. It is not tied to the shot, the scan or the acquisition window. It comes with prompt pickup on the corner channels and, in 20% of cases, with a hit at one spot, (−6.6, −10.3) mm. It looks like a high-threshold electrical transient, e.g. an MCP/HV micro-discharge or a cable on input 7. It does not affect conversion. | high (what it does), low (what it is) |
| 3 | x−y time-sum difference on the 2025 plates: **121.0 ± 0.5 bins** (June). It varies across the plate from ~10 to ~185 bins. Absolute sums can't be measured: no MCP pulses. | high |
| 4 | Edge clipping: a wider window adds 0.4% hits, but **~80% of those are random pulse combinations**, not atoms. Keep 3200. | medium-high |
| 5 | Active area: round to 7%, **X/Y axis ratio 1.07 ± 0.02**, mean radius 40.0 ± 0.5 mm at matlab-2019's scale, centre within ~1 mm of (0, 0). | medium |
| 6 | Hot spots: two strong ones, (15.9, 1.4) mm at 3–4 Hz and (32.3, 1.2) mm at 0.4–1.8 Hz, plus ~6 weak ones (June frame). The dark-count density varies ±24% across the plate. | high (spots), low (efficiency) |
| 7 | The halo run (collisions44) **cannot calibrate the plates**. Its halo is a 2.3:1 ellipse along the trap axes (in-trap collision), and no back-to-back peak is measurable. | high |
| 8 | **Two converters wrote TXY in July 2026.** Some MATLAB TXY come from the 2023 lab edit, which loses 7–29% of hits, and one file is corrupted by both writing at once. | high |
| 9 | Data notes: the log "posixtime" is local time encoded as UTC (+10 h). The QE run has hits out to 7 s and a few at T = −81 s … +62 s. Shot gaps are listed below. | high |

### What Tony should check in the lab

1. **Corner cabling, urgent.** What changed between 27 Jun and 21 Jul 2026 at the
   anode/amplifier/CFD/TDC chain? x1↔x2 and y1↔y2 are swapped, so July–October images are rotated
   180°. Analyses that combine runs across that date, or use fixed positions (masks, hot spots,
   ROIs, the front panel's rotation), are affected. Either swap the cables back, or convert later
   raw data with the swapped channel map (candidate profile below). MATLAB's TXY written since
   then are rotated.
2. **TDC input 7.** What is plugged into it: a cable, a terminator, nothing? Is input 7 enabled
   in the TDC software, and at what threshold? Was anything moved there in 2025 (e.g. an MCP
   pick-off)? If it is an MCP or HV monitor, a lower threshold would give absolute time sums.
3. **MCP pulses (channel 4)** are not recorded. One calibration run with the MCP pick-off on
   channel 4 would measure the absolute time sums and their variation across the plate.
4. **The front panel or another converter is converting in the live folders.** In July some
   `d_txy_forc` files were written by the 2023 lab edit, and one by two programs at once.
   Check which program on the TDC PC writes `d_txy_forc` besides AutoConvert.
5. **The visible active diameter** (the plates' datasheet). This measurement gives 80 mm (radius
   40 mm) at matlab-2019's v⊥, but the 2017 and 2022 plates look smaller (37 mm and 36 mm) with "the
   same diameter". So the edge is only a rough absolute scale.
6. **A calibration run for the 2025 plates:** a free-space halo with ≥100 halo atoms per shot over
   ≥1,000 shots, keeping the raw files; a dark run of 30 min or more for the flat field; and a large
   thermal cloud. Use the current cabling, and say which one it is.

## Data used

| Set | Plates | What | Shots |
|---|---|---|---|
| `txy-2026` (4 runs, 2026-06-19…27) | 2025 | raw + MATLAB TXY | 172 |
| `calib-2026/20260625_Ramsey_weak_trap` | 2025 | every raw file of the run, logs | 519 |
| `calib-2026/20260722-tight-trap-freq-meas` | 2025 | raw + TXY, 6 per subfolder | 24 |
| `calib-2026/20261010-411trapcollisions44` | 2025 | TXY only (halo) | 866 (all) |
| `calib-2026/20260727-RingBEC`, `…/20260812_Quantum_efficiency` | 2025 | TXY only | 100, 45 |
| `calib-2026/20250104_off_axis_check_mirror` | 2022 | raw, pre-swap | 6 |
| `txy-v1` (8 sets), `calib-v1` (3 halo runs) | 2017, 2022 | raw + TXY | 309, 4,020 |

`~/HeLab-samples/calib-2026/` (776 MB) was copied once from X by
`scripts/copy_calib_2026.py` and then locked read-only. Its `manifest.json` gives each file's
source path, mtime and SHA-256. Its file listings, with sizes and mtimes for every post-swap folder,
are in the scratch folder. They were used for the shot-gap counts, and the relevant numbers are in
`out/other_checks.json`.

**Method checks.**
- **Probe matcher.** `scripts/probe_match.py` is a copy of the converter's reference match that
  also returns the four corner times. It agrees with MATLAB's TXY on 44 of 44 files
  (`validate_probe.py`), and its hit counts equal the earlier MATLAB probe's.
- **Time sums from MCP pulses.** On the 2022-11 MCP shots they come out at x 3362 and y 3293 bins
  (earlier: 3367 / 3294), and the no-MCP x−y difference equals the MCP one (69 vs 68).
- **Rule.** Unless a row says otherwise, positions use matlab-2019's v⊥ (1 bin of x1−x2 =
  13.16 µm) and are given in the **June 2026 frame**: later runs are rotated back by 180°.

## 1. Channel 7

**Where it appears.**
- **2017–2024 data:** no channel-7 pulse in any of the 309 `txy-v1` raw files, the 4,020
  `calib-v1` raw files (2019-11, 2022-12, 2023-01) or the 6 pre-swap files of January 2025.
- **Post-swap data:** present in every post-swap folder with raw files:

| Set | Shots | With ch7 | ch7 per shot | Rate |
|---|---|---|---|---|
| 2026-06-20 Rabi (sample) | 43 | 35 | 1.44 | 0.33 Hz |
| 2026-06-25 Ramsey (all) | 519 | 384 | 1.31 (variance 1.25) | 0.28 Hz |
| 2026-06-26 / 27 Ramsey (samples) | 43 / 43 | 30 / 27 | 1.30 / 1.07 | 0.29 / 0.25 Hz |
| 2026-07-21/22 tight trap (sample) | 24 | 6 | 0.29 | 0.07 Hz |

**When.**
- **Uniform in time.** Pulses are spread evenly from 0 to 4.08 s after the trigger (KS test
  against uniform, p = 0.43). They are not tied to the end of the acquisition (the last pulse
  comes at 4.02–4.03 s).
- **A correction to my earlier note.** That note said "near its end": the ch7 *row* often sits
  near the end of the file, but the files are not in time order. The *time* is uniform.
- **Poisson.** Counts per shot follow a Poisson distribution (observed 135/187/124/52/15/6 against
  140/183/120/53/17/5 expected).
- **Unrelated to the experiment:**
  - the scanned T_delay (Spearman p = 0.75);
  - time in the run (p = 0.74; no drift);
  - the shot's hit count (r = 0.07);
  - the mains phase: weak (Rayleigh R = 0.08, p ≈ 0.01 at 50 Hz, one of several frequencies
    tried, so not significant).
- **Logs.** No log column relates to it (`out/ch7_survey.csv`, `ch7_pulses.csv`).

**What comes with it** (figure `ch7_overview.png`):
- **Prompt corner pulses.** 95% of ch7 pulses have a corner pulse within 10 ns (x1 82%, y1 52%,
  x2 32%, y2 4%), at near-fixed offsets: y1 +1.9 ns, x1 +7.5 ns, x2 about −2 to 0 ns. Further
  corner pulses follow over the next ~70 ns, and almost none come before ch7. By chance one would
  expect ~1 pulse per channel within ±7.5 ns over all 681 ch7 pulses; 278 (x1), 196 (x2) and
  332 (y1) are seen.
- **A matched hit at one spot.** 135 of 681 (20%) come with a reconstructed hit that has a corner
  within 10 ns. Those hits cluster at **(−6.6, −10.3) mm**, IQR 5.5 × 5.8 mm, and the hit's MCP
  time is ~26 ns *before* the ch7 pulse. The October halo data show a very weak excess near
  (−9.2, −11.7) mm in the same frame; that may be a coincidence.
- **No time-sum relation.** It is not a normal MCP pick-off: x1 + x2 − 2·t7 shows no peak near the
  time sum.

**Best guess.**
- **What it is:** a TDC input that fires on rare, large electrical transients, at ~1 per 3 s in
  June. Either:
  - something connected to input 7 (a pick-off or monitor with a high threshold, or an unterminated
    cable acting as an antenna) responds to a discharge-like event in the detector; the same event
    couples promptly into the anode readout and, a fifth of the time, produces a real-looking hit
    at one spot; or
  - input 7 sees the giant MCP pulses of a micro-discharge site near (−7, −10) mm.
- **Why the rate fell in July:** the drop from 0.3 Hz to 0.07 Hz happened together with the corner
  re-cabling, which suggests the cabling around input 7 changed too.
- **What it isn't:** an end-of-acquisition marker, or a camera or shutter trigger. Either would be
  regular, or locked to the trigger or the sequence.

**Conversion.** HeLab's converter ignores channel 7, as MATLAB does. The output is
**byte-identical** with the ch7 rows removed: 1,028 of 1,028 file × profile pairs (matlab-2019,
plates-2025) over all local post-swap raw files with ch7 (`ch7_conversion.py`). The ~135 ch7
hits are 0.009% of the run's hits, so they are negligible as ghost counts.

## 2. The 2025 plates, item by item

### 2.1 x−y time-sum difference

D = (x1 + x2) − (y1 + y2), per matched hit (`plate_probes.py`, figures `pp_*.png`):

| Plates / set | Median D (bins) | IQR | Plane fit at centre | dD per 13 mm in X / Y |
|---|---|---|---|---|
| **2025, June 2026** (648 shots, 2.0 M hits) | **121.0 ± 0.5** | 62 | 120.6 | +17 / −25 |
| 2025, July 2026 (re-cabled) | 103.0 ± 0.2 | 26 | 101.5 | −16 / +24 |
| 2022 (2023-02 … 2025-01) | 106 | 56 | 102.6 | +25 / −24 |
| 2022, 2022-11 (MCP shots) | 69 | 61 | 56 | +30 / −27 |
| 2017 (2020, 2022-07) | 112 | 96 | 99 | +29 / −28 |

- **Position dependence.** D changes smoothly across the plate. The map's 5–95% range is
  **7…186 bins** in June, low in the upper left and high in the lower right. This is the time sums
  varying along the delay lines. With MCP pulses on the 2022 plates, each sum grows ~30–40 bins
  per 13 mm along its own axis (x: +39, y: +31).
- **The July gradients flip sign.** This is what a swap of x1↔x2 and y1↔y2 does. Swapping
  corners leaves D unchanged, so the ~19-bin lower intercept probably comes from the new cables'
  delays.
- **Effect on output.** 121 bins = 3 ns, so T is shifted by ~1.5 ns: negligible.
- **Effect on matching.** The match check |D| < 400 is centred on 0. With D at 121 ± 90, a
  tighter check would cut real hits: 200 drops 9.7% of hits in June, nearly all atoms. To tighten
  it, the check would need an offset field. Schema 1 has none; that is a stage-3 schema proposal.
- **Absolute sums:** **not measurable.** No post-swap raw file has a single channel-4 (MCP)
  pulse. For the 2022 plates: x 3362, y 3293 bins.
- **Better data:** one run with MCP pulses recorded.

### 2.2 Edge clipping (the 3200-bin window)

Re-matched with a window of 4000 and |x1−x2|, |y1−y2| < 4200 on both axes (my earlier note
widened x only):

| Set | Hits added | Of those, in the atoms' arrival windows | With a consistent sum (\|D − median\| < 60) |
|---|---|---|---|
| 2025, June | +0.41% (8,047) | 92% (normal hits: 94%) | **25%** (normal hits 74%; random combinations ~15%) |
| 2025, July | +0.04% | 80% | – |
| 2022 plates | +0.02% | 87% | 36% |
| 2017 plates | +0.41% | 62% | 31% |

- **Mostly random combinations.** The extra hits arrive with the atoms because random pulse
  combinations need a high pulse rate. But only a quarter have a consistent time sum, and their
  |X| and |Y| distributions are flat from 3200 to 4200 bins, with no plate edge. So **~80% are
  random combinations**, and real clipped atoms are ≲0.1% of hits.
- **Recommendation:** keep 3200 (confidence medium-high).
- **Better data:** a large flat cloud, which would show a real edge.

### 2.3 Pulse spacing, ringing, dead time

Same-channel intervals, 1 ns bins (`pulse_spacing_fine.py`, figures `ps_fine.png`,
`ps_intervals.png`):

| | x1 | x2 | y1 | y2 |
|---|---|---|---|---|
| Reflection peak, ns (2025 June) | 173.7 | 195.4 | 169.9 | 189.8 |
| Reflection peak, ns (2022 plates, 2023-03) | 176.0 | 195.5 | 170.9 | 190.3 |
| Reflection peak, ns (2025 **July**) | **196.6** | **174.3** | **187.3** | **171.1** |
| Reflection excess per pulse (June) | 0.146 | 0.142 | 0.114 | 0.102 |
| Shortest interval, ns (0.1th percentile, June) | 100 | 124 | 117 | 115 |
| Pulses per matched hit (June) | 2.21 | 1.81 | 1.68 | 1.67 |

- **Reflections.** Every channel has a second pulse ~170–196 ns after the first, about twice the
  delay line's transit time: a reflection. Its delay is a fingerprint of the physical end.
  - In July the fingerprints moved: x1 shows what was x2's and vice versa, and y1↔y2 likewise.
    That is the cable swap.
  - The 2022 plates (2023-03) have the same fingerprints as June: the anode and readout are
    unchanged.
- **Dead time.** Pulses closer than ~100–125 ns almost never occur on the 2022 and 2025 plates,
  against ~15 ns on the 2017 plates (2022-07). This is the electronics' dead time.
- **No converter dead time.** One would remove real atoms in dense clouds: 0.25 µs on every
  corner drops 17.6% of June hits, and the 2023 edit's 0.5 µs on x1 drops 28.9%, nearly all inside
  the atoms' windows. Keep 0.
- **The x1 surplus** (+29% over the other corners in June; +36% on the 2022 plates) follows the
  physical end. In July it is on channel 1 (x2/others 1.23 vs x1/others 0.95). So it comes from
  the "x1" end's line, amplifier or CFD, upstream of wherever the swap was made. Most of it is
  short-interval pulses: 52% of x1 intervals are under 300 ns, against 38–45% on the other corners.
- **Random-combination share** (from the flat pedestal of D): June 5.4% of hits, July 0.9%, 2022
  plates 0.7–1.1%. It grows with the instantaneous pulse rate: June's clouds arrive in two 40 ms
  windows. This is the main source of "ghost" hits in dense clouds, and an offset-centred, tighter
  sum check (2.1) would reduce it.

### 2.4 Active area, roundness, centre

The half-density edge of the background-window (dark-count) image, fitted per 15° sector with an
ellipse (`images_hotspots.py`, `geometry_flatfield.py`, figure `img_background_by_era.png`):

| Plates / run | Centre (mm, own frame) | Semi-axes (mm) | Ratio | Mean radius ± sd (mm) |
|---|---|---|---|---|
| **2025, June 2026** | (0.6, −1.25) | 41.2 × 38.2 | 1.077 | 39.6 ± 2.2 |
| **2025, 2026-10-10** (rotated frame) | (−1.0, 0.5) | 41.3 × 38.8 (halves 41.5 × 38.0, 41.3 × 38.3) | 1.064 (1.091, 1.079) | 40.05 ± 1.0 |
| 2022 plates (2022-12, 2023-01) | (1.9, 2.0) | 38.5 × 33.2 (tilted 144°) | 1.16 | 35.6 ± 3.1 |
| 2017 plates (2019-11) | (6.2, −3.8) | 37.7 × 34.6 | 1.089 | 36.8 ± 3.4 |

- **Ratio.** X is wider than Y by **1.07 ± 0.02** on the 2025 plates; the long axis lies within
  10–14° of X. The 2017 plates show the same, 1.09.
- **What it means.** If the plates' active area is round, v⊥y/v⊥x ≈ 1.07, or the anode's x scale
  is ~7% long. Because it appears across plates, it is probably the anode and readout, not the
  plates (confidence medium).
- **Centre.** The two 2025 runs agree after rotation, at about (0.8, −0.9) ± 0.8 mm in the June
  frame.
- **Absolute scale.** The radius is 40 mm at matlab-2019's scale. With "the same diameter" the
  older plates look 8–11% smaller, so the edge is not a reliable absolute scale.
- **Rotation (the front panel's 0.61 rad).** Not measurable here.
- **Candidate v⊥** (geometric mean kept): x 5.088e5, y 5.444e5 m/s, against 5.2632e5 for both.
  This is provisional and needs a round reference.
- **Better data:** a dark run of 30 min or more, and a halo or ring of known shape in free space.

### 2.5 Hot spots and an efficiency map

Hot spots are found with HeLab's own finder (`helab.analysis.hotspots`, α 0.01) on
background-window hits: June 88k hits over 2,194 s; October 117k hits over 3,389 s. They are given
in the June frame:

| Spot (mm) | r (mm) | June rate | Oct rate | Also in |
|---|---|---|---|---|
| (15.9, 1.4) | 2.5 | 3.3 Hz | 4.4 Hz | Jul tight trap, RingBEC |
| (32.3, 1.2) | 1.4 | 1.8 Hz | 0.44 Hz | RingBEC |
| (8.8, −1.0) | 1.5 | 0.10 Hz | 0.13 Hz | |
| (1.2, −0.2) | 1.1 | 0.08 Hz | – | |
| (−27.6, −7.7) | 3.8 | – | 0.14 Hz | |
| (7.1, −3.1) | 1.6 | – | 0.06 Hz | |
| (−29.0, −18.3), (−21.6, −19.4) | 1.6, 1.0 | 0.04 Hz each | – | |

- **Different from the old plates.** None coincides with the 2022 plates' spots, e.g. (27.9, −2.8)
  at 174k counts, (20.1, 14.5), (10.0, 12.2), or with the commented "new detector" spot
  (3.44, 18.96) in `hotspot_mask.m`.
- **Total background:** ~35–40 Hz over the plate.
- **The 180° proof.** June's background image against October's as stored: r = −0.02. Rotated by
  180°: **r = 0.984**. Mirrored in X or Y only: r ≈ 0.0. For RingBEC, rotated: r = 0.80
  (fewer counts).

**Efficiency map** (`ff_relative_density.png`):
- **Spread.** Without the hot-spot bins, the dark-count density in 4 mm bins varies with an
  **sd of 24%** (Poisson 5–6%). The 5–95% range is 0.61…1.34 of the mean.
- **Reproducible.** The June and October maps agree at r = 0.73, and their difference has an sd
  of 18%.
- **Radial fall-off:** 0.96 (r < 12 mm), 0.90 (12–18), 0.85 (18–24), 0.78 (> 24 mm).
- **How far from a true flat field.** Dark counts measure the local dark rate times the gain
  above threshold, not the detection efficiency for atoms. They also include random combinations.
  So this map ranks regions; it does not give efficiency.
- **No cloud-based map.** The large QE clouds aren't flat or well modelled, so I didn't attempt
  one.
- **Better data:** a long dark run, plus a large thermal cloud, whose smooth profile divides out.

### 2.6 Halos: what they can and cannot calibrate

`halos.py`, `halo_bb_control.py`; figures `halo_bb.png` (loose selection, superseded) and
`halo_bb_control.png`.

- **The data.** collisions44 has two BECs 4.05 ms apart in T at (−7.0, −1.3) mm, its own frame,
  and an s-wave halo between them. Expected radius g·ΔT/2 = 19.9 mm/s, or 8.3 mm at t_f = 0.416 s.
- **Its shape.** The halo's equator is a **2.3:1 ellipse** with radii ~14 and ~6.3 mm, the long
  axis at ~−35°.
- **The shape is physical.** That direction matches the trap axes (the front panel rotates by
  0.61 rad = 35°) and is 35° off the detector axes, where any v⊥ error would act. The geometric-mean
  radius, 9.5 mm, is near the expected 8.3 mm. So this is an in-trap-collision halo, distorted by
  the trap, and its roundness says nothing about X/Y scale.
- **Back-to-back correlation is blind to linear errors.** Any affine change of X, Y (scale per
  axis, rotation, shear, centre) keeps v1 + v2 = 2c for every back-to-back pair. Maximising the BB
  correlation therefore cannot fix v⊥x, v⊥y or rotation, only non-linear distortion; the
  numerical check confirms it (x × 1.05 or 0.1 rad: no change). It can fix the scale only together
  with a known radius.
- **No BB peak.** Shell selections give g2(|v1 + v2| < 0.7 mm/s) = 0.87 ± 0.03, a slight dip and
  no peak. The radial and quadratic distortion scans were therefore flat (nothing to optimise).
- **The positive control is too weak to judge.** On the 2022-plate "3 halos" run the same code
  has only 7–12 shell atoms per shot (3–8 pairs in the peak bins).
- **Conclusion:** BB-based calibration of the 2025 plates is **not possible with the data on X**
  (confidence high).
- **Better data:** a free-space halo (Bragg-split, trap off) with ≥100 halo atoms per shot over
  ≥1,000 shots, with the raw files kept, so that matching parameters can also be compared on it.

### 2.7 Matching parameters (HeLab's converter, numpy backend, 172 June shots)

From `matching_params.py`. "Atoms" means the change falls inside the atoms' arrival windows (1.7%
of the time in June).

| Change from matlab-2019 | Hits | Change | Inside atom windows / outside |
|---|---|---|---|
| none (= plates-2025 today) | 529,523 | – | – |
| match tolerance 100 / 300 | | −0.014% / +0.009% | all inside |
| x−y sum tolerance 200 / 300 / 600 | | **−9.7%** / −2.1% / +3.4% | ~95% inside |
| window 3600 / 4000 | | +0.16% / +0.41% | mostly inside; ~80% random (2.2) |
| search depth 18 / 72 | | 0 / 0 | |
| dead time 0.25 µs, all corners | | **−17.6%** | 97% inside |
| x1 dead time 0.5 µs (2023 edit) | | **−28.9%** | 98% inside |
| T sums 3367/3294 | | 0 (T shifts ~1.5 ns) | |
| x2 retry (probe) | | +0.007% | |

In July (sparser clouds) every effect is about 10× smaller: −0.8% for a sum tolerance of 200,
−7.4% for the 2023 edit. **Nothing beats matlab-2019 on these data.** The one improvement worth
building is an offset-centred x−y sum check (D − 121, tolerance ~200), against random
combinations. It needs a schema field; test it on a halo with raw files. The halo correlation
could not be tested: the only 2025 halo has no raw files.

## 3. Other findings

- **Two converters writing TXY (July 2026).** I classified each MATLAB TXY by whether its hits
  ever come closer than 0.4 µs; the 2023 edit's x1 dead time prevents that (`txy_origin_scan.py`).
  - `20260722-…500Hzsampling/d_txy_forc146.txt` is byte-identical to `matlab-2023-lab-edit`.
  - **`20260722-…1000Hzsampling/d_txy_forc183.txt` is corrupted.** It is as long as the
    2019-variant output: its first 16 KiB and its last 65 kB are 2019 output, the middle is
    2023-edit output, and line 465 has 4 fields. That is two programs writing the same file at
    once.
  - RingBEC shots 1 and 841 are 2023-edit-like.
  - None of the 172 June shots, the 45 QE files or the 866 collision files.
  - Of the rest of the tight-trap sample, 22 of 24 MATLAB TXY are identical to HeLab's matlab-2019.
  - Effect: a 2023-edit file has 7–29% fewer hits and T −1.66 ns, a silent shot-to-shot
    inconsistency.
- **Quantum_efficiency (2026-08-12).** 13 subfolders `16pt999`…`17pt199` (likely an RF frequency
  in MHz; the unit is unknown).
  - **Size:** ~15 shots each, about 276k–295k hits per shot. There is a slight downward trend with
    the parameter (−5% from 16.999 to 17.199; `qe_hits_vs_param.png`), estimated from the X file
    sizes at 34.9 bytes per hit.
  - **Timing:** hits arrive continuously from T ≈ 0, peaking at 0.37–0.41 s and tailing out to
    ~7 s, as an outcoupled beam would; at 17.199 they come in pulses. The acquisition runs to
    ~7 s, against 4 s elsewhere.
  - **Peak rates** of 0.6–1.7 hits/µs approach the ~100 ns per-channel dead time, so losses
    depend on the rate.
  - **Stray hits:** 7 of 45 files have up to 40 hits at **T < 0, down to −81 s**, and 7 have
    hits beyond 9 s, up to +62 s. These are stray rows far from the trigger in the raw file.
  - **No QE number:** the folder holds no independent atom number (absorption image) or reference.
  - The top level holds 301 earlier shots (setup or tuning; median 2.4 MB, ~69k hits).
- **RingBEC (2026-07-27):** 1,007 TXY, rotated 180° like everything after July, with 2 of 100
  sampled from the 2023 edit. Not analysed further.
- **Logs** (`log_LabviewMatlab.txt`):
  - `posixtime` is local time (AEST) encoded as UTC, **36,000 s ahead** of the true epoch;
    `date` is the local time. Each entry comes ~25 s before its raw file's mtime.
  - The 06-20 log spells the field `shot n_um`, and it has 2 duplicate shot numbers (06-25 has 1).
  - The logs cover more shots than the cherry-picked folders hold: 06-25 has 1,263 rows for 519
    files.
  - Scan columns: `T_scan` (Rabi), `T_delay_scan` (Ramsey; plus `B_trap_scan` and `T_scan` on
    06-25). ch7 relates to none of them.
- **Shot gaps and pauses** (X listings):
  - Rabi is missing 4712–4800 and 5303–5310, and its logs lack raw 4711, 5301, 5302 and 5816.
  - The 2026-07-23 tight trap is missing 573–584 and 4 single shots.
  - Collisions44 is missing 315–340.
  - RingBEC is missing 6 single shots; QE 102 (mostly setup).
  - The 2026-07-22 tight-trap folder has 4 raw files without TXY.
  - 0-byte TXY: one each in 06-20, 06-26 and 07-23.
  - The tight-trap folders, "empty" in my earlier note, now hold 468 raw files and 857 TXY.
- **Ghost counts.** No MCP channel, so the 2022-style ghost-count analysis is impossible. The
  random-combination share (2.3) is the ghost-hit measure available: 5.4% of hits in June's dense
  clouds.

## Scripts (`scripts/`, run from that folder with the venv)

| Script | What |
|---|---|
| `common.py` | paths, raw/TXY/log readers, the helab environment (scratch overrides) |
| `copy_calib_2026.py` | the one-time copy from X with its manifest |
| `probe_match.py`, `validate_probe.py` | the corner-returning matcher; its check against MATLAB |
| `ch7_survey.py`, `ch7_conversion.py`, `ch7_figures.py` | channel 7 |
| `build_hits.py` | per-hit corner times per set (normal and wide window) into the scratch folder |
| `plate_probes.py` | time-sum difference, MCP sums, edge clipping |
| `pulse_spacing.py`, `pulse_spacing_fine.py` | intervals, reflections, dead time, pulse budget |
| `images_hotspots.py`, `images_hotspots_edge.py`, `geometry_flatfield.py` | background images, hot spots, edge, rotation test, flat field |
| `halos.py`, `halo_bb_control.py` | halo shape and back-to-back correlation |
| `matching_params.py` | HeLab converter with perturbed profiles |
| `txy_origin_scan.py` | which converter wrote each MATLAB TXY |
| `other_checks.py` | QE, gaps, logs |
| `write_profile.py` | the provisional profile JSON |

Numbers: `out/*.json`, `out/*.csv` (including `swapped_map_check.json`: the swapped channel map
gives exactly X → −X and Y → −Y on July raw files, with hit counts +0.001%).

## Figures (`figures/`)

| File | Shows |
|---|---|
| `ch7_overview.png` | ch7 time, count per shot vs Poisson, coincident corner pulses, associated hit positions and delay |
| `pp_p25_2025_plates_Jun_2026.png`, `pp_p25_2025_plates_Jul_2026.png` | D histogram, D map across the plate, T of wide-window extras vs normal hits |
| `pp_p22_2022_plates.png`, `pp_p22_2022_plates_2022-11_ghost_counts.png`, `pp_p17_2017_plates.png` | the same for the 2022 and 2017 plates |
| `ps_fine.png`, `ps_intervals.png` | same-channel interval spectra: reflections, dead time |
| `img_background_by_era.png` | background images per era with hot spots and edge points |
| `ff_relative_density.png` | relative dark-count density, June vs October (rotated), and their mean |
| `halo_bb.png` | first, loose BB selection and the affine and non-linear scans (superseded) |
| `halo_bb_control.png` | BB g2: 2022-plate control vs the 2025 collisions halo |
| `qe_hits_vs_param.png` | QE run: hits per shot vs the folder parameter |

## Candidate profiles (in the JSON, not installed)

`wired_as_june_2026` is matlab-2019 with v⊥ x 5.088e5 and y 5.444e5. `wired_as_from_july_2026`
is the same with corners `x1=1, x2=0, y1=3, y2=2`, for raw data recorded after the swap; it gives
the June orientation. Both are `calibrated: false`, and both load with `DetectorProfile.from_dict`.
The v⊥ change is the only output change, and it rests on the round-active-area assumption. Until
Tony decides, `plates-2025` should stay a copy of matlab-2019.
