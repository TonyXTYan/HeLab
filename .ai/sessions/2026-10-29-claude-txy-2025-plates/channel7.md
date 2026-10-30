# What is channel 7?

**PROVISIONAL** (Claude, 2026-10-29). This answers Tony's "can you investigate what channel 7
might be?". It follows [investigation.md](investigation.md) §1. The orientation question
(exactly 180°?) is in [orientation.md](orientation.md). Analysis only: nothing was written to X,
and nothing was copied this time.

## Evidence covers

X is still being transferred, so later folders may change the picture. The raw data here is:

| Period | Folder | Raw files used | How |
|---|---|---|---|
| 2026-06-19…20 | `20260620_Rabi_trial_weak_intrap` | 162 of 1,619 | every 10th, streamed from X |
| 2026-06-25 | `20260625_Ramsey_weak_trap` | 519 of 519 | local copy (`calib-2026`) |
| 2026-06-25…26 | `20260626_Ramsey_weaktrap` | 154 of 1,840 | every 12th, from X |
| 2026-06-26…27 | `20260627_Ramsey_weaktrap` | 172 of 2,570 | every 15th, from X |
| 2026-07-21…22 | `20260722-tight-trap-freq-meas` (4 subfolders) | 118 of 468 | every 4th, from X |
| 2026-09-21…22 | `2026-09-22 BEC run` (new on X) | 90 of 269 | every 3rd, from X |
| Pre-swap | `txy-v1` (2019–2024), `calib-v1` (2019-11, 2022-12, 2023-01), `20250104_off_axis_check_mirror` | 4,335 | local |

- **Gaps:** there is no post-swap raw data from 2025 at all; the only 2025 raw folder on X is
  January's, before the plate swap. There is none between 2026-06-27 and 2026-07-21, or from
  August or October (those folders are TXY only).
- **No TDC configuration is on X.** A file-name search to depth 7 found `.ini`, `.xml`, settings
  and `*tdc*` files only for experiment-control LabVIEW, M-LOOP and old MATLAB copies. There is a
  shortcut to `my_read_tdc_gui_v1.0.1` (the TDC program lives on the TDC PC). The per-shot logs and
  folder notes say nothing about the TDC or channel 7.

## Findings

### 1. Rate history: falling, not tied to the experiment

| Period | ch7 rate | Shots with ch7 | Wiring (reflection fingerprints) |
|---|---|---|---|
| 2026-06-19…27 | 0.25–0.40 Hz per day (mean 0.30) | 68–86% | as in June and all earlier data |
| 2026-07-21…22 | 0.06–0.16 Hz per subfolder (mean 0.12) | 24–48% | swapped (x1↔x2, y1↔y2) |
| 2026-09-21…22 | **0.003 Hz** (1 pulse in 90 shots) | 1% | swapped, as in July |
| 2017-03 … 2025-01 | **none** in 4,335 files | 0% | – |

- **No warm-up or HV-ramp signature.** Rates are flat within runs (time-quarter rates, Spearman
  p = 0.12–0.75), apart from one mild overnight rise in 06-26 (0.20 → 0.37 Hz, p = 0.014), and
  nothing depends on the hour of day.
- **Shot by shot,** the counts are Poisson. The times are uniform over the 4 s window, and
  unrelated to the scanned parameters, the time in the run or the hit count (investigation.md §1).
- **The drop does span the cable swap,** which falls between 06-27 and 07-21. But the rate kept
  falling, to almost zero by September, with the wiring unchanged since July. So the swap is at
  most part of the story.

### 2. Every channel-7 pulse sits at the start of a "burst"

On 2026-06-25 (681 pulses, each compared with 20 random times per pulse in the same shots):

- **All four corners fire within −50…+150 ns** of 99.4–100% of ch7 pulses, against 0.0% at random
  times. Within ±1 µs there are **23 corner pulses** (median, p90 25), against 0.02 at random
  times. Within ±10 µs there are 26: the event lasts less than ~1–2 µs.
- **ch7 comes first.** The corner pulses start 0–10 ns *after* ch7, in a fixed pattern: x1 +7.8 ns
  (IQR 1.5), y1 +1.9 ns (IQR 1.7), x2 and y2 ~+20 ns. The commonest orders are "y1 < x1"
  (166 cases), "x1" alone (95), "x2 < x1" (71) and "x1 < x2" (69).
- **Not an MCP pulse.** With ch7 as t0, x1+x2−2·t7 and y1+y2−2·t7 show no peak near the time sums
  (~84 / 82 ns). The only excess is at 5 ns (x) and 70 ns (y), which is just the prompt pattern.
