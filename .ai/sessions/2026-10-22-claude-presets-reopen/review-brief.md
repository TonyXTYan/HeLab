# Review brief: Presets Reopen (Codex Reviewer, Flint)

Review `agent/presets-reopen` at **`a74fd07`** against base **`c3d4b50`** (`git diff c3d4b50...a74fd07`).
Read `AGENTS.md`, `roadmaps/agent-workflow.md`, the worker's `brief.md` (objective 1a, 1b, 2; the
"Follow-up 1" section is work still to come, not to review) and `handoff.md` in this folder.

**Where to work:** the worker (Loom) keeps editing the floor's own checkout, so review and test in
the detached worktree CoCo made at that commit: `.ai/temp/review-presets/` under the floor root
(its `venv` is a link to the floor's; `pytest.ini`'s `pythonpath = .` makes pytest import that
worktree's `helab`). From there: `source venv/bin/activate && source ../../local/floor-env.sh`, then
`pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`, `mypy helab/ --strict`,
`mypy tests --strict`, `pyright helab tests`. Check first that `python -c "import helab; print(helab.__file__)"`
run from the worktree under pytest names the worktree (a test in `tests/test_test_isolation.py` does).
Don't edit, commit or push anything; don't launch the GUI.

**Look hardest at:**
- Reopened plots never cause source-folder I/O: RAM, one local `cached` read, else waiting for a
  tab's load (`helab/views/plots/arrangement.py`, `FolderWait`); nothing during rendering reads
  disk; the startup tab's own selection and loads unchanged.
- Validation (`helab/analysis/presets.py`): every incompatibility named, nothing clamped or silently
  replaced; corrupt or partial records recoverable; format version handling.
- Applying an arrangement: the folder loads through the normal path (cache first, large-folder
  question), Live only under `start_live`'s rules; tab grouping/floating restore; no leaked docks
  or `QWebEngineView`s (`tests/test_left_widgets.py`).
- Settings rules: every key/prefix in `settings_defaults.py`, reads through `read_setting`, tests on
  their own ini; nothing touches native settings.
- Lifetimes: plots closed or tabs closed while waiting; quit while a cached read is in flight;
  signals disconnected (`_end_wait`); the record written at quit before plots close.
- The shared `instance.py` edits: `run()`'s hook, `_title`, `_show_follow` (the Result Cache floor
  owns the run path; CoCo already knows `run_reopened` calls `_submit(view)` without `one_off=True`
  once both merge, so no need to report that).
- Tests that prove it, and doc changes the handoff should propose but doesn't.

**Report** to CoCo with `maestri ask "CoCo" "<findings>"`: most severe first, each with file:line,
what goes wrong and how you know; then the checks you ran with results (every RERUN with its
reason). Say plainly if you found no blocker.
