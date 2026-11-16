# v0.0.9 re-review — 2026-11-17 (Australia/Sydney)

Repository: `TonyXTYan/HeLab`, branch `dev/v0.0.9`.

- Current reviewed head: `09ca79b200fff60fb9c5af6db514de20890f3a6f`.
- Previous reviewed head: `d2bd306da96e74bb457275f58dfa0a8f0ff7c13f`.
- Main/merge base: `a0c7f5c66cf570db6c6decd5e348f31205eafbbd`.
- Delta: 36 commits, principally Live/converter fixes and the new standalone `side_projects/laserlock` application.

**Result: three new findings, and all five previous findings remain reproducible.** The new findings below concern laserlock, not HeLab's main analysis GUI. No application code was changed; no review changes were committed or pushed. Tests used temporary data, simulated instruments and fake VISA sessions. No physical instrument was connected or commanded.

## New findings

### N1 — P1: Release leaves a pending correction able to change the output

**Locations:** `side_projects/laserlock/laserlock/engine.py:140–144`, `:324–326`, `:377–389`.

`_tick()` queues a correction in `_target` while the DG1022's next output slot may still be in the future. `release()` changes mode to idle and tells the user it is holding the applied voltage, but leaves `_target` intact. `_flush_output()` applies it even in idle mode. Clicking Release between computation and the next output slot therefore does not actually hold the voltage at the value reported to the user.

**Verified with fake devices:** starting at 3.0000 V, computed one correction, called `release()`, confirmed the snapshot was idle, then flushed. The output changed to **3.0100 V after Release**. This requires no unlucky simultaneous access: it follows directly from an ordinary pending output.

**Requested fix:** invalidate pending lock-originated targets when releasing, and make command validity survive the handoff from target selection to device I/O. A generation or equivalent command-ownership check should prevent an old correction from being applied after its lock session ends. Preserve deliberate manual output commands in idle mode.

**Acceptance tests:** hold the output slot unavailable, queue a correction, Release, then open the slot; no old correction may be written. Cover Release followed by manual output and re-engagement, and a device call waiting for its command slot.

### N2 — P2: the step limit does not bound individual hardware output changes

**Locations:** `side_projects/laserlock/laserlock/controller.py:92–100`; `side_projects/laserlock/laserlock/engine.py:324–326`, `:377–389`.

The controller limits each computed target relative to its previous computed `self.voltage`. The engine can process multiple readings while writes are rate-limited, advancing this virtual voltage without applying any intermediate target. When a write becomes possible it sends the final target directly. Thus “Max step / update” is a limit per controller calculation, not a guarantee on the physical voltage jump. This distinction matters when the measurement rate exceeds the output rate, which is the coalescing path the engine supports.

**Verified with fake devices and a fixed clock:** with nonzero integral gain, `max_step=0.0100 V`, and ten readings while the output slot was unavailable, no intermediate writes occurred. The next single write changed the output by **0.1000 V**, ten times the setting. The absolute 0–7 V limit still held; this is a step-limit defect, not evidence of exceeding the hard voltage range.

**Requested fix:** enforce the intended physical step bound against the last applied output at the output stage and reconcile the controller's state/anti-windup with the applied value. Keep queued targets coalesced rather than building a backlog. If the setting is deliberately only a calculation-step limit, its UI/documentation must explicitly distinguish it from a physical output-step safeguard; the current control provides the former only.

**Acceptance tests:** run a fake source faster than a rate-limited fake output, with integral action and changing errors. Check consecutive physical writes, including the first write after a delay, against the declared bound. Include a slow/rounded device result.

### N3 — P2: a stable-range hold succeeds without a valid measurement

**Locations:** `side_projects/laserlock/laserlock/engine.py:551–565`, `:621–628`.

The final hold test rejects confirmed hops and three out-of-range readings, but never requires a valid reading. If signal disappears or no fresh measurements arrive during the hold, `_collect()` can repeatedly return an empty list. With no hop or outlier to reject, the hold returns `None` (success), and `_find_stable()` engages and reports a successful lock using the earlier scan. Absence of measurements is being treated as evidence of stability.

**Verified:** ran `_hold_test()` with its collection seam returning no measurements for the entire hold; it returned success. The caller's immediate success path to `_engage_in()` is visible at lines 623–628. This is a deterministic logic probe, not a live hardware result.

**Requested fix:** require fresh valid measurements during the hold, including sufficiently recent measurements at its end; return a clear insufficient-readings/no-signal result when those requirements are not met. Keep the output unlocked and use the existing failed-scan cleanup path.

**Acceptance tests:** signal disappears after the scan, repeated stale readings, zero fresh readings, loss and recovery during the hold, and a genuinely stable fresh stream. Only the last case, or an explicitly satisfied recovery policy, may pass.

