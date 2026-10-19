# Parallel agent workflow and run isolation

Added: 2026-10-15. Workflow rules decided by Tony 2026-10-15; the isolation
code (settings profiles) is a draft plan, nothing implemented.
Priority and completion: [overview](_readme.md). The code decoupling that makes
parallel features possible is in [refactoring](refactoring.md).

## Purpose

Let several AI agents work on separate HeLab features at once, on Maestri
floors (and later possibly cloud agents), without disturbing Tony's checkout,
his settings and cache, the packaged release, or each other.

## Roles and rules (decided 2026-10-15)

- **Coordinator**: one long-lived agent with Maestro Mode on its terminal. It
  reviews the roadmap and active work, proposes tasks and writes briefs, creates
  floors and recruits workers on them, reviews and integrates. It doesn't edit
  feature code. It asks Tony before starting a worker.
- **Assistant** (added 2026-10-19): a second Ground terminal for Tony's
  questions, small urgent Ground changes and quick features (hardened later
  on a floor), so the Coordinator's context stays on the floors. It doesn't
  create floors or recruit, and it tells the Coordinator about decisions that
  change the plan and about Ground commits.
- **Workers**: one task each. A worker starts a **new branch from the commit
  Tony or the coordinator chose** (`agent/<task>`), in its own worktree (a
  Maestri floor), clone or cloud environment, may **commit there freely**, and
  **pushes once, when its work is done** (each push runs the full CI matrix),
  to `TonyXTYan/HeLab` only, never `HeBECANU`.
- **Tony's checkout and branches**: committing there, merging into his branches
  or `main`, landing a floor and opening a PR need Tony's approval.
- **Documentation**: a worker writes only its own session folder
  (`.ai/sessions/<date>-<tool>-<task>/`: brief, notes, handoff with proposed doc
  changes). It doesn't edit AGENTS.md, `roadmaps/`, `.ai/MANUAL_TODO.md` or
  `.ai/memory/`; the coordinator updates those when merging.
- **Review**: by a different model from the author where possible; the
  reviewer reads the actual diff and reruns critical checks. Branches are
  integrated one at a time, with the full suite after each.
