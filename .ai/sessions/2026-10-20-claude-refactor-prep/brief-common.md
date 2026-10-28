# Common brief for the refactor track workers (2026-10-20)

Read first: `AGENTS.md` (repo rules), and
`.ai/sessions/2026-10-20-claude-refactor-prep/readiness.md` (the plan, the survey
and Tony's decisions). You are one of three workers running at the same time on
a 4-core Linux cloud container, each in its own git worktree under
`/home/user/wt/<track>`, all branched from `agent/refactor-prep` (`9cf8782`).
Tony is asleep: decide within these rules and record judgement calls in your
notes. Don't ask questions. If something can't be done safely, stop that piece
and explain.

## Rules

- **Behaviour-preserving only.** No change to user-visible behaviour, wording,
  timing, settings keys, cache format or helper protocol. Move ownership and
  code. Don't redesign. A move and a feature change never share a commit.
- **Work only in your worktree** (`/home/user/wt/<track>`) and on your branch.
  Never touch `/home/user/HeLab` (the coordinator's checkout) or another
  worktree. Never `pip install`/`uv pip install` (the venv is shared; `venv`
  in your worktree is a symlink).
- **Run Python from your worktree root, always as `python -m pytest`,
  `python -m mypy`** etc. after `source venv/bin/activate`. Bare `pytest` would
  import the coordinator's checkout through the editable install. Check once
  with `python -c "import helab; print(helab.__file__)"`.
- **No re-export shims.** When code moves, update every import in `helab/` and
  `tests/` to the new home. A test that patches a name (`monkeypatch.setattr`,
  `patch("module.name")`, `patch.object(module, ...)`) must patch the module
  where the code *looks the name up* at call time. A re-export or a
  `from x import name` copy makes the patch silently do nothing. After each
  move, grep `tests/` for the old module path and old names to be sure.
- **Keep names** (including leading underscores) unless a rename is needed.
  Package-internal underscore names imported across your new modules are fine.
- **Strict typing.** `python -m mypy helab --strict`, `python -m mypy tests
  --strict`, `pyright helab tests` must stay clean (the suite's
  `tests/test_typing.py` runs them too).
- **Tests.** While working, run the targeted files (`-n 2 --reruns 2
  --reruns-delay 1` at most). At the end of each slice run the full suite once
  with `python -m pytest -n 2 --reruns 5 --reruns-delay 1 -q -rR
  --basetemp=/tmp/claude-0/wt-<track>-pytest -p no:cacheprovider`. Report every
  RERUN, and treat a test that passed only on rerun as suspect if it touches
  what you moved. Other workers run suites at the same time, so a timing test
  can flake. Rerun such a failure alone before you believe it.
- **Commits.** One or more commits per slice on your branch, each with a
  concise subject and a body saying what moved, why, and the validation (see
  `git log` for the style). End every commit message with:

  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_013tyqPSqfVHdtfERx3e42hz
  ```

  Never put a model name anywhere else in the repo. **Don't push** and don't
  merge; the coordinator reviews and pushes.
- **Docs.** Update path and name references for code you moved in `AGENTS.md`
  and `roadmaps/refactoring.md` (and any other doc that names the moved file,
  e.g. `.ai/memory/results/*.md` or `roadmaps/*.md`: grep). Make no other
  roadmap or priority edits. Write your notes to
  `.ai/sessions/2026-10-20-claude-refactor-prep/<track>-notes.md`: what moved
  where, decisions, test results with reruns, anything left or suspicious.
- **Stop after the slice you were asked for** and report: the commits, test
  results (with RERUN lines), and open points. You'll be resumed for the next
  slice after review.
