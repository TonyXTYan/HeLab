# Planning docs audit (2026-10-28)

Subagent of the Assistant (Side), read-only, on `dev/v0.0.7` at `7b82c9d`. The uncommitted
edits to `.ai/DECISIONS_TODO.md` and `.ai/ID_BLOCKS.md` were read as current, including Q6.11,
which was added while this audit ran. Scope: `roadmaps/*.md`, the three `.ai/*_TODO.md` lists,
`.ai/ID_BLOCKS.md`, `.ai/memory/`. The project memory folder
`~/.claude/projects/-Users-tonyyan-GitHub-Local-HeLab/memory` is a symlink to `.ai/memory`
(`diff -r` shows no difference), so it can't drift. Line numbers are those of the working tree
at the time of the audit.

Tags: **[AI]** mechanical fix; **[Tony]** needs his decision.

## Findings

### 1. The v0.0.6a1 release isn't finished: its draft has no assets, and the docs don't say so [AI + Tony]
- **Where:** `roadmaps/_readme.md:48-52`.
- **What the doc says:** "Left: CI green with no RERUN, the merge, and publishing the draft."
  Line 21 of the same file already says v0.0.6a1 "went to `main`".
- **Evidence:**
  - Merge `9c477c2` is on `origin/main`, and tag `v0.0.6a1` → `9c477c2` exists on origin.
  - The test jobs had no RERUN, in both the PR run (40671522382) and the `main` push
    (40675311830).
  - The `main` run **failed** in "Tag tested main commit and create draft release":
    `ValueError: Draft was replaced, removed or published; refusing to modify it`.
  - `gh release view untagged-0855e2edbc65d73ef84f` shows `"assets":[]`, `isDraft: true`.
  - The fix, `d36a20e`, is only on `dev/v0.0.7`, not on `main`. Its message says v0.0.5a1's
    draft is empty in the same way.
  - Neither known-issues nor any TODO list records this.
- **Fix:**
  - [AI] Rewrite the item: merge and tag done, CI clean, draft empty because of the
    `untagged-…` lookup bug (fixed in `d36a20e` on dev/v0.0.7).
  - [AI] Add a Fixed entry in known-issues citing run 40675311830.
  - [Tony] How to fill the draft. Options: attach the run's build artifacts by hand, re-run the
    release job once the fix is on `main`, or skip v0.0.6a1 assets and let v0.0.7 carry them.
    Also say whether v0.0.5a1's empty draft matters, given Q1.3 keeps it unpublished.

### 2. CI at `dev/v0.0.7`'s head failed on macOS; its RERUNs aren't in known-issues [AI]
- **Where:** `roadmaps/known-issues.md` (Tests and CI).
- **Evidence:** run 40679555921 (`7b82c9d`), job "macos + py3.13 / Tests" (122786573479), was
  cancelled at 20m33s. The previous macOS runs took 5–6 min. From its log:
  - `test_folder_summary.py::test_disk_cache_summary_tracks_shared_save_completion[cache_saved]`:
    RERUN ×3, at 11:27:38–11:27:50.
  - `test_analysis_gui.py::test_another_library_draws_the_plot_again_without_a_rerun`: RERUN
    and "replacing crashed worker gw0". Two 100 s faulthandler dumps were at line 581.
  - `test_correlations.py::test_fifty_shots_of_two_thousand_events_take_seconds`: RERUN ×5,
    then **FAILED**.
  - Faulthandler dumps also in `test_correlations.py:326` (`test_g2_zero_error_matches_its_scatter`).
  - `test_correlations_plot.py:216` (`test_back_to_back_pairs_peak_at_zero_with_the_trap_origin`):
    RERUN and "replacing crashed worker gw1".
  - The commit message reports "-n 12 … no RERUN" for the local run; the earlier dev/v0.0.7
    run 40679110506 (`e75a105`) passed.
- **Fix:**
  - Add the four tests to known-issues with the run and job IDs. The pattern (compute-heavy
    tests timing out together) suggests a slow runner, but no cause has been found.
  - Update the existing `test_folder_summary` entry (line 75): it reran again, three times,
    so it isn't a one-off.

### 3. The roadmap's v0.0.7 focus contradicts block 6's decisions [AI]
- **Where:** `roadmaps/_readme.md:26-34`.
- **What the roadmap says:**
  - Distributed compute is listed as a v0.0.7 focus, with "The first slice is Q6.2".
  - The converter item says only "Inputs and where it runs: Q6.3".
