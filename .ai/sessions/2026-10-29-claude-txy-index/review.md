# Review: one index for HeLab's converted TXY (`agent/txy-index`)

Reviewer (Claude Opus 5.5), 2026-10-29. Branch `agent/txy-index` at `1e7329c`; base `1d3bbb9`, with
`dev/v0.0.7` (`9f0b21f`) merged. I reviewed `git diff 9f0b21f...HEAD` (17 files) against the brief,
`AGENTS.md`, `.ai/architecture/converter.md` and Ledger's handoff. I didn't edit any code.

**Count: 1 High (it blocks landing: Windows CI is red), 4 Low, 3 Nit.**

## Checks I ran (floor venv, `.ai/local/floor-env.sh`, macOS)

- Full suite: `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`:
  **8195 passed, 669 skipped, 0 reruns** (123.6 s).
- `mypy helab/ --strict`: no issues (191 files). `mypy tests --strict`: no issues (159).
  `mypy helab/ --strict --platform win32`: no issues (191). `pyright helab tests`: 0 errors.
  `pyright --pythonplatform Windows helab tests`: 0 errors.
- I reproduced Low-1 and Low-2 by hand with a script in my scratchpad (output quoted below).

## CI run 40863356565 (head `1e7329c`)

**Conclusion: failure.** I read every job's log (the `ERROR:root:` lines are tests' expected log
output).

| Job ID | Job | Result |
|---|---|---|
| 123411955202 / 123411955244 / 123411955281 | Build (ubuntu / macos / windows) | success |
| 123411955434 | macos Converter backends | success: 675 passed, 516 skipped |
| 123411955614 | ubuntu Converter backends | success: 675 passed, 516 skipped |
| 123411955568 | **windows Converter backends** | **failure:** 1 failed, 673 passed, 517 skipped, 5 rerun: `…[newer]` (High-1) |
| 123411955474 | macos Tests (1/2) | success: 4082 passed, 322 skipped |
| 123411955446 | macos Tests (2/2) | success: 4113 passed, 347 skipped |
| 123411956066 | ubuntu Tests (1/2) | success: 4080 passed, 324 skipped |
| 123411955657 | ubuntu Tests (2/2) | success: 4113 passed, 347 skipped |
| 123411955728 | windows Tests (1/2) | success: 4069 passed, 333 skipped, no rerun |
| 123411955603 | **windows Tests (2/2)** | **failure:** 1 failed, 4096 passed, 361 skipped, 6 rerun |

RERUNs, quoted from the "rerun reasons":

- `tests/test_convert_helab.py::test_a_missing_or_damaged_index_only_means_shots_convert_again[newer]`:
  five reruns, then FAILED, in both Windows jobs. `IndexUnavailable: HeLab's TXY index is newer and
  couldn't be set aside ([WinError 32] The process cannot access the file because it is being used by
  another process …)`. This is High-1.
- `tests/test_io_service_run.py::test_writing_held_data_out_counts_as_progress` (windows Tests
  (2/2), one rerun, then passed): `assert (2 == 1)` with
  `where 2 = len([0.000682100000005903, 0.0014403000000129396])`, at `tests\test_io_service_run.py:40`.
  This branch doesn't touch `IOService` or that test, so I don't think this branch caused it. It
  isn't in `roadmaps/known-issues.md`, so it needs an entry there (a Windows timing flake: two
  progress marks where the test expects one).

## Findings

### High-1: on Windows, the `[newer]` damaged-index test fails every run because the test leaves its own SQLite connection open

- **Where:** `tests/test_convert_helab.py:1306` (`with sqlite3.connect(index) as conn:` in
  `test_a_missing_or_damaged_index_only_means_shots_convert_again`). The same pattern is at
  `tests/test_convert_helab.py:172` in `test_provenance_rows_round_trip_and_say_what_is_stale`.
