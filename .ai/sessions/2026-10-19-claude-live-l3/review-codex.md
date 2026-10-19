# Codex review — Live L3

Branch `agent/live-l3`, base `d0b8fbe`, reviewed head `959bcf5` (2026-10-19).

## Verdict

**Changes requested.** Hold/coalesce, the per-plot timer, empty-folder Live I/O, result records and the staged failure render are broadly sound. The findings below leave a pinned plot able to advance, a changed pre-Live dataset unable to catch up, and one bundled plot without a clear zero-event state.

## Findings

1. **P1 — Pinning while a Live rerun is in flight still replaces the pinned plot.** `AnalysisInstance._live_settings_changed` calls `Follow.pin()` and stops the timer, but it neither marks the in-flight result as unshowable nor restores the last shown view. `AnalysisInstance._finished` then renders every completed result whose job ID matches, regardless of `follow.on` (`helab/models/ScriptTreeSelector.py:274-315,380-390`; `helab/analysis/follow.py:137-150`). Reproduce: show rev 1, hold a rerun on rev 2, turn Follow Live off, release the run. Rev 2 replaces rev 1 after the pin. Since `Follow.ran` already became rev 2 at submission, a subsequent manual Rerun also uses rev 2. Preserve the last displayed revision when pinning and discard or defer that in-flight result's rendering; test this sequence with a gated runner.

2. **P2 — A changed pre-Live dataset with the same shot numbers never catches a plot up.** The first `LiveFeed.publish` after Live starts uses `view_of(dataset)`. A plot made before Live can have another view identity for the same path. `Follow.offer` accepts that view, but `Follow.waiting()` counts only shot numbers absent from the old view, so `due()` refuses to run when the newer dataset has the same shots with changed fingerprints (`helab/analysis/follow.py:80-90,113-135,167-179`; `helab/views/HelabMainWindow.py:925-931`). The pending slot can then remain forever if no further shots arrive. This conflicts with the handoff's pre-Live catch-up case and the coverage rule for changed fingerprints. Run once on a changed input even when the number of new shots is zero; add a test with equal shot sets and differing fingerprints/signatures.

3. **P2 — Counts per shot does not show a zero-event empty state.** Its render guard checks only `len(data.shots)` (`helab/scripts/standard/basic_plots.py:117-129`). A loaded TXY shot with an empty event array yields a normal plot with zero counts, while the other bundled event plots use an explicit empty pane. The L3 brief requires every bundled plot to show a clear state for no events yet. Check `data.total == 0` and distinguish this from no shots or none chosen; add a test with a selected shot whose array has shape `(0, 3)`.

## Other review points

- Live arrivals do not call `runner.cancel`; `Follow.pending` is one slot and newer offers replace it. The runner's result is delivered to Qt on the GUI thread. Closing a dock stops its timer, disconnects signals, cancels its own job and guards `_finished` with `is_closed`/job ID. These paths were inspected, and existing tests cover coalescing and closing.
- The timer belongs to the plot instance. Pinning and closing stop it. Stopping Live or switching tabs removes the feed but retains revisions already offered; if a delay timer is armed, it can still run after Live is off. The handoff states this as an intentional judgment call. It should be confirmed with Tony because the brief also says plots keep their last revision after a tab switch; the existing Live-off test covers only a revision held below the every-N threshold.
- Coverage uses the effective Shots selection and view fingerprints, and `reuse_key()` includes the analysis identity, root/signatures, parameters and coverage. The bundled-plot keys passed JSON round trips. `Coverage.of` silently omits a fingerprint absent from view metadata, so the absolute “every result has fingerprints” guarantee still depends on the loader providing one for each loaded shot; I found no failing production path in this diff.
- Commit `672a96b` changes `live_check`'s guard from falsey memory to `memory is None`, allowing `[]` while still refusing an omitted base. `FolderCache.empty_dataset` is pinned through `_display`, and the empty start requires a current listing with zero TXY files and zero subfolders. Existing helper-process/read-gate and tab tests exercise the first shot. I found no change to settling, identity/mismatch, or I/O lane behavior in that commit.
- The “index 7 is out of bounds” text in `settings-live-group.png` is staged. `render_live_plots.py:56-60` explicitly raises that `RuntimeError` for a selected revision and captures the settings after the failure; it is not evidence of a bundled-plot indexing fault. Failed reruns keep the prior widget and show the amber line in the covered path.
- Changed paths match the brief's ownership plus the approved empty-folder files, tests and session artifacts.

## Checks