- **Evidence:** DECISIONS_TODO block 6.
  - Q6.2 is **Postponed** ("postpone distributed compute build until we have a very good
    working tdc_autoconvert within helab", lines 151-152).
  - Q6.3 is answered: the X share samples; replace MATLAB with a headless HeLab converter plus a
    Live toggle; output named `d_txy_helab_<N>.txy`.
  - Q6.5 is decided: a byte-identical reference first, then one builder per backend (NumPy,
    Numba, Cython/C, Rust, MLX).
  - Q6.8 is answered: the toggle shows after Live is turned on.
  - Q6.10 and Q6.11 (detector profiles, calibration) are open.
  - findings.md: the 2019 variant reproduces both samples byte for byte.
- **Fix:**
  - Mark distributed compute "postponed until the converter works (Q6.2)".
  - State the converter's stages: reference, benchmark spike, then the backends and the Live
    toggle.
  - Use byte-identical output as the bar, and link the findings until a plan file exists.

### 4. The TXY converter appears twice on the roadmap, with an older bar in Near term [AI]
- **Where:** `roadmaps/_readme.md:84-91` (Near term) and `roadmaps/_readme.md:28-30` (Now).
- **What the Near term item says:** the check is "the same event counts and values to 8
  significant figures, for the variant that wrote them".
- **Evidence:** findings.md:31-37 and Q6.5 (line 183) set the bar at byte-identical output to
  the 2019 variant. The Near term item also still frames the MATLAB `movefile` change as the
  task, but Q6.3.2 replaces MATLAB.
- **Fix:**
  - Fold the Near term item into the Now item, keeping its link to `core-update.md`.
  - Say whether the MATLAB converter's temp-name change is still wanted. That is Tony's call if
    unclear: it is moot once HeLab replaces MATLAB, but MATLAB keeps converting until then.

### 5. Writing HeLab's TXY beside the raw files would reverse a standing rule [Tony]
- **Where:** `.ai/DECISIONS_TODO.md:227-234` (Q6.7, proposed (a): write `d_txy_helab_<N>.txy`
  beside the raw files on the share).
- **The conflict:**
  - `roadmaps/quality-control-and-repair.md:19-21`: "Repaired files live in HeLab's cache
    folder, not the source folder (Tony, 2026-10-15), so HeLab keeps never writing to source
    folders".
  - Q6.3.2 (line 161): "every HeLab-made TXY stays in HeLab's temp folder".
- **Fix:** Q6.7 should name the rule it would change, so Tony decides knowingly. If (a) is
  chosen, record the exception in the QC plan and in `.ai/architecture/io-and-browsing.md`.

### 6. The release tidy-up is due after v0.0.6a1 in all five lists [AI]
Each list says to tidy at each release.
- **Roadmap** (`_readme.md:13-15`, "move ticked items to Done at the next tidy-up"): six ticked
  items still sit in the active sections, at lines 70-72, 101-103, 114-117, 124-126, 148 and
  196-199. Done (line 248) has only the v0.0.5a1 block. Add a v0.0.6a1 block, and move the
  release item (finding 1) there once it's finished.
- **known-issues** (lines 12-13, "Drop fixed items at the next release's tidy-up"): the whole
  Fixed section, lines 96-280, is from dev/v0.0.6.
- **AI_TODO** (line 23, "drop ticked items at each release's tidy-up"): A1.5, A3.1, A3.2, A3.3
  and A5.1 are ticked. The heading "Before the v0.0.6 release (block 1)" (line 32) is past; its
  open items A1.2, A1.3, A1.4 and A1.6–A1.8 need a new heading.
- **DECISIONS_TODO**, Recently decided (lines 32-78):
  - Can be cleared: Q6.1, Q5.2, and Q1.1–Q1.5. Each is recorded where it lives: the roadmap
    Now and Release repos items, `smoke-automation.md`, MANUAL_TODO:25 and :181. Q1.4 also has
    the stale open decision of finding 10.
  - Must stay: the block applied "as proposed … each needs Tony's confirmation" (Q3.2, Q3.1,
    Q2.8, Q2.3, Q3.3, Q3.4, Q3.6.3, Q2.2.1, Q2.2.2, Q4.1). AGENTS.md still says "(Q3.3, to
    confirm)". **[Tony]:** confirm these so the tidy-up can clear them.
  - The heading "Before the v0.0.6 release" (lines 80-82) is now only a pointer: remove it.
  - "After the release (not blocking)" (line 262) should say v0.0.6.

