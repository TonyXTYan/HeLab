# Handoff: caching v2 (`agent/caching-v2`), Vault

Worker: Vault (Claude Opus 5.5). Brief: [brief.md](brief.md). Updated at each checkpoint.

## Stage 0 (checkpoint 1): A19.2, cache-5, cache-4, cache-6

Commits on `agent/caching-v2` (base `92fc597`, `dev/v0.0.8` at `d9d647f` merged):

| Commit | What |
|---|---|
| `b4ab6f6` | cache-5: a save whose guard names a re-keyed folder is `SaveRejected("cleared", REKEYED)`, its file retired at once |
| `46f481f` | cache-4: tests close the `sqlite3` connections they open (29 blocks in 11 files) |
| `cd6edca` | cache-6: `admin.py`'s comment on `prefs` and volume hints |
| `ce8eae7` | A19.2: the Clear fence between Clear converted TXY and a running conversion |

Checks at `ce8eae7` (macOS, M4 Max): `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`:
**8522 passed, 672 skipped, 2 warnings in 251.95s; no RERUN** (the warnings: pyqtgraph's NumPy 2.5
`arr.shape` DeprecationWarning in `test_t_spectrum.py`, known); `mypy helab/ --strict`, `mypy tests --strict`,
`mypy helab/ --strict --platform win32`: no issues; `pyright helab tests` and `--pythonplatform Windows`:
0 errors. Log: `.ai/temp/stage0/suite.log`.

