# Setting up Maestri for HeLab (human guide)

2026-10-15. How Tony (or anyone running HeLab's agents) sets up Maestri so a
coordinator can run workers on floors, following the rules in
[roadmaps/agent-workflow.md](../roadmaps/agent-workflow.md). Written from the
[Maestri docs](https://www.themaestri.app/en/docs/floors) (Floors, Maestro Mode,
Terminals & Agents, Connections, Notes) and HeLab's needs. Steps marked
**(check)** haven't been tried with this repo yet: the floor review is a later
step in the workflow plan.

## What you get

- **Ground**: your own checkout (`HeLab/`, currently `dev/v0.0.5a`). You and
  the coordinator live here. Agents never commit here without asking.
- **Floors**: one per task. Each is a git worktree of HeLab on its own branch,
  in `.maestri/floors` next to the project, with its own canvas and terminals.
  On APFS, Ground's files (including `venv.nosync/` and other gitignored
  files) are copy-on-write cloned in, so creation is near-instant.
- **Coordinator**: one terminal with Maestro Mode. It proposes tasks, creates
  floors, recruits workers, reviews and integrates. It asks you before starting
  a worker, and before landing or opening a PR.

## 1. One-time setup

1. **Install the agents** Maestri will run: Claude Code and Codex, signed in
   (`claude`, `codex`). Maestri expects them installed already.
2. **GitHub CLI**: `gh auth status` should show the account that can push to
   `TonyXTYan/HeLab`. Floors use `gh` for pull requests; without it Maestri
   opens the PR page in the browser.
3. **Workspace**: one Maestri workspace rooted at the HeLab checkout (sidebar
   → new workspace, or `maestri workspace create "HeLab" --dir <path>` from a
   Maestro terminal).
4. **Notifications**: Settings → General → *Notify when a floor needs you*
   (blocked, ready for review, PR conflicts) and Settings → Notifications →
   *Notify when an agent needs attention*.
5. **Presets** (optional): Settings → Terminal → Quick Start, one preset each
   for Claude Code and Codex, so the coordinator can recruit either. Extra
   accounts: Settings → Agents → Accounts.
6. **Gitignore**: `.maestri/` (role folders, `.maestri/roles/<id>/`) is in
   `.gitignore`.

## 2. Coordinator terminal

1. Draw a terminal on Ground (Terminal tool), choose Claude Code or Codex, and
   give it any name (Tony's is **Maestro**); the role is what makes it the
   Coordinator.
2. Right-click → **Edit Terminal** → **Details** → tick **Maestro** → Save.
   Only a Maestro (or you) can create floors and recruit agents.
3. Optional role (Settings → Agents → roles), name **Coordinator**, with
   instructions such as:

   > You coordinate parallel HeLab work. Your shell starts in a Maestri role
   > folder (`.maestri/roles/<id>/`): run every command from the repo root
   > (`cd "$(git rev-parse --show-toplevel)"` first, then
   > `source venv/bin/activate`; Claude Code resets the shell to the start
   > folder after every command, so prefix each one). Read `AGENTS.md`,
   > `roadmaps/agent-workflow.md` and `.ai/maestri-setup.md` first and follow
   > them. Don't edit feature
   > code. Propose tasks with a brief; ask Tony before creating a floor or
   > recruiting, and before landing a floor or opening a PR. Keep the
   > "Active work" note current. Apply workers' proposed doc changes when
   > integrating.

   A role starts the agent in `.maestri/roles/<id>/`, where Maestri writes
   the role's own `AGENTS.md`, `CLAUDE.md` and `role.json` (gitignored via
   `.maestri/`). Don't symlink or edit them: Maestri regenerates them from the
   role. The repo's instructions still load, because Claude Code reads every
   `CLAUDE.md` from the start folder up and Codex reads every `AGENTS.md` from
   the git root down. What breaks is anything relative to the start folder:
   `source venv/bin/activate`, `pytest` (collects nothing), `mypy helab/`.
   Hence the "repo root first" line. Claude Code may also ask permission to
   edit files above its start folder; the alternative is a terminal without a
   role, started in the repo root, with this text as its first prompt.