- **The burst is an echo train.** It starts with a pulse on the physical "x1" end: TDC ch0 in June,
  ch1 after the swap; that end is first in 56% of bursts against ~14% for each other end. All four
  ends follow within ~30 ns, and then a group of pulses on every channel repeats every ~170–190 ns
  for more than 1 µs (`figures/ch7_burst_profile.png`). That period is the delay lines' reflection
  round trip: a large signal bouncing in the lines.
- **The "spot" at (−6.6, −10.3) mm is not a place on the MCP.** The hit "reconstructed" from a ch7
  burst has corners at the fixed offsets above, and those offsets alone put it at
  ((7.8 − 20.8) ns, (1.9 − 21.2) ns) → (−6.8, −10.2) mm. In the image it is only a 1.3× excess,
  590 hits against 451 expected within 3 mm. It does contain 8 pairs closer than 1 ms, against
  0.16 expected: burst fragments.

### 3. The bursts are common; channel 7 catches only the biggest

The burst finder takes ≥ 15 corner pulses within 1 µs, all four corners, outside the atoms'
arrival windows (`scripts/ch7_burst_detail.py`, `ch7_burst_eras.py`; figure
`ch7_burst_sizes.png`).

| Data | Burst rate (quiet windows) | Bursts with ch7 |
|---|---|---|
| 2026-06-20 / 06-25 / 06-26 / 06-27 | 7.7 / 8.0 / 8.3 / 8.4 Hz | 4.4% / 4.1% / 3.2% / 3.6% |
| 2026-07-21…22 | 7.9 Hz | 1.7% |
| 2026-09-21…22 | 6.1 Hz | **0%** (0 of 1,450) |
| 2022 plates: 2023-02, 2023-03, 2024-11, 2025-01 | 0.07–0.6 Hz | – |
| 2022 plates, 2022-11 ghost-count runs | **4.5 Hz** | – |
| 2017 plates: 2019, 2020, 2022-07 | 0.02–0.23 Hz | – |

- **ch7 tracks burst size.** It fires on 0% of bursts with 15–20 pulses (in 3 µs), 3.8% at 20–25,
  31% at 25–30 and 20% at 30–40. Bursts with ch7 have 26 pulses (median), those without 19. That is
  a threshold.
- **The source didn't change, ch7's sensitivity did.** The bursts continue at 6–8 Hz from June to
  September; what fell is the fraction ch7 catches (4% → 1.7% → 0).
- **The bursts make ghost hits.** On 2026-06-25 each burst yields 0.82 reconstructed hits, which is
  **16% of all hits in the quiet windows** (~6.5 ghost hits/s). They land at stereotyped apparent
  positions (`ch7_burst_sizes.png`, middle), including June's weak "hot spots" (8.8, −1.8),
  (−29, −18) and (−21.6, −19.4). Those are burst artefacts, not MCP defects. The strong spot H1
  at (15.8, 1.2) mm is not among them.
- **The 2022-11 "ghost counts" runs had the same phenomenon** at 4.5 Hz. The 2025 plates have it at
  6–8 Hz in every run sampled, against ~0.2–0.6 Hz in normal 2023–2024 runs.

### 4. Channel 5's extra rows behave differently

`scripts/ch5_compare.py`, every era.
- **Channel 5:** its rows besides the trigger come in trains of 8–15 rows about 50–62 ns apart.
  The trains sit at +54.6 µs after the trigger, near 3.9–4.2 s (the end of the window) or before
  the trigger, with **no corner pulses around them** (median 0 within 1 µs). That looks like
  ringing on the trigger line at fixed points of the TDC cycle, and it is the same in 2019 and 2026.
- **Channel 7:** single pulses at random times, each inside a detector burst. It is not a sibling of
  channel 5's rows.

## Hypotheses, ranked

