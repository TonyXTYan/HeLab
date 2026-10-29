# Brief: Quick Fixes 6, the slow typing tail in CI (`agent/quick-fixes-6`)

Coordinator: CoCo, 2026-10-29 (overnight build; Side approved: the v0.0.7 PR needs clean CI;
Q16.2, the time limits themselves, stays for Tony). One Quick Fixer, then a Reviewer.
Base `4132e36` (`dev/v0.0.7`).

## Job

CI's Windows test job on `dev/v0.0.7` 02cda86 (run 40790912863) was cancelled at its 30-min limit
(30:13) at 99%, while the six `tests/test_typing.py` tests (mypy strict and soft on helab and tests,
pyright; ~1-3 min each) ran last on one xdist worker. Ubuntu shows the same ~3-min tail (the packaging
floor saw it). Make the typing tests start first and spread across workers, so they overlap the rest
of the suite instead of forming a serial tail.

## Conditions (Side)

- **Test-only.** Order the typing tests first with a collection hook (e.g.
  `pytest_collection_modifyitems` in `tests/conftest.py`, or in `tests/test_typing.py`'s module if a
  hook there works with xdist); do **not** switch the whole run's `--dist` mode or change CI files;
  keep the rest of the distribution as it is. Check how xdist's default `load` scheduling hands out
  the first items (they go to workers in order, a few each), so the six really start on different
  workers early.
- **Show the effect**: `--durations` and the per-worker tail (when each worker finished) before and
  after, locally and on all three OSes in CI (compare against run 40790912863 and 40793460604).
- No CI time-limit change, no workflow change.

## Rules

As your role says: cause first, notes in `.ai/sessions/2026-10-29-claude-quick-fixes-6/notes.md`, the
full suite (inside and once outside the checkout basetemp), `mypy helab/ --strict`, `mypy tests
--strict`, `pyright helab tests`, `mypy --platform win32`, `pyright --pythonplatform Windows`; report
every RERUN. Push once when done; report the commit and the CI run with each OS's test-job time and
tail. The landing waits for CI green on 3 OSes by run ID.
