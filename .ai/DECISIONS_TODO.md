# Decisions for Tony

The ongoing list of open questions only Tony can answer. Any agent may raise one. It is one of
three living lists shared by every agent:

- this file: decisions, `Q` IDs;
- [MANUAL_TODO](MANUAL_TODO.md): checks that need Tony at a screen or the lab, `M` IDs;
- [AI_TODO](AI_TODO.md): work agents may do without asking, `A` IDs.

**IDs** are `<letter><block>.<item>[.<sub>]`, e.g. `Q1.2` or `Q2.2.1`. The block says where an
item came from (date, agent, session, branch), in [ID_BLOCKS](ID_BLOCKS.md). An ID never changes
and is never reused. Floors and cloud agents number their proposals provisionally in their own
handoff (`Q~1`, `A~1`, `M~1`). The Coordinator or the Assistant merges them in here under the
next block, and records the mapping in ID_BLOCKS. Use IDs in commits, briefs and Chat ("Q1.2:
yes").

How to use this list:

- Each question has its context in a few lines, the options and a **Proposed** answer, under
  the heading for when it's needed.
- Tony answers under it or in Chat, and the Assistant writes the answer in.
- Once answered, the decision goes where it lives:
  - `.ai/memory/results/` for settled design;
  - the roadmap or a plan for priorities;
  - AGENTS.md or `.ai/architecture/` for rules.

  Then the question moves to **Recently decided** as one line with its ID, cleared at each
  release's tidy-up.
- Features stay in `roadmaps/_readme.md` and bugs in `roadmaps/known-issues.md`; only the
  question goes here.

## Recently decided

Tony in Chat, 2026-10-28, wrapping up v0.0.6 (block 6):

- **Q6.12 v0.0.7's focus:** the TXY converter port (`tdc_autoconverter`) and distributed results
  compute; distributed compute was then postponed until the converter works well (Q6.2). This
  replaces Q1.9's order; its other items stay on the roadmap (item 6 is A7.2).
- **Q6.4 Dependabot can't scan the repo: "a,b,c go".** (a) the 42 alerts were dismissed as not
  used and #8 closed; (b) `DLD_front_panel` and `Momentum_Bells_test` are cloned by hand
  (README); (c) `dependency-graph.yml` submits `requirements.lock` (`7b82c9d`). The check once
  v0.0.7 is on `main` is A7.1.
- **Q2.7 Dependabot alerts on `main`:** resolved by Q6.4 (alerts dismissed, the lock submitted).

Tony's answers in Chat, 2026-10-28, on the [docs audit](sessions/2026-10-28-claude-docs-audit/)
(block 8):

- **Q8.1 The empty v0.0.6a1 draft:** leave it; v0.0.7's release is the first with zips.
- **Q8.2 HeLab still never writes to source folders:** HeLab's TXY stay in its temp folder;
  writing them beside the raw files (Q6.7 a) is revisited with Q6.9.
- **Q8.3 Release tidy-up:** yes, as proposed; the ten "applied as proposed" items are listed for
  him to confirm before they are cleared.
- **Q8.4 `helab/utils/synchronised_dict.py`:** removed (unused since Codebase Review 2).
- **Q8.5 TXY spike setup:** Rust installed machine-wide (Homebrew, 2026-10-28); Numba, Cython,
  maturin and MLX go only into each floor's own venv. One floor per backend, each branched from
  the reference commit; the cross-checker is recruited as a Worker (the Reviewer role is
  read-only) and the Reviewer does the final review; final timings are taken serially by one
  agent on an idle machine, with Tony's HeLab quit.
- **Q8.6 Samples:** a fixed sample set is copied from X once to a local gitignored folder; floors
  read only that, never X (mounted read-write, and its `/Volumes/…-4` path depends on mount order).
- **Q2.1.1** the orphaned pytest was killed; **Q2.1.2** `.ai/temp` stays; **Q2.2.3** the six agent
  branches were pushed (2026-10-28); **Q2.5 yes:** floors run HeLab with their own settings file.

Tony's answers in Chat, 2026-10-29, on what building the converter needs (block 9;
[plan](../roadmaps/txy-converter.md)):

