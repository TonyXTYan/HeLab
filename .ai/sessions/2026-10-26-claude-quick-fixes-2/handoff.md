# Quick fixes, batch 2: handoff (Ferrule, 2026-10-26)

Branch `agent/quick-fixes-2` on base `0840acb`, pushed twice (`26994dd`, then job 6 at `9c1ce7a`). Details per job:
[notes.md](notes.md).

| Job | Commit | Change |
|---|---|---|
| 1 | `9d90156` | `cache_move.verify` also checks saved and pending results' files (`results/<uuid>.npz`). |
| 2 | `778641a` | `roots_verify` added to `io_helper.CACHE_ONLY`; tests keep it in step with `IOService.CACHE_OPERATIONS`. |
| 3 | `28fbc18` | A data root that goes or changes UUID drops its folders' saved-result counts from RAM (`FolderCache._root_results_gone`, nested roots kept). |
| 4 | `8de9ea6` | Audit: `tests/test_load_sources.py` pins what `merged` / `updated` loads read and when they save; five label proposals for Tony (notes, job 4). |
| 5 | `cd2b0c3` | `pytest.ini` `addopts = --no-qt-log`: pytest-qt's per-test swap of Qt's message handler raced with a Qt message from another thread (the scatter test's Ubuntu teardown reruns). |
| 6 | `93fb3dd` | Proposals 1-4, agreed by Tony: origin "disk cache + N TXY files read" / "memory [+ disk cache] [+ N TXY files read]" (`load_origin`), `file_started` only for files read, cache reason "K … to read" (dropped at 0). "Cached data found" kept. |
| notes | `26994dd`, `0ff0e12`, `9c1ce7a` | Brief, notes, `repro/` scripts, this handoff. |

## CI

| Run (head) | OS (py3.13) | Tests | RERUN |
|---|---|---|---|
| 40268142898 (`26994dd`, jobs 1-5) | Ubuntu | 4337 passed, 4 skipped, 2 xfailed | none |
| | macOS | 4339 passed, 2 skipped, 2 xfailed | none |
| | Windows | 4319 passed, 18 skipped, 2 xfailed | none |
| 40270085653 (`9c1ce7a`, + job 6) | Ubuntu | 4337 passed, 4 skipped, 2 xfailed | none |
| | macOS | 4339 passed, 2 skipped, 2 xfailed | none |
| | Windows | 4319 passed, 18 skipped, 2 xfailed | 1 (below) |

Both runs: success, builds green on all three.

Windows RERUN in 40270085653 (job 121400850933):
`test_result_cache_quit.py::test_an_old_stores_answer_never_says_saved_in_the_recreated_one`,
reason "PermissionError: [WinError 32] The process cannot access the file because it is being
used by another process: '…\\caches575\\store-v3\\records.sqlite'" (in `shutil.py`). The test
already waits for every helper's confirmed exit (`not cache.service.cache_busy()`) before
`shutil.rmtree(directory)` (line 152), so the file was still open after that: a handle Windows
hadn't released yet, or another process (indexer, antivirus). Not touched in this batch (not its
code); a candidate job, in the family of `8195fc7`.

## Proposed doc changes (for the coordinator)

- **AGENTS.md › Testing:** "pytest-qt's Qt log capture is off (`--no-qt-log`, `pytest.ini`): its
  per-test swap of Qt's message handler raced with QtWebEngine logging from another thread
  (Ubuntu teardown errors); Qt messages show in captured stderr."
- **roadmaps/known-issues.md:** move the jobs 1, 2, 3 and scatter-test items to fixed, using the
  lines in notes.md; append the `test_activation_sources` note (no rerun since 2026-10-23; its
  macOS teardown failure may have been the same race).
- **roadmaps/_readme.md › Now:** close "Finish the status-message audit" (done: `8de9ea6`, `93fb3dd`).
- **known-issues (Tests and CI):** add the Windows rerun above, cause unknown.

## Open

- Which Linux thread sends the Qt message at the end of the scatter test is not confirmed (no
  Docker running here); `--no-qt-log` removes the race whatever it is.
