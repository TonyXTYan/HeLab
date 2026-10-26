# Codebase review 2 and fixes (brief for the Reviewer and the Fixer)

Floor "Codebase Review 2", branch `agent/codebase-review-2`, from `3eb0fbf` (`dev/v0.0.6`,
2026-10-26). Session folder: `.ai/sessions/2026-10-26-claude-codebase-review-2/`:
- this brief is `brief.md`;
- the Reviewer keeps `findings.md` and the Fixer `notes.md`;
- one shared `handoff.md` comes at the end.

Asked by Tony (Chat, 2026-10-26: "fix bugs and do an overview codebase review in a separate floor",
then "proceed").

Two agents on this floor, connected to each other and to the Coordinator (CoCo):
- **Sextant** (Reviewer, Claude Fable): reads code and finds issues. Never edits, commits or
  pushes.
- **Rasp** (Worker, Claude Opus): fixes what Sextant sends, with tests, and commits on the
  branch. While waiting for findings, fixes the known bugs below.

Both read:
- `AGENTS.md`: the codebase rules. Most findings are breaches of them.
- `roadmaps/agent-workflow.md`.
- `roadmaps/known-issues.md`: already known, so don't re-report, but say if you find the cause.
- The last review, `.ai/sessions/2026-10-22-claude-codebase-review/` (`findings.md`, `handoff.md`,
  up to `fc0f50d`). Don't repeat what it found or fixed.

## Part 1: what landed since the last review (`git log fc0f50d..3eb0fbf`, ~160 commits)

Sextant goes through these, most at risk first:

1. **The store-identity rule and the presets / saved-results code** in `helab/utils/folder_cache.py`
   (`store_answer`, `_store_changed`, `_store_not_confirmed`, `HeldWrite`, presets section,
   result counts), `helab/utils/cache_store.py` (presets, results, `pending_results`, `_migrate`),
   `helab/io_ops/admin.py`, `helab/io_ops/results.py`. Its docstring is the rule. Look for the
   rule and the code drifting apart, and for cases the 1560-cell enumeration in
   `tests/test_store_identity.py` can't see.
2. **Saved analysis results in the plot path**: `helab/views/plots/cached_results.py`,
   `instance.py` (`_submit`, `run_reopened`, one-off runs), `helab/analysis/result_cache.py`,
   `result_codec.py`, `result_types.py`, and Make room / Discard in `CacheDialogs`.
3. **Presets and plot reopen**: `helab/views/plots/presets.py`, `arrangement.py` (`PlotReopen`,
   `FolderWait`, `PresetFolder`), `helab/analysis/presets.py`, `helab/views/PresetsInspector.py`.
4. **The quick fixes**: `io_service._run`'s closed-pipe handling, `cache_move.verify`, the
   loading labels (`load_origin`, `file_started` only for files read), the mismatch fence
   (`b66bba6`), and `tests/conftest.py` changes (`no_quitting_cache`, `where_qt_raised`).

## Part 2: an overview pass over the whole codebase

After Part 1. Don't go line by line: look for what a newcomer would trip on.
- Duplication that has drifted (two copies of a rule behaving differently).
- Dead code: modules, functions, settings or event kinds nothing uses.
- `helab/utils/folder_cache.py`'s size and structure: say whether and how it should split, as a
  proposal for Tony, not a change.
- AGENTS.md rules broken anywhere: source I/O or disk reads on the GUI thread or during rendering;
  names tests patch imported by value; events outside `events.py`'s contract; removals without
  the user asking; tests touching real data.
- Types weaker than they could be (`Any`, casts, `# type: ignore`), and comments that no longer
  match the code.
- AGENTS.md itself: statements the code no longer bears out, as proposed doc edits.

## Rasp's first jobs, before findings arrive

1. **Windows rerun of the store test**: `tests/test_result_cache_quit.py::test_an_old_stores_answer_never_says_saved_in_the_recreated_one`.
   It reran once on Windows CI (run 40270085653, job 121400850933) with WinError 32 deleting
   `store-v3\records.sqlite`. This was after it waited for every helper's confirmed exit
   (`cache_busy()`, `8195fc7`).
   - Find what still holds the file: the test process's own connections? A helper not counted by
     `cache_busy()`, e.g. the identity probe or a presets read started after the wait?
   - Fix it. A bounded retry of the delete on Windows is acceptable only if you can say why the
     handle outlives the process.
   - Check the other tests that delete a store the same way.
