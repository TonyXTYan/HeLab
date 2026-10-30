# TXY converter port: findings before the spike (2026-10-28)

Side (Claude), on Ground, while planning v0.0.7's converter port with Tony in Chat (orange).
Decisions are in [DECISIONS_TODO](../../DECISIONS_TODO.md) (Q6.3, Q6.5, Q6.9, Q6.10, Q6.11); the plan is [roadmaps/txy-converter.md](../../../roadmaps/txy-converter.md).

## Samples on X

X is `//…/X`, mounted on Tony's Mac at `/Volumes/192.168.137.1-4` (an HDD over SMB: list and
read sparingly). One listing pass, 5 levels deep, took ~1 min and found ~442k raw `d*.txt` and
~440k `d_txy_forc*.txt` in 557 folders, 2019–2024:

| Folder | Raw files |
|---|---|
| `dld_output_cheerypicked` | 225k |
| `2020_Momentum_Bells` | 120k |
| `2024_Momentum_Bells_V2` | 58k |
| `2022_degenerate_He3_and_He4_mixture` | 17k |
| `20241107_RT_low_mod_occ_350_mus` | 11k |
| `2022_ghost_counts_debacle` | 9k |
| `2023_BEC_DFG_oscillation_data` | 1k |

TXY is 27–41 % of the raw size: 2022 ghost counts `…cut_1` 9.0 MB raw → 2.5 MB TXY;
`20241107…` 679 MB → 279 MB.

## MATLAB runs headless

`/Applications/MATLAB_R2025b.app/bin/matlab -nodisplay -batch "…"` starts in ~5 s, licensed, no
toolboxes needed (the reconstruction uses core functions only; `uniquetol` and `textscan` are
core). Run on local copies only: `dld_raw_to_txy_counts` writes beside its input.

Both sample shots are reproduced **byte for byte** by the 2019 variant (`dlmwrite`, precision 8,
flags `1,0,1,0`):

| Shot | 2019 variant | 2023 lab edit |
|---|---|---|
| 2022 ghost counts `d1` (1.5 MB) | 12,152 hits, identical, 0.33 s (first call) | 10,678 |
| `20241107` `d1111` (51 kB) | 588 hits, identical, 5 ms | 506 |

## What runs

`dld_raw_to_txy_counts` calls `dld_read_5channels_reconst_multi_imp(file, 1, 0, 1, 0)`:
subtract the trigger time, no 5-hit/MCP groups, 4-corner matching without MCP, no 3-corner
reconstruction. Only lines ~30–66 (import, sort), 424–599 (4-corner match) and the final combine
run, about 200 lines. The 3-corner section (with the tsum correction polynomials `a_x … d_y`)
and the MCP sections never run.

## The 4-corner match (2019 variant)

Constants: `bin_time` 25 ps; `tsum` 3200 bins (80 ns); tolerance 200 bins; `v_perp_x/y`
5.2632e5 m/s; `search_no` 36 rows.

For each pulse on channel 0 (x1), in time order from the second sorted row:

1. **x2:** search rows −1, +1, −2, +2, … up to 36 rows away; skip rows more than `T_sum` from
   x1 in time, and pulses already used (their channel is set to NaN). The first channel-1 pulse
   with `|x1 − x2| < 3400` is taken. A second candidate sets `how_many_x = 2` and breaks.
2. **The quirk:** `if how_many_x == ~1` is `how_many_x == 0` (`~1` is false), so only "no x2"
   skips. The comment says "If cant find X or is not unique", so an ambiguous x2 was meant to be
   rejected, but the nearest candidate is kept.
3. **y1/y2:** the same search for channels 2 and 3, requiring `|y1 − y2| < 3400` and
   `|x1 + x2 − y1 − y2| < 400` (the x and y sums agree). This check is what catches a wrong x2:
   a wrong pair rarely has the right sum. When it fails, the hit is dropped, and **x1 is not
   retried with the other x2 candidate**. A second y pair also only breaks; the first is kept.
4. **Output:** T = (tx + ty)/2 with tx = (x1 + x2 − T_sum)/2, ty likewise; X = (x1 − x2)·v·25 ps,
   Y = (y1 − y2)·v·25 ps. The four pulses are marked used.

The first sorted row is skipped as "the trigger". The raw files start with several channel-5
rows: in 2022 `d1` the first is the trigger and the next 15 are small numbers (~6.4e6) that
sort first; in 2024 `d1111` there are 12 channel-5 rows within ~55 µs of the trigger.
`t_zero` is the first **unsorted** row. Channel 4 (MCP) has 33k pulses in 2022 `d1` and none in
2024 `d1111`.

## The 2023 lab edit

