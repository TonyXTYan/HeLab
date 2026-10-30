---
date: 2026-10-29
status: settled
name: txy-converter
description: "The TXY converter in HeLab (v0.0.7, stages 1, 2 and 4): replaces MATLAB's tdc_autoconvert byte for byte; d_txy_helab_<tag>_<N>.txt with frozen tags, into the cache (default) or temp folder, beside the raw files only per folder; NumPy default + Cython optional + the reference; four TXY source modes; settle and damaged (20 s) rules; temp name + rename; JSON detector profiles, default matlab-2019, plate profiles and calibration by halo correlation; Tony's decisions and wording"
metadata:
  node_type: memory
  type: result
---
Decided with Tony in Maestri Chat, 2026-10-28 and 2026-10-29 (Q6.x, Q8.x, Q9.x, Q10.x–Q18.x in
`.ai/DECISIONS_TODO.md`, decided ones under Recently decided). Plan and stages:
`roadmaps/txy-converter.md`; how it works: `.ai/architecture/converter.md`; built overnight on
2026-10-29 (`.ai/sessions/2026-10-29-claude-v0.0.7-overnight/mandate.md`), follow-ups landed
`c718c71`. Open questions stay in DECISIONS_TODO (Q12.6, Q14.2, Q14.4, Q15.3, Q23.x, Q25.2,
Q25.4).

## Goal and bar

- **Replace MATLAB's `tdc_autoconvert`** with a headless HeLab converter, plus an auto-convert
  toggle in Live (Q6.3.2, 2026-10-28). Raw files for testing are on X ("there are many raw d files
  in Volume/X that you can read for testing"), read-only and outside pytest.
- **Byte-identical first** (Q6.5, 2026-10-28): stages 1 and 2 reproduce the existing MATLAB
  converter's output, and the code stays adaptable so detector parameters can be tweaked; later
  perhaps a parameter scan on real signals. Tony's prompt: "try build using few different packages
  and benchmark, how about GPU accelerated?" (MLX tried; not Julia, PyTorch or JAX).
- **v0.0.7 ships stages 1, 2 and 4 and the smoke pass** (Q9.9); calibration (stage 3) and
  replacing MATLAB (stage 5) may follow. Distributed compute waits: "postpone distributed compute
  build until we have a very good working tdc_autoconvert within helab" (Q6.2, 2026-10-28).

## Output

- **Where** (Tony, 2026-10-29): Q12.1 a folder without a data root converts to temp; Q12.4 a
  typed `--output beside` overrides the folder's setting; Q12.3 converted TXY in the cache get
  their own budget, beside TXY none; Q19.7 the temp output stays; Q26.2 one
  `converted-txy/index.sqlite` replaces the per-shot JSON before v0.0.7's release (built,
  landed `460360b`); Q19.5/Q27.4 a Don't cache folder converts to temp.
- **The command line may override Don't cache** (Q30.2, Tony 2026-10-30, answered twice): a typed
  `helab convert --output cache` warns and asks `[y/N]` on a terminal (temp by default and without
  one); `--output cache-forced` writes to the cache without asking. The app and the setting's
  default keep "the flag wins".
- **Last used** (Q30.3, 2026-10-30): a load marks a folder's `last_used` at most hourly; the uses it
  skipped are written at quit, a quit save like the others (quit window, 5 s, Quit now skips), and
  ("(a)+(c)") also in the background every ~10 min (A30.4, built). `helab convert --once` calls a raw file
  damaged only at 60 s by its mtime (Q23.7 (c)). A TXY is current only while its size and
  mtime match the index (Q30.1).