### 7. Decided Q6 items still sit in the open section, one decision has no ID, and Q2.7 is moot [AI]
- **Where:** `.ai/DECISIONS_TODO.md`.
- **Decided but still open-listed:** Q6.2 (postponed, line 151), Q6.3 (answered, line 153),
  Q6.5 (decided, line 185), Q6.8 (answered, line 236) and Q6.4 (decided, line 257).
  - The rule at lines 22-28: once answered, the decision goes where it lives and the question
    moves to Recently decided as one line.
  - Their content belongs in the converter plan (finding 18) and the roadmap.
  - Q6.4's follow-up ("Once v0.0.7 is on main, check that Dependabot's graph run passes") is
    agent work: make it an AI_TODO item.
- **No ID:** "v0.0.7's focus" at lines 40-42 is a decision without one. Fold it into Q6.1, or
  give it the next free ID (Q6.12, since IDs are never reused).
- **Moot:** Q2.7 (lines 106-108, "wait for v0.0.6 to clear the Dependabot alerts") was settled
  by the release plus Q6.4(a), which dismissed the 42 alerts. Move it to Recently decided as
  "resolved by Q6.4".
- **Order:** block 6 runs 6.2, 6.3, 6.5, 6.9, 6.10, 6.11, 6.6, 6.7, 6.8, 6.4. Sort by number.

### 8. One Q1.9 item that should "stay on the roadmap" isn't on any list [AI]
- **Where:** `.ai/DECISIONS_TODO.md:288`. Q1.9 item 6 is "The `--upgrade` lock refresh
  (python-dateutil 3.0), in its own CI run."
- **Evidence:** lines 41-42 say Q1.9's "other items stay on the roadmap". Items 1–5 are there
  (export, `refactoring.md` FolderCache, headless runner, converter, D13). "dateutil" and
  "--upgrade" appear in no roadmap or TODO file; the README only has the generic command.
- **Fix:** add it to AI_TODO, or to the roadmap's Now.

### 9. The roadmap says Basic plots use ms/mm, but they keep s/m [AI]
- **Where:** `roadmaps/_readme.md:155-157`, "Standard analyses … (v1 done 2026-10-19; T in ms
  and X/Y in mm since 2026-10-20)".
- **Evidence:**
  - AGENTS.md:183-184: "Basic plots v1 keeps s and m with SI prefixes".
  - `.ai/architecture/dld-analyses.md` says the same.
  - `helab/scripts/standard/` has no `unit_prefix`, `display_units` or `GroupedAxis`; all ten
    users are in `helab/scripts/dld/`.
- **Fix:** "T/X/Y in s and m with SI prefixes; the DLD port's plots use ms/mm".

### 10. Several plans still list decisions that have been made [AI]
- **`roadmaps/app-updates.md:276`:** "Release repos: confirm the proposal" is still under Open
  decisions. Line 55 says it was confirmed on 2026-10-28 (Q1.4). Remove it.
- **`.ai/MANUAL_TODO.md:561-566`:** "Release repos: confirm the proposal" is confirmed. Reword
  to the remaining steps: stop pushing dev branches to HeBECANU, and fast-forward at the first
  lab-ready version.
- **`roadmaps/live-monitoring.md:175`:** the open decision "Live with settle age only … Keep, or
  re-read recently changed shots in Live? (Tony to decide, 2026-10-19)" was answered.
  - Same file, lines 114-119: "a shot Live read in the last 5 minutes that then changes is read
    again".
  - known-issues.md:275-277 says "settle age only, by Tony's decision (2026-10-20); Live
    re-reads a recently read shot that changes".
- **`roadmaps/build-size.md:3`:** "Draft; nothing implemented". Line 53 of the same file says
  "Done 2026-10-13", and `_readme.md:67` says "Step 1 done".
- **`roadmaps/app-versioning.md:8`** (the "authoritative" section): `__version__ = "0.0.5a1"`.
  It is `0.0.6a1` now; use a placeholder such as `"X.Y.Z"`.

### 11. Plans and memory still point at AGENTS.md sections that moved [AI]
AGENTS.md was cut to rules plus a map (Q3.2). These pointers name sections it no longer has.

