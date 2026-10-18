# macOS serial coverage follow-up — 2026-10-13

Tony reported that the next CI run passed Windows and Linux but failed macOS, and directed inspection of the connected Maestri terminal `PyTest`. That terminal showed a passing local run (`681 passed, 1 skipped, 2 xfailed, 11 warnings`), not the failing CI serial coverage result.

Live [run 38254922599](https://github.com/TonyXTYan/HeLab/actions/runs/38254922599), commit `3920f3e6f41491ab1e8667c1843a7f68bc4c0d06`, completed with conclusion `failure`:

- Required Windows and Ubuntu test jobs succeeded.
- All three required build jobs succeeded, including macOS.
- The macOS parallel test step succeeded: `681 passed, 1 skipped, 2 xfailed, 23 warnings, 1 rerun`.
- The macOS-only serial coverage step failed: `1 failed, 674 passed, 1 skipped, 2 xfailed, 20 warnings`.
- Failure: `tests/test_cache_contention.py::test_held_write_lock_still_lets_a_manual_scan_run`, assertion at line 100 that saved history remains blocked. CI observed `blocked=False`.

The test's fixture held SQLite's write lock for just 0.5 seconds. `scan()` can first warn that its start metadata cannot be saved, then complete the source scan after that lock expires and successfully save its outcome. Clearing the old failure flag in that case is correct. A warning at the beginning does not imply the final outcome save must also fail. This test therefore relied on the scan finishing within the lock's fixed lifetime.

A local serial coverage run of the original contention module passed (`15 passed in 2.88s`), showing the CI failure is timing-dependent. A scratch probe delayed `_scan` by 0.6 seconds and reproduced the relevant combination deterministically: initial lock warning, successful scan, saved successful outcome, `blocked=False`.

Fix: change only the manual-scan contention test. An independent SQLite connection begins a write transaction and remains open through the entire scan, then closes before reading persisted history. The lock now persists through both attempted history writes regardless of scan duration. No application or workflow implementation changes are required.

Verification on macOS arm64, Python 3.13.15:

- Contention module under serial coverage after the fix: `15 passed in 2.26s`.
- Scratch probes: `2 passed in 1.49s`, including executing the fixed test with a 0.6-second source-scan delay.
- Exact full macOS coverage command: `venv/bin/pytest --cov=helab --cov-report=xml --cov-report=term --ignore=tests/test_typing.py --cache-clear --timeout=120 --timeout-method=thread` — `675 passed, 1 skipped, 2 xfailed, 20 warnings in 40.43s`; reported coverage 86%.
- Strict mypy: no issues in 58 application files and 40 test files.
- Pyright: zero errors/warnings.
- `git diff --check`: clean.

The six typing tests are intentionally excluded from the serial coverage command and were validated separately with the strict checking commands. Tony subsequently authorized committing and pushing this fix and note. GitHub validation of the fix remains pending.
