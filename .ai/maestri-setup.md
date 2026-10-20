# Setting up Maestri for HeLab (human guide)

2026-10-15. How Tony (or anyone running HeLab's agents) sets up Maestri so a
coordinator can run workers on floors, following the rules in
[roadmaps/agent-workflow.md](../roadmaps/agent-workflow.md). Written from the
[Maestri docs](https://www.themaestri.app/en/docs/floors) (Floors, Maestro Mode,
Terminals & Agents, Connections, Notes) and HeLab's needs. Steps marked
**(check)** haven't been tried with this repo yet: the floor review is a later
step in the workflow plan.

## What you get

- **Ground**: your own checkout (`HeLab/`, currently `dev/v0.0.6`). You and
  the coordinator live here. Agents never commit here without asking.
- **Floors**: one per task. Each is a git worktree of HeLab on its own branch,
  in `.maestri/floors` next to the project, with its own canvas and terminals.
  On APFS, Ground's files (including `venv.nosync/` and other gitignored
  files) are copy-on-write cloned in, so creation is near-instant.
- **Coordinator**: one terminal with Maestro Mode. It proposes tasks, creates
  floors, recruits workers, reviews and integrates. It asks you before starting
  a worker, and before landing or opening a PR.

## 0. A new computer, from nothing

For a Mac with nothing installed (2026-10-19). Steps marked **(check)**
haven't been done on a second machine yet. Then continue with sections 1–4.

