# Area review: `cache` (disk cache store and data roots), HeLab 0.0.7a1

Reviewer 2 (Ledgerline), 2026-10-31, read-only, on `agent/area-review` (base `c3a503f`).
Read: `helab/utils/cache_store.py`, `cache_paths.py`, `data_roots.py`, `cache_move.py`, `cache_setting.py`,
`helab/io_ops/stores.py`, `admin.py`, `markers.py`, `results.py`, and `FolderCache`'s store identity, presets,
removals, pending saves, flags/constants and root events (`helab/utils/folder_cache.py`), with the boundaries into
`loading.py`, `convert.py`, `live.py`, `CacheMover.py`, `CacheDialogs.py` and `IOService`.
Scratch tests (kept, not committed): `.ai/temp/area-review-cache/` (run with `pytest -p tests.conftest <file>`).

**No High finding.** 6 findings: 0 High, 1 Medium, 3 Low, 2 Nit/doc.

## Findings

### cache-1 · Medium · Folder flags and `write_beside` outlive a data root's change of identity

`helab/utils/folder_cache.py:620-631` (`_root_seen`), `:699-704` (`_root_gone`), `:3674-3690` (`root_changed`),
with `remember_prefs` `:1171-1173`.

When the root known at a folder changes UUID or goes (`root_changed` with a new UUID: a replaced marker, It's a
copy…; without one: marker removed or invalid, Delete .helab-root…, Settings › Data roots › Forget; also
`root_found`/`data_root` naming another UUID), RAM drops the old root's **constants** (`_root_constants_gone`) and
**saved-result counts** (`_root_results_gone`), and `removed(affected, KINDS)` drops the saved records, but nothing
drops the old root's **folder flags** (`prefs`, `_confirmed_prefs`: Don't cache / Don't auto-load) or the
converter's **`convert_prefs`** (`write_beside`). The next listing can't correct them either: under the new key it
finds no flags and calls `remember_prefs(path, {}, known=False)`, which by design "only fills in a folder this
session knows nothing about". This is the class of Codex's 9 (state kept across a context change), and the
constants path was fixed for exactly this case while the flags beside it weren't.