| # | Hypothesis | For | Against | Likelihood |
|---|---|---|---|---|
| 1 | **Input 7 is connected to a signal line that sees the detector's large burst events: an MCP/HV monitor or pick-off, a spare amplifier/CFD output, or an unterminated cable acting as an antenna near the detector electronics. Its effective threshold or coupling has drifted down since June (re-cabling in July, then further).** | In 100% of ch7 pulses all four corners fire within 150 ns; ch7 leads the burst by 0–10 ns, so it sees the source *before* the anode chain; it tracks burst size (a threshold); the bursts stay at 6–8 Hz while ch7's share falls 4% → 1.7% → 0%, so the sensor changed, not the source; it appears only after January 2025, i.e. with the 2025 work. | Doesn't say which line. | **high** |
| 2 | The MCP timing pick-off moved from ch4 to ch7, with a very high threshold. | Fires early on big events; the MCP channel is absent since the swap. | No time-sum relation for normal hits; never fires on ordinary atoms (0.3 Hz against kHz in clouds; uniform in T while atoms arrive in windows); fires only inside bursts. At most a special case of 1 (a pick-off set so high that only discharges cross it). | low-medium (as a variant of 1) |
| 3 | A TDC-internal flag (FIFO, rate-overflow or group marker) on a virtual channel 7. | Fires in the densest pulse bursts, more for bigger ones. | It comes *before* the burst's first pulse; not deterministic (31% at 25–30 pulses); its share fell with re-cabling while the bursts didn't, which a firmware flag wouldn't do unless the settings changed. | low |
| 4 | An experiment signal: camera, shutter, laser, RF, LabVIEW digital line. | – | Poisson, uniform over the window, no correlation with logs, scans or time; every pulse inside a detector burst. | very low |
| 5 | An end-of-acquisition or other cycle marker. | – | Uniform in time; not at the window's end. | ruled out |
| 6 | The same thing as channel 5's extra rows. | – | Different pattern: trains at fixed times, no corner pulses. | ruled out |

**And the bursts themselves.** Large events starting at the physical x1 end, at 6–8 Hz, ringing
for ≥ 1 µs. Candidates:
- MCP micro-discharges or field emission on the new plates;
- sparking or corona at an HV feedthrough or connector near the x1-end readout;
- electrical pickup from another device coupling into the anode lines.

The data can't separate these. The x1 end leading in 56% of bursts points to something local to
that end's path.

## What Tony could check in the lab

1. **Follow the cable on TDC input 7.** What is connected: a cable, a terminator, nothing? Where
   does it go? When was it plugged in (after January 2025)? Was it touched during the July
   re-cabling? If nothing is connected and it still fires, it's an open input picking up noise:
   terminate it or disable it.
2. **The TDC program's settings on the TDC PC** (`my_read_tdc_gui_v1.0.1`): the channel enable mask
   and the threshold/CFD level for input 7, and whether channel 4 (MCP) is still enabled. Copy the
   config file to X, so the next analysis can read it.
3. **Scope test.** Put input 7's cable and one anode amplifier output (the x1 end) on a scope,
   triggered on input 7, or on a high threshold on x1. A ch7 event with a ~170–190 ns echo train
   on the anode confirms hypothesis 1, and the waveform shows whether it's a discharge (a large,
   fast spike) or pickup (oscillatory).
4. **HV off and HV scan.** Take ~10 min of acquisition with the MCP HV off (and the anode bias off),
   everything else on. If the bursts and ch7 vanish, the source is in the detector or its HV; if
   they stay, it's external pickup. Then a few HV settings: a discharge rate rises steeply with HV.
5. **The x1 end.** Since bursts start there, inspect that feedthrough, cable, amplifier and CFD
   (seating, shielding, ground); swapping that amplifier channel with another would show whether
   the "first end" follows the amplifier.
6. **Labelled photos** of the TDC input panel and the amplifier/CFD crate, to settle the July swap
   ([orientation.md](orientation.md)) and the ch7 wiring together.

## Consequences for analysis (provisional)

- **Conversion:** ch7 is ignored; the output is unchanged (investigation.md §1).
- **Bursts:** they are a real data-quality issue. ~0.8 ghost hits per burst is ~6.5 ghost hits/s,
  16% of background-window hits. Their stereotyped positions show up as weak "hot spots". A burst
  veto in the converter (drop hits whose pulses fall within ~1–2 µs of ≥ 15 corner pulses) would
  remove them. It needs testing on real atoms in dense clouds, where real hits can reach that
  density; the veto above was only applied outside the atoms' windows. That is a stage-3 candidate,
  not a profile field today.

## Files

| What | Where |
|---|---|
| Scripts | `scripts/ch7_x_scan.py` (rate history from X), `ch7_deep.py` (coincidences, time sums, multiplicity, spot), `ch7_bursts.py` (burst profile), `ch7_burst_detail.py` with `ch7_burst_detail_lib.py` (sizes, ghost hits, history), `ch7_burst_eras.py` (older eras), `ch5_compare.py` |
| Numbers | `out/ch7_x_files.csv`, `ch7_x_pulses.csv` (raw tables, kept out of git, Q29.6), `ch7_deep.json`, `ch7_bursts.json`, `ch7_burst_detail.json`, `ch7_burst_eras.json`, `ch5_compare.json`, `ch7_trends.json` |
| Figures | `figures/ch7_deep.png` (first pulse per channel after ch7; time-sum test against random times; ±1 µs multiplicity; associated hits), `ch7_burst_profile.png` (the echo train, June against July wiring), `ch7_burst_sizes.png` (size with/without ch7; ghost-hit positions; burst rate and ch7 share by period) |
