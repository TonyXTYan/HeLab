# Review: Caching v2 checkpoint 3 (switch still off)

Reviewer: Assay (Claude Opus 5.5), 2026-10-31. Read-only on code. The code commits after checkpoint 2 landed:
- `34ec22c` cache-1;
- `fc25864` step 5 (`raw_fill`, conversions' raw rows, Q28.6);
- `fe7957b` step 6 (the store-v3 question, Settings › Cache's rows);
- `8627566` the export item (`helab cache dump|export`);
- `393f999` step 7 (the integration check).

The `dev/v0.0.8` merges (`f5fe405`, `cd5b0d1`) and handoff-only commits are skipped. Read: the handoff's steps 5–8,
the addendum's §10–11, the brief's steps 5–7 and Data safety, AGENTS.md (current).

**Verdict: no blocker while the switch is off. 6 findings: 0 High, 1 Medium, 1 Low, 4 Nit.**
- Every finding is reachable only with the `store_v4` switch on, except C3-5 (docs) and C3-6 (the export CLI).
- C3-1 should be fixed before the switch is turned on for anyone with large raw files.

## Findings

### C3-1 · Medium · A conversion's raw rows have no byte limit and no heartbeat, so a large-shot folder can time out the conversion

- `helab/io_ops/convert.py:858-865` (`_RawRows.add` flushes at `BATCH_SHOTS` only) and `:866-874` (`flush` →
  `save_batch(..., beat=None)`); `helab/io_ops/raw_fill.py:110-119` (`save_batch` beats only between shots, and
  only when given a beat).
- **Scenario.** The switch is on, and Live auto-convert (or a Convert) runs on a folder of large shots, say
  20 MB each (`SPLIT_BYTES` is 20 MB, so such shots exist).
  - **Memory.** `_RawRows` keeps every converted shot's raw bytes until 50 have gathered. `raw_fill` also stops at
    `BATCH_BYTES` (64 MB); `_RawRows` doesn't. That is up to about 1 GB held in the helper.
  - **Time.** `flush` then encodes all 50 at zstd 9 in the conversion's own thread, with no heartbeat. At the
    addendum's measured 16 MB/s per M4 thread on real samples, 1 GB takes about 60 s; at the lab PC's estimated
    4–5 MB/s, about 200–250 s. Both pass `NO_PROGRESS_TIMEOUT` (60 s), so `IOService` kills the conversion.
  - **Result.** The conversion ends in an error, which in Live stops auto-convert until Retry
    (`explorer_live.py`'s `convert.error`). Its TXY were already written, but the raw rows of the batch are lost.
- `raw_fill` has the same heartbeat gap for one very large file: `raw_layer.encode` and `to_hlb` run without a
  beat. A single raw file of a few hundred MB takes over 60 s on the lab PC, so the fill is killed every time a save
  queues it.
- **Fix.**
  - `_RawRows.add` flushes at `BATCH_BYTES` too.
  - Encode under a heartbeat. The converter's `_Ticker` with `compute_budget(len(data))` fits, or pass the
    conversion's `Heartbeat` into `save_batch`.
  - In `raw_fill`, run each shot's encode under the same kind of ticker.
- **How verified.** By reading.
  - A synthetic 19 MB raw file encodes in 0.32 s here (60 MB/s): sorted synthetic data compresses better than
    real shots. So the timings above use the addendum's measured real-sample rate and its lab-PC estimate, not a
    run on the lab PC.
  - The memory bound follows from `add`'s single condition.

### C3-2 · Low · `raw_fill` caches a half-written raw file, and its completion is then reported as "overwritten: the TDC may be misconfigured"

- `helab/io_ops/raw_fill.py:197-215`: it reads any file settled by age and unchanged during the read, with no
  `not_done` check. `FolderCache._raw_overwritten` then raises the Q28.6 desktop notice.
- **Scenario.**
  1. The TDC pauses mid-file for longer than the settle time (default 5 s). The converter guards against exactly
     this: `raw.not_done` says "no final newline: it may still be being written", and the file waits until it
     is damaged at 20 s.
  2. `raw_fill` caches the partial file's layer.
  3. When the TDC finishes, the next fill sees another fingerprint, replaces the row and sends `raw_overwritten`:
     a desktop notification, an amber Folder details line and a log warning saying the TDC may be misconfigured.
     It isn't. Q28.6's warning should mean a file changed in place after it was done.
- **Fix.**
  - In `raw_fill`, treat a file whose layer facts fail the trigger-free checks (`blank`, no `final_newline`) as
    waiting, as the converter does. Conversions' raw rows already pass `not_done`.
  - Optionally, don't send `raw_overwritten` when the replaced row's facts say it wasn't finished.
- **How verified.** Scratch test (`.ai/temp/assay/test_zz_c3.py`, on the export of `393f999`): a `d4.txt` cut
  mid-line is saved by the first fill, and after the file is completed the second fill sends `raw_overwritten` for
  `d4.txt`.

### C3-3 · Nit · The store-v3 choice is never compared with v3's `store_id`, so a recreated store-v3 isn't asked about again

- `helab/utils/cache_store.py:3125-3149` (`set_legacy_choice` records `v3_store_id`, and its docstring says "so a
  store-v3 an older HeLab makes again later is asked about again"); `helab/utils/store_v4.py:287`
  (`legacy_choice` reads only `choice`).
- **Scenario.**
  1. The user answers Ignore, or Clear.
  2. An older HeLab started by hand on that machine (the case `LegacyStore` exists for) makes a new store-v3.
  3. `legacy_choice` still says `ignore` or `clear`. The new v3 is never asked about and never read through.
     After `clear` it isn't counted in the budget either.

  Nothing is lost, but the docstring's promise isn't kept, and the Settings row shows a stale choice.
- **Fix.** Treat the choice as unanswered when the present v3's `store_id` differs from `v3_store_id`, at
  `measure_legacy` and `_kept_legacy`. Or drop the promise.
- **How verified.** `grep v3_store_id helab`: it is written in `set_legacy_choice`, `clear_legacy` and the import,
  and compared nowhere.

### C3-4 · Nit · A Clear of store-v3 cut short leaves a `store-v3.clearing-<hex>` folder nothing shows or removes

- `helab/utils/cache_store.py:3151-3181` (`clear_legacy`: rename aside, then `shutil.rmtree(aside,
  ignore_errors=True)`, returning the bytes measured before).
- **Scenario.** On Windows a file held open (an antivirus scan, an indexer) makes `rmtree` skip it. The folder
  `store-v3.clearing-1a2b3c4d` stays in the cache folder:
  - `older_stores` doesn't list it (`name[7:]` isn't digits);
  - no Clear offers it;
  - the reply says every byte was removed.
- **Fix.** Report what is left. List `store-v*.clearing-*` folders in `older_stores`, or retry their removal at
  the next Clear old stores… (they are HeLab's own, already asked for).
- **How verified.** By reading.

### C3-5 · Nit (docs) · AGENTS.md's "only helpers (and `helab convert`) open the store" now has a third opener

- `helab/cache_cli.py:112-118`, `:131` (`helab cache export --folder` opens store-v4's `records.sqlite`,
  `mode=ro`, `query_only`, `NO_CKPT_ON_CLOSE`).
- **Scenario.** The rule in AGENTS.md's disk-cache section still names only helpers and `helab convert`. The
  handoff's step 8 proposes the code-map row and a `cache-store.md` bullet, but not this rule.
- **Proposed wording:** "Only helpers, `helab convert` and, read only, `helab cache` open the store …".
- **How verified.** By reading AGENTS.md (current) and the handoff's step 8.

### C3-6 · Nit · `helab cache export --folder` with a store it can't open dies with a traceback and exit 1 ("nothing to export")

- `helab/cache_cli.py:131` (`_read_only` is called outside the `try`), `:112-118`.
- **Scenario.** `records.sqlite` exists but can't be opened (permissions, or a WAL store without `-shm` in a
  read-only folder). `sqlite3.connect` raises `OperationalError`, which escapes `main`. Python exits 1 with a
  traceback, the code the docstring gives to "nothing to export", not 2 with a message.
- **Fix.** Catch `sqlite3.Error` around `_read_only` as a `CliError`.
- **How verified.** A script on the export: a `records.sqlite` with mode 000 under `--cache` gives
  `escaped: OperationalError unable to open database file`.

## Checked, no finding

- **`raw_fill` and the I/O rules.**
  - It's a helper operation, in `SOURCE_OPERATIONS` (guarded, and refused offline by `OFFLINE_REFUSED`) and
    `CACHE_ONLY`. `IOService` lists it in `CACHE_OPERATIONS` (held during a cache move) and `PAUSABLE`, with a
    label and a noun. Its owner `raw_fill:<path>` isn't a foreground owner, so it runs on the background lane.
  - It holds its slot until exit, through `IOService`'s unchanged rule.
  - Its timeout is `NO_PROGRESS_TIMEOUT`, fed by heartbeats per listed entry, per 8 MB read block and per encoded
    shot (see C3-1 for the gap inside an encode).
  - **Bounded and deduplicated:** one per folder (`_raw_fills`). A request while it runs, or a yield (`more`),
    queues it once more after `done`, at the back. An error doesn't retry. It yields after about 30 s.
  - **Refusals:** offline, while quitting, for Don't cache, and in store-v3 (`schedule_raw_fill`, and again in the
    helper); without a data root, the helper answers `no_data_root`; a read-only store answers `read_only`.
  - It checks `Pause.checkpoint` per shot.
  - **Settled reads:** `settled_by_age`, not dated ahead, `fstat` before and after, and `read_at` taken before the
    read (C2-10's rule kept). Each batch's files are published just before its save.
  - Triggered by a valid `cache_saved` only, never by listings or scans.
- **Conversions' raw rows.** Only online, in store-v4, with a data root, for output to the cache or beside. One raw
  guard per conversion. Store trouble gives one `cache_warning`; a `SaveRejected` stops raw rows quietly and never
  fails the conversion (apart from C3-1). `read_at` comes from each shot's read.
- **Q28.6.** Once per shot per session: `events.notify` with a key, a log warning, and an amber Problems line in
  Folder details that stays one line, with the files in its tooltip.
- **cache-1.** `_root_prefs_gone` runs beside `_root_constants_gone` at all three places. It drops `prefs`,
  `_confirmed_prefs` and `convert_prefs` for the folders the old root held (not those of a nested root), and keeps
  a folder whose flag write is in flight.
- **Step 6.**
  - **The question:** asked once a session while unanswered; closing it answers nothing; Keep and Ignore go
    through `legacy_choice`.
  - **Clear of store-v3:** asked with its size and refused while `other_instances` names another HeLab. Older
    HeLabs register in `instances/` too (checked at 0.0.7a1, `e03c32a5`). `clear_legacy` renames aside, never
    follows a link, and sends `removed` kind `legacy`.
  - **Make room** names raw pulses and only copies, and removes exactly `room_items`. Its "Clear old stores…" is a
    separate, asked choice.
  - **Settings › Cache:** the Raw pulses and Older cache rows; Clear all passes `raw` in store-v4
    (`CacheTab.py:559`).
  - **IDs and names:** `cache_clear_raw`, `cache_legacy_choice`, `cache_clear_legacy`; the message boxes'
    buttons through `_open`'s `identify_buttons` and `disk_cache_clear_old`. `test_accessible_names` passes.
- **Nothing removed without asking.** Raw rows go only through Clear all, Clear raw (which warns about only
  copies), a root's Clear, Make room's named plan, and Don't cache's seen layers (C2-9). store-v3 goes only by an
  asked Clear. No new housekeeping.
- **The export.**
  - `helab/main.py` dispatches `cache` after the frozen `--helab-io-helper` entry and `convert`, before any Qt or
    cache import.
  - It never writes into a `store-v*` folder and never replaces a file without `--force`.
  - The store is read `mode=ro` without checkpointing; `test_cache_cli` hashes the store's files.
  - `hlb.read` and `raw_layer.columns` are Qt-free.
  - With `--folder` and no `--cache`, it imports `constants`, which may create the temp and cache folders as
    `helab convert` does. A~6 already proposes covering this.
- **Fails without its change, where claimed.**
  - `34ec22c`: with `folder_cache.py` put back as it was before it, `test_root_change_flags.py` gives **3 failed,
    1 passed** (the nested-root case passes either way), and 4 passed with it.
  - `393f999`: with the handoff's mutation applied to `admin.py`'s Clear default (`or KINDS`, leaving out raw),
    `test_caching_v2_session.py` **fails**; as committed it passes.
  - The other commits make no such claim.

## Checks (run by the reviewer)

On an export of `393f999`, whose `helab/` and `tests/` equal `HEAD` `c63f89e` (the floor was clean):
- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-assay` (the full suite: every touched test,
  `test_raw_fill.py`, `test_store_v3_question.py`, `test_cache_cli.py`, `test_caching_v2_session.py`,
  `test_root_change_flags.py` included): **8847 passed, 673 skipped, 2 warnings, 3 failed, 15 rerun in 158.83 s.**
  - All 3 failures and all 15 RERUNs are the three git-provenance tests (the export has no `.git`; 5 reruns each).
  - In the floor checkout (same code): **3 passed, no RERUN**.
  - No other RERUN.
  - The 2 warnings are the known pyqtgraph ones.
  - The totals match Vault's 8851 passed and 672 skipped, once the export's 3 and 1 are added back.
- `mypy helab/ --strict` (201 files), `mypy tests --strict` (186), `--platform win32`: no issues.
- `pyright helab tests` and `--pythonplatform Windows`: 0 errors.
- Scratch checks, not committed:
  - C3-2: `.ai/temp/assay/test_zz_c3.py`;
  - C3-6: an inline script;
  - the encode timing: 19 MB in 0.32 s on this M4, synthetic data;
  - the two mutations above (in copies, `.ai/temp/assay/mut-*`).

On fix diffs I re-check only the fixes, their tests and the touched files' type checks.