4. In the first prompt, mention **@Maestro** so the agent loads the
   `maestri-manager` skill.

## 3. Register note

1. Draw a Note on Ground (Note tool), rename it **Active work**.
2. Connect it to the Coordinator: select the terminal, press **Ctrl L** (or the
   Connection tool), click the note.
3. Starting content:

   | Task | Floor / branch | Base commit | Agent | Owned paths | Status | Blocked on |
   |---|---|---|---|---|---|---|

Note ropes stay on one floor, so workers on floors don't see this note; they
report to the Coordinator (`maestri ask`) and post their floor status instead.
Keep the note in Maestri's own storage: if you *Move to…* a file inside the
repo, floors would copy a stale version of it.

## 4. Floor setup hook

Right-click the floor button (bottom right, next to the minimap) →
**Configure Hooks…** → **Setup**, tick **Auto-run**, and add each command
below as its own entry, in this order, so each can be switched on or off.
Maestri provides `$MAESTRI_FLOOR_PATH`, `$MAESTRI_ROOT_PATH`,
`$MAESTRI_BRANCH_NAME`, `$MAESTRI_FLOOR_NAME` and `$MAESTRI_PROJECT_NAME`.
Every command starts from the floor's folder itself and the venv ones refuse
to run on Ground, so none relies on an earlier one's working directory.