- Full suite, outside sandbox with `venv/bin` on `PATH`, `venv/bin/pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`: **1115 passed, 2 skipped, 2 xfailed; no RERUN**. The first attempt omitted `venv/bin` from `PATH`, so six typing tests could not find `mypy`/`pyright`; the corrected full rerun passed.
- `venv/bin/mypy helab/ --strict`: passed (79 files).
- `venv/bin/mypy tests --strict`: passed (61 files).
- `venv/bin/mypy helab/ tests --strict --platform win32`: passed (140 files). Initial sandboxed concurrent attempts failed to open mypy's SQLite cache; sequential runs outside the sandbox passed.
- `venv/bin/pyright helab tests` and `venv/bin/pyright helab tests --pythonplatform Windows`: 0 errors each.
- `git diff --check d0b8fbe..HEAD`: clean.

These are code review findings; the three new edge cases above were not added to the worker branch as tests or fixes.

## Recheck at 30723a9

**Verdict: approved for these three findings.** I reviewed `git diff 959bcf5..30723a9` at head `30723a9`. No new findings in the fix diff.

- **P1 resolved (`2089da4`):** the instance keeps each job's view and the last successfully shown view. Turning Follow off pins `Follow.ran` to the shown view; completion of the already running newer job is ignored while pinned. A manual Rerun stays on the pinned view, and turning Follow on again offers the feed's latest view. The new gated test covers that sequence. The result cannot be delivered to a closed dock because the existing close guard and signal cleanup still apply.
- **P2 changed input resolved (`9d9c54e`):** pending data now compares shot numbers and fingerprints. A different input identity with changed shots runs once even below an every-N threshold; subsequent revisions of one input still obey the policy. Purely identical shot content remains held. The new unit and plot-level tests cover an equal shot set with a changed fingerprint and verify the result's coverage and signature.
- **P2 empty state resolved (`f80091f`):** Counts per shot now shows the explicit empty pane when selected shots have zero events. The shared empty-state test now covers no shots, none chosen and zero events for all four bundled plots.
- The previously noted Live-off delay-timer behavior is unchanged by agreement in the handoff: an already offered revision may finish one rerun after Live stops or the tab switches. This remains a product decision for Tony, not a new finding on these fixes.

**Validation:** full suite outside sandbox with `venv/bin` on `PATH`, `venv/bin/pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`: **1122 passed, 2 skipped, 2 xfailed, no RERUN**. `venv/bin/mypy helab/ --strict` (79 files), `venv/bin/mypy tests --strict` (61), and `venv/bin/mypy helab/ tests --strict --platform win32` (140) passed. `venv/bin/pyright helab tests` and `venv/bin/pyright helab tests --pythonplatform Windows` both reported 0 errors. `git diff --check 959bcf5..30723a9` was clean. This recheck section is left uncommitted.

## Round 2 review at 4492385

**Verdict: changes requested.** I reviewed `3b417ae..4492385` at head `4492385`. The Live-off catch-up, any-folder Live behavior and newest-shot paths follow the Round 2 handoff in the cases tested. Two Dash page lifecycle issues remain.

### Findings

1. **P1 — A page can stay permanently one figure behind.** `DashServer` stores the figure and revision in separate synchronized dictionaries and reads them separately in both `display_page` and `newer_figure` (`helab/utils/dash_server.py:43-53,65-78`). A poll can read figure 1, then `update_plot` writes figure 2 and revision 2, then the poll reads revision 2 and sends **figure 1 with revision 2**. The client's store now says 2, so subsequent polls return 204 and never show figure 2. I reproduced this interleaving deterministically: `newer_figure('/plot/p', 1)` returned the old figure paired with revision 2, and the next call with `shown=2` returned `None`. The initial page callback has the same split-read risk. Store each plot's `(figure, revision)` as one atomic value or protect both operations with one lock, and test an update interleaved with a poll/page load.

2. **P2 — A browser page keeps the last plot after its dock closes.** `remove_plot` drops both server entries, but the polling callback maps a missing plot to `PreventUpdate` (`helab/utils/dash_server.py:56-63,84-87`). An existing **Open in browser** page therefore retains its old `dcc.Graph` and continues its one-second polling indefinitely. I sent the Dash callback a poll after `remove_plot` and received HTTP 204 with no body. The existing test checks only that server dictionaries are empty, not what an already open page shows. Return a closed/removed state that clears the graph or replaces it with the plot-not-found message, and stop that page's interval. Keep the no-figure-in-server behavior after close.

### Other review points

