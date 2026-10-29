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
  writing `d_txy_helab_<N>.txy` (now `d_txy_helab_<tag>_<N>.txt`, Q18.4) beside the raw files is an
  option the user turns on per folder (with auto-convert at launch). This amends Q8.2 (HeLab
  still writes nothing else to source folders).
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

Tony's answers on v0.0.7's converter scope, 2026-10-28/29 (block 6). His wording is in the
[converter memory](memory/results/txy-converter.md); the design is in the
[plan](../roadmaps/txy-converter.md#decided). The parts still open are under block 6 below.

- **Q6.3 The converter's inputs:** raw files on X for testing (read-only, outside pytest); the goal
  is to replace `tdc_autoconvert` with a headless HeLab converter, plus Live's auto-convert toggle.
- **Q6.5 Benchmark first:** a reference reproducing MATLAB byte for byte, then one floor per
  backend; done as stages 1 and 2.
- **Q6.6 Which TXY a folder uses:** offer all three; built as the four source modes of Q18.2.
- **Q6.8 The auto-convert toggle** shows once Live is on (built, `6454b4a`).
- **Q6.10 Detector profiles** (most of it): the default is `matlab-2019`; a plate profile may
  change every parameter we might calibrate; the 2022-11 ghost counts were on the new plates; plate
  swaps 2017-03-17 and 2025-06-18.
- **Q6.11 Calibration** (most of it): profiles are JSON; the 2017, 2022 and 2025 plates' profiles
  are built in (2025 uncalibrated), with import, export and tweak; calibrated means the parameters
  that maximise the back-to-back correlation across halos, plus hotspot and efficiency maps; Tony
  approves each; provisional calibrations from X's data come in stage 3.

Tony's answers in Chat, 2026-10-29, on converter stages 1–4 and their follow-ups (blocks 10–18).
Settled design: [converter memory](memory/results/txy-converter.md); mechanics:
[converter.md](architecture/converter.md); plan: [txy-converter](../roadmaps/txy-converter.md).

- **Q10.1 The third MATLAB variant:** "no, ignore those": no built-in profile; the two 2022-07
  shots stay proven exceptions in `dev/txy/reference_exceptions.py`.
- **Q10.2 A raw file with no rows** is never skipped silently: OK. As built since Q18.5 it waits
  20 s and is marked damaged; Q23.3 asks to confirm that.
- **Q10.3 A shot with no hits** gives a 0-byte HeLab TXY (A10.5): OK, and the GUI warns about it
  (A17.1, `62d156e`).
- **Q11.1** numba's cache in the cache folder: superseded by Q18.1.
- **Q11.2 Backends:** NumPy the default, Cython the optional one; the app ships NumPy, Cython and
  the reference (A9.1, `134e2ec`).
- **Q11.3** `reference` stays in the build, and every backend's code stays in the repo.
- **Q12.2, Q12.5, Q12.7** were settled as Q18.4, Q18.5 and Q18.6.
- **Q14.1, Q14.3** were settled by Q18.2 (four source modes, a profile chosen by its tag).
  **Q14.5** became the caching rethink (block 19; Q19.3 is still open).
- **Q15.1** became a check in the running app (M18.1, merged into M23.2); the list it asked about
  became one `live_launch_folder` (Q18.3). **Q15.2** was superseded by Q18.3.
- **Q16.1** no `setup.py` extra for the fast backends (`native/build.py` serves developers and CI).
- **Q16.2 CI time:** (b), two pytest groups on every OS (A17.2, `874fd2b`).
- **Q18.1** numba's cache goes in HeLab's temp folder, for developers trying numba (`874fd2b`).
- **Q18.2** four TXY source modes: helab-priority (the default), matlab-priority, helab-only,
  matlab-only (`c718c71`; converter.md "TXY sources").
- **Q18.3** Live runs in one folder; one launch folder, opened alone; Live on collapses the left
  panel (`dbf80e4`; [live](architecture/live.md)).
- **Q18.4 Tagged names** `d_txy_helab_<tag>_<N>.txt`, tags frozen once used, no metadata beside the
  raw files ("agree with your suggestions"; `26a2ade`; AGENTS.md's write rule).
- **Q18.5 Damaged raw files:** unchanged for 20 s and still failing the format checks ("damaged
  timeout 20s").
- **Q18.6** keep the temporary name and rename, and the `.partial` cleanup ("keep partial"; on
  AGENTS.md's housekeeping list).

Tony's answers on caching after the converter, 2026-10-29 (blocks 19 and 22). **No cache code
until his explicit go** (A19.1 and A19.2 included). Plan: [caching v2](../roadmaps/caching-v2.md);
settled design: [caching memory](memory/results/caching-v2.md).

- **Q19.4** a fresh `store-v4`, with a one-time choice for store-v3: keep using it (read for what
  v4 lacks), clear it (asked) or ignore it.
- **Q19.9 Cache the raw pulses** ("plan to move on to caching the raw d files"): a raw layer per
  raw file and TXY layers per tag. Its premise, that a raw layer costs about what TXY caching costs
  now, was corrected by the [design note](sessions/2026-10-29-claude-caching-audit/store-v4-design.md):
  a raw layer is ≈ 1.8× an `m19v1` TXY layer with Q22.7's proposed codec (1.9× at zstd 5), and
  raw plus one tag ≈ 2.7× today's store (2.8×); the plan's "Size" gives the settings.
- **Q19.10** the raw layer is filled wherever HeLab caches a folder today (loads of the selected
  folder, Live's saves, presets and reopened plots, auto-convert).
- **Q22.1–Q22.4, Q22.6, Q22.8–Q22.10 as proposed:** a background `raw_fill` job; HeLab layers keyed
  by profile hash with tags as names; behave as Keep until the store-v3 choice is made; import the
  user's own v3 state once; raw layers whose file is gone, or from an older parser, kept and
  labelled; offline, HeLab layers made from the raw layer; no "clear this tag" action; `%.17g`
  text for full-precision tags.
- **Q22.5** a raw file overwritten after it was read is read again and re-converted, with a big
  warning (it only happens when the TDC is misconfigured); per-shot plots get a shot-index axis
  (A22.1).
- **Q22.11 Cache policy:** the raw layer and the selected TXY versions together; a global default
  to cache raw files; a per-folder source priority whose TXY layer is cached too.

## Process lessons and v0.0.7's gate (block 24)

From the overnight build ([mandate](sessions/2026-10-29-claude-v0.0.7-overnight/mandate.md)) and
the [planning-docs audit 2](sessions/2026-10-29-claude-docs-audit-2/planning.md), 2026-10-29.

- **Q24.1 Codex Reviewers can't run unattended on floors.** **Tony, 2026-10-29: OK** (Claude
  Reviewers for unattended runs, Codex when he is present). At ~01:50 the Codex Reviewer stalled
  on its first approval prompt and CoCo replaced it with a Claude Reviewer. Codex asks approval
  even for `maestri list`; floors are untrusted in `~/.codex/config.toml`; and the compound
  `cd … && …` commands agents run don't match its allow rules. Options: (a) configure Codex for
  floors (trust the floors folder, allow rules that match); (b) Claude Reviewers for unattended
  runs, Codex when Tony is present. Proposed: (b).
- **Q24.2 "Supervised runs" as a documented mode?** On 2026-10-29 Tony delegated approvals to
  Side within a written mandate (what Side may approve, what is never done, a decision log).
  Proposed: yes, written into the workflow guide and modelled on that
  [mandate](sessions/2026-10-29-claude-v0.0.7-overnight/mandate.md). **Tony, 2026-10-29: yes, and only Tony starts it** ("ask me to start the mandate mode"); written up in the setup guide, roles later.
- **Q24.3 Which converter checks join v0.0.7's smoke pass?** **Tony, 2026-10-29: "live convert
  and plot update"** (M1.9). The pass (M1.1–M1.8) has no converter
  step, and MANUAL_TODO's converter items don't gate a release. Proposed: an M1.9 "Converter" step
  on the Mac and a lab PC: Live auto-convert on a sample folder (M15.1's core), `helab convert
  --watch --once` on a sample, a plot of the converted data, and the TXY source choice (M23.1,
  M14.1). The rest (M12.1, M15.1 in full at the acquisition PC, M16.1 on the Sandy Bridge PC) stay
  lab validation. What else v0.0.7 needs before its PR is the roadmap's
  [Release v0.0.7](../roadmaps/_readme.md#now-v007) item.
- **Q24.4 Land a floor only when its branch's latest CI is green on all three OSes?** Decided
  overnight (mandate, 06:20) after helab-core landed with Windows failing. Today's docs fixes
  write it as a landing condition (AGENTS.md's Landing line, the workflow guide, setup §6), so it
  needs Tony's confirmation. Proposed: yes (every job, checked by run ID). **Tony, 2026-10-29: OK.**

## Converter stage 4, HeLab core (block 12)

From the `agent/txy-helab-core` handoff (`sessions/2026-10-29-claude-txy-helab-core/handoff.md`),
2026-10-29. These were **decided by Side overnight, for Tony to confirm, and built that way**. Tony
hasn't answered them yet (2026-10-29), so they stay open. (Q12.2, Q12.5 and Q12.7 were settled as
Q18.4–Q18.6, above.)

- **Q12.1** A folder with no data root, asked for `cache`, converts to the temp folder (follows "no
  data root, no disk cache"; `convert_plan.fallback` says why). Built. **Tony, 2026-10-29: yes.**
- **Q12.3** HeLab's TXY in the cache folder are outside the 8 GB budget and no housekeeping removes
  them. The same question as Q19.2: answer it there. **Tony, 2026-10-29: no; converted TXY in the
  cache get their own budget, separate from the 8 GB dataset budget; TXY written beside the raw
  files have no limit** (they are data in the source folder; HeLab never removes them). Its default
  size and Make room behaviour come with the caching work (no cache code until Tony's go).
- **Q12.4** `helab convert --output beside` writes beside for that run without the folder's flag and
  saves no flag. AGENTS.md's write rule already says so, so a rule rests on this answer. **Tony, 2026-10-29: OK, a typed command overrides the app's settings.**
- **Q12.6** (an idea, not built) A manual **Convert anyway** for a file stuck waiting: the user's
  choice to convert it as it is (never one modified within the settle age), recorded in the
  provenance; a request field (e.g. `force_shots`) is the seam.

## Converter stage 4, UI and Live (blocks 14, 15)

From the `agent/txy-ui` and `agent/txy-live` handoffs (`sessions/2026-10-29-claude-txy-{ui,live}/handoff.md`).

- **Q14.2 Save a plot's TXY source and profile with presets, arrangements and reopened plots?**
  Not built (a format change in `analysis/presets.py`); a reopened plot starts "As the folder's
  tab" (Q23.4 is the same question). Proposed: save them once `analysis/presets.py` changes format
  for something else.
- **Q14.4 Count HeLab's TXY in a folder's status?** Today status and counts come from MATLAB's TXY
  alone; proposed: count current HeLab TXY of the tab's tag once scans can see HeLab's folders
  cheaply (A23.1 waits for this). Caching v2's stage 5 would make raw files drive status.
- **Q15.3 The low-count threshold** `convert_low_hits`: default 100 hits, 0 off, once per shot.
  Alternatives: a rate like MATLAB's 700 Hz (needs `t_max` in `shot_converted`); per-folder
  thresholds. A low shot can notify twice (Shot trends' Notify during Live is a separate rule).
  Tony, 2026-10-29: later.

## Caching after the converter (block 19; [audit](sessions/2026-10-29-claude-caching-audit/audit.md))

Tony asked (Q14.5) to rethink caching now that HeLab converts raw files; Q19.4, Q19.9 and Q19.10
are decided (above), and the plan is [caching v2](../roadmaps/caching-v2.md). **Tony, 2026-10-29:
keep planning; no cache code until he gives an explicit go** (A19.1 and A19.2 included).

- **Q19.1 Keep HeLab's own TXY files once loads convert on read?** (a) no: only beside and export;
  (b) yes, as a cache in the budget; (c) yes, as now. Proposed: (a), at stage 2.
- **Q19.2 Until then, does `<cache>/converted-txy` count toward the 8 GB budget?** (Also Q12.3.)
  **Answered by Tony under Q12.3, 2026-10-29: a separate budget; beside TXY unlimited.**
  Today it is outside the budget and no housekeeping removes it; Settings → Cache shows its size
  with a Clear (asked first). Proposed: yes, counted and shown; Make room may offer it, always
  asked (no AGENTS.md change).
- **Q19.3 Disk-cache every TXY source (Q14.5)?** Proposed: yes, as layers (no duplication), stage 1.
- **Q19.5 Does Don't cache this folder also stop HeLab's TXY going to the cache folder?** Proposed:
  yes; such folders convert to temp, like folders without a data root.
- **Q19.6 Precision of data converted on read:** 8 significant figures like the TXY text (T ≈ 0.4 s
  → 10 ns), or full float64? Proposed (as Q19.9's proposal and Q22.10 imply): binary always (text
  only beside the raw files or on export); `m19v1` rounds to 8 significant figures so it matches
  its text exactly; newer tags keep full float64. The plan marks this proposed.
- **Q19.7 Drop the temp output setting after stage 2?** Proposed: yes.
- **Q19.8 Temp-folder TXY of folders without a data root:** cleared by the user only (proposed),
  or deleted after N days at startup (a new housekeeping line)?

## Store-v4 design (block 22; [design note](sessions/2026-10-29-claude-caching-audit/store-v4-design.md))

Planning only (no cache code until Tony's go). Tony answered the rest of the block (above).

- **Q22.7 The disk budget:** keep 8 GB (proposed; Settings shows the split) or raise the default
  (e.g. 20 GB)? Tony asked first to look harder at raw compression. Measured on the 309-shot
  sample set (13.7 M pulses, raw text 15.8 B/pulse): int64 time deltas + int8 channels, Blosc zstd
  level 9 with byte shuffle, **27.5 MB (2.0 B/pulse, 7.9×)**, the best of ten variants (zstd 5:
  29.5; bitshuffle, 32-bit deltas or per-channel streams: no better, 29–38; lz4hc: 38.4 MB but
  4.9 GB/s decoding vs ~1.9). An estimate for independent deltas is ~2.2 B/pulse, so generic
  compression is at its floor. The only big gain left would be a lossless codec that knows hit
  structure (corner pulses of a hit are correlated), which ties the raw layer to the converter:
  not proposed. Proposed: zstd 9 + byte shuffle on int64 deltas; raw layer ≈ 1.8× a TXY layer.

## Converter follow-ups as built (block 23)

From the `agent/txy-followups` handoff (`sessions/2026-10-29-claude-txy-followups/handoff.md`),
landed `c718c71`. Q15.2 is superseded by Q18.3 (built), Q14.3 settled by Q18.2 (a profile by its tag),
Q12.7 confirmed as Q18.6 (the patterns now tagged).

- **Q23.1 Tags for the two built-ins Tony didn't name**: `matlab-2023-lab-edit` → `m23v1`,
  `plates-2017` → `p17v1` (CoCo agreed for now). Frozen once released: confirm before v0.0.7 ships.
- **Q23.2 "File explorer panel" = the whole left panel** (tabs, summary, Live line, Folder details),
  collapsed while Live watches. Alternative: collapse only the folder tree, keeping the Live line and
  Folder details visible. Proposed: as built.
- **Q23.3 No rows waits 20 s** before it is damaged (was: unconvertible once settled, Q10.2).
  Proposed: keep (one rule for all three checks).
- **Q23.4 A plot's profile choice isn't saved** with presets, arrangements or reopened plots: a
  reopened plot starts "As the folder's tab". The same question as Q14.2: answer it there.
- **Q23.5 The Live line turns amber for no-hit shots** (the whole line, which otherwise means
  "stopped"). Alternative: amber only in Folder details. Proposed: as built.
- **Q23.6 A beside TXY from another computer with a colliding `u` tag** would be taken as current (no
  record there). Proposed: accept (≈1e-6), or later write the hash into the name.
- **Q23.7 `helab convert --once` and damaged files**: one look has no "first seen", so `--once` goes
  by the mtime alone (≥ 20 s; its settle rule is 60 s by the mtime alone too). Alternative: `--once`
  never reports damaged. Proposed: as built.

## Post-2025 plates (block 25; [investigation](sessions/2026-10-29-claude-txy-2025-plates/investigation.md))

Provisional analysis, nothing applied to HeLab. **The corner cables were swapped between
2026-06-27 and 2026-07-21** (x1↔x2, y1↔y2): every image since July is rotated 180° against June
and all earlier data (reflection delays per delay-line end, background images r = 0.984 only when
rotated, and the x1 ringing excess moved from channel 0 to channel 1; Side re-checked the last).

- **Q25.1 How should HeLab handle the swap?** Options: (a) a `plates-2025` profile pair split by
  date (June: today's channel map; from July: x1↔x2, y1↔y2 swapped), so HeLab's own TXY come out
  unrotated; plus a per-folder "rotated 180°" note for MATLAB's July+ TXY; (b) swap the cables
  back in the lab and treat July–October as rotated. Proposed: (a) now, and (b) if the swap was
  accidental (M25.1).
- **Q25.2 Channel 7:** random (~1.3 per shot, Poisson), absent 2019 – Jan 2025, with corner pulses
  within 10 ns 95 % of the time; likely a high-threshold transient (an MCP/HV micro-discharge or
  whatever is on input 7). Conversion is unaffected (byte-identical without it). Proposed: ignore
  it in every profile; find out what is on input 7 (M25.2).
- **Q25.3 Another converter on the TDC PC:** some July `d_txy_forc` were written by the 2023 lab
  edit (7–29 % fewer hits), and `20260722-tight-trap-1000Hzsampling/d_txy_forc183.txt` is corrupted
  by two writers. Proposed: find and stop the second writer (M25.3); HeLab's checker flags such
  files; HeLab's own conversion avoids both problems.
- **Q25.4 The per-shot logs' "posixtime" is local time stored as UTC** (10 h ahead). Proposed: HeLab
  reads it as local time when it uses these logs, and the lab fixes the logger.

The provisional `plates-2025` numbers (x−y sum difference 121 ± 0.5 bins; active area round to
7 %, radius 40.0 ± 0.5 mm at `matlab-2019` scale; candidate v⊥ x 5.088e5, y 5.444e5 m/s; hot spots
at (15.9, 1.4) and (32.3, 1.2) mm) wait for stage 3 and Tony's approval. Keep `matlab-2019`'s
matching settings (a wider window adds mostly random combinations; a converter dead time loses real
atoms). The collisions halo can't calibrate the plates (elliptical, no measurable back-to-back
peak): a free-space halo run with raw files kept is needed (M25.4).

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

Q6.3, Q6.5, Q6.6 and Q6.8, and most of Q6.10 and Q6.11, are decided (above); the parts still open
are here.

- **Q6.2 Distributed results compute: what comes first?** **Postponed** (Tony, 2026-10-28):
  "postpone distributed compute build until we have a very good working tdc_autoconvert within
  helab". The roadmap already has the parts: the [headless runner](../roadmaps/headless-analysis.md)
  and [cross-machine result sharing](../roadmaps/network-runners-and-web.md#cross-machine-result-sharing).
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
- **Q6.7 How other HeLabs get the acquisition PC's TXY** (Q6.2, as Tony framed it: the
  acquisition PC watches the raw files, converts them, maybe runs analysis; other HeLabs on the
  network fetch the TXY from its HeLab store). Options:
  - (a) it writes `d_txy_helab_<tag>_<N>.txt` beside the raw files on the share, as MATLAB does,
    and other HeLabs read them as ordinary files (built as a per-folder option, Q9.7);
  - (b) its HeLab serves its store read-only (HTTP or SSH), and other HeLabs fetch by data root
    and shot;
  - (c) other HeLabs open its store folder over SMB: no, SQLite over SMB isn't safe.

  Proposed: (a) once HeLab replaces MATLAB (it needs nothing new and works with HeLab closed);
  (b) later, for analysis results, which have no file of their own.
- **Q6.9 Store HeLab's TXY, or only cache it?** Tony: if conversion keeps up with raw files
  arriving at the network transfer limit, HeLab might never store TXY in the archives and keep
  them only in its local cache. The Q6.5 benchmark is done (2026-10-29: on this Mac every backend
  but the reference converts faster than gigabit delivers raw files, numpy on one core included;
  the lab PCs are untimed, M11.1). Tony, 2026-10-28: "real experiments have one d every ~30s"; the
  target is converting faster than raw files cross the network, so other HeLabs read the raw files
  and convert them as they read, with no TXY stored. On X, TXY is 27–41 % of the raw size (2022
  and 2024 folders), so the TXY archive is ~22–29 % of a folder; reading raw files moves 2.4–3.6×
  the bytes on a first, uncached load. Caching v2 answers it in effect (Q19.9: cache the raw
  files; Q19.1, to decide: HeLab writes TXY only beside the raw files or on export). Proposed:
  close Q6.9 as answered by caching v2, with Q19.1 still to decide.
- **Q6.10 (still open) The ~2022 plate swap date.** On X the last old-plate run is 2022-08-22 and
  the first named for the new plates is `20221103_bragg_beam_tests_new_plates`, so 2022-11-03
  provisionally until a closer date is found.
- **Q6.11 (still open) Calibration data:** can the lab take a calibration set (a dark run, a large
  thermal cloud, a halo, with the MCP channel on), and was the MCP channel recorded in 2025? The
  2025 plates' calibration data exists but wasn't reachable on 2026-10-29 (expected within days).

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
- [Live monitoring](../roadmaps/live-monitoring.md#open-decisions): 3.
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
- [TXY converter](../roadmaps/txy-converter.md#open-decisions): Q items (Q6.7, Q6.9–Q6.11, block
  12, Q14.2, Q14.4, Q15.3, block 23), plus one smaller question there.
- [Caching v2](../roadmaps/caching-v2.md#open-decisions): Q items (Q19.1–Q19.3, Q19.5–Q19.8,
  Q22.7); its design is in the store-v4 design note.
