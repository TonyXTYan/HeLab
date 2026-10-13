# Refactoring large modules

Added: 2026-10-13. Draft; nothing implemented.
Priority and completion: [overview](_readme.md).

## Purpose

The folder-browser and cache work grew a few modules to sizes that are hard to
read, review and change safely. Live monitoring and the analysis workflow will
add to the same files. The aim is to split them into focused modules **without
changing behaviour**, before that work starts.

## Measurements (2026-10-13)

| File | Lines | Shape |
|---|---|---|
| `helab/views/FolderExplorer.py` | 1908 | `FolderExplorer`: 116 methods (loading, large folders, summary wording, context menu, scans, flags, navigation) |
| `helab/utils/folder_cache.py` | 1644 | `FolderCache`: 81 methods; `_on_event` alone is ~340 lines |
| `helab/io_helper.py` | 1332 | 38 functions: every helper operation in one process entry module |
| `helab/utils/cache_store.py` | 1326 | `CacheStore`: 66 methods over records, datasets and maintenance |
| `helab/views/HelabMainWindow.py` | 1248 | `HelabMainWindow`: 59 methods |
| `helab/models/SnapshotFileSystemModel.py` | 1050 | `SnapshotFileSystemModel`: 58 methods |
| `tests/test_folder_cache.py` | 1413 | Follows `folder_cache` |
| `tests/test_folder_summary.py` | 1204 | Follows the summary wording |

## Rules for every step

- Move code, don't change it. Behaviour, wording and timings stay the same;
  clean-ups go in separate later commits.
- One module per step, each its own commit. Each step passes the full suite
  (`pytest -n 12 --reruns 5 --reruns-delay 1`) and strict mypy/pyright.
- Keep the import rules:
  - helper modules never import Qt GUI code;
  - scanning doesn't import numpy or pandas (they stay local imports in the
    loading code);
  - `--version` loads no GUI services (`tests/test_versioning.py`);
  - the frozen helper entry point in `helab/main.py` still runs first.
- Check that the PyInstaller build still finds every moved module, and that a
  packaged helper still runs a load.
- Update references to moved names in `AGENTS.md`, `.ai/memory/results/` and
  test monkeypatch targets (for example `helab.io_helper.SETTLE_SECONDS`).

## Proposed splits, in order

The least coupled code goes first, and the GUI goes last.

1. **`io_helper.py` → a helper package.** It's pure functions behind a clear
   process boundary.
   - Keep `io_helper.py` as the entry point and dispatcher (`emit`, `Pause`,
     `Heartbeat`, `main`).
   - Move the operations into separate modules:
     - browsing: `list_folder`, `scan`, summaries, subtrees;
     - loading: `read_cached`, `load`, fingerprints, settling;
     - `folder_icons`;
     - `cache_admin` with its usage and pending-save events;
     - `cache_move_job`.
2. **`CacheStore` → parts that share one connection.**
   - records: summaries, histories, subtrees, folder prefs;
   - datasets: save, read, retire, sweep;
   - maintenance: inventory, clear, purge, trim, adopt, discard, budget.
3. **`FolderCache` → a job core plus stores.**
   - the job core: submit, deliver, replay, cancel, transfer, and `_on_event`
     split per operation;
   - dataset memory: datasets, retain/release, RAM budget, eviction;
   - disk-cache state: status, usage, pending saves, removals, admin, sweep;
   - folder metadata: snapshots, summaries, histories, subtrees, prefs, icons.
4. **`FolderExplorer` → the widget plus collaborators.**
   - a load controller: selection loads, background loads, dwell, cached
     display, large folders, `_io_event`;
   - the summary and activity wording, moved to plain functions that tests can
     call without widgets;
   - the context menu with folder flags;
   - basic-scan controls.
   - Keep the public names that `FolderDetailsPanel`, `HelabMainWindow` and the
     tests use, or forward them.
5. Later, if still needed: `HelabMainWindow` (docks and menus) and
   `SnapshotFileSystemModel` (node state versus Qt model glue).

Split the tests along the same lines as their modules.

## Acceptance

- No module over about 800 lines and no class over about 50 methods. This is a
  guideline, not a hard rule.
- The full suite and type checks pass after each step, and the import rules
  above still hold.
- A packaged app still browses, loads (in its helper) and moves the cache.

## Open decisions

- When to start: after `v0.0.5a1` merges, as the first v0.0.6 work (proposed).
- Package and module names (for example `helab/helper/` for step 1).
- The size guideline, and whether a test should enforce it.
