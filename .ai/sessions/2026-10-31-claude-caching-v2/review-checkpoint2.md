# Review: Caching v2 checkpoint 2 (steps 2–4, switch off): `03fc012..c3c40c5`

Reviewer: Assay (Claude Opus 5.5), 2026-10-31. Read-only on code. Read: [design-stage1.md](design-stage1.md), the
handoff's "Steps 2–4", the brief's steps 2–4 and Data safety, AGENTS.md's disk-cache rules. `9515c58` (my own file)
and `ed5a62e` (a handoff count) were skipped.

**Verdict: no blocker for landing inert. 6 findings: 0 High, 1 Medium, 2 Low, 3 Nit.** With the switch off nothing
changes, and no store-v4 folder is made. Every finding is behind the switch, so no user can reach one yet. C2-1 must
be fixed before the switch can ever be turned on. C2-2 is cheapest to fix now, before anything writes a format-1
`.hlb` (step 5).

## Findings

### C2-1 · Medium · Keep's read-through brings store-v3's rows back after the user removes them in store-v4

- `helab/utils/cache_store.py:1308` (`read_records` reads v3 for every key v4 has no row for), `:2142` and `:2148`
  (`find_result`), `:2191` (`_folder_results` counts); `:1374` (`save_records` with `None` deletes the v4 row);
  `helab/io_ops/scanning.py:110` (a folder whose subfolder status went to nothing is saved as `None`).
- **Scenario.** The switch is on and store-v3 is kept (Keep, or not answered yet). In v4 the user does any of:
  - clears a folder's records (`remove(("summaries",), [path])`);
  - clears all cached analysis (`remove_results()`);
  - uses a data root's Clear cached data… (`clear_root`).

  In every case the next read finds no v4 row, so it reads v3. The cleared summary and results come back, results
  are counted again (2 for the folder), and `find_result` serves v3's result with `legacy=True`. The same happens
  without the user doing anything: when `scanning.py` deletes a folder's subtree record, v3's older subfolder status
  shows again. In v4 a removal and "never saved" look the same. That undoes what the user asked for, and it breaks
  the save-guard invariant (AGENTS.md: a removal can't be undone by data written before it).
- **Proposed fix** (owned file). Read through to v3 only for what v4 has never removed:
  - skip v3 for a key once v4 has bumped `gen_<kind>`, the key's `epoch_key(kind, key)` row, or its root epoch
    (`results:` rows for results);
  - make `save_records(..., None)` bump that kind's epoch in v4, so a delete also fences v3.

  Add a test along the lines of the scratch test below.
- **How verified.** Scratch test (not committed: `.ai/temp/assay/test_zz_cp2.py`, run from an export of
  `c3c40c5`). After those three removals in v4, `read_record` returns v3's `{"from": "v3"}`, and `find_result`
  returns a `legacy` result with a count of 2.

### C2-2 · Low · The `.hlb` header has no checksum; damage to it in the facts or meta is accepted as data

- `helab/utils/hlb.py:97-117` (`read_header`), `:120-150` (`unpack`); `helab/convert/raw_layer.py:189-197`.
- **Scenario.** One wrong character in a layer's JSON header that keeps it valid JSON is read as data:
  - `"first_channel":5` read as `7` makes `raw_layer.not_done(facts, 5)` answer `not_trigger_first` for a whole
    shot;
  - a flipped `final_newline`, `blank`, `t_zero`, or the maker's or meta's fields, pass the same way.

  Every chunk has a CRC, but the header has none. In the same vein:
  - trailing bytes after the last chunk are accepted;
  - addendum §5 promises a check for overlapping chunks, which `unpack` doesn't make (each chunk's CRC limits the
    harm).

  CoCo's criterion is that every corruption is an error. The chunks meet it; the header doesn't.
- **Proposed fix.** Before step 5 writes the first file, add a `<u4` CRC32 of the header after the length (or a
  `header_crc32` the reader checks), and require the chunks to tile the body exactly: contiguous, no gaps or
  overlaps, ending at the file's end. Format 1 is still unwritten, so this costs no format bump. Later it would
  need one.
