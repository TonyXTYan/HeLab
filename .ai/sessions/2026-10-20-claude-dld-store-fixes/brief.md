# DLD store fixes (Worker brief)

Branch `agent/dld-store-fixes` from `fb47de7` (agent/dld-front-panel-port after merging the seven
DLD branches). From the I/O review of fb47de7 (probes: the review session's `rv-io-probes/`
`schema_probe.py`, `rekey_probe.py`, `list_bench.py`, `trace_probe.py`).

1. **Blocker.** `folder_constants` (F0b) was only in `SCHEMA`, which runs for a new store only:
   every store made before the merge never got it. `read_constants` errored, so every listing entry
   had `saved_read=False` with a `cache_warning` (Refresh after remount never replaced RAM status),
   `set_constants` raised "no such table", and `rekey_subtree` raised on a nested `.helab-root`
   after `_discover_root` had committed `record_root` on its own, so the re-key was never retried
   and the subtree's rows (datasets, summaries, histories, flags) stayed under the outer key.
   Fix: one `_migrate(conn)` on every writable open (table + `raw_times` column, rechecked under
   `BEGIN IMMEDIATE`); read-only opens treat the missing table as none set; `rekey_subtree` skips
   missing tables; `record_root` + `rekey_subtree` in one transaction. Tests with 1231025's schema.
2. Low: refuse `set_folder_constants` while quitting; include in-flight writes in `quit_saves`
   (consistent with flags).
3. Low: the local-lane constants write ignored `verified_volumes`.
4. Minor: listings sent `"constants": {}` per entry (+4 % payload) and FolderCache stored an
   empty record per listed folder.
5. Document only: an older HeLab's `rekey_subtree` doesn't know `folder_constants`.
6. (Coordinator, tests review) `tests/test_io_trace.py`: the cache-b reload must assert a `loaded`
   from the cache, and exercise "unless … the caller has it".

Stay out of `helab/scripts/`, `helab/analysis/`, `ScriptTreeSelector.py` (agent/dld-decisions).