**Python.** The cloned venv has the right packages but is wired to Ground by
absolute paths (script shebangs, `activate`, and the editable install of
`helab`), so a bare `pytest` on a floor can import **Ground's** code. Until the
pytest `pythonpath` guard lands, give each floor a fresh venv (about 16 s with
uv's cache). Keep 1 and 2 both on or both off.

1. Fresh venv:

   ```bash
   cd "$MAESTRI_FLOOR_PATH" && [ "$MAESTRI_FLOOR_PATH" != "$MAESTRI_ROOT_PATH" ] && uv venv --clear --seed --python 3.13 venv
   ```

2. Packages and the floor's own editable `helab`:

   ```bash
   cd "$MAESTRI_FLOOR_PATH" && [ "$MAESTRI_FLOOR_PATH" != "$MAESTRI_ROOT_PATH" ] && uv pip install -q --python venv/bin/python -r requirements.txt -e .
   ```

**Private app folders**, for tests and any manual run (QSettings is **not** yet
isolated, see below). Command 3 starts `.ai/local/floor-env.sh` afresh; 4 and
5 add a line each.

3. App folder (locks, `cache-move.json`):

   ```bash
   mkdir -p "$MAESTRI_FLOOR_PATH/.ai/local" && echo "export HELAB_APP_DIR_OVERRIDE=\"$HOME/Library/Caches/HeLab/floors/$MAESTRI_FLOOR_NAME/app\"" > "$MAESTRI_FLOOR_PATH/.ai/local/floor-env.sh"
   ```

4. Cache folder:

   ```bash
   echo "export HELAB_DIR_CACHES_OVERRIDE=\"$HOME/Library/Caches/HeLab/floors/$MAESTRI_FLOOR_NAME/caches\"" >> "$MAESTRI_FLOOR_PATH/.ai/local/floor-env.sh"
   ```

5. Temp folder:

   ```bash
   echo "export HELAB_DIR_TEMPS_OVERRIDE=\"$HOME/Library/Caches/HeLab/floors/$MAESTRI_FLOOR_NAME/temps\"" >> "$MAESTRI_FLOOR_PATH/.ai/local/floor-env.sh"
   ```

**Optional**, added but switched off; switch it on when a task needs the
legacy MATLAB converter (submodule folders start empty on a floor):

6. Submodules:

   ```bash
   cd "$MAESTRI_FLOOR_PATH" && git submodule update --init --recursive
   ```

**Teardown** (runs on Delete Floor): remove that floor's private folders. The
name check stops an empty `$MAESTRI_FLOOR_NAME` from removing every floor's
folders.

1. Floor folders:

   ```bash
   [ -n "$MAESTRI_FLOOR_NAME" ] && rm -rf "$HOME/Library/Caches/HeLab/floors/$MAESTRI_FLOOR_NAME"
   ```

**(check)** That Maestri runs setup commands in order and stops or carries on
after a failing one; that `.ai/local/floor-env.sh` reads correctly for a floor
name with spaces.

When creating a floor in the UI you can add **Excluded folders**; `build`
and `dist` are excluded by default. Worth adding: `htmlcov`, `.ai/temp`,
`.pytest_cache`. Check that `.codegraph/` works on a floor or re-run
`codegraph init -i` there **(check)**.

## 5. Running a task

1. **Choose the base commit** (you or the Coordinator). To start from a commit
   other than Ground's current one, make the branch first, then use it:

   ```bash
   git branch agent/<task> <commit>
   maestri floor create "<Task>" --branch agent/<task> --existing-branch
   ```

   Otherwise `maestri floor create "<Task>" --branch agent/<task>`, or type
   `@New Floor` in the Coordinator's composer with the task.
2. **Recruit the worker** on that floor (the Coordinator asks you first):

   ```bash
   maestri recruit "<Codename>" --floor "<Task>" --preset "Claude Code"
   ```

   then `maestri ask` it the brief (objective, acceptance, base commit, owned
   paths and paths not to touch, checks, handoff). For review, recruit the
   other model (`--preset "Codex"`) on the same floor.
3. **The worker**:
   - works from the floor's root: a worker recruited with `--role` starts in
     `.maestri/roles/<id>/`, so it runs `cd "$(git rev-parse --show-toplevel)"`
     first and confirms that path is the floor, not Ground;
   - runs `source .ai/local/floor-env.sh` before tests or a manual run;
   - runs tests with its own `--basetemp=.ai/temp/pytest` and about `-n 4`
     when several workers are busy;
   - commits freely on its branch; writes only its own
     `.ai/sessions/<date>-<tool>-<task>/` (brief, notes, handoff with proposed
     doc changes);
   - when done, pushes the branch **once**, runs
     `maestri floor status "<summary>" --state review`, and reports to the
     Coordinator.
4. **Don't launch the HeLab GUI from a floor yet**: QSettings is still shared
   with your real app (settings profiles are planned in the workflow plan).
   Tests are safe; they use temporary settings and folders.

## 6. Landing

You land floors (or approve the Coordinator doing it from Ground).

- Click the airplane button beside the floor, or **Land Floor** in its menu.
- **Merge Locally**: pick the target branch (e.g. `dev/v0.0.5a`). **Sync**
  first pulls the target's latest changes into the floor. A merge is refused
  when the target's checkout has uncommitted work, or lists the conflicting
  files and stops.
- **Pull Request**: pick **Into**; title and description come from the commit
  and PR template. Maestri then tracks reviews and CI, offers *Ask an Agent to
  Fix the Checks* and the like, and lands the floor after **Merge…**.
- The floor is removed after landing unless **Keep this floor after landing**
  is ticked. The branch stays in the repo.
- CLI equivalent, from a Ground terminal only:
  `maestri floor land "<Task>" --into dev/v0.0.5a`.

After landing, the Coordinator applies the worker's proposed doc changes
(AGENTS.md, `roadmaps/`, MANUAL_TODO, memory) on Ground and asks you before
committing them.

## 7. Clean-up

**Delete Floor** removes the floor folder including uncommitted changes;
commits stay unless **Also remove the branch** is ticked. Unload idle floors to
free memory. Remove the branch on GitHub too once it's merged.

## Not yet in place

- Settings profiles (`HELAB_SETTINGS_OVERRIDE`, share/isolated per checkout,
  hard-coded defaults): until then, no GUI runs from floors.
- The pytest `pythonpath` guard: until then, fresh venv per floor (above).
- The floor review items marked **(check)**.
