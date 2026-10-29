# Planning docs audit 2 (2026-10-29)

Subagent of the Assistant (Side), read-only, on `dev/v0.0.7` at `36e3d6c` (clean tree). Scope:
`roadmaps/*.md`, `.ai/DECISIONS_TODO.md`, `.ai/AI_TODO.md`, `.ai/MANUAL_TODO.md`,
`.ai/ID_BLOCKS.md`, `.ai/memory/`, with the 2026-10-29 session notes and the
[overnight mandate](../2026-10-29-claude-v0.0.7-overnight/mandate.md) as sources. Claims about the
code were checked with grep at `36e3d6c`; cited commits are all ancestors of `HEAD`. Yesterday's
[audit](../2026-10-28-claude-docs-audit/planning.md) is not repeated, except where one of its
findings is still open; those places say so.

A link checker (relative paths and GitHub heading anchors) over the scope plus `AGENTS.md` and
`.ai/architecture/*.md` found **no broken links or anchors**.

Tags: **[AI]** a mechanical fix an agent can make; **[Tony]** needs his decision.

## Findings

### 1. DECISIONS_TODO keeps about 40 decided items in its open sections [AI]

- **Where:** `.ai/DECISIONS_TODO.md:95-344` (blocks 10-23) and `:380-524` (block 6).
- **What's wrong:** the file's own rule (`:22-28`) says an answered question goes where it lives
  and then moves to **Recently decided** as one line. Recently decided (`:32-93`) holds only blocks
  6, 8 and 9, Q2.6 and the "confirm all" line. Everything Tony answered on 2026-10-29 after block 9
  stayed in place, so a reader can't tell open from closed without reading every entry.
