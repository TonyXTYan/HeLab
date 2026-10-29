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

## Round 1 re-check (head `9691873`, `git diff 1e7329c..9691873`)

**Result: no open findings.** High-1, Low-1 to Low-4 and Nit-1 and Nit-3 are fixed. Nit-2 is kept
on purpose and I accept the reason. I add one new Nit (Nit-4), which doesn't block landing.

| Finding | Status | What I checked |
|---|---|---|
| High-1 | **closed** | `contextlib.closing` plus `commit()` at `tests/test_convert_helab.py:172` and `:1330`. The `[newer]` case passes on both Windows jobs of run 40866574094. The new `test_an_index_that_cant_be_set_aside_fails_the_conversion_to_be_tried_again` covers a set-aside refused while another process has the file open. The handoff explains why that never retries in a fast loop: Live waits for Retry, `--watch` waits for its `--interval`, and IOService never retries a helper's `error`. |
| Low-1 | **closed** | `clear_converted` opens the index for writing only when `index_schema(root) == SCHEMA`. `_index_files` puts a newer HeLab's live index and its `index-newer-…` files in a separate list, so Clear doesn't count them as ours and never removes them. Settings › Cache reports them as `newer` (typed in `events.ConvertedUsageField`; the tooltip has a line for them). `test_a_clear_leaves_a_newer_helabs_index_alone` checks the bytes are unchanged and the `newer` file stays, while a damaged set-aside file goes. |
| Low-2 | **closed** | `_OWN_FILE` now includes `\.folder\.json\.[0-9a-f]{16}\.partial`. `own_partial()` is back to its pattern from before this branch (the TXY and JSON temporaries, and `folder.json`'s). Tests check the folder gets removed, that an uppercase-hex look-alike stays, and the full look-alike list for housekeeping. AGENTS.md's housekeeping line stays as it was. |
| Low-3 | **closed** | `find` calls `provenance.read_shots(...)`. The handoff proposes adding it to io-and-browsing's list of patched names. |
| Low-4 | **closed** | `provenance.py`'s docstring and the doc proposals now say the cache folder is never on a share (`cache_location` refuses one), and that a load moves its folder's `last_used` on. |
| Nit-1 | **closed** | Every file is measured by its `stat`. `TxyIndex.held` is gone; nothing else used it. |
| Nit-2 | **kept, accepted** | Orphan rows stay. Pruning would have to tell them apart from beside rows, which are the only provenance of their TXY. CoCo agreed. |
| Nit-3 | **closed** | `read_shots` closes its index once on each path, before any set-aside (Windows can't rename an open file). |
| Nit-4 (new) | open, Nit | `CacheTab` keeps Clear enabled whenever `bytes` > 0, and `bytes` always includes our live `index.sqlite`, which Clear keeps. So after a Clear the row shows "0 files · 12 kB" with Clear still enabled, and pressing it removes nothing. This dates from round 0. A damaged live index is likewise left by Clear now (for the next conversion to set aside) and still counted. Possible fix: enable on `files` alone, or count the index separately. |

### Checks (floor venv, macOS)

- Touched and new tests: `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`
  on `test_convert_helab`, `test_converter_tab`, `test_txy_sources`, `test_helper_events`,
  `test_cache_switch` and `test_headless_imports`: **150 passed, 0 reruns**.
- `mypy helab/ --strict` (191 files), `mypy tests --strict` (159), and `mypy helab/ --strict --platform
  win32` (191): no issues. `pyright helab tests` and `pyright --pythonplatform Windows helab tests`:
  0 errors.

### CI run 40866574094 (head `9691873`)

**Attempt 1: failure.** I read every job's log. These jobs passed: macOS Converter backends
(123422851803: 676 passed), Ubuntu Converter backends (123422851804: 676 passed), Windows Converter
backends (123422851980: 675 passed), macOS Tests (2/2) (123422851805: 4115 passed), Ubuntu Tests
(1/2) (123422851876: 4079 passed), Ubuntu Tests (2/2) (123422851827: 4116 passed), Windows Tests
(1/2) (123422851982: 4069 passed), Windows Tests (2/2) (123422852009: 4099 passed), and the three
Builds. **No RERUN in any job.**

**macOS Tests (1/2) (123422851726): failure.** 3108 passed, then xdist stopped with
`INTERNALERROR> AssertionError: ('tests/test_root_discovery.py::test_volume_check_alone_refreshes_hints_without_visiting_markers', <WorkerController gw2>)`.

**Attempt 2: success.** "Re-run failed jobs" ran only macOS Tests (1/2) (123440148708: 4082 passed,
322 skipped, no RERUN). The other jobs in attempt 2 have new IDs but carry attempt 1's logs (the
same counts and times).

**Ledger's diagnosis: I agree.** The worker's log shows the chain. `test_root_discovery.py:347`
patches `os.lstat` for the whole process (`lambda *_: pytest.fail("visited a source folder")`). While
that patch was in place, pytest's unraisable hook ran `tracemalloc_message`. Coverage's tracer
(`_should_trace` → `canonical_filename` → `abs_file` → `os.path.realpath`) then called the patched
`lstat`. That raised `Failed` inside `sys.unraisablehook` and the xdist worker crashed. A crashed
worker is an INTERNALERROR, which `--reruns` never retries. This branch doesn't touch
`test_root_discovery.py`, data roots or markers.

It still needs a known-issues entry: neither the handoff nor `roadmaps/known-issues.md` names it.
A fix would patch `os.lstat` only for the paths under test, or patch the name in `data_roots`
rather than in `os`. Together with the Windows `test_writing_held_data_out_counts_as_progress`
RERUN from run 40863356565 (already in the handoff for CoCo to file), that makes two known-issues
entries for the landing.

## Round 3 review (head `5dc161f`, `git diff 9691873..5dc161f`)

**Result: no blocker.** Nit-4 is closed. WAL, `_patient`, the move and the 200 ms wait hold up under
the checks below. I add two Low findings (both about where the docs promise more than the code does)
and three Nits. None of them stops the landing if CoCo accepts them as follow-ups.

| Finding | Status | What I checked |
|---|---|---|
| Nit-4 | **closed** | `CacheTab.py:668` enables Clear only when `clearable` > 0. `converted_usage` computes `clearable`/`clearable_bytes` with the same `_cleared` rule `clear_converted` uses, plus a `folder.json` left alone in its folder (as Clear removes it, now with its bytes counted). `test_the_cache_tab_shows_and_clears_converted_txy` shows "0 files · <index>" with Clear disabled after a Clear. |
| Low-5 (new) | open, Low | See below: the temp folder is user-set, so it isn't always local. |
| Low-6 (new) | open, Low | See below: the index never shrinks, and the tooltip says "a few kB". |
| Nit-5 (new) | open, Nit | An index made by an earlier head of this branch stays in DELETE mode. |
| Nit-6 (new) | open, Nit | The confirm text can read "Removes 0 TXY files … with their records (40 kB)". |
| Nit-7 (new) | open, Nit | `_patient` can wait up to about 2 × `BUSY_SECONDS`, not "up to 10 s". |

### Low-5: "the temp folder is the OS's" isn't so; WAL (and the URI) need a local, plain path

- **Where:** `helab/convert/provenance.py:35` ("and the temp folder is the OS's"), and the handoff's
  lines 70–71 ("A UNC *temp* override, a developer setting").
- **Why:** Settings has an editable temp folder with Browse… (`SettingsDialog.py:127`, `:143`,
  `:329`). Nothing checks it with `cache_location_problem`; only Help › Record I/O trace warns
  (`io_ops/trace_check.py:18`). So a user can put it on a network drive, a UNC path or a synced
  folder. There:
  - **WAL** needs shared memory (`-shm`) that SQLite doesn't support over a network filesystem, and
    a sync client can copy `index.sqlite` and `-wal` separately. The likely outcome is a "damaged"
    index (set aside, shots converted again) or lock errors (`IndexUnavailable`, conversions to temp
    fail). Don't-cache folders always convert to temp (Q27.4).
  - **A UNC path** still fails every open, as I noted in round 0 (Low-4): `pathlib.Path.as_uri()`
    gives `file://server/share/…` and SQLite refuses the authority. With WAL nothing changes here,
    but the handoff now calls it a developer setting, and it isn't.
- **Fix (any one):** refuse a network or synced temp folder in Settings the way the cache folder is
  refused (Tony's call on wording, so a `Q~` for DECISIONS); or, for a base where
  `cache_location_problem(base)` is non-empty, keep the index in DELETE mode and build the URI as
  `file:` plus the quoted path, which keeps a UNC host inside the path. At least correct the
  docstring and the doc proposal.

### Low-6: the index never shrinks, and the row says "a few kB"

- **Where:** `CacheTab.py:57` ("which keeps the index (a few kB, counted here)"), and the handoff's
  line 369.
- **Why:** each row is about 400 bytes. I measured 5000 rows at 1,986,560 bytes. The index has
  `auto_vacuum` 0, and nothing runs `VACUUM`. After `clear_converted` removed all 5000 TXY and their
  rows, the file was still 1,986,560 bytes. The row then reads "0 files · 2.0 MB" with Clear
  disabled. The user has no way to get that space back short of deleting the file by hand. A lab
  that converts tens of thousands of shots ends up with tens of MB.
- **Fix:** run `VACUUM` on the index at the end of a Clear that removed rows. Clear is rare and
  asked for. In WAL, `VACUUM` takes the write lock, and `_patient` covers a busy answer. Then the
  tooltip can say "counted here" without "a few kB". At least drop "a few kB".

### Nits

- **Nit-5:** `provenance.py:351` sets WAL only when it creates the file (`user_version` 0). An index
  made by an earlier head of this branch (1e7329c–c546394, on dev machines or the floor) stays in
  DELETE mode for good. My probe confirmed it. Nothing shipped with DELETE, so accepting this is
  fine. Otherwise, switch it on a writable open when `PRAGMA journal_mode` says `delete`, ignoring
  busy.
- **Nit-6:** `CacheTab.py:474`: with only a damaged set-aside index or old records to clear, Clear is
  now enabled and the confirm reads "Removes 0 TXY files HeLab converted, with their records (40
  kB)". Possible fix: name the files when `files` is 0 ("Removes HeLab's leftover records (40 kB)").
- **Nit-7:** `provenance.py:181–196`: the deadline is checked only between attempts. An attempt that
  starts just before the deadline can wait SQLite's own 10 s busy timeout, so the total approaches
  20 s. CI's "after 13.41 s" (run 40879735789) shows the overshoot. That is still inside the 60 s
  no-progress timeout. Only the docstring and the handoff ("up to the same 10 s") need a change.

### What I checked and found sound

- **WAL with two writers and readers:** `BEGIN IMMEDIATE` per write, with `_patient` retrying
  `SQLITE_BUSY`/`SQLITE_LOCKED` (extended codes by `& 0xFF`). `_transaction` and `_prepare` roll
  themselves back first, so each retry starts clean. A damaged file raises `DatabaseError`, which
  `_patient` doesn't retry, so it still goes to set-aside. Readers open with `mode=rw`, so the last
  one to close checkpoints and removes `-wal`/`-shm`. A `mode=ro` reader would leave them, but no
  HeLab code opens one. Under a write transaction held by another connection, `read_shots`,
  `index_schema` and `converted_usage` each answered in under 1 ms (probe).
- **Checkpoints:** SQLite's automatic checkpoint (1000 pages) on commit. No connection holds a read
  transaction between operations (autocommit, `isolation_level=None`), so nothing pins the `-wal`.
  The last close removes it: two-writer test, `listdir == [index.sqlite]`, on all three OSes.
- **A killed writer:** probe with `wal_autocheckpoint = 0`, one committed update and one open
  `BEGIN IMMEDIATE`, then `os._exit`. `-wal`/`-shm` were left. The next reader saw the committed row
  and not the uncommitted one. The next writer wrote in 1 ms, and its close left only
  `index.sqlite`.
- **The move:** `_copy_tree` copies `-wal` and skips `-shm` (`SKIP_SUFFIXES`). `checkpoint` covers
  only the store, which is fine because no index writer runs during a move: helpers are stopped and
  `helab convert` registers in `cache_locks`. `test_a_cache_move_carries_rows_still_in_the_wal`
  proves the rows replay at the new place, and that `-wal`/`-shm` are measured with the index but
  are neither TXY nor `clearable`, and Clear leaves them.
- **Windows file handles:** a set-aside while another process has the index open fails at the first
  companion rename, since SQLite's win32 VFS doesn't share delete. `_COMPANIONS` puts `-journal`
  then `-wal` first, so nothing is half renamed, and it fails as `IndexUnavailable` (accepted in
  round 1). Clear never touches `-wal`/`-shm`. The move's test exits its writer before cleanup.
  Windows CI passes all of it.
- **The 200 ms wait (`helab_txy.py:217`):** `touch` is a single autocommit statement, not wrapped in
  `_patient`. So `PRAGMA busy_timeout = 200` bounds it: 0.25 s in my probe under a held write. On a
  timeout, `sqlite3.OperationalError` is swallowed, `last_used` doesn't move, and the load returns
  its shots as usual. Opening and reading in `find` don't wait on a writer in WAL. One gap: no test
  pins the 200 ms. The probe is in the review scratch, not the suite.
- **The GUI never opens the index:** unchanged. `CacheTab` reads only the inventory.
- **`events.py`:** `ConvertedUsageField` has `clearable` and `clearable_bytes`, and
  `ConvertedSummaryField` sums them. `test_helper_events` passes.

### Checks (floor venv, macOS, head `5dc161f`)

- Touched tests: `test_convert_helab`, `test_converter_tab`, `test_txy_sources`,
  `test_helper_events`, `test_cache_switch`, `test_cache_move` and `test_headless_imports`, with
  `-n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`: **195 passed, 0 reruns**.
- Full suite, same flags: **8199 passed, 669 skipped, 0 reruns** (2 min 3 s).
- `mypy helab/ --strict` (191 files), `mypy tests --strict` (159), and `mypy helab/ --strict
  --platform win32` (191): no issues. `pyright helab tests` and `pyright --pythonplatform Windows
  helab tests`: 0 errors.

### CI run 40883472651 (head `5dc161f`, attempt 1): success

I read every job's log:

| Job | ID | Result |
|---|---|---|
| macOS Converter backends | 123480992365 | 678 passed |
| Ubuntu Converter backends | 123480992493 | 678 passed |
| Windows Converter backends | 123480992308 | 677 passed |
| macOS Tests (1/2) | 123480992457 | 4082 passed |
| macOS Tests (2/2) | 123480992782 | 4117 passed |
| Ubuntu Tests (1/2) | 123480992399 | 4079 passed |
| Ubuntu Tests (2/2) | 123480992535 | 4117 passed |
| Windows Tests (2/2) | 123480992168 | 4101 passed |
| Windows Tests (1/2) | 123480992297 | 4069 passed, **1 rerun** |
| Three Builds, Detect branch | — | success |

The compat matrix (3.11, 3.12, 3.14) was skipped because this is a push, not a PR.

- **The rerun, quoted from "rerun reasons":**
  `RERUN tests/test_plot_backends.py::test_2d_plots_draw_with_every_library[values1-Matplotlib-CountsPerShot]`,
  "worker 'gw1' crashed while running …", with no traceback.
- **Is it known?** `roadmaps/known-issues.md:98` has the same test's worker crash on Windows, but
  for the `[values0-Plotly-CountsPerShot]` case (run 40803552596). This one is the Matplotlib case,
  so the entry should be widened to name it and this run. It isn't this branch's: the branch
  doesn't touch plots.
- **The two-writer test passed on every OS with no rerun.** On Windows Tests (2/2) it took about
  10 s from start to pass (13:41:40 → 13:41:50, including two interpreter starts), against about
  2 s on Ubuntu. That is worth watching, but it isn't a failure.

## Round 4 review (head `1b71c37`, `git diff 5dc161f..1b71c37`)

**Result: no blocker.** Low-5, Low-6, Nit-6 and Nit-7 are closed, and the 200 ms wait is pinned by a
test. Nit-5 is accepted. I add one new Low (Low-7), small and in the spirit of Low-5, and one Nit
about the timing test (Nit-8).

| Finding | Status | What I checked |
|---|---|---|
| Low-5 | **closed** (except Low-7) | `convert.journal_for(base)` returns DELETE when `cache_location.cache_location_problem` objects, otherwise WAL. `convert_folder` (`convert.py:561`) passes it on. `_uri` percent-quotes the whole path, so a UNC `\\server\share` has no URI authority. The test runs both modes and checks `?`, `#`, `%` and spaces in a name (no `?` on Windows). The docstring is corrected, and Q~5 asks Tony about refusing such a temp folder. |
| Low-6 | **closed** | `clear_converted` ends with `TxyIndex.vacuum()` (through `_patient`, its `sqlite3.Error` ignored), but only after a `forget_removed` that succeeded. In WAL, `VACUUM` leaves a full-size `-wal` until the last connection closes, which is normal and gone after the Clear. The tooltip drops "a few kB". The test shows 400 rows and a file under a quarter of its size afterwards. |
| Nit-5 | **accepted** | Nothing with DELETE reached Ground or a release. |
| Nit-6 | **closed** | With `files` 0, the question names old records and damaged indexes. Tested. |
| Nit-7 | **closed** | Each attempt's `busy_timeout` is what is left of `BUSY_SECONDS`. The last sleep is capped by it, and `finally` restores the 10 s timeout. The bound is now BUSY_SECONDS plus one 1 ms attempt. |
| 200 ms touch | **pinned** | `test_a_load_whose_last_used_mark_times_out_still_returns_its_shots` holds `BEGIN IMMEDIATE` while a load runs: four shots returned, `last_used` unchanged, under 5 s. It fails at about 11 s without the limit, per the handoff. |
| Low-7 (new) | open, Low | See below. |
| Nit-8 (new) | open, Nit | The timing test (see (a) below). |

### Low-7: a damaged index set aside during a write comes back in WAL, even on a non-local temp folder

- **Where:** `provenance.py:293`, `TxyIndex._write`:
  `self.conn = open_index(self.root, write=True).conn`. No `journal` is passed, so the default is
  WAL.
- **Why:** `open_index`'s own set-aside retry keeps the caller's `journal`, but `_write` doesn't. On
  a network or synced temp folder, where an index is most likely to be found damaged, the
  replacement is made in WAL, which is what Low-5 set out to avoid. `clear_converted`
  (`helab_txy.py:471`) also opens with the default. That only matters if the index vanishes between
  `index_schema` and the open, which is a race, so it can be ignored.
- **Fix:** keep the journal on the `TxyIndex`, set by `open_index`, and pass it on in `_write`. Or
  make `open_index`'s default `journal_for(os.path.dirname(root))`. That needs a helper in
  `helab/convert/` (it is Qt-free; `cache_location` would have to be checked for `PURE`), or a
  caller-supplied default. Add a test: a write that finds the index damaged on a base that
  `cache_location_problem` objects to leaves a DELETE index.

### (a) The `_patient` timing test: robust now?

- **The CI evidence:**
  - At 0.3 + 0.2 s (87d0475, run 40888404379), the test failed after 5 reruns on macOS Tests (2/2)
    (job 123498366886): `assert (180.245601541 - 179.548123916) < (0.3 + 0.2)`.
  - At 1.0 + 0.6 s (463c44e, run 40890989136), it reran on macOS Tests (2/2) (123507559816),
    Windows Converter backends (123507559950) and macOS Converter backends (123507560022). The
    held-lock case took 1.68 s, 1.66 s, 1.68 s and 1.63 s:
    `assert (281.217096666 - 279.533168416) < (1.0 + 0.6)`.
  - The overshoot is steady at about 0.65 s on both OSes, not a rare spike: SQLite counts its
    busy-wait sleeps nominally.
- **Locally:** 15 runs while the full suite ran with `-n 8` took 2.09–2.16 s each, about 1.05 s per
  case.
- **At 1.0 + 2.0 s (1b71c37):** CI's worst is 1.68 s, so the margin is about 1.3 s, and run
  40894080358 had no rerun of it. **Robust enough to land.** But the wall-time check discriminates
  poorly: the regression it guards against waits the connection's 5 s default, only 2 s above the
  bound. What actually catches a regression is the behaviour check (`timeouts` shrinking and starting
  at ≤ 1000, the 10 s restored). The handoff says that check alone fails with the per-attempt
  timeout removed.
- **Nit-8 (suggested):**
  - Open `conn` with `timeout=60`, so a regression would wait 60 s, and bound the held-lock case at
    `BUSY_SECONDS + 5` s. That is loose enough for any runner and still catches the bug.
  - Drop the wall-time assert on the fake-lock case, or drive it with a fake clock (patch
    `provenance.time` with a `monotonic`/`sleep` pair that advances a counter). Then assert that the
    sleeps add up to ≤ `BUSY_SECONDS`, and that the last sleep is capped.
  - Also: the handoff's round 4 Nit-7 line still says "within `BUSY_SECONDS` plus 0.2 s". It is 2 s
    now.

### (b) The Windows rerun of `test_scan_reports_cached_children_without_loading_or_probing_them`: is it this branch?

**No, and the branch can't plausibly cause it.**

- **The failure:** "rerun reasons", Windows Tests (2/2), job 123518429856:
  `tests\test_folder_cache.py:1155: assert scanned == [str(root)]`. The diff was
  `'C:\\Users\\RUNNER~1\\AppData\\Local\\Temp\\helab_io_1p59fsr4'` at index 0, in front of the test's
  `…\test_scan_reports_cached_child0\root`.
- **Why it happens:** the test patches `os.scandir` for the whole process
  (`monkeypatch.setattr("os.scandir", record_scandir)`) and records every call. A `helab_io_` folder
  is `IOService._run`'s private folder for a non-load request (`io_service.py:800`).
  `IOService.release` removes it with `shutil.rmtree` on a daemon thread, "HeLab-artifact-cleanup"
  (`io_service.py:963`), and `rmtree` lists through `os.scandir`. A request from an earlier test on
  worker gw0 was still being cleaned up when this test's patch went in.
- **This exact trap is in known-issues already.** The `test_folder_summary.py::test_scan_metadata_survives_restart_without_reading_txy_contents`
  entry (`roadmaps/known-issues.md:212–214`) says "its process-wide `os.scandir` patch caught
  `IOService.release`'s `shutil.rmtree` on a daemon thread; the patches now act only on the test's
  own thread". `test_folder_cache.py` has the same pattern unfixed.
- **The branch:** it changes what an admin helper computes (the converted-TXY inventory, the `temps`
  parameter). It adds no threads, doesn't touch `release` or the `helab_io_` folders, and doesn't
  touch `test_folder_cache.py`. The gw0 tests just before were `test_constant_layers` and
  `test_constants`, and none of the branch's tests. Any IOService request from any earlier test
  leaves the same thread.
- **Fix (for the known-issues entry):** record only calls from the test's own thread
  (`threading.get_ident()` check), as `test_folder_summary` now does, or only paths under
  `tmp_path`.

### Checks (floor venv, macOS, head `1b71c37`)

- Touched tests: `test_convert_helab`, `test_converter_tab`, `test_txy_sources`,
  `test_helper_events`, `test_cache_switch`, `test_cache_move`, `test_cache_mover`,
  `test_headless_imports` and `test_folder_cache`, with
  `-n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`: **261 passed, 0 reruns**.
- Full suite (`-n 8`, same rerun flags): **8205 passed, 669 skipped, 0 reruns** (1 min 21 s).
- `mypy helab/ --strict` (191), `mypy tests --strict` (159), and `mypy helab/ --strict --platform
  win32` (191): no issues. `pyright helab tests` and `pyright --pythonplatform Windows helab tests`:
  0 errors.

### CI run 40894080358 (head `1b71c37`, attempt 1): success

I read every job's log:

| Job | ID | Result |
|---|---|---|
| macOS Converter backends | 123518429781 | 681 passed |
| Ubuntu Converter backends | 123518429771 | 681 passed |
| Windows Converter backends | 123518429768 | 680 passed |
| macOS Tests (1/2) | 123518429785 | 4086 passed |
| macOS Tests (2/2) | 123518429895 | 4119 passed |
| Ubuntu Tests (1/2) | 123518429866 | 4084 passed |
| Ubuntu Tests (2/2) | 123518429867 | 4120 passed |
| Windows Tests (1/2) | 123518429983 | 4073 passed |
| Windows Tests (2/2) | 123518429856 | 4103 passed, **1 rerun** (`test_folder_cache`, (b) above) |
| Three Builds, Detect branch | — | success |

The `_patient` timing test passed with no rerun in every job.

## Round 5 check (head `11389a9`, `git diff 1b71c37..11389a9`, Low-7 and Nit-8 only)

**Result: 0 open findings.** Low-7 and Nit-8 are closed. From my side, the floor can land.

| Finding | Status | What I checked |
|---|---|---|
| Low-7 | **closed** | `TxyIndex` keeps the `journal` it was opened with: `open_index` passes it on both its reader and writer paths. `_write`'s replacement after a set-aside reopens with `journal=self.journal` (`provenance.py:294`). `clear_converted` now opens with `journal_for(dirname(root))`, which covers the race I set aside. The new `test_a_damaged_index_replaced_mid_write_keeps_its_bases_journal` damages a DELETE index under its open connection: pages after the first are overwritten, and the change counter is bumped so the cached pages are dropped. The next `record` sets the damaged index aside and writes the row to a DELETE replacement. I checked that the test catches the old behaviour with a probe: forcing `journal = WAL` on the same `TxyIndex` gives a WAL replacement, and a DELETE one with the fix. |
| Nit-8 | **closed** | The retry part now runs on a fake clock (`provenance.time` patched; time passes only by sleeps). It asserts the back-off sequence 5, 10, 20, 40, 80, 100 ms, the capped last sleep, sleeps adding up to exactly `BUSY_SECONDS`, shrinking per-attempt timeouts starting at 1000 ms (one more attempt than sleeps), and the timeout restored. The real-lock case uses a connection with `timeout=60`, so a regression would wait 60 s, against a bound of `BUSY_SECONDS + 5` s. That is loose enough for loaded runners and still catches the bug. The class-level `sleeps` list is new for each test call (the class is defined inside the test), so reruns don't share it. |

### Checks (floor venv, macOS, head `11389a9`)

- `test_convert_helab`, `test_converter_tab`, `test_txy_sources`, `test_cache_switch`,
  `test_helper_events` and `test_headless_imports`, with `-n 4 --reruns 5 --reruns-delay 1
  --basetemp=.ai/temp/pytest-review`: **159 passed, 0 reruns**. The two changed tests passed 5 times
  out of 5 in a loop, each run about 1.35 s.
- `mypy helab/ --strict` (191), `mypy tests --strict` (159), and `mypy helab/ --strict --platform
  win32` (191): no issues. `pyright helab tests` and `pyright --pythonplatform Windows helab tests`:
  0 errors.

### CI run 40898587803 (head `11389a9`, attempt 1): success, no RERUN

I read every job's log:

| Job | ID | Result |
|---|---|---|
| Windows Converter backends | 123534527562 | 681 passed |
| macOS Converter backends | 123534527796 | 682 passed |
| Ubuntu Converter backends | 123534527985 | 682 passed |
| Windows Tests (1/2) | 123534527631 | 4074 passed |
| Windows Tests (2/2) | 123534528047 | 4103 passed |
| macOS Tests (1/2) | 123534527835 | 4087 passed |
| macOS Tests (2/2) | 123534527652 | 4119 passed |
| Ubuntu Tests (1/2) | 123534527941 | 4085 passed |
| Ubuntu Tests (2/2) | 123534527676 | 4119 passed |
| Three Builds, Detect branch | — | success |

**No RERUN in any job.** Both changed tests passed on all three OSes (Tests (1/2) on each). The
compat matrix was skipped because this is a push.