- **Q9.1 The acquisition PC** (the one with `TDC_User`) already runs HeLab and has MATLAB.
- **Q9.2 Backends in the build:** ship every backend for now, with a note to remove the unused
  ones (A9.1).
- **Q9.3 Where HeLab's TXY go:** the temp folder while testing; then a setting, defaulting to the
  disk cache.
- **Q9.4 Alerts:** the system notification API only; none of MATLAB's other alerts (sounds, plot,
  email).
- **Q9.5 Headless converter:** a small command for now (`helab convert --watch <folder>`).
- **Q9.6 Live auto-convert:** resets each session by default; the user can pick folders that
  remember Live and auto-convert and start them when HeLab launches.
- **Q9.7 Writing beside the raw files:** by default HeLab converts into its temp folder or cache;
  writing `d_txy_helab_<N>.txy` beside the raw files is an option the user turns on per folder
  (with auto-convert at launch). This amends Q8.2 (HeLab still writes nothing else to source
  folders).
- **Q9.8 MATLAB's converter gets no temp-name change:** once HeLab converts, no `d_txy_forc` is
  being written; HeLab keeps its checks for half-written TXY anyway, and must be careful about
  raw `d` files still being written.
- **Q9.9 v0.0.7 ships** with stages 1, 2 and 4 done (Live auto-convert and the headless command
  working) and the smoke pass; calibration (stage 3) and replacing MATLAB (stage 5) may follow.

- **Q2.6 Windows CI time: yes** (Tony, 2026-10-29): the Windows test job's limit is 30 min (20
  elsewhere). With it: agents push only at checkpoints, never with every commit (when the work is
  done, after review fixes, or when a CI run is worth it); AGENTS.md, the guide and the Worker and
  Quick Fixer roles say so.

Confirmed by Tony, 2026-10-29 ("confirm all"), and recorded where each lives (AGENTS.md, the
setup guide, the roles): Q3.1, Q3.2, Q2.8, Q2.3, Q3.3, Q3.4, Q3.6.3, Q2.2.1, Q2.2.2, Q4.1.

## From the audit (block 2)

These come from the [audit](sessions/2026-10-28-claude-v0.0.6-checks/audit.md), whose finding
numbers are given as #N. They are quick yes/no answers.

