# TXY ship: working notes (Worker, Claude Opus 5.5)

## How the groups are split (A17.2), and why

Options weighed: a CI matrix of `-k`/path lists (kept by hand, drifts as files are added); xdist
`--dist loadgroup` (groups tests within one run's workers, doesn't split across runners);
pytest-split (a new dependency plus a `.test_durations` file to keep current); a conftest option.

Chosen: `--test-group N/M` in `tests/conftest.py`. A test's group is `zlib.crc32(nodeid) % M + 1`:
deterministic on every OS (node IDs use `/` everywhere), every xdist worker (each collects and must
select the same tests) and every run, with nothing recorded. Per test rather than per module, so a
slow module's tests spread over both groups and the groups stay close in time as the suite grows
(module times vary a lot; ~200 modules hashed whole would leave a lumpy split). Module-scoped
fixtures may then run in both groups, as they already do on several xdist workers. The slow-first
tests (`SLOW_FIRST_MODULES`, `test_typing.py`'s six) are dealt out in turn (1, 2, 1, …) so each
group gets three, and the slow-first ordering then runs them first inside the group.

The check that every test is in exactly one group: `tests/test_test_groups.py` reads this run's
own full collection (stashed in `config.stash[ALL_TESTS]` before the group's selection, so no
second 30-s collection), and a nested pytest of a probe folder checks that `--test-group 1/2` and
`2/2` partition the run end to end (and that a bad value is a usage error before collecting).

CI: `ci-test.yml`'s `test` job gets `strategy.matrix.group: ['1/2', '2/2']` (fail-fast off);
GitHub names them "Tests (1/2)" and "Tests (2/2)". The caller's `needs.required-tests.result` is a
failure if any matrix job of any OS fails, so the release gate needs both groups unchanged. Each
macOS group uploads its coverage.xml; Codecov merges uploads of one commit (no `codecov.yml`, so
no `after_n_builds` to adjust). `main` has no branch protection or rulesets (checked with `gh api`),
so no required-check name changes.
