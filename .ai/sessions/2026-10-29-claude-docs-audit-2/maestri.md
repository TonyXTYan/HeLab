# Audit of the Maestri setup, after the overnight run (2026-10-29, afternoon)

Read-only. Done on Ground, `dev/v0.0.7` at `36e3d6c` (= origin), with a clean working tree. Only
read-only commands were used: `maestri list`, `role list`, `role show` (all five roles),
`floor list`, `preset list` and `preset show`, `note read "Active work"` and `help floor`, plus
`git worktree list`, `git branch`, `git ls-remote` (no fetch), `git log` and `git reflog`. No
Maestri state was changed and no agent was messaged.

What I compared: tonight's lessons (the mandate's log, the briefs, the commits) against
`.ai/maestri-setup.md` (the guide), `roadmaps/agent-workflow.md` (the workflow), AGENTS.md:19-40
and the live roles. I don't repeat the items that the previous audit
(`.ai/sessions/2026-10-28-claude-docs-audit/maestri.md`) reported and that have since been fixed.

Tags: **[AI]** marks mechanical work. **[Tony]** marks a decision that is Tony's.

## What checks out

- **The live roles match the guide.** All five live roles (Coordinator, Worker, Reviewer,
  Assistant, Quick Fixer) match the guide's §2 copies word for word, after whitespace is joined.
  The only difference is the `Role: <Name>` header that `role show` adds. The two role folders on
  Ground (Assistant `19b8…`, Coordinator `3b67…`) are present.
- **Yesterday's fixes are in place:**
  - `--keep-branch` / no `--delete-branch` (guide §7 and the Coordinator role);
  - "the current dev branch" in place of `dev/v0.0.6`;
  - the floor-only packages rule;
  - hook 1's symlink guard;
  - hook 5b (the settings file);
  - the Reviewer's check that it is on a floor;
  - the Quick Fixer's `M~1`, written in its handoff;
  - the push-at-checkpoints rule, in AGENTS.md:22-24, the workflow (:30-33, :104-106) and the
    Worker and Quick Fixer roles.
- **Git is in order:**
  - 16 worktrees, one for each floor. Every one has a clean working tree, with nothing untracked
    either.
  - Every floor branch is an ancestor of `dev/v0.0.7`, so all 16 have landed.
  - All 26 local `agent/*` branches have the same commit on GitHub (checked live with
    `git ls-remote`). That includes the six that were behind yesterday (Q2.2.3, done).
  - `dev/v0.0.7` = origin. The only mismatch is local `main`, which is 2 commits behind
    `origin/main` (harmless).
- **Leftovers are gone:**
  - `~/Library/Caches/HeLab/floors/` holds 4 folders, each for a floor that still exists. The two
    leftovers reported yesterday are gone.
  - The orphaned pytest (pid 15027) is gone.
- **AGENTS.md** is 18.4 KB, within Codex's 32 KiB.

## Findings

1. **No document lists the landing conditions, including tonight's "branch CI green on all three
   OSes, checked by run ID".** [AI]
   - **Where they're missing:**
     - Guide §6, `.ai/maestri-setup.md:550-572`, covers how to land, not when.
     - Workflow step 5, `roadmaps/agent-workflow.md:101-102`, says only "reviews … and asks Tony
       before landing".
     - The Coordinator role (guide :128-158) names no conditions.
   - **Where they exist today:**
     - The mandate (`.ai/sessions/2026-10-29-claude-v0.0.7-overnight/mandate.md:18-21`) set the
       first conditions. The new CI rule was added only after the miss at :278. There,
       helab-core landed with its own branch runs red on Windows (Windows-only typing errors and
       3 tests), and `01776d6` and `e4a63b5` went red on `dev/v0.0.7`.
     - Briefs repeat the rule one by one (`txy-followups/brief.md:55-56`,
       `quick-fixes-6/brief.md:33`).
   - **Related lessons that are also only in briefs or the log:**
     - **Windows typing.** Briefs added `mypy --platform win32` and
       `pyright --pythonplatform Windows` (`txy-followups/brief.md:50`). AGENTS.md:87 and the
       roles still say only "strict mypy and pyright".
     - **Keep the suite's whole output.** At mandate:277 a RERUN on Ground at `e9c5bfa` went
       unaccounted for, because CoCo's output filter dropped it.
     - **CI now has more jobs.** It runs two test groups per OS (`ci-test.yml:123`, "Tests
       (1/2)" and "(2/2)") plus a "Converter backends" job (:34). "Green" has to cover all of
       them, plus the build.
   - **Fix:** add a "Landing conditions" list to guide §6 and the workflow's step 5. Give the
     Coordinator role one clause: "land only when guide §6's conditions hold". The list:
     1. the Reviewer has no open findings;
     2. the branch contains the current dev branch;
     3. the branch's latest CI run is green on macOS, Windows and Ubuntu (both test groups, the
        backends job and the build), checked with `gh run view <id>` and quoted by run ID;
     4. the full suite on the merged tree passes, with output kept whole in `.ai/temp/<name>.txt`
        and every RERUN named and explained or filed;
     5. `mypy --strict` (also with `--platform win32`) and `pyright` (also with
        `--pythonplatform Windows`) pass;
     6. Ground is clean (finding 4).

     Add the two Windows type checks to AGENTS.md:87 and to the Worker, Reviewer and Quick Fixer
     test lines (guide :198-200, :221-222, :264-266). The Worker's done-report should name its
     green run ID.

