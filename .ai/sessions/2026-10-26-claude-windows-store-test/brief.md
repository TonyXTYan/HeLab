# Windows store test (brief, CoCo, 2026-10-26)

Floor "Windows Store Test", branch `agent/windows-store-test`, base `848b667` (dev/v0.0.6 = origin).
Coordinator: CoCo. Tony approved this floor (Chat, 2026-10-26: "proceed").

## Objective

Make dev's Windows CI green again. One test fails there every time:

`tests/test_result_cache_quit.py::test_an_old_stores_answer_never_says_saved_in_the_recreated_one`

- **Where:** Windows CI only, run 39906031010 at `5617381` (the merge of Quick Fixes and Result
  Cache), all 6 attempts. macOS and Ubuntu pass with no RERUN.
- **What fails:** line 150, `shutil.rmtree(store_options()["directory"])`, which "recreates" the
  store, raised `PermissionError: [WinError 32] … being used by another process:
  …\caches67N\store-v3\records.sqlite`. Some process still had the store open. The
  `AnalysisRunner … has no attribute 'core'/'results'` tracebacks after it are only that failed
  test's teardown, since its window was never closed.
- **Full Windows job log:** `.ai/temp/win-fail.log` on this floor (the failure is near line 16850,
  the rerun reasons near 17223).
- **History:** the same test passed on Windows in the Result Cache branch's own CI (run
  39899355683 at `8794d82`). The Quick Fixes commits then merged in (`66b771a`, `e326fdf`, `6dcf8f2`,
  `6597740`, `73ec41b`) changed `tests/conftest.py`, `pytest.ini` (`faulthandler_timeout`) and
  `helab/utils/io_service.py` (`_run`: an `OSError` writing a helper's request now means it exited).
  Find out whether one of them changed the timing, or whether the race was there all along and now
  always loses.

## What to find

1. **Which process holds `records.sqlite` at line 150.** Candidates:
   - the lookup's own helper, which has delivered `result_found` but not yet exited (the test
     waits only for `held[0][0] not in cache.service.pending`);
   - another local-lane helper (the first plot's `result_save`, an inventory, the sweep, a presets
     read);
   - a connection in the test process itself (the `ResourceWarning: unclosed database` lines in
     the log come from other tests, but check).
2. **The fix.** Most likely test-only: before deleting the store, wait until no helper that opens
   it is running. For example, wait on the IOService's running helpers with their exits confirmed,
   or use `IOService.hold_cache` as a cache move does. Prefer an existing seam over a new one.
   - If the app itself would fail in the same case (a store recreated while a helper has it open),
     say so but don't change the app. The R2 rule already treats that as a store change. Ask
     before changing any app code.
   - Check the other tests that delete or replace a store while HeLab runs, e.g. grep `rmtree` and
     `store_options()["directory"]` in `tests/test_store_identity.py`, `test_result_cache*.py` and
     `test_presets*.py`. Fix any that share the pattern.

You have no Windows machine. On macOS you can reproduce "an open file can't be deleted" by
checking, before the rmtree, that no helper process is alive (e.g. assert the service has no
running or stopping helpers) and seeing that assertion fail. Windows CI is the real check.

## Scope

- **Owned paths:** the failing test, its helpers, and other tests with the same pattern.
- **Ask CoCo before:** touching `helab/`, `tests/conftest.py` beyond a small fixture, or more than
  a few files.

## Checks and handoff

- Commit the fix: a subject, then a body with the cause, the fix and the checks.
- Write `notes.md` in this folder with the cause, evidence, fix and checks, and a proposed
  known-issues line. The open item is in `roadmaps/known-issues.md` → Tests and CI; propose
  moving it to Fixed.
- Before reporting, run:
  - the full suite (`pytest -n 12 --reruns 5 --reruns-delay 1`);
  - the failing module 10 times;
  - `mypy helab/ --strict`, `mypy tests --strict` and `pyright helab tests`.
  Report each RERUN with its reason.
- **Push the branch once**, when done, to check it on Windows CI. Read the Windows job's log with
  `gh api repos/TonyXTYan/HeLab/actions/jobs/<id>/logs`; `gh run view --log` can return nothing.
- Keep `maestri floor status` current. Post `--state review` when CI is green.
- Report: `maestri ask "CoCo" "<cause, commit, files, checks with RERUNs, CI run and result, proposed known-issues line>"`.
