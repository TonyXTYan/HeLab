# Windows store test (Tallow, 2026-10-26)

Brief: [brief.md](brief.md). Branch `agent/windows-store-test`, base `848b667`.

## Job: WinError 32 in `test_an_old_stores_answer_never_says_saved_in_the_recreated_one`

### Cause

The test deleted `store-v3` while the second plot's `result_find` helper still had
`records.sqlite` open. That helper sends `result_found` from inside its store
(`helab/io_ops/results.py`, `result_find`: `send(event)` comes before `store.close()` in the
`finally`). The test held that event and then waited for
`held[0][0] not in cache.service.pending`. That is true as soon as the helper starts, since
`IOService._start` moves a request from `pending` to `active`. So the wait reduced to "the
event arrived", while the helper might still be running with the store open. macOS and Linux
let `rmtree` unlink an open file. Windows refuses (WinError 32), and Windows helpers take
longer to close and exit after sending, so there the test nearly always lost the race.

The race was there from the start (`78b8bad`). It isn't a timing change from Quick Fixes:
- Their `io_service._run` change is write, then flush, then close. Before, it was write, then
  close, which flushes anyway. Either way the request is sent before the helper reads it.
- `pytest.ini`'s `faulthandler_timeout`, `no_quitting_cache` and `where_qt_raised` don't touch
  a running test's helpers.
- The one Windows pass (run 39899355683, job 120237117507, gw3 at 42 %, no RERUN) was luck: that
  helper happened to exit before the test's next poll.

The holder isn't a connection in the test process: the test opens none before line 150.
`results_saved()` runs only afterwards. Nor is it the first plot's `result_save` or an
inventory: in the macOS repro the only live cache helper was `result_find`.

### Evidence

- The Windows log (`.ai/temp/win-fail.log`): all 6 attempts failed at line 150 with
  `PermissionError: [WinError 32] … caches67N\store-v3\records.sqlite` (rerun reasons near line 17223).
- macOS repro: I printed the cache helpers in `active`/`retired` just before the `rmtree`. In
  2 of 5 runs it showed `[('result_find', None, None, False)] True`: `poll()` None, so the
  process was alive, its exit not confirmed, and `cache_busy()` was True.

### Fix (test only)

Before deleting, the test now waits for `bool(held) and not cache.service.cache_busy()`.
`IOService.cache_busy()` is the existing seam that `CacheMover` checks before a move. It is True
while any helper that opens the disk cache is running or its exit isn't yet confirmed by the
reaper. The `rmtree` follows in the same GUI-thread call, so no new helper can start in
between. App code is unchanged. The app treats a store recreated under a running helper as a
store change (R2's store-identity rule). Deleting the store by hand while HeLab runs isn't
something the app does.

Other tests that delete a store while HeLab runs don't share the pattern:
- `test_store_identity.py:319` (`test_a_store_in_the_folder_whatever_its_age_ends_quit`) and
  `test_presets_store.py:524` (`test_a_store_recreated_at_the_same_folder_is_read_as_itself`)
  wait for `not cache._preset_jobs`. That is cleared on `done`, which `io_helper` sends only
  after the operation returns, and `cache_admin` has closed its store (`with`) by then.
- `test_store_identity.py:359` runs its helpers to completion (`find`, `save_through_helper`)
  before deleting.

### Checks

- With a temporary assertion that no cache helper process was alive at the `rmtree`: 10 of 10
  passed after the fix. Before the fix it failed 2 of 5.
- `tests/test_result_cache_quit.py` ×10: all passed (3 tests each).
- Full suite `pytest -n 12 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`: 4307
  passed, 2 skipped, 2 xfailed, **no RERUN**.
- `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests`: clean.
- Windows CI: see the report to CoCo (run ID and result).

### Proposed `roadmaps/known-issues.md` line (move to Fixed)

- [x] `test_result_cache_quit.py::test_an_old_stores_answer_never_says_saved_in_the_recreated_one`
  failed on Windows CI every attempt (WinError 32 deleting `store-v3`). The cause: the test
  deleted the store as soon as the lookup's `result_found` arrived, and that event is sent with
  the store still open. Its wait (`not in pending`) held as soon as the helper started. The
  test now waits for `IOService.cache_busy()` to clear (every cache helper's exit confirmed)
  first. Test only; the race was there since `78b8bad`. (`<commit>`, Tallow, 2026-10-26)

## Job 2: `test_row_tooltip[cache outdated]` and `[checked, outdated]` on Windows CI

Found on this branch's first push (run 40260907064). The store test above passed on its first
attempt there (job 121372926050). But these two cases failed all 6 attempts. Their reruns
(5 × 2, with a 5 s delay) took the Windows test step past its `timeout-minutes: 20`, and the
step was cancelled at 99 % before the summary printed (so no rerun reasons in the log).

### Cause

The expectations in `CASES` are built at import, and `stamp(AFTER)` includes the age:
`AFTER = NOW - 6600 s` reads "1h ago". The tooltip takes its ages when the test runs
(`_stamp`: `relative_age(time.time() - timestamp)`, whole hours above an hour). Once
`test_row_tooltip` runs 600 s or more after the module was collected, `AFTER` reads "2h ago" and
the two cases with `stamp(AFTER)` in a module-level expectation fail. Here the session started
at 02:50:38 and the module ran at 03:04, 14 minutes in. The earlier Windows runs reached it
within 10 minutes. On macOS the whole suite takes about 1 minute. The other `stamp()` values
(`SCANNED`, `BEFORE`: 2h and 2h 10m) would break the same way after 50 minutes.

### Fix (test only)

`test_row_tooltip` freezes `time.time` at `STAMPED`, the moment `CASES` finished stamping, so
the tooltip's ages are the ones the expectations were taken with. Exactly `NOW` would be unsafe,
since `NOW - (NOW - 7200)` can come out 1e-7 s short and floor to "1h". The other tests in the
module stamp inside the test and are unaffected.

### Checks

- Simulated a late run with the module imported on a clock 700 s back: the original fails exactly
  `[cache outdated]` and `[checked, outdated]`; the fixed one passes 38/38.
- `tests/test_row_tooltip.py` ×10: all passed. Full suite (-n 12 --reruns 5): 4307 passed,
  no RERUN. `mypy tests --strict`, `pyright tests`: clean (helab unchanged).

### Proposed `roadmaps/known-issues.md` line (Fixed)

- [x] `test_row_tooltip.py::test_row_tooltip[cache outdated]` / `[checked, outdated]` failed
  whenever the module ran 10 minutes or more after collection (Windows CI, run 40260907064; their
  reruns ran the step past 20 min). The cause: expectations stamped at import ("1h ago") against
  ages taken at run time ("2h ago"). The test now freezes `time.time` at the moment the
  expectations were stamped. (`<commit>`, Tallow, 2026-10-26)

## CI (run 40263152153 at `5a63fd5`): green

| OS (py3.13) | Tests | RERUN | Run Tests step |
|---|---|---|---|
| macOS | 4307 passed, 2 skipped, 2 xfailed | 0 | 3 min 30 s |
| Ubuntu | 4305 passed, 4 skipped, 2 xfailed | 0 | 4 min 42 s |
| Windows | 4287 passed, 18 skipped, 2 xfailed | 0 | 9 min 47 s (pytest 584 s; step limit 20 min) |

All three builds passed. On Windows the store test and `test_row_tooltip` passed on their first
attempts. The earlier cancelled run (40260907064) hit the step limit only because of the
tooltip's 10 failing reruns.
