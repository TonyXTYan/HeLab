# Cache rebuild S7–S11 (Claude, reviewed by Codex)

Sessions S7–S11 of [the cache plan](../../../roadmaps/cache-storage-and-settings.md#sessions),
2026-10-10…11. Each session: implement, full validation (pytest -n 6 with the typing tests,
mypy --strict on helab and tests, pyright, `git diff --check`), mutation-check every new test
(mutate a scratch copy of `helab`, run `venv/bin/pytest` with `PYTHONPATH` on it, confirm the
intended test fails), then Codex review rounds in Maestri Terminal #1 until Codex said ready.

| Session | Commit | Codex rounds | Findings fixed | Final suite |
|---|---|---|---|---|
| S7 Cache tab, budgets, dialogs | `52201ca` | 7 | 5 + 2 + 1 + 2 + 2 + 2 + 1 | 530 passed |
| S8 Large-folder warning | `34f59c6` | 6 | 5 + 3 + 2 + 2 + 1 + 1 | 545 passed |
| S9 Cache folder move | `9ba2eae` | 4 | 8 + 7 + 2 + 2 | 599 passed |
| S10 Folder flags | `eafcf4b` | 4 | 5 + 4 + 3 + 2 (+1 P3 wording) | 615 passed |

Recurring kinds of finding, kept as rules in
[disk-cache-and-budgets](../../memory/results/disk-cache-and-budgets.md#lessons-from-the-reviews-keep-these-when-changing-the-code):
ordering by arrival time instead of the store's own counters; approvals or intents left in
tab-wide state; a setting taking effect before the store knew it; destructive steps not
proving ownership (a user's files in a move target, a newer move's record, a helper outliving
its HeLab).

Known flaky test (also observed failing on `9ba2eae` under `-n 6`, so it predates S10; no
earlier baseline was tested):
`tests/test_two_step_browse.py::test_refresh_cancels_only_automatic_subscriptions_and_suppresses_new_checks`.

Not done here: native UI and real-volume checks, listed in
[MANUAL_TODO](../../MANUAL_TODO.md#v005a-cache-rebuild-native-checks-added-2026-10-11).
