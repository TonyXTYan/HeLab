# GUI responsiveness implementation

Date: 2026-10-06

## Delivered behavior

- Default folder availability is resolved after the window appears, in an isolated helper. The user's `/Volumes/dld_output` candidate remains first. An unavailable or timed-out default produces a Retry state rather than synchronous startup probing.
- The explorer opens directly inside its target. Parent navigation is explicit; unrelated mounted volumes are not scanned automatically.
- `SnapshotFileSystemModel` replaces `QFileSystemModel` in the active explorer. Qt rendering queries only use memory. Directory discovery and metadata/status computation are isolated from the GUI process.
- Directory results arrive in batches of at most 128 entries. UI delivery is capped at 64 messages and an 8 ms budget per timer turn. Refresh traversal is incremental and only follows branches expanded in the current view.
- `IOService` permits two active requests, at most 128 queued requests, and at most two retired/stalled requests before dispatch pauses. Duplicate requests coalesce. Generations reject results after navigation; closed tabs disconnect their receivers.
- Scans time out after 15 seconds, default resolution after 5 seconds, and loads after 300 seconds. These deadlines are request parameters in `IOService.submit()`. Cancellation and timeout retire/kill helpers asynchronously and never wait for a blocked OS call on the GUI thread.
- TXY loading, compressed-cache access, source fingerprint validation, and compression run in helpers. Daemon reader threads read temporary per-shot artifacts and deliver ordinary NumPy arrays to the GUI. The existing float64 dictionary and Blosc-compressed data-cache format are retained. Changed files trigger reloads; cache clearing is also asynchronous.
- Folder spinners remain visible on selected rows. The explorer also shows an indeterminate scan bar, dataset progress when measurable, Cancel and Retry controls, and a path entry field. The main status bar summarizes active/queued work. Existing plots remain available while replacement data loads.
- Folder rows are 16 px high. The folder and footer indicators share a 10 px arc spinner with a 2.5 px stroke and synchronized animation; the footer indicator hides when idle.
- Main-window path entry and Windows drive discovery avoid synchronous remote metadata probing. The application no longer disables tab switching because I/O is active.
- Shutdown stops producers and retries first, invalidates results, and cancels helpers without joining them. Shared legacy caches are closed outside the GUI thread after their users finish. Legacy worker cancellation without retry no longer schedules another scan.
- `GUIWatchdog` measures event-loop delay and dumps thread stacks from an independent daemon thread after sustained stalls.
- The packaged helper bootstrap executes before GUI/cache/Dash imports. Windowed bundles use local request/result files because standard streams may be unavailable.

## Validation

The full suite passed: **110 tests**, including the existing strict mypy and pyright tests. The final checkpoint run reported the existing `logging.warn` deprecation warning and a Dash startup thread warning because port 8050 was already occupied.

Focused regression coverage checks:

- Rendering performs no filesystem or disk-cache reads.
- Scope excludes collapsed descendants and rejects stale results after navigation.
- A helper sleeping for 60 seconds does not stop the GUI heartbeat; heartbeat gaps remain below 200 ms in the test. The request times out and the helper is retired/reaped.
- Cancellation does not restart scans, navigation remains enabled, and shutdown returns within 200 ms in the service test.
- Queue bounds and request deduplication hold.
- TXY shot IDs, float64 values, NaN-row filtering, compressed-cache reuse, and changed-source reloads behave correctly.
- The windowed helper file protocol runs through the early main-module bootstrap without initializing the GUI/Dash startup path. This uses an executable wrapper rather than a built bundle.

The loading UI was inspected with offscreen previews. `explorer-preview.png` shows the selected-folder spinner and busy indicator before the later row-height and spinner refinements. `loading-preview.png` shows the main-window arrangement. The 16 px row height was separately verified with offscreen Qt rendering.

Commands used:

```sh
source venv/bin/activate
venv/bin/pytest -q
venv/bin/mypy helab tests --strict
venv/bin/pyright helab tests
git diff --check
```

## Limits and release checks

- Responsiveness was verified using controlled stalled helpers and offscreen Qt windows. A manual run against the actual stalled remote mount is still needed to confirm the environment-specific behavior.
- The frozen helper transport/bootstrap is covered by a regression test. An actual PyInstaller build and Windows runtime execution were not performed.
- These changes protect browsing and dataset loading from stalled source I/O. Arbitrary custom analysis actions and legacy development plotting functions can still execute expensive code on the GUI thread; they are outside this I/O isolation boundary.
- An OS-wide stall can still affect the application. If helper termination itself stalls, dispatch is bounded rather than spawning unlimited replacements.
- The active browser uses lazy snapshots and tooltips; legacy `HelabFileSystemModel` and worker classes remain for compatibility and their existing tests. Old filesystem/status-cache debugging menus are replaced by refresh/deep-scan and asynchronous data-cache actions in the active browser.

Existing default-path edits were preserved. Cross-tab folder-snapshot and in-memory dataset sharing remain planned follow-up work and are not implemented in this checkpoint.
