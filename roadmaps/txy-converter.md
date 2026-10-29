# TXY converter port

Horizon: v0.0.7's focus (Q6.12). Added: 2026-10-28, planned with Tony in Chat; decisions are
Q6.2–Q6.11 and Q8.x in [DECISIONS_TODO](../.ai/DECISIONS_TODO.md); evidence is in the
[findings](../.ai/sessions/2026-10-28-claude-txy-converter-plan/findings.md).
Priority and completion: [overview](_readme.md).

## Purpose

Replace MATLAB's `tdc_autoconverter` (raw DLD `d<N>.txt` → TXY) with HeLab: a headless HeLab
converter on the acquisition PC, and an auto-convert toggle in Live on any HeLab
([Live L4](live-monitoring.md#stages)). Later, detector profiles calibrated per MCP plate
replace the constants MATLAB hard-codes, and a parameter scan tunes them on real signals.

## Decided

- **Goal** (Q6.3.2): HeLab replaces `tdc_autoconvert`; a headless converter, plus Live's
  auto-convert toggle, shown once Live is on (Q6.8), and folders set to start Live and
  auto-convert at launch (Q9.6).
- **Output:** `d_txy_helab_<N>.txy`, written to a temporary name and renamed. In this build every
  HeLab-made TXY stays in HeLab's temp folder; HeLab still never writes to source folders (Q8.2).
- **First bar: byte-identical output.** Stages 1–2 reproduce the existing `_txy_forc` files byte
  for byte, or prove why a reference differs. Stage 1 measured it: of the 309 sample shots,
  `matlab-2019` reproduces 303; the other 6 are proved reference faults (a raw file MATLAB read
  half-written, two shots re-converted on 2023-02-08 by a third variant with a 2 µs x1 dead time,
  three empty files from wrappers that write them). The 2023 lab edit writes 12–14 % fewer hits
  and is reproduced on MATLAB's own output of it.
- **Adaptable:** every constant the MATLAB code hard-codes is a field of a detector profile, so
  later profiles can change them (Q6.10). The ambiguous-x2 handling is measured while building
  (below); changing it is a profile option, never the default.
- **Profiles** (Q6.11): JSON files. The 2017, 2022 and 2025 plates' profiles are built into the
  app, which can import, export and tweak them; the 2025 profile is marked uncalibrated.
- **Implementation is chosen by benchmark** (Q6.5, Q8.5): a plain-Python reference, then one
  backend per floor; the backend stays switchable (lab PCs differ: Apple Silicon, CUDA of unknown
  version, Intel iGPU only).
- **Samples** (Q8.6): a fixed set copied once from X to a local folder; floors read only that.
- **Which TXY a folder uses** (Q6.6): the plot settings offer all three: MATLAB's with HeLab's
  filling missing shots, HeLab's wherever they exist, or both as two datasets for comparing.
  Every dataset and saved result records its source, so caches never mix them.
- **Default profile** (Q6.10): `matlab-2019`. Plate profiles may change every parameter below.
  Plate swaps: 2017-03-17, ~2022 (between 2022-08-22 and 2022-11-03 on X; 2022-11-03 for now),
  2025-06-18. The 2022-11 ghost-counts run is on the new plates.
- **Calibrated** (Q6.11): with halos, the parameters that maximise the correlation across halos
  (the back-to-back pair correlation); plus hotspot maps and efficiency by region. Tony approves
  each calibration; the first, provisional ones are made in stage 3 from the data on X (copied
  to `~/HeLab-samples/calib-v1/`), once the converter is built.
- **Building** (Q9.1–Q9.9, 2026-10-29): the acquisition PC (`TDC_User`) already runs HeLab and
  has MATLAB. Every backend ships for now (A9.1 removes the unused ones). HeLab's TXY go to the
  temp folder while testing, then a setting defaulting to the disk cache; writing them beside the
  raw files is a per-folder option (with auto-convert at launch). Alerts use system
  notifications only. The headless converter starts as `helab convert --watch <folder>`. Live
  auto-convert resets each session, except in folders the user sets to start Live and
  auto-convert at launch. MATLAB's converter isn't changed; HeLab must be careful about raw
  files still being written. v0.0.7 ships with stages 1, 2 and 4 and the smoke pass.
- **Postponed:** distributed compute until the converter works well (Q6.2).

## What the MATLAB converter does

`dld_raw_to_txy_counts` calls `dld_read_5channels_reconst_multi_imp(file, 1, 0, 1, 0)`: subtract
the trigger time, then match four corners without the MCP. About 200 of its 1,660 lines run:
read, sort by time, match each x1 to an x2, y1 and y2 within a 36-row search, then T, X, Y.
Constants: 25 ps bins, one time sum of 3200 bins ± 200 for both axes, v⊥ 5.2632e5 m/s on both
axes, channels 0–3 the corners (4 MCP, 5 trigger). It writes with `dlmwrite`, precision 8. The
[findings](../.ai/sessions/2026-10-28-claude-txy-converter-plan/findings.md) have the match
step by step, the 2023 lab edit, the quirks to reproduce, and the git history. Stage 1 found
more: the output matrix grows with zeros past its `floor(rows/4)` preallocation, so a lone x pair
there is a "phantom" hit at T = 0, Y = 0; and a third variant (2019 plus a 2 µs x1 dead time)
re-converted some 2022-07 shots on 2023-02-08 ([converter.md](../.ai/architecture/converter.md)).

Measured so far (findings): x and y time sums differ by ~100 bins on both plates (harmless, T
only); with MCP pulses (2022-11) they are x 3367 and y 3294 bins, not 3200; the 3200-bin x
window clips 0.1–0.4 % of hits on the old plates and almost none on the 2023 plates; X/Y may be
off by a few percent per axis if v⊥ was never recalibrated.

## Design (proposed)

- **A Qt-free package, `helab/convert/`**, listed as pure in `tests/test_headless_imports.py`:
  - `raw`: parse a raw file to channel and time arrays (and the done-writing checks: settled
    5 s, ends with a newline, first line is the trigger channel, Q: which channel per era);
  - `profile`: `DetectorProfile` (time sums per axis, tolerances, v⊥ per axis, search depth,
    dead time per channel, channel map, centre, rotation, x2 handling, `calibrated`, version),
    to and from JSON, with the built-in profiles;
  - `reconstruct`: `reconstruct(pulses, profile) -> txy` behind one backend interface;
    `backends/` holds the reference and the chosen fast backend(s);
  - `txy`: write TXY exactly as `dlmwrite` precision 8 does, to a temporary name, then rename.
- **Profile parameters** (all may be calibrated; `matlab-2019` fixes them at MATLAB's values):
  - per axis: the time sum (a constant, plus a correction across the plate, as the unused
    3-corner code's cubic once did), the match tolerances, v⊥ (scale), and a non-linearity map;
  - geometry: centre, rotation (the front panel's 0.61 rad), active-area radius;
  - timing: the trigger offset (the 25 ps bin is the TDC's and fixed);
  - per channel: dead time and ringing window, and the channel map (trigger channel 5 or 4);
  - matching: search depth, the x−y sum tolerance, retrying the other x2 or y candidate,
    3-corner reconstruction (MATLAB has it, switched off), MCP matching where recorded;
  - maps: hotspot mask and efficiency by region.
- **Built-in profiles:** `matlab-2019` (the exact MATLAB constants: the default while the
  comparison runs), `matlab-2023-lab-edit`, and the plate profiles `plates-2017`,
  `plates-2022`, `plates-2025` (uncalibrated), which start from `matlab-2019` and change only
  through calibration (stage 3). The default is `matlab-2019` (Q6.10).
- **Provenance:** every HeLab TXY records the raw file's fingerprint and the profile's name,
  version and hash, so shots can be converted again when a profile improves.
- **In HeLab:** a helper operation (`helab/io_ops/`) converts settled raw files; it is source I/O,
  so Work Offline refuses it, and it gets its own event kinds (`events.py`). HeLab's TXY are a
  new file kind (`file_kinds.py`). Docs: a new `.ai/architecture/converter.md`.

## Stages

**Stage 0, on Ground (the Assistant), before any floor.**
- **Done 2026-10-29:** the sample set, copied from X to `~/HeLab-samples/txy-v1/` (outside the
  repo, read-only, 257 MB): 8 sets of ~40 evenly spaced shots plus the 3 largest, each with its
  `_txy_forc`: 2019 halos, 2020 halos, 2022-07 He3/He4 and large He3 clouds (old plates),
  2022-11 ghost counts (the only set with MCP pulses, 10 shots), 2023-02 He3/He4 (new plates),
  2023-03 Momentum Bells, 2024-11 low occupancy. `manifest.json` gives each set's source folder
  and each file's SHA-256.
- MATLAB-made references for the same shots stay as they are; MATLAB runs only on local copies.
- Briefs for stage 1, with this plan.

**Stage 1, the reference and harness** (one floor; a builder and a cross-checker, both Workers;
the Reviewer reviews at the end). **Done 2026-10-29** (`agent/txy-reference`, landed as
`d26e196`; [session](../.ai/sessions/2026-10-29-claude-txy-reference/handoff.md)): `helab/convert/`
and `dev/txy/`; 303 of 309 shots identical and 6 proved reference faults; the 2023 edit identical
on MATLAB's own output; 39 synthetic cases and 1,367 `textscan` probes judged by MATLAB; the
reference converts ~11 MB/s per core. x2 handling: on old plates a retry of the other x2 would
add 0.1–0.7 % hits, on new plates almost none; the default is unchanged.
- The builder ports the running path to plain Python, quirks included (`how_many_x == ~1`, the
  first sorted row skipped, `t_zero` from the unsorted first row), as `matlab-2019` and
  `matlab-2023-lab-edit`; then the harness: the sample manifest, a checker (byte-identical, and
  on mismatch the first differing line), a timing harness, and the backend interface.
- The cross-checker never edits the port. It checks it line by line against both MATLAB
  variants, against MATLAB run headless on synthetic edge cases (ambiguous matches, pulses
  exactly at a tolerance or the dead time, empty, truncated, hits at the file's start and end),
  and against the real samples the builder didn't use.
- Both measure the x2 handling: how often a second x2 or y pair exists, and what retrying the
  other candidate would recover. A report only; the default doesn't change.
- Tests use synthetic raw files and `tests_sample_data/`, never the sample set (tests never
  touch real data).
- **Done when:** byte-identical on every synthetic case and every sample shot for
  `matlab-2019`, and for `matlab-2023-lab-edit` on MATLAB's own output; the full suite and type
  checks pass; the cross-checker and the Reviewer have no open findings.

**Stage 2, backends** (one floor per backend, each from stage 1's commit; the cross-checker
connected to all). **Done 2026-10-29** (landed `d522691` cython, `32158c2` mlx, `7031bea` rust,
`aecbe68` numba, `ed35099` numpy with the shared fast I/O and the within-shot split; the final
serial timings `3bd791c`, [results](../.ai/sessions/2026-10-29-claude-txy-bench/results.md)): all five byte-identical to
the reference, also with everything built together. End to end per core: numpy 119, numba 171,
cython 170, rust 178, mlx 72, reference 13 MB/s; numpy on 12 processes 1,049 MB/s. Both targets
are met by numpy on one core; the next lever is the text I/O, not the backends. Recommendation
(Q11.2, for Tony): numpy the default, rust (or cython) optional, drop numba and mlx (A9.1).
- Candidates: NumPy vectorised (plus fast text reading and writing), Numba, Cython or C, Rust
  (PyO3, maturin), Apple GPU (MLX). CUDA (CuPy) is noted for the lab PCs, untested here. Not
  Julia, PyTorch or JAX (packaging).
- Each must pass stage 1's checker byte for byte. Packages go only into the floor's own venv.
- Parallelism, measured for each: across shots (processes), threads where the backend releases
  the GIL, and within one shot (cut the pulse stream at gaps longer than the match window;
  must stay byte-identical).
- Measures: raw MB/s per core and in total, latency per shot (small and large), reading and
  writing separately, and the size each backend adds to the PyInstaller build.
- Final timings are taken serially by one agent on an idle machine, Tony's HeLab quit.
- **Done when:** a results table and a recommendation (a default backend that works everywhere,
  plus optional fast ones), checked by the Reviewer. Targets: Live, one shot every ~30 s
  (easy); bulk, faster than raw files cross the network, ~100 MB/s on gigabit (Q6.9).

**Stage 3, calibration** (can start once stage 1 is done; includes D11's raw-pulse diagnostics,
[DLD port](dld-front-panel-port.md)).
- From raw pulses: time sums per axis (absolute ones need MCP pulses) and across the plate;
  the x−y difference; pulse spacing (ringing and dead time per channel); hotspot and efficiency
  maps from a dark run and a large thermal cloud.
- Geometry: the profile that maximises the back-to-back correlation across halos (a distortion
  smears the peak), checked against halo roundness and radius; and the plate's edge in a flat
  field (the diameter hasn't changed; no mask or grid).
- Data: the 2017 plates from the 2019–2021 halo runs; the 2022 plates from X's
  `dld_output_cheerypicked` (`20221212_new_plates_halo_test_4`, 2,423 shots;
  `20230130_new_plates_halo_3_halos`, 797; 2023–2024 halo runs) and the 2022-11 ghost counts,
  the only set with MCP pulses (time sums x 3367, y 3294 bins). The 2025 plates' calibration data
  exists but isn't reachable yet.
- A calibration panel proposes a profile; Tony checks it on known physics before saving it.
- The 2025 plates need a calibration set (a dark run, a large thermal cloud, a halo, ideally
  with the MCP channel recorded); until then `plates-2025` stays uncalibrated.

**Stage 4, in HeLab** (core **done 2026-10-29**, `775fb1d` + Windows fixes `6cbe446`: the helper operation, settle checks,
events, the file kind, output locations, provenance, `helab convert --watch`; the TXY source choice
and the profile manager `475c6a6`; Live auto-convert, start at launch and low-count alerts `6454b4a`;
packaging `7cb168e`: every backend in the lock and the build, compiled ones built and required in
CI on three OSes, macOS app sizes mlx +234 MB, numba+llvmlite +127, rust +0.48, cython +0.27.
**Stage 4 done 2026-10-29**; after Tony's answers, the build ships numpy, cython and the reference
(`134e2ec`, A9.1); split into floors in the
[overnight mandate](../.ai/sessions/2026-10-29-claude-v0.0.7-overnight/mandate.md)). Every backend
in the build (Q9.2; NumPy alone always works). The helper operation (raw files read only once settled: unchanged for
5 s, size stable between checks, ending in a newline, starting with the trigger channel), the
file kind, Live's auto-convert toggle (Q6.8), folders set to start Live and auto-convert at
launch (Q9.6), the output location (temp, then a setting defaulting to the cache; beside the raw
files as a per-folder option, Q9.7), low-count alerts through system notifications (Q9.4), the
TXY source choice in the plot settings (Q6.6), `helab convert --watch <folder>` (Q9.5; the
[headless service](headless-analysis.md) can take it over later), the profile manager (import,
export, tweak), provenance, and docs.

**Stage 5, replacing MATLAB on the acquisition PC.** Run beside MATLAB, compare their output on
every shot, then switch (Q6.3.2).

**Later:** distributed compute (Q6.2, Q6.7), TXY kept only in caches (Q6.9), the parameter scan
over profiles scored on real signals.

## Open decisions

- Q6.7: how other HeLabs get the acquisition PC's TXY (postponed with Q6.2).
- Q6.9: store HeLab's TXY, or only cache them (after the benchmark).
- Q6.10: the exact 2022 plate swap date.
- Q6.11: the 2025 plates' data (reachable within days; whether it has MCP pulses).
- Which channel starts a raw file in each era (`start_channel` was switched between `5` and `4`
  in 2023).
