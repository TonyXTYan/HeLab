# Handoff: quick fixes, batch 3 (Shim, 2026-10-27)

Branch `agent/quick-fixes-3` (base `450b6ec`), pushed at `de00aa2`. Details: [notes.md](notes.md).

## Done

- **`test_store_identity.py::test_a_store_in_the_folder_whatever_its_age_ends_quit` timeout at
  `-n 12`.** Cause: a test closing a real main window shuts down the app-wide IOService. That
  stops its timer, so its retired helpers are never forgotten. `cache_busy()` counted them though
  their exit was confirmed, and `store_free()` stayed False for the rest of the worker's run.
  Fix: `cache_busy()` goes by the reaper's `exited` flag (`12338a3`), with a test that fails
  before.
- Commits: `12338a3` (fix and tests), `fc1b91c` (notes), `de00aa2` (Feeler's review points in
  the notes). This handoff is committed locally only.

## Checks

- Local (macOS): full suite `-n 12 --reruns 5` three times and `-n 4` once, 4465 passed and 2
  skipped each, no RERUN. The identity module 10 times. mypy (strict, helab and tests) and pyright
  clean.
- Review: Feeler (Codex) found no blocker and no new P1 or P2.
- CI run 40465666760 at `de00aa2`, success, no RERUN on any OS:
  - macOS: 4465 passed, 2 skipped (442 s).
  - Ubuntu: 4463 passed, 4 skipped (480 s).
  - Windows: 4438 passed, 25 skipped (900 s).
  - Builds passed on all three; compatibility matrices skipped (no PR).

## Proposed doc changes (for the Coordinator)

- `roadmaps/known-issues.md`: move the identity test's line to Fixed (text in notes.md, "Proposed
  `roadmaps/known-issues.md` line").
- Add the open follow-up line (notes.md, "Proposed follow-up line"): a main-window test leaves the
  app-wide IOService closed until the next `get_io_service()`, and a live one lasts the worker's
  run against later tests' stores. Don't reset a closed one without waiting for its helpers.
- The fix keeps the exit-confirmation rule only. A Windows venv's `python.exe` redirector child
  may still hold store files briefly; that is the existing known-issues line, unchanged.