- **Q2.4 `.ai/coding-workspace.md` (#4).** It's a symlink into your `ai-common` folder, broken
  everywhere else. Commit a real copy here, or keep the link and say it's Mac-only? Proposed: a
  copy.

## From the instructions audit (block 3)

Finding numbers refer to the
[instructions audit](sessions/2026-10-28-claude-v0.0.6-checks/instructions-audit.md).

- **Q3.5 Decisions out of AGENTS.md (#6).** Half done: the "(Tony, date)" notes now sit in
  `.ai/architecture/` files, not AGENTS.md. Proposed: also record each in
  `.ai/memory/results/`, where settled decisions live, and have the architecture files link
  there.
- **Q3.6 Smaller rules (#11, #21).** Q3.6.3 is applied (Recently decided).
  - Q3.6.1: commit subjects in the log's "Area: summary" style?
  - Q3.6.2: do floors need the two large submodules (Momentum_Bells_test, DLD_front_panel)?
    Proposed: no; only `legacy/tdc_autoconverter`.

## Automating the smoke pass (block 5)

- **Q5.1 Which model drives the smoke pass** ([runbook](sessions/2026-10-28-claude-smoke-automation/plan.md))?
  Proposed: Haiku 5.5, with Sonnet 5.5 if Haiku misreads the screen. The dry run (A5.1, done
  2026-10-28) used Sonnet 5.5 ([results](sessions/2026-10-28-claude-smoke-mac/results.md)), so
  Haiku is still untried.
  Also: which computer-use tool runs it on each machine (the Claude desktop app's computer use
  on the Mac; check a lab PC can run it)?
- **Q5.2.5 Shape of the debug/smoke menu** (from Q5.2, approved: [plan](../roadmaps/smoke-automation.md)): extend the
  existing Debug menu, or a separate "Smoke" menu shown only with a flag? Proposed: a "Smoke"
  menu behind `HELAB_SMOKE=1`, so release users never see it.

## v0.0.7 scope (block 6)

- **Q6.2 Distributed results compute: what comes first?** (Postponed, below.) The roadmap
  already has the parts: the [headless runner](../roadmaps/headless-analysis.md) and
  [cross-machine result sharing](../roadmaps/network-runners-and-web.md#cross-machine-result-sharing).
  Options:
  - (a) One machine (e.g. the acquisition PC) runs a headless HeLab that computes chosen
    results as shots settle, and other HeLabs read its completed results, read-only.
  - (b) A HeLab sends a heavy job (e.g. Release time on 22.5 M rows, 15.5 min on a Mac) to a
    faster machine and gets the result back.
  - (c) Split one job across several machines or processes.

  Also: how results travel (over SSH from the computing machine, or files on the share beside
  `.helab-root`), and which machines take part. Proposed: (a) first, over SSH, with results
  keyed by data root and input snapshot. It pairs with the converter on the same machine.
  (b) follows on the same runner; (c) is not planned.

  **Postponed** (Tony, 2026-10-28): "postpone distributed compute build until we have a very
  good working tdc_autoconvert within helab".
- **Q6.3 The converter port's inputs.** Answered, 2026-10-28 (Tony in Chat):
  - Q6.3.1: "there are many raw d files in Volume/X that you can read for testing": the X share
    (`//…/X`, mounted at `/Volumes/192.168.137.1-4` on Tony's Mac). For example
    `20241107_RT_low_mod_occ_350_mus` (10,911 raw, 10,904 `_txy_forc`, small shots) and
    `2022_ghost_counts_debacle/20221123_ghost_counts_with_cut_1` (10 pairs, ~1.5 MB raw).
    Read-only, and outside pytest (tests never touch real data).
  - Q6.3.2: the goal is to replace MATLAB's `tdc_autoconvert` with HeLab, as a headless HeLab
    converter, and Live can also toggle auto-convert. Converted files are named
    `d_txy_helab_<N>.txy`. In the current build every HeLab-made TXY stays in HeLab's temp folder.
  - Still planning: no building until the goals are clear.
- **Q6.5 Implementation benchmark (spike).** (Decided, below.) Tony: "try build using few
  different packages and benchmark, how about GPU accelerated?". Goal: choose how the reconstruction runs. A pure-Python
  port of the MATLAB loop is the reference; each candidate must give the same output (event
  counts, 8 significant figures) on the X samples. Candidates: NumPy vectorised, Numba, Cython or
  Rust (PyO3), and GPU (CuPy on NVIDIA, PyTorch MPS or JAX on the Mac). Parsing, reconstruction
  and writing are timed separately, on small and large shots, on the Mac and the acquisition PC.
  Note on GPU: the matching is a greedy sequential pass over time-sorted pulses, and shots are
  small (~3k–100k pulses), so copying to the GPU may cost more than it saves. Text parsing and
  writing likely dominate. Proposed: go, as a spike on a floor whose only output is a results
  note and the benchmark script; and which GPUs do the lab PCs have?

  **Yes, benchmark first in a spike floor** (Tony, 2026-10-28), possibly one terminal agent per
  numerical package; confirm the parallelisation plan first. Test on the local Apple Silicon Mac
  for now. Lab machines vary: some have CUDA (version unknown), some only an Intel iGPU, so the
  conversion backend must stay easy to switch. Also measure whether conversion keeps up with raw
  files arriving at network speed (see Q6.9). More raw folders are a few levels down on X, an
  HDD over the network, so read it sparingly. MATLAB check (Side, 2026-10-28): R2025b runs headless on Tony's
  Mac (`matlab -nodisplay -batch`, ~5 s to start, core functions only). Both sample shots
  (2022 ghost counts `d1`, 2024 `20241107` `d1111`) are reproduced **byte for byte** by the 2019
  variant (`legacy/tdc_autoconverter`, `dlmwrite` precision 8); the 2023 variant writes 12–14 %
  fewer hits (the x1 dead time). So the port's bar can be byte-identical output.

  **Decided** (Tony, 2026-10-28): stages 1 and 2 build variants that reproduce the existing
  MATLAB converter's results, and the code stays adaptable so the detector parameters can be
  tweaked; later perhaps a parameter-space scan optimised on signals from real data. The
  builder and a reviewer write the reference first (the reviewer cross-checks, also against
  MATLAB run headless), then one builder per backend, all connected to the reviewer. Backends:
  NumPy, Numba, Cython/C, Rust (PyO3), Apple GPU (MLX); not Julia, PyTorch or JAX (packaging).
  Findings: [session notes](sessions/2026-10-28-claude-txy-converter-plan/findings.md).
- **Q6.6 Which TXY a folder uses when both `d_txy_forc*.txt` and HeLab's `d_txy_helab_*.txy`
  exist** (side by side on the acquisition PC, old archives re-converted with a better profile,
  folders where MATLAB missed shots). Options: (a) MATLAB's by default, HeLab's filling only the
  shots MATLAB lacks, with a per-folder "TXY from: MATLAB / HeLab (profile)" switch; (b) HeLab's
  whenever they exist; (c) both, as two datasets of the same folder, for comparing. Either way
  every dataset and saved result records its source (MATLAB, or HeLab's profile and version) so
  caches never mix them, and Folder details and each plot's source line say which is shown.
  Proposed: (a) now, (c) later as a comparison mode; the default flips to HeLab's after stage 5.
  **Decided** (Tony, 2026-10-29): offer all three, (a), (b) and (c), in the plot settings.
- **Q6.7 How other HeLabs get the acquisition PC's TXY** (Q6.2, as Tony framed it: the
  acquisition PC watches the raw files, converts them, maybe runs analysis; other HeLabs on the
  network fetch the TXY from its HeLab store). Options:
  - (a) it writes `d_txy_helab_<N>.txy` beside the raw files on the share, as MATLAB does, and
    other HeLabs read them as ordinary files;
  - (b) its HeLab serves its store read-only (HTTP or SSH), and other HeLabs fetch by data root
    and shot;
  - (c) other HeLabs open its store folder over SMB: no, SQLite over SMB isn't safe.

  Proposed: (a) once HeLab replaces MATLAB (it needs nothing new and works with HeLab closed);
  (b) later, for analysis results, which have no file of their own.
- **Q6.8 The Live auto-convert toggle.** (Answered, below.) Proposed: a per-folder switch in
  the Live controls, remembered like Don't auto-load, off by default. **Answered** (Tony, 2026-10-28): "show auto convert
  toggle after live is toggled". Later: configurations that turn on Live and auto-convert as soon
  as HeLab starts (a roadmap item, not v0.0.7's first step).
- **Q6.9 Store HeLab's TXY, or only cache it?** Tony: if conversion keeps up with raw files
  arriving at the network transfer limit, HeLab might never store TXY in the archives and keep
  them only in its local cache. Waits for the Q6.5 benchmark. Tony, 2026-10-28: "real
  experiments have one d every ~30s"; the target is converting faster than raw files cross the
  network, so other HeLabs read the raw files and convert them as they read, with no TXY stored.
  On X, TXY is 27–41 % of the raw size (2022 and 2024 folders), so the TXY archive is ~22–29 % of
  a folder; reading raw files moves 2.4–3.6× the bytes on a first, uncached load.
- **Q6.10 Detector profiles and the default variant.** Both MATLAB variants hard-code the old
  detector: channel map, one time sum (3200 bins) ± 200, v⊥ on both axes, a 36-row search; the
  2023 lab edit adds an x1 dead time of 0.5 µs (−12–14 % hits) and time sums 3390/3275 in T only.
  If those are the post-2023 detector's time sums, the 2019 converter may drop hits at the
  outer x edge and stretch X by ~6 % (untested; [notes](sessions/2026-10-28-claude-txy-converter-plan/findings.md)).
  Also: the ambiguous-x2 quirk (nearest kept, not rejected as the comment intends). Proposed:
  the constants become a named detector profile; the default reproduces the 2019 converter byte
  for byte; the 2023 edit and any corrected profile are separate, checked on their own; which
  shots came from which detector is Tony's to say. Tony, 2026-10-28: the MCP plates changed in ~2022 and in 2025
  (on X, the He3/He4 folders' `old_plates` end 2022-07 and `new_plates` start 2023-02); look into
  the x2 handling while building. Probe results (old vs new plates, MCP-measured time sums
  x 3367 / y 3294 bins in 2022-11) are in the notes. Detailed for Tony, 2026-10-29: profiles
  `matlab-2019` (exact), `matlab-2023-lab-edit`, and `plates-2017/2022/2025` (copies of
  `matlab-2019` until calibrated). Proposed: new conversions use `matlab-2019` until a plate
  profile is calibrated and approved, then the plate profile valid on the shot's date (the raw
  file's time, as D7 reads it), with a per-folder override; MATLAB's quirks stay only in
  `matlab-2019`. Needed from Tony: the plate swap dates (2017; ~2022, between 2022-07-29 and
  2023-02-04 on X; 2025) and whether the 2022-11 ghost-counts run was on the old or new plates.
  **Answered** (Tony, 2026-10-29): the default is `matlab-2019`; the 2022-11 ghost-counts run was
  on the new plates (so the ~2022 swap falls between 2022-07-29 and 2022-11-23, and the
  MCP-measured time sums x 3367 / y 3294 are the 2022 plates'); a plate profile may change every
  parameter we might want to calibrate (listed in the [plan](../roadmaps/txy-converter.md)).
  Swap dates (Tony, 2026-10-29): 2017-03-17 and 2025-06-18; the 2022 date is unknown. On X the
  last old-plate run is 2022-08-22 and the first named for the new plates is
  `20221103_bragg_beam_tests_new_plates`, so provisionally 2022-11-03 until a closer date is found.
- **Q6.11 Detector calibration in the converter plan.** Tony, 2026-10-28: the 2025 plates have
  not been calibrated yet; plan for calibrating. Proposed: a calibration stage after the
  byte-identical reference, built on D11's raw-pulse diagnostics (time sums from MCP pulses and
  by position, x−y sum difference, pulse spacing for ringing and dead time, hotspot and
  efficiency maps from dark counts and flat fields) plus a geometry check on known shapes
  (Momentum Bells halos: radius and roundness; BEC position). Its output is a versioned detector
  profile with a valid-from date and plate, recorded with every TXY HeLab makes. Questions:
  where is 2025 data; was the MCP channel recorded; can the lab take a calibration set (dark run,
  large thermal cloud, a halo, with the MCP channel on); where profiles live (proposed: built-in
  ones in the repo, the lab's in one shared file beside the data). **Answered** (Tony, 2026-10-28): profiles are JSON files; the
  2017, 2022 and 2025 plates' profiles are built into the app, which can import, export and
  tweak them; the 2025 profile is marked uncalibrated. The MCP diameter hasn't changed; there is
  no mask or grid. The file server with post-2025 data is offline for now; Tony will say when it
  is back. Still open: whether the lab can take a calibration set, and whether the MCP channel
  was recorded in 2025. Detailed for Tony, 2026-10-29: the 2017 and 2022 plates can probably be
  calibrated from data on X (2019–2021 halos; 2023 halos in `2020_Momentum_Bells/Full_S_RT`;
  the 2022-11 ghost counts with MCP pulses if on the right plates); only 2025 needs new data.
  Also open: when a profile counts as calibrated (proposed: halo roundness and radius within 1 %,
  time sums measured with their spread, a hotspot map) and who approves (proposed: Tony, from a
  calibration report HeLab shows before saving). **Answered** (Tony, 2026-10-29): with halos,
  calibrated means the parameters that maximise the correlation across halos (the back-to-back
  pair correlation); also hotspot maps and efficiency, by region, with the other parameters
  listed. Calibration data for the 2025 plates exists but isn't reachable now; meanwhile use the
  old data in X's `dld_output_cheerypicked` (2022 plates: `20221212_new_plates_halo_test_4`,
  2,423 shots; `20230130_new_plates_halo_3_halos`, 797; many 2023–2024 halo runs; none of those
  checked has MCP pulses). Tony approves calibrations (2026-10-29). Provisional calibrations
  from the data on X come after the converter is built (stage 3), not before; the halo runs are
  copied to `~/HeLab-samples/calib-v1/` for then. The 2025 data should be reachable within a few
  days.

## After the v0.0.6 release (not blocking)

### Q1.6 Lab numbers only Tony can give
- Q1.6.1: the detector QE (0.1 proposed), the trap frequencies and the trap's axial axis. They are
  used by BEC properties' QE checks and are amber "unconfirmed" in Settings → Lab parameters.
- Q1.6.2: the hot spots of the current detector, which become the "current detector" mask
  preset. Find them with Find hot spots on a flat field or an atom-free T window.
- Q1.6.3: how auto detection should find orders 0, ±1, ±2 in Transfer fractions (roadmap: "Tony
  to describe").

### Q1.7 Windows 3D scatter window flicker
On the Mac, the hidden QQuickWidget stops the main window from closing and reopening when the
first 3D scatter opens. Before turning the same fix on for the lab PCs, check (M1.8):
- whether the flicker happens there;
- whether the fix is safe on PCs that can't paint QtWebEngine.

### Q1.8 The tray / menu-bar icon for notifications
Shot trends' Notify during Live shows a system notification through a tray icon. Is the icon
acceptable, or should notifications use the status bar only?

### Q1.9 After the release (replaced by v0.0.7's focus, Q6.12; kept for the record)
1. Export with provenance, together with the analysis worker in the activity panel.
2. The `folder_cache.py` split (it should run alone).
3. The headless runner and CLI.
4. The TXY converter port (needs sample raw and `_txy_forc` files from Tony).
5. The DLD port's D13 (halo centring per shot).
6. The `--upgrade` lock refresh (python-dateutil 3.0), in its own CI run (A7.2).

## Open decisions inside plans

Plans keep their own design questions; they are indexed here so none is missed (proposed after
the docs audit; Tony, 2026-10-29: "keep fixing docs as proposed"). When work on a plan starts, the ones
that block it become Q items here, as the converter's did (Q6.6–Q6.11).

- [DLD front panel port](../roadmaps/dld-front-panel-port.md#open-decisions): 33 (some overlap
  Q1.6).
- [Analysis job runner](../roadmaps/analysis-job-runner.md#open-decisions): 7.
- [Network runners and web](../roadmaps/network-runners-and-web.md#open-decisions): 7.
- [Live monitoring](../roadmaps/live-monitoring.md#open-decisions): 6.
- [Headless analysis](../roadmaps/headless-analysis.md#open-decisions): 5.
- [Run comparison and batch](../roadmaps/run-comparison-and-batch.md#open-decisions): 5.
- 4 each: [agent workflow](../roadmaps/agent-workflow.md),
  [analysis workflow](../roadmaps/analysis-workflow.md#open-decisions),
  [cache-only browsing](../roadmaps/cache-only-browsing.md#open-decisions),
  [presets and workspaces](../roadmaps/presets-and-workspaces.md#open-decisions),
  [refactoring](../roadmaps/refactoring.md#open-decisions),
  [result caching](../roadmaps/result-caching.md#open-decisions).
- [App updates](../roadmaps/app-updates.md#open-decisions): 3.
- In prose: [quality control and repair](../roadmaps/quality-control-and-repair.md#acceptance-and-open-decisions),
  [reproducible workflows](../roadmaps/reproducible-workflows.md#dependencies-and-open-decisions).
- [TXY converter](../roadmaps/txy-converter.md#open-decisions): already Q6.6–Q6.11, plus two
  smaller ones there.
