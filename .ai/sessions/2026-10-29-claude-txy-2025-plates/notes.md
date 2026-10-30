# Post-2025 plate data: converter check and plate probes (2026-10-29)

Side (Claude), on Ground, at Tony's request in Chat: "now we have some post 2025 plate swap data in
volume x cherry-picked, can you run tests on them?". Read-only on X; no app or cache code changed.

## Data

X's `dld_output_cheerypicked` now has nine folders dated after the 2025-06-18 plate swap. Four have
raw files with MATLAB's `d_txy_forc` beside them (Jun 2026: `20260620_Rabi_trial_weak_intrap`
1,619 shots, `20260625_Ramsey_weak_trap` 519, `20260626_Ramsey_weaktrap` 1,840,
`20260627_Ramsey_weaktrap` 2,570); five have TXY only or nothing (`20260722/23-tight-trap-freq-meas`
empty, `20260727-RingBEC` 1,007 TXY, `20260812_Quantum_efficiency` 159 TXY,
`20261010-411trapcollisions44` 866 TXY).

A sample set was copied once, like `txy-v1`: `~/HeLab-samples/txy-2026/` (read-only, 78 MB), the
four raw folders, 43 shots each (about 40 evenly spaced plus the 3 largest), each with its
`_txy_forc`, and `manifest.json` with SHA-256s.

## Converter check

`dev/txy/check_samples.py --root ~/HeLab-samples/txy-2026 --positions all --profile matlab-2019`:
**172 of 172 shots byte-identical** to their MATLAB TXY, with the `reference` and `numpy` backends
(Cython isn't built on Ground). So the 2026 TXY were also written by the 2019 converter, and HeLab
reproduces them exactly.

## Raw files

- First line: channel 5 (the trigger) in all 172 files.
- **New: channel 7.** One or two channel-7 pulses per file, near its end (e.g. 2.54 s after the
  trigger in a `20260625` shot). Not in the 2019–2024 samples. Ignored by the converter, as by
  MATLAB; its meaning (an external marker?) is for Tony.
- No MCP pulses (channel 4), so the 2025 plates' absolute time sums can't be measured from these
  runs (the same limit as 2023–2024).
- x1 has ~22–24 % more pulses than x2, y1 or y2, as on the 2022 plates (ringing on x1).

## Plate probe (MATLAB, the 2019 variant keeping raw corner times; `probe2.m` in scratch)

| Set | Plates | Hits | x−y sum (bins, median / IQR) | Hits added by a 4000-bin x window | 99.9 % range x1−x2 / y1−y2 |
|---|---|---|---|---|---|
| 2026-06-20 Rabi | 2025 | 86,610 | 121 / 61 | +0.23 % | −2909…2957 / −2893…2772 |
| 2026-06-25 Ramsey | 2025 | 133,113 | 121 / 62 | +0.28 % | −2902…2916 / −2894…2727 |
| 2026-06-26 Ramsey | 2025 | 130,406 | 121 / 63 | +0.30 % | −2902…2911 / −2905…2742 |
| 2026-06-27 Ramsey | 2025 | 179,394 | 123 / 64 | +0.30 % | −2905…2899 / −2903…2729 |
| 2023-02 He3/He4 | 2022 | 145,422 | 106 / 68 | +0.00 % | −2509…2816 / −2449…2595 |
| 2024-11 low occupancy | 2022 | 33,270 | 98 / 39 | +0.04 % | −2826…3059 / −2748…2770 |
| 2022-07 large He3 | 2017 | 358,269 | 97 / 76 | +0.46 % | −3021…3168 / −3046…2875 |

Readings (provisional, for stage 3):

- The x and y time sums differ by ~121 bins on the 2025 plates (2022 plates ~98–106, 2017 plates
  ~97). Harmless for matching (the check allows 400); it shifts T by ~1.5 ns.
- The 2025 plates' hits fill more of the 3200-bin x window than the 2022 plates' did, and a
  4000-bin window adds ~0.25–0.30 % hits (2022 plates: ~0 %; 2017 plates: 0.46 %). Whether those
  extra hits are atoms or random pulse combinations isn't checked (their arrival-time distribution
  would tell): a stage 3 calibration question for `plates-2025`.
- The footprint is close to square (x ±2900, y −2900…+2750 bins at 99.9 %), unlike the 2022
  plates' smaller one.
