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

Cleared at the v0.0.7a1 tidy-up (2026-10-31) where each was recorded in memory, an architecture file,
the roadmap or a plan, or was superseded or one-off; these two aren't recorded there yet:

- **Q5.1** the smoke pass runs on Sonnet 5.5 (it drove both runs so far); Haiku stays untried.
- **Q30.4** with the disk cache off this session, Settings › Cache doesn't list the temp folder's
  converted TXY: "ok", left for caching v2.

## Quick Fixes 7 (block 38)

From Quick Fixes 7's [handoff](sessions/2026-10-31-claude-quick-fixes-7/handoff.md) (Rivet on Ground,
Codex's review of PR #10, six rounds; detail in its `notes.md`).

- **Q38.1** Beside conversion on a file system with neither hard links nor a no-replace rename
  (`txy.write_atomic` refuses rather than risk replacing a file: `c194f37`). (a) Refuse as built: the
  run fails with the reason, auto-convert stops (amber line, Retry), Live goes on, nothing is written.
  (b) Per shot: `shot_unconvertible` with the reason, not tried again while the raw file is unchanged, as
  for a path too long. (c) Fall back to HeLab's cache or temp folder for that run, saying so in the plan
  (as `convert_plan`'s `fallback` does when the folder's flag is off). Proposed: (a); (b) or (c) only if
  M38.1 shows the lab share needs it (macOS FAT and Linux's local file systems work; Windows refuses an
  existing name itself).
- **Q38.2** Under HeLab priority, should Live switch a shot held from MATLAB's TXY to a HeLab TXY converted
  during Live (read it again as a changed shot, like a HeLab-held shot converted again)? As built
  (`fefe6ab`), it keeps MATLAB's until the folder's next load (Refresh, reopening, a restart). Proposed:
  no, keep it (no mismatch, no surprise rereads during a run; the next load takes HeLab's).
- **Q38.3** (wording) After switching to HeLab only, Folder details' load line counts the shots it leaves
  out (only MATLAB's TXY) as "N files removed", though no file went (`924109a`). Proposed: "N left out
  (TXY source)", apart from files really gone (a `load_counts` key and
  `FolderExplorer.load_count_details`).

## UI polish (block 36)

From the UI polish floor's [handoff](sessions/2026-10-30-claude-ui-polish/handoff.md) and Ibis's
[review](sessions/2026-10-30-claude-ui-polish/review.md) (landed `c104502`).

- **Q36.2** (v0.0.8, Tony) Settings › General's temp folder row says a change applies at the next start:
  offer to restart, or apply it live like the cache folder's move? Proposed: leave it (rarely changed).
- **Q36.3** The settings panel's least width is a fixed 250 px (nothing cut at macOS's default font; a
  row may be cut below 320 px on a wider font until the panel is widened). Never cut on any font instead:
  `max(250, min(the contents' least width, 320))`, but then a wider font can't go below 320. Proposed: keep
  250 and look on a lab PC (M36.1).

## Converter stage 4, HeLab core (block 12)

From the `agent/txy-helab-core` handoff (`sessions/2026-10-29-claude-txy-helab-core/handoff.md`).
Tony answered Q12.1, Q12.3 and Q12.4 on 2026-10-29 (Recently decided); Q12.2, Q12.5 and Q12.7 were
settled as Q18.4–Q18.6.

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

Tony asked (Q14.5) to rethink caching now that HeLab converts raw files; the plan is
[caching v2](../roadmaps/caching-v2.md), and the rest of blocks 19 and 22 is decided (Recently
decided). **Tony, 2026-10-29: keep planning; no cache code until he gives an explicit go** (A19.1
and A19.2 included).

- **Q19.1 Keep HeLab's own TXY files once loads convert on read?** (a) no: only beside and export;
  (b) yes, as a cache in the budget; (c) yes, as now. Proposed: (a), at stage 2.
  **Tony, 2026-10-29: "default no, but … we need to keep options open"**: for a bridging time
  HeLab writes TXY beside the raw files (the per-folder option stays), and raw files may be local
  or on remote servers, "so we might still want txy caching?" Reply sent in Chat: the store's TXY
  layers are that cache (binary, local, in the budget, made once per profile), so remote raw
  files load from the layer without the share; the text output to HeLab's folders stays as a
  non-default option until he drops it. To confirm.

## Converter follow-ups as built (block 23)

From the `agent/txy-followups` handoff (`sessions/2026-10-29-claude-txy-followups/handoff.md`),
landed `c718c71`. Q15.2 is superseded by Q18.3 (built), Q14.3 settled by Q18.2 (a profile by its tag),
Q12.7 confirmed as Q18.6 (the patterns now tagged).

- **Q23.2 "File explorer panel" = the whole left panel** (tabs, summary, Live line, Folder details),
  collapsed while Live watches. Alternative: collapse only the folder tree, keeping the Live line and
  Folder details visible. Proposed: as built.