1. **Command-line tools and Homebrew**: `xcode-select --install` (gives
   `git`), then [Homebrew](https://brew.sh) and `brew install gh node`
   (`node` for the npm tools below).
2. **Git identity**: `git config --global user.name "…"` and
   `git config --global user.email "…"`.
3. **GitHub**: `gh auth login` with the account that can push to
   `TonyXTYan/HeLab`; `gh auth setup-git` lets `git push` use it.
4. **uv**: `curl -LsSf https://astral.sh/uv/install.sh | sh`, then open a new
   terminal.
5. **Clone** outside iCloud Drive if you can (inside it, keep the venv in
   `venv.nosync/` with a `venv` symlink, see AGENTS.md):

   ```bash
   git clone --recurse-submodules https://github.com/TonyXTYan/HeLab.git
   cd HeLab && git switch dev/v0.0.6
   ```

6. **Python and packages** (the README's "Setup (any machine)"):

   ```bash
   uv python install 3.13
   uv venv --seed --python 3.13 venv && source venv/bin/activate
   uv pip install -r requirements.lock -e .
   pytest -n 4 --reruns 5 --reruns-delay 1   # should pass; report any RERUN
   ```

7. **Agents**: Claude Code (`curl -fsSL https://claude.ai/install.sh | bash`)
   and Codex (`npm install -g @openai/codex`); run `claude` and `codex` once
   each to sign in.
8. **Claude's global instructions**: copy `~/.claude/CLAUDE.md` from the
   existing Mac (the AGENTS.md / CLAUDE.md convention and the CodeGraph rules).
   It isn't in the repo.
9. **CodeGraph**: `npm install -g @colbymchenry/codegraph`, register it for
   Claude Code with `claude mcp add --scope user codegraph -- codegraph serve --mcp`,
   then run `codegraph init -i` in the repo (`.codegraph/` is gitignored).
10. **Project memory**: Claude keeps memory per checkout path, in
    `~/.claude/projects/<encoded path>/memory`. HeLab's lives in the repo
    (`.ai/memory`), so link it. Start `claude` once in the repo and quit, then:

    ```bash
    dir=$(ls -d ~/.claude/projects/*HeLab | head -1)   # the encoded repo path
    [ -d "$dir/memory" ] && [ ! -L "$dir/memory" ] && mv "$dir/memory" "$dir/memory.local"
    ln -s "$PWD/.ai/memory" "$dir/memory"
    ```

    Without the link, Claude on this Mac starts with an empty memory.
11. **Maestri**: install the app from [themaestri.app](https://www.themaestri.app),
    open it and sign in. It provides the `maestri` CLI inside its terminals
    (`$MAESTRI_CLI`) and installs its agent skills (`maestri`,
    `maestri-chat`, `maestri-manager`, … in `~/.claude/skills/`) **(check)**.
12. **Maestri settings don't sync**: `.maestri/` (roles, floors) is gitignored
    and hooks live in the app. Redo sections 1–4 here: workspace,
    notifications, presets, the coordinator terminal and role (the role text
    is in section 2), the register note and the floor setup hook.
13. **HeLab's own state is per machine**: settings (QSettings plist) and the
    cache in `~/Library/Caches/HeLab` start empty. Data roots are found again
    from their `.helab-root` markers. A drive this Mac reaches at a new
    location asks "same folder or a copy?" once.

**Two computers at once.** Run one coordinator on each. Both branch
`agent/<task>` from `dev/v0.0.6` and land back into it. Before landing, pull
`dev/v0.0.6` first: `git pull` on Ground, or **Sync** in the land dialog. Keep
the two machines on different roadmap items, and say in the register note
which machine owns which task.

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
   > integrating. Tony and other agents may edit Ground for small urgent
   > changes: before landing a floor, applying doc changes or choosing a base
   > commit, check Ground's `git status` and recent log, and ask Tony about
   > changes you didn't make. Never stash, reset, check out over or discard
   > them. Base commits are always committed (`HEAD` or a hash). Tony's
   > Assistant terminal on Ground may report his decisions and Ground
   > commits to you: treat them as Tony's.

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
5. Two more roles (Settings → Agents → roles), for the Coordinator to recruit
   with `--role` (section 5). Don't tick Maestro for either. The brief adds
   the task itself; these hold the rules every task shares.

   **Worker**:

   > You do one HeLab task on a Maestri floor. Your shell starts in a Maestri
   > role folder (`.maestri/roles/<id>/`): run every command from the floor's
   > root (`cd "$(git rev-parse --show-toplevel)"` first, then
   > `source venv/bin/activate` and `source .ai/local/floor-env.sh`; Claude
   > Code resets the shell to the start folder after every command, so prefix
   > each one). Check that the root is the floor (under `.maestri/floors`),
   > not Ground; if it is Ground, stop and tell the Coordinator. Read
   > `AGENTS.md`, `roadmaps/agent-workflow.md` and your brief first and
   > follow them. Work on your floor's `agent/<task>` branch, from the base
   > commit in the brief; commit freely there, and push the branch once, to
   > `TonyXTYan/HeLab` only, when the work is done. Change only the brief's
   > owned paths. Write documentation only in your own
   > `.ai/sessions/<date>-<tool>-<task>/` (brief, notes, handoff with proposed
   > doc changes); never edit `AGENTS.md`, `roadmaps/`, `.ai/MANUAL_TODO.md`
   > or `.ai/memory/`. Run tests with
   > `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`
   > plus strict mypy and pyright, and report any RERUN. Don't launch the
   > HeLab GUI. Ask the Coordinator (`maestri ask`) when blocked or when the
   > brief is unclear; keep `maestri floor status` current, and when done
   > post `--state review` and send the Coordinator your handoff's summary.

   **Reviewer**:

   > You review one HeLab branch on a Maestri floor, read-only. Your shell
   > starts in a Maestri role folder (`.maestri/roles/<id>/`): run every
   > command from the floor's root (`cd "$(git rev-parse --show-toplevel)"`
   > first, then `source venv/bin/activate` and
   > `source .ai/local/floor-env.sh`; prefix each command). Read `AGENTS.md`,
   > `roadmaps/agent-workflow.md`, the brief and the worker's handoff. Review
   > the actual diff against the brief's base commit
   > (`git diff <base>...HEAD`), not the handoff's account of it: correctness,
   > the brief's acceptance criteria, the codebase rules in `AGENTS.md`,
   > tests that prove the change, and doc changes the handoff should propose.
   > Rerun the critical checks yourself (the full suite with
   > `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`,
   > strict mypy, pyright). Don't edit, commit or push. Send your findings to
   > the Coordinator (`maestri ask`), most severe first, each with file and
   > line, and say plainly when you found no blocker.

   Recruit the Reviewer with the other model from the worker's (Codex
   reviews Claude's work, Claude reviews Codex's).
6. **Assistant terminal** (optional): a second Ground terminal for Tony's
   questions, ideas and small urgent changes, so the Coordinator's context
   stays on the floors. Tick **Maestro** on it only so it can manage roles
   and talk to the Coordinator; it leaves floors and recruiting to the
   Coordinator. Connect it to the Coordinator (Ctrl L). Role
   **Assistant**:

   > You are Tony's assistant on Ground, beside the Coordinator. Your shell
   > starts in a Maestri role folder (`.maestri/roles/<id>/`): run every
   > command from the repo root (`cd "$(git rev-parse --show-toplevel)"`
   > first, then `source venv/bin/activate`; Claude Code resets the shell to
   > the start folder after every command, so prefix each one). Read
   > `AGENTS.md`, `roadmaps/agent-workflow.md` and `.ai/maestri-setup.md`
   > first and follow them. Answer Tony's questions, make small urgent
   > changes and quick features on Ground (`dev/v0.0.6`, "Work on Ground"
   > in the guide: small, outside floors' owned paths, tested and typed,
   > then handed to the Coordinator with what is left to harden), edit
   > docs and this guide, manage Maestri roles when Tony asks, and check on
   > the Coordinator and floors (`maestri ask`, `maestri check`). Ask Tony
   > before committing unless he has asked for the commit. Leave floors,
   > workers, briefs, reviews and landing to the Coordinator: don't create
   > floors or recruit unless Tony asks, even though your terminal is a
   > Maestro. Never stash, reset or discard changes you didn't make. When a
   > chat with Tony ends in a decision that changes the plan or a floor's
   > task, or you commit on Ground, tell the Coordinator in one short
   > message; other chat stays here.

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
   cd "$MAESTRI_FLOOR_PATH" && [ "$MAESTRI_FLOOR_PATH" != "$MAESTRI_ROOT_PATH" ] && uv pip install -q --python venv/bin/python -r requirements.lock -e .
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
   maestri recruit "<Codename>" --floor "<Task>" --preset "Claude Code" --role "Worker"
   ```

   A Claude worker or reviewer runs Opus 5.5 at the effort the Coordinator
   picks (low, medium, high, xhigh, max), set in the new terminal with
   `/model` and `/effort` if it didn't start that way. Fable only with
   Tony's approval (agent workflow, Models).

   then `maestri ask` it the brief (objective, acceptance, base commit, owned
   paths and paths not to touch, checks, handoff). For review, recruit the
   other model on the same floor (`--preset "Codex" --role "Reviewer"`).

   Before sending the brief, `maestri check` the new terminal: a recruit can
   hang at start, showing only its typed `claude …` command and no Claude UI,
   so a brief sent then never arrives (RAM Worker, 2026-10-20; Ctrl-C didn't
   help). Restart it in place with
   `maestri recruit "<Codename>" --preset "Claude Code" --replace "<Codename>"`
   (same node, floor and role), check again, then send the brief. It happened
   once with an explicit `--command`, which other recruits used without
   trouble, so the flag isn't known to be the cause.
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

## Work on Ground

Tony (or his Assistant terminal, section 2) may make small urgent changes on
Ground, on `dev/v0.0.6`, while floors run. The Coordinator doesn't make them:
it doesn't edit feature code. The Assistant tells the Coordinator about each
Ground commit.

- Add a **Ground** row to Active work (task, terminal, files, status) and
  clear it when the change is committed; the Coordinator warns a floor whose
  owned paths overlap.
- **Commit before landing a floor**: Merge Locally is refused while Ground has
  uncommitted changes. Sync then brings the change into the floor before the
  merge.
- A change that overlaps a floor's owned paths and isn't small goes to that
  floor's worker instead. Anything bigger becomes its own floor.

**Quick features.** Tony may ask the Assistant for a small feature he can use
at once, then have the Coordinator send a floor to harden it (edge cases,
slow drives, Windows, tests):

- Keep it small: about a day's work, a few files, outside every floor's owned
  paths. Anything bigger starts as a floor.
- Run the tests and typing before committing; commit (after asking Tony) as
  soon as he has tried it and is happy, so it doesn't block landing.
- After the commit, send the Coordinator one message: the commit, what the
  feature does and what it doesn't cover yet. The Coordinator decides on a
  hardening floor based on that commit.
- Add a roadmap line marked "quick version on Ground, hardening pending", and
  keep that list short: harden before adding more.

## 6. Landing

You land floors (or approve the Coordinator doing it from Ground).

- Click the airplane button beside the floor, or **Land Floor** in its menu.
- **Merge Locally**: pick the target branch (e.g. `dev/v0.0.6`). **Sync**
  first pulls the target's latest changes into the floor. A merge is refused
  when the target's checkout has uncommitted work, or lists the conflicting
  files and stops.
- **Pull Request**: pick **Into**; title and description come from the commit
  and PR template. Maestri then tracks reviews and CI, offers *Ask an Agent to
  Fix the Checks* and the like, and lands the floor after **Merge…**.
- The floor is removed after landing unless **Keep this floor after landing**
  is ticked. The branch stays in the repo.
- CLI equivalent, from a Ground terminal only:
  `maestri floor land "<Task>" --into dev/v0.0.6`.

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