- **Why:** used as a context manager, Python's `sqlite3.Connection` commits or rolls back but
  **doesn't close** (checked locally: the connection still answers after the `with` block). In the
  `newer` case, the test's `conn` keeps `index.sqlite` open. On Windows a file another handle holds
  open can't be renamed, so `provenance.set_aside` (`helab/convert/provenance.py:173`,
  `os.rename(path, aside)`) raises `WinError 32`, and `open_index` turns that into `IndexUnavailable`.
  CI job 123411955568 ("windows + py3.13 / Converter backends") shows
  `RERUN …test_a_missing_or_damaged_index_only_means_shots_convert_again[newer]` five times, then
  `FAILED` with "HeLab's TXY index is newer and couldn't be set aside ([WinError 32] The process
  cannot access the file because it is being used by another process …)". Summary:
  `1 failed, 673 passed, 517 skipped, 5 rerun`. The production code closes its own connection
  before setting the file aside (`open_index`'s `conn.close()`), so the fault is the test's.
- **Fix:** in both places, `with contextlib.closing(sqlite3.connect(...)) as conn:`. Line 172 also
  needs an explicit `conn.commit()` after its `UPDATE`, because `closing` doesn't commit. Then push
  and read the new run job by job. The handoff should also note that on Windows a damaged or newer
  index can't be set aside while another process has it open (for example a running `helab convert`
  or a load). That case is transient: the conversion fails with `IndexUnavailable` and is tried
  again.

### Low-1: Settings › Cache's Clear sets aside and then deletes a *newer* HeLab's index, including its beside rows

- **Where:** `helab/io_ops/helab_txy.py:428` (`open_index(root, write=True)` in `clear_converted`)
  and `:469` (removing the files that match `SET_ASIDE_PATTERN`).
- **Why:** `open_index(write=True)` sets aside an index with `user_version` above 1 as
  `index-newer-…`, and the same Clear then deletes every set-aside file. An older build's Clear
  therefore destroys a newer build's whole index, including the rows of beside TXY. The docstring
  promises those rows stay ("the only account of how they were made"). Reproduced:
  `user_version = 2` index plus one TXY → after `clear_converted`, the directory holds `['abc',
  'index.sqlite']` (a fresh index) and the newer one is gone (its 4096 bytes are counted in
  `cleared`).
- **Fix:** in `clear_converted`, open the index as a reader first. Write rows only when its schema is
  `SCHEMA`; set a file aside only when it is damaged. Leave a newer index untouched and skip its row
  updates. Add a `newer` case to a Clear test.

### Low-2: old builds' `.folder.json.<16 hex>.partial` leftovers are no longer removed, measured or cleared by anything

- **Where:** `helab/io_ops/helab_txy.py:316` (`_OWN_FILE`) and `helab/io_ops/convert.py`
  (`own_partial()` is now `partial()`).
- **Why:** before this branch, `own_partial()` removed `.folder.json.<hex>.partial` as housekeeping.
  Now it doesn't, and `_OWN_FILE` never matched that name. The handoff says old builds' JSON
  temporaries "are cleared only by Settings › Cache", but that holds only for
  `.d_txy_helab_*.json.*.partial`. The leftover also keeps Clear from removing its hash folder.
  Reproduced: after `clear_converted`, `abc/` still holds `.folder.json.0123456789abcdef.partial`.
  Only tonight's dev builds could have made one.
- **Fix:** add `|\.folder\.json\.[0-9a-f]{16}\.partial` to `_OWN_FILE`, with a test that Clear
  counts and removes it and that look-alikes stay.

### Low-3: `helab_txy.find` imports `read_shots` by value, and tests patch that name

- **Where:** `helab/io_ops/helab_txy.py:105`. The patch is in
  `tests/test_txy_sources.py::test_records_are_read_only_for_shots_helab_could_give`
  (`monkeypatch.setattr(provenance, "read_shots", …)`).
- **Why:** the rule in AGENTS.md and io-and-browsing says a name tests patch is called as
  `module.name` from other modules, never imported by value. The code works today only because the
  import sits inside the function.
- **Fix:** call `provenance.read_shots(...)` in `find`, and propose adding `provenance.read_shots` to
  io-and-browsing's list of patched names.

### Low-4: proposed docs: the network-share wording and "read-only"

- **Where:** the handoff's "Journal mode" section ("If the cache folder isn't local") and its
  io-and-browsing proposal ("read-only, never created or set aside by a load").