Files outside the brief's owned paths, approved by CoCo (2026-10-31): `helab/convert/provenance.py` (the
fence) and `helab/convert/txy.py` (`write_atomic`'s optional `after_rename`). Both stay Qt-free and in `PURE`.

### A19.2: how the fence works

- `converted-txy/index.sqlite` gains a `fence` table (one row: a random token, `cleared_at`), added
  **within schema 1**: `CREATE TABLE IF NOT EXISTS` by the first Clear (and in `_TABLES` for a new index);
  `user_version` stays 1, so 0.0.7a1 reads and writes the index unchanged (convert-3's constraint).
- `clear_converted` first sets a new token (`TxyIndex.set_fence`, one `BEGIN IMMEDIATE`), then lists the
  folders and removes, as before.
- A conversion into the cache or temp base reads the token when it starts (`provenance.fence_of`, right
  after `_places`, before the listing). For each TXY: the row is written only while the token is unchanged
  (`record(fence=…)`, checked inside the row's transaction), then `hold(fence)` takes `BEGIN IMMEDIATE` and
  checks again, `write_atomic` renames, and `after_rename=index.release` lets go at once (a `finally` lets
  go too if anything failed before the rename). The row is still committed before the rename.
- So a Clear's `set_fence` lands either before the hold (the write is refused: `provenance.Cleared`, the
  temporary removed by `write_atomic`, the row forgotten) or after the rename (it waits on the lock, then
  lists and finds the TXY and removes it with its row). Each refused shot, and every later shot of that
  conversion (unread: `read` checks `index.fence()` first), is `shot_waiting` with reason `cleared`
  (`convert.CLEARED`); the next check converts them. A `FileNotFoundError` from the write while the fence
  has moved (a Clear removed the in-flight temporary, which `_OWN_FILE` matches) counts the same.
- Beside writes aren't fenced (`fence` is None): Clear never removes them.

CoCo's three points and the `after_rename` question:

1. **An older HeLab's Clear is unfenced.** 0.0.7a1's `clear_converted` never sets the token, so its Clear
   against this build's running conversion behaves as before (may leave TXY). Likewise 0.0.7a1's
   conversions never check it, so this build's Clear vs an old conversion is unfenced too.
2. **The held lock spans the rename alone.** `hold` is the last thing in `before_rename`; `after_rename`
   runs right after `os.replace`/`_rename_new` and before `_fsync_folder`. **Busy past `BUSY_SECONDS`**
   (10 s): `hold` raises `IndexUnavailable` with nothing held; `write_atomic` removes the temporary; the
   row is forgotten (or, if that is busy too, left matching no TXY on disk, so the shot is converted
   again); the exception fails the conversion as any index write it can't make does today, and the app
   tries again. The TXY already there is untouched (no rename happened): never a lost TXY. Test:
   `test_a_busy_lock_for_the_rename_fails_the_conversion_and_loses_no_txy`.
3. **Clear between pin and rename, both orders**: `test_a_clear_between_the_row_and_the_rename`
   (`before the lock`: refused, no TXY, no row, shot 2 waits unread; `while the rename holds it`: the
   Clear is shown blocked with the token unchanged, then removes the TXY and its row after the rename).
   Also `test_a_clear_after_a_conversion_started_refuses_its_rows_and_its_shots_wait` (fence moved before
   the row) and `test_the_fence_table_is_added_within_schema_1`.
4. **`after_rename` raising after the rename**: the TXY is in place and its row committed; `write_atomic`'s
   handler only removes the temporary name (already gone) and re-raises, skipping the folder fsync. In
   the converter the callback is `TxyIndex.release`, which suppresses `sqlite3.Error`, so it doesn't raise
   in practice; if it did, the `finally` calls `release` again (idempotent: `_held` is cleared first, and
   SQLite drops the lock with the connection at `index.close()` anyway). The converter's `except` would then
   forget the row of a TXY that exists, so that shot converts again next time (no loss). Test:
   `test_write_atomic_calls_after_rename_between_the_rename_and_the_folders_fsync` (default path unchanged;
   order rename → callback → fsync; raising leaves the file).

Gaps left (documented in `clear_converted`'s docstring):
- A base with **no index yet** isn't fenced: Clear makes no index (it would show as kept bytes in Settings ›
  Cache). Only the base's first conversion since the index (Q26.2), between its start and its first
  `open_index(write=True)` (the listing), can still write after such a Clear.
- A **damaged or busy** index isn't fenced (Clear can't write it); a **newer** HeLab's isn't ours.
- **Clear removes in-flight temporaries** (`_OWN_FILE` matches `.d_txy_helab_…partial` of any age). A
  conversion that started before the Clear now treats that as `cleared`; one that started *after* the
  Clear's token, while the Clear is still removing, can have its temporary removed and fail that shot's
  write (FileNotFoundError, the conversion fails and is tried again). Pre-existing, very small window.
  Proposed A~1 below.

### cache-5

`_guard_holds` and `_check_result_guard` raise `SaveRejected("cleared", cache_store.REKEYED)` ("The
folder's data root changed before saving completed") instead of `ValueError`. Every save path already
handles `SaveRejected`: `save_dataset`/`add_pending` retire the file (`_reject_file`), `save_result`
retires it (`_reject_result_file`), `result_save` sends `result_not_saved` (reason `cleared`), listings and
summaries swallow it as before, and `confirm_dataset`'s caller (which caught only `StoreError`/
`SaveRejected`) no longer lets a raw `ValueError` escape. `adopt_pending_result`'s `except ValueError` is gone.

### cache-4

All 29 `with sqlite3.connect(…) as c:` blocks in tests are `with contextlib.closing(sqlite3.connect(…)) as
c, c:` (commit on exit kept, connection closed). The other direct connections in tests already close in
`finally`. Checked with a `gc.collect()` after every test and `-W always::ResourceWarning` on the 11 files:
no `unclosed database`; the same on the old `test_cache_switch.py` shows the leak
(`.ai/temp/cache-4/gc_plugin.py`, not committed).

## Proposed doc changes (for the Coordinator)

- **known-issues** (cache-4): replace the `test_cache_switch.py` leak entry with: "Fixed on
  `agent/caching-v2` (`46f481f`): the leaks were the tests' own `with sqlite3.connect(...)` blocks (29 in
  11 files; sqlite3's context manager commits but never closes), not the store's error paths; tests now use
  `contextlib.closing`." In the entry above it (`test_root_discovery.py::test_volume_check_alone_…`), the
  sentence "The collected object may be one of `test_cache_switch.py`'s leaked connections (next)" becomes
  "…may have been one of the tests' leaked connections (fixed, `46f481f`); the patch-the-name fix still stands."
- **cache-store.md**, "Tables added within store-v3" (cache-6): "…and its re-key of a nested root leaves the
  subtree's constants (0.0.5) and converter flags (0.0.6) behind, and a 0.0.6 HeLab's Clear folder
  preferences leaves `write_beside` on."
- **cache-store.md**, "Converted TXY in the cache folder" (A19.2): add "Clear fences conversions already
  running (A19.2): it first sets a new token in the index's `fence` table, and a conversion that started
  before writes no TXY after it (its shots wait as `cleared` and convert at the next check); a base with
  no index yet, a damaged or busy index and 0.0.7a1's Clear or conversions aren't fenced."
- **converter.md**: the same in the converter's index section, plus "`txy.write_atomic` takes
  `after_rename` (run after the rename, before the folder fsync)" and the `shot_waiting` reason `cleared`.
- **AI_TODO**: A19.2 done.

## Follow-ups (provisional)

- **A~1** Clear converted TXY skips temporaries younger than `PARTIAL_MAX_AGE` (1 h) like housekeeping
  does, so it never removes a running conversion's in-flight file (today it removes every
  `_OWN_FILE` partial). Small; changes what Clear's inventory calls clearable.