| Pointer | Now in |
|---|---|
| `roadmaps/analysis-workflow.md:23` "AGENTS.md › Script system" | `.ai/architecture/plots-and-scripts.md` |
| `roadmaps/cache-only-browsing.md:12` "AGENTS.md › Work Offline" | `.ai/architecture/io-and-browsing.md:16` |
| `roadmaps/live-monitoring.md:99` "the architecture summary is in AGENTS.md" | `.ai/architecture/live.md` |
| `roadmaps/cache-storage-and-settings.md:630` "[AGENTS.md › Caching](../AGENTS.md)" | `.ai/architecture/cache-store.md` |
| `.ai/memory/results/analysis-plots.md:10` "AGENTS.md › Script system" | `.ai/architecture/plots-and-scripts.md` |
| `.ai/memory/results/live-monitoring.md:10` "AGENTS.md › Live" | `.ai/architecture/live.md` |
| `.ai/memory/results/disk-cache-and-budgets.md:12` "AGENTS.md has the code map" | still true, but the detail is in `cache-store.md` |

### 12. Memory files with stale facts [AI]
- **`results/disk-cache-and-budgets.md:5` and `:18`:** say "store-v2" and
  `store-v2/records.sqlite`. Code: `cache_store.py:31` `STORE_DIRNAME = "store-v3"`. The index
  line (MEMORY.md:19) already says "now store-v3".
- **`results/basic-scan-defaults-and-failures.md:27`:** "(store-v2 since S5 …)", the same.
- **`results/subfolder-derived-status.md:5`** (description): "saved (folder-subtree-v1)".
  `folder-subtree-v1` appears nowhere in `helab/` or `tests/`; the body (line 31) correctly says
  the `subtrees` table.
- **`results/analysis-plots.md`:**
  - Line 24: "Axes in s and m as stored (Tony to confirm the units)". Decided 2026-10-20: the
    DLD port uses ms/mm, Basic plots v1 keeps s/m.
  - MEMORY.md:23 ("crop rule and units open") and the description (line 5, "open: … units")
    say the same.
  - Line 17's RAM-budget "follow-up" landed on 2026-10-20 (`_readme.md:124-126`).
  - Line 33 lists Floating plot settings under **Open**; it landed on 2026-10-20
    (`_readme.md:148`).
- **`project_v0.0.5a-folder-browser.md`** (MEMORY.md:21) is a v0.0.5a project note, and
  v0.0.5a1 shipped on 2026-10-19.
  - It cites store-v2 (line 32).
  - Line 48 says "Status-message review by Codex: TODO in MEMORY.md". MEMORY.md has no such
    TODO, and the audit was ticked done on 2026-10-26 (`_readme.md:70-72`).
  - Its open threads are now tracked elsewhere: 100k entries (known-issues:17), one background
    lane (known-issues:26), the "keep the previous signature" check (MANUAL_TODO:185-188), and
    silent scan skipping on cache failure (`_readme.md:104`).
  - Fix: retire it, or reduce it to the one fact still unique there (the default cache folders
    moved to `~/Library/Caches/HeLab` / `%LOCALAPPDATA%\HeLab`, which the Lab Main PC's notes (now local only, Q29.2)
    already links).
- **`results/maestri-chat-and-codex.md:1-4`:** the only memory file without `name:` and
  `description:` front matter. Cosmetic.
- **Checked and found nothing wrong:**
  - Every backticked identifier in the cache, browsing, Live and plots memory files exists in
    the code (e.g. `_refresh_open_tooltip`, `subtree_save`, `store_answer`, `usage_seq`,
    `prefs_cleared_at`, `QuitSaveDialog`, `CentralHint`, `_start_with_rhi_surface`,
    `HELAB_TEST_READ_GATE`).
  - Every index line points at an existing file, and every `[[wiki-link]]` resolves.

### 13. No memory results for the v0.0.6 decisions [Tony, ties to Q3.5]
- **Where:** `.ai/memory/MEMORY.md`. The index and folder were last changed on 2026-10-21/22.
- **What's missing:** no `results/` file for:
  - Work Offline (cache-only, 2026-10-26);
  - presets stage 1 (2026-10-23);
  - the DLD port's settled choices (units, constants layers);
  - smoke automation (Q5.2).
- **Evidence:** DECISIONS_TODO:23 says settled design goes to `.ai/memory/results/`. Today
  these decisions live only in the plans, `.ai/architecture/` and session handoffs.
- **Fix:** Q3.5 already proposes recording such decisions in memory. Once Tony answers it, an
  agent can write these files and their index lines.

