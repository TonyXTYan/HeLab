# Quick fixes, batch 2: handoff (Ferrule, 2026-10-26)

Branch `agent/quick-fixes-2` on base `0840acb`, pushed once (head `26994dd`). Details per job:
[notes.md](notes.md).

| Job | Commit | Change |
|---|---|---|
| 1 | `9d90156` | `cache_move.verify` also checks saved and pending results' files (`results/<uuid>.npz`). |
| 2 | `778641a` | `roots_verify` added to `io_helper.CACHE_ONLY`; tests keep it in step with `IOService.CACHE_OPERATIONS`. |
| 3 | `28fbc18` | A data root that goes or changes UUID drops its folders' saved-result counts from RAM (`FolderCache._root_results_gone`, nested roots kept). |
| 4 | `8de9ea6` | Audit only: `tests/test_load_sources.py` pins what `merged` / `updated` loads read and when they save; five label proposals for Tony in notes (job 4). No wording changed. |
| 5 | `cd2b0c3` | `pytest.ini` `addopts = --no-qt-log`: pytest-qt's per-test swap of Qt's message handler raced with a Qt message from another thread (the scatter test's Ubuntu teardown reruns). |
| notes | `26994dd` | Brief, notes, `repro/` scripts. |

## CI

Run 40268142898 (head `26994dd`): success.

| OS (py3.13) | Tests | RERUN |
|---|---|---|
| Ubuntu | 4337 passed, 4 skipped, 2 xfailed | none |
| macOS | 4339 passed, 2 skipped, 2 xfailed | none |
| Windows | 4319 passed, 18 skipped, 2 xfailed | none |

Builds passed on all three.

## Proposed doc changes (for the coordinator)

- **AGENTS.md › Testing:** "pytest-qt's Qt log capture is off (`--no-qt-log`, `pytest.ini`): its
  per-test swap of Qt's message handler raced with QtWebEngine logging from another thread
  (Ubuntu teardown errors); Qt messages show in captured stderr."
- **roadmaps/known-issues.md:** move the jobs 1, 2, 3 and scatter-test items to fixed, using the
  lines in notes.md; append the `test_activation_sources` note (no rerun since 2026-10-23; its
  macOS teardown failure may have been the same race).
- **roadmaps/_readme.md › Now:** the status-message audit item: keep it open as "audit done: five
  label proposals for Tony (notes, job 4)", or close it and add a new item once Tony picks wording.

## Open

- Job 6 (label changes from job 4), if Tony wants them.
- Which Linux thread sends the Qt message at the end of the scatter test is not confirmed (no
  Docker running here); `--no-qt-log` removes the race whatever it is.
