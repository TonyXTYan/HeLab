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