- `Follow.live_ended()` bypasses N and delay for one pending catch-up; an in-flight run is left to finish, then the pending newest view runs. `Follow.due()` blocks a pinned plot, and the new tests cover delay, N, pinning, in-flight work and an errored Live tab. I found no cancellation added for Live stop.
- The expanded empty-folder rule still requires a known zero-TXY status and no existing loaded or disk-cached dataset. `live_check` scans one directory with `os.scandir` and treats child directories only as `has_dirs`; the tab and helper tests check that a subfolder's shots are not read.
- `PlotlyPane.destroyed` removes its server figure and revision; the in-place scatter keeps one pane and URL across revisions. The new `@pyqtSlot` closes the runner connection promptly. These paths did not reveal a server-side per-plot data leak in the normal close test.
- The scatter reserves the display cap for the highlighted newest shot first, then samples older events into the remaining slots; when the newest shot alone exceeds the cap, the cap necessarily samples it. The histogram uses the same bins and labels its overlay as scaled. The v3 result identities reflect both plot changes. Tests cover a newest shot below the cap, the overlays and a following Live revision; an above-cap newest shot and a native camera-retention check remain untested.
- Every open Dash page sends one callback request per second, even when its figure has not changed (then a 204 response); the server uses threaded requests. No multi-page polling benchmark or native lab-PC load check was provided. That is a performance caveat, separate from the two correctness findings.
- `dash_server.py` is outside the original brief's owned paths, but the Round 2 handoff records Maestro's authorization for this change.

### Checks

- Full suite outside sandbox with `venv/bin` on `PATH`, `venv/bin/pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`: **1135 passed, 2 skipped, 2 xfailed; no RERUN**.
- `venv/bin/mypy helab/ --strict` (79 files), `venv/bin/mypy tests --strict` (61), and `venv/bin/mypy helab/ tests --strict --platform win32` (140): passed.
- `venv/bin/pyright helab tests` and `venv/bin/pyright helab tests --pythonplatform Windows`: 0 errors each.
- `git diff --check d0b8fbe..HEAD`: clean. The review section is left uncommitted.

## Recheck at 69c2ced

**Verdict: changes requested for one new P2 finding.** I reviewed `4492385..69c2ced` at head `69c2ced`. The two prior Dash findings are resolved; the new histogram right axis has a lifetime issue.

### Finding

1. **P2 — A highlighted histogram rerun retains its old overlay and data after the plot widget is deleted.** `overlay_newest` connects the local `follow` closure to both `plot.vb.sigResized` and `plot.vb.sigYRangeChanged` (`helab/scripts/standard/basic_plots.py:97-110`). That closure captures the plot and the overlay. In an offscreen Qt reproduction, after `GraphicsLayoutWidget.deleteLater()`, deferred-delete delivery and `gc.collect()`, Qt has deleted the widget, plot and overlay, but weak references to the plot wrapper, overlay wrapper, overlay curve and its NumPy `yData` are all still alive. The same reproduction without the overlay collects the plot, and disconnecting these two callbacks before deletion collects all five objects. A Live plot that replaces its widget on each revision therefore retains old histogram arrays and Qt wrappers. Disconnect the callbacks on widget/plot teardown or bind their lifetime to a QObject that Qt destroys with the widget, and add a close/replacement test using weak references.

### Rechecked behavior

- **Dash P1 fixed:** `PlotSnapshot(revision, figure)` is replaced and read as one value under `_plots_lock`. The forced interleaving test lands an update after the snapshot read for both a poll and an initial page: the old figure keeps its old revision and the next poll receives the new figure. The HTTP poll test verifies figure and revision together.
- **Dash P2 fixed:** after `remove_plot`, an existing page's HTTP poll clears and hides the graph, displays the closed text, and disables its interval. The server no longer retains that plot's snapshot.
- **Histogram right axis:** the overlay curve holds real bin counts. Its view divides the main Y range by `sum(all bins)/sum(newest bins)` in linear mode and subtracts `log10` of that scale in log mode; both place the curve at the intended relative height. The right axis is linked to the overlay view, the X ranges match, and Y zoom follows. Both axes use decade ticks in log mode. The overlay ignores drag, click and wheel events so the main plot handles them. I inspected the linear and log renders. Qt destroys the overlay graphics object with the widget; the Python retention above remains.

### Checks

- Full suite outside sandbox with `venv/bin` on `PATH`, `venv/bin/pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`: **1139 passed, 2 skipped, 2 xfailed; no RERUN**.
- `venv/bin/mypy helab/ --strict` (79 files), `venv/bin/mypy tests --strict` (61), `venv/bin/mypy helab/ tests --strict --platform win32` (140): passed.
- `venv/bin/pyright helab tests` and `venv/bin/pyright helab tests --pythonplatform Windows`: 0 errors each.
- `git diff --check d0b8fbe..HEAD`: clean. This review section is left uncommitted.
