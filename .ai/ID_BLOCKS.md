# ID blocks

This file is the registry of blocks for the IDs in [DECISIONS_TODO](DECISIONS_TODO.md) (`Q`),
[AI_TODO](AI_TODO.md) (`A`) and [MANUAL_TODO](MANUAL_TODO.md) (`M`).

**ID format:** `<letter><block>.<item>[.<sub>]`, e.g. `Q1.2`, `A2.3`, `M1.5` or `Q2.2.1`.

**Blocks:**
- A block is one task or session: a floor, a cloud agent, or an Assistant or Coordinator
  session on Ground.
- The three lists share one block counter.
- Item numbers count within their own letter.
- An ID never changes and is never reused, even after its item is decided, done or dropped.

**Who writes what:**
- Only Ground writes this file and the three lists, which means the Coordinator, the Assistant
  or Tony.
- Floors and cloud agents number their proposals provisionally in their own session folder:
  `Q~1`, `A~1`, `M~1`.
- When it merges them, the Coordinator or the Assistant:
  - takes the next block number;
  - adds a row here with the mapping, e.g. `Q~1→Q5.1, A~1→A5.1`;
  - copies the items into the lists with their new IDs.
- A session on Ground that adds items takes a block before it adds the first one.

**References:** commits, briefs, handoffs and Chat refer to items by ID ("Fixes A2.2", "Q1.2:
yes"), so `git log --grep=A2.2` finds an item's history. Audit reports keep their own finding
numbers (#N), because they are snapshots that are never edited.

Decisions are `Q` (question), not `D`, so they don't clash with the DLD port's D1–D15 (Tony,
2026-10-28). Other feature IDs (Live's L1–L5, result caching's R1–R5) have no dot after the
number.

| Block | Date | Agent (tool) | Task, session | Branch | Provisional → final |
|---|---|---|---|---|---|
| 1 | 2026-10-28 | Side (claude), Ground | v0.0.6 release: decisions, smoke pass, AI tasks (`sessions/2026-10-28-claude-v0.0.6-checks/`) | dev/v0.0.6 | first use, old letters A–I → Q1.1–Q1.9 (first D1.x, renamed to Q the same day), numbers 1–8 → A1.1–A1.8; the smoke pass's steps → M1.1–M1.8 |
| 2 | 2026-10-28 | Side (claude) + 3 subagents, Ground | audit of agents, roles, docs and logs (`…/audit.md`) | dev/v0.0.6 | old letters J–Q → Q2.1–Q2.8, 9–13 → A2.1–A2.5 |
| 3 | 2026-10-28 | Side (claude) + subagent, Ground | instructions audit (`…/instructions-audit.md`) | dev/v0.0.6 | old letters R–W → Q3.1–Q3.6, 14–16 → A3.1–A3.3 |
| 4 | 2026-10-28 | Side (claude), Ground | the ID scheme itself (Tony in Chat) | dev/v0.0.6 | Q4.1 |
| 5 | 2026-10-28 | Side (claude), Ground | automating the smoke pass with computer use (`sessions/2026-10-28-claude-smoke-automation/plan.md`) | dev/v0.0.6 | A5.1, Q5.1, Q5.2 |
| 6 | 2026-10-28 | Side (claude), Ground | wrapping up v0.0.6, v0.0.7's scope (Tony in Chat) | dev/v0.0.6 → dev/v0.0.7 | Q6.1–Q6.12 (Q6.12 numbered later, by block 7) |
| 7 | 2026-10-28 | Side (claude) subagent, Ground | planning-docs audit fixes (`sessions/2026-10-28-claude-docs-audit/planning.md`) | dev/v0.0.7 | A7.1, A7.2 |
| 8 | 2026-10-28 | Side (claude) + 3 subagents, Ground | docs and Maestri audit (`sessions/2026-10-28-claude-docs-audit/`), Tony's answers in Chat | dev/v0.0.7 | Q8.1–Q8.6, A8.1, M8.1 |
| 9 | 2026-10-29 | Side (claude), Ground | what building the converter needs (Tony in Chat) | dev/v0.0.7 | Q9.1–Q9.9, A9.1 |
| 10 | 2026-10-29 | Forge, Lens (claude), floor TXY Reference; merged by CoCo | converter stage 1 (`sessions/2026-10-29-claude-txy-reference/`) | agent/txy-reference | Forge Q~1 + Lens Q~2→Q10.1, Forge Q~2→Q10.2, Lens Q~1→Q10.3; Forge A~2→A10.1, Forge A~3 + Lens A~3→A10.2, A~4→A10.3, A~5→A10.4, Forge A~1→A10.5; M~1→M10.1; Lens A~1, A~2 done on the floor (F1, F2) |
| 11 | 2026-10-29 | Abacus, Ember, Anvil, Ferrous, Prism, Tally (claude), floors TXY numpy/numba/cython/rust/mlx/bench; merged by CoCo | converter stage 2 (`sessions/2026-10-29-claude-txy-{numpy,numba,cython,rust,mlx,bench}/`) | agent/txy-{numpy,numba,cython,rust,mlx,bench} | numba Q~1→Q11.1; bench Q~1 + cython Q~1 + rust Q~1→Q11.2; bench Q~2→Q11.3; numpy Q~1 (releases_gil stays False) decided by CoCo, technical; numba A~1 + cython A~1/A~3 + rust A~1 + mlx A~1/A~2→A11.1; numba A~4 + mlx A~3 + numpy A~2 + bench A~2→A11.2; numba A~5→A11.3; bench A~1 + numpy A~3→A11.4; numba A~3 dropped (numba's pieces could use split.py; moot if numba goes); numpy A~1, cython M~1, rust A~2 done by the bench; bench M~1 + M~2 + numba M~1→M11.1; rust M~1→M11.2; bench A~3→M11.3 |
| 12 | 2026-10-29 | Keel (claude), floor TXY helab-core; merged by CoCo | converter stage 4 core (`sessions/2026-10-29-claude-txy-helab-core/`) | agent/txy-helab-core | Q~1–Q~7→Q12.1–Q12.7; A~1→A12.1, A~2→A12.2, A~5→A12.3; A~3 = A11.3, A~4 = A10.3 (the UI floor's), A~6 = the main-window known issue (Quick Fixes 4); M~1→M12.1; fix round: Gannet's (b)→A12.4 |
| 13 | 2026-10-29 | Mender (claude), floor Quick Fixes 4; merged by CoCo | four CI-flaky tests (`sessions/2026-10-29-claude-quick-fixes-4/`) | agent/quick-fixes-4 | A~2→A13.1; A~1 is a bug, filed in known-issues (App) |
| 14 | 2026-10-29 | Facet (claude), floor TXY ui; merged by CoCo | TXY source choice, profile manager (`sessions/2026-10-29-claude-txy-ui/`) | agent/txy-ui | Q~1–Q~5→Q14.1–Q14.5; A~1 done (spec datas); A~2→A14.1; Egret round 3 low→A14.2; M~1→M14.1, M~2→M14.2 |
| 15 | 2026-10-29 | Lantern (claude), floor TXY live; merged by CoCo | Live auto-convert, start at launch (`sessions/2026-10-29-claude-txy-live/`) | agent/txy-live | Q~1→Q15.1, Q~2→Q15.2, Q~3→Q15.3; Q~4 moot (UI landed); A~1, A~2 done; A~3→A15.1, A~4→A15.2, A~5→known-issues, A~6→A15.3; M~1→M15.1, M~2→M15.2 |
| 16 | 2026-10-29 | Crate (claude), floor TXY packaging; merged by CoCo | packaging every backend (`sessions/2026-10-29-claude-txy-packaging/`) | agent/txy-packaging | Q~1→Q16.1, Q~2→Q16.2; A~1→A9.1 note, A~2→A16.1, A~3→A16.2, Puffin's nit 1→A16.3; M~1→M16.1, M~2→M16.2 |
| 17 | 2026-10-29 | Side (claude), Ground | Tony's answers on the converter's open questions (Chat) | dev/v0.0.7 | A17.1, A17.2 |
| 18 | 2026-10-29 | Side (claude), Ground | converter follow-ups (Tony in Chat) | dev/v0.0.7 | Q18.1–Q18.6, A18.1, M18.1 |
| 19 | 2026-10-29 | Rivet (claude), floor Quick Fixes 6; merged by CoCo | test_typing first (`sessions/2026-10-29-claude-quick-fixes-6/`) | agent/quick-fixes-6 | A~1 (future slow modules) folded into testing.md; Tern's finding 1→A19.1 |
| 19 | 2026-10-29 | Side (claude) subagent, Ground | caching audit after the converter (`sessions/2026-10-29-claude-caching-audit/audit.md`) | dev/v0.0.7 | Q19.1–Q19.9, A19.1, A19.2 |