In the front panel's copy (`legacy/DLD_front_panel/lib/Core_BEC_Analysis/lib/import_mcp_tdc_data/`),
committed by Tony on 2023-08-29 as a sync of the lab machine ("don't ask me, I'm not the one who
created these chain of submodules...."); who made the edit and when is not recorded. That
folder's `dld_raw_to_txy.m` calls it with the same flags, so TXY written by the front panel may
come from it.

1. **x1 dead time:** before matching, `uniquetol(x1, 0.5e-6/bin_time, 'DataScale', 1)` keeps
   one x1 per 0.5 µs (20,000 bins) and drops the rest. The same cut for x2 (0.5 µs), y1 (5 µs)
   and y2 (3 µs) is written and commented out. Likely aimed at the 2022 ghost counts (ringing on
   x1), and it also drops real second hits: −12 % and −14 % on the two samples. `uniquetol`'s
   grouping (first of a run, or chained) is to be confirmed by running it.
2. **Separate time sums:** `T_sum_x = 3390`, `T_sum_y = 3275` in tx/ty only, which shifts T by
   −(190 + 75)/4 bins ≈ −1.66 ns. The matching still uses 3200 ± 200.
3. **X/Y:** the columns now hold raw x1, x2, y1, y2, but X = (x1 − x2)·v·25 ps is unchanged.
4. **Abandoned:** MCP matching (commented out); `dld_pulses_used` is built and not returned.

## Detector assumptions, and the new detector

Both variants hard-code the old detector: the channel map (0–3 corners, 4 MCP, 5 trigger), one
time sum (3200) for both axes, the tolerance, v⊥ on both axes, and the 36-row search.
`tdc_auto_convert.m`'s done-writing check also wants the first line to start with channel `5`
(the 2023 lab sync added `start_channel = '5';%'4';%`).

There is no hotspot mask, radius cut, position limit or rotation in the converter. The front
panel applies them at import: `dld_xy_rot` 0.61 rad, `txylim`, and an optional
`hotspot_mask` (Bryce, 2020-06), whose default ("good as of 2019-11-20") is a 38 mm detector
circle minus nine hotspots, with the new detector's one hotspot (3.44, 18.96) mm, r 5.5 mm,
commented out.

**Hypotheses for the post-2023 detector (untested):** if 3390/3275 are its measured time sums:

- the x2 window (`|x2 − x1| ≤ 3200` bins, i.e. |X| ≤ 42.1 mm at the old v⊥) may drop hits at
  the outer x edge;
- v⊥ is the delay line's length over its time sum, so a longer time sum with the old v⊥
  overstates X by ~6 % and Y by ~2 %: the image would be slightly stretched in x;
- T is offset by ~+1.66 ns (negligible).

Check on post-2023 flat-ish shots: hits near the x edge with a wider window, and the image's
aspect ratio.

## tdc_autoconverter history (`HeBECANU/tdc_autoconverter`)

- 2017-11-15 to 11-17: David Shin, "AutoConvert v2"; the reconstruction file arrives in the
  first commit (it carries Bryce's earlier change log).
- 2018-10 to 2019-03: Bryce Henson, project layout, `is_early`, graph output, sounds, README.
- 2019-07-07: rkhakimov, "minor bug fixes" and "merged changes on tdc computer" (`e4f8812`, the
  submodule's pin). The reconstruction is byte-identical to the 2017 one: it has not changed
  since at least 2017 in this repo.
- 2023-08-29: `TDC_User` "sync changes" (branch `TDC_User`): the default folder becomes local
  (`C:\Users\TDC_user\…\dld_output`) and `start_channel = '5'`. Same day, Tony's
  `LaserMac-BECMachine-cloudstor` branch ("original .git folder is broken") holds only
  `AutoConvert.m` and the README.
- 2025-01-03: Tony's `dev-tony`: `tdc_convert_filelist.m` (converts a given list of files, no
  watching or sounds; noted in its header as ChatGPT-generated), calling the same
  `dld_raw_to_txy_counts`.

Nothing in the history mentions the detector change or the dead time.

## Old vs new MCP plates (He3/He4 folders)

Tony: the MCP plates changed in ~2022 and in 2025. On X, `2022_degenerate_He3_and_He4_mixture/
he3_he4_mixture/` has `old_plates` (2022-04 to 2022-07) and `new_plates` (2023-02), so the ~2022
change falls between 2022-08 and 2023-02. X has no 2025 data (latest is 2024-11).

Probe (MATLAB, a copy of the 2019 variant that keeps the raw corner times, `scratchpad` only;
5 shots each, every 40th shot from #10): old `20220727_he3_he4_even_mix`, new
`20230210_BEC_DFG_cold_368.5_He3_0.793_evap`, and old-plate `20220706_large_he3_clouds_v2…`.
None of these files has MCP pulses (channel 4).

| Set | Hits | x sum − y sum (bins, median, IQR) | Extra hits with a 4000-bin x window | 99.9 % range of x1−x2 / y1−y2 (bins) |
|---|---|---|---|---|
| old plates | 35,802 | 93, 67 | +133 (0.4 %), \|x1−x2\| > 3200: 190 | −3015…3183 / −3051…2920 |
| large He3 clouds (old) | 30,467 | 101, 72 | +33 (0.1 %), \|x1−x2\| > 3200: 71 | −3000…3187 / −3038…2637 |
| new plates (2023) | 26,826 | 108, 65 | +4 (0.01 %) | −2268…2422 / −2075…2130 |

With the default window, old-plate hits stop exactly at |x1 − x2| = 3200 (the cut); with 4000
they reach ~3700. Whether those extra hits are atoms or random pulse combinations is not yet
checked (their T distribution would tell).

Absolute time sums from MCP pulses, 2022-11 ghost counts `d1` (the nearest MCP pulse within
10 ns of each hit, 11,202 of 12,152 hits): **x 3367 (IQR 99), y 3294 (IQR 63)** bins. Any MCP
cable delay offsets both equally. These match the 2023 edit's 3390 / 3275 better than 3200.

Readings:

- x and y time sums differ by ~70–110 bins on both plates. The 2019 code tolerates that (its
  check allows 400), so it only shifts T, by ~1.6 ns.
- The 3200-bin x window clips ~0.1–0.5 % of hits on the old plates and almost none on the
  2023 plates, whose hits span a smaller range.
- X/Y scale: v⊥ is fixed for 3200 on both axes, while the measured sums are ~5 % (x) and
  ~3 % (y) longer. If v⊥ was never recalibrated, X/Y may be off by a few percent and differ
  between axes. A physical check: Momentum Bells halos (`2020_Momentum_Bells/…halos…`) are
  spheres of known radius, so their aspect ratio and size calibrate both axes directly.
