# Analysis result caching

Horizon: R1 with the first analysis, then staged with the analysis workflow and
Live. Added: 2026-10-15 (rules gathered from the job-runner, Live and
analysis-behaviour plans of 2026-10-14). Direction agreed with Tony; formats,
budgets and defaults are draft.
Priority and completion: [overview](_readme.md).

This document is the **one home** for how analysis results are kept, reused and
saved, including during Live. Other plans link here instead of restating the
rules. The TXY **dataset** cache is a different store with its own rules: see
[cache storage](cache-storage-and-settings.md) and, while monitoring,
[Live dataset-cache writes](live-monitoring.md#dataset-cache-writes-while-monitoring).

## Rules

1. **Results are separate from the TXY dataset cache.** Clearing and eviction
   of one never touch the other (they share one disk budget, rule 6). Clearing the result cache never
   removes explicit exports.
2. **Three retention policies.** Each result is held **in RAM only**, **cached
   on disk**, or **exported/kept** by an explicit user action as a durable file.
   The job record says which policy took effect and whether the result is still
   available. A failed disk save is reported and the result stays in RAM.
3. **Who decides the policy.** The script declares its capabilities and a
   default; user defaults and per-folder/script settings override it. Overrides
   are local per-user settings, never tracked project files
   ([network plan](network-runners-and-web.md#local-only-settings-and-portable-records)).
   How long a run takes never silently decides retention. Result caching and
   saving changed parameters are separate settings.
4. **Three script capabilities**, declared separately:
   - `cache_supported`: a completed one-off run may be cached on disk;
   - `live_supported`: the script can update its result as Live adds shots;
   - `live_cache_supported`: the script can advance a saved result through the
     Live protocol. It requires the other two; Live support alone doesn't imply it.
   The runner validates the declarations before offering any control that
   depends on them.
5. **Reuse needs an exact match.** A cached result is reused only when the
   dataset snapshot (included shots and fingerprints), the script's exact
   managed version or unmanaged file hash, effective parameters, shot selection
   and execution environment all match. A changed script hash marks old results
   as not current; they stay viewable with their original identity. Results that
   used a shot later repaired are outdated
   ([QC](quality-control-and-repair.md)). An outdated result may show at once
   with an indicator while a permitted rerun runs
   ([analysis workflow](analysis-workflow.md#folder-following-analysis-behaviour-decided-2026-10-14)).
6. **Bounded RAM and disk.** RAM results are bounded and evicted least recently
   used, except those a view shows. Saved results count toward the disk cache's
   budget (Tony, 2026-10-22).
   Nothing on disk is removed automatically until user-controlled clearing and
   retention exist, matching the dataset cache's "nothing removed without
   asking".
7. **Live results stay in RAM.** Quick and Live intermediate results never
   cause a disk write per arriving shot. Only `live_cache_supported` scripts
   show **Auto-update cache**, which persists coalesced revisions under a
   bounded write policy and saves the latest completed revision when Live
   stops. A Live script without it updates in RAM and, if `cache_supported`
   and enabled, may save one final one-off result when Live stops.
8. **Coverage is explicit.** HeLab knows which TXY shots (and repaired
   variants) are loaded in RAM; each Live script reports the exact shots it has
   analysed. The runner sends only the missing shots through the script's
   update method. Coverage and result revision are tied to parameters and
   script identity, so reconnects, repairs and duplicate notifications can't
   silently reuse old work. Readers see the last **completed** revision while
   the next one runs.

## Stages

Each stage is one or more reviewable code slices.

| Stage | Delivers | Needs |
|---|---|---|
| R1 (done 2026-10-19) | RAM-only results for the first analysis (3D scatter), bound to the dataset view; job record shows the policy | [Analysis workflow](analysis-workflow.md), dataset view ([refactoring](refactoring.md)) |
| R2 (done 2026-10-23, `agent/result-cache-r2`, merge `5617381`) | Disk-cached one-off results (`cache_supported`: Correlations, Release time), exact lookup key with the execution environment, outdated marker, results in the one disk budget with Make room / Discard, Clear cached analysis in Settings → Cache and Data roots, the reuse setting, the folder-row badge, reopened plots included; one store identity rule with presets (`FolderCache.store_answer`). Handoff: `.ai/sessions/2026-10-22-claude-result-cache-r2/handoff.md` | R1 |
| R3 | Live RAM updates (`live_supported`): coverage tracking and missing-shot updates, last completed revision shown. Coverage recorded on every result (shots and fingerprints, `Coverage.diff`) and the reuse key assembled (`AnalysisResult.reuse_key`), 2026-10-19; missing-shot updates still to come | R1, [Live](live-monitoring.md#stages) L1 |
| R4 | **Auto-update cache** (`live_cache_supported`): coalesced revision writes, save at Live stop, the final one-off save for other scripts | R2, R3 |
| R5 | Publishing completed revisions to other machines | R4, [network extension](network-runners-and-web.md#cross-machine-result-sharing) |

## Open decisions

- Decided (2026-10-23): `store-v3` `results` + `pending_results` tables and
  `results/` `.npz` files, owned by helpers; no separate budget.
- Coalescing rule for Auto-update cache (every N revisions, time, or both).
- Initial default policy per analysis type; which script instances supply the
  latest Live result when several exist.
