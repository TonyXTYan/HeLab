# CI matrix split

- Required Python 3.13 tests/builds run on macOS, Windows and Ubuntu for every
  branch push and PR to main. Python 3.11/3.12/3.14 compatibility checks run only
  on PRs to main and remain non-blocking.
- All four matrices disable fail-fast; removed whole-workflow cancellation.
  Shared workflow_call-only test/build files keep jobs in the caller's CI CD run.
- Release still needs get-version, test and build only. Version selection, release
  job, artifact names, provenance and older-tag recovery tests were preserved.
- JUnit artifacts upload after failed tests when a report exists.
- Verified 6 push / 24 PR test-build combinations, failure-policy inputs, unchanged
  release jobs, migrated steps and syntax of all 23 Bash blocks. Actionlint passed
  with only the pre-existing unsupported concurrency.queue key excluded.
- Focused versioning/release tests: 46 passed. git diff --check passed.
- No live GitHub run or push. Existing unrelated test changes untouched.

## Dependency graph follow-up

- Tony requested one branch/version detection job feeding all four matrices,
  with all four feeding tag/release. Tests and builds stay parallel.
- Added detection dependencies to both test matrices and both compatibility
  dependencies to release. The release condition explicitly permits skipped
  compatibility jobs while requiring successful detection and required tests/builds;
  workflow cancellation and should_release=false still prevent release.
- Verified graph edges, 4096 combinations of dependency results/release flag/
  cancellation in the condition, unchanged other job behavior and 23 Bash blocks.
  Actionlint passed with the same pre-existing queue-key exclusion; diff check passed.
- Follow-up validated locally before commit/push; live GitHub execution pending.

## Explicit compatibility skips

- Run 38258185459 succeeded with all six required jobs passing, but the summary
  showed unexpanded compatibility matrices as pending while their job states were
  completed/skipped. Tony approved trying explicit inner-job skips.
- Removed compatibility caller conditions and passed a PR-only `enabled` boolean
  to each reusable job (default true for required jobs). Pushes expand all entries,
  then skip 18 compatibility jobs before runners start; PRs enable all 24 jobs.
- Local event-count checks and all 4096 release-condition combinations passed.
  Actionlint passed with the existing queue-key exclusion; diff check passed.
- Summary icon rendering must be verified in the next GitHub run.

## Skipped-job labels

- Run 38260536960 confirmed both compatibility groups now render the skipped icon,
  with nine completed entries each and all 18 jobs skipped with no steps. Tony
  confirmed the browser display, then noted raw input expressions in child names.
- Made child names literal (Tests / Build) and moved explicit OS/Python labels to
  the expanded caller matrix names; updated required-failure summary labels.
- All 24 labels are distinct and identify OS/Python; other workflow behavior is
  unchanged. All 23 Bash blocks, actionlint (same queue exclusion) and diff check
  passed. Label rendering needs a new live run after commit/push.
