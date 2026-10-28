# Quick fixes, batch 1: CI reruns (brief, CoCo, 2026-10-23)

Floor "Quick Fixes", branch `agent/quick-fixes`, base `2994870` (dev/v0.0.6 = origin). Coordinator: CoCo. Tony asked for this (Chat, 2026-10-23: "create the role, recruit, and fix").

## Objective

Find the cause of the open CI reruns in `roadmaps/known-issues.md` → Tests and CI, then fix each one or add diagnostics that name the cause, in this order (worst first):

1. **`tests/test_presets_window.py::test_a_live_off_preset_turns_live_off_in_a_real_tab`: the test worker crashes.** The worker died with no traceback ("worker 'gwN' crashed", "node down: Not properly terminated") on Ubuntu (runs 39814028933, 39880474971) and Windows (39880474971). That's 3 of 4 CI test runs off macOS. It passes on rerun and in 8 macOS runs. The test builds the real `HelabMainWindow` offscreen with two arrangement presets. It is new from Presets Reopen (handoff: `.ai/sessions/2026-10-22-claude-presets-reopen/handoff.md`). A native crash is likely, e.g. a Qt object used after deletion, a dock or window torn down twice, or a QWebEngine page. That could hit the app too, so look at the production path, not only the test. Ideas: run it under `PYTHONFAULTHANDLER=1` with `-p no:cacheprovider` in a loop with the whole module and its neighbours under `-n 4`; `faulthandler.enable(all_threads=True)` in the test; a Linux run if Docker is available here. If you can't reproduce it, add diagnostics that will name the crash at the next CI failure (faulthandler output to a file the test prints, or `pytest -p faulthandler` with `faulthandler_timeout`), and say so.
2. **`tests/test_live_plots.py::test_a_following_scatter_updates_its_page_in_place`: a teardown error.** "Exceptions caught in Qt event loop: TypeError: 'NoneType' object is not callable", on Ubuntu in runs 39731793369 and 39880474971. Probably a callback (timer, signal or Dash poll) firing after its owner was torn down.
3. **`tests/test_live_io.py::test_a_live_check_pauses_background_work_only_while_it_reads`.** `waitUntil` timed out at line 102 on Windows (39731793369).
4. **`tests/test_io_service_run.py::test_a_helper_that_dies_leaves_what_it_said_in_the_log`.** The helper's error was "[Errno 32] Broken pipe" instead of "I/O helper exited unexpectedly" (line 79), twice on macOS (39734426913). Decide whether the app should report a broken pipe as the helper exiting (code) or the test should accept both (test).
5. **`tests/test_cache_first.py::test_a_folder_changed_within_its_mtime_tick_is_listed[cached]`.** The cause is probably the test spending part of `RACY_SECONDS` before its first load. A test-only fix is saved as R-23 in `.ai/sessions/2026-10-22-claude-codebase-review/findings.md`: check it and apply it if it holds.
6. **`tests/test_plot_settings_panel.py::test_activation_sources`.** A macOS teardown failure, cause unknown. Read the rerun reasons of any CI run that has it; if nothing new turns up, record what you tried and move on.
7. **Cosmetic:** `helab/views/plots/presets.py` ends with an extra blank line (`git diff --check`).

The known-issues entries have the details. Before you start, count each test's reruns over the recent CI runs: `gh run list --branch dev/v0.0.6` and the agent branches, then `gh api repos/TonyXTYan/HeLab/actions/jobs/<id>/logs`. Windows logs include the test output there, whereas `gh run view --log` can return nothing. Say if any of them no longer occurs.

## Scope

- Owned paths: those tests and their helpers (`tests/`). In the code they exercise: the smallest change that fixes the cause.
- Ask CoCo before:
  - changing anything a user sees;
  - touching `tests/conftest.py` beyond a small fixture;
  - touching more than a few files for one job.
- Don't touch `helab/analysis/results*`, the result cache, or `cache_store.py`'s results tables: the Result Cache floor (Cellar) is working there and lands soon. If a fix needs them, ask first.

## Checks and handoff

- Per job: a commit (subject + body: cause, fix, checks), and a section in this folder's `notes.md` with the cause, evidence, fix, checks and a proposed known-issues line (fixed with the commit, or still open with what's now known).
- Before each report: the full suite, strict mypy (helab and tests) and pyright. Report each RERUN with its reason.
- Don't push: CoCo pushes the batch once, to check it on Windows and Ubuntu CI.
- Report each job when it's done (then go on): `maestri ask "CoCo" "<job N: cause, commit, files, checks with RERUNs, proposed known-issues line>"`. When all are done, post `--state review` and add a short handoff.md.