- **How verified.** A script on the export: `raw_layer.from_hlb` of a blob with `"first_channel":5` → `7` returns
  `first_channel=7`, and `not_done(..., 5)` then reports `not_trigger_first`. `blob + b"junk"` decodes. A change that
  breaks the JSON is refused, as it should be.

### C2-3 · Low · An invalid `machine-id` file makes `machine_id()` recurse until `RecursionError`

- `helab/utils/store_v4.py:113-136`.
- **Scenario.** `app_folder()/machine-id` holds anything but 32 lowercase hex characters, for example a partial
  write, an upper-case id, or a later format. The read rejects it, `O_EXCL` hits `FileExistsError`, the file isn't
  empty, so the function calls itself, forever. With the switch on, that happens at the GUI's first
  `store_root()` (`session_maker` → `maker_record`), so `store_options()` raises, and so does `helab convert`. An
  empty file instead gives `""` every time and is never repaired. (Also: `os.path.getsize` inside the
  `except FileExistsError` branch isn't covered by the `except OSError` after it.)
- **Proposed fix.** No recursion: on an invalid or empty file, replace it atomically (temporary file, then
  `os.replace`) with a new id, or return `""` once.
- **How verified.** A script on the export: contents `abc123\n` and `"A"*32` each raise `RecursionError`; an
  empty file returns `""`.

### C2-4 · Nit · Keep counts a v3 result that v4 shadows

- `helab/utils/cache_store.py:2189-2195`.
- **Scenario.** v4 saves lookup `k1` for a folder whose v3 also has `k1`. `find_result` never returns v3's `k1`
  again, but `_folder_results` adds every v3 row, so the badge's count and bytes include it. The step-4 test even
  asserts it: `test_keep_reads_records_and_results_through_from_store_v3` expects 4 where 3 are reachable.
- **Fix.** Count only v3 rows whose `lookup` isn't in v4 for that key (or say in the handoff that the count is "v4 +
  v3 rows"). Once C2-1 is fixed, removed keys should count 0 from v3 too.
- **How verified.** Scratch test (`test_a_shadowed_v3_result_is_counted_twice`, passes).

### C2-5 · Nit · The retried import can bring back a flag the user cleared in v4 meanwhile

- `helab/utils/store_v4.py:182-221`.
- **Scenario.** v3 can't be read when v4 is created, for example because an older HeLab holds it, so
  `imported_v3` isn't set. The user then clears a folder's flags in v4, which deletes the row. At a later writable
  open, the import succeeds, and `INSERT OR IGNORE` adds v3's old flag (Don't cache, say) back. This is the same
  "removed or never set" ambiguity as C2-1, and it's rare.
- **Fix.** Either import only at creation (and say a failed import is skipped for good), or skip a key that v4 has
  touched since (its `set_at` rows, or a per-table "cleared after creation" note).
- **How verified.** By reading.

### C2-6 · Nit · With the switch off, a leftover store-v4 still becomes the cache move's primary

- `helab/utils/cache_move.py:134-136` (`primary`: the newest folder present), `:153-155` (`_passenger`).
- **Scenario.** A developer turned the switch on, then off. store-v3 is live again, but `store-v4/` exists. A move
  then records v4's `store_id`, checkpoints only v4, and treats the live v3 as a passenger: copied with its `-wal`,
  not checkpointed, verified through `LegacyStore`. The data is still safe, since the copy is verified. But it
  contradicts addendum §9 ("With the switch off, v3 is the only store: as today"), and recovery's `valid_at`
  follows v4's id.
- **Fix.** Choose the primary by `live_layout()` where the caller knows it, or note this case in the handoff and
  the docs.
- **How verified.** By reading.

## Checked, no finding

- **The switch.** The `store_v4` row is bool, off, and has no control. It is read once per process, at the first
  `store_root()` (`folder_cache.store_options`, `convert_cli`), and helpers never call it.
  - `CacheStore` takes its layout from the folder's name, so a v3 path is never opened as v4 or the reverse.
  - Off: `store-v3` as before, no maker in the environment, no `store-v4` folder
    (`test_with_the_switch_off_…`).
  - `ROOT_LAYOUT_VERSION == LAYOUT_VERSION`, so `root_mode` keeps its behaviour.
  - `remove_old_caches` touches only its three named old folders.
