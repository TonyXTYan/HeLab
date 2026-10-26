# Cache Only review findings (Vernier, Codex; relayed by CoCo)

## Round 1 (3eb0fbf...3b2223f, 2026-10-26)

Blocker found: five findings, all reproduced. Vernier's probe script is `review-probe-round1.py`, in this folder.

Vernier's validation in the review copy: 4416 passed, no RERUN; mypy strict on helab and tests, and pyright, all clean.

**P1. `helab/utils/io_service.py:463`: completed ordinary loads keep source access after Work Offline.**
- Once a normal load sends `loaded`, its SharedJob is removed and `request.completed=True`.
- `FolderCache.set_offline` no longer sees it, and this condition leaves it out of cancellation, although `finishes_offline=False` (no save flag).
- `loading.py:618–632` then re-reads held TXY shots and checks source files for its cache write.
- Scenario: reuse shot 1 from RAM while loading new shot 2, then go offline after `loaded` but before the cache tail finishes. The probe recorded a real `d_txy_forc1.txt` read, reason "cache save: read", while `service.offline=True`.
- D3 calls these finishing writes local, but this tail isn't local. Either keep truly local writes and the explicitly allowed Live save while stopping ordinary source-reading tails, or don't claim offline until the remaining source work ends.

**P2. `helab/utils/folder_cache.py:1867` (also `set_offline` 2017–2022, `_start_deferred` 2372–2381): saves asked for but deferred are lost on entry.**
- Scenario: another ordinary load (e.g. another tab's) owns a Live folder when Live's stop asks for its save, so `save()` records it in `_deferred_saves`.
- Going offline cancels the blocking load, `_forget_job` schedules `_start_deferred`, and that pops the old save and resubmits it through the new offline refusal.
- It gets offline/cancelled and leaves `quit_saves` without being saved. Probe: a deferred save existed before the switch; afterwards the events were [offline, cancelled], no pending save, and `quit_saves=[]`.
- The same refusal happens when a deferred stop-save waits for a finishing cache writer.
- Keep the authorization of saves asked for before the switch.

**P2. `helab/io_ops/stores.py:220–224`: exact mount-path equality doesn't make current mounts win over nested hints.**
- Scenario: last session had old-server/old-share mounted at `/Volumes/lab/subdir`. Now a different share is mounted at `/Volumes/lab`, and `subdir` is an ordinary folder in it.
- `_offline_mounts` still injects the old nested mount, because no current mount has that exact path.
- Longest-prefix resolution then maps `/Volumes/lab/subdir/run` to `smb://old-server/old-share/run`, and so to that share's old root:// data, not the mounted share's. The probe confirmed this key.
- The same applies to stale hints carried in a cache copied from another machine.
- Hints are correctly offline-only, and an exact current mount does win. A current non-system mount that contains the path must win too.

**P2. `helab/utils/folder_cache.py:2024–2026` (Work Online's caller, `HelabMainWindow.py:1219–1224`): an offline listing still queued or running absorbs Work Online's forced Refresh.**
- Going online leaves its SharedJob keyed (list, path). `refresh()` either sees the existing subscription at `submit:1865` or joins that same job at :1934, so no online list is queued.
- Its old entries then arrive after the switch. Probe: only `saved_list` at Refresh, then `offline_listed_at=1000` while `cache.offline=False`.
- A following details scan adds current children but never prunes missing ones, by design (`SnapshotFileSystemModel.py:778–782`). After a current child "fresh" was injected, the removed offline child "stale" stayed beside it.
- Cancel or fence offline jobs and replays when leaving, then issue real listings.

**P2. `helab/io_ops/listings.py:84–89`: "newer listing wins" is compared outside the write transaction.**
- Two HeLabs or helpers can both read the previous row. The newer observation commits first, then the older helper `save_records` it unconditionally under a still-valid guard.
- Probe, with two CacheStore connections interleaved between the comparison and the write: the listing at 2000 saved, then the listing at 1000 saved, and the final row had `listed_at=1000` with the old child names.
- Guard generations and epochs don't order listings. Compare and write under the same write lock, or use a conditional update.

**Test coverage limits (to fix with the findings):**
- `no_source_io` asserts operation names after `_start`. Most navigation tests freeze dispatch and answer helpers by hand.
- It doesn't deny the underlying source filesystem or network calls, and it misses completed helper tails and deferred saves that already exist.
- The test named `relists_every_tab` opens only one tab and waits until its offline listing has finished.
- Not tested: an in-flight listing across the online/offline switch, a nested current mount against a hint, and concurrent listings' ordering.
