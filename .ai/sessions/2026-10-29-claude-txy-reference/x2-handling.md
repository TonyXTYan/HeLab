# x2 and y handling on the sample set (builder, 2026-10-29; cross-checked by Lens, corrected after its F3)

What MATLAB does (matlab-2019, both variants alike): for each x1 the search visits rows −1, +1,
−2, +2 … and keeps the **first** x2 candidate; meeting a **second** stops the x2 search
(`how_many_x == ~1` means only "no x2" skips). If no y pair then passes the sum check
(|x1 + x2 − y1 − y2| < 400) the hit is dropped, and the second x2 is never tried. For y, the first
pair in search order is kept; a second pair is only counted.

Measured with `dev/txy/x2_report.py --positions all` (counts kept by the reference port itself,
`MatchStats`; the default output is unchanged by counting). "Retry would match" checks whether
the second x2 candidate would find a y pair, **without** using it, so later matches are as
MATLAB's: an estimate of what a retry would recover, before any knock-on effect (a recovered hit
takes 4 pulses later x1 rows might have used, and MATLAB finds at most 2 candidates, so a third is
never seen).

| Set | Hits | x2 ambiguous (of x1 with an x2) | x2 found, no y | of which x2 ambiguous | Retry would match (of hits) | y ambiguous (of hits) |
|---|---|---|---|---|---|---|
| 2019-halos-old-plates | 259,421 | 5,878 (2.22 %) | 5,177 | 728 | 523 (0.20 %) | 595 (0.23 %) |
| 2020-halos-weak-trap | 123,344 | 1,046 (0.84 %) | 1,470 | 279 | 167 (0.14 %) | 127 (0.10 %) |
| 2022-07-old-plates-he3he4 | 287,703 | 14,728 (4.73 %) | 23,566 | 3,053 | 1,430 (0.50 %) | 738 (0.26 %) |
| 2022-07-old-plates-large-he3 | 358,269 | 27,350 (6.80 %) | 43,775 | 6,027 | 2,818 (0.79 %) | 972 (0.27 %) |
| 2022-11-ghost-counts-mcp | 70,461 | 10 (0.01 %) | 16,708 | 10 | 2 (0.00 %) | 0 |
| 2023-02-new-plates-he3he4 | 145,422 | 12 (0.01 %) | 54,186 | 10 | 3 (0.00 %) | 0 |
| 2023-03-momentum-bells | 202,801 | 14 (0.01 %) | 28,224 | 10 | 1 (0.00 %) | 0 |
| 2024-11-rt-low-occupancy | 33,270 | 2 (0.01 %) | 4,087 | 2 | 0 | 0 |
| **all** | **1,480,691** | **49,040 (2.96 %)** | **177,193** | **10,119** | **4,944 (0.33 %)** | **2,432 (0.16 %)** |

**What a retry really gains** (Lens's F3: the column above overstates it by ~15 %, since a
recovered hit takes pulses later MATLAB hits used). Simulated over whole shots with
`dev/txy/x2_retry.py --positions all` (a copy of the reference loop with the retry; with the
retry off it equals the reference on every shot, checked before counting). Lens's own simulation
gives the same nets.

| Set | Hits | Retry the second x2: net | new / lost hits (as rows) | Retry every candidate: net |
|---|---|---|---|---|
| 2019-halos-old-plates | 259,421 | +491 (0.19 %) | 521 / 30 | +492 |
| 2020-halos-weak-trap | 123,344 | +164 (0.13 %) | 166 / 2 | +164 |
| 2022-07-old-plates-he3he4 | 287,703 | +1,192 (0.41 %) | 1,391 / 199 | +1,203 |
| 2022-07-old-plates-large-he3 | 358,269 | +2,402 (0.67 %) | 2,741 / 339 | +2,424 |
| 2022-11-ghost-counts-mcp | 70,461 | +2 | 2 / 0 | +2 |
| 2023-02-new-plates-he3he4 | 145,422 | +3 | 3 / 0 | +3 |
| 2023-03-momentum-bells | 202,801 | +1 | 1 / 0 | +1 |
| 2024-11-rt-low-occupancy | 33,270 | 0 | 0 / 0 | 0 |
| **all** | **1,480,691** | **+4,255 (0.29 %)** | **4,825 / 570** | **+4,289 (0.29 %)** |

"New / lost" compares output rows, so a later hit that matches differently counts once in each;
Lens counts by pulse (4,648 recovered, 393 later hits lost). The net is the same.

Readings:

- On the **old plates** (2019–2022-07) a second x2 is met for 0.8–6.8 % of x1 with an x2, and
  retrying it nets about **0.1–0.7 %** more hits (most in the large He3 clouds, where pulses are
  densest). Retrying every candidate rather than only the second adds just 34 more over all
  sets. The non-committing column above is an upper estimate.
- On the **new plates** (from 2022-11) ambiguity is almost nil (~0.01 %), so the x2 handling
  barely matters there. Their many "x2 found, no y" have another cause, not looked into here
  (missing y pulses, or the time sums: x 3367 / y 3294 bins measured on 2022-11 against the 3200
  used); worth a look in stage 3's calibration.
- A second y pair is rarer (≤ 0.27 %) and its first-in-search-order choice can't be checked
  without the MCP pulse.
- The default never changes (Q6.10): a retry would be a new `x2_handling` value of a plate
  profile, decided with the calibration (stage 3).