### 14. MANUAL_TODO: items done elsewhere, stale steps, and a wrong route [AI]
- **Lines 586-587**, "Record the required Python 3.13 suite/type-check and build results for
  the release commit": unticked, though AI_TODO A1.5 (line 60) is ticked and says it "covers
  MANUAL_TODO's" item. Tick it.
- **Lines 311-316** (store-v2 / account-independent SMB-key build) duplicate lines 181-182
  (Q1.5). A1.1 asked to merge them; it isn't done.
- **Lines 389-390:** a reproducible hover-menu failure goes "to `roadmaps/_readme.md`". It
  should go to known-issues (the AGENTS.md routing table and AI_TODO A1.6).
- **M1.1 (lines 47-48)** still says "Help › About HeLab" and "version 0.0.5a1 (until the
  bump)".
  - The smoke results (`2026-10-28-claude-smoke-mac/results.md:13`) found About under the
    HeLab menu on macOS.
  - The version is now `0.0.6a1`.

### 15. AI_TODO status drift [AI]
- **A1.2** (line 39) is partly done: the smoke pass ran a `pyinstaller HeLab.spec --clean -y`
  build at `41a6a7d`, and its helpers ran (`smoke-mac/results.md:5`). The About check on the
  release commit wasn't done: About showed `0.0.5a1`, before the bump. Note this on the item.
- **A1.8** (line 82) is partly done: the smoke problems are in known-issues (lines 49-64). Not
  done: the overlapping MANUAL_TODO items (Presets 345-352, Work Offline 367-385, Saved results
  394-396) aren't marked Mac-passed.
- **A2.5** (line 109) is still open, as is the A2.1 #16 item for
  `test_analysis_gui.py::test_scatter_from_the_panel`. known-issues has neither test (grep).

### 16. ID_BLOCKS doesn't record the M IDs [AI]
- **`.ai/ID_BLOCKS.md:36`:** block 1's mapping lists Q1.1–Q1.9 and A1.1–A1.8, but not
  M1.1–M1.8 (MANUAL_TODO:15 assigns them to the smoke pass).
- **Line 41:** block 6's branch is `dev/v0.0.6`, but Q6.4 onward were raised after the merge,
  on `dev/v0.0.7` (Q6.4: "found 2026-10-28 after the v0.0.6a1 merge"). Write "dev/v0.0.6 →
  dev/v0.0.7".
- **Checked and found nothing wrong:**
  - No duplicate IDs.
  - Block ranges match the items: Q2.1–Q2.8, A2.1–A2.5, Q3.1–Q3.6, A3.1–A3.3, Q4.1, Q5.1–Q5.2,
    A5.1 and Q6.1–Q6.11.
  - Every AI_TODO item has an ID. MANUAL_TODO's older items have none, by design (line 15).

### 17. Smaller roadmap and known-issues points [AI]
- **known-issues.md:29-32:** "Clear the analysis view or mark it stale, once plotting exists".
  Plotting exists now, and the plots' "Showing previously loaded data" prefix
  (`views/plots/workspace.py:306`) is a stale signal. Re-check whether the case (data dropped
  while shown) is covered, and reword or close the entry.
