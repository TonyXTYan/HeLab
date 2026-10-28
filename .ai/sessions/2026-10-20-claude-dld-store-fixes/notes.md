# Notes: DLD store fixes

## What changed

- `helab/utils/cache_store.py`: `_add_raw_times` → `_migrate(conn)`, run after the layout check on
  every writable open. Fast path without a lock when both are present; otherwise `BEGIN IMMEDIATE`,
  re-check, `CREATE TABLE folder_constants` (only if `sqlite_master` lacks it) and the `raw_times`
  `ALTER`, one commit. `CacheStore._constants_table` (read at open): a read-only store (newer
  layout) without the table answers `read_constants` with "missing" for every path, never an error,
  so `saved_read` stays true. `rekey_subtree` skips tables the store lacks.
  `_unverified_mounts` (set by `io_helper._cache_store`): the mounts whose volume hints the opener
  didn't trust.
- `helab/io_helper.py`:
  - `_discover_root`: `record_root` and `rekey_subtree` in one `store.transaction()`. A failed
    re-key rolls the root record back too (`cache_warning` "Data root could not be recorded"), so the
    next listing sees the marker as new, takes `old_key` again and retries; `removed` /
    `root_rekeyed` are sent only after the commit.
  - Listing entries carry `constants` only when the folder has a saved row (a row whose values
    were all restored is still sent: it carries `set_at`). `_send_constants` likewise sends only the
    folders above that have a row.
  - `cache_admin("constants")` opens the store with the request's `verified_volumes` (only this
    action; the other admin actions name no source folder). A folder on a held mount answers
    `session_only` with `UNVERIFIED_CONSTANTS` ("its drive isn't verified yet this session").
- `helab/utils/folder_cache.py`:
  - `set_folder_constants` and `set_folder_prefs` refuse while `quitting` (failure signal with
    `QUITTING` = "HeLab is quitting"; nothing shown changes).
  - `quit_saves` also lists folders whose flags or constants write is queued or running
    (`_pref_writes`, `_constant_writes`); `folder_settings_saving(path)`; `quitSavesChanged` when
    such a write ends. `QuitSaveDialog.state` says "saving its flags or constants".
  - Constants saves send `verified_volumes`; `_constants_roots_moved` (run on `volumesVerified`,
    root changes) now also clears `UNVERIFIED_CONSTANTS` answers, so those values are saved then.
  - `remember_constants` stores no record for "none set"; with `known` it deletes the record.
- `tests/test_store_migration.py` (new), `tests/test_folder_constants.py` (listing assertions,
  `verified_volumes` in params), `tests/test_io_trace.py` (coordinator's item).

## Judgement calls (proposed, for Tony)

- **Flags are treated like constants while quitting.** Both are the user's explicit choice, and a
  helper killed at quit loses it (its SQLite transaction rolls back). So both refuse new choices
  while quitting and both are waited for by the quit window. Before, neither was waited for; the
  coordinator asked for constants and to stay consistent with flags.
- **Constants writes respect verified volumes; flags still don't.** Flags (`cache_admin prefs`)
  open the store with no source path and trust every hint, as before. I left them: changing them
  needs a "pending flag" state in the UI (a flag is shown at once and reverted on failure; a
  constants value already has a session-only state with a reason and an automatic retry, so the
  wait came for free). Risk for flags is small in practice (the folder's parent was just listed by
  a source helper, which re-reads and records its volume ID), but the same holds for constants.
  Proposed follow-up: flags the same way, if Tony wants it.
- The reason text lives in both `io_helper` and `folder_cache` (folder_cache doesn't import
  io_helper); a test checks they match.
- A listing's absent `constants` key with `saved_read` true means "none set", which for a folder
  this session knows nothing about is a no-op, and for one it holds is ignored (`known=False`),
  as `{}` was before. So the app side needed no new branch, only no empty records.

## Validation

- Targeted: `tests/test_store_migration.py` (9), `test_folder_constants.py`, `test_cache_store.py`,
  `test_root_discovery.py`, `test_shot_times.py`, `test_live.py`, `test_cache_first.py`,
  `test_scan_history.py`, `test_io_trace.py`.
- `tests/test_store_migration.py` builds a store with 1231025's schema (copied from
  `git show 1231025:helab/utils/cache_store.py`, `SCHEMA` + `ROOT_SCHEMA`) and checks: open migrates
  (table, column, old dataset row reads with `raw_times == []`); 6 concurrent helper processes
  opening the old store all succeed and write; read-only (layout+1) old store reads constants as
  missing and isn't changed; re-key skips a missing table; two listings with an old store have
  `saved_read` everywhere and no `cache_warning`; a nested root's first re-key failing leaves no
  root record and the second listing moves flags, constants, summary and dataset; constants on an
  unverified volume wait, then save; the app resaves on `volumesVerified`; quitting.
- `list_bench.py` on the 10k-subfolder tree (median of 5, this container):

  | code | store | median | payload | warnings | saved_read |
  |---|---|---|---|---|---|
  | fb47de7 | old | 372 ms | 4.09 MB | 81 `cache_warning` (no such table) | all False |
  | fb47de7 | fresh | 374 ms | 4.25 MB | none | all True |
  | this branch | old (migrated on open) | 368 ms | 4.07 MB | none | all True |
  | this branch | fresh | 379 ms | 4.07 MB | none | all True |

  Payload −4.2 % against fb47de7's fresh store; time unchanged within noise. On the GUI thread,
  listings no longer call `remember_constants` for folders without constants (was ~35 ms per 10k).
- mypy --strict helab, mypy --strict tests, pyright helab tests: clean. `git diff --check` clean.
- Full suite (`-n 4 --reruns 5 --reruns-delay 1 -rR`): `2 failed, 1659 passed, 7 skipped,
  2 xfailed, 2 warnings, 10 rerun in 168.62s`. The 2 failures are the known root-only ones
  (`test_constants.py::test_read_only_saved_folder_is_replaced`,
  `test_cache_mover.py::test_recovery_isnt_usable_after_a_failed_settings_write`); all 10 RERUNs are
  those two (5 each). No other test needed a rerun.
