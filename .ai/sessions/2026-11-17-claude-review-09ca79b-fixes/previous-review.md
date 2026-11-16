# v0.0.9 security and bug review

Reviewed `TonyXTYan/HeLab`, branch `dev/v0.0.9`, at `d2bd306da96e74bb457275f58dfa0a8f0ff7c13f` (2026-11-11).
Comparison base: `origin/main`, `a0c7f5c66cf570db6c6decd5e348f31205eafbbd` (also the merge base).

**Recommendation: fix R1 and R2 before shipping the source updater.** Five actionable findings follow. No application code was edited and no review changes were committed or pushed. Review artifacts live in a separate detached worktree.

## R1 — P1: a partially failed venv swap leaves HeLab unable to restart

**Locations:** `helab/updates/updater.py:729–740`, `:912–922`, `:966–981`.

`swap_in()` renames the current venv to `.previous`, then installs `.new`. The caller only sets `swapped = True` after the whole function returns. If the last rename fails (for example, a persistent Windows permission/antivirus error), rollback sees `swapped=False` and only deletes `.new`. It never restores the active venv. Relaunch uses the now-missing original Python path and fails. An existing older backup can also be renamed out of the way before its location is returned to the caller. Restore's three-rename sequence has the same partial-progress problem.

**Verified:** injected an error on `.new → venv`, then called the same rollback branch as `update()`. The active venv was absent; the original remained stranded in `venv.previous`.

**Requested fix:** make both update and Restore swaps transactional at each rename, preserving enough state to reverse every completed step even when the next step raises. Preserve the previous restore record when an attempted update fails before replacing it successfully. Consider a small durable journal so a crash between renames is recoverable too.

**Acceptance tests:** inject failure after each rename, with and without a pre-existing `.previous`, for update and Restore. Assert the active Python path and original venv contents are restored, earlier backups survive, and code/restore metadata remain consistent. Include the symlinked-venv case.

## R2 — P1: the updater does not exclude a new HeLab start while changing code and venv

**Locations:** `helab/updates/updater.py:212–238`, `:813–831`, `:880–934`; `helab/main.py:209–226`.

The updater checks that processes and locks are gone but retains no exclusion lock during installation. `lock_held()` explicitly releases its probe immediately. After the old GUI exits, someone can launch HeLab again while the updater fetches, builds packages or swaps the venv. That GUI can take `running.lock` normally; the updater does not recheck it before the swap and proceeds under a running application. This violates the requirement that code/environment changes happen only after HeLab and its helpers have exited, and can leave a running process mixing versions or holding files the updater needs to replace.

**Verified:** drove `update()` with isolated planning/build stubs, acquired the real `running.lock` during the build to represent a new GUI, and confirmed the real `swap_in()` ran while that lock remained held.

**Requested fix:** establish a shared update/start exclusion protocol, held throughout code changes, venv changes and rollback. GUI startup and `helab convert` must participate before importing/using mutable application code. Hand off safely to the intended relaunch. Repeated process polling alone leaves the race open.

**Acceptance tests:** pause installation before checkout and before venv swap; attempt independent GUI/converter starts and a second updater. They must be blocked/refused until the transaction ends. Verify failure/rollback releases the exclusion and the intended relaunch succeeds.

## R3 — P2: reduced images shift bin positions when the last block is smaller

**Locations:** `helab/analysis/histogram2d.py:115–148`; `helab/scripts/standard_v2/histograms_2d.py:1032–1035`, `:1260–1267`.

`block_mean()` permits a smaller final block and `block_edges()` correctly preserves its narrower width. However, PyQtGraph's `setRect()` and Matplotlib's `imshow(extent=...)` stretch all reduced cells uniformly over the complete range. For a bin count not divisible by the reduction factor, those displayed coordinates no longer match the underlying bins. Features shift relative to physical coordinates and overlays; the last cell is drawn too wide. This affects the default screen-resolution image path above the reduction threshold.

**Verified:** 2,049 unit-width bins reduce by 2 to 1,025 cells. The true final cell starts at 2,048; the uniform raster starts it at approximately 2,047.001. The mismatch needs no large allocation to reproduce.

**Requested fix:** either resample into genuinely uniform physical-coordinate display cells, or render the actual reduced edges. Keep edge blocks' values/weighting and their drawn coordinates consistent in both backends.

**Acceptance tests:** non-divisible shapes such as 2,049×4 and 3,001×5, with an isolated feature at the high edge. Check actual rendered cell coordinates against the original edges in PyQtGraph and Matplotlib; retain a divisible-shape control.

## R4 — P2: Plane projections bypasses the large-plot memory warning and display reduction

**Locations:** `helab/scripts/standard_v2/plane_projections.py:138`, `:319–324`, `:393–396`; inherited default `helab/scripts/base.py:197–208`.

The new plot allows 10,000 bins per axis for up to four planes, retaining all planes' `int64` counts and passing full-resolution arrays to Plotly on the GUI thread. It does not override `estimated_bytes()`, so the existing settings warning receives zero. Four maximum-size counts arrays alone occupy 3.2 GB (about 2.98 GiB), before histogram temporaries, Plotly copies/serialization and rendering. Even the default three enabled planes retain 2.4 GB at that bin setting. A valid UI choice can therefore consume several GB and stall rendering without the warning implemented for the adjacent XY/XT/YT plot.

**Verified:** `PlaneProjections().estimated_bytes('', {'panel_bins': 10000, 'plane4_on': True})` returns `0`. The memory lower bound follows directly from array shape and dtype; an OOM was deliberately not induced.

