# Quick fixes, batch 3 (brief, CoCo, 2026-10-27)

Floor "Quick Fixes 3", branch `agent/quick-fixes-3`, base `450b6ec` (dev/v0.0.6 = origin, CI
40296966339 green). Coordinator: CoCo. Tony asked for this through his Assistant (2026-10-27).
Only this one fix: find the cause, not a longer wait.

## The job

`tests/test_store_identity.py::test_a_store_in_the_folder_whatever_its_age_ends_quit` failed all
6 attempts in 2 of 3 local full runs on Ground at `797cd02`. That's macOS, `-n 12 --reruns 5
--reruns-delay 1`, 2026-10-26.
- **Rerun reason:** `pytestqt.exceptions.TimeoutError: waitUntil timed out in 30000 milliseconds`
  at line 317.
- **The wait:** `cache.presets_read and not cache._preset_jobs and store_free(service)`.
- **Where it passed:** the floor runs and CI use `-n 4`, and passed with no RERUN. So did the
  third local run.
- **Full log** of a failed run: `.ai/temp/ground-run-n12-failed.txt` on this floor.
- **It's in** `roadmaps/known-issues.md` → Tests and CI.

**Suspect (CoCo's, unconfirmed):** `store_free()` in `tests/conftest.py`, from `5607182`, also
counts the app-wide IOService (`io_service._service`). That service lasts the worker's whole run,
and its timers and plots' preset reads keep starting helpers in later tests. With 12 workers, or a
busy worker, it may never be idle for this test's whole 30 s.
- Then the wait isn't about this test's store at all.
- Or a helper of the app-wide service is never confirmed as exited (`cache_busy()` stays true),
  which would be a real bug in `IOService`'s exit bookkeeping.
- Find out which of the three parts of the wait is false when it times out, and why.

## What to do

1. **Reproduce:**
   - the full suite at `-n 12 --reruns 0 -p no:randomly`, a few times;
   - or the failing worker's order: the log names the worker (gw10), so take the test IDs that
     worker ran before it, with `--dist loadgroup`, or replay its order from the log with
     `-p no:xdist`.
   - At the timeout, log which part is false and what `cache_busy()` sees: each request's
     operation, owner, lane, started, process alive or not, and `exited` set or not.
2. **Find the cause, then fix it** where it lives:
   - If the app-wide service is legitimately busy with another test's work, the test should only
     wait for what touches its own store, which is what Windows needs. Or isolate the app-wide
     service's work from this test, e.g. stop its timers or quiesce it for the test. Choose what
     keeps 5607182's Windows protection.
   - If a helper's exit is never confirmed, or a job never ends, that's an app bug: fix it in
     `helab/` with a test that fails before.
   - A longer timeout is not a fix.
3. **Check the other users of `store_free`** (grep) for the same problem.

## Scope

- **Owned paths:** `tests/` (`test_store_identity.py`, `conftest.py`'s `store_free` and the
  related fixtures), plus `helab/utils/io_service.py` or `folder_cache.py` only if the cause is
  there.
- **Ask CoCo before** changing behaviour users see, or more than a few files.

## Checks and handoff

- **Commit** with the cause, the fix and the checks.
- **Notes:** `notes.md` in this folder, with the cause, the evidence (what was false at the
  timeout), the fix and a proposed known-issues line (move to Fixed).
- **Before reporting:**
  - the full suite at `-n 12 --reruns 5 --reruns-delay 1` three times, and at `-n 4` once;
  - the module 10 times;
  - `mypy helab/ --strict`, `mypy tests --strict` and `pyright helab tests`.
  Report every RERUN with its reason.
- **Don't push yet:** a reviewer checks the fix first, and then you push once. Report to CoCo:
  `maestri ask "CoCo" "<cause, evidence, fix, commits, files, checks with RERUNs, proposed known-issues line>"`.
- Keep `maestri floor status` current.