2. **Overnight, unattended supervision isn't a documented mode. The Coordinator role contradicts
   how it ran, and the register still says the mandate is in force.** [Tony for the mode and
   wording; AI for the draft]
   - **How it ran:** the mandate is the only record. Under it, Side approved floors, recruits,
     landings and pushes "on Tony's behalf, tonight only" (mandate:14-25), with a "Never tonight"
     list (:27-37) and a decision log (:66+).
   - **What the role says:** the Coordinator role (guide :134-136) says "ask Tony before creating
     a floor or recruiting, and before landing a floor". Neither role allows delegating that.
   - **The register is stale:** the "Active work" note, line 23, still says "Overnight
     2026-10-29: Side approves for Tony per the mandate; reports go to Side, not Chat". The run
     is over, and that line conflicts with the Coordinator role's "Tony reads Maestri Chat …
     `maestri say --progress`".
   - **Undocumented:**
     - who pushes the dev branch, and when (CoCo pushed `dev/v0.0.7` after every landing,
       origin's reflog 04:59-15:00);
     - heartbeats;
     - what to do near an account limit or a full context (mandate:101-104 "5h:99%", :280
       "context at 60 %").
   - **Fix:** add a "Supervised runs (Tony away)" section to the workflow, built on the mandate's
     pattern:
     - Tony's words, quoted, with a start and an explicit end ("until Tony is back in Chat");
     - the scope, the approvals delegated to the Assistant and the never-list;
     - only reversible choices, and nobody answers an agent's permission prompt;
     - a decision log marked "for Tony to confirm", carried into DECISIONS_TODO at the end;
     - landing conditions as in finding 1;
     - pushes only at landings;
     - heartbeats, a morning report, and the register line removed when the run ends.

     Give the Coordinator and Assistant roles a clause each: "… unless a written mandate in
     `.ai/sessions/` delegates it; it ends when Tony says so". Whether this becomes a standing
     mode is Tony's call (proposed Q).

3. **Codex Reviewers can't run unattended, yet the guide still prescribes them.** [Tony for the
   Codex setting; AI for the text]
   - **What the guide says:**
     - :227-228 "Recruit the Reviewer with the other model from the worker's (Codex reviews
       Claude's work …)";
     - :481-483 `--preset "Codex" --role "Reviewer"`;
     - the workflow (:47-49) says "a different model … where possible".
   - **What happened:** at mandate:96-100, Kestrel (Codex) stalled on its first approval prompt
     (`maestri list` / `floor status`). It was replaced in place by Heron (Claude). All 16 of
     tonight's Reviewers were Claude (`maestri role list`).
   - **Two likely causes:**
     - **Floors aren't trusted.** `~/.codex/config.toml` trusts only `…/HeLab` and
       `…/PencilMaps`, and floors live in `…/GitHub-Local/.maestri/floors/`.
     - **Every command is compound.** The roles make each command start with
       `cd "$(git rev-parse --show-toplevel)" && source …`, a compound shell command. Codex's
       `prefix_rule(["maestri"])` (`~/.codex/rules/default.rules`) doesn't match such wrappers
       (memory `results/maestri-chat-and-codex.md`).
   - **Still to settle:**
     - Guide :99-102's **(check)** has its answer now.
     - The mandate's "For Tony" item on this was never carried to DECISIONS_TODO (no Codex item
       there).
   - **Fix:**
     - Guide :227 and :481: "Codex reviews only while Tony is at the screen; unattended, recruit
       a Claude Reviewer (a fresh terminal, never the author)". Replace :99-102's (check) with
       the finding.
     - Add a Q: (a) trust `~/GitHub-Local/.maestri/floors` in Codex and/or set its approval
       policy for floors; (b) keep Codex for attended reviews only; (c) drop Codex reviewers.
       Proposed: (b) now, (a) only if Tony accepts the sandbox trade-off.