- **store-v3 opened only by `LegacyStore`.** It opens with `mode=ro`, else `mode=rw` with `query_only`, and sets
  `NO_CKPT_ON_CLOSE` either way. It never creates anything, runs no `_migrate`, and has no write method.
  - `cache_move`'s own read connection now sets `NO_CKPT_ON_CLOSE` too.
  - The guard test watches every `sqlite3.connect` and `CacheStore` open, and hashes v3's files.
  - The GUI process opens v3 only during startup recovery's `valid_at`, as it already opened the store there.
- **The import (Q22.4).** Once, in its own `BEGIN IMMEDIATE`, checked again under the lock. With no v3 it is marked
  done, and a v3 that appears later isn't imported. An unreadable v3 is retried (but see C2-5).
- **Keep.** v4 first, then v3, for exact and family matches in the right order; answers carry v4's `store_id` and
  `legacy`. A v3 read error is an error answer, never missing. Ignore and Clear never open v3 (a test). Apart from
  C2-1 and C2-4, correct.
- **cache-2.** Record kinds use `<kind>:<key>` in v4, and datasets keep the folder's row. Every record save's guard
  covers its kind:
  - `listings` (`listings.py:70`);
  - `summaries` (`loading.py:283`, `save_held.py:57`);
  - `summaries` and `histories` (`metadata._send_guard`, which goes to the GUI and back);
  - `subtrees` and `histories` (`scanning.py`).

  So no save is wrongly rejected as `REKEYED`. Per-kind rows left under an old key after a re-key are harmless, as
  the handoff says.
- **Makers.** Every dataset and result save goes through `_upsert_dataset` or `_upsert_result`, which set
  `maker`, and the row goes in within the same transaction. The hostname's privacy note is in the handoff.
- **`.hlb` and the raw layer.**
  - Chunks: offset, length, CRC and size are all checked, including a cut or a flip, and every chunk failure is an
    `HlbError`.
  - A newer `format` is refused, never rewritten.
  - `raw_layer.not_done` mirrors `raw.not_done` line for line.
  - Compact: row 0 first, then a stable argsort. Times below 2^62 are exact in int64, and their deltas can't
    overflow.
  - `check()` ties the arrays' shape to `facts.rows`.
- **Layer = file.** `same_txy` runs every available backend plus `split`, on every case, textscan probe, lab sample
  and fuzz case. Here that is `reference` and `numpy`, and cython only in CI's Converter backends job, which now runs
  `test_raw_layer.py`.
- **`--via-layer`** stays in memory (`check.convert_via_layer`), and a test checks it writes nothing.
- **Format rule.** A newer v4 `format` opens read only and is never set aside. Layout 5 would be `store-v5`.
  `store_v4.migrate` exists and is called on every writable open (empty for now).
- **`cache_move` with two stores.** Every store is verified (integrity, id, named files including `raw/`). The
  record's `store_ids` is additive. Copy recovery is safe: `verified` is reached only after `verify` passes for
  every store. A rename moves both stores at once.
- **`PURE`** includes `helab.utils.hlb` and `helab.convert.raw_layer`. `legacy_store` and `store_v4` are cache
  utilities like `cache_store`, which isn't in `PURE` either.
- **AGENTS.md cache rules.** The store is opened by helpers only. No new removal or housekeeping. `_migrate` still
  runs, plus `store_v4.migrate`. No change to the budget or units. `cache_dir()` isn't bypassed: the store folder
  comes from `store_root(cache_dir())`.
- **Docs.** The handoff's S0-2 line still proposes "add `cleared` to `CONVERT_SETTLING`". CoCo has my correction
  (leave it out of `stuck()`) for when it is applied.

## Checks (run by the reviewer)

I tested an export of `c3c40c5` (`git archive`, with `testdata` and `legacy/tdc_autoconverter` symlinked) in
`.ai/temp/assay/src3`, because Vault keeps working on the branch. The floor checkout now has Vault's uncommitted
`cache_store.py` edit.

- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-assay` (the full suite, which includes every
  touched test): **8695 passed, 673 skipped, 3 failed, 15 rerun in 140.57 s.**
  - **All 3 failures and all 15 RERUNs are the export's lack of `.git`**, the same three tests as at stage 0
    ("rerun reasons": `git clone … exit status 128`; `commit='unknown'`):
    - `test_release_recovery.py::test_detached_pr_stamp_records_source_branch_and_merge_ref_without_replacing_commit`
    - `test_versioning.py::test_frozen_metadata_survives_no_git_and_unrelated_cwd`
    - `test_versioning.py::test_source_provenance_ignores_launch_directory`
  - In a `--shared` clone at `c3c40c5`, `test_frozen_metadata…` still failed (`commit='unknown'`, 5 reruns), again
    the environment. All three pass in the floor checkout, **3 passed, no RERUN**; neither these tests nor
    `build_info.py` changed in this range.
  - No other test needed a rerun. The total matches the worker's 8699 passed and 672 skipped once the export's
    3 and 1 are added back.
- `mypy helab/ --strict` (199 files), `mypy tests --strict` (178), `mypy helab/ --strict --platform win32`: no
  issues.
- `pyright helab tests` and `--pythonplatform Windows` (in the clone at `c3c40c5`): 0 errors.
- Scratch checks, not committed: C2-1 and C2-4 (`.ai/temp/assay/test_zz_cp2.py`), C2-2 and C2-3 (inline scripts,
  quoted above).

On fix diffs I re-check only the fixes, their tests and the type checks of the touched files.

## Re-check of the fixes (`bdbd2bc..6a89c5d`; `d207b61` not included)

**Open findings: 2 new Nits (C2-7, C2-8), each a narrow gap left by a fix. C2-1 to C2-5 are fixed. C2-6 is fixed
in `cache_move`, but takes effect only once the app sends the layout (CoCo's call: see below).**

**Fails without its fix.** For each fix commit I exported that commit, put back its `helab/` files from its parent,
and ran the tests it added. Each test failed without its fix and passed with it:

| Finding | Commit | Without the fix | With it |
|---|---|---|---|
| C2-2 | `471a980` (`hlb.py`) | 5 failed | 5 passed |
| C2-3 | `6d53159` (`store_v4.py`) | 4 failed (`RecursionError`) | 4 passed |
| C2-1, C2-4 | `9d5889c` (`cache_store.py`, `legacy_store.py`) | 10 failed | 10 passed |
| C2-5 | `47a6723` (`cache_store.py`, `store_v4.py`) | 1 failed | 1 passed |
| C2-6 | `0551343` (`admin.py`, `cache_move.py`) | 2 failed | 2 passed |

**C2-2: fixed.** A header CRC32 sits after the length (offset 12; the header starts at 16), and is checked before
the JSON is parsed. Chunks must fill the body in the order listed, with no gap, overlap or trailing byte. The
damage set gains a flipped header byte, a wrong CRC, a gap, an overlap and trailing bytes. My `first_channel` 5 → 7
case is now an error. The addendum's §5 diagram is updated.

**C2-3: fixed.**
- An invalid or empty file is replaced by a new id, atomically: a temporary file, then `os.replace`.
- A missing one is made with `os.link`, so two first starts agree.
- No recursion; any OS error gives `""`.
- Observation, not a finding: the new file gets the default mode (umask), not addendum §4's 0600. Its contents are
  a random id, so this matters little; the addendum's text could say so.

**C2-1, C2-4: fixed.**
- v3 is read through only for a key and kind v4 never removed: the kind's generation, the key's epoch
  (`results:` for results), its root's epoch, or a `legacy-hidden:<kind>:<key>` tombstone written by a `None`
  save.
- Purges by age record their cutoff (`meta.legacy_purged`).
- The checks run inside the read transactions.
- The tombstone rows match no guard key, so no save is affected.
- Counts add only v3 lookups that v4 lacks, and none for a removed key; the step-4 test's 4 is now 3.
- One narrow gap remains: C2-7.

**C2-5: fixed for data roots** (`meta.forgotten_before_import`). The commit says flags are "only set, never
deleted". That's true, but Clear folder preferences turns them off only in the rows v4 already has, which leaves
C2-8.

**C2-6: fixed in the owned code.**
- `start(..., layout=)` records `primary`.
- `checkpoint`, `verify`, `valid_at`, `store_at`, `usable_after_recovery` and `recover` all use it.
- A record without it behaves as before.
- But `CacheMover` (an `app` file) doesn't send the layout yet, so until that one-line change lands, a move with the
  switch off and a leftover `store-v4` still picks v4 as primary. The handoff proposes the change.
- **CoCo's call:** close C2-6 on that proposal, or keep it open until `CacheMover` sends `live_layout()`. Either way
  only a developer with a leftover v4 can hit it, and the data stays safe: both stores are verified.

**Handoff:** the fix table is accurate, and S0-2's proposed fix is corrected (leave `cleared` out of `stuck()`).

### C2-7 · Nit · A later purge that keeps failures brings back v3 histories with failures that an earlier purge hid

- `helab/utils/cache_store.py:721-741` (`_legacy_purged`, `_note_purge`: one cutoff and one flag per kind);
  `helab/utils/legacy_store.py:123` (`records(..., keep_failures=)`).
- **Scenario.**
  1. Keep is on, and v3 holds a scan history with failures, saved at 50.
  2. The user purges records at cutoff 100, failures included. The history is hidden. Good.
  3. A later purge by age at cutoff 200 keeps failures (the default). `_note_purge` replaces the entry with
     `[200, False]`, and `records(before=200, keep_failures=True)` lets every v3 history with failures through.
  4. The history from step 1 is back. A history with failures blocks automatic scans of that folder again.
- **Fix.** Keep two cutoffs per kind: the latest, and the latest of a purge that took failures. Hide v3 histories
  with failures saved before the second.
- **How verified.** Scratch test (`.ai/temp/assay/test_zz_cp2fix.py`, run on code identical to `6a89c5d`): after
  the first purge `read_record` is missing; after the second it returns `{'failures': [{'x': 1}]}`.

### C2-8 · Nit · A Clear folder preferences made before a retried import is undone by that import

- `helab/utils/store_v4.py:200-240` (`import_legacy`: `INSERT OR IGNORE` of `folder_prefs`/`convert_prefs`);
  `cache_store.clear_prefs` turns off only the rows v4 has, and records `prefs_cleared_at`, which is checked on
  writes only.
- **Scenario.**
  1. v3 can't be read when v4 is created, so the import is pending.
  2. In v4, the user clears folder preferences (every flag off).
  3. At the next writable open, the import adds v3's rows that v4 lacks, Don't cache on included, with their old
     `set_at`. The flag the user just turned off is on again.

  Same class as C2-5, which fixed only `roots`. Rare: it needs v3 to be unreadable at v4's creation.
- **Fix.** In the import, import a `folder_prefs`/`convert_prefs` row with `set_at <= prefs_cleared_at` with its
  flags off, or skip it.
- **How verified.** Same scratch file: after `clear_prefs(100)` and the retried import, `read_prefs(FLAGGED)` gives
  `{'no_cache': True, …, 'set_at': 10.0}`.

**Checks (re-check).** On an export of `6a89c5d`:
- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-assay` (the full suite, every touched test
  included): **8719 passed, 673 skipped, 3 failed, 15 rerun in 153.63 s.**
  - All 3 failures and all 15 RERUNs are the same three git-provenance tests as before, failing because the export
    has no `.git` (5 reruns each).
  - Those three pass in the floor checkout: **3 passed, no RERUN**. Neither they nor `build_info.py` changed since
    `6a89c5d`.
  - No other RERUN.
- `mypy helab/ --strict` (199 files), `mypy tests --strict` (178), `--platform win32`: no issues.
- `pyright helab tests` and `--pythonplatform Windows` (code identical to `6a89c5d`): 0 errors.
- The fails-without-fix table above, and the C2-7 and C2-8 scratch tests.

On the C2-7 and C2-8 fixes (and C2-6's wiring, if it lands here) I'll re-check only those diffs.
