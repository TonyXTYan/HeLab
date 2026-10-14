# Shared cache reuse implementation

Date: 2026-10-06

## Existing caches and decision

Kept `data_ram_cache` and its existing Blosc/pickle dictionary format. It is a disk cache, despite the RAM name. Kept legacy status and OS caches for their consumers; neither represents the complete new folder model, and their reads do not belong in GUI rendering.

Added `helab/utils/folder_cache.py`: a session memory store and subscription layer associated with IOService. New tabs keep independent Qt models, selections, expansion states and data dictionaries, while sharing directory metadata and NumPy arrays.

## Behavior

- A folder snapshot checked within 10 seconds is reused without launching a scan. Older snapshots display immediately, followed by a shared background check. Explicit Refresh and deep recalculation bypass the freshness window. Completed child-folder counts are restored from memory without scanning children.
- The last successful default-folder resolution is reused within the session.
- Concurrent scan, load and default-resolution requests share a producer. Closing/cancelling a tab removes only its subscription; other subscribers continue.
- Complete scans are published in 128-entry Qt batches. Failed/incomplete scans do not replace snapshots. New refresh results supersede deferred older replay.
- Loaded arrays are shared by folder/source fingerprint, marked read-only, and attached through a private dictionary per tab. Analysis code needing mutable arrays should use `.copy()`.
- Refresh propagates source changes to other tabs. Old displayed arrays remain available during replacement or failure. The main window routes signals to their originating tab, including inactive tabs, while keeping visible titles/plots scoped to the active tab.
- Green RAM badges describe shared memory availability. Footer text distinguishes finding the default folder, scanning, checking for changes, loading data and Ready. The 16 px rows and existing arc spinner remain.
- The 512 MiB array-data budget evicts unused entries. Open tabs pin their current datasets and can exceed that soft budget. Snapshot retention is limited to 256 folders and 100,000 entries; one scan exceeding the entry limit fails without publishing partial results.
- Clearing a folder cache invalidates shared datasets and obsolete load results. A transactional disk epoch prevents a load started before clearing from repopulating the disk entry. Helpers recheck file metadata before publishing loaded data and reject files that changed during reading.
- Scan/load fingerprints both use the target metadata of symlinked TXY files, avoiding perpetual reloads caused by mismatched signatures. Directory symlinks remain untraversed.
- Temporary helper artifacts are cleaned asynchronously after their arrays have been read. Shared subscriptions/cache state are released on shutdown.

## Validation

The focused tests include real helper processes: a warm second tab produces no additional scan/load request and shares the same array objects; a changed-source refresh produces one new scan and one new load for both tabs.

Additional tests cover concurrent subscribers, cancellation, independent dictionaries, read-only arrays, default-path reuse, expired snapshots and failed validation, refresh replay ordering, child-count restoration, memory eviction/pinning, late results after clearing, disk invalidation epochs, changes during source reading, oversized-folder limits, and symlinked file fingerprints. Existing responsiveness and disk-cache reuse regressions remain.

Final full suite: **123 passed**, including strict mypy and pyright checks. The existing `logging.warn` deprecation warning remains. `git diff --check` is clean.

```sh
source venv/bin/activate
venv/bin/pytest -q
venv/bin/mypy helab tests --strict
venv/bin/pyright helab tests
git diff --check
```

## Limits

- This memory store lasts for one application session. Restarting the application still uses and validates the existing disk cache.
- Freshness checks occur on access or explicit Refresh; this does not add a periodic filesystem watcher. An unchanged size/mtime fingerprint cannot detect deliberately altered contents with preserved metadata.
- Paths are normalized lexically without filesystem resolution. Symlink aliases and differently cased aliases may have separate entries.
- Read-only arrays prevent ordinary in-place mutation; this is a plugin contract, not a security boundary.
- Actual stalled remote mounts, Windows execution and packaged builds remain manual release checks.
- Concurrent settings-related edits in README.md, constants.py, tests/test_constants.py and the settings paragraph of AGENTS.md were preserved; they were not part of this cache work.

The user requested a local cache-reuse commit after verifying the concurrent work. The settings changes were committed separately as `62cdf55`. No push was requested.