## Previous findings rechecked at the current head

The affected source files are byte-for-byte unchanged since the earlier review. The five previous probes were rerun against **this checkout**, and all reproduced. Full triggers, fixes and acceptance tests are in `previous-review/review.md` in the ZIP; the fresh observations are in `current-review/previous-findings.log`.

| ID | Priority | Current status |
|---|---|---|
| R1 | P1 | Still open: partial venv swap failure leaves the active venv missing; rollback does not restore it. |
| R2 | P1 | Still open: updater only probes process/locks and does not exclude a new app start through installation. |
| R3 | P2 | Still open: non-divisible image-reduction blocks are uniformly stretched, shifting their physical bin positions. |
| R4 | P2 | Still open: Plane projections estimates zero bytes despite potentially multi-GB counts and full-resolution rendering. |
| R5 | P2 | Still open here on Python 3.13.5/Linux: final-teardown timer exits with an empty crash file; the raw-file-descriptor control retains the stack. |

## Security review scope

Reviewed the incremental HeLab changes for request/job lifecycle, cancellation/retry, conversion failure handling, and source/store boundaries. Inspected laserlock's device command paths, output limits, threading, configuration and shutdown code. Rechecked the earlier updater/integrity findings. No new remotely exploitable vulnerability was confirmed. This does not constitute a dependency-CVE audit or verification of real instrument behavior. N1–N3 are control/measurement correctness findings; the priority reflects their demonstrated behavior, not a claimed hardware-damage outcome.

## Validation and deliverables

- `current-review/new_findings_probes.py` and `new-findings.log`: the three new fake-device/logic reproductions.
- `current-review/previous_findings_probes.py` and `previous-findings.log`: all five previous probes rerun against the current head.
- `current-review/reviewed-delta.patch`, `commits-since-previous.txt`, `changes-summary.txt`: exact reviewed changes and commit list.
- `previous-review/`: every retained artifact from the original review, including its full report, probes and complete validation logs. Historical results describe `d2bd306`, not the new head.
- Standalone laserlock suite: **35 passed, 1 failed** in 63.24 s. The failure is `test_laserlock.py::test_window_draws_hops`, at line 488: `assert sum(a.isVisible() for a, _ in win._hop_pool) == 1`, observed **0**. The same test failed alone in 3.51 s. A longer simulator diagnostic did display the marker (`pool=1` by 1.34 s in that run); the original test uses fixed-duration event pumping and the UI throttles hop redraws. The exact cause of the failing assertion remains unresolved; do not call this suite green. Logs: `laserlock-tests.log`, `laserlock-hop-focused.log`, `hop-diagnostic.log`.
- The side-project suite is intentionally skipped by HeLab's normal collection when `laserlock` is not importable. It was therefore run separately with its source on `PYTHONPATH` and PyVISA 1.16.2 installed into an isolated review-only dependency directory; no native VISA backend or real hardware was used. That environment/cache is not part of the ZIP.
- Main HeLab suite: **2 failed, 9,916 passed, 696 skipped, 18 warnings, 4 rerun**, 591.33 s. Command: `pytest -n 4 --reruns 2 --reruns-delay 1 -q`, with the venv scripts on `PATH` and the worktree's `venv` symlink in place before starting. **Not a clean suite.** Both failures reproduce symptoms recorded in the original review. Full output is retained as `current-review/full-suite.log`.
- All six tests in `tests/test_typing.py` passed in this run: strict and non-strict mypy for application/tests, and separate Pyright application/test checks. Unlike the initial historical run, this run had no missing-type-checker launch failures.
- This report is a review handoff; no fixes have been applied. The existing Python 3.13.5 environment was reused, rather than rebuilt from the lock file. Native Windows/macOS instrument/updater paths and private lab data were not exercised.

Every automatic rerun in the current main run (quoted from its `rerun reasons` summary):

| Test | Reruns | Reason and final result |
|---|---:|---|
| `tests/test_convert_helab.py::test_a_killed_helpers_workers_exit` | 2 | `AssertionError: assert [psutil.Proce...] == []`; `Left contains 3 more items`, Python processes in `status='zombie'`; failed at line 1193. The test has a pre-existing known-issues entry, and zombie children were also seen in the prior review. Cause not resolved here. |
| `tests/test_quit_confirms.py::test_a_teardown_stuck_where_the_watch_cant_run_is_ended_from_the_crash_files_timer` | 2 | `assert '__del__' in ''`; failed at line 121. Same empty-file symptom as R5. |

Please record these occurrences and the separate laserlock marker-test failure in the project's known-issues list when processing the handoff; shared roadmap documents were left untouched. The report, probe outputs and preserved logs were read back before packaging. The ZIP builder checks CRCs, entry contents and the SHA-256 manifest for every payload file.