- **Why:**
  - `cache_location.cache_location_problem` (`helab/utils/cache_location.py:52`) already refuses a
    cache folder on a network drive or a UNC path. Separately, `provenance._connect` builds a
    `file://server/share/…` URI from a UNC path, which SQLite refuses ("invalid uri authority:
    server"; checked locally on SQLite 3.53.1). So the share case can't happen for the cache folder,
    and with a UNC temp-folder override every index open would fail.
  - A load isn't read-only on the index: `_mark_used` → `TxyIndex.touch` writes `last_used` (Q~3).
- **Fix:** in converter.md, say the cache folder can't be on a share (it is refused), so DELETE mode
  is for local disks. In io-and-browsing, say "never created or set aside by a load, which only
  moves its folder's `last_used` on at most hourly".

### Nit-1: `converted_usage` reports a file's size from its row, not the file

`helab/io_ops/helab_txy.py:385`: `size = known.get((folder.name, entry.name))`. Suppose a redo is
killed after its row: the row pins the new temporary file's size, while the older TXY stays on
disk. Or someone replaces a TXY by hand. In both cases the row's size is reported. It only affects
the byte figure shown. Either take the row's size only when its `(size, mtime)` match the entry,
or use `entry.stat()` (free on Windows).

### Nit-2: orphan rows are never pruned

Some rows name a TXY that isn't on disk (a conversion killed between its row and the rename, or a
TXY deleted by hand). Nothing removes them, and Clear removes only rows of the files it deletes, so
their `folders` row stays too. It's harmless: the primary key replaces them on the next
conversion, and Settings › Cache counts files, not rows. Worth an A~ follow-up: Clear could drop
non-beside rows whose TXY is missing.

### Nit-3: `read_shots` closes its index twice

`helab/convert/provenance.py`: `read_shots` calls `index.close()` in its `except` and again in
`finally`. That's harmless (`close` is idempotent), but the `except` call can go.

## What I checked and found right

- **When a shot is current:** the row is written in `before_rename` with `os.stat(temporary)` after
  fsync and close. The rename keeps size and mtime (`os.replace`, and the hard-link and rename
  routes for beside). The test checks this on all three OSes. A kill between row and rename leaves a
  row matching no TXY, and `stale` compares `(size, mtime)`, so an older TXY of the same size isn't
  taken (`[False]` case). `forget` deletes the row only where `txy_sha256` and `txy_mtime_ns` are
  this write's, and is suppressed on `OSError`. `finish` runs on the helper's main thread, so the
  single connection is never shared across threads.
- **Two writers:** each write is one `BEGIN IMMEDIATE` transaction with a 10 s busy timeout. Index
  creation re-checks `user_version` under the lock. DELETE journal. The two-process test checks
  every row and `integrity_check`. Readers use `mode=rw` and never create a file.
- **Missing, damaged or newer index:** shots convert again. The set-aside name matches
  `SET_ASIDE_PATTERN` exactly, and nothing deletes it but Clear (see Low-1 for the newer case).
  `IndexUnavailable` fails the conversion before the rename.
- **Q27.4:** the store's `no_cache` flag is read for the exact folder, as `FolderCache.folder_prefs`
  does ("never its parent's or subfolders'"). If the flag can't be read, or the store can't be
  opened, the TXY go to temp, with the right fallback text. `folders()` looks in `(temps, key)`, so
  loads find them (test passes).
- **Q27.5:** Clear removes only the files it lists, never a link. It removes rows by
  (name, size, mtime) and never beside rows, keeps the index, and is confirmed first in the GUI
  (`CacheTab.clear_converted`). `FolderCache.cache_admin` passes `temps`. The GUI never opens the
  index: no `provenance`, `open_index` or `sqlite3` use in `helab/views`, `helab/utils` (outside the
  store and the move), `helab/models` or `helab/analysis`.
- **Housekeeping:** `own_partial()` is `partial()`, and its tests include the look-alikes and the
  index names. Old JSON is ignored, but measured and cleared (except Low-2).
- **Cache-folder move:** `converted-txy/` is inside the cache folder. The rename and copy routes are
  both tested, and nothing converts again afterwards.
- **Converter bytes:** `tests/data/convert/` and the byte-for-byte tests are untouched, and
  `write_atomic` writes the same bytes. Converter-backends jobs on macOS and Ubuntu: 675 passed.
- **Helper events:** `ConvertedUsageField` and `ConvertedSummaryField` are typed at the send, and
  `test_the_converted_txy_summary_is_the_declared_shape` checks both admin paths.
- **Strict typing, win32 included:** all clean (above).
- **Q~1–Q~4, A~1, A~2, M~1, M~2:** I agree with the proposals. Q~1 (size and mtime) is what makes
  "row before rename" safe.
