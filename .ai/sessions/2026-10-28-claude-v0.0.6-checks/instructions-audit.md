# Audit of agent instructions: AGENTS.md, CLAUDE.md and Maestri roles (2026-10-28)

This audit was read-only and nothing was changed. Tony asked for it in Chat. It was done on Ground
at `927de44`, plus the uncommitted `.ai/DECISIONS_TODO.md` and `.ai/AI_TODO.md`. The Assistant
checked the roles and the CLAUDE.md files itself. An agent read AGENTS.md as instructions; it
didn't check whether its code names are current (the [first audit](audit.md) did that). The
Assistant checked its main claim: `~/.codex/config.toml` doesn't set `project_doc_max_bytes`,
and the first 32 KiB of AGENTS.md end at line 134.

Each finding is tagged [Tony] (a decision, also in [DECISIONS_TODO](../../DECISIONS_TODO.md))
or [AI] (mechanical, also in [AI_TODO](../../AI_TODO.md)).

## AGENTS.md (92 KB, 203 lines, ~23k tokens in every agent)

1. **Codex reads only the first third of it.** By default Codex loads 32 KiB of project
   docs, and this Mac doesn't raise the limit. The cut falls at line 134, so Codex agents
   never see:
   - Caching ("only helpers open the store", "nothing is removed without asking");
   - Threading;
   - the UI rule that rendering never reads disk;
   - Settings persistence;
   - CI.

   Codex reviewers (e.g. Feeler) were asked to check "the codebase rules in AGENTS.md", and
   half of those rules never reached them. Fix: restructure under 30 KB (item 2). As a stopgap,
   move the must-follow rules to the top and raise Codex's limit. [Tony]
2. **Restructure it as rules plus a map**, targeting ~24 KB with a 30 KB cap:
   - header;
   - **Rules for every task** (~3 KB);
   - **Where things go** (a routing table);
   - commands;
   - a code map with one line per module family;
   - area invariants: 3–6 bullets per area, each ending "Design: <doc>";
   - a design-doc index.

   Of today's text, about 20 KB are invariants (~9 KB once terse), ~45 KB design description
   and ~22 KB UI wording, history and per-plot detail. Much of the description exists only here
   (`HeldWrite`, `mismatch_hold`, `OFFLINE_OPERATIONS`, `confirm_dataset`, `UnitSpinBox`,
   `PresetBar`, `FolderWait`, `verified_volumes`, `tidy_logs`…). It must move into
   `.ai/memory/results/` or the roadmap plans, not be deleted. [Tony: go-ahead; AI: a docs-only
   floor after the release]
3. **Must-follow rules are buried in long paragraphs:**
   - "report any RERUN" and "never import helab before conftest" (line 60, 2.6 KB);
   - "nothing is removed without asking" (mid-149, 8.5 KB);
   - "never reads disk during rendering" (end of 161).

   Item 2 fixes this. [AI]
4. **"Nothing is removed without the user asking" contradicts automatic housekeeping** in the
   same file:
   - the sweep deletes orphan store files after 1 h;
   - pending saves and results expire after 1 h;
   - old diskcache folders are deleted at start;
   - logs beyond 300 are deleted;
   - the mismatched list drops its oldest entries;
   - RAM eviction.

   Scope the rule to the user's data and records, and list the exceptions. [Tony: the wording]
5. **Line 12 contradicts line 24 and AI_TODO.** Line 12 says to offer `_readme.md` items and
   start only after Tony agrees; AI_TODO says agents do its items without asking. Proposed:
   offer roadmap and known-issues items, and do AI_TODO items. [Tony]
6. **Where decisions go.** Line 23 lists AGENTS.md as a place for decisions, while line 25
   says settled decisions go to memory results and "this file keeps only the codebase rules"
   (it's unclear which file). AGENTS.md has 9 inline "(Tony, date)" decisions. Proposed:
   decisions live in memory results, and AGENTS.md states the rule and links there. [Tony]
7. **Internal contradictions and ambiguities.** [AI]
   - Line 155, "online browsing still lists every folder", contradicts lines 123 and 124
     (selecting a folder with saved counts and a cache, or a RAM-held leaf folder, doesn't
     list it).
   - Three different "settle"s: `SETTLE_SECONDS` (files being written), `settle_seconds` /
     `SETTLE_MAX` (the selection) and Live's "settled by age". They need a glossary line.
   - Lane counts: "two source-I/O lanes", then "background lanes", then "a third, local
     lane". Say it once: three lanes (foreground, background with N slots, local with 2
     slots).
8. **Missing guidance.** [AI]
   - The floor rule: workers never edit AGENTS.md, roadmaps, MANUAL_TODO, memory or the two
     new lists. It's only in the workflow docs.
   - A routing table: bug, feature, manual check, agent chore, question for Tony, settled
     decision, evidence.
   - A definition of done: the checks for a small change, and the checks before a handoff
     (`test_typing.py` already runs mypy and pyright inside pytest).