4. **Ground must be clean before a landing and before a new floor. The guide says so only for
   Maestri's Merge Locally.** [AI]
   - **What the guide says:** :530-532, "Commit before landing … Merge Locally is refused while
     Ground has uncommitted changes".
   - **How landings actually ran:** none of tonight's 16 used Maestri. All were plain
     `git merge` on Ground (`git reflog dev/v0.0.7`: "merge agent/txy-…: Fast-forward / Merge
     made by the 'ort' strategy"), and `git merge` doesn't refuse unrelated uncommitted work.
   - **Uncommitted work got mixed in:**
     - The Assistant's 43 KB log sat uncommitted on Ground and had to be committed by CoCo with
       the landing docs ("committed with this log", mandate:273, :300).
     - CoCo's `6fcf012` swept in "Side's DECISIONS_TODO edit" (its own commit message).
   - **New floors copy Ground's files as they are.** `maestri help floor`: "the ground's files,
     dependencies included, are cloned into it". Every floor's `.ai/temp` holds Ground's
     `kestrel-brief.md` and `pytest-coco/` (finding 7), so whatever is uncommitted or untracked
     on Ground goes into a new floor.
   - **Fix:**
     - In the Coordinator role and guide §5 step 1 / §6: before `floor create` and before any
       landing, `git status --porcelain` must be empty. If it isn't, ask whoever made the change
       (the Assistant or Tony) to commit or hold it; never fold it into a landing commit.
     - In "Work on Ground": during a run, the Assistant keeps logs and drafts outside the tree
       (`.ai/local/` or a Maestri note) or commits them at once.

5. **Two Ground agents took the same block ID, and the fix changed an ID that was already
   published.** [AI; Tony for whether a published ID may move]
   - **The rule:** `.ai/ID_BLOCKS.md:20-24` says the merger "takes the next block number", with
     no reservation step, although CoCo and the Assistant (and its subagents) write the same
     working tree.
   - **What happened:**
     - `6fcf012` (CoCo, 12:36, pushed 12:36:57) took block 19 for Quick Fixes 6, with A19.1.
     - `c513a78` (Side's caching-audit subagent, 12:45) also wrote a block 19 row; its items
       had been numbered before it read HEAD.
     - `f405de0` moved CoCo's A19.1 to A20.1 (ID_BLOCKS.md:55). That breaks :13, "An ID never
       changes", for an ID that was already on GitHub.
   - **Fix:** in ID_BLOCKS.md "Who writes what", and in one clause each in the Coordinator and
     Assistant roles:
     - write the block's row ("reserved") in Ground's working tree before numbering any item;
     - a subagent gets its block number from its parent before it starts;
     - re-read ID_BLOCKS.md at HEAD just before committing;
     - on a clash, the uncommitted side renumbers.

     The rename itself stays recorded in row 20.

6. **All 16 floors are kept after landing; 15 can go.** [Tony]

   | Floor | Status shown | State |
   |---|---|---|
   | TXY numpy, TXY numba, TXY cython, TXY rust, TXY mlx | done | landed, clean, pushed |
   | TXY bench | review (stale) | landed (`3bd791c`), clean, pushed |
   | TXY helab-core | review (stale) | landed (`6cbe446`), clean, pushed |
   | TXY live, TXY ui, TXY packaging | done | landed, clean, pushed |
   | Quick Fixes 4, Quick Fixes 5 | done | landed, clean, pushed |
   | Quick Fixes 6 | review (stale) | landed (`879f4d0`), clean, pushed |
   | TXY ship | review (stale) | landed (`8dcb19f`), clean, pushed |
   | TXY followups | review (stale) | landed (`c0011b0`), clean, pushed |
   | **TXY Reference** | done | **keep** until M11.3: its `.ai/temp/txy/matlab-2023/` is the only 2023 reference set, and `~/HeLab-samples/` has no copy yet |

   - **Safe to delete:** for every floor, `git merge-base --is-ancestor <branch> dev/v0.0.7`
     holds, `git status --porcelain` is empty, and local = GitHub.
   - **The command:** `maestri floor delete "<Name>" --keep-branch`, from Ground (Tony, or CoCo
     with his OK).
   - **Afterwards:** check that `~/Library/Caches/HeLab/floors/` has dropped the "Quick Fixes 4",
     "TXY helab-core", "TXY live" and "TXY ui" folders (§7).
   - **Leave alone:** the two `PencilMaps--…` floors in the same folder belong to another
     project.
   - **What the docs lack:** a rule for how long a landed floor is kept. Proposed for §6/§7:
     "keep a landed floor only for a named reason (written in its status); delete it with
     `--keep-branch` once that is done".
   - **`floor list` can't show unloaded floors.** It doesn't say which floors are unloaded; the
     register says stage 2, bench, live, ui, packaging and QF4 are.

7. **`.ai/temp` isn't excluded from floors created from the command line, so every floor carries
   Ground's 2.8 GB of scratch.** [AI for the guide; Tony applies the hook in the app]
   - **What the guide says:**
     - :374-376 says `.ai/temp` "is excluded from the clone";
     - :447-449's Excluded folders is an option of the UI's create dialog;
     - `maestri floor create` has no exclude flag, and tonight's floors were made from the CLI.
   - **Evidence:**
     - Every floor's `.ai/temp` has Ground's `kestrel-brief.md`, `pr-body.md` and
       `pytest-coco/`.
     - Apparent sizes run from 3.4 GB to 15 GB per floor. The clones are copy-on-write, so
       less of that is on disk.
     - Ground's `.ai/temp` is 2.8 GB, up from 386 MB yesterday (Q2.1.2 "stays").
   - **Side effect:** copies of AGENTS.md and the guide under `.ai/temp/pytest-*/…/checkout/`
     show up in a `grep -r .ai` (they did in this audit).
   - **Fix:**
     - Hook 3 empties the floor's `.ai/temp` before recreating it. It takes the same floor ≠
       root guard as hooks 1 and 6, e.g.
       `cd "$MAESTRI_FLOOR_PATH" && [ "$MAESTRI_FLOOR_PATH" != "$MAESTRI_ROOT_PATH" ] && rm -rf .ai/temp && mkdir -p .ai/temp .ai/local && …`.
     - Reword :374-376 and :447-449: Excluded folders applies only in the UI.

8. **How landings actually happen isn't documented.** [AI]
   - **What the guide documents:** §6 covers only the UI and `maestri floor land … --into`. That
     command deletes the floor unless `--keep-floor`, a flag the guide doesn't name (:562 gives
     only the UI tick box).
   - **What happened:** every landing tonight was `git merge agent/<task>` on Ground, a
     fast-forward when the branch already contained the dev branch. That leaves the floor and
     its status in place, so five floors still say "review" (finding 6).
   - **Fix:**
     - Document both routes in §6.
     - Name `--keep-floor`.
     - After any landing: `maestri floor status --floor "<Task>" "Landed <sha>" --state done`,
       and update the register.
     - Never pass `--delete-branch`, as the guide already says.

9. **The "Active work" register is stale.** [AI, for the Coordinator]
   - **Line 16:** TXY followups shows "briefed (Tony: go)", but it landed (`c718c71`).
   - **Line 23:** "Ground … at `4132e36`" (it is now `36e3d6c`), and the mandate line from
     finding 2.
   - **Lines 30-36 ("Open"):** v0.0.6-era items, such as "no floors until answered" and the
     v0.0.6 draft.
   - **Line 38 ("Branches kept on GitHub"):** lacks the 16 new `agent/*` branches.

10. **Two agents on one floor share a test folder.** [AI, low]
    - **The setup:** the workflow (:27-33) and the roles assume one Worker per floor. Stage 1 ran
      two Workers on "TXY Reference": Forge, the builder, and Lens, the cross-checker
      (mandate:41-43).
    - **The clash:** the Worker role's `--basetemp=.ai/temp/pytest` is the same for both, and
      pytest empties its basetemp, so concurrent runs clear each other.
    - **Fix:** a guide line in §5: "a second agent on a floor gets its own basetemp
      (`.ai/temp/pytest-<name>`) and session subfolder, and the brief says which paths it may
      commit".

11. **The guide doesn't say what lets Claude recruits run without prompts.** [AI, (check)]
    - **The facts:**
      - the "Claude Code" preset runs a bare `claude`;
      - `~/.claude/settings.json` has no `permissions` or `defaultMode`;
      - Claude recruits ran all night without stalling, and Codex didn't.
    - **Why it matters:** a new machine (§0) wouldn't reproduce this.
    - **Fix:** find out the mode Maestri or Claude Code uses (auto mode?) and add it to §1 step 5
      or §5 step 2, next to the Codex note from finding 3.

12. **Small points.** [AI]
    - **`maestri floor unload` has no command in the guide.** The CLI has
      `maestri floor unload "<Name>"`, but guide :580 says "Unload idle floors" without it.
    - **`floor create --copy` is now explained** in `help floor`: an independent APFS copy, Mac
      only. `--copy-ground` is still unexplained (:468, (check)).
    - **(check) markers still open from the last audit:** :415 (the bytecode hook on a real
      floor; 16 floors ran tonight alone) and :445 (a failing step).
    - **The new `.ai/sessions/<date>-<tool>-<task>/` pattern** of a cross-checker writing
      `crosscheck/` inside the builder's session folder (txy-reference) works, but isn't
      mentioned anywhere.
