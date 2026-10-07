# Load queue modes: implementation notes

Date: 2026-10-07
Status: implemented, uncommitted on `dev/v0.0.5a`.

## Bug found while implementing

`FolderCache._replay` passed the `revalidate` flag on to the follow-up scan, so every finished change check started another one. Any folder selected after its cached snapshot was older than 10 s kept rescanning, and its row spun forever. This was the main cause of "green RAM icon but still spinning". The flag is now removed from the follow-up scan, and the scan keeps the caller's priority.

## What changed

- `IOService`:
  - A load that has sent `loaded` (still writing its disk cache) gets `FINISH_TIMEOUT = 120 s`.
  - It no longer counts toward `MAX_ACTIVE_LOADS` or `MAX_ACTIVE`; at most `MAX_FINISHING = 2` can run.
  - New: `load_busy()`, `promote(owner)`.
- `FolderCache`:
  - `transfer()` moves a load subscription between owners, so the job keeps running and keeps its shots.
  - `promote(path)`.
- `SnapshotFileSystemModel`:
  - `load_states` (path → "queued"/"loading") replaces `FolderNode.loading`. It survives root changes.
  - New `LOAD_QUEUED_ROLE`.
- `FolderExplorer`:
  - `load_mode` and a background owner `f"{owner}:bg"` (generation 0).
  - The 3 s wait (`DWELL_MS`) is skipped when the queue is idle or the dataset is already in memory.
  - `queue_load()` handles the context-menu "Load data".
  - Background queue cap: `MAX_BACKGROUND_LOADS = 8`. The oldest still-queued load is dropped first.
  - Queued rows show a dotted grey ring.
- Settings:
  - `LOAD_MODE_SETTING`/`LOAD_MODE_LABELS`/`read_load_mode` in `constants.py`.
  - View → "When Selecting Another Folder" (exclusive actions).
  - Settings → General combo box. The main window re-reads the setting after the dialog closes.

## Validation

- `tests/test_load_queue.py`: 10 tests covering each mode, the 3 s wait, background → foreground handover with its shots, context-menu queueing, the cap, Cancel, revalidation priority and the no-loop fix, finishing loads, promote, and settings/menu sync.
- `pytest -n 4`: 161 passed, 1 failed. The failure is `test_mypy_helab_tests_strict`, which already fails at the baseline (`tests/test_debugIcons.py` untyped `mouseClick`).
- `mypy helab/` is clean. `pyright` reports 98 errors, the same as the baseline.
- Not yet done: the manual check in the real app with large and network folders.