- **Name** (Q18.4, 2026-10-29, "agree with your suggestions"): `d_txy_helab_<tag>_<N>.txt` (`.txt`
  like MATLAB's `d_txy_forc<N>.txt`). Short fixed tags, frozen once used: `m19v1` matlab-2019,
  `p22v1` plates-2022 v1, `p25t1` plates-2025 testing (prefixes `a`/`b`/`t` for alpha, beta,
  testing); app-tweaked profiles `u<hash>`. `m23v1` and `p17v1` are still to confirm (Q23.1).
- **Where** (Q9.3, Q9.7, 2026-10-29): a setting, the disk cache by default or the temp folder;
  writing beside the raw files is an option per folder. This amended Q8.2 ("HeLab still never
  writes to source folders"): HeLab writes nothing else beside them, no metadata either (Q18.4:
  per-shot provenance only in HeLab's folders; a beside TXY is current while newer than its raw
  file).
- **Temporary name and rename** (Q18.6, "keep partial"): it stops other readers seeing a
  half-written TXY whatever the speed (Tony's 2026-10-19 rule for MATLAB); writing elsewhere and
  moving isn't atomic across a share. A later conversion removes its own `.partial` leftovers (on
  AGENTS.md's housekeeping list).
- **No hits** (Q10.3, "OK"): a 0-byte HeLab TXY, so "converted, empty" differs from "not converted
  yet", and the GUI warns about such shots (A17.1).

## Raw files not done

- Read only once settled; HeLab keeps its checks for half-written files, and must be careful about
  raw files still being written (Q9.8). MATLAB's converter gets no temp-name change (Q9.8).
- **Damaged** (Q18.5, "damaged timeout 20s"; raw files arrive about one per 30 s): a raw file
  unchanged for 20 s that still fails the format checks is marked damaged (a notification, a status
  in Live and Folder details, no TXY) and never holds up later shots. A file with no rows is never
  skipped silently (Q10.2, "OK"); as built it follows the same 20 s rule (Q23.3 to confirm).

## Backends

- **What ships** (Q11.2, 2026-10-29): "NumPy stays the default, and Cython is the optional
  backend." The app ships NumPy, Cython and the reference (`134e2ec`); numba, MLX and Rust left
  the build, lock and CI's required set.
- **Keep the code** (Q11.3): "yes, and keep all the backend code developed"; the reference stays in
  the build as the test oracle, never the default.
- No `setup.py` extra for the fast backends (Q16.1, "no"). numba's cache, for developers, goes in
  HeLab's temp folder (Q18.1).
- Measured (stage 2): NumPy meets both targets on one core (Live, one shot per ~30 s: "real
  experiments have one d every ~30s"; bulk, faster than gigabit); compiled backends ~1.5× per core.

## Which TXY a folder uses

- Q6.6 (2026-10-29): offer the choices in the plot settings. Built as **four source modes**
  (Q18.2): helab-priority (the default), matlab-priority, helab-only, matlab-only; HeLab's profile
  chosen by its tag. Every dataset and saved result records its source.

## Live and the headless command

- The auto-convert toggle shows once Live is on: "show auto convert toggle after live is toggled"
  (Q6.8, 2026-10-28). It resets each session (Q9.6).
- **One launch folder** (Q18.3): Live runs in one folder only; an instance set to launch Live and
  auto-convert opens no other folder tabs; turning Live on collapses the file explorer panel
  (built as the whole left panel, Q23.2 to confirm).
- Alerts: system notifications only, none of MATLAB's sounds, plot or email (Q9.4).
- Headless: a small command for now, `helab convert --watch <folder>` (Q9.5).
- The acquisition PC (`TDC_User`) already runs HeLab and has MATLAB (Q9.1).

## Detector profiles and calibration

- **Post-2025 plates** (Q25.1, Q25.5, Tony 2026-10-29): the July 2026 cable swap is the
  detector's orientation, so `plates-2025` gets a dated 180° rotation, applied as exact sign flips;
  a burst veto, opt-in in stage 3 after the lab check, tested on dense clouds. Findings provisional
  while X is transferred (`.ai/sessions/2026-10-29-claude-txy-2025-plates/`).
- **Profiles** (Q6.11, 2026-10-28): JSON files; the 2017, 2022 and 2025 plates' profiles are built
  into the app, which can import, export and tweak them; the 2025 profile is marked uncalibrated.
  The MCP diameter hasn't changed; no mask or grid.
- **Default** (Q6.10, 2026-10-29): `matlab-2019`; a plate profile may change every parameter we
  might want to calibrate. The 2022-11 ghost-counts run was on the new plates. Plate swaps
  2017-03-17 and 2025-06-18; the 2022 date is unknown (2022-11-03 provisionally, Q6.10 open).
- The third MATLAB variant (two 2022-07 shots re-converted 2023-02-08): "no, ignore those"; no
  built-in profile (Q10.1).
- **Calibrated** (Q6.11, 2026-10-29): with halos, the parameters that maximise the correlation
  across halos (the back-to-back pair correlation); also hotspot maps and efficiency by region.
  Tony approves each calibration. Provisional calibrations from X's data come in stage 3, after
  the converter is built (halo runs copied to `~/HeLab-samples/calib-v1/`).

## Process

- Samples (Q8.6): a fixed set copied once from X to `~/HeLab-samples/txy-v1/`; floors read only
  that, never X. Backend floors' packages only in their own venvs (Q8.5).