- **Evidence (decided, still in open sections):**
  - Block 10: Q10.1 (`:105`), Q10.2 (`:109`), Q10.3 (`:114`).
  - Block 11: Q11.1 (superseded by Q18.1, `:209`), Q11.2 (`:132`), Q11.3 (`:136`).
  - Block 12: Q12.2, Q12.5, Q12.7, settled by Q18.4, Q18.5 and Q18.6 (`:221-233`).
  - Block 14: Q14.1 and Q14.3 (settled by Q18.2, as block 23's intro at `:325-326` says);
    Q14.5 (handed to the caching audit, `:234`, now Q19.3).
  - Block 15: Q15.2 (superseded by Q18.3, `:325`); Q15.1 (became the check M18.1, `:216`).
  - Block 16: Q16.1 (`:197`), Q16.2 (`:203`, built as A17.2).
  - Block 18: the whole block, under the heading "Decided:" (`:206-235`).
  - Block 19: Q19.4 (`:252`), Q19.9 (`:274`), Q19.10 (`:279`).
  - Block 22: Q22.1-Q22.6 and Q22.8-Q22.11 (`:286-287`, `:299`, `:313`); only Q22.7's budget is
    still open.
  - Block 6 (still open from yesterday's #7): Q6.3 (`:399`), Q6.5 (`:409`), Q6.6 (`:446`), Q6.8
    (`:458`), and most of Q6.10 and Q6.11.
- **What is still open:** Q1.6-Q1.8, Q2.4, Q3.5, Q3.6.1-2, Q5.1, Q5.2.5, Q6.2 (postponed), Q6.7,
  Q6.9 (see #6), the open parts of Q6.10 (the 2022 swap date) and Q6.11 (a calibration set; 2025
  MCP pulses), Q12.1, Q12.3, Q12.4 and Q12.6 (#2), Q14.2/Q23.4 (#3), Q14.4, Q15.3, Q19.1-Q19.3,
  Q19.5-Q19.8, Q22.7 and Q23.1-Q23.7.
- **Fix:** move each decided item to Recently decided as one line ("Q10.1 no built-in profile for
  the third variant; converter.md"), after checking it is recorded where it lives (#4, #5, #9).
  Leave each block's open items under their heading, and drop the blocks that become empty.

### 2. Overnight decisions "for Tony to confirm": several are confirmed but still marked, three are not, and one is already a rule in AGENTS.md [AI + Tony]

- **Where:** `.ai/DECISIONS_TODO.md:104`, `:111-113`, `:124`, `:142`; `.ai/AI_TODO.md:157`; `AGENTS.md:131-134`.
- **Confirmed or superseded, but still marked "for Tony to confirm":**
  - Q10.1 (`:104`) and Q10.3 (`:111-113`): Tony answered both on 2026-10-29 (`:105`, `:114`), yet
    each still reads "Decided by Side overnight, for Tony to confirm". A10.5 (`AI_TODO.md:157`)
    still credits it to "Side overnight".
  - Q11.1 (`:124`): the numba cache in `cache_dir()` was replaced by Tony's Q18.1 (temp folder),
    built in `134e2ec` (`converter.md:147`).
  - Block 12's header (`:142`) still lists Q12.2, Q12.5 and Q12.7 as unconfirmed. Tony settled
    them as Q18.4, Q18.5 and Q18.6 (`:219-233`), and `AGENTS.md:168-175` already dropped the
    "(to confirm)" on the housekeeping line.
- **Never confirmed (open) [Tony]:**
  - **Q12.1:** a folder with no data root, asked for `cache`, converts to temp.
  - **Q12.3:** HeLab's TXY in the cache folder stay outside the budget. This is the same question
    as Q19.2 (`:248`); merge the two.
  - **Q12.4:** `helab convert --output beside` writes beside for that run without the folder's
    flag. It is already written into AGENTS.md's source-folder write rule (`AGENTS.md:131-134`,
    "or asks for it on the command line (Q12.4)"), so a rule rests on an unconfirmed decision.
- **Process decisions in the mandate that never became Q items:**
  - **The final Reviewer is Codex, replaced by a Claude Reviewer if it stalls** (mandate ~01:30,
    ~01:50). Codex did stall on its first approval prompt on a floor. `.ai/maestri-setup.md:100-102`
    still says "(check)" about what an untrusted floor changes for Codex. [Tony: trust the floors
    folder in `~/.codex/config.toml`, or keep Claude Reviewers on floors? AI: replace the
    "(check)" with what happened.]
  - **Land only when the branch's latest CI is green on all three OSes** (mandate 06:20, after
    helab-core landed with Windows failing). Neither `roadmaps/agent-workflow.md` nor
    `.ai/maestri-setup.md` nor the Coordinator's role says so. [Tony to confirm; AI to record.]
- **Fix:** [AI] strip the stale markers (Q10.1, Q10.3, Q11.1, block 12 header, A10.5). [Tony]
  answer Q12.1, Q12.3 with Q19.2, Q12.4, and the two process rules.

### 3. Q14.2 is both settled and open [AI, then Tony]

- **Where:** `.ai/DECISIONS_TODO.md:211-212` versus `:334-336`.
- **What's wrong:** Q18.2 is filed as deciding "(Q14.1, Q14.2)". Q23.4 says "A plot's profile
  choice isn't saved with presets, arrangements or reopened plots (Q14.2 still open)". Q18.2 chose
  the four source modes; it didn't decide whether a plot's choice is saved with presets.
- **Fix:** drop Q14.2 from Q18.2's parenthesis and keep Q14.2 (or Q23.4, one of them) as the open
  question. [Tony: proposed, save the source and profile with presets and arrangements once
  `analysis/presets.py` changes format for something else.]

### 4. Block 22's decisions are only in a session note; the caching v2 plan contradicts Q22.2 and lists Q22.x as open [AI]

- **Where:** `roadmaps/caching-v2.md:49-53`, `:61-62`, `:69-70`, `:104-109`.
- **What's wrong:** Tony answered Q22.1-Q22.4, Q22.6 and Q22.8-Q22.10 "as proposed"
  (`DECISIONS_TODO.md:286-287`). Only Q22.5, Q22.7's measurements and Q22.11 reached the plan.
  - **Q22.1 (fill the raw layer in a background `raw_fill` job):** missing. The plan's loading
    order (`:52-53`) ends with "else read the share".
  - **Q22.2 (key HeLab layers by profile hash, with tags as names):** contradicted. The plan
    says "one stored dataset per (folder, source tag)" (`:49-50`) and "HeLab shots are identified
    by raw fingerprint + profile tag" (`:61-62`).
  - **Q22.3 (behave as Keep until the store-v3 question is answered), Q22.4 (import the user's
    v3 state once), Q22.6 (orphaned or old-parser raw layers kept and labelled), Q22.8 (offline
    conversion from the raw layer), Q22.9 (no clear-tag action) and Q22.10 (`%.17g` text):** all
    missing.
  - `:69-70` says "Design to write before stage 1 (a design note, then this section)". The note
    exists (`sessions/2026-10-29-claude-caching-audit/store-v4-design.md`, `37c0a83`).
  - "Open decisions" (`:106-109`) lists Q22.1-Q22.10 as open, and also Q19.6, which the plan
    states as settled at `:63-65` (#7).
- **Fix:** write the block 22 answers into the plan's raw layer, TXY layers and Store v4 sections.
  Key layers by profile hash, with the tag as their name. Cut the open list to Q19.1-Q19.3,
  Q19.5, Q19.7, Q19.8 and Q22.7. Name the `.hlb` pickle-free container, since known-issues
  `:17-24` already cite it as the fix.

### 5. The v0.0.7 converter is described as it was before Tony's 2026-10-29 answers [AI]

- **Where:** `roadmaps/_readme.md:29-45`; `roadmaps/txy-converter.md:20-21`, `:37-39`, `:47-54`,
  `:146-147`, `:187-188`, `:200-210`.
- **What's wrong:**
  - **Output name.** Both files give the output as `d_txy_helab_<N>.txy` (`_readme.md:32`,
    `txy-converter.md:20`). Since Q18.4 (`26a2ade`, landed `c718c71`) it is
    `d_txy_helab_<tag>_<N>.txt` (`helab/utils/file_kinds.py:33`, `AGENTS.md:133`).
  - **Where the output goes.** "For now every HeLab-made TXY stays in HeLab's temp folder" and
    "HeLab still never writes to source folders (Q8.2)" were replaced by Q9.3 and Q9.7. The
    setting defaults to `cache` (`settings_defaults.py:103`), and writing beside the raw files is
    an option per folder.
  - **Stage status.** "stage 4 (in HeLab) started" (`_readme.md:41`) should be "done"
    (`02cda86`; follow-ups `c718c71`). "Q11.2 on which fast backend to keep" (`:40`) is decided:
    Cython.
  - **Open list.** `_readme.md:41-43` still lists Q6.6 as open; it was decided as the four
    modes, Q18.2.
  - **Backends.** "Every backend ships for now" (`txy-converter.md:48`, `:188`) and the
    recommendation "for Tony" (`:146-147`) stop at Q9.2. Since Q11.2 and `134e2ec`, the app ships
    numpy, cython and the reference.
  - **Source choice.** "Which TXY a folder uses" (`:37-39`) is Q6.6's three options; it is now
    Q18.2's four modes.
  - **Stages 3 and 5.** Neither says "not started" (`:162`, `:197`), and nothing gives the
    stage 3 / stage 5 versus v0.0.7 split.
  - **No link to caching v2.** "Later: … TXY kept only in caches (Q6.9)" (`:200`) predates the
    plan, and `txy-converter.md` never links `caching-v2.md`.
- **Fix:**
  - Rewrite the `_readme.md` item: stages 1, 2 and 4 done with their commits; stages 3 and 5 not
    started, after v0.0.7; left for v0.0.7: the smoke pass, the Q23.1 tag freeze, the version bump
    and the PR (#8).
  - In `txy-converter.md`, update "Decided" (output and name, Q18.4; locations, Q9.3, Q9.7; what
    ships, Q11.2 and Q11.3; source modes, Q18.2; damaged files, Q18.5). Mark stages 3 and 5 "not
    started", and point "Later" at caching v2.

### 6. Converter open questions are listed stale in three places [AI + Tony]

- **Where:** `roadmaps/txy-converter.md:203-210`; `.ai/DECISIONS_TODO.md:576-577`, `:462-470`.
- **What's wrong:**
  - The plan's "Open decisions" omits every open converter question raised since stage 1: Q12.1,
    Q12.3, Q12.4, Q12.6, Q14.2/Q23.4, Q14.4, Q15.3 and Q23.1-Q23.7.
  - The index at `:576` says "already Q6.6-Q6.11, plus two smaller ones". Q6.6 and Q6.8 are
    decided, and the plan lists five items.
  - Q6.9 ("store HeLab's TXY, or only cache them") is still open, although its benchmark is done
    and caching v2 (Q19.9: cache the raw files; Q19.1 proposed: HeLab writes TXY only beside the
    raw files or on export) answers it in effect.
  - Caching v2 is missing from the "Open decisions inside plans" index (`:554-577`).
- **Fix:** [AI] list the open Q IDs in the plan's open section, fix the index line, and add
  caching-v2. [Tony] close Q6.9 as "answered by caching v2 (Q19.9; Q19.1 to decide)", or keep it
  open.

### 7. Caching numbers and precision disagree between the decision text and the plan [AI + Tony]

- **Where:** `.ai/DECISIONS_TODO.md:264-275`, `:276-281`, `:285`, `:312`;
  `roadmaps/caching-v2.md:26-31`, `:63-65`, `:106`.
- **What's wrong:**
  - **The cost premise.** Q19.9 and Q19.10's proposal reason that a raw layer "costs about
    what caching TXY costs now" (`:267`, `:278`). The plan (`:26-29`) corrected that: a raw layer
    is ~1.9× a TXY layer, and raw plus one tag ~2.8× today's store.
  - **The ratio.** Block 22's header says ~1.9× (`:285`), Q22.7 says ≈ 1.8× with the chosen
    codec (`:312`), and the plan says 1.9× (`:28`) while naming that codec (`:30-31`).
  - **Precision.** Q19.6 is open in DECISIONS_TODO and in the plan's open list (`:106`), but the
    plan states it as settled (`:63-65`, "(Q19.6)"), and Q22.10 (`%.17g` for full-precision
    tags, decided) assumes it.
- **Fix:** [AI] add a note under Q19.9 that the cost was corrected to ~1.8-1.9× (2.8× with one
  tag). Use 1.8× wherever zstd 9 with byte shuffle is the codec. [Tony] Q19.6: confirm
  "binary always; `m19v1` at 8 significant figures; newer tags float64" (implied by Q19.9 and
  Q22.10), or the plan marks it proposed.

### 8. Nothing tracks what v0.0.7 still needs before its PR, and the smoke pass has no converter step [AI + Tony]

- **Where:** `roadmaps/_readme.md:19-52`; `.ai/MANUAL_TODO.md:14-16`, `:18-133`;
  `.ai/DECISIONS_TODO.md:84-85`, `:328-329`.
- **What's wrong:**
  - Q9.9 says v0.0.7 ships with stages 1, 2 and 4 "and the smoke pass". The roadmap's Now has no
    "Release v0.0.7" item, unlike v0.0.6a1 (`:66-73`). Left to do: the smoke pass on a Mac and a
    lab PC, Q23.1 (tags frozen once released: "confirm before v0.0.7 ships"), the version bump
    (`_version.py` is still `0.0.6a1`), the PR, and the release tidy-up (Q8.3).
  - The smoke pass M1.1-M1.8 has no converter step, though the converter is v0.0.7's whole
    content. The converter checks (M12.1, M14.1-M14.2, M15.1-M15.2, M16.1-M16.2, M23.1-M23.3)
    sit below it, and MANUAL_TODO's header (`:14-16`) says items there "don't gate a release".
- **Fix:** [AI] add a "Release v0.0.7" item to Now with those steps and Q23.1. [Tony] which
  converter checks gate v0.0.7. Proposed: an M1.9 "Converter" step built from M23.1, M23.2, M14.1
  and M15.2 (Mac and lab PC), with M12.1 and M15.1 at the acquisition PC and M16.1 on the Sandy
  Bridge PC.

### 9. No memory result for the converter's settled design; the Live memory contradicts Q18.3 [AI]

- **Where:** `.ai/memory/MEMORY.md`, `.ai/memory/results/` (no converter or caching file);
  `.ai/memory/results/live-monitoring.md:15`; `.ai/memory/results/disk-cache-and-budgets.md:18-19`.
- **What's wrong:** DECISIONS_TODO's rule (`:22-25`) sends settled design to
  `.ai/memory/results/`. Tony's converter decisions are spread across DECISIONS_TODO, the plan,
  `converter.md` and AGENTS.md, and none has a memory result:
  - Q6.3.2, Q6.5, Q6.10 and Q6.11;
  - Q8.6 and Q9.1-Q9.9;
  - Q10.1-Q10.3 and Q11.2-Q11.3;
  - Q16.1-Q16.2 and Q18.1-Q18.6.

  Yesterday's #13 and Q3.5 cover older decisions; this rule already applies to new ones. The
  existing memory files have stale facts too:
  - `live-monitoring.md:15` says "Live greys out the tab's folder explorer". Since Q18.3
    (`dbf80e4`), Live on collapses the whole left panel (`.ai/architecture/live.md:11`). The
    memory also has none of L4's decisions: the auto-convert toggle (Q6.8), one launch folder
    (Q9.6, Q18.3) and the low-count threshold (Q15.3).
  - `disk-cache-and-budgets.md:18-19` says "Only helper processes open the store". AGENTS.md
    `:155` now adds `helab convert`.
  - Q16.1 (no `setup.py` extra) is recorded nowhere but DECISIONS_TODO.
- **Fix:** write `results/txy-converter.md` (Tony's decisions with dates and wording; output
  name and locations; what ships; source modes; settle and damaged rules; profiles and plate
  dates) and `results/caching-v2.md` (Q19.4, Q19.9, Q19.10, Q22.x, Q22.11, "no cache code until
  Tony's go"), and index both in MEMORY.md. Update `live-monitoring.md` for L4 and Q18.3, and
  `disk-cache-and-budgets.md` for `helab convert`.

### 10. AI_TODO: nine done items unticked, A19.x not marked on hold, a duplicate, misfiled items [AI]

- **Where:** `.ai/AI_TODO.md`.
- **Done, not ticked** (the rule at `:23`: tick with the commit):
  - A10.1 settle checks (`:143`; `775fb1d`, `converter.md:198`).
  - A10.2 backend constraints (`:146`; stage 2 landings, e.g. `ed35099`).
  - A10.4 durable writes (`:154`; `io_ops/convert.py:7`, `write_atomic`).
  - A10.5 empty TXY (`:157`; `converter.md:30`).
  - A11.1 packaging (`:163`; `7cb168e`, then `134e2ec`).
  - A11.2 in the helper (`:170`; `io_ops/convert.py:350`, `reconstruct._LOAD_LOCK`). Its "under
    `cache_dir()`" is now temp, Q18.1.
  - A12.3 Live sends the summary back (`:191`; `6454b4a`, `folder_cache.py:1228`).
  - A17.1 no-hit warning (`:234`; `62d156e`).
  - A17.2 two pytest groups (`:238`; `874fd2b`, `ci-test.yml:203` `--test-group`).
- **On hold, not marked:** A19.1 and A19.2 (`:249-252`). Tony: no cache coding until his
  explicit go, "A19.1 and A19.2 included" (`DECISIONS_TODO.md:243-244`). This list is "work
  agents may do without asking" (`:3`), so an agent could pick them up.
- **One item, three IDs:** A18.1 (`:236`, filed under block 17's heading), A23.1 (`:273`) and
  Q14.4 are the same question: does folder status count HeLab's TXY? Both A items say "waits for
  Tony", which belongs in DECISIONS_TODO, not here.
- **Other stale details:**
  - A20.1 cites `tests/conftest.py ~158-161`. The `spread` check is now at `:205-209` (the group
    hook moved it).
  - Block 20's section sits before block 19's (`:241`, `:247`).
- **Fix:** tick the nine with their commits; put "On hold: Tony's go (block 19)" on A19.1 and
  A19.2; drop A18.1 in favour of A23.1, marked "waits for Q14.4"; move the misfiled lines; fix
  A20.1's line reference.

### 11. MANUAL_TODO: converter checks still name backends that left the build, and duplicate each other [AI]

- **Where:** `.ai/MANUAL_TODO.md:134-137`, `:157-164`, `:190-194`, `:199-200`.
- **What's wrong:**
  - **Backends that left the build (Q11.2, `134e2ec`).**
    - M11.1 (`:157-162`) says "the chosen compiled backend once CI builds it (numba too if it
      still ships)". CI builds cython now; numba doesn't ship.
    - M11.2 (`:163-164`) is "superseded by M16.1" (`:192`) but still open.
    - M16.1 (`:190-192`) asks to check `--backend rust` in "the CI Windows build", which no
      longer builds rust.
    - M16.2 (`:193-194`) lists `helab_convert_rs.abi3.so`, libmlx and libllvmlite, none of which
      ship now.
  - **Duplicate checks.** M18.1 (`:136-137`, its own section) checks start-at-launch, as do
    M23.2 (`:199-200`) and the end of M15.1 (`:183-186`). Its basis, Q15.1's
    `live_launch_folders` list, became the single `live_launch_folder` (Q18.3), and A23.3 removes
    the old row.
- **Fix:**
  - Tick M11.2 as superseded.
  - Reduce M16.1 to `--backend cython`, and M16.2 to the cython `_kernel` (the ship floor's own
    item M~1 says a release zip is ≈ 294 MB).
  - Reword M11.1 to numpy and cython.
  - Fold M18.1 into M23.2 (tick it "merged into M23.2") and delete the extra section.

### 12. Live plan and roadmap still describe Live before L4 and Q18.3 [AI]

- **Where:** `roadmaps/live-monitoring.md:114-123`, `:173-183`; `roadmaps/_readme.md:185`;
  `.ai/DECISIONS_TODO.md:565`.
- **What's wrong:**
  - "Live greys out the tab's explorer" (`:121`) is now "Live on collapses the left panel"
    (Q18.3, Q23.2).
  - "The converter's temp-name rename remains the real fix (planned)" (`:118-119`). For
    HeLab's own conversions it is built (`write_atomic`); MATLAB's converter gets no change (Q9.8).
  - L4's decisions (Q6.8, Q9.6, Q18.3, Q15.3) are not under a "Decided" heading in the plan.
  - `_readme.md:185` says "L4 (converter in HeLab) next", while `live-monitoring.md:93` says
    L4's auto-convert, start at launch and alerts are done (`6454b4a`).
  - The index (`DECISIONS_TODO.md:565`) counts 6 open decisions for Live. Its section
    (`:173-183`) has 3 open ones, beside 3 marked decided.
- **Fix:** update those lines, add "Decided in L4 (2026-10-29)" with the four IDs, set
  `_readme.md:185` to "L4 auto-convert done 2026-10-29 (`6454b4a`, `c718c71`); converter stage 5
  replaces MATLAB", and make the count 3.

### 13. known-issues: one entry is stale, and one RERUN occurrence is missing [AI]

- **Where:** `roadmaps/known-issues.md:33-36`, `:115-124`.
- **What's wrong:**
  - "The temp folder (`DIR_TEMPS`) … nothing uses it … Remove the setting, or move helper
    folders into it" (`:33-36`). Since stage 4, HeLab's converted TXY can go there
    (`folder_cache.py:928`, `:1216`; `convert_cli.py:213`), and numba's cache too (Q18.1). Removing
    the setting is no longer an option. The remaining gap is only that helpers' private folders
    use the system temp folder.
  - `test_analysis_gui.py::test_another_library_draws_the_plot_again_without_a_rerun` reran
    again on macOS CI run 40765484151 (packaging handoff `:136-138`; its reason was lost when the
    job was cut at its 20-min limit). The entry at `:115-124` records only the 2026-10-28 run.
  - Every other RERUN in the 2026-10-29 session notes is listed or fixed. The CI run on `99d3ba5`
    (40806199913) had no RERUN in any of its six test jobs (logs checked). The run on `36e3d6c`
    was still in progress during this audit.
- **Fix:** reword the temp-folder entry; add the second occurrence to the 2026-10-28 entry, or
  make it an entry of its own.

### 14. ID_BLOCKS rows 19 and 22 lack the provisional-to-final mapping; small ID oddities [AI]

- **Where:** `.ai/ID_BLOCKS.md:54`, `:57`; `.ai/DECISIONS_TODO.md:216`, `:234`, `:313`.
- **What's wrong:**
  - The rule (`ID_BLOCKS.md:20-23`) asks for the provisional-to-final mapping. Row 19 says
    "Q19.1-Q19.10, A19.1, A19.2", but the audit's items were Q~1-Q~8 and A~1-A~3: A~1→A19.1,
    A~3→A19.2, and A~2 (build Q18.1) was dropped as built. Q19.9 and Q19.10 came later from
    Tony's Chat. Row 22 is the same: the design note's Q~1-Q~10 became Q22.1-Q22.10, and Q22.11
    and A22.1 came from Tony's answers, not the note.
  - **The block 19/20 clash.** It was resolved (row 20 says QF6's A19.1 became A20.1), and no
    doc in scope still uses the old meaning. `git log --grep=A19.1` will still find `6fcf012`
    for the wrong item, and row 20 says so. No other renumbering of blocks 19-23 shows in the
    history of `ID_BLOCKS.md`.
  - Q14.4 and Q14.5 are written in bold a second time in block 18 (`:216`, `:234`), so they
    read as new entries.
  - Q22.11 sits between Q22.7 and Q22.8 (`:313`).
- **Fix:** add the mappings to rows 19 and 22; un-bold the re-mentions; sort Q22.11 last.

### 15. Cross-plan inconsistencies around store-v4 [AI]

- **Where:** `roadmaps/_readme.md:46-48`, `:227-229`; `roadmaps/caching-v2.md:3`;
  `roadmaps/known-issues.md:17-24`.
- **What's wrong:**
  - **Pickle-free datasets.** The roadmap keeps "Dataset format without pickle … Kept as pickle
    for now" under Unchosen ideas (`:227-229`), while the store-v4 design plans exactly that
    (`.hlb`) and known-issues present store-v4 as the fix for both the pickle risk and the 2.1 GB
    limit.
  - **Horizon.** Caching v2 is listed under "Now: v0.0.7" (`:46-48`), but its own horizon is
    "after v0.0.7's converter" (`caching-v2.md:3`).
- **Fix:** point the unchosen idea at caching v2 ("planned in store-v4, not approved"). Say on
  the Now item that v0.0.7 covers its planning only, with building to follow Tony's go.

## Checked and fine

- Every commit hash cited in `_readme.md`, `txy-converter.md` and known-issues for 2026-10-28/29
  is an ancestor of `HEAD`.
- No duplicate ID definitions in the three lists (only the bold re-mentions in #14).
- AGENTS.md's write rule and housekeeping line match Q18.4 and Q18.6 and the code
  (`file_kinds.py:33`); converter.md is current for Q18.x and Q23.x.
- caching-v2 is consistently "planning only, no cache code"; no cache code landed after Tony's
  instruction (since `c513a78`, `cache_store.py` is unchanged; `folder_cache.py` changed only in
  the follow-ups' Q18.2/Q18.4 commits `26a2ade`, `dda90fd`, `163f4f3`, `c0011b0`).
- A21.1, A20.1, A15.2, A15.3, A14.2, A13.1, A12.1 and A12.2 are still open in the code, as listed.