Scenario: tick Don't auto-load (or Don't cache) on `root/run` under root A → the marker of `root` is replaced (or
It's a copy… gives it a new UUID, or the user deletes or forgets it) → for the rest of the session `root/run` keeps
both flags in RAM: `FolderExplorer` skips its automatic loads (`FolderExplorer.py:863`, `:1108`), the row and Folder
details show the flags ticked, results reuse is hidden (`analysis_cached`, `:3187`), Live's cache status says "Don't cache"
(`explorer_live.py:407`), and the store has no flag for the new key; after a restart they are gone. The same for
`write_beside`: Settings and the explorer show "write beside" on; the converter helper re-checks the store
(`io_ops/convert.py:332-346`) so **nothing is written beside the raw files** (the invariant holds), but each
conversion then falls back to the cache folder with "writing beside the raw files is off for this folder" while
the UI says it is on.

Verified: scratch test `.ai/temp/area-review-cache/test_scratch_flags_root_change.py` (both `root_changed` shapes:
new UUID and marker removed): after the event constants are `{}` but `folder_prefs(RUN)` is still
`{"no_cache": True, "no_auto_load": True}` and `write_beside(RUN)` still True, also after a `known=False` listing
answer. No test in `tests/` covers flags across a root change (`test_folder_constants.py` covers constants only).

Fix direction: a `_root_prefs_gone(path)` beside `_root_constants_gone`, called from the same three places: drop
`prefs`, `_confirmed_prefs` and `convert_prefs` for folders `_root_holds(path, folder)`, except a flag write still
in flight (`_pref_writes`), and emit `folderPrefsChanged`; plus a test like the constants one.

### cache-2 · Low · A records-only removal fences the folder's dataset save (one epoch for every kind)

`helab/utils/cache_store.py:2229-2231` (`remove` bumps the folder's single `folder_epochs` row whatever the kinds),
checked by `_guard_holds` `:1173` and `adopt_pending` `:1461`.

`remove((kind,), paths)` bumps each path's one folder epoch for any kind, and every dataset save and pending save
checks that epoch. So Settings → Cache's **purge of old folder records** (`purge_records`: summaries, subfolder
status, listings, histories) of a folder whose load is saving, or whose save waits for Make room / Save update,
makes that dataset save fail. Results were given their own `results:<key>` epoch for exactly this reason
(`_results_epoch` docstring); the record kinds share the dataset's.

Scenario: a folder scanned a month ago (old `folder_summaries` row) is loaded now and its save waits as
`over_budget` → the user opens Settings → Cache and purges records older than 30 days → Make room answers
"Cache was cleared before saving completed" and the save is discarded (its data stays in RAM; the next load saves
again). Same for a load whose save is in flight during the purge (`cache_save_failed`). The reverse also happens
quietly: Make room, trim and dataset purges bump the folders they take, so those folders' in-flight listing,
summary and subtree saves are refused (`listings.py:93` swallows it).

Verified: scratch test `.ai/temp/area-review-cache/test_scratch_purge_epoch.py`: after `purge_records`, both
`save_dataset(guard)` and `adopt_pending` raise `SaveRejected("cleared")`.

Fix direction: per-kind folder epochs (`<kind>:<key>` rows, as results have), bumping only the kinds removed;
datasets' removal still bumping what its saves check. Natural to do in store-v4 (caching v2) rather than in store-v3.

### cache-3 · Low · Another running HeLab's pending saves are asked about here

`helab/utils/cache_store.py:2390-2396` (`inventory` lists every `pending_saves` row), `folder_cache.py:3536-3550`
(merged into `pending_saves`), `CacheDialogs` asks about every one.

Pending saves carry no owner. Every inventory (startup's `restore_pending`, each Settings → Cache refresh) brings in
all pending saves in the store, including those of a second HeLab running now (instances are allowed:
`instances/<pid>.lock`; `helab convert` too, though it holds no pending saves), and this window asks Make room /
Don't cache this folder now about a load it never did. "Don't cache" here discards the other instance's save; the
other instance's own question then ends in "This save is no longer waiting". `restore_pending`'s docstring says
"saves still waiting … from an earlier session", which the code can't tell apart.

Verified by reading the path (no instance or session field anywhere in `pending_saves`, the inventory or the merge).
Not run with two GUIs.

Fix direction: record the owning instance (pid and its lock's token, or a session id) with each pending save and
pending result (store-v4), and ask only about this instance's or those of instances no longer running.

### cache-4 · Low (tests, known-issues) · The `test_cache_switch.py` "store error path" leak is the test's own

`tests/test_cache_switch.py:207` (and `:136`, `:302`; 29 such lines across `tests/`).

`with sqlite3.connect(...) as connection:` commits on exit but never closes the connection (sqlite3's context
manager manages the transaction only), so each use leaks a `sqlite3.Connection` until the GC collects it, in
whichever later test is running. Known-issues attributes `test_newer_store_is_read_but_never_written`'s leak to "the
store's error paths"; tracemalloc puts it at line 207 of the test. This matters beyond warnings: the known
`test_root_discovery.py::test_volume_check_alone_refreshes_hints_without_visiting_markers` RERUN entry says a
GC-timed collection inside a patched hook may be one of these.

Verified: `PYTHONTRACEMALLOC=90 python -W always::ResourceWarning -m pytest -p gc_plugin <both tests>`
(`.ai/temp/area-review-cache/gc_plugin.py` collects after each test): one `unclosed database`, allocated at
`tests/test_cache_switch.py:207`. **Unverified:** the two leaks named for
`test_load_that_cannot_read_the_cache_leaves_its_flag_unknown` didn't show with a collection after the test; I
read `read_cached`/`load_folder`'s store handling (`loading.py:39-68`, `:275-303`) and both close in `finally`.

Fix direction: `contextlib.closing(sqlite3.connect(...))` (or an explicit `close()`) in tests; correct the
known-issues entry (store code not implicated for that test).

### cache-5 · Nit · A save whose guard names a re-keyed folder fails as a raw error and leaves a file for the sweep

`cache_store.py:1163-1167` and `:1729-1730` (`ValueError` "The save guard doesn't cover …"), `io_ops/results.py:99-112`.

If a nested root is found between a job's guard and its save, the save's key differs from the guard's: the store
raises `ValueError` (deliberately: never re-guard under the new key). `adopt_pending_result` turns that into a clean
rejection ("The folder's data root changed before saving completed"), but `result_save` catches only
`SaveRejected`, so the plot gets a helper error with the internal text, and dataset saves report it as
`cache_save_failed` with the same text. The file already published (`write_result_file`, `write_dataset_file`) is
named by no row and is deleted only by the orphan sweep an hour later (within housekeeping, so no rule broken).
Verified by reading.

Fix direction: map that `ValueError` to `SaveRejected("cleared", "The folder's data root changed …")` in
`save_result`/`save_dataset`, which also retires the file at once.

### cache-6 · Nit (docs, comment)

- `cache-store.md` "Tables added within store-v3": the mixed-versions sentence names only constants for an older
  HeLab's re-key; a 0.0.6 HeLab doesn't know `convert_prefs`, so its re-key leaves `write_beside` rows behind (the
  safe direction: off under the new key) and its Clear folder preferences doesn't turn `write_beside` off.
  Proposed: "…and its re-key of a nested root leaves the subtree's constants (0.0.5) and converter flags (0.0.6)
  behind, and a 0.0.6 HeLab's Clear folder preferences leaves `write_beside` on."
- `helab/io_ops/admin.py:55-58`: the comment says the actions other than constants and convert_prefs "name no source
  folder", but `prefs` (the folder flags) does; it trusts every volume hint, which `cache-store.md` documents as
  intended ("flags still trust every hint"). Proposed: say so in the comment.

## Checked and fine

- **Migrations:** every table and column added since store-v3 shipped (0.0.5a1 `5a8ae6fd` → 0.0.6a1 → 0.0.7a1:
  `folder_constants`, `datasets.raw_times`, `presets`, `results`/`pending_results` + `gen_results`, `listings` +
  `gen_listings`, `mount_hints`, `convert_prefs`) is in `_migrate`, checked again under `BEGIN IMMEDIATE`; the
  `results` schema is unchanged between 0.0.6a1 and 0.0.7a1. Read-only (newer) stores read missing tables as empty.
- **Save guards:** every dataset, pending, record, listing, confirm and result write checks its guard in the write
  transaction; `clear_root` bumps `root-clear://`, which every dataset/record guard below the root carries;
  `clear_root_results`/purges bump the results epochs; `no_cache` is checked in every dataset and result save
  transaction; replaced files are retired, never deleted inline; `_reject_file` never retires a file a row names.
- **Budget:** the fit rule is decided on the real row (savepoint, rolled back), records counted, pending excluded;
  `_active_budget` takes the newest `set_at`; Make room removes exactly the plan shown (`expected_room` /
  `room_ids`) or nothing; with no plan the question says the rule it applies.
- **Housekeeping matches AGENTS.md's list:** the sweep deletes retired files after 10 min, unnamed store files over
  1 h old, pending saves/results over 1 h; `remove_old_caches` touches only the three old diskcache folders;
  nothing else removes without a user action. Folder flags, constants, convert prefs and presets are never removed
  by Clear all, purges, Make room or a root's clear.
- **Store identity:** `store_answer`/probe/held-writes logic: answers from another store wait for the probe, writes
  name their store (`presets` rows only to `params.store`, `adopt_result` and `result_save` refuse another store),
  a failed probe leaves the store unknown without retrying by itself.
- **Data roots:** no path-key fallback (`DataRoots.key` raises `NoDataRoot`; a pending nearest root is RAM only even
  under a confirmed outer one); every direct `CacheStore(...)` open outside `_cache_store` uses only the roots and
  volume tables; marker writes are exclusive-create or temp+replace, `root_remove` deletes only a regular file
  holding the expected UUID; discovery's record + re-key is one transaction; re-key moves every folder-keyed table
  (incl. `convert_prefs`, results and pending results) with newer-wins and retires losers.
- **Local-lane trust:** cached reads, loads, listings' subtree/history writes, results, constants and convert prefs
  pass `verified_volumes`; offline hints are used only where nothing non-transparent is mounted at or above.
- **Cache move:** queued requests get the current `store_options()` when they start (`IOService._start`), so none
  opens the old folder after the switch; record-before-touch, idempotent recovery, copy verified (integrity, id,
  every named file's size) before cutover, old folder deleted only after the setting is saved and recorded.
- **GUI never opens the store:** no `CacheStore`/`sqlite3` use in the GUI process; `cache_dir()` used everywhere
  (`DIR_CACHES` only in `constants.py`).

## Checks run

- Scratch tests above (both pass, i.e. confirm the behaviour described).
- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review-cache`: **8510 passed, 672 skipped,
  2 warnings in 282.31s; no RERUN** (warnings: pyqtgraph's NumPy 2.5 `arr.shape` DeprecationWarning in
  `test_t_spectrum.py`). Log: `.ai/temp/area-review-cache/suite.log`. One oddity, **not** in this area (for the `app`
  reviewer): at ~98% an xdist worker printed `ERROR:root:GUI stalled for 123.57s; capturing thread stacks` from
  `helab/utils/gui_watchdog.py:40`, with the worker's main thread idle in execnet's receive loop: a GUI watchdog left
  running after its test, reporting the idle worker as a stall. No test failed; not in known-issues.
- `mypy helab/ --strict`: no issues in 195 files; `mypy tests --strict`: no issues in 175; `pyright helab tests`:
  0 errors, 0 warnings.
