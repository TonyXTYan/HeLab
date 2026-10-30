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
  **Q14.5** became the caching rethink (block 19; Q19.3 decided: yes, as layers).
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
  a raw layer is ≈ 1.8× an `m19v1` TXY layer with Q22.7's codec (decided) (1.9× at zstd 5), and
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
- **Q22.7** keep the 8 GB disk budget and the raw codec (zstd 9 + byte shuffle on int64 deltas);
  "but let's be OS aware" (Q26.1).
- **Q19.2** = Q12.3: HeLab's converted TXY in the cache get their own budget, separate from the 8 GB
  dataset budget; beside TXY unlimited; its size and Make room come with caching v2.
- **Q19.3** yes: each TXY source a plot uses is cached as its own layer, as it is used ("which
  should be rare anyways"); identical profiles share one layer.
- **Q19.5** yes: Don't cache this folder also keeps HeLab's TXY out of the cache folder (they go to
  temp, like folders without a data root). Not built yet: Q27.4.
- **Q19.6** as proposed: binary always (text only beside the raw files or on export); `m19v1`
  rounds to 8 significant figures, newer tags keep full float64.
- **Q19.7** no: keep the temp folder and the temp output ("for future analysis scratch dumps and
  temp storage for new features").
- **Q19.8** no JSON per TXY file; "an index to store the hash table from temp dir to real dir is
  fine" (Q26.2). Cleanup stays the user's (Settings › Cache's Clear, asked first).
- **Q26.1 Byte units by OS**, with GiB labels ("use GiB labels for binary so it's clear"): disk
  sizes and rates SI on macOS and Linux, powers of 1024 labelled KiB/MiB/GiB on Windows; RAM in GiB
  on every OS; defaults follow (8 GB / 8 GiB disk budget, minimums 1 GB / 1 GiB, RAM minimum
  1 GiB); one helper `byte_size(n, kind)`. AGENTS.md's units rule and `cache-store.md` change with
  the code. A26.1, to a floor when convenient ("ask one of the floors to do it when convenient").
- **Q26.2** ("26.2 ok"): one `converted-txy/index.sqlite` (folders and shots tables) replaces
  `folder.json` and the per-shot `.json` records, before v0.0.7's release; a small floor. The design
  is in [converter](architecture/converter.md#where-files-go).

Tony in Chat, 2026-10-29, on the overnight lessons (block 24), the converter core (block 12), the
post-2025 plates (block 25) and versions (block 27):

- **Q24.1** Claude Reviewers for unattended runs, Codex only while Tony is at the screen.
- **Q24.2** supervised runs (mandate mode) are a documented mode, and only Tony starts one ("ask me
  to start the mandate mode"; [setup](maestri-setup.md#supervised-runs-mandate-mode)).
- **Q24.3** the smoke pass gains "live convert and plot update" (M1.9).
- **Q24.4** a floor lands only when its branch's latest CI is green on all three OSes (every job,
  checked by run ID).
- **Q12.1** a folder with no data root, asked for `cache`, converts to the temp folder.
- **Q12.3** converted TXY in the cache get their own budget, separate from the 8 GB dataset budget;
  TXY written beside the raw files have no limit (data in the source folder; HeLab never removes
  them). Its default size and Make room come with caching v2.
- **Q12.4** a typed command overrides the folder's setting (`helab convert --output beside`).
- **Q25.1** the July 2026 cable swap is the detector's orientation: profiles gain an orientation
  field, date-split for `plates-2025` (180° from July 2026, measured 180.0 ± 0.3°), applied as exact
  sign flips and axis swaps for multiples of 90° (stage 3).
- **Q25.3** another converter on the TDC PC: "not an issue at the moment".
- **Q25.5** the burst veto, agreed in this order: find the source in the lab (M25.5); in stage 3 an
  opt-in profile option (its own tag and hash; vetoed bursts and hits in each shot's record) that
  recognises bursts by the ~180 ns echo pattern and the x1-end start rather than density alone,
  tested on dense-cloud runs (atom counts and peak shapes unchanged); a burst-rate-per-shot plot
  for Live.
- **Q27.1** saved-result reuse off by default for now ("yup turn that off for now"): a new key
  `reuse_saved_results`, default off, so earlier saves of `result_reuse` (on) don't keep it on;
  back on with Q27.2.
- **Q27.4** build Q19.5 now, in Q26.2's floor (Don't-cache folders convert to temp): "ok".
- **Q27.5** Q26.2's floor also lists and clears temp-folder TXY in Settings › Cache (A19.1): "ok".
- **A26.1** (byte units by OS) in v0.0.7: "do now".
- **Q23.1** tags `m23v1` (matlab-2023-lab-edit) and `p17v1` (plates-2017), frozen once released: "ok".
- **v0.0.7's version:** a pre-release, `0.0.7a1` ("do a pre-release"), then v0.0.8 development
  straight away; a final `0.0.7` only if a reason comes up.
- **Standing OK:** the Assistant commits record-only changes on Ground (these lists, ID_BLOCKS)
  without asking each time; code and other docs still need Tony's OK (AGENTS.md, Commits).
- **Q27.3** dev versions ("27.3 ok"): a dev branch carries `X.Y.Z.devN` from its first commit and the
  PR sets the release version. Starts with `dev/v0.0.8`, cut from `main` after v0.0.7a1's PR is
  merged (its first commit sets `0.0.8.dev0` and changes AGENTS.md's bump rule and app versioning's
  workflow), not before.
- **Privacy pass** (block 29, Tony asked 2026-10-29; both repos are public; the scan's details are
  kept out of git in `.ai/local/privacy-2026-10-29/`): no secrets or transcripts found. **Q29.1** a
  lab folder name quoted in the post-2025 plates session removed everywhere; **Q29.6** that
  session's raw per-file tables moved to `.ai/local/sessions-data/` (summaries and figures kept);
  **Q29.2** the four lab-machine memory notes moved to gitignored `.ai/local/memory/`, with a stub
  in MEMORY.md; **Q29.3** tailnet and X-share addresses may stay ("I'm okay with leaving tailscale
  address up"); **Q29.4** `DEV_POTENTIAL_DATA_PATHS` trimmed to the lab share and the sample data,
  the stray `cov.syspath.txt` removed, the LM Studio prototype's thesis paths made an argument;
  **Q29.5** no history rewrite (the tip is fixed before v0.0.7a1's squashed PR).
- **Q28.2** caching v2 and store-v4 go into **v0.0.8** ("cache store upgrade goes into v0.0.8?"):
  release v0.0.7 first, then build on `dev/v0.0.8` from `main`.
- **Q27.2** "make versioning more robust during the next store and cache upgrade, so we're better
  prepared for the distributed analysis too": a direction, settled with the design (the plan's
  [Versioning](../roadmaps/caching-v2.md#versioning)).

Tony in Chat, 2026-10-30, via the Assistant, on the converted-TXY index floor (block 30,
[handoff](sessions/2026-10-29-claude-txy-index/handoff.md)):

- **Q30.1** a HeLab TXY is current only while its size **and mtime** are the index row's (was size
  alone): yes.
- **Q30.2** (answered twice) a typed `helab convert --output cache` overrides a Don't cache folder
  (the user's intent, as Q12.4): a warning naming the folder, then `[y/N]` on a terminal (default
  temp), temp with the warning without one; `--output cache-forced` writes to the cache without
  asking. The app and the setting's default keep "the flag wins". Built.
- **Q30.3** `last_used`: a load marks at most hourly; the uses it skipped are written at quit, a quit
  save like the others (the quit window, a ~5 s no-progress limit, Quit now skips it; built), and
  also in the background every ~10 min ("(a)+(c)"; A30.4), respecting Work Offline, lane pausing, quit
  and the cache being off.
- **Q30.4** with the disk cache off this session, Settings › Cache doesn't list the temp folder's
  converted TXY: "ok", left for caching v2.
- **Q30.5** Settings refuses a temp folder on a network drive, a UNC path or a synced folder, as it
  does the cache folder ("HeLab's temp folder can't be on a network drive or in a synced folder
  ({problem}): choose a folder on this computer's own disk."; an existing such setting kept but
  warned about once): yes (A30.5).

Tony in Chat, 2026-10-30, on computer use and the smoke pass (blocks 5 and 31,
[plan](../roadmaps/smoke-automation.md)):

- **Q5.2.5** the runner's menu items go in the existing Debug menu, not a separate "Smoke" menu
  (the Assistant's proposal, approved with the Smoke ready floor). Being built on `agent/smoke-ready`.
- **Q31.1** accessibility names and descriptions on every button and control, and stable IDs
  (`objectName`), with a test that fails on any unnamed control ("let's set this up properly";
  the AGENTS.md rule proposed at landing): `agent/smoke-ready`.
- **Q31.2** the computer-use extras 1–5, 7 and 9 from the Mac pass's notes: stable IDs, milestone
  log lines, Debug › Dump State, Quit that confirms, `--geometry`, a bundle ID for source runs on
  macOS, Return committing a typed value and the plot tab's ×: `agent/smoke-ready`,
  `agent/runner-tools`. Item 8 (no popup combos) dropped: the Debug menu routes avoid them, and the
  smoke pass keeps one step done the way a person would.
- **Q31.3** the quit window lists every pending operation (kind, folder, how long), not only
  folder names.
- **Q5.1** the smoke pass runs on Sonnet 5.5 (it drove both runs so far); Haiku stays untried.

Tony in Chat, 2026-10-30, on the provisional UI pass (block 33,
[findings](sessions/2026-10-30-claude-ui-provisional-0.0.7/findings.md), "as proposed"), for a "UI
polish" floor after Smoke ready lands (Q33.6):

- **Q33.1** double-clicking a folder with no subfolders selects it (and so loads it) instead of making
  it the tree's top; a typed path to such a folder opens its parent and selects its row; a folder
  with subfolders, or not listed yet, opens as today.
- **Q33.2** the default split gives the plots the room: folders ~380 px, settings ~320 px, plots the
  rest, the user's drags kept across restarts; the folder panel does **not** collapse by itself when
  a plot opens (only Live collapses it, Q18.3). The runbook collapses it for the plot steps.
- **Q33.3** a newly floated plot opens offset ~40 px from the last one, at a usable size (~800×600,
  kept on screen); a restart restores where the user left them.
- **Q33.4** a floating plot window gets a **Dock** button ("add a dock back button").
- **Q33.5** the Debug menu's three placeholder items ("Debug - 6", "Draw a line in debug console",
  "Debug - validate tab status") go.
- **Q33.6** go for the UI polish floor (Q33.1–Q33.5, A33.1–A33.4), after Smoke ready lands, since it
  touches the same widgets.
- **Q23.7** `helab convert --once` calls a raw file damaged only at 60 s by its mtime (its settle
  age), not 20 s: "c" (Tony, 2026-10-30). Live and `--watch` keep 20 s with two checks. Built
  (`agent/txy-index`, landed with merge `e06d891`).
- **Q23.6** a custom profile's tag is `u` + **32** hex digits of its content hash (was 8): "so it's
  really annoying, also pushes the user to make a proper frozen profile" (Tony, 2026-10-30). Built-in
  tags unchanged. Names stay far inside every file system's 255-per-name limit (~56 characters, ~82
  for the temporary name); `file_kinds.HELAB_TXY`'s tag pattern (16 characters now) must take 33;
  Windows' 260-character full path is the only real limit: test a deep path, and say so clearly.
- **Q33.7** Live's check interval (Settings › General, 3 s) and the **settle time** (now only
  `HELAB_SETTLE_SECONDS`, 5 s) are both settings, defaults 3 and 5 s; the settle time 2–60 s (below
  2 s HeLab can't tell a file still being written: `RACY_SECONDS`). It applies to every read (browse,
  load, cache), so its help says so and AGENTS.md's "5 s" becomes the default. Measured again on a
  live lab run (M33.1).

Tony in Chat, 2026-10-30, on the byte units floor (block 32,
[handoff](sessions/2026-10-29-claude-byte-units/handoff.md)):

- **Q32.1** a disk budget saved under the OS's minimum (in practice 1 GB on a Windows PC, the old
  minimum) becomes 1 GiB at the next Settings Save: "ok (a)" (the minimum is 1 GiB, Q26.1 (c); HeLab
  already uses 1 GiB from startup).

Tony in Chat, 2026-10-30, via the Assistant, on the Smoke ready floor (block 34,
[handoff](sessions/2026-10-30-claude-smoke-ready/handoff.md)):

- **Q34.1** Debug › Save Window Screenshot to Temp Folder, without a dialog: yes, built.
- **Q34.2** a folder tab's own controls keep the same IDs in every tab (only the shown tab's are on
  screen); the tab bar's close buttons and the Debug items carry the tab's number: keep.
- **Q34.3** Debug › Close Folder Tab › <title>, with Debug › Show Folder Tab › <title> beside it
  ("tabs switchable by name"): yes, built.
- **Q34.4** a conversion running at quit is waited for in the quit window (its shot finishes; Quit now
  skips it): yes, as built.

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

## Automating the smoke pass (blocks 5, 31)

- **Q31.4 Where the test data lives** (computer-use extra 6): a set prepared locally in
  `~/GitHub-Local/HeLab-testdata` (75 MB, 148 files: a few raw + MATLAB TXY shots per detector era,
  Live, raw-only, TXY-only, nested and damaged folders; `manifest.json`, `tools/build.py`; not a git
  commit, nothing pushed). Host: (a) a private GitHub repo (beside the code, a deploy key in CI,
  plain git under ~1 GB) or (b) a private Hugging Face dataset (made for data, no LFS quota, would
  also take the 2.6 GB sample sets; another account and token). Proposed: (a) for this set, (b) if
  the full samples go online too. Also: does the lab agree to its shots in a private hosted repo?

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