- **Duplicated questions:**
  - Q1.8 (DECISIONS_TODO:278-280) repeats MANUAL_TODO:455-456 ("is the tray/menu-bar icon
    acceptable").
  - Q1.7 repeats MANUAL_TODO:239-242 and M1.8's last step.
  - Keep the question in DECISIONS_TODO and the check in MANUAL_TODO, linked; this is part of
    A1.1.
- **Decisions held outside DECISIONS_TODO:** `dld-front-panel-port.md` holds 33 open decisions
  (`_readme.md:168`; the count matches), and they overlap Q1.6.1 (QE, trap frequencies, axial
  axis = DLD #1–#3). live-monitoring.md:176-180 and app-updates.md:271-284 hold more.
  **[Tony]:** index the plans' open-decision lists from DECISIONS_TODO with one line each, or
  accept that plans keep their own.
- **Q2 audit items re-checked; all still open and accurate:**
  - Q2.1.1: pid 15027 is still running, 5 days, from the removed result-cache-r2 floor's venv.
  - Q2.1.2: `.ai/temp/pytest-land` is still 386 MB.
  - Q2.2.3: six local agent branches are one commit ahead of origin: cache-only,
    codebase-review-2, presets-reopen, quick-fixes-2, quick-fixes-3, windows-store-test.
  - Q2.6: Windows tests took 15:13–15:33 of the 20-min limit in today's three runs, and the
    macOS job hit it (finding 2).

### 18. Links [AI: none to fix]
All 346 relative Markdown links and their `#anchors` resolve (GitHub slug rules), and so do the
memory `[[wiki-links]]`, across `roadmaps/*.md`, the three TODO lists, ID_BLOCKS and
`.ai/memory/**`. A check of backticked paths found only historical references in plan logs
(`helab/workers/`, `helab/scripts/dev/` in `cache-storage-and-settings.md`; `_build_info.py`
in app-versioning's "Historical" options), which are fine as history.

## The TXY converter port: what the roadmap needs

There is no `roadmaps/` plan file for the converter yet, which is expected. Today the converter
is described in five places that don't agree: `_readme.md:28-30` (Now), `_readme.md:84-91`
(Near term), `live-monitoring.md:93` (L4), `dld-front-panel-port.md:139-144`, and DECISIONS_TODO
Q6.3–Q6.11 with `sessions/2026-10-28-claude-txy-converter-plan/findings.md`.

When `roadmaps/txy-converter.md` (or similar) is written, these places need updating.

**Point at the new plan:**
- `roadmaps/_readme.md:28-30`: the Now item links `live-monitoring.md#stages`; link the plan.
  Merge the Near term item (`:84-91`) into it, and update `:167` ("raw-pulse diagnostics after
  the converter port") and `:187` ("L4 (converter in HeLab) next").
- `roadmaps/live-monitoring.md`:
  - `:93`: the L4 row ("raw → TXY conversion and QC as shots settle; needs L3, QC") should link
    the plan and add the Q6.8 toggle (shown after Live is on).
  - `:79-84`: the "Acquisition machine" section points at the 2026-10-14 session design
    (`remote-headless.md#live-acquisition-machine…`).
  - `:147-148`.
- `roadmaps/dld-front-panel-port.md`:
  - `:7`, `:139-144`, `:241` and `:253`: D11 "comes after the TXY converter port".
  - Q6.11 now proposes D11's raw-pulse diagnostics as the converter's **calibration stage**, so
    D11's sequencing and ownership change. It would move into the converter plan or become its
    dependency; it is no longer "after".
- `roadmaps/headless-analysis.md`: no mention of the converter, though Q6.3.2 makes the
  converter a headless HeLab mode. Add it to the first milestone or its dependencies.
- `roadmaps/quality-control-and-repair.md:27`: "A future HeLab-run TDC converter is a separate
  file-generation capability". Link it.
- `roadmaps/network-runners-and-web.md#cross-machine-result-sharing`: Q6.7(b) and the postponed
  Q6.2.

**Prerequisites the plan must take on:**
- `roadmaps/cache-storage-and-settings.md#file-kinds` and the unchosen idea at
  `_readme.md:229-231` ("More file kinds: measure raw `d*.txt` sizes, and load/cache other data
  formats"). The converter (and D11) need HeLab to read raw `d*.txt`, and Q6.6 needs a
  `d_txy_helab_*.txy` file kind. That idea becomes a prerequisite rather than an unchosen idea.
- `roadmaps/known-issues.md:18-21`: the temp folder (`DIR_TEMPS`) is "created … but nothing
  uses it". Q6.3.2 says HeLab-made TXY "stays in HeLab's temp folder", so the plan resolves
  this entry: use `DIR_TEMPS`, or choose the cache folder as the QC plan did.
- `roadmaps/known-issues.md:275-277` and `live-monitoring.md:118-119`: "The converter's
  temp-name rename remains the real fix". Once HeLab writes its own TXY, it can guarantee
  write-then-rename; MATLAB-written folders still can't.
- `roadmaps/data-roots.md:64` and `MANUAL_TODO:180`: the converter must ignore `.helab-root`.
  This is trivial for HeLab's own converter, but list it in the plan's checks.

**Decisions to carry from DECISIONS_TODO into the plan once settled:**
- Q6.3 (samples, name, goal), Q6.5 (reference and per-backend stages, the byte-identical bar),
  Q6.8 (toggle), Q6.9 (store or cache only), Q6.10 (detector profiles), Q6.11 (calibration),
  Q6.6 and Q6.7.
- Then a `.ai/memory/results/txy-converter.md` with its MEMORY.md index line.
- findings.md:4 lists "Q6.3, Q6.5, Q6.9, Q6.10"; add Q6.11.