- **Models** (decided 2026-10-19): Claude agents (coordinator, assistant,
  workers, reviewers) run **Opus 5.5** by default, at the effort the
  coordinator judges the task needs. **Fable** (any Fable model) runs only
  with Tony's approval: no Fable recruit or Fable subagent without asking
  him first (a forked subagent inherits its parent's model). A Codex
  reviewer for Claude's work is unaffected.
- **Brief**: objective and acceptance criteria, base commit, owned paths and
  paths not to touch, contracts used or changed, checks to run, handoff.
- **Register**: the coordinator keeps live state (task, agent, floor, branch,
  owned paths, status, blocked on) outside Git, proposed as a Maestri note;
  each floor's `maestri floor status` line shows its state.

## Maestri floors (primary)

Step-by-step setup for a person (coordinator terminal, register note, setup
hook, landing): [.ai/maestri-setup.md](../.ai/maestri-setup.md).

1. Tony (or the coordinator, with his approval) picks the base commit.
2. The coordinator creates the floor on a new branch:
   `maestri floor create "<Task>" --branch agent/<task>`, from a ground
   checkout of the chosen commit, then recruits a worker on it with the brief.
3. Floor setup (a script to write, run once per floor):
   - **Python**: the floor's copy-on-write venv has the right packages but is
     wired to the ground checkout by absolute paths: its `bin/` scripts start
     with ground's `venv.nosync/bin/python3.13`, `activate` sets ground's
     `VIRTUAL_ENV`, and its editable install points at ground's `helab/`. It is
     usable with two guards: pytest must import the floor's code (proposed:
     `pythonpath = .` in a pytest config, so `pytest` and `python -m pytest`
     both test the checkout they run in; helpers already follow the GUI's
     checkout via `PYTHONPATH`), and the app runs as `python -m helab`, not
     the `helab` entry point. A branch that changes `requirements.txt` gets a
     fresh venv instead (`uv venv --seed --python 3.13 venv && uv pip install
     -r requirements.txt -e .`, 16 s measured 2026-10-15 with uv's cache), so
     it never installs into ground's venv.
   - **Profile**: a private settings/app/cache folder for the floor (below).
   - **Stale bytecode**: delete the copied `__pycache__` folders, which carry Ground's
     paths into tracebacks (Live L3 notes, 2026-10-19).
   - **Tests**: own `--basetemp`, and about `-n 4` per worker when several run.
   - CodeGraph: initialise `.codegraph/` in the floor if the worker uses it.
4. The worker commits as it goes; when done it writes its handoff, pushes its
   branch once and posts `--state review`.
5. The coordinator reviews, applies the handoff's doc changes, and asks Tony
   before landing or opening a PR.

Each push starts the full CI matrix (macOS, Windows, Ubuntu), hence the single
final push. A further push after review fixes is fine.

**Later step:** review how Maestri floors fit this repo before the pilot:
what the copy-on-write clone includes (venv, `.ai/local/`, `.codegraph/`,
gitignored build output), setup hooks for the floor setup script, landing
into a branch other than ground's, and cleaning up floors and branches.

## Cloud agents (kept open)

The same rules apply: a new branch from the chosen commit, commit and push at
will, handoff in its session folder. Suited to tasks that need neither macOS
nor the lab volume: fixtures, typing, CI, docs, large reviews. They run on
Linux, can't see the Maestri canvas, and can't do native or real-volume checks,
so a floor reviewer or Tony does those. Keep the brief, register and handoff
format tool-neutral so a cloud worker can be added without changing them.

## Settings and data isolation (plan)

Today a source checkout, every worktree and the packaged app share one native
settings store (`com.anu-he-bec-group.HeLab.plist`) and one app/cache folder
(`~/Library/Caches/HeLab`). A branch that changes a setting's meaning or the
cache layout can disturb Tony's real settings and cache. Tests already avoid
both (`tests/conftest.py` sets `HELAB_DIR_*_OVERRIDE` and
`HELAB_APP_DIR_OVERRIDE`; tests pass tmp `QSettings` files), but nothing
enforces it.

**Hard-coded defaults.** Every setting has one default in code (a single
table, for example `helab/utils/settings_defaults.py`, with the key, type,
default and a short description). It is the starting point for every new
profile, and it serves the release too: **Restore default** actions and
tooltips showing the default value all read it.

**Profiles.** One resolved at startup, before any settings, cache or Dash
import (including the frozen helper entry), gives the settings file and the
app folder (caches, temps, locks, `cache-move.json`):

| Run | Settings | App folder |
|---|---|---|
| Packaged release | Native store, as now | Default (`~/Library/Caches/HeLab`) |
| Checkout set to **share** | The release's settings and cache, as today | Default |
| Checkout set to **isolated** (agent worktree, floor, cloud) | Own ini file, started from the hard-coded defaults | Own folder |
| pytest | Tmp ini per worker from the defaults, always isolated | Tmp per worker (as now) |

- **Each checkout saves its own choice** (share or isolated) in a gitignored
  file in that checkout, so the choice is never merged between branches.
  Tony's own checkouts will mostly share; the floor setup script writes
  *isolated* for every agent worktree. With no file, a git worktree or clone
  made by an agent is isolated; the default for a main checkout is to decide
  (share keeps today's behaviour). pytest ignores the choice.
- An isolated profile starts from the hard-coded defaults and changes only its
  own copy; it never reads or writes the release's settings or cache. The
  packaged app never sees isolated profiles.
- `HELAB_SETTINGS_OVERRIDE=<file.ini>` selects a settings file; a profile
  variable (name to decide, e.g. `HELAB_PROFILE_DIR`) can set settings, caches,
  temps and app folder from one root, and the existing `HELAB_DIR_*` and
  `HELAB_APP_DIR_OVERRIDE` variables keep working.
- **One settings factory.** Replace the direct `QSettings(QSETTINGS_ORG_NAME,
  QSETTINGS_APP_NAME)` calls (`main.py`, `constants.py`, `HelabMainWindow.py`,
  `SettingsDialog.py`) with one function returning the profile's settings;
  helpers already open settings from `settings_spec`. A test fails if anything
  else constructs the native store.
- The packaged release behaves as now, plus Restore default and default-value
  tooltips from the defaults table.

Open decisions:

- Default for a main checkout with no saved choice (share, as today, or ask
  once at first launch).
- Name and format of the per-checkout file (for example a gitignored
  `.helab-profile`, or `.ai/local/profile.json`), and how the About box and
  status bar show which profile is running.
- Where isolated profile folders live (beside the default app folder, e.g.
  `~/Library/Caches/HeLab/profiles/<name>`, or inside the checkout under a
  gitignored folder) and when old ones are removed (only when asked).
- Whether an isolated profile may copy real cached data in for real-volume
  tests (a copy, never the release's live cache).
