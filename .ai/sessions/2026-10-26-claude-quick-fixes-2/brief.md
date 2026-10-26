# Quick fixes, batch 2 (brief, CoCo, 2026-10-26)

Floor "Quick Fixes 2", branch `agent/quick-fixes-2`, base `0840acb` (dev/v0.0.6 = origin).
Coordinator: CoCo. Tony asked for this (Chat, 2026-10-26: "parallel floors, work on fixes and
cache-only mode").

A second floor, "Cache Only", runs beside you. It will change `helab/utils/folder_cache.py`,
`helab/utils/io_service.py`, `helab/io_ops/browse.py`, `helab/utils/cache_store.py` and the folder
browser. Keep your changes there as small as you can: your batch lands first and the Cache Only
floor merges it.

## Jobs, in order

1. **`cache_move.verify` doesn't check saved results' files** (known-issues › App, from Result
   Cache R2). `helab/utils/cache_move.py`, `verify(cache_dir, store_id)`, checks the datasets'
   files and sizes but not `results/<uuid>.npz`. Add `SELECT file, bytes FROM results` beside the
   datasets, in the same style, and also the pending results' files if they have them. Add a
   test, in the style of the existing verify tests, that fails without the change: a moved cache
   with a result file missing or the wrong size.
2. **`roots_verify` is missing from `io_helper.CACHE_ONLY`**, though
   `IOService.CACHE_OPERATIONS` lists it (known-issues › App). Sent without a cache, it would fail
   with a vague `KeyError`. Add it, and a test that the two lists agree, so the next operation
   can't drift. Check whether any other operation differs between them.
3. **A forgotten data root keeps its saved-result count in memory, hidden** (known-issues › App,
   R2). When a folder's data root is forgotten while HeLab runs, its last saved-result count
   ("Cached analysis: N results") stays in `FolderCache` RAM until a listing says otherwise.
   - Find where `root_changed` / `forget_root` drop a root's other RAM state (e.g.
     `_root_constants_gone`, the flags). Drop the result counts the same way, for the folders that
     root held, not those inside a nested root below.
   - If that needs more than a small change, stop and report what it would take.
4. **Status-message audit: load-phase labels for `merged` / `updated` sources** (`roadmaps/_readme.md`
   › Now). Notes: `.ai/sessions/2026-10-08-codex-roadmap-review/notes.md#status-messages`, which
   links the original audit and its fixes.
   - Check that each label a load shows (tab line, Folder details, status bar) matches what the
     helper actually does in those two sources: which files it reads, and when the disk cache is
     written (`disk_cached` comes after `loaded` for `updated`).
   - Report each mismatch with the wording now and the wording you propose. Don't change wording
     users see: Tony decides it. Tests that pin the right labels are welcome.
5. **The remaining CI reruns.** Covers `test_live_plots.py::test_a_following_scatter_updates_its_page_in_place`
   (the teardown "TypeError: 'NoneType' object is not callable") and
   `test_plot_settings_panel.py::test_activation_sources`.
   - Count both tests' reruns in the CI runs since 2026-10-23: `gh run list --branch dev/v0.0.6`
     and the `agent/*` branches, then `gh api repos/TonyXTYan/HeLab/actions/jobs/<id>/logs`.
   - If one reran, its rerun reasons now carry `where_qt_raised`'s note: use it to find the cause
     and fix it.
   - If neither reran, record that and stop there.

## Scope

- **Owned paths:** the files each job names and their tests.
- **Ask CoCo before:** changing anything a user sees; touching `tests/conftest.py`; touching more
  than a few files for one job.

## Checks and handoff

- **Per job:** a commit (subject + body: cause, fix, checks), and a section in this folder's
  `notes.md` with the cause, evidence, fix, checks and a proposed known-issues line.
- **Before each report:** the full suite (`pytest -n 4 --reruns 5 --reruns-delay 1
  --basetemp=.ai/temp/pytest`), `mypy helab/ --strict`, `mypy tests --strict` and
  `pyright helab tests`. Report each RERUN with its reason.
- **Report each job when it's done, then go on:** `maestri ask "CoCo" "<job N: cause, commits,
  files, checks with RERUNs, proposed known-issues line>"`.
- **When all are done:**
  - Push the branch once (to `TonyXTYan/HeLab`).
  - Read each OS's test log (`gh api …/jobs/<id>/logs`).
  - Write a short `handoff.md`, post `--state review` and report the CI run.
