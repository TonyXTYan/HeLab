# Docs audit 3 (2026-10-29)

A Side (Claude) subagent, read-only; written here by Side from its report. Scope: what changed since
`c5a193e` (`639f133`…`311a356`) and the uncommitted blocks 25–27, plus anything still stale.
6 wrong, 15 stale, 7 nits, 3 for Tony. Applied on Ground by Side unless marked otherwise.

**Checked and fine:** AGENTS.md 19,658 bytes; every relative link and anchor in scope resolves
(415+); MEMORY.md indexes every file once; every `helab/convert` module but `numba_kernels` is in
`PURE`; AGENTS.md's names exist; budgets in code match the docs; the marker parser ignores unknown
fields.

## Wrong

1. M1.10 expected an older HeLab to read a newer store read-only, but 0.0.6a1 and v0.0.7 share
   layout 3 (`cache_store.py:30`); only a higher layout opens read-only. Fixed in M1.10 and block 27.
2. Q19.2 recorded Tony's Q12.3 answer (separate budget) and still proposed "counted". Moved to
   Recently decided.
3. `cache-store.md:27` called the converted-TXY budget Tony's open question. Fixed.
4. `caching-v2.md` had no separate converted-TXY budget (Q12.3). Added.
5. `caching-v2.md` Versioning said dev builds carry `X.Y.Z.devN`, against AGENTS.md's bump rule and
   app-versioning. Now proposed, for Tony (T1).
6. Q19.5 (Don't cache → conversions to temp) decided but not built: `FolderCache.convert` always
   sends `store_options()` and `_places` never checks `no_cache`. Noted in `converter.md`; T2.

## Stale

7. DECISIONS_TODO kept decided items in open sections (Q19.3, Q19.5–Q19.8, Q22.7, Q26.1, Q26.2,
   block 24, Q12.1/Q12.3/Q12.4, Q25.1/Q25.3/Q25.5, Q27.1/Q27.2). Cleaned.
8. "Tony hasn't answered" Q12.x. Fixed.
9. Small "still open"/"proposed" wording (Q19.3, Q22.7, Q19.6). Fixed.
10. "Open decisions inside plans" converter line. Fixed.
11. `txy-converter.md`: Q12.1/Q12.4 "to confirm", open list, stage 3 lacking Q25.5's agreed plan. Fixed.
12. `_readme.md` Release v0.0.7 "Left:" lacked Q26.2, Q27.1 and M1.9/M1.10. Fixed.
13. `_readme.md` converter open list and stage 3 note. Fixed.
14. MANUAL_TODO said the pass has no converter step. Fixed.
15. Q24.1 called open in `maestri-setup.md` (3 places) and `agent-workflow.md`. Fixed.
16. `converter.md` called the burst veto "proposed". Fixed.
17. `converter.md` Where files go / Provenance didn't say Q26.2 replaces them. Fixed.
18. `txy-converter` memory listed answered Q12s and lacked block 25. Fixed.
19. "Proposed in Q22.7" wording in the plan and memory. Fixed.
20. `result-caching.md` lacked Q27.1/Q27.2. Fixed.
21. ID_BLOCKS rows 1 and 24 lacked M1.9/M1.10 notes. Fixed.

## Nits

22. "M1.1–M1.8" in `_readme.md` and `smoke-automation.md`. Fixed.
23. MANUAL_TODO link to dropped A1.5. Fixed.
24. Pointers from the SI rule to Q26.1 (AGENTS.md, `cache-store.md`, memory). Fixed.
25. A26.1 as its own Recently decided line. Folded.
26. MEMORY.md caching line. Fixed.
27. A12.4 names per-shot JSON temporaries Q26.2 removes: drop at the release tidy-up (no edit).
28. `caching-v2.md` intro: Q26.2 has its go. Fixed.

## For Tony

- **T1:** dev branches carry `X.Y.Z.devN` from their first commit (changes AGENTS.md's bump rule)?
- **T2:** build Q19.5 now in the Q26.2 floor (converter side, small), or wait for the cache go?
- **T3:** the Q26.2 floor also does A19.1's listing (show and clear temp-folder TXY), A19.2 on hold?