- **Q23.3 No rows waits 20 s** before it is damaged (was: unconvertible once settled, Q10.2).
  Proposed: keep (one rule for all three checks).
- **Q23.4 A plot's profile choice isn't saved** with presets, arrangements or reopened plots: a
  reopened plot starts "As the folder's tab". The same question as Q14.2: answer it there.
- **Q23.5 The Live line turns amber for no-hit shots** (the whole line, which otherwise means
  "stopped"). Alternative: amber only in Folder details. Proposed: as built.

## Versions across machines (block 27)

Tony asked (2026-10-29) how robust HeLab is when the acquisition PC runs an older frozen build, his
laptop a source build and other PCs other versions. Checked: build info (version, commit,
modified) in About, `--version` and every log; an older HeLab opens a store of a **newer layout**
read-only (v0.0.6a1 and v0.0.7 share layout 3, so 0.0.6a1 opens v0.0.7's store writable: M1.10);
beside TXY are byte-identical across versions (frozen tags; another calibration is another tag);
profiles carry a schema; settings fall back to defaults. Tony: "3. fine, our TXY carry a converter
tag"; the marker is JSON with unknown fields ignored, so metadata can be added without a version
bump. Q27.1–Q27.5 are decided (Recently decided).

## Caching v2 readiness (block 28; [review](sessions/2026-10-29-claude-caching-v2-readiness/readiness.md))

Tony asked (2026-10-29) whether caching v2 / store-v4 can be built unattended (mandate mode). The
review: ready for stages 0–1 after these answers and a few design fixes; stage 2 in a later run.

- **Q28.1 The go:** which stages? Proposed: stage 0 (A19.1, A19.2 with Q26.2's floor) and stage 1
  (the raw layer, store-v4's core, the read-only store-v3 reader, the user-state import) only.

- **Q28.3 Behind a switch:** store-v4 drops `datasets`, and the TXY layers replacing it come only in
  stage 2, so stage 1 as the live store would stop disk caching of folders. Proposed: build
  store-v4 behind a switch that stays off until stage 2 and Tony's go.
- **Q28.4 Provenance in stage 1's schema** (Q27.2): every row records a `made_by` (HeLab version,
  commit, modified, machine, Python/NumPy/SciPy); a machine is a random id in the app folder plus
  the hostname. Proposed: yes.
- **Q28.5 Make room and store-v3:** MATLAB's TXY layers and layers cached without raw files are not
  rebuildable, so Make room treats them like data; under Keep, a large store-v3 counts in the
  budget and Make room can't free it. Proposed: Make room offers "Clear store-v3…" (asked first).
- **Q28.6 The "big warning"** for an overwritten raw file (Q22.5). Proposed: a system notification
  once per shot per session, plus a Folder details line and a log line.

## Post-2025 plates (block 25; [investigation](sessions/2026-10-29-claude-txy-2025-plates/investigation.md))

Provisional analysis, nothing applied to HeLab; Q25.1, Q25.3 and Q25.5 are decided (Recently decided). **Tony, 2026-10-29: X is still being transferred
(more folders to come), so every finding here is provisional** and is re-checked when the
transfer completes. **The corner cables were swapped between
2026-06-27 and 2026-07-21** (x1↔x2, y1↔y2): every image since July is rotated 180° against June
and all earlier data (reflection delays per delay-line end, background images r = 0.984 only when
rotated, and the x1 ringing excess moved from channel 0 to channel 1; Side re-checked the last).

- **Q25.2 Channel 7:** random (~1.3 per shot, Poisson), absent 2019 – Jan 2025, with corner pulses
  within 10 ns 95 % of the time; likely a high-threshold transient (an MCP/HV micro-discharge or
  whatever is on input 7). Conversion is unaffected (byte-identical without it). Proposed: ignore
  it in every profile; find out what is on input 7 (M25.2). Tony asked to investigate further
  (`channel7.md`): every channel-7 pulse starts a stereotyped **burst** (~23 corner pulses within
  ±1 µs, an echo train ringing from the physical x1 end); channel 7 catches only the largest
  bursts, and its share fell (June 4 %, July 1.7 %, September 0 %) while the bursts stayed at 6–8 Hz
  in every period (2023–24 runs: 0.2–0.6 Hz; 2022-11 ghost-count runs: 4.5 Hz). Most likely input 7
  is wired to a line that sees these events (an MCP/HV monitor or pick-off, a spare amplifier
  output, an unterminated cable) with a drifting threshold. The (−6.6, −10.3) mm "spot" is an
  artefact of the burst's fixed timing.
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
- [TXY converter](../roadmaps/txy-converter.md#open-decisions): Q items (Q6.7, Q6.9–Q6.11, Q12.6,
  Q14.2, Q14.4, Q15.3, block 23, Q25.2, Q25.4), plus one smaller question there.
- [Caching v2](../roadmaps/caching-v2.md#open-decisions): Q items (Q19.1 to confirm, Q27.3, block
  28); its design is in the store-v4 design note.