2. **Then the open known-issues items** that turn out small. Say which you take, and ask CoCo
   before anything that changes what users see.

## Working together

- **Sextant's findings:**
  - Each finding goes in `findings.md` with an ID (`C-1`, `C-2`, …), a severity (blocker / high /
    medium / low / quality), file:line, what goes wrong and when (a concrete scenario), and the
    suggested fix.
  - Then send Rasp the batch's IDs (`maestri ask "Rasp" …`, short; the detail is in the file).
  - Reread the code before reporting. Report only what you'd defend, and mark "unsure" what you
    couldn't confirm.
- **Rasp's fixes:**
  - Work in severity order. Each correctness fix gets a test that fails before and passes after.
    Make one commit per finding or tight group, with the IDs in the subject.
  - Record each finding in `notes.md` as fixed (commit), declined (why) or needs Tony. Rasp may
    ask Sextant to clarify, and may disagree with reasons.
  - Sextant reviews Rasp's commits for each batch (`git show`) before the batch counts as done.
- **Needs Tony** (don't change; list it in the handoff): anything that changes behaviour users
  see, wording, settings or defaults, the cache/store format, or a decision recorded in AGENTS.md
  or `.ai/memory/results/`. Bug fixes that restore the documented behaviour don't need asking.
- **Telling CoCo:**
  - A blocker or high finding: Sextant tells CoCo at once (`maestri ask "CoCo" …`, one line).
  - After each part, Sextant sends CoCo one line: the part, counts by severity, fixed so far.
- Rasp keeps `maestri floor status` current.

## Owned paths (Rasp)

`helab/` and `tests/`, except the Cache Only floor's files below.

**The "Cache Only" floor (Harbor, `agent/cache-only`) is building offline mode and owns these
files; don't edit them:**
- `helab/utils/folder_cache.py`, `io_service.py`, `cache_store.py`, `cache_paths.py`,
  `data_roots.py`, `settings_defaults.py`;
- `helab/io_helper.py`, `helab/io_ops/browse.py`, `stores.py`, the new `listings.py`;
- `helab/models/SnapshotFileSystemModel.py`, `helab/views/FolderExplorer*` and the explorer
  modules;
- `HelabMainWindow.py`, `CacheTab.py`, `DataRootsTab.py`, `RootDuplicatesWindow.py`,
  `MissingShotsWindow.py`, `DataRootDialogs.py`.

Findings there:
- Keep the fix in `notes.md` as "held for Cache Only" (the change and its test written out).
  Rasp applies it after Cache Only lands and this branch merges `dev/v0.0.6`; CoCo says when.
- If a finding there is a blocker or high, tell CoCo at once.

Sextant reviews those files too (Part 1 is mostly there); only the editing waits.

Never edit `roadmaps/`, `AGENTS.md`, `.ai/MANUAL_TODO.md`, `.ai/memory/`, `requirements*` or
`legacy/`. Proposed doc changes go in the handoff.

## Checks (Rasp; Sextant reruns the critical ones before signing off)

From the floor root, after `source venv/bin/activate && source .ai/local/floor-env.sh`, run:
- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`. Sextant uses
  `.ai/temp/pytest-review`. Report every RERUN with its reason.
- `mypy helab/ --strict`, `mypy tests --strict` and `pyright helab tests`.

Don't launch the HeLab GUI.

## Handoff

When both parts are done, or CoCo says stop, write `handoff.md` with:
- the counts;
- each finding's outcome: fixed + commit, declined + why, needs Tony + the question, or held for
  Cache Only;
- the open risks and Part 2's structural proposals;
- proposed edits to `AGENTS.md`, `roadmaps/known-issues.md` and others.

Then:
- Rasp pushes `agent/codebase-review-2` once to `TonyXTYan/HeLab`, reads each OS's CI test log
  (`gh api repos/TonyXTYan/HeLab/actions/jobs/<id>/logs`) and reports every RERUN.
- Rasp posts `--state review` and sends CoCo the summary.
- Sextant confirms to CoCo that it reviewed every fix.