9. **CodeGraph is required but isn't there.**
   - Line 13 and `.cursor/rules/codegraph.mdc` (alwaysApply, "This project has a CodeGraph MCP
     server configured") assume it.
   - There's no `.codegraph/`, no MCP server and no `codegraph_*` tools on this Mac.
   - `maestri-setup.md` §0 points at a `~/.claude/CLAUDE.md` that doesn't exist.

   Proposed: "if `codegraph_*` tools are available…". [Tony]
10. **References that only work on Tony's Mac or in some checkouts.**
    - `.ai/coding-workspace.md` (line 17, and MEMORY.md's first line) is a committed symlink
      to `/Users/tonyyan/Documents/GitHub/ai-common/…`.
    - `.ai/session-export-*/` (line 26) is absent here.

    [Tony: the ai-common copy; AI: "if present"]
11. **Smaller points.**
    - Commit format: the log's "Area: summary" subject style isn't stated. [Tony]
    - Submodules: Setup names one of three, and `--recursive` pulls ~440 MB more; say whether
      floors and tests need them. [Tony]
    - Line 3 says "development branch" where it means the development repo. [AI]
    - A size rule, so the file doesn't grow back: a new feature adds at most one invariant
      line and a pointer. [Tony]
    - The one stale code name: `CacheTab.confirm` is `_confirm`. [AI]

## CLAUDE.md files

12. **The repo's `CLAUDE.md` is only `@AGENTS.md`.** Every Claude session, and every
    subagent, loads all 92 KB. That's fine once item 2 brings it to ~24 KB. Nothing else to
    change.
13. **Role folders.** Maestri writes the `CLAUDE.md`, `AGENTS.md` and `role.json` in
    `.maestri/roles/<id>/` (gitignored). They match the live Coordinator and Assistant roles
    word for word.
14. **There's no global `~/.claude/CLAUDE.md` on this Mac**, though `maestri-setup.md` §0
    step 8 says to copy one from the existing Mac. Either drop the step or say what it should
    hold. [Tony, with item 9]
15. **The Claude memory folder is a symlink to `.ai/memory`, so Claude loads MEMORY.md by
    itself, but Codex must read it.** AGENTS.md line 25 ("Read it first") is right for Codex,
    redundant for Claude. No change.

## Maestri roles (Coordinator, Worker, Reviewer, Assistant, Quick Fixer)

16. **The Quick Fixer role is documented nowhere** (not in `maestri-setup.md` §2 or
    `agent-workflow.md`). Two of its rules differ from Worker's:
    - "don't push unless told", where Worker says "push once when done";
    - a session folder of `<date>-claude-<task>`, where Worker's is `<date>-<tool>-<task>`.

    [Tony: the push rule; AI: the docs]
17. **The new lists aren't in any role.** Proposed:
    - Worker, Quick Fixer and Reviewer never edit `DECISIONS_TODO.md` / `AI_TODO.md`; they
      propose entries in their handoff.
    - The Coordinator applies them when landing.
    - The Assistant writes Tony's answers into DECISIONS_TODO and moves decided items out.
    - Every agent adds a question to DECISIONS_TODO, or proposes one, instead of guessing.

    [AI, once Tony agrees to the lists]
18. **The branch rule is in no role.** The Coordinator lands floors, but "keep agent branches
    on GitHub" lives only in memory, and `maestri-setup.md:459` says to delete them. [Tony,
    DECISIONS_TODO K]
19. **The Assistant role names `dev/v0.0.6`.** It goes stale at the next version. Say "the
    current dev branch (roadmap's Now)". [AI]
20. **The Assistant role says "edit docs and this guide".** It doesn't say which guide;
    name `.ai/maestri-setup.md`. [AI]
21. **"Address the user as 🎓Tony" is in no role**, and the Coordinator's and Assistant's
    Chat posts don't use it. The Assistant hasn't either. Proposed: apply it to direct replies to
    Tony (Chat answers), not to progress lines or agent-to-agent messages. [Tony]
22. **Worker's and Quick Fixer's "Don't launch the HeLab GUI"** can go if floors get their own
    settings file (DECISIONS_TODO N). [Tony]
23. **Reviewer:** "check the codebase rules in AGENTS.md" fails for a Codex reviewer until
    item 1 is fixed. Until then, the brief should paste the rules block. [AI, stopgap]

**Fine as they are:**
- The Coordinator, Worker, Reviewer and Assistant prompts match the guide's §2 texts.
- The repo-root-first line is in every role.
- Commit asking, Ground edits and Chat posting agree across the roles and AGENTS.md.
- The role-folder files are regenerated from the live roles.
