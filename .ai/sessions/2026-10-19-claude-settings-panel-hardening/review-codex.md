# Codex review: Settings panel hardening

Branch `agent/settings-panel-hardening`, base `486cf56`, head `6514ee9` (8 commits). Verdict: **changes requested** for one activation defect; one lifecycle gap needs a decision or explicit coverage. The unexplained early fatal error did not recur in this review.

## Findings

1. **Activation after hiding a focused plot can stay on the hidden plot (moderate).** `PlotSettingsPanel._focus_changed` returns whenever the old widget is hidden (`helab/models/ScriptTreeSelector.py:795-802`). The existing test demonstrates that hiding plot A moves focus to B while the panel deliberately remains on A (`tests/test_plot_settings_panel.py:130-140`). A subsequent click in B's already focused editor produces no `focusChanged` signal, and no tab or window activation is involved if B is a separate dock in the same main window. The Settings panel therefore still shows hidden A despite clicking B. Add a regression case for that click and arrange to follow the first user interaction with the newly focused plot, or select a visible fallback when a plot is hidden. The current test resets focus to A before checking a user focus change, so it misses the case.

2. **Accepted main-window close still leaves plot runs connected and results pinned until widget deletion (remaining lifecycle gap).** `HelabMainWindow.closeEvent` detaches the panel but neither closes plot docks nor deletes the window (`helab/views/HelabMainWindow.py:1428-1458`). `AnalysisInstance.close`, which disconnects the runner and unpins the result, runs on dock close or destruction (`helab/models/ScriptTreeSelector.py:129-132, 280-293`). A normal QWidget close hides the window; it does not destroy its child docks. In a process that continues after closing one window (including tests), the old instances can remain connected to `AnalysisRunner.finished` and pin results. The new deletion test exercises `middle_mainwindow.deleteLater()`, while the main-window close test has no open plots. Cover accepted close with open plots and either end those runs there or document why the application can rely on immediate process teardown. This is a gap in the claimed lifetime hardening, not evidence that the new `destroyed` hook is faulty.

## Other review points

- `detach()` explicitly disconnects both application signals and the tab signal and is called only after the close decision is accepted. Deleting a panel also ends its QObject receiver connections. Tests check receiver counts across repeated panels and windows.
- `tab_target` excludes deleted, floating, detached and lone hidden docks; it can use a hidden dock inside a tab group. `_add_dock` shows the new dock before tabbing, addressing quick succession. Tests cover the stated rule, all-floating placement and 20 immediate plot openings.
- `DockTabCloser` matches Qt tab data against the dock's C++ address. This survives title collisions and tab reordering because lookup uses the current index's data. The tests cover title collisions and newly created bars after float, redock and show. Actual drag docking on cocoa and Windows remains a manual UI check. If a future Qt version changes the tab-data convention, it safely closes no dock.
- The hidden RHI surface is gated on `darwin` plus `cocoa` and `QtQuickWidgets` imports only in that branch. Windows, Linux and offscreen take the no-op path. Native Mac first-scatter behavior and the lab PC remain manual checks.
- `UnitSpinBox` uses a full-match number/prefix/unit parse, locale-aware comma, integral-only integer input, and clamp-on-fixup. Tests cover the listed invalid inputs, SI prefixes, negatives, empty input, limits and the parameter-tree path. The changed point-size assertion matches the approved clamping decision.
- Changed files are within brief ownership, including the explicitly approved `tests/test_analysis.py` assertion. The handoff's “seven commits, not pushed” line is stale relative to the reviewed eight-commit pushed head.
- The early fatal Python error could be related to Qt object teardown, but this review did not reproduce it or isolate a cause. The dock `destroyed` slot and panel page cleanup have targeted tests; accepted close with live plots is the remaining untested lifetime path.

## Validation

- Full suite, outside the sandbox with `venv/bin` on `PATH`: `pytest -n 6 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review` — **1072 passed, 2 skipped, 2 xfailed, no RERUN** (25.16 s).
- `mypy helab/ --strict` — 77 files clean. `mypy tests --strict` and `mypy tests --strict --platform win32` — 59 files clean each. Mypy initially failed because the sandbox could not open its cache database; all three passed with separate cache directories under `/private/tmp`.
- `pyright helab tests` and `pyright tests --pythonplatform Windows` — 0 errors each.
- `git diff --check 486cf56..HEAD` — clean.

## Recheck at c05ae95

Reviewed `git diff 6514ee9..c05ae95` (the two fix commits plus updated handoff). **The two original production findings are resolved.** Visibility loss now schedules a next-event-loop check and selects a visible fallback; tests cover the hidden plot followed by a click in another plot, and transient hide during float/redock. Accepted main-window close now calls `close_plots()`, taking each dock through `AnalysisInstance.close`; a test verifies cancellation, runner disconnection and result unpinning with one completed and one running plot.

**New minor test finding (fix before landing):** `tests/test_analysis_gui.py:583` connects an anonymous lambda to the app-wide `AnalysisRunner.finished`, and never disconnects it. Line 589 explicitly expects that extra receiver after the window closes. This test therefore leaves a global connection and its captured `cancelled` results alive for later tests. Keep a named callback and disconnect it in a `finally` block (after the cancellation assertion), then assert the runner's receiver count returns to its starting value. This is test contamination, not a remaining production leak. Verdict: **production fixes accepted; test cleanup requested**.

Validation at `c05ae95`:
- Full suite outside sandbox, `venv/bin` on `PATH`: `pytest -n 6 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review-recheck` — 1075 passed, 2 skipped, 2 xfailed, no RERUN (33.73 s).
- `mypy helab/ --strict`: 77 files clean; `mypy tests --strict` and `mypy tests --strict --platform win32`: 59 files clean each (separate writable caches under `/private/tmp`).
- `pyright helab tests` and `pyright tests --pythonplatform Windows`: 0 errors each.
- `git diff --check 6514ee9..c05ae95`: clean.

This recheck section is uncommitted. The earlier review file was added to the branch by the worker/coordinator between the two heads.