**Requested fix:** implement an estimate covering every enabled plane and rendering overhead, connect the existing warning/Undo/Cancel behavior, and prepare a bounded-resolution display on the worker while preserving full analysis counts. Preserve any intentional full-resolution export option separately.

**Acceptance tests:** estimates scale with enabled planes and bin count; a modest test budget triggers the warning; Plotly's displayed cell count stays bounded for large requested bin counts. Test via estimates/small fixtures rather than allocating multi-GB arrays.

## R5 — P2: the last-resort teardown timer can exit without saving its crash stack

**Locations:** `helab/utils/crash_file.py:45–71`; `tests/test_quit_confirms.py:112–121`.

The existing stuck-teardown test fails consistently here on Linux/Python 3.13.5: the timer exits with code 1 as intended, but its crash file is empty instead of containing the stuck destructor's stack. Holding the Python file object in `_armed` does not keep the output usable through the final interpreter collection in this reproduction. The process ends, but the diagnostic evidence this feature promises is lost.

**Verified:** failed on all three attempts in the full suite and again alone (`1 failed in 3.84s`). As a control, the same teardown script passed an unwrapped `os.open()` file descriptor to `faulthandler.dump_traceback_later()`; it exited with code 1 and recorded `__del__` in the stack. This isolates the output-lifetime problem from suite load.

**Requested fix:** give the armed timer an output descriptor that stays open through Python object finalization, and keep its ownership/cleanup explicit. The raw-fd control is evidence for that approach, not a completed cross-platform fix.

**Acceptance tests:** retain the existing subprocess test and require a nonempty stack naming the stuck destructor on supported Python versions and OSes. Also verify ordinary clean exits still remove empty crash files.

## Security scope and limits

Focused review covered the new source updater's trust checks, command construction, process/lock lifecycle and recovery; GitHub update responses and CI selection; script import/probe changes; changed release workflows; and new analysis/display paths. R2 is an integrity/exclusion issue, not a demonstrated remote-code-execution exploit.

No new remotely exploitable vulnerability was confirmed in the inspected changes. This is not security certification or a dependency-CVE audit. User analysis scripts still execute Python with the user's permissions: the probe process is a reliability check, not a sandbox. The legacy store-v3 fallback still uses pickle; this predates the branch and requires trusted cache contents. Neither is counted above as a newly introduced defect. Native Windows/macOS updater behavior and private lab data were not exercised.

## Validation

- `probes.py` and `probes.txt` beside this report contain the five probes and observed results. File mutations are confined to temporary directories; updater lifecycle tests use injected stubs where noted above.
- Focused existing tests: **212 passed, 3 skipped**, no reruns (`test_updates_updater.py`, `test_updates_launch.py`, `test_updates_github.py`, `test_basic_plots_v2_hist2d.py`).
- RGA side-project tests: **23 passed**, no reruns.
- Full suite (`pytest -n 8 --reruns 2 --reruns-delay 1 -q`, Python 3.13.5/Linux, existing environment): **8 failed, 9,892 passed, 695 skipped, 18 rerun**, 604.05 s. **Not a clean run.** Six failures were this review's initial `PATH` setup error; the remaining failures were the converter test below and R5. Private data/optional backends were not installed for this review.
- Strict mypy subsequently passed: **244 application files**, **242 test files**. Final separate Pyright checks of `helab` and `tests` both passed with **0 errors, 0 warnings**. A parallel retry of the typing tests was stopped after subprocesses received signal 9; a combined Pyright run also exited 247 without diagnostics. The successful final Pyright checks ran separately after the full suite to reduce resource contention. Detailed results are in the retained logs.

Every test needing a rerun in the full run:

| Test | Reruns | Observed reason / final result |
|---|---:|---|
| `test_typing.py::test_pyright_tests` | 2 | `FileNotFoundError: ... 'pyright'`; failed in initial suite |
| `test_typing.py::test_pyright_helab` | 2 | Same initial PATH error; failed in initial suite |
| `test_typing.py::test_mypy_helab_soft` | 2 | `FileNotFoundError: ... 'mypy'`; failed in initial suite |
| `test_typing.py::test_mypy_helab_strict` | 2 | Same initial PATH error; failed in initial suite |
| `test_typing.py::test_mypy_helab_tests_soft` | 2 | Same initial PATH error; failed in initial suite |
| `test_typing.py::test_mypy_helab_tests_strict` | 2 | Same initial PATH error; failed in initial suite |
| `test_convert_helab.py::test_a_killed_helpers_workers_exit` | 2 | Expected no children, found three zombie Python processes; failed. This test already has a known-issues entry, but the recorded earlier symptom was the pool not yet being visible, not these zombie children. Cause of this occurrence remains unresolved. |
| `test_basic_plots_v2_hist2d.py::test_dots_on_a_black_or_white_plot_area[local density]` | 1 | `worker 'gw1' crashed while running ...` / `Not properly terminated`; passed on retry. Cause not established. |
| `test_correlations.py::test_fifty_shots_of_two_thousand_events_take_seconds` | 1 | `AssertionError: radial: 25.5 s`, against `< 20`; passed on retry. This timing test already has a known-issues entry. |
| `test_quit_confirms.py::test_a_teardown_stuck_where_the_watch_cant_run_is_ended_from_the_crash_files_timer` | 2 | `assert '__del__' in ''`; failed, including an isolated follow-up. See R5. |

Please record the new rerun/failure occurrences in `roadmaps/known-issues.md` when applying fixes; this review leaves shared roadmap documents unchanged. Retained logs: `full-suite.log`, `focused-tests.log`, `rga-tests.log`, `typing-retry.log`, `strict-types.log`, `pyright-app.log`, `pyright-tests.log`, `quit-focused.log` beside this report.
