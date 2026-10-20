# Handoff: DLD store fixes

Branch `agent/dld-store-fixes` (from `fb47de7`), one commit. Not pushed or merged.
Details and the benchmark table: [notes.md](notes.md).

## Fixed

1. **Old stores gain `folder_constants` and `raw_times` on open** (`cache_store._migrate`, every
   writable open, under `BEGIN IMMEDIATE`, re-checked under the lock; concurrent helpers migrate
   once). Read-only stores without the table read as "none set". `rekey_subtree` skips missing
   tables. `_discover_root` records the root and re-keys in one transaction, so a failed re-key is
   retried by the next listing instead of orphaning the subtree's rows under the outer key.
2. **Quitting:** `set_folder_constants` and `set_folder_prefs` refuse while quitting; the quit window
   waits for flags and constants writes still running (proposed, for Tony: flags included for
   consistency, since a killed helper loses either choice).
3. **Constants writes respect verified volumes** (`verified_volumes` with the request; on an
   unverified volume: session-only with "its drive isn't verified yet this session", saved again on
   `volumesVerified`). Flags (`cache_admin prefs`) still trust every hint, as before; why and the
   proposed follow-up are in notes.md.
4. **Listings send `constants` only when set** (−4.2 % payload at 10k subfolders); FolderCache keeps
   no empty records.
6. `tests/test_io_trace.py`: the cache-b reload now asserts its `loaded` came from the cache with all
   four shots' times, and a load whose shots are all held by the caller without a disk cache stats
   no raw file and reads nothing.

## Notes (document only)

- **Mixed versions (5):** an older HeLab (before F0b) opening a migrated store is fine (it names
  its tables), but its `rekey_subtree` doesn't know `folder_constants`: a nested root found by that
  HeLab moves the subtree's other rows and leaves its constants under the outer root's key, where
  this HeLab no longer looks. Beside D7's note that an older HeLab's save resets a folder's
  `raw_times` to `[]`. Both only while lab machines run mixed versions.
- **Constants have no save guard or epoch:** nothing removes them (not Clear all, purges, a root's
  Clear cached data, nor making room), so the only race is between choices, which `set_at` settles
  (newest wins, in the store's transaction). AGENTS.md should say so (below).

## Proposed AGENTS.md text

In **Caching**, after "Folder flags (… ) … every dataset save checks `no_cache` in its transaction.":

> Folder constants (Folder constants…, store `folder_constants`, `FolderCache.folder_constant_records`)
> are like the flags: one folder's own values, never removed by Clear all, purges, a root's Clear or
> making room, moved by a nested root's re-key; they need no save guard or epoch since nothing
> removes them, and the newest `set_at` wins. Listings send an entry's `constants` only when the
> folder has a saved row (with `saved_read`, no key means none set). Constants writes on the local
> lane wait for an unverified volume (session-only until `volumesVerified`); quitting refuses new
> flags and constants and waits for those being written (`quit_saves`).

and replace D7's "added to older store-v3 databases on open" wording with:

> Tables and columns added within `store-v3` (`folder_constants`, `datasets.raw_times`) are added to
> older stores on every writable open (`cache_store._migrate`, once under the write lock), never
> only in `SCHEMA`, which runs for a new store alone; read-only stores without them read as empty.

## Validation

See the commit message and notes.md: targeted tests, the full suite (line in the final report),
mypy --strict helab and tests, pyright helab tests, `git diff --check`, `list_bench.py`.
